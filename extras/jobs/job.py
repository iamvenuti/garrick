#!/usr/bin/env python3
"""Wrap one scheduled run. An optional extra.

    python3 job.py <name> [--agent] [--cwd FOLDER] [--timeout SECONDS] -- <command> [args...]
    python3 job.py status [<name>...]      every job's state, as JSON
    python3 job.py notify <title> <message>  send a line through the notifier
    python3 job.py check-scripts <file>...   find job scripts that call an assistant directly

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
   still going is skipped with exit 75 and a line in the log. The lock
   records this process and, once it starts, the command's process group.
   It stands while this process lives, however long that is: a Mac that
   sleeps mid-run wakes past any limit, and the run is still the one
   holding it. Once this process has gone, as after a crash, the lock
   stands while the command it left behind still runs, until the time the
   run could rightly take: the wait for the shared lock below, the sign-in
   retry and the run itself, with ten minutes of slack. The next fire after
   that stops the command and takes the lock over. A lock whose process and
   command have both gone is taken over at once.
4. **A watchdog.** A run still going after `--timeout` seconds (1500) is
   stopped, with every process it started, and exits 124. When this
   process is itself asked to stop (SIGTERM from `launchctl bootout` or a
   shutdown, SIGHUP, SIGINT), it stops the command's process group first,
   lets go of its locks, and leaves a heartbeat saying so, with exit 128
   plus the signal's number, as a shell reports it: 143 for SIGTERM.
5. **With `--agent`**, one assistant job at a time across all jobs: headless
   sessions started in the same minute, as happens when a laptop wakes with
   several jobs overdue, can fail each other's sign-in. A run that waits its
   whole time limit for another assistant job is skipped with exit 75. Then
   a sign-in check (agent.py login), once more after five minutes if it
   fails, and exit 4 with the run skipped if it fails again. A run that
   exits 0 having added no line for the job to agent.py's ledger gets a line
   in its log and `no_call` in its heartbeat: fine if it had nothing to ask,
   but a job that runs `claude -p` or `codex exec` itself is held by no cap
   and no deny profile, and this is how it shows.
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
   raise a notice, and count as a working run. A command's own exit 4 or 124
   reads "exited 4": only this wrapper's sign-in check and watchdog say
   "could not sign in" and "timed out". A command killed by a signal exits
   128 plus its number, and the reason names the signal. A run stopped
   because this process was asked to stop raises no notice.

Where a notice goes: with GARRICK_NOTIFY=1, a macOS notification; with
GARRICK_NOTIFY_CMD, a command of yours, run with two more arguments, the
title and the message, and GARRICK_NOTIFY_KIND (failed, recovered, idle or
message), GARRICK_JOB and GARRICK_EXIT in its environment. Either, both or
neither. Nothing here leaves the machine unless that command sends it.
GARRICK_JOB_TIMEOUT, GARRICK_LOGIN_RETRY_AFTER, GARRICK_IDLE_DAYS and
GARRICK_ALERT_REPEAT set to anything but a number keep their defaults, with a
line in the log saying so, and so does a GARRICK_JOB_TIMEOUT of zero. A
`--timeout` of zero or less is refused with exit 64.

GARRICK_ENV_FILE names a file of KEY=value lines read into the run's
environment before anything else, such as a sign-in token for a machine with
no desktop session. It is read before every other setting, so it can set any
of them, GARRICK_JOBS_DIR included. Its values are never written to the log.

The command runs in `--cwd` (or GARRICK_WORKSPACE, or your home folder; never
`/`, where a scheduler starts) with GARRICK_JOB, GARRICK_ITEMS_FILE,
GARRICK_JOBS_DIR and GARRICK_HEADLESS=1 set.

What the status page reads, all in the jobs folder:

    <name>.heartbeat.json  the last run: job, started, finished, finished_ts,
                           exit, seconds, ok, quiet, reason, items, idle_days,
                           idle, agent, no_call, failing_since
    <name>.lock/until      while a run holds it: "<until> <pid> <started>",
                           then " <group> <group started>" once the
                           command runs; times in epoch seconds
    <name>.alert.json      while a job is failing: exit, since, alerted
    <name>.idle-alert      when the idle notice last went, epoch seconds
    <name>.log             one `===== ... exit N  (Ns) =====` line a run,
                           with `  quiet` before the closing `=====` when
                           the exit was quiet

`job.py status` reads them for you. `job.py check-scripts` reads a job's
scripts, or the plists that run them, for a line that runs `claude -p` or
`codex exec` itself instead of going through agent.py, and exits 1 when it
finds one.

Standard library only, Python 3.9 or later. Not installed by install.py.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

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
STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
STOP_GRACE = 5      # launchd follows its SIGTERM with SIGKILL 20 s later
SAME_START = 5      # seconds of leeway when a process's start is matched against a lock's record


def stamp(t: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def number(name: str, default: float, warnings: List[str], above_zero: bool = False) -> float:
    """A count of seconds or days from the environment. A value that is not a
    number of zero or more (above zero, with `above_zero`) falls back to the
    default, with a warning for the log: a typo in a plist must not stop
    every run."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not 0 <= value < float("inf") or (above_zero and value == 0):
        warnings.append("job: %s is %r, not a number of %s; using %g\n"
                        % (name, raw, "seconds above zero" if above_zero else "zero or more", default))
        return default
    return value


# --------------------------------------------------------------------------- being stopped


class Stopped(Exception):
    """This process was asked to stop: `launchctl bootout`, a plist loaded
    again, the Mac shutting down, Ctrl-C."""

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


_handling = False
_deferred: List[int] = []


def _stop(signum, frame):
    hold_signals()
    raise Stopped(signum)


def _defer(signum, frame):
    _deferred.append(signum)


def catch_signals() -> None:
    """From here on a stop raises Stopped, so the run can stop its command and
    let go of its locks. A stop that came while they were held is raised now."""
    if not _handling:
        return
    for sig in STOP_SIGNALS:
        signal.signal(sig, _stop)
    if _deferred:
        raise Stopped(_deferred.pop(0))


def hold_signals() -> None:
    """A stop waits while a child is being started, or the run is writing up
    its result: either takes a moment, and an interrupted one leaves a child
    nobody knows of or a lock nobody releases. A handler of our own, not
    SIG_IGN, so the child does not inherit a deaf ear."""
    if not _handling:
        return
    for sig in STOP_SIGNALS:
        signal.signal(sig, _defer)


def start_handling() -> Optional[dict]:
    """Catch the stop signals for the length of a run; the handlers there
    were before, for stop_handling. None where signals cannot be caught, off
    the main thread."""
    global _handling
    try:
        previous = {sig: signal.getsignal(sig) for sig in STOP_SIGNALS}
        for sig in STOP_SIGNALS:
            signal.signal(sig, _stop)
    except ValueError:
        return None
    _handling = True
    del _deferred[:]
    return previous


def stop_handling(previous: Optional[dict]) -> None:
    global _handling
    if previous is None:
        return
    _handling = False
    for sig, handler in previous.items():
        signal.signal(sig, handler if handler is not None else signal.SIG_DFL)


def signal_name(signum: int) -> str:
    try:
        return signal.Signals(signum).name
    except ValueError:
        return "signal %d" % signum


def stop_group(proc: subprocess.Popen, grace: float) -> None:
    """SIGTERM to the command's whole process group, then SIGKILL if it is
    still there after `grace` seconds."""
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            break
        try:
            proc.wait(timeout=wait)
            break
        except subprocess.TimeoutExpired:
            continue


def stop_orphan(group: int) -> None:
    """The same for a group this process did not start, left by a run whose
    job.py was killed: it is nobody's child here, so it is watched, not
    waited on."""
    for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        try:
            os.killpg(group, sig)
        except OSError:
            return
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                os.killpg(group, 0)
            except OSError:
                return
            time.sleep(0.2)


# --------------------------------------------------------------------------- locks


def process_start(pid: int) -> Optional[float]:
    """When a process started, in epoch seconds, from the time `ps` says it
    has been running: wall time, so a Mac's sleep counts, and no time zone to
    get wrong. None when ps cannot say."""
    try:
        out = subprocess.run(["ps", "-o", "etime=", "-p", str(pid)], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, timeout=10).stdout.strip()
        days, _, clock = out.rpartition("-")
        seconds = 0
        for field in clock.split(":"):
            seconds = seconds * 60 + int(field)
        return time.time() - seconds - int(days or 0) * 86400
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def same_process(pid: int, started: Optional[float]) -> Optional[bool]:
    """Whether `pid` is still the process a lock recorded as started at
    `started`: True, False when it has gone or its number now belongs to a
    later process, None when it lives but its start cannot be checked."""
    if not alive(pid):
        return False
    if started is None:
        return None
    began = process_start(pid)
    if began is None:
        return None
    return began <= started + SAME_START


def group_state(group: int, started: Optional[float]) -> Optional[bool]:
    """Whether the command's process group a lock recorded still runs: True
    when its first process is still the one recorded, False when the group
    has gone or its number belongs to another, None when only processes it
    started remain, which cannot be checked. The system gives no new process
    a group's number while that group lives."""
    try:
        os.killpg(group, 0)
    except PermissionError:
        return False                 # another user's: not one of ours
    except OSError:
        return False
    if alive(group):
        return same_process(group, started)
    return None


def read_record(lock: Path) -> List[float]:
    """The numbers in a lock's `until`: until, pid, started, then group and
    group started once the command runs. [] when it has none."""
    try:
        words = (lock / "until").read_text(encoding="utf-8").split()
    except OSError:
        return []
    numbers: List[float] = []
    for word in words[:5]:
        try:
            numbers.append(float(word))
        except ValueError:
            break
    return numbers


def holder(lock: Path, hold: float) -> Tuple[bool, Optional[int]]:
    """Whether a run still holds `lock`, and the process group of a command
    left running by a job.py that has gone, to stop before the lock is taken
    over.

    A job.py that lives holds its lock whatever the clock says: the time on
    the lock is wall time, which runs on while a Mac sleeps, so a run caught
    by a closed lid wakes past it, still going. Time counts only once job.py
    has gone, for the command it left behind without a watchdog, or when the
    process cannot be checked. A lock without a record goes by its age."""
    numbers = read_record(lock)
    now = time.time()
    if not numbers:
        try:
            return now <= lock.stat().st_mtime + hold, None
        except OSError:
            return False, None              # gone already
    late = now > numbers[0]
    if len(numbers) < 2:
        return not late, None
    me = same_process(int(numbers[1]), numbers[2] if len(numbers) > 2 else None)
    if me is True:
        return True, None
    if me is None:
        return not late, None
    if len(numbers) < 4:
        return False, None
    group = int(numbers[3])
    left = group_state(group, numbers[4] if len(numbers) > 4 else None)
    if left is None:
        return True, None                   # cannot be sure it is ours to stop, so it stands
    if left and late:
        return False, group
    return left, None


def orphan(lock: Path) -> Optional[int]:
    """The process group of a command still running in a lock whose job.py
    has gone, for the line that says why a fire was skipped."""
    numbers = read_record(lock)
    if len(numbers) < 4 or same_process(int(numbers[1]), numbers[2] if len(numbers) > 2 else None) is not False:
        return None
    group = int(numbers[3])
    return group if group_state(group, numbers[4] if len(numbers) > 4 else None) is not False else None


def take_lock(lock: Path, hold: float, notes: Optional[List[str]] = None) -> bool:
    """mkdir is atomic. The lock records, in `until`, when it goes stale, which
    process holds it and when it was taken, and later the command's process
    group (mark_child). A run that finds it judges it by that record
    (holder), so a job with a short time limit does not take over the lock
    of one with a long limit, and a lock whose process has gone is taken over
    at once. A lock without a record, left by an older version, goes stale
    `hold` seconds after it was made."""
    took_over = False
    for _ in range(2):
        try:
            lock.mkdir()
        except FileExistsError:
            if took_over:
                return False
            held, left = holder(lock, hold)
            if held:
                return False
            if left:
                stop_orphan(left)
                if notes is not None:
                    notes.append("job: stopped process group %d, left running past its time by a run whose "
                                 "job.py had gone\n" % left)
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
    """Held by nobody: the next fire takes it over (holder)."""
    return not holder(lock, hold)[0]


def mark_child(lock: Path, group: int, started: float) -> None:
    """Add the command's process group to this process's lock record, so a
    later run knows the command still runs even if this process is killed
    outright. Written whole, then moved into place."""
    path = lock / "until"
    try:
        words = path.read_text(encoding="utf-8").split()
        if len(words) < 3 or words[1] != str(os.getpid()):
            return
        fresh = lock / "until.new"
        fresh.write_text("%s %s %s %d %d\n" % (words[0], words[1], words[2], group, started), encoding="utf-8")
        os.replace(fresh, path)
    except OSError:
        pass


def release(lock: Path) -> None:
    """Remove the lock, unless another run took it over while this one was
    away, as when a laptop sleeps through a run's limit."""
    try:
        holder = (lock / "until").read_text(encoding="utf-8").split()[1]
    except (OSError, IndexError):
        holder = str(os.getpid())
    if holder == str(os.getpid()):
        shutil.rmtree(lock, ignore_errors=True)


def watchdog(cmd: List[str], timeout: float, cwd: Path, env: dict, log,
             locks: Tuple[Path, ...] = ()) -> Tuple[int, Optional[str]]:
    """Run the command in its own process group, so a stop reaches the
    assistant it started as well as the script that started it. The group
    goes into each of `locks`. Returns the exit code and what ended the run
    when it was not the command's own exit: "timeout", "start", or "signal"
    for a command killed by one, whose code is then 128 plus its number.
    A stop of this process stops the group, then goes on up as Stopped."""
    hold_signals()
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        log.write("job: could not start %s: %s\n" % (cmd[0], exc))
        catch_signals()
        return EXIT_START, "start"
    try:
        began = time.time()
        for lock in locks:
            mark_child(lock, proc.pid, began)
        catch_signals()
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        hold_signals()
        stop_group(proc, 10)
        return EXIT_TIMEOUT, "timeout"
    except Stopped:
        stop_group(proc, STOP_GRACE)
        raise
    if code < 0:
        return 128 - code, "signal"
    return code, None


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


def describe(code: int, seconds: float, timeout: float, cause: Optional[str] = None) -> str:
    """Why a run failed, in words, for the notice and the log. `cause` is
    what this wrapper saw end the run (watchdog's, or "login"): a command's
    own exit 4 or 124 is its own, and reads as a number."""
    if cause == "login":
        return "could not sign in to %s, twice" % agent.harness()
    if cause == "timeout":
        return "timed out and was stopped after %ds" % timeout
    if cause == "start":
        return "could not start its command; see the log"
    if cause == "signal":
        return "was stopped by %s after %ds (exit %d)" % (signal_name(code - 128), seconds, code)
    if code == agent.EXIT_CONNECTOR:
        return "needs a connector %s does not have; see the log" % agent.harness()
    if code == agent.EXIT_CAP:
        return "reached a spending cap; agent.py ledger shows which"
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


def load_env_file() -> List[str]:
    """GARRICK_ENV_FILE into this run's environment, which the sign-in check
    and the job both inherit. Read before any other setting, so the file can
    hold any of them; returns the lines for the log, which is not open yet.
    Names in the log, never values."""
    raw = os.environ.get("GARRICK_ENV_FILE", "").strip()
    if not raw:
        return []
    path = Path(raw).expanduser()
    try:
        values = read_env_file(path)
    except (OSError, UnicodeDecodeError) as exc:
        return ["job: GARRICK_ENV_FILE %s could not be read (%s); running without it\n"
                % (path, exc.__class__.__name__)]
    lines = []
    try:
        if path.stat().st_mode & 0o077:
            lines.append("job: %s can be read by other users of this Mac; chmod 600 it\n" % path)
    except OSError:
        pass
    if "GARRICK_ENV_FILE" in values:
        lines.append("job: GARRICK_ENV_FILE in %s is left out: the file is read once\n" % path)
        values.pop("GARRICK_ENV_FILE")
    os.environ.update(values)
    lines.append("job: read %s from %s\n" % (", ".join(sorted(values)) or "nothing", path))
    return lines


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
    """Who holds a lock, or None when nobody does, by the rule a run takes
    a lock over with (holder): a living job.py holds it whatever its time."""
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
    if not holder(lock, 2 * 1500 + 300 + SLACK)[0]:
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


# A line that starts an assistant itself: `claude -p` or `codex exec` in a
# shell script, or the same two words as items of a Python list. What follows
# a `#` is a comment and does not count.
DIRECT_CALL = re.compile(r"""^[^#]*?(?:\b(claude)\s+(?:-p|--print)\b|\b(codex)\s+exec\b"""
                         r"""|["'](claude)["']\s*,\s*["'](?:-p|--print)["']|["'](codex)["']\s*,\s*["']exec["'])""")


def direct_calls(path: Path) -> List[str]:
    """`<file>:<line>: ...` for each line of a job script that runs an
    assistant without agent.py. Such a call loads no deny profile, counts
    against no cap and is tied to one assistant. A plist is read for the
    command it runs and the files that command names. agent.py, which builds
    those commands, and this file, which describes them, are never findings."""
    if path.name in ("agent.py", "job.py"):
        return []
    if path.suffix == ".plist":
        try:
            with path.open("rb") as f:
                args = [str(a) for a in plistlib.load(f).get("ProgramArguments", [])]
        except (OSError, ValueError, AttributeError) as exc:
            return ["%s: could not be read as a plist (%s)" % (path, exc.__class__.__name__)]
        found = []
        if DIRECT_CALL.match(" ".join(args)):
            found.append("%s: runs an assistant itself; run it through job.py and agent.py" % path)
        for a in args:
            if a.endswith((".sh", ".py", ".zsh", ".bash")) and Path(a).is_file():
                found += direct_calls(Path(a))
        return found
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ["%s: could not be read (%s)" % (path, exc.__class__.__name__)]
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        m = DIRECT_CALL.match(line)
        if m:
            found.append("%s:%d: runs %s directly; call agent.py run instead"
                         % (path, n, next(g for g in m.groups() if g)))
    return found


def check_scripts(paths: List[str]) -> int:
    """0 when every file goes through agent.py, 1 when one does not or could
    not be read: a file left unread is not a file found clean."""
    found = []
    for raw in paths:
        found += direct_calls(Path(raw).expanduser())
    for line in found:
        print(line)
    if not found:
        print("job.py: %d file%s checked; every assistant call goes through agent.py"
              % (len(paths), "" if len(paths) == 1 else "s"))
    return 1 if found else 0


def recorded_calls(name: str, since: float, now: float) -> int:
    """How many lines agent.py's ledger gained for `name` from `since` on. A
    call refused by a cap writes one too, so it counts."""
    hours = (now - since) / 3600 + 0.1
    return sum(1 for e in agent.read_ledger(agent.ledger_path(), now, hours)
               if e.get("job") == name and e["ts"] >= since - 1)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "check-scripts" and "--" not in argv:
        if len(argv) < 2:
            print("usage: job.py check-scripts <script or plist>...", file=sys.stderr)
            return agent.EXIT_USAGE
        return check_scripts(argv[1:])
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
              "       job.py notify <title> <message>\n"
              "       job.py check-scripts <script or plist>...", file=sys.stderr)
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
    if args.timeout is not None and not 0 < args.timeout < float("inf"):
        print("job.py: --timeout is %g; give the seconds a run may take, above zero" % args.timeout,
              file=sys.stderr)
        return agent.EXIT_USAGE
    # The env file first: every setting below may come from it.
    env_lines = load_env_file()
    warnings: List[str] = []
    if args.timeout is None:
        args.timeout = number("GARRICK_JOB_TIMEOUT", 1500, warnings, above_zero=True)
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
    notes: List[str] = []
    if not take_lock(lock, hold_job, notes):
        left = orphan(lock)
        why = ("the previous run's command, process group %d, is still going though its job.py has gone"
               % left) if left else "the previous run still holds the lock"
        with log_path.open("a", encoding="utf-8") as log:
            log.write("===== %s  %s  skipped: %s =====\n\n" % (stamp(), name, why))
        return EXIT_LOCKED
    agent_lock = jobs / "agent.lock"
    held_agent = False
    previous = start_handling()
    try:
        # Only the run that holds the lock touches its files: a fire that is
        # skipped must not rotate the log of the run it found still going.
        agent.rotate(log_path)
        items_file.unlink(missing_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            start = time.time()
            log.write("===== %s  %s  start =====\n" % (stamp(start), name))
            log.writelines(env_lines + warnings + notes)
            log.flush()
            env = dict(os.environ, GARRICK_JOB=name, GARRICK_ITEMS_FILE=str(items_file),
                       GARRICK_JOBS_DIR=str(jobs), GARRICK_HEADLESS="1")
            code, cause = 0, None
            try:
                if args.agent:
                    asked = time.time()
                    notes = []
                    while not take_lock(agent_lock, hold_agent, notes):
                        left = asked + args.timeout - time.time()
                        if left <= 0:
                            # Running anyway would put two assistants side by side: the lock is there to stop that.
                            log.write("===== %s  %s  skipped: another assistant job held the shared lock for %ds "
                                      "=====\n\n" % (stamp(), name, time.time() - asked))
                            return EXIT_LOCKED
                        time.sleep(min(15, left))
                    held_agent = True
                    log.writelines(notes)
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
                            code, cause = EXIT_LOGIN, "login"
                    if signed_in is None:
                        # No answer is not a no: a Mac that slept through the check runs out its time on waking.
                        log.write("job: %s did not answer the sign-in check in time; running anyway\n"
                                  % agent.harness())
                if code == 0:
                    log.flush()
                    code, cause = watchdog(cmd, args.timeout, cwd, env, log,
                                           (lock, agent_lock) if held_agent else (lock,))
                    if cause == "timeout":
                        log.write("job: stopped by the watchdog after %ds\n" % args.timeout)
            except Stopped as stop:
                return stopped(stop.signum, name, start, log, beat, alert_state, bool(args.agent))
            hold_signals()
            now = time.time()
            seconds = now - start
            is_quiet = code in quiet
            ok = code == 0 or is_quiet
            reason = None if code == 0 else describe(code, seconds, args.timeout, cause)
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
            no_call = bool(args.agent) and code == 0 and recorded_calls(name, start, time.time()) == 0
            if no_call:
                log.write("job: %s exited 0 and recorded no assistant call. Fine if it had nothing to ask; "
                          "otherwise it runs claude or codex around agent.py, where no cap or deny profile "
                          "holds it, and job.py check-scripts finds the line.\n" % name)
            log.write("===== %s  %s  exit %d  (%ds)%s =====\n\n"
                      % (stamp(now), name, code, seconds, "  quiet" if is_quiet else ""))
            write_json(beat, {"job": name, "started": stamp(start), "finished": stamp(now),
                              "finished_ts": round(now, 3), "exit": code, "seconds": round(seconds),
                              "ok": ok, "quiet": is_quiet, "reason": reason, "items": items,
                              "idle_days": idle, "idle": is_idle, "agent": bool(args.agent), "no_call": no_call,
                              "failing_since": stamp(failing_since) if failing_since else None})
            return code
    except Stopped as stop:
        return 128 + stop.signum                      # before the log was open: nothing to write it in
    finally:
        if held_agent:
            release(agent_lock)
        release(lock)
        stop_handling(previous)


def stopped(signum: int, name: str, start: float, log, beat: Path, alert_state: Path, agent_job: bool) -> int:
    """This process was asked to stop mid-run, and has stopped its command:
    a line in the log and a heartbeat that say so, and exit 128 plus the
    signal's number. No notice: a stop is something you or the Mac did, and
    the next run says whether the job works. The locks go in main's finally."""
    now = time.time()
    code = 128 + signum
    reason = "was stopped by %s after %ds, before it finished" % (signal_name(signum), now - start)
    log.write("job: %s %s; what it had started was stopped with it, and its locks let go\n" % (name, reason))
    log.write("===== %s  %s  exit %d  (%ds) =====\n\n" % (stamp(now), name, code, now - start))
    state = read_json(alert_state)
    since = state.get("since") if state and isinstance(state.get("since"), (int, float)) else None
    write_json(beat, {"job": name, "started": stamp(start), "finished": stamp(now),
                      "finished_ts": round(now, 3), "exit": code, "seconds": round(now - start),
                      "ok": False, "quiet": False, "reason": reason, "items": None,
                      "idle_days": None, "idle": False, "agent": agent_job, "no_call": False,
                      "failing_since": stamp(since) if since else None})
    return code

if __name__ == "__main__":
    sys.exit(main())
