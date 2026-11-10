#!/usr/bin/env python3
"""desk: one cmux tab per thread, opened, closed and wrapped.

    desk status [--today] [--json] every live assistant tab: workspace, state, folder;
                                   --today only those used today, --json for a script
    desk open NAME                 a tab in that thread's or project's folder, in its zone's workspace
    desk open NAME --prompt TEXT   the same, starting the session on TEXT; an idle tab
                                   already there gets TEXT instead, a busy one nothing
    desk close TAB [--wrap] [--yes]  close one tab (--session ID, or --folder PATH for
                                   every tab at or below a folder); --wrap has the
                                   tab wrap its thread first
    desk wrap TAB [--yes]          have one tab wrap its thread and stay open (--session ID,
                                   or --folder PATH); waits until the wrap has finished.
                                   Exit 3, typing nothing, when the tab is mid-turn
    desk workspace NAME            a new workspace in cmux's sidebar
    desk colour [ZONE...]          each zone's workspace in its colour from the status
                                   page's Settings > Zones; a zone named with no colour
                                   has its colour cleared
    desk agent [claude|codex]      which assistant a new tab starts; with a name, sets it
                                   in System/desk.json, as the status page's Settings does

Without --yes, close and wrap change nothing and say what they would do. Desk
quits nothing: cmux resumes the sessions of its tabs itself when it reopens, and
quitting it is yours. "Close for the day" is the threads skill's procedure: it
asks each session used today to wrap, one at a time, and uses `desk wrap` for
the cmux tabs among them.

The workspace is --workspace, else GARRICK_WORKSPACE, else the folder you are
in or the nearest one above it holding System/rules.md, else ~/Garrick. The
settings are in System/desk.json (desk.example.json, beside this file, shows
every one), or the file GARRICK_DESK_CONFIG names. A zone's colour comes from
the status page's Settings › Zones, kept in System/garrick-settings.json:
a tab opened in a project or thread colours its zone's workspace with it. A
tab at the workspace root, in a wiki or in System/ takes none. A new tab
starts the assistant `agent` names only when its command is found here;
otherwise desk says so and opens nothing. Standard library only.
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cmuxlib as cx  # noqa: E402

WRAP_PROMPT = ("Closing for the day: this tab stays open once the wrap is done. Do not ask questions. "
               "If this session produced no deliverable or decision, say so in one line and stop.")
CLOSE_PROMPT = ("This tab closes once the wrap is done. Do not ask questions. "
                "If this session produced no deliverable or decision, say so in one line and stop.")
WRAP_START_S, WRAP_LIMIT_S = 90, 15 * 60          # for the wrap to begin, and to finish
LOCK_S = 600                                      # a wrap lock older than this counts as gone, as wrap_lock.py's
SKIP = ("archive", "Archive", "Inbox")
SETTINGS = ("workspaces", "skip", "aliases", "agent", "before_quit", "socket_password_file")
FILLER = {"the", "thread", "project", "tab"}
MATCH_MIN = 4                                     # letters before part of a tab's name may stand for it
CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")
AGENT_NAMES = {"claude": "Claude Code", "codex": "Codex"}
# Where the two assistants' installers put their command, looked in when the
# PATH desk was started with lacks it: the status app and launchd start it
# with a bare one. The user's own shell is asked last (agent_found()).
SHELL_WAIT_S = 10                                  # for the user's shell to say where a command is
AGENT_DIRS = ("~/.local/bin", "~/.claude/local", "/opt/homebrew/bin", "/usr/local/bin",
              "~/.npm-global/bin", "~/.bun/bin", "~/.volta/bin", "~/.cargo/bin")


class DeskError(Exception):
    pass


# ------------------------------------------------------------------ the workspace and its settings

def find_workspace(given: Optional[str] = None) -> Path:
    def ok(p: Path) -> bool:
        return (p / "System" / "rules.md").is_file() and (p / "Zones").is_dir()
    for named in (given, os.environ.get("GARRICK_WORKSPACE")):
        if named:
            p = Path(named).expanduser().resolve()
            if not ok(p):
                raise DeskError("%s is not a Garrick workspace" % p)
            return p
    here = Path.cwd().resolve()
    for p in (here, *here.parents):
        if ok(p):
            return p
    home = (Path.home() / "Garrick").resolve()
    if ok(home):
        return home
    raise DeskError("no workspace here; pass --workspace or set GARRICK_WORKSPACE")


def config_path(ws: Path) -> Path:
    """System/desk.json, or the file GARRICK_DESK_CONFIG names."""
    return Path(os.environ.get("GARRICK_DESK_CONFIG") or ws / "System" / "desk.json").expanduser()


def load_config(ws: Path, path: Optional[Path] = None) -> dict:
    """System/desk.json, merged over the defaults. Every key is optional; an
    unknown one is refused, so a misspelt setting is not silently ignored."""
    cfg = {"workspaces": {"neutral": "System"}, "skip": list(SKIP), "aliases": {}, "agent": "claude",
           "before_quit": [], "socket_password_file": None}
    path = path or config_path(ws)
    if path.is_file():
        try:
            given = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise DeskError("%s is not valid JSON: %s" % (path, e))
        if not isinstance(given, dict):
            raise DeskError("%s should hold one JSON object" % path)
        unknown = sorted(set(given) - set(SETTINGS) - {"_comment"})
        if unknown:
            raise DeskError("%s has settings desk does not know: %s" % (path.name, ", ".join(unknown)))
        for key in ("workspaces", "aliases"):
            if key in given and not (isinstance(given[key], dict)
                                     and all(isinstance(v, str) for v in given[key].values())):
                raise DeskError("%s: %s should map names to names" % (path.name, key))
        if "skip" in given and not (isinstance(given["skip"], list) and all(isinstance(v, str) for v in given["skip"])):
            raise DeskError("%s: skip should be a list of folder names" % path.name)
        if "agent" in given and given["agent"] not in cx.AGENTS:
            raise DeskError("%s: agent should be one of %s" % (path.name, ", ".join(cx.AGENTS)))
        if "socket_password_file" in given and not isinstance(given["socket_password_file"], (str, type(None))):
            raise DeskError("%s: socket_password_file should be a path" % path.name)
        cfg["workspaces"].update(given.get("workspaces", {}))
        for key in ("skip", "aliases", "agent", "socket_password_file"):
            if key in given:
                cfg[key] = given[key]
        if "before_quit" in given:
            if not isinstance(given["before_quit"], list):
                raise DeskError("%s: before_quit should be a list of commands" % path.name)
            cfg["before_quit"] = given["before_quit"]          # retired: kept only so main() can say so
    if cfg["socket_password_file"]:
        cx.PASSWORD_FILE = Path(cfg["socket_password_file"]).expanduser()
    return cfg


_SETTINGS_LIB: Dict[Path, object] = {}


def settings_lib(ws: Path):
    """garrick_lib, which keeps the choices a workspace holds: the
    workspace's own copy in System/tools, else the one beside this extra
    (System/cmux is a step from System/tools), else a Garrick clone's
    template. One accessor for the colours, shared with the status page,
    which the desk runs without. None when none of them has it."""
    ws = Path(ws)
    if ws not in _SETTINGS_LIB:
        here = Path(__file__).resolve().parent
        found = None
        for src in (ws / "System" / "tools" / "garrick_lib.py", here.parent / "tools" / "garrick_lib.py",
                    here.parent.parent / "template" / "System" / "tools" / "garrick_lib.py"):
            if not src.is_file():
                continue
            try:
                spec = importlib.util.spec_from_file_location("garrick_desk_settings", str(src))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                continue
            if callable(getattr(mod, "preferences", None)):
                found = mod
                break
        _SETTINGS_LIB[ws] = found
    return _SETTINGS_LIB[ws]


def zone_colours(ws: Path) -> Dict[str, str]:
    """Each zone's colour, by cmux's name for it, from the choices the
    workspace keeps, where the status page's Settings › Zones saves them:
    {"zones": {"Work": {"color": "Teal", …}}}. A name cmux does not know is
    dropped, whatever its case is matched; nothing saved, or nothing that
    reads, is no colour."""
    lib = settings_lib(ws)
    try:
        zones = lib.preferences(ws).get("zones") if lib is not None else None
    except Exception:
        zones = None
    named = {c.lower(): c for c in cx.COLOURS}
    out = {}
    for zone, style in (zones.items() if isinstance(zones, dict) else ()):
        colour = style.get("color") if isinstance(style, dict) else None
        if isinstance(colour, str) and colour.lower() in named:
            out[zone] = named[colour.lower()]
    return out


def workspace_lib(ws: Path):
    """The workspace's own garrick_lib, for the Aliases table and near matches, or None."""
    src = ws / "System" / "tools" / "garrick_lib.py"
    if not src.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("garrick_desk_lib", str(src))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


class Desk:
    def __init__(self, ws: Path, cfg: Optional[dict] = None):
        self.ws = ws
        self.cfg = cfg if cfg is not None else load_config(ws)
        self.lib = workspace_lib(ws)
        heard = {}
        if self.lib is not None:
            try:
                heard = self.lib.load_context(ws).get("aliases", {})
            except Exception:
                heard = {}
        heard.update(self.cfg["aliases"])
        self.aliases = {norm(k): v for k, v in heard.items()}

    # -------------------------------------------------------------- places

    def zones(self) -> List[str]:
        base = self.ws / "Zones"
        return sorted(z.name for z in base.iterdir() if z.is_dir() and not z.name.startswith((".", "_")))

    def containers(self) -> set:
        """Folders that hold projects rather than being one. A session there
        reaches every project below it and collides with all of them."""
        return {"", "Zones", "Wikis"} | {"Zones/" + z for z in self.zones()}

    def places(self) -> List[dict]:
        """Every folder a tab may open in: projects, threads, the wikis, System."""
        out = []
        skip = set(self.cfg["skip"])
        hidden = lambda d: d.name.startswith((".", "_")) or d.name in skip
        for zone in self.zones():
            for p in sorted((self.ws / "Zones" / zone).iterdir()):
                if not p.is_dir() or hidden(p) or not (p / (p.name + ".md")).is_file():
                    continue
                out.append({"kind": "project", "zone": zone, "project": p.name, "name": p.name, "path": p})
                threads = p / "Threads"
                for t in sorted(threads.iterdir()) if threads.is_dir() else []:
                    if t.is_dir() and not hidden(t) and (t / (t.name + ".md")).is_file():
                        out.append({"kind": "thread", "zone": zone, "project": p.name, "name": t.name, "path": t})
        wikis = self.ws / "Wikis"
        for w in sorted(wikis.iterdir()) if wikis.is_dir() else []:
            if w.is_dir() and not hidden(w):
                out.append({"kind": "wiki", "zone": "neutral", "project": None, "name": w.name, "path": w})
        system = self.ws / "System"
        for d in sorted(system.iterdir()):
            if d.is_dir() and not hidden(d) and (d / (d.name + ".md")).is_file():
                out.append({"kind": "project", "zone": "neutral", "project": d.name, "name": d.name, "path": d})
        out.append({"kind": "system", "zone": "neutral", "project": None, "name": "System", "path": system})
        return out

    def rel(self, path) -> str:
        try:
            return str(Path(path).resolve().relative_to(self.ws))
        except ValueError:
            return str(path)

    def say_place(self, place: dict) -> str:
        if place["kind"] == "thread":
            return "%s, %s" % (place["project"], place["name"])
        return place["name"]

    def resolve(self, query: str) -> dict:
        """One place for a heard name, or DeskError naming the candidates.

        The threads skill's order: an alias, then a thread's name, then
        "project thread", then a project, wiki or System, then a part of a
        name, initials, and last a name that sounds or is spelt close."""
        as_path = Path(query).expanduser()
        if as_path.is_absolute() or "/" in query:
            p = (as_path if as_path.is_absolute() else self.ws / query).resolve()
            if p.is_dir() and (p == self.ws or self.ws in p.parents):
                known = [x for x in self.places() if x["path"].resolve() == p]
                return known[0] if known else {"kind": "folder", "zone": cx.zone_of(self.ws, p),
                                               "project": None, "name": p.name or "the workspace", "path": p}
            raise DeskError("%s is not a folder in the workspace" % query)

        places = self.places()
        q = norm(query, filler=True)
        meant = self.aliases.get(q) or self.aliases.get(norm(query))
        if meant and norm(meant, filler=True) != q:
            return self.resolve(meant)

        def pick(hits: List[dict]) -> Optional[dict]:
            if len(hits) == 1:
                return hits[0]
            if hits:
                raise DeskError("%r could be %s. Which one?" % (query, "; ".join(
                    "%s in %s" % (self.say_place(h), h["zone"] if h["zone"] != "neutral" else "the workspace")
                    for h in hits)))
            return None

        def heard(place: dict) -> str:
            """The `spoken` form in its note, for a name that does not say how it
            is said. Matched alongside the name, as the threads skill resolves."""
            form = getattr(self.lib, "spoken_of", None)
            if form is None or place["kind"] not in ("thread", "project"):
                return ""
            return norm(form(place["path"]))

        def by_form(place: dict) -> bool:
            form = heard(place)
            return bool(form) and form == q

        steps = [
            [p for p in places if p["kind"] == "thread" and (norm(p["name"]) == q or by_form(p))],
            [p for p in places if p["kind"] == "thread" and norm(p["project"] + p["name"]) == q],
            [p for p in places if p["kind"] != "thread" and (norm(p["name"]) == q or by_form(p))],
        ]
        for hits in steps:
            found = pick(hits)
            if found:
                return found
        if not q:
            raise DeskError("say which thread or project")
        labels = [(norm(p["name"]), p) for p in places] + \
                 [(norm(p["project"] + p["name"]), p) for p in places if p["kind"] == "thread"] + \
                 [(form, p) for p in places for form in [heard(p)] if form]
        hits = unique(p for k, p in labels if q in k)
        if not hits and len(q) >= 2:
            hits = unique(p for p in places if initials(p["name"]).startswith(q))
        if not hits:
            alike = getattr(self.lib, "sounds_alike", None)
            if alike is not None:
                hits = unique(p for p in places if alike(query, p["name"]))
        if not hits:
            near = set(difflib.get_close_matches(q, [k for k, _ in labels], n=4, cutoff=0.75))
            hits = unique(p for k, p in labels if k in near)
        found = pick(hits)
        if found:
            return found
        live = [self.say_place(p) for p in places if p["kind"] in ("thread", "project")][:6]
        raise DeskError("nothing called %r. Some that exist: %s" % (query, ", ".join(live) or "none yet"))

    def workspace_for(self, zone: Optional[str]) -> str:
        names = self.cfg["workspaces"]
        if zone in (None, "neutral", "root"):
            return names.get("neutral", "System")
        return names.get(zone, zone)


# ------------------------------------------------------------------ small helpers

def norm(s: str, filler: bool = False) -> str:
    s = s.lower().replace("&", " and ")
    if filler:
        s = " ".join(w for w in re.split(r"[\s,]+", s) if w not in FILLER)
    return re.sub(r"[^a-z0-9]", "", s)


def initials(name: str) -> str:
    return norm("".join(w[0] for w in re.split(r"[\s\-]+", name) if w))


def unique(items) -> List[dict]:
    seen, out = set(), []
    for p in items:
        if id(p) not in seen:
            seen.add(id(p))
            out.append(p)
    return out


def cmux(*args, **kw):
    try:
        return cx.cmux(*args, **kw)
    except cx.CmuxError as e:
        raise DeskError(str(e))


def close_surface(s: dict) -> None:
    """Close a tab's surface. cmux 0.65 refuses a surface that still runs a
    process (the assistant is one) with the code `confirmation_required`,
    unless forced. Desk has checked the transcript, but that says nothing about
    what else runs in the terminal, so it forces only when cmux asks and the
    surface's foreground, read just now, is the tab's own assistant's process
    group and nothing else (matched by process id: its name is a version number).
    A job, a dev server or a `!` command would be killed too: those tabs are left for the user. Older cmux has no --force and never asks,
    so it closes on the first call.

    cmux will not close the last surface of a workspace (`invalid_state`, saying
    "last surface"). When the tab is the only surface in the only pane there, and the same check on the foreground holds,
    the workspace is closed instead (#376). Any other `invalid_state` keeps
    cmux's own message."""
    args = ["close-surface", "--surface", s["surface"]]
    if s.get("workspace"):
        args += ["--workspace", s["workspace"]]
    try:
        cx.cmux(*args)
        return
    except cx.CmuxError as e:
        if e.code == "invalid_state" and "last surface" in str(e).lower() and s.get("workspace") and only_surface(s):
            close_workspace(s)
            return
        if e.code != "confirmation_required":
            raise DeskError(str(e))
    require_own_foreground(s)
    cmux(*args, "--force")


def require_own_foreground(s: dict) -> None:
    """Refuse unless the tab's foreground, read just now, is its own assistant's
    process group and nothing else."""
    sid = s["surface"]
    pid = s.get("pid")
    if not pid or cx.foreground_groups().get(sid) != [pid]:
        running = cx.foregrounds().get(sid)
        raise DeskError("cmux will not close %s without possibly killing %s; close the tab by hand" % (
            tab_label(s), ", ".join(running) if running else "a program desk cannot name"))


def only_surface(s: dict) -> bool:
    """Whether the tab is the one surface its workspace holds. `list-pane-surfaces`
    reads the focused pane only, so the workspace's panes are listed and the
    surfaces counted across all of them: a pane with none, such as cmux 0.65's
    global dock, does not count (#490). False when cmux cannot say, or when a
    pane holds surfaces it does not name."""
    try:
        data = cx.cmux("list-panes", "--workspace", s["workspace"], "--json", "--id-format", "both", parse=True)
        panes = data.get("panes")
    except (cx.CmuxError, AttributeError):
        return False
    if not isinstance(panes, list) or not panes:
        return False
    ids = []
    for pane in panes:
        if not isinstance(pane, dict):
            return False
        names = pane.get("surface_ids")
        if isinstance(names, list):
            if pane.get("surface_count", len(names)) != len(names):
                return False
            ids += names
        elif pane.get("surface_count") != 0:
            return False
    return ids == [s["surface"]]


def close_workspace(s: dict) -> None:
    """Close the workspace of a tab that is its last. Only after the tab's
    foreground is shown to be its own assistant and nothing else."""
    require_own_foreground(s)
    args = ["close-workspace", "--workspace", s["workspace"]]
    try:
        cx.cmux(*args)
        return
    except cx.CmuxError as e:
        if e.code != "confirmation_required":
            raise DeskError(str(e))
    cmux(*args, "--force")


def live_sessions() -> List[dict]:
    try:
        return [s for s in cx.roster(running_only=True) if s["alive"]]
    except cx.CmuxError as e:
        raise DeskError(str(e))


# A tab whose last turn has ended, and one that has had no turn yet.
IDLE = ("idle", "empty")


def state_of(s: dict) -> str:
    """From the assistant's transcript: a tab's title and cmux's own lifecycle
    flag can be stale. `empty` is a Claude Code tab with no prompt since it
    started or was cleared: idle, with nothing to wrap."""
    return cx.session_state(s)


def tab_label(s: dict) -> str:
    t = re.sub(r"^[^\w(]+\s*", "", s.get("tab") or "")       # drop the assistant's status glyph
    return t or "(%s)" % Path(s.get("cwd") or "?").name


def wrap_prompt(agent: str, why: str = None) -> str:
    """Claude Code runs the skill by its slash command; Codex is asked in words."""
    if agent not in cx.AGENTS:
        raise DeskError("desk cannot wrap a %s session" % agent)
    return ("/threads wrap it. " if agent == "claude" else "Use the threads skill to wrap it. ") + (why or WRAP_PROMPT)


def plain(text: str) -> str:
    """Text on one line. A newline or another control character typed into a
    tab acts as a key: a newline would send the line before it was finished."""
    return CONTROL.sub(" ", text)


def agent_found(agent: str) -> bool:
    """Whether the assistant's command is installed: on this PATH, in one of
    AGENT_DIRS, or found by the user's own shell, which a tab starts in. A
    shell that cannot be asked, or does not answer in time, is taken to have
    it, so a tab is never refused on a guess. The shell's answer goes to a
    file, not a pipe: a job its startup files leave running in the
    background would hold a pipe open, and the check would wait it out."""
    if shutil.which(agent):
        return True
    for folder in AGENT_DIRS:
        p = Path(folder).expanduser() / agent
        if p.is_file() and os.access(str(p), os.X_OK):
            return True
    with tempfile.TemporaryFile() as out:
        try:
            proc = subprocess.Popen([os.environ.get("SHELL") or "/bin/zsh", "-ilc", "command -v %s" % shlex.quote(agent)],
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
        except OSError:
            return True
        try:
            code = proc.wait(timeout=SHELL_WAIT_S)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)       # the shell and whatever it started
            except OSError:
                pass
            proc.wait()
            return True
        out.seek(0)
        return code == 0 and bool(out.read().strip())


def require_agent(agent: str, named: bool = False) -> None:
    """Refuse, in words, a tab whose assistant would fail to start. `named`:
    the assistant was given with --agent, not taken from the setting."""
    if not agent_found(agent):
        other = next(k for k in cx.AGENTS if k != agent)
        raise DeskError("%s is not installed here, so the tab would not start. Install it, or %s"
                        % (agent, "start it with --agent %s" % other if named else
                           "choose %s for cmux tabs in Settings › Opening a thread" % AGENT_NAMES[other]))


def start_command(agent: str, name: str, prompt: Optional[str]) -> str:
    """Claude Code is named after the thread; both take a first prompt as an argument."""
    args = ["claude", "-n", plain(name)] if agent == "claude" else [agent]
    if prompt:
        args.append(plain(prompt))
    return shlex.join(args)


def midnight() -> float:
    return time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))


def touched_today(folder) -> int:
    """Files under the folder changed since midnight, leaving out build output and caches."""
    start, n = midnight(), 0
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("build", "__pycache__")]
        for f in files:
            try:
                n += os.path.getmtime(os.path.join(root, f)) >= start
            except OSError:
                pass
    return n


def used_today(s: dict) -> bool:
    """The session took a turn since midnight: its transcript moved today."""
    try:
        return bool(s.get("transcript")) and os.path.getmtime(s["transcript"]) >= midnight()
    except OSError:
        return False


def print_table(rows, headers):
    if not rows:
        print("  (none)")
        return
    w = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    for r in [headers, ["-" * x for x in w]] + rows:
        print("  " + "  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)).rstrip())


def bring_forward() -> bool:
    """Start cmux, or bring it in front of the app that asked: desk picks the tab
    inside cmux, but cmux itself may be behind."""
    bundle = cx.app()
    if bundle is None or sys.platform != "darwin":
        return False
    return subprocess.run(["open", str(bundle)], capture_output=True).returncode == 0


def workspaces() -> Dict[str, dict]:
    data = cmux("workspace", "list", "--json", "--id-format", "both", parse=True)
    return {(w.get("custom_title") or w.get("title") or ""): {"id": w["id"]}
            for w in data.get("workspaces", []) if isinstance(w, dict) and w.get("id")}


def set_colour(ref: str, colour: Optional[str]) -> bool:
    """A cmux workspace in one of cmux's named colours, or its colour cleared
    with None. Whether cmux took it: a colour is never worth failing for."""
    action = ["--action", "set-color", "--color", colour] if colour else ["--action", "clear-color"]
    try:
        cx.cmux("workspace-action", *action, "--workspace", ref)
        return True
    except cx.CmuxError:
        return False


def colour_for(desk: "Desk", place: dict, target: str, at_root: bool) -> Optional[str]:
    """The colour a new tab gives its workspace: its zone's, when the tab is in
    a zone's project or thread and goes to that zone's own workspace."""
    zone = place.get("zone")
    if at_root or zone in (None, "neutral", "root") or target != desk.workspace_for(zone):
        return None
    return zone_colours(desk.ws).get(zone)


def send(surface: str, text: str) -> None:
    """Type one line into a tab, then press Enter: the only key that submits it."""
    cmux("send", "--surface", surface, "--", plain(text))
    cmux("send-key", "--surface", surface, "enter")


def flags(desk: Desk, sessions: List[dict]) -> List[str]:
    """What is out of place among the open tabs."""
    out, by_folder = [], {}
    for s in sessions:
        r = desk.rel(s.get("cwd") or "")
        by_folder.setdefault(r, []).append(tab_label(s))
        if r in desk.containers():
            out.append("%s sits at %s, which holds projects: it collides with every one below it"
                       % (tab_label(s), r or "the workspace root"))
    for r, tabs in sorted(by_folder.items()):
        if len(tabs) > 1:
            out.append("%d tabs share %s: %s" % (len(tabs), r, ", ".join(tabs)))
    return out


# ------------------------------------------------------------------ verbs

def cmd_status(desk: Desk, a) -> None:
    sessions = live_sessions()
    if a.today:
        sessions = [s for s in sessions if used_today(s) and state_of(s) != "empty"]
    sessions.sort(key=lambda x: (x.get("workspace_name") or "", tab_label(x)))
    if a.json:
        print(json.dumps([{"session_id": s["session_id"], "agent": s["agent"], "workspace": s.get("workspace_name"),
                           "tab": tab_label(s), "state": state_of(s), "folder": desk.rel(s["cwd"] or ""),
                           "note": thread_note(desk, s)} for s in sessions], indent=1))
        return
    rows = [[s.get("workspace_name") or "-", tab_label(s)[:34], s["agent"], state_of(s), desk.rel(s["cwd"] or "")[:44]]
            for s in sessions]
    print("%d assistant tab%s %s" % (len(sessions), "" if len(sessions) == 1 else "s", "used today" if a.today else "open"))
    print_table(rows, ["workspace", "tab", "agent", "state", "folder"])
    for f in flags(desk, sessions):
        print("  ! " + f)


def cmd_open(desk: Desk, a) -> None:
    query = " ".join(a.name)
    place = desk.resolve(query)
    folder = place["path"].resolve()
    r = desk.rel(folder)
    # The root opens only when named by its full path, for a job that files
    # into every zone, such as processing the inboxes. A heard name never lands there.
    at_root = folder == desk.ws and Path(query).expanduser().is_absolute()
    if r in desk.containers() and not at_root:
        raise DeskError("%s holds projects; it is not one. Say which project or thread."
                        % (r or "the workspace root"))
    agent = a.agent or desk.cfg["agent"]

    # An assistant named for this open (--agent) takes only a tab running it: a
    # prompt sent to a tab running the other would start the wrong one (#307).
    existing = [s for s in live_sessions() if s.get("cwd") and Path(s["cwd"]).resolve() == folder
                and (not a.agent or s.get("agent") == a.agent)]
    if existing and not a.new:
        if not a.prompt:
            s = existing[0]
            if a.dry_run:
                print("already open: %s in %s" % (tab_label(s), s.get("workspace_name") or "?"))
                return
            if s.get("surface"):
                cmux("rpc", "surface.focus", json.dumps({"surface_id": s["surface"]}), check=False)
            if a.front:
                bring_forward()
            print("already open: %s in %s; brought it forward" % (tab_label(s), s.get("workspace_name") or "?"))
            return
        # A prompt is typed only into a tab whose last turn has ended: a busy
        # tab would take the text as an answer to something else. A tab desk
        # cannot read, such as a session cmux remembers but whose transcript
        # is gone, is passed over, and a new tab starts on the prompt instead.
        states = [(s, state_of(s)) for s in existing]
        idle = [s for s, st in states if st in IDLE and s.get("surface")]
        busy = [s for s, st in states if st == "working"]
        if idle or busy:
            s = (idle or busy)[0]
            if a.dry_run:
                print("%s: %s in %s" % ("would send to" if idle else "mid-turn, would send nothing to",
                                        tab_label(s), s.get("workspace_name") or "?"))
                return
            if s.get("surface"):
                cmux("rpc", "surface.focus", json.dumps({"surface_id": s["surface"]}), check=False)
            if a.front:
                bring_forward()
            if not idle:
                raise DeskError("%s is mid-turn; brought it forward and sent nothing" % tab_label(s))
            send(s["surface"], a.prompt)
            print("sent to %s in %s: %s" % (tab_label(s), s.get("workspace_name") or "?", a.prompt))
            return

    at_root = Path(folder).resolve() == desk.ws.resolve()
    name = a.title or ("Workspace" if at_root else desk.say_place(place) if place["kind"] == "thread"
                       else folder.name or "Workspace")
    command = start_command(agent, name, a.prompt)
    target = a.target or desk.workspace_for(place["zone"] if not at_root else "root")
    require_agent(agent, named=bool(a.agent))
    if a.dry_run:
        print("would open %s in %s, running: %s" % (r or "the workspace root", target, command))
        return
    spaces = workspaces()
    if target in spaces:
        cmux("new-surface", "--workspace", spaces[target]["id"], "--working-directory", str(folder),
             "--command", command, "--focus", "true")
        where = "a new tab in %s" % target
    else:
        cmux("new-workspace", "--name", target, "--cwd", str(folder), "--command", command, "--focus", "true")
        where = "a new workspace, %s" % target
    colour = colour_for(desk, place, target, at_root)
    if colour:
        try:
            ref = (spaces.get(target) or workspaces().get(target) or {}).get("id")
        except DeskError:
            ref = None
        if ref:
            set_colour(ref, colour)
    if a.front:
        bring_forward()
    print("opened %s: %s" % (name, where))


def match_tab(query: str, sessions: List[dict]) -> dict:
    """The one tab a heard name means: its whole name or folder, or else a part
    of one at least MATCH_MIN letters long that no other tab shares. A shorter
    part, "it" say, sits inside too many names to close a tab on."""
    q = norm(query, filler=True)
    if not q:
        raise DeskError("say which tab")
    names = lambda s: (norm(tab_label(s)), norm(Path(s.get("cwd") or "").name))
    hits = [s for s in sessions if q in names(s)]
    if not hits:
        if len(q) < MATCH_MIN:
            raise DeskError("no open tab is called %r; say more of its name" % query)
        hits = [s for s in sessions if any(q in n for n in names(s))]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise DeskError("no open tab matches %r" % query)
    raise DeskError("%r matches several tabs: %s. Which one?" % (query, ", ".join(tab_label(s) for s in hits)))


def choose_tabs(desk: Desk, a, live: List[dict]) -> List[dict]:
    """The tabs a close or a wrap names: by folder, by session id, or by name."""
    if a.folder:
        root = Path(a.folder).expanduser().resolve()
        chosen = [s for s in live if s.get("cwd") and (Path(s["cwd"]).resolve() == root
                                                       or root in Path(s["cwd"]).resolve().parents)]
        if not chosen:
            raise DeskError("no open tab in %s" % (desk.rel(root) or "the workspace root"))
    elif a.session:
        chosen = [s for s in live if s["session_id"] == a.session]
        if not chosen:
            raise DeskError("no open tab runs session %s" % a.session)
    else:
        chosen = [match_tab(" ".join(a.tab), live)]
    return chosen


def cmd_close(desk: Desk, a) -> None:
    chosen = choose_tabs(desk, a, live_sessions())
    # Every tab is checked before any is closed, so a refusal leaves them all open.
    for s in chosen:
        state = state_of(s)
        if state == "working":
            raise DeskError("%s is mid-turn or waiting on a question; let it finish first" % tab_label(s))
        if state == "?":
            raise DeskError("cannot tell whether %s is idle: its %s transcript is missing or unreadable"
                            % (tab_label(s), s.get("agent")))
        if state == "empty" and a.wrap:
            raise DeskError("nothing to wrap in %s: it has had no prompt since it started or was cleared. "
                            "Close it without --wrap." % tab_label(s))
    labels = ", ".join(tab_label(s) for s in chosen)
    if a.wrap:
        unsupported = [tab_label(s) for s in chosen if s.get("agent") not in cx.AGENTS]
        if unsupported:
            raise DeskError("desk cannot wrap %s; close it without --wrap" % ", ".join(unsupported))
    if not a.yes:
        print("would %sclose %s. A closed tab drops out of tomorrow's restore; the conversation stays, and %s "
              "brings it back. Run again with --yes." % ("wrap, then " if a.wrap else "", labels, " or ".join(
                  "`%s`" % cx.resume_command(s["agent"], s["session_id"]) for s in chosen if s.get("agent") in cx.AGENTS)
                  or "its assistant"))
        return
    closed, left = [], []
    for s in chosen:
        # Checked again tab by tab: a wrap takes minutes, and a tab may have
        # started a turn since the check above.
        if a.wrap:
            ready = wrap_tab(desk, s, CLOSE_PROMPT) is not None
        else:
            ready = state_of(s) in IDLE
        if not ready:
            left.append(tab_label(s))
            continue
        close_surface(s)
        closed.append(tab_label(s))
    if closed:
        print("closed %s" % ", ".join(closed))
    if left:
        raise DeskError("left open, busy since the check or no longer readable: %s" % ", ".join(left))


def cmd_focus(desk: Desk, a) -> None:
    """Bring the tab running a session forward: the surface focus `open` makes for
    a tab already there, then cmux itself in front of the app that asked."""
    hits = [s for s in live_sessions() if s.get("session_id") == a.session and s.get("surface")]
    if not hits:
        raise DeskError("no live cmux tab runs that session")
    s = hits[0]
    cmux("rpc", "surface.focus", json.dumps({"surface_id": s["surface"]}), check=False)
    bring_forward()
    print("brought %s forward in %s" % (tab_label(s), s.get("workspace_name") or "?"))


def cmd_workspace(desk: Desk, a) -> None:
    name = " ".join(a.name)
    if name in workspaces():
        raise DeskError("a workspace called %r is already there" % name)
    args = ["new-workspace", "--name", name, "--focus", "true"]
    if a.folder:
        place = desk.resolve(a.folder)
        agent = a.agent or desk.cfg["agent"]
        require_agent(agent, named=bool(a.agent))
        args += ["--cwd", str(place["path"]), "--command", start_command(agent, desk.say_place(place), None)]
    cmux(*args)
    print("made the workspace %s" % name)


def cmd_agent(desk: Desk, a) -> None:
    """Which assistant a new tab starts. Named, it is written to the settings
    file, every other setting kept; the status page's Settings and the setup
    skill set it this way."""
    if not a.agent:
        print(desk.cfg["agent"])
        return
    path = config_path(desk.ws)
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data["agent"] = a.agent
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".desk-", suffix=".json", dir=str(path.parent))
    try:                                  # whole or not at all: the desk refuses a half-written file
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, str(path))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    desk.cfg["agent"] = a.agent
    print("a new cmux tab starts %s%s" % (AGENT_NAMES[a.agent], "" if agent_found(a.agent)
                                         else "; %s is not installed here yet" % a.agent))


def cmd_colour(desk: Desk, a) -> None:
    """Each zone's open workspace in its colour from Settings › Zones, as the
    status page's Settings asks when a colour changes. A zone named here with
    no colour has its colour cleared. With no zone named, every zone with a
    colour, and nothing cleared: a colour set by hand in cmux stays."""
    colours = zone_colours(desk.ws)
    unknown = [z for z in a.zones if z not in desk.zones()]
    if unknown:
        raise DeskError("no zone called %s" % ", ".join(unknown))
    spaces = workspaces()
    neutral = desk.workspace_for("neutral")
    done = []
    for zone in a.zones or sorted(colours):
        name = desk.workspace_for(zone)
        if name == neutral or name not in spaces:
            continue
        colour = colours.get(zone)
        if set_colour(spaces[name]["id"], colour):
            done.append("%s %s" % (name, colour.lower() if colour else "uncoloured"))
    print("coloured %s" % ", ".join(done) if done else "no zone's workspace is open to colour")


def thread_note(desk: Desk, s: dict) -> Optional[str]:
    """The note of the thread a tab sits in, by its path from the workspace: the
    nearest folder at or above the tab's, under Zones/, holding <Folder>/<Folder>.md."""
    try:
        ws = desk.ws.resolve()
        here = Path(s.get("cwd") or "").resolve()
    except OSError:
        return None
    for folder in (here, *here.parents):
        if folder == ws or ws not in folder.parents:
            return None
        note = folder / (folder.name + ".md")
        if note.is_file():
            rel = str(note.relative_to(ws))
            return rel if rel.startswith("Zones/") else None
    return None


def wrap_files(desk: Desk, rel: str):
    """The lock and the finish record wrap_lock.py keeps for a thread note."""
    name = "wrap-%s" % rel.strip("/").replace("/", "__")
    folder = desk.ws / "System" / "generated"
    return folder / (name + ".lock"), folder / (name + ".done")


def wrap_finished(desk: Desk, rel: str) -> Optional[float]:
    """When the last wrap of the note finished, from its record; None when there is none."""
    try:
        data = json.loads(wrap_files(desk, rel)[1].read_text(encoding="utf-8"))
        return datetime.strptime(data["finished"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
    except (OSError, ValueError, KeyError, TypeError):
        return None


def wrap_running(desk: Desk, rel: str) -> bool:
    try:
        return time.time() - wrap_files(desk, rel)[0].stat().st_mtime < LOCK_S
    except OSError:
        return False


def wrap_tab(desk: Desk, s: dict, why: str) -> Optional[float]:
    """Ask the tab's own session to wrap its thread, and wait for that turn to
    end and the wrap's lock to go. Seconds taken; DeskError when it does not.

    None, having typed nothing, when the tab is not idle at the moment of
    sending: a tab may have started a turn since it was checked, and one
    stopped on a permission question would take the wrap's text and Enter as
    its answer."""
    name, transcript = tab_label(s), s.get("transcript")
    state, turns = cx.turn_state(transcript, s["agent"])
    alive = s["session_id"] in {x["session_id"] for x in live_sessions()}
    if state != "idle" or not alive or not s.get("surface"):
        print("skipped %s: %s; typed nothing" % (name, "its session has ended" if not alive else
                                                 "mid-turn or waiting on a question" if state == "working"
                                                 else "its state cannot be read"), flush=True)
        return None
    rel = thread_note(desk, s)
    send(s["surface"], wrap_prompt(s["agent"], why))
    began = time.time()
    while True:
        time.sleep(5)
        state, now = cx.turn_state(transcript, s["agent"])
        if state == "?":
            raise DeskError("%s: its transcript could not be read during the wrap" % name)
        if now > turns and state == "idle" and not (rel and wrap_running(desk, rel)):
            return time.time() - began                  # the wrap's turn has ended, and its lock is gone
        if s["session_id"] not in {x["session_id"] for x in live_sessions()}:
            raise DeskError("%s: its session ended during the wrap" % name)
        if now == turns and time.time() - began > WRAP_START_S:
            raise DeskError("%s: the wrap never started" % name)
        if time.time() - began > WRAP_LIMIT_S:
            raise DeskError("%s: the wrap ran past %d minutes, or is waiting on a question" % (name, WRAP_LIMIT_S // 60))


def cmd_wrap(desk: Desk, a) -> int:
    """Have each tab named wrap its thread, one at a time, and leave it open.
    One at a time because wraps write shared files (the Todo list, a hub
    note) and two at once collide. 3 when a tab was skipped."""
    chosen = choose_tabs(desk, a, live_sessions())
    for s in chosen:
        if s.get("agent") not in cx.AGENTS:
            raise DeskError("desk cannot wrap %s" % tab_label(s))
    if not a.yes:
        for s in chosen:
            print("would have %s wrap %s (%s) and leave it open. Run again with --yes." % (
                tab_label(s), thread_note(desk, s) or "its thread", state_of(s)))
        return 0
    skipped = 0
    for s in chosen:
        began = time.time()
        took = wrap_tab(desk, s, WRAP_PROMPT)
        if took is None:
            skipped += 1
            continue
        rel = thread_note(desk, s)
        done = wrap_finished(desk, rel) if rel else None
        record = "" if rel is None else ", record written" if done and done >= began else ", no wrap record: check %s" % rel
        print("wrapped %s (%s, %ds%s)" % (tab_label(s), rel or "no thread", took, record), flush=True)
    return 3 if skipped else 0


# ------------------------------------------------------------------ main

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="desk", description=__doc__.split("\n")[0])
    p.add_argument("--workspace", help="the workspace; default GARRICK_WORKSPACE, or the one you are in")
    sub = p.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("status", help="every live assistant tab")
    st.add_argument("--today", action="store_true", help="only the tabs used today")
    st.add_argument("--json", action="store_true", help="for a script: one object per tab")
    st.set_defaults(fn=cmd_status)

    o = sub.add_parser("open", help="a tab in a thread's or project's folder")
    o.add_argument("name", nargs="+")
    o.add_argument("--agent", choices=cx.AGENTS, help="default: the agent setting, else claude")
    o.add_argument("--workspace", dest="target", metavar="NAME", help="the cmux workspace, instead of the zone's")
    o.add_argument("--title", help="the session's name; default the thread's")
    o.add_argument("--new", action="store_true", help="a second tab, even with one already open there")
    o.add_argument("--prompt", help="start the session on this, or send it to the idle tab already there")
    o.add_argument("--front", action="store_true", help="bring cmux in front of the app that asked")
    o.add_argument("--dry-run", action="store_true")
    o.set_defaults(fn=cmd_open)

    c = sub.add_parser("close", help="close a tab")
    c.add_argument("tab", nargs="*")
    c.add_argument("--session", help="the tab running this session id")
    c.add_argument("--folder", help="every tab at or below this folder")
    c.add_argument("--wrap", action="store_true", help="have each tab wrap its thread first (the threads skill)")
    c.add_argument("--yes", action="store_true")
    c.set_defaults(fn=cmd_close)

    wr = sub.add_parser("wrap", help="have a tab wrap its thread and stay open")
    wr.add_argument("tab", nargs="*")
    wr.add_argument("--session", help="the tab running this session id")
    wr.add_argument("--folder", help="every tab at or below this folder")
    wr.add_argument("--yes", action="store_true")
    wr.set_defaults(fn=cmd_wrap)

    fo = sub.add_parser("focus", help="bring the tab running a session forward")
    fo.add_argument("--session", required=True, help="the session id")
    fo.set_defaults(fn=cmd_focus)

    w = sub.add_parser("workspace", help="a new cmux workspace")
    w.add_argument("name", nargs="+")
    w.add_argument("--folder", help="start an assistant tab in this thread's or project's folder")
    w.add_argument("--agent", choices=cx.AGENTS)
    w.set_defaults(fn=cmd_workspace)

    ag = sub.add_parser("agent", help="which assistant a new tab starts, or set it")
    ag.add_argument("agent", nargs="?", choices=cx.AGENTS)
    ag.set_defaults(fn=cmd_agent)

    co = sub.add_parser("colour", help="each zone's workspace in its colour from Settings › Zones")
    co.add_argument("zones", nargs="*", metavar="ZONE", help="only these; one with no colour is cleared")
    co.set_defaults(fn=cmd_colour)

    return p


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    try:
        ws = find_workspace(a.workspace)
        desk = Desk(ws)
        if desk.cfg["before_quit"]:
            print("desk: before_quit is retired and ignored. `update` moves its commands into System/jobs/nightly.local; "
                  "or move them there by hand.", file=sys.stderr)
        return a.fn(desk, a) or 0
    except (DeskError, cx.CmuxError) as e:
        print("desk: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
