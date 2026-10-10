#!/usr/bin/env python3
"""The zone guard: a check before the assistant writes outside the project its
session was opened in.

A session opened in a thread belongs to that thread's project. An edit there,
or to a file lying loose in the project's zone folder (a zone's Todo.md), goes
ahead. An edit anywhere else in the workspace (another project, another zone,
a wiki, System/) is stopped once, with a sentence naming both places. A
session opened at the workspace root, in System/, or outside any workspace,
is never stopped: System/ describes the whole workspace, so its sessions work
across it, and neither is an edit outside the workspace: the scratchpad, /tmp,
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
otherwise the event's cwd. Paths are judged where they really lead, through
any link, and on a disk that ignores case, as a Mac's does, without it. A scheduled job (GARRICK_HEADLESS=1) has nobody to
ask, so the guard stands aside for it. It reads files only, and never calls a
model. Any error lets the edit through: a broken guard must not stop work.

    python3 zone_guard.py --check

says whether the guard is registered where it must run, and changes nothing:
Claude Code on PreToolUse and PostToolUse for the four editing tools, in
~/.claude/settings.json, and Codex on PreToolUse for apply_patch, in
~/.codex/hooks.json, each with a command whose zone_guard.py exists. An
assistant with no folder in your home (~/.claude, ~/.codex) is skipped. Exit
0 when every assistant found has it, 1 when one does not or none was found.
Whether Codex trusts the hook (its /hooks) is not written where this can
read it.
"""
import json
import os
import re
import shlex
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


def case_blind(root):
    """Whether the disk under `root` ignores case, as a Mac's does unless it
    was formatted otherwise: there `/users/...` and `zones/work` name the same
    folders as `/Users/...` and `Zones/Work`."""
    flipped = root.swapcase()
    if flipped == root:
        return sys.platform == "darwin"
    try:
        return os.path.samefile(root, flipped)
    except OSError:
        return False


def parts(root, path, blind=False):
    """`path` below `root` as a list of names, or None when it is not below.
    Both are real paths. On a disk that ignores case (`blind`), the names are
    matched without it and given as the folders spell them."""
    rel = os.path.relpath(path, root)
    if rel == ".":
        return []
    if rel != ".." and not rel.startswith(".." + os.sep):
        names = rel.split(os.sep)
    elif blind:
        top, below = root.split(os.sep), path.split(os.sep)
        if [n.casefold() for n in below[:len(top)]] != [n.casefold() for n in top]:
            return None
        names = below[len(top):]
        if not names:
            return []
    else:
        return None
    return true_case(root, names) if blind else names


def true_case(root, names):
    """`names` below `root` as the folders there spell them. A name that is
    not there yet, as for a new file, stays as given."""
    out, here = [], root
    for i, name in enumerate(names):
        try:
            entries = os.listdir(here)
        except OSError:
            return out + names[i:]
        if name not in entries:
            name = next((e for e in entries if e.casefold() == name.casefold()), name)
        out.append(name)
        here = os.path.join(here, name)
    return out


def home_place(names):
    """The folder a session opened at `names` (relative to the root) may write
    in, as relative names. [] means anywhere: the root itself."""
    if not names or names[0] == "System":
        return []              # the root, or System/, which governs every zone
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
    if names[0] == "Wikis":
        return names[:2]
    return names[:1]


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
    # Real paths: a link inside the project to a folder in another zone is
    # judged by where the file lands, not by the link's place.
    return [os.path.realpath(os.path.join(cwd, os.path.expanduser(p))) for p in found if p]


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
    home_dir = os.path.realpath(home_dir)
    root = workspace_root(home_dir)
    if root is None:
        return None, []
    blind = case_blind(root)
    home = home_place(parts(root, home_dir, blind))
    if not home:
        return home, []
    out = []
    for path in edits(event):
        names = parts(root, path, blind)
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


# --------------------------------------------------------------------------- --check


def registered(path, event, tools):
    """Problems with the guard's hook for `event` in the settings file at
    `path`: [] when an entry whose matcher covers every one of `tools` runs a
    zone_guard.py that exists."""
    shown = path.replace(os.path.expanduser("~"), "~", 1)
    try:
        with open(path) as f:
            hooks = json.load(f).get("hooks") or {}
        entries = hooks.get(event) or []
    except FileNotFoundError:
        return ["%s does not exist" % shown]
    except (OSError, ValueError, AttributeError):
        return ["%s is not readable JSON with a hooks block" % shown]
    best = None
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        for hook in entry.get("hooks") or []:
            scripts = guard_paths(hook.get("command", "") if isinstance(hook, dict) else "")
            if not scripts:
                continue
            missed = [t for t in tools if not matches(str(entry.get("matcher") or ""), t)]
            gone = [p for p in scripts if not os.path.isfile(p)]
            if not missed and not gone:
                return []
            problem = []
            if missed:
                problem.append("its %s hook misses %s" % (event, ", ".join(missed)))
            if gone:
                problem.append("its %s hook runs %s, which does not exist" % (event, gone[0]))
            best = best or ["%s: %s" % (shown, "; ".join(problem))]
    return best or ["%s runs no zone guard on %s for %s" % (shown, event, "|".join(tools))]


def guard_paths(command):
    """The zone_guard.py files a hook's command names, with ~ and $HOME
    expanded."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    return [os.path.expanduser(os.path.expandvars(w)) for w in words if w.endswith("zone_guard.py")]


def matches(matcher, tool):
    """Whether a hook matcher picks `tool`, as both assistants read one: empty
    or `*` for every tool, otherwise a pattern such as `Edit|Write`."""
    if matcher in ("", "*"):
        return True
    try:
        return re.fullmatch(matcher, tool) is not None
    except re.error:
        return tool in matcher.split("|")


def check():
    """Print, for each assistant, whether the guard runs there. 0 when it runs
    for every assistant found, 1 otherwise."""
    home = os.path.expanduser("~")
    places = (("Claude Code", os.path.join(home, ".claude"), "settings.json",
               (("PreToolUse", CLAUDE_TOOLS), ("PostToolUse", CLAUDE_TOOLS))),
              ("Codex", os.path.join(home, ".codex"), "hooks.json", (("PreToolUse", ("apply_patch",)),)))
    found, ok = 0, True
    for name, folder, settings, events in places:
        if not os.path.isdir(folder):
            print("%s: not on this machine (no ~/%s), skipped." % (name, os.path.basename(folder)))
            continue
        found += 1
        problems = []
        for event, tools in events:
            problems += registered(os.path.join(folder, settings), event, tools)
        if problems:
            ok = False
            print("%s: the zone guard is not registered. %s." % (name, "; ".join(problems)))
        else:
            print("%s: the zone guard is registered on %s." % (name, " and ".join(e for e, _ in events)))
    if not found:
        print("Neither Claude Code nor Codex is set up for this user, so the guard runs nowhere.")
    return 0 if ok and found else 1


def main():
    if sys.argv[1:] == ["--check"]:
        return check()
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
