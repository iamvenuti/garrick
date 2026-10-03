#!/usr/bin/env python3
"""Garrick's Status: a status page for a Garrick workspace. An optional extra.

    python3 status.py [--workspace FOLDER] [--out FILE] [--open] [--obsidian VAULT] [--no-graph]

One self-contained HTML file that answers "is anything wrong, and where was I"
at a glance: every live thread by zone with how long since its resume point
moved, what the check found, open actions, what is waiting in the inboxes,
and, if you run scheduled jobs, how they ran and what the assistant spent.
A graph of the notes and the links between them, zone by zone, fills a card
at the top; click a note to open it or copy what to say about it. Hover a
thread in the list for the same actions. Every card can be dragged elsewhere
or hidden, and Reset view puts the page back.

**Show, don't store.** The page reads files the workspace and the jobs extra
already keep, and writes nothing but itself. It runs no server, loads nothing
from the network and carries no third-party script. Delete it and nothing is
lost: every fact on it lives in a file you own. Each panel says where its
numbers come from and how old they are.

**It lives in `System/generated/status.html`**, the folder for pages a tool
rebuilds. The page is the one place that shows every zone at once, so that
folder is kept out of two things: the workspace's git history (the root
`.gitignore` names it, and `check.py` reports it if not) and the wording the
wall check treats as shared by every side (`check.py` leaves the folder out,
so wording that appears only on this page never counts as shared).
What it shows is names, party tags, dates, counts, the check's findings
(which quote link targets and party names), the section headings of each
Todo.md, and the targets of links: the graph reads a note's frontmatter and
the targets of its [[links]], and draws the links as lines. The rest of a
note's body never reaches the page. Pass --no-graph to leave the graph out.

**Links open the files themselves**, in whatever app you use for Markdown.
Pass `--obsidian VAULT` if you opened the workspace root in Obsidian as a vault
called VAULT, and the links open there instead.

Copy this folder into your workspace as `System/status/`, next to
`System/jobs/` if you have it, and run it by hand or on a schedule through
job.py (see docs/extras/status-page.md). Standard library only, Python 3.9 or
later. Not installed by install.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import importlib.util
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True

E = html.escape
NAME = "Garrick's Status"     # what the page is called; its files and flags keep their names
DAYS = 14
EXIT = {0: "ok", 3: "answer incomplete", 4: "could not sign in", 6: "missing connector", 8: "spending cap",
        64: "bad arguments", 75: "skipped, still running", 124: "timed out", 127: "command not found"}
OK_EXITS = (0, 75)
LOGLINE = re.compile(r"^===== (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  (\S+)  (?:exit (-?\d+)  \((\d+)s\)|skipped)")
TODO_ITEM = re.compile(r"^\s*-\s\[ \]\s")


# --------------------------------------------------------------------------- where things are

def is_workspace(folder: Path) -> bool:
    return (folder / "System" / "rules.md").is_file() and (folder / "Zones").is_dir()


def find_workspace(given: Optional[str]) -> Path:
    """The folder named, or the one this runs in. A named folder must hold
    System/rules.md and Zones/, so a mistyped path stops here instead of
    gaining a System/generated/ of its own."""
    for how, cand in (("--workspace", given), ("GARRICK_WORKSPACE", os.environ.get("GARRICK_WORKSPACE"))):
        if cand:
            folder = Path(cand).expanduser().resolve()
            if not is_workspace(folder):
                raise SystemExit("status: %s (from %s) is not a Garrick workspace: it has no System/rules.md "
                                 "and Zones/ folder. Check the path." % (folder, how))
            return folder
    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        if is_workspace(folder):
            return folder
    for folder in (Path(__file__).resolve().parent, *Path(__file__).resolve().parents):
        if is_workspace(folder):
            return folder
    raise SystemExit("status: no workspace found. Pass --workspace, set GARRICK_WORKSPACE, or run it from inside one.")


def load_agent(ws: Path):
    """The jobs extra's agent module, for the ledger and the caps, if it is installed."""
    here = Path(__file__).resolve().parent
    for folder in (ws / "System" / "jobs", here.parent / "jobs"):
        if (folder / "agent.py").is_file():
            sys.path.insert(0, str(folder))
            try:
                import agent  # noqa: F401
                return agent
            except Exception:
                return None
    return None


def jobs_dir(agent) -> Path:
    if agent is not None:
        return agent.jobs_dir()
    set_to = os.environ.get("GARRICK_JOBS_DIR")
    if set_to:
        return Path(set_to).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "garrick-jobs"
    return Path.home() / ".local" / "state" / "garrick-jobs"


_LIBS: Dict[Path, object] = {}


def workspace_lib(ws: Optional[Path]):
    """The workspace's own garrick_lib, from System/tools, when it is there:
    the parser check.py uses, so the page reads a note the way the check does."""
    if ws is None:
        return None
    if ws not in _LIBS:
        mod, src = None, ws / "System" / "tools" / "garrick_lib.py"
        if src.is_file():
            try:
                spec = importlib.util.spec_from_file_location("garrick_status_lib", str(src))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if not callable(getattr(mod, "parse_frontmatter", None)):
                    mod = None
            except Exception:
                mod = None
        _LIBS[ws] = mod
    return _LIBS[ws]


def _value(raw: str):
    """One frontmatter value for the fallback parser: a trailing comment
    dropped, quotes taken off, [a, b] read as a list."""
    quote = None
    for i, ch in enumerate(raw):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1].isspace()):
            raw = raw[:i]
            break
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]") and not raw.startswith("[["):
        return [v.strip().strip("\"'") for v in raw[1:-1].split(",") if v.strip()]
    return raw.strip("\"'")


def frontmatter(path: Path, ws: Optional[Path] = None) -> dict:
    """The note's frontmatter: the workspace's own parser (garrick_lib in
    System/tools) when it is there, a small one otherwise that also drops
    trailing comments and reads block lists. Only frontmatter is ever read
    from a note here."""
    lib = workspace_lib(ws)
    if lib is not None:
        try:
            return lib.parse_frontmatter(path) or {}
        except Exception:
            pass
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict = {}
    key = None
    for line in lines[1:]:
        if line.strip() in ("---", "..."):
            break
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and key is not None:
            out[key] = (out[key] if isinstance(out.get(key), list) else []) + [_value(item.group(1))]
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:(.*)$", line)
        key = m.group(1) if m else None
        if m:
            out[key] = _value(m.group(2))
    return out


def as_text(value) -> str:
    """A frontmatter value as one string: a list joined, nothing as ''."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def visible_dirs(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def tags(value) -> List[str]:
    """Party tags from `acme`, `[acme, birch]`, `#acme` or a block list."""
    items = value if isinstance(value, list) else re.split(r"[,\[\]]", as_text(value))
    out = []
    for t in items:
        t = re.sub(r"\s+#.*$", "", as_text(t)).strip().strip("[]\"'").lstrip("#").strip()
        if t and t not in out:
            out.append(t)
    return out


def as_date(value) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(as_text(value).strip()[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------- what the page reads

def threads(ws: Path) -> Dict[str, dict]:
    """Per zone: every live thread's project, name, party and the date its
    note was last updated. Frontmatter only, like "what's open"."""
    out = {}
    for zone in visible_dirs(ws / "Zones"):
        rows, parked, done = [], [], 0
        for project in visible_dirs(zone):
            if project.name == "Inbox":
                continue
            hub = project / (project.name + ".md")
            pfm = frontmatter(hub, ws)
            for thread in visible_dirs(project / "Threads"):
                note = thread / (thread.name + ".md")
                fm = frontmatter(note, ws)
                state = as_text(fm.get("status")).strip().lower()
                if state == "done":
                    done += 1
                    continue
                row = {"zone": zone.name, "project": project.name, "thread": thread.name, "note": note,
                       "hub": hub if hub.is_file() else None,
                       "party": tags(fm.get("party") or pfm.get("party")),
                       "updated": as_date(fm.get("updated")), "status": state}
                (parked if state == "parked" else rows).append(row)
        # By name, as you would look for one; the freshness bar carries the age.
        by_name = lambda r: (r["thread"].casefold(), r["project"].casefold())  # noqa: E731
        rows.sort(key=by_name)
        parked.sort(key=by_name)
        out[zone.name] = {"rows": rows, "parked": parked, "done": done, "folder": zone}
    return out


def todo(ws: Path) -> Dict[str, dict]:
    out = {}
    for zone in visible_dirs(ws / "Zones"):
        f = zone / "Todo.md"
        if not f.is_file():
            continue
        counts, section = {}, None
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("## "):
                section = line[3:].strip()
            elif section and section.lower() != "done" and TODO_ITEM.match(line) and "<action>" not in line:
                counts[section] = counts.get(section, 0) + 1
        out[zone.name] = {"counts": counts, "file": f, "when": dt.datetime.fromtimestamp(f.stat().st_mtime)}
    return out


def inboxes(ws: Path) -> List[Tuple[str, Path, int]]:
    """Files waiting to be filed: each zone's Inbox and the Meetings inbox."""
    places = [(z.name, z / "Inbox") for z in visible_dirs(ws / "Zones")]
    places.append(("Meetings", ws / "Wikis" / "Meetings" / "raw" / "inbox"))
    out = []
    for name, folder in places:
        if folder.is_dir():
            n = sum(1 for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
            out.append((name, folder, n))
    return out


def check(ws: Path) -> Optional[dict]:
    tool = ws / "System" / "tools" / "check.py"
    if not tool.is_file():
        return None
    try:
        proc = subprocess.run([sys.executable, str(tool), "--root", str(ws), "--json"],
                              capture_output=True, text=True, timeout=300)
        data = json.loads(proc.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"failed": True}
    titles = {}
    try:
        src = tool.read_text(encoding="utf-8")
        titles = dict(re.findall(r'\(\s*"([a-z-]+)",\s*"([^"]+)"\s*\)', src.split("EAR_GROUP")[0]))
    except OSError:
        pass
    data["titles"] = titles
    return data


def repos(ws: Path) -> List[dict]:
    """The root, each zone, and the wikis: the installer makes one repository
    at Wikis/ for both. A wiki with a repository of its own is listed too."""
    places = [("Workspace", ws)] + [(z.name, z) for z in visible_dirs(ws / "Zones")] + \
             [("Wikis", ws / "Wikis")] + [(w.name, w) for w in visible_dirs(ws / "Wikis")]
    out = []
    for name, folder in places:
        if not (folder / ".git").exists():
            continue
        def git(*args):
            try:
                return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, timeout=30).stdout
            except (OSError, subprocess.TimeoutExpired):
                return ""
        dirty = len(git("status", "--porcelain").splitlines())
        ct = git("log", "-1", "--format=%ct").strip()
        out.append({"name": name, "dirty": dirty, "last": dt.datetime.fromtimestamp(int(ct)) if ct.isdigit() else None})
    return out


# One line per ingest in each wiki's log: `- 2026-09-24: [[wiki/sources/slug|Title]] (…)`.
LOG_ENTRY = re.compile(r"^\s*-\s+(\d{4}-\d\d-\d\d):\s+\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")


def wikis(ws: Path) -> List[dict]:
    """Per wiki: its log, how many entries it holds, and the newest entry's
    date and title. Nothing else from the line: not its zone, not its parties."""
    out = []
    for w in visible_dirs(ws / "Wikis"):
        log = w / "wiki" / "log.md"
        if not log.is_file():
            continue
        entries = []
        for n, line in enumerate(log.read_text(encoding="utf-8", errors="replace").splitlines()):
            m = LOG_ENTRY.match(line)
            when = as_date(m.group(1)) if m else None
            if when:
                target = m.group(2).strip()
                title = (m.group(3) or target.rsplit("/", 1)[-1]).strip()
                entries.append((when, -n, title, target))
        row = {"name": w.name, "log": log, "count": len(entries), "when": None, "title": "", "page": None}
        if entries:
            when, _, title, target = max(entries)   # the newest; on a tie, the line nearer the top
            page = (w / (target if target.endswith(".md") else target + ".md")).resolve()
            inside = str(page).startswith(str(w.resolve()) + os.sep)
            row.update(when=when, title=title[:100] + ("…" if len(title) > 100 else ""),
                       page=page if inside and page.is_file() else None)
        out.append(row)
    return out


WIKILINK = re.compile(r"\[\[([^\]|#^]+)")
# Folders that hold no notes of their own: an inbox, raw records, superseded
# versions, generated pages. Compared without regard to case.
SKIP_DIRS = {"inbox", "raw", "archive", "generated"}


def walked(root: Path, folder: str, name: str, in_zone: bool) -> bool:
    """Whether the graph reads the folder `name` inside `folder`. A zone's own
    Inbox is left out. A project or a thread is read whatever it is called, so
    one named Archive or raw stays on the graph; anywhere else a folder named
    for an inbox, raw records, old versions or generated pages is left out."""
    if name.startswith((".", "_")):
        return False
    depth = Path(folder).relative_to(root).parts
    if in_zone and not depth:
        return name != "Inbox"                                # every other folder here is a project
    if in_zone and len(depth) == 2 and depth[1] == "Threads":
        return True                                           # a thread
    return name.casefold() not in SKIP_DIRS
# What a note is, in the order the legend shows them. Colours are fixed so a
# kind looks the same in every workspace; none is amber or red, which the
# rings use for threads gone quiet. Threads take the brand blue, the light
# theme's accent, which also draws the lines of a selected note. A mail page
# (`type: email` in the Meetings wiki) has its own kind beside meetings.
KINDS = [("project", "project", "#e07b39"), ("thread", "thread", "#3d73e0"),
         ("note", "other notes", "#9aa0a6"), ("meeting", "meeting", "#7a5af8"), ("mail", "mail", "#c94f9c"),
         ("person", "person", "#13a38a"), ("knowledge", "knowledge", "#7c9a2d")]


def graph(ws: Path, T: Dict[str, dict], link: "Links", now: dt.datetime) -> dict:
    """Every note in the zones and the wikis, and the [[links]] between them.
    From a note it keeps its title, kind, place, party tags and, for a thread,
    how long since it moved; from its body only the targets of its links.
    Instructions (AGENTS.md) are not notes, and each zone's Todo.md has the
    Open actions card, so neither is drawn. A parked thread, with the notes in
    its folder, and a project with no live thread left, with everything in it,
    are marked `s` and drawn only when the page is asked to show them."""
    places = [(z.name, z) for z in visible_dirs(ws / "Zones")]
    places += [(w.name, w / "wiki") for w in visible_dirs(ws / "Wikis") if (w / "wiki").is_dir()]
    names = short_names(T)
    held = {(r["zone"], r["project"], r["thread"]) for z in T.values() for r in z["parked"]}
    awake = {(r["zone"], r["project"]) for z in T.values() for r in z["rows"]}
    asleep = {(zone, project) for zone, project, _ in held} - awake
    notes = []
    for place, root in places:
        in_zone = root.parent.name == "Zones"
        for folder, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if walked(root, folder, d, in_zone))
            for f in sorted(files):
                if not f.endswith(".md") or f == "AGENTS.md" or f.startswith((".", "_")):
                    continue
                if folder == str(root) and (f in ("index.md", "log.md") and root.name == "wiki"
                                            or f == "Todo.md" and root.parent.name == "Zones"):
                    continue
                notes.append((place, root, Path(folder) / f))
    rel = {path: path.relative_to(ws).with_suffix("").as_posix() for _, _, path in notes}
    by_rel = {r: p for p, r in rel.items()}
    nodes, index = [], {}
    kinds = [k for k, _, _ in KINDS]
    projects = [(place, path.parent.name) for place, root, path in notes
                if root.parent.name == "Zones" and path.parent.parent == root and path.stem == path.parent.name]
    threads_said = {t.casefold() for z in T.values() for r in z["rows"] + z["parked"] for t in [r["thread"]]}
    for place, root, path in notes:
        fm = frontmatter(path, ws)
        parts = path.relative_to(root).parts
        kind = as_text(fm.get("type")).strip().lower()
        kind = "mail" if kind in ("email", "mail") else kind
        in_zone = root.parent.name == "Zones"
        project = parts[0] if len(parts) > 1 and in_zone else ""
        if kind == "project" or (len(parts) == 2 and parts[1] == parts[0] + ".md"):
            kind = "project"
        elif kind in ("source", "concept", "entity", "summary") or root.parent.name == "Knowledge":
            kind = "knowledge"
        elif kind not in kinds:
            kind = "note"
        thread = parts[2] if kind == "thread" and len(parts) > 3 else ""
        state = as_text(fm.get("status")).strip().lower()
        moving = kind == "thread" and state != "done"
        updated = as_date(fm.get("updated"))
        days = (now.date() - updated).days if moving and updated else None
        party = tags(fm.get("party") or fm.get("parties"))
        folder_thread = parts[2] if in_zone and len(parts) > 3 and parts[1] == "Threads" else ""
        parked = (place, project) in asleep or (place, project, folder_thread) in held
        say = names.get((place, project, thread), "") if thread else ""
        if kind == "project" and project.casefold() not in threads_said \
                and sum(1 for _, p in projects if p.casefold() == project.casefold()) == 1:
            say = project        # "open Acme Review": the threads skill resolves a project name too
        # Short keys keep the page small. The layout adds x, y, vx, vy, ax, ay, r,
        # i, adj, deg, lp and lw to each node in the browser, so none of those is used here.
        index[path] = len(nodes)
        nodes.append({"n": as_text(fm.get("title")).strip() or path.stem, "k": kinds.index(kind), "z": place, "p": project,
                      "t": party, "d": days, "s": 1 if parked else 0,
                      "c": 1 if kind in ("project", "thread") else 0, "h": 1 if kind == "project" else 0,
                      "w": say, "u": link(path)})
    by_base: Dict[str, Path] = {}
    for p in sorted(rel, key=lambda q: len(rel[q])):
        by_base.setdefault(p.stem.lower(), p)
    edges = set()
    for _, _, path in notes:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for target in WIKILINK.findall(text):
            # In a Markdown table the alias's pipe is escaped, [[x\|alias]]: drop the backslash.
            target = target.strip().rstrip("\\").strip().rstrip("/")
            target = target[:-3] if target.endswith(".md") else target
            hit = by_rel.get(target)
            if hit is None:
                ends = [p for p, r in rel.items() if r.endswith("/" + target)]
                hit = min(ends, key=lambda q: len(rel[q])) if ends else by_base.get(target.split("/")[-1].lower())
            if hit is not None and hit != path:
                a, b = index[path], index[hit]
                edges.add((min(a, b), max(a, b)))
    used = sorted({n["k"] for n in nodes})
    return {"nodes": nodes, "edges": sorted(edges), "colors": [c for _, _, c in KINDS],
            "kinds": [[i, KINDS[i][1]] for i in used], "mode": "all" if len(nodes) <= 150 else "core"}


def launch_agents() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _int(entry: dict, key: str) -> Optional[int]:
    try:
        return int(entry[key]) if key in entry else None
    except (TypeError, ValueError):
        return None


MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
# How often a calendar entry fires, by the largest unit it names, and how long
# without a run before the job counts as late.
PERIODS = (("Month", "yearly", dt.timedelta(days=367)), ("Day", "monthly", dt.timedelta(days=32)),
           ("Weekday", "weekly", dt.timedelta(days=8)), ("Hour", "daily", dt.timedelta(days=2)),
           ("Minute", "hourly", dt.timedelta(hours=3)))


def when(p: dict) -> Tuple[str, Optional[dt.timedelta]]:
    """A launchd job's schedule in words, and how long before a missing run is
    late: the shortest wait any of its calendar entries allows."""
    if "StartInterval" in p:
        secs = _int(p, "StartInterval")
        if not secs or secs <= 0:
            return "schedule not read", None
        m = secs // 60
        return ("every %d min" % m if m < 120 else "every %d h" % (m // 60)), dt.timedelta(seconds=3 * secs)
    cal = p.get("StartCalendarInterval")
    cal = [c for c in (cal if isinstance(cal, list) else [cal]) if isinstance(c, dict)]
    if not cal:
        return "no schedule in its plist", None
    days = "Sun Mon Tue Wed Thu Fri Sat".split()
    words, kinds, late = [], [], None
    for c in cal:
        kind, wait = next(((k, w) for key, k, w in PERIODS if key in c), ("every minute", dt.timedelta(minutes=3)))
        hour, minute = _int(c, "Hour"), _int(c, "Minute") or 0
        clock = "%02d:%02d" % (hour, minute) if hour is not None else "at :%02d" % minute
        day, weekday, month = _int(c, "Day"), _int(c, "Weekday"), _int(c, "Month")
        lead = ("%d %s " % (day or 1, MONTHS[(month - 1) % 12]) if month else "day %d, " % day if day
                else days[weekday % 7] + " " if weekday is not None else "")
        words.append(lead + clock)
        kinds.append(kind)
        late = wait if late is None else min(late, wait)
    prefix = kinds[0] + " " if len(set(kinds)) == 1 else ""
    return prefix + ", ".join(words), late


def launchd_jobs(folder: Optional[Path] = None) -> Dict[str, dict]:
    """Job name -> what its launchd plist says: the schedule in words, how
    long before a missing run is late, whether it calls the assistant
    (--agent) and the environment it runs with. Only plists that run job.py;
    anything else in the folder, or a plist that does not read, is passed
    over. Elsewhere than macOS there are none, and schedules are unknown."""
    out: Dict[str, dict] = {}
    folder = folder or launch_agents()
    if not folder.is_dir():
        return out
    for plist in sorted(folder.glob("*.plist")):
        try:
            p = plistlib.loads(plist.read_bytes())
        except Exception:
            continue
        args = p.get("ProgramArguments") if isinstance(p, dict) else None
        if not isinstance(args, list):
            continue
        args = [str(a) for a in args]
        at = next((i for i, a in enumerate(args) if a.endswith("job.py")), None)
        if at is None or at + 1 >= len(args):
            continue
        flags = args[at + 2:]
        flags = flags[:flags.index("--")] if "--" in flags else flags
        env = p.get("EnvironmentVariables")
        words, late = when(p)
        out[args[at + 1]] = {"schedule": words, "late": late, "agent": "--agent" in flags,
                             "env": env if isinstance(env, dict) else {}, "plist": plist}
    return out


def history(folder: Path, name: str, now: dt.datetime) -> List[Tuple[dt.datetime, int]]:
    since = now - dt.timedelta(days=DAYS)
    runs = []
    for path in (folder / (name + ".log.1"), folder / (name + ".log")):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = LOGLINE.match(line)
            if not m:
                continue
            when = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            if when >= since:
                runs.append((when, int(m.group(3)) if m.group(3) else 75))
    return runs


def jobs(folder: Path, now: dt.datetime, sched: Optional[Dict[str, dict]] = None) -> List[dict]:
    if not folder.is_dir():
        return []
    sched = launchd_jobs() if sched is None else sched
    out = []
    for beat in sorted(folder.glob("*.heartbeat.json")):
        try:
            hb = json.loads(beat.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = hb.get("job") or beat.name[:-len(".heartbeat.json")]
        when = None
        try:
            when = dt.datetime.strptime(str(hb.get("finished"))[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
        code = int(hb.get("exit", -1)) if str(hb.get("exit", "")).lstrip("-").isdigit() else -1
        words, limit = (sched[name]["schedule"], sched[name]["late"]) if name in sched else ("schedule not found", None)
        if when and limit and now - when > limit:
            state, status = "critical", "late: last ran %s" % age(when, now)
        elif code not in OK_EXITS:
            state, status = "critical", "exit %d: %s" % (code, EXIT.get(code, "failed"))
        elif hb.get("idle_days"):
            state, status = "warning", "idle %s days" % hb["idle_days"]
        else:
            state, status = "good", "ok"
        out.append({"name": name, "when": when, "seconds": hb.get("seconds"), "state": state, "status": status,
                    "schedule": words, "runs": history(folder, name, now), "log": folder / (name + ".log")})
    return out


CAP_VARS = (("calls_day", "GARRICK_CAP_CALLS_DAY"), ("calls_hour", "GARRICK_CAP_CALLS_HOUR"), ("cost_day", "GARRICK_CAP_COST_DAY"))


def caps_in_use(agent, sched: Dict[str, dict]) -> Tuple[Dict[str, float], str]:
    """The caps the assistant's calls run under, and where the page read them.
    agent.py takes its caps from the environment of the job that calls it, so
    a scheduled job's caps are the ones in its launchd plist, and a cap the
    plist leaves out is agent.py's default. Where jobs set different caps the
    lowest is shown: it is the first to stop a call. With no plist for a job
    that calls the assistant, the caps are this environment's."""
    defaults = dict(getattr(agent, "DEFAULT_CAPS", None) or {"calls_day": 48, "calls_hour": 12, "cost_day": 20.0})

    def read(env) -> Dict[str, float]:
        out = {}
        for key, var in CAP_VARS:
            try:
                out[key] = float(env.get(var, defaults[key]))
            except (TypeError, ValueError):
                out[key] = float(defaults[key])
        return out
    calling = sorted(name for name, j in sched.items() if j.get("agent"))
    if calling:
        each = [read(sched[name]["env"]) for name in calling]
        caps = {key: min([c[key] for c in each if c[key]] or [0.0]) for key, _ in CAP_VARS}
        if len(calling) == 1:
            return caps, "Caps from the launchd plist of %s." % calling[0]
        return caps, "Caps from the launchd plists of %s; where they differ, the lowest." % (
            ", ".join(calling[:-1]) + " and " + calling[-1])
    if any(var in os.environ for _, var in CAP_VARS):
        return agent.caps(), "Caps from the GARRICK_CAP_* settings the page was built with; a scheduled job may run under others."
    return agent.caps(), "Caps are agent.py's defaults; a job that sets GARRICK_CAP_* runs under its own."


def ledger(agent, folder: Path, now: dt.datetime, sched: Optional[Dict[str, dict]] = None) -> Optional[dict]:
    path = folder / "ledger.jsonl"
    if agent is None or not path.is_file():
        return None
    entries = agent.read_ledger(path, now.timestamp(), DAYS * 24)
    caps, caps_from = caps_in_use(agent, launchd_jobs() if sched is None else sched)
    calls = [e for e in entries if not e.get("refused")]
    day = [e for e in calls if now.timestamp() - e["ts"] < 86400]
    hour = [e for e in calls if now.timestamp() - e["ts"] < 3600]
    by = {}
    for e in entries:
        j = by.setdefault(e.get("job", "?"), {"calls": 0, "cost": 0.0, "failed": 0, "refused": 0, "denied": set()})
        if e.get("refused"):
            j["refused"] += 1
            continue
        j["calls"] += 1
        j["cost"] += float(e.get("cost_usd") or 0)
        j["failed"] += 1 if e.get("exit") else 0
        j["denied"] |= set(e.get("denied") or [])
    return {"caps": caps, "caps_from": caps_from, "day": len(day), "hour": len(hour),
            "cost_day": sum(float(e.get("cost_usd") or 0) for e in day),
            "by": by, "refused_today": [e for e in entries if e.get("refused") and now.timestamp() - e["ts"] < 86400]}


# --------------------------------------------------------------------------- small helpers

def age(t: dt.datetime, now: dt.datetime) -> str:
    s = (now - t).total_seconds()
    if s < 3600:
        return "%d min ago" % max(1, s // 60)
    if s < 86400 * 2:
        return "%d h ago" % round(s / 3600)
    return "%d days ago" % round(s / 86400)


class Links:
    def __init__(self, ws: Path, vault: Optional[str]):
        self.ws, self.vault = ws, vault

    def __call__(self, path: Path) -> str:
        """A link to the file. In Obsidian a file is named by its path in the
        vault, so a note that is a symlink to a file elsewhere keeps the path
        of the link; a file outside the workspace, such as a job's log, is
        linked as a file."""
        if self.vault:
            rel = None
            for candidate in (Path(os.path.abspath(path)), path.resolve()):
                try:
                    rel = candidate.relative_to(self.ws).as_posix()
                    break
                except ValueError:
                    continue
            if rel is not None:
                rel = rel[:-3] if rel.endswith(".md") else rel
                return "obsidian://open?vault=%s&file=%s" % (urllib.parse.quote(self.vault), urllib.parse.quote(rel))
        return path.resolve().as_uri()


def day_cells(runs: List[Tuple[dt.datetime, int]], now: dt.datetime) -> List[Tuple[str, str]]:
    """One cell per day, oldest first, coloured by how the day ended: red when
    its last run failed or most runs did, amber when it failed and recovered."""
    out = []
    for i in range(DAYS - 1, -1, -1):
        day = (now - dt.timedelta(days=i)).date()
        rs = sorted(r for r in runs if r[0].date() == day)
        bad = [r for r in rs if r[1] not in OK_EXITS]
        if not rs:
            out.append(("none", "%s · no run" % day.strftime("%a %d %b")))
            continue
        ended_bad = rs[-1][1] not in OK_EXITS
        state = "critical" if ended_bad or len(bad) * 2 > len(rs) else "warning" if bad else "good"
        tip = "%s · %d run%s" % (day.strftime("%a %d %b"), len(rs), "" if len(rs) == 1 else "s")
        if bad:
            codes = sorted({r[1] for r in bad})
            tip += " · %d failed (exit %s)%s" % (len(bad), ", ".join(map(str, codes)), "" if ended_bad else " · recovered")
        else:
            tip += " · all ok"
        out.append((state, tip))
    return out


ICON = {
    "good": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="var(--good)"/><path d="M4.8 8.2l2.1 2.1 4.3-4.6" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "warning": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5l7 12.5H1z" fill="var(--warning)" stroke="var(--warning)" stroke-width="1.5" stroke-linejoin="round"/><path d="M8 6v3.6" stroke="#0b0b0b" stroke-width="1.7" stroke-linecap="round"/><circle cx="8" cy="11.9" r="1" fill="#0b0b0b"/></svg>',
    "critical": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="var(--critical)"/><path d="M5.4 5.4l5.2 5.2M10.6 5.4l-5.2 5.2" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>',
    "none": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="var(--muted)" stroke-width="1.6"/></svg>',
}
CHEV = '<svg class="chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'


def short_names(T: Dict[str, dict]) -> Dict[Tuple[str, str, str], str]:
    """The name to say for each thread, as the threads skill says it: the
    thread alone when no other thread has that name, else "project, thread",
    and the zone first as well, "zone, project, thread", when two projects
    of that name, in two zones, both have the thread. Keyed by zone, project
    and thread."""
    every = [(r["zone"], r["project"], r["thread"]) for z in T.values() for r in z["rows"] + z["parked"]]
    threads_n: Dict[str, int] = {}
    pairs_n: Dict[Tuple[str, str], int] = {}
    for _, p, t in every:
        threads_n[t.lower()] = threads_n.get(t.lower(), 0) + 1
        pairs_n[(p.lower(), t.lower())] = pairs_n.get((p.lower(), t.lower()), 0) + 1
    return {(z, p, t): (t if threads_n[t.lower()] == 1 else "%s, %s" % (p, t) if pairs_n[(p.lower(), t.lower())] == 1
                        else "%s, %s, %s" % (z, p, t)) for z, p, t in every}


def thread_card(r: dict, names: Dict[Tuple[str, str, str], str], link: "Links", days: Optional[int]) -> str:
    """What a thread's card shows, as JSON for its row: the same fields the
    graph gives a note, so one helper draws both. Names, tags, the days since
    the note was updated, whether it is parked, the name to say, and links."""
    return json.dumps({"n": r["thread"], "kl": "thread", "z": r["zone"], "p": r["project"], "t": r["party"], "d": days,
                       "s": 1 if r["status"] == "parked" else 0, "w": names[(r["zone"], r["project"], r["thread"])], "h": 0,
                       "u": link(r["note"]), "pu": link(r["hub"]) if r["hub"] else ""},
                      separators=(",", ":"), ensure_ascii=False)


def copy(label: str, text: str, say: str) -> str:
    """A button that copies a phrase for your assistant, or a command for your
    terminal. The page acts on nothing itself."""
    return '<button class="act" type="button" data-copy="%s" data-say="%s">%s</button>' % (E(text), E(say), E(label))


def script_json(data) -> str:
    """JSON safe inside a <script> element: with <, > and & written as escapes,
    no title can close the element or open a comment in it."""
    return (json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def rebuild_command(ws: Path, vault: Optional[str] = None, show_graph: bool = True, out: Optional[Path] = None) -> str:
    """The command that builds this page again, with the flags it was built
    with, absolute and quoted so it runs from any folder."""
    words = ["python3", str(Path(__file__).resolve()), "--workspace", str(ws)]
    if vault:
        words += ["--obsidian", vault]
    if not show_graph:
        words.append("--no-graph")
    if out is not None:
        words += ["--out", str(out)]
    return " ".join(shlex.quote(w) for w in words + ["--open"])


# Garrick's mark: a white Gr on brand blue, like an element tile, and a small
# "ai" in the full mark. The letters are outlines of Baskervville, a Baskerville
# revival released under the SIL Open Font License, so the page carries them as
# paths and needs no font. The favicon cut is Gr alone, larger and centred:
# the "ai" cannot be read at 16 pixels.
BRAND = "#3D73E0"
_G = ("M397 -11Q325 -11 263.5 15.5Q202 42 157.0 90.5Q112 139 87.0 204.5Q62 270 62 348Q62 427 88.0 495.5Q114 564 160.5 615.0"
      "Q207 666 269.0 695.0Q331 724 403 724Q436 724 468.0 717.5Q500 711 536 692Q558 681 570.0 677.0Q582 673 592 673Q621 673 621 710"
      "H646L644 595L646 478H621Q619 543 590.5 591.5Q562 640 513.5 667.0Q465 694 402 694Q289 694 226.5 604.0Q164 514 164 350"
      "Q164 190 224.5 104.5Q285 19 398 19Q451 19 495.0 36.5Q539 54 565.5 83.0Q592 112 592 146V174Q592 218 571.5 237.0Q551 256 496 261"
      "L453 265V289L619 285L773 289V265L728 261Q667 255 667 174V156Q667 118 689 79L703 54L680 39Q656 75 629 75Q619 75 611.5 71.5"
      "Q604 68 576 48Q533 17 490.0 3.0Q447 -11 397 -11Z")
_R = ("M28 -3V20L44 22Q77 26 92.0 33.5Q107 41 111.5 61.0Q116 81 116 121V329Q116 378 97.5 395.5Q79 413 28 413V436Q68 436 105.5 439.0"
      "Q143 442 186 448L175 333H186V121Q186 81 190.5 61.0Q195 41 210.5 33.5Q226 26 258 22L274 20V-3L151 0ZM184 269 173 312"
      "Q194 391 228.0 422.5Q262 454 304 454Q344 454 358.0 434.0Q372 414 372 394Q372 372 359.0 358.0Q346 344 323 344Q305 344 293.0 353.5"
      "Q281 363 281 378Q281 383 282.0 387.0Q283 391 284 398Q285 402 285.5 405.0Q286 408 286 410Q286 420 272 420Q254 420 236.5 399.5"
      "Q219 379 205.0 345.0Q191 311 184 269Z")
_A = ("M405 -11Q362 -11 343.5 16.0Q325 43 325 104V320Q325 379 302.5 404.0Q280 429 227 429Q191 429 169.5 420.0Q148 411 148 396"
      "Q148 392 149.5 387.5Q151 383 152 377Q157 357 157 349Q157 333 144.5 321.5Q132 310 112 310Q93 310 81.0 323.5Q69 337 69 358"
      "Q69 386 91.5 407.5Q114 429 153.5 441.5Q193 454 244 454Q323 454 359.0 416.5Q395 379 395 296V116Q395 65 403.0 44.5Q411 24 430 24"
      "Q444 24 455.5 33.5Q467 43 472 59L490 52Q472 -11 405 -11ZM163 -11Q112 -11 81.0 14.0Q50 39 50 79Q50 117 81.0 151.5Q112 186 180 223"
      "Q210 240 247.0 256.5Q284 273 329 289L330 270Q233 230 180.5 182.0Q128 134 128 87Q128 58 145.0 42.0Q162 26 193 26Q221 26 248.5 40.5"
      "Q276 55 297.5 78.5Q319 102 328 130L334 97Q309 47 263.5 18.0Q218 -11 163 -11Z")
_I = ("M28 -3V20L44 22Q77 26 92.0 33.5Q107 41 111.5 61.0Q116 81 116 121V332Q116 377 98.0 395.0Q80 413 35 413H28V436Q78 436 114.5 438.5"
      "Q151 441 186 448V121Q186 81 190.5 61.0Q195 41 210.5 33.5Q226 26 258 22L274 20V-3L151 0ZM132 554Q106 554 91.0 572.0Q76 590 76 615"
      "Q76 641 91.0 658.5Q106 676 132 676Q161 676 174.5 658.5Q188 641 188 615Q188 590 174.5 572.0Q161 554 132 554Z")


def mark(full: bool = True, attrs: str = "", image: bool = False) -> str:
    """The mark as SVG: the full one with "ai", or the favicon cut. An SVG
    used as an image needs its namespace; one inside the page does not."""
    glyphs = ([(_G, 8.28, 48.54, 0.04384), (_R, 42.69, 48.54, 0.04384), (_A, 50.99, 60.86, 0.01310), (_I, 57.41, 60.86, 0.01310)]
              if full else [(_G, 2.08, 49.50, 0.04910), (_R, 40.62, 49.50, 0.04910)])
    paths = "".join('<path d="%s" fill="#fff" transform="translate(%.2f %.2f) scale(%.5f -%.5f)"/>' % (d, x, y, k, k)
                    for d, x, y, k in glyphs)
    return ('<svg viewBox="0 0 64 64"%s%s><rect width="64" height="64" rx="3.5" fill="%s"/>%s</svg>'
            % (' xmlns="http://www.w3.org/2000/svg"' if image else "", attrs, BRAND, paths))


def favicon() -> str:
    """The tab icon, carried in the page as a data URI: nothing is fetched."""
    return '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%s">' % urllib.parse.quote(mark(full=False, image=True), safe="")


GRIP = ('<svg viewBox="0 0 16 16" aria-hidden="true"><g fill="currentColor"><circle cx="6" cy="4" r="1.2"/><circle cx="10" cy="4" r="1.2"/>'
        '<circle cx="6" cy="8" r="1.2"/><circle cx="10" cy="8" r="1.2"/><circle cx="6" cy="12" r="1.2"/><circle cx="10" cy="12" r="1.2"/></g></svg>')
CLOSE = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'


def card(id_: str, title: str, meta: str, body: str, open_: bool = True, fixed: bool = False) -> str:
    """A folding card. Unless fixed, its header has a grip to drag it elsewhere
    and a button to hide it; the browser remembers both."""
    tools = "" if fixed else ('<span class="tools"><span class="grip" draggable="true" title="Drag to move" aria-hidden="true">%s</span>'
                              '<button class="hide" type="button" title="Hide this card" aria-label="Hide %s">%s</button></span>' % (GRIP, E(title), CLOSE))
    return ('<details class="card" id="%s"%s><summary class="head">%s<h2>%s</h2><span class="meta">%s</span>%s</summary>'
            '<div class="body">%s</div></details>' % (id_, " open" if open_ else "", CHEV, E(title), E(meta), tools, body))


def meter(value: float, cap: float, label: str, right: str) -> str:
    pct = 0 if not cap else min(100.0, value / cap * 100)
    kind = "critical" if pct >= 90 else "warning" if pct >= 70 else ""
    return ('<div class="m"><span class="ink2">%s</span><span class="num">%s</span><div class="meter %s"><i style="width:%.1f%%"></i></div></div>'
            % (E(label), E(right), kind, pct))


# --------------------------------------------------------------------------- the page

CSS = r"""
:root{color-scheme:light;--display:"Baskervville","Libre Baskerville",Baskerville,"Baskerville Old Face",Georgia,serif;--page:#f4f3f0;--side:#ecebe6;--surface:#fcfcfb;--raise:#fff;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--line:rgba(11,11,11,.10);--grid:#e1e0d9;--base:#c3c2b7;--accent:#3d73e0;--track:#cfdcf7;--wash:rgba(61,115,224,.10);
--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--none:#e6e5df;--shadow:0 1px 2px rgba(11,11,11,.04),0 4px 16px rgba(11,11,11,.04)}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;--side:#131312;--surface:#1a1a19;--raise:#211f1e;
--ink:#fff;--ink2:#c3c2b7;--line:rgba(255,255,255,.10);--grid:#2c2c2a;--base:#383835;--accent:#6590e6;--track:#112e6a;--wash:rgba(101,144,230,.14);--none:#2a2a28;--shadow:none}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--side:#131312;--surface:#1a1a19;--raise:#211f1e;
--ink:#fff;--ink2:#c3c2b7;--line:rgba(255,255,255,.10);--grid:#2c2c2a;--base:#383835;--accent:#6590e6;--track:#112e6a;--wash:rgba(101,144,230,.14);--none:#2a2a28;--shadow:none}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline;text-underline-offset:2px}
.app{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh}
aside{position:sticky;top:0;height:100vh;overflow:auto;background:var(--side);border-right:1px solid var(--line);padding:22px 14px;display:flex;flex-direction:column;gap:18px}
.brand{display:flex;align-items:center;gap:10px;padding:0 8px}.brand .mark{width:34px;height:34px;flex:none;display:block}.brand h1{font:600 18px/1.15 var(--display);margin:0;letter-spacing:.005em}.brand p{margin:2px 0 0;color:var(--muted);font-size:12px}
.overall{display:flex;align-items:center;gap:10px;padding:10px;border-radius:10px;background:var(--surface);border:1px solid var(--line)}
.overall svg{width:22px;height:22px;flex:none}.overall b{display:block;font-size:13px}.overall span{color:var(--ink2);font-size:12px}
nav{display:flex;flex-direction:column;gap:1px}
nav a{display:flex;align-items:center;gap:9px;padding:7px 10px;border-radius:8px;color:var(--ink2);font-size:13px}
nav a:hover{background:var(--wash);text-decoration:none;color:var(--ink)}nav a.on{background:var(--surface);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line)}
nav a .n{margin-left:auto;font-size:11px;color:var(--muted)}nav .sub{padding-left:28px;font-size:12px}
.dot{width:8px;height:8px;border-radius:50%;flex:none;background:var(--none)}.dot.good{background:var(--good)}.dot.warning{background:var(--warning)}.dot.critical{background:var(--critical)}
.controls{margin-top:auto;display:flex;flex-direction:column;gap:10px;padding:0 6px}
.switch{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--ink2);cursor:pointer}
.switch input{appearance:none;width:30px;height:18px;border-radius:9px;background:var(--base);position:relative;cursor:pointer;margin:0}
.switch input::after{content:"";position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:#fff;transition:left .15s}
.switch input:checked{background:var(--accent)}.switch input:checked::after{left:14px}
.seg{display:flex;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:2px}
.seg button{flex:1;border:0;background:none;color:var(--ink2);font:inherit;font-size:12px;padding:4px 0;border-radius:6px;cursor:pointer}.seg button.on{background:var(--wash);color:var(--ink)}
main{padding:26px 30px 80px;min-width:0}
.stale{display:none;margin:0 0 16px;padding:10px 14px;border-radius:10px;background:var(--surface);border:1px solid var(--critical);font-weight:600}
.top{display:grid;grid-template-columns:minmax(220px,1.1fr) repeat(4,minmax(140px,1fr));gap:14px;margin-bottom:18px}
.hero,.tile{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:var(--shadow);min-width:0}
.hero{display:flex;flex-direction:column;justify-content:space-between}
.hero .fig{font:600 52px/1 var(--display);letter-spacing:-.01em;display:flex;align-items:center;gap:12px}.hero .fig svg{width:28px;height:28px}
.hero .lbl,.tile .lbl{color:var(--ink2);font-size:12px}.hero .lbl{font-size:14px;margin-top:6px}
.tile .val{font-size:26px;font-weight:620;letter-spacing:-.02em;margin:4px 0 8px;display:flex;align-items:baseline;gap:8px}
.tile .val small{font-size:12px;font-weight:500;color:var(--muted)}.tile .sub{font-size:12px;color:var(--muted);margin-top:6px}
.meter{height:6px;border-radius:3px;background:var(--track);overflow:hidden}.meter i{display:block;height:100%;border-radius:3px;background:var(--accent)}
.meter.warning i{background:var(--warning)}.meter.critical i{background:var(--critical)}
.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:16px;align-items:start}
.full{grid-column:span 12}.stack{grid-column:span 5;display:flex;flex-direction:column;gap:16px;min-width:0}.stack.left{grid-column:span 7}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);min-width:0;scroll-margin-top:16px}
summary{list-style:none;cursor:pointer}summary::-webkit-details-marker{display:none}
.head{display:flex;align-items:center;gap:10px;padding:14px 16px}.head h2{font:600 16px/1.2 var(--display);margin:0}
.head .meta{color:var(--muted);font-size:12px;margin-left:auto;text-align:right}
.chev{width:16px;height:16px;flex:none;color:var(--muted);transition:transform .15s}details[open]>summary .chev{transform:rotate(90deg)}
.body{padding:0 16px 16px}.muted{color:var(--muted)}.ink2{color:var(--ink2)}.num{font-variant-numeric:tabular-nums}
.row{display:grid;align-items:center;gap:12px;padding:8px 2px;border-top:1px solid var(--grid)}.rows>.row:first-child{border-top:0}
.jobs .row{grid-template-columns:18px minmax(0,1fr) 180px 86px 140px}.jobs .row .status{overflow:hidden;text-overflow:ellipsis}
.row>svg,.item>svg{width:16px;height:16px}
.name{font-weight:560;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.name small{display:block;font-weight:400;color:var(--muted);font-size:12px}
.strip{display:flex;gap:2px}.strip i{width:11px;height:18px;border-radius:3px;background:var(--none);flex:none}
.strip i.good{background:var(--good)}.strip i.warning{background:var(--warning)}.strip i.critical{background:var(--critical)}.strip i:hover,.strip i:focus{outline:2px solid var(--ink)}
.status{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--ink2);white-space:nowrap}.status svg{width:14px;height:14px;flex:none}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px;color:var(--muted);font-size:12px}.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{width:10px;height:10px;border-radius:2px;background:var(--none)}.legend i.good{background:var(--good)}.legend i.warning{background:var(--warning)}.legend i.critical{background:var(--critical)}
.attn{display:flex;flex-direction:column;gap:6px}.attn a{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:10px;background:var(--raise);border:1px solid var(--line)}
.attn a:hover{text-decoration:none;border-color:var(--base)}.attn svg{width:16px;height:16px;flex:none}
.zones{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:0 22px}
.zone>summary{display:flex;align-items:baseline;gap:8px;padding:10px 0 8px}
.zone>summary h3{margin:0;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink2)}.zone>summary .meta{margin-left:auto;font-size:12px;color:var(--muted)}
.thread{display:grid;grid-template-columns:minmax(0,1fr) 80px 34px;align-items:center;gap:10px;padding:6px 0;border-top:1px solid var(--grid);font-size:13px}
.thread .t{min-width:0}.thread .t a{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.thread .t small{display:block;color:var(--muted);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip{display:inline-flex;align-items:center;font-size:11px;padding:0 6px;border-radius:999px;border:1px solid var(--line);color:var(--ink2);margin-left:4px}
.fresh{height:6px;border-radius:3px;background:var(--grid);position:relative}.fresh i{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:var(--good)}
.fresh.warning i{background:var(--warning)}.fresh.critical i{background:var(--critical)}
.group>summary{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;font-size:13px}.group>summary:hover{background:var(--wash)}
.group>summary .counts{margin-left:auto;display:flex;gap:6px}
.group ul{list-style:none;margin:2px 0 8px;padding:0 0 0 32px}.group li{display:flex;gap:8px;padding:5px 0;color:var(--ink2);font-size:12.5px;border-top:1px solid var(--grid)}
.group li:first-child{border-top:0}.group li svg{width:14px;height:14px;flex:none;margin-top:2px}
.clean{display:flex;align-items:center;gap:8px;color:var(--ink2);padding:8px 2px}.clean svg{width:16px;height:16px}
.bullet{display:grid;grid-template-columns:110px minmax(0,1fr) 40px;align-items:center;gap:10px;font-size:12.5px;padding:5px 0}
.bar{position:relative;height:10px;background:var(--track);border-radius:3px}.bar i{position:absolute;left:0;top:0;bottom:0;background:var(--accent);border-radius:3px}
.tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.item{display:flex;align-items:center;gap:9px;padding:8px 10px;border-radius:10px;background:var(--raise);border:1px solid var(--line);min-width:0}
.meters{display:flex;flex-direction:column;gap:12px}.meters .m{display:grid;grid-template-columns:1fr auto;gap:4px 10px;font-size:12px}.meters .m .meter{grid-column:1/-1}
table{border-collapse:collapse;width:100%;font-size:12.5px}th{text-align:left;color:var(--muted);font-weight:500;font-size:11.5px;padding:6px;border-bottom:1px solid var(--grid)}
td{padding:6px;border-bottom:1px solid var(--grid)}tr:last-child td{border-bottom:0}th.r,td.r{text-align:right;font-variant-numeric:tabular-nums}.scroll{overflow-x:auto}
.thread{border-radius:6px;transition:background .1s}.thread:hover,.thread.on{background:var(--wash)}
.act{font:inherit;font-size:11px;font-weight:560;line-height:1;padding:5px 8px;border-radius:7px;border:1px solid var(--line);background:var(--raise);color:var(--ink2);white-space:nowrap;cursor:pointer}
.act:hover{color:var(--ink);border-color:var(--base)}.act.wide{display:block;width:100%;padding:8px;font-size:12px}
.parked>summary{display:flex;align-items:center;gap:6px;padding:8px 0 4px;font-size:12px;color:var(--muted)}.parked>summary .n{margin-left:auto}
.parked .chev{width:13px;height:13px}.parked .thread{opacity:.8}
#toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--ink);color:var(--surface);font-size:13px;padding:9px 14px;border-radius:10px;opacity:0;transition:opacity .15s;pointer-events:none;z-index:10;max-width:90vw}
@media (hover:none){.head .tools{opacity:1}}
#tip{position:fixed;pointer-events:none;z-index:9;background:var(--ink);color:var(--surface);font-size:12px;padding:6px 9px;border-radius:7px;max-width:280px;opacity:0}
.only [data-ok="1"]{display:none}
.only .rows:not(:has([data-ok="0"]))::after,.only .zone:not(:has([data-ok="0"]))::after,.only .tiles:not(:has([data-ok="0"]))::after{content:"Nothing wrong here.";display:block;color:var(--muted);font-size:12px;padding:8px 2px}
.slot{display:flex;flex-direction:column;gap:16px;min-width:0}.slot.full{grid-column:span 12}.slot .card{grid-column:auto}
.slot:not(:has(>.card:not([hidden]))){display:none}
.grid:not(:has(.stack.right>.card:not([hidden]))) .stack.left,.grid:not(:has(.stack.left>.card:not([hidden]))) .stack.right{grid-column:span 12}
.stack .zones{grid-template-columns:1fr}[hidden]{display:none!important}
.head .tools{display:flex;gap:2px;align-items:center;opacity:0;transition:opacity .12s;margin-left:2px}
.head:hover .tools,.head:focus-within .tools{opacity:1}
.grip,.hide{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;color:var(--muted);border:0;background:none;padding:0;cursor:pointer}
.grip{cursor:grab}.grip:hover,.hide:hover{background:var(--wash);color:var(--ink)}.grip svg,.hide svg{width:14px;height:14px}
.dragging .slot{display:flex!important;min-height:64px;border-radius:14px;outline:2px dashed var(--grid);outline-offset:4px}
.ph{border:2px dashed var(--accent);border-radius:14px;background:var(--wash);flex:none}.card.lifted{display:none}
nav a.off{opacity:.45}nav a.off::after{content:"hidden";margin-left:6px;font-size:10.5px;color:var(--muted)}
.hint{font-size:11.5px;color:var(--muted);margin:0}
.zt{display:flex;align-items:baseline;gap:8px;margin:8px 0 2px}.zt .act{margin-left:auto;align-self:center}a.act:hover{text-decoration:none}
.gwrap{position:relative;height:560px;border-radius:10px;background:var(--raise);border:1px solid var(--line);overflow:hidden}
.gwrap canvas{display:block;width:100%;height:100%;touch-action:none;cursor:grab}.gwrap canvas.drag{cursor:grabbing}.gwrap canvas.hot{cursor:pointer}
.gbar{position:absolute;left:10px;top:10px;right:10px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;pointer-events:none}.gbar>*{pointer-events:auto}
.gbar .gseg{display:flex;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:2px}
.gbar button{border:0;background:none;color:var(--ink2);font:inherit;font-size:12px;padding:4px 9px;border-radius:6px;cursor:pointer}
.gbar button.on{background:var(--wash);color:var(--ink)}.gbar>button{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:5px 9px}
.gpop,.tcard{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px;box-shadow:0 6px 24px rgba(0,0,0,.14);font-size:12.5px}
.gpop{position:absolute;right:10px;top:10px;width:290px;max-height:calc(100% - 20px);overflow:auto}
.tcard{position:fixed;left:0;top:0;width:300px;max-width:calc(100vw - 16px);z-index:9}
.gpop h4,.tcard h4{margin:0 22px 2px 0;font-size:14px;font-weight:640;overflow-wrap:anywhere}.tcard h4{margin-right:0}
.gpop .x{position:absolute;right:8px;top:6px;border:0;background:none;color:var(--muted);font-size:18px;line-height:1;cursor:pointer;padding:2px 4px}
.gacts{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 4px}.gacts a.act:hover{text-decoration:none}
.gpop .glinks{display:flex;flex-direction:column;margin-top:8px;border-top:1px solid var(--grid);padding-top:6px}
.gpop .glinks button{display:flex;align-items:center;gap:7px;text-align:left;border:0;background:none;color:var(--ink2);font:inherit;font-size:12.5px;padding:4px;border-radius:6px;cursor:pointer}
.gpop .glinks button:hover{background:var(--wash);color:var(--ink)}.gpop .glinks i{width:8px;height:8px;border-radius:50%;flex:none}
.gpop .glinks span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gpop .glinks small{white-space:nowrap;font-size:11px}
.legend i.ring{background:none;border-radius:50%;border:2px solid}
@media (max-width:1180px){.top{grid-template-columns:repeat(2,minmax(0,1fr))}.hero{grid-column:span 2}.stack,.stack.left{grid-column:span 12}}
@media (max-width:820px){.app{grid-template-columns:1fr}aside{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line)}nav{flex-direction:row;flex-wrap:wrap}nav .sub{display:none}.controls{margin-top:0}main{padding:16px}
.jobs .row{grid-template-columns:18px minmax(0,1fr) auto}.jobs .row>:nth-child(4){display:none}.jobs .row .strip{grid-column:2/-1;grid-row:2}.tiles{grid-template-columns:1fr}
.gwrap{height:440px}.gpop{left:10px;right:10px;top:auto;bottom:10px;width:auto;max-height:55%}}
"""

# What a note's panel in the graph and a thread's card in the list both show,
# built in one place, so the two offer the same actions under the same labels.
# Each action opens a file or copies a phrase; none acts on the workspace.
PANEL_JS = r"""
var Panel=(function(){
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function copy(p){return'<button class="act" type="button" data-copy="'+esc(p)+'" data-say="'+esc('Copied “'+p+'”. Paste it to your assistant.')+'">Copy “'+esc(p)+'”</button>'}
function acts(o){var a='<a class="act" href="'+esc(o.u)+'">Open</a>';if(o.pu)a+='<a class="act" href="'+esc(o.pu)+'">Open project</a>';
if(o.w){a+=copy('open '+o.w);if(!o.h)a+=copy((o.s?'wake ':'park ')+o.w)}return'<div class="gacts">'+a+'</div>'}
function ago(d){return d===0?'today':d===1?'yesterday':d+' days ago'}
function state(o){if(o.s)return'Parked'+(o.d!=null?', updated '+ago(o.d):'');if(o.d==null)return'';
return o.d>45?'Untouched for '+o.d+' days':(o.d>14?'Aging: updated ':'Updated ')+ago(o.d)}
function head(o){var s=state(o);return'<h4>'+esc(o.n)+'</h4><div class="muted">'+esc([o.kl,o.z,o.p].filter(Boolean).join(' · '))+'</div>'
+(o.t&&o.t.length?'<div style="margin-top:4px">'+o.t.map(function(t){return'<span class="chip" style="margin:0 4px 0 0">'+esc(t)+'</span>'}).join('')+'</div>':'')
+(s?'<div class="ink2" style="margin-top:4px">'+esc(s)+'</div>':'')}
return{esc:esc,acts:acts,head:head}})();
"""

JS = r"""
(function(){var root=document.documentElement,st={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
function theme(t){if(t==='auto')root.removeAttribute('data-theme');else root.setAttribute('data-theme',t);document.querySelectorAll('.seg button').forEach(function(b){b.classList.toggle('on',b.dataset.t===t)});st.set('garrick-status-theme',t)}
theme(st.get('garrick-status-theme')||'auto');document.querySelectorAll('.seg button').forEach(function(b){b.onclick=function(){theme(b.dataset.t)}});
var only=document.getElementById('only');only.checked=st.get('garrick-status-only')==='1';function apply(){document.body.classList.toggle('only',only.checked);st.set('garrick-status-only',only.checked?'1':'0')}only.onchange=apply;apply();
document.querySelectorAll('details[id]').forEach(function(d){var s=st.get('garrick-fold-'+d.id);if(s==='0')d.open=false;if(s==='1')d.open=true;d.addEventListener('toggle',function(){st.set('garrick-fold-'+d.id,d.open?'1':'0')})});
var h=(Date.now()-new Date(document.body.dataset.built))/36e5,el=document.getElementById('age');if(el)el.textContent=h<1?Math.max(1,Math.round(h*60))+' min ago':h<48?Math.round(h)+' h ago':Math.round(h/24)+' days ago';
if(h>36){var s=document.getElementById('stale');s.style.display='block';s.textContent='Built '+Math.round(h)+' hours ago, so it may be out of date. Run status.py again to refresh it.'}
var tip=document.getElementById('tip');function show(e){var t=e.target.closest&&e.target.closest('[data-tip]');if(!t){tip.style.opacity=0;return}tip.textContent=t.dataset.tip;tip.style.opacity=1;
var r=t.getBoundingClientRect(),x=e.type==='focusin'?r.left+r.width/2:e.clientX,y=e.type==='focusin'?r.top:e.clientY,w=tip.offsetWidth;tip.style.left=Math.min(innerWidth-w-8,Math.max(8,x-w/2))+'px';tip.style.top=(y-tip.offsetHeight-12)+'px'}
document.addEventListener('mousemove',show);document.addEventListener('focusin',show);document.addEventListener('scroll',function(){tip.style.opacity=0},true);
var toast=document.getElementById('toast');function say(s){toast.textContent=s;toast.style.opacity=1;clearTimeout(say.t);say.t=setTimeout(function(){toast.style.opacity=0},2600)}
function put(text){if(navigator.clipboard&&window.isSecureContext){return navigator.clipboard.writeText(text)}var a=document.createElement('textarea');a.value=text;a.style.position='fixed';a.style.opacity=0;document.body.appendChild(a);a.select();try{document.execCommand('copy')}finally{document.body.removeChild(a)}return Promise.resolve()}
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('button[data-copy]');if(b)put(b.dataset.copy).then(function(){say(b.dataset.say)},function(){say(b.dataset.copy)})});
/* A thread's card: opens under its row on hover, or on focus from the keyboard,
   with what the graph panel shows for that note. It is fixed, so a scrolled
   page cannot push it out of view, and overlaps its row by a pixel, so the
   pointer never falls into a gap on the way in. While one is open, another
   row takes over only after a dwell, so the pointer can cross rows to reach it. */
var tc=document.createElement('div'),tRow=null,tHide=0,tShow=0,tQuiet=false;tc.className='tcard';tc.id='tcard';tc.hidden=true;
function tPlace(){if(!tRow)return;var b=tRow.getBoundingClientRect();if(b.bottom<0||b.top>innerHeight){tClose();return}
var w=tc.offsetWidth,h=tc.offsetHeight,x=Math.min(b.right-w,innerWidth-w-8),y=b.bottom-1;if(y+h>innerHeight-8&&b.top-h+1>=8)y=b.top-h+1;
tc.style.left=Math.max(8,x)+'px';tc.style.top=Math.max(8,y)+'px'}
function tOpen(row){clearTimeout(tHide);clearTimeout(tShow);if(tRow!==row){var o;try{o=JSON.parse(row.dataset.card)}catch(x){return}
if(tRow)tRow.classList.remove('on');tRow=row;row.classList.add('on');tc.innerHTML=Panel.head(o)+Panel.acts(o);tc.setAttribute('aria-label',o.n);
row.parentNode.insertBefore(tc,row.nextSibling)}tc.hidden=false;tPlace()}
function tClose(){clearTimeout(tShow);clearTimeout(tHide);if(tRow)tRow.classList.remove('on');tRow=null;tc.hidden=true}
function tLater(){clearTimeout(tShow);clearTimeout(tHide);tHide=setTimeout(tClose,220)}
document.querySelectorAll('.thread[data-card]').forEach(function(row){
row.addEventListener('mouseenter',function(){clearTimeout(tHide);clearTimeout(tShow);if(tRow===row&&!tc.hidden)return;tShow=setTimeout(function(){tOpen(row)},tRow&&!tc.hidden?350:150)});
row.addEventListener('mouseleave',tLater);
row.addEventListener('focusin',function(){if(tQuiet){tQuiet=false;return}tOpen(row)});
row.addEventListener('click',function(e){if(e.target.closest('a,button'))return;if(tRow===row&&!tc.hidden)tClose();else tOpen(row)})});
tc.addEventListener('mouseenter',function(){clearTimeout(tHide);clearTimeout(tShow)});tc.addEventListener('mouseleave',tLater);
document.addEventListener('focusin',function(e){if(tRow&&!tRow.contains(e.target)&&!tc.contains(e.target))tClose()});
document.addEventListener('keydown',function(e){if(e.key!=='Escape'||!tRow)return;var r=tRow,back=tc.contains(document.activeElement);tClose();
if(back){var a=r.querySelector('a');if(a){tQuiet=true;a.focus()}}});
window.addEventListener('scroll',function(){if(tRow)requestAnimationFrame(tPlace)},{passive:true});window.addEventListener('resize',function(){if(tRow)tPlace()});
var links={};document.querySelectorAll('nav a[href^="#"]').forEach(function(a){links[a.getAttribute('href').slice(1)]=a});
if('IntersectionObserver' in window){var io=new IntersectionObserver(function(es){es.forEach(function(x){if(x.isIntersecting&&links[x.target.id]){Object.keys(links).forEach(function(k){links[k].classList.remove('on')});links[x.target.id].classList.add('on')}})},{rootMargin:'-20% 0px -70% 0px'});Object.keys(links).forEach(function(id){var t=document.getElementById(id);if(t)io.observe(t)})}
})();
"""


# Where each card sits and which are hidden: a view preference like the theme
# and the folds, kept in the browser and nowhere else. A card the stored
# layout does not know stays where the page put it.
LAYOUT_JS = r"""
(function(){
var KEY='garrick-status-layout',st={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
var slots={};document.querySelectorAll('[data-slot]').forEach(function(s){slots[s.dataset.slot]=s});
function cards(){return Array.prototype.slice.call(document.querySelectorAll('[data-slot]>.card[id]'))}
function inSlot(el){return el&&el.parentNode&&el.parentNode.hasAttribute&&el.parentNode.hasAttribute('data-slot')}
var L=null;try{L=JSON.parse(st.get(KEY)||'null')}catch(e){}
if(L&&L.v===1){Object.keys(L.c||{}).forEach(function(k){var s=slots[k];if(s)(L.c[k]||[]).forEach(function(id){var el=document.getElementById(id);if(inSlot(el))s.appendChild(el)})});
(L.h||[]).forEach(function(id){var el=document.getElementById(id);if(inSlot(el))el.hidden=true})}
function save(){var c={};Object.keys(slots).forEach(function(k){c[k]=Array.prototype.slice.call(slots[k].children).filter(function(e){return e.classList.contains('card')}).map(function(e){return e.id})});
st.set(KEY,JSON.stringify({v:1,c:c,h:cards().filter(function(e){return e.hidden}).map(function(e){return e.id})}));sync()}
function sync(){var h=cards().filter(function(e){return e.hidden});
document.querySelectorAll('nav a[href^="#"]').forEach(function(a){var t=document.getElementById(a.getAttribute('href').slice(1)),c=t&&t.closest('.card');a.classList.toggle('off',!!(c&&c.hidden))});
var n=document.getElementById('hidden-note');if(n){n.hidden=!h.length;n.textContent=h.length+' card'+(h.length>1?'s':'')+' hidden. Click one in the list above to bring it back.'}}
function toast(t){var el=document.getElementById('toast');if(!el)return;el.textContent=t;el.style.opacity=1;setTimeout(function(){el.style.opacity=0},2600)}
document.addEventListener('click',function(e){
var b=e.target.closest('.head .hide,.head .grip');if(b){e.preventDefault();e.stopPropagation();
if(b.classList.contains('hide')){var c=b.closest('.card');c.hidden=true;save();toast(c.querySelector('h2').textContent+' hidden. Bring it back from the sidebar, or Reset view.')}return}
var a=e.target.closest('nav a[href^="#"]');if(a){var t=document.getElementById(a.getAttribute('href').slice(1)),c=t&&t.closest('.card');if(c&&c.hidden){c.hidden=false;c.open=true;save()}}},true);
var drag=null,ph=document.createElement('div');ph.className='ph';
document.addEventListener('dragstart',function(e){var g=e.target.closest&&e.target.closest('.grip');if(!g)return;drag=g.closest('.card');
e.dataTransfer.effectAllowed='move';try{e.dataTransfer.setData('text/plain',drag.id);e.dataTransfer.setDragImage(drag.querySelector('summary'),24,20)}catch(x){}
ph.style.height=Math.min(drag.offsetHeight,140)+'px';
setTimeout(function(){if(!drag)return;document.body.classList.add('dragging');drag.parentNode.insertBefore(ph,drag);drag.classList.add('lifted')},0)});
document.addEventListener('dragover',function(e){if(!drag)return;var s=e.target.closest&&e.target.closest('[data-slot]');if(!s)return;e.preventDefault();e.dataTransfer.dropEffect='move';
var before=null;Array.prototype.forEach.call(s.children,function(c){if(before||c===ph||c===drag||c.hidden||!c.classList.contains('card'))return;var r=c.getBoundingClientRect();if(e.clientY<r.top+r.height/2)before=c});
if(before){if(ph.nextSibling!==before)s.insertBefore(ph,before)}else if(s.lastElementChild!==ph)s.appendChild(ph)});
document.addEventListener('drop',function(e){if(!drag)return;e.preventDefault();if(ph.parentNode)ph.parentNode.insertBefore(drag,ph);end();save()});
document.addEventListener('dragend',function(){if(drag)end()});
function end(){document.body.classList.remove('dragging');if(drag)drag.classList.remove('lifted');if(ph.parentNode)ph.parentNode.removeChild(ph);drag=null}
var r=document.getElementById('reset-view');if(r)r.onclick=function(){try{var ks=[];for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);
if(k.indexOf('garrick-')===0&&k!=='garrick-status-theme')ks.push(k)}ks.forEach(function(k){localStorage.removeItem(k)})}catch(x){}
try{history.replaceState(null,'',location.pathname+location.search)}catch(x){}location.reload()};
sync();
})();
"""

# The graph: a force layout on a canvas, written here because the page loads
# nothing from the network. Each zone and wiki has its own spot, laid along the
# card in its proportions, so a zone reads as a cluster and the notes fill the
# card. It sways a few degrees when left alone and stops for a hover, a drag,
# an open panel, or the system's reduced-motion setting.
GRAPH_JS = r"""
(function(){
var src=document.getElementById('graph-data'),cv=document.getElementById('gcv');if(!src||!cv)return;
var G=JSON.parse(src.textContent),wrap=cv.parentNode,ctx=cv.getContext('2d'),pop=document.getElementById('gpop');
var st={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
var reduce=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
var mode=st.get('garrick-graph-mode')||G.mode,spin=!reduce&&st.get('garrick-graph-spin')!=='0',parked=st.get('garrick-graph-parked')==='1';
var N=G.nodes,hubOf={},seed=7;function rnd(){seed=(seed*16807)%2147483647;return seed/2147483647}
N.forEach(function(n,i){n.i=i;n.adj=[];if(n.h)hubOf[n.z+'/'+n.p]=n});
G.edges.forEach(function(e){N[e[0]].adj.push(e[1]);N[e[1]].adj.push(e[0])});
var places=[];N.forEach(function(n){if(places.indexOf(n.z)<0)places.push(n.z);n.r=(n.h?7:n.c?5:4)+Math.min(5,Math.sqrt(n.adj.length)*.8)});
var V=[],E=[],alpha=1,theta=0,phase=0,SWAY=.1,pull=1.4,ticks=0,scale=1,px=0,py=0,auto=true,hover=null,sel=null,drag=null,W=0,H=0,dpr=1,asp=2,running=false,shown=false,glides=0,last=0,idle=0,C={},bar=wrap.querySelector('.gbar'),top=58;
/* Where each zone and wiki sits: its notes are drawn toward that spot. A few
   places that fit across the card go in a row, more go round an ellipse in the
   card's proportions, each given room by how many notes it draws, and in the
   order that keeps linked places next to each other. */
function room(k){return 30*Math.sqrt(k)+20}
function spots(nodes,links){var cnt={},live=[],w={},A={};nodes.forEach(function(n){cnt[n.z]=(cnt[n.z]||0)+1});
places.forEach(function(p){if(cnt[p])live.push(p)});links.forEach(function(e){var a=N[e[0]].z,b=N[e[1]].z;if(a!==b)w[a+'\n'+b]=w[b+'\n'+a]=(w[a+'\n'+b]||0)+1});
if(!live.length)return A;if(live.length===1){A[live[0]]=[0,0];return A}
var long=Math.max(asp,1/asp),gap=40,sum=0,big=0;live.forEach(function(p){var r=room(cnt[p]);sum+=2*r;big=Math.max(big,r)});
var row=live.length<=3&&(sum+gap*(live.length-1))/(2*big)<=long*1.25;
live=order(live,w,row);
if(row){var x=-(sum+gap*(live.length-1))/2;live.forEach(function(p){var r=room(cnt[p]);x+=r;A[p]=asp>=1?[x,0]:[0,x];x+=r+gap});return A}
var rm=sum/2/live.length,k=rm,a,b,per;
for(var i=0;i<80;i++){a=asp>=1?k*asp+(asp-1)*rm:k;b=asp>=1?k:k/asp+(1/asp-1)*rm;
per=Math.PI*(3*(a+b)-Math.sqrt((3*a+b)*(a+3*b)));if(per>=sum*1.15)break;k*=1.08}
var M=720,cum=[0],pts=[];for(i=0;i<=M;i++){var t=Math.PI+i/M*6.2832;pts.push([a*Math.cos(t),b*Math.sin(t)]);if(i)cum.push(cum[i-1]+Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1]))}
var at=-room(cnt[live[0]])/sum*cum[M],j=0;
live.forEach(function(p){var share=2*room(cnt[p])/sum*cum[M],s=((at+share/2)%cum[M]+cum[M])%cum[M];at+=share;
for(j=0;j<M&&cum[j+1]<s;j++);A[p]=pts[j]});return A}
/* the order of places along the row or round the ellipse that puts the most
   links between neighbours: every order is tried when there are few places */
function order(live,w,row){if(live.length<3||live.length>7)return live;var best=live,score=1e18;
function cost(o){var c=0,n=o.length;for(var i=0;i<n;i++)for(var j=i+1;j<n;j++){var d=j-i;if(!row)d=Math.min(d,n-d);c+=(w[o[i]+'\n'+o[j]]||0)*d*d}return c}
(function perm(o,rest){if(!rest.length){var c=cost(o);if(c<score){score=c;best=o}return}
rest.forEach(function(p,i){perm(o.concat([p]),rest.slice(0,i).concat(rest.slice(i+1)))})})(row?[]:[live[0]],row?live:live.slice(1));return best}
function anchors(){var A=spots(V,E);V.forEach(function(n){var a=A[n.z]||[0,0];n.ax=a[0];n.ay=a[1]})}
/* parked threads and projects stay off the graph unless asked for, as in the lists */
function visible(n){return(mode==='all'||n.c)&&(parked||!n.s)}
function rebuild(){V=N.filter(visible);var on={};V.forEach(function(n){on[n.i]=1});E=G.edges.filter(function(e){return on[e[0]]&&on[e[1]]});
N.forEach(function(n){n.deg=0});E.forEach(function(e){N[e[0]].deg++;N[e[1]].deg++});anchors();
var drawn={};V.forEach(function(n){drawn[n.k]=1});document.querySelectorAll('.glegend [data-k]').forEach(function(s){s.hidden=!drawn[s.dataset.k]});
document.querySelectorAll('.gseg button').forEach(function(b){b.classList.toggle('on',b.dataset.m===mode)})}
/* Every note pushes every other away, which costs the square of the notes a
   step. Past BIG notes a quadtree stands in for each far group by its centre,
   which keeps a step near n log n; near notes still push one by one. */
var BIG=400;
function quad(x,y,s){return{x:x,y:y,s:s,m:0,cx:0,cy:0,kids:null,pts:null}}
function put(q,n,d){q.cx=(q.cx*q.m+n.x)/(q.m+1);q.cy=(q.cy*q.m+n.y)/(q.m+1);q.m++;if(q.kids)return into(q,n,d);
if(!q.pts||d>24){(q.pts||(q.pts=[])).push(n);return}var o=q.pts,h=q.s/2;q.pts=null;
q.kids=[quad(q.x,q.y,h),quad(q.x+h,q.y,h),quad(q.x,q.y+h,h),quad(q.x+h,q.y+h,h)];o.forEach(function(p){into(q,p,d)});into(q,n,d)}
function into(q,n,d){var h=q.s/2;put(q.kids[(n.x>=q.x+h?1:0)+(n.y>=q.y+h?2:0)],n,d+1)}
function tree(){var x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;V.forEach(function(n){x0=Math.min(x0,n.x);y0=Math.min(y0,n.y);x1=Math.max(x1,n.x);y1=Math.max(y1,n.y)});
var t=quad(x0,y0,Math.max(x1-x0,y1-y0)+1);V.forEach(function(n){put(t,n,0)});return t}
function apart(a,b,S){var dx=b.x-a.x,dy=b.y-a.y,d2=dx*dx+dy*dy||1,k,m;if(d2>360000)return;k=S*alpha/d2;a.vx-=dx*k;a.vy-=dy*k;
m=a.r+b.r+(a.h&&b.h?55:a.h||b.h?28:14);if(d2<m*m){k=(m-Math.sqrt(d2))/Math.sqrt(d2)*.25;a.x-=dx*k;a.y-=dy*k}}
function shove(q,a,S){if(!q.m)return;if(q.pts){for(var i=0;i<q.pts.length;i++)if(q.pts[i]!==a)apart(a,q.pts[i],S);return}
var dx=q.cx-a.x,dy=q.cy-a.y,d2=dx*dx+dy*dy;
if(q.s*q.s<.81*d2){if(d2<=360000){var k=S*alpha*q.m/d2;a.vx-=dx*k;a.vy-=dy*k}return}
for(var j=0;j<4;j++)shove(q.kids[j],a,S)}
function step(){var L=70,S=900,i,j,a,b,dx,dy,d2,k,m;
if(V.length>BIG){var t=tree();V.forEach(function(n){shove(t,n,S)})}
else for(i=0;i<V.length;i++){a=V[i];for(j=i+1;j<V.length;j++){b=V[j];dx=b.x-a.x;dy=b.y-a.y;d2=dx*dx+dy*dy||1;if(d2>360000)continue;
k=S*alpha/d2;a.vx-=dx*k;a.vy-=dy*k;b.vx+=dx*k;b.vy+=dy*k;
m=a.r+b.r+(a.h&&b.h?55:a.h||b.h?28:14);if(d2<m*m){k=(m-Math.sqrt(d2))/Math.sqrt(d2)*.25;a.x-=dx*k;a.y-=dy*k;b.x+=dx*k;b.y+=dy*k}}}
E.forEach(function(e){a=N[e[0]];b=N[e[1]];dx=b.x+b.vx-a.x-a.vx;dy=b.y+b.vy-a.y-a.vy;var d=Math.sqrt(dx*dx+dy*dy)||1;
k=(d-L)/d*alpha*(a.z===b.z?.3:.09)/Math.max(1,Math.min(a.deg,b.deg));a.vx+=dx*k;a.vy+=dy*k;b.vx-=dx*k;b.vy-=dy*k});
/* The pull toward a place's spot is weaker across the card than down it, so
   the notes spread in the card's proportions. Every few steps it is adjusted
   by how far the notes' own proportions still are from the card's. */
if(alpha>.05&&++ticks%10===0&&V.length>1){var bx=box([0]),la=(bx[1]-bx[0]+40)/(bx[3]-bx[2]+40);pull=Math.max(.7,Math.min(4,pull*Math.pow(asp/la,.3)))}
var q=pull;V.forEach(function(n){var g=(n.deg?.04:.08)*alpha;n.vx-=(n.x-n.ax)*g/q;n.vy-=(n.y-n.ay)*g*q;if(n===drag)return;n.vx*=.6;n.vy*=.6;n.x+=n.vx;n.y+=n.vy});
var mx=0,my=0;V.forEach(function(n){mx+=n.x;my+=n.y});mx/=V.length||1;my/=V.length||1;if(!drag)V.forEach(function(n){n.x-=mx;n.y-=my});
alpha=Math.max(0,alpha-(alpha>.02?.005:.0005)*(V.length>BIG?2:1))}
function toScreen(n){var c=Math.cos(theta),s=Math.sin(theta);return[W/2+px+scale*(n.x*c-n.y*s),H/2+py+scale*(n.x*s+n.y*c)]}
function toWorld(x,y){var c=Math.cos(theta),s=Math.sin(theta),u=(x-W/2-px)/scale,v=(y-H/2-py)/scale;return[u*c+v*s,-u*s+v*c]}
/* Fit: the box the visible notes fill, as drawn, over the whole sway while it
   sways, scaled the same both ways into the card and centred in it. Room is
   kept for the buttons at the top and the names under the lowest notes. */
function box(turns){var b=[1e9,-1e9,1e9,-1e9];(turns||(spin?[-SWAY,SWAY,theta]:[theta])).forEach(function(t){var c=Math.cos(t),s=Math.sin(t);
V.forEach(function(n){var x=n.x*c-n.y*s,y=n.x*s+n.y*c;if(x<b[0])b[0]=x;if(x>b[1])b[1]=x;if(y<b[2])b[2]=y;if(y>b[3])b[3]=y})});return b}
function fit(now){if(!W||!H||!V.length)return;var b=box(),l=34,r=34,t=top,u=36,
k=Math.min((W-l-r)/Math.max(1,b[1]-b[0]),(H-t-u)/Math.max(1,b[3]-b[2]),2.2),
x=l+(W-l-r)/2-W/2-k*(b[0]+b[1])/2,y=t+(H-t-u)/2-H/2-k*(b[2]+b[3])/2;
if(now){scale=k;px=x;py=y;return false}var going=Math.abs(k-scale)>scale*.001||Math.abs(x-px)>.2||Math.abs(y-py)>.2;
scale+=(k-scale)*.08;px+=(x-px)*.08;py+=(y-py)*.08;return going}
function colors(){var cs=getComputedStyle(document.documentElement);['--ink','--ink2','--muted','--base','--accent','--warning','--critical','--raise'].forEach(function(v){C[v]=cs.getPropertyValue(v).trim()})}
function fill(n){return G.colors[n.k]||C['--muted']}
function ring(n){return n.d==null||n.s?null:n.d>45?C['--critical']:n.d>14?C['--warning']:null}
function draw(){ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
var f=sel||hover,near={};if(f){near[f.i]=1;f.adj.forEach(function(i){near[i]=1})}
var P={};V.forEach(function(n){P[n.i]=toScreen(n)});
E.forEach(function(e){var a=P[e[0]],b=P[e[1]],hot=f&&(e[0]===f.i||e[1]===f.i);
ctx.globalAlpha=f&&!hot?.12:(N[e[0]].s||N[e[1]].s)?.25:.55;ctx.strokeStyle=hot?C['--accent']:C['--base'];ctx.lineWidth=hot?1.6:1;
ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke()});
var zs=Math.max(.7,Math.min(1.6,scale));
V.forEach(function(n){var p=P[n.i],r=n.r*zs;ctx.globalAlpha=f&&!near[n.i]?.15:n.s?.3:1;
ctx.fillStyle=fill(n);ctx.beginPath();ctx.arc(p[0],p[1],r,0,6.283);ctx.fill();
var rc=ring(n);if(rc){ctx.strokeStyle=rc;ctx.lineWidth=2.2;ctx.beginPath();ctx.arc(p[0],p[1],r+3.2,0,6.283);ctx.stroke()}
if(n===sel){ctx.strokeStyle=C['--ink'];ctx.lineWidth=2;ctx.beginPath();ctx.arc(p[0],p[1],r+(rc?6.4:3),0,6.283);ctx.stroke()}});
ctx.textAlign='left';ctx.textBaseline='top';ctx.lineJoin='round';
names(P,f,near,zs).forEach(function(l){var n=l.n;ctx.globalAlpha=f&&!near[n.i]?.2:n.s?.45:1;ctx.font=l.font;
ctx.strokeStyle=C['--raise'];ctx.lineWidth=3.5;ctx.strokeText(n.n,l.x,l.y);ctx.fillStyle=l.big?C['--ink']:C['--ink2'];ctx.fillText(n.n,l.x,l.y)});
ctx.globalAlpha=1}
/* Which names to draw, and where. They are placed most wanted first: the note
   in focus, its linked notes, projects, threads, then the rest once zoomed in.
   A name whose box would cover one already placed tries above its note, then
   beside it, and is left out when none of those is free, unless it is the
   note in focus or a project, which are always named. A name keeps the side it
   had while that stays free, so names do not hop as the graph moves. The
   list comes back least wanted first, so the most wanted is drawn on top. */
var FONT='system-ui,-apple-system,sans-serif';
function names(P,f,near,zs){var want=[],out=[],cells={};
V.forEach(function(n){var w=n===f?0:f&&near[n.i]?1:n.h?2:n.c?3:scale>1.4?4:-1;if(w<0)n.lp=-1;else want.push([w,n])});
want.sort(function(a,b){return a[0]-b[0]||b[1].deg-a[1].deg||a[1].i-b[1].i});
function each(b,fn){for(var x=Math.floor(b[0]/64);x<=Math.floor(b[2]/64);x++)for(var y=Math.floor(b[1]/64);y<=Math.floor(b[3]/64);y++)if(fn(x+' '+y))return true;return false}
function free(b){return!each(b,function(k){return(cells[k]||[]).some(function(o){return b[0]<o[2]&&o[0]<b[2]&&b[1]<o[3]&&o[1]<b[3]})})}
want.forEach(function(e){var n=e[1],p=P[n.i],big=n.h||n===f;if(p[0]<-200||p[0]>W+200||p[1]<-40||p[1]>H+40){n.lp=-1;return}
var font=(big?'600 12px ':'11px ')+FONT,lw=n.lw||(n.lw={});if(lw[font]==null){ctx.font=font;lw[font]=ctx.measureText(n.n).width}
var w=lw[font],h=big?14:13,r=n.r*zs+(ring(n)?6:3),at=[[p[0]-w/2,p[1]+r+1],[p[0]-w/2,p[1]-r-1-h],[p[0]+r+4,p[1]-h/2],[p[0]-r-4-w,p[1]-h/2]],
tries=n.lp>=0?[n.lp,0,1,2,3]:[0,1,2,3],pad=n.lp>=0?-1:1,got=-1,box=null;
for(var i=0;i<tries.length&&got<0;i++){var x=Math.max(2,Math.min(W-w-2,at[tries[i]][0])),y=at[tries[i]][1],b=[x-2-pad,y-pad,x+w+2+pad,y+h+pad];
if(free(b)){got=tries[i];box=[x,y,b]}}
if(got<0&&(n===f||n.h)){got=0;box=[Math.max(2,Math.min(W-w-2,at[0][0])),at[0][1]];box.push([box[0]-2,box[1],box[0]+w+2,box[1]+h])}
n.lp=got;if(got<0)return;each(box[2],function(k){(cells[k]||(cells[k]=[])).push(box[2])});out.push({n:n,x:box[0],y:box[1],font:font,big:big})});
return out.reverse()}
/* One frame. The loop runs only while something moves: the layout settling,
   the fit easing, a drag, a glide, or the sway (with its pause after a touch).
   When all is still it stops, and any touch, button or new size wakes it. */
function frame(t){if(!running)return;var dt=Math.min(64,t-(last||t)),moving=alpha>0||!!drag||glides>0;last=t;
if(alpha>0){step();if(V.length<=BIG)step()}if(auto&&fit())moving=true;
idle+=dt;if(spin&&!hover&&!sel&&!drag){moving=true;if(idle>2500){phase+=dt*.0002;theta=SWAY*Math.sin(phase)}}
if((frame.k=(frame.k||0)+1)%30===0||!C['--ink'])colors();draw();if(moving)requestAnimationFrame(frame);else running=false}
function size(){var r=wrap.getBoundingClientRect();W=r.width;H=r.height;dpr=window.devicePixelRatio||1;cv.width=W*dpr;cv.height=H*dpr;
if(bar&&bar.offsetHeight)top=bar.offsetTop+bar.offsetHeight+14;/* the buttons, however many lines they wrap to */
var a=W>120&&H>top+120?Math.max(.5,Math.min(3,(W-68)/(H-top-36))):asp;if(Math.abs(Math.log(a/asp))>.15){asp=a;return true}}
function wake(){if(shown&&!running){running=true;last=0;requestAnimationFrame(frame)}}
function start(){shown=true;wake()}function stop(){shown=false;running=false}
function at(e){var r=cv.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,best=null,bd=1e9;
V.forEach(function(n){var p=toScreen(n),d=Math.hypot(p[0]-x,p[1]-y);if(d<n.r*Math.max(.7,Math.min(1.6,scale))+5&&d<bd){bd=d;best=n}});return{x:x,y:y,n:best}}
var down=null;
cv.addEventListener('pointerdown',function(e){var h=at(e);idle=0;down={x:h.x,y:h.y,n:h.n,px:px,py:py,moved:false};if(h.n){drag=h.n;alpha=Math.max(alpha,.25)}cv.classList.add('drag');cv.setPointerCapture(e.pointerId);wake()});
cv.addEventListener('pointermove',function(e){var h=at(e);idle=0;if(down||h.n!==hover)wake();
if(down){if(Math.hypot(h.x-down.x,h.y-down.y)>4)down.moved=true;
if(drag&&down.moved){var w=toWorld(h.x,h.y);drag.x=w[0];drag.y=w[1];drag.vx=drag.vy=0;alpha=Math.max(alpha,.2)}
else if(!drag&&down.moved){auto=false;px=down.px+h.x-down.x;py=down.py+h.y-down.y}return}
hover=h.n;cv.classList.toggle('hot',!!h.n);
if(h.n){var n=h.n;cv.dataset.tip=n.n+' · '+G.kinds.filter(function(k){return k[0]===n.k})[0][1]+(n.d!=null?' · updated '+n.d+'d ago':'')+(n.s?' · parked':'')+' · click for options'}else delete cv.dataset.tip});
cv.addEventListener('pointerup',function(){cv.classList.remove('drag');if(!down)return;if(!down.moved){if(down.n)select(down.n);else close()}drag=null;down=null;wake()});
cv.addEventListener('pointerleave',function(){if(!down){hover=null;delete cv.dataset.tip;wake()}});
cv.addEventListener('dblclick',function(e){var h=at(e);if(h.n)location.href=h.n.u});
cv.addEventListener('wheel',function(e){if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();idle=0;auto=false;
var r=cv.getBoundingClientRect(),x=e.clientX-r.left-W/2,y=e.clientY-r.top-H/2,k=Math.exp(-e.deltaY*.01);k=Math.max(.2,Math.min(5,scale*k))/scale;px=x-(x-px)*k;py=y-(y-py)*k;scale*=k;wake()},{passive:false});
var esc=Panel.esc;
function kindName(n){var k=G.kinds.filter(function(x){return x[0]===n.k})[0];return k?k[1]:'note'}
function select(n,centre){sel=n;hover=null;delete cv.dataset.tip;var hub=hubOf[n.z+'/'+n.p];
var o={n:n.n,kl:kindName(n),z:n.z,p:n.p,t:n.t,d:n.d,s:n.s,w:n.w,h:n.h,u:n.u,pu:hub&&hub!==n?hub.u:''};
var nb=n.adj.map(function(i){return N[i]}).sort(function(a,b){return(b.h-a.h)||(b.c-a.c)||a.n.localeCompare(b.n)});
var links=nb.map(function(m){return'<button data-i="'+m.i+'"><i style="background:'+fill(m)+'"></i><span>'+esc(m.n)+'</span>'+(visible(m)?'':'<small class="muted">'+(m.s&&!parked?'parked':'everything')+'</small>')+'</button>'}).join('');
pop.innerHTML='<button class="x" aria-label="Close">×</button>'+Panel.head(o)+Panel.acts(o)
+(nb.length?'<div class="glinks"><div class="muted" style="font-size:11.5px;padding:2px 4px">Linked notes · '+nb.length+'</div>'+links+'</div>':'<p class="muted">No links to or from this note.</p>');
pop.hidden=false;wake();if(centre){var p=toScreen(n);auto=false;glide(px-(p[0]-W/2)+(W>700?-150:0),py-(p[1]-H/2))}}
function close(){sel=null;pop.hidden=true;wake()}
function glide(tx,ty){var sx=px,sy=py,t0=performance.now();glides++;wake();(function g(t){var k=Math.min(1,(t-t0)/350),e=1-Math.pow(1-k,3);px=sx+(tx-sx)*e;py=sy+(ty-sy)*e;if(k<1)requestAnimationFrame(g);else glides--})(t0)}
pop.addEventListener('click',function(e){if(e.target.closest('.x'))return close();
var b=e.target.closest('button[data-i]');if(b){var m=N[+b.dataset.i];if(!visible(m)){if(!(mode==='all'||m.c)){mode='all';st.set('garrick-graph-mode',mode)}
if(m.s&&!parked){parked=true;st.set('garrick-graph-parked','1');parkBtn()}rebuild();alpha=Math.max(alpha,.3)}select(m,true)}});
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&sel)close()});
document.querySelectorAll('.gseg button').forEach(function(b){b.onclick=function(){mode=b.dataset.m;st.set('garrick-graph-mode',mode);if(sel&&!visible(sel))close();rebuild();alpha=Math.max(alpha,.5);auto=true;wake()}});
var sp=document.getElementById('gspin');function spinBtn(){sp.textContent=spin?'Pause rotation':'Rotate';sp.disabled=reduce;if(reduce)sp.title='Reduced motion is on'}
sp.onclick=function(){spin=!spin;st.set('garrick-graph-spin',spin?'1':'0');spinBtn();wake()};spinBtn();
document.getElementById('gfit').onclick=function(){auto=true;theta=phase=0;wake()};
var pk=document.getElementById('gpark');function parkBtn(){pk.textContent=parked?'Hide parked':'Show parked';pk.classList.toggle('on',parked)}
pk.hidden=!N.some(function(n){return n.s});pk.onclick=function(){parked=!parked;st.set('garrick-graph-parked',parked?'1':'0');parkBtn();if(sel&&!visible(sel))close();rebuild();alpha=Math.max(alpha,.5);auto=true;wake()};parkBtn();
/* Every note starts near its place's spot, as if everything were drawn, so a
   note that a wider view brings in arrives from where it belongs. */
size();var A0=spots(N,G.edges);N.forEach(function(n){var a=A0[n.z]||[0,0],t=rnd()*6.2832,d=Math.sqrt(rnd())*room(8);
n.x=a[0]+Math.cos(t)*d;n.y=a[1]+Math.sin(t)*d;n.vx=n.vy=0});
/* The warm-up: 400 steps, or 160 cooling twice as fast past BIG notes, so a
   large workspace opens in about a second rather than ten. */
rebuild();for(var i=0;i<(V.length>BIG?160:400);i++)step();colors();fit(true);
if('ResizeObserver' in window)new ResizeObserver(function(){if(size()){anchors();alpha=Math.max(alpha,.3)}if(auto)fit(true);draw();wake()}).observe(wrap);
/* a still graph redraws itself when the theme changes, by the switch or the system */
function recolor(){colors();draw()}
if('MutationObserver' in window)new MutationObserver(recolor).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
var dark=window.matchMedia&&matchMedia('(prefers-color-scheme: dark)');if(dark)dark.addEventListener?dark.addEventListener('change',recolor):dark.addListener&&dark.addListener(recolor);
if('IntersectionObserver' in window)new IntersectionObserver(function(es){es[0].isIntersecting?start():stop()}).observe(wrap);else start();
})();
"""


def build(ws: Path, vault: Optional[str] = None, now: Optional[dt.datetime] = None, folder: Optional[Path] = None,
          show_graph: bool = True, out: Optional[Path] = None) -> str:
    now = now or dt.datetime.now()
    agent = load_agent(ws)
    folder = folder or jobs_dir(agent)
    link = Links(ws, vault)
    T, TD, IB, C, R, W = threads(ws), todo(ws), inboxes(ws), check(ws), repos(ws), wikis(ws)
    sched = launchd_jobs() if folder.is_dir() else {}     # the plists matter only to the jobs extra
    J, L = jobs(folder, now, sched), ledger(agent, folder, now, sched)

    # ---- what needs attention, worst first
    attn = []
    if C and C.get("failed"):
        attn.append(("critical", "The check did not run", "#checks"))
    elif C and C.get("errors"):
        attn.append(("critical", "The check found %d error%s" % (C["errors"], "" if C["errors"] == 1 else "s"), "#checks"))
    for j in J:
        if j["state"] == "critical":
            attn.append(("critical", "%s: %s" % (j["name"], j["status"]), "#jobs"))
    if L:
        stopped: Dict[str, int] = {}          # one line per job, however many calls it lost
        for e in L["refused_today"]:
            job = str(e.get("job") or "a job")
            stopped[job] = stopped.get(job, 0) + 1
        for job, n in stopped.items():
            attn.append(("critical", "The spending cap stopped %s%s" % (job, "" if n == 1 else " %d times in 24 hours" % n), "#calls"))
    waiting = sum(n for _, _, n in IB)
    if waiting:
        attn.append(("warning", "%d item%s waiting in the inboxes" % (waiting, "" if waiting == 1 else "s"), "#inboxes"))
    if C and C.get("warnings"):
        attn.append(("warning", "The check found %d warning%s" % (C["warnings"], "" if C["warnings"] == 1 else "s"), "#checks"))
    attn.sort(key=lambda a: a[0] != "critical")
    worst = "critical" if any(a[0] == "critical" for a in attn) else "warning" if attn else "good"

    live = sum(len(z["rows"]) for z in T.values())
    parked_n = sum(len(z["parked"]) for z in T.values())
    names = short_names(T)
    aging = sum(1 for z in T.values() for r in z["rows"] if r["updated"] and (now.date() - r["updated"]).days > 14)
    week = sum(1 for z in T.values() for r in z["rows"] if r["updated"] and (now.date() - r["updated"]).days <= 7)
    open_actions = sum(sum(t["counts"].values()) for t in TD.values())

    # ---- sidebar
    nav = [("overview", "Overview", worst, len(attn) or "")] + ([("graph", "Graph", "", "")] if show_graph else []) + \
          [("threads", "Threads", "warning" if aging else "good", live)]
    navh = "".join('<a href="#%s"><span class="dot %s"></span>%s<span class="n">%s</span></a>' % (i, s, E(t), E(str(n))) for i, t, s, n in nav)
    navh += "".join('<a class="sub" href="#zone-%s">%s<span class="n">%d</span></a>' % (re.sub(r"\W+", "-", z.lower()), E(z), len(T[z]["rows"])) for z in T)
    more = [("checks", "Checks", "critical" if C and (C.get("errors") or C.get("failed")) else "warning" if C and C.get("warnings") else "good",
             (C.get("errors", 0) + C.get("warnings", 0)) if C and not C.get("failed") else ""),
            ("todo", "Open actions", "good", open_actions), ("inboxes", "Inboxes", "warning" if waiting else "good", waiting or "")]
    if J:
        more.append(("jobs", "Scheduled jobs", "critical" if any(j["state"] == "critical" for j in J) else "good", len(J)))
    if L:
        more.append(("calls", "Assistant calls", "critical" if L["refused_today"] else "good", L["day"]))
    more += [("repos", "Repositories", "good", ""), ("wikis", "Wikis", "good", "")]
    navh += "".join('<a href="#%s"><span class="dot %s"></span>%s<span class="n">%s</span></a>' % (i, s, E(t), E(str(n))) for i, t, s, n in more)
    overall = "All clear" if not attn else "%d need%s attention" % (len(attn), "s" if len(attn) == 1 else "")
    aside = ('<aside><div class="brand">%s<div><h1>%s</h1><p>Built %s · <span id="age">just now</span></p></div></div>'
             '<div class="overall">%s<div><b>%s</b><span>%d live thread%s, %d touched this week</span></div></div><nav>%s</nav>'
             '<div class="controls">%s<p class="hint" id="hidden-note" hidden></p>'
             '<button class="act wide" type="button" id="reset-view" title="Every card back in place and shown, folds open, graph and filter as built">Reset view</button>'
             '<label class="switch"><input type="checkbox" id="only"> Problems only</label>'
             '<div class="seg" role="group" aria-label="Theme"><button data-t="auto">Auto</button><button data-t="light">Light</button><button data-t="dark">Dark</button></div></div></aside>'
             % (mark(full=False, attrs=' class="mark" aria-hidden="true"'), E(NAME), now.strftime("%a %d %b, %H:%M"), ICON[worst], E(overall),
                live, "" if live == 1 else "s", week, navh,
                copy("Copy the rebuild command", rebuild_command(ws, vault, show_graph, out),
                     "Copied. Run it in a terminal to rebuild the page.").replace('class="act"', 'class="act wide"')))

    # ---- hero and tiles
    if attn:
        hero = '<div class="hero" id="overview"><div class="fig">%s%d</div><div class="lbl">%s attention</div></div>' % (
            ICON[worst], len(attn), "thing needs" if len(attn) == 1 else "things need")
    else:
        hero = '<div class="hero" id="overview"><div class="fig" style="font-size:38px">%sAll clear</div><div class="lbl">Nothing failing, waiting or broken.</div></div>' % ICON["good"]
    tiles = [("Live threads", "%d" % live, "%d touched this week, %d untouched for 14+ days" % (week, aging)),
             ("Open actions", "%d" % open_actions, "across %d zone%s" % (len(TD), "" if len(TD) == 1 else "s")),
             ("Waiting to be filed", "%d" % waiting, "in the zone and meeting inboxes"),
             ("Check", ("%d<small>errors</small>%d<small>warnings</small>" % (C.get("errors", 0), C.get("warnings", 0)))
              if C and not C.get("failed") else "—", "run just now" if C else "check.py not found")]
    if L:
        cap = L["caps"]["calls_day"]
        tiles[3] = ("Assistant calls, 24 h", "%d<small>%s</small>" % (L["day"], "of %g" % cap if cap else "no cap"),
                    "$%.2f at list price" % L["cost_day"])
    top = '<div class="top">%s%s</div>' % (hero, "".join(
        '<div class="tile"><div class="lbl">%s</div><div class="val">%s</div><div class="sub">%s</div></div>' % (E(a), b, E(c)) for a, b, c in tiles))

    # ---- attention
    attn_card = ""
    if attn:
        attn_card = '<div class="full">%s</div>' % card("attention", "Needs attention", "%d item%s" % (len(attn), "" if len(attn) == 1 else "s"),
                                                       '<div class="attn">%s</div>' % "".join('<a href="%s">%s<span>%s</span></a>' % (h, ICON[k], E(t)) for k, t, h in attn),
                                                       fixed=True)

    # ---- threads, one column per zone
    cols = ""
    for z, data in T.items():
        rows, na, nb = [], 0, 0
        for r in data["rows"]:
            days = (now.date() - r["updated"]).days if r["updated"] else None
            k = "good" if days is not None and days <= 14 else "warning" if days is not None and days <= 45 else "critical"
            na += k == "warning"
            nb += k == "critical"
            chips = "".join('<span class="chip">%s</span>' % E(p) for p in r["party"])
            rows.append('<div class="thread" data-ok="%d" data-card="%s"><div class="t"><a href="%s">%s</a><small>%s%s</small></div>'
                        '<div class="fresh %s"><i style="width:%.1f%%"></i></div><span class="num muted" style="text-align:right">%s</span></div>'
                        % (k == "good", E(thread_card(r, names, link, days)), E(link(r["note"])), E(r["thread"]), E(r["project"]), chips,
                           k, max(3.0, min(100.0, (days if days is not None else 60) / 60 * 100)), "%dd" % days if days is not None else "—"))
        held = []
        for r in data["parked"]:
            days = (now.date() - r["updated"]).days if r["updated"] else None
            held.append('<div class="thread" data-ok="1" data-card="%s"><div class="t"><a href="%s">%s</a><small>%s</small></div>'
                        '<span></span><span class="num muted" style="text-align:right">%s</span></div>'
                        % (E(thread_card(r, names, link, days)), E(link(r["note"])), E(r["thread"]), E(r["project"]),
                           "%dd" % days if days is not None else "—"))
        slug = re.sub(r"\W+", "-", z.lower())
        parked_block = ('<details class="parked" id="parked-%s"><summary>%sParked<span class="n">%d</span></summary>%s</details>'
                        % (slug, CHEV, len(held), "".join(held))) if held else ""
        meta = "%d live" % len(data["rows"]) + (" · %d aging" % na if na else "") + (" · %d stale" % nb if nb else "") + (" · %d done" % data["done"] if data["done"] else "")
        cols += ('<details class="zone" id="zone-%s" open><summary>%s<h3>%s</h3><span class="meta">%s</span></summary>%s%s</details>'
                 % (slug, CHEV, E(z), E(meta), "".join(rows) or '<p class="muted">No live threads.</p>', parked_block))
    legend = ('<div class="legend"><span><i class="good"></i>updated in the last 14 days</span><span><i class="warning"></i>15 to 45 days</span>'
              '<span><i class="critical"></i>over 45 days</span><span>· the bar is days since the thread note was updated, full at 60</span></div>')
    threads_card = card("threads", "Threads", "%d live · %d parked · by name · hover one for what to do" % (live, parked_n),
                        '<div class="zones">%s</div>%s' % (cols, legend))

    # ---- checks
    if C is None:
        body = '<p class="muted">No <code>System/tools/check.py</code> in this workspace.</p>'
    elif C.get("failed"):
        body = '<div class="clean">%sThe check did not run. Run <code>python3 System/tools/check.py</code> to see why.</div>' % ICON["critical"]
    else:
        groups = {}
        for f in C.get("findings", []):
            groups.setdefault(f.get("check", "?"), []).append(f)
        body = "" if groups else '<div class="clean">%sNo problems found.</div>' % ICON["good"]
        for name, fs in groups.items():
            errs = sum(1 for f in fs if f.get("severity") == "error")
            counts = "".join('<span class="chip">%s %d</span>' % (ICON[k].replace("<svg ", '<svg width="12" height="12" '), n)
                             for k, n in (("critical", errs), ("warning", len(fs) - errs)) if n)
            lis = "".join('<li>%s<span>%s: %s</span></li>' % (ICON["critical" if f.get("severity") == "error" else "warning"], E(f.get("path", "")), E(f.get("message", ""))) for f in fs)
            body += ('<details class="group" data-ok="0"%s><summary>%s<b>%s</b><span class="counts">%s</span></summary><ul>%s</ul></details>'
                     % (" open" if errs else "", CHEV, E(C["titles"].get(name, name)), counts, lis))
    checks_card = card("checks", "Checks", "check.py, run as the page was built", body)

    # ---- open actions and inboxes
    tb = ""
    for z, t in TD.items():
        scale = max(list(t["counts"].values()) + [1]) * 1.08
        tb += ('<div class="zt"><b><a href="%s">%s</a></b><span class="muted" style="font-size:12px">changed %s</span>'
               '<a class="act" href="%s" title="Open %s/Todo.md">Open</a></div>' % (E(link(t["file"])), E(z), age(t["when"], now), E(link(t["file"])), E(z)))
        if not t["counts"]:
            tb += '<p class="muted" style="font-size:12px;margin:2px 0">Nothing open.</p>'
        for sec, n in t["counts"].items():
            tb += '<div class="bullet"><span class="ink2">%s</span><div class="bar"><i style="width:%.1f%%"></i></div><span class="num">%d</span></div>' % (E(sec), n / scale * 100, n)
    todo_card = card("todo", "Open actions", "unticked items in each zone's Todo.md", tb or '<p class="muted">No Todo.md found.</p>')
    ib = "".join('<a class="item" data-ok="%d" href="%s">%s<div class="name">%s<small>%s</small></div></a>' % (
        0 if n else 1, E(link(f)), ICON["warning" if n else "good"], E(name), "%d waiting" % n if n else "empty") for name, f, n in IB)
    inbox_card = card("inboxes", "Inboxes", "files waiting to be filed; say \"process the inbox\"", '<div class="tiles">%s</div>' % ib)

    # ---- jobs and calls, only when the jobs extra is in use
    jobs_card = calls_card = ""
    if J:
        rows = []
        for j in J:
            strip = "".join('<i class="%s" tabindex="0" data-tip="%s"></i>' % (s, E(t)) for s, t in day_cells(j["runs"], now))
            last = age(j["when"], now) if j["when"] else "never"
            rows.append('<div class="row" data-ok="%d">%s<div class="name"><a href="%s">%s</a><small>%s</small></div><div class="strip">%s</div>'
                        '<div class="ink2 num" data-tip="took %ss">%s</div><span class="status">%s%s</span></div>'
                        % (j["state"] == "good", ICON[j["state"]], E(link(j["log"])), E(j["name"]), E(j["schedule"]), strip,
                           E(str(j["seconds"])), E(last), ICON[j["state"]], E(j["status"])))
        legend = ('<div class="legend"><span><i class="good"></i>every run ok</span><span><i class="warning"></i>some failed, then recovered</span>'
                  '<span><i class="critical"></i>ended the day failed, or most runs failed</span><span><i></i>no run</span><span>· one cell per day, last %d days</span></div>' % DAYS)
        jobs_card = card("jobs", "Scheduled jobs", "heartbeats and logs in %s" % folder.name, '<div class="rows jobs">%s</div>%s' % ("".join(rows), legend))
    if L:
        c = L["caps"]
        def against(text, cap, unit=""):     # "3 / 48", or "3, no cap" when the cap is 0
            return "%s / %s%g" % (text, unit, cap) if cap else "%s, no cap" % text
        m = (meter(L["day"], c["calls_day"], "Calls, last 24 h", against("%d" % L["day"], c["calls_day"]))
             + meter(L["hour"], c["calls_hour"], "Calls, last hour", against("%d" % L["hour"], c["calls_hour"]))
             + meter(L["cost_day"], c["cost_day"], "Cost, last 24 h", against("$%.2f" % L["cost_day"], c["cost_day"], "$"))
             + '<p class="hint">%s</p>' % E(L["caps_from"]))
        trs = "".join('<tr><td>%s</td><td class="r">%d</td><td class="r">$%.2f</td><td>%s</td><td class="r">%d</td><td class="r">%d</td></tr>'
                      % (E(job), d["calls"], d["cost"], E(", ".join(sorted(d["denied"]))) or '<span class="muted">none</span>', d["failed"], d["refused"])
                      for job, d in sorted(L["by"].items()))
        table = ('<div class="scroll"><table><thead><tr><th>Job</th><th class="r">Calls</th><th class="r">Cost</th><th>Refused tools</th>'
                 '<th class="r">Failed</th><th class="r">Capped</th></tr></thead><tbody>%s</tbody></table></div>' % trs) if trs else '<p class="muted">No calls yet.</p>'
        calls_card = card("calls", "Assistant calls", "ledger.jsonl, last %d days, list-price cost" % DAYS,
                          '<div class="meters">%s</div><div style="margin-top:14px">%s</div>' % (m, table))

    # ---- repositories and wikis
    rr = "".join('<div class="item" data-ok="1" data-tip="last commit %s">%s<div class="name">%s<small>%s</small></div></div>' % (
        E(age(r["last"], now)) if r["last"] else "never", ICON["good" if not r["dirty"] else "none"], E(r["name"]),
        "%d uncommitted" % r["dirty"] if r["dirty"] else "all committed") for r in R)
    repos_card = card("repos", "Repositories", "a ring means work not yet committed", '<div class="tiles">%s</div>' % rr if rr else '<p class="muted">No git repositories found.</p>')
    def newest(w):
        if not w["when"]:
            return "nothing logged yet"
        title = ('<a href="%s">%s</a>' % (E(link(w["page"])), E(w["title"]))) if w["page"] else E(w["title"])
        return "%s · %s" % (E(w["when"].strftime("%d %b %Y").lstrip("0")), title)
    wr = "".join('<div class="row" style="grid-template-columns:1fr"><div class="name"><a href="%s">%s</a><small style="white-space:normal">%s</small></div></div>' % (
        E(link(w["log"])), E(w["name"]), newest(w)) for w in W)
    wikis_card = card("wikis", "Wikis", "newest entry in each log", '<div class="rows">%s</div>' % wr if wr else '<p class="muted">No wiki logs found.</p>')

    # ---- the graph
    graph_card = ""
    if show_graph:
        GR = graph(ws, T, link, now)
        core = sum(1 for n in GR["nodes"] if n["c"])
        legend = "".join('<span data-k="%d"><i style="background:%s"></i>%s</span>' % (i, GR["colors"][i], E(label)) for i, label in GR["kinds"])
        legend = ('<div class="legend glegend">%s<span><i class="ring" style="border-color:var(--warning)"></i>thread untouched 15 to 45 days</span>'
                  '<span><i class="ring" style="border-color:var(--critical)"></i>over 45 days</span><span><i style="opacity:.3;background:var(--muted)"></i>parked, when shown</span>'
                  '<span>· click a note to open it or copy what to say, double-click to open it, drag to move, pinch or ⌘-scroll to zoom</span></div>' % legend)
        data = script_json(GR)
        graph_card = card("graph", "Graph", "%d notes, %d links · %d projects and threads · names only" % (len(GR["nodes"]), len(GR["edges"]), core),
                          '<div class="gwrap"><canvas id="gcv" role="img" aria-label="Graph of the notes in every zone and wiki, and the links between them"></canvas>'
                          '<div class="gbar"><div class="gseg" role="group" aria-label="Notes shown"><button data-m="core">Projects and threads</button>'
                          '<button data-m="all">Everything</button></div><button id="gpark" type="button"></button><button id="gspin"></button><button id="gfit">Fit</button></div>'
                          '<div class="gpop" id="gpop" hidden></div></div>%s<script type="application/json" id="graph-data">%s</script>' % (legend, data))

    left = checks_card + jobs_card + wikis_card
    right = todo_card + inbox_card + calls_card + repos_card
    main = ('<main><div class="stale" id="stale"></div>%s<div class="grid">%s<div class="slot full" data-slot="top">%s%s</div>'
            '<div class="slot stack left" data-slot="left">%s</div><div class="slot stack right" data-slot="right">%s</div>'
            '<div class="slot full" data-slot="bottom"></div></div></main>'
            % (top, attn_card, graph_card, threads_card, left, right))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title>%s<style>%s</style></head><body data-built="%s"><div class="app">%s%s</div>'
            '<div id="tip" role="tooltip"></div><div id="toast" role="status"></div><script>%s%s%s%s</script></body></html>' % (
                E(NAME), favicon(), CSS, now.isoformat(timespec="seconds"), aside, main, PANEL_JS, LAYOUT_JS, JS, GRAPH_JS if show_graph else ""))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build the status page for a Garrick workspace.")
    ap.add_argument("--workspace", help="the workspace folder (default: GARRICK_WORKSPACE, or the folder this runs in)")
    ap.add_argument("--out", help="where to write the page (default: System/generated/status.html)")
    ap.add_argument("--obsidian", metavar="VAULT", help="link into Obsidian, with the workspace root opened as this vault")
    ap.add_argument("--open", action="store_true", help="open the page when it is built")
    ap.add_argument("--no-graph", action="store_true", help="leave the graph out: the page then reads nothing but frontmatter")
    args = ap.parse_args(argv)
    ws = find_workspace(args.workspace)
    generated = ws / "System" / "generated"
    out = Path(args.out).expanduser() if args.out else generated / "status.html"
    inside = str(out.resolve()).startswith(str(ws) + os.sep)
    if inside and not str(out.resolve()).startswith(str(generated.resolve()) + os.sep):
        print("status: %s is inside the workspace but not in System/generated/; this page shows every zone, "
              "so keep it where git and the wall check leave it alone." % out, file=sys.stderr)
    if inside and (ws / ".git").exists():
        try:
            probe = subprocess.run(["git", "-C", str(ws), "check-ignore", "-q", "--no-index", "System/generated/status.html"],
                                   capture_output=True, text=True)
        except OSError:                       # no git on this PATH: nothing to check against
            probe = None
        if probe is not None and probe.returncode == 1:
            print("status: the workspace's .gitignore does not name System/generated/; add that line so the page "
                  "is never committed.", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(build(ws, args.obsidian, show_graph=not args.no_graph, out=out.resolve() if args.out else None), encoding="utf-8")
    os.replace(tmp, out)
    print(out)
    if args.open:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.run([opener, str(out)], check=False)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
