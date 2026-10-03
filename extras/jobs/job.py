#!/usr/bin/env python3
"""Wrap one scheduled run. An optional extra.

    python3 job.py <name> [--agent] [--cwd FOLDER] [--timeout SECONDS] -- <command> [args...]

The name is letters, digits, hyphens and underscores, and not `agent`. The
scheduler (launchd, cron) runs this, and this runs the job. One place for
everything a run needs when nobody is watching it:

1. **A log**, `<name>.log` in the jobs folder, rotated at 1 MB with one older
   generation kept.
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
6. **An idle alarm.** A job that reports how much it did (agent.report_items)
   and has done nothing for GARRICK_IDLE_DAYS days (7) gets a line in its log
   and `idle_days` in its heartbeat. A job that exits 0 having found nothing
   looks healthy on every other check.

With GARRICK_NOTIFY=1, a failed or idle run also raises a macOS notification.
Nothing here leaves the machine. GARRICK_JOB_TIMEOUT, GARRICK_LOGIN_RETRY_AFTER
and GARRICK_IDLE_DAYS set to anything but a number keep their defaults, with
a line in the log saying so.

The command runs in `--cwd` (or GARRICK_WORKSPACE, or your home folder; never
`/`, where a scheduler starts) with GARRICK_JOB, GARRICK_ITEMS_FILE,
GARRICK_JOBS_DIR and GARRICK_HEADLESS=1 set.

Standard library only, Python 3.9 or later. Not installed by install.py.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent  # noqa: E402

EXIT_LOGIN = 4
EXIT_LOCKED = 75
EXIT_TIMEOUT = 124
SLACK = 600  # two sign-in checks of up to 90 s each, the watchdog's grace, a slow start


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
    """mkdir is atomic. The lock records, in `until`, when it goes stale and
    which process holds it. A run that finds it judges it by that record, so
    a job with a short time limit does not take over the lock of one with a
    long limit. A lock without a record, left by an older version, goes stale
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
        record = "%d %d\n" % (time.time() + hold, os.getpid())
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
    try:
        until = float((lock / "until").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        try:
            until = lock.stat().st_mtime + hold
        except OSError:
            return True  # gone already
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
        return 127
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


def notify(message: str) -> None:
    if os.environ.get("GARRICK_NOTIFY") != "1" or sys.platform != "darwin":
        return
    script = ['-e', 'on run argv', '-e', 'display notification (item 1 of argv) with title "Garrick"',
              '-e', 'end run', message]
    subprocess.run(["osascript"] + script, capture_output=True)


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


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("usage: job.py <name> [--agent] [--cwd FOLDER] [--timeout SECONDS] -- <command> [args...]",
              file=sys.stderr)
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

    jobs = agent.jobs_dir()
    jobs.mkdir(parents=True, exist_ok=True)
    name = args.name
    log_path = jobs / ("%s.log" % name)
    beat = jobs / ("%s.heartbeat.json" % name)
    items_file = jobs / ("%s.items" % name)
    lastwork = jobs / ("%s.lastwork" % name)
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
                if not agent.login_ok(cwd):
                    log.write("job: %s is not signed in; checking again in %ds\n" % (agent.harness(), retry))
                    log.flush()
                    time.sleep(retry)
                    if not agent.login_ok(cwd):
                        log.write("job: %s could not sign in twice. Job not started.\n" % agent.harness())
                        code = EXIT_LOGIN
            if code == 0:
                log.flush()
                code = watchdog(cmd, args.timeout, cwd, env, log)
                if code == EXIT_TIMEOUT:
                    log.write("job: stopped by the watchdog after %ds\n" % args.timeout)
            now = time.time()
            items = read_items(items_file) if code == 0 else None
            idle = idle_days(items, lastwork, now)
            if idle is not None and idle >= idle_limit:
                log.write("job: idle. It has run cleanly and done nothing for %d days: its input has stopped "
                          "arriving, or it should be stopped.\n" % idle)
                notify("%s has done nothing for %d days." % (name, idle))
            elif code not in (0, EXIT_LOCKED):
                notify("%s exited %d. Log: %s" % (name, code, log_path))
            log.write("===== %s  %s  exit %d  (%ds) =====\n\n" % (stamp(now), name, code, now - start))
            beat.write_text(json.dumps({"job": name, "finished": stamp(now), "exit": code,
                                        "seconds": round(now - start), "items": items,
                                        "idle_days": idle}, sort_keys=True) + "\n", encoding="utf-8")
            return code
    finally:
        if held_agent:
            release(agent_lock)
        release(lock)


if __name__ == "__main__":
    sys.exit(main())
