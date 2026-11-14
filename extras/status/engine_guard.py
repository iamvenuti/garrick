#!/usr/bin/env python3
"""engine_guard.py: the pre-tool hook of an engine session at Act (#571). It is the engine's own, bound to one zone.

    GARRICK_ENGINE_WS=<workspace> GARRICK_ENGINE_ZONE=<zone> python3 engine_guard.py < event

A write (Edit, Write, MultiEdit, NotebookEdit) is stopped unless it lands, where it really leads, through any link
and on a disk that ignores case, in one of three places: the zone the exchange is bound to, a wiki, or the
workspace's own `Inbox/`. A path under a synced shared folder (`.shared/`) is never written here: a write there
publishes, so it goes through `hold`. Anything else, another zone, `System/`, the settings, the rules, is refused.

It is built on the same idea as the shipped `extras/hooks/zone_guard.py` (a write outside the session's own place is
stopped), and differs in the three ways an unattended engine needs: it **refuses** where the zone guard asks (nobody
is there to ask), it is **bound to the exchange's zone** whatever folder the session runs in, and it **fails closed**:
an event it cannot read, or an error, refuses the write. The zones' commit check runs as for any commit.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.dont_write_bytecode = True

WRITES = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SHARED = ".shared"


def _real(path: str, cwd: str) -> str:
    return os.path.realpath(os.path.join(cwd or os.getcwd(), os.path.expanduser(path)))


def targets(event: dict) -> list:
    given = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    found = [given.get("file_path") or given.get("notebook_path") or ""]
    return [_real(p, cwd) for p in found if p]


def _inside(path: str, folder: str, blind: bool) -> bool:
    a, b = (path.casefold(), folder.casefold()) if blind else (path, folder)
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def _blind(root: str) -> bool:
    """Whether the disk under `root` ignores case, as a Mac's does."""
    swapped = root.swapcase()
    return swapped != root and os.path.exists(swapped) and os.path.samefile(swapped, root)


def decide(event: dict, ws: str, zone: str):
    """None to let the write run, or the hook's reply that refuses it."""
    if event.get("tool_name") not in WRITES:
        return None
    root = os.path.realpath(ws)
    blind = _blind(root)
    home = os.path.join(root, "Zones", zone)
    allowed = [home, os.path.join(root, "Wikis"), os.path.join(root, "Inbox")]
    bad = []
    for path in targets(event):
        shared = SHARED in re.split(r"[\\/]", path)
        if shared or not any(_inside(path, a, blind) for a in allowed):
            bad.append(path)
    if not event.get("tool_input") or not targets(event):
        bad = ["(no path)"]
    if not bad:
        return None
    reason = ("Refused: this exchange is bound to the %s zone. A write goes in that zone, a wiki or the workspace's "
              "Inbox, never in another zone, System/, or a shared folder; a write to a shared folder is queued "
              "with hold." % zone)
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def main() -> int:
    ws, zone = os.environ.get("GARRICK_ENGINE_WS", ""), os.environ.get("GARRICK_ENGINE_ZONE", "")
    try:
        event = json.load(sys.stdin)
        if not ws or not zone or not isinstance(event, dict):
            raise ValueError("no binding")
        reply = decide(event, ws, zone)
    except Exception:
        reply = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                        "permissionDecisionReason": "Refused: the engine's guard could not judge this write."}}
    if reply:
        print(json.dumps(reply, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
