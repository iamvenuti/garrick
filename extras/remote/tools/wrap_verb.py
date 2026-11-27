"""wrap_verb.py: the `wrap` verb's input, checked for its shape before anything is prepared (#723).

The wrap takes words, not judgment. The assistant writes the Resume here block's six rows, the dated entry, the commit
message and the Todo changes; `System/tools/wrap.py` does every step that needs no judgment, and it fails a key it does not
take, or one that is missing, with nothing written. This module checks the same shape first, so that a bad request is
refused at prepare and never stored, and passes the words on unchanged. It writes nothing.

Two keys of that tool are never passed from here. `memory` names a file outside the workspace, in the assistant's own folder
on the Mac. `lock: "held"` says that a caller holds the thread's lock, and a remote caller holds none. A request that carries
either is refused in words.

Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROWS = ("Live artifact", "Rebuild with", "Next action", "Keep in mind", "Waiting on", "Deadline")
TAKES = ("project", "thread", "resume", "entry", "message", "todo", "checkpoint")
MUST = ("project", "resume", "entry", "message")
NEVER = {
    "memory": "A wrap from here does not write a memory pointer: that file is outside the workspace, on the Mac. Leave memory out.",
    "lock": "A wrap from here takes its own lock. A request cannot say that one is held. Leave lock out.",
}
MOST_PROSE, MOST_LINE, MOST_MESSAGE, MOST_TODO_LINE, MOST_TODO_LINES = 6000, 2000, 300, 200, 20
LAYOUT = re.compile(r"^(#{1,6}\s|---+\s*$|\||<!--)")


def never(given) -> str:
    """The refusal of a key that is never passed, or "". Any value counts: a key that is there is refused."""
    for key, words in NEVER.items():
        if key in given and given[key] is not None:
            return words
    return ""


def one_line(value, what, most) -> str:
    if not isinstance(value, str) or not value.strip():
        return "%s is empty or is not text." % what
    if "\n" in value or "\r" in value:
        return "%s must be one line." % what
    if len(value) > most:
        return "%s is too long." % what
    return ""


def prose(value, what) -> str:
    if not isinstance(value, str) or not value.strip():
        return "%s is empty or is not text." % what
    if len(value) > MOST_PROSE or "\r" in value:
        return "%s is too long, or has carriage returns." % what
    for line in value.splitlines():
        if LAYOUT.match(line.strip()):
            return "%s has a line that would change the note's layout." % what
    return ""


def shape(fields) -> str:
    """Why the wrap's own fields are not the input wrap.py takes, or "". `fields` has passed the generic checks."""
    resume = fields.get("resume")
    if not isinstance(resume, dict) or set(resume) != {"stands", "rows"} or not isinstance(resume["rows"], dict):
        return "resume must hold stands and rows, and nothing else."
    if set(resume["rows"]) != set(ROWS):
        return "resume rows must be exactly: %s." % ", ".join(ROWS)
    why = prose(resume["stands"], "resume stands")
    for row in ROWS:
        why = why or one_line(resume["rows"][row], "the %s row" % row, MOST_LINE)
    why = why or prose(fields.get("entry"), "entry") or one_line(fields.get("message"), "message", MOST_MESSAGE)
    if why:
        return why
    todo = fields.get("todo")
    if todo is not None:
        if not isinstance(todo, dict) or set(todo) - {"add", "tick"}:
            return "todo takes add and tick, and nothing else."
        for kind in ("add", "tick"):
            lines = todo.get(kind) or []
            if not isinstance(lines, list) or len(lines) > MOST_TODO_LINES:
                return "todo %s must be a short list." % kind
            for line in lines:
                why = one_line(line, "a todo %s line" % kind, MOST_TODO_LINE)
                if why:
                    return why
    if fields.get("checkpoint") not in (None, "folded"):
        return "checkpoint is either left out or \"folded\"."
    return ""


def note_rel(fields) -> str:
    """The note a wrap writes, from the zone: the thread's note, or the hub of a project that keeps its resume point there."""
    project, thread = fields["project"], fields.get("thread")
    return "%s/Threads/%s/%s.md" % (project, thread, thread) if thread else "%s/%s.md" % (project, project)


def inside(zone_dir: Path, fields) -> bool:
    """Whether the project, the thread and the note are real folders and a file of the zone: no link on the way, and
    every resolved path below the zone. A folder that is not there is left to the wrap tool, which says so in words."""
    try:
        zone = zone_dir.resolve()
        walk = zone_dir
        for part in note_rel(fields).split("/"):
            walk = walk / part
            if walk.is_symlink():
                return False
            if walk.exists() and zone not in walk.resolve().parents:
                return False
    except OSError:
        return False
    return True
