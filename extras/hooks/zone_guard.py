#!/usr/bin/env python3
"""The zone guard: a check before the assistant writes outside the project its
session was opened in.

A session opened in a thread belongs to that thread's project. An edit there,
or to a file lying loose in the project's zone folder (a zone's Todo.md), goes
ahead. An edit anywhere else in the workspace (another project, another zone,
a wiki, System/) is stopped once, with a sentence naming both places. A
session opened at the workspace root, or outside any workspace, is never
stopped, and neither is an edit outside the workspace: the scratchpad, /tmp,
the assistant's own memory.

It is a hook for two harnesses, reading the event on stdin:

- Claude Code, on PreToolUse and PostToolUse for Edit, Write, MultiEdit and
  NotebookEdit. Before the edit it asks you, in Claude Code's own permission
  prompt. After an edit you allowed it remembers the place, so the rest of the
  session writes there without asking again. Refuse, and it asks next time.
- Codex, on PreToolUse for apply_patch. Codex hooks cannot ask, so the first
  edit to a place is refused with the same sentence, which tells the
  assistant to check with you; a second edit there in the same session goes
  through.

The session's home is $CLAUDE_PROJECT_DIR when Claude Code sets it, which
stays where the session started however often a command changes folder;
otherwise the event's cwd. A scheduled job (GARRICK_HEADLESS=1) has nobody to
ask, so the guard stands aside for it. It reads files only, and never calls a
model. Any error lets the edit through: a broken guard must not stop work.
"""
import json
import os
import re
import sys
import tempfile

CLAUDE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
PATCH_PATH = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): *(.+?)\s*$", re.M)


def workspace_root(folder):
    """The nearest folder at or above `folder` holding System/rules.md."""
    for f in [folder] + parents(folder):
        if os.path.isfile(os.path.join(f, "System", "rules.md")):
            return f
    return None


def parents(path):
    out = []
    while True:
        up = os.path.dirname(path)
        if up == path:
            return out
        out.append(up)
        path = up


def parts(root, path):
    """`path` below `root` as a list of names, or None when it is not below."""
    rel = os.path.relpath(path, root)
    if rel == ".":
        return []
    if rel == ".." or rel.startswith(".." + os.sep):
        return None
    return rel.split(os.sep)


def home_place(names):
    """The folder a session opened at `names` (relative to the root) may write
    in, as relative names. [] means anywhere: the root itself."""
    if not names:
        return []
    if names[0] == "Zones":
        return names[:3]       # a project, or the zone or Zones/ itself
    if names[0] == "Wikis":
        return names[:2]       # one wiki
    return names[:1]           # System/, or another top-level folder


def allowed(home, target):
    """Whether a file at `target` may be written from a session homed at `home`
    (both as names below the root)."""
    if target[:len(home)] == home:
        return True
    # A project's session may write the files loose in its zone's folder.
    return len(home) == 3 and home[0] == "Zones" and len(target) == 3 and target[:2] == home[:2]


def say(names):
    """A place as a person would say it: Work › Acme Review, System, Wikis › Meetings."""
    if not names:
        return "the workspace root"
    if names[0] == "Zones":
        if len(names) == 1:
            return "Zones"
        if len(names) == 2:
            return "the %s zone" % names[1]
        return "%s › %s" % (names[1], names[2])
    return " › ".join(names)


def target_place(names):
    """The place a file belongs to, for naming and remembering it."""
    if names[0] == "Zones":
        return names[:3] if len(names) > 3 else names[:2]
    return home_place(names)


def edits(event):
    """The files the tool call would write, as absolute paths."""
    tool, given = event.get("tool_name"), event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    if tool == "apply_patch":
        found = PATCH_PATH.findall(given.get("command") or given.get("patch") or "")
    elif tool in CLAUDE_TOOLS:
        found = [given.get("file_path") or given.get("notebook_path") or ""]
    else:
        return []
    return [os.path.abspath(os.path.join(cwd, os.path.expanduser(p))) for p in found if p]


def memory_file(event):
    session = re.sub(r"[^A-Za-z0-9_.-]", "", str(event.get("session_id") or ""))
    if not session:
        return None
    return os.path.join(tempfile.gettempdir(), "garrick-zone-guard", session)


def remembered(event):
    path = memory_file(event)
    try:
        with open(path) as f:
            return {line.strip() for line in f if line.strip()}
    except (OSError, TypeError):
        return set()


def remember(event, places):
    path = memory_file(event)
    if not path or not places:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        for p in places:
            f.write(p + "\n")


def outside(event):
    """(home names, [(place names, path)]) for every edit outside the home."""
    home_dir = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or ""
    if not home_dir:
        return None, []
    home_dir = os.path.abspath(home_dir)
    root = workspace_root(home_dir)
    if root is None:
        return None, []
    home = home_place(parts(root, home_dir))
    if not home:
        return home, []
    out = []
    for path in edits(event):
        names = parts(root, path)
        if names and not allowed(home, names):
            out.append((target_place(names), "/".join(names)))
    return home, out


def decide(event):
    """The hook's reply as a dict, or None to stay silent and let the edit run."""
    stage = event.get("hook_event_name")
    home, away = outside(event)
    if not away:
        return None
    keys = ["/".join(p) for p, _ in away]
    if stage == "PostToolUse":
        remember(event, keys)
        return None
    if stage != "PreToolUse":
        return None
    known = remembered(event)
    fresh = [(p, f) for p, f in away if "/".join(p) not in known]
    if not fresh:
        return None
    where = "; ".join("%s (%s)" % (say(p), f) for p, f in fresh)
    if event.get("tool_name") == "apply_patch":
        remember(event, ["/".join(p) for p, _ in fresh])
        reason = ("Zone guard: this session was opened in %s, and this edit is in %s. "
                  "Ask the user whether it belongs in this session before going on; "
                  "that place's own session is usually the right one. If they say yes, "
                  "make the same edit again and it will go through." % (say(home), where))
        decision = "deny"
    else:
        reason = ("Zone guard: this session was opened in %s, and this edit is in %s. "
                  "Allow it if it belongs here; otherwise do it in that place's own "
                  "session." % (say(home), where))
        decision = "ask"
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


def main():
    if os.environ.get("GARRICK_HEADLESS") == "1":
        return 0
    try:
        reply = decide(json.load(sys.stdin))
    except Exception:
        return 0
    if reply:
        print(json.dumps(reply, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
