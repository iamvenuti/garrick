#!/usr/bin/env python3
"""The read guard: a check on what an assistant session reads (#613).

The zone guard stops writes outside the session's project. This one covers
reads. It is a hook for Claude Code and Codex, reading the event on stdin, and
it asks `garrick_lib.decide()` of the workspace it runs in, the same question
every other enforcement point asks.

- SessionStart records the session's scope: the zone, project and parties of
  the folder it was opened in. The record lives in the read guard's folder
  (garrick_lib.read_guard_dir(), next to the jobs' folder), outside every
  workspace, keyed by the session id. A session with no record is judged by its
  working folder, as the zone guard judges writes.
- PreToolUse, on Read, Grep, Glob and Bash: each file the call names is
  labelled by where it is (a zone's folder, a Meetings page's `zone:`, a
  Knowledge page, System) and decided. `deny` is the rules' wall sentence and
  names nothing. A raw Grep or Glob over a wiki, or over a folder that holds
  several zones, is refused with a pointer to `recall.py search`. A Bash command
  gets the same decision for the plain path words in it; a command that cannot
  be read that way is allowed and logged as unread, because a shell command
  cannot be parsed completely.

A session opened at the workspace root or in System/ keeps full read. Nothing
is refused unless System/garrick-settings.json says `"read-guard": "enforce"`:
by default the guard decides and logs, and lets every call through. The log
holds the time, the tool, the decision, the scope's zone and a hash of the
path: never a path, a party, a title or a count of what was held back. Any
error lets the call through and logs that it did; a broken guard must not stop
work. A scheduled job (GARRICK_HEADLESS=1) is logged and never refused.

    python3 read_guard.py --check

says whether the guard is registered, and changes nothing.
"""
import hashlib
import json
import os
import re
import shlex
import sys
import time
import types

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import zone_guard as zg  # noqa: E402

# The rules' wall sentence, word for word. Nothing else is said across a wall.
WALL_REFUSAL = ("A wall holds some material back from this project, so I have not used it. "
                "Nothing was written.")
SEARCH_POINTER = ("To search the wikis, use recall.py search in System/tools: it keeps to what this project may read.")
ASK_AGAIN = " Ask the user whether to read it; once they agree, read it again."

READ_TOOLS = ("Read", "Grep", "Glob")
SHELL_TOOLS = ("Bash", "shell", "exec_command", "local_shell")
AGENTS_FILES = ("agents.md", "agents.local.md")
LOG_BYTES = 1_000_000
PRUNE_DAYS = 30

ALLOW, CONFIRM, DENY = "allow", "confirm", "deny"
RANK = {ALLOW: 0, CONFIRM: 1, DENY: 2}


# ------------------------------------------------------------------ the guard's own folder


def digest(text):
    return hashlib.sha1(str(text).encode("utf-8", "replace")).hexdigest()[:12]


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "", str(name or ""))


def log(folder, tool, decision, zone, what, kind=""):
    """One line: when, the tool, the decision, the scope's zone, a hash. Never the path, a party, a title or a count."""
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "read-guard.log")
        try:
            if os.path.getsize(path) > LOG_BYTES:
                os.replace(path, path + ".1")
        except OSError:
            pass
        line = {"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": str(tool)[:80], "decision": decision,
                "zone": zone or "", "id": digest(what)}
        if kind:
            line["kind"] = kind
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


def inside(folder, path):
    try:
        return os.path.commonpath([os.path.realpath(folder), path]) == os.path.realpath(folder)
    except ValueError:
        return False


# ------------------------------------------------------------------ the session's scope


def home_of(event):
    """Where the session was opened: $CLAUDE_PROJECT_DIR when Claude Code sets it, else the event's folder."""
    given = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd")
    return os.path.realpath(given) if given else None


def derive(lib, root, home):
    """The scope of a session opened in `home`: {kind, zone, project, wiki, parties}. `root` is the workspace root,
    which with System/ keeps full read. A zone, or a project in it, holds that zone. A wiki holds its own wiki only.
    Any other folder holds no zone: it reads what no zone owns."""
    blind = zg.case_blind(root)
    names = zg.parts(root, home, blind)
    if names is None:
        return None
    if not names or names[0] == "System":
        return {"kind": "root", "zone": "", "project": "", "wiki": "", "parties": []}
    if names[0] == "Zones" and len(names) >= 2:
        zone = lib.zone_of(root, "Zones/%s/x" % names[1]) or names[1]
        project = names[2] if len(names) >= 3 else ""
        parties = []
        if project:
            try:
                fm = lib.parse_frontmatter(os.path.join(root, "Zones", names[1], project, project + ".md"))
                value = fm.get("party")
                parties = [str(p) for p in (value if isinstance(value, list) else [value]) if p]
            except Exception:
                parties = []
        return {"kind": "zone", "zone": zone, "project": project, "wiki": "", "parties": parties}
    if names[0] == "Wikis" and len(names) >= 2:
        return {"kind": "wiki", "zone": "", "project": "", "wiki": names[1], "parties": []}
    return {"kind": "other", "zone": "", "project": "", "wiki": "", "parties": []}


def record_path(folder, event):
    session = safe(event.get("session_id"))
    return os.path.join(folder, "sessions", session + ".json") if session else None


def record_scope(lib, root, event, folder):
    home = home_of(event)
    path = record_path(folder, event)
    if not home or not path:
        return
    scope = derive(lib, root, home)
    if scope is None:
        return
    scope["root"] = root
    scope["time"] = int(time.time())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(scope, fh)
    prune(os.path.dirname(path))


def prune(folder):
    cutoff = time.time() - PRUNE_DAYS * 86400
    try:
        for name in os.listdir(folder):
            full = os.path.join(folder, name)
            if os.path.getmtime(full) < cutoff:
                os.remove(full)
    except OSError:
        pass


def session_scope(lib, root, event, folder):
    """The recorded scope of the session when the workspace matches, else the one its folder gives."""
    path = record_path(folder, event)
    if path:
        try:
            with open(path, encoding="utf-8") as fh:
                got = json.load(fh)
            if isinstance(got, dict) and got.get("root") == root and got.get("kind") in ("root", "zone", "wiki", "other"):
                return got
        except (OSError, ValueError):
            pass
    home = home_of(event)
    return derive(lib, root, home) if home else None


def open_workspace(event):
    """(root, lib) for the workspace the session's folder is in, or (None, None)."""
    home = home_of(event)
    if not home:
        return None, None
    root = zg.workspace_root(home)
    if root is None:
        return None, None
    tools = os.path.join(root, "System", "tools")
    if tools not in sys.path:
        sys.path.insert(1, tools)
    import garrick_lib
    return root, garrick_lib


# ------------------------------------------------------------------ what a path is


def label_of(lib, root, ctx, names, path, searching):
    """(zones the path is labelled with or None, kind), kind one of ok, span, wall-less. `span` is a search over
    several zones' material: refused whole, whatever each file holds."""
    if not names:
        return (None, "span") if searching else ({lib.KNOWLEDGE}, "ok")
    top = names[0]
    if top == "Zones":
        if len(names) == 1:
            return (None, "span") if searching else ({lib.KNOWLEDGE}, "ok")
        if len(names) == 3 and names[2].casefold() in AGENTS_FILES:
            return {lib.KNOWLEDGE}, "ok"
        zone = lib.zone_of(root, "Zones/%s/x" % names[1]) or names[1]
        return {zone}, "ok"
    if top == "Wikis":
        if len(names) == 1:
            return (None, "span") if searching else ({lib.KNOWLEDGE}, "ok")
        wiki, rel = names[1], "/".join(names)
        if len(names) == 3 and names[2].casefold() in AGENTS_FILES:
            return {lib.KNOWLEDGE}, "ok"
        if wiki == "Knowledge":
            if len(names) == 2:
                return {lib.KNOWLEDGE}, "ok"
            try:
                import recall
                zone = recall.Refresher.page_zone(types.SimpleNamespace(root=__import__("pathlib").Path(root)), rel,
                                                  __import__("pathlib").Path(path))
            except Exception:
                zone = lib.UNZONED
            return ({zone} if zone else {lib.KNOWLEDGE}), "ok"
        if wiki == "Meetings":
            if searching and (len(names) == 2 or os.path.isdir(path) or re.search(r"[*?\[]", path)):
                return None, "span"
            if len(names) == 2:
                return {lib.KNOWLEDGE}, "ok"
            return {lib.zone_of(root, rel) or lib.UNZONED}, "ok"
        return None, "ok"      # another wiki: no label, so no permit
    return {lib.KNOWLEDGE}, "ok"   # System/, the root's own files, anything no zone owns


def judge(lib, root, ctx, scope, path, searching):
    """(ALLOW | CONFIRM | DENY, kind) for one path. kind is span, wall or unlabelled for a refusal, else ok."""
    if scope["kind"] == "root":
        return ALLOW, "ok"
    names = zg.parts(root, path, zg.case_blind(root))
    if names is None:
        return ALLOW, "outside"
    if scope["kind"] == "wiki" and names[:2] == ["Wikis", scope["wiki"]]:
        return ALLOW, "ok"
    labels, kind = label_of(lib, root, ctx, names, path, searching)
    if kind == "span":
        return DENY, "span"
    mine = {scope["zone"]} if scope["kind"] == "zone" and scope["zone"] else set()
    verdict = lib.decide(mine, labels, "read", ctx)
    if verdict == "permit":
        return ALLOW, "ok"
    if verdict == "confirm":
        return CONFIRM, "wall"
    known = set((ctx.get("zone_walled") or {})) - {lib.UNZONED}
    real = labels is not None and (labels & known) - mine
    return DENY, ("wall" if real else "unlabelled")


# ------------------------------------------------------------------ the tool calls


def tool_paths(event, lib):
    """[(real path, searching)] the call names, and whether a part of it could not be read."""
    tool, given = event.get("tool_name"), event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    if tool == "Read":
        return [(os.path.realpath(os.path.join(cwd, os.path.expanduser(given.get("file_path") or ""))), False)], False
    if tool == "Grep":
        base = os.path.realpath(os.path.join(cwd, os.path.expanduser(given.get("path") or "")))
        return [(base, os.path.isdir(base))], False
    if tool == "Glob":
        pattern = os.path.expanduser(given.get("pattern") or "")
        given_base = os.path.expanduser(given.get("path") or "")
        cut = re.search(r"[*?\[{]", pattern)
        prefix = pattern[:cut.start()] if cut else pattern
        prefix = prefix if not cut else prefix.rsplit("/", 1)[0] if "/" in prefix else ""
        base = os.path.realpath(os.path.join(cwd, given_base, prefix))
        return [(base, bool(cut) or os.path.isdir(base))], False
    if tool in SHELL_TOOLS:
        command = given.get("command") or given.get("cmd") or ""
        if isinstance(command, list):
            command = " ".join(str(c) for c in command)
        return shell_paths(str(command), cwd)
    return [], False


def shell_paths(command, cwd):
    """The plain path words of a shell command, and whether anything in it could not be read. Best effort: a word
    with a variable in it, a substitution or an unbalanced quote makes the command partly unread."""
    unread = "$(" in command or "`" in command
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:
        return [], True
    out = []
    for word in words:
        for cand in {word, word.split("=", 1)[-1]}:
            if not cand or re.fullmatch(r"[|&;<>()]+", cand):
                continue
            if "$" in cand:
                unread = True
                continue
            if "/" not in cand and not cand.startswith("~") and cand not in ("Zones", "Wikis"):
                continue
            cut = re.search(r"[*?\[{]", cand)
            glob = bool(cut)
            if cut:
                cand = cand[:cut.start()].rsplit("/", 1)[0] if "/" in cand[:cut.start()] else ""
            real = os.path.realpath(os.path.join(cwd, os.path.expanduser(cand or ".")))
            out.append((real, glob or os.path.isdir(real)))
    return out, unread


def pre(event, lib, root, ctx, scope, folder):
    tool = event.get("tool_name")
    if tool not in READ_TOOLS and tool not in SHELL_TOOLS:
        return None
    paths, unread = tool_paths(event, lib)
    mode, cross = lib.read_guard_mode(root), lib.read_guard_cross(root)
    zone = scope["zone"] or scope["kind"]
    # The guard's own folder, where a setting put it inside a workspace, is never read by a session, in any mode.
    if folder_in(root, folder):
        for path, _ in paths:
            if inside(folder, path):
                log(folder, tool, DENY, zone, path, "log")
                return deny_reply(WALL_REFUSAL, DENY)
    worst, kind, what, named = ALLOW, "ok", "", False
    for path, searching in paths:
        verdict, why = judge(lib, root, ctx, scope, path, searching)
        if why == "outside":
            continue
        if not named or RANK[verdict] > RANK[worst]:
            worst, kind, what, named = verdict, why, path, True
    if worst == DENY and kind == "wall" and cross == "ask":
        worst = CONFIRM
    if worst == ALLOW and unread:
        kind = "unread"
    if not named and not unread:
        return None                    # nothing in the workspace was named
    log(folder, tool, worst, zone, what or tool, kind if kind != "ok" else "")
    if mode != "enforce" or os.environ.get("GARRICK_HEADLESS") == "1" or worst == ALLOW:
        return None
    reason = WALL_REFUSAL + (" " + SEARCH_POINTER if kind == "span" else "")
    if worst == CONFIRM:
        if codex(event):
            key = digest(what)
            if key in asked(event, folder):
                return None
            remember(event, folder, key)
            return deny_reply(reason + ASK_AGAIN, DENY)
        return deny_reply(reason, "ask")
    return deny_reply(reason, DENY)


def codex(event):
    """A harness that cannot ask: Codex. Claude Code sets CLAUDE_PROJECT_DIR and names its own read tools."""
    return not os.environ.get("CLAUDE_PROJECT_DIR") and event.get("tool_name") not in READ_TOOLS


def asked(event, folder):
    path = os.path.join(folder, "asked", safe(event.get("session_id")) or "none")
    try:
        with open(path, encoding="utf-8") as fh:
            return {l.strip() for l in fh if l.strip()}
    except OSError:
        return set()


def remember(event, folder, key):
    path = os.path.join(folder, "asked", safe(event.get("session_id")) or "none")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(key + "\n")


def deny_reply(reason, decision):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


# ------------------------------------------------------------------ the hook


def handle(event):
    stage = event.get("hook_event_name")
    if stage not in ("SessionStart", "PreToolUse"):
        return None
    root, lib = open_workspace(event)
    if root is None:
        return None
    folder = str(lib.read_guard_dir())
    if stage == "SessionStart":
        record_scope(lib, root, event, folder)
        return None
    scope = session_scope(lib, root, event, folder)
    if scope is None:
        return None
    if scope["kind"] == "root" and not folder_in(root, folder):
        return None
    return pre(event, lib, root, lib.load_context(root), scope, folder)


def folder_in(root, folder):
    """Whether the guard's folder sits inside the workspace, which only a setting can do."""
    return inside(root, os.path.realpath(folder))


def main():
    if sys.argv[1:] == ["--check"]:
        return check()
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        reply = handle(event)
    except Exception:
        # A broken guard must not stop work: the call goes through, and the log says so.
        try:
            import garrick_lib
            log(str(garrick_lib.read_guard_dir()), event.get("tool_name") or event.get("hook_event_name"), "error", "", "error")
        except Exception:
            pass
        return 0
    if reply:
        print(json.dumps(reply, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ --check


def registered(path, wants):
    """Problems with the read guard's hooks in the settings file at `path`. `wants` is [(event, [tools])]."""
    shown = path.replace(os.path.expanduser("~"), "~", 1)
    try:
        with open(path) as fh:
            hooks = json.load(fh).get("hooks") or {}
    except FileNotFoundError:
        return ["%s does not exist" % shown]
    except (OSError, ValueError, AttributeError):
        return ["%s is not readable JSON with a hooks block" % shown]
    problems = []
    for event, tools in wants:
        entries = hooks.get(event) or []
        covered = set()
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks") or []:
                command = hook.get("command", "") if isinstance(hook, dict) else ""
                try:
                    words = shlex.split(command)
                except ValueError:
                    words = command.split()
                scripts = [os.path.expanduser(os.path.expandvars(w)) for w in words if w.endswith("read_guard.py")]
                if scripts and all(os.path.isfile(s) for s in scripts):
                    covered |= {t for t in tools if zg.matches(str(entry.get("matcher") or ""), t)}
        missed = [t for t in tools if t not in covered]
        if missed:
            problems.append("%s: no read guard on %s for %s" % (shown, event, ", ".join(missed) or "any tool"))
    return problems


def check_lines(home=None):
    """(lines, ok) for the read guard: one line for each assistant found. The zone guard's --check prints these
    beside its own; they never change its exit code, since the read guard is optional."""
    home = home or os.path.expanduser("~")
    places = (("Claude Code", os.path.join(home, ".claude"), "settings.json",
               [("SessionStart", ["startup"]), ("PreToolUse", list(READ_TOOLS) + ["Bash"])]),
              ("Codex", os.path.join(home, ".codex"), "hooks.json",
               [("SessionStart", ["startup"]), ("PreToolUse", ["Bash"])]))
    lines, ok = [], True
    for name, folder, settings, wants in places:
        if not os.path.isdir(folder):
            continue
        problems = registered(os.path.join(folder, settings), wants)
        if problems:
            ok = False
            lines.append("%s: the read guard is not registered. %s." % (name, "; ".join(problems)))
        else:
            lines.append("%s: the read guard is registered on %s." % (name, " and ".join(e for e, _ in wants)))
    return lines, ok


def check():
    lines, ok = check_lines()
    for line in lines or ["Neither Claude Code nor Codex is set up for this user, so the read guard runs nowhere."]:
        print(line)
    return 0 if ok and lines else 1


if __name__ == "__main__":
    sys.exit(main())
