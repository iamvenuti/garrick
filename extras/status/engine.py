#!/usr/bin/env python3
"""engine.py: one engine for the Ask box and the Telegram channel (#571).

    engine.run(ws, "telegram", "file the inbox", zone="Work", exchange={...})

A channel names its settings (channels.py): a tier, an effort and an autonomy. This file runs one request as those
settings say, and returns what the assistant said and the actions it held.

**Read.** The session has Garrick's read tools (search, read, places, thread_state, owed) and nothing else: it answers.

**Act.** The session has, besides, file tools and a fixed list of commands, in the zone the exchange is bound to:
the workspace's own scripts (intake.py, scaffold.py for a project, a thread, a park or a wake, check.py's quick
check, the todo reader) and `git add` and `git commit` in that zone's repository. There is **no open shell**: a
shell can send (`curl`, `gh`, `mail`) and would walk round `hold`, so every command is named. The servers the session
has are Garrick's two and no others (`--strict-mcp-config`): the send, share and delete tools of the owner's
connectors are not there, and neither is any tool Garrick does not know. In their place is `hold`, which queues the
action for the owner's yes (hold.py). A write outside the zone, a wiki or the workspace's Inbox is refused by the
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
import shutil
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
# The commands an Act session may run, by script and subcommand. Everything the shell offers beyond them is absent.
# Left out on purpose: intake.py learn and scaffold.py party and zone (they write the wall's own tables), rename,
# move, delete and undo (not what a message from a phone should do unattended), check.py allow, page_action.py (its
# `settings` and `run` verbs would let a session raise its own level), and every command that reaches the network.
INTAKE = ("list", "parse", "file-conversation", "file-reading", "file-to-project", "extract-attachment", "move-to-zone",
          "skip", "file-note", "notes", "process-notes")
SCAFFOLD = ("project", "thread", "checkpoint")
TODO = ("digest",)
JOB = "ask"                 # the ledger's name for an interactive call: both channels count against Ask's own caps
TURN_TIMEOUT = 240
MOST_REQUEST = 4000


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


def act_commands(ws: Path, zone: str) -> List[str]:
    """The Bash patterns an Act session is allowed: named commands only, with their absolute paths."""
    ws = Path(ws).resolve()
    py = "python3"
    out = []
    for sub in INTAKE:
        out.append("Bash(%s %s %s:*)" % (py, ws / "System" / "skills" / "intake" / "intake.py", sub))
    for sub in SCAFFOLD:
        out.append("Bash(%s %s %s:*)" % (py, ws / "System" / "tools" / "scaffold.py", sub))
    out.append("Bash(%s %s --quick:*)" % (py, ws / "System" / "tools" / "check.py"))
    for sub in TODO:
        out.append("Bash(%s %s %s:*)" % (py, ws / "System" / "skills" / "todo" / "todo.py", sub))
    repo = ws / "Zones" / zone
    for word in ("add", "commit", "status", "diff", "log"):
        out.append('Bash(git -C "%s" %s:*)' % (repo, word))
    return out


def allowed_tools(ws: Path, zone: str, level: str) -> List[str]:
    """Every tool the session is allowed, by name: nothing else is asked for. At Read, Garrick's read tools; at Act
    and Full, those, the file tools, the named commands and `hold`."""
    tools = tool_names(READ_SERVER, READ_TOOLS)
    if level in ("act", "full"):
        tools += list(FILE_TOOLS) + act_commands(ws, zone) + tool_names(HOLD_SERVER, ("hold",))
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
        out["hooks"] = {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [
            {"type": "command", "command": "%s %s" % (sys.executable or "python3", HERE / "engine_guard.py")}]}]}
    return out


def build(ws: Path, channel: str, zone: str, planned: dict, level: str, exchange: dict, folder: Path, cap: dict) -> Tuple[List[str], dict]:
    """The command and its environment for one turn. Pure: it starts nothing."""
    a = agent_lib()
    claude = shutil.which("claude") or "claude"
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
    cmd += ["--allowedTools"] + allowed_tools(ws, zone, level)      # last: the flag takes every word after it
    env = {"GARRICK_ENGINE_WS": str(Path(ws).resolve()), "GARRICK_ENGINE_ZONE": zone, "GARRICK_ENGINE_CHANNEL": channel,
           "GARRICK_ENGINE_EXCHANGE": exchange["id"], "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "GARRICK_BACKGROUND": "1"}
    env.pop("GARRICK_HEADLESS", None)
    return cmd, env


def default_runner(cmd, tier, cwd, env):
    return agent_lib().run_prepared(cmd, tier, cwd=cwd, job=JOB, timeout=TURN_TIMEOUT, env=env)


def folder_for(exchange_id: str) -> Path:
    safe = "".join(c for c in exchange_id if c.isalnum() or c in "-_")[:64] or "x"
    return hold.jobs_dir() / "engine" / safe


def run(ws: Path, channel: str, text: str, zone: str, exchange: Optional[dict] = None, runner: Optional[Callable] = None,
        cap: Optional[dict] = None, fresh: bool = False, context: str = "") -> dict:
    """One request in one zone. `exchange` is the caller's record: {"id", "session"}; the reply says the session to
    keep. Returns {"ok", "say", "held": [entries queued this turn], "session", "tier", "effort", "autonomy", "set",
    "limited", "deep", "usage", "cost"}. Never raises for the assistant's failure: `ok` is False with a sentence."""
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
    level = now["autonomy"]
    saved = "<saved-state>\n%s\n</saved-state>\n" % context[:4000].replace("</saved-state>", "") if context else ""
    prompt = "<channel>%s</channel>\n<zone>%s</zone>\n<autonomy>%s</autonomy>\n%s<request>\n%s\n</request>" % (
        channel, zone, level, saved, planned["text"][:MOST_REQUEST])
    planned["prompt"] = prompt
    if channels.assistant() != "claude":
        return {"ok": False, "say": "This channel runs on Claude for now; the assistant chosen cannot be used for it.", "held": [],
                "session": exchange.get("session"), "autonomy": level, "limited": now["limited"]}
    known = {e["id"] for e in hold.pending()}                  # what was waiting already is not this turn's
    cmd, env = build(ws, channel, zone, planned, level, exchange, folder_for(exchange["id"]), cap)
    code, got = (runner or default_runner)(cmd, planned["tier"], folder_for(exchange["id"]), env)
    held = [e for e in hold.pending(channel=channel) if e.get("exchange") == exchange["id"] and e["id"] not in known]
    if got.get("refused"):
        return {"ok": False, "say": "Not run: %s." % str(got["refused"]).rstrip("."), "held": held, "session": exchange.get("session"),
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
    through one assistant call that is allowed that tool and no other."""
    if "write" in (e.get("request") or {}):
        return hold.write_shared(ws, e)
    tool = str((e.get("request") or {}).get("tool") or "")
    args = (e.get("request") or {}).get("args") or {}
    if not tool:
        return False, "the action names no tool"
    claude = shutil.which("claude") or "claude"
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
