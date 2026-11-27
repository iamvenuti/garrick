"""common.py: what the read tools and the write tools share: where the service keeps state, the words of a
refusal, and a few small checks. Standard library only."""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

NEW_REACH = "new_context_required"
NEW_CHAT = "start_new_chat"
NOT_THERE = "No such place. places() lists the projects and threads."      # the words Ask uses for a place that is not there
NOT_GIVEN = "That id was not given in this conversation."                  # and for an id that was never handed out
NO_ZONE = "No such zone."

# The machine code and the spoken sentence are context.py's (NEW_CONTEXT_REQUIRED, NEW_CONTEXT_SAY). One copy is kept here, because this
# module cannot load context.py on its own; test_tools_reach_words.py fails when the two differ.
REACH_SAY = "That is outside what this connection may reach. The owner sets that at the Mac."
NEW_CHAT_SAY = "That chat belongs to an earlier setting. Start a new chat."
WRITE_REACH_SAY = REACH_SAY

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}


def state_root() -> Path:
    """The service's own folder: GARRICK_REMOTE_HOME, else the Mac's Application Support folder. Mode 0700."""
    given = os.environ.get("GARRICK_REMOTE_HOME")
    root = Path(given).expanduser() if given else Path.home() / "Library" / "Application Support" / "Garrick" / "remote"
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(root), 0o700)
    except OSError:
        pass
    return root


def private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(path), 0o700)
    except OSError:
        pass
    return path


def short(text: str, size: int = 12) -> str:
    """A fixed-length name for a grant or a zone in a folder name: never the text itself, so nothing in it can name a path."""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:size]


def refusal(code: str, say: str) -> dict:
    return {"error": code, "say": say}


def reach_refusal() -> dict:
    return refusal(NEW_REACH, REACH_SAY)


def write_reach_refusal() -> dict:
    return refusal(NEW_REACH, WRITE_REACH_SAY)


def check_handle(session, handle):
    """None when the handle is fine or none was sent; else the refusal. A handle is an aid, not the boundary:
    it stops an old chat that carries on after the owner changed the reach."""
    if handle in (None, ""):
        return None
    try:
        session.check_handle(str(handle)[:200])
    except Exception as e:                      # HandleRefused, or anything a session raises: fail closed
        words = str(e)
        return refusal(NEW_CHAT, words if "start a new chat" in words.lower() else NEW_CHAT_SAY)
    return None


def clean_zone_name(name) -> str:
    return " ".join(str(name or "").split())


_SAFE = re.compile(r"[0-9a-fA-F]{8,64}")


def op_id_ok(value) -> bool:
    return isinstance(value, str) and bool(_SAFE.fullmatch(value))
