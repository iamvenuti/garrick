#!/usr/bin/env python3
"""Wrap one scheduled run. An optional extra.

    python3 job.py <name> [--agent] [--cwd FOLDER] [--timeout SECONDS] -- <command> [args...]

The scheduler (launchd, cron) runs this, and this runs the job. One place for
everything a run needs when nobody is watching it:

1. **A log**, `<name>.log` in the jobs folder, rotated at 1 MB with one older
   generation kept.
2. **A heartbeat**, `<name>.heartbeat.json`: when the last run finished, its
   exit code, how long it took, how much it did. A scheduler lists a job as
   loaded whether or not it has ever worked; the heartbeat says whether it ran.
3. **A lock.** One run per job at a time. A fire that finds the previous run
   still going is skipped with exit 75 and a line in the log.
4. **A watchdog.** A run still going after `--timeout` seconds (1500) is
   stopped, with every process it started, and exits 124.
5. **With `--agent`**, one assistant job at a time across all jobs: headless
   sessions started in the same minute, as happens when a laptop wakes with
   several jobs overdue, can fail each other's sign-in. Then a sign-in check
   (agent.py login), once more after five minutes if it fails, and exit 4
   with the run skipped if it fails again.
6. **An idle alarm.** A job that reports how much it did (agent.report_items)
   and has done nothing for GARRICK_IDLE_DAYS days (7) gets a line in its log
   and `idle_days` in its heartbeat. A job that exits 0 having found nothing
   looks healthy on every other check.

With GARRICK_NOTIFY=1, a failed or idle run also raises a macOS notification.
Nothing here leaves the machine.

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
MAX_LOG_BYTES = 1024 * 1024


def stamp(t: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def rotate(path: Path) -> None:
    if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
        path.replace(path.with_name(path.name + ".1"))


def take_lock(lock: Path, stale_after: float) -> bool:
    """mkdir is atomic. A lock older than the watchdog limit plus slack belongs
    to a run that died without cleaning up, and is taken over."""
    try:
        lock.mkdir()
        return True
    except FileExistsError:
        if time.time() - lock.stat().st_mtime > stale_after:
            shutil.rmtree(lock, ignore_errors=True)
            try:
                lock.mkdir()
                return True
            except FileExistsError:
                return False
        return False


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
    ap.add_argument("--timeout", type=float, default=float(os.environ.get("GARRICK_JOB_TIMEOUT", 1500)))
    args = ap.parse_args(argv[:split])
    cmd = argv[split + 1:]
    if not cmd:
        print("job.py: no command after --", file=sys.stderr)
        return agent.EXIT_USAGE

    jobs = agent.jobs_dir()
    jobs.mkdir(parents=True, exist_ok=True)
    name = args.name
    log_path = jobs / ("%s.log" % name)
    beat = jobs / ("%s.heartbeat.json" % name)
    items_file = jobs / ("%s.items" % name)
    lastwork = jobs / ("%s.lastwork" % name)
    cwd = Path(args.cwd or os.environ.get("GARRICK_WORKSPACE") or Path.home()).expanduser()
    stale = args.timeout + 600
    rotate(log_path)
    items_file.unlink(missing_ok=True)

    lock = jobs / ("%s.lock" % name)
    with log_path.open("a", encoding="utf-8") as log:
        if not take_lock(lock, stale):
            log.write("===== %s  %s  skipped: the previous run still holds the lock =====\n\n" % (stamp(), name))
            return EXIT_LOCKED
        agent_lock = jobs / "agent.lock"
        held_agent = False
        try:
            start = time.time()
            log.write("===== %s  %s  start =====\n" % (stamp(start), name))
            log.flush()
            env = dict(os.environ, GARRICK_JOB=name, GARRICK_ITEMS_FILE=str(items_file),
                       GARRICK_JOBS_DIR=str(jobs), GARRICK_HEADLESS="1")
            code = 0
            if args.agent:
                waited = 0
                while not take_lock(agent_lock, stale):
                    if waited >= args.timeout:
                        log.write("job: gave up after %ds waiting for another assistant job\n" % waited)
                        break
                    time.sleep(15)
                    waited += 15
                else:
                    held_agent = True
                if waited:
                    log.write("job: waited %ds for another assistant job\n" % waited)
                if not agent.login_ok(cwd):
                    retry = float(os.environ.get("GARRICK_LOGIN_RETRY_AFTER", 300))
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
            limit = int(os.environ.get("GARRICK_IDLE_DAYS", 7))
            if idle is not None and idle >= limit:
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
                shutil.rmtree(agent_lock, ignore_errors=True)
            shutil.rmtree(lock, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
