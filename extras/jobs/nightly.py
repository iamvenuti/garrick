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

Each step runs whatever happened in the steps before it, with a time limit
of its own, so one that hangs is stopped and the rest still run. The exit
code is the worst of the four (the highest), so any failure turns the job
red. Each step's exit code, its seconds and its last lines go to job.py
through GARRICK_STEPS_FILE (agent.report_steps), and the heartbeat says
which step failed.

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
import os
import subprocess
import sys
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
           else ("nightly.local", None, "not executable: chmod +x %s" % local if local.is_file() else "none"),
           ("status", [sys.executable, str(STATUS / "status.py"), "--workspace", str(ws), "--same-flags"], "")
           if (STATUS / "status.py").is_file() else ("status", None, "no System/status/status.py")]
    return out


def run_step(cmd: List[str], cwd: Path, limit: float) -> Tuple[int, List[str], float]:
    """Run one step, its output passed on to the log; (exit, last lines, seconds)."""
    env = {k: v for k, v in os.environ.items() if k != "GARRICK_STEPS_FILE"}    # the steps file is this script's
    env["GARRICK_WORKSPACE"] = str(cwd)
    start = time.time()
    try:
        r = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=limit,
                           stdin=subprocess.DEVNULL)
        code, text = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or b""
        text = (out.decode("utf-8", "replace") if isinstance(out, bytes) else out) + "\nstopped after %ds" % limit
        code = EXIT_TIMEOUT
    except OSError as exc:
        code, text = 127, "could not start: %s" % exc
    lines = [line for line in text.splitlines() if line.strip()]
    for line in lines:
        print("  " + line)
    return code, [line[:300] for line in lines[-TAIL:]], time.time() - start


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
    return max((d["exit"] for d in failed), default=0)


if __name__ == "__main__":
    sys.exit(main())
