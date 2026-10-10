"""cmuxlib.py: the cmux plumbing desk and the status page share.

Run the cmux CLI, list the live agent sessions, read whether each one is
mid-turn, and place a folder in the workspace. Nothing here knows about any
project or party; the layout it assumes is Garrick's: Zones/<Zone>/<Project>,
with Wikis/ and System/ as neutral ground. Standard library only.

The status page needs one call, which never raises and never waits long:

    sessions_by_folder(workspace)  ->  {folder: "idle" | "working"}

cmux's control socket accepts only processes cmux started, unless it is in
password mode. A process outside cmux (the status page's app, a scheduled job)
then needs the password, which goes in the environment as cmux's own
CMUX_SOCKET_PASSWORD, never on a command line. It is read from that variable,
or else from a file only you can read: GARRICK_CMUX_PASSWORD_FILE, the
`socket_password_file` desk's config names, or cmux-socket.password in the
jobs folder.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True

AGENTS = ("claude", "codex")          # the two assistants desk opens, wraps and resumes
NEUTRAL_TOPS = ("Wikis", "System")
APP_ID = "com.cmuxterm.app"
APP_BINARIES = ("/Applications/cmux.app/Contents/Resources/bin/cmux",
                "~/Applications/cmux.app/Contents/Resources/bin/cmux")
STATUS_TIMEOUT = 2                    # seconds: the page waits no longer than this
TAIL = 256 * 1024                     # the end of a transcript is enough to say idle or working
# The system records that close a Claude Code turn. A run with no terminal
# writes only stop_hook_summary; a tab writes it and then turn_duration.
CLAUDE_TURN_ENDS = ("turn_duration", "stop_hook_summary", "local_command")
SHELLS = ("bash", "csh", "dash", "fish", "ksh", "nu", "sh", "tcsh", "zsh")

PASSWORD_FILE: Optional[Path] = None  # set from desk's config; the environment wins


class CmuxError(Exception):
    """A cmux call failed, with a readable message."""


# --------------------------------------------------------------------------- where things are

def jobs_dir() -> Path:
    """The jobs extra's folder (extras/jobs/agent.py): logs, snapshots, the password file."""
    set_to = os.environ.get("GARRICK_JOBS_DIR")
    if set_to:
        return Path(set_to).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "garrick-jobs"
    return Path.home() / ".local" / "state" / "garrick-jobs"


def binary() -> Optional[str]:
    """The cmux CLI, or None. GARRICK_CMUX names it; otherwise PATH, then the
    app bundle, since the status app and launchd start with a bare PATH."""
    named = os.environ.get("GARRICK_CMUX")
    if named:
        p = Path(named).expanduser()
        return str(p) if p.is_file() and os.access(str(p), os.X_OK) else None
    found = shutil.which("cmux")
    if found:
        return found
    for candidate in APP_BINARIES:
        p = Path(candidate).expanduser()
        if p.is_file() and os.access(str(p), os.X_OK):
            return str(p)
    return None


def installed() -> bool:
    return binary() is not None


def app() -> Optional[Path]:
    """The cmux.app the CLI belongs to, for bringing it forward or starting it;
    None when the CLI is not inside one."""
    exe = binary()
    if exe is None:
        return None
    for parent in Path(exe).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def password_file() -> Path:
    set_to = os.environ.get("GARRICK_CMUX_PASSWORD_FILE")
    if set_to:
        return Path(set_to).expanduser()
    return PASSWORD_FILE or jobs_dir() / "cmux-socket.password"


def socket_env() -> Dict[str, str]:
    """The environment for a cmux call: the password, where there is one.

    The file is refused when anyone but you can read it, since whoever reads it
    can type into every terminal cmux has open."""
    env = dict(os.environ, CMUX_QUIET="1")
    if env.get("CMUX_SOCKET_PASSWORD"):
        return env
    f = password_file()
    try:
        mode = f.stat().st_mode
    except OSError:
        return env
    if mode & 0o077:
        raise CmuxError("%s can be read by others; run chmod 600 on it" % f)
    try:
        env["CMUX_SOCKET_PASSWORD"] = f.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise CmuxError("could not read %s: %s" % (f, e.strerror or e))
    return env


# --------------------------------------------------------------------------- cmux

def cmux(*args, parse: bool = False, check: bool = True, timeout: float = 30, password: bool = True):
    """Run a cmux command. Parsed JSON with parse=True, else its output.
    password=False for a command that reads cmux's records on disk: it sends
    the password when there is a good one, and goes without otherwise."""
    exe = binary()
    if exe is None:
        raise CmuxError("cmux is not installed here")
    try:
        env = socket_env()
    except CmuxError:
        if password:
            raise
        env = dict(os.environ, CMUX_QUIET="1")
    try:
        p = subprocess.run([exe] + [str(a) for a in args], capture_output=True, text=True,
                           env=env, timeout=timeout, stdin=subprocess.DEVNULL)
    except OSError as e:
        raise CmuxError("cmux could not be run: %s" % (e.strerror or e))
    except subprocess.TimeoutExpired:
        raise CmuxError("cmux %s took longer than %ss" % (args[0], timeout))
    if check and p.returncode != 0:
        msg = (p.stderr or p.stdout).strip().splitlines()
        raise CmuxError("cmux %s failed: %s" % (args[0], msg[-1] if msg else "no output"))
    return json_tail(p.stdout) if parse else p.stdout


def json_tail(text: str):
    """JSON from cmux's output, past any notice lines in front of it."""
    s = text.strip()
    starts = [i for i in (s.find("{"), s.find("[")) if i >= 0]
    if not starts:
        raise CmuxError("expected JSON from cmux, got: %s" % (s[:120] or "nothing"))
    try:
        return json.loads(s[min(starts):])
    except ValueError as e:
        raise CmuxError("could not read cmux's JSON: %s" % e)


def alive() -> bool:
    try:
        cmux("ping", timeout=5)
        return True
    except CmuxError:
        return False


def resume_command(agent: str, session_id: str) -> str:
    """The command that brings back one exact saved session."""
    if agent not in AGENTS:
        raise CmuxError("desk cannot resume a %s session" % agent)
    if not session_id:
        raise CmuxError("a session id is needed to resume")
    return shlex.join([agent, "--resume", session_id] if agent == "claude" else [agent, "resume", session_id])


# --------------------------------------------------------------------------- sessions

def pid_alive(pid) -> Optional[bool]:
    """True, False, or None when there is no pid to check."""
    if not pid:
        return None
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (ValueError, TypeError, OverflowError):
        return None


def pid_recycled(s: dict) -> bool:
    """A session's pid now belongs to another program. Pids come round again
    after a restart, so a long-gone session can still answer os.kill; cmux
    keeps the arguments it launched and the ones it reads at that pid now."""
    stored, launched = s.get("stored_pid_arguments"), s.get("launch_arguments")
    if not stored or not launched:
        return False
    return Path(str(stored[0])).name != Path(str(launched[0])).name


def records(timeout: float = 30) -> List[dict]:
    """Every session cmux has a record of, live or not. Read from disk, so it
    works without the socket."""
    data = cmux("sessions", "list", "--json", "--all", parse=True, timeout=timeout, password=False)
    found = data.get("sessions", []) if isinstance(data, dict) else []
    return [s for s in found if isinstance(s, dict)]


def roster(running_only: bool = True, titles: Optional[dict] = None, timeout: float = 30) -> List[dict]:
    """The agent sessions cmux knows about, each with its tab and workspace name
    when the socket answers (titles={} skips asking)."""
    out = []
    for s in records(timeout):
        # cmux can report a session as running after its process has gone; ask the kernel.
        live = pid_alive(s.get("pid"))
        if live is None:
            live = s.get("agent_lifecycle") == "running"
        if live and pid_recycled(s):
            live = False
        if running_only and not live:
            continue
        out.append({
            "agent": s.get("agent"),
            "session_id": s.get("session_id"),
            "workspace": s.get("workspace_id"),
            "surface": s.get("surface_id"),
            "cwd": s.get("cwd") or s.get("launch_working_directory"),
            "transcript": s.get("transcript_path"),
            "restorable": s.get("is_restorable"),
            "alive": bool(live),
        })
    if titles is None:
        titles = surface_titles()
    for r in out:
        meta = titles.get(r.get("surface") or "", {})
        r["tab"] = meta.get("tab", "")
        r["workspace_name"] = meta.get("workspace", "")
    return out


def surface_titles() -> Dict[str, dict]:
    """{surface id: {"tab", "workspace"}} for every open tab; empty when the socket is down."""
    out: Dict[str, dict] = {}
    try:
        windows = cmux("list-windows", "--json", parse=True)
    except CmuxError:
        return out
    if isinstance(windows, dict):
        windows = windows.get("windows", [])
    for win in windows or []:
        args = ["workspace", "list", "--json", "--id-format", "both"]
        if isinstance(win, dict) and win.get("id"):
            args += ["--window", win["id"]]
        try:
            spaces = cmux(*args, parse=True).get("workspaces", [])
        except (CmuxError, AttributeError):
            continue
        for ws in spaces:
            name = ws.get("custom_title") or ws.get("title") or ""
            try:
                surfaces = cmux("list-pane-surfaces", "--workspace", ws["id"], "--json", "--id-format", "both",
                                parse=True).get("surfaces", [])
            except (CmuxError, KeyError, AttributeError):
                continue
            for sf in surfaces:
                if sf.get("id"):
                    out[sf["id"]] = {"tab": sf.get("title") or "", "workspace": name}
    return out


def turn_state(path, agent: Optional[str] = None, tail: Optional[int] = None) -> Tuple[str, int]:
    """(idle | working | ?, turns started) from a Claude Code or Codex transcript.

    Claude Code closes a turn with a system record: turn_duration, or
    stop_hook_summary alone in a run with no terminal, or local_command for a
    slash command. A reply after that record, with no prompt typed, is a turn
    the session began itself, on a task's notice or a stop hook that sent it
    back to work. Codex records event_msg task_started,
    then task_complete or turn_aborted for the same turn id; its commentary,
    tool output and final message do not end a turn. With no agent given it is
    told from the records. A transcript that is missing, or whose records are
    not recognised, reads ?, never idle. `tail` reads only that many bytes from
    the end: enough for the state, but the count is then of those bytes only.
    """
    if agent is not None and agent not in AGENTS:
        return "?", 0
    state, turns, recognised = "?", 0, False
    active = set()
    try:
        with open(path, "rb") as f:
            if tail:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - tail))
                if size > tail:
                    f.readline()                 # the first line is cut
            for raw in f:
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                kind = d.get("type")
                if agent is None:
                    if kind in ("session_meta", "event_msg", "response_item"):
                        agent = "codex"
                    elif kind in ("user", "assistant", "system"):
                        agent = "claude"
                if agent == "codex":
                    payload = d.get("payload")
                    if not isinstance(payload, dict):
                        continue
                    if kind == "session_meta":
                        recognised = True
                        if state == "?":
                            state = "idle"
                    elif kind == "event_msg":
                        event, turn = payload.get("type"), payload.get("turn_id") or "current"
                        if event == "task_started":
                            recognised = True
                            turns += 1
                            active.add(turn)
                            state = "working"
                        elif event in ("task_complete", "turn_aborted"):
                            recognised = True
                            active.discard(turn)
                            state = "working" if active else "idle"
                elif agent == "claude":
                    if kind == "user" and not d.get("isMeta"):
                        content = (d.get("message") or {}).get("content")
                        text = content if isinstance(content, str) else " ".join(
                            x.get("text", "") for x in content or [] if isinstance(x, dict))
                        recognised = True
                        turns += 1
                        state = "idle" if "[Request interrupted" in text else "working"
                    elif kind == "system" and d.get("subtype") in CLAUDE_TURN_ENDS:
                        recognised = True
                        state = "idle"
                    elif kind == "assistant" and state == "idle" \
                            and (d.get("message") or {}).get("model") != "<synthetic>":
                        state = "working"
    except (OSError, TypeError, ValueError):
        return "?", 0
    return (state if recognised else "?"), turns


def sessions_by_folder(workspace: Path) -> Dict[str, str]:
    """{folder: "idle" | "working"} for every live session in the workspace.

    The folder is the absolute, resolved path a tab was opened in: a project's,
    a thread's, a wiki's. Several sessions in one folder read working when any
    of them is. A session whose state cannot be read counts as idle. Empty when
    cmux is not installed or does not answer within two seconds. Never raises.
    """
    try:
        root = Path(workspace).expanduser().resolve()
        out: Dict[str, str] = {}
        for s in roster(running_only=True, titles={}, timeout=STATUS_TIMEOUT):
            if not s.get("cwd"):
                continue
            folder = Path(s["cwd"]).expanduser().resolve()
            if folder != root and root not in folder.parents:
                continue
            state = turn_state(s.get("transcript"), s.get("agent"), tail=TAIL)[0] if s.get("transcript") else "?"
            key = str(folder)
            out[key] = "working" if state == "working" or out.get(key) == "working" else "idle"
        return out
    except Exception:
        return {}


def foregrounds() -> Dict[str, Optional[List[str]]]:
    """{surface id: the names of the programs in its terminal's foreground}.

    Read from cmux's process view. A surface whose foreground cmux does not
    show, or shows without its programs, maps to None: nobody can say what
    would read a line typed there. Empty when cmux does not answer."""
    try:
        data = cmux("top", "--all", "--processes", "--json", "--id-format", "both", parse=True)
    except CmuxError:
        return {}
    out: Dict[str, Optional[List[str]]] = {}

    def processes(items, found):
        for p in items or []:
            if isinstance(p, dict):
                found.append(p)
                processes(p.get("children"), found)
        return found

    def visit(node):
        if isinstance(node, list):
            for x in node:
                visit(x)
        elif isinstance(node, dict):
            if node.get("kind") == "surface" and node.get("id"):
                groups = node.get("foreground_pgids") or []
                procs = processes(node.get("processes"), [])
                names: Optional[List[str]] = []
                for g in groups:
                    members = [p for p in procs if p.get("pgid") == g]
                    leaders = [p for p in members if p.get("pid") == g] or members
                    if not leaders:
                        names = None
                        break
                    names += [Path(str(p.get("name") or "")).name.lstrip("-") for p in leaders]
                out[node["id"]] = names or None
                return
            for v in node.values():
                visit(v)

    visit(data)
    return out


def at_shell_prompt(names: Optional[List[str]]) -> bool:
    """Only a shell holds the terminal: a line typed there is a command. An
    editor, a database client, a password prompt or an assistant would take it
    as their own input."""
    return bool(names) and all(n in SHELLS for n in names)


# --------------------------------------------------------------------------- places

def zone_of(workspace: Path, path) -> Optional[str]:
    """The zone's name, "neutral" for System/ and the wikis, "root" at the top,
    or None outside the workspace."""
    try:
        rel = Path(path).resolve().relative_to(Path(workspace).resolve())
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return "root"
    if parts[0] == "Zones" and len(parts) >= 2:
        return parts[1]
    if parts[0] in NEUTRAL_TOPS:
        return "neutral"
    return "root"
