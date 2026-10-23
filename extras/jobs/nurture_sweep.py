#!/usr/bin/env python3
"""A scheduled job: Context Nurture each night, the mechanical kind only.

    python3 nurture_sweep.py --workspace /Users/<you>/Garrick [--scope Zones/Work]... [--digest]

It runs the workspace's own `System/tools/nurture.py nightly`, which gathers
every finding of `check.py`, `wiki_lint.py` for both wikis and the drift
`drift.py` last saved, sorts them into their kinds and applies the
mechanical ones: a link broken by a rename with exactly one candidate, a
deliverable without its date prefix, a thread missing from its hub's list, a
status synonym, a note path written as code that leads to exactly one live
note, a thread's note with no `parent:`. One commit per repository, of the files it changed and no
other, by name, so whatever another session has not committed stays out of
it; a file with changes not committed is not touched at all, and waits in
the report. Each commit goes through the repository's wall check, and one it
refuses is put back. Wall, attribution and judgment findings never change
with nobody watching: they wait in the day's report,
`System/generated/nurture/<YYYY-MM-DD>.md`, for "nurture the context".

With --digest, one line goes through System/tools/notifications.py as the
*Todo summary* event, the morning digest's, saying what was fixed first and
then what waits, in counts: never a file's content. Nothing to fix and
nothing waiting sends nothing; a copy only behind the share is not waiting.
A wall waits whatever else does, so one wall is enough for a notice. When the
context debt is over its threshold, or has kept rising for a week, a line
says so, with the scope carrying most and the request that nurtures it:
"Context debt 42, up from 18 last week, mostly attribution in the Meetings
wiki. Say "nurture the meetings"." Pages that would fade add a line too,
once a wiki's count reaches the setting's minimum ("41 meeting pages would go
dormant and 9 to the archive. Say "fade the meetings"."), and either line
alone is worth sending. Nothing fades overnight: a fade waits for a yes on
its written proposal.

No assistant is called. Run it through job.py, so it has a log, a lock and a
watchdog:

    python3 job.py nurture --cwd /Users/<you>/Garrick -- \\
        /usr/bin/python3 /Users/<you>/Garrick/System/jobs/nurture_sweep.py \\
        --workspace /Users/<you>/Garrick --digest

Exit codes: 0; 1 when a commit was refused or a source did not run; 64 for
a workspace without System/tools/nurture.py.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

EXIT_USAGE = 64


def run(workspace: Path, scopes: List[str]) -> dict:
    """The workspace's own nurture.py, unattended, as JSON."""
    script = workspace / "System" / "tools" / "nurture.py"
    args = [sys.executable, str(script), "nightly", "--root", str(workspace), "--json"]
    for scope in scopes:
        args += ["--scope", scope]
    r = subprocess.run(args, capture_output=True, text=True, timeout=3600, stdin=subprocess.DEVNULL)
    try:
        out = json.loads(r.stdout)
    except ValueError:
        return {"error": (r.stderr or r.stdout).strip()[-300:] or "nurture.py exited %d" % r.returncode,
                "code": r.returncode or 1}
    out["code"] = r.returncode
    return out


def send_digest(said: str) -> None:
    import job
    job.notify("digest", "Context", said, event="todo-summary")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Apply the mechanical context fixes overnight; leave the rest for a session.")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--scope", action="append", default=[], help="a zone, project or wiki, from the workspace's top; repeat for more")
    ap.add_argument("--digest", action="store_true", help="send one line, what was fixed and what waits, as the Todo summary notice")
    args = ap.parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    if not (workspace / "System" / "tools" / "nurture.py").is_file():
        print("nurture_sweep: %s has no System/tools/nurture.py; update Garrick first" % workspace, file=sys.stderr)
        return EXIT_USAGE
    out = run(workspace, args.scope)
    if "error" in out:
        print("nurture_sweep: %s" % out["error"], file=sys.stderr)
        return out["code"] or 1
    said = out.get("digest", "")
    for c in out.get("commits", []):
        print("%s: committed %s, %s" % (c["repo"], c["commit"], ", ".join(c["paths"])))
    for item in out.get("held", []):
        print("held: %s: %s" % (item["path"], item["held"]))
    for f in out.get("failed", []):
        print("did not run: %s" % f, file=sys.stderr)
    owed = out.get("debt_line") or ""                              # a nurture.py older than the debt has none
    print(said)
    if owed:
        print(owed)
    waits = out.get("waiting", len(out.get("items") or []))      # a nurture.py older than `waiting` counts every item
    if args.digest and (out.get("fixed") or waits or out.get("refused") or out.get("fade") or owed):
        send_digest("\n".join(x for x in (said, owed) if x))
    return out["code"]


if __name__ == "__main__":
    sys.exit(main())
