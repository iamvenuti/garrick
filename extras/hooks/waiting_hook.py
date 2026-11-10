#!/usr/bin/env python3
"""The waiting hook: tells Garrick that a Claude Code session has stopped on a
permission prompt, which its transcript does not record.

It runs on four events, reading the event on stdin:

- Notification, with a `permission_prompt` or an `idle_prompt`: writes a
  small marker for the session, `~/.garrick-waiting/<session id>.json`, with
  the kind, the tool's name where the prompt names one, and the time. Nothing
  else from the event is kept: the message can name a file, a command or a
  question, and none of it is written.
- UserPromptSubmit and PostToolUse: the next prompt clears the session's
  marker, and so does the result of the tool the prompt was for. The result
  of another tool leaves a permission marker in place, and an idle_prompt
  never replaces an open permission_prompt: the row stays until the next
  prompt or that tool's result (the reader also drops a marker once the
  transcript is written after it).

Garrick's agents_working.py reads the markers, once a minute, with the
transcripts, and shows a session with an open `permission_prompt` as waiting.
The marker lives in the home folder, outside every workspace, and is never
committed. It reads and writes nothing else and never calls a model. Any error
is swallowed: a broken hook must not stop a session.
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

KINDS = ("permission_prompt", "idle_prompt")
CLEARS = ("UserPromptSubmit", "PostToolUse")
SAFE = re.compile(r"[^A-Za-z0-9_.:-]")
TOOL = re.compile(r"\buse\s+([A-Za-z0-9_.:-]{1,40})")


def folder() -> Path:
    return Path(os.environ.get("GARRICK_HOME") or Path.home()) / ".garrick-waiting"


def session_id(event: dict) -> str:
    sid = event.get("session_id")
    return sid if isinstance(sid, str) and sid and SAFE.sub("", sid) == sid and len(sid) <= 80 else ""


def handle(event: dict, now: float = None) -> None:
    sid = session_id(event)
    if not sid:
        return
    name = event.get("hook_event_name")
    mark = folder() / (sid + ".json")
    if name in CLEARS:
        if name == "PostToolUse":
            try:
                have = json.loads(mark.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            tool = event.get("tool_name")
            if isinstance(have, dict) and have.get("kind") == "permission_prompt" and have.get("tool") \
                    and tool != have.get("tool"):
                return                                          # another tool's result: the one asked about still waits
        try:
            mark.unlink()
        except OSError:
            pass
        return
    if name != "Notification":
        return
    kind = event.get("notification_type")
    if kind not in KINDS:
        return
    found = TOOL.search(event.get("message") or "") if isinstance(event.get("message"), str) else None
    try:
        if kind == "idle_prompt" and json.loads(mark.read_text(encoding="utf-8")).get("kind") == "permission_prompt":
            return                                              # an idle prompt never replaces an open permission prompt
    except (OSError, ValueError, AttributeError):
        pass
    body = {"session": sid, "kind": kind, "tool": found.group(1) if found else "",
            "since": time.time() if now is None else now}
    folder().mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".w-", dir=str(folder()))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(body, f)
    os.replace(tmp, mark)


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
        if isinstance(event, dict):
            handle(event)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
