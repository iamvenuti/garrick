#!/usr/bin/env python3
"""A scheduled job: Garrick's one nightly run, four steps in order (#276).

    python3 nightly.py --workspace /Users/<you>/Garrick [--scope Zones/Work]... [--digest]
                       [--also FOLDER]... [--moved OLD=NEW]...

1. **nurture**: Context Nurture's mechanical kind, as nurture_sweep.py runs
   it, with `--scope` and `--digest` passed on. It runs check.py in full,
   the night's only full check.
2. **effort**: `System/status/effort.py --record`, with `--also` and
   `--moved` passed on, so the Effort view keeps the days Claude Code's
   transcripts lose after 30. Skipped when the status page extra is not
   there.
3. **nightly.local**: the workspace's own nightly checks,
   `System/jobs/nightly.local`, run in the workspace when the file exists
   and is executable. Garrick never ships or changes it. Without it the
   step is skipped, and that is no fault.
4. **status**: `System/status/status.py --same-flags`, so the page shows
   what the first three found, with the flags the Mac app or the Obsidian
   plugin last gave it. It runs its own quick check (check.py --quick), as
   every rebuild does, so the page shows the state after the fixes.
   Skipped when the status page extra is not there.

Each step runs whatever happened in the steps before it, in a process group
of its own, with a time limit of its own: one that hangs is stopped with
everything it started, git included, and the rest still run. Its output goes
to the job's log as it comes. The exit code is 0 when every step exited 0
and 1 when any did not, so any failure turns the job red and none reads as a
code job.py gives a meaning of its own (75, skipped; 8, a spending cap).
Each step's own exit code, its seconds and its last lines go to job.py
through GARRICK_STEPS_FILE (agent.report_steps), and the heartbeat and the
reason say which step failed and how. A stop asked of this script (SIGTERM
from job.py's watchdog or launchctl bootout) stops the step running first.

No assistant is called, so the run counts nothing against the jobs' caps.
nightly.local should call none either: a check that needs the assistant is a
job of its own, with `--agent`. Run it through job.py, so it has a log, a
lock and a watchdog:

    python3 job.py gr-nightly --cwd /Users/<you>/Garrick --timeout 3600 -- \\
        /usr/bin/python3 /Users/<you>/Garrick/System/jobs/nightly.py \\
        --workspace /Users/<you>/Garrick --digest

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import collections
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import agent  # noqa: E402

NURTURE = HERE / "nurture_sweep.py"
STATUS = HERE.parent / "status"            # System/status beside System/jobs, as extras/status is beside extras/jobs
LOCAL = ("System", "jobs", "nightly.local")
# Seconds each step may take; their sum stays under the plist's --timeout 3600.
LIMITS = {"nurture": 1800, "effort": 600, "nightly.local": 600, "status": 480}
TAIL = 10
EXIT_TIMEOUT = 124
EXIT_FAILED = 1
GRACE = 5                                  # seconds between SIGTERM and SIGKILL to a step's group
NOT_EXECUTABLE = "not executable (chmod +x %s)"
_running: List[subprocess.Popen] = []      # the step under way, for a stop asked of this script


def steps(ws: Path, args: argparse.Namespace) -> List[Tuple[str, Optional[List[str]], str]]:
    """(step, command, why it is skipped) for the four steps, in order. A
    step with no command is skipped."""
    nurture = [sys.executable, str(NURTURE), "--workspace", str(ws)]
    for scope in args.scope:
        nurture += ["--scope", scope]
    if args.digest:
        nurture.append("--digest")
    effort = [sys.executable, str(STATUS / "effort.py"), "--workspace", str(ws), "--record"]
    for a in args.also:
        effort += ["--also", a]
    for m in args.moved:
        effort += ["--moved", m]
    local = ws.joinpath(*LOCAL)
    out = [("nurture", nurture, ""),
           ("effort", effort, "") if (STATUS / "effort.py").is_file() else ("effort", None, "no System/status/effort.py"),
           ("nightly.local", [str(local)], "") if local.is_file() and os.access(str(local), os.X_OK)
           else ("nightly.local", None, NOT_EXECUTABLE % local if local.is_file() else "none"),
           ("status", [sys.executable, str(STATUS / "status.py"), "--workspace", str(ws), "--same-flags"], "")
           if (STATUS / "status.py").is_file() else ("status", None, "no System/status/status.py")]
    return out


def stop_group(proc: subprocess.Popen) -> None:
    """SIGTERM to the step's whole process group, then SIGKILL to whatever of
    it is left: a step's children, such as git, never outlive it."""
    for sig, wait in ((signal.SIGTERM, GRACE), (signal.SIGKILL, GRACE)):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            return                              # the group has gone
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            pass


def run_step(cmd: List[str], cwd: Path, limit: float) -> Tuple[int, List[str], float]:
    """Run one step in a process group of its own, its output, standard
    error included, passed on to the log as it comes; (exit, last lines,
    seconds). Past `limit`, the whole group is stopped and the step exits 124."""
    env = {k: v for k, v in os.environ.items() if k != "GARRICK_STEPS_FILE"}    # the steps file is this script's
    env["GARRICK_WORKSPACE"] = str(cwd)
    start = time.time()
    tail: collections.deque = collections.deque(maxlen=TAIL)

    def said(line: str) -> None:
        line = line.rstrip("\n")
        if line.strip():
            print("  " + line, flush=True)
            tail.append(line[:300])

    try:
        proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace", start_new_session=True)
    except OSError as exc:
        said("could not start: %s" % exc)
        return 127, list(tail), time.time() - start
    _running.append(proc)
    pump = threading.Thread(target=lambda: [said(line) for line in proc.stdout], daemon=True)
    pump.start()
    try:
        code = proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        stop_group(proc)
        code = EXIT_TIMEOUT
    finally:
        _running.remove(proc)
    try:
        os.killpg(proc.pid, signal.SIGKILL)     # anything the step left behind in its group
    except OSError:
        pass
    pump.join(timeout=GRACE)
    if code == EXIT_TIMEOUT:
        said("stopped after %ds, with everything it started" % limit)
    return code, list(tail), time.time() - start


def stopped(signum, frame):
    """Asked to stop: stop the step under way with its group, then go."""
    for proc in list(_running):
        stop_group(proc)
    raise SystemExit(128 + signum)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Garrick's nightly run: nurture, the effort record, your own checks, the page.")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--scope", action="append", default=[], help="for nurture: a zone, project or wiki; repeat for more")
    ap.add_argument("--digest", action="store_true", help="for nurture: send its one line as the Todo summary notice")
    ap.add_argument("--also", action="append", default=[], metavar="FOLDER",
                    help="for effort: a folder the workspace used to live in (repeatable)")
    ap.add_argument("--moved", action="append", default=[], metavar="OLD=NEW",
                    help="for effort: a folder renamed or moved, its old path and its path now (repeatable)")
    args = ap.parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve()
    if not (ws / "System").is_dir():
        print("nightly: %s is not a workspace: it has no System/ folder" % ws, file=sys.stderr)
        return agent.EXIT_USAGE
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, stopped)
    done: List[dict] = []
    for step, cmd, why in steps(ws, args):
        if cmd is None:
            print("nightly: %s skipped: %s" % (step, why))
            done.append({"step": step, "exit": 0, "skipped": why})
        else:
            print("nightly: %s" % step)
            code, tail, seconds = run_step(cmd, ws, LIMITS[step])
            print("nightly: %s exit %d (%ds)" % (step, code, seconds))
            done.append({"step": step, "exit": code, "seconds": round(seconds), "tail": tail})
        agent.report_steps(done)                  # after each step, so a run stopped midway still says how far it got
    failed = [d for d in done if d["exit"]]
    print("nightly: %s" % ", ".join("%s %s" % (d["step"], "skipped" if "skipped" in d else "ok" if not d["exit"]
                                                else "exit %d" % d["exit"]) for d in done))
    return EXIT_FAILED if failed else 0         # each step's own code is in the steps, and so in the heartbeat


if __name__ == "__main__":
    sys.exit(main())
