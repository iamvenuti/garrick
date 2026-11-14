#!/usr/bin/env python3
"""A scheduled job: file the notes waiting in the inboxes, and update a thread when a note warrants it (#572).

    python3 notes_job.py --workspace /Users/<you>/Garrick [--fetch "<command>"]... [--tier sonnet]

Fetching and filing are two steps. Each `--fetch` command (the mail fetcher, say) runs first, one after another; a
fetcher that fails is reported and the others still run, and the notes already saved are processed all the same.
Then the intake skill's `process_notes.py` runs over every inbox: code finds the notes, settles each destination and
makes every write; the assistant, when there is work, is called once per zone with no tools, to say what each note
warrants (see that file). An empty queue, or only notes already waiting for an answer, makes no assistant call at
all, and an assistant call goes through agent.py like every job's, under the jobs' caps and into the ledger.

The job commits only what it wrote, in the zone each note belongs to, through the zone's wall check, and never
sends anything. Run it through job.py, so it has a log, a lock and a watchdog:

    python3 job.py gr-notes --agent --cwd /Users/<you>/Garrick -- \
        /usr/bin/python3 /Users/<you>/Garrick/System/jobs/notes_job.py --workspace /Users/<you>/Garrick

A workspace with its own scheduler runs `python3 System/skills/intake/intake.py process-notes` instead: the same step.
Exit codes: 0; 1 when a fetch failed or a note could not be filed; 64 for a workspace without the intake skill.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import agent  # noqa: E402

FETCH_TIMEOUT = 300


def fetch(commands: List[str]) -> List[str]:
    """Run each fetch command; the reasons of those that failed. One failing never stops the next."""
    failed = []
    for command in commands:
        try:
            r = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=FETCH_TIMEOUT, stdin=subprocess.DEVNULL)
            if r.returncode != 0:
                failed.append("%s exited %d" % (Path(shlex.split(command)[0]).name, r.returncode))
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            failed.append("a fetch did not run: %s" % type(e).__name__)
    return failed


def processor(workspace: Path):
    src = workspace / "System" / "skills" / "intake" / "process_notes.py"
    if not src.is_file():
        return None
    sys.path.insert(0, str(src.parent))
    spec = importlib.util.spec_from_file_location("garrick_process_notes", str(src))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch, then file the notes waiting in the inboxes.")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--fetch", action="append", default=[], help="a command that saves notes into an inbox; repeat for more")
    ap.add_argument("--tier", default="sonnet", choices=agent.TIERS)
    args = ap.parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    mod = processor(workspace)
    if mod is None:
        print("notes_job: %s has no System/skills/intake/process_notes.py; update Garrick first" % workspace, file=sys.stderr)
        return agent.EXIT_USAGE
    failed = fetch(args.fetch)
    for why in failed:
        print("notes_job: %s" % why, file=sys.stderr)
    result = mod.run(workspace, mod.agent_assessor(workspace, args.tier))
    print(json.dumps(result, sort_keys=True))
    agent.report_items(result["filed"])
    return 1 if failed or result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
