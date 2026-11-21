#!/usr/bin/env python3
"""engine.py: one engine for the Ask box and the Telegram channel (#571).

    engine.run(ws, "telegram", "file the inbox", zone="Work", exchange={...})

A channel names its settings (channels.py): a tier, an effort and an autonomy. This file runs one request as those
settings say, and returns what the assistant said and the actions it held.

**Read.** The session has Garrick's read tools (search, read, places, thread_state, owed) and nothing else: it answers.

**Act.** The session has, besides, file tools and a fixed list of commands, in the zone the exchange is bound to.
Every command is one call of one wrapper (engine_cmd.py), which checks each argument against the zone and then runs
the real command: the workspace's own scripts (intake.py without `list`, `process-notes` and `learn`; scaffold.py for
a project, a thread and a checkpoint; the quick check; the todo reader) and `git add`, `commit`, `status`, `diff` and
`log` in that zone's repository, with no flag that skips the hook or writes elsewhere. There is **no open shell**: a
shell can send (`curl`, `gh`, `mail`) and would walk round `hold`, so every command is named, and the pre-tool hook
refuses a command that is anything but one call of the wrapper. The servers the session has are Garrick's two and no
others (`--strict-mcp-config`): the send, share and delete tools of the owner's connectors are not there, and neither
is any tool Garrick does not know. In their place is `hold`, which queues the action for the owner's yes (hold.py). A
write outside the zone, a wiki's `wiki/` folder or the workspace's Inbox, or into a `.git` folder, is refused by the
engine's guard (engine_guard.py), a pre-tool hook bound to the zone; the zones' commit check runs as for any commit.

**Full** (Ask only) is Act, with `hold` answered for the owner without asking: the sends run. Garrick's default is
Act, and an assistant that fails the capability check (channels.capability) runs at Read.

**A session continues.** The first turn of an exchange starts a session; the next is `--resume` of it, so a follow-up
does not repeat the discovery. The caller keeps the exchange record (`session`, started time, turns); a session older
than the caller's limit is replaced, and a `deep:` request is one request on a bigger tier, with the settings
unchanged.

Every call goes through agent.run_prepared(): the same caps and ledger as every call, per request, whichever channel
sent it. Nothing here sends anything, and there is no tool that does. Text the session reads is untrusted.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import channels  # noqa: E402
import hold  # noqa: E402

BRIEF = HERE / "engine-brief.md"
READ_SERVER = "garrick"
HOLD_SERVER = "garrick_hold"
READ_TOOLS = ("search", "read", "places", "thread_state", "owed")
FILE_TOOLS = ("Read", "Grep", "Glob", "Edit", "Write")
# The commands an Act session may run, by script and subcommand, each through engine_cmd.py (which binds every
# argument to the exchange's zone). Left out on purpose: intake.py list (it returns every zone's inbox), process-notes
# (the job's own pass), learn, and scaffold.py party and zone (they write the wall's own tables), rename, move, delete
# and undo (not what a message from a phone should do unattended), check.py allow, page_action.py (its `settings` and
# `run` verbs would let a session raise its own level), and every command that reaches the network.
INTAKE = ("parse", "file-conversation", "file-reading", "file-to-project", "extract-attachment", "move-to-zone",
          "skip", "file-note", "notes")
SCAFFOLD = ("project", "thread", "checkpoint")
TODO = ("digest",)
GIT = ("add", "commit", "status", "diff", "log")
JOB = "ask"                 # the ledger's name for an interactive call: both channels count against Ask's own caps
TURN_TIMEOUT = 240
MOST_REQUEST = 4000
NOT_STARTED = (126, 127)       # the exit codes of a command that was found but not runnable, or not found
NOT_STARTED_SAY = "The background assistant could not be started, so this goes to a visible one."


def agent_lib():
    """agent.py of the jobs extra: beside this file's folder in a workspace (System/jobs/), or in a Garrick clone."""
    src = HERE.parent / "jobs" / "agent.py"
    if not src.is_file():
        src = HERE.parent.parent / "extras" / "jobs" / "agent.py"
    key = "garrick_engine_agent_%x" % abs(hash(str(src)))
    if key in sys.modules and Path(sys.modules[key].__file__).is_file():
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, str(src))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def tool_names(server: str, names) -> List[str]:
    return ["mcp__%s__%s" % (server, n) for n in names]


def act_commands(ws: Path, zone: str, commit: bool = True) -> List[str]:
    """The Bash patterns an Act session is allowed: one wrapper, one pattern per tool and subcommand. The zone is not
    in a pattern: the wrapper takes it from the exchange's own environment and refuses any other."""
    import engine_cmd
    out = []
    for tool, subs in (("intake", INTAKE), ("scaffold", SCAFFOLD), ("todo", TODO), ("git", GIT)):
        for sub in subs:
            if not commit and tool == "git" and sub in ("add", "commit"):
                continue                # a bounded run edits; the commit is code's, through the hook
            out.append("Bash(%s:*)" % engine_cmd.prefix(tool, sub))
    out.append("Bash(%s --quick)" % engine_cmd.prefix("check"))
    return out


def allowed_tools(ws: Path, zone: str, level: str, commit: bool = True) -> List[str]:
    """Every tool the session is allowed, by name: nothing else is asked for. At Read, Garrick's read tools; at Act
    and Full, those, the file tools, the named commands and `hold`."""
    tools = tool_names(READ_SERVER, READ_TOOLS)
    if level in ("act", "full"):
        tools += list(FILE_TOOLS) + act_commands(ws, zone, commit) + tool_names(HOLD_SERVER, ("hold",))
    return tools


def mcp_config(ws: Path, zone: str, channel: str, exchange: str, state: Path) -> dict:
    py = sys.executable or "python3"
    env = {"GARRICK_ENGINE_CHANNEL": channel, "GARRICK_ENGINE_ZONE": zone, "GARRICK_ENGINE_EXCHANGE": exchange,
           "GARRICK_JOBS_DIR": str(hold.jobs_dir())}
    return {"mcpServers": {
        READ_SERVER: {"command": py, "args": [str(HERE / "ask_tools.py"), "serve", "--workspace", str(ws), "--state", str(state),
                                              "--zone", zone]},
        HOLD_SERVER: {"command": py, "args": [str(HERE / "hold_tools.py")], "env": env}}}


def session_settings(ws: Path, level: str) -> dict:
    """The settings file the session loads: Garrick's deny profile, and at Act the guard on every write."""
    a = agent_lib()
    try:
        base = json.loads(Path(a.PROFILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        base = {}
    out = {"permissions": {"deny": list((base.get("permissions") or {}).get("deny") or [])}}
    if level in ("act", "full"):
        import engine_guard
        out["hooks"] = {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash", "hooks": [
            {"type": "command", "command": engine_guard.hook_command()}]}]}
    return out


def build(ws: Path, channel: str, zone: str, planned: dict, level: str, exchange: dict, folder: Path, cap: dict,
          commit: bool = True, only: Optional[List[str]] = None) -> Tuple[List[str], dict]:
    """The command and its environment for one turn. Pure: it starts nothing."""
    a = agent_lib()
    claude = channels.claude_path() or "claude"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "settings.json").write_text(json.dumps(session_settings(ws, level)), encoding="utf-8")
    (folder / "mcp.json").write_text(json.dumps(mcp_config(ws, zone, channel, exchange["id"], folder / "read")), encoding="utf-8")
    (folder / "read").mkdir(exist_ok=True)
    cmd = [claude, "-p", planned["prompt"], "--model", planned["tier"], "--output-format", "json",
           "--permission-mode", "default", "--settings", str(folder / "settings.json"), "--setting-sources", "",
           "--strict-mcp-config", "--mcp-config", str(folder / "mcp.json"),
           "--tools", ",".join(FILE_TOOLS + ("Bash",)) if level in ("act", "full") else "",
           "--system-prompt", BRIEF.read_text(encoding="utf-8")]
    if cap.get("effort_flag"):
        cmd += ["--effort", planned["effort"]]
    budget = a._number("GARRICK_MAX_CALL_USD", a.DEFAULT_MAX_CALL_USD)
    if budget > 0:
        cmd += ["--max-budget-usd", "%g" % budget]
    if exchange.get("session") and not planned.get("fresh"):
        cmd += ["--resume", str(exchange["session"])]
    cmd += ["--allowedTools"] + allowed_tools(ws, zone, level, commit)      # last: the flag takes every word after it
    env = {"GARRICK_ENGINE_WS": str(Path(ws).resolve()), "GARRICK_ENGINE_ZONE": zone, "GARRICK_ENGINE_CHANNEL": channel,
           "GARRICK_ENGINE_EXCHANGE": exchange["id"], "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "GARRICK_BACKGROUND": "1"}
    env.pop("GARRICK_HEADLESS", None)
    if only is not None:
        env["GARRICK_ENGINE_ONLY"] = json.dumps([str(x) for x in only])     # set by run_bounded alone: the guard reads it
    return cmd, env


def default_runner(cmd, tier, cwd, env):
    try:
        return agent_lib().run_prepared(cmd, tier, cwd=cwd, job=JOB, timeout=TURN_TIMEOUT, env=env)
    except FileNotFoundError:
        return 127, {}


def folder_for(exchange_id: str) -> Path:
    safe = "".join(c for c in exchange_id if c.isalnum() or c in "-_")[:64] or "x"
    return hold.jobs_dir() / "engine" / safe


def run(ws: Path, channel: str, text: str, zone: str, exchange: Optional[dict] = None, runner: Optional[Callable] = None,
        cap: Optional[dict] = None, fresh: bool = False, context: str = "", level: Optional[str] = None, commit: bool = True,
        only: Optional[List[str]] = None) -> dict:
    """One request in one zone. `exchange` is the caller's record: {"id", "session"}; the reply says the session to
    keep. Returns {"ok", "say", "held": [entries queued this turn], "session", "tier", "effort", "autonomy", "set",
    "limited", "deep", "usage", "cost"}. Never raises for the assistant's failure: `ok` is False with a sentence.
    `level` names the level for this call alone (run_bounded asks for Act); `commit=False` leaves `git add` and `git
    commit` out of the session's commands."""
    ws = Path(ws).resolve()
    if channel not in channels.CHANNELS:
        raise ValueError("no channel called %r" % (channel,))
    exchange = exchange if isinstance(exchange, dict) and exchange.get("id") else dict(exchange or {}, id="%s-%s" % (channel, zone))
    cap = cap if cap is not None else channels.capability(ws)
    now = channels.effective(ws, channel, cap)
    planned = channels.plan(now, text)
    planned.update(prompt="", fresh=fresh)
    if not planned["text"]:
        return {"ok": False, "say": "There was nothing in the request.", "held": [], "session": exchange.get("session")}
    level = level if level in channels.LEVELS else now["autonomy"]
    saved = "<saved-state>\n%s\n</saved-state>\n" % context[:4000].replace("</saved-state>", "") if context else ""
    prompt = "<channel>%s</channel>\n<zone>%s</zone>\n<autonomy>%s</autonomy>\n%s<request>\n%s\n</request>" % (
        channel, zone, level, saved, planned["text"][:MOST_REQUEST])
    planned["prompt"] = prompt
    if channels.assistant() != "claude":
        return {"ok": False, "say": "This channel runs on Claude for now; the assistant chosen cannot be used for it.", "held": [],
                "session": exchange.get("session"), "autonomy": level, "limited": now["limited"]}
    known = {e["id"] for e in hold.pending()}                  # what was waiting already is not this turn's
    cmd, env = build(ws, channel, zone, planned, level, exchange, folder_for(exchange["id"]), cap, commit, only)
    code, got = (runner or default_runner)(cmd, planned["tier"], folder_for(exchange["id"]), env)
    held = [e for e in hold.pending(channel=channel) if e.get("exchange") == exchange["id"] and e["id"] not in known]
    if got.get("refused"):
        return {"ok": False, "say": "Not run: %s." % str(got["refused"]).rstrip("."), "held": held, "session": exchange.get("session"),
                "tier": planned["tier"], "autonomy": level}
    if code in NOT_STARTED:       # `env` or the shell could not start the command (#628): a plain sentence, never a bare exit code
        return {"ok": False, "unavailable": True, "say": NOT_STARTED_SAY, "held": [], "session": exchange.get("session"),
                "tier": planned["tier"], "autonomy": level}
    ok = code == 0
    say = (got.get("text") or "").strip() if ok else "That did not work (exit %s). Nothing more was done." % code
    if level == "full" and held:
        # Full: the sends run without asking. Only Ask offers it, and only an owner who set it.
        for e in list(held):
            hold.run(e["id"], ws, lambda w, rec: execute_held(w, rec, runner))
        held = []
    return {"ok": ok, "say": say, "held": held, "session": got.get("session_id") or exchange.get("session"),
            "tier": planned["tier"], "effort": planned["effort"], "autonomy": level, "set": now["set"],
            "limited": now["limited"], "why": now["why"], "deep": planned["deep"], "usage": got.get("usage") or {},
            "cost": got.get("cost_usd")}


def execute_held(ws: Path, e: dict, runner: Optional[Callable] = None) -> Tuple[bool, str]:
    """Do one held action, after the owner's yes. A write under a shared folder is code's; a connector tool runs
    through one assistant call that is allowed that tool and no other: the one name, checked again here against the
    shape of a connector tool and the kinds a hold may be.

    Not narrowed to one server: the owner's connectors are the assistant account's own, with no config file Garrick
    could name in `--strict-mcp-config` without guessing, so the call loads them as the owner's settings do, and
    `--allowedTools` is the one tool."""
    if "write" in (e.get("request") or {}):
        return hold.write_shared(ws, e)
    tool = str((e.get("request") or {}).get("tool") or "")
    args = (e.get("request") or {}).get("args") or {}
    if not tool:
        return False, "the action names no tool"
    if not hold.TOOL_RE.match(tool) or hold.kind_of({"tool": tool}) not in hold.HELD_KINDS:
        return False, "the action names a tool that is not a connector tool that sends, shares or deletes"
    claude = channels.claude_path() or "claude"
    prompt = ("The owner has approved this one action. Do exactly it, with the tool %s and these arguments, and "
              "nothing else; then say in one sentence what happened.\n<arguments>\n%s\n</arguments>" % (tool, json.dumps(args)[:8000]))
    cmd = [claude, "-p", prompt, "--model", "haiku", "--output-format", "json", "--permission-mode", "default",
           "--setting-sources", "user", "--allowedTools", tool]
    workdir = Path(tempfile.mkdtemp(prefix="garrick-held-"))
    try:
        code, got = (runner or default_runner)(cmd, "haiku", workdir, {})
    finally:
        shutil.rmtree(str(workdir), ignore_errors=True)
    if code != 0 or got.get("refused"):
        return False, "the assistant could not do it (%s)" % (got.get("refused") or "exit %s" % code)
    return True, (got.get("text") or "Done.").strip()[:300]


# ---- one bounded edit, or one commit, for the Context queue (#592) --------------------------------------------------

TRAILER = "Garrick-Bounded"
BOUNDED_MESSAGE = 72            # characters of a commit's first line
MOST_FILES = 8                  # files one bounded edit may name
MOST_COMMIT = 50                # files one commit-only call may name: the page's COMMIT_MOST
NO_WIKI_REPO = "no repository for this wiki"
MOST_DIRTY = 400                # files the repository may already hold changed, for the check that nothing else moved
_page_action = None


def _pa():
    """page_action.py, beside this file: its git runner, wall-hook check and zone lock are the page's own, so a bounded
    commit is made the way every other commit of the page is."""
    global _page_action
    if _page_action is None:
        spec = importlib.util.spec_from_file_location("garrick_engine_page_action", str(HERE / "page_action.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _page_action = mod
    return _page_action


def _fail(say: str, **more) -> dict:
    return dict({"ok": False, "say": say, "commit": "", "files": [], "repo": ""}, **more)


def _folder(ws: Path, zone) -> Tuple[Optional[Path], Optional[Path], str]:
    """(the zone's or the wiki's folder, the repository that holds it, "") or (None, None, why). The name must be exactly
    one folder of Zones/ or Wikis/. A zone is its own repository. A wiki is `Wikis/<name>/.git` when it has one, else
    the one repository of `Wikis/` that a default install makes; with neither, `why` is NO_WIKI_REPO."""
    if not isinstance(zone, str) or not zone or zone.startswith((".", "_")) or "/" in zone or "\\" in zone or "\0" in zone:
        return None, None, "That is not a zone or a wiki."
    found = [p for p in (ws / "Zones" / zone, ws / "Wikis" / zone) if p.is_dir() and not p.is_symlink()]
    if len(found) != 1:
        return None, None, "That is not one zone or one wiki."
    folder = found[0].resolve()
    if (folder / ".git").is_dir():
        return folder, folder, ""
    if folder.parent.name == "Wikis":
        shared = ws / "Wikis"
        if (shared / ".git").is_dir() and not shared.is_symlink():
            return folder, shared.resolve(), ""
        return None, None, NO_WIKI_REPO
    return None, None, "%s has no repository of its own." % zone


def _inside(ws: Path, folder: Path, files, most: int = MOST_FILES, gone_ok: bool = False) -> Tuple[Optional[List[str]], str]:
    """The files as paths from the workspace, each a real file inside `folder`, or the reason one is not. With `gone_ok` (a
    commit of what is already changed) a file that no longer exists is let through, when its place resolves inside the
    folder: the caller then checks that git reports it changed."""
    if not isinstance(files, (list, tuple)) or not files or len(files) > most:
        return None, "Name the file to change."
    out = []
    for rel in files:
        if not isinstance(rel, str) or not rel or rel.startswith(("/", "~")) or "\\" in rel or "\0" in rel or ".." in rel.split("/"):
            return None, "That is not a path in this workspace."
        full = (ws / rel).resolve()
        if folder not in full.parents or not (full.is_file() or (gone_ok and not os.path.lexists(str(ws / rel)))):
            return None, "That file is not inside %s." % folder.name
        parts = full.relative_to(folder).parts
        if any(x in (".git", ".shared") or x in (".gitattributes", ".gitmodules") for x in parts) or (folder.parent.name == "Wikis" and parts[0] == "raw"):
            return None, "That file is not one to change here."
        rel_in = str(full.relative_to(ws.resolve()))
        if rel_in not in out:
            out.append(rel_in)
    return out, ""


class _Snapshot(dict):
    """{path: bytes or None} as `_dirty` returns it, with `stats`: what each path's file looked like when its bytes were
    read, so a later snapshot can keep the bytes of a file that has not been touched since."""
    stats: Dict[str, tuple]
    read_at: Dict[str, int]


RACY_NS = 2_000_000_000                 # a file touched within this long of being read may be rewritten unseen (as git treats it)


def _now_ns() -> int:
    return time.time_ns()


def _stamp(path: Path):
    """What identifies one state of a file: size, change time, modification time and inode. None when it is no file."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_size, st.st_ctime_ns, st.st_mtime_ns, st.st_ino) if stat.S_ISREG(st.st_mode) else None


def _dirty(git, repo: Path, known: Optional[Dict[str, Optional[bytes]]] = None) -> Optional[Dict[str, Optional[bytes]]]:
    """{path from the repository: its bytes now (None when gone)} for every path git reports changed or new, or None
    when there are too many to keep. Each file's bytes are read once: a file that `known` (an earlier snapshot of this
    repository) holds, and whose stamp has not changed since, keeps the bytes it was read with, but only when its change and
    modification times were at least two seconds older than that read: a file touched closer to the read may be rewritten
    within one clock tick without the stamp moving (racy-clean, as git guards), so it is read again."""
    code, said = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if code != 0:
        return None
    paths = []
    parts = said.split("\0")
    i = 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) > 3:
            paths.append(e[3:])
            if e[0] in "RC":
                i += 1                  # a rename names its source next
    if len(paths) > MOST_DIRTY:
        return None
    out = _Snapshot()
    out.stats = {}
    out.read_at = {}
    seen = getattr(known, "stats", {})
    seen_at = getattr(known, "read_at", {})
    for rel in paths:
        at = _now_ns()
        stamp = _stamp(repo / rel)
        if stamp is None:
            out[rel] = None
        elif (rel in seen and seen[rel] == stamp and rel in known and rel in seen_at
              and stamp[1] <= seen_at[rel] - RACY_NS and stamp[2] <= seen_at[rel] - RACY_NS):
            out[rel], out.stats[rel], out.read_at[rel] = known[rel], stamp, seen_at[rel]
        else:
            try:
                out[rel] = (repo / rel).read_bytes()
                out.stats[rel], out.read_at[rel] = stamp, at
            except OSError:
                out[rel] = None
    return out


def _moved(before: Dict[str, Optional[bytes]], after: Dict[str, Optional[bytes]]) -> List[str]:
    """The paths whose state differs between two snapshots of what git reports changed."""
    return sorted(p for p in set(before) | set(after) if (p in before) != (p in after) or before.get(p) != after.get(p))


def _put_back(git, repo: Path, before: Dict[str, Optional[bytes]], after: Dict[str, Optional[bytes]], named) -> List[str]:
    """After a failed run: the named files are as they were (a tracked one is restored from HEAD, a new one is removed).
    Nothing else is touched: a new file, a path that was already changed before the run and moved during it, or a tracked
    file that was clean is left as it is, because the run did not name it and may not be the one who changed it (the
    guard keeps the run itself to the named files). Returns those paths."""
    left = []
    for rel in _moved(before, after):
        tracked = git(repo, "ls-files", "--error-unmatch", "--", rel)[0] == 0
        if rel in named:
            if rel in before:
                continue                # a named file that was changed before the run is never put back from here
            if tracked:
                git(repo, "checkout", "-q", "HEAD", "--", rel)
            else:
                try:
                    (repo / rel).unlink()
                except OSError:
                    pass
        else:
            left.append(rel)
    return left


def _others(ws: Path, skip: Path) -> Dict[str, Dict[str, Tuple[int, int]]]:
    """{repository: {changed path: (size, mtime)}} for every other repository under Zones/ and Wikis/ that a run could
    reach, apart from `skip`: the check that a bounded run wrote nowhere else."""
    repos = []
    for top in ("Zones", "Wikis"):
        base = ws / top
        if not base.is_dir():
            continue
        if top == "Wikis" and (base / ".git").is_dir():
            repos.append(base)
        for p in sorted(base.iterdir()):
            if p.is_dir() and not p.is_symlink() and (p / ".git").exists():
                repos.append(p)
    out = {}
    pa = _pa()
    for repo in repos:
        if repo.resolve() == skip.resolve():
            continue
        code, said = pa.git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
        state = {}
        parts = said.split("\0") if code == 0 else []
        i = 0
        while i < len(parts):
            e = parts[i]
            i += 1
            if len(e) > 3:
                try:
                    st = (repo / e[3:]).stat()
                    state[e] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    state[e] = (-1, 0)
                if e[0] in "RC":
                    i += 1
        out[str(repo)] = state
    return out


def _head(git, repo: Path) -> str:
    code, said = git(repo, "rev-parse", "HEAD")
    return said.strip() if code == 0 else ""


def _staged(git, repo: Path) -> set:
    code, said = git(repo, "diff", "--cached", "--name-only", "-z")
    return {x for x in said.split("\0") if x} if code == 0 else set()


def _message(ws: Path, folder: Path, repo: Path, files: List[str], request: str, given: str, runner, cap) -> str:
    """The commit's first line: the caller's, or one the assistant writes from the diff (a commit with no request), or a
    plain one from the file's name when the assistant cannot."""
    line = " ".join((given or "").split())
    if not line and not request:
        code, diff = _pa().git(repo, "diff", "HEAD", "--stat", "--", *[str(Path(ws, f).resolve().relative_to(repo)) for f in files])
        if code == 0 and diff.strip():
            got = run(ws, "ask", "Write one plain line, under 70 characters, that says what this change does, for a commit "
                      "message. Say the line and nothing else.\n\n" + diff[:3000], folder.name, {"id": "bounded-message"},
                      runner, cap, level="read")
            if got.get("ok"):
                line = " ".join(str(got.get("say") or "").strip().splitlines()[:1])
    if not line:
        line = "%s: %s" % (folder.name, " ".join(request.split())[:50] if request else "update %s" % Path(files[0]).stem)
    return line[:BOUNDED_MESSAGE].rstrip()


def _left_say(say: str, left) -> str:
    """The failure's sentence, and when a file the run did not name changed, that it was left as it is."""
    return "%s A file the assistant was not given also changed; it was left as it is." % say.rstrip(".") + "." if left else say


def run_bounded(ws, zone, files, request, message="", runner=None, cap=None) -> dict:
    """One bounded edit or commit: only `files` (workspace-relative paths, all inside `zone`'s folder, or one wiki's
    folder when zone names a wiki), at Act, no send, share or delete, committed in that repository through its own
    hook (never --no-verify). Returns {"ok": bool, "say": one plain sentence, "commit": sha or "", "files": [...],
    "repo": workspace-relative path of the zone or wiki}. A refused commit leaves no edit (the files are restored). With
    the engine unavailable (Ask off, a capability check failed, not Claude, a wiki with no repository) returns
    {"ok": False, "unavailable": True, "say": ...} and touches nothing.

    Every path is checked before anything runs; the session cannot commit (no `git add`, no `git commit`) and its write
    guard is bound to exactly these files, so a write anywhere else is refused as it is made. The one commit is made here,
    through the repository's hook, with a trailer that names it as this call's. After the run only the given files may
    have changed, in this repository and in every other under Zones/ and Wikis/: anything else fails the run. Only the
    named files and paths the run created are put back; a file the run did not name is never reverted or deleted. A
    file that already held changes that are not committed is refused, so no one's own edit is committed under the
    assistant's name."""
    ws = Path(ws).resolve()
    request = " ".join(str(request or "").split())[:MOST_REQUEST]
    unavailable = {"ok": False, "unavailable": True, "say": "The background assistant is not available, so this goes to a visible one.",
                   "commit": "", "files": [], "repo": ""}
    folder, repo, why = _folder(ws, zone)
    if folder is None:
        return unavailable if why == NO_WIKI_REPO else _fail(why)
    rels, why = _inside(ws, folder, files, MOST_FILES if request else MOST_COMMIT, gone_ok=not request)
    if rels is None:
        return _fail(why)
    cap = cap if cap is not None else channels.capability(ws)
    now = channels.effective(ws, "ask", cap)
    if request and (channels.assistant() != "claude" or not cap.get("ok") or now["autonomy"] == "read"
                    or (runner is None and not channels.claude_path())):
        return unavailable
    pa = _pa()
    repo_rel = str(folder.relative_to(ws))
    inner = [str((ws / r).resolve().relative_to(repo)) for r in rels]
    try:
        with pa.zone_lock(repo):
            before = _dirty(pa.git, repo)
            if before is None:
                return _fail("%s holds too many unsaved changes to check." % repo.name)
            for r, i in zip(rels, inner):
                if not os.path.lexists(str(ws / r)) and i not in before:
                    return _fail("That file is not inside %s." % folder.name)
            if any(i in before for i in inner) and request:
                return _fail("That file has changes that are not saved yet, so nothing was changed.")
            head = _head(pa.git, repo)
            if not request and not any(i in before for i in inner):
                return _fail("There is nothing to commit in that file.")
            staged = _staged(pa.git, repo)
            if request:
                text = ("%s\nChange only these files, in %s: %s. Do not commit. Do not send, share or delete anything." % (
                    request, folder.name, ", ".join(rels)))
                elsewhere = _others(ws, repo)
                got = run(ws, "ask", text, folder.name, {"id": "bounded-%s" % secrets.token_hex(4)}, runner, cap, level="act",
                          commit=False, only=rels)
                after = _dirty(pa.git, repo, before)
                if after is None:
                    after = {}
                for e in got.get("held") or []:
                    hold.cancel(e["id"])
                stray = [p for p in _moved(before, after) if p not in inner]
                far = _others(ws, repo) != elsewhere
                if got.get("unavailable") and not got.get("ok"):        # the assistant could not be started: nothing was edited
                    _put_back(pa.git, repo, before, after, inner)
                    return dict(unavailable, say=str(got.get("say") or unavailable["say"]))
                if got.get("held") or not got.get("ok") or _head(pa.git, repo) != head:
                    left = _put_back(pa.git, repo, before, after, inner)
                    if got.get("held"):
                        return _fail(_left_say("The assistant wanted to send or delete something, which this does not allow. Nothing was kept.", left or far))
                    if _head(pa.git, repo) != head:
                        return _fail("The assistant made a commit of its own, so the change needs a look.")
                    return _fail(_left_say(str(got.get("say") or "The assistant could not make the change.").strip()[:200], left or far))
                if stray or far:
                    left = _put_back(pa.git, repo, before, after, inner)
                    if left or far:
                        return _fail("The assistant changed a file it was not given, so nothing was kept. "
                                     "The file it was given was put back; the other was left as it is.")
                    return _fail("The assistant changed more than the file, so everything was put back.")
                if not any(i in _moved(before, after) for i in inner):
                    return _fail("The assistant made no change.")
            line = _message(ws, folder, repo, rels, request, message, runner, cap)
            trailer = "%s: %s" % (TRAILER, secrets.token_hex(4))
            problem = pa.commit_refusal(repo)
            code, said = (1, "%s, so nothing was committed" % problem) if problem else pa.git(repo, "add", "--", *inner)
            if code == 0:
                code, said = pa.git(repo, "commit", "-q", "-m", "%s\n\n%s" % (line, trailer), "--", *inner, timeout=pa.COMMIT_TIMEOUT)
            if code != 0:
                after = _dirty(pa.git, repo, after if request else before) or {}
                fresh = [i for i in inner if i not in staged]               # what was staged before is still staged
                if fresh:
                    pa.git(repo, "reset", "-q", "--", *fresh)
                if request:
                    _put_back(pa.git, repo, before, after, inner)
                why = said if code is None else ((said or "git refused").strip().splitlines() or ["git refused"])[-1]
                return _fail("The commit was refused, so no change was kept: %s" % why[:160])
            return {"ok": True, "say": "Made the change and committed it.", "commit": _head(pa.git, repo), "files": rels, "repo": repo_rel,
                    "trailer": trailer}
    except pa.Refused as e:
        return _fail(str(e))


def _trailer_of(message: str) -> bool:
    """Whether the message's last paragraph is Garrick's trailer line, and no other text: a trailer is the last
    paragraph of a message, so a line of that shape anywhere else is the author's own words."""
    paragraphs = [p for p in re.split(r"\n[ \t]*\n", message.strip("\n")) if p.strip()]
    if len(paragraphs) < 2:
        return False
    return bool(re.fullmatch(r"%s: [0-9a-f]{8}" % TRAILER, paragraphs[-1].strip()))


def undo_bounded(ws, repo, commit, path=None) -> dict:
    """Revert `commit` only, only if it was made by run_bounded (its message ends with the trailer
    `Garrick-Bounded: <id>`) and no later commit in the repository touched its files; else {"ok": False, "say": ...}
    and nothing changes. `repo` is the zone's or the wiki's folder. With `path` (from the workspace), the commit must
    also include that file. Nothing may be staged: the revert is committed with the reverted files only. The revert goes
    through the hook."""
    ws = Path(ws).resolve()
    if not isinstance(repo, str) or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        return {"ok": False, "say": "That is not a change to undo."}
    parts = repo.split("/")
    if len(parts) != 2 or parts[0] not in ("Zones", "Wikis"):
        return {"ok": False, "say": "That is not a zone or a wiki."}
    folder, git_repo, why = _folder(ws, parts[1])
    if folder is None or folder.parent.name != parts[0]:
        return {"ok": False, "say": why if folder is None and why != NO_WIKI_REPO else "That is not a zone or a wiki."}
    pa = _pa()
    try:
        with pa.zone_lock(git_repo):
            code, body = pa.git(git_repo, "log", "-1", "--format=%H%x00%B", commit)
            full, _, message = body.partition("\0") if code == 0 else ("", "", "")
            full = full.strip()
            if not full or not _trailer_of(message):
                return {"ok": False, "say": "That change was not made here, so it is not undone from here."}
            if pa.git(git_repo, "merge-base", "--is-ancestor", full, "HEAD")[0] != 0:
                return {"ok": False, "say": "That change is no longer part of this history."}
            code, names = pa.git(git_repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", full)
            files = [n for n in names.splitlines() if n]
            if code != 0 or not files:
                return {"ok": False, "say": "Garrick could not read what that change touched."}
            if path is not None:
                try:
                    own = str((ws / str(path)).resolve().relative_to(git_repo))
                except ValueError:
                    own = None
                if own not in files:
                    return {"ok": False, "say": "That change is not one of this page, so it is not undone from here."}
            code, later = pa.git(git_repo, "log", "--format=%H", "%s..HEAD" % full, "--", *files)
            if code != 0 or later.strip():
                return {"ok": False, "say": "The file changed again after that, so it is not undone. You can look at it first.", "later": True}
            code, dirty = pa.git(git_repo, "status", "--porcelain", "--", *files)
            if code != 0 or dirty.strip():
                return {"ok": False, "say": "The file has changes that are not saved, so it is not undone. You can look at it first.", "later": True}
            if pa.git(git_repo, "diff", "--cached", "--quiet")[0] != 0:
                return {"ok": False, "say": "Something else is staged in this repository, so nothing was undone. You can look at it first.", "later": True}
            problem = pa.commit_refusal(git_repo)
            if problem:
                return {"ok": False, "say": "%s, so nothing was undone." % problem}
            lines = message.splitlines()
            code, said = pa.git(git_repo, "revert", "--no-commit", full)
            if code == 0:
                code, said = pa.git(git_repo, "commit", "-q", "-m", "Undo: %s\n\nGarrick-Undo: %s" % (
                    (lines[0] if lines else "a change")[:60], full[:12]), "--", *files, timeout=pa.COMMIT_TIMEOUT)
            if code != 0:
                pa.git(git_repo, "revert", "--quit")
                pa.git(git_repo, "reset", "-q", "HEAD", "--", *files)
                pa.git(git_repo, "checkout", "-q", "HEAD", "--", *files)
                why = said if code is None else ((said or "git refused").strip().splitlines() or ["git refused"])[-1]
                return {"ok": False, "say": "The undo was refused, so nothing changed: %s" % why[:160]}
            return {"ok": True, "say": "Undone.", "commit": _head(pa.git, git_repo), "files": files, "repo": repo}
    except pa.Refused as e:
        return {"ok": False, "say": str(e)}
