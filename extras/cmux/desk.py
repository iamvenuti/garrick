#!/usr/bin/env python3
"""desk: one cmux tab per thread, opened, closed, wrapped and brought back.

    desk status                    every live assistant tab: workspace, state, folder
    desk open NAME                 a tab in that thread's or project's folder, in its zone's workspace
    desk open NAME --prompt TEXT   the same, starting the session on TEXT; an idle tab
                                   already there gets TEXT instead, a busy one nothing
    desk close TAB [--wrap] [--yes]  close one tab (--session ID, or --folder PATH for
                                   every tab at or below a folder); --wrap has the
                                   tab wrap its thread first
    desk workspace NAME            a new workspace in cmux's sidebar
    desk end [--yes]               check nothing is mid-turn, then quit cmux
    desk shutdown [--yes]          wrap each tab used today (the threads skill), run the
                                   before-quitting commands, quit cmux
    desk start                     launch or restore cmux, resume any tab it brought back
                                   at a bare shell prompt, then list the tabs

Without --yes, close, end and shutdown change nothing and say what they would
do. Quitting keeps every tab in cmux's restore set; closing a tab takes it out.
A quit also records which session sat in which tab, so `start` can resume a
tab cmux brought back at a bare prompt. The record is used once.

The workspace is --workspace, else GARRICK_WORKSPACE, else the folder you are
in or the nearest one above it holding System/rules.md, else ~/Garrick. The
settings are in System/desk.json (desk.example.json, beside this file, shows
every one), or the file GARRICK_DESK_CONFIG names. Standard library only.
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cmuxlib as cx  # noqa: E402

WRAP_PROMPT = ("Shutting down for the day: cmux quits once every tab has wrapped. Do not ask questions. "
               "If this session produced no deliverable or decision, say so in one line and stop.")
CLOSE_PROMPT = ("This tab closes once the wrap is done. Do not ask questions. "
                "If this session produced no deliverable or decision, say so in one line and stop.")
WRAP_START_S, WRAP_LIMIT_S = 90, 15 * 60          # for the wrap to begin, and to finish
QUIT_AFTER_S = 3
SKIP = ("archive", "Archive", "Inbox")
SETTINGS = ("workspaces", "skip", "aliases", "agent", "before_quit", "socket_password_file")
FILLER = {"the", "thread", "project", "tab"}
MATCH_MIN = 4                                     # letters before part of a tab's name may stand for it
CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")


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


def load_config(ws: Path, path: Optional[Path] = None) -> dict:
    """System/desk.json, merged over the defaults. Every key is optional; an
    unknown one is refused, so a misspelt setting is not silently ignored."""
    cfg = {"workspaces": {"neutral": "System"}, "skip": list(SKIP), "aliases": {}, "agent": "claude",
           "before_quit": [], "socket_password_file": None}
    path = path or Path(os.environ.get("GARRICK_DESK_CONFIG") or ws / "System" / "desk.json").expanduser()
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
        cfg["before_quit"] = commands(given.get("before_quit", []), path.name)
    if cfg["socket_password_file"]:
        cx.PASSWORD_FILE = Path(cfg["socket_password_file"]).expanduser()
    return cfg


def commands(given, where: str) -> List[List[str]]:
    """before_quit: each command a string, split as a shell would, or a list of arguments."""
    if not isinstance(given, list):
        raise DeskError("%s: before_quit should be a list of commands" % where)
    out = []
    for c in given:
        if isinstance(c, str) and c.strip():
            try:
                out.append(shlex.split(c))
            except ValueError as e:
                raise DeskError("%s: cannot read the command %r: %s" % (where, c, e))
        elif isinstance(c, list) and c and all(isinstance(a, str) for a in c):
            out.append(list(c))
        else:
            raise DeskError("%s: %r is not a command" % (where, c))
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

        steps = [
            [p for p in places if p["kind"] == "thread" and norm(p["name"]) == q],
            [p for p in places if p["kind"] == "thread" and norm(p["project"] + p["name"]) == q],
            [p for p in places if p["kind"] != "thread" and norm(p["name"]) == q],
        ]
        for hits in steps:
            found = pick(hits)
            if found:
                return found
        if not q:
            raise DeskError("say which thread or project")
        labels = [(norm(p["name"]), p) for p in places] + \
                 [(norm(p["project"] + p["name"]), p) for p in places if p["kind"] == "thread"]
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


def live_sessions() -> List[dict]:
    try:
        return [s for s in cx.roster(running_only=True) if s["alive"]]
    except cx.CmuxError as e:
        raise DeskError(str(e))


def state_of(s: dict) -> str:
    """From the assistant's transcript: a tab's title and cmux's own lifecycle flag can be stale."""
    return cx.turn_state(s.get("transcript"), s.get("agent"))[0]


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


def notify(message: str) -> None:
    """A macOS notification: shutdown and start run detached, with nobody watching."""
    if sys.platform != "darwin":
        return
    subprocess.run(["osascript", "-e", 'on run argv\ndisplay notification (item 1 of argv) with title "Desk"\nend run',
                    message], capture_output=True)


def say(message: str, log: Optional[Path] = None) -> None:
    print(message, flush=True)
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))


def snapshot_file() -> Path:
    return cx.jobs_dir() / "desk-snapshot.json"


def shutdown_log() -> Path:
    return cx.jobs_dir() / "desk-shutdown.log"


def write_snapshot(sessions: List[dict]) -> int:
    """Which session sits in which tab, for `start` to check cmux's restore against."""
    rows = [{"session_id": s["session_id"], "agent": s["agent"], "surface": s.get("surface"),
             "workspace": s.get("workspace_name"), "tab": tab_label(s), "cwd": s.get("cwd")}
            for s in sessions if s.get("session_id") and s.get("cwd")]
    target = snapshot_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"taken": time.strftime("%Y-%m-%dT%H:%M:%S"), "taken_unix": time.time(), "tabs": rows},
                              indent=1), encoding="utf-8")
    tmp.replace(target)
    return len(rows)


def quit_cmux() -> None:
    """Detached and a few seconds late, so the caller has answered before cmux takes its own terminal down."""
    subprocess.Popen(["/bin/sh", "-c", "sleep %d; osascript -e 'tell application id \"%s\" to quit'"
                      % (QUIT_AFTER_S, cx.APP_ID)], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    rows = [[s.get("workspace_name") or "-", tab_label(s)[:34], s["agent"], state_of(s), desk.rel(s["cwd"] or "")[:44]]
            for s in sorted(sessions, key=lambda x: (x.get("workspace_name") or "", tab_label(x)))]
    print("%d assistant tab%s open" % (len(sessions), "" if len(sessions) == 1 else "s"))
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

    existing = [s for s in live_sessions() if s.get("cwd") and Path(s["cwd"]).resolve() == folder]
    if existing and not a.new:
        s = existing[0]
        if a.dry_run:
            print("already open: %s in %s" % (tab_label(s), s.get("workspace_name") or "?"))
            return
        if s.get("surface"):
            cmux("rpc", "surface.focus", json.dumps({"surface_id": s["surface"]}), check=False)
        if a.front:
            bring_forward()
        if a.prompt:
            # Typed into the tab only when its last turn has ended: a busy tab, or
            # one desk cannot read, would take the text as an answer to something else.
            state = state_of(s)
            if state != "idle" or not s.get("surface"):
                raise DeskError("%s is %s; brought it forward and sent nothing" % (
                    tab_label(s), "mid-turn" if state == "working" else "in a state desk cannot read"))
            send(s["surface"], a.prompt)
            print("sent to %s in %s: %s" % (tab_label(s), s.get("workspace_name") or "?", a.prompt))
            return
        print("already open: %s in %s; brought it forward" % (tab_label(s), s.get("workspace_name") or "?"))
        return

    name = a.title or (desk.say_place(place) if place["kind"] == "thread" else folder.name or "Workspace")
    command = start_command(agent, name, a.prompt)
    target = a.target or desk.workspace_for(place["zone"] if not at_root else "root")
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


def cmd_close(desk: Desk, a) -> None:
    live = live_sessions()
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
    # Every tab is checked before any is closed, so a refusal leaves them all open.
    for s in chosen:
        state = state_of(s)
        if state == "working":
            raise DeskError("%s is mid-turn or waiting on a question; let it finish first" % tab_label(s))
        if state == "?":
            raise DeskError("cannot tell whether %s is idle: its %s transcript is missing or unreadable"
                            % (tab_label(s), s.get("agent")))
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
            ready = wrap_tab(s, CLOSE_PROMPT, None) is not None
        else:
            ready = state_of(s) == "idle"
        if not ready:
            left.append(tab_label(s))
            continue
        args = ["close-surface", "--surface", s["surface"]]
        if s.get("workspace"):
            args += ["--workspace", s["workspace"]]
        cmux(*args)
        closed.append(tab_label(s))
    if closed:
        print("closed %s" % ", ".join(closed))
    if left:
        raise DeskError("left open, busy since the check or no longer readable: %s" % ", ".join(left))


def cmd_workspace(desk: Desk, a) -> None:
    name = " ".join(a.name)
    if name in workspaces():
        raise DeskError("a workspace called %r is already there" % name)
    args = ["new-workspace", "--name", name, "--focus", "true"]
    if a.folder:
        place = desk.resolve(a.folder)
        args += ["--cwd", str(place["path"]), "--command",
                 start_command(a.agent or desk.cfg["agent"], desk.say_place(place), None)]
    cmux(*args)
    print("made the workspace %s" % name)


def cmd_end(desk: Desk, a) -> None:
    sessions = live_sessions()
    busy = [s for s in sessions if state_of(s) != "idle"]
    rows = []
    for s in sorted(sessions, key=lambda x: (x.get("workspace_name") or "", tab_label(x))):
        r = desk.rel(s.get("cwd") or "")
        n = touched_today(s["cwd"]) if s.get("cwd") and r not in desk.containers() else 0
        rows.append([s.get("workspace_name") or "-", tab_label(s)[:34], state_of(s), n or "-", r[:44]])
    print("%d assistant tab%s open" % (len(sessions), "" if len(sessions) == 1 else "s"))
    print_table(rows, ["workspace", "tab", "state", "files today", "folder"])
    if busy:
        print("\n  still busy: %s" % ", ".join("%s (%s)" % (tab_label(s), state_of(s)) for s in busy))
    lost = [tab_label(s) for s in sessions if s.get("restorable") is False]
    if lost:
        print("  will not come back when cmux starts again: %s" % ", ".join(lost))
    touched = [r[1] for r in rows if r[3] != "-"]
    if touched:
        print("  changed files today, worth a wrap: %s" % ", ".join(touched))
    if not a.yes:
        print("\nNothing quit. Run again with --yes to quit cmux; every tab comes back when it starts.")
        return
    if busy and not a.force:
        raise DeskError("not quitting while a tab is busy or desk cannot read it. Let it finish, or pass --force.")
    write_snapshot(sessions)
    quit_cmux()
    print("\ncmux quits in %d seconds. `desk start`, or opening cmux, brings it all back." % QUIT_AFTER_S)


def stop(why: str, log: Optional[Path]) -> None:
    say("stopped: " + why, log)
    notify("Stopped; cmux is still running. " + why)
    raise DeskError(why)


def wrap_tab(s: dict, why: str, log: Optional[Path]) -> Optional[float]:
    """Ask the tab's own session to wrap its thread, and wait for that turn to
    end. Seconds taken; DeskError, and a notification, when it does not.

    None, having typed nothing, when the tab is not idle at the moment of
    sending. Tabs are checked once before the first wrap, and a wrap can take
    fifteen minutes: a tab may start a turn in that time, and one stopped on a
    permission question would take the wrap's text and Enter as its answer."""
    name, transcript = tab_label(s), s.get("transcript")
    state, turns = cx.turn_state(transcript, s["agent"])
    alive = s["session_id"] in {x["session_id"] for x in live_sessions()}
    if state != "idle" or not alive or not s.get("surface"):
        say("skipped %s: %s; typed nothing" % (name, "its session has ended" if not alive else
                                                 "mid-turn or waiting on a question" if state == "working"
                                                 else "its state cannot be read"), log)
        return None
    send(s["surface"], wrap_prompt(s["agent"], why))
    began = time.time()
    while True:
        time.sleep(5)
        state, now = cx.turn_state(transcript, s["agent"])
        if state == "?":
            stop("%s: its transcript could not be read during the wrap" % name, log)
        if now > turns and state == "idle":
            return time.time() - began                  # the wrap's turn has ended
        if s["session_id"] not in {x["session_id"] for x in live_sessions()}:
            stop("%s: its session ended during the wrap" % name, log)
        if now == turns and time.time() - began > WRAP_START_S:
            stop("%s: the wrap never started" % name, log)
        if time.time() - began > WRAP_LIMIT_S:
            stop("%s: the wrap ran past %d minutes, or is waiting on a question" % (name, WRAP_LIMIT_S // 60), log)


def cmd_shutdown(desk: Desk, a) -> None:
    """Wrap every tab used today, one at a time, then run the before-quitting
    commands and quit. One at a time because wraps write shared files (the
    Todo list, a hub note) and two at once collide. A wrap that does not
    finish stops the shutdown with cmux still up: a tab waiting on a question
    must not be quit under it."""
    log = shutdown_log() if a.yes else None
    sessions = live_sessions()
    unknown = [tab_label(s) for s in sessions if state_of(s) == "?"]
    if unknown:
        raise DeskError("cannot tell whether these are idle: %s. Look at them before shutting down." % ", ".join(unknown))
    busy = [tab_label(s) for s in sessions if state_of(s) == "working"]
    if busy:
        raise DeskError("%d tab%s mid-turn or waiting on a question: %s. Let them finish first."
                        % (len(busy), "" if len(busy) == 1 else "s", ", ".join(busy)))
    todo = sorted((s for s in sessions if s["agent"] in cx.AGENTS and used_today(s)),
                  key=lambda x: (x.get("workspace_name") or "", tab_label(x)))
    before = desk.cfg["before_quit"]
    if not a.yes:
        print("%d tab(s) open; %d used today would be wrapped, one at a time:" % (len(sessions), len(todo)))
        for s in todo:
            print("  %s / %s" % (s.get("workspace_name") or "-", tab_label(s)))
        for c in before:
            print("then: %s" % shlex.join(c))
        print("then cmux quits.\n\nNothing done. Run again with --yes.")
        return

    say("shutdown: %d tab(s) to wrap" % len(todo), log)
    notify("Shutting down: wrapping %d tab(s), then quitting cmux" % len(todo))
    skipped = []
    for i, s in enumerate(todo, 1):
        took = wrap_tab(s, WRAP_PROMPT, log)
        if took is None:
            skipped.append(tab_label(s))
            continue
        say("wrapped %d of %d: %s (%ds)" % (i, len(todo), tab_label(s), took), log)
    if skipped:
        stop("not wrapped, busy when its turn came: %s" % ", ".join(skipped), log)

    unsafe = [tab_label(s) for s in live_sessions() if state_of(s) != "idle"]
    if unsafe:
        stop("tabs became busy before quitting: %s" % ", ".join(unsafe), log)
    failed = []
    for c in before:
        try:
            rc = subprocess.run(c, cwd=str(desk.ws), capture_output=True, text=True, timeout=15 * 60).returncode
        except (OSError, subprocess.TimeoutExpired) as e:
            rc = "did not run (%s)" % (getattr(e, "strerror", None) or type(e).__name__)
        say("%s: %s" % (shlex.join(c), "done" if rc == 0 else "exit %s" % rc), log)
        if rc != 0:
            failed.append(Path(c[0]).name)
    final = live_sessions()
    unsafe = [tab_label(s) for s in final if state_of(s) != "idle"]
    if unsafe:
        stop("tabs became busy before quitting: %s" % ", ".join(unsafe), log)
    n = write_snapshot(final)
    say("snapshot: %d tab(s) recorded; quitting cmux" % n, log)
    notify("Wrapped %d tab(s)%s. cmux quits now." % (len(todo), "; check " + ", ".join(failed) if failed else ""))
    quit_cmux()


def settle(limit: int = 60, quiet: int = 10) -> None:
    """Wait until cmux has stopped bringing sessions back: the live set unchanged
    for `quiet` seconds. Typing into a tab cmux is still resuming would land in
    the new session's prompt."""
    last, since, began = None, time.time(), time.time()
    while time.time() - began < limit:
        now = sorted(s["session_id"] or "" for s in live_sessions())
        if now != last:
            last, since = now, time.time()
        elif time.time() - since >= quiet:
            return
        time.sleep(2)


def last_session_start() -> Optional[float]:
    """When cmux last started an assistant in any tab, from its records; 0 for
    never, None when the records cannot be read."""
    try:
        found = cx.records()
    except cx.CmuxError:
        return None
    newest = 0.0
    for r in found:
        try:
            when = datetime.fromisoformat(str(r.get("started_at")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        newest = max(newest, when)
    return newest


def take_snapshot(since: Optional[float]) -> Tuple[List[dict], Optional[str]]:
    """The last quit's record of its tabs, and why it is not to be used, if it
    is not. It is renamed on reading, so it is acted on once. It is out of date
    when cmux has started a session since it was taken: cmux ran after that
    quit, and its tabs are no longer the ones the record names."""
    snap = snapshot_file()
    if not snap.is_file():
        return [], None
    used = snap.with_name("desk-snapshot.used.json")
    try:
        snap.replace(used)
        data = json.loads(used.read_text(encoding="utf-8"))
        tabs, taken = data.get("tabs", []), data.get("taken_unix")
    except (OSError, ValueError, AttributeError):
        return [], "the record of the last quit could not be read"
    if not isinstance(tabs, list) or not isinstance(taken, (int, float)):
        return [], "the record of the last quit carries no date"
    if since is None:
        return [], "cmux's own records could not be read, so the age of the last quit's record is unknown"
    if since > taken:
        return [], "cmux has run since the last quit was recorded"
    return [t for t in tabs if isinstance(t, dict)], None


def resume_missing(tabs: List[dict], before: set) -> Tuple[List[str], List[str]]:
    """Resume each recorded tab cmux brought back without its session.

    Only into a tab this start brought back (one not in `before`), found by its
    surface id, or else by workspace and name when exactly one recorded tab
    and one tab brought back carry them. Only when cmux shows a shell alone in
    that tab's foreground, since a line typed into an editor or a password
    prompt is theirs: `cd <folder> && <the resume command>`."""
    if not tabs:
        return [], []
    live = live_sessions()
    alive_ids = {s["session_id"] for s in live}
    taken = {s.get("surface") for s in live}
    titles = {k: v for k, v in cx.surface_titles().items() if k not in before}
    fore = cx.foregrounds()
    label = lambda t: re.sub(r"^[^\w(]+\s*", "", t or "")
    named: Dict[tuple, List[str]] = {}
    for sid, meta in titles.items():
        named.setdefault((meta.get("workspace"), label(meta.get("tab"))), []).append(sid)
    recorded: Dict[tuple, int] = {}
    for t in tabs:
        key = (t.get("workspace"), t.get("tab"))
        recorded[key] = recorded.get(key, 0) + 1
    resumed, lost = [], []
    for t in tabs:
        name = t.get("tab") or "?"
        if t.get("session_id") in alive_ids:
            continue
        if t.get("agent") not in cx.AGENTS or not t.get("session_id") or not t.get("cwd"):
            lost.append("%s (desk cannot resume it)" % name)
            continue
        surface = t.get("surface") if t.get("surface") in titles else None
        key = (t.get("workspace"), t.get("tab"))
        if not surface and recorded.get(key) == 1 and len(named.get(key, [])) == 1:
            surface = named[key][0]
        if not surface:
            lost.append("%s (not among the tabs this start brought back)" % name)
            continue
        if surface in taken:
            lost.append("%s (another session is in its tab)" % name)
            continue
        if not cx.at_shell_prompt(fore.get(surface)):
            lost.append("%s (something other than a shell holds the tab)" % name)
            continue
        send(surface, "cd %s && %s" % (shlex.quote(t["cwd"]), cx.resume_command(t["agent"], t["session_id"])))
        taken.add(surface)
        resumed.append(name)
    return resumed, lost


def cmd_start(desk: Desk, a) -> None:
    # Read before cmux brings anything back, which starts sessions of its own.
    since = last_session_start()
    before: Optional[set] = None              # the tabs there before this start; None, it brought none back
    if not cx.alive():
        if not bring_forward():
            raise DeskError("cmux is not running, and desk cannot start it from here")
        for _ in range(30):
            time.sleep(1)
            if cx.alive():
                break
        else:
            raise DeskError("cmux did not come up within 30 seconds")
        time.sleep(3)                                     # its own restore is still reopening tabs
        before = set()
        print("started cmux; it reopens the tabs it had")
    elif not live_sessions():
        before = set(cx.surface_titles())
        cmux("restore-session")
        time.sleep(3)
        print("restored cmux's last saved tabs")
    resumed, lost = [], []
    if before is None:
        print("cmux was already running: desk resumes only the tabs it brings back itself")
    else:
        settle()
        tabs, stale = take_snapshot(since)
        if stale:
            print("  ! resumed nothing: %s" % stale)
        resumed, lost = resume_missing(tabs, before)
    if resumed:
        print("resumed %d tab(s) cmux left at a bare prompt: %s" % (len(resumed), ", ".join(resumed)))
    if lost:
        print("  ! not resumed: %s" % ", ".join(lost))
    if a.notify:
        notify("cmux is up.%s%s" % (" Resumed %d tab(s)." % len(resumed) if resumed else "",
                                     " Not resumed: %s." % ", ".join(lost) if lost else ""))
    cmd_status(desk, a)


# ------------------------------------------------------------------ main

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="desk", description=__doc__.split("\n")[0])
    p.add_argument("--workspace", help="the workspace; default GARRICK_WORKSPACE, or the one you are in")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="every live assistant tab").set_defaults(fn=cmd_status)

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

    w = sub.add_parser("workspace", help="a new cmux workspace")
    w.add_argument("name", nargs="+")
    w.add_argument("--folder", help="start an assistant tab in this thread's or project's folder")
    w.add_argument("--agent", choices=cx.AGENTS)
    w.set_defaults(fn=cmd_workspace)

    e = sub.add_parser("end", help="check, then quit cmux without wrapping")
    e.add_argument("--yes", action="store_true")
    e.add_argument("--force", action="store_true", help="quit even with a tab busy")
    e.set_defaults(fn=cmd_end)

    sd = sub.add_parser("shutdown", help="wrap each tab used today, then quit cmux")
    sd.add_argument("--yes", action="store_true")
    sd.set_defaults(fn=cmd_shutdown)

    st = sub.add_parser("start", help="start or restore cmux, resume stragglers, list the tabs")
    st.add_argument("--notify", action="store_true", help="post a notification when done")
    st.set_defaults(fn=cmd_start)
    return p


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    try:
        ws = find_workspace(a.workspace)
        a.fn(Desk(ws), a)
    except (DeskError, cx.CmuxError) as e:
        print("desk: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
