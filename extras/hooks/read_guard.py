#!/usr/bin/env python3
"""The read guard: a check on what an assistant session reads, and on what a
mail or calendar connector hands back to it (#613, #614).

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
- PostToolUse, on a connector's tool (Gmail, Calendar, any pattern in the
  settings): each result is labelled by the addresses on it, matched against
  the Parties table as the intake skill matches a mail, and decided. A refused
  result is removed from what the assistant sees, and the output ends with the
  wall sentence, once and with no count. This works only where the harness lets
  a hook replace a tool's output, which Claude Code does and Codex does not.

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
EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
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
    """Whether `path` lies in `folder`, on a disk that ignores case without it (fix round N1)."""
    folder = os.path.realpath(folder)
    if zg.case_blind(zg.nearest_existing(folder)):
        folder, path = folder.casefold(), path.casefold()
    try:
        return os.path.commonpath([folder, path]) == folder
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


def text_file(path):
    """Whether a Knowledge file can be read as a page: a regular file under the size cap, with no NUL byte in it."""
    try:
        import recall
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > recall.MAX_FILE_BYTES:
            return False
        with open(path, "rb") as fh:
            return b"\0" not in fh.read(8192)
    except Exception:
        return False


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
            if os.path.isdir(path) or not os.path.exists(path):
                return {lib.KNOWLEDGE}, "ok"      # a folder, or nothing there: Knowledge's own, readable from any scope
            if not text_file(path):
                return {lib.UNZONED}, "ok"        # a file that cannot be read as text, or is over the size cap
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


def both(joined, searching):
    """[(path, searching)] for a path as written and as it really leads. A link in the workspace to a place outside it
    is judged by where it sits as well as where it leads, and the stricter verdict stands."""
    real, written = os.path.realpath(joined), os.path.abspath(joined)
    return [(real, searching)] + ([(written, searching)] if written != real else [])


BRACE_LIMIT = 64


def braces(pattern):
    """The patterns a brace group stands for, `{a,b}/x` as `a/x` and `b/x`, nested groups too. More than BRACE_LIMIT
    of them, or a group never closed, cuts the pattern at the first brace, so it is judged by what comes before."""
    open_at = pattern.find("{")
    if open_at < 0:
        return [pattern]
    depth, parts, start = 0, [], open_at + 1
    for i in range(open_at, len(pattern)):
        c = pattern[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                parts.append(pattern[start:i])
                head, tail = pattern[:open_at], pattern[i + 1:]
                out = []
                for part in parts:
                    out.extend(braces(head + part + tail))
                    if len(out) > BRACE_LIMIT:
                        return [pattern[:open_at] + "*"]
                return out
        elif c == "," and depth == 1:
            parts.append(pattern[start:i])
            start = i + 1
    return [pattern[:open_at] + "*"]


def glob_paths(cwd, given_base, pattern):
    """[(real path, searching)] for a glob pattern: each brace expansion judged by its own literal prefix, up to the
    first wildcard. A prefix that is empty is the folder the pattern is based in, searched as a span of it."""
    out = []
    for one in braces(pattern):
        cut = re.search(r"[*?\[{]", one)
        prefix = one[:cut.start()] if cut else one
        prefix = prefix if not cut else prefix.rsplit("/", 1)[0] if "/" in prefix else ""
        joined = os.path.join(cwd, given_base, prefix)
        out.extend(both(joined, bool(cut) or os.path.isdir(joined)))
    return out


def tool_paths(event, lib):
    """[(real path, searching)] the call names, and whether a part of it could not be read."""
    tool, given = event.get("tool_name"), event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    if tool == "Read":
        return both(os.path.join(cwd, os.path.expanduser(given.get("file_path") or "")), False), False
    if tool == "Grep":
        joined = os.path.join(cwd, os.path.expanduser(given.get("path") or ""))
        found = both(joined, os.path.isdir(joined))
        if isinstance(given.get("glob"), str) and given["glob"]:
            found += glob_paths(cwd, os.path.expanduser(given.get("path") or ""), given["glob"])
        return found, False
    if tool == "Glob":
        return glob_paths(cwd, os.path.expanduser(given.get("path") or ""), os.path.expanduser(given.get("pattern") or "")), False
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
            joined = os.path.join(cwd, os.path.expanduser(cand or "."))
            out.extend(both(joined, glob or os.path.isdir(joined)))
    return out, unread


def pre(event, lib, root, ctx, scope, folder):
    tool = event.get("tool_name")
    if tool not in READ_TOOLS and tool not in SHELL_TOOLS:
        return None
    paths, unread = tool_paths(event, lib)
    mode, cross = lib.read_guard_mode(root), lib.read_guard_cross(root)
    zone = scope["zone"] or scope["kind"]
    stop = own_folder(event, folder, tool, paths, zone, mode)
    if stop is not None:
        return stop or None
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


def own_folder(event, folder, tool, paths, zone, mode):
    """The guard's own folder holds the log and the scope records: no session reads it, wherever it sits. None when
    the call names nothing in it; else {} when it is let through (warn-only, a scheduled job), or the refusal."""
    hit = [p for p, _ in paths if inside(folder, p)]
    if not hit:
        return None
    log(folder, tool, DENY, zone, hit[0], "folder")
    if mode != "enforce" or os.environ.get("GARRICK_HEADLESS") == "1":
        return {}
    return deny_reply(WALL_REFUSAL, DENY)


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


# ------------------------------------------------------------------ connector results


def note_tool(folder, tool):
    """Remember the name of a connector tool the session used, and nothing else about the call."""
    path = os.path.join(folder, "tools-seen.json")
    try:
        with open(path, encoding="utf-8") as fh:
            seen = json.load(fh)
        seen = seen if isinstance(seen, dict) else {}
    except (OSError, ValueError):
        seen = {}
    today = time.strftime("%Y-%m-%d")
    if seen.get(tool) == today:
        return
    seen[tool] = today
    os.makedirs(folder, exist_ok=True)
    temporary = "%s.%d.tmp" % (path, os.getpid())
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(seen, fh, sort_keys=True)
    os.replace(temporary, path)


def blocks_of(response):
    """A tool's response as a list of content blocks, whatever shape it came in; None when it has none."""
    if isinstance(response, str):
        return [{"type": "text", "text": response}]
    if isinstance(response, dict):
        if isinstance(response.get("content"), list):
            return response["content"]
        return [{"type": "text", "text": json.dumps(response, ensure_ascii=False)}]
    return response if isinstance(response, list) else None


ID_KEYS = ("id", "threadId", "messageId", "eventId", "iCalUID")
TOKEN_KEY = re.compile(r"token|cursor|page", re.I)
NUMERIC = re.compile(r"\s*[-+]?[\d.,]+\s*")


def is_results(value):
    """A list of results: not empty, and every item an object with an id of its own. An empty list is never one."""
    return (isinstance(value, list) and bool(value) and all(isinstance(i, dict) for i in value)
            and all(any(isinstance(i.get(k), (str, int)) for k in ID_KEYS) for i in value))


def has_results(value):
    """Whether a results list sits anywhere inside `value`."""
    if is_results(value):
        return True
    if isinstance(value, dict):
        return any(has_results(v) for v in value.values())
    if isinstance(value, list):
        return any(has_results(v) for v in value)
    return False


class Filter:
    """Judges a parsed connector result, failing closed. Every item of every list of objects is judged by its own
    addresses. What is left outside the kept items (the scalar fields of a container) is judged by its own
    addresses too, and a field that holds an address no zone permits is dropped. An object with no list of
    results is one result, judged whole. When anything is removed, no count stays outside the kept items."""

    def __init__(self, lib, ctx, scope, suggest, strip):
        self.lib, self.ctx, self.scope, self.suggest, self.strip = lib, ctx, scope, suggest, strip
        self.removed = []

    def permitted(self, value):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return decide_result(self.lib, self.ctx, self.scope, self.suggest, text)

    def harmless(self, value):
        """A part with no address passes; one with addresses passes only when decide() permits them."""
        text = json.dumps(value, ensure_ascii=False)
        return not EMAIL.search(text) or self.permitted(text)

    def top(self, data):
        """The filtered tree, or None for a result removed whole."""
        if isinstance(data, list):
            return self.items(data, True)
        if is_results_free(data):
            if self.permitted(data):
                return data
            self.removed.append((result_id(data), ""))
            return None
        return self.container(data)

    def items(self, items, strict):
        kept = []
        for item in items:
            ok = self.permitted(item) if strict else self.harmless(item)
            if ok:
                kept.append(item)
            else:
                self.removed.append((result_id(item) if isinstance(item, dict) else item, ""))
        return kept

    def container(self, data):
        """A dict that holds lists of results. Each list is judged item by item. What is left over, taken as one
        more result, is judged by its own addresses: when they are not permitted, all of it goes."""
        leftover = {k: v for k, v in data.items() if not is_results(v) and not (isinstance(v, dict) and has_results(v))}
        gone = bool(leftover) and not self.harmless(leftover)
        if gone:
            self.removed.append(("fields", ""))
        new = {}
        for key, value in data.items():
            if is_results(value):
                new[key] = self.items(value, True)
            elif isinstance(value, dict) and has_results(value):
                new[key] = self.container(value)
            elif not gone:
                part = self.residue(key, value)
                if part is not DROP:
                    new[key] = part
        return new

    def residue(self, key, value):
        if isinstance(value, bool) or isinstance(value, (int, float)):
            return DROP if self.strip else value
        if isinstance(value, str):
            if self.strip and NUMERIC.fullmatch(value) and not TOKEN_KEY.search(key):
                return DROP
            if not self.harmless(value):
                self.removed.append((key, ""))
                return DROP
            return value
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                part = self.residue(k, v)
                if part is not DROP:
                    out[k] = part
            return out
        if isinstance(value, list):
            if not value:
                return value
            out = []
            for item in value:
                part = self.residue(key, item) if not isinstance(item, (dict, list)) else self.residue_item(key, item)
                if part is not DROP:
                    out.append(part)
            return out
        return value

    def residue_item(self, key, item):
        if not self.harmless(item):
            self.removed.append((key, ""))
            return DROP
        return self.residue(key, item)


DROP = object()


def is_results_free(data):
    """A dict with no list of results anywhere in it: one object, one result."""
    return isinstance(data, dict) and not has_results(data)


def filter_tree(lib, ctx, scope, suggest, data):
    """(tree or None, removed): the data with what no zone permits taken out; None when the whole result goes."""
    first = Filter(lib, ctx, scope, suggest, False)
    tree = first.top(data)
    if not first.removed:
        return data, []
    second = Filter(lib, ctx, scope, suggest, True)
    tree = second.top(data)
    return tree, second.removed


def result_id(item):
    for key in ("id", "threadId", "messageId", "eventId", "iCalUID"):
        if isinstance(item.get(key), (str, int)):
            return item[key]
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


def decide_result(lib, ctx, scope, suggest, text):
    addresses = EMAIL.findall(text)
    labels = lib.connector_labels(ctx, addresses, suggest) if addresses else None
    mine = {scope["zone"]} if scope["kind"] == "zone" and scope["zone"] else set()
    return lib.decide(mine, labels, "read", ctx) == "permit"


def load_suggest(root):
    import importlib.util
    path = os.path.join(root, "System", "skills", "intake", "intake.py")
    spec = importlib.util.spec_from_file_location("garrick_intake_for_read_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.suggest


def is_error(event, response):
    return bool(event.get("is_error") or event.get("error")
                or (isinstance(response, dict) and (response.get("isError") or response.get("is_error") or response.get("error"))))


def named_elsewhere(lib, ctx, scope, text):
    """Whether `text` holds a name the Parties or People table gives to another walled zone: the full name, or the
    first word of a party's name when it is four letters or more."""
    mine = {scope["zone"]} if scope["kind"] == "zone" and scope["zone"] else set()
    walled = ctx.get("zone_walled") or {}
    zones = {}
    tags = {}
    for tag, row in (ctx.get("parties") or {}).items():
        zone = (row.get("zone") or "").strip()
        tags[tag] = zone
        name = (row.get("party") or "").strip()
        if name:
            zones.setdefault(name.casefold(), set()).add(zone)
            first = re.split(r"[\s&,]+", name)[0]
            if len(first) >= 4:
                zones.setdefault(first.casefold(), set()).add(zone)
    for person in ctx.get("people") or []:
        name = (person.get("name") or "").strip()
        if name:
            zones.setdefault(name.casefold(), set()).add(tags.get(str(person.get("party") or "").strip("`").lower(), ""))
    low = text.casefold()
    for name, where in zones.items():
        if re.search(r"(?<!\w)%s(?!\w)" % re.escape(name), low) and any(z not in mine and walled.get(z, True) for z in where):
            return True
    return False


def judge_text(lib, ctx, scope, suggest, text, error):
    """(text kept or None, removed) for one piece of text from a connector."""
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, (dict, list)):
        # Not JSON. An error's text with no address passes unless it names another walled zone's party or person.
        if error and not EMAIL.search(text):
            if named_elsewhere(lib, ctx, scope, text):
                return None, [(text, "error")]
            return text, []
        if decide_result(lib, ctx, scope, suggest, text):
            return text, []
        return None, [(text, "unparsed")]
    if isinstance(data, list) and not all(isinstance(i, dict) for i in data):
        return None, [(text, "unparsed")]
    tree, gone = filter_tree(lib, ctx, scope, suggest, data)
    if not gone:
        return text, []
    if tree is None:
        return None, gone
    return json.dumps(tree, ensure_ascii=False), gone


def judge_block(lib, ctx, scope, suggest, block, error):
    """([blocks to show], removed) for one content block. A text block, and the text of a resource block, are
    judged; a block of any other type has no text to read and passes."""
    if not isinstance(block, dict):
        return [block], []
    kind = block.get("type", "text")
    if kind == "resource" and isinstance(block.get("resource"), dict):
        res = block["resource"]
        if isinstance(res.get("text"), str):
            text, gone = judge_text(lib, ctx, scope, suggest, res["text"], error)
            if not gone:
                return [block], []
            return ([] if text is None else [dict(block, resource=dict(res, text=text))]), gone
        if res.get("blob"):
            return [], [("resource", "unparsed")]       # bytes the filter cannot read
        return [block], []
    text = block.get("text") if kind == "text" else None
    if not isinstance(text, str):
        return [block], []
    text, gone = judge_text(lib, ctx, scope, suggest, text, error)
    if not gone:
        return [block], []
    return ([] if text is None else [dict(block, text=text)]), gone


def post(event, lib, root, ctx, scope, folder):
    tool = str(event.get("tool_name") or "")
    if not tool.startswith("mcp__"):
        return None
    note_tool(folder, tool)
    if not lib.tool_matches(lib.connector_patterns(root), tool) or scope["kind"] == "root":
        return None
    response = event.get("tool_response")
    if response is None:
        return None
    mode = lib.read_guard_mode(root)
    zone = scope["zone"] or scope["kind"]
    suggest = load_suggest(root)
    blocks = blocks_of(response)
    error = is_error(event, response)
    extra = response.get("structuredContent") if isinstance(response, dict) else None
    if blocks is None:
        removed, out = [("unparsed", "unparsed")], []
    else:
        removed, out = [], []
        for block in blocks:
            got, gone = judge_block(lib, ctx, scope, suggest, block, error)
            out.extend(got)
            removed.extend(gone)
        if extra is not None and isinstance(response.get("content"), list):
            text = extra if isinstance(extra, str) else json.dumps(extra, ensure_ascii=False)
            removed.extend(judge_block(lib, ctx, scope, suggest, {"type": "text", "text": text}, error)[1])
    if not removed:
        log(folder, tool, ALLOW, zone, tool)
        return None
    for what, kind in removed:
        log(folder, tool, DENY, zone, what, kind)
    if mode != "enforce" or os.environ.get("GARRICK_HEADLESS") == "1":
        return None
    out.append({"type": "text", "text": WALL_REFUSAL})
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedMCPToolOutput": out}}


# ------------------------------------------------------------------ the hook


def handle(event):
    stage = event.get("hook_event_name")
    if stage not in ("SessionStart", "PreToolUse", "PostToolUse"):
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
    if stage == "PostToolUse":
        # The tools seen are noted for every session, the root's too, so the check can name one on no list.
        return post(event, lib, root, lib.load_context(root), scope, folder)
    if scope["kind"] == "root":
        if event.get("tool_name") not in READ_TOOLS and event.get("tool_name") not in SHELL_TOOLS:
            return None
        paths, _ = tool_paths(event, lib)
        stop = own_folder(event, folder, event.get("tool_name"), paths, "root", lib.read_guard_mode(root))
        return stop or None
    return pre(event, lib, root, lib.load_context(root), scope, folder)


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
               [("SessionStart", ["startup"]), ("PreToolUse", list(READ_TOOLS) + ["Bash"]),
                ("PostToolUse", ["mcp__claude_ai_Gmail__search_threads"])]),
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
