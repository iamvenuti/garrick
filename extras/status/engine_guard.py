#!/usr/bin/env python3
"""engine_guard.py: the pre-tool hook of an engine session at Act (#571). It is the engine's own, bound to one zone.

    GARRICK_ENGINE_WS=<workspace> GARRICK_ENGINE_ZONE=<zone> python3 engine_guard.py < event

A write (Edit, Write, MultiEdit, NotebookEdit) is stopped unless it lands, where it really leads, through any link
and on a disk that ignores case, in one of three places: the zone the exchange is bound to, the `wiki/` folder of a
wiki (never its `raw/`, the record), or the inbox of the Meetings wiki, or the workspace's own `Inbox/`. A path under a
synced shared folder (`.shared/`) is never written here: a write there publishes, so it goes through `hold`. A path
with a `.git` part, and `.gitattributes` and `.gitmodules`, are refused wherever they are: a file there makes git run
code. Anything else, another zone, `System/`, the settings, the rules, is refused.

A Bash command is refused unless it is one call of the engine's own wrapper (engine_cmd.py) with nothing joined to it.

A refusal exits 2, as well as printing the deny reply: Claude treats any other non-zero exit as no block.

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
import shlex
import sys

sys.dont_write_bytecode = True

WRITES = ("Edit", "Write", "MultiEdit", "NotebookEdit")
HERE = os.path.dirname(os.path.realpath(__file__))
SHARED = ".shared"
# A write that makes `git status` or a commit run code: the git directory (config, hooks) and the two files that
# change how git reads a tree. Refused anywhere, whatever the case of the name.
GIT_NAMES = (".gitattributes", ".gitmodules")


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


def _git_part(path: str) -> bool:
    parts = [p.casefold() for p in re.split(r"[\\/]", path) if p]
    return ".git" in parts or bool(parts and parts[-1] in GIT_NAMES)


def _wiki_ok(path: str, root: str, blind: bool) -> bool:
    """Whether the path is in a wiki's `wiki/` folder or in the Meetings wiki's inbox: the record beside them is not."""
    base = os.path.join(root, "Wikis")
    if not _inside(path, base, blind) or len(path) <= len(base):
        return False
    rel = [p for p in path[len(base):].split(os.sep) if p]
    if blind:
        rel = [p.casefold() for p in rel]
    if len(rel) >= 3 and rel[1] == "wiki":
        return True
    return len(rel) >= 4 and rel[:3] == ["meetings" if blind else "Meetings", "raw", "inbox"]


def hook_command() -> str:
    """The command line of this hook as the session's settings carry it: both words quoted, so a path with a space
    in it still runs this file (a hook that cannot start is not a block)."""
    return "%s %s" % (shlex.quote(sys.executable or "python3"), shlex.quote(os.path.join(HERE, "engine_guard.py")))


def bash_ok(command) -> bool:
    """Whether a Bash command is one call of the engine's own wrapper and nothing joined to it: no second command, no
    pipe, redirect, substitution or line break. The permission list names the wrapper; this holds what it cannot."""
    if not isinstance(command, str) or not command.strip() or "\n" in command or "\r" in command:
        return False
    if "`" in command or "$(" in command or "${" in command:
        return False
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    tokens = list(lex)
    if any(t and set(t) <= set(";&|<>()") for t in tokens):
        return False
    return (len(tokens) >= 3 and os.path.basename(tokens[0]).startswith("python")
            and os.path.realpath(tokens[1]) == os.path.join(HERE, "engine_cmd.py"))


def decide(event: dict, ws: str, zone: str):
    """None to let the write run, or the hook's reply that refuses it."""
    if event.get("tool_name") == "Bash":
        if bash_ok((event.get("tool_input") or {}).get("command")):
            return None
        return _deny("Refused: a command here is one call of the engine's own wrapper (engine_cmd.py), alone on its line, "
                     "with no pipe, redirect, substitution or second command.")
    if event.get("tool_name") not in WRITES:
        return None
    root = os.path.realpath(ws)
    blind = _blind(root)
    home = os.path.join(root, "Zones", zone)
    allowed = [home, os.path.join(root, "Inbox")]
    bad = []
    for path in targets(event):
        shared = SHARED in re.split(r"[\\/]", path)
        if shared or _git_part(path) or not (any(_inside(path, a, blind) for a in allowed) or _wiki_ok(path, root, blind)):
            bad.append(path)
    if not event.get("tool_input") or not targets(event):
        bad = ["(no path)"]
    if not bad:
        return None
    reason = ("Refused: this exchange is bound to the %s zone. A write goes in that zone, a wiki's wiki/ folder or the "
              "workspace's Inbox, never in another zone, System/, a wiki's raw record, a .git folder, or a shared folder; "
              "a write to a shared folder is queued with hold." % zone)
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}


def main() -> int:
    ws, zone = os.environ.get("GARRICK_ENGINE_WS", ""), os.environ.get("GARRICK_ENGINE_ZONE", "")
    try:
        event = json.load(sys.stdin)
        if not ws or not zone or not isinstance(event, dict):
            raise ValueError("no binding")
        reply = decide(event, ws, zone)
    except BaseException:                      # fail closed, and with the exit code Claude blocks on
        reply = _deny("Refused: the engine's guard could not judge this write.")
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
