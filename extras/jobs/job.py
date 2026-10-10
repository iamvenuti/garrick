#!/usr/bin/env python3
"""Wrap one scheduled run. An optional extra.

    python3 job.py <name> [--agent] [--cwd FOLDER] [--timeout SECONDS] -- <command> [args...]
    python3 job.py status [<name>...]      every job's state, as JSON
    python3 job.py notify <title> <message>  send a line through the notifier

The name is letters, digits, hyphens and underscores, and not `agent`. The
scheduler (launchd, cron) runs this, and this runs the job. One place for
everything a run needs when nobody is watching it:

1. **A log**, `<name>.log` in the jobs folder (~/Library/Logs/garrick-jobs/
   on a Mac, or GARRICK_JOBS_DIR), rotated at 1 MB with one older generation
   kept.
2. **A heartbeat**, `<name>.heartbeat.json`: when the last run finished, its
   exit code, how long it took, how much it did. A scheduler lists a job as
   loaded whether or not it has ever worked; the heartbeat says whether it ran.
3. **A lock.** One run per job at a time. A fire that finds the previous run
   still going is skipped with exit 75 and a line in the log. A lock stands
   for as long as its run can rightly take: the wait for the shared lock
   below, the sign-in retry and the run itself, with ten minutes of slack.
   After that it belongs to a run that died without cleaning up, and the
   next fire takes it over.
4. **A watchdog.** A run still going after `--timeout` seconds (1500) is
   stopped, with every process it started, and exits 124.
5. **With `--agent`**, one assistant job at a time across all jobs: headless
   sessions started in the same minute, as happens when a laptop wakes with
   several jobs overdue, can fail each other's sign-in. A run that waits its
   whole time limit for another assistant job is skipped with exit 75. Then
   a sign-in check (agent.py login), once more after five minutes if it
   fails, and exit 4 with the run skipped if it fails again.
6. **An idle alarm.** A job that reports how much it did (agent.report_items,
   or `agent.py items`) and has done nothing for GARRICK_IDLE_DAYS days (7)
   gets a line in its log, `idle` in its heartbeat and a notice, repeated
   every GARRICK_IDLE_DAYS days while it stays idle. A job that exits 0
   having found nothing looks healthy on every other check. 0 turns it off.
7. **Notices, throttled.** A failure raises one on the first failed run and
   whenever the exit code changes, then at most once every
   GARRICK_ALERT_REPEAT seconds (3600) while the same failure lasts. A job
   that was failing and exits 0 again always raises one. Each says why in
   words: could not sign in, a connector missing, a cap reached, timed out.
   Exit codes in GARRICK_QUIET_EXITS, such as `5` for a job that reached
   some of its sources, are logged and kept in the heartbeat as quiet, never
   raise a notice, and count as a working run.

Where a notice goes: with GARRICK_NOTIFY=1, a macOS notification; with
GARRICK_NOTIFY_CMD, a command of yours, run with two more arguments, the
title and the message, and GARRICK_NOTIFY_KIND (failed, recovered, idle or
message), GARRICK_JOB and GARRICK_EXIT in its environment. Either, both or
neither. Nothing here leaves the machine unless that command sends it.
GARRICK_JOB_TIMEOUT, GARRICK_LOGIN_RETRY_AFTER, GARRICK_IDLE_DAYS and
GARRICK_ALERT_REPEAT set to anything but a number keep their defaults, with a
line in the log saying so.

GARRICK_ENV_FILE names a file of KEY=value lines read into the run's
environment before anything else, such as a sign-in token for a machine with
no desktop session. Its values are never written to the log.

The command runs in `--cwd` (or GARRICK_WORKSPACE, or your home folder; never
`/`, where a scheduler starts) with GARRICK_JOB, GARRICK_ITEMS_FILE,
GARRICK_JOBS_DIR and GARRICK_HEADLESS=1 set.

What the status page reads, all in the jobs folder:

    <name>.heartbeat.json  the last run: job, started, finished, finished_ts,
                           exit, seconds, ok, quiet, reason, items, idle_days,
                           idle, agent, failing_since
    <name>.lock/until      while a run holds it: "<until> <pid> <started>",
                           epoch seconds
    <name>.alert.json      while a job is failing: exit, since, alerted
    <name>.idle-alert      when the idle notice last went, epoch seconds
    <name>.log             one `===== ... exit N  (Ns) =====` line a run,
                           with `  quiet` before the closing `=====` when
                           the exit was quiet

`job.py status` reads them for you.

Standard library only, Python 3.9 or later. Not installed by install.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent  # noqa: E402

EXIT_LOGIN = agent.EXIT_LOGIN
EXIT_LOCKED = 75
EXIT_TIMEOUT = agent.EXIT_TIMEOUT
EXIT_START = 127
SLACK = 600  # two sign-in checks of up to 90 s each, the watchdog's grace, a slow start
NOTIFY_TIMEOUT = 60
ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def stamp(t: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def number(name: str, default: float, warnings: List[str]) -> float:
    """A count of seconds or days from the environment. A value that is not a
    number of zero or more falls back to the default, with a warning for the
    log: a typo in a plist must not stop every run."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not 0 <= value < float("inf"):
        warnings.append("job: %s is %r, not a number of zero or more; using %g\n" % (name, raw, default))
        return default
    return value


def take_lock(lock: Path, hold: float) -> bool:
    """mkdir is atomic. The lock records, in `until`, when it goes stale, which
    process holds it and when it was taken. A run that finds it judges it by
    that record, so a job with a short time limit does not take over the lock
    of one with a long limit, and a lock whose process has gone is taken over
    at once. A lock without a record, left by an older version, goes stale
    `hold` seconds after it was made."""
    took_over = False
    for _ in range(2):
        try:
            lock.mkdir()
        except FileExistsError:
            if took_over or not is_stale(lock, hold):
                return False
            shutil.rmtree(lock, ignore_errors=True)
            took_over = True
            continue
        now = time.time()
        record = "%d %d %d\n" % (now + hold, os.getpid(), now)
        try:
            (lock / "until").write_text(record, encoding="utf-8")
        except OSError:
            return True  # the lock holds all the same, and goes stale by its age
        if took_over:
            # Several runs can find one stale lock at once, as when a laptop
            # wakes with jobs overdue. The last record written stands; the
            # runs whose record it is not step back.
            time.sleep(1)
            try:
                return (lock / "until").read_text(encoding="utf-8") == record
            except OSError:
                return False
        return True
    return False


def is_stale(lock: Path, hold: float) -> bool:
    """Past its time, or held by a process that has gone, as after a crash."""
    try:
        words = (lock / "until").read_text(encoding="utf-8").split()
        until = float(words[0])
    except (OSError, ValueError, IndexError):
        try:
            until = lock.stat().st_mtime + hold
        except OSError:
            return True  # gone already
        words = []
    if len(words) > 1 and words[1].isdigit() and not alive(int(words[1])):
        return True
    return time.time() > until


def release(lock: Path) -> None:
    """Remove the lock, unless another run took it over while this one was
    away, as when a laptop sleeps through a run's limit."""
    try:
        holder = (lock / "until").read_text(encoding="utf-8").split()[1]
    except (OSError, IndexError):
        holder = str(os.getpid())
    if holder == str(os.getpid()):
        shutil.rmtree(lock, ignore_errors=True)


def watchdog(cmd: List[str], timeout: float, cwd: Path, env: dict, log) -> int:
    """Run the command in its own process group, so a stop reaches the
    assistant it started as well as the script that started it."""
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        log.write("job: could not start %s: %s\n" % (cmd[0], exc))
        return EXIT_START
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig, grace in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
            try:
                proc.wait(timeout=grace)
                break
            except subprocess.TimeoutExpired:
                continue
        return EXIT_TIMEOUT


def notify(kind: str, title: str, message: str, log=None, job: str = "", code: Optional[int] = None) -> bool:
    """Send a notice to wherever the settings say: a macOS notification with
    GARRICK_NOTIFY=1, and the command in GARRICK_NOTIFY_CMD, run as
    `<command> <title> <message>`. A notifier that fails costs a line in the
    log, never the run. True when there was somewhere to send it."""
    sent = False
    if os.environ.get("GARRICK_NOTIFY") == "1" and sys.platform == "darwin":
        script = ['-e', 'on run argv',
                  '-e', 'display notification (item 1 of argv) with title "Garrick" subtitle (item 2 of argv)',
                  '-e', 'end run', message, title]
        subprocess.run(["osascript"] + script, capture_output=True)
        sent = True
    command = os.environ.get("GARRICK_NOTIFY_CMD", "").strip()
    if command:
        sent = True
        env = dict(os.environ, GARRICK_NOTIFY_KIND=kind, GARRICK_JOB=job or os.environ.get("GARRICK_JOB", ""),
                   GARRICK_EXIT="" if code is None else str(code))
        try:
            proc = subprocess.run(shlex.split(command) + [title, message], env=env, capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, timeout=NOTIFY_TIMEOUT)
            problem = "exited %d" % proc.returncode if proc.returncode else ""
            output = (proc.stdout + proc.stderr).strip()
        except (OSError, ValueError) as exc:
            problem, output = "could not start: %s" % exc, ""
        except subprocess.TimeoutExpired:
            problem, output = "took longer than %ds and was stopped" % NOTIFY_TIMEOUT, ""
        if problem:
            line = "job: the notifier %s%s\n" % (problem, (": " + output.splitlines()[-1]) if output else "")
            if log:
                log.write(line)
            else:
                sys.stderr.write(line)
    return sent


def describe(code: int, seconds: float, timeout: float) -> str:
    """Why a run failed, in words, for the notice and the log."""
    if code == EXIT_LOGIN:
        return "could not sign in to %s, twice" % agent.harness()
    if code == agent.EXIT_CONNECTOR:
        return "needs a connector %s does not have; see the log" % agent.harness()
    if code == agent.EXIT_CAP:
        return "reached a spending cap; agent.py ledger shows which"
    if code == EXIT_TIMEOUT:
        return "timed out and was stopped after %ds" % timeout
    if code == EXIT_START:
        return "could not start its command; see the log"
    return "exited %d after %ds" % (code, seconds)


def quiet_exits(warnings: List[str]) -> Set[int]:
    """The exit codes in GARRICK_QUIET_EXITS, separated by commas or spaces.
    One that is not a whole number from 1 to 255 is left out, with a warning."""
    raw = os.environ.get("GARRICK_QUIET_EXITS", "")
    out: Set[int] = set()
    for word in raw.replace(",", " ").split():
        if word.isdigit() and 1 <= int(word) <= 255:
            out.add(int(word))
        else:
            warnings.append("job: GARRICK_QUIET_EXITS has %r, not an exit code from 1 to 255; left out\n" % word)
    return out


def read_env_file(path: Path) -> Dict[str, str]:
    """KEY=value lines, as a shell would read them: `export ` and matching
    quotes are allowed, blank lines and `#` lines skipped, anything else
    ignored."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not ENV_KEY.fullmatch(key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def load_env_file(log) -> None:
    """GARRICK_ENV_FILE into this run's environment, which the sign-in check
    and the job both inherit. Names in the log, never values."""
    raw = os.environ.get("GARRICK_ENV_FILE", "").strip()
    if not raw:
        return
    path = Path(raw).expanduser()
    try:
        values = read_env_file(path)
    except (OSError, UnicodeDecodeError) as exc:
        log.write("job: GARRICK_ENV_FILE %s could not be read (%s); running without it\n"
                  % (path, exc.__class__.__name__))
        return
    try:
        if path.stat().st_mode & 0o077:
            log.write("job: %s can be read by other users of this Mac; chmod 600 it\n" % path)
    except OSError:
        pass
    os.environ.update(values)
    log.write("job: read %s from %s\n" % (", ".join(sorted(values)) or "nothing", path))


def read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")


def read_epoch(path: Path) -> Optional[float]:
    try:
        return float(path.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def alert(name: str, code: int, ok: bool, state_path: Path, now: float, repeat: float, reason: str,
          log_path: Path, seconds: float, log) -> Optional[float]:
    """Notices on failure and recovery, throttled. A failure notifies on the
    first failed run and on any change of exit code, then at most every
    `repeat` seconds while it lasts; a return to working always notifies.
    The state, `<name>.alert.json`, lasts as long as the failure does.
    Returns when the failure began, or None when the job is working."""
    state = read_json(state_path)
    if ok:
        if state is not None:
            notify("recovered", "Job recovered", "%s is working again: exit %d after %ds." % (name, code, seconds),
                   log, name, code)
            state_path.unlink(missing_ok=True)
        return None
    since = state.get("since") if state and isinstance(state.get("since"), (int, float)) else now
    last = state.get("alerted") if state and isinstance(state.get("alerted"), (int, float)) else 0
    if state is None or state.get("exit") != code or now - last >= repeat:
        again = state is not None and state.get("exit") == code
        message = "%s %s. Log: %s" % (name, reason, log_path)
        if again:
            message += " Still failing; another notice in %s while it does." % span(repeat)
        notify("failed", "Job failed", message, log, name, code)
        last = now
    write_json(state_path, {"exit": code, "since": since, "alerted": last})
    return since


def span(seconds: float) -> str:
    if seconds >= 7200 and seconds % 3600 == 0:
        return "%d hours" % (seconds // 3600)
    if seconds == 3600:
        return "an hour"
    if seconds >= 120:
        return "%d minutes" % (seconds // 60)
    return "%d seconds" % seconds


def read_items(path: Path) -> Optional[int]:
    if not path.exists():
        return None
    digits = "".join(c for c in path.read_text(encoding="utf-8", errors="replace") if c.isdigit())
    return int(digits) if digits else None


def idle_days(items: Optional[int], lastwork: Path, now: float) -> Optional[int]:
    """Days since the last run that did anything, for jobs that report. The
    first report starts the clock rather than raising the alarm at once."""
    if items is None:
        return None
    if items > 0 or not lastwork.exists():
        lastwork.write_text("%d\n" % now, encoding="utf-8")
        return 0
    try:
        last = float(lastwork.read_text(encoding="utf-8").strip())
    except ValueError:
        lastwork.write_text("%d\n" % now, encoding="utf-8")
        return 0
    return int((now - last) // 86400)


def lock_state(lock: Path) -> Optional[dict]:
    """Who holds a lock, or None when nobody does. A lock past its time, or
    whose process has gone, is held by nobody, and the next fire takes it
    over."""
    if not lock.is_dir():
        return None
    try:
        words = (lock / "until").read_text(encoding="utf-8").split()
    except OSError:
        words = []
    numbers = []
    for word in words[:3]:
        try:
            numbers.append(float(word))
        except ValueError:
            break
    until = numbers[0] if numbers else None
    pid = int(numbers[1]) if len(numbers) > 1 else None
    started = numbers[2] if len(numbers) > 2 else None
    if until is None:
        try:
            started = lock.stat().st_mtime
        except OSError:
            return None
    # A lock without a record is judged by the default limits: the page cannot know the job's own.
    if is_stale(lock, 2 * 1500 + 300 + SLACK):
        return None
    return {"pid": pid, "started": stamp(started) if started else None, "until": stamp(until) if until else None}


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError):
        return True
    except OSError:
        return False
    return True


def status(folder: Optional[Path] = None, names: Optional[List[str]] = None) -> dict:
    """Every job the jobs folder knows, as the status page reads it: whether
    a run holds its lock now, its last heartbeat, and its notices. A job is
    known once it has a log, a heartbeat or a lock."""
    folder = folder or agent.jobs_dir()
    found: Set[str] = set()
    if folder.is_dir():
        for path in folder.iterdir():
            for suffix in (".heartbeat.json", ".log", ".lock"):
                if path.name.endswith(suffix):
                    stem = path.name[:-len(suffix)]
                    if not agent.name_problem(stem):
                        found.add(stem)
    jobs = []
    for name in sorted(names or found):
        state = read_json(folder / ("%s.alert.json" % name))
        idle_at = read_epoch(folder / ("%s.idle-alert" % name))
        held = lock_state(folder / ("%s.lock" % name))
        jobs.append({
            "job": name,
            "running": held is not None,
            "lock": held,
            "heartbeat": read_json(folder / ("%s.heartbeat.json" % name)),
            "failing": {"exit": state.get("exit"),
                        "since": stamp(state["since"]) if isinstance(state.get("since"), (int, float)) else None,
                        "notified": stamp(state["alerted"]) if isinstance(state.get("alerted"), (int, float)) else None}
                       if state else None,
            "idle_notified": stamp(idle_at) if idle_at else None,
            "log": str(folder / ("%s.log" % name)),
        })
    return {"folder": str(folder), "assistant_lock": lock_state(folder / "agent.lock"), "jobs": jobs}


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "status" and "--" not in argv:
        problems = [agent.name_problem(n) for n in argv[1:] if agent.name_problem(n)]
        if problems:
            print("job.py: %s" % problems[0], file=sys.stderr)
            return agent.EXIT_USAGE
        print(json.dumps(status(names=argv[1:]), indent=2, sort_keys=True))
        return 0
    if argv and argv[0] == "notify" and "--" not in argv:
        if len(argv) != 3:
            print("usage: job.py notify <title> <message>", file=sys.stderr)
            return agent.EXIT_USAGE
        if not notify("message", argv[1], argv[2]):
            print("job.py: no notifier is set (GARRICK_NOTIFY_CMD, or GARRICK_NOTIFY=1 on a Mac); nothing sent",
                  file=sys.stderr)
        return 0
    if "--" not in argv:
        print("usage: job.py <name> [--agent] [--cwd FOLDER] [--timeout SECONDS] -- <command> [args...]\n"
              "       job.py status [<name>...]\n"
              "       job.py notify <title> <message>", file=sys.stderr)
        return agent.EXIT_USAGE
    split = argv.index("--")
    ap = argparse.ArgumentParser(prog="job.py")
    ap.add_argument("name")
    ap.add_argument("--agent", action="store_true", help="the job calls an assistant")
    ap.add_argument("--cwd")
    ap.add_argument("--timeout", type=float, help="seconds before the watchdog stops the run (1500)")
    args = ap.parse_args(argv[:split])
    cmd = argv[split + 1:]
    if not cmd:
        print("job.py: no command after --", file=sys.stderr)
        return agent.EXIT_USAGE
    problem = agent.name_problem(args.name)
    if problem:
        print("job.py: %s" % problem, file=sys.stderr)
        return agent.EXIT_USAGE
    warnings: List[str] = []
    if args.timeout is None:
        args.timeout = number("GARRICK_JOB_TIMEOUT", 1500, warnings)
    retry = number("GARRICK_LOGIN_RETRY_AFTER", 300, warnings)
    idle_limit = number("GARRICK_IDLE_DAYS", 7, warnings)
    repeat = number("GARRICK_ALERT_REPEAT", 3600, warnings)
    quiet = quiet_exits(warnings) | {EXIT_LOCKED}   # a command's own "skipped" is never a failure

    jobs = agent.jobs_dir()
    jobs.mkdir(parents=True, exist_ok=True)
    name = args.name
    log_path = jobs / ("%s.log" % name)
    beat = jobs / ("%s.heartbeat.json" % name)
    items_file = jobs / ("%s.items" % name)
    lastwork = jobs / ("%s.lastwork" % name)
    alert_state = jobs / ("%s.alert.json" % name)
    idle_alert = jobs / ("%s.idle-alert" % name)
    cwd = Path(args.cwd or os.environ.get("GARRICK_WORKSPACE") or Path.home()).expanduser()
    # The job's lock covers the wait for the shared one, the sign-in retry and
    # the run; the shared one covers the retry and the run.
    hold_job = 2 * args.timeout + retry + SLACK
    hold_agent = args.timeout + retry + SLACK

    lock = jobs / ("%s.lock" % name)
    if not take_lock(lock, hold_job):
        with log_path.open("a", encoding="utf-8") as log:
            log.write("===== %s  %s  skipped: the previous run still holds the lock =====\n\n" % (stamp(), name))
        return EXIT_LOCKED
    agent_lock = jobs / "agent.lock"
    held_agent = False
    try:
        # Only the run that holds the lock touches its files: a fire that is
        # skipped must not rotate the log of the run it found still going.
        agent.rotate(log_path)
        items_file.unlink(missing_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            start = time.time()
            log.write("===== %s  %s  start =====\n" % (stamp(start), name))
            log.writelines(warnings)
            load_env_file(log)
            log.flush()
            env = dict(os.environ, GARRICK_JOB=name, GARRICK_ITEMS_FILE=str(items_file),
                       GARRICK_JOBS_DIR=str(jobs), GARRICK_HEADLESS="1")
            code = 0
            if args.agent:
                asked = time.time()
                while not take_lock(agent_lock, hold_agent):
                    left = asked + args.timeout - time.time()
                    if left <= 0:
                        # Running anyway would put two assistants side by side: the lock is there to stop that.
                        log.write("===== %s  %s  skipped: another assistant job held the shared lock for %ds =====\n\n"
                                  % (stamp(), name, time.time() - asked))
                        return EXIT_LOCKED
                    time.sleep(min(15, left))
                held_agent = True
                if time.time() - asked >= 1:
                    log.write("job: waited %ds for another assistant job\n" % (time.time() - asked))
                signed_in = agent.login_state(cwd)
                if signed_in is False:
                    log.write("job: %s is not signed in; checking again in %ds\n" % (agent.harness(), retry))
                    log.flush()
                    time.sleep(retry)
                    signed_in = agent.login_state(cwd)
                    if signed_in is False:
                        log.write("job: %s could not sign in twice. Job not started.\n" % agent.harness())
                        code = EXIT_LOGIN
                if signed_in is None:
                    # No answer is not a no: a Mac that slept through the check runs out its time on waking.
                    log.write("job: %s did not answer the sign-in check in time; running anyway\n" % agent.harness())
            if code == 0:
                log.flush()
                code = watchdog(cmd, args.timeout, cwd, env, log)
                if code == EXIT_TIMEOUT:
                    log.write("job: stopped by the watchdog after %ds\n" % args.timeout)
            now = time.time()
            seconds = now - start
            is_quiet = code in quiet
            ok = code == 0 or is_quiet
            reason = None if code == 0 else describe(code, seconds, args.timeout)
            if is_quiet:
                log.write("job: exit %d is quiet: logged, no notice\n" % code)
            elif reason:
                log.write("job: %s %s\n" % (name, reason))
            log.flush()
            failing_since = alert(name, code, ok, alert_state, now, repeat, reason or "", log_path, seconds, log)
            items = read_items(items_file) if ok else None
            idle = idle_days(items, lastwork, now)
            is_idle = bool(idle_limit) and idle is not None and idle >= idle_limit
            if items:
                idle_alert.unlink(missing_ok=True)
            if is_idle:
                log.write("job: idle. It has run cleanly and done nothing for %d days: its input has stopped "
                          "arriving, or it should be stopped.\n" % idle)
                alerted = read_epoch(idle_alert)
                if alerted is None or now - alerted >= idle_limit * 86400:
                    notify("idle", "Job idle", "%s has run cleanly but done nothing for %d days: its input has "
                           "stopped arriving, or it should be stopped." % (name, idle), log, name, code)
                    idle_alert.write_text("%d\n" % now, encoding="utf-8")
            log.write("===== %s  %s  exit %d  (%ds)%s =====\n\n"
                      % (stamp(now), name, code, seconds, "  quiet" if is_quiet else ""))
            write_json(beat, {"job": name, "started": stamp(start), "finished": stamp(now),
                              "finished_ts": round(now, 3), "exit": code, "seconds": round(seconds),
                              "ok": ok, "quiet": is_quiet, "reason": reason, "items": items,
                              "idle_days": idle, "idle": is_idle, "agent": bool(args.agent),
                              "failing_since": stamp(failing_since) if failing_since else None})
            return code
    finally:
        if held_agent:
            release(agent_lock)
        release(lock)


if __name__ == "__main__":
    sys.exit(main())
