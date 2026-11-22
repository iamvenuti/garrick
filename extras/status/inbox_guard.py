#!/usr/bin/env python3
"""inbox_guard.py: the pre-tool hook of the background inbox run (#634, S3). It is the inbox run's own.

    GARRICK_INBOX_WS=<workspace> [GARRICK_INBOX_ZONE=<zone>] python3 inbox_guard.py < event

A write (Edit, Write, MultiEdit, NotebookEdit) is stopped unless the path, once every link on the way is followed, is one that
`inbox_run.allowed()` names inside the workspace: an inbox, the Meetings and Knowledge wikis, a project's or thread's own
`Sources/`, a zone's `Todo.md` and `Needs you` files. With `GARRICK_INBOX_ZONE` set (an answer to a question), a path under
`Zones/` must be in that zone. The check is made before the write, so a file outside the workspace, a nested repository or an
ignored path is never written, which the check after the run could not see.

A refusal exits 2, as well as printing the deny reply: Claude treats any other non-zero exit as no block. It fails closed: an
event it cannot read, or an error, refuses the write.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import json
import os
import shlex
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
WRITES = ("Edit", "Write", "MultiEdit", "NotebookEdit")
sys.path.insert(0, HERE)


def hook_command() -> str:
    return "%s %s" % (shlex.quote(sys.executable or "python3"), shlex.quote(os.path.join(HERE, "inbox_guard.py")))


def targets(event: dict) -> list:
    given = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    found = [given.get("file_path") or given.get("notebook_path") or ""]
    return [os.path.realpath(os.path.join(cwd, os.path.expanduser(p))) for p in found if p]


def decide(event: dict, ws: str, zone: str = ""):
    """None to let the write run, or the hook's reply that refuses it."""
    if event.get("tool_name") not in WRITES:
        return None
    import inbox_run
    root = os.path.realpath(ws)
    paths = targets(event)
    if not paths:
        return _deny("Refused: a write with no path.")
    for path in paths:
        rel = os.path.relpath(path, root)
        parts = rel.split(os.sep)
        if rel.startswith("..") or os.path.isabs(rel) or not inbox_run.allowed("/".join(parts)):
            return _deny("Refused: the inbox run writes only in an inbox, a wiki, a project's Sources/, a zone's Todo.md and its "
                         "Needs you files.")
        if zone and parts[0] == "Zones" and parts[1] != zone:
            return _deny("Refused: this run is for one zone, and the path is in another.")
    return None


def _deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def main() -> int:
    ws, zone = os.environ.get("GARRICK_INBOX_WS", ""), os.environ.get("GARRICK_INBOX_ZONE", "")
    try:
        event = json.load(sys.stdin)
        if not ws or not isinstance(event, dict):
            raise ValueError("no binding")
        reply = decide(event, ws, zone)
    except BaseException:                      # fail closed, and with the exit code Claude blocks on
        reply = _deny("Refused: the inbox run's guard could not judge this write.")
    if reply:
        print(json.dumps(reply, ensure_ascii=False))
        print(reply["hookSpecificOutput"]["permissionDecisionReason"], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except BaseException:
        code = 2
    sys.exit(code)
