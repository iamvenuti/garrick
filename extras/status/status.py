#!/usr/bin/env python3
"""The status page for a Garrick workspace. An optional extra.

    python3 status.py [--workspace FOLDER] [--out FILE] [--open] [--obsidian VAULT | --no-obsidian] [--no-cmux] [--no-graph]
                      [--settle SECONDS] [--also FOLDER ...] [--moved OLD=NEW ...]

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
numbers come from and how old they are. The one call out is the release
notice, off until System/garrick-settings.json switches it on: then a build
starts System/tools/release.py, at most once a day and without waiting for it,
and Needs attention names a newer Garrick once GitHub has said there is one.

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
The simple home (#175), which a new workspace opens on and Settings › Home
chooses, is the one exception: a piece of work means nothing without its
next action, so it also shows the Resume here block's Where it stands, Next
action and Waiting on, the newest dated entry, a note's opening sentence,
its Needs you questions and the names of the files in its folder. It still
lives in System/generated/, never committed and outside the wall check.

**It offers what this machine has**, and asks at every build. A note's link
opens it in Obsidian when Obsidian has registered the workspace, or the zone or
wiki the note is in, as a vault; otherwise it opens the file itself, in
whatever app you use for Markdown. `--obsidian VAULT` names the workspace root
as the vault instead, and `--no-obsidian` keeps every link a file link. In
Garrick.app (see `app/`), projects and threads also offer Reveal in
Finder and Open in Claude, Codex or cmux, for each one installed and switched
on in Settings, where one of them can also be what clicking a thread's name
does; `--no-cmux` leaves cmux out. Open in Claude on a thread hands it over
as the simple home's Continue does (#180), through page_action.py's
`continue`, where this build finds Claude Code's command-line tool
(handoff.py's find_claude()); without it, it falls back to the deep link,
which leaves the question for you to send. A zone with no Todo.md gets no Open
actions, and a workspace with none gets no card for them.
A zone given a colour or an icon in Settings › Zones shows them wherever
the page names it.

**The Guide tab** shows Garrick's own docs: the copy in System/garrick-docs/
that the installer and every update put there, drawn by guide.py beside this
file. A link between two pages stays on the page, a link into Garrick's own
files opens on GitHub at the release the workspace runs, and the pages cost
the other tabs nothing until the Guide is opened.

The buttons that act are carried out by page_action.py beside this file, for
the Mac app and the Obsidian plugin. Preview features (FLAGS) stay off until
System/garrick-flags.json switches them on. With the cmux extra beside this folder
(../cmux/cmuxlib.py), the page shows which projects and threads have a
session open, and its buttons can drive the desk. `--settle` lets a burst of
build requests make one page; `--also` and `--moved` reach effort.py.

Copy this folder into your workspace as `System/status/`, next to
`System/jobs/` if you have it, and run it by hand or on a schedule through
job.py (see docs/extras/status-page.md). Standard library only, Python 3.9 or
later. Not installed by install.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import importlib.util
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True

E = html.escape
NAME = "Garrick"     # what the page is called, as the app is; its files and flags keep their names
DAYS = 14
EXIT = {0: "ok", 3: "answer incomplete", 4: "could not sign in", 6: "missing connector", 8: "spending cap",
        64: "bad arguments", 75: "skipped, still running", 124: "timed out", 127: "command not found"}
OK_EXITS = (0, 75)
# job.py's end-of-run line; a quiet exit ends with "  quiet" before the rule.
LOGLINE = re.compile(r"^===== (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  (\S+)  (?:exit (-?\d+)  \((\d+)s\)(  quiet)?|skipped)")
TODO_ITEM = re.compile(r"^\s*-\s\[ \]\s")
# Where Garrick lives, for Settings › About Garrick. The page loads nothing from
# it: each link opens in your browser, and a report goes only when you submit
# it there yourself.
PROJECT = "https://github.com/iamvenuti/garrick"
UNKNOWN = ("Garrick, version unknown: this workspace has no record of the copy it was installed from. "
           "Say the day you downloaded it instead.")


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
                try:
                    import job  # noqa: F401  (its lock rule, for "running now")
                except Exception:
                    pass
                return agent
            except Exception:
                return None
    return None


# The cmux extra's library, beside this folder as System/cmux/ is beside
# System/status/. With it, the page shows which projects and threads have a
# session open, and in the app offers Open and Close session, Start up and
# Shut down, which the desk carries out. Without it, none of that is drawn.
CMUXLIB = Path(__file__).resolve().parent.parent / "cmux" / "cmuxlib.py"


def cmux_extra(lib: Optional[Path] = None):
    """The cmux extra's library, loaded; None when it is not here or does not load."""
    lib = lib or CMUXLIB
    if not lib.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("garrick_cmuxlib", str(lib))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return False


def sessions(ws: Path, lib: Optional[Path] = None) -> Optional[Dict[str, str]]:
    """Resolved folder -> "idle" or "working", for every session the cmux
    extra knows is open; None when the extra is not installed. A library that
    fails to load or answer counts as installed with nothing open."""
    mod = cmux_extra(lib)
    if mod is None:
        return None
    try:
        found = mod.sessions_by_folder(ws)
    except Exception:
        return {}
    return {os.path.realpath(str(k)): v for k, v in (found or {}).items() if v in ("idle", "working")}


def desk_ready(lib: Optional[Path] = None) -> bool:
    """Whether the desk can act here: the cmux extra is installed and finds
    cmux (its installed(); a library without that check is taken at its word)."""
    mod = cmux_extra(lib)
    if not mod:
        return False
    try:
        check = getattr(mod, "installed", None)
        return bool(check()) if callable(check) else True
    except Exception:
        return False


def session_in(open_: Optional[Dict[str, str]], folder: Path) -> Optional[str]:
    """The state of the sessions open in a folder or below it: working when
    any is, idle when all are, None when there are none."""
    if not open_:
        return None
    root = os.path.realpath(str(folder))
    found = [v for k, v in open_.items() if k == root or k.startswith(root + os.sep)]
    return ("working" if "working" in found else "idle") if found else None


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


DRIFT = ("System", "generated", "drift.json")
DRIFT_SAY = {"drifted": "has drifted from its shared copy", "missing": "is missing, here or on the share",
             "unread": "has a row in published.md that does not read",
             "conflict": "is a copy a sync conflict left on the share"}


def drifted(ws: Path) -> List[str]:
    """What drift.py last found worth a look, from System/generated/drift.json,
    which it writes when run from a session or the app: a launchd job may
    not read a cloud folder, so the page never compares anything itself."""
    try:
        data = json.loads(ws.joinpath(*DRIFT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for f in data.get("files", []) if isinstance(data, dict) else []:
        if isinstance(f, dict) and f.get("state") in DRIFT_SAY:
            where = f.get("project", "?") + (", " + f["thread"] if f.get("thread") else "")
            out.append("%s: %s %s" % (where, f.get("file") or "published.md", DRIFT_SAY[f["state"]]))
    return out


def workspace_context(ws: Path) -> dict:
    """System/context.md as the workspace's own garrick_lib reads it, or {}."""
    lib = workspace_lib(ws)
    try:
        return lib.load_context(ws) if lib is not None and callable(getattr(lib, "load_context", None)) else {}
    except Exception:
        return {}


def workspace_stamp(ws: Path) -> dict:
    """The installer's stamp, System/garrick-version.json, or {}."""
    try:
        stamp = json.loads(ws.joinpath("System", "garrick-version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return stamp if isinstance(stamp, dict) else {}


def installed_version(ws: Path) -> str:
    """Which Garrick this workspace came from, in the words `check.py --version`
    uses, read from the stamp the installer wrote. A workspace whose tools
    predate the stamp says the version is unknown."""
    lib = workspace_lib(ws)
    read, say = getattr(lib, "read_version", None), getattr(lib, "say_version", None)
    if not (callable(read) and callable(say)):
        return UNKNOWN
    try:
        stamp = read(ws)
        said = [say(stamp)]
        changes = getattr(lib, "say_changes", None)
        if callable(changes):
            said.append(changes(ws, stamp))
        return " ".join(s for s in said if s) or UNKNOWN
    except Exception:
        return UNKNOWN


def release_notice(ws: Path) -> Optional[Tuple[str, str]]:
    """With the release notice switched on, the newer Garrick the last question
    to GitHub found, as (line, link to its release notes); else None. Reads
    the answer kept in System/generated/, through the workspace's own
    garrick_lib, and never asks: release_ask() does, in the background."""
    lib = workspace_lib(ws)
    on, newer, say = (getattr(lib, n, None) for n in ("release_notice_on", "newer_release", "say_newer_release"))
    if not (callable(on) and callable(newer) and callable(say)):
        return None
    try:
        found = newer(ws) if on(ws) else None
        return (say(ws), found["url"]) if found else None
    except Exception:
        return None


def release_ask(ws: Path) -> bool:
    """Start System/tools/release.py in a process of its own to ask GitHub for
    the newest release, when the release notice is switched on and has not
    asked in the last day. The build never waits for it: the next build shows
    the answer. Returns whether it started one."""
    lib, tool = workspace_lib(ws), ws / "System" / "tools" / "release.py"
    due = getattr(lib, "release_due", None)
    try:
        if not (callable(due) and tool.is_file() and due(ws)):
            return False
        subprocess.Popen([sys.executable, str(tool), "--root", str(ws), "latest", "--background"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         cwd=str(ws), start_new_session=True)
        return True
    except Exception:                         # the page is built either way
        return False


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

DONE = {"done", "closed", "archived", "complete", "completed"}
PARKED = {"parked", "dormant", "paused", "on-hold"}
RESUME = re.compile(r"^#{1,6}\s+Resume here\b", re.I)
MONTH = {m.lower(): i + 1 for i, m in enumerate(("January February March April May June July August September "
                                                  "October November December").split())}
SPOKEN_DATE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b")


def resume_point(note: Path) -> Tuple[bool, Optional[dt.date]]:
    """Whether a thread note has its `### Resume here` block, as the threads
    skill writes it, and the date the block gives itself: the first date on
    its "Where it stands" line, or anywhere in the block before its table.
    The full page reads nothing else of the block, and nothing of it reaches
    that page; the simple home reads the rest through resume_read()."""
    found = resume_read(note)
    return found["block"], found["date"]


RESUME_ROW = re.compile(r"^\|\s*([^|]*?)\s*\|\s*(.*?)\s*\|\s*$")
ENTRY_LINE = re.compile(r"^\*\*(?:[A-Z][a-z]+ \d\d:\d\d, )?(\d{1,2} [A-Za-z]{3,9}\.? \d{4})\.\*\*\s*(.*\S)\s*$")
PLACEHOLDER = re.compile(r"^<[^>]*>$")


def said_date(text: str) -> Optional[dt.date]:
    """The first date in `text`, ISO or spoken ("3 October 2026")."""
    iso = re.search(r"\b(\d{4}-\d\d-\d\d)\b", text)
    if iso and as_date(iso.group(1)):
        return as_date(iso.group(1))
    for day, month, year in SPOKEN_DATE.findall(text):
        number = MONTH.get(month.lower()) or next((n for m, n in MONTH.items() if m[:3] == month.lower()[:3]), None)
        try:
            if number:
                return dt.date(int(year), number, int(day))
        except ValueError:
            continue
    return None


def filled(text: Optional[str]) -> str:
    """A note's words as written, or "" where they are still the template's `<placeholder>`."""
    text = (text or "").strip()
    return "" if not text or PLACEHOLDER.match(text) else text


def resume_read(note: Path) -> dict:
    """A thread note's resume point, read once: `block`, whether it has a
    `### Resume here` block, and `date`, the date the block gives itself (see
    resume_point()). For the simple home, also `where`, its Where it stands
    line; `rows`, its table by row name (Next action, Waiting on, …), each
    as written and "" where it is still the template's placeholder; `entry`,
    the newest dated entry below it, (its date, its words); and `about`, the
    note's opening sentence under its title."""
    out = {"block": False, "date": None, "where": "", "rows": {}, "entry": None, "about": ""}
    try:
        lines = note.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    title = next((i for i, l in enumerate(lines) if l.startswith("# ")), None)
    if title is not None:
        para = []
        for l in lines[title + 1:]:
            if l.startswith("#") or (para and not l.strip()):
                break
            if l.strip():
                para.append(l.strip())
        out["about"] = filled(" ".join(para))
    for i, line in enumerate(lines):
        if not RESUME.match(line):
            continue
        out["block"] = True
        lead: List[str] = []
        for text in lines[i + 1:i + 12]:
            if text.startswith(("#", "|", "---")):
                break
            if text.strip():
                lead.append(text.strip())
            if out["date"] is None:
                out["date"] = said_date(text)
        out["where"] = filled(re.sub(r"^\*\*Where it stands,?[^*]*\*\*\s*", "", " ".join(lead)).replace("**", ""))
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if lines[j].startswith("#") or lines[j].strip() == "---":
                end = j
                break
            m = RESUME_ROW.match(lines[j])
            if m and m.group(1) and not set(m.group(1)) <= set("-: "):
                out["rows"][m.group(1)] = filled(m.group(2).replace("\\|", "|"))
        for l in lines[end:end + 40]:
            m = ENTRY_LINE.match(l.strip())
            if m:
                out["entry"] = (said_date(m.group(1)), filled(m.group(2)))
                break
            if l.startswith("## "):
                break
        break
    return out


# The checkpoint beside a resume point: `### Checkpoint` under Resume here,
# what a session recorded as the work happened and has not wrapped yet. Only
# its comment line is read here, which carries when it was written and the
# hash of the resume point it was written against; no content of the block
# reaches the page, as resume_point() promises of the block above it. The page
# gets no button either: confirming a checkpoint is a wrap, and a wrap needs an
# assistant that knows the session.
CHECKPOINT_MARK = re.compile(r"(?m)^<!--[ \t]*garrick-checkpoint[ \t]([^\n]*?)-->[ \t]*$")
CHECKPOINT_FIELD = re.compile(r"(\w+)=(\S+)")
MONTH_NAMES = tuple(m.capitalize() for m in sorted(MONTH, key=MONTH.get))


def checkpoint_mark(note: Path, ws: Optional[Path]) -> Optional[dict]:
    """The unwrapped checkpoint in a note, as its comment line carries it:
    `at`, when it was written, `said` and `full`, that time short and long, and
    `stale`, whether the resume point has moved since. None where the note has
    no checkpoint. Stale needs the workspace's own `resume_hash`, so without
    `garrick_lib.py` a block reads as current: the time it carries is true
    either way, and only the second claim would be a guess."""
    try:
        body = note.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = CHECKPOINT_MARK.search(body)
    if m is None:
        return None
    fields = dict(CHECKPOINT_FIELD.findall(m.group(1)))
    try:
        when = dt.datetime.fromisoformat(fields.get("at") or "")
    except ValueError:
        when = None
    lib = workspace_lib(ws)
    base = None
    if lib is not None and callable(getattr(lib, "resume_hash", None)):
        try:
            base = lib.resume_hash(body)
        except Exception:
            base = None
    said = "%02d:%02d" % (when.hour, when.minute) if when else "an unreadable time"
    full = "%s on %d %s %d" % (said, when.day, MONTH_NAMES[when.month - 1], when.year) if when else said
    return {"at": when, "said": said, "full": full,
            "stale": bool(base and fields.get("base") and fields["base"] != base)}


def checkpoint_chip(r: dict) -> str:
    """A thread's unwrapped checkpoint as a pill: when it was written, or that
    it is out of date where the resume point has moved since. Not coloured for
    trouble: a checkpoint is work recorded, and what marks a thread on this
    page is its own next action."""
    mark = r.get("checkpoint")
    if not mark:
        return ""
    if mark["stale"]:
        return '<span class="chip" title="%s">checkpoint out of date</span>' % E(
            "Its checkpoint from %s was written against an older resume point, so a wrap has left it behind: "
            "read it, do not resume from it" % mark["full"])
    return '<span class="chip" title="%s">unwrapped since %s</span>' % (
        E("Work this session recorded at %s and no wrap has folded in yet. Open the thread to read it: "
          "only a wrap confirms it" % mark["full"]), E(mark["said"]))


def threads(ws: Path) -> Dict[str, dict]:
    """Per zone: every live thread's project, name, party and the date its
    note was last updated, read from frontmatter like "what's open"; and
    whether the note has a Resume here block, with that block's own date
    (resume_point), and its unwrapped checkpoint read from the comment line
    alone (checkpoint_mark), with `touched`, the later of `updated:` and that
    checkpoint's day: this afternoon's unwrapped work is newer than the last
    wrap, and the views that order by what moved last say so. A project
    with no thread note is its own single thread, read from its hub, as in a
    workspace laid out before Garrick gave every project a Threads/ folder.
    A project whose hub says parked holds every live thread in it parked
    too, each marked `held`; `held` per zone names those projects.

    For the Threads card's search (#140), names only: each row's `spoken:`
    form, `finished` per zone, the threads `done` counts, with their
    project, name and note, and `projects`, each project by name with its
    hub's status (live, parked or done), its spoken form and whether it is
    its own single thread (`own`). Nothing of a note's body is read here."""
    out = {}
    for zone in visible_dirs(ws / "Zones"):
        rows, parked, done, asleep, finished, projects = [], [], 0, [], [], {}
        for project in visible_dirs(zone):
            if project.name == "Inbox":
                continue
            hub = project / (project.name + ".md")
            pfm = frontmatter(hub, ws)
            hub_state = as_text(pfm.get("status")).strip().lower() if hub.is_file() else ""
            hub_parked = hub_state in PARKED
            if hub_parked:
                asleep.append(project.name)
            found = [(t.name, t / (t.name + ".md")) for t in visible_dirs(project / "Threads")]
            own = False
            if not any(n.is_file() for _, n in found) and hub.is_file() and \
                    as_text(pfm.get("type")).strip().lower() == "project":
                found, own = [(project.name, hub)], True
            if hub.is_file() or any(n.is_file() for _, n in found):
                projects[project.name] = {"status": "done" if hub_state in DONE else "parked" if hub_parked else "live",
                                          "spoken": as_text(pfm.get("spoken")).strip(), "own": own,
                                          "hub": hub if hub.is_file() else None, "party": tags(pfm.get("party"))}
            for name, note in found:
                fm = pfm if note == hub else frontmatter(note, ws)
                state = as_text(fm.get("status")).strip().lower()
                if state in DONE:
                    done += 1
                    if note.is_file():
                        finished.append({"zone": zone.name, "project": project.name, "thread": name, "note": note,
                                         "hub": hub if hub.is_file() else None, "status": "done",
                                         "party": tags(fm.get("party") or pfm.get("party")),
                                         "updated": as_date(fm.get("updated")), "spoken": as_text(fm.get("spoken")).strip()})
                    continue
                held = hub_parked and note != hub          # parked with its project, whatever its own status
                state = "parked" if state in PARKED or held else state
                read = resume_read(note)
                has_block, resumed = read["block"], read["date"]
                mark = checkpoint_mark(note, ws)
                updated = as_date(fm.get("updated"))
                when = [d for d in (updated, mark["at"].date() if mark and mark["at"] else None) if d]
                row = {"zone": zone.name, "project": project.name, "thread": name, "note": note,
                       "rel": note.relative_to(zone).as_posix(), "hub": hub if hub.is_file() else None,
                       "party": tags(fm.get("party") or pfm.get("party")),
                       "updated": updated, "status": state,
                       "resume": has_block, "resumed": resumed,
                       "checkpoint": mark, "touched": max(when) if when else None,
                       "spoken": as_text(fm.get("spoken")).strip(), "read": read}
                if held:
                    row["held"] = True
                (parked if state == "parked" else rows).append(row)
        # By name, as you would look for one; the freshness bar carries the age.
        by_name = lambda r: (r["thread"].casefold(), r["project"].casefold())  # noqa: E731
        rows.sort(key=by_name)
        parked.sort(key=by_name)
        finished.sort(key=by_name)
        out[zone.name] = {"rows": rows, "parked": parked, "done": done, "folder": zone, "held": asleep,
                          "finished": finished, "projects": projects}
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


# ---- preview features: in Garrick's source, not yet released. Each is off
# unless the workspace switches it on in System/garrick-flags.json, as
# {"effort": true}. A workspace that runs Garrick's main as its own switches
# on what it is trying out; a release switches a feature on for everyone and
# drops its flag. Settings lists them, and which are on.
FLAGS = {
    "effort": ("Effort", "On Overview, the assistant's active time and list-price cost per thread over 7 days, 30 days or all "
               "time, read from Claude Code's own transcripts. Run effort.py --record nightly to keep days past their clean-up."),
    "ask": ("Ask", "In the Garrick app: the panel's field, and the box ⌘G opens, answer a request in plain words and act "
            "on it, through a warm assistant session under the scheduled jobs' caps (ask.py). Off, the field opens your assistant."),
}


def preview_flags(ws: Path) -> Dict[str, bool]:
    try:
        data = json.loads(ws.joinpath("System", "garrick-flags.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {k: isinstance(data, dict) and data.get(k) is True for k in FLAGS}


_PREFS = None


def prefs():
    """prefs.py, beside this file: the one way to the choices the page keeps."""
    global _PREFS
    if _PREFS is None:
        spec = importlib.util.spec_from_file_location("garrick_prefs", str(Path(__file__).with_name("prefs.py")))
        _PREFS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_PREFS)
    return _PREFS


_TL = None


def todo_lines():
    """todo_lines.py, beside this file: the reader for action lines."""
    global _TL
    if _TL is None:
        spec = importlib.util.spec_from_file_location("garrick_todo_lines", str(Path(__file__).with_name("todo_lines.py")))
        _TL = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_TL)
    return _TL


def system_notes(ws: Path) -> Dict[str, Path]:
    """The hub and thread notes of every project kept in System/, by name and
    by path from the workspace, lower-cased. Such a project has no Todo.md of
    its own: its actions live in a zone's, opening with its thread's link."""
    out: Dict[str, Path] = {}
    for project in visible_dirs(ws / "System"):
        hub = project / (project.name + ".md")
        if not hub.is_file() or as_text(frontmatter(hub, ws).get("type")).strip().lower() != "project":
            continue
        for note in [hub] + [t / (t.name + ".md") for t in visible_dirs(project / "Threads")]:
            if note.is_file():
                out.setdefault(note.relative_to(ws).with_suffix("").as_posix().lower(), note)
                out.setdefault(note.stem.lower(), note)
    return out


def todo_list(ws: Path, link: "Links", today: dt.date) -> List[dict]:
    """Preview: each zone's open actions, read from the notes, never written.
    Per zone: the lines of Todo.md grouped under its `## ` headings in their
    order, then the lines that sit in thread notes ("In thread notes"), then
    what was ticked today, with counts of the open, the overdue and the
    undated. An empty section is left out, but an empty Inbox is said. A
    label names a note in the zone or, failing that, a project in System/."""
    tl = todo_lines()
    out = []
    system = system_notes(ws)
    for zone in visible_dirs(ws / "Zones"):
        todo_md = zone / "Todo.md"
        notes = {}
        for n in tl.notes(str(zone)):
            rel = Path(n).relative_to(zone).with_suffix("").as_posix()
            notes.setdefault(rel.lower(), Path(n))
            notes.setdefault(Path(n).stem.lower(), Path(n))
        for name, n in system.items():
            notes.setdefault(name, n)

        def row(t, done=False):
            field = t["scheduled"] if t["waiting"] else t["due"]
            try:
                when = dt.date.fromisoformat(field) if field else None
            except ValueError:
                when = None
            late = bool(when and (when <= today if t["waiting"] else when < today)) and not done
            if t["file"] != "Todo.md":
                thread, note = Path(t["file"]).stem, zone / t["file"]
            elif t["target"]:
                thread, note = t["thread"], notes.get(t["target"].lower()) or notes.get(t["target"].rsplit("/", 1)[-1].lower())
            else:
                thread, note = None, None
            return dict(t, when=when, late=late, done=done, field=field if when else "", label=thread,
                        link=link(note) if note else "", zone=zone.name,
                        alpha=("%s\u0001%s" % (thread or ("\uffff" if t["unsure"] else ""), re.sub(r"[*_`]", "", t["text"]))).casefold())

        rows = [row(t) for t in tl.tasks(str(zone)) if t["text"] and "<action>" not in t["text"]]
        if not rows and not todo_md.is_file():
            continue
        order: List[str] = []
        if todo_md.is_file():
            order = [l[3:].strip() for l in todo_md.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("## ")]
        groups = []
        for name in order:
            if name in (g for g, _ in groups):
                continue
            items = [r for r in rows if r["file"] == "Todo.md" and r["section"] == name]
            if items or name == "Inbox":
                groups.append((name, sorted(items, key=lambda r: r["alpha"])))
        loose = [r for r in rows if r["file"] == "Todo.md" and r["section"] not in order]
        if loose:
            groups.append(("Not under a heading", sorted(loose, key=lambda r: r["alpha"])))
        elsewhere = [r for r in rows if r["file"] != "Todo.md"]
        if elsewhere:
            groups.append(("In thread notes", sorted(elsewhere, key=lambda r: (r["file"].lower(), r["alpha"]))))
        done = [row(t, done=True) for t in tl.done_on(str(zone), today) if t["text"] and "<action>" not in t["text"]]
        out.append({"zone": zone.name, "file": todo_md if todo_md.is_file() else None, "groups": groups,
                    "done": sorted(done, key=lambda r: r["alpha"]), "open": len(rows),
                    "late": sum(1 for r in rows if r["late"]), "undated": sum(1 for r in rows if r["when"] is None)})
    return out


def todo_row(r: dict, today: dt.date, actions: bool, said_late: bool = False) -> str:
    """One action. The row carries what a button sends back (its zone, file,
    the line's key) and what the filters and sorts read (late, undated, the
    date, the A-Z key); the buttons themselves are drawn only with actions.
    With `said_late`, a late line also says so in words (late_said()), as a
    thread's todo list on the Threads card draws it (#179)."""
    when = r["when"]
    if when is None:
        chip, cls = ("waiting" if r["waiting"] else "") if not actions else ("＋ chase date" if r["waiting"] else "＋ date"), "none"
    else:
        rel = "today" if when == today else "tomorrow" if (when - today).days == 1 else \
            "%s %d %s" % (when.strftime("%a"), when.day, when.strftime("%b"))
        chip = "%s %s" % ("Chase" if r["waiting"] else "Due", rel)
        cls = "overdue" if r["late"] else "today" if when == today else ""
    name = r["label"] or ("thread?" if r["unsure"] else "")
    thr = ('<a class="thr" href="%s">%s</a>' % (E(r["link"]), E(name)) if r["link"] and name
           else '<span class="thr%s">%s</span>' % (" unsure" if r["unsure"] and not r["label"] else "", E(name)) if name else "")
    meta = []
    if r["priority"] in ("🔺", "⏫"):
        meta.append('<span class="prio">%s priority</span>' % ("highest" if r["priority"] == "🔺" else "high"))
    if r["also"]:
        meta.append("<span>also in %d more</span>" % len(r["also"]))
    if r["file"] != "Todo.md":
        meta.append("<span>in the thread note</span>")
    if said_late and r["late"] and when is not None:
        meta.append('<span class="lateby">%s</span>' % E(late_said(r, today)))
    tick = ('<button class="tick" type="button" aria-label="%s: %s"></button>' % ("Reopen" if r["done"] else "Mark done", E(r["text"][:80]))
            if actions else "")
    date = ('<button class="tdate %s" type="button" title="Set the date">%s</button>' % (cls, E(chip)) if actions
            else '<span class="tdate %s">%s</span>' % (cls, E(chip)))
    return ('<div class="trow%s%s%s" data-z="%s" data-f="%s" data-k="%s" data-sec="%s" data-w="%d" data-d="%s" data-a="%s">'
            '%s<div class="tmain"><div class="ttext">%s%s</div>%s</div>%s</div>'
            % (" done" if r["done"] else "", " late" if r["late"] else "", " undated" if when is None else "",
               E(r["zone"]), E(r["file"]), E(r["key"]), E(r["section"] or ""), 1 if r["waiting"] else 0, E(r["field"]),
               E(r["alpha"]), tick, thr, md_inline(r["text"]),
               '<div class="tmeta">%s</div>' % "".join(meta) if meta else "", date))


def thread_actions(T: Dict[str, dict], lists: List[dict], C: Optional[dict], ws: Path) -> None:
    """Hang what a thread owes on each of its rows: `actions`, its open task
    lines, the late ones first; `next`, the first of them; `late`, whether
    one of them is overdue or due a chase; `checks`, the error findings
    against a file in its folder that the page can explain and fix
    (explained(), with Nurture's mechanical fix where it has one), and
    `flagged`, how many; and `urgent`, late or flagged.

    The actions are the zone's own task lines, the ones the Todo tab shows: a
    line in `Todo.md` whose `[[label]]` names the thread, and any line in the
    thread's own folder. Urgency is the action's and never the row's age. A
    thread nobody has touched for seven weeks is often simply slow, or
    waiting on somebody; a thread with nothing open at all is not urgent
    either. A warning never marks a row, nor an error the page cannot say
    in plain words with its fix (#179): both stay on the Checks card and in
    Nurture, where the user goes to tidy up on purpose."""
    flags: Dict[str, List[dict]] = {}
    for f in (C or {}).get("findings") or []:
        if f.get("severity") != "error":
            continue
        path = re.sub(r":\d+$", "", str(f.get("path") or ""))
        said = explained(f)
        if path and said:
            flags.setdefault(path, []).append(dict(said, path=path, finding=f))
    per_zone = {z["zone"]: [r for _, rows in z["groups"] for r in rows] for z in lists}
    for zone, data in T.items():
        labels: Dict[str, List[dict]] = {}
        folders: Dict[str, List[dict]] = {}
        for a in per_zone.get(zone, []):
            if a["file"] != "Todo.md":
                folders.setdefault(Path(a["file"]).parent.as_posix(), []).append(a)
            elif a["label"]:
                labels.setdefault(a["label"].casefold(), []).append(a)
        for r in data["rows"] + data["parked"]:
            mine, seen = [], set()
            for a in labels.get(r["thread"].casefold(), []) + folders.get(Path(r["rel"]).parent.as_posix(), []):
                if (a["file"], a["key"]) not in seen:
                    seen.add((a["file"], a["key"]))
                    mine.append(a)
            mine.sort(key=lambda a: (0 if a["late"] else 1, a["when"] or dt.date.max, a["alpha"]))
            here = r["note"].parent.relative_to(ws).as_posix() + "/"
            r["actions"] = mine
            r["next"] = mine[0] if mine else None
            r["late"] = any(a["late"] for a in mine)
            r["checks"] = []
            for path in sorted(p for p in flags if p.startswith(here)):
                for x in flags[path]:
                    if "fixed_by" not in x:
                        x["fixed_by"] = nurture_fix(ws, x["finding"])
                    r["checks"].append(dict(x, shown=path[len(here):]))
            r["flagged"] = len(r["checks"])
            r["urgent"] = bool(r["late"] or r["flagged"])


# The check chip (#179). An error finding marks a thread's row only where the
# page can say what is wrong in plain words and what fixes it. Each entry is
# the checks it is for, a pattern for check.py's message, what is wrong, what
# fixes it, and the request to copy for the assistant, said with the thread's
# name: `nurture`, `wrap` or `finish`. A message no entry matches leaves the
# row as it is. A wall finding is said without its material: no party, file
# content or words that matched, which the Checks card and Nurture name.
CHECK_SAID = (
    (("threads", "projects"), r"`status` is (?P<v>.+?), should be ",
     "Its status says {v}, a word no tool reads: a thread is active, parked or done.",
     "Set `status:` to whichever of the three it is.", "nurture"),
    (("threads", "projects"), r"frontmatter `type` is (?P<v>.+?), should be (?P<want>\w+)$",
     "It is not marked as a {want}, so the tools do not read it as one.",
     "Set `type: {want}` in its frontmatter.", "nurture"),
    (("projects",), r"frontmatter `zone` is (?P<v>.+?) but the project sits in (?P<zone>.+)$",
     "It names the zone {v}, but the project sits in {zone}.",
     "Set `zone: {zone}` in its frontmatter.", "nurture"),
    (("threads", "projects"), r"`(?P<key>created|updated)` is (?P<v>.+?), should be a date written YYYY-MM-DD$",
     "Its `{key}:` date, {v}, is not one the tools can read.",
     "Write it as the year, month and day, YYYY-MM-DD.", "nurture"),
    (("threads",), r"status is done but there is no `### Outcome` block$",
     "It says done, but has no Outcome block saying what was delivered or decided.",
     "Finish it: the threads skill writes the Outcome where the resume point was.", "finish"),
    (("threads",), r"`### Outcome` sits outside `## State of play`$",
     "Its Outcome block sits outside State of play, where the tools look for it.",
     "Move `### Outcome` under `## State of play`.", "nurture"),
    (("threads",), r"no `## State of play` section$",
     "It has no State of play section, where its resume point lives.",
     "Wrap it: a wrap writes the section and its Resume here block.", "wrap"),
    (("threads",), r"no `### Resume here` block$",
     "It has no Resume here block, so nobody can pick it up cold.",
     "Wrap it: a wrap writes the block.", "wrap"),
    (("threads",), r"`### Resume here` sits outside `## State of play`$",
     "Its Resume here block sits outside State of play, where the tools look for it.",
     "Move `### Resume here` under `## State of play`.", "nurture"),
    (("threads", "projects"), r"`party` (?P<v>\S+) is not a tag in the Parties table$",
     "It names the party {v}, which is not in the Parties table, so no wall can be checked for it.",
     "Correct the tag, or add the party to the Parties table first.", "nurture"),
    (("links",), r"links (?P<v>.+), in the (?P<zone>.+) zone; zones never reference each other unless asked$",
     "It links into the {zone} zone, and zones never link to each other.",
     "Take the link out, or keep what it points at in this zone.", "nurture"),
    (("placeholders",), r"unfilled (?P<v>.+); the install did not finish$",
     "It still holds {v}, which the installer should have filled in.",
     "Fill each one in, or take it out.", "nurture"),
    (("walls",), r"",
     "It names, links or quotes something from the far side of a wall, so its zone will not commit it.",
     "Take that material out. Nurture names the file and the wall, and takes it out only on your yes.", "nurture"),
)


def explained(f: dict) -> Optional[dict]:
    """What the page says of an error finding: `what` is wrong and what `fix`es
    it, in plain words, and `say`, the request to copy; None for a finding no
    entry of CHECK_SAID covers, which then marks no row."""
    check, message = str(f.get("check") or ""), str(f.get("message") or "")
    for checks, pattern, what, fix, say in CHECK_SAID:
        m = re.match(pattern, message) if check in checks else None
        if m:
            words = {k: (v if k in ("key", "want", "zone") else "“%s”" % v.strip("'\"")) for k, v in m.groupdict().items()}
            return {"check": check, "what": what.format(**words), "fix": fix.format(**words), "say": say}
    return None


_NURTURE: Dict[Path, object] = {}


def nurture_lib(ws: Path):
    """The workspace's own System/tools/nurture.py and a context for it, once
    per workspace, or None: the page asks it which findings it has a
    mechanical fix for, so a Fix button stands exactly where `nurture.py fix`
    would apply one. What it imports leaves sys.modules and sys.path as they
    were; the module keeps its own references."""
    if ws not in _NURTURE:
        lib, src = None, ws / "System" / "tools" / "nurture.py"
        if src.is_file():
            path, before, name = list(sys.path), set(sys.modules), "garrick_status_nurture"
            try:
                spec = importlib.util.spec_from_file_location(name, str(src))
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod                 # its dataclasses look their module up by name
                spec.loader.exec_module(mod)
                if callable(getattr(mod, "claim_mechanical", None)):
                    lib = (mod, mod.Ctx(ws, headless=True))
            except Exception:
                lib = None
            finally:
                sys.path[:] = path
                for k in set(sys.modules) - before:
                    sys.modules.pop(k, None)
        _NURTURE[ws] = lib
    return _NURTURE[ws]


def nurture_fix(ws: Path, f: dict) -> Optional[str]:
    """Nurture's mechanical fix for a finding, in words, or None where it has
    none: claimed as `nurture.py` claims it, so the page never offers a Fix
    the tool would hold or decline."""
    lib = nurture_lib(ws)
    if lib is None:
        return None
    N, ctx = lib
    try:
        item = N.Item("check", str(f.get("check") or ""), N.strip_line(str(f.get("path") or "")),
                      str(f.get("message") or ""), str(f.get("ear") or ""), str(f.get("severity") or "warning"))
        if not N.claim_mechanical(ctx, item) or not item.fix:
            return None
        if item.fix.get("op") == "status":
            return "Change it to `%s`, the word every tool reads." % item.fix.get("to")
        said = N.say_mechanical(item)
    except Exception:
        return None
    said = said[len(item.path) + 2:] if said.startswith(item.path + ": ") else said
    return said[:1].upper() + said[1:] + "."


def add_projects(T: Dict[str, dict]) -> Dict[str, List[dict]]:
    """Per zone, the projects the + dialog offers, each with the threads that
    have notes of their own. A project is parked when all its threads are."""
    out: Dict[str, List[dict]] = {}
    for zone, data in T.items():
        groups: Dict[str, list] = {}
        for r in data["rows"] + data["parked"]:
            groups.setdefault(r["project"], []).append(r)
        out[zone] = [{"name": p, "parked": all(r["status"] == "parked" for r in rs),
                      "subs": [{"name": r["thread"], "parked": r["status"] == "parked"}
                               for r in sorted(rs, key=lambda r: r["thread"].casefold()) if r["note"] != r["hub"]]}
                     for p, rs in groups.items()]
    return out


def todo_list_card(lists: List[dict], today: dt.date, actions: bool = False,
                   projects: Optional[Dict[str, List[dict]]] = None, link: Optional["Links"] = None,
                   styles: Optional[Dict[str, dict]] = None) -> str:
    """The Todo tab: one zone at a time, picked above the list, each in its
    colour and with its icon from Settings › Zones; All, Overdue and No date
    to filter; A–Z or by due date to sort. In the app with actions on, a box
    ticks a line (or reopens one ticked today), its date opens a menu of
    dates, and ＋ Add writes a new one."""
    styles = styles or {}
    panes = ""
    for z in lists:
        body = ""
        for name, rows in z["groups"]:
            slug = re.sub(r"[^a-z0-9]+", "-", ("%s-%s" % (z["zone"], name)).lower()).strip("-")
            items = "".join(todo_row(r, today, actions) for r in rows) or '<p class="tempty">Inbox clear.</p>'
            body += ('<details class="tgroup" id="tg-%s" open><summary>%s<span class="tname">%s</span><span class="n">%d</span></summary>'
                     '<div class="trows">%s</div></details>' % (slug, CHEV, E(name), len(rows), items))
        if z["done"]:
            slug = re.sub(r"[^a-z0-9]+", "-", z["zone"].lower()).strip("-")
            body += ('<details class="tgroup donegroup" id="tg-%s-done-today" open><summary>%s<span class="tname">Done today</span>'
                     '<span class="n">%d</span>%s</summary><div class="trows">%s</div></details>'
                     % (slug, CHEV, len(z["done"]), '<span class="hint tacts">Tick a box again to reopen it</span>' if actions else "",
                        "".join(todo_row(r, today, actions) for r in z["done"])))
        add = ('<button type="button" class="act primary tadd-open" data-zone="%s" title="Add an action to %s/Todo.md">＋ Add</button>'
               % (E(z["zone"]), E(z["zone"]))) if actions and z["file"] else ""
        opener = ('<a class="act" href="%s" title="Open %s/Todo.md">Open Todo.md</a>' % (E(link(z["file"])), E(z["zone"]))
                  if link and z["file"] else "")
        summ = ('<b>%d</b> open · <span class="%s"><b>%d</b> overdue or due a chase</span> · <b>%d</b> without a date'
                % (z["open"], "bad" if z["late"] else "", z["late"], z["undated"]))
        panes += '<div class="tz" data-zone="%s"><div class="tsum">%s<span class="tsum-acts">%s%s</span></div>%s</div>' % (
            E(z["zone"]), summ, add, opener, body)
    zones = "".join('<button type="button" data-tz="%s"%s>%s<span class="n">%d</span></button>'
                    % (E(z["zone"]), zone_attr(z["zone"], styles), zone_name(z["zone"], styles), z["open"])
                    for z in lists)
    bar = ('<div class="tbar"><div class="seg zseg" role="group" aria-label="Zone"%s>%s</div>'
           '<div class="seg fseg" role="group" aria-label="Show"><button type="button" data-tf="all">All</button>'
           '<button type="button" data-tf="late">Overdue</button><button type="button" data-tf="nodate">No date</button></div>'
           '<div class="seg sseg" role="group" aria-label="Sort"><button type="button" data-ts="alpha" title="By thread, then by the action">A–Z</button>'
           '<button type="button" data-ts="date" title="Dated lines first, soonest first; then the rest, A–Z">Due date</button></div>'
           '<span class="hint">%s</span></div>'
           % (" hidden" if len(lists) < 2 else "", zones,
              "Tick to close. Click a date to set it; a dated Inbox line moves to This week, Soon or Waiting on." if actions
              else "Read from the notes. A preview feature."))
    dialog = add_dialog("".join(add_tree(z["zone"], (projects or {}).get(z["zone"], [])) for z in lists)) if actions else ""
    return '<div id="todolist" class="todotab%s">%s%s%s</div>' % ("" if actions else " ro", bar, panes, dialog)


_GD = None


def guide_mod():
    """guide.py, beside this file: the Markdown renderer, and the Guide tab's pages."""
    global _GD
    if _GD is None:
        spec = importlib.util.spec_from_file_location("garrick_guide", str(Path(__file__).with_name("guide.py")))
        _GD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_GD)
    return _GD


def guide_tab(ws: Path) -> Tuple[str, str]:
    """The Guide tab: the docs this workspace was installed with, in System/garrick-docs/,
    its links to Garrick's own files pointing at the release it runs. (The tab's body,
    the pages that wait at the end of the page until it opens.)"""
    gd = guide_mod()
    try:
        text = ws.joinpath(*CHANGELOG).read_text(encoding="utf-8")
    except OSError:
        text = None
    ref = gd.release_ref(text, edge=workspace_stamp(ws).get("from") in ("clone", "adopted"))
    return gd.guide(ws.joinpath(*gd.DOCS), ref)


_EF = None


def effort():
    """effort.py, beside this file: the reader for the time and token ledger."""
    global _EF
    if _EF is None:
        spec = importlib.util.spec_from_file_location("garrick_effort", str(Path(__file__).with_name("effort.py")))
        _EF = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_EF)
    return _EF


def say_time(secs: float) -> str:
    m = int(round(secs / 60))
    return "%d h %02d" % (m // 60, m % 60) if m >= 60 else "%d min" % m if m else "–"


def say_cost(usd: float) -> str:
    return "$%.0f" % usd if usd >= 100 else "$%.2f" % usd if usd else "–"


def say_tokens(n: int) -> str:
    return "%.1f M" % (n / 1e6) if n >= 1e6 else "%d k" % round(n / 1e3) if n >= 1e3 else str(n)


class Effort:
    """The last 30 days of the effort ledger, laid over the Threads card: each
    row's active time and list-price cost, for the card's Time and Cost views.
    Rows take their figures with take(), and whatever no row took is said once
    at the foot by foot(), so the card's figures add up to its total."""

    DAYS = 30

    def __init__(self, rows: Dict[tuple, dict], today: dt.date):
        since = (today - dt.timedelta(days=self.DAYS - 1)).isoformat()
        self.fields = ("seconds", "cost", "sessions", "unpriced") + tuple(effort().TOKENS)
        self.agg: Dict[tuple, dict] = {}
        for (day, zone, project, thread), r in rows.items():
            if day >= since:
                a = self.agg.setdefault((zone, project, thread), {f: 0 for f in self.fields})
                for f in self.fields:
                    a[f] += r.get(f) or 0
        self.used: set = set()
        per_project: Dict[tuple, dict] = {}
        for (zone, project, _), a in self.agg.items():
            p = per_project.setdefault((zone, project), {"seconds": 0, "cost": 0.0})
            p["seconds"] += a["seconds"]
            p["cost"] += a["cost"]
        self.top = {k: max([p[k] for p in per_project.values()] + [0]) or 1 for k in ("seconds", "cost")}
        self.total = {k: sum(a[k] for a in self.agg.values()) for k in ("seconds", "cost", "sessions")}

    def take(self, keys) -> dict:
        """The figures of these (zone, project, thread) keys, summed, and
        marked as shown. A key already shown elsewhere counts once."""
        out = {f: 0 for f in self.fields}
        for k in keys:
            if k in self.agg and k not in self.used:
                self.used.add(k)
                for f in self.fields:
                    out[f] += self.agg[k][f]
        return out

    def keys(self, zone: str, project: str) -> List[tuple]:
        return [k for k in self.agg if k[0] == zone and k[1] == project]

    def attrs(self, a: dict) -> str:
        return ' data-s="%d" data-c="%.4f"' % (a["seconds"], a["cost"])

    def cells(self, a: dict) -> str:
        """The Time and Cost cells of a row, each a bar against the largest
        project and a figure; CSS shows the pair the card's view asks for."""
        tip = "Last %d days: %s input · %s output · %s cache read · %s cache write · %d session%s%s" % (
            self.DAYS, say_tokens(a["input"]), say_tokens(a["output"]), say_tokens(a["cache_read"]),
            say_tokens(a["cache_write"]), a["sessions"], "" if a["sessions"] == 1 else "s",
            " · some messages from a model with no list price, not costed" if a["unpriced"] else "")
        return "".join('<div class="ebar %s">%s</div><span class="num %s" data-tip="%s">%s</span>'
                       % (cls, '<i style="width:%.1f%%"></i>' % (a[k] / self.top[k] * 100) if a[k] else "", cls, E(tip), E(say(a[k])))
                       for cls, k, say in (("mt", "seconds", say_time), ("mc", "cost", say_cost)))

    def zone_meta(self, zone: str, also: Tuple[str, ...] = ()) -> str:
        a = {k: sum(v[k] for kk, v in self.agg.items() if kk[0] in (zone,) + also) for k in ("seconds", "cost")}
        return '<span class="meta me">%s · %s</span>' % (E(say_time(a["seconds"])), E(say_cost(a["cost"])))

    def foot(self) -> str:
        """What no row showed, by kind, then the whole: the line that makes
        the card's figures add up."""
        kinds: Dict[str, dict] = {}
        for k, a in self.agg.items():
            if k in self.used:
                continue
            kind = "outside the zones" if not k[0] else "started in a zone's own folder" if not k[1] else "finished or renamed threads"
            t = kinds.setdefault(kind, {"seconds": 0, "cost": 0.0})
            t["seconds"] += a["seconds"]
            t["cost"] += a["cost"]
        parts = ["%s %s · %s" % (kind[:1].upper() + kind[1:], say_time(t["seconds"]), say_cost(t["cost"]))
                 for kind, t in sorted(kinds.items(), key=lambda kv: -kv[1]["seconds"])]
        return ('<p class="hint me efoot"><b>Last %d days: %s active · %s at list price · %d session%s.</b>%s Claude Code sessions, read '
                'from their transcripts; Codex is not counted yet. Active time counts the gaps between messages up to five minutes. '
                'A project&#39;s figure includes its work in no thread. Scheduled jobs are in Assistant calls.</p>'
                % (self.DAYS, E(say_time(self.total["seconds"])), E(say_cost(self.total["cost"])), self.total["sessions"],
                   "" if self.total["sessions"] == 1 else "s", (" " + E(" · ".join(parts)) + ".") if parts else ""))


def torder_switch() -> str:
    """By name, Recent: the order of each zone's projects and threads on the
    Threads card. Recent is most recently touched first (#143)."""
    return ('<div class="tmodes torder" role="group" aria-label="Order">%s</div>'
            % "".join('<button type="button" data-to="%s"%s aria-pressed="%s">%s</button>'
                      % (k, ' class="on"' if k == "name" else "", "true" if k == "name" else "false", label)
                      for k, label in (("name", "By name"), ("recent", "Recent"))))


def tview_switch() -> str:
    """Updated, Time, Cost: what the Threads card's bars and figures show."""
    return ('<div class="tmodes" role="group" aria-label="What the bars show">%s</div>'
            % "".join('<button type="button" data-tm="%s"%s>%s</button>' % (k, ' class="on"' if k == "updated" else "", label)
                      for k, label in (("updated", "Updated"), ("time", "Time"), ("cost", "Cost"))))


# The Time and Cost views of the Threads card. A row carries all three pairs
# of cells; the view shows one. A unit (a project with its threads, or a
# thread alone) carries data-a, its place by name, and data-s and data-c, its
# figures, so each view can put the largest first and Updated put them back.
# By name and Recent choose the order underneath: Recent puts the most
# recently touched first, read from each unit's first row's data-r.
TVIEW_CSS = r"""
.tmodes{display:inline-flex;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:2px;margin:0 0 8px}
.tmodes button{border:0;background:none;color:var(--ink2);font:inherit;font-size:12px;padding:4px 10px;border-radius:6px;cursor:pointer}
.tmodes button.on{background:var(--wash);color:var(--ink)}
.tview .mt,.tview .mc,.tview .me{display:none}
.tview[data-tm="time"] .mt,.tview[data-tm="cost"] .mc{display:block}.tview:not([data-tm="updated"]) .me{display:block}
.tview:not([data-tm="updated"]) .mu{display:none!important}
.tview:not([data-tm="updated"]) .thread{grid-template-columns:minmax(0,1fr) 80px 60px}
.tview .num.mt,.tview .num.mc{text-align:right;font-variant-numeric:tabular-nums}
.ebar{height:6px;border-radius:3px;background:var(--grid);position:relative}.ebar i{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:var(--accent);min-width:2px}
.efoot{margin-top:10px}.efoot b{font-weight:600;color:var(--ink2)}
.chip.tchip{font:inherit;font-size:11px;line-height:1.45;background:none;cursor:pointer}.chip.tchip:hover{border-color:var(--base)}
.chip.todo.ok{color:var(--good);border-color:color-mix(in srgb,var(--good) 45%,transparent)}.chip.tchip[aria-expanded="true"]{background:var(--wash)}
.tpop{grid-column:1/-1;margin:2px 0 4px 16px;padding:4px 6px;background:var(--surface);border:1px solid var(--line);border-radius:10px;font-size:13px}
.tpop[hidden]{display:none}.tpop-h{margin:4px 8px 2px;font-size:11.5px;color:var(--muted)}.tpop .trows{padding:0}.tpop .lateby{color:var(--critical)}
.cfind{padding:8px}.cfind+.cfind{border-top:1px solid var(--grid)}.cfind p{margin:0 0 4px;line-height:1.45}.cfind .cfix{color:var(--ink2)}
.cfind .hacts{margin:6px 0 2px}.webonly{display:none}.nohost .webonly{display:inline}
"""

TVIEW_JS = r"""
document.querySelectorAll('.tview').forEach(function(v){
var st={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,x){try{localStorage.setItem(k,x)}catch(e){}}};
/* a unit's last touch is on its first row: the thread's own, or its project's, which is its newest thread's */
function rec(x){var t=x.classList.contains('thread')?x:x.querySelector('.thread');return(t&&t.dataset.r)||''}
function order(c){var m=v.dataset.tm,key=m==='time'?'s':m==='cost'?'c':null,recent=v.dataset.to==='recent',kids=[].filter.call(c.children,function(x){return x.dataset.a!==undefined});
kids.sort(function(a,b){if(key){var d=(+b.dataset[key]||0)-(+a.dataset[key]||0);if(d)return d}
if(recent){var ra=rec(a),rb=rec(b);if(ra!==rb)return rb>ra?1:-1}return a.dataset.a-b.dataset.a});
var tail=[].filter.call(c.children,function(x){return x.matches('details.parked')})[0]||null;kids.forEach(function(k){c.insertBefore(k,tail)})}
function sort(){v.querySelectorAll('.tsort').forEach(order)}
function mode(m){v.dataset.tm=m;v.querySelectorAll('.tmodes button[data-tm]').forEach(function(b){b.classList.toggle('on',b.dataset.tm===m)});sort();st.set('garrick-threads-view',m)}
/* By name or Recent, remembered as the folds are, and said in the line under the card */
function by(o){v.dataset.to=o;v.querySelectorAll('.tmodes button[data-to]').forEach(function(b){b.classList.toggle('on',b.dataset.to===o);b.setAttribute('aria-pressed',b.dataset.to===o?'true':'false')});sort();
var g=v.querySelector('.gsum');if(g)g.textContent=g.textContent.replace(/by name|most recently touched first/,o==='recent'?'most recently touched first':'by name');st.set('garrick-threads-order',o)}
v.querySelectorAll('.tmodes button[data-tm]').forEach(function(b){b.onclick=function(){mode(b.dataset.tm)}});
v.querySelectorAll('.tmodes button[data-to]').forEach(function(b){b.onclick=function(){by(b.dataset.to)}});
var m=st.get('garrick-threads-view');if(m&&v.querySelector('.tmodes button[data-tm="'+m+'"]'))mode(m);
var o=st.get('garrick-threads-order');if(o&&v.querySelector('.tmodes button[data-to="'+o+'"]'))by(o)});
"""

# The Threads card's chips (#179): `todo N` and `check` each open their list
# at the foot of their row, one at a time per row, and shut it on a second
# click; the thread's card stands aside while a list is open. The list left
# open is remembered in this window, so the rebuild a tick brings shows it
# again, until the row has nothing left to list.
TCHIP_JS = r"""
(function(){var KEY='garrick-tchip';
function pop(b){return document.getElementById(b.getAttribute('aria-controls'))}
function set(b,o){var p=pop(b);if(!p)return;p.hidden=!o;b.setAttribute('aria-expanded',o?'true':'false')}
function keep(id){try{if(id)sessionStorage.setItem(KEY,id);else sessionStorage.removeItem(KEY)}catch(e){}}
document.querySelectorAll('.tview').forEach(function(v){v.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('button.tchip');if(!b)return;
e.preventDefault();e.stopPropagation();var p=pop(b);if(!p)return;var o=p.hidden,row=b.closest('.thread');
[].forEach.call(document.querySelectorAll('button.tchip[aria-expanded="true"]'),function(x){set(x,false)});
set(b,o);keep(o?p.id:'');if(o&&window.ThreadRows)ThreadRows.close();if(o&&row)row.classList.remove('on')})});
var was=null;try{was=sessionStorage.getItem(KEY)}catch(e){}
if(was){var b=document.querySelector('button.tchip[aria-controls="'+was.replace(/[^\w-]/g,'')+'"]');if(b)set(b,true);else keep('')}})();
"""


# ---- adding a line from the Todo list. Shared with the workspace's own page:
# the dialog, the tree it picks a project or thread from, its styles and its
# script. Each page supplies only TaddOpen's button and window.TaddSend, the
# way its request reaches page_action.py.
def add_tree(zone: str, projects: List[dict]) -> str:
    """The thread picker: No thread, then each live project with its threads
    folding under it, then the parked ones under their own label, since an
    action can still belong to them. `projects` are dicts with name, parked
    and subs, each sub a dict with name and parked."""
    name = "tadd-t-%s" % zone
    out = ['<label class="tnode"><input type="radio" name="%s" value="-" checked><span>No thread</span></label>' % E(name)]
    shown_parked = False
    for r in sorted(projects, key=lambda r: (bool(r["parked"]), r["name"].casefold())):
        if r["parked"] and not shown_parked:
            out.append('<div class="tsep">Parked</div>')
            shown_parked = True
        node = '<label class="tnode"><input type="radio" name="%s" value="%s"><span>%s</span></label>' % (E(name), E(r["name"]), E(r["name"]))
        if not r["subs"]:
            out.append('<div class="tproj" data-n="%s"><span class="tchev-sp"></span>%s</div>' % (E(r["name"].lower()), node))
            continue
        subs = "".join('<label class="tnode tsub" data-n="%s"><input type="radio" name="%s" value="%s"><span>%s</span>%s</label>'
                       % (E(t["name"].lower()), E(name), E(r["name"] + "/" + t["name"]), E(t["name"]),
                          ' <span class="chip">parked</span>' if t["parked"] else "") for t in r["subs"])
        n = len(r["subs"])
        count = "%d thread%s" % (n, "" if n == 1 else "s")
        out.append('<div class="tproj" data-n="%s"><button type="button" class="tchev" aria-expanded="false" title="Show its %s">%s</button>'
                   '%s<small>%s</small><div class="tsubs" hidden>%s</div></div>' % (E(r["name"].lower()), count, CHEV, node, count, subs))
    return '<div class="ttree" data-zone="%s" hidden>%s</div>' % (E(zone), "".join(out))


def add_dialog(trees: str) -> str:
    return ('<dialog id="tadd" class="tadd" aria-labelledby="tadd-h"><h3 id="tadd-h">New action in <span id="tadd-zone"></span></h3>'
            '<label class="tlab" for="tadd-text">What</label><input type="text" id="tadd-text" maxlength="500" autocomplete="off" placeholder="Send the revised terms">'
            '<div class="tlab">Thread <span class="hint">optional</span><input type="search" id="tadd-filter" placeholder="Filter" aria-label="Filter projects and threads"></div>'
            '<div class="ttrees">%s</div><div class="tlab">Date <span class="hint">optional</span></div>'
            '<div class="tadd-dates"><div class="seg" role="group" aria-label="Quick dates"><button type="button" data-q="" class="on">None</button>'
            '<button type="button" data-q="0">Today</button><button type="button" data-q="1">Tomorrow</button><button type="button" data-q="7">In a week</button></div>'
            '<input type="date" id="tadd-date" aria-label="Date"></div><p class="hint" id="tadd-where">Goes to the Inbox.</p>'
            '<div class="tadd-acts"><button type="button" class="act" id="tadd-cancel">Cancel</button>'
            '<button type="button" class="act primary" id="tadd-ok">Add</button></div></dialog>' % trees)


TADD_CSS = r"""
.act.primary{background:var(--accent);border-color:var(--accent);color:#fff}.act.primary:hover{filter:brightness(1.08);color:#fff}
dialog.tadd{width:min(520px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow:auto;border:1px solid var(--line);border-radius:14px;background:var(--surface);color:var(--ink);padding:20px 22px;box-shadow:0 18px 60px rgba(0,0,0,.25)}
dialog.tadd::backdrop{background:rgba(0,0,0,.28)}
.tadd h3{margin:0 0 14px;font-size:16px}.tadd .tlab{display:flex;align-items:center;gap:8px;margin:14px 0 6px;font-size:12px;font-weight:600;color:var(--ink2)}
.tadd .tlab .hint{font-weight:400}.tadd input[type=text],.tadd input[type=search],.tadd input[type=date]{font:inherit;font-size:13px;color:var(--ink);background:var(--raise);border:1px solid var(--line);border-radius:8px;padding:7px 10px}
.tadd #tadd-text{width:100%}.tadd #tadd-filter{margin-left:auto;width:150px;padding:4px 8px;font-size:12px}
.ttrees{border:1px solid var(--line);border-radius:10px;background:var(--raise);max-height:260px;overflow:auto;padding:6px 8px}
.tnode{display:inline-flex;align-items:center;gap:7px;padding:4px 2px;font-size:13px;cursor:pointer}.tnode input{accent-color:var(--accent);margin:0}
.tproj{display:flex;flex-wrap:wrap;align-items:center;gap:2px 4px;border-top:1px solid var(--grid)}.tproj small{color:var(--muted);font-size:11.5px}
.tsep{font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);padding:10px 2px 2px;border-top:1px solid var(--grid)}
.tchev,.tchev-sp{width:20px;height:20px;flex:none}.tchev{border:0;background:none;padding:0;cursor:pointer;color:var(--muted);line-height:0}
.tchev .chev{width:13px;height:13px}.tchev[aria-expanded="true"] .chev{transform:rotate(90deg)}
.tsubs{flex-basis:100%;padding-left:26px;display:flex;flex-direction:column}.tsubs[hidden]{display:none}.tnode.tsub{font-size:12.5px}
.tadd-dates{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.tadd-dates .seg button{padding:5px 10px;font-size:12px;line-height:1.2}
.tadd-acts{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}.tadd-acts .act{font-size:12.5px;padding:7px 14px}
.tadd .shake{animation:tshake .3s}@keyframes tshake{25%{transform:translateX(-4px)}75%{transform:translateX(4px)}}
"""

MANAGE_CSS = r"""
.mg-new{display:flex;gap:6px;justify-content:flex-end;margin:0 0 8px}.mg-acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
dialog.gmanage .mg-msg{margin:12px 0 0;font-size:12.5px;color:var(--ink2)}dialog.gmanage .mg-msg.bad{color:var(--critical)}
dialog.gmanage select,dialog.gmanage input[type=text]{font:inherit;font-size:13px;color:var(--ink);background:var(--raise);border:1px solid var(--line);border-radius:8px;padding:7px 10px;width:100%;box-sizing:border-box}
dialog.gmanage .mg-row{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin-top:18px}
dialog.gmanage ul{margin:8px 0 0;padding-left:18px;font-size:13px}.act.danger{color:var(--critical);border-color:var(--critical)}
.act.danger:disabled{opacity:.45}#mg-undo{position:fixed;left:50%;bottom:64px;transform:translateX(-50%);z-index:11;display:flex;gap:10px;align-items:center;
background:var(--ink);color:var(--surface);font-size:13px;padding:7px 8px 7px 14px;border-radius:10px}
"""

# Making, renaming and deleting projects and threads (#36, #37, #38): its own
# script, so an error here leaves the rest of the page working; the card's
# head asks window.GarrickManage only when this loaded. In the app, a
# dialog's request goes to page_action.py, which runs
# scaffold.py; anywhere else the dialog copies the phrase to say instead.
MANAGE_JS = r"""
(function(){var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick,D={zones:{},acting:false};
try{D=JSON.parse(document.getElementById('manage-data').textContent)}catch(e){}
var act=!!(host&&D.acting);
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function say(s){var t=document.getElementById('toast');if(!t)return;t.textContent=s;t.style.opacity=1;clearTimeout(say.t);say.t=setTimeout(function(){t.style.opacity=0},4000)}
function copy(text,done){var ok=function(){say(done)};if(host){host.postMessage({copy:text});ok();return}
if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(text).then(ok,function(){say(text)});return}say(text)}
function send(q,said){if(window.GarrickAct&&GarrickAct(q,said))return;host.postMessage({act:q});say(said)}
/* the card's own buttons: Rename and Delete on a thread or a project, New thread here on a project */
window.GarrickManage=function(o){if(!o||!o.mg||o.held)return'';var m=esc(JSON.stringify(o.mg)),k=o.mg[2]?'thread':'project';
return'<div class="mg-acts">'+(k==='project'?'<button class="act" type="button" data-manage="new-thread" data-mg="'+m+'">New thread here</button>':'')
+'<button class="act" type="button" data-manage="rename" data-mg="'+m+'">Rename…</button>'
+'<button class="act" type="button" data-manage="delete" data-mg="'+m+'">Delete…</button></div>'};
function dialog(title,body,buttons){var d=document.getElementById('gmanage');if(d)d.remove();d=document.createElement('dialog');d.id='gmanage';
d.className='tadd gmanage';d.innerHTML='<h3>'+esc(title)+'</h3>'+body+'<p class="mg-msg" id="mg-msg"></p><div class="mg-row">'+buttons+'</div>';
document.body.appendChild(d);d.addEventListener('close',function(){d.remove()});d.addEventListener('click',function(e){if(e.target===d)d.close()});
d.showModal();var c=d.querySelector('[data-cancel]');if(c){c.onclick=function(){d.close()};}return d}
function field(id,label,value){return'<label class="tlab" for="'+id+'">'+esc(label)+'</label><input type="text" id="'+id+'" value="'+esc(value||'')+'" autocomplete="off">'}
function select(id,label,opts,chosen){return'<label class="tlab" for="'+id+'">'+esc(label)+'</label><select id="'+id+'">'
+opts.map(function(x){var v=Array.isArray(x)?x[0]:x,n=Array.isArray(x)?x[1]:x;return'<option value="'+esc(v)+'"'+(v===chosen?' selected':'')+'>'+esc(n)+'</option>'}).join('')+'</select>'}
function val(d,id){var e=d.querySelector('#'+id);return e?e.value.trim():''}
function bad(d,t){var m=d.querySelector('#mg-msg');m.textContent=t;m.classList.add('bad')}
/* a zone still busy with another request (WORK_JS) keeps the dialog open and says so */
function busy(d,z){var b=act&&window.GarrickBusy&&GarrickBusy(z);if(b)bad(d,z+' is still busy: '+b+' Try again when it is done.');return!!b}
var CANCEL='<button class="act" type="button" data-cancel>Cancel</button>';
/* what already has the name being typed, or one heard as it (#140): any project or thread, in any zone and any
   status, by the test scaffold.py puts a sibling's name to. It warns and never refuses: Make it still makes it. */
var DUP='<p class="mg-msg mg-dup" id="mg-dup" role="status" hidden></p>';
function dup(d){var m=d.querySelector('#mg-dup'),n=val(d,'mg-name'),F=window.GarrickFind,hits=F&&n?F.alike(n):[];m.hidden=!hits.length;
if(!hits.length){m.innerHTML='';return}
function what(h){return esc([h.k==='p'?'a project':h.p,h.z].concat(h.s==='live'?[]:[h.s]).join(', '))}
m.innerHTML='Already there: '+(hits.length===1?esc(hits[0].n)+' ('+what(hits[0])+'). <a href="'+esc(hits[0].u)+'">Open it</a>'
:hits.slice(0,3).map(function(h){return'<a href="'+esc(h.u)+'" title="Open its note">'+esc(h.n)+'</a> ('+what(h)+')'}).join('; ')+(hits.length>3?'; and '+(hits.length-3)+' more':'')+'.')}
function watch(d){var i=d.querySelector('#mg-name');i.addEventListener('input',function(){dup(d)});dup(d)}
function zoneNames(){return Object.keys(D.zones||{})}
function zoneOf(){var z=(window.GarrickPrefs&&localStorage.getItem('garrick-graph-place'))||'';return D.zones[z]?z:zoneNames()[0]||''}
function newThread(mg){var z=mg?mg[0]:zoneOf(),zs=zoneNames();if(!zs.length){say('There is no zone yet.');return}
var d=dialog('New thread',select('mg-zone','Zone',zs,z)+'<div id="mg-p"></div>'+field('mg-name','Name, one you can say')+DUP,
CANCEL+'<button class="act primary" type="button" data-go>'+(act?'Make it':'Copy the phrase')+'</button>');
function projects(){var p=(D.zones[val(d,'mg-zone')]||{}).projects||[];d.querySelector('#mg-p').innerHTML=p.length?select('mg-project','Project',p,mg?mg[1]:''):'<p class="mg-msg">No project in this zone yet: make one first.</p>'}
d.querySelector('#mg-zone').onchange=projects;projects();watch(d);d.querySelector('#mg-name').focus();
d.querySelector('[data-go]').onclick=function(){var q={verb:'new-thread',zone:val(d,'mg-zone'),project:val(d,'mg-project'),name:val(d,'mg-name')};
if(!q.project||!q.name)return bad(d,'Pick a project and give the thread a name.');if(busy(d,q.zone))return;
d.close();if(act)send(q,'Making '+q.name+' in '+q.project+'…');else copy('new thread '+q.name+' in '+q.project,'Copied “new thread '+q.name+' in '+q.project+'”. Paste it to your assistant.')}}
function newProject(){var zs=zoneNames(),z=zoneOf();if(!zs.length){say('There is no zone yet.');return}
var d=dialog('New project',select('mg-zone','Zone',zs,z)+field('mg-name','Name, one you can say')+DUP+'<div id="mg-pt"></div>'+field('mg-thread','Its first thread'),
CANCEL+'<button class="act primary" type="button" data-go>'+(act?'Make it':'Copy the phrase')+'</button>');
function parties(){var p=(D.zones[val(d,'mg-zone')]||{}).parties||[];d.querySelector('#mg-pt').innerHTML=p.length?select('mg-party','For',p,''):'<p class="mg-msg">No party belongs to this zone yet: add it to System/context.md first.</p>'}
d.querySelector('#mg-zone').onchange=parties;parties();watch(d);d.querySelector('#mg-name').focus();
d.querySelector('[data-go]').onclick=function(){var q={verb:'new-project',zone:val(d,'mg-zone'),name:val(d,'mg-name'),party:val(d,'mg-party'),thread:val(d,'mg-thread')};
if(!q.name||!q.party||!q.thread)return bad(d,'A project needs a name, its party and its first thread.');if(busy(d,q.zone))return;
d.close();if(act)send(q,'Making '+q.name+'…');else copy('new project '+q.name+' for '+q.party+' in '+q.zone+', first thread '+q.thread,'Copied the phrase. Paste it to your assistant.')}}
function rename(mg){var old=mg[2]||mg[1],kind=mg[2]?'thread':'project';
var d=dialog('Rename '+old,field('mg-name','New name, one you can say',old)+'<p class="mg-msg">Its folder, its note and every link to it in '+esc(mg[0])+' follow, in one commit. The old name stays a heard name for it.</p>',
CANCEL+'<button class="act primary" type="button" data-go>'+(act?'Rename':'Copy the phrase')+'</button>');var i=d.querySelector('#mg-name');i.focus();i.select();
d.querySelector('[data-go]').onclick=function(){var to=val(d,'mg-name');if(!to||to===old)return bad(d,'Give it a new name.');
var q={verb:'rename',zone:mg[0],project:mg[1],to:to};if(mg[2])q.thread=mg[2];if(busy(d,q.zone))return;d.close();
if(act)send(q,'Renaming '+old+'…');else copy('rename '+old+' to '+to,'Copied “rename '+old+' to '+to+'”. Paste it to your assistant.')}}
function del(mg){var name=mg[2]||mg[1],kind=mg[2]?'thread':'project',subs=mg[5]||[];
var gone=['its folder, '+mg[3]+' file'+(mg[3]===1?'':'s')];if(kind==='thread')gone.push('its line in the project’s note');
if(mg[4])gone.push(mg[4]+' open line'+(mg[4]===1?'':'s')+' in Todo.md that name'+(mg[4]===1?'s':'')+' it');
if(subs.length)gone.push('its threads: '+subs.join(', '));
var body='<p>Deleting '+esc(name)+' removes:</p><ul>'+gone.map(function(g){return'<li>'+esc(g)+'</li>'}).join('')+'</ul>'
+'<p class="mg-msg">Meetings pages stay, and so does '+esc(mg[0])+'’s history: the deletion can be undone. To keep it on record, finish it or park it instead.</p>'
+(kind==='project'?field('mg-confirm','Type '+name+' to delete it'):'');
var d=dialog('Delete '+name+'?',body,'<button class="act" type="button" data-finish>Finish instead</button><button class="act" type="button" data-park>Park instead</button>'
+CANCEL+'<button class="act danger" type="button" data-go'+(kind==='project'?' disabled':'')+'>Delete</button>');
d.querySelector('[data-cancel]').focus();
var c=d.querySelector('#mg-confirm');if(c){c.oninput=function(){d.querySelector('[data-go]').disabled=c.value.trim()!==name}}
d.querySelector('[data-finish]').onclick=function(){d.close();copy('finish '+name,'Copied “finish '+name+'”. Paste it to your assistant.')};
d.querySelector('[data-park]').onclick=function(){var q={verb:'park',zone:mg[0],project:mg[1]};if(mg[2])q.thread=mg[2];if(busy(d,q.zone))return;d.close();
if(act)send(q,'Parking '+name+'…');else copy('park '+name,'Copied “park '+name+'”. Paste it to your assistant.')};
d.querySelector('[data-go]').onclick=function(){var q={verb:'delete',zone:mg[0],project:mg[1],confirm:name};if(mg[2])q.thread=mg[2];if(busy(d,q.zone))return;d.close();
if(act)send(q,'Deleting '+name+'…');else copy('delete '+name,'Copied “delete '+name+'”. Paste it to your assistant, who asks you again.')}}
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('button[data-manage]');if(!b)return;e.preventDefault();e.stopPropagation();
var mg=null;try{mg=b.dataset.mg?JSON.parse(b.dataset.mg):null}catch(err){}
var v=b.dataset.manage;if(v==='new-project')newProject();else if(v==='new-thread')newThread(mg);else if(v==='rename'&&mg)rename(mg);else if(v==='delete'&&mg)del(mg)},true);
/* Undo, for a minute after a deletion or a rename from the page: the app rebuilds the page after
   every request, so the commit to revert is kept in this browser until then */
var prev=window.GarrickActed;window.GarrickActed=function(q,out){
if(q&&out&&out.ok&&(q.verb==='delete'&&q.confirm||q.verb==='rename')){var m=/(?:commit )([0-9a-f]{7,40})/.exec(out.say||'');
try{localStorage.setItem('garrick-undo',JSON.stringify({zone:q.zone,commit:m?m[1]:'',what:q.verb==='delete'?'Deleted '+q.confirm:'Renamed '+(q.thread||q.project)+' to '+q.to,until:Date.now()+60000}))}catch(e){}}
if(prev)return prev(q,out)};
function offer(){var u=null;try{u=JSON.parse(localStorage.getItem('garrick-undo')||'null')}catch(e){}if(!u||!act||!u.commit||u.until<Date.now())return;
var bar=document.createElement('div');bar.id='mg-undo';bar.innerHTML='<span>'+esc(u.what)+'.</span><button class="act" type="button">Undo</button>';
document.body.appendChild(bar);bar.querySelector('button').onclick=function(){localStorage.removeItem('garrick-undo');bar.remove();send({verb:'undo',zone:u.zone,commit:u.commit},'Undoing…')};
setTimeout(function(){bar.remove()},Math.max(0,u.until-Date.now()))}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',offer);else offer();
})();
"""

# ---- finding a project or a thread by name (#140). Before starting a thread
# you want to know whether one already exists, and the one most easily made
# twice is the one the card does not show: parked under another project, in
# another zone, or finished. The box at the head of the Threads card looks
# through every zone at once, live, parked and finished, by name and spoken
# form (find_data), word by word, each word the start of a word of the name,
# its project's or its zone's, ignoring case and accents. While a query is in
# it, the matches take the columns' place, live first, then parked, then
# finished, each with its project and zone and a chip saying parked or done;
# the columns themselves are only hidden, so clearing the box, or Esc, shows
# them exactly as they were, folds and order included. A match is a row like
# the card's: its name opens it as the row's does, its hover card is the
# row's, with Wake on a parked one, and a finished one's opens its note and
# changes nothing. `/` puts the cursor in the box from anywhere but a field
# or the Guide. The query is kept in the window's sessionStorage, so the
# rebuild after a Park or Wake from a match keeps showing what was found.
#
# GarrickFind.alike is the same index put to the test scaffold.py applies to
# a sibling's name (garrick_lib.sounds_alike, ported here word for word): the
# New project and New thread dialogs name what is already there as a name is
# typed, and leave the choice to make another.
FIND_MAX = 60     # matches drawn at once; the line above them says how many more
FIND_BOX = ('<div class="tfind" role="search"><input type="search" id="tfind" placeholder="Find a project or thread" '
            'autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" aria-controls="tfound" '
            'aria-label="Find a project or thread by name, in every zone, live, parked or finished">'
            '<kbd aria-hidden="true" title="Press / to search">/</kbd></div>')
FIND_LIST = ('<div class="tfound" id="tfound" hidden><p class="hint tfound-n" id="tfound-n" role="status"></p>'
             '<div class="tfound-list" id="tfound-list" role="list" aria-label="Projects and threads found"></div></div>')

FIND_CSS = r"""
.mg-new{flex-wrap:wrap;align-items:center}
.tfind{position:relative;flex:1 1 200px;min-width:0;max-width:420px;margin-right:auto}
.tfind input{width:100%;box-sizing:border-box;font:inherit;font-size:13px;color:var(--ink);background:var(--raise);border:1px solid var(--line);border-radius:8px;padding:6px 30px 6px 10px;margin:0}
.tfind input::placeholder{color:var(--muted)}.tfind input:focus{outline:2px solid var(--accent);outline-offset:-1px}
.tfind kbd{position:absolute;right:8px;top:50%;transform:translateY(-50%);font:inherit;font-size:11px;line-height:16px;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 5px;pointer-events:none}
.tfind input:focus~kbd,.tfind input:not(:placeholder-shown)~kbd{display:none}
@media (hover:none){.tfind kbd{display:none}}
.tview.finding .zones,.tview.finding .tmodes,.tview.finding .legend,.tview.finding .efoot,.tview.finding .gsum{display:none!important}
.tfound-n{margin:0 0 6px}
.sres{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px;padding:6px 4px;border-top:1px solid var(--grid);border-radius:6px;font-size:13px;transition:background .1s}
.sres:hover,.sres.on{background:var(--wash)}.sres .t{min-width:0}
.sres .t a{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sres .t small{display:block;color:var(--muted);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sres .chip{margin:0}.sres[data-st="done"] .t a{color:var(--ink2)}
dialog.gmanage .mg-dup a{color:var(--accent)}
"""

FIND_JS = r"""
(function(){
var box=document.getElementById('tfind'),v=box&&box.closest('.tview'),wrap=document.getElementById('tfound'),list=document.getElementById('tfound-list'),
said=document.getElementById('tfound-n'),D={items:[],zones:{}},MAX=%(max)d,RANK={live:0,parked:1,done:2},KEY='garrick-find';
try{D=JSON.parse(document.getElementById('find-data').textContent)||D}catch(e){}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function rx(u,plain){try{return new RegExp(u,'u')}catch(e){return plain}}
var SPLIT=rx('[^\\p{L}\\p{N}]+',/[^a-z0-9\u00c0-\u024f]+/),LETTER=rx('\\p{L}',/[a-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f]/);
/* a name as the box reads it: lower case, accents gone, & as "and", an apostrophe joining its word */
function fold(s){s=String(s==null?'':s).replace(/&/g,' and ');if(s.normalize)s=s.normalize('NFD');return s.toLowerCase().replace(/[\u0300-\u036f]/g,'').replace(/['\u2018\u2019`]/g,'')}
function words(s){return fold(s).split(SPLIT).filter(Boolean)}
function cmp(a,b){a=fold(a);b=fold(b);return a<b?-1:a>b?1:0}
(D.items||[]).forEach(function(it){it._own=words([it.n,it.sp].join(' '));it._all=it._own.concat(words([it.k==='p'?'':it.p,it.psp,it.z].join(' ')))});
/* every query word the start of a word of the name, its spoken form, its project's or its zone's */
function has(ws,q){for(var i=0;i<ws.length;i++)if(ws[i].lastIndexOf(q,0)===0)return true;return false}
function every(qs,ws){return qs.every(function(q){return has(ws,q)})}
function key(z,p,t){return z+'\n'+p+'\n'+t}
function card(r){try{return JSON.parse(r.dataset.card)}catch(e){return null}}
/* the card's own rows, read afresh each time: Park and Wake move them (PARK_JS) */
function rows(){var m={};[].forEach.call(document.querySelectorAll('.tview .zones .thread[data-card]'),function(r){var c=card(r);if(!c)return;
var k=c.kl==='project'?key(c.z,c.n,''):key(c.z,c.p,c.n);(m[k]=m[k]||[]).push({el:r,c:c})});return m}
function rowsOf(m,it){return m[it.k==='p'?key(it.z,it.n,''):key(it.z,it.p,it.n)]}
function state(it,rs){if(!rs||it.s==='done')return it.s;
if(it.k==='p')return rs[0].c.hp||rs.every(function(x){return!!x.el.closest('details.parked')})?'parked':'live';
return rs[0].c.s?'parked':'live'}
function hits(test){var m=rows(),out=[];(D.items||[]).forEach(function(it){var own=test(it);if(own===null)return;var rs=rowsOf(m,it);
out.push({it:it,rs:rs,s:state(it,rs),own:own?0:1})});
out.sort(function(a,b){return RANK[a.s]-RANK[b.s]||a.own-b.own||cmp(a.it.n,b.it.n)||cmp(a.it.p||'',b.it.p||'')||cmp(a.it.z,b.it.z)});return out}
/* null for a query with no word in it: the card as it was */
function find(q){var qs=words(q);if(!qs.length)return null;return hits(function(it){return every(qs,it._all)?every(qs,it._own):null})}
function cardText(h){return h.rs?h.rs[0].el.dataset.card:JSON.stringify(h.it.c||{n:h.it.n,kl:h.it.k==='p'?'project':'thread',z:h.it.z,p:h.it.k==='p'?'':h.it.p})}
function line(h){var it=h.it,c=cardText(h),o=JSON.parse(c);
var where=(it.k==='p'?'Project · ':it.p&&it.p!==it.n?esc(it.p)+' · ':'')+(D.zones[it.z]||esc(it.z));
return'<div class="sres" role="listitem" data-st="'+h.s+'" data-card="'+esc(c)+'"><div class="t"><a href="'+esc(o.u||'')+'">'+esc(it.n)+'</a><small>'+where+'</small></div>'
+(h.s==='live'?'':'<span class="chip">'+h.s+'</span>')+'</div>'}
function R(){return window.ThreadRows||{bind:function(){},close:function(){}}}
function keep(q){try{if(q)sessionStorage.setItem(KEY,q);else sessionStorage.removeItem(KEY)}catch(e){}}
function render(){if(!box)return;var q=box.value,hs=find(q);R().close();keep(q);v.classList.toggle('finding',!!hs);wrap.hidden=!hs;
if(!hs){list.innerHTML='';said.textContent='';return}
list.innerHTML=hs.slice(0,MAX).map(line).join('');[].forEach.call(list.querySelectorAll('.sres'),function(r){R().bind(r)});
var n=hs.length,l=hs.filter(function(h){return h.s==='live'}).length;
said.textContent=n?n+(n===1?' match':' matches')+' in every zone'+(l<n?', '+l+' live':'')+(n>MAX?'; the first '+MAX+' are shown, so type more of the name':''):'Nothing by that name in any zone, live, parked or finished.'}
/* the test scaffold.py puts a sibling's name to (garrick_lib.sounds_alike): the same once case, accents and
   punctuation are gone, the same phonetic key, or, both four letters or more, one edit apart */
var DW=['zero','one','two','three','four','five','six','seven','eight','nine'],
START=[['kn','n'],['gn','n'],['pn','n'],['wr','r'],['ps','s'],['wh','w'],['x','s']],
DIGR=[['sch','sk'],['tch','ch'],['dg','j'],['ph','f'],['ck','k'],['qu','kw'],['gh',''],['sh','x'],['ch','x'],['th','0']];
function nname(s){s=String(s).replace(/&/g,' and ');if(s.normalize)s=s.normalize('NFKD');s=s.replace(/[0-9]/g,function(d){return' '+DW[+d]+' '}).toLowerCase();
var o='';for(var i=0;i<s.length;i++){var ch=s[i];if(s.charCodeAt(i)<0x250&&LETTER.test(ch))o+=ch}return o}
function wkey(word){var w=nname(word),i;if(!w)return'';for(i=0;i<START.length;i++)if(w.lastIndexOf(START[i][0],0)===0){w=START[i][1]+w.slice(START[i][0].length);break}
w=w.split('x').join('ks');DIGR.forEach(function(d){w=w.split(d[0]).join(d[1])});
var o='';for(i=0;i<w.length;i++){var ch=w[i],nx=w.charAt(i+1);if(ch==='c')ch='eiy'.indexOf(nx)>=0?'s':'k';else if(ch==='q')ch='k';else if(ch==='z')ch='s';o+=ch}
if(!o)return'';var k=['aeiouy'.indexOf(o[0])>=0?'A':o[0]];for(i=1;i<o.length;i++){ch=o[i];if('aeiouyhw'.indexOf(ch)<0&&ch!==k[k.length-1])k.push(ch)}return k.join('')}
function pkey(s){return String(s).replace(/&/g,' and ').split(/[\s\-\u2010\u2011]+/).map(wkey).filter(Boolean).join(' ')}
function dist(a,b){if(a===b)return 0;if(a.length<b.length){var t=a;a=b;b=t}var prev=[],i,j;for(j=0;j<=b.length;j++)prev.push(j);
for(i=1;i<=a.length;i++){var cur=[i];for(j=1;j<=b.length;j++)cur.push(Math.min(prev[j]+1,cur[j-1]+1,prev[j-1]+(a[i-1]===b[j-1]?0:1)));prev=cur}return prev[b.length]}
function alike(a,b){var na=nname(a),nb=nname(b);if(!na||!nb)return false;if(na===nb)return true;var ka=pkey(a),kb=pkey(b);
if(ka&&(ka===kb||ka.split(' ').join('')===kb.split(' ').join('')))return true;return Math.min(na.length,nb.length)>=4&&dist(na,nb)<=1}
function plain(h){var c=JSON.parse(cardText(h));return{n:h.it.n,k:h.it.k,p:h.it.k==='p'?'':h.it.p,z:h.it.z,s:h.s,u:c.u||''}}
window.GarrickFind={find:function(q){var hs=find(q);return hs?hs.map(plain):[]},
alike:function(name){if(!nname(name))return[];return hits(function(it){return[it.n].concat(it.sp?[it.sp]:[]).some(function(f){return alike(name,f)})?true:null}).map(plain)},
soundsAlike:alike};
if(!box||!v||!wrap)return;
box.addEventListener('input',render);
box.addEventListener('search',render);
/* Esc empties the box and puts the card back; with nothing in it, leaves the box. Down and Enter reach the first match. */
box.addEventListener('keydown',function(e){if(e.key==='Escape'){if(box.value){e.preventDefault();e.stopPropagation();box.value='';render()}else box.blur();return}
if(e.key!=='ArrowDown'&&e.key!=='Enter')return;var a=list.querySelector('.sres .t>a');if(!a)return;e.preventDefault();if(e.key==='Enter')a.click();else a.focus()});
list.addEventListener('keydown',function(e){var a=e.target.closest&&e.target.closest('.sres .t>a');if(!a)return;
var all=[].slice.call(list.querySelectorAll('.sres .t>a')),i=all.indexOf(a);
if(e.key==='ArrowDown'&&i<all.length-1){e.preventDefault();all[i+1].focus()}else if(e.key==='ArrowUp'){e.preventDefault();(i>0?all[i-1]:box).focus()}
else if(e.key==='Escape')box.focus()});
/* "/" from anywhere but a field, a dialog or the Guide, whose pages have their own search */
document.addEventListener('keydown',function(e){if(e.key!=='/'||e.metaKey||e.ctrlKey||e.altKey||e.defaultPrevented)return;var t=e.target||{};
if(t.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName||'')||(t.closest&&t.closest('dialog')))return;
if(document.body.dataset.tab==='guide')return;var c=box.closest('.card'),sec=box.closest('section.tab');if(!c||c.hidden||!sec)return;
e.preventDefault();if(sec.hidden&&window.StatusTab)StatusTab(sec.id.slice(4));if(!c.open)c.open=true;box.focus();if(box.select)box.select()});
/* drawn again once Park or Wake has moved a row, so a match says what it now is */
var prev=window.GarrickActed;window.GarrickActed=function(q,out){var r=prev?prev(q,out):undefined;if(box.value)render();return r};
var q0=null;try{q0=sessionStorage.getItem(KEY)}catch(e){}if(q0){box.value=q0;render()}
})();
""" % {"max": FIND_MAX}

# An action that runs (#77): a request that commits in a zone can take a minute
# or more, since each commit runs the zone's wall check. While it runs, a toast
# of its own stays up with a spinner and the time so far, says why after
# ACTION_WHY seconds, and holds every button that acts on that zone; other
# zones stay usable. A result that took longer than the toast's ACTION_TOAST
# shows as a card: one that saved fades ACTION_TOAST after it came, unless the
# pointer is on it, and a failure stays until dismissed; a quick one goes to
# the host's toast as before (#107). What
# runs, and what waits to be seen, is kept in this window's sessionStorage, so
# the rebuild after a request, or one asked for meanwhile, does not lose it. A
# request with no reply after ACTION_LOST seconds, past the Obsidian plugin's
# fifteen minutes, is taken as lost. ZONE_VERBS are the requests page_action.py
# runs under the zone's lock.
#
# The page's memory is a cache. page_action.py keeps a durable record of park,
# wake and the Todo verbs (System/tools/operations.py, in the jobs folder), and
# the page asks for the open set, as {"verb": "operations"}, on load and every
# ACTION_POLL seconds while one of its entries is still running. The record
# wins: a reload, or an app that was quit, finds the action again with its
# phase, a result that landed while the page was away is shown and dismissable,
# an entry the record does not know after ACTION_UNKNOWN seconds is given up as
# lost, and what the user reads comes from the record's own sentence, never
# from the page: only the outcome "saved" is a success. A workspace without the
# module is told so once. ACTION_LOST stays the last resort for a reply that
# never comes. A request the record finds done already, past a double click's
# window, comes back as a question rather than a second edit (`again`, #137):
# it stays on screen, however quick, with a Do it again button that sends the
# same request once more with `confirm` naming the action it was asked about.
#
# It asks only a host that has said it can answer a request that reads: the
# host sets window.GarrickReads as the page loads, and calls window.GarrickReady
# once it has, when that is after this script ran. An older app or plugin, which
# toasts and rebuilds the page for every request it passes on, says nothing, is
# asked nothing, and behaves exactly as it did in 0.26.0, with ACTION_LOST as
# the fallback. The record is still written, and is there to be read as soon as
# the host is updated.
# Ticks and unticks are the exception (#107). A Todo line's box stays
# clickable while its zone is busy: the click strikes the row through at once
# and is queued, and the queue goes to page_action.py as one request, with
# "keys", once the zone is free and ACTION_BATCH seconds have passed since the
# last tick in it, so five quick ticks are one commit and one wall check. A
# second click on a line still queued takes it back. A batch shows no toast of
# its own unless it takes longer than ACTION_TOAST; one that saved says "Saved
# 3" in the small toast, which fades, and one refused stays as a card naming
# its lines, with their boxes put back. The queue is kept in sessionStorage
# with the rest, so a rebuild draws a queued tick as clicked.
# A refused ACTION_KEEP stays as a card too, however quickly it came back
# (#177): each is a deliberate, one-off action, its dialog or the Undo bar has
# closed, and a four-second toast with a long reason is gone before it is read.
ACTION_TOAST = 4
ACTION_BATCH = 2
ACTION_WHY = 10
ACTION_LOST = 960
ACTION_POLL = 3
ACTION_UNKNOWN = 60
ACTION_KEEP = ("rename", "delete", "new-project", "new-thread", "undo")
ZONE_VERBS = ("todo-done", "todo-undo", "todo-date", "todo-add", "park", "wake", "new-project", "new-thread", "rename",
              "delete", "undo", "interrupt", "answer", "later", "continue", "fix", "suggestion", "start", "stop-using",
              "bring-back")

WORK_CSS = r"""
#work{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:10;display:flex;flex-direction:column;gap:6px;width:max-content;max-width:90vw}
#work[hidden]{display:none}#work .wk{display:flex;gap:10px;align-items:flex-start;background:var(--ink);color:var(--surface);font-size:13px;padding:9px 14px;border-radius:10px}
#work .wbody{display:flex;flex-direction:column;gap:2px;min-width:0}#work small,#work .wt{color:color-mix(in srgb,var(--surface) 72%,transparent);font-size:12px}
#work .wt{font-weight:inherit;font-variant-numeric:tabular-nums;margin-left:4px}#work .bad{box-shadow:inset 3px 0 0 var(--critical)}
#work .ask{box-shadow:inset 3px 0 0 var(--accent)}#work .wagain{align-self:flex-start;margin-top:4px;background:none;border:1px solid currentColor;border-radius:6px;color:inherit;font:inherit;font-size:12px;padding:2px 8px;cursor:pointer}
#work .wspin{flex:none;width:11px;height:11px;margin-top:3px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:wspin .8s linear infinite}
@keyframes wspin{to{transform:rotate(360deg)}}@media (prefers-reduced-motion:reduce){#work .wspin{animation:none;border-right-color:currentColor;opacity:.6}}
#work .wx{flex:none;background:none;border:0;color:inherit;font:inherit;font-size:16px;line-height:1;padding:0 2px;cursor:pointer;opacity:.7}#work .wx:hover{opacity:1}
"""

# Its own script, after MANAGE_JS, so it wraps every window.GarrickActed set
# before it. The page's buttons hand it a request through window.GarrickAct,
# which sends one that commits in a zone and shows it running, and answers
# false for any other, which the button sends as before; window.GarrickHeld
# says when a zone is still busy, and window.GarrickBusy what it is busy with.
# Without this script the buttons send as they did before it.
WORK_JS = r"""
(function(){var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;if(!host)return;
var TOAST=@TOAST@,WHY=@WHY@,LOST=@LOST@,ZONED=@ZONED@,KEY='garrick-work',box=document.getElementById('work'),W=[],timer=null,POLL=@POLL@,UNKNOWN=@UNKNOWN@,SEEN=[],OPS={},
BATCH=@BATCH@,Q=[],HOV=null,TICKS=['todo-done','todo-undo'],KEEP=@KEEP@;
try{W=JSON.parse(sessionStorage.getItem(KEY)||'[]')||[]}catch(e){}
try{SEEN=JSON.parse(sessionStorage.getItem(KEY+'-seen')||'[]')||[]}catch(e){}
try{OPS=JSON.parse(sessionStorage.getItem(KEY+'-ops')||'{}')||{}}catch(e){}
try{Q=JSON.parse(sessionStorage.getItem(KEY+'-ticks')||'[]')||[]}catch(e){}
function keep(){try{sessionStorage.setItem(KEY,JSON.stringify(W));sessionStorage.setItem(KEY+'-seen',JSON.stringify(SEEN.slice(-60)));sessionStorage.setItem(KEY+'-ops',JSON.stringify(OPS));
sessionStorage.setItem(KEY+'-ticks',JSON.stringify(Q))}catch(e){}}
/* the operation ids this window has already shown the end of, so the record never shows one twice */
function mark(){[].forEach.call(arguments,function(o){if(o&&SEEN.indexOf(o)<0)SEEN.push(o)})}
function mint(){var s='';for(var i=0;i<16;i++)s+='0123456789abcdef'.charAt(Math.floor(Math.random()*16));return s}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function zoned(q){return!!q&&ZONED.indexOf(q.verb)>=0&&typeof q.zone==='string'}
function running(z){return W.filter(function(e){return!e.out&&e.q.zone===z})[0]||null}
function took(ms){var s=Math.max(0,Math.round(ms/1000));return s<60?s+' s':Math.floor(s/60)+' min'+(s%60?' '+s%60+' s':'')}
function toast(s){var t=document.getElementById('toast');if(!t)return;t.textContent=s;t.style.opacity=1;clearTimeout(toast.t);toast.t=setTimeout(function(){t.style.opacity=0},TOAST*1000)}
/* every button that acts on a busy zone: a Todo line's date, its + Add, a card's Rename, Delete and New thread here, Park and Wake.
   Not a Todo line's box: a tick made while the zone is busy is queued below, never refused (#107) */
function str(s){return'"'+String(s).replace(/["\\]/g,'\\$&')+'"'}
function holds(z){var j=JSON.stringify(z),Z=str(z);return['.trow[data-z='+Z+'] button.tdate','.tadd-open[data-zone='+Z+']',
'button[data-mg^='+str('['+j+',')+']'].concat(['park','wake'].map(function(v){return'button[data-act*='+str('"verb":"'+v+'"')+'][data-act*='+str('"zone":'+j)+']'}))}
function hold(){var zs=[];W.forEach(function(e){if(!e.out&&zs.indexOf(e.q.zone)<0)zs.push(e.q.zone)});var sel=[].concat.apply([],zs.map(holds)).join(',');
var st=document.getElementById('work-hold');if(!st){st=document.createElement('style');st.id='work-hold';document.head.appendChild(st)}
st.textContent=sel?sel+'{opacity:.45;pointer-events:none;cursor:default}':'';
[].forEach.call(document.querySelectorAll('[data-work-held]'),function(b){b.disabled=false;b.removeAttribute('data-work-held')});
if(sel)[].forEach.call(document.querySelectorAll(sel),function(b){if(!b.disabled){b.disabled=true;b.setAttribute('data-work-held','')}})}
/* a Todo line's rows by zone and key, its box set to done or not, and its words as the box's label has them, for a card */
function rows(z,k){return[].filter.call(document.querySelectorAll('.trow'),function(r){return r.dataset.z===z&&r.dataset.k===k})}
function paint(z,k,d){rows(z,k).forEach(function(r){r.classList.toggle('done',d);var b=r.querySelector('.tick');
if(b)b.setAttribute('aria-label',(d?'Reopen':'Mark done')+String(b.getAttribute('aria-label')||'').replace(/^[^:]*/,''))})}
function words(z,k){var r=rows(z,k)[0],b=r&&r.querySelector('.tick'),s=b?String(b.getAttribute('aria-label')||'').replace(/^[^:]*:\s*/,''):'';
return s.length>60?s.slice(0,59)+'…':s}
/* a batch refused as a whole: its boxes back as they were, and a click on one of them meanwhile dropped, since the row is back too */
function back(e){var z=e.q.zone,d=e.q.verb!=='todo-done';(e.q.keys||[]).forEach(function(k){paint(z,k,d)});
Q=Q.filter(function(x){return!(x.q.zone===z&&(e.q.keys||[]).indexOf(x.q.key)>=0)})}
function shown(e,now){return!!e.out||!e.q.keys||!!e.shown||now-e.t0>=TOAST*1000}
function render(){var now=Date.now(),html='';if(box){html=W.map(function(e,i){if(!shown(e,now))return'';
if(e.out)return'<div class="wk '+(e.out.ok?'ok':e.out.again?'ask':'bad')+'" data-i="'+i+'"><div class="wbody"><small>'+esc(e.say.replace(/…$/,''))+', '+took(e.done-e.t0)+'</small><span>'+esc(e.out.say)
+'</span>'+(!e.out.ok&&e.lines&&e.lines.length?'<small>'+esc(e.lines.filter(String).join(' · '))+'</small>':'')
+(e.out.again?'<button type="button" class="wagain" data-again="'+i+'">Do it again</button>':'')+'</div><button type="button" class="wx" data-wx="'+i+'" aria-label="Dismiss" title="Dismiss">×</button></div>';
return'<div class="wk"><span class="wspin" aria-hidden="true"></span><div class="wbody"><span>'+esc(e.say)+'<span class="wt" data-t0="'+e.t0+'" aria-hidden="true">'+took(now-e.t0)+'</span></span>'
+((e.phase===undefined?now-e.t0>=WHY*1000&&['continue','start'].indexOf(e.q.verb)<0:e.phase==='checking')?'<small>Committing: the wall check can take a minute.</small>':'')+'</div></div>'}).join('');
box.innerHTML=html;box.hidden=!html;document.body.style.setProperty('--work-h',html?box.offsetHeight+8+'px':'0px')}hold()}
/* each second: the time so far, why after WHY, a request with no reply after LOST given up, a batch's own toast once it has taken TOAST,
   and a card that says saved gone TOAST after it came, unless the pointer is on it */
function sweep(){var now=Date.now(),changed=false;W.slice().forEach(function(e){
if(e.out){if(e.fade&&now>=e.fade&&HOV!==e){W.splice(W.indexOf(e),1);changed=true}return}
if(now-e.t0>LOST*1000){e.out={ok:false,say:'No reply after '+took(LOST*1000)+'. Look at git status in '+e.q.zone+' before trying again.'};e.done=now;changed=true}
else if(!e.why&&now-e.t0>=WHY*1000){e.why=1;changed=true}
if(e.q.keys&&!e.shown&&now-e.t0>=TOAST*1000){e.shown=1;changed=true}});if(changed)keep();return changed}
/* the ticks queued in a zone go as one request once the zone is free and BATCH seconds have passed since the last of them:
   the ones for the same verb and note as the oldest, the rest after it, with whatever was ticked meanwhile */
function flush(){var now=Date.now(),sent=false;
Q.map(function(x){return x.q.zone}).filter(function(z,i,a){return a.indexOf(z)===i}).forEach(function(z){var mine=Q.filter(function(x){return x.q.zone===z});
if(running(z)||mine.some(function(x){return now-x.t<BATCH*1000}))return;
var one=mine[0].q,go=mine.filter(function(x){return x.q.verb===one.verb&&x.q.file===one.file}),keys=go.map(function(x){return x.q.key}),n=keys.length;
Q=Q.filter(function(x){return go.indexOf(x)<0});var q={verb:one.verb,zone:z,file:one.file,keys:keys,op:mint()};host.postMessage({act:q});
W.push({q:q,op:q.op,say:(q.verb==='todo-done'?'Ticking ':'Reopening ')+(n===1?'it…':n+' lines…'),t0:now,lines:keys.map(function(k){return words(z,k)})});sent=true});
if(sent)keep();return sent}
function tick(){var sent=flush();if(sweep()||sent)render();else if(box)[].forEach.call(box.querySelectorAll('.wt'),function(t){t.textContent=took(Date.now()-t.dataset.t0)});poll();run()}
/* the record: ask for the open set on load, and every POLL seconds while an entry of ours is running; only Python reads the file.
   Never asked of a host that has not said it can answer a request that reads: an older one would toast and rebuild the page for each */
function poll(first){var now=Date.now();if(!window.GarrickReads||OPS.durable===false)return;
if(!first&&(now-(OPS.asked||0)<POLL*1000-200||!W.some(function(e){return!e.out})))return;
OPS.asked=now;keep();host.postMessage({act:{verb:'operations'}})}
/* a host whose flag is set after this script has run says so, and the first ask is made then */
window.GarrickReady=function(){poll(true)};
function heard(out){if(!out||!out.ok||out.durable===false){OPS.durable=false;if(!OPS.said){OPS.said=1;toast('Actions are not recoverable here: if this page reloads while one is running, look at git status in its zone.')}keep();run();return}
OPS.durable=true;OPS.verbs=out.verbs||[];OPS.lost=out.lost||'';reconcile(out.ops||[]);keep();render();run()}
function reconcile(ops){var now=Date.now(),by={};ops.forEach(function(r){by[r.op]=r});
ops.forEach(function(r){var e=W.filter(function(x){return x.op===r.op})[0],end=r.state==='completed'||r.state==='failed',keys=TICKS.indexOf(r.verb)>=0&&r.keys&&r.keys.length?r.keys:null;
if(!e){if(SEEN.indexOf(r.op)>=0||ZONED.indexOf(r.verb)<0)return;
e={q:{verb:r.verb,zone:r.zone,op:r.op},op:r.op,say:r.label||'Working…',t0:Math.round(r.at*1000)};W.push(e);
if(keys){e.q.keys=keys;e.lines=keys.map(function(k){return words(r.zone,k)});if(!end)keys.forEach(function(k){paint(r.zone,k,r.verb==='todo-done')})}}
/* a batch that saved while the page was away: the same small notice as one heard here, and no card */
if(end&&keys&&r.outcome==='saved'){if(!e.out){W.splice(W.indexOf(e),1);toast(r.say||'Saved')}mark(r.op);return}
if(end){if(!e.out){e.out={ok:r.outcome==='saved',say:r.say||''};e.done=Math.round((r.done||r.at)*1000);if(e.out.ok)e.fade=now+TOAST*1000;else if(e.q.keys)back(e)}mark(r.op)}
else if(!e.out)e.phase=r.phase||''});
W.forEach(function(e){if(e.out||!e.op||by[e.op]||(OPS.verbs||[]).indexOf(e.q.verb)<0||now-e.t0<=UNKNOWN*1000)return;
e.out={ok:false,say:(OPS.lost||'No record of this action was found. Look at git status in {zone} before trying again.').replace('{zone}',e.q.zone)};e.done=now;mark(e.op)})}
function run(){var on=W.some(function(e){return!e.out||e.fade})||Q.length>0;if(on&&!timer)timer=setInterval(tick,1000);if(!on&&timer){clearInterval(timer);timer=null}}
window.GarrickBusy=function(z){var e=running(z);return e?e.say:''};
window.GarrickHeld=function(q){var e=zoned(q)&&running(q.zone);if(e)toast(q.zone+' is still busy: '+e.say);return!!e};
window.GarrickAct=function(q,said,lines){if(!zoned(q))return false;if(GarrickHeld(q))return true;q=Object.assign({},q,{op:q.op||mint()});host.postMessage({act:q});
W.push({q:q,op:q.op,say:said||'Working…',t0:Date.now(),lines:lines||undefined});keep();render();run();return true};
/* a tick or an untick (#107): queued, never refused for a busy zone, and sent with the ones made within BATCH seconds of it.
   A second click on a line still queued takes the first back, and nothing is sent for it */
window.GarrickTick=function(q){if(!q||TICKS.indexOf(q.verb)<0||typeof q.zone!=='string'||typeof q.key!=='string')return false;
var was=Q.filter(function(x){return x.q.zone===q.zone&&x.q.file===q.file&&x.q.key===q.key})[0];
if(was){if(was.q.verb!==q.verb)Q.splice(Q.indexOf(was),1)}else Q.push({q:{verb:q.verb,zone:q.zone,file:q.file,key:q.key},t:Date.now()});
keep();run();return true};
/* the reply, from the host: a quick one is the host's toast, as before; a slow one stays here, and the toast steps aside.
   A batch of ticks that saved is one small notice however long it took; one refused stays, naming its lines, with their boxes back.
   A refused rename, deletion, new project, new thread or undo stays too, however quick (KEEP, #177) */
var prev=window.GarrickActed;window.GarrickActed=function(q,out){if(q&&q.verb==='operations'){heard(out);return}
var e=zoned(q)&&(W.filter(function(x){return!x.out&&q.op&&x.op===q.op})[0]||running(q.zone));
if(e&&e.q.verb===q.verb){var now=Date.now();
if(out&&out.state==='running'&&!out.outcome){   /* an identical request is already under way: this entry becomes that one, and nothing was saved */
W.splice(W.indexOf(e),1);if(out.op&&!W.some(function(x){return x.op===out.op})&&SEEN.indexOf(out.op)<0){var j={q:{verb:q.verb,zone:q.zone,op:out.op},op:out.op,say:out.say||'Working…',t0:now};
if(e.q.keys){j.q.keys=e.q.keys;j.lines=e.lines}W.push(j)}
keep();render();run();return}
/* a success is the record's outcome "saved"; with no record, the reply's ok, as before. A request the record holds already
   comes back asking whether it is meant again (`again`), and stays, however quick, with the button that confirms it */
mark(e.op,out&&out.op);var ok=out&&out.outcome?out.outcome==='saved':!!(out&&out.ok),again=out&&out.again||'';
if(e.q.keys&&ok&&!again){W.splice(W.indexOf(e),1);toast(out.say||'Saved')}
else if(now-e.t0>TOAST*1000||again||e.q.keys||!ok&&KEEP.indexOf(e.q.verb)>=0){e.out={ok:ok,say:out&&out.say||'That did not work.',again:again};e.done=now;
if(ok&&!again)e.fade=now+TOAST*1000;else if(e.q.keys&&!again)back(e);var t=document.getElementById('toast');if(t)t.style.opacity=0}else W.splice(W.indexOf(e),1);keep();render();run()}
if(prev)return prev(q,out)};
/* Do it again: the same request, once more, with `confirm` naming the action it was asked about (operations.py) */
if(box)box.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('[data-again]');
if(a&&a.dataset.again!==undefined){var w=W[+a.dataset.again];if(w&&w.out&&w.out.again){W.splice(W.indexOf(w),1);keep();render();
GarrickAct(Object.assign({},w.q,{op:'',confirm:w.out.again}),w.say,w.lines)}return}
var x=e.target.closest&&e.target.closest('[data-wx]');if(!x)return;W.splice(+x.dataset.wx,1);keep();render()});
/* the pointer on a card that says saved holds it; off it, the card has TOAST seconds more */
if(box){box.addEventListener('mouseover',function(e){var c=e.target.closest&&e.target.closest('[data-i]');HOV=c?W[+c.dataset.i]||null:null});
box.addEventListener('mouseout',function(e){var to=e.relatedTarget,c=to&&to.closest&&to.closest('[data-i]');if(c&&HOV&&W[+c.dataset.i]===HOV)return;
if(HOV&&HOV.fade)HOV.fade=Date.now()+TOAST*1000;HOV=null})}
/* a rebuilt page draws each line as the note has it: a tick still queued, or on its way, is drawn as clicked */
Q.forEach(function(x){paint(x.q.zone,x.q.key,x.q.verb==='todo-done')});
W.forEach(function(e){if(!e.out&&e.q.keys)e.q.keys.forEach(function(k){paint(e.q.zone,k,e.q.verb==='todo-done')})});
sweep();render();run();poll(true)})();
""".replace("@TOAST@", str(ACTION_TOAST)).replace("@WHY@", str(ACTION_WHY)).replace("@LOST@", str(ACTION_LOST)) \
    .replace("@POLL@", str(ACTION_POLL)).replace("@UNKNOWN@", str(ACTION_UNKNOWN)).replace("@BATCH@", str(ACTION_BATCH)) \
    .replace("@ZONED@", json.dumps(list(ZONE_VERBS), separators=(",", ":"))) \
    .replace("@KEEP@", json.dumps(list(ACTION_KEEP), separators=(",", ":")))


TADD_JS = r"""
(function(){var dlg=document.getElementById('tadd');if(!dlg)return;
var dtext=document.getElementById('tadd-text'),ddate=document.getElementById('tadd-date'),dfil=document.getElementById('tadd-filter'),dwhere=document.getElementById('tadd-where'),dz='';
function at(n){var d=new Date();d.setHours(12,0,0,0);d.setDate(d.getDate()+n);return d}
function iso(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
function lab(d){return d.toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short'})}
function tree(){return dlg.querySelector('.ttree[data-zone="'+dz+'"]')}
/* where the line will land, as todo_lines.add files it */
function where(){var v=ddate.value,w=/(^|\s)#waiting/.test(dtext.value),s='Inbox';
if(v){var n=Math.round((new Date(v+'T12:00:00')-at(0))/864e5);s=w?'Waiting on':n<=7?'This week':'Soon'}
dwhere.textContent='Goes to '+s+(v?', '+(w?'chase ':'due ')+lab(new Date(v+'T12:00:00')):'')+'.';
dlg.querySelectorAll('[data-q]').forEach(function(b){b.classList.toggle('on',b.dataset.q===''?!v:iso(at(+b.dataset.q))===v)})}
function tfilt(){var q=dfil.value.trim().toLowerCase(),t=tree();if(!t)return;t.querySelectorAll('.tsep').forEach(function(x){x.hidden=!!q});
t.querySelectorAll('.tproj').forEach(function(p){var subs=p.querySelectorAll('.tsub'),any=false;
subs.forEach(function(x){var m=!q||x.dataset.n.indexOf(q)>=0;x.hidden=!m;any=any||m&&!!q});
var me=!q||p.dataset.n.indexOf(q)>=0;p.hidden=!(me||any);var box=p.querySelector('.tsubs'),c=p.querySelector('.tchev');
if(box&&q){box.hidden=!any&&!me;if(me&&!any)subs.forEach(function(x){x.hidden=false})}else if(box){box.hidden=c.getAttribute('aria-expanded')!=='true';subs.forEach(function(x){x.hidden=false})}})}
window.TaddOpen=function(z){dz=z;document.getElementById('tadd-zone').textContent=z;dlg.querySelectorAll('.ttree').forEach(function(t){t.hidden=t.dataset.zone!==z});
dtext.value='';ddate.value='';dfil.value='';var none=tree()&&tree().querySelector('input[value="-"]');if(none)none.checked=true;tfilt();where();dlg.showModal();dtext.focus()};
dlg.addEventListener('click',function(e){var c=e.target.closest('.tchev');if(c){var box=c.parentNode.querySelector('.tsubs'),o=box.hidden;box.hidden=!o;c.setAttribute('aria-expanded',o?'true':'false');return}
var q=e.target.closest('[data-q]');if(q){ddate.value=q.dataset.q===''?'':iso(at(+q.dataset.q));where();return}
if(e.target===dlg){var r=dlg.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dlg.close()}});
ddate.addEventListener('input',where);dtext.addEventListener('input',where);dfil.addEventListener('input',tfilt);
document.getElementById('tadd-cancel').addEventListener('click',function(){dlg.close()});
/* sent inside the click that asked for it, as every page action is */
function add(){var t=dtext.value.replace(/\s+/g,' ').trim();if(!t){dtext.classList.remove('shake');void dtext.offsetWidth;dtext.classList.add('shake');dtext.focus();return}
var busy=window.GarrickBusy&&GarrickBusy(dz);if(busy){dwhere.textContent=dz+' is still busy: '+busy+' Add it when that is done.';return}
var pick=tree()&&tree().querySelector('input:checked');if(window.TaddSend)window.TaddSend(dz,pick?pick.value:'-',ddate.value||'-',t);dlg.close()}
document.getElementById('tadd-ok').addEventListener('click',add);
dtext.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();add()}})})();
"""


# The Todo tab: one zone at a time, a filter, a sort,
# and in the app, the tick, the date menu and the pending
# row of a line being added. Shared with any page that carries the tab.
TODO_CSS = r"""
.todotab .tbar{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;margin-bottom:14px}
.todotab .tbar .seg button{flex:none;padding:5px 12px;font-size:12.5px;display:inline-flex;gap:6px;align-items:center;line-height:1.2}
.todotab .tbar .seg .n{font-size:11px;color:var(--muted)}.todotab .tbar .hint{flex:1;min-width:220px}
.tsum{display:flex;flex-wrap:wrap;align-items:center;gap:6px;color:var(--ink2);font-size:12.5px;margin:0 2px 12px}
.tsum b{color:var(--ink);font-variant-numeric:tabular-nums}.tsum .bad,.tsum .bad b{color:var(--critical)}
.tsum-acts{margin-left:auto;display:flex;gap:6px}.tsum .tadd-open{font-size:12px;padding:6px 12px}
.tgroup{background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);margin-bottom:12px}
.tgroup>summary{display:flex;align-items:center;gap:8px;padding:11px 16px;font-weight:640;font-size:14px}
.tgroup>summary .n{color:var(--muted);font-weight:500;font-size:12px;font-variant-numeric:tabular-nums}
.tgroup>summary .hint{margin-left:auto;font-weight:400}
.trows{padding:0 8px 6px}
.trow{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:10px;align-items:start;padding:8px;border-top:1px solid var(--grid);border-radius:8px}
.ro .trow,.nohost .trow{grid-template-columns:minmax(0,1fr) auto}.nohost .trow .tick{display:none}
.trow:first-child{border-top:0}.trow:hover{background:var(--wash)}
.trow.pending{opacity:.6;pointer-events:none}.trow.pending .tmeta span{font-style:italic}
.trow.done .tick{background:var(--good);border-color:var(--good)}
.trow.done .tick::after{content:"";width:9px;height:5px;border-left:2px solid #fff;border-bottom:2px solid #fff;transform:translateY(-1px) rotate(-45deg)}
.trow.done .ttext{text-decoration:line-through;color:var(--muted)}.trow.done .thr{color:var(--muted)}
.ttext{font-size:13.5px;line-height:1.45;overflow-wrap:anywhere}
.ttext code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--wash);padding:0 3px;border-radius:4px}
.thr{display:inline-block;font-size:12px;font-weight:620;color:var(--accent);margin-right:7px;white-space:nowrap}.thr.unsure{color:var(--muted);font-weight:500}
.tmeta{display:flex;flex-wrap:wrap;gap:3px 12px;margin-top:3px;font-size:11.5px;color:var(--muted)}
.tmeta .prio{color:var(--critical)}.tmeta .moved{color:var(--accent);font-weight:560}
.tdate{border:1px solid var(--line);background:var(--raise);border-radius:7px;font:inherit;font-size:12px;padding:3px 9px;color:var(--ink2);white-space:nowrap;font-variant-numeric:tabular-nums}
button.tdate{cursor:pointer}button.tdate:hover{border-color:var(--base);color:var(--ink)}
.tdate.none{color:var(--muted);border-style:dashed;background:none}.tdate:empty{visibility:hidden}
.ro .tdate.none:not(:empty){border-style:solid}.nohost button.tdate{pointer-events:none}.nohost button.tdate.none{visibility:hidden}
.tdate.overdue{color:var(--critical);border-color:color-mix(in srgb,var(--critical) 45%,transparent)}
.tdate.today{color:var(--accent);border-color:color-mix(in srgb,var(--accent) 45%,transparent)}
.trow.done .tdate{visibility:hidden}
.tempty{color:var(--muted);font-size:12.5px;margin:2px 8px 10px}
.todotab[data-tf="late"] .trow:not(.late),.todotab[data-tf="nodate"] .trow:not(.undated){display:none}
.todotab[data-tf="late"] .tempty,.todotab[data-tf="nodate"] .tempty,.tgroup.empty{display:none}
.dmenu{position:fixed;z-index:11;background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:0 6px 24px rgba(0,0,0,.16);padding:6px;width:236px}
.dmenu .dh{font-size:11px;color:var(--muted);padding:4px 8px 2px;text-transform:uppercase;letter-spacing:.05em}
.dmenu button{display:flex;justify-content:space-between;align-items:baseline;width:100%;border:0;background:none;font:inherit;font-size:13px;color:var(--ink2);padding:6px 8px;border-radius:6px;cursor:pointer;text-align:left}
.dmenu button:hover,.dmenu button:focus-visible{background:var(--wash);color:var(--ink);outline:none}
.dmenu button small{color:var(--muted);font-size:11.5px;font-variant-numeric:tabular-nums}
.dmenu .pick{display:flex;gap:6px;padding:7px 4px 3px;border-top:1px solid var(--grid);margin-top:4px}
.dmenu input{flex:1;min-width:0;font:inherit;font-size:12.5px;padding:3px 6px;border:1px solid var(--line);border-radius:6px;background:var(--raise);color:var(--ink)}
.dmenu .pick button{width:auto;flex:none;border:1px solid var(--line);background:var(--raise);font-size:12px;font-weight:560;padding:3px 10px}
.dmenu .clear{color:var(--critical)}
@media (max-width:820px){.trow{grid-template-columns:22px minmax(0,1fr)}.trow .tdate{grid-column:2;justify-self:start}}
"""

TODO_JS = r"""
(function(){
var todo=document.getElementById('todolist');if(!todo)return;
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
var st={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
var panes=[].slice.call(todo.querySelectorAll('.tz'));
function say(s){var t=document.getElementById('toast');if(!t)return;t.textContent=s;t.style.opacity=1;clearTimeout(say.t);say.t=setTimeout(function(){t.style.opacity=0},2600)}
/* the zone asked for last, else Work when there is one, as the graph does, else the first */
function has(z){return panes.some(function(p){return p.dataset.zone===z})}
function zone(z){if(!has(z))z=has('Work')?'Work':panes[0]&&panes[0].dataset.zone;
panes.forEach(function(p){p.hidden=p.dataset.zone!==z});todo.querySelectorAll('[data-tz]').forEach(function(b){b.classList.toggle('on',b.dataset.tz===z)});
st.set('garrick-todo-zone',z);empties()}
window.TodoZone=zone;
todo.querySelectorAll('[data-tz]').forEach(function(b){b.onclick=function(){zone(b.dataset.tz)}});
function filt(f){todo.dataset.tf=f;todo.querySelectorAll('[data-tf]').forEach(function(b){b.classList.toggle('on',b.dataset.tf===f)});st.set('garrick-todo-filter',f);empties()}
todo.querySelectorAll('[data-tf]').forEach(function(b){b.onclick=function(){filt(b.dataset.tf)}});
function empties(){var f=todo.dataset.tf||'all',want=f==='late'?'.trow.late':f==='nodate'?'.trow.undated':null;
todo.querySelectorAll('.tgroup').forEach(function(g){g.classList.toggle('empty',!!want&&!g.querySelector(want))})}
/* A-Z by thread, then the action; Due date puts dated lines first, soonest first, then the rest A-Z */
function sort(s){todo.dataset.ts=s;todo.querySelectorAll('[data-ts]').forEach(function(b){b.classList.toggle('on',b.dataset.ts===s)});st.set('garrick-todo-sort',s);
todo.querySelectorAll('.trows').forEach(function(box){var rows=[].slice.call(box.children).filter(function(r){return r.classList.contains('trow')});
rows.sort(function(a,b){if(s==='date'){var x=a.dataset.d||'',y=b.dataset.d||'';if(x!==y){if(!x)return 1;if(!y)return -1;return x<y?-1:1}}
return a.dataset.a<b.dataset.a?-1:a.dataset.a>b.dataset.a?1:0});rows.forEach(function(r){box.appendChild(r)})})}
todo.querySelectorAll('[data-ts]').forEach(function(b){b.onclick=function(){sort(b.dataset.ts)}});
sort(st.get('garrick-todo-sort')==='date'?'date':'alpha');zone(st.get('garrick-todo-zone'));
var f0=st.get('garrick-todo-filter');filt(f0==='late'||f0==='nodate'?f0:'all');
/* a zone's "Open the list" on the Overview opens the tab on that zone */
document.addEventListener('click',function(e){var g=e.target.closest&&e.target.closest('[data-tz-go]');if(g)zone(g.dataset.tzGo)},true);
/* what a button sends: Garrick's request, page_action.py's to carry out */
function send(verb,r,more,said){var q={verb:verb,zone:r.dataset.z,file:r.dataset.f,key:r.dataset.k};for(var k in more||{})q[k]=more[k];
if(window.GarrickAct&&GarrickAct(q,said))return;host.postMessage({act:q});say(said)}
/* a zone still busy with another request (WORK_JS) says so, and the row stays as it is */
function held(verb,r){return!!(window.GarrickHeld&&GarrickHeld({verb:verb,zone:r.dataset.z}))}
/* where a line is drawn: the Todo tab, and the list a thread's todo chip opens on the Threads card (#179), which ticks and dates the same way */
var places=[todo].concat([].slice.call(document.querySelectorAll('.tview')));
function twins(r){return[].filter.call(document.querySelectorAll('.trow'),function(x){return x===r||x.dataset.z===r.dataset.z&&x.dataset.f===r.dataset.f&&x.dataset.k===r.dataset.k})}
/* a tick is queued with the ticks around it (WORK_JS's GarrickTick, #107), even while the zone is busy; without it, sent at once as before.
   Every place the line is drawn is struck through with it */
function onTick(e){var b=e.target.closest('.tick');if(!b||!host)return;var r=b.closest('.trow');if(r.classList.contains('pending'))return;
var d=!r.classList.contains('done'),verb=d?'todo-done':'todo-undo';
if(!(window.GarrickTick&&GarrickTick({verb:verb,zone:r.dataset.z,file:r.dataset.f,key:r.dataset.k}))){if(held(verb,r))return;send(verb,r,null,d?'Ticking it…':'Reopening it…')}
twins(r).forEach(function(x){var t=x.querySelector('.tick');x.classList.toggle('done',d);if(t)t.setAttribute('aria-label',(d?'Reopen':'Mark done')+t.getAttribute('aria-label').replace(/^[^:]*/,''))})}
places.forEach(function(el){el.addEventListener('click',onTick)});
/* the date menu: the date is worked out at the click, so a page built yesterday still means today */
var menu=document.createElement('div');menu.className='dmenu';menu.hidden=true;menu.setAttribute('role','menu');document.body.appendChild(menu);var mrow=null;
function at(n){var d=new Date();d.setHours(12,0,0,0);d.setDate(d.getDate()+n);return d}
function next(w){var d=at(0),k=(w-d.getDay()+7)%7||7;return at(k)}
function iso(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
function lab(d){return d.toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short'})}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function open(r,b){mrow=r;var w=r.dataset.w==='1',o=[['Today',at(0)],['Tomorrow',at(1)],[at(0).getDay()===5?'Next Friday':'Friday',next(5)],['Next Monday',next(1)],
['In a week',at(7)],['In two weeks',at(14)]].filter(function(x,i,a){return a.findIndex(function(y){return iso(y[1])===iso(x[1])})===i});
menu.innerHTML='<div class="dh">'+(w?'Chase on':'Due')+'</div>'+o.map(function(x){return'<button type="button" role="menuitem" data-v="'+iso(x[1])+'"><span>'+x[0]+'</span><small>'+esc(lab(x[1]))+'</small></button>'}).join('')
+'<div class="pick"><input type="date" aria-label="Another date" value="'+esc(r.dataset.d||'')+'"><button type="button" class="set">Set</button></div>'
+(r.dataset.d?'<button type="button" class="clear" role="menuitem" data-v="-">Clear the date</button>':'');
menu.hidden=false;var q=b.getBoundingClientRect(),mw=menu.offsetWidth,mh=menu.offsetHeight,y=q.bottom+4;if(y+mh>window.innerHeight-8)y=q.top-mh-4;
menu.style.left=Math.max(8,Math.min(q.right-mw,window.innerWidth-mw-8))+'px';menu.style.top=Math.max(8,y)+'px';var f=menu.querySelector('button');if(f)f.focus()}
function shut(){menu.hidden=true;mrow=null}
places.forEach(function(el){el.addEventListener('click',function(e){var b=e.target.closest('button.tdate');if(!b||!host)return;e.stopPropagation();var r=b.closest('.trow');if(mrow===r&&!menu.hidden)shut();else if(!held('todo-date',r))open(r,b)})});
menu.addEventListener('click',function(e){var b=e.target.closest('button');if(!b||!mrow)return;var v=b.classList.contains('set')?menu.querySelector('input').value:b.dataset.v;if(!v)return;apply(mrow,v);shut()});
menu.addEventListener('keydown',function(e){if(e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();menu.querySelector('.set').click()}});
document.addEventListener('click',function(e){if(!menu.hidden&&!menu.contains(e.target))shut()});
document.addEventListener('keydown',function(e){if(e.key==='Escape')shut()});window.addEventListener('scroll',function(){if(!menu.hidden)shut()},{passive:true});
/* the row says the new date at once, and waits for the rebuild: the line's key changes with its date */
function apply(r,v){if(held('todo-date',r))return;send('todo-date',r,{date:v},'Dating it…');r.classList.add('pending');
var b=r.querySelector('.tdate'),w=r.dataset.w==='1';r.dataset.d=v==='-'?'':v;r.classList.remove('late','undated');b.className='tdate';
if(v==='-'){b.textContent=w?'＋ chase date':'＋ date';b.classList.add('none');r.classList.add('undated');return}
var d=new Date(v+'T12:00:00'),n=Math.round((d-at(0))/864e5);
b.textContent=(w?'Chase ':'Due ')+(n===0?'today':n===1?'tomorrow':lab(d));
if(n<0||(w&&n===0)){b.classList.add('overdue');r.classList.add('late')}else if(n===0)b.classList.add('today');
if(r.dataset.sec==='Inbox'&&r.dataset.f==='Todo.md'){var m=r.querySelector('.tmeta');if(!m){m=document.createElement('div');m.className='tmeta';r.querySelector('.tmain').appendChild(m)}
var s=m.querySelector('.moved');if(!s){s=document.createElement('span');s.className='moved';m.appendChild(s)}s.textContent='→ moves to '+(w?'Waiting on':n<=7?'This week':'Soon')}}
/* a line being added shows at once, greyed, in the section it is going to; the rebuild replaces it with the real row */
window.TodoPending=function(z,target,date,text){var pane=panes.filter(function(p){return p.dataset.zone===z})[0];if(!pane)return;
var w=/(^|\s)#waiting/.test(text),sec='Inbox',chip=w?'＋ chase date':'＋ date';
if(date!=='-'){var d=new Date(date+'T12:00:00'),n=Math.round((d-at(0))/864e5);sec=w?'Waiting on':n<=7?'This week':'Soon';chip=(w?'Chase ':'Due ')+(n===0?'today':n===1?'tomorrow':lab(d))}
function named(x){var t=x.querySelector('summary .tname');return t?t.textContent:''}
var groups=[].slice.call(pane.querySelectorAll('details.tgroup')),g=groups.filter(function(x){return named(x)===sec})[0];
var note=g?'adding…':'adding to '+sec+'…';if(!g)g=groups.filter(function(x){return named(x)==='Inbox'})[0];if(!g)return;
g.open=true;var rows=g.querySelector('.trows'),empty=rows.querySelector('.tempty');if(empty)empty.remove();
var name=target!=='-'?target.split('/').pop():'',r=document.createElement('div');r.className='trow pending';
r.innerHTML='<span class="tick" aria-hidden="true"></span><div class="tmain"><div class="ttext">'+(name?'<span class="thr">'+esc(name)+'</span>':'')+esc(text)
+'</div><div class="tmeta"><span>'+note+'</span></div></div><span class="tdate'+(date==='-'?' none':'')+'">'+esc(chip)+'</span>';
rows.insertBefore(r,rows.firstChild);var c=g.querySelector('summary .n');if(c)c.textContent=String((+c.textContent||0)+1);r.scrollIntoView({block:'nearest'})};
})();
"""

# After a button whose effect lands later than the rebuild that follows it
# (a session opened or closed through the desk, a thread parked or woken),
# the page keeps asking for a rebuild, every two seconds for up to thirty,
# until #state-data shows what was asked for. In a browser it reloads. The
# scroll position survives each reload. A park or wake the host has said was
# done keeps its request beside the expectation, so a reload of a page built
# before it lands moves the row again (window.GarrickRedo, read by JS).
RELOAD_JS = r"""
(function(){var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
function keep(){try{sessionStorage.setItem('garrick-scroll',String(window.scrollY))}catch(e){}}
window.addEventListener('pagehide',keep);window.addEventListener('beforeunload',keep);
try{var y=+sessionStorage.getItem('garrick-scroll');sessionStorage.removeItem('garrick-scroll');if(y)setTimeout(function(){window.scrollTo(0,y)},0)}catch(e){}
window.GarrickExpect=function(x){try{localStorage.setItem('garrick-expect',JSON.stringify({x:x,until:Date.now()+30000}))}catch(e){}};
var w=null;try{w=JSON.parse(localStorage.getItem('garrick-expect')||'null')}catch(e){}if(!w||typeof w.x!=='string')return;
var S={parked:[],live:[]};try{S=JSON.parse(document.getElementById('state-data').textContent)}catch(e){}
var i=w.x.indexOf(':'),want=w.x.slice(0,i),key=w.x.slice(i+1),now;
if(want==='parked'||want==='active')now=(S.parked||[]).indexOf(key)>=0?'parked':'active';
/* live: or none: with no folder (Start up, Shut down) asks about every folder */
else now=(S.live||[]).some(function(f){return f===key||f.indexOf(key+'/')===0})?'live':'none';
if(now===want||!(Date.now()<w.until)){try{localStorage.removeItem('garrick-expect')}catch(e){}return}
if(w.q)window.GarrickRedo=w.q;
setTimeout(function(){if(host)host.postMessage({rebuild:true});else location.reload()},2000)})();
"""


# The menu bar. Inside Garrick.app the page hands the app what
# its menu bar icon lists: the build's own rows (#menu-data, whose absence
# takes the icon away), with the zone the graph shows and the
# app a thread opens in, both kept in this window's storage. It sends them at
# load and after any change, so the menu follows the graph's drop-down and
# Settings. Settings › Menu bar is the app's, not the page's: the app puts
# its values in window.GarrickApp and keeps what is chosen here. It runs in a
# script element of its own, so nothing else on the page can stop it.
MENU_JS = r"""
(function(){var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;if(!host)return;
function g(k){try{return localStorage.getItem(k)}catch(e){return null}}
var el=document.getElementById('menu-data'),data=null;try{data=el?JSON.parse(el.textContent):null}catch(e){}
function sync(){var P=window.GarrickPrefs,on=P?P.launchers():{};     /* PANEL_JS's, in another script: the defaults if it failed */
host.postMessage({menu:data&&{data:data,place:g('garrick-graph-place')||'',def:P?P.def():'note',note:on.note!==false,
launchers:(document.body.dataset.launchers||'').split(',').filter(function(k){return k&&on[k]!==false})}})}
sync();document.addEventListener('change',function(){setTimeout(sync,0)},true);
})();
"""

# Settings › Menu bar's controls, for any page that carries menu_settings():
# shown only inside the app, which answers them. Shared with pages built
# elsewhere, which send the menu's rows their own way.
MENU_SETTINGS_JS = r"""
(function(){var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
var box=document.getElementById('menu-settings');if(!host||!box)return;box.hidden=false;
function say(s){var t=document.getElementById('toast');if(!t)return;t.textContent=s;t.style.opacity=1;clearTimeout(say.t);say.t=setTimeout(function(){t.style.opacity=0},4000)}
var show=document.getElementById('menu-show'),login=document.getElementById('menu-login'),key=document.getElementById('menu-hotkey'),style=document.getElementById('menu-style');
var ask=document.getElementById('menu-askkey'),NOTE={hotkey:'Opens the menu or the panel from any app',askhotkey:'Opens the Ask box from any app, with the preview ask on',
dictationkey:'Click, then press the shortcut your dictation tool starts on. Pause the tool first if it takes the keys'};
var dict=document.getElementById('menu-dictation'),dkey=document.getElementById('menu-dictkey'),FIELD={hotkey:'menu-hotkey',askhotkey:'menu-askkey',dictationkey:'menu-dictkey'};
/* what the box does once it opens, said under the choice */
var DICT={off:'Once the Ask box opens, start dictation in it too',macos:'Starts macOS Dictation in the box, with no permission needed',
key:'Pressed for your dictation tool once the box has the cursor. Needs the Accessibility permission. A tool that listens only while its key is held cannot be started this way'};
function note(which,s){var n=document.getElementById(FIELD[which]+'-note');if(n)n.textContent=s||NOTE[which]}
function fill(){var a=window.GarrickApp||{};show.checked=!!a.menubar;login.checked=!!a.login;login.disabled=a.login==null;
/* an app built before the panel says no style, and its row stays hidden; one built before the Ask hotkey, that row */
if(style){style.closest('.launcher-row').style.display='style' in a?'':'none';style.value=a.style||'icon';style.disabled=!a.menubar}
if(ask){ask.closest('.launcher-row').style.display='askhotkey' in a?'':'none';ask.value=a.askhotkey||''}
var said=a.said||{};note('hotkey',said.hotkey);note('askhotkey',said.askhotkey||(a.askdefault?NOTE.askhotkey+'. ⌘G until you set another':''));
/* an app built before #35 says no dictation, and both its rows stay hidden */
if(dict){var m=a.dictation||'off',dn=document.getElementById('menu-dictation-note');dict.closest('.launcher-row').style.display='dictation' in a?'':'none';
dict.value=m;if(dn)dn.textContent=said.dictation||DICT[m]||DICT.key;
if(dkey){dkey.closest('.launcher-row').style.display='dictation' in a&&m==='key'?'':'none';dkey.value=a.dictationkey||'';note('dictationkey',said.dictationkey)}}
if(a.login==null)document.getElementById('menu-login-note').textContent='Needs macOS 13 or later';key.value=a.hotkey||''}
window.GarrickAppSet=function(a){window.GarrickApp=a;fill()};fill();
/* the app's settings: kept by the app, so a change here does not rebuild the page */
function tell(e,o){e.stopPropagation();host.postMessage({app:o})}
show.addEventListener('change',function(e){tell(e,{menubar:show.checked})});
if(style)style.addEventListener('change',function(e){tell(e,{style:style.value})});
if(dict)dict.addEventListener('change',function(e){tell(e,{dictation:dict.value})});
login.addEventListener('change',function(e){tell(e,{login:login.checked})});
var MOD=[['ctrlKey','⌃','ctrl'],['altKey','⌥','alt'],['shiftKey','⇧','shift'],['metaKey','⌘','cmd']];
function name(e){var c=e.code;if(/^Key[A-Z]$/.test(c))return c.slice(3);if(/^Digit\d$/.test(c))return c.slice(5);if(/^F\d{1,2}$/.test(c))return c;
return{Space:'Space',Minus:'-',Equal:'=',BracketLeft:'[',BracketRight:']',Backslash:'\\',Semicolon:';',Quote:"'",Comma:',',Period:'.',Slash:'/',Backquote:'`'}[c]||null}
/* A field records the keys pressed in it. While it has the focus the app lets go of
   its own hot keys, so a key it holds, ⌘G say, reaches the field; the app takes them
   back when the field loses it. One key never serves both: said under the field.
   The dictation shortcut is pressed by the app, not held by it, so macOS's rule on
   ⌥ does not apply to it, and it may be neither of the hotkeys. */
function recorder(el,which,other){if(!el)return;var o=function(v){var q={};q[which]=v;host.postMessage({app:q})};
el.addEventListener('focus',function(){host.postMessage({app:{recording:true}})});
el.addEventListener('blur',function(){host.postMessage({app:{recording:false}})});
el.addEventListener('keydown',function(e){if(e.key==='Tab')return;e.preventDefault();e.stopPropagation();
if(e.key==='Escape'){el.blur();return}
if((e.key==='Backspace'||e.key==='Delete')&&!(e.metaKey||e.ctrlKey||e.altKey)){o(null);return}
var n=name(e);if(!n)return;
function no(s){note(which,s);say(s)}
if(!(e.metaKey||e.ctrlKey||e.altKey)&&!/^F\d/.test(n)){no('Use ⌘, ⌃ or ⌥ with the key.');return}
if(which!=='dictationkey'&&e.altKey&&!e.metaKey&&!e.ctrlKey){no('Since macOS 15, a shortcut with only ⌥ or ⌥⇧ never reaches an app: add ⌘ or ⌃.');return}
var mods=MOD.filter(function(m){return e[m[0]]}),label=mods.map(function(m){return m[1]}).join('')+n;
if(which==='dictationkey'){if((key&&key.value===label)||(ask&&ask.value===label)){no(label+" is already a hotkey of Garrick's. Pick your dictation tool's key.");return}}
else{var a=window.GarrickApp||{},taken=other&&other.value===label&&!(which==='hotkey'&&a.askdefault);
if(taken){no(label+' is already the '+(which==='hotkey'?'Ask':"menu's")+' hotkey. Clear it there, or pick another.');return}}
o({code:e.code,mods:mods.map(function(m){return m[2]}),label:label})})}
recorder(key,'hotkey',ask);recorder(ask,'askhotkey',key);recorder(dkey,'dictationkey',null);
document.getElementById('menu-hotkey-clear').onclick=function(){host.postMessage({app:{hotkey:null}})};
var ac=document.getElementById('menu-askkey-clear');if(ac)ac.onclick=function(){host.postMessage({app:{askhotkey:null}})};
var dc=document.getElementById('menu-dictkey-clear');if(dc)dc.onclick=function(){host.postMessage({app:{dictationkey:null}})};
})();
"""


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
    """check.py's findings, run as the page is built. With `--quick`, where the
    workspace's check.py has it: every check but the comparison of wording
    with the meetings, which on a large workspace is most of a full run's
    time, and which the commit hook and a scheduled full check still make."""
    tool = ws / "System" / "tools" / "check.py"
    if not tool.is_file():
        return None
    try:
        quick = ["--quick"] if "--quick" in tool.read_text(encoding="utf-8") else []
    except OSError:
        quick = []
    try:
        proc = subprocess.run([sys.executable, str(tool), "--root", str(ws), "--json"] + quick,
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
    at Wikis/ for both. A wiki with a repository of its own is listed too.
    When git fails or runs out of time, the repository is `unread`, never
    clean: an empty answer is not a count of nothing."""
    places = [("Workspace", ws)] + [(z.name, z) for z in visible_dirs(ws / "Zones")] + \
             [("Wikis", ws / "Wikis")] + [(w.name, w) for w in visible_dirs(ws / "Wikis")]
    out = []
    for name, folder in places:
        if not (folder / ".git").exists():
            continue
        def git(*args):
            try:
                proc = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                return None
            return proc.stdout if proc.returncode == 0 else None
        porcelain = git("status", "--porcelain", "-z", "--untracked-files=all")
        changes = changed_files(porcelain or "")
        ct = (git("log", "-1", "--format=%ct") or "").strip()
        out.append({"name": name, "folder": folder, "dirty": len(changes), "changes": changes,
                    "unread": porcelain is None, "since": oldest_change(folder, changes),
                    "last": dt.datetime.fromtimestamp(int(ct)) if ct.isdigit() else None})
    return out


def oldest_change(folder: Path, changes) -> Optional[dt.datetime]:
    """When the longest-waiting uncommitted change was made: the oldest
    modification time among the changed files still on disk. A deleted file
    has none and is passed over."""
    times = []
    for path, _ in changes:
        try:
            times.append((folder / path).stat().st_mtime)
        except OSError:
            continue
    return dt.datetime.fromtimestamp(min(times)) if times else None


STALE_CHANGES = dt.timedelta(hours=24)   # uncommitted for longer than this is raised


# How `git status --porcelain` marks a file, as the Repositories card says it.
# A file staged and then edited again is both staged and not staged.
UNMERGED = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
CHANGE_KINDS = (("conflicted", "conflicted"), ("staged", "staged"), ("unstaged", "not staged"), ("untracked", "untracked"))


def changed_files(porcelain: str) -> List[Tuple[str, Tuple[str, ...]]]:
    """(path, kinds) for every file `git status --porcelain -z` lists: one entry
    per file, a rename under its new name. A count of these is a count of
    files, never of commits."""
    out, items = [], porcelain.split("\0")
    i = 0
    while i < len(items):
        item = items[i]
        i += 1
        if len(item) < 4:
            continue
        xy, path = item[:2], item[3:]
        if "R" in xy or "C" in xy:
            i += 1                              # the name it had before
        if xy == "??":
            kinds = ("untracked",)
        elif xy in UNMERGED:
            kinds = ("conflicted",)
        else:
            kinds = tuple(k for k, mark in (("staged", xy[0]), ("unstaged", xy[1])) if mark not in " ?!")
        if kinds:
            out.append((path, kinds))
    return out


def say_files(n: int) -> str:
    return "1 changed file" if n == 1 else "%d changed files" % n


def say_kinds(changes) -> str:
    """"2 staged, 5 not staged, 5 untracked": what a repository's changed files are."""
    counts = [(sum(1 for _, ks in changes if k in ks), label) for k, label in CHANGE_KINDS]
    return ", ".join("%d %s" % (n, label) for n, label in counts if n)


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
         ("person", "person", "#13a38a"), ("source", "source", "#7c9a2d"), ("concept", "concept", "#8c6d1f"),
         ("entity", "entity", "#4b6584")]

# Each place's kinds come from Garrick's own model of it, and nothing else: a
# page whose type and folder the model does not know is drawn as other notes.
# The core view of a place is its hubs: a zone's projects and threads, the
# people in Meetings, the concepts and entities in Knowledge.
CORE_LABEL = {"Meetings": "People", "Knowledge": "Concepts and entities"}
WIKI_LABEL = 40          # characters of a wiki page's title drawn on the graph; the card has it whole


def wiki_kind(wiki: str, kind: str, parts: tuple, source_type: str = "source") -> str:
    if wiki == "Meetings":
        return kind if kind in ("meeting", "mail", "person") else "note"
    if kind in (source_type, "source") and (not parts or parts[0] == "sources"):
        return "source"
    if kind == "concept" or (parts and parts[0] == "concepts" and kind in ("", "concept")):
        return "concept"
    if kind == "entity" or (parts and parts[0] == "entities" and kind in ("", "entity")):
        return "entity"
    return "note"


def short_label(title: str, limit: int = WIKI_LABEL) -> str:
    """A title cut at a word to about `limit` characters, with an ellipsis."""
    if len(title) <= limit:
        return title
    cut = title[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-–—")
    return (cut or title[:limit]) + "…"


OTHER = next(c for k, _, c in KINDS if k == "note")    # a note no colour group of its vault takes: "other notes"


def vault_of(ws: Path, folder: Path) -> Optional[Path]:
    """The Obsidian vault a folder's notes belong to: the nearest folder at or
    above it, up to the workspace root, that holds a .obsidian folder."""
    return todo_lines().vault_of(ws, folder)


def obsidian_graph(vault: Optional[Path]) -> Tuple[List[Tuple[List[str], str, str]], List[object]]:
    """A vault's own graph settings: the colour groups of .obsidian/graph.json
    as (terms, colour, label), each an OR of terms, and the ignore filters of
    .obsidian/app.json (userIgnoreFilters), a path prefix or a /regex/ each.
    Whatever is missing or does not read is empty."""
    groups: List[Tuple[List[str], str, str]] = []
    ignore: List[object] = []
    if vault is None:
        return groups, ignore
    try:
        data = json.loads((vault / ".obsidian" / "graph.json").read_text(encoding="utf-8"))
        for cg in data.get("colorGroups") or []:
            terms = [t.strip() for t in re.split(r"\s+OR\s+", str(cg.get("query") or "")) if t.strip()]
            rgb = (cg.get("color") or {}).get("rgb")
            if terms and isinstance(rgb, int):
                groups.append((terms, "#%06x" % (rgb & 0xFFFFFF), group_label(terms, len(groups) + 1)))
    except (OSError, ValueError, AttributeError, TypeError):
        groups = []
    ignore = todo_lines().ignore_filters(vault)      # read as the Todo card reads them
    return groups, ignore


# A property term: [key], [key:value], with either side quoted, and the
# ["key","value"] form some vaults hold.
PROPERTY_TERM = re.compile(r"""\[\s*["']?([\w-]+)["']?\s*(?:[:,]\s*(.+?))?\s*\]""")


def group_word(term: str) -> str:
    """One term of a colour group as a person would say it: a folder's last
    name, a file's name, a property's value (or its key), a tag. Empty for a
    term Garrick does not read."""
    m = PROPERTY_TERM.fullmatch(term.strip())
    if m:
        word = (m.group(2) or m.group(1)).strip().strip("\"'")
    else:
        m = re.fullmatch(r"(file|path|tag):(.+)", term.strip())
        if not m:
            return ""
        kind, value = m.group(1), m.group(2).strip().strip("\"'")
        if kind == "path":
            value = [part for part in value.split("/") if part.strip()][-1:] or [""]
            value = value[0]
        elif kind == "file":
            value = value.rsplit("/", 1)[-1]
            value = value[:-3] if value.lower().endswith(".md") else value
        else:
            value = value.lstrip("#")
        word = value
    word = re.sub(r"[-_]+", " ", word).strip()
    return word[:1].upper() + word[1:]


def group_label(terms: List[str], n: int = 0) -> str:
    """A colour group as the legend says it: `[type:project] OR file:Brief`
    reads "Project, Brief", `path:"Notes/wiki/concepts/"` reads "Concepts".
    A word said twice, or as singular and plural, is said once; a group with
    no word Garrick reads is "Group n"."""
    said, seen = [], set()
    for t in terms:
        word = group_word(t)
        key = word.lower()
        key = key[:-1] if key.endswith("s") and len(key) > 3 else key
        if word and key not in seen:
            seen.add(key)
            said.append(word)
    return ", ".join(said) or "Group %d" % n


def group_match(term: str, fm: dict, rel: str) -> bool:
    """Whether a note answers one term of a colour group's query, in the forms
    Garrick reads: [key], [key:value], file:, path: and tag:. Any other term
    never matches: the page reads no note's text to test it."""
    m = PROPERTY_TERM.fullmatch(term.strip())
    if m:
        key, want = m.group(1), m.group(2)
        if key not in fm:
            return False
        have = fm[key] if isinstance(fm[key], list) else [fm[key]]
        return want is None or any(as_text(v).strip("\"' ").lower() == want.strip().strip("\"'").lower() for v in have)
    m = re.fullmatch(r"(file|path|tag):(.+)", term)
    if not m:
        return False
    kind, want = m.group(1), m.group(2).strip().strip("\"'").lower()
    if kind == "file":
        base = rel.rsplit("/", 1)[-1].lower()
        return want in (base, base[:-3] if base.endswith(".md") else base)
    if kind == "path":
        return want in rel.lower()
    want = want.lstrip("#")
    return any(t.lower() == want or t.lower().startswith(want + "/") for t in tags(fm.get("tags")))


def ignored(rel: str, filters: List[object]) -> bool:
    return todo_lines().ignored(rel, filters)


def graph(ws: Path, T: Dict[str, dict], link: "Links", now: dt.datetime, cmux: bool = False, actions: bool = False,
          desk: Optional[Dict[str, str]] = None, drive: bool = False, urgent: Optional[set] = None) -> dict:
    """Every note in the zones and the wikis, and the [[links]] between them.
    From a note it keeps its title, kind, place, party tags and, for a thread,
    how long since it moved; from its body only the targets of its links.
    Instructions (AGENTS.md) are not notes, and each zone's Todo.md has the
    Open actions card, so neither is drawn. A parked thread, with the notes in
    its folder, and a project with no live thread left, with everything in it,
    are marked `s` and drawn only when the page is asked to show them.

    A place inside an Obsidian vault with colour groups of its own
    (.obsidian/graph.json) is coloured by them, `g` naming the group, and a
    note no group takes is grey; the vault's ignore filters (.obsidian/app.json)
    leave notes out, as Obsidian's graph does. Elsewhere each kind keeps its
    colour. Every note in a project carries the folder an app opens it in
    (`f`), its thread's or else its project's, where an app can open one. A
    thread whose own next action is overdue or due a chase, named by zone,
    project and thread in `urgent`, is marked `lt` and draws the one ring the
    graph has: age alone never marks a note."""
    places = [(z.name, z) for z in visible_dirs(ws / "Zones")]
    places += [(w.name, w / "wiki") for w in visible_dirs(ws / "Wikis") if (w / "wiki").is_dir()]
    names = short_names(T)
    held = {(r["zone"], r["project"], r["thread"]) for z in T.values() for r in z["parked"]}
    hubs_parked = {zone: set(data.get("held", ())) for zone, data in T.items()}
    awake = {(r["zone"], r["project"]) for z in T.values() for r in z["rows"]}
    asleep = {(zone, project) for zone, project, _ in held} - awake
    groups: List[list] = []                           # [colour, label], every vault's in turn
    vaults: Dict[Path, Tuple[int, list, list]] = {}   # vault -> (its first group's index, groups, filters)
    vault_at: Dict[Path, Optional[Path]] = {}         # place's root -> its vault
    notes = []
    for place, root in places:
        in_zone = root.parent.name == "Zones"
        vault = vault_at[root] = vault_of(ws, root)
        if vault is not None and vault not in vaults:
            gs, filters = obsidian_graph(vault)
            vaults[vault] = (len(groups), gs, filters)
            groups += [[colour, label] for _, colour, label in gs]
        filters = vaults[vault][2] if vault is not None else []
        for folder, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if walked(root, folder, d, in_zone))
            for f in sorted(files):
                if not f.endswith(".md") or f == "AGENTS.md" or f.startswith((".", "_")):
                    continue
                if folder == str(root) and (f in ("index.md", "log.md") and root.name == "wiki"
                                            or f == "Todo.md" and root.parent.name == "Zones"):
                    continue
                if filters and ignored((Path(folder) / f).relative_to(vault).as_posix(), filters):
                    continue
                notes.append((place, root, Path(folder) / f))
    rel = {path: path.relative_to(ws).with_suffix("").as_posix() for _, _, path in notes}
    by_rel = {r: p for p, r in rel.items()}
    nodes, index = [], {}
    kinds = [k for k, _, _ in KINDS]
    lib, source_type = workspace_lib(ws), "source"
    try:
        if lib is not None and callable(getattr(lib, "knowledge_schema", None)):
            source_type = lib.knowledge_schema(ws)[0]["source"]["type"]     # a wiki that names its sources otherwise
    except Exception:
        pass
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
        wiki = root.parent.name if not in_zone else ""
        if wiki:
            kind = wiki_kind(wiki, kind, parts, source_type)
        elif kind == "project" or (len(parts) == 2 and parts[1] == parts[0] + ".md"):
            kind = "project"
        elif kind not in ("project", "thread"):
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
        project_said = project if project and project.casefold() not in threads_said \
            and sum(1 for _, p in projects if p.casefold() == project.casefold()) == 1 else ""
        if kind == "project" and project_said:
            say = project        # "open Acme Review": the threads skill resolves a project name too
        # Short keys keep the page small. The layout adds x, y, vx, vy, ax, ay, r,
        # i, adj, deg, lp and lw to each node in the browser, so none of those is used here.
        index[path] = len(nodes)
        title = as_text(fm.get("title")).strip() or path.stem
        hub = kind in ("project", "thread", "person", "concept", "entity")
        nodes.append({"n": short_label(title) if wiki else title, "k": kinds.index(kind), "z": place, "p": project,
                      "t": party, "d": days, "s": 1 if parked else 0,
                      "c": 1 if hub else 0, "h": 1 if kind == "project" else 0,
                      "w": say, "u": link(path)})
        if moving and urgent and (place, project, folder_thread) in urgent:
            nodes[-1]["lt"] = 1                  # its next action is overdue or due a chase
        if wiki and nodes[-1]["n"] != title:
            nodes[-1]["N"] = title                   # the whole title, for the card and the tooltip
        vault = vault_at[root]
        if vault is not None and vaults[vault][1] and not wiki:     # a wiki is drawn by its kinds, whatever its vault says
            first, gs, _ = vaults[vault]
            rel_v = path.relative_to(vault).as_posix()
            nodes[-1]["g"] = next((first + i for i, (terms, _, _) in enumerate(gs) if any(group_match(t, fm, rel_v) for t in terms)), -1)
        if in_zone and project:
            home = root / project / "Threads" / folder_thread if folder_thread else root / project
            if cmux:
                nodes[-1]["f"] = str(home)          # where the apps a card offers open it
                if not say:                          # what they resume there
                    lw = names.get((place, project, folder_thread), "") if folder_thread else project_said
                    if lw:
                        nodes[-1]["lw"] = lw
            if drive:
                nodes[-1]["dk"] = [place, project, folder_thread]     # what the desk opens and closes
            live = session_in(desk, home) if kind in ("project", "thread") else None
            if live:
                nodes[-1]["live"] = live
        if kind == "project" and in_zone and project:
            nodes[-1]["hp"] = 1 if project in hubs_parked.get(place, ()) else 0
            if actions:
                nodes[-1]["pp"] = [place, project]                          # Park and Wake for all of it
        if kind == "thread" and in_zone and project in hubs_parked.get(place, ()):
            nodes[-1]["held"] = 1                                           # woken with its project
        elif actions and kind == "thread" and in_zone and folder_thread:
            nodes[-1]["pa"] = [place, path.relative_to(root).as_posix()]   # what Park and Wake act on
        if actions and kind == "thread" and in_zone and folder_thread and path.name == folder_thread + ".md":
            nodes[-1]["oc"] = [place, path.relative_to(root).as_posix()]   # what Open in Claude continues (#180)
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
    used = sorted({n["k"] for n in nodes if "g" not in n}
                  | ({kinds.index("note")} if any(n.get("g") == -1 for n in nodes) else set()))
    # In a wiki's core view the hubs are joined when one page links both: two
    # people in the same meeting, two concepts cited by the same source. The
    # third number is how many pages do.
    wikis = {place for place, root, _ in notes if root.parent.name != "Zones"}
    neighbours: Dict[int, set] = {}
    for a, b in edges:
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    co: Dict[Tuple[int, int], int] = {}
    for i, n in enumerate(nodes):
        if n["z"] not in wikis or n["c"]:
            continue
        hubs = sorted(j for j in neighbours.get(i, ()) if nodes[j]["c"] and nodes[j]["z"] == n["z"])
        for x in range(len(hubs)):
            for y in range(x + 1, len(hubs)):
                co[(hubs[x], hubs[y])] = co.get((hubs[x], hubs[y]), 0) + 1
    counts: Dict[str, int] = {}
    for n in nodes:
        counts[n["z"]] = counts.get(n["z"], 0) + 1
    return {"nodes": nodes, "edges": sorted(edges), "colors": [c for _, _, c in KINDS], "other": OTHER,
            "kinds": [[i, KINDS[i][1]] for i in used], "groups": groups,
            "mode": "all" if len(nodes) <= 150 else "core",
            "modes": {z: "all" if c <= 150 else "core" for z, c in counts.items()},
            "cl": {z: CORE_LABEL[z] for z in wikis if z in CORE_LABEL},
            "ce": [[a, b, w] for (a, b), w in sorted(co.items())]}


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


def history(folder: Path, name: str, now: dt.datetime) -> List[Tuple[dt.datetime, int, bool]]:
    """(when, exit, quiet) for each run the job's logs record in the last DAYS days."""
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
                runs.append((when, int(m.group(3)) if m.group(3) else 75, bool(m.group(5))))
    return runs


def quiet_exits(env: dict) -> Tuple[int, ...]:
    """Exit codes a job's plist marks as quiet in GARRICK_QUIET_EXITS, comma
    or space separated: the job did its work and held something back, and
    job.py raises no alarm for it. Anything not a number is passed over."""
    raw = str((env or {}).get("GARRICK_QUIET_EXITS") or "")
    return tuple(int(w) for w in re.split(r"[\s,]+", raw) if re.fullmatch(r"-?\d+", w))


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True                           # there, but another user's
    return True


def lock_held(lock: Path, now: dt.datetime) -> bool:
    """Whether a run holds the job's lock now. With the jobs extra loaded,
    job.py's own rule decides: a run whose job.py lives holds its lock
    whatever the time on it says, since that time runs on while a Mac
    sleeps. Without it, the record in `until`, "<until> <pid> [<started>]",
    holds until that time while its process lives, and a lock without a
    record counts for three hours."""
    if not lock.is_dir():
        return False
    job = sys.modules.get("job")
    if job is not None and hasattr(job, "holder"):
        try:
            return bool(job.holder(lock, 3 * 3600)[0])
        except Exception:
            pass
    try:
        words = (lock / "until").read_text(encoding="utf-8").split()
        if now.timestamp() >= float(words[0]):
            return False
        return pid_alive(int(words[1])) if len(words) > 1 and words[1].isdigit() else True
    except (OSError, ValueError, IndexError):
        try:
            return now.timestamp() - lock.stat().st_mtime < 3 * 3600
        except OSError:
            return False


def idle_limit(env: dict) -> float:
    """The days of idling a job's plist allows (GARRICK_IDLE_DAYS), or job.py's 7."""
    try:
        value = float((env or {}).get("GARRICK_IDLE_DAYS", 7))
    except (TypeError, ValueError):
        return 7.0
    return value if value >= 0 else 7.0


def jobs(folder: Path, now: dt.datetime, sched: Optional[Dict[str, dict]] = None) -> List[dict]:
    """One row per heartbeat in the jobs folder. A run whose exit job.py
    calls fine (the heartbeat's `ok` or `quiet`), or whose code the plist
    lists in GARRICK_QUIET_EXITS, is fine; a failure is said in the
    heartbeat's own `reason` when it has one. An idle job (the heartbeat's
    `idle`; from an older job.py, `idle_days` past the plist's
    GARRICK_IDLE_DAYS, 7) is a warning. A job whose lock is held is running now.
    A job whose plist runs job.py but which has no heartbeat yet, never run or
    not since its plist was added, gets a row too: neutral, "not run yet",
    with the schedule its plist gives."""
    sched = launchd_jobs() if sched is None else sched
    out = []
    for beat in sorted(folder.glob("*.heartbeat.json")) if folder.is_dir() else []:
        try:
            hb = json.loads(beat.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(hb, dict):
            continue
        name = hb.get("job") or beat.name[:-len(".heartbeat.json")]
        when = None
        try:
            when = dt.datetime.strptime(str(hb.get("finished"))[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
        code = int(hb.get("exit", -1)) if str(hb.get("exit", "")).lstrip("-").isdigit() else -1
        env = sched[name].get("env", {}) if name in sched else {}
        # job.py says itself whether the exit was fine (`ok`, `quiet`); an older
        # heartbeat leaves it to the codes and the plist's GARRICK_QUIET_EXITS.
        quiet = set(quiet_exits(env)) | ({code} if hb.get("quiet") is True or (hb.get("ok") is True and code not in OK_EXITS) else set())
        words, limit = (sched[name]["schedule"], sched[name]["late"]) if name in sched else ("schedule not found", None)
        try:
            idle = int(hb.get("idle_days") or 0)
        except (TypeError, ValueError):
            idle = 0
        if when and limit and now - when > limit:
            state, status = "critical", "late: last ran %s" % age(when, now)
        elif code not in OK_EXITS and code not in quiet:
            reason = hb.get("reason") if isinstance(hb.get("reason"), str) and hb.get("reason") else EXIT.get(code, "failed")
            state, status = "critical", "exit %d: %s" % (code, reason)
        elif (hb["idle"] is True) if isinstance(hb.get("idle"), bool) else (idle and idle >= idle_limit(env)):
            state, status = "warning", "idle %d days" % idle
        elif code in quiet and code not in OK_EXITS:
            state, status = "good", "ok, exit %d is quiet" % code
        elif hb.get("no_call") is True:
            state, status = "good", "ok, called no assistant"   # fine when there was nothing to do
        else:
            state, status = "good", "ok"
        out.append({"name": name, "when": when, "seconds": hb.get("seconds"), "state": state, "status": status,
                    "schedule": words, "runs": history(folder, name, now), "log": folder / (name + ".log"),
                    "quiet": tuple(sorted(quiet)), "running": lock_held(folder / (name + ".lock"), now),
                    "idle": state == "warning" and status.startswith("idle")})
    beaten = {j["name"] for j in out}
    for name, plist in sched.items():
        if name not in beaten:
            out.append({"name": name, "when": None, "seconds": None, "state": "none", "status": "not run yet",
                        "schedule": plist["schedule"], "runs": history(folder, name, now), "log": folder / (name + ".log"),
                        "quiet": quiet_exits(plist.get("env", {})), "running": lock_held(folder / (name + ".lock"), now),
                        "idle": False})
    return sorted(out, key=lambda j: j["name"].casefold())


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


def call_budget(agent, sched: Dict[str, dict]) -> float:
    """What one Claude call may spend before it is stopped: GARRICK_MAX_CALL_USD
    in the plists of the jobs that call the assistant, the lowest where they
    differ, or agent.py's default. 0 means no budget."""
    default = float(getattr(agent, "DEFAULT_MAX_CALL_USD", 5.0))
    calling = [j for j in sched.values() if j.get("agent")]
    envs = [j.get("env") or {} for j in calling] or [os.environ]
    found = []
    for env in envs:
        try:
            found.append(float(env.get("GARRICK_MAX_CALL_USD", default)))
        except (TypeError, ValueError):
            found.append(default)
    return min([b for b in found if b > 0] or [0.0])


def deny_list(agent) -> Optional[set]:
    """The tools a headless call may never use: the deny list in the jobs
    extra's headless-settings.json, beside agent.py. None when it is missing,
    does not read or has lost one of the entries every profile must hold
    (agent.py's own test), which agent.py refuses to run without."""
    profile = getattr(agent, "PROFILE", None)
    problem = getattr(agent, "profile_problem", None)
    try:
        if problem is not None and problem(Path(profile)):
            return None
    except Exception:
        return None
    try:
        data = json.loads(Path(profile).read_text(encoding="utf-8"))
        deny = data["permissions"]["deny"]
    except (TypeError, OSError, ValueError, KeyError):
        return None
    return {str(t) for t in deny} if isinstance(deny, list) else None


def denied_by_list(tool: str, deny: Optional[set]) -> bool:
    """A refused tool the deny list names: by its name, or by its server for
    a connector's tool (`mcp__server` covers `mcp__server__tool`). A tool
    refused only because no allow rule named it is not on the list."""
    if not deny:
        return False
    return tool in deny or any("(" not in d and tool.startswith(d + "__") for d in deny)


def ledger(agent, folder: Path, now: dt.datetime, sched: Optional[Dict[str, dict]] = None) -> Optional[dict]:
    path = folder / "ledger.jsonl"
    if agent is None or not path.is_file():
        return None
    entries = agent.read_ledger(path, now.timestamp(), DAYS * 24)
    sched = launchd_jobs() if sched is None else sched
    caps, caps_from = caps_in_use(agent, sched)
    calls = [e for e in entries if not e.get("refused")]
    day = [e for e in calls if now.timestamp() - e["ts"] < 86400]
    hour = [e for e in calls if now.timestamp() - e["ts"] < 3600]
    by = {}
    for e in entries:
        j = by.setdefault(e.get("job", "?"), {"calls": 0, "cost": 0.0, "failed": 0, "refused": 0, "denied": set(), "turns": []})
        if e.get("refused"):
            j["refused"] += 1
            continue
        j["calls"] += 1
        j["cost"] += float(e.get("cost_usd") or 0)
        j["failed"] += 1 if e.get("exit") else 0
        j["denied"] |= set(e.get("denied") or [])
        if isinstance(e.get("turns"), (int, float)):
            j["turns"].append(e["turns"])
    per_day: Dict[dt.date, list] = {}
    for e in calls:
        d = dt.datetime.fromtimestamp(e["ts"]).date()
        c = per_day.setdefault(d, [0, 0.0])
        c[0] += 1
        c[1] += float(e.get("cost_usd") or 0)
    days = [(now.date() - dt.timedelta(days=i)) for i in range(DAYS - 1, -1, -1)]
    return {"caps": caps, "caps_from": caps_from, "day": len(day), "hour": len(hour),
            "cost_day": sum(float(e.get("cost_usd") or 0) for e in day),
            "by": by, "refused_today": [e for e in entries if e.get("refused") and now.timestamp() - e["ts"] < 86400],
            "per_day": [(d,) + tuple(per_day.get(d, (0, 0.0))) for d in days],
            "began": dt.datetime.fromtimestamp(entries[0]["ts"]) if entries else None,
            "over_budget": [e for e in day if e.get("subtype") == "error_max_budget_usd"],
            "budget": call_budget(agent, sched), "deny": deny_list(agent)}


# --------------------------------------------------------------------------- small helpers

def age(t: dt.datetime, now: dt.datetime) -> str:
    s = (now - t).total_seconds()
    if s < 3600:
        return "%d min ago" % max(1, s // 60)
    if s < 86400 * 2:
        return "%d h ago" % round(s / 3600)
    return "%d days ago" % round(s / 86400)


# ---- what this machine has. Obsidian and cmux are both optional, so every
# build asks, and the page offers only what will work on it.
MAC_APPS = (Path("/Applications"), Path.home() / "Applications")


def mac_app(name: str, apps: Optional[List[Path]] = None) -> Optional[Path]:
    for folder in (MAC_APPS if apps is None else apps):
        app = Path(folder) / (name + ".app")
        if app.is_dir():
            return app
    return None


def obsidian_config() -> List[Path]:
    """Where Obsidian keeps its list of vaults: macOS, Linux, Windows."""
    home = Path.home()
    found = [home / "Library" / "Application Support" / "obsidian" / "obsidian.json",
             home / ".config" / "obsidian" / "obsidian.json"]
    if os.environ.get("APPDATA"):
        found.append(Path(os.environ["APPDATA"]) / "obsidian" / "obsidian.json")
    return found


def obsidian_vaults(ws: Path, config: Optional[Path] = None, apps: Optional[List[Path]] = None) -> List[Tuple[Path, str]]:
    """The vaults Obsidian has registered that hold this workspace's notes:
    the root, or a zone or wiki opened on its own, or a folder above the
    workspace. Each comes with the name a link gives it: the folder's name,
    or the vault's id when two registered vaults share a name. On a Mac,
    Obsidian must still be installed. Deepest first, so a note opens in the
    vault closest to it."""
    if sys.platform == "darwin" and mac_app("Obsidian", apps) is None:
        return []
    data = None
    for f in ([config] if config else obsidian_config()):
        try:
            data = json.loads(Path(f).read_text(encoding="utf-8"))
            break
        except (OSError, ValueError):
            continue
    vaults = data.get("vaults") if isinstance(data, dict) else None
    known = [(str(vid), Path(v["path"])) for vid, v in (vaults or {}).items() if isinstance(v, dict) and v.get("path")]
    names = [p.name for _, p in known]
    root = ws.resolve()
    out = []
    for vid, folder in known:
        where = folder.resolve()
        if where.is_dir() and (where == root or root in where.parents or where in root.parents):
            out.append((where, folder.name if names.count(folder.name) == 1 else vid))
    return sorted(out, key=lambda v: len(v[0].parts), reverse=True)


def cmux_installed(apps: Optional[List[Path]] = None) -> bool:
    """cmux is a macOS app; the page offers it where it is installed."""
    return "cmux" in launchers_installed(apps)


# The apps a project or thread can be opened in, in the order the page offers
# them: key, label, bundle id, the names its .app may carry. The page offers
# the ones installed here, Settings chooses among those, and only Garrick's
# Status.app can open them; in a browser the page still only copies.
LAUNCHERS = (("finder", "Finder", "com.apple.finder", ()),
             ("cmux", "cmux", "com.cmuxterm.app", ("cmux",)),
             ("codex", "Codex", "com.openai.codex", ("Codex", "ChatGPT")),
             ("claude", "Claude", "com.anthropic.claudefordesktop", ("Claude",)))
VERB = {"finder": "Reveal in Finder", "cmux": "Open in cmux", "codex": "Open in Codex", "claude": "Open in Claude"}
LABEL = {k: label for k, label, _, _ in LAUNCHERS}


def bundle_id(app: Path) -> Optional[str]:
    try:
        with (app / "Contents" / "Info.plist").open("rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier")
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


# Codex opens a folder through its own launcher inside the app bundle, as
# Garrick.app and the Obsidian plugin both run it. An app without one is
# installed but cannot be opened into a folder, so the page does not offer it:
# a launcher that cannot work is disabled with its reason on it, rather than
# offered and refused after the click.
CODEX_CLI = ("Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
             "Contents/Resources/codex", "Contents/Resources/bin/codex")
NOT_ON_A_MAC = "Opening an app is a Mac's own; this page was built elsewhere"
NOT_INSTALLED = "Not installed on this Mac"
NO_CODEX_CLI = "Installed, but its own launcher is missing: reinstall the Codex app"
# Installed and able to work, but this build was told to leave it out (--no-cmux).
LEFT_OUT = "Left out when this page was built"


def launcher_state(apps: Optional[List[Path]] = None) -> Dict[str, Optional[str]]:
    """Every launcher of LAUNCHERS, to None where it will work on this Mac or
    to why it will not. An app is known by its bundle id, so the ChatGPT app is
    not taken for Codex; one with no readable Info.plist is taken at its name.
    Settings puts the reason on the row it greys out, and the page offers only
    the ones with none."""
    if sys.platform != "darwin":
        return {key: NOT_ON_A_MAC for key, _, _, _ in LAUNCHERS}
    state: Dict[str, Optional[str]] = {}
    for key, _, bundle, names in LAUNCHERS:
        if key == "finder":
            state[key] = None                   # every Mac has it
            continue
        app = next((a for a in (mac_app(name, apps) for name in names)
                    if a is not None and bundle_id(a) in (bundle, None)), None)
        if app is None:
            state[key] = NOT_INSTALLED
        elif key == "codex" and not any(os.access(app / rel, os.X_OK) for rel in CODEX_CLI):
            state[key] = NO_CODEX_CLI
        else:
            state[key] = None
    return state


def launchers_installed(apps: Optional[List[Path]] = None) -> Tuple[str, ...]:
    """Which of LAUNCHERS will work on this Mac: the ones launcher_state()
    found nothing wrong with, in the order the page offers them."""
    state = launcher_state(apps)
    return tuple(key for key, _, _, _ in LAUNCHERS if state[key] is None)


class Links:
    def __init__(self, ws: Path, vault: Optional[str] = None, vaults: Optional[List[Tuple[Path, str]]] = None):
        """`vault` names the workspace root as a vault; `vaults` are the
        vaults found on this machine, deepest first."""
        self.ws = ws
        self.vaults = [(ws, vault)] if vault else list(vaults or [])

    def __call__(self, path: Path) -> str:
        """A link to the file. In Obsidian a file is named by its path in the
        vault, so a note that is a symlink to a file elsewhere keeps the path
        of the link; a file in no vault, such as a job's log, is linked as a
        file."""
        for root, name in self.vaults:
            for candidate in (Path(os.path.abspath(path)), path.resolve()):
                rel = None
                for base in (Path(os.path.abspath(root)), Path(root).resolve()):
                    try:
                        rel = candidate.relative_to(base).as_posix()
                        break
                    except ValueError:
                        continue
                if rel is not None:
                    rel = rel[:-3] if rel.endswith(".md") else rel
                    return "obsidian://open?vault=%s&file=%s" % (urllib.parse.quote(name), urllib.parse.quote(rel))
        return path.resolve().as_uri()


def day_cells(runs: List[Tuple[dt.datetime, int]], now: dt.datetime, quiet: Tuple[int, ...] = ()) -> List[Tuple[str, str]]:
    """One cell per day, oldest first, coloured by how the day ended: red when
    its last run failed or most runs did, amber when it failed and recovered.
    A run that exited with one of the job's quiet codes counts as fine."""
    fine = set(OK_EXITS) | set(quiet)

    def ok(r):
        return r[1] in fine or (len(r) > 2 and bool(r[2]))
    out = []
    for i in range(DAYS - 1, -1, -1):
        day = (now - dt.timedelta(days=i)).date()
        rs = sorted((r for r in runs if r[0].date() == day), key=lambda r: r[0])
        bad = [r for r in rs if not ok(r)]
        if not rs:
            out.append(("none", "%s · no run" % day.strftime("%a %d %b")))
            continue
        ended_bad = not ok(rs[-1])
        state = "critical" if ended_bad or len(bad) * 2 > len(rs) else "warning" if bad else "good"
        tip = "%s · %d run%s" % (day.strftime("%a %d %b"), len(rs), "" if len(rs) == 1 else "s")
        if bad:
            codes = sorted({r[1] for r in bad})
            tip += " · %d failed (exit %s)%s" % (len(bad), ", ".join(map(str, codes)), "" if ended_bad else " · recovered")
        else:
            held = sorted({r[1] for r in rs if ok(r) and r[1] not in OK_EXITS})
            tip += " · all ok" + (" (exit %s is quiet)" % ", ".join(map(str, held)) if held else "")
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


def thread_card(r: dict, names: Dict[Tuple[str, str, str], str], link: "Links", days: Optional[int], cmux: bool = False,
                actions: bool = False, desk: Optional[Dict[str, str]] = None, today: Optional[dt.date] = None,
                drive: bool = False) -> str:
    """What a thread's card shows, as JSON for its row: the same fields the
    graph gives a note, so one helper draws both. Names, tags, the days since
    the note was updated, whether it is parked (`held` when only because its
    project is), the name to say, its note's link; whether the note has a
    Resume here block (`r`), how old that block's date is (`rd`), and whether
    its own next action is overdue or due a chase (`lt`), which is the one
    thing that marks a thread; its age never does. Where an app to open it in is installed (`cmux`, for any
    of LAUNCHERS), also the thread's folder. With the cmux extra (`desk`, the
    sessions open), the session's state, and with `drive` (the extra and
    cmux) what the desk opens and closes."""
    card = {"n": r["thread"], "kl": "thread", "z": r["zone"], "p": r["project"], "t": r["party"], "d": days,
            "s": 1 if r["status"] == "parked" else 0, "w": names[(r["zone"], r["project"], r["thread"])], "h": 0,
            "u": link(r["note"]), "r": 1 if r.get("resume") else 0,
            "rd": (today - r["resumed"]).days if today and r.get("resumed") else None}
    if r.get("urgent"):
        card["lt"] = 1
    if cmux:
        card["f"] = str(r["note"].parent)
    if r.get("held"):
        card["held"] = 1             # parked with its project: woken with it, from the project's card
    elif actions:
        card["pa"] = [r["zone"], r["rel"]]
    if actions:
        card["oc"] = [r["zone"], r["rel"]]     # what Open in Claude continues (#180), parked or not
    if r["note"] != r["hub"]:
        card["mg"] = [r["zone"], r["project"], r["thread"], files_in(r["note"].parent),
                      open_naming(r["note"].parents[3], {r["thread"]})]
    if drive:
        card["dk"] = [r["zone"], r["project"], "" if r["note"] == r["hub"] else r["thread"]]
    live = session_in(desk, r["note"].parent)
    if live:
        card["live"] = live
    return json.dumps(card, separators=(",", ":"), ensure_ascii=False)


def files_in(folder: Path) -> int:
    """How many files deleting a folder would take, for the warning."""
    return sum(len([f for f in fs if not f.startswith(".")]) for d, _, fs in os.walk(folder) if ".git" not in Path(d).parts)


_OPEN: Dict[Path, List[str]] = {}


def open_naming(zone: Path, names: set) -> int:
    """How many open lines of the zone's Todo.md link to one of `names`, as
    scaffold.py's delete would remove them."""
    if zone not in _OPEN:
        try:
            text = (zone / "Todo.md").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        _OPEN[zone] = [l for l in text.splitlines() if re.match(r"\s*- \[ \]", l)]
    n = 0
    for line in _OPEN[zone]:
        targets = [t.split("|")[0].split("#")[0] for t in re.findall(r"\[\[([^\]]+)\]\]", line)]
        n += any(t.rsplit("/", 1)[-1] in names for t in targets)
    return n


def manage_data(T: Dict[str, dict], ctx: dict, acting: bool) -> dict:
    """For the New project and New thread dialogs: each zone's projects and
    the parties a project there can be for; and whether the app acts, or the
    page only copies the phrase to say."""
    zones = {}
    for zone, data in T.items():
        projects = sorted({r["project"] for r in data["rows"] + data["parked"] if r.get("hub")}, key=str.casefold)
        parties = sorted([[tag, p.get("party") or tag] for tag, p in ctx.get("parties", {}).items()
                          if (p.get("zone") or "").strip().lower() in ("", zone.lower())], key=lambda x: x[1].casefold())
        zones[zone] = {"projects": projects, "parties": parties}
    return {"zones": zones, "acting": acting}


def find_data(T: Dict[str, dict], link: "Links", styles: Dict[str, dict], folders: bool, today: dt.date) -> dict:
    """What the Threads card's search box looks through (#140): every project
    and thread in every zone, live, parked and finished, by its name, its
    project's and its zone's, and the `spoken:` forms of the first two. Names
    only, never a note's body. A live or parked one has its row on the card
    already, and the page takes its card from there, so what Park or Wake did
    since is what it shows. A finished thread, or a project with no row of its
    own, carries its card here as `c`: the note to open, and nothing that
    changes it. `zones` is each zone's label as the card heads it."""
    items = []
    for zone, data in T.items():
        P = data.get("projects", {})
        on_card = {r["project"] for r in data["rows"] + data["parked"]}
        for project, p in sorted(P.items(), key=lambda kv: kv[0].casefold()):
            if p["own"]:                        # its own single thread: listed once, as the thread
                continue
            it = {"k": "p", "z": zone, "n": project, "s": p["status"]}
            if p["spoken"]:
                it["sp"] = p["spoken"]
            if project not in on_card and p["hub"]:
                c = {"n": project, "kl": "project", "z": zone, "p": "", "t": p["party"], "d": None, "h": 1,
                     "s": 1 if p["status"] == "parked" else 0, "u": link(p["hub"])}
                if p["status"] == "done":
                    c["fin"] = 1
                if folders:
                    c["f"] = str(p["hub"].parent)
                it["c"] = c
            items.append(it)
        for state, rs in (("live", data["rows"]), ("parked", data["parked"]), ("done", data.get("finished", []))):
            for r in rs:
                it = {"k": "t", "z": zone, "p": r["project"], "n": r["thread"], "s": state}
                if r.get("spoken"):
                    it["sp"] = r["spoken"]
                spoken = P.get(r["project"], {}).get("spoken")
                if spoken and r["note"] != r["hub"]:
                    it["psp"] = spoken
                if state == "done":
                    c = {"n": r["thread"], "kl": "thread", "z": zone, "p": r["project"], "t": r["party"],
                         "d": (today - r["updated"]).days if r["updated"] else None, "s": 0, "fin": 1, "h": 0, "u": link(r["note"])}
                    if folders:
                        c["f"] = str(r["note"].parent)
                    it["c"] = c
                items.append(it)
    return {"items": items, "zones": {z: "<span%s>%s</span>" % (zone_attr(z, styles), zone_name(z, styles)) for z in T}}


def menu_data(T: Dict[str, dict], names: Dict[Tuple[str, str, str], str], link: "Links", folders: bool, trouble: bool,
              desk: Optional[Dict[str, str]] = None, drive: bool = False, cli: bool = False) -> dict:
    """What the app's menu bar icon lists: per zone, its
    live projects by name, each with its live threads by name, and whether
    the Status tab carries its red dot. A project or thread gives its name,
    the name to say, its note's link and, where an app can open it, its
    folder: the app offers the same actions its card does. A project with no
    thread notes is its own thread. With the cmux extra, each row also says
    whether a session is open in it (`s`: "idle", "working" or None; a
    project counts its threads'), and with `drive` what the desk opens
    (`dk`: zone, project, thread or ""), and `dk` on the whole menu too: the
    app then opens anything in cmux through the desk, the workspace root for
    Process the Inbox and Ask included. A thread, and a project that is one
    thread, gives its note (`oc`: zone, note from the zone): with `cli`, where
    this build found Claude Code's command-line tool (`cli` on the whole menu),
    the app's Open in Claude continues it through page_action.py, as the
    page's does (#180). The app keeps the zone the graph shows;
    parked threads stay out, as do figures."""
    said = {r["thread"].casefold() for z in T.values() for r in z["rows"] + z["parked"]}
    project_n: Dict[str, int] = {}
    for data in T.values():
        for p in {r["project"] for r in data["rows"] + data["parked"]}:
            project_n[p.casefold()] = project_n.get(p.casefold(), 0) + 1

    def entry(name, say, note, dk, oc=None):
        e = {"n": name, "w": say, "u": link(note)}
        if oc:
            e["oc"] = oc
        if drive:
            e["dk"] = dk
        if folders:
            e["f"] = str(note.parent)
        live = session_in(desk, note.parent)
        if live:
            e["s"] = live
        return e

    zones = []
    for zone, data in T.items():
        groups: Dict[str, list] = {}
        for r in data["rows"]:
            groups.setdefault(r["project"], []).append(r)
        projects = []
        for project, rs in sorted(groups.items(), key=lambda kv: kv[0].casefold()):
            if len(rs) == 1 and rs[0]["note"] == rs[0]["hub"]:          # its own thread
                projects.append(dict(entry(project, names[(zone, project, project)], rs[0]["note"], [zone, project, ""],
                                           [zone, rs[0]["rel"]]), t=[]))
                continue
            hub = rs[0]["hub"] or rs[0]["note"]
            say = project if project.casefold() not in said and project_n.get(project.casefold()) == 1 else ""
            threads = [entry(r["thread"], names[(zone, project, r["thread"])], r["note"], [zone, project, r["thread"]],
                             [zone, r["rel"]])
                       for r in sorted(rs, key=lambda r: r["thread"].casefold())]
            projects.append(dict(entry(project, say, hub, [zone, project, ""]), t=threads))
        zones.append({"z": zone, "p": projects})
    out = {"trouble": trouble, "zones": zones}
    if drive:
        out["dk"] = 1
    if cli:
        out["cli"] = 1
    return out


def help_button(name: str, key: str) -> str:
    """A "?" that shows or hides the explanation help_text() makes for the
    same key, where it stands. A button, so the keyboard reaches it, and
    aria-expanded says whether the explanation is showing."""
    return ('<button class="qhelp" type="button" aria-expanded="false" aria-controls="help-%s" aria-label="Explain %s" '
            'title="Explain">?</button>' % (key, E(name)))


def help_text(key: str, html: str) -> str:
    """A Settings section's explanation, word for word, hidden until its "?" is pressed."""
    return '<p class="hint sethelp" id="help-%s" hidden>%s</p>' % (key, html)


def set_head(name: str, key: str) -> str:
    """A Settings section's heading, with the "?" for its explanation."""
    return '<h3>%s%s</h3>' % (E(name), help_button(name, key))


def menu_settings() -> str:
    """Settings › Menu bar, shown in Garrick.app
    only: the icon or a panel at a screen edge, opening at login, the
    shortcut that opens either, the one that opens the Ask box (preview
    ask), and the dictation the box starts once it opens. The app keeps
    them all, so they hold when the window is closed."""
    return ('<section class="setsec apponly" id="menu-settings" hidden>' + set_head("Menu bar", "menu") + help_text("menu", 'A menu of the live '
            'projects of the zone the graph shows, with their threads, kept at hand outside this window. Click one to open it as a '
            'thread&#39;s name would, or point at it for the other apps above. Close the window and the menu stays.') +
            '<div class="launcher-row"><label class="launcher-choice"><input type="checkbox" id="menu-show"> <span>Show the menu'
            '<small>Marked in red when something on the Status tab failed</small></span></label></div>'
            '<div class="launcher-row" style="display:none"><label class="launcher-choice" for="menu-style"><span>Shows as'
            '<small>A panel opens when the pointer rests on the top third of its edge, or on the notch</small></span></label>'
            '<select id="menu-style" class="menu-style"><option value="icon">Menu bar icon</option><option value="left">Panel from the left</option>'
            '<option value="right">Panel from the right</option><option value="top">Panel from the top</option></select></div>'
            '<div class="launcher-row"><label class="launcher-choice"><input type="checkbox" id="menu-login"> <span>Open at login'
            '<small id="menu-login-note">Starts the app when you log in, with the window as you left it</small></span></label></div>'
            '<div class="launcher-row"><label class="launcher-choice" for="menu-hotkey"><span>Hotkey<small id="menu-hotkey-note">Opens the menu '
            'or the panel from any app</small></span></label>'
            '<span class="hotkey"><input type="text" id="menu-hotkey" readonly placeholder="Click, then press keys" aria-label="Hotkey">'
            '<button class="act" type="button" id="menu-hotkey-clear">Clear</button></span></div>'
            '<div class="launcher-row" style="display:none"><label class="launcher-choice" for="menu-askkey"><span>Ask hotkey<small id="menu-askkey-note">'
            'Opens the Ask box from any app, with the preview ask on</small></span></label>'
            '<span class="hotkey"><input type="text" id="menu-askkey" readonly placeholder="None" aria-label="Ask hotkey">'
            '<button class="act" type="button" id="menu-askkey-clear">Clear</button></span></div>'
            '<div class="launcher-row" style="display:none"><label class="launcher-choice" for="menu-dictation"><span>Then start dictation'
            '<small id="menu-dictation-note">Once the Ask box opens, start dictation in it too</small></span></label>'
            '<select id="menu-dictation" class="menu-style"><option value="off">Off</option><option value="macos">macOS Dictation</option>'
            '<option value="fn">Press Fn</option><option value="fn2">Press Fn twice</option><option value="key">Press a shortcut</option></select></div>'
            '<div class="launcher-row" style="display:none"><label class="launcher-choice" for="menu-dictkey"><span>Dictation shortcut'
            '<small id="menu-dictkey-note">Click, then press the shortcut your dictation tool starts on. Pause the tool first if it takes the keys</small></span></label>'
            '<span class="hotkey"><input type="text" id="menu-dictkey" readonly placeholder="Click, then press keys" aria-label="Dictation shortcut">'
            '<button class="act" type="button" id="menu-dictkey-clear">Clear</button></span></div></section>')


def copy(label: str, text: str, say: str) -> str:
    """A button that copies a phrase for your assistant, or a command for your
    terminal. The page acts on nothing itself."""
    return '<button class="act" type="button" data-copy="%s" data-say="%s">%s</button>' % (E(text), E(say), E(label))


# The changelog the workspace was installed with: install.py copies the
# release's CHANGELOG.md here, so the page shows release notes without
# fetching anything.
CHANGELOG = ("System", "garrick-changelog.md")
GEAR = ('<svg viewBox="0 0 20 20" width="17" height="17" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.5" '
        'stroke-linejoin="round" d="M8.6 2.5h2.8l.4 2.1 1.5.9 2-.8 1.4 2.4-1.6 1.4v1.8l1.6 1.4-1.4 2.4-2-.8-1.5.9-.4 2.1H8.6l-.4-2.1'
        '-1.5-.9-2 .8-1.4-2.4 1.6-1.4V8.5L3.3 7.1l1.4-2.4 2 .8 1.5-.9z"/><circle cx="10" cy="10" r="2.4" fill="none" '
        'stroke="currentColor" stroke-width="1.5"/></svg>')


REBUILD = ('<svg viewBox="0 0 20 20" width="17" height="17" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.6" '
           'stroke-linecap="round" stroke-linejoin="round" d="M16 10a6 6 0 1 1-1.8-4.3M16 3.5v3.4h-3.4"/></svg>')


def changelog_sections(text: str) -> List[Tuple[str, str, List[str]]]:
    """Each `## [name] - date` section of a Keep a Changelog file, with its lines."""
    out: List[Tuple[str, str, List[str]]] = []
    for line in text.splitlines():
        m = re.match(r"^## \[([^\]]+)\](?:\s*-\s*(\S+))?", line)
        if m:
            out.append((m.group(1), m.group(2) or "", []))
        elif out and not re.match(r"^\[[^\]]+\]:\s*\S", line):     # link references stay out
            out[-1][2].append(line)
    return out


def md_inline(s: str) -> str:
    """A line of Markdown, through guide.py's renderer: a link keeps its text, since the page links only to Garrick."""
    return guide_mod().inline(s)


def md_block(lines: List[str]) -> str:
    """A changelog section, through guide.py's renderer: its ### headings drawn as <h5>, its links as their text."""
    return guide_mod().blocks("\n".join(lines), shift=2)


def release_notes(text: Optional[str], edge: bool = False) -> str:
    """The newest release's notes, read from a changelog on this machine. With
    `edge`, for a workspace that follows main rather than a release, also
    what is waiting under Unreleased."""
    if not text:
        return ""
    sections = changelog_sections(text)
    parts = []
    if edge:
        waiting = [s for s in sections if s[0].lower() == "unreleased" and any(l.strip() for l in s[2])]
        if waiting:
            parts.append(("Coming next, on main", waiting[0][2]))
    released = [s for s in sections if s[0].lower() != "unreleased"]
    if released:
        name, date, lines = released[0]
        parts.append(("What's new in %s%s" % (name, ", " + date if date else ""), lines))
    return "".join('<details class="notes"%s><summary>%s</summary><div>%s</div></details>'
                   % ("", E(title), md_block(lines)) for title, lines in parts)


# Where a way past the wall check is reported: GitHub's private advisory form.
BYPASS = "/security/advisories/new"


def about_garrick(version: str, notes: str = "") -> str:
    """Settings › About Garrick: which Garrick this is, its release notes, and
    the ways to report a bug, suggest a change, ask, or hear about releases.
    Each is a link to Garrick's GitHub page, opened in the browser, where
    nothing is sent until you submit it yourself; the bug form arrives with the
    version filled in. For someone with no GitHub account, a report to copy and
    send to whoever set Garrick up. The page never calls out: a newer release
    is asked for at build, only with the release notice switched on, by
    System/tools/release.py (release_ask)."""
    report = ("Garrick bug report\n\nWhich Garrick: %s\n\nWhat happened:\n\nHow to make it happen again:\n\n"
              "Assistant and its version:\n\nUse invented names (Acme, Birch), never a real client's." % version)
    # The two forms that publish what you write warn, as their tooltip, what
    # the paragraph behind the "?" says; a way past the wall check has a row
    # of its own, so the private report is never deeper than the others.
    invented = "Use invented names (Acme, Birch), never a real client's."
    links = [
        ("Report a bug", "/issues/new?" + urllib.parse.urlencode({"template": "bug.yml", "garrick": version}),
         "The bug form on GitHub, with this version filled in", invented),
        ("Report a wrong refusal", "/issues/new?template=wall-check.yml", "The wall check refused something it should allow", invented),
        ("Report a bypass privately", BYPASS, "A way past the wall check, seen only by the maintainer", ""),
        ("Suggest a change", "/discussions/new?category=ideas", "Something Garrick should do, or do differently", ""),
        ("Ask a question", "/discussions/new?category=q-a", "How something works, or how it went for you", ""),
        ("Announcements", "/discussions/categories/announcements", "News of each release; watch it on GitHub to hear of the next", ""),
        ("All releases", "/releases", "Every release and what it changed", ""),
    ]
    rows = "".join('<a class="setlink" href="%s" target="_blank" rel="noopener"%s><b>%s</b><small>%s</small></a>'
                   % (E(PROJECT + path), ' title="%s"' % E(tip) if tip else "", E(label), E(about))
                   for label, path, about, tip in links)
    return ('<section class="setsec">%s<p class="setver" id="garrick-version">%s</p>'
            '<div class="gacts">%s%s</div>%s<div class="setlinks">%s</div>%s</section>'
            % (set_head("About Garrick", "about"), E(version), copy("Copy version", version, "Copied the version."),
               copy("Copy a report", report, "Copied a report. Fill it in and send it."), notes, rows,
               help_text("about", 'These open GitHub in your browser. The page sends nothing: a report goes only when you submit it '
                         'there. Use invented names (Acme, Birch), never a real client&#39;s. No GitHub account? Copy a report and send '
                         'it to whoever set Garrick up for you. A way past the wall check: <a href="%s" target="_blank" rel="noopener">'
                         'report it privately</a>.' % E(PROJECT + BYPASS))))


def launcher_choices(installed: Tuple[str, ...], obsidian: bool = False,
                     why: Optional[Dict[str, Optional[str]]] = None) -> str:
    """Settings › Opening a thread: the note's own link, then each app Garrick
    can open a project in, with a checkbox (offered on the cards) and a radio
    (what clicking a thread's name does). A launcher that cannot work here is
    disabled with the reason on it, before any click rather than after: not
    installed, or installed without the launcher it opens a folder through.
    Kept in this viewer's own storage, so the page still writes nothing."""
    why = launcher_state() if why is None else why
    rows = [("note", "Open in Obsidian" if obsidian else "Open the note", True, "The note&#39;s own link")]
    rows += [(k, VERB[k], k in installed,
              "Installed" if k in installed else E(why[k]) if why.get(k) else LEFT_OUT)
             for k, _, _, _ in LAUNCHERS]
    html = "".join('<div class="launcher-row"><label class="launcher-choice"><input type="checkbox" data-launcher="%s"%s> <span>%s<small>%s</small></span></label>'
                   '<label class="launcher-default" title="What clicking a thread does"><input type="radio" name="garrick-default" value="%s"%s> Default</label></div>'
                   % (k, "" if ok else " disabled", E(label), note, k, "" if ok else " disabled")
                   for k, label, ok, note in rows)
    return ('<section class="setsec">%s%s%s</section>'
            % (set_head("Opening a thread", "launchers"), help_text("launchers", 'Tick what project and thread cards offer; the dot marks what '
               'clicking a thread&#39;s name does. Apps open from Garrick&#39;s Status.app, which says what opened. Claude starts with the phrase '
               'that resumes the thread typed in, for you to send, and is started first and waited for when it is not running; Codex and cmux open '
               'in the folder and say that the phrase is now on the clipboard; Finder, which can take neither, names the phrase instead. A greyed '
               'row says why it cannot work here. Saved as you change it.'),
               html))


def follow_settings() -> str:
    """Settings › Explore: whether the graph follows the zone you are reading
    on the Threads card (#142, FOLLOW_JS). On until switched off, and kept in
    this window, as the graph's other choices are; only on a page with the graph."""
    return ('<section class="setsec" id="follow-settings">%s%s<div class="launcher-row"><label class="launcher-choice">'
            '<input type="checkbox" id="graph-follow" checked> <span>Follow the zone in view<small>Explore shows the zone you are '
            'reading on the Threads card</small></span></label></div></section>'
            % (set_head("Explore", "explore"), help_text("explore", 'Scroll the Threads card from one zone into the next and Explore '
               'switches to it once it has filled the window for a moment. With the zones side by side, point at a column or open a '
               'project or thread in it. The switch is for this page only: the zone you pick in Explore&#39;s drop-down still leads '
               'the card and is what the page opens on. Picking All or a wiki pauses it until the page reloads. Kept in this window.')))


def preview_section(flags: Dict[str, bool]) -> str:
    rows = "".join('<div class="flagrow"><b>%s</b><span class="chip%s">%s</span><small>%s</small></div>'
                   % (E(FLAGS[k][0]), " on" if on else "", "on" if on else "off", E(FLAGS[k][1])) for k, on in flags.items())
    return ('<section class="setsec">%s%s%s</section>'
            % (set_head("Preview features", "preview"), rows, help_text("preview", 'In Garrick&#39;s source but not yet released, '
               'so they may still change. Switch one on in <code>System/garrick-flags.json</code>, for example '
               '<code>{"effort": true}</code>, and rebuild the page.')))


# The foot of Settings, under the last section: the cards hidden in this
# window, when there are any, then Reset view, its explanation as its tooltip
# and behind its "?".
VIEW_HELP = "Cards dragged or hidden, folds, the graph's view and the open tab are remembered in this window only."
VIEW = ('<div class="setfoot"><div class="setrule"><div class="hiddencards" id="hidden-cards" hidden></div><div class="gacts">'
        '<button class="act" type="button" id="reset-view" title="%s">Reset view</button>%s</div>%s</div></div>'
        % (E(VIEW_HELP + " Reset view puts every card back in place and shown, in the order this Garrick builds, "
                         "folds, graph and filter as built."),
           help_button("Reset view", "view"), help_text("view", E(VIEW_HELP))))


def settings(ws: Path, installed: Tuple[str, ...] = (), zones: Tuple[str, ...] = (),
             styles: Optional[Dict[str, dict]] = None, graph: bool = False, sched: Optional[Dict[str, dict]] = None,
             layout: str = "full") -> str:
    """The Settings dialog: which apps to open projects in, whether Explore
    follows the zone in view (with the graph), each zone's colour and icon,
    where notices go (`sched`, the jobs' plists, for the ones that override
    it), About Garrick, and the preview features with which are switched on."""
    stamp = workspace_stamp(ws)
    try:
        text = ws.joinpath(*CHANGELOG).read_text(encoding="utf-8")
    except OSError:
        text = None
    notes = release_notes(text, edge=stamp.get("from") in ("clone", "adopted"))
    # Two columns where the window is wide enough, so every section fits in
    # about one window height: what you choose on the left, Notifications
    # (the longest) and Garrick on the right, with Reset view at the foot of
    # it, level with the left's end.
    return ('<dialog id="settings" class="settings" aria-labelledby="settings-title">'
            '<button class="sclose" type="button" id="close-settings" title="Close" aria-label="Close Settings">&#215;</button>'
            '<h2 id="settings-title" tabindex="-1" autofocus>Settings</h2><div class="setcols"><div class="setcol">%s</div>'
            '<div class="setcol">%s</div></div></dialog>'
            % (home_settings(layout) + launcher_choices(installed, bool(mac_app("Obsidian"))) + (follow_settings() if graph else "")
               + zone_settings(list(zones), styles or {}) + menu_settings() + wait_settings(ws),
               notify_settings(ws, list(zones), styles or {}, sched, CMUXLIB.is_file())
               + about_garrick(installed_version(ws), notes) + preview_section(preview_flags(ws)) + VIEW))


LAUNCH_KEYS = ("note",) + tuple(k for k, _, _, _ in LAUNCHERS)


def shared_launchers(ws: Path) -> Optional[dict]:
    """The launcher settings saved for every viewer of the page, in the
    workspace's own settings file (prefs.FILE, committed with it):
    {"launchers": the ways to open a thread that cards offer, as {name: true
    or false} or a list of the names switched on, "default": what clicking a
    thread does}. The page carries them as a list. The
    app's Settings writes them, through page_action.py; inside the app they
    come before what a window remembers. None when there are none, or they do
    not read; an unknown key is dropped."""
    data = prefs().read(ws)
    on = data.get("launchers")
    if isinstance(on, dict):                  # {"note": true, "cmux": false, ...}: a key left out is on
        chosen = [k for k in LAUNCH_KEYS if on.get(k, True) is True]
    elif isinstance(on, list):                # the names of those switched on
        chosen = [k for k in LAUNCH_KEYS if k in on]
    else:
        return None
    default = data.get("default") if data.get("default") in LAUNCH_KEYS else "note"
    return {"launchers": chosen, "default": default}


# A colour and an icon for each zone, chosen in Settings › Zones and saved
# beside the launchers, in the workspace's own settings file:
# {"zones": {"Work": {"color": "Teal", "icon": "briefcase"}}}.
# The colours are cmux's sixteen named workspace colours, so a zone's labels
# here and its workspace in cmux agree. Each has an ink for a label's text on
# each ground: on light, cmux's own default value, at 4.9 to 1 or more against
# the page; on dark, the same hue lightened to 4.8 to 1 or more, the darker of
# cmux's colours staying the darker, so neighbours such as Red and Crimson
# stay apart.
ZONE_COLOURS = {
    "Red": ("#C0392B", "#E9A39B"), "Crimson": ("#922B21", "#E1857C"), "Orange": ("#A04000", "#ED9960"),
    "Amber": ("#7D6608", "#D6B018"), "Olive": ("#4A5C18", "#8EB12E"), "Green": ("#196F3D", "#2DC86E"),
    "Teal": ("#006B6B", "#15C1C1"), "Aqua": ("#0E6B8C", "#3FBDEA"), "Blue": ("#1565C0", "#82B6F1"),
    "Navy": ("#1A5276", "#50A3D9"), "Indigo": ("#283593", "#7380D9"), "Purple": ("#6A1B9A", "#BB74E7"),
    "Magenta": ("#AD1457", "#F187B6"), "Rose": ("#880E4F", "#ED5CA9"), "Brown": ("#7B3F00", "#E6851F"),
    "Charcoal": ("#3E4B5E", "#8798B0"),
}
# The icons a zone can take: a fixed set, so each stays legible at label size.
# Drawn as the page's other icons are, a 16-unit square in one stroke of the
# text's own colour, so an icon takes its zone's colour with the name.
ZONE_ICONS = {
    "briefcase": '<rect x="2.5" y="5" width="11" height="8.5" rx="1.5"/><path d="M6 5V3.8c0-.5.4-.8.8-.8h2.4c.5 0 .8.3.8.8V5M2.5 9h11"/>',
    "house": '<path d="M2.5 7.5L8 3l5.5 4.5M4 6.5V13h8V6.5M6.7 13V9.8h2.6V13"/>',
    "flask": '<path d="M6 2.5h4M6.8 2.5v4.2l-3.5 5.8c-.4.7.1 1.5.9 1.5h7.6c.8 0 1.3-.8.9-1.5L9.2 6.7V2.5M4.6 10.5h6.8"/>',
    "rocket": '<path d="M8 1.8c2.1 1.5 3.1 3.8 2.9 6.7L9.6 11H6.4L5.1 8.5C4.9 5.6 5.9 3.3 8 1.8zM5.1 8.5l-1.6 2.2.4 2 2.5-1.7M10.9 8.5l1.6 2.2-.4 2-2.5-1.7M7 13.4l1 1.3 1-1.3"/>'
              '<circle cx="8" cy="6.3" r="1.1"/>',
    "book": '<path d="M8 4.5C6.8 3.6 5 3.2 2.5 3.3v9.2c2.5-.1 4.3.3 5.5 1.2 1.2-.9 3-1.3 5.5-1.2V3.3C11 3.2 9.2 3.6 8 4.5zM8 4.5v9.2"/>',
    "globe": '<circle cx="8" cy="8" r="5.5"/><path d="M2.5 8h11M8 2.5C6.4 4.1 5.6 5.9 5.6 8s.8 3.9 2.4 5.5c1.6-1.6 2.4-3.4 2.4-5.5S9.6 4.1 8 2.5z"/>',
    "heart": '<path d="M8 13.5S2.5 10.2 2.5 6.3c0-1.7 1.3-3 2.9-3 1.1 0 2 .6 2.6 1.5.6-.9 1.5-1.5 2.6-1.5 1.6 0 2.9 1.3 2.9 3 0 3.9-5.5 7.2-5.5 7.2z"/>',
    "star": '<path d="M8 2.3l1.75 3.6 3.95.55-2.86 2.78.68 3.94L8 11.3l-3.52 1.87.68-3.94L2.3 6.45l3.95-.55z"/>',
    "leaf": '<path d="M13.5 2.5C7 2.5 3 5.5 3 10c0 2.4 1.6 4 4 4 4.5 0 6.5-4.5 6.5-11.5zM2.5 13.5C5.5 10.5 8 8 11 5.5"/>',
    "wrench": '<path d="M10.6 2.6a3.2 3.2 0 0 0-3.9 4.2l-3.9 3.8a1.5 1.5 0 0 0 2.1 2.1l3.9-3.9a3.2 3.2 0 0 0 4.2-3.9l-1.9 1.9-1.6-.5-.5-1.6z"/>',
    "chart": '<path d="M2.5 2.5v11h11M5.5 11V8.5M8.5 11V5.5M11.5 11V7.5"/>',
    "shield": '<path d="M8 2l5 2v3.8c0 3-2.1 5.4-5 6.2-2.9-.8-5-3.2-5-6.2V4z"/>',
}


def zone_icon(name: str) -> str:
    """A zone's icon, drawn inline in its text's colour; "" for none."""
    body = ZONE_ICONS.get(name)
    if not body:
        return ""
    return ('<svg class="zi" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" '
            'stroke-linecap="round" stroke-linejoin="round">%s</svg>' % body)


def zone_styles(ws: Path) -> Dict[str, dict]:
    """Settings › Zones, as saved in the workspace's own settings file
    (prefs.FILE): per zone, {"color": one of cmux's names, "icon": one of
    ZONE_ICONS}. A colour is matched whatever its case; an unknown colour or
    icon is dropped, and a zone left with neither is left out, so it looks as
    it always has."""
    zones = prefs().read(ws).get("zones")
    if not isinstance(zones, dict):
        return {}
    named = {k.lower(): k for k in ZONE_COLOURS}
    out = {}
    for zone, given in zones.items():
        if not isinstance(given, dict):
            continue
        colour = named.get(given["color"].lower()) if isinstance(given.get("color"), str) else None
        icon = given.get("icon") if given.get("icon") in ZONE_ICONS else None
        style = {k: v for k, v in (("color", colour), ("icon", icon)) if v}
        if style:
            out[zone] = style
    return out


def zone_class(zone: str, styles: Dict[str, dict]) -> str:
    """The classes that put a zone's colour on a label's text, with a space in front; "" for none."""
    colour = styles.get(zone, {}).get("color")
    return " zc zc-%s" % colour.lower() if colour else ""


def zone_attr(zone: str, styles: Dict[str, dict]) -> str:
    """zone_class() as a class attribute, for a label with no class of its own; "" for none."""
    c = zone_class(zone, styles)
    return ' class="%s"' % c.strip() if c else ""


def zone_name(zone: str, styles: Dict[str, dict]) -> str:
    """A zone's name as a label shows it: its icon, if it has one, then the name."""
    return zone_icon(styles.get(zone, {}).get("icon", "")) + E(zone)


def zone_css() -> str:
    """Each colour's ink as a variable for each theme, set as the page sets its
    own, and the rule that puts it on a label. Two classes and the root, so a
    zone's colour holds over a button's own, selected or hovered."""
    light = ";".join("--zc-%s:%s" % (k.lower(), on) for k, (on, _) in ZONE_COLOURS.items())
    dark = ";".join("--zc-%s:%s" % (k.lower(), on) for k, (_, on) in ZONE_COLOURS.items())
    rules = "".join(":root .zc.zc-%s{color:var(--zc-%s)}" % (k.lower(), k.lower()) for k in ZONE_COLOURS)
    return ('\n:root{%s}\n@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){%s}}\n'
            ':root[data-theme="dark"]{%s}\n%s\n'
            '.zi{width:1.15em;height:1.15em;flex:none;vertical-align:-.2em;margin-right:.4em}.seg button .zi{margin-right:0}\n'
            '.gzw{position:relative;display:inline-flex;align-items:center}.gzw .gzi{position:absolute;left:9px;display:flex;pointer-events:none}\n'
            '.gzw .gzi .zi{margin:0}.gzw.hasi .gzsel{padding-left:27px}\n'
            '.zrow{display:flex;align-items:center;gap:8px;padding:3px 0}.zrow .zprev{flex:1;min-width:0;font-size:13px;font-weight:560;'
            'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\n'
            '.zpick{position:relative}.zbtn{display:inline-flex;align-items:center;gap:6px;min-width:112px;font:inherit;font-size:12px;'
            'color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:4px 9px;cursor:pointer}'
            '.zbtn .zi{margin:0}.zbtn:focus-visible,.zcell:focus-visible{outline:2px solid var(--accent,#2D6CDF);outline-offset:1px}\n'
            '.zsw{display:inline-block;width:14px;height:14px;border-radius:50%%;flex:none}'
            '.znone{display:inline-block;width:14px;height:14px;border-radius:50%%;border:1.5px dashed var(--muted);box-sizing:border-box;flex:none}\n'
            '.zpop{position:absolute;right:0;top:calc(100%% + 4px);z-index:5;display:grid;gap:4px;padding:8px;background:var(--surface);'
            'border:1px solid var(--line);border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18)}.zpop[hidden]{display:none}'
            '.zp-col{grid-template-columns:repeat(6,26px)}.zp-ico{grid-template-columns:repeat(5,30px)}\n'
            '.zcell{display:flex;align-items:center;justify-content:center;height:26px;padding:0;border:1px solid transparent;'
            'border-radius:7px;background:none;color:var(--ink);cursor:pointer}.zp-ico .zcell{height:30px}.zp-ico .zcell .zi{margin:0;width:16px;height:16px}'
            '.zcell:hover{background:var(--line)}.zcell.on{border-color:var(--ink)}\n' % (light, dark, dark, rules))


def zone_swatch(colour: Optional[str]) -> str:
    """A dot in a colour's ink for the theme in use; a dashed ring for none."""
    if colour not in ZONE_COLOURS:
        return '<i class="zsw znone"></i>'
    return '<i class="zsw" style="background:var(--zc-%s)"></i>' % colour.lower()


def zone_settings(zones: List[str], styles: Dict[str, dict]) -> str:
    """Settings › Zones: a row per zone, its name drawn as chosen, a colour
    and an icon. In the app only: what is chosen is saved for every viewer,
    and for the cmux desk, through page_action.py when Settings closes."""
    if not zones:
        return ""
    def options(none, names, chosen):
        return '<option value="">%s</option>' % none + "".join(
            '<option value="%s"%s>%s</option>' % (E(n), " selected" if n == chosen else "", E(n[:1].upper() + n[1:]))
            for n in names)
    def pick(kind, zone, chosen):
        # A button that shows the choice, over a palette that shows every one:
        # a select's list cannot draw a colour or an icon. The select stays,
        # hidden, as what the row reads and saves.
        if kind == "col":
            names, label = ZONE_COLOURS, "Colour"
            face = zone_swatch(chosen) + '<span>%s</span>' % (E(chosen) if chosen else "No colour")
            cells = '<button type="button" class="zcell" data-v="" title="No colour">%s</button>' % zone_swatch("") + "".join(
                '<button type="button" class="zcell" data-v="%s" title="%s">%s</button>' % (E(n), E(n), zone_swatch(n)) for n in names)
        else:
            names, label = ZONE_ICONS, "Icon"
            face = (zone_icon(chosen) or '<i class="znone"></i>') + '<span>%s</span>' % (E(chosen[:1].upper() + chosen[1:]) if chosen else "No icon")
            cells = '<button type="button" class="zcell" data-v="" title="No icon"><i class="znone"></i></button>' + "".join(
                '<button type="button" class="zcell" data-v="%s" title="%s">%s</button>' % (E(n), E(n[:1].upper() + n[1:]), zone_icon(n)) for n in names)
        return ('<span class="zpick"><select class="z%s" hidden aria-hidden="true" tabindex="-1">%s</select>'
                '<button type="button" class="zbtn" aria-haspopup="true" aria-expanded="false" aria-label="%s for %s">%s</button>'
                '<span class="zpop zp-%s" hidden role="group" aria-label="%s for %s">%s</span></span>'
                % (kind, options("No " + label.lower(), names, chosen), label, E(zone), face, kind, label, E(zone), cells))
    rows = "".join('<div class="zrow" data-zone="%s"><span class="zprev%s">%s</span>%s%s</div>'
                   % (E(z), zone_class(z, styles), zone_name(z, styles),
                      pick("col", z, styles.get(z, {}).get("color")), pick("ico", z, styles.get(z, {}).get("icon")))
                   for z in zones)
    return ('<section class="setsec apponly" id="zone-settings">%s%s%s<script type="application/json" id="zone-icons">%s</script></section>'
            % (set_head("Zones", "zones"), help_text("zones", 'A colour and an icon for each zone, '
               'shown wherever the page names it. With the cmux extra, a tab the desk opens takes its zone&#39;s colour too. '
               'Saved for every viewer when you close Settings, in <code>%s</code>, which is committed with your '
               'workspace.' % E(prefs().FILE)), rows, script_json({k: zone_icon(k) for k in ZONE_ICONS})))


_NL: Dict[Path, object] = {}


def notify_lib(ws: Path):
    """System/tools/notifications.py, which keeps Settings › Notifications:
    the workspace's own, else the one a step from this extra, else a Garrick
    clone's template, as prefs.py finds garrick_lib. None when there is none."""
    key = Path(ws)
    if key not in _NL:
        found = None
        for src in (key / "System" / "tools" / "notifications.py", Path(__file__).resolve().parent.parent / "tools" / "notifications.py",
                    Path(__file__).resolve().parent.parent.parent / "template" / "System" / "tools" / "notifications.py"):
            if not src.is_file():
                continue
            try:
                spec = importlib.util.spec_from_file_location("garrick_status_notifications", str(src))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                continue
            if callable(getattr(mod, "settings", None)) and hasattr(mod, "EVENTS"):
                found = mod
                break
        _NL[key] = found
    return _NL[key]


NOTIFY_TOKEN = "python3 System/tools/notifications.py telegram-token"
NOTIFY_CMUX_TEST = "python3 System/tools/notifications.py test cmux"
NOTIFY_QUIET = (("send", "Send"), ("hold", "Hold"), ("drop", "Drop"))


def notify_overrides(lib, sched: Optional[Dict[str, dict]]) -> Tuple[str, str]:
    """The line under the simple view about jobs whose launchd plist sets
    GARRICK_NOTIFY or GARRICK_NOTIFY_CMD, and its tooltip, which names them
    and the variable. ("", "") when no plist does."""
    forced = sorted((name, [k for k in lib.override(j.get("env") or {})]) for name, j in (sched or {}).items()
                    if lib.override(j.get("env") or {}))
    if not forced:
        return "", ""
    line = ("1 scheduled job sends its notices its own way and skips these settings." if len(forced) == 1 else
            "%d scheduled jobs send their notices their own way and skip these settings." % len(forced))
    tip = ("%s. Take it out of the job's launchd plist to use these settings."
           % "; ".join("%s sets %s in its launchd plist" % (n, " and ".join(vs)) for n, vs in forced))
    return line, tip


def notify_settings(ws: Path, zones: List[str], styles: Dict[str, dict], sched: Optional[Dict[str, dict]] = None,
                    desk: bool = False) -> str:
    """Settings › Notifications (#110). It opens on four plain choices, the
    simple view: where to send (this Mac, Telegram, with Set up… for the
    bot), which of four events to be told about, and quiet hours. Under More
    options, closed until opened, is everything else: the channels, each
    tested from here, with a command of your own; which events go to which,
    and what each does in quiet hours; and which channels each zone's
    notices may use, with a Telegram chat of its own. The simple view drives
    the form under More options (NOTIFY_JS), whose request is what is saved,
    as notifications.py's from_simple() says; settings it cannot say
    (notifications.py's is_simple()) are custom, kept as they are until "Use
    the simple choices". In the app only: what is chosen goes to
    page_action.py when Settings closes, or when a test is sent or the bot
    set up, which save first. `desk` says the cmux extra is here, which
    brings the cmux channel, the Desk event and "only when away". Jobs whose
    plist sets GARRICK_NOTIFY or GARRICK_NOTIFY_CMD are counted, since those
    override what is chosen here, and named in the line's tooltip. The
    Telegram token never reaches the page: only whether one was stored."""
    lib = notify_lib(ws)
    if lib is None:
        return ""
    cfg = lib.settings(ws)
    ch = cfg["channels"]
    def box(attr, on, label="", extra=""):
        return '<input type="checkbox" %s%s%s%s>' % (attr, " checked" if on else "", ' aria-label="%s"' % E(label) if label else "", extra)
    def row(key, title, about, button):
        return ('<div class="launcher-row nch"><label class="launcher-choice">%s <span>%s<small>%s</small></span></label>%s</div>'
                % (box('data-nch="%s"' % key, ch.get(key)), E(title), about, button))
    def test(key, label):
        return '<button class="act" type="button" data-ntest="%s" title="Saves these settings, then sends a test">Send a test</button>' % key
    stored = lib.token_stored(ws)
    chat = cfg["telegram"]["chat"]
    rows = row("mac", "This Mac", "A notification in the corner of the screen", test("mac", "This Mac"))
    if desk:
        rows += row("cmux", "cmux", "A session in cmux gets its notice on its own tab, in place of the Mac&#39;s",
                    '<button class="act" type="button" data-copy="%s" data-say="Copied. Run it in a cmux tab: the test lands '
                    'on that tab.">Copy a test</button>' % E(NOTIFY_CMUX_TEST))
    rows += row("telegram", "Telegram", "A message from your own bot, on your phone", test("telegram", "Telegram"))
    rows += ('<div class="nfield"><input type="text" id="n-chat" value="%s" placeholder="Chat ID, such as 123456789" '
             'aria-label="Telegram chat ID" autocomplete="off" spellcheck="false"><span class="hint ntok">%s</span>'
             '<button class="act" type="button" data-copy="%s" data-say="Copied. Run it in a terminal and paste the token '
             'there, where it is not shown.">Copy the token command</button></div>'
             % (E(chat), "Token kept in this Mac&#39;s keychain since %s" % E(stored) if stored
                else "No token on this Mac yet", E(NOTIFY_TOKEN)))
    rows += row("command", "A command of your own", "Run with the title and the message, as GARRICK_NOTIFY_CMD is",
                test("command", "Your command"))
    rows += ('<div class="nfield"><input type="text" id="n-cmd" value="%s" placeholder="/bin/sh /Users/you/notify.sh" '
             'aria-label="The command to run" autocomplete="off" spellcheck="false"></div>' % E(cfg["command"]))
    quiet = lambda name, chosen: ('<select data-nq aria-label="%s in quiet hours">%s</select>' % (E(name), "".join(
        '<option value="%s"%s>%s</option>' % (v, " selected" if v == chosen else "", label) for v, label in NOTIFY_QUIET)))
    events = ""
    for key, label, about in lib.EVENTS:
        if key == "desk" and not desk:
            continue
        e = cfg["events"][key]
        extra = ""
        if key == "finished":
            extra += ('<span class="nafter">after <input type="number" data-nafter min="0" max="%d" value="%d" '
                      'aria-label="Minutes a turn must run"> min or more</span>' % (lib.AFTER_MAX, e["after"]))
        if key in lib.SESSION_EVENTS and desk:
            extra += ('<label class="naway" title="In cmux, nothing while you are looking at that tab">%s only when away</label>'
                      % box("data-naway", e["away"]))
        cells = "".join('<td%s>%s</td>' % ("" if ch.get(c) else ' class="noff"',
                                           box('data-nto="%s"' % c, c in e["to"], "%s to %s" % (label, lib.CHANNEL_LABELS[c])))
                        for c in lib.CHANNELS)
        events += ('<tr data-nev="%s"><th scope="row">%s<small>%s</small>%s</th>%s<td>%s</td></tr>'
                   % (key, E(label), E(about), extra, cells, quiet(label, e["quiet"])))
    q = cfg["quiet"]
    # A zone's box for a channel switched off is hidden, not greyed: ticked and
    # greyed read as broken. Its value stays, for when the channel comes on.
    zrows = ""
    for z in zones:
        zc = cfg["zones"].get(z, {})
        allowed = zc.get("to", list(lib.CHANNELS))
        zrows += ('<div class="nzone" data-zone="%s"><span class="zprev%s">%s</span><span class="nzto">%s</span>'
                  '<input type="text" data-nzchat value="%s" placeholder="Telegram chat ID" aria-label="%s&#39;s own Telegram chat" '
                  'autocomplete="off" spellcheck="false"%s></div>'
                  % (E(z), zone_class(z, styles), zone_name(z, styles), "".join(
                      '<label%s>%s %s</label>' % ("" if ch.get(c) else " hidden",
                                                  box('data-nzto="%s"' % c, c in allowed, "%s to %s" % (z, lib.CHANNEL_LABELS[c])),
                                                  {"mac": "Mac", "telegram": "Telegram", "command": "Command"}[c])
                      for c in lib.CHANNELS), E(zc.get("chat", "")), E(z), "" if ch.get("telegram") else " hidden"))
    more = ('<details class="nmore" id="notify-more"><summary>More options</summary><div class="nchans">%s</div>'
            '<table class="nev"><thead><tr><th scope="col">Event</th><th scope="col">Mac</th><th scope="col">Telegram</th>'
            '<th scope="col">Command</th><th scope="col">In quiet hours</th></tr></thead><tbody>%s</tbody></table>%s</details>'
            % (rows, events, ('<h4 class="nsub">Zones</h4><p class="hint nzhelp">Send a zone&#39;s notices to a chat of its own, '
                              'or keep a zone off some channels.</p>%s' % zrows) if zrows else ""))
    line, tip = notify_overrides(lib, sched)
    help_html = ('Choose where notices go and which ones you get. A notice names the zone or thread and what happened, never what '
                 'a note or a meeting says, since a phone shows it on a locked screen. &#8220;A session needs me&#8221; and &#8220;a '
                 'long task finishes&#8221; need hooks in Claude Code or Codex: ask your assistant to set up notifications. More '
                 'options sets each event, channel and zone on its own, and adds a command of your own. In quiet hours a long task '
                 'that finishes is not reported at all, rather than held till morning. Saved in <code>%s</code> when '
                 'you close Settings; a Telegram bot&#39;s token is kept in this Mac&#39;s keychain, never there.' % E(prefs().FILE))
    if line:
        help_html += (' A scheduled job whose launchd plist sets GARRICK_NOTIFY or GARRICK_NOTIFY_CMD sends its notices its own '
                      'way; take the variable out of the plist to use these settings.')
    simple = notify_simple(lib, cfg, desk, bool(stored), line, tip) if callable(getattr(lib, "from_simple", None)) else ""
    if not simple:          # a workspace whose notifications.py predates the simple view: More options is all there is
        more = more.replace('<details class="nmore" id="notify-more">', '<details class="nmore" id="notify-more" open>', 1)
        more += ('<div class="launcher-row"><label class="launcher-choice">%s <span>Quiet hours<small>What each event does then '
                 'is its last column</small></span></label><span class="nquiet"><input type="time" id="n-from" value="%s" '
                 'aria-label="Quiet from"> to <input type="time" id="n-to" value="%s" aria-label="Quiet until"></span></div>'
                 % (box('id="n-quiet"', q["on"]), E(q["from"]), E(q["to"])))
        if line:
            more += '<p class="hint nover" title="%s">%s</p>' % (E(tip), E(line))
    return ('<section class="setsec apponly" id="notify-settings"%s>%s%s%s%s<p class="hint" id="n-said" role="status" hidden></p>'
            '</section>'
            % (notify_data(lib, cfg, desk) if simple else "", set_head("Notifications", "notify"), help_text("notify", help_html),
               simple, more))


def notify_data(lib, cfg: dict, desk: bool) -> str:
    """What the page's script needs to mirror notifications.py's simple
    mapping, as the section's attributes: the events the simple view sets,
    each event's quiet-hours choice there, and whether the settings are
    custom now, as is_simple() says."""
    data = {"tell": [e for e, _ in lib.SIMPLE_EVENTS], "follow": list(lib.SIMPLE_FOLLOW), "channels": list(lib.CHANNELS),
            "send": list(lib.SEND_TO), "quiet": {k: v["quiet"] for k, v in lib.DEFAULT_EVENTS.items()}}
    return ' data-simple="%s" data-custom="%d"' % (E(json.dumps(data, separators=(",", ":"))), 0 if lib.is_simple(cfg, desk) else 1)


def notify_simple(lib, cfg: dict, desk: bool, stored: bool, line: str, tip: str) -> str:
    """The simple view: Send to, with Telegram's Set up…; Tell me when;
    quiet hours, with what they do in one sentence; the custom line; and
    the count of jobs that send their own way."""
    choices = lib.simple_choices(cfg)
    chat = cfg["telegram"]["chat"]
    ready = bool(chat and stored)
    def box(attr, on, label=""):
        return '<input type="checkbox" %s%s%s>' % (attr, " checked" if on else "", ' aria-label="%s"' % E(label) if label else "")
    state = ('<span class="ntgok">Set up</span><button type="button" class="nlink" data-ntgopen aria-expanded="false" '
             'aria-controls="n-tgset">Change</button>' if ready else
             '<button type="button" class="act" data-ntgopen aria-expanded="false" aria-controls="n-tgset">Set up&#8230;</button>')
    send = ('<div class="nsrow"><span class="nslab">Send to</span><span class="nsopts"><label>%s This Mac</label>'
            '<label>%s My phone (Telegram)</label><span class="ntgstate">%s</span></span></div>'
            % (box('data-ns="mac"', choices["send"]["mac"]), box('data-ns="telegram"', choices["send"]["telegram"]), state))
    setup = ('<div class="ntgset" id="n-tgset" hidden><ol>'
             '<li><span>In Telegram, message @BotFather, send /newbot, and paste the token it gives you.</span>'
             '<span class="nfield"><input type="password" id="n-token" autocomplete="off" spellcheck="false" '
             'aria-label="The bot&#39;s token" placeholder="123456789:AA&#8230;"><button class="act" type="button" data-ntok>Save'
             '</button></span>%s</li>'
             '<li><span>Now send your bot any message, then press Find my chat.</span><span class="nfield">'
             '<button class="act" type="button" data-nfind%s>Find my chat</button></span></li></ol></div>'
             % ('<small class="ntgsaved">A token is kept in this Mac&#39;s keychain; save another to replace it.</small>' if stored else "",
                "" if stored else ' disabled title="Save the token first"'))
    after = ('<input type="number" id="n-safter" min="0" max="%d" value="%d" aria-label="Minutes a task must run">'
             % (lib.AFTER_MAX, choices["after"]))
    words = {"finished": 'a long task finishes, <span class="nsafter">after %s min</span>' % after}
    tell = "".join('<label>%s <span>%s</span></label>' % (box('data-nt="%s"' % e, choices["tell"][e], label if e == "finished" else ""),
                                              words.get(e, E(label)))
                   for e, label in lib.SIMPLE_EVENTS)
    q = choices["quiet"]
    rule = "At night only &#8220;a session needs me&#8221;%s get%s through; the rest waits until morning." % (
        (" and the desk", "") if desk else ("", "s"))
    quiet = ('<div class="nsrow nsq"><label>%s Quiet from</label><input type="time" id="n-from" value="%s" aria-label="Quiet from">'
             '<span>to</span><input type="time" id="n-to" value="%s" aria-label="Quiet until"></div><p class="hint nsrule">%s</p>'
             % (box('id="n-quiet"', q["on"]), E(q["from"]), E(q["to"]), rule))
    custom = lib.is_simple(cfg, desk) is False
    note = ('<p class="ncustom" id="n-custom"%s><span>Your choices are custom, under More options.</span>'
            '<button class="act" type="button" id="n-usesimple">Use the simple choices</button></p>' % ("" if custom else " hidden"))
    over = '<p class="hint nover" title="%s">%s</p>' % (E(tip), E(line)) if line else ""
    return ('<div class="nsimple">%s%s<div class="nsrow"><span class="nslab">Tell me when</span><span class="nsopts nscol">%s'
            '</span></div>%s%s%s</div>' % (send, setup, tell, quiet, note, over))


def script_json(data) -> str:
    """JSON safe inside a <script> element: with <, > and & written as escapes,
    no title can close the element or open a comment in it."""
    return (json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def rebuild_command(ws: Path, vault: Optional[str] = None, show_graph: bool = True, out: Optional[Path] = None,
                    flags: Tuple[str, ...] = ()) -> str:
    """The command that builds this page again, with the flags it was built
    with, absolute and quoted so it runs from any folder."""
    words = ["python3", str(Path(__file__).resolve()), "--workspace", str(ws)]
    if vault:
        words += ["--obsidian", vault]
    words += list(flags)
    if not show_graph:
        words.append("--no-graph")
    if out is not None:
        words += ["--out", str(out)]
    return " ".join(shlex.quote(w) for w in words + ["--open"])


# Garrick's mark: a cabinet of three compartments behind walls, a narrow spine
# on the left, the open one in blue and a closed one beneath. The blue is one
# colour tuned for each ground: BRAND on light, the lighter BRAND_ON_DARK on
# dark, where BRAND falls to 3.4 to 1. The small cut, for 32 pixels and below,
# is drawn on the 16-pixel grid so its walls stay a pixel wide in the tab.
BRAND = "#3D73E0"
BRAND_ON_DARK = "#8EB1F5"
MARK_INK = "#1E2833"
MARK_INK_ON_DARK = "#F5F0E6"
_MARK = {
    True: ("M22.75 6V58H8.5C7.12 58 6 56.88 6 55.5V8.5C6 7.12 7.12 6 8.5 6ZM26.75 32H58V55.5C58 56.88 56.88 58 55.5 58H26.75Z",
           "M26.75 6H55.5C56.88 6 58 7.12 58 8.5V28H26.75Z"),
    False: ("M24 4V60H6C4.9 60 4 59.1 4 58V6C4 4.9 4.9 4 6 4ZM28 32H60V58C60 59.1 59.1 60 58 60H28Z",
            "M28 4H58C59.1 4 60 4.9 60 6V28H28Z"),
}


def mark(full: bool = True, attrs: str = "", image: bool = False) -> str:
    """The mark as SVG: the full one, or the small cut. Inside the page its
    colours follow the page's theme through CSS; an SVG used as an image needs
    its namespace and follows the browser's own light or dark setting."""
    ink, blue = _MARK[full]
    if image:
        style = ("<style>.mi{fill:%s}.mb{fill:%s}@media (prefers-color-scheme:dark){.mi{fill:%s}.mb{fill:%s}}</style>"
                 % (MARK_INK, BRAND, MARK_INK_ON_DARK, BRAND_ON_DARK))
        return ('<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">%s<path class="mi" d="%s"/><path class="mb" d="%s"/></svg>'
                % (style, ink, blue))
    return ('<svg viewBox="0 0 64 64"%s><path class="mi" fill="%s" d="%s"/><path class="mb" fill="%s" d="%s"/></svg>'
            % (attrs, MARK_INK, ink, BRAND, blue))


def app_icon() -> str:
    """The Mac app's icon at 1024 pixels: the mark in its dark colours on a navy
    tile, on the macOS icon grid (an 824-unit rounded square, centred), with
    the mark at three fifths of the tile. Plain fills, so any rasteriser draws it."""
    ink, blue = _MARK[True]
    k = 0.6 * 824 / 52
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">'
            '<rect x="100" y="100" width="824" height="824" rx="185.4" fill="%s"/>'
            '<g transform="translate(%.2f %.2f) scale(%.4f)"><path fill="%s" d="%s"/><path fill="%s" d="%s"/></g></svg>'
            % (MARK_INK, 512 - 32 * k, 512 - 32 * k, k, MARK_INK_ON_DARK, ink, BRAND_ON_DARK, blue))


def favicon() -> str:
    """The tab icon, carried in the page as a data URI: nothing is fetched."""
    return '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%s">' % urllib.parse.quote(mark(full=False, image=True), safe="")


GRIP = ('<svg viewBox="0 0 16 16" aria-hidden="true"><g fill="currentColor"><circle cx="6" cy="4" r="1.2"/><circle cx="10" cy="4" r="1.2"/>'
        '<circle cx="6" cy="8" r="1.2"/><circle cx="10" cy="8" r="1.2"/><circle cx="6" cy="12" r="1.2"/><circle cx="10" cy="12" r="1.2"/></g></svg>')
CLOSE = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'


MOVE = ('<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 5.5h9.5M10 3l2.5 2.5L10 8M13 10.5H3.5M6 8l-2.5 2.5L6 13" fill="none" '
        'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def card(id_: str, title: str, meta: str, body: str, open_: bool = True, fixed: bool = False) -> str:
    """A folding card. Unless fixed, its header has a grip to drag it elsewhere
    and a button to hide it; the browser remembers both."""
    tools = "" if fixed else ('<span class="tools"><span class="grip" draggable="true" title="Drag to move" aria-hidden="true">%s</span>'
                              '<button class="totab" type="button" title="Move to the other tab" aria-label="Move %s to the other tab">%s</button>'
                              '<button class="hide" type="button" title="Hide this card" aria-label="Hide %s">%s</button></span>'
                              % (GRIP, E(title), MOVE, E(title), CLOSE))
    return ('<details class="card" id="%s"%s><summary class="head">%s<h2>%s</h2><span class="meta">%s</span>%s</summary>'
            '<div class="body">%s</div></details>' % (id_, " open" if open_ else "", CHEV, E(title), E(meta), tools, body))


REPO_LIST_CAP = 30   # paths shown per kind; the count above stays exact


def repo_changes(ws: Path, r: dict) -> str:
    """One repository's changed files, by kind, to read and nothing more. No
    button commits them: another session may be halfway through that work."""
    where = "the workspace folder" if r["folder"] == ws else r["folder"].relative_to(ws).as_posix()
    groups = []
    for kind, label in CHANGE_KINDS:
        paths = [path for path, ks in r["changes"] if kind in ks]
        if not paths:
            continue
        more = len(paths) - REPO_LIST_CAP
        items = "".join("<li><code>%s</code></li>" % E(p) for p in paths[:REPO_LIST_CAP])
        items += '<li class="muted">and %d more</li>' % more if more > 0 else ""
        groups.append('<p class="hint">%s, %d</p><ul class="paths">%s</ul>' % (E(label[:1].upper() + label[1:]), len(paths), items))
    button = copy("Copy the folder's path", str(r["folder"]), "Copied the path of %s." % r["name"])
    return ('<details class="notes changes"><summary>%s: %s</summary><p class="hint">In %s. %s. '
            'Nothing here commits: review them in your git tool, or ask your assistant.</p>%s<div class="gacts">%s</div></details>'
            % (E(r["name"]), E(say_files(r["dirty"])), E(where), E(say_kinds(r["changes"])), "".join(groups), button))


def meter(value: float, cap: float, label: str, right: str) -> str:
    pct = 0 if not cap else min(100.0, value / cap * 100)
    kind = "critical" if pct >= 90 else "warning" if pct >= 70 else ""
    return ('<div class="m"><span class="ink2">%s</span><span class="num">%s</span><div class="meter %s"><i style="width:%.1f%%"></i></div></div>'
            % (E(label), E(right), kind, pct))


def cost_chart(L: dict) -> str:
    """The assistant's cost per day, one column per day of the last DAYS,
    against the costliest day; hover a column for its calls. Until three
    days have calls, a line says since when the ledger has been recording."""
    days = L["per_day"]
    if sum(1 for _, n, _ in days if n) < 3:
        since = "since %s" % L["began"].strftime("%d %b").lstrip("0") if L.get("began") else "from the first call"
        return ('<p class="hint" style="margin-top:14px">Recording %s. The cost per day shows once three days have calls.</p>' % E(since))
    top = max(c for _, _, c in days) or 1.0
    last = max(i for i, (_, n, _) in enumerate(days) if n)
    cols = "".join('<div data-tip="%s"><b style="height:%.1f%%"></b>%s</div>'
                   % (E("%s · %d call%s · $%.2f" % (d.strftime("%a %d %b"), n, "" if n == 1 else "s", c)), c / top * 100,
                      '<em>$%.2f</em>' % c if i == last else "") for i, (d, n, c) in enumerate(days))
    ticks = "".join("<span>%s</span>" % d.strftime("%d") for d, _, _ in days)
    return ('<div class="ink2" style="font-size:12px;margin:14px 0 0">Cost per day, last %d days</div>'
            '<div class="cols" role="img" aria-label="Cost per day, last %d days">%s</div><div class="ticks">%s</div>' % (DAYS, DAYS, cols, ticks))


# ------------------------------------------------- what you were doing, what you owe
# Overview opens on the Threads card (#143): each live thread by name or most
# recently touched first. Open actions and the inboxes sit beside it, and the
# graph keeps every mode it has behind Explore at the foot of the same tab.
#
# A row is the thread's name, its age bar, and at most two chips (#179):
# `todo N` for what is owed, green, or red once one of its open lines is late,
# and `check` for an error the page can explain and fix. Each opens a list
# under the row on a click: the open lines, late first, each with its box to
# tick as the Todo tab draws it; or the finding in plain words, with Fix where
# Nurture has a mechanical fix and the request to copy where it has not. A
# thread with nothing open shows nothing: its age bar says how long it has
# been quiet, and its next action is one click away rather than repeated
# under its name.
#
# Nothing here is coloured for age. The days since a note moved are a figure
# and nothing more; red belongs to the thread's own open actions and errors,
# which thread_actions() works out.


def day_said(when: dt.date, today: dt.date) -> str:
    """A date as the Todo tab says it: today, tomorrow, or Wed 18 Mar."""
    return "today" if when == today else "tomorrow" if (when - today).days == 1 else \
        "%s %d %s" % (when.strftime("%a"), when.day, when.strftime("%b"))


def late_said(a: dict, today: dt.date) -> str:
    """What makes a line late, and since when: a due date that has passed, or
    a `#waiting` line's chase date that has come."""
    return ("to chase since %s" if a["waiting"] else "was due %s") % day_said(a["when"], today)


def row_id(r: dict) -> str:
    """A row's own name for the lists its chips open, the same on every build,
    so a list left open stays open across the rebuild a tick brings."""
    return hashlib.sha1(("%s/%s" % (r["zone"], r["rel"])).encode("utf-8")).hexdigest()[:10]


def todo_chip(r: dict, today: dt.date) -> str:
    """`todo N`, for a thread with open actions: green when none is late, red
    when one is. Colour is not the only signal: the red chip's tooltip says
    which lines are late and since when."""
    mine = r.get("actions") or []
    if not mine:
        return ""
    late = [a for a in mine if a["late"]]
    n = len(mine)
    if late:
        tip = "%d of %d open action%s late: %s" % (len(late), n, "" if n == 1 else "s", "; ".join(
            "%s, %s" % (re.sub(r"[*_`\[\]]", "", a["text"])[:60], late_said(a, today)) for a in late[:3])) + \
            ("; and %d more" % (len(late) - 3) if len(late) > 3 else "")
    else:
        tip = "%d open action%s, none late" % (n, "" if n == 1 else "s")
    return ('<button type="button" class="chip tchip todo %s" aria-expanded="false" aria-controls="tp-%s" title="%s">todo %d</button>'
            % ("late" if late else "ok", row_id(r), E(tip + ". Click to list them"), n))


def todo_pop(r: dict, today: dt.date, actions: bool) -> str:
    """The list a `todo` chip opens: the thread's open lines, late first, each
    drawn by todo_row() as the Todo tab draws it, with its box and date in the
    app and the late ones saying since when. A tick here goes the Todo tab's
    way (TODO_JS), queued with the ticks around it (#107)."""
    mine = r.get("actions") or []
    if not mine:
        return ""
    late = sum(1 for a in mine if a["late"])
    head = "%d open%s" % (len(mine), " · %d late" % late if late else ", none late")
    return ('<div class="tpop" id="tp-%s" hidden><p class="tpop-h">%s</p><div class="trows">%s</div></div>'
            % (row_id(r), head, "".join(todo_row(dict(a, label=None, unsure=False), today, actions, said_late=True)
                                        for a in mine)))


def check_chip(r: dict) -> str:
    """`check`, for a thread with an error the page can explain and fix."""
    found = r.get("checks") or []
    if not found:
        return ""
    tip = "The check found an error here: %s%s Click for what fixes it" % (
        re.sub(r"`", "", found[0]["what"]), " And %d more." % (len(found) - 1) if len(found) > 1 else "")
    return ('<button type="button" class="chip tchip check late" aria-expanded="false" aria-controls="cp-%s" title="%s">check</button>'
            % (row_id(r), E(tip)))


def check_pop(r: dict, name: str) -> str:
    """What a `check` chip opens: each finding in plain words, the file it is
    in, and its fix. Where Nurture has a mechanical fix, a Fix button runs it
    (page_action.py's `fix`), shown in the app; otherwise, and in a browser,
    the request to copy for the assistant: `nurture <thread>`, or `wrap` or
    `finish` where that is what writes the missing block."""
    found = r.get("checks") or []
    if not found:
        return ""
    items = ""
    for x in found:
        zone, shown = re.match(r"Zones/([^/]+)/(.+)$", x["path"]), x.get("shown") or x["path"]
        phrase = "%s %s" % (x["say"], name)
        ask = copy("Copy “%s”" % phrase, phrase, "Copied “%s”. Paste it to your assistant." % phrase)
        if x.get("fixed_by") and zone and zone.group(1) == r["zone"]:
            fix, acts = x["fixed_by"], (
                '<button class="act primary tacts" type="button" data-act="%s" data-say="%s">Fix</button><span class="webonly">%s</span>'
                % (E(json.dumps({"verb": "fix", "zone": r["zone"], "file": zone.group(2)})), E("Fixing %s…" % shown), ask))
        else:
            fix, acts = x["fix"], ask
        items += ('<div class="cfind"><p><b>%s</b> %s</p><p class="cfix">%s</p><div class="hacts">%s</div></div>'
                  % (E(shown), md_inline(x["what"]), md_inline(fix), acts))
    return '<div class="tpop" id="cp-%s" hidden>%s</div>' % (row_id(r), items)


def start_card() -> str:
    """A workspace with no projects: the one request that makes the first one,
    and where the route is written. The route is the meetings skill's, and is
    not repeated here."""
    ask = "help me prepare my next supplier call"
    return card("start", "Start here", "nothing is set up yet, and nothing needs to be",
                '<p>Ask your assistant for the thing you actually need, in your own words. There is no tag, zone or '
                'thread to learn first.</p><p class="hsay">“%s”</p><div class="hacts">%s</div>'
                '<p class="hint">That one request is the route: your assistant follows <i>Nothing there yet: from an '
                'ordinary request to a saved brief</i> in <code>System/skills/meetings/SKILL.md</code>, which asks one '
                'question and leaves you a party, a project, its first thread and the brief in that thread note. It is '
                'written there, not here.</p>'
                % (E(ask), copy("Copy the request", ask, "Copied the request. Paste it to your assistant.")))


HOME_CSS = r"""
.chip.late{color:var(--critical);border-color:color-mix(in srgb,var(--critical) 45%,transparent)}
.hacts{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
.hsay{font-family:var(--display);font-size:17px;margin:12px 0}
.torder{margin-right:8px}
.hleft{margin:0 0 16px;padding:12px 14px;border-radius:10px;background:var(--surface);border:1px solid var(--accent)}
.hleft p{margin:0 0 8px}.hleft p.hint{margin:0}
.hleft pre{margin:0 0 10px;padding:8px 10px;max-height:200px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;font-size:13px;background:var(--raise);border:1px solid var(--line);border-radius:8px;user-select:text}
"""


# A thought, the card #102 added and #143 took away, kept what was typed into
# it in this browser's own storage. A browser that still holds some shows it
# once, in a message at the top of the Overview offering Copy, so nobody
# loses a note they left there. A successful Copy or Close removes it from
# the browser; until then it shows again on the next load.
THOUGHT_LEFT = ('<div class="hleft" id="thought-left" role="region" aria-label="A thought you left on this page" hidden>'
                '<p><b>A thought you left on this page.</b> The <i>A thought</i> card is gone. This is what you had typed '
                'into it, still kept in this browser only.</p><pre id="thought-text"></pre>'
                '<div class="hacts"><button class="act" type="button" id="thought-copy">Copy</button>'
                '<button class="act" type="button" id="thought-close">Close</button></div>'
                '<p class="hint">Paste it to your assistant and say where it belongs, or make it an action with '
                '<i>＋ Add</i> on the Todo tab. Once copied or closed, it is gone from this browser.</p></div>')

HOME_JS = r"""
(function(){var box=document.getElementById('thought-left');if(!box)return;
var KEY='garrick-thought',t=null;try{t=localStorage.getItem(KEY)}catch(e){}
function drop(){try{localStorage.removeItem(KEY)}catch(e){}}
if(t===null)return;if(!t.trim()){drop();return}
document.getElementById('thought-text').textContent=t;box.hidden=false;
var c=document.getElementById('thought-copy');
if(c)c.onclick=function(){var say=window.GarrickSay||function(){},done=function(){drop();say('Copied your thought. It is gone from this browser.')};
if(!window.GarrickCopy){say('Select the text and copy it by hand.');return}
var p=GarrickCopy(t);if(p&&p.then)p.then(done,function(){say('Could not copy. Select the text and copy it by hand.')});else done()};
var x=document.getElementById('thought-close');if(x)x.onclick=function(){drop();box.hidden=true}})();
"""


# --------------------------------------------------------------------------- the simple home (#175)
#
# For someone who does not think in zones, projects and threads: three things
# on one page, and everything else under More. **Your work**, the pieces of
# work, most recent first, each with its next action, when it last moved and
# what is owed to other people, with Continue where the next step is the
# user's and "Waiting on <who>" where it is not; **Ask something**, one box
# that opens Claude on the whole workspace; and **Needs you**, the questions
# Garrick asked and is waiting on, each answered in one click. A piece of
# work's name opens its page. "Work" is the only unit shown: a project that is
# one thread is one piece of work, and a project with several shows one per
# live thread, as "Project, Thread".
#
# Unlike the full page, the simple home shows some of a note's words: the
# Resume here block's Where it stands, Next action and Waiting on, the newest
# dated entry, and the note's opening sentence, since a piece of work is
# nothing without them. The page stays in System/generated/, never committed
# and outside the wall check, as it always was. A new workspace opens on it
# ("home": "simple" in System/garrick-settings.json, which install.py writes);
# a workspace without that key keeps the page it had, and Settings › Home
# switches either way.

HOMES = ("simple", "full")
# The example's manifest in its zone, as garrick_lib.EXAMPLE_MANIFEST names it:
# a zone is the example only with one that names it, as System/tools/example.py
# reads it (present()), never by its name alone.
EXAMPLE_MANIFEST = ".example.json"
VISIBLE_WORK = 5
QUESTIONS = "Needs you"
NOBODY = {"", "nobody", "no one", "noone", "none", "nothing", "-", "—", "n/a", "no"}
OPTION_LINE = re.compile(r"^\s*-\s+\[(?![ xX]\])([^\]]+)\]\s+(\S.*?)\s*$")
FILES_SHOWN = 12
_HO = None


def handoff_mod():
    """handoff.py, beside this file: the record Continue keeps, and whether
    the desktop app can open work on this Mac."""
    global _HO
    if _HO is None:
        spec = importlib.util.spec_from_file_location("garrick_status_handoff", str(Path(__file__).with_name("handoff.py")))
        _HO = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_HO)
    return _HO


_YW = None


def your_work_mod():
    """your_work.py, beside this file: what the home and page_action.py share
    about the user's own work, a folder read and never written (#182)."""
    global _YW
    if _YW is None:
        spec = importlib.util.spec_from_file_location("garrick_status_your_work", str(Path(__file__).with_name("your_work.py")))
        _YW = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_YW)
    return _YW


def home_layout(ws: Path) -> str:
    """"simple" where System/garrick-settings.json says `"home": "simple"`,
    otherwise "full": a workspace that never chose keeps the page it had."""
    try:
        data = json.loads(ws.joinpath("System", "garrick-settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "full"
    return "simple" if isinstance(data, dict) and data.get("home") == "simple" else "full"


# A Resume block's Next action ends with whose it is ("…; Robin's", "…; the
# assistant's"), which the home has no use for: every row there is the user's.
OWNER_TAIL = re.compile(r"[;,]\s*(?:the\s+)?[A-Z]?[\w.-]+(?:\s+[\w.-]+){0,2}[\u2019']s\s*\.?\s*$")


def without_owner(text: Optional[str]) -> Optional[str]:
    """A next action without the whose-it-is tail the Resume block adds."""
    if not text:
        return text
    return OWNER_TAIL.sub("", text).rstrip() or text


def waiting_on(text: str) -> Optional[str]:
    """Who a piece of work waits on, from its Waiting on row: None where the
    row says nobody, is empty, or is still the template's placeholder."""
    said = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", filled(text)).strip().rstrip(".")
    if said.casefold() in NOBODY or re.match(r"(?i)^(nobody|no one|none)\b", said):
        return None
    return said


def ago(day: Optional[dt.date], today: dt.date) -> str:
    """When something last moved, as said aloud: Today, Yesterday, 3 days ago, Last week."""
    if day is None:
        return "No date"
    n = (today - day).days
    if n <= 0:
        return "Today"
    if n == 1:
        return "Yesterday"
    if n < 7:
        return "%d days ago" % n
    if n < 14:
        return "Last week"
    if n < 60:
        return "%d weeks ago" % (n // 7)
    return "On %d %s %d" % (day.day, MONTH_NAMES[day.month - 1], day.year)


def due_said(day: dt.date, today: dt.date) -> str:
    """A due date the way a person says it: today, tomorrow, Thursday, 14 November."""
    n = (day - today).days
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if 1 < n < 7:
        return day.strftime("%A")
    return "%d %s" % (day.day, MONTH_NAMES[day.month - 1])


def owed_said(owed: List[dict], today: dt.date) -> str:
    """What a piece of work owes other people, from its Todo.md lines: "2 owed,
    1 due Thursday", "1 owed, due Friday", "3 owed, 1 overdue". Each unticked
    line is one owed; a 📅 date makes it due."""
    if not owed:
        return ""
    late = [a for a in owed if a["when"] and a["when"] < today]
    due = sorted(a["when"] for a in owed if a["when"] and a["when"] >= today)
    said = "%d owed" % len(owed)
    if late:
        return said + (", overdue" if len(owed) == 1 else ", %d overdue" % len(late))
    if due:
        first = [d for d in due if d == due[0]]
        return said + (", due %s" % due_said(due[0], today) if len(owed) == 1
                       else ", %d due %s" % (len(first), due_said(due[0], today)))
    return said


def questions_in(folder: Path, zone: Path, today: dt.date) -> List[dict]:
    """The Needs you questions in a piece of work's folder, oldest first: the
    open ones, and the ones put off whose day has come, each with `shown`;
    one put off to a later day is listed with `shown` False, for the count.
    Answered ones are left out."""
    out = []
    box = folder / QUESTIONS
    if not box.is_dir():
        return out
    for f in sorted(box.glob("*.md")):
        if f.name.startswith((".", "_")):
            continue
        fm = frontmatter(f)
        state = as_text(fm.get("status")).strip().lower() or "open"
        if state not in ("open", "later"):
            continue
        later = as_date(fm.get("later"))
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)
        ask, context, opts = "", [], []
        for line in body.splitlines():
            m = OPTION_LINE.match(line)
            if m:
                opts.append((m.group(1).strip(), m.group(2).strip()))
            elif not ask and re.match(r"^\s*\*\*.+\*\*\s*$", line):
                ask = line.strip().strip("*").strip()
            elif ask and line.strip() and not opts and not line.startswith("#"):
                context.append(line.strip())
        if not ask:
            continue
        out.append({"file": f.relative_to(zone).as_posix(), "zone": zone.name, "ask": ask, "context": " ".join(context),
                    "options": opts, "own": as_text(fm.get("own")).strip(), "asked": as_date(fm.get("asked")), "later": later,
                    "shown": state == "open" or (later is not None and later <= today)})
    return out


def party_names(ctx: dict, tags_: List[str]) -> List[str]:
    """Who is involved, from System/context.md: each party by its name, then
    the people listed for it, with their role."""
    out = []
    parties = ctx.get("parties") or {}
    for t in tags_:
        p = parties.get(t.lower())
        name = (p or {}).get("party") or ""
        people = ["%s (%s)" % (x["name"], x["role"]) if x.get("role") else x["name"]
                  for x in ctx.get("people") or [] if (x.get("party") or "").lower() == t.lower() and x.get("name")]
        if name and t.lower() != "personal":
            out.append(name + (": " + ", ".join(people) if people else ""))
        elif people:
            out.append(", ".join(people))
    return out


def work_name_for(r: dict) -> str:
    """The name the home gives a thread: its project's where the project is
    one thread, "Project, Thread" where it has more. page_action.py's
    work_name() counts the same thread notes."""
    if r["note"] == r["hub"]:
        return r["project"]
    project = r["note"].parents[2]
    threads = [t for t in (project / "Threads").glob("*/*.md") if t.parent.name + ".md" == t.name]
    return r["project"] if len(threads) <= 1 else "%s, %s" % (r["project"], r["thread"])


def example_zone(ws: Path) -> Optional[str]:
    """The zone the worked example is in, or None: the first zone whose
    .example.json names it, read as System/tools/example.py's present() does."""
    zones = ws / "Zones"
    for zone in sorted(zones.iterdir()) if zones.is_dir() else []:
        manifest = zone / EXAMPLE_MANIFEST
        if not (zone.is_dir() and manifest.is_file()):
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("zone") == zone.name:
            return zone.name
    return None


def works(ws: Path, T: Dict[str, dict], today: dt.date) -> List[dict]:
    """Every live piece of work, most recent first, as the home shows it.
    Read from what Garrick keeps already: the thread note's Resume here block
    (Next action, Waiting on), its `updated:` date and an unwrapped
    checkpoint's (`touched`), the zone's Todo.md lines that open with its
    link (thread_actions(), run first), and its Needs you questions."""
    ctx = workspace_context(ws)
    if not ctx:
        lib = prefs().lib(ws)
        try:
            ctx = lib.load_context(ws) if lib is not None and callable(getattr(lib, "load_context", None)) else {}
        except Exception:
            ctx = {}
    example = example_zone(ws)
    Y = your_work_mod()
    looks = Y.first_looks(ws)
    out = []
    for zone, data in T.items():
        zdir = data["folder"]
        for r in data["rows"]:
            read = r.get("read") or {}
            rows = read.get("rows") or {}
            hub_fm = frontmatter(r["hub"], ws) if r["hub"] else {}
            folder_said = as_text(hub_fm.get("folder")).strip()
            files = handoff_mod().resolve_folder(ws, folder_said) if folder_said else None
            nxt = filled(rows.get("Next action"))
            if not nxt and r.get("next"):
                nxt = r["next"]["text"]
            owed = [a for a in r.get("actions") or [] if a["file"] == "Todo.md" and not a["waiting"]]
            about = read.get("about") or ""
            if not about and r["hub"] and r["hub"] != r["note"]:
                about = resume_read(r["hub"])["about"]
            key = "%s/%s" % (zone, r["rel"])
            note_fm = hub_fm if r["note"] == r["hub"] else frontmatter(r["note"], ws)
            first_look = as_date(note_fm.get(Y.FIRST_LOOK))
            discovered = as_text(hub_fm.get(Y.DISCOVERED)).strip()
            look = looks.get(key) if isinstance(looks.get(key), dict) else None
            out.append({
                "id": Y.work_id(work_name_for(r), key),
                # From a folder of the user's (#182): made by a yes, read for the first time by Start with
                # this one, its first look and the request drawn from it, and whether it waits to be started.
                "discovered": discovered, "first_look": first_look, "look": look,
                "unstarted": bool(discovered) and files is not None and first_look is None and zone != example,
                "name": work_name_for(r), "zone": zone, "project": r["project"], "thread": r["thread"],
                "note": r["note"], "hub": r["hub"], "rel": r["rel"], "key": "%s/%s" % (zone, r["rel"]),
                "example": zone == example, "next": without_owner(nxt), "waiting": waiting_on(rows.get("Waiting on", "")),
                "deadline": filled(rows.get("Deadline")), "moved": r.get("touched") or r.get("updated"),
                "owed": owed, "about": about, "where": read.get("where") or "", "entry": read.get("entry"),
                "who": party_names(ctx, r["party"]), "files": files, "folder_said": folder_said,
                "files_dir": files or (r["hub"].parent if r["hub"] else
                                       r["note"].parents[2] if r["note"].parent.parent.name == "Threads" else r["note"].parent),
                "own_files": files is None, "questions": questions_in(r["note"].parent, zdir, today),
            })
    out.sort(key=lambda w: (-(w["moved"] or dt.date.min).toordinal(), w["name"].casefold()))
    return out


def example_state(ws: Path) -> Optional[str]:
    """"present" while the example's zone is there with its manifest;
    "archived" when System/tools/example.py (#174) says it is put away; None
    otherwise, and always where there is no such tool and no such zone. A zone
    of the user's that happens to be called Example is not the example."""
    if example_zone(ws):
        return "present"
    tool = ws / "System" / "tools" / "example.py"
    if not tool.is_file():
        return None
    try:
        r = subprocess.run([sys.executable, str(tool), "--root", str(ws), "--json", "status"], capture_output=True,
                           text=True, timeout=15, stdin=subprocess.DEVNULL, cwd=str(ws))
        state = json.loads(r.stdout).get("state") if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None
    return "archived" if state == "archived" else None


def act_button(req: str, label: str, say: str, cls: str = "act", extra: str = "") -> str:
    """A button that asks page_action.py for `req`, a request already in JSON."""
    return '<button class="%s" type="button" data-act="%s" data-say="%s"%s>%s</button>' % (cls, E(req), E(say), extra, E(label))


def continue_button(w: dict, label: str = "Continue", primary: bool = True) -> str:
    """Continue, or Continue in Claude: with a first look's suggested request
    waiting (#182), the request is what Claude is asked, once."""
    if suggested_ready(w):
        return act_button(json.dumps({"verb": "continue", "zone": w["zone"], "file": w["rel"], "suggested": True}), label,
                          "Opening %s in Claude, with your request…" % w["name"], "act go%s" % (" primary" if primary else ""),
                          ' data-phrase="%s"' % E(w["look"]["request"]))
    return act_button(json.dumps({"verb": "continue", "zone": w["zone"], "file": w["rel"]}), label,
                      "Opening %s in Claude…" % w["name"], "act go%s" % (" primary" if primary else ""),
                      ' data-phrase="%s"' % E("Where am I on %s?" % w["name"]))


def suggested_ready(w: dict) -> bool:
    """Whether a first look's suggested request waits to be asked: its
    question answered, and Continue not yet pressed on it."""
    look = w.get("look")
    if not look or look.get("used") or not look.get("request"):
        return False
    return look.get("question") not in [q["file"] for q in w["questions"]]


def start_button(w: dict, label: str = "Start with this one", primary: bool = False) -> str:
    """Start with this one (#182): the first time Garrick reads the work's files."""
    return act_button(json.dumps({"verb": "start", "zone": w["zone"], "file": w["rel"]}), label,
                      "Reading %s: Garrick reads its files now, and changes nothing in the folder. This takes a minute "
                      "or two…" % w["name"], "act go%s" % (" primary" if primary else ""))


def work_row(w: dict, today: dt.date) -> str:
    """One piece of work: its name, which opens its page; its next action; when
    it last moved and what it owes; Continue, or who it waits on."""
    shown = [q for q in w["questions"] if q["shown"]]
    nxt = md_inline(w["next"]) if w["next"] else '<span class="muted">No next step written yet</span>'
    if shown:
        nxt += ' <span class="muted">· waits on your answer above</span>'
    owed = owed_said(w["owed"], today)
    meta = E(ago(w["moved"], today)) + (' · <span class="sh-owed">%s</span>' % E(owed) if owed else "")
    side = ('<span class="sh-wait go">Waiting on %s</span>' % E(w["waiting"]) if w["waiting"] else continue_button(w))
    return ('<div class="sh-row" data-w="%s"><div class="sh-name"><button type="button" class="sh-link" data-w-open="%s">%s</button>%s</div>'
            '<div class="sh-next">%s</div><div class="sh-meta">%s</div>%s</div>'
            % (E(w["id"]), E(w["id"]), E(w["name"]), '<span class="sh-tag">Example</span>' if w["example"] else "",
               nxt, meta, side))


def question_card(q: dict, w: dict) -> str:
    """A question Garrick asked: what it asks, why, one button per answer, and Not now."""
    ask = q["ask"] if w["name"].casefold().split(",")[0] in q["ask"].casefold() else "%s: %s" % (w["name"], q["ask"])
    buttons = "".join(act_button(json.dumps({"verb": "answer", "zone": q["zone"], "file": q["file"], "label": label}),
                                 label, "Noting: %s…" % label, "act sh-opt", ' title="%s"' % E("Then: " + action))
                      for label, action in q["options"])
    if not q["options"]:
        buttons = continue_button(w, "Answer in Claude", primary=False)
    if q.get("own"):
        # An answer in the user's own words (#182): a box opens under the buttons, and its words are the answer.
        buttons += ('<button class="act sh-own" type="button" data-own="%s" data-zone="%s" data-file="%s">%s</button>'
                    % (E(q["own"]), E(q["zone"]), E(q["file"]), E(q["own"])))
        later = '<button class="act" type="button" data-w-open="%s">See where it stands</button>' % E(w["id"])
    else:
        later = act_button(json.dumps({"verb": "later", "zone": q["zone"], "file": q["file"]}), "Not now",
                           "Putting it off until tomorrow…", "act sh-later")
    return ('<div class="sh-q" data-q="%s"><b>%s</b>%s<div class="sh-opts">%s%s</div></div>'
            % (E(q["file"]), md_inline(ask), '<p>%s</p>' % md_inline(q["context"]) if q["context"] else "", buttons, later))


def home_section(W: List[dict], today: dt.date, example: Optional[str], local: Optional[str],
                 yours: Optional[dict] = None) -> str:
    """The home: Ask something, Needs you, the note when local sessions are
    off, the work from a folder of the user's waiting to be started and the
    suggestions waiting for an answer (#182), Your work with Add your own
    work, and the foot: the example's line, and the work put away."""
    yours = yours or {}
    shown = [(q, w) for w in W for q in w["questions"] if q["shown"]]
    shown.sort(key=lambda qw: (qw[0]["asked"] or dt.date.min, qw[0]["file"]))
    put_off = sum(1 for w in W for q in w["questions"] if not q["shown"])
    count = ("%d question%s" % (len(shown), "" if len(shown) == 1 else "s")) if shown else \
        ("%d put off" % put_off if put_off else "")
    needs = ("".join(question_card(q, w) for q, w in shown) if shown
             else '<div class="sh-empty">Nothing needs you.</div>')
    off = ('<div class="sh-card sh-warn" id="sh-off" role="status"><b>%s</b><p>%s</p></div>'
           % (E(handoff_mod().LOCAL_OFF_TITLE), E(handoff_mod().LOCAL_OFF))) if local else ""
    start = start_section([w for w in W if w["unstarted"]], any(w["discovered"] and w["first_look"] for w in W),
                          yours.get("confirmed") or {}, today)
    waiting = "".join('<div class="sh-card sh-waiting"><span>%s</span><button class="act" type="button" data-w-open="%s">'
                      'See them</button></div>' % (E(said), E(vid)) for vid, said in yours.get("waiting") or [])
    W = [w for w in W if not w["unstarted"]]
    rows = [work_row(w, today) for w in W]
    if rows:
        rest = W[VISIBLE_WORK:]
        more = ""
        if rest:
            names = ", ".join(w["name"] for w in rest[:3]) + (", …" if len(rest) > 3 else "")
            more = ('<details class="sh-more" id="sh-more"><summary>%d more: %s</summary>%s</details>'
                    % (len(rest), E(names), "".join(rows[VISIBLE_WORK:])))
        listing = '<div class="sh-card sh-list" id="sh-list">%s%s</div>' % ("".join(rows[:VISIBLE_WORK]), more)
    else:
        listing = ('<div class="sh-card sh-start" id="sh-start"><div class="sh-big">Start with your own work</div>'
                   '<p>Press <b>Add your own work</b> and pick the folder you work from: Garrick suggests the pieces of '
                   'work in it, and changes nothing there. Or say what you are working on in Ask something above, in '
                   'your own words. There is nothing to learn first.</p></div>')
    foot = ""
    if example == "present":
        foot = ('<div class="sh-foot"><span>Everything marked Example is made up, to show how Garrick works.</span>%s</div>'
                % act_button(json.dumps({"verb": "example", "do": "archive"}), "Remove the example",
                             "Putting the example away…", "sh-link",
                             ' data-confirm="Click again to remove the example"'))
    elif example == "archived":
        foot = ('<div class="sh-foot"><span>The example is archived. Nothing of yours was touched.</span>%s</div>'
                % act_button(json.dumps({"verb": "example", "do": "restore"}), "Bring the example back",
                             "Bringing the example back…", "sh-link"))
    for a in yours.get("away") or []:
        foot += ('<div class="sh-foot sh-away"><span>%s is put away. Its folder is as it was.</span>%s</div>'
                 % (E(a["project"]), act_button(json.dumps({"verb": "bring-back", "zone": a["zone"], "project": a["project"]}),
                                                "Bring it back", "Bringing %s back…" % a["project"], "sh-link")))
    add = ('<span class="sh-right"><button class="act" type="button" data-pick="folder" data-phrase="%s">Add your own work'
           '</button></span>' % E(ADD_PHRASE))
    return ('<form class="sh-ask" id="sh-ask" autocomplete="off"><input id="sh-askbox" name="q" placeholder="Ask something, or start new work" '
            'aria-label="Ask something"><button class="act primary" type="submit">Ask</button></form>'
            '<div class="sh-answer" id="sh-answer" role="status" hidden></div>'
            '<h2 class="sh-h">Needs you <small>%s</small></h2><div class="sh-card" id="sh-needs">%s</div>%s%s%s'
            '<h2 class="sh-h">Your work <small>most recent first</small>%s</h2>%s%s'
            % (E(count), needs, off, start, waiting, add, listing, foot))


# What a browser copies for Add your own work, since only the Mac app can open its folder picker.
ADD_PHRASE = "Look through the folder I keep my work in, and suggest the pieces of work in it. Change nothing there."


def start_section(waiting: List[dict], started: bool, confirmed: Dict[str, dict], today: dt.date) -> str:
    """The work a yes made from a folder of the user's, not read yet (#182):
    Start with one, before any is started, then Ready to start."""
    if not waiting:
        return ""
    rows = []
    for i, w in enumerate(waiting):
        p = confirmed.get(w["discovered"]) or {}
        meta = [where_said(p) if p else "Folder %s" % E(your_work_mod().said_folder(w["folder_said"].rstrip("/")))]
        if p.get("last"):
            meta.append("last activity %s" % ago(as_date(p["last"]), today).lower())
        if p.get("files"):
            meta.append("%d files" % p["files"])
        rows.append('<div class="sh-row" data-w="%s"><div class="sh-name"><button type="button" class="sh-link" data-w-open="%s">'
                    '%s</button>%s</div><div class="sh-meta">%s</div>%s</div>'
                    % (E(w["id"]), E(w["id"]), E(w["name"]), "" if started else '<span class="sh-tag sh-new">New</span>',
                       " · ".join(meta), start_button(w, "Start" if started else "Start with this one",
                                                      primary=not started and i == 0)))
    if started:
        return ('<h2 class="sh-h">Ready to start <small>not read yet</small></h2><div class="sh-card sh-list" id="sh-ready">%s</div>'
                % "".join(rows))
    return ('<h2 class="sh-h">Start with one</h2><div class="sh-card sh-list" id="sh-startone"><div class="sh-lead">You said yes to '
            '%d piece%s of work. Pick one to start: Garrick reads its files now and tells you where it stands. The others '
            'wait here until you are ready.</div>%s</div>' % (len(waiting), "" if len(waiting) == 1 else "s", "".join(rows)))


def where_said(p: dict) -> str:
    """Where a proposal's files are, as the page says it: a folder with the one it is in, or the word its files' names share."""
    if p.get("kind") == "names":
        return "Files whose names include “%s”" % E(p.get("name") or "")
    parts = [x for x in str(p.get("folder") or "").split("/") if x]
    if not parts:
        return "The folder itself"
    return "Folder %s, in %s" % (E(parts[-1]), E(parts[-2] if len(parts) > 1 else p.get("_picked") or "the folder you picked"))


def your_work_data(ws: Path) -> dict:
    """What the home needs from the folders looked through (#182): the
    proposals said yes to, by id; one line for each folder whose suggestions
    still wait, with its view's id; and the work put away."""
    Y = your_work_mod()
    confirmed, waiting = {}, []
    for real, entry in sorted(Y.discovery(ws)["folders"].items()):
        if not isinstance(entry, dict):
            continue
        for p in entry.get("confirmed") or []:
            if isinstance(p, dict) and p.get("id"):
                confirmed[p["id"]] = dict(p, _picked=entry.get("name") or "")
        n = len(entry.get("top") or []) + len(entry.get("more") or [])
        if n:
            waiting.append((Y.view_id(real), "%d suggestion%s from %s wait%s for your answer." % (
                n, "" if n == 1 else "s", entry.get("name") or os.path.basename(real), "s" if n == 1 else "")))
    return {"confirmed": confirmed, "waiting": waiting, "away": Y.put_away(ws)}


def discovery_pages(ws: Path, today: dt.date) -> str:
    """One page for each folder looked through whose suggestions still wait
    (#182): the pieces of work Garrick found, most recently active first,
    each with Yes, Rename and Not a piece of work; the rest under more; and
    what was left out, and why."""
    Y = your_work_mod()
    options = Y.places(ws, workspace_context(ws) or {})
    place = ""
    if len(options) > 1:
        place = ('<div class="sh-card sh-place"><label><b>Which part of your workspace is this work for?</b> '
                 '<select data-place><option value="">Choose…</option>%s</select></label></div>'
                 % "".join('<option value="%s">%s</option>' % (E(json.dumps(dict({"zone": o["zone"]},
                                                                                **({"party": o["party"]} if o["party"] else {})))),
                                                               E(o["label"])) for o in options))
    if any(o["party"] is None for o in options):
        # A zone with no party yet, as before any interview: whose work it is, asked here, in place (#182).
        place += ('<div class="sh-card sh-place sh-owner"%s><label><b>%s</b> <input data-owner data-needed="%s" '
                  'placeholder="%s" aria-label="%s"></label></div>'
                  % (" hidden" if len(options) > 1 else "", E(Y.OWNER), "1" if len(options) == 1 else "",
                     E(Y.OWNER_HINT), E(Y.OWNER)))
    out = []
    for real, entry in sorted(Y.discovery(ws)["folders"].items()):
        if not isinstance(entry, dict):
            continue
        top, more = entry.get("top") or [], entry.get("more") or []
        if not (top or more):
            continue
        name = entry.get("name") or os.path.basename(real)
        rows = [suggestion_row(dict(p, _picked=name), today) for p in top]
        # What was said yes to from this folder stays in the list, marked, under its own name: a rename shows.
        rows += [kept_row(dict(p, _picked=name)) for p in entry.get("confirmed") or [] if isinstance(p, dict)]
        rest = [suggestion_row(dict(p, _picked=name), today) for p in more]
        listing = "".join(rows) + ('<details class="sh-more"><summary>%d more, quieter lately</summary>%s</details>'
                                   % (len(rest), "".join(rest)) if rest else "")
        left = left_out_said(entry)
        flat = ('<div class="sh-card sh-flat"><b>%s is mostly loose files, not folders.</b> So Garrick grouped them by a '
                'word their names share. The groups are a guess: rename any that read wrong.</div>' % E(name)
                if entry.get("flat") else "")
        out.append('<article class="sh-work sh-disc" id="%s" hidden><button type="button" class="sh-link sh-back" data-home>‹ Home'
                   '</button><h1>Your work in %s</h1><div class="sh-sub">%s</div><div class="sh-assure">Garrick read only names '
                   'and dates, %d files, and changed nothing in %s.</div>%s%s<div class="sh-card sh-list">%s%s</div></article>'
                   % (E(Y.view_id(real)), E(name),
                      "Groups of files you worked on lately, most recent first. Say yes to the ones you want Garrick to "
                      "keep track of." if entry.get("flat") else "Pieces of work you were busy with lately, most recent "
                      "first. Say yes to the ones you want Garrick to keep track of.",
                      int(entry.get("files") or 0), E(name), flat, place, listing,
                      '<div class="sh-left">%s</div>' % E(left) if left else ""))
    return "".join(out)


def suggestion_row(p: dict, today: dt.date) -> str:
    """One proposal: its name, where its files are, when it last moved, and the three answers."""
    meta = "Last activity %s · %d files" % (ago(as_date(p.get("last")), today).lower(), int(p.get("files") or 0))
    latest = ""
    if p.get("kind") == "names" and p.get("latest"):
        latest = '<div class="sh-meta">Latest: %s</div>' % E("; ".join(p["latest"][:3]))
    yes = act_button(json.dumps({"verb": "suggestion", "id": p["id"], "answer": "yes"}), "Yes",
                     "Adding %s…" % p.get("name"), "act primary", ' data-sugg=""')
    no = act_button(json.dumps({"verb": "suggestion", "id": p["id"], "answer": "not"}), "Not a piece of work",
                    "Noting it…", "act", ' data-sugg=""')
    rename = ('<button class="act" type="button" data-rename="%s" data-name="%s">Rename</button>' % (E(p["id"]), E(p.get("name") or "")))
    return ('<div class="sh-row sh-prop" data-sugg-id="%s"><div class="sh-name">%s</div><div class="sh-next">%s</div>'
            '<div class="sh-meta">%s</div>%s<span class="go sh-ans">%s%s%s</span></div>'
            % (E(p["id"]), E(p.get("name") or ""), where_said(p), E(meta), latest, yes, rename, no))


def kept_row(p: dict) -> str:
    """A suggestion already said yes to: its name, as renamed, and that Garrick keeps track of it."""
    renamed = p.get("suggested") and p.get("suggested") != p.get("name")
    return ('<div class="sh-row sh-prop sh-kept"><div class="sh-name">%s</div><div class="sh-next">%s</div>'
            '<div class="sh-meta sh-said">✓ Garrick will keep track of this%s.</div></div>'
            % (E(p.get("name") or ""), where_said(p), ", renamed from %s" % E(p["suggested"]) if renamed else ""))


def left_out_said(entry: dict) -> str:
    """The line under the suggestions: what was left out, and why, three names at most for each reason."""
    by: Dict[str, List[str]] = {}
    for l in entry.get("left_out") or []:
        if isinstance(l, dict) and l.get("folder"):
            by.setdefault(str(l.get("said") or "left out"), []).append(str(l["folder"]).replace("/", " › "))
    for r in entry.get("routines") or []:
        if isinstance(r, dict) and r.get("label"):
            by.setdefault("a report made again and again", []).append(str(r["label"]))
    parts = ["%s (%s%s)" % (said, ", ".join(names[:3]), " and %d more" % (len(names) - 3) if len(names) > 3 else "")
             for said, names in by.items()]
    return ("Not suggested: " + "; ".join(parts) + ".") if parts else ""


def work_files(w: dict, kept: Optional[dict], today: dt.date) -> Tuple[str, str]:
    """A piece of work's files, (the summary for its heading, the list): what
    is new, changed or missing since it was last continued, from the files
    Continue kept; before its first Continue, what changed since the work last
    moved."""
    H = handoff_mod()
    now = H.walk(w["files_dir"], project=w["own_files"])
    since = None
    if kept and isinstance(kept.get("files"), dict):
        diff = H.compare(kept["files"], now)
        since = as_date(str(kept.get("seen") or "")[:10])
        said_since = "since you last continued it" + (" %s" % ago(since, today).lower() if since else "")
    else:
        moved = w["moved"]
        cut = time.mktime(moved.timetuple()) + 86400 if moved else None
        diff = {"new": sorted(p for p, (m, _) in now.items() if cut and m >= cut), "changed": [], "missing": []}
        said_since = "since it last moved" if moved else ""
    marks = {p: "new" for p in diff["new"]}
    marks.update({p: "changed" for p in diff["changed"]})
    ordered = sorted(now, key=lambda p: (p not in marks, -now[p][0], p.casefold()))
    items = "".join('<li>%s%s</li>' % (E(p), ' <span class="sh-tag">%s</span>' % marks[p] if p in marks else "")
                    for p in ordered[:FILES_SHOWN])
    items += "".join('<li class="sh-gone">%s <span class="sh-tag">missing</span></li>' % E(p) for p in diff["missing"][:FILES_SHOWN])
    if len(ordered) > FILES_SHOWN:
        items += '<li class="muted">%d more</li>' % (len(ordered) - FILES_SHOWN)
    parts = ["%d %s" % (len(diff[k]), k) for k in ("new", "changed", "missing") if diff[k]]
    head = ("%s %s" % (", ".join(parts), said_since)).strip() if parts else ("nothing new " + said_since).strip() if said_since else ""
    body = '<ul class="sh-files">%s</ul>' % items if items else '<p class="muted">No files yet.</p>'
    return head, body


def work_page(w: dict, today: dt.date, kept: Optional[dict]) -> str:
    """A piece of work's own page: what it is, who is involved, what happened
    last, what is open, the next step, Continue, and its files. One from a
    folder of the user's (#182) also says when its first look was made, to
    be checked; asks its next step there; offers the request drawn from it;
    says where its files live; and has Stop using this."""
    dl = []
    if w["about"]:
        dl.append(("What it is", md_inline(w["about"])))
    Y = your_work_mod()
    if w["discovered"]:
        # Work from a folder of the user's (#182): the people its files name, from its first look, never the party
        # the work was filed under, which may be only whose work it is.
        involved = re.search(r"\bInvolved: (.+?)\.(?=\s+Answered on |\s*$)", w["where"] or "")
        dl.append(("Who's involved", md_inline(involved.group(1)) if involved else
                   E("No one is named in its files yet.") if w["first_look"] else
                   E("Garrick has not read its files yet.")))
    elif w["who"]:
        dl.append(("Who's involved", E("; ".join(w["who"]))))
    entry = w["entry"]
    first = Y.FIRST_ENTRY_RE.match(entry[1]) if entry and entry[1] else None
    if first:
        # The newest dated entry is Garrick's own first look: what the page shows is the work's own last event.
        dl.append(("What happened last", md_inline(first.group(1))))
    elif entry and entry[1]:
        dl.append(("What happened last", ("%s: " % E(ago(entry[0], today)) if entry[0] else "") + md_inline(entry[1])))
    elif w["where"]:
        dl.append(("What happened last", md_inline(w["where"])))
    opened = []
    shown = [q for q in w["questions"] if q["shown"]]
    look_q = (w.get("look") or {}).get("question")
    if shown and not (len(shown) == 1 and shown[0]["file"] == look_q):
        opened.append("A question for you, on the home: %s" % E(shown[0]["ask"]))
    for a in w["owed"]:
        opened.append('<span class="sh-owed">Owed%s:</span> %s' % (" by %s" % E(due_said(a["when"], today)) if a["when"] else "",
                                                                    md_inline(a["text"])))
    if w["waiting"]:
        opened.append("Waiting on %s" % E(w["waiting"]) + (", %s" % md_inline(w["deadline"]) if w["deadline"] else ""))
    if opened:
        dl.append(("Open", "<br>".join(opened)))
    asking = [q for q in w["questions"] if q["file"] == look_q]
    if not asking:                              # an open first look's question says the next step itself, once
        dl.append(("Next", "<b>%s</b>" % md_inline(w["next"]) if w["next"] else '<span class="muted">No next step written yet</span>'))
    head, files = work_files(w, kept, today)
    # A folder is named with the one it is in, never as a path (#182).
    where = ("Folder: %s" % E(Y.said_folder(str(w["files"])))) if w["files"] is not None else "Kept with the work in Garrick"
    if w["folder_said"] and w["files"] is None:
        where = "Folder: %s, which is not there now" % E(Y.said_folder(w["folder_said"].rstrip("/")))
    first = ""
    if w["first_look"] and asking:
        first = ('<div class="sh-first"><i aria-hidden="true">✓</i> First look, made %s from the folder\'s files. Check it '
                 'before you rely on it.</div>' % E(ago(w["first_look"], today).lower()))
    if w["unstarted"]:
        acts = start_button(w, primary=True)
        dl = [("Not read yet", "Garrick has not opened these files. Start with this one reads them and tells you where "
               "the work stands; nothing in the folder is changed.")]
    else:
        acts = continue_button(w, "Continue in Claude", primary=not w["waiting"] and not asking)
    extra = ""
    if asking:
        extra += '<h2 class="sh-h">Needs you <small>1 question</small></h2><div class="sh-card">%s</div>' % question_card(asking[0], w)
    elif suggested_ready(w):
        extra += ('<h2 class="sh-h">Suggested request</h2><div class="sh-card sh-req">Garrick suggests starting here:'
                  '<blockquote>%s</blockquote>%s<div class="sh-what">Opens Claude\'s desktop app on %s, with this request '
                  'already asked. Claude can read the folder, and its editing tools are kept out of it in every mode. '
                  'A shell command is not covered, whether you approve it or Claude\'s Auto mode runs it.</div></div>'
                  % (E(w["look"]["request"]), continue_button(w, "Continue in Claude"), E(w["name"])))
        acts = ""
    foot = ""
    if w["files"] is not None and not w["example"]:
        foot = ('<div class="sh-foot"><span>Where these files live: left in place, in %s. Garrick only reads them.</span>%s</div>'
                % (E(Path(str(w["files"])).name), act_button(
                    json.dumps({"verb": "stop-using", "zone": w["zone"], "file": w["rel"]}), "Stop using this",
                    "Putting %s away…" % w["name"], "sh-link",
                    ' data-confirm="Click again: Garrick puts its record away, and the folder stays as it is"')))
    return ('<article class="sh-work" id="%s" hidden><button type="button" class="sh-link sh-back" data-home>‹ Home</button>'
            '<h1>%s%s</h1><div class="sh-sub">%s%s</div><div class="sh-card sh-ws">%s<dl>%s</dl><div class="sh-acts">%s</div></div>%s'
            '<h2 class="sh-h">Files <small>%s</small></h2><div class="sh-card sh-ws">%s</div>%s</article>'
            % (E(w["id"]), E(w["name"]), '<span class="sh-tag">Example</span>' if w["example"] else "", where,
               " · %s" % E(head) if head else "", first, "".join("<dt>%s</dt><dd>%s</dd>" % (E(k), v) for k, v in dl),
               acts, extra, E(head), files, foot))


def home_settings(layout: str) -> str:
    """Settings › Home: which page Garrick opens on."""
    def choice(value, label, small):
        return ('<div class="launcher-row"><label class="launcher-choice"><input type="radio" name="garrick-home" value="%s"%s> '
                '<span>%s<small>%s</small></span></label></div>' % (value, " checked" if layout == value else "", label, small))
    return ('<section class="setsec apponly" id="home-settings">%s%s%s%s</section>'
            % (set_head("Home", "home"), help_text("home", 'What Garrick opens on. <b>Simple</b> shows your work, Ask '
               'something and the questions waiting on you, with everything else under More. <b>Full</b> opens on the '
               'Overview, Todo and Status tabs. Kept in <code>System/garrick-settings.json</code> as <code>"home"</code>.'),
               choice("simple", "Simple", "Your work, Ask something and Needs you; the rest under More"),
               choice("full", "Full", "The Overview, Todo, Status and Guide tabs")))


SIMPLE_CSS = r"""
body.simple[data-tab=home] .bar .tabs,body.simple[data-tab=work] .bar .tabs{display:none}body.simple .bar .bacts{margin-left:auto}
body.simple[data-tab=home] #rebuild,body.simple[data-tab=work] #rebuild,body.simple[data-tab=home] .bar .seg.theme,body.simple[data-tab=work] .bar .seg.theme{display:none}
.sh-dot,.sh-morebtn{display:inline-flex;align-items:center;gap:6px;border:0;background:none;color:var(--ink2);font:inherit;font-size:13px;cursor:pointer;padding:4px 6px;border-radius:7px;white-space:nowrap}
.sh-dot:hover,.sh-morebtn:hover{color:var(--ink);background:var(--wash)}.sh-morebtn{color:var(--accent)}
body.simple:not([data-tab=home]):not([data-tab=work]) .sh-morebtn{display:none}
#tab-home,#tab-work{max-width:880px;margin:0 auto}
.sh-ask{display:flex;gap:8px;background:var(--raise);border:1px solid var(--line);border-radius:12px;padding:10px 12px;box-shadow:var(--shadow)}
.sh-ask input{flex:1;border:0;background:none;font:inherit;font-size:15px;color:var(--ink);outline:none;min-width:0}
.sh-ask .act,.sh-acts .act,.sh-row .act{font-size:13px;padding:7px 12px;border-radius:8px}
.sh-answer{margin:10px 0 0;padding:12px 14px;border-radius:12px;background:var(--surface);border:1px solid var(--line);white-space:pre-wrap;color:var(--ink2);position:relative}
.sh-answer b{display:block;color:var(--ink);margin-bottom:4px;white-space:normal}.sh-answer .wx{position:absolute;top:6px;right:8px;border:0;background:none;color:var(--muted);font-size:16px;cursor:pointer}
h2.sh-h{font-family:var(--display);font-weight:400;font-size:19px;margin:26px 0 10px;display:flex;align-items:baseline;gap:10px}
h2.sh-h small{font-family:system-ui,-apple-system,sans-serif;font-size:12px;color:var(--muted)}
.sh-card{background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
.sh-q{padding:14px 16px;border-left:3px solid var(--warning);border-top:1px solid var(--line)}.sh-q:first-child{border-top:0;border-radius:12px 12px 0 0}
.sh-q:only-child{border-radius:12px}.sh-q p{margin:4px 0 10px;color:var(--ink2)}.sh-opts{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.sh-opts .act{font-size:13px;padding:6px 12px;border-radius:8px}
.sh-empty{padding:14px 16px;color:var(--muted)}
.sh-warn{padding:14px 16px;border-left:3px solid var(--warning);margin-top:12px}.sh-warn p{margin:4px 0 0;color:var(--ink2)}
.sh-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 14px;padding:12px 16px;border-top:1px solid var(--line);align-items:center}
.sh-list>.sh-row:first-child{border-top:0}.sh-row>.go{grid-row:1/span 3;grid-column:2}
.sh-name{font-weight:600;min-width:0}.sh-next{color:var(--ink2);grid-column:1;min-width:0;overflow-wrap:anywhere}.sh-meta{grid-column:1;font-size:12px;color:var(--muted)}
.sh-link{color:var(--accent);cursor:pointer;background:none;border:0;font:inherit;padding:0;text-align:left}.sh-link:hover{text-decoration:underline;text-underline-offset:2px}
.sh-name .sh-link{color:var(--ink);font-weight:600}.sh-name .sh-link:hover{color:var(--accent)}
.sh-tag{display:inline-block;font-size:11px;font-weight:600;color:var(--accent);background:var(--wash);border-radius:4px;padding:0 6px;margin-left:6px;vertical-align:1px}
.sh-owed{color:color-mix(in srgb,var(--warning) 62%,var(--ink));font-weight:600}
.sh-wait{font-size:12px;color:var(--muted);border:1px dashed var(--line);border-radius:8px;padding:5px 10px;white-space:nowrap}
details.sh-more>summary{padding:10px 16px;border-top:1px solid var(--line);font-size:13px;color:var(--accent)}details.sh-more[open]>summary{color:var(--muted)}
.sh-foot{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-top:22px;font-size:13px;color:var(--muted)}
.sh-start{padding:26px 20px;text-align:center}.sh-start p{color:var(--ink2);max-width:440px;margin:6px auto 0}.sh-big{font-family:var(--display);font-size:20px}
.sh-work h1{font-family:var(--display);font-weight:400;font-size:26px;margin:10px 0 2px}.sh-sub{color:var(--muted);font-size:13px;margin-bottom:14px;overflow-wrap:anywhere}
.sh-ws{padding:14px 16px}.sh-ws dl{margin:0}.sh-ws dt{font-size:12px;color:var(--muted);margin-top:10px}.sh-ws dt:first-child{margin-top:0}.sh-ws dd{margin:2px 0 0;overflow-wrap:anywhere}
.sh-acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.sh-files{margin:0;padding:0;list-style:none;font-size:13px;color:var(--ink2)}.sh-files li{padding:3px 0;overflow-wrap:anywhere}.sh-gone{text-decoration:line-through;color:var(--muted)}
.sh-right{margin-left:auto;font-family:system-ui,-apple-system,sans-serif}.sh-right .act{font-size:13px;padding:6px 12px;border-radius:8px}
.sh-tag.sh-new{color:var(--good);background:color-mix(in srgb,var(--good) 12%,transparent)}
.sh-lead{padding:12px 16px 4px;color:var(--ink2)}.sh-list>.sh-lead+.sh-row{border-top:0}
.sh-waiting{display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:space-between;padding:12px 16px;margin-top:12px;color:var(--ink2)}
.sh-waiting .act,.sh-q .act,.sh-ans .act,.sh-req .act{font-size:13px;padding:6px 12px;border-radius:8px}
.sh-assure{font-size:13px;color:var(--ink2);background:var(--wash);border-radius:10px;padding:9px 12px;margin:0 0 14px}
.sh-flat,.sh-place{padding:12px 16px;border-left:3px solid var(--accent);margin-bottom:14px;color:var(--ink2)}.sh-place select{font:inherit;margin-left:6px}
.sh-ans{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end}.sh-prop .sh-name{overflow-wrap:anywhere}
.sh-prop .sh-edit{display:flex;gap:6px;flex-wrap:wrap}.sh-prop .sh-edit input{font:inherit;font-weight:600;min-width:0;width:min(320px,100%);padding:4px 8px;border-radius:7px;border:1px solid var(--accent);background:var(--raise);color:var(--ink)}
.sh-said{color:var(--good)}.sh-kept .sh-name{color:var(--ink2)}
.sh-owner input{font:inherit;min-width:0;width:min(320px,100%);margin-left:6px;padding:4px 8px;border-radius:7px;border:1px solid var(--line);background:var(--raise);color:var(--ink)}
.sh-left{padding:10px 16px 12px;font-size:12px;color:var(--muted);border-top:1px solid var(--line)}
.sh-first{font-size:12px;color:var(--muted);margin:0 0 10px}.sh-first i{font-style:normal;color:var(--good)}
.sh-req{padding:14px 16px}.sh-req blockquote{margin:6px 0 12px;padding:10px 12px;border-left:3px solid var(--accent);background:var(--wash);border-radius:0 8px 8px 0;color:var(--ink)}
.sh-what{font-size:12px;color:var(--muted);margin-top:8px}
.sh-ownbox{margin-top:10px}.sh-ownbox textarea{width:100%;font:inherit;color:var(--ink);background:var(--raise);border:1px solid var(--accent);border-radius:8px;padding:8px 10px;min-height:60px;resize:vertical}
@media (max-width:560px){.sh-row{grid-template-columns:minmax(0,1fr)}.sh-row>.go{grid-row:auto;grid-column:1;justify-self:start;margin-top:4px}.sh-ans{justify-content:flex-start}
#tab-home,#tab-work{max-width:none}main{padding:16px 16px 80px}body.simple .sh-dot .sh-dw{display:none}}
"""

# The simple home's script: which view shows (home, a piece of work's page,
# or a tab under More), kept in this window's sessionStorage so the rebuild
# after an action comes back to it, and on Home for a new window; Ask
# something, and Claude's answer when it comes back to the page; Settings ›
# Home. Continue, an answer and Not now commit in a zone, so WORK_JS shows
# each running until its reply comes, as it does every such button. A browser cannot act:
# there Continue and Ask copy what to say to Claude instead.
SIMPLE_JS = r"""
(function(){var body=document.body;if(!body.classList.contains('simple'))return;
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick,VIEW='garrick-simple-view',ANS='garrick-simple-answer';
function ss(k,v){try{if(v===undefined)return sessionStorage.getItem(k);if(v===null)sessionStorage.removeItem(k);else sessionStorage.setItem(k,v)}catch(e){return null}}
function say(s){if(window.GarrickSay)GarrickSay(s)}
var tab=window.StatusTab;
function view(v,keep){var arts=document.querySelectorAll('article.sh-work'),id=v.indexOf('work:')===0?v.slice(5):'',a=id&&document.getElementById(id);
if(id&&!a)v='home';
if(a){arts.forEach(function(x){x.hidden=x!==a});tab('work')}else if(v.indexOf('tab:')===0)tab(v.slice(4));else tab('home');
ss(VIEW,v);if(!keep)window.scrollTo(0,0)}
window.StatusTab=function(n){if(n!=='work')ss(VIEW,n==='home'?'home':'tab:'+n);return tab(n)};
document.addEventListener('click',function(e){var t=e.target.closest?e.target:null;if(!t)return;
var w=t.closest('[data-w-open]');if(w){e.preventDefault();view('work:'+w.dataset.wOpen);return}
if(t.closest('[data-home]')){e.preventDefault();view('home');return}
var m=t.closest('[data-more]');if(m){e.preventDefault();view('tab:'+m.dataset.more);return}
var tb=t.closest('.tabs [data-tab]');if(tb&&tb.dataset.tab==='home'){view('home');return}
var g=t.closest('button.go[data-act]');if(!g)return;
if(!host){e.stopPropagation();var p=g.dataset.phrase||'';if(window.GarrickCopy)GarrickCopy(p).then(function(){say('Copied “'+p+'”. Paste it into Claude.')});return}
if(body.dataset.local==='managed'){e.stopPropagation();say('Claude can\'t open work on this Mac. See the note on the home.')}},true);
/* Ask something: in the app, Claude opens on the words; in a browser they are copied for you */
function askReq(v){return{verb:'ask-desktop',prompt:v}}
var form=document.getElementById('sh-ask'),box=document.getElementById('sh-askbox');
if(form)form.addEventListener('submit',function(e){e.preventDefault();var v=(box.value||'').trim();if(!v){box.focus();return}
if(!host){if(window.GarrickCopy)GarrickCopy(v).then(function(){say('Copied. Paste it into Claude.')});return}
var b=form.querySelector('button');b.disabled=true;b.textContent='Asking…';ss(ANS,JSON.stringify({q:v,a:''}));
host.postMessage({act:askReq(v)});say('Opening Claude on “'+v.slice(0,60)+'”…')});
function answer(){var d=null;try{d=JSON.parse(ss(ANS)||'null')}catch(e){}var el=document.getElementById('sh-answer');if(!el)return;
if(!d||!d.a){el.hidden=true;return}el.hidden=false;el.textContent='';var h=document.createElement('b');h.textContent=d.q;el.appendChild(h);
el.appendChild(document.createTextNode(d.a));var x=document.createElement('button');x.className='wx';x.type='button';x.textContent='×';
x.setAttribute('aria-label','Dismiss');x.onclick=function(){ss(ANS,null);el.hidden=true};el.appendChild(x)}
var prev=window.GarrickActed;window.GarrickActed=function(q,out){
if(q&&(q.verb==='discover'||q.verb==='start')&&out&&out.ok&&out.view)ss(VIEW,'work:'+out.view);   /* the suggestions, or the work's first look, after the rebuild */
if(q&&q.verb==='ask-desktop'){var d={q:q.prompt,a:out&&out.answer||''};
if(d.a)ss(ANS,JSON.stringify(d));else ss(ANS,null);answer();var b=form&&form.querySelector('button');if(b){b.disabled=false;b.textContent='Ask'}
if(out&&out.ok&&box)box.value=''}
if(prev)return prev(q,out)};
answer();var v=ss(VIEW);view(v||'home',true);
/* Add your own work (#182): the Mac app opens its own folder picker, and picking a folder grants it access; a browser
   cannot, so it copies what to ask Claude instead. A suggestion's Yes and Not a piece of work carry the part of the
   workspace chosen above them; Rename and Change it open a box for the user's words */
function act(q,said){if(!host){say('Answer this in the Garrick app: a browser cannot change anything.');return}
if(!(window.GarrickAct&&GarrickAct(q,said))){host.postMessage({act:q});say(said)}}
function placed(el,q){var art=el.closest('article'),sel=art&&art.querySelector('select[data-place]'),ow=art&&art.querySelector('input[data-owner]'),pl={};
if(sel){if(!sel.value){sel.focus();say('First choose which part of your workspace this work is for.');return null}
try{pl=JSON.parse(sel.value)}catch(x){return null}}
q=Object.assign({},q,pl);
/* whose work it is, where that part of the workspace has no one yet: kept for the rebuild, in case the answer is refused */
if(ow&&(sel?!pl.party:ow.dataset.needed==='1')){var v=ow.value.trim();if(!v){ow.focus();say('First say whose work this is: your employer, or “my own”.');return null}
ss('garrick-owner',v);q=Object.assign(q,{owner:v})}
return q}
function owner(){[].forEach.call(document.querySelectorAll('select[data-place]'),function(sel){var art=sel.closest('article'),box=art&&art.querySelector('.sh-owner');
function show(){var pl={};try{pl=JSON.parse(sel.value||'{}')}catch(x){}if(box)box.hidden=!sel.value||!!pl.party}sel.onchange=show;show()});
var kept=ss('garrick-owner');if(kept)[].forEach.call(document.querySelectorAll('input[data-owner]'),function(i){if(!i.value)i.value=kept})}
function renameReq(id,v){return{verb:'suggestion',id:id,answer:'rename',name:v}}
function ownReq(z,f,l,v){return{verb:'answer',zone:z,file:f,label:l,text:v}}
function rename(b){var row=b.closest('.sh-prop'),cell=row&&row.querySelector('.sh-name');if(!cell||cell.querySelector('input'))return;
var was=cell.textContent,key='garrick-rename-'+b.dataset.rename;cell.innerHTML='<div class="sh-edit"><input aria-label="New name"><button class="act primary" type="button">Save</button><button class="act" type="button">Cancel</button></div>';
var inp=cell.querySelector('input'),bs=cell.querySelectorAll('button');inp.value=ss(key)||b.dataset.name||was;inp.focus();inp.select();
/* the name typed is kept until the rename is saved, so a refusal and the rebuild after it never lose it */
function save(){var v=inp.value.trim();if(!v){inp.focus();return}ss(key,v);var q=placed(b,renameReq(b.dataset.rename,v));if(q)act(q,'Adding '+v+'…')}
function drop(){ss(key,null);cell.textContent=was}
bs[0].onclick=save;bs[1].onclick=drop;inp.onkeydown=function(e){if(e.key==='Enter'){e.preventDefault();save()}if(e.key==='Escape')drop()}}
function own(b){var card=b.closest('.sh-q'),box=card&&card.querySelector('.sh-ownbox');if(!card)return;if(box){box.remove();return}
box=document.createElement('div');box.className='sh-ownbox';var ta=document.createElement('textarea');ta.setAttribute('aria-label','The next step, in your words');
box.appendChild(ta);var row=document.createElement('div');row.className='sh-opts';row.innerHTML='<button class="act primary" type="button">Save</button><button class="act" type="button">Cancel</button>';
box.appendChild(row);card.appendChild(box);var bs=row.querySelectorAll('button');ta.focus();
bs[0].onclick=function(){var v=ta.value.trim();if(!v){ta.focus();return}act(ownReq(b.dataset.zone,b.dataset.file,b.dataset.own,v),'Noting the next step…')};
bs[1].onclick=function(){box.remove()}}
document.addEventListener('click',function(e){var t=e.target.closest?e.target:null;if(!t)return;
var pk=t.closest('[data-pick]');if(pk){e.preventDefault();e.stopPropagation();if(host)host.postMessage({pick:pk.dataset.pick});
else if(window.GarrickCopy)GarrickCopy(pk.dataset.phrase||'').then(function(){say('Only the Garrick app can open your folders. What to ask Claude instead is copied: paste it into Claude.')});return}
var sg=t.closest('button[data-sugg]');if(sg){var q;try{q=JSON.parse(sg.dataset.act)}catch(x){return}e.preventDefault();e.stopPropagation();
q=placed(sg,q);if(q)act(q,sg.dataset.say);return}
var rn=t.closest('button[data-rename]');if(rn){e.preventDefault();rename(rn);return}
var ow=t.closest('button[data-own]');if(ow){e.preventDefault();own(ow)}},true);
/* after a rebuild: a rename typed and not yet saved opens again with its words, and whose work it is is filled in again */
owner();[].forEach.call(document.querySelectorAll('button[data-rename]'),function(b){if(ss('garrick-rename-'+b.dataset.rename))rename(b)});
var prior=window.GarrickActed;window.GarrickActed=function(q,out){if(q&&q.verb==='suggestion'&&out&&out.ok){
if(q.answer==='rename')ss('garrick-rename-'+q.id,null);if(q.owner)ss('garrick-owner',null)}if(prior)return prior(q,out)}})();
/* Settings › Home, on either page: saved for every viewer at once, then the page rebuilds on the choice */
(function(){var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
function homeReq(v){return{verb:'settings',home:v}}
[].forEach.call(document.querySelectorAll('input[name="garrick-home"]'),function(r){r.onchange=function(){if(!host||!r.checked)return;
try{sessionStorage.removeItem('garrick-simple-view')}catch(e){}host.postMessage({act:homeReq(r.value)});
if(window.GarrickSay)GarrickSay(r.value==='simple'?'Garrick opens on the simple home now.':'Garrick opens on the full page now.')}})})();
"""


# --------------------------------------------------------------------------- the page

CSS = r"""
:root{color-scheme:light;--display:"Baskervville","Libre Baskerville",Baskerville,"Baskerville Old Face",Georgia,serif;--page:#f4f3f0;--side:#ecebe6;--surface:#fcfcfb;--raise:#fff;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--line:rgba(11,11,11,.10);--grid:#e1e0d9;--base:#c3c2b7;--accent:#3d73e0;--track:#cfdcf7;--wash:rgba(61,115,224,.10);
--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--none:#e6e5df;--shadow:0 1px 2px rgba(11,11,11,.04),0 4px 16px rgba(11,11,11,.04);--mark-ink:#1e2833;--mark-blue:#3d73e0}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;--side:#131312;--surface:#1a1a19;--raise:#211f1e;
--ink:#fff;--ink2:#c3c2b7;--line:rgba(255,255,255,.10);--grid:#2c2c2a;--base:#383835;--accent:#6590e6;--track:#112e6a;--wash:rgba(101,144,230,.14);--none:#2a2a28;--shadow:none;--mark-ink:#f5f0e6;--mark-blue:#8eb1f5}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--side:#131312;--surface:#1a1a19;--raise:#211f1e;
--ink:#fff;--ink2:#c3c2b7;--line:rgba(255,255,255,.10);--grid:#2c2c2a;--base:#383835;--accent:#6590e6;--track:#112e6a;--wash:rgba(101,144,230,.14);--none:#2a2a28;--shadow:none;--mark-ink:#f5f0e6;--mark-blue:#8eb1f5}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline;text-underline-offset:2px}
.app{min-height:100vh}
.mark .mi{fill:var(--mark-ink)}.mark .mb{fill:var(--mark-blue)}
.dot{width:8px;height:8px;border-radius:50%;flex:none;background:var(--none)}.dot.good{background:var(--good)}.dot.warning{background:var(--warning)}.dot.critical{background:var(--critical)}
.switch{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--ink2);cursor:pointer}
.switch input{appearance:none;width:30px;height:18px;border-radius:9px;background:var(--base);position:relative;cursor:pointer;margin:0}
.switch input::after{content:"";position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:#fff;transition:left .15s}
.switch input:checked{background:var(--accent)}.switch input:checked::after{left:14px}
main{padding:22px 30px 80px;min-width:0}
.stale{display:none;margin:0 0 16px;padding:10px 14px;border-radius:10px;background:var(--surface);border:1px solid var(--critical);font-weight:600}
.top{display:grid;grid-template-columns:minmax(220px,1.1fr) repeat(var(--tiles,4),minmax(140px,1fr));gap:14px;margin-bottom:18px}
a.go{color:inherit;text-decoration:none;cursor:pointer;display:block}a.go:hover{border-color:var(--base)}
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
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);min-width:0;scroll-margin-top:80px}
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
.fresh.warning i{background:var(--warning)}.fresh.critical i{background:var(--critical)}.fresh.age i{background:var(--base)}
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
.pchev{box-sizing:border-box;width:16px;border:0;background:none;padding:0 3px 0 0;margin:0;cursor:pointer;color:var(--muted);line-height:0;vertical-align:-2px}
.pchev .chev{width:13px;height:13px}.pchev[aria-expanded="true"] .chev{transform:rotate(90deg)}
/* a project with no chevron keeps its room, so every name starts in one column */
.tunit>.thread:not(.proj)>.t{padding-left:16px}
.thread .t .subn{font-size:11.5px}.thread.proj .t>a{display:inline}.thread.sub{padding-left:20px;border-top:1px dashed var(--grid);font-size:12.5px}
.gsum{margin:6px 0 0}
.onlybar{display:flex;justify-content:flex-end;margin:-4px 0 12px}
.phead{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.phead h4{margin:0;min-width:0}
.phead .pflip{flex:none;font-size:11px;padding:3px 8px}.gpop .phead{padding-right:30px}
.gzsel{font:inherit;font-size:12px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:5px 26px 5px 10px;
appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);
background-position:calc(100% - 13px) 50%,calc(100% - 9px) 50%;background-size:4px 4px;background-repeat:no-repeat;cursor:pointer}
.tabs{display:flex;gap:2px;margin:0 0 18px;border-bottom:1px solid var(--line)}
.tabs button{border:0;background:none;font:inherit;font-size:13.5px;font-weight:560;color:var(--ink2);padding:8px 12px 9px;border-bottom:2px solid transparent;margin-bottom:-1px;cursor:pointer;display:inline-flex;gap:7px;align-items:center}
.tabs button:hover{color:var(--ink)}.tabs button.on{color:var(--ink);border-bottom-color:var(--accent)}
.tabs .n{font-size:11.5px;color:var(--muted);font-weight:500;font-variant-numeric:tabular-nums}
.nohost .tacts{display:none}.nohost .tadd-open{display:none}
.tick{width:18px;height:18px;margin-top:1px;border-radius:5px;border:1.5px solid var(--base);background:var(--raise);cursor:pointer;padding:0;display:grid;place-items:center}
.tick:hover{border-color:var(--accent)}
.flagrow{display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:6px 0;border-top:1px solid var(--line);font-size:13px}
.flagrow small{grid-column:1/-1;color:var(--muted);font-size:12px}.chip.on{color:var(--good);border-color:var(--good)}
#toast{position:fixed;left:50%;bottom:calc(22px + var(--work-h,0px));transform:translateX(-50%);background:var(--ink);color:var(--surface);font-size:13px;padding:9px 14px;border-radius:10px;opacity:0;transition:opacity .15s;pointer-events:none;z-index:10;max-width:90vw}
@media (hover:none){.head .tools{opacity:1}}
#tip{position:fixed;pointer-events:none;z-index:9;background:var(--ink);color:var(--surface);font-size:12px;padding:6px 9px;border-radius:7px;max-width:280px;opacity:0}
.only [data-ok="1"]{display:none}
.only .rows:not(:has([data-ok="0"]))::after,.only .zone:not(:has([data-ok="0"]))::after,.only .tiles:not(:has([data-ok="0"]))::after{content:"Nothing wrong here.";display:block;color:var(--muted);font-size:12px;padding:8px 2px}
.slot{display:flex;flex-direction:column;gap:16px;min-width:0}.slot.full{grid-column:span 12}.slot .card{grid-column:auto}
.slot:not(:has(>.card:not([hidden]))){display:none}
/* one column takes the width when the other is empty, except while a card is dragged: then both show, side by side */
body:not(.dragging) .grid:not(:has(.stack.right>.card:not([hidden]))) .stack.left,body:not(.dragging) .grid:not(:has(.stack.left>.card:not([hidden]))) .stack.right{grid-column:span 12}
.stack .zones{grid-template-columns:1fr}[hidden]{display:none!important}
.head .tools{display:flex;gap:2px;align-items:center;opacity:0;transition:opacity .12s;margin-left:2px}
.head:hover .tools,.head:focus-within .tools{opacity:1}
.grip,.hide,.totab{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;color:var(--muted);border:0;background:none;padding:0;cursor:pointer}
.grip{cursor:grab}.grip:hover,.hide:hover,.totab:hover{background:var(--wash);color:var(--ink)}.grip svg,.hide svg,.totab svg{width:14px;height:14px}
.dragging .slot{display:flex!important;min-height:64px;border-radius:14px;outline:2px dashed var(--grid);outline-offset:4px}
.ph{border:2px dashed var(--accent);border-radius:14px;background:var(--wash);flex:none}.card.lifted{display:none}
.hint{font-size:11.5px;color:var(--muted);margin:0}
.changes .hint{margin:6px 0 2px}.paths{margin:0;padding-left:18px;font-size:12px}.paths code{word-break:break-all}
.zt{display:flex;align-items:baseline;gap:8px;margin:8px 0 2px}.zt .act{margin-left:auto;align-self:center}a.act:hover{text-decoration:none}
.gwrap{position:relative;height:560px;border-radius:10px;background:var(--raise);border:1px solid var(--line);overflow:hidden}
.gwrap canvas{display:block;width:100%;height:100%;touch-action:none;cursor:grab}.gwrap canvas.drag{cursor:grabbing}.gwrap canvas.hot{cursor:pointer}
.gbar{position:absolute;left:10px;top:10px;right:10px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;pointer-events:none}
.gbar.gcorner{left:auto;top:auto;bottom:10px;justify-content:flex-end}.gbar>*{pointer-events:auto}
.gbar .gseg{display:flex;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:2px}
.gbar button{border:0;background:none;color:var(--ink2);font:inherit;font-size:12px;padding:4px 9px;border-radius:6px;cursor:pointer}
.gbar button.on{background:var(--wash);color:var(--ink)}.gbar>button{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:5px 9px}
.gpop,.tcard{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px;box-shadow:0 6px 24px rgba(0,0,0,.14);font-size:12.5px}
.gpop{position:absolute;right:10px;top:10px;width:290px;max-height:calc(100% - 20px);overflow:auto}
.tcard{position:fixed;left:0;top:0;width:300px;max-width:calc(100vw - 16px);z-index:9}
.gpop h4,.tcard h4{margin:0 22px 2px 0;font-size:14px;font-weight:640;overflow-wrap:anywhere}.tcard h4{margin-right:0}
.gpop .x{position:absolute;right:8px;top:6px;border:0;background:none;color:var(--muted);font-size:18px;line-height:1;cursor:pointer;padding:2px 4px}
.gacts{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 4px}.gacts a.act:hover{text-decoration:none}
/* In Garrick.app, which sets --icon-<app> and .appicons: each way to open a note is its app's icon, as in its
   menu bar, the default on a tinted square. A browser keeps the words. */
.act[data-k=note]{--ic:var(--icon-note)}.act[data-k=note][href^="obsidian:"]{--ic:var(--icon-obsidian,var(--icon-note))}
.act[data-k=finder]{--ic:var(--icon-finder)}.act[data-k=cmux]{--ic:var(--icon-cmux)}.act[data-k=codex]{--ic:var(--icon-codex)}.act[data-k=claude]{--ic:var(--icon-claude)}
.appicons .gacts{align-items:center}
.appicons .act[data-k]{width:34px;height:34px;padding:0;font-size:0;color:transparent;border-color:transparent;border-radius:8px;background:transparent var(--ic) center/26px no-repeat}
.appicons .act[data-k][data-d]{background-color:color-mix(in srgb,var(--accent) 22%,transparent)}
.appicons .act[data-k]:hover{border-color:var(--base)}
.gpop .glinks{display:flex;flex-direction:column;margin-top:8px;border-top:1px solid var(--grid);padding-top:6px}
.gpop .glinks button{display:flex;align-items:center;gap:7px;text-align:left;border:0;background:none;color:var(--ink2);font:inherit;font-size:12.5px;padding:4px;border-radius:6px;cursor:pointer}
.gpop .glinks button:hover{background:var(--wash);color:var(--ink)}.gpop .glinks i{width:8px;height:8px;border-radius:50%;flex:none}
.gpop .glinks span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gpop .glinks small{white-space:nowrap;font-size:11px}
.legend i.ring{background:none;border-radius:50%;border:2px solid}
.live{display:inline-block;width:8px;height:8px;border-radius:50%;flex:none;margin:0 2px 1px 6px;vertical-align:middle;background:var(--good);box-shadow:0 0 0 3px color-mix(in srgb,var(--good) 22%,transparent)}
.live.working{background:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 25%,transparent);animation:livepulse 1.4s ease-in-out infinite}
@keyframes livepulse{50%{box-shadow:0 0 0 5px color-mix(in srgb,var(--accent) 8%,transparent)}}
@media (prefers-reduced-motion:reduce){.live.working{animation:none}}
.thread .t a+.live{margin-left:.4em}.thread.pending{opacity:.55}.tline .live{margin:0 7px 1px 1px}
.thread .t>a{display:inline-block;max-width:calc(100% - 16px);vertical-align:bottom}
.chip.nores{color:var(--muted);border-style:dashed}.phead .pbtns{display:flex;gap:6px;flex:none}
.status.running{color:var(--accent)}
.cols{display:flex;align-items:flex-end;gap:2px;height:96px;border-bottom:1px solid var(--base);padding-top:16px}
.cols div{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%;position:relative}
.cols b{display:block;width:100%;max-width:22px;background:var(--accent);border-radius:4px 4px 0 0;min-height:0}
.cols em{position:absolute;top:-16px;font-style:normal;font-size:11px;color:var(--ink2)}
.ticks{display:flex;gap:2px;font-size:10px;color:var(--muted);margin-top:4px}.ticks span{flex:1;text-align:center}
.desk-acts{display:flex;gap:6px;margin-left:6px}.act.armed{background:var(--critical);border-color:var(--critical);color:#fff}
@media (max-width:1180px){.top{grid-template-columns:repeat(2,minmax(0,1fr))}.hero{grid-column:span 2}.stack,.stack.left{grid-column:span 12}}
@media (max-width:820px){main{padding:16px}
.jobs .row{grid-template-columns:18px minmax(0,1fr) auto}.jobs .row>:nth-child(4){display:none}.jobs .row .strip{grid-column:2/-1;grid-row:2}.tiles{grid-template-columns:1fr}
.gwrap{height:440px}.gpop{left:10px;right:10px;top:auto;bottom:10px;width:auto;max-height:55%}}
"""

# The top row both pages share: the mark and name with when the page was built,
# the tabs, and the controls, pinned while the page scrolls. Each page passes
# its own tabs and controls.
def bar(mark_svg: str, name: str, built: str, tabs: str, controls: str) -> str:
    return ('<header class="bar"><div class="brand">%s<div class="bname"><h1>%s</h1><p>Built %s · <span id="age">just now</span></p></div></div>'
            '%s%s</header>' % (mark_svg, name, E(built), tabs, controls))


# Auto, light and dark as icons, each named for a screen reader and on hover.
THEME_SEG = ('<div class="seg theme" role="group" aria-label="Theme">'
             '<button type="button" data-t="auto" title="Follow the system" aria-label="Theme: follow the system">'
             '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.6" fill="none" stroke="currentColor" stroke-width="1.5"/>'
             '<path d="M8 2.4a5.6 5.6 0 0 1 0 11.2z" fill="currentColor"/></svg></button>'
             '<button type="button" data-t="light" title="Light" aria-label="Theme: light">'
             '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" stroke-width="1.5"/>'
             '<path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" '
             'stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button>'
             '<button type="button" data-t="dark" title="Dark" aria-label="Theme: dark">'
             '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13 9.6A5.4 5.4 0 0 1 6.4 3a5.4 5.4 0 1 0 6.6 6.6z" fill="none" '
             'stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg></button></div>')

BAR_CSS = r"""
header.bar{position:sticky;top:0;z-index:8;display:flex;align-items:stretch;gap:24px;padding:0 30px;min-height:58px;background:var(--page);border-bottom:1px solid var(--line)}
.bar .brand{display:flex;align-items:center;gap:10px;flex:none}.bar .brand .mark{width:30px;height:30px;flex:none;display:block}
.bar h1{font:600 17px/1.1 var(--display,Baskerville,"Baskerville Old Face",Georgia,serif);margin:0;letter-spacing:.005em;white-space:nowrap}
.bar .bname p{margin:2px 0 0;color:var(--muted);font-size:11.5px;white-space:nowrap}
.bar .tabs{flex:1;min-width:0;margin:0;border:0;align-self:stretch}
.bar .tabs button{padding:0 12px;margin-bottom:-1px;border-bottom:2px solid transparent}.bar .tabs button.on{border-bottom-color:var(--accent)}
.bar .bacts{display:flex;align-items:center;gap:6px;flex:none}
.seg{display:flex;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:2px}
.seg button{border:0;background:none;color:var(--ink2);font:inherit;font-size:12px;padding:4px 7px;border-radius:6px;cursor:pointer;line-height:0}
.seg button.on{background:var(--wash);color:var(--ink)}.seg button:hover{color:var(--ink)}.seg.theme svg{width:15px;height:15px}
html{scroll-padding-top:76px}
.hiddencards{margin-top:12px}.hiddencards .gacts{margin:4px 0 0}
@media (max-width:820px){header.bar{flex-wrap:wrap;gap:6px 12px;padding:8px 16px 0}.bar .brand{flex:1}.bar .tabs{order:3;flex-basis:100%;overflow-x:auto}.bar .tabs button{padding:8px 10px}}
"""


# Settings: the dialog, its sections and the cog that opens it. Kept apart so
# a page built on this one (the workspace's own status page, where it runs
# ahead of a release) can carry the same dialog with the same look.
SETTINGS_CSS = r"""
.cog{flex:none;margin:0;padding:5px;border:0;border-radius:8px;background:none;color:var(--muted);cursor:pointer;line-height:0}
.cog:hover,.cog:focus-visible{color:var(--ink);background:var(--wash)}
.launcher-row{display:flex;align-items:center;justify-content:space-between;gap:12px}
.launcher-default{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--ink2)}.launcher-default input{accent-color:var(--accent)}
.launcher-default:has(input:disabled){opacity:.4}
.nohost .apponly{display:none}.launcher-choice:has(input:disabled){opacity:.5}.hotkey{display:flex;gap:6px;align-items:center}
.hotkey input{width:150px;font:inherit;font-size:13px;text-align:center;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:5px 8px;cursor:pointer}
.hotkey input:focus{outline:2px solid var(--accent);outline-offset:1px}
.menu-style{font:inherit;font-size:13px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:5px 8px}
.menu-style:disabled{opacity:.5}
dialog.settings{position:relative}dialog.settings .sclose{position:absolute;top:14px;right:14px;width:30px;height:30px;display:flex;align-items:center;
justify-content:center;font-size:20px;line-height:1;border:0;background:none;color:var(--muted);border-radius:8px;cursor:pointer}
dialog.settings .sclose:hover{background:var(--wash);color:var(--ink)}
dialog.settings .setsec{margin-top:14px}dialog.settings .setsec:first-of-type{margin-top:0}
.launcher-choice{display:flex;align-items:center;gap:12px;padding:3px 0;font-size:13px}
/* Settings › Menu bar as one form: the name on the left, every control in one column on the right, of one width,
   a tick at that column's left edge as a field starts there, and a hotkey's Clear as an × inside its field */
#menu-settings .launcher-row{display:grid;grid-template-columns:minmax(0,1fr) 232px;column-gap:14px;align-items:center;min-height:32px}
#menu-settings .launcher-row>.launcher-choice:only-child{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1fr) 232px;column-gap:14px}
#menu-settings .launcher-choice:only-child>span{grid-column:1;grid-row:1}#menu-settings .launcher-choice:only-child>input{grid-column:2;grid-row:1;justify-self:start;margin:0}
#menu-settings .menu-style{width:100%}#menu-settings .hotkey{position:relative;display:block;width:100%}
#menu-settings .hotkey input{width:100%;box-sizing:border-box;padding-right:26px}
#menu-settings .hotkey .act{position:absolute;right:4px;top:50%;transform:translateY(-50%);width:20px;height:20px;padding:0;border:0;border-radius:50%;background:none;font-size:0;line-height:20px;color:var(--muted);cursor:pointer}
#menu-settings .hotkey .act::after{content:"\00d7";font-size:15px}#menu-settings .hotkey .act:hover{background:var(--line);color:var(--ink)}
#menu-settings .hotkey input:placeholder-shown+.act{display:none}
.launcher-choice input{width:16px;height:16px;accent-color:var(--accent)}.launcher-choice small{display:block;font-size:12px;color:var(--muted)}
.launcher-choice input:disabled+span{color:var(--muted)}
.notes{margin-top:8px;border:1px solid var(--line);border-radius:10px;padding:6px 10px}.notes summary{cursor:pointer;font-size:13px;font-weight:600}
.notes div{max-height:240px;overflow:auto;font-size:12.5px;color:var(--ink2)}.notes h5{margin:10px 0 2px;font-size:12px}.notes ul{margin:4px 0;padding-left:18px}
.notes li{margin:3px 0}.notes p{margin:6px 0}.notes code{font-size:11.5px}
dialog.settings{max-height:calc(100vh - 48px);overflow:auto;overscroll-behavior:contain}dialog.settings h2:focus{outline:none}
dialog.settings{background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:16px;max-width:460px;width:calc(100% - 32px);padding:20px 24px;box-shadow:var(--shadow)}
dialog.settings::backdrop{background:rgba(0,0,0,.35)}dialog.settings h2{margin:0 0 12px;font:600 20px/1.2 var(--display)}
dialog.settings h3{display:flex;align-items:center;gap:6px;margin:0 0 4px;font-size:13px}
dialog.settings .setver{margin:0;font-size:13px;color:var(--ink2)}dialog.settings .hint{margin-top:12px}dialog.settings .hint a{color:var(--accent)}
dialog.settings .gacts{margin:8px 0 2px}
/* two columns once the window is wide enough, so Settings fits in about one window height */
.setcols{display:grid;grid-template-columns:minmax(0,1fr);gap:14px 28px}
@media (min-width:760px){dialog.settings{max-width:860px}.setcols{grid-template-columns:repeat(2,minmax(0,1fr))}}
/* a section's explanation, word for word, behind the "?" beside its heading */
#settings .setsec:not(.explained) :is(.launcher-choice,.setlink,.flagrow) small{display:none}
.qhelp{flex:none;width:17px;height:17px;padding:0;display:inline-flex;align-items:center;justify-content:center;font:inherit;font-size:10.5px;font-weight:600;line-height:1;color:var(--muted);background:none;border:1px solid var(--line);border-radius:50%;cursor:pointer}
.qhelp:hover,.qhelp[aria-expanded="true"]{color:var(--ink);border-color:var(--muted)}.qhelp:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
dialog.settings .sethelp{margin:2px 0 6px}
.setcol{display:flex;flex-direction:column;min-width:0}.setfoot{margin-top:auto;padding-top:14px}.setrule{padding-top:10px;border-top:1px solid var(--line)}
dialog.settings .setfoot .gacts{align-items:center;margin:0}dialog.settings .hiddencards .gacts{margin:4px 0 0}.setfoot .hiddencards{margin:0 0 10px}
.setlinks{margin-top:8px;border-bottom:1px solid var(--line)}.setlink{display:block;padding:5px 2px;border-top:1px solid var(--line);color:var(--ink);text-decoration:none}
.setlink:hover{background:var(--wash)}.setlink b{display:block;font-size:13px;font-weight:600}.setlink small{display:block;font-size:12px;color:var(--muted)}
/* Settings › Notifications: the simple view, four plain choices; then More options, with the channels, a table of
   events against them, and the zones */
#notify-settings [hidden]{display:none!important}
#notify-settings .nsimple{display:flex;flex-direction:column;gap:8px;margin:4px 0 6px;font-size:13px}
#notify-settings .nsrow{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px}
#notify-settings .nslab{flex:0 0 92px;font-weight:560;color:var(--ink2)}
#notify-settings .nsopts{display:flex;flex-wrap:wrap;align-items:center;gap:4px 14px;flex:1;min-width:0}
#notify-settings .nsopts.nscol{flex-direction:column;align-items:flex-start;gap:5px}
#notify-settings .nsimple label{display:inline-flex;align-items:center;gap:6px}
#notify-settings .nsimple input[type=checkbox],#notify-settings .nmore input[type=checkbox]{accent-color:var(--accent)}
#notify-settings .nsafter{white-space:nowrap}#notify-settings .nsq{align-items:center;gap:6px}#notify-settings .nsrule{margin:-4px 0 0 24px;font-size:12px}
#notify-settings .ntgstate{display:inline-flex;align-items:center;gap:8px}#notify-settings .ntgok{color:var(--ink2)}
#notify-settings .ntgok::before{content:'';display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--good);margin-right:6px;vertical-align:1px}
#notify-settings .nlink{background:none;border:0;padding:0;font:inherit;font-size:12.5px;color:var(--accent);cursor:pointer;text-decoration:underline}
#notify-settings .ntgset{border:1px solid var(--line);border-radius:9px;padding:9px 12px;background:var(--wash)}
#notify-settings .ntgset ol{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:10px;font-size:12.5px}
#notify-settings .ntgset li{display:flex;flex-direction:column;gap:5px}#notify-settings .ntgset .nfield{margin:0}
#notify-settings .ntgset small{font-size:11.5px;color:var(--muted)}
#notify-settings input[type=password]{font:inherit;font-size:12.5px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:7px;padding:4px 7px;flex:1;min-width:150px}
#notify-settings .ncustom{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin:0;padding:7px 10px;border-radius:8px;background:var(--wash);font-size:12.5px}
#notify-settings .nover{margin:0;font-size:12px;cursor:help}
#notify-settings details.nmore{margin-top:6px;border-top:1px solid var(--line);padding-top:6px}
#notify-settings details.nmore>summary{cursor:pointer;font-size:12.5px;font-weight:560;color:var(--ink2);list-style:none;padding:3px 0}
#notify-settings details.nmore>summary::-webkit-details-marker{display:none}
#notify-settings details.nmore>summary::before{content:'\203A';display:inline-block;width:12px;transition:transform .15s}
#notify-settings details.nmore[open]>summary::before{transform:rotate(90deg)}
#notify-settings .nzhelp{margin:0 0 4px;font-size:12px}
#notify-settings .nch{min-height:30px}#notify-settings .nfield{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:0 0 6px 28px}
#notify-settings input[type=text],#notify-settings input[type=time],#notify-settings input[type=number],#notify-settings select{font:inherit;font-size:12.5px;
color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:7px;padding:4px 7px}
#notify-settings .nfield input[type=text]{flex:1;min-width:150px}#notify-settings .ntok{flex-basis:100%;margin:0}
#notify-settings input[type=number]{width:52px;padding:2px 5px}
.nev{width:100%;border-collapse:collapse;margin:10px 0 6px;font-size:12.5px}
.nev th,.nev td{padding:5px 3px;border-bottom:1px solid var(--line);text-align:center;vertical-align:middle}
.nev thead th{font-size:11px;font-weight:600;color:var(--muted)}.nev thead th:first-child,.nev th[scope=row]{text-align:left}
.nev th[scope=row]{font-weight:560}.nev th small{display:block;font-size:11.5px;font-weight:400;color:var(--muted)}
.nev .nafter,.nev .naway{display:block;font-size:11.5px;font-weight:400;color:var(--ink2);margin-top:2px;white-space:nowrap}
.nev .naway input{vertical-align:-2px;margin:0 3px 0 0}.nev thead th:first-child{width:46%}
.nev input[type=checkbox],.nzone input[type=checkbox]{accent-color:var(--accent)}.nev select{width:64px;padding:4px 3px}
.nev td.noff,.nzone label.noff{opacity:.4}
#settings .setsec:not(.explained) .nev th small{display:none}
.nquiet{display:flex;align-items:center;gap:6px;font-size:12.5px}
#notify-settings .nsub{margin:12px 0 4px;font-size:12px}
.nzone{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;padding:4px 0;border-bottom:1px solid var(--line);font-size:12.5px}
.nzone .zprev{flex:1;min-width:90px;font-weight:560}.nzone .nzto{display:flex;gap:8px}.nzone label{display:flex;align-items:center;gap:3px}
.nzone input[type=text]{width:120px}
#n-said{margin-top:8px}#n-said.bad{color:var(--critical,#C0392B)}
"""

# What a note's panel in the graph and a thread's card in the list both show,
# built in one place, so the two offer the same actions under the same labels.
# Each action opens a file or copies a phrase; none acts on the workspace.
# Inside Garrick.app (extras/status/app/), which answers to
# window.webkit.messageHandlers.garrick, a project or thread with a folder
# (`f`, there only where cmux is installed) also gets Open in cmux: a cmux tab
# in that folder, with the phrase that resumes it on the clipboard. There, and
# in the Obsidian plugin, which gives the page the same bridge, the apps take
# the place of Copy "open X"; a browser, which can only copy, keeps it.
# Open in Claude on a thread (`oc`, its note) is the one launcher that acts
# (#180): where the build found Claude Code's command-line tool (the body's
# data-cli), it sends the simple home's Continue request, page_action.py's
# `continue`, and the working card says "Opening <thread> in Claude…" until
# the desktop app has opened on Claude's answer, or the refusal stays there in
# its own words. Without the tool, and for a project of several threads, it
# is the deep link, which leaves "open X" typed in for you to send.
PANEL_JS = r"""
/* Which apps a card offers and what clicking a thread's name does. In the
   app, the settings saved for every viewer (#launch-settings, written by
   page_action.py from what Settings sends) come first; a browser keeps its own. */
var GarrickPrefs=(function(){
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick,KEYS=['note','finder','cmux','codex','claude'];
var el=document.getElementById('launch-settings'),shared=null;if(host&&el){try{shared=JSON.parse(el.textContent)}catch(e){}}
if(shared&&!Array.isArray(shared.launchers))shared=null;
function local(k){try{return localStorage.getItem(k)}catch(e){return null}}
function launchers(){if(shared){var o={};KEYS.forEach(function(k){o[k]=shared.launchers.indexOf(k)>=0});return o}
try{return JSON.parse(local('garrick-launchers')||'{}')||{}}catch(e){return{}}}
function def(){return(shared?shared['default']:local('garrick-default'))||'note'}
function set(on,d){if(shared)shared={launchers:KEYS.filter(function(k){return on[k]!==false}),'default':d||'note'};
try{localStorage.setItem('garrick-launchers',JSON.stringify(on));localStorage.setItem('garrick-default',d||'note')}catch(e){}}
function request(){var on=launchers();return{verb:'settings',launchers:KEYS.filter(function(k){return on[k]!==false}),'default':def()}}
return{launchers:launchers,def:def,set:set,request:request}})();
var Panel=(function(){
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function copy(p){return'<button class="act" type="button" data-copy="'+esc(p)+'" data-say="'+esc('Copied “'+p+'”. Paste it to your assistant.')+'">Copy “'+esc(p)+'”</button>'}
var LABEL={claude:'Claude',codex:'Codex',cmux:'cmux',finder:'Finder'};
function prefs(){return GarrickPrefs.launchers()}
function chosen(){var on=prefs();return(document.body.dataset.launchers||'').split(',').filter(function(k){return k&&on[k]!==false})}
function phrase(o){return o.w?'open '+o.w:o.lw?'open '+o.lw:''}
/* Open in Claude on a thread, where the build found Claude Code's CLI: the simple home's Continue request (#180) */
function cont(o){return o.oc&&document.body.dataset.cli?{verb:'continue',zone:o.oc[0],file:o.oc[1]}:null}
function going(o){return'Opening '+o.n+' in Claude…'}
/* What the page says the moment the button is pressed: that it is opening, never that it
   opened. The host says what opened, and only it can: a cold Claude is started and waited
   for, Codex and cmux say the clipboard now holds the phrase, Finder names the phrase it
   cannot take, and a failure says what is left to do. An app built before 0.28.0 says
   nothing back, and then this line is all there is. */
function launch(k,o){var p=phrase(o),say=k==='finder'?'Showing '+o.n+' in Finder…':'Opening '+o.n+' in '+LABEL[k]+'…';
var l=k==='finder'?'Reveal in Finder':'Open in '+LABEL[k];
var q=k==='claude'&&cont(o);if(q)return'<button class="act" type="button" data-k="claude"'+dmark(k,o)+' title="'+l+'" aria-label="'+l+'" data-act="'+esc(JSON.stringify(q))+'" data-say="'+esc(going(o))+'">'+l+'</button>';
if(k==='cmux'&&o.dk)return'<button class="act" type="button" data-k="cmux"'+dmark(k,o)+' title="'+l+'" aria-label="'+l+'" data-act="'+desk(o,'open')+'"'
+(o.f?' data-expect="'+esc('live:'+o.f)+'"':'')+' data-say="'+esc('Opening '+o.n+' in cmux…')+'">'+l+'</button>';
return'<button class="act" type="button" data-launch="'+k+'" data-k="'+k+'"'+dmark(k,o)+' title="'+l+'" aria-label="'+l+'" data-folder="'+esc(o.f)+'" data-phrase="'+esc(p)+'" data-say="'+esc(say)+'">'+l+'</button>'}
/* the cmux extra's desk: open a session for the thread, or close the project's */
function deskReq(o,v){var q={verb:v,zone:o.dk[0],project:o.dk[1]};if(o.dk[2])q.thread=o.dk[2];return q}
function desk(o,v){return esc(JSON.stringify(deskReq(o,v)))}
/* data-k names the app, so Garrick.app can draw the button as its icon, as its menu bar does; data-d marks the default */
function dmark(k,o){var d=GarrickPrefs.def();if(!d||!o.f||chosen().indexOf(d)<0)d='note';return k===d?' data-d':''}
function acts(o){var a=prefs().note===false?'':'<a class="act" href="'+esc(o.u)+'" data-k="note"'+dmark('note',o)+' title="Open the note" aria-label="Open the note">Open</a>';
if(o.f&&host)chosen().forEach(function(k){a+=launch(k,o)});
/* the phrase to copy only where nothing opens it: a browser, or a host with no app offered */
if(o.w&&!(o.f&&host&&chosen().length))a+=copy('open '+o.w);return'<div class="gacts">'+a+'</div>'}
/* a thread by its note (pa), or a project by its name (pp), its hub then holding every thread in it */
function park(o){var s=o.h?o.hp:o.s,v=s?'wake':'park',q=o.h?{verb:v,zone:o.pp[0],project:o.pp[1]}:{verb:v,zone:o.pa[0],file:o.pa[1]},
k=o.h?o.pp[0]+'/'+o.pp[1]+'/'+o.pp[1]+'.md':o.pa[0]+'/'+o.pa[1];
return'<button class="act pflip" type="button" data-act="'+esc(JSON.stringify(q))+'" data-expect="'+esc((s?'active:':'parked:')+k)
+'" data-say="'+(s?'Waking ':'Parking ')+esc(o.n)+'…"'+(o.h?' title="'+(s?'Wake':'Park')+' the project and every thread in it"':'')+'>'+(s?'Wake':'Park')+'</button>'}
function shut(o){return o.dk&&o.live&&host?'<button class="act pflip" type="button" data-act="'+desk(o,'close')+'"'+(o.f?' data-expect="'+esc('none:'+o.f)+'"':'')
+' data-say="Closing the session…">Close session</button>':''}
/* Park or Wake, beside the name: it acts in the app, and copies the phrase anywhere else;
   with a session open, Close session sits beside it */
function flip(o){var c=shut(o),f=pflip(o);return c&&f?'<span class="pbtns">'+c+f+'</span>':c||f}
function pflip(o){if(o.fin||o.held||o.pend||(o.h&&o.hp==null))return'';if(host&&(o.h?o.pp:o.pa))return park(o);if(!o.w)return'';
var s=o.h?o.hp:o.s,p=(s?'wake ':'park ')+o.w;
return'<button class="act pflip" type="button" data-copy="'+esc(p)+'" data-say="'+esc('Copied “'+p+'”. Paste it to your assistant.')+'" title="Copy “'+esc(p)+'”">'+(s?'Wake':'Park')+'</button>'}
function ago(d){return d===0?'today':d===1?'yesterday':d+' days ago'}
/* how long since the note moved, as a figure: age is not urgency, so nothing here reads as a fault */
function state(o){if(o.fin)return'Finished'+(o.d!=null?', updated '+ago(o.d):'');if(o.held)return'Parked with its project';if(o.pend)return'Woken with its project';if(o.s)return'Parked'+(o.d!=null?', updated '+ago(o.d):'');if(o.d==null)return'';
return'Last touched '+ago(o.d)}
/* the thread's resume point: the date its Resume here block gives, or that it has none */
function resume(o){if(o.r==null||o.s)return'';if(!o.r)return'No resume block';return o.rd!=null?'Resume point dated '+ago(o.rd):'Resume point not dated'}
function line(t,html){return t?'<div class="ink2 tline" style="margin-top:4px">'+(html?t:esc(t))+'</div>':''}
/* a row's card (row) leaves out the kind, zone and project: the section it sits in says the zone, the row above it the project;
   the graph's panel, which floats free of any list, keeps them */
function head(o,row){return'<div class="phead"><h4>'+esc(o.N||o.n)+'</h4>'+flip(o)+'</div>'+(row?'':'<div class="muted">'+esc([o.kl,o.z,o.p].filter(Boolean).join(' · '))+'</div>')
+(o.t&&o.t.length?'<div style="margin-top:4px">'+o.t.map(function(t){return'<span class="chip" style="margin:0 4px 0 0">'+esc(t)+'</span>'}).join('')+'</div>':'')
+line(state(o))+line(resume(o))+line(o.live?'<span class="live '+esc(o.live)+'"></span>Session open in cmux, '+esc(o.live):'',true)
+(window.GarrickManage?GarrickManage(o):'')}
/* what clicking a thread's name does, on its row or among what the search box found (.sres): its own link,
   unless Settings picked an app the Mac app can open it in */
document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('.thread .t>a,.sres .t>a');if(!a||!host)return;
var d=GarrickPrefs.def();if(!d||d==='note'||chosen().indexOf(d)<0)return;
var row=a.closest('.thread,.sres'),o;try{o=JSON.parse(row.dataset.card)}catch(x){return}if(!o.f)return;
e.preventDefault();e.stopPropagation();if(d==='cmux'&&o.dk){if(o.f&&window.GarrickExpect)GarrickExpect('live:'+o.f);host.postMessage({act:deskReq(o,'open')});return}
var q=d==='claude'&&cont(o);if(q){if(window.GarrickHeld&&GarrickHeld(q))return;if(!(window.GarrickAct&&GarrickAct(q,going(o)))){host.postMessage({act:q});if(window.GarrickSay)GarrickSay(going(o))}return}
host.postMessage({launch:d,folder:o.f,phrase:phrase(o)})},true);
return{esc:esc,acts:acts,head:head}})();
"""

JS = r"""
(function(){var root=document.documentElement,st={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
function theme(t){if(t==='auto')root.removeAttribute('data-theme');else root.setAttribute('data-theme',t);document.querySelectorAll('.seg button').forEach(function(b){b.classList.toggle('on',b.dataset.t===t)});st.set('garrick-status-theme',t)}
theme(st.get('garrick-status-theme')||'auto');document.querySelectorAll('.seg button').forEach(function(b){b.onclick=function(){theme(b.dataset.t)}});
var only=document.getElementById('only');only.checked=st.get('garrick-status-only')==='1';function apply(){var t=document.getElementById('tab-status')||document.body;t.classList.toggle('only',only.checked);st.set('garrick-status-only',only.checked?'1':'0')}only.onchange=apply;apply();
document.querySelectorAll('details[id]').forEach(function(d){var s=st.get('garrick-fold-'+d.id);if(s==='0')d.open=false;if(s==='1')d.open=true;d.addEventListener('toggle',function(){st.set('garrick-fold-'+d.id,d.open?'1':'0')})});
var h=(Date.now()-new Date(document.body.dataset.built))/36e5,el=document.getElementById('age');if(el)el.textContent=h<1?Math.max(1,Math.round(h*60))+' min ago':h<48?Math.round(h)+' h ago':Math.round(h/24)+' days ago';
if(h>36){var s=document.getElementById('stale');s.style.display='block';s.textContent='Built '+Math.round(h)+' hours ago, so it may be out of date. Run status.py again to refresh it.'}
var tip=document.getElementById('tip');function show(e){var t=e.target.closest&&e.target.closest('[data-tip]');if(!t){tip.style.opacity=0;return}tip.textContent=t.dataset.tip;tip.style.opacity=1;
var r=t.getBoundingClientRect(),x=e.type==='focusin'?r.left+r.width/2:e.clientX,y=e.type==='focusin'?r.top:e.clientY,w=tip.offsetWidth;tip.style.left=Math.min(innerWidth-w-8,Math.max(8,x-w/2))+'px';tip.style.top=(y-tip.offsetHeight-12)+'px'}
document.addEventListener('mousemove',show);document.addEventListener('focusin',show);document.addEventListener('scroll',function(){tip.style.opacity=0},true);
var toast=document.getElementById('toast');function say(s){toast.textContent=s;toast.style.opacity=1;clearTimeout(say.t);say.t=setTimeout(function(){toast.style.opacity=0},2600)}
/* In Garrick.app the app copies, opens cmux and rebuilds; in a browser
   the page copies and nothing else. */
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
if(!host)document.body.classList.add('nohost');      /* a browser cannot act: its action buttons stay hidden */
function put(text){if(host){host.postMessage({copy:text});return Promise.resolve()}
if(navigator.clipboard&&window.isSecureContext){return navigator.clipboard.writeText(text)}var a=document.createElement('textarea');a.value=text;a.style.position='fixed';a.style.opacity=0;document.body.appendChild(a);a.select();try{document.execCommand('copy')}finally{document.body.removeChild(a)}return Promise.resolve()}
window.GarrickCopy=put;window.GarrickSay=say;      /* what HOME_JS copies the thought with, and says it in */
var rb=document.getElementById('rebuild');if(host&&rb){rb.removeAttribute('data-copy');rb.title='Rebuild the page now';
rb.onclick=function(){host.postMessage({rebuild:true});say('Rebuilding…')}}
document.addEventListener('click',function(e){var t=e.target.closest?e.target:null;if(!t)return;
/* An action (the page's or the desk's): the app runs page_action.py, then rebuilds the page.
   One with data-confirm asks for a second click within four seconds; one with data-expect
   keeps the page rebuilding until what it asked for shows (RELOAD_JS). */
var x=t.closest('button[data-act]');if(x){if(!host)return;var r;try{r=JSON.parse(x.dataset.act)}catch(err){return}
if(window.GarrickHeld&&GarrickHeld(r))return;   /* its zone still busy with another (WORK_JS) */
if(x.dataset.confirm&&!x.classList.contains('armed')){var was=x.textContent;x.classList.add('armed');x.textContent=x.dataset.confirm;
setTimeout(function(){x.classList.remove('armed');x.textContent=was},4000);return}
x.classList.remove('armed');if(x.dataset.expect&&window.GarrickExpect)GarrickExpect(x.dataset.expect);
if(window.GarrickAct&&GarrickAct(r,x.dataset.say))return;host.postMessage({act:r});say(x.dataset.say);return}
var c=t.closest('button[data-launch]');if(c&&host){var m={launch:c.dataset.launch,folder:c.dataset.folder,phrase:c.dataset.phrase||''};
if(m.launch==='cmux'){m.cmux=m.folder;m.copy=m.phrase}   /* an app built before 0.5.0 knows only this form */
host.postMessage(m);say(c.dataset.say);return}
var b=t.closest('button[data-copy]');if(b)put(b.dataset.copy).then(function(){say(b.dataset.say)},function(){say(b.dataset.copy)})});
/* The Todo list's + button (in the app): Garrick's dialog opens on
   that zone, and the app runs page_action.py with the request, then rebuilds. */
document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('.tadd-open[data-zone]');if(a&&window.TaddOpen)TaddOpen(a.dataset.zone)});
window.TaddSend=function(z,target,date,text){if(!host)return;var q={verb:'todo-add',zone:z,target:target,date:date,text:text},s='Adding to '+z+': '+text.slice(0,60)+'…';
if(!(window.GarrickAct&&GarrickAct(q,s))){host.postMessage({act:q});say(s)}
if(window.TodoPending)TodoPending(z,target,date,text)};
/* A project's threads fold under its row on the Threads card; the fold is remembered. */
function chev(b){var box=document.getElementById(b.dataset.sub);if(!box)return;
function set(o){box.hidden=!o;b.setAttribute('aria-expanded',o?'true':'false')}set(st.get('garrick-fold-'+b.dataset.sub)==='1');
b.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();var o=box.hidden;set(o);st.set('garrick-fold-'+b.dataset.sub,o?'1':'0')})}
document.querySelectorAll('.pchev').forEach(chev);
/* Tabs, when the Todo list is on: one open at a time, remembered in this window. */
var tabSecs=document.querySelectorAll('main>section.tab'),tabBtns=document.querySelectorAll('.tabs [data-tab]');
window.StatusTab=function(n){if(!document.getElementById('tab-'+n))n='overview';
if(n==='guide'&&window.GarrickGuide)GarrickGuide.mount();       /* the Guide's pages go on the page the first time it opens */
tabSecs.forEach(function(sec){sec.hidden=sec.id!=='tab-'+n});document.body.dataset.tab=n;
tabBtns.forEach(function(b){var on=b.dataset.tab===n;b.classList.toggle('on',on);b.setAttribute('aria-selected',on?'true':'false')});
try{localStorage.setItem('garrick-tab',n)}catch(e){}window.dispatchEvent(new Event('resize'))};
tabBtns.forEach(function(b){b.onclick=function(){StatusTab(b.dataset.tab)}});
var tSaved=null;try{tSaved=localStorage.getItem('garrick-tab')}catch(e){}StatusTab(tSaved||'overview');
/* a sidebar link opens the tab its section is in, wherever the card has been moved; a link into
   the Guide shows its page first (GUIDE_JS), so it never leaves the page in any host */
document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('a[href^="#"]');if(!a||a.getAttribute('href')==='#')return;
var id=a.getAttribute('href').slice(1),el=(window.GarrickGuide&&GarrickGuide.reveal(id))||document.getElementById(id),sec=el&&el.closest('section.tab');if(!sec)return;
StatusTab(sec.id.slice(4));if(!a.closest('nav')){e.preventDefault();var c=el.closest('details');if(c)c.open=true;el.scrollIntoView({block:'start'})}},true);
/* Settings: a modal dialog sits above the page, so the toast moves into it
   while it is open, or nothing it copies would say so. The app's Settings…
   (⌘,) calls StatusSettings.open(). */
var sd=document.getElementById('settings');
function sdShut(){sd.close()}
var sdChanged=false,lpChanged=false;sd.addEventListener('change',function(){sdChanged=true});
/* leaving Settings after a change rebuilds the page in the app, so what was chosen shows at once; a change
   to the apps or the zones is saved for every viewer first, through page_action.py, which rebuilds the page after it */
sd.addEventListener('close',function(){document.body.appendChild(toast);if(!sdChanged||!host)return;
/* Notifications that would be refused stay in the dialog, unsent, with the reason, rather than lost to a rebuild */
var N=window.GarrickNotify,bad=N&&N.changed()&&N.problem();if(bad){say(bad+' Nothing was saved yet.');return}
sdChanged=false;var q=sdReq();if(q)host.postMessage({act:q});else host.postMessage({rebuild:true})});
/* What Settings has to save, as one request: the apps, the zones, the notifications, While you wait, each only when it changed,
   or, with `all` (a test of a channel, NOTIFY_JS), a request whatever changed. null when there is nothing. */
function sdReq(all){var N=window.GarrickNotify,n=!!(N&&N.changed()),W=window.GarrickWait,w=!!(W&&W.changed());if(!(lpChanged||zChanged||n||w||all))return null;
var q=lpChanged?GarrickPrefs.request():{verb:'settings'};if(zChanged)q.zones=zreq();if(n)q.notifications=N.request();
if(w){q['while-you-wait']=W.request();W.saved()}
lpChanged=zChanged=false;if(n)N.saved();return q}
window.GarrickSettingsReq=sdReq;
sd.addEventListener('click',function(e){if(e.target!==sd)return;var r=sd.getBoundingClientRect();   /* the backdrop, not the padding */
if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)sdShut()});
window.StatusSettings={open:function(){if(sd.open)return;sd.appendChild(toast);sd.showModal()}};
document.getElementById('open-settings').onclick=window.StatusSettings.open;
document.getElementById('close-settings').onclick=sdShut;
function lprefs(){return GarrickPrefs.launchers()}
function dpref(){return GarrickPrefs.def()}
function radios(){sd.querySelectorAll('input[name="garrick-default"]').forEach(function(r){var c=sd.querySelector('input[data-launcher="'+r.value+'"]');
r.disabled=!c||c.disabled||!c.checked;r.checked=r.value===dpref()});if(!sd.querySelector('input[name="garrick-default"]:checked')){var n=sd.querySelector('input[value="note"]');if(n)n.checked=true}}
sd.querySelectorAll('input[name="garrick-default"]').forEach(function(r){r.onchange=function(){GarrickPrefs.set(lprefs(),r.value);lpChanged=true;
say('Clicking a thread now: '+r.closest('.launcher-row').querySelector('span').firstChild.textContent.trim()+'.')}});
sd.querySelectorAll('input[data-launcher]').forEach(function(c){c.checked=!c.disabled&&lprefs()[c.dataset.launcher]!==false;
c.onchange=function(){var p=lprefs();p[c.dataset.launcher]=c.checked;GarrickPrefs.set(p,!c.checked&&dpref()===c.dataset.launcher?'note':dpref());lpChanged=true;radios();
say((c.checked?'Showing ':'Hiding ')+c.parentNode.querySelector('span').firstChild.textContent.trim()+'.')}});radios();
/* Settings › Zones: each row draws its zone as chosen; every zone's choice goes with the request when Settings closes */
var zChanged=false,zIcons={};try{zIcons=JSON.parse(document.getElementById('zone-icons').textContent)}catch(e){}
function zpick(r,k){return r.querySelector(k).value}
sd.querySelectorAll('.zrow').forEach(function(r){r.querySelectorAll('select').forEach(function(s){s.onchange=function(){zChanged=true;
var c=zpick(r,'.zcol'),p=r.querySelector('.zprev');p.className='zprev'+(c?' zc zc-'+c.toLowerCase():'');p.innerHTML=zIcons[zpick(r,'.zico')]||'';
p.appendChild(document.createTextNode(r.dataset.zone))}})});
/* Each choice is a button over a palette: the palette sets the hidden select and runs its onchange */
function zface(b,s){var v=s.value,o=s.options[s.selectedIndex],ico=s.classList.contains('zico');
b.innerHTML=(ico?(zIcons[v]||'<i class="znone"></i>'):(v?'<i class="zsw" style="background:var(--zc-'+v.toLowerCase()+')"></i>':'<i class="zsw znone"></i>'))+'<span></span>';
b.lastChild.textContent=o?o.textContent:''}
function zshut(except){sd.querySelectorAll('.zpop').forEach(function(p){if(p!==except&&!p.hidden){p.hidden=true;p.previousSibling.setAttribute('aria-expanded','false')}})}
sd.querySelectorAll('.zpick').forEach(function(k){var s=k.querySelector('select'),b=k.querySelector('.zbtn'),p=k.querySelector('.zpop');
function mark(){p.querySelectorAll('.zcell').forEach(function(c){c.classList.toggle('on',c.dataset.v===s.value)})}mark();
b.onclick=function(e){e.stopPropagation();zshut(p);p.hidden=!p.hidden;b.setAttribute('aria-expanded',String(!p.hidden));if(!p.hidden){mark();var on=p.querySelector('.zcell.on')||p.querySelector('.zcell');on.focus()}};
p.onclick=function(e){var c=e.target.closest('.zcell');if(!c)return;e.stopPropagation();s.value=c.dataset.v;s.onchange();zface(b,s);mark();p.hidden=true;b.setAttribute('aria-expanded','false');b.focus()};
p.onkeydown=function(e){if(e.key==='Escape'){e.preventDefault();e.stopPropagation();p.hidden=true;b.setAttribute('aria-expanded','false');b.focus()}}});
sd.addEventListener('click',function(e){if(!e.target.closest('.zpick'))zshut(null)});
/* each "?" shows or hides its section's explanation where it stands */
sd.addEventListener('click',function(e){var q=e.target.closest('.qhelp'),p=q&&document.getElementById(q.getAttribute('aria-controls'));if(!p)return;
p.hidden=!p.hidden;q.setAttribute('aria-expanded',String(!p.hidden));var sec=q.closest('.setsec');if(sec)sec.classList.toggle('explained',!p.hidden)});
/* a row's own line shows with its section's explanation; until then it is the row's tooltip, read as it stands (some lines change) */
sd.addEventListener('mouseover',function(e){var r=e.target.closest('.launcher-row,.setlink,.flagrow'),m=r&&r.querySelector('small');
if(!m||!m.textContent.trim())return;if(!('tip0' in r.dataset))r.dataset.tip0=r.getAttribute('title')||'';r.title=m.textContent.trim()+(r.dataset.tip0?' '+r.dataset.tip0:'')});
function zreq(){var o={};sd.querySelectorAll('.zrow').forEach(function(r){var s={},c=zpick(r,'.zcol'),i=zpick(r,'.zico');if(c)s.color=c;if(i)s.icon=i;o[r.dataset.zone]=s});return o}
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
if(tRow)tRow.classList.remove('on');tRow=row;row.classList.add('on');tc.innerHTML=Panel.head(o,1)+Panel.acts(o);tc.setAttribute('aria-label',o.n);
row.parentNode.insertBefore(tc,row.nextSibling)}tc.hidden=false;tPlace()}
function tClose(){clearTimeout(tShow);clearTimeout(tHide);if(tRow)tRow.classList.remove('on');tRow=null;tc.hidden=true;dark()}
function tLater(){clearTimeout(tShow);clearTimeout(tHide);tHide=setTimeout(tClose,220)}
/* the row's node in the graph, lit while the row is hovered or has the focus (#62); GarrickGraph is there only with the graph */
function light(row){var g=window.GarrickGraph,o;if(!g)return;try{o=JSON.parse(row.dataset.card)}catch(x){return}g.focus(o.u)}
function dark(){if(window.GarrickGraph)GarrickGraph.focus(null)}
/* a row whose todo or check list is open (TCHIP_JS) keeps its card shut, so the list can be read and ticked */
function listing(row){return!!row.querySelector('.tpop:not([hidden])')}
function bindRow(row){
row.addEventListener('mouseenter',function(){light(row);clearTimeout(tHide);clearTimeout(tShow);if(listing(row)||tRow===row&&!tc.hidden)return;tShow=setTimeout(function(){tOpen(row)},tRow&&!tc.hidden?350:150)});
row.addEventListener('mouseleave',function(){dark();tLater()});
row.addEventListener('focusin',function(){light(row);if(tQuiet){tQuiet=false;return}if(listing(row))return;tOpen(row)});
row.addEventListener('click',function(e){if(e.target.closest('a,button,.tpop'))return;if(tRow===row&&!tc.hidden)tClose();else tOpen(row)})}
document.querySelectorAll('.thread[data-card]').forEach(bindRow);
tc.addEventListener('mouseenter',function(){clearTimeout(tHide);clearTimeout(tShow)});tc.addEventListener('mouseleave',tLater);
document.addEventListener('focusin',function(e){if(tRow&&!tRow.contains(e.target)&&!tc.contains(e.target))tClose()});
document.addEventListener('keydown',function(e){if(e.key!=='Escape'||!tRow)return;var r=tRow,back=tc.contains(document.activeElement);tClose();
if(back){var a=r.querySelector('a');if(a){tQuiet=true;a.focus()}}});
window.addEventListener('scroll',function(){if(tRow)requestAnimationFrame(tPlace)},{passive:true});window.addEventListener('resize',function(){if(tRow)tPlace()});
/* what PARK_JS needs of the list: a row's card and fold, bound as these are */
window.ThreadRows={bind:bindRow,chev:chev,close:tClose};
})();
"""


# Settings › Notifications (#110), in the app: the form under More options
# read into the shape notifications.py keeps, sent with what else Settings
# changed when it closes (JS's sdReq), and "Send a test", which saves first
# and names one channel. The simple view above it drives that form: a change
# there is written into More options as notifications.py's from_simple()
# says, mirrored here (simpleOf, fromSimple), so More options always shows
# what will be saved, and the request is built from More options alone. A
# form the simple view cannot say is custom (the section's data-custom, from
# is_simple(), then worked out again here whenever More options changes):
# the simple view then writes nothing until "Use the simple choices". The
# minutes and the quiet hours are one setting each, shown once or kept in
# step, so they always apply. Telegram's Set up… saves the token, or finds
# the chat, through page_action.py, saving the rest first as a test does:
# the token goes in that one request and nowhere else, and the field is
# emptied as it goes. The app rebuilds the page after a request, so these
# reopen Settings at this section and show the reply they kept in this
# window's sessionStorage, which never holds the request.
# Runs after WORK_JS, so it wraps the GarrickActed every other script set.
NOTIFY_JS = r"""
(function(){var sec=document.getElementById('notify-settings');if(!sec)return;
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick,changed=false,
CHAT=/^(?:-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$/,TOKEN=/^\d{3,20}:[A-Za-z0-9_-]{20,100}$/,S=null,custom=sec.dataset.custom==='1';
try{S=JSON.parse(sec.dataset.simple||'null')}catch(x){}
function val(id){var e=document.getElementById(id);return e?e.value.trim():''}
function on(k){var c=sec.querySelector('[data-nch="'+k+'"]');return!!(c&&c.checked)}
function say(s){if(window.GarrickSay)GarrickSay(s)}
/* a channel switched off greys its column; in each zone's row its box is hidden, kept for when it comes back on */
function paint(){['mac','telegram','command'].forEach(function(k){
sec.querySelectorAll('[data-nto="'+k+'"]').forEach(function(c){var cell=c.closest('td');if(cell)cell.classList.toggle('noff',!on(k))});
sec.querySelectorAll('[data-nzto="'+k+'"]').forEach(function(c){var l=c.closest('label');if(l)l.hidden=!on(k)})});
sec.querySelectorAll('[data-nzchat]').forEach(function(t){t.hidden=!on('telegram')})}
function request(){var ch={};sec.querySelectorAll('[data-nch]').forEach(function(c){ch[c.dataset.nch]=c.checked});
var ev={};sec.querySelectorAll('tr[data-nev]').forEach(function(r){var e={to:[],quiet:r.querySelector('[data-nq]').value};
r.querySelectorAll('[data-nto]').forEach(function(c){if(c.checked)e.to.push(c.dataset.nto)});
var a=r.querySelector('[data-naway]');if(a)e.away=a.checked;
var f=r.querySelector('[data-nafter]');if(f)e.after=Math.max(0,Math.min(240,parseInt(f.value,10)||0));ev[r.dataset.nev]=e});
var zs={};sec.querySelectorAll('.nzone').forEach(function(r){var z={to:[]};r.querySelectorAll('[data-nzto]').forEach(function(c){if(c.checked)z.to.push(c.dataset.nzto)});
var t=r.querySelector('[data-nzchat]');if(t&&t.value.trim())z.chat=t.value.trim();zs[r.dataset.zone]=z});
var qt=document.getElementById('n-quiet');
return{channels:ch,telegram:{chat:val('n-chat')},command:val('n-cmd'),events:ev,
quiet:{on:!!(qt&&qt.checked),from:val('n-from')||'22:00',to:val('n-to')||'07:00'},zones:zs}}
/* what notifications.py's clean() would refuse, said before anything is sent */
function problem(){var r=request(),chats=[r.telegram.chat];Object.keys(r.zones).forEach(function(z){chats.push(r.zones[z].chat||'')});
for(var i=0;i<chats.length;i++)if(chats[i]&&!CHAT.test(chats[i]))return'A Telegram chat ID is a number, such as 123456789, or -100 and a number for a group.';
if(r.channels.telegram&&!chats.some(Boolean))return'Telegram needs a chat ID to send to, or switch it off.';
if(r.channels.command&&!r.command)return'Name the command to run, or switch it off.';return''}
/* the simple view, as notifications.py's simple_choices(), from_simple() and is_simple() say */
function tracked(ch){var t=S.send.filter(function(c){return!!ch[c]});return t.length?t:['mac']}
function simpleOf(r){var tr=tracked(r.channels),t={};S.tell.forEach(function(e){var x=r.events[e];t[e]=!!x&&tr.some(function(c){return x.to.indexOf(c)>=0})});
return{send:{mac:!!r.channels.mac,telegram:!!r.channels.telegram},tell:t,after:r.events.finished?r.events.finished.after:2,quiet:r.quiet}}
function fromSimple(s,r){var o=JSON.parse(JSON.stringify(r)),c=o.channels;c.mac=!!s.send.mac;c.telegram=!!s.send.telegram&&!!o.telegram.chat;
if('cmux' in c)c.cmux=c.mac;c.command=false;var tr=tracked(c);
Object.keys(o.events).forEach(function(k){var e=o.events[k],want=S.tell.indexOf(k)>=0?!!s.tell[k]:S.follow.indexOf(k)>=0;
e.to=S.channels.filter(function(x){return tr.indexOf(x)>=0?want:e.to.indexOf(x)>=0});if(S.quiet[k])e.quiet=S.quiet[k];if('away' in e)e.away=false;
if('after' in e)e.after=s.after});o.quiet=s.quiet;Object.keys(o.zones).forEach(function(z){o.zones[z]={to:S.channels.slice()}});return o}
function stable(v){return JSON.stringify(v,function(k,x){if(x&&typeof x==='object'&&!Array.isArray(x)){var o={};Object.keys(x).sort().forEach(function(j){o[j]=x[j]});return o}return x})}
function isSimple(r){return stable(fromSimple(simpleOf(r),r))===stable(r)}
function sbox(a){return sec.querySelector('.nsimple [data-'+a+']')}
function readSimple(){var t={};S.tell.forEach(function(e){var b=sbox('nt="'+e+'"');t[e]=!!(b&&b.checked)});
var r=request();return{send:{mac:!!(sbox('ns="mac"')||{}).checked,telegram:!!(sbox('ns="telegram"')||{}).checked},tell:t,
after:Math.max(0,Math.min(240,parseInt(val('n-safter'),10)||0)),quiet:r.quiet}}
function showSimple(s){['mac','telegram'].forEach(function(k){var b=sbox('ns="'+k+'"');if(b)b.checked=s.send[k]});
S.tell.forEach(function(e){var b=sbox('nt="'+e+'"');if(b)b.checked=s.tell[e]});var a=document.getElementById('n-safter');if(a)a.value=s.after}
/* the advanced form set to a full set of settings, as request() reads it back */
function write(r){sec.querySelectorAll('[data-nch]').forEach(function(c){c.checked=!!r.channels[c.dataset.nch]});
sec.querySelectorAll('tr[data-nev]').forEach(function(row){var e=r.events[row.dataset.nev];if(!e)return;
row.querySelectorAll('[data-nto]').forEach(function(c){c.checked=e.to.indexOf(c.dataset.nto)>=0});
var q=row.querySelector('[data-nq]');if(q)q.value=e.quiet;var a=row.querySelector('[data-naway]');if(a)a.checked=!!e.away;
var f=row.querySelector('[data-nafter]');if(f&&'after' in e)f.value=e.after});
sec.querySelectorAll('.nzone').forEach(function(row){var z=r.zones[row.dataset.zone]||{};
row.querySelectorAll('[data-nzto]').forEach(function(c){c.checked=!z.to||z.to.indexOf(c.dataset.nzto)>=0});
var t=row.querySelector('[data-nzchat]');if(t)t.value=z.chat||''});paint()}
function setCustom(c){custom=c;var p=document.getElementById('n-custom');if(p)p.hidden=!c}
function tgpanel(open){var p=document.getElementById('n-tgset');if(!p)return;p.hidden=!open;
sec.querySelectorAll('[data-ntgopen]').forEach(function(b){b.setAttribute('aria-expanded',String(open))});if(open){var t=p.querySelector('[data-nfind]:not([disabled])')||document.getElementById('n-token');if(t)t.focus()}}
/* a change in the simple view goes into More options, unless the settings are custom; the minutes always do */
function simpleChanged(t){changed=true;
if(t.matches('[data-ns="telegram"]')&&t.checked&&!val('n-chat')){t.checked=false;tgpanel(true);say('Set up Telegram first: two steps, below.');return}
var f=sec.querySelector('[data-nafter]');if(t.id==='n-safter'&&f)f.value=Math.max(0,Math.min(240,parseInt(t.value,10)||0));
if(!custom&&S)write(fromSimple(readSimple(),request()))}
/* a change in More options: the simple view shows what it now says, and whether it can say all of it */
function moreChanged(t){changed=true;paint();if(!S)return;var r=request();if(t.matches('[data-nafter]')){var a=document.getElementById('n-safter');if(a)a.value=r.events.finished.after}
showSimple(simpleOf(r));setCustom(!isSimple(r))}
sec.addEventListener('change',function(e){var t=e.target;if(t.id==='n-token')return;
if(t.closest('.nsimple'))simpleChanged(t);else if(t.closest('.nmore'))moreChanged(t);else changed=true;paint()});
sec.addEventListener('input',function(e){if(e.target.matches('input[type=text],input[type=number],input[type=time]'))changed=true});
/* one request to page_action.py: what Settings would save, the notifications as they stand, and `more`, then the reply after the rebuild */
function nact(more,said){if(!host)return;var bad=problem();if(bad){say(bad);return}
var q=window.GarrickSettingsReq&&GarrickSettingsReq(true)||{verb:'settings'};
q.notifications=request();changed=false;
for(var k in more)q[k]=more[k];try{sessionStorage.setItem('garrick-reopen','notify-settings');if(!more.test)sessionStorage.setItem('garrick-ntg','1')}catch(x){}
host.postMessage({act:q});say(said)}
function ntest(ch){nact({test:ch},'Saving, then sending a test…')}
sec.addEventListener('click',function(e){var b=e.target.closest('[data-ntest]');if(b){e.preventDefault();ntest(b.dataset.ntest);return}
if(e.target.closest('[data-ntgopen]')){e.preventDefault();var p=document.getElementById('n-tgset');tgpanel(!!(p&&p.hidden));return}
if(e.target.closest('[data-ntok]')){e.preventDefault();var t=document.getElementById('n-token'),v=t?t.value.trim():'';if(t)t.value='';
if(!TOKEN.test(v)){say('That is not a bot token: BotFather gives one such as 123456789:AA…');return}nact({token:v},'Keeping the token in the keychain…');return}
if(e.target.closest('[data-nfind]')){e.preventDefault();nact({'find-chat':true},'Looking for your chat…');return}
if(e.target.closest('#n-usesimple')){e.preventDefault();write(fromSimple(readSimple(),request()));setCustom(false);changed=true;say('Using the simple choices. Close Settings to save them.')}});
/* the reply, kept across the rebuild it brings, shown under the section: only what page_action.py said, never what was sent */
function said(){var s=null;try{s=JSON.parse(sessionStorage.getItem('garrick-ntest')||'null')}catch(x){}
var p=document.getElementById('n-said');if(!p||!s)return;p.hidden=false;p.textContent=s.say;p.classList.toggle('bad',!s.ok)}
var was=window.GarrickActed;window.GarrickActed=function(q,a){if(q&&q.verb==='settings'&&(q.test||q.token||q['find-chat'])){
if(q.token)q.token='';      /* the host hands the request back: the token goes no further than this */
try{sessionStorage.setItem('garrick-ntest',JSON.stringify({ok:!!(a&&a.ok),say:(a&&a.say)||''}))}catch(x){}said()}
return was?was.apply(this,arguments):undefined};
var back=null,tg=null;try{back=sessionStorage.getItem('garrick-reopen');sessionStorage.removeItem('garrick-reopen');tg=sessionStorage.getItem('garrick-ntg');sessionStorage.removeItem('garrick-ntg')}catch(x){}
if(back&&window.StatusSettings){StatusSettings.open();sec.scrollIntoView({block:'start'});said();
var s=null;try{s=JSON.parse(sessionStorage.getItem('garrick-ntest')||'null')}catch(x){}if(tg&&!(s&&s.ok&&sec.querySelector('.ntgok')))tgpanel(true)}
else{try{sessionStorage.removeItem('garrick-ntest')}catch(x){}}
paint();
window.GarrickNotify={changed:function(){return changed},request:request,problem:problem,saved:function(){changed=false}};
})();
"""


# ---- Settings › While you wait (#111) ------------------------------------------
# One block, kept apart from the rest of Settings: what the Garrick band offers
# while a long turn runs. System/tools/next_up.py owns the keys, their defaults
# and their check; this block only draws them and reads the form back. The
# page sends them with what else Settings changed when it closes (JS's sdReq
# asks window.GarrickWait), and page_action.py checks them through the same
# module before they are kept in System/garrick-settings.json.
_WAIT: Dict[Path, object] = {}


def wait_lib(ws: Path):
    """System/tools/next_up.py, found as notify_lib() finds its module. None
    when there is none, and then the section is left out."""
    key = Path(ws)
    if key not in _WAIT:
        found = None
        for src in (key / "System" / "tools" / "next_up.py", Path(__file__).resolve().parent.parent / "tools" / "next_up.py",
                    Path(__file__).resolve().parent.parent.parent / "template" / "System" / "tools" / "next_up.py"):
            if not src.is_file():
                continue
            try:
                spec = importlib.util.spec_from_file_location("garrick_status_next_up", str(src))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                continue
            if callable(getattr(mod, "settings", None)) and hasattr(mod, "SOURCE_LABELS"):
                found = mod
                break
        _WAIT[key] = found
    return _WAIT[key]


def wait_settings(ws: Path) -> str:
    """Settings › While you wait: on or off, how long a turn runs before the
    band offers anything, same zone only, which sources count and in what
    order, and when a parked or an unwrapped thread is old enough to name.
    In the app only, as the other sections that save are."""
    lib = wait_lib(ws)
    if lib is None:
        return ""
    cfg = lib.settings(ws)
    box = lambda attr, on, label="": '<input type="checkbox" %s%s%s>' % (
        attr, " checked" if on else "", ' aria-label="%s"' % E(label) if label else "")
    num = lambda key, value, low, high, label: (
        '<input type="number" data-wnum="%s" min="%d" max="%d" value="%d" aria-label="%s">' % (key, low, high, value, E(label)))
    order = list(cfg["sources"]) + [s for s in lib.SOURCES if s not in cfg["sources"]]
    rows = "".join(
        '<li class="wsrc" data-wsrc="%s"><label>%s %s</label><span class="wmove">'
        '<button class="act" type="button" data-wup aria-label="Move %s up" title="Earlier">&#8593;</button>'
        '<button class="act" type="button" data-wdown aria-label="Move %s down" title="Later">&#8595;</button></span></li>'
        % (s, box("data-won", s in cfg["sources"], lib.SOURCE_LABELS[s]), E(lib.SOURCE_LABELS[s]), E(lib.SOURCE_LABELS[s]),
           E(lib.SOURCE_LABELS[s])) for s in order)
    return ('<section class="setsec apponly" id="wait-settings">%s%s'
            '<div class="launcher-row"><label class="launcher-choice">%s <span>Suggest something while a turn runs'
            '<small>One line in the Garrick band, once a turn has run longer than this</small></span></label>'
            '<span class="wafter">%s seconds</span></div>'
            '<div class="launcher-row"><label class="launcher-choice">%s <span>Same zone only'
            '<small>Only what is in the zone the session works in; off, every zone</small></span></label></div>'
            '<h4 class="nsub">What counts, first to last</h4><ol class="wsrcs">%s</ol>'
            '<div class="launcher-row"><span class="wdays">A parked thread untouched for %s days, a live one not wrapped for %s days'
            '</span></div></section>'
            % (set_head("While you wait", "wait"), help_text("wait", 'While a turn runs longer than the threshold, the Garrick '
               'band shows one thing worth doing elsewhere: the top of the interruption stack, a Todo line due today or late, a chase '
               'that has come due, what waits in an Inbox, a parked thread to park or finish, a live one to wrap. It is said in a few '
               'words, never quotes a meeting and never names the thread the turn is working on. <code>/garrick next</code>, '
               '<code>open</code>, <code>tick</code> and <code>later</code> act on it, and none of them touches the running session. '
               'In a session without the band, ask &#8220;what&#39;s next&#8221;: the answer comes from the same list, '
               '<code>python3 System/tools/next_up.py</code>. Saved in <code>%s</code>.' % E(prefs().FILE)),
               box('id="w-on"', cfg["on"]), num("threshold", cfg["threshold"], lib.THRESHOLD[0], lib.THRESHOLD[1],
                                                 "Seconds a turn runs first"),
               box('id="w-zone"', cfg["same-zone"]), rows,
               num("parked-days", cfg["parked-days"], lib.DAYS[0], lib.DAYS[1], "Days a parked thread is left alone"),
               num("wrap-days", cfg["wrap-days"], lib.DAYS[0], lib.DAYS[1], "Days since a live thread was wrapped")))


WAIT_CSS = r"""
/* Settings › While you wait: the switches, then the sources in their order, each with a box and two arrows */
#wait-settings input[type=number]{font:inherit;font-size:12.5px;width:56px;padding:2px 5px;color:var(--ink);background:var(--surface);
border:1px solid var(--line);border-radius:7px}
#wait-settings .wafter,#wait-settings .wdays{font-size:12.5px;color:var(--ink2)}
.wsrcs{list-style:none;margin:0 0 6px;padding:0}.wsrc{display:flex;align-items:center;gap:8px;padding:3px 0;border-bottom:1px solid var(--line);font-size:12.5px}
.wsrc label{flex:1;display:flex;align-items:center;gap:6px}.wsrc input{accent-color:var(--accent)}.wsrc.woff label{opacity:.5}
.wmove{display:flex;gap:3px}.wmove .act{padding:0 6px;min-width:0;line-height:20px}
"""

# Read back as next_up.py's clean() takes it. A number out of range is brought
# into range here, so nothing the form can hold is refused when Settings closes.
WAIT_JS = r"""
(function(){var sec=document.getElementById('wait-settings');if(!sec)return;var changed=false,list=sec.querySelector('.wsrcs');
function paint(){list.querySelectorAll('.wsrc').forEach(function(r,i,all){r.classList.toggle('woff',!r.querySelector('[data-won]').checked);
r.querySelector('[data-wup]').disabled=i===0;r.querySelector('[data-wdown]').disabled=i===all.length-1})}
sec.addEventListener('change',function(){changed=true;paint()});
sec.addEventListener('input',function(e){if(e.target.matches('input[type=number]'))changed=true});
sec.addEventListener('click',function(e){var b=e.target.closest('[data-wup],[data-wdown]');if(!b)return;e.preventDefault();var r=b.closest('.wsrc');
if(b.hasAttribute('data-wup')&&r.previousElementSibling)list.insertBefore(r,r.previousElementSibling);
else if(b.hasAttribute('data-wdown')&&r.nextElementSibling)list.insertBefore(r.nextElementSibling,r);else return;
changed=true;paint();b.focus();var d=document.getElementById('settings');if(d)d.dispatchEvent(new Event('change'))});
function n(k){var e=sec.querySelector('[data-wnum="'+k+'"]'),v=parseInt(e.value,10);if(isNaN(v))v=parseInt(e.defaultValue,10);
return Math.max(+e.min,Math.min(+e.max,v))}
function request(){var src=[];list.querySelectorAll('.wsrc').forEach(function(r){if(r.querySelector('[data-won]').checked)src.push(r.dataset.wsrc)});
return{on:document.getElementById('w-on').checked,threshold:n('threshold'),'same-zone':document.getElementById('w-zone').checked,
sources:src,'parked-days':n('parked-days'),'wrap-days':n('wrap-days')}}
paint();
window.GarrickWait={changed:function(){return changed},request:request,saved:function(){changed=false}};
})();
"""
# ---- end of Settings › While you wait ---------------------------------------------


# Park and Wake land on the threads list at once, with no wait for the
# rebuild: Garrick.app and the Obsidian plugin hand page_action.py's reply to
# window.GarrickActed, and a request that was done moves its row. It runs
# after JS, whose rows it moves and binds through window.ThreadRows.
PARK_JS = r"""
(function(){var R=window.ThreadRows||{bind:function(){},chev:function(){},close:function(){}};
/* Park and Wake land on the list at once. When the host says the request was done (window.GarrickActed, called by
   Garrick.app and the Obsidian plugin with the request and page_action.py's reply), the row moves to its zone's
   Parked fold or back, a project with every thread in it, its card says what it now is, and the counts follow.
   It stays greyed until the rebuild brings the real row; a reload of a page built before that moves it again. */
function cardOf(r){try{return JSON.parse(r.dataset.card)}catch(e){return null}}
function setCard(r,f){var c=cardOf(r);if(c){f(c);r.dataset.card=JSON.stringify(c)}}
function inFold(r){return!!r.closest('details.parked')}
function nameOf(el){var a=el.querySelector('.t>a');return a?a.textContent.toLowerCase():''}
/* by name, as the build lists them; a zone's live units stay above its Parked fold */
function place(box,el,tail){var kind=el.classList.contains('tunit')?'tunit':'thread',n=nameOf(el);
box.insertBefore(el,[].filter.call(box.children,function(x){return x.classList.contains(kind)&&x!==el&&nameOf(x)>n})[0]||tail||null)}
function fold(z,make){var f=[].filter.call(z.children,function(x){return x.matches('details.parked')})[0]||null;if(f||!make)return f;
var c=z.querySelector(':scope>summary>svg');f=document.createElement('details');f.className='parked tsort';f.id='parked-'+z.id.slice(5);
f.innerHTML='<summary>'+(c?c.outerHTML:'')+'Parked<span class="n">0</span></summary>';z.appendChild(f);return f}
function headOf(u){return u.querySelector(':scope>.thread.proj')}
function group(box,project){return[].filter.call(box.children,function(u){var h=u.classList.contains('tunit')&&headOf(u),c=h&&cardOf(h);return c&&c.n===project})[0]||null}
/* a project's row in the other list, its threads to follow: a copy of this one's */
function newGroup(src,box,tail){var u=document.createElement('div'),h=headOf(src).cloneNode(true),b=h.querySelector('.pchev'),s=document.createElement('div');
u.className='tunit';u.dataset.a=src.dataset.a;h.classList.remove('on');s.className='subthreads tsort';s.hidden=true;
s.id=/-parked$/.test(b.dataset.sub)?b.dataset.sub.replace(/-parked$/,''):b.dataset.sub+'-parked';b.dataset.sub=s.id;
u.appendChild(h);u.appendChild(s);place(box,u,tail);R.chev(b);R.bind(h);return u}
/* a project's row counts its threads; one with none left goes */
function recountUnit(u){var h=headOf(u),s=u.querySelector(':scope>.subthreads');if(!h||!s)return;var rs=s.querySelectorAll(':scope>.thread'),n=rs.length;if(!n){u.remove();return}
var bare=inFold(u)?0:[].filter.call(rs,function(r){var c=cardOf(r);return c&&c.r===0}).length,t=h.querySelector('.subn'),b=h.querySelector('.pchev');
var urg=inFold(u)?0:[].filter.call(rs,function(r){var c=cardOf(r);return c&&c.lt}).length;
if(t)t.textContent=n+' thread'+(n===1?'':'s')+(urg?' · '+urg+' needing a chase':'')+(bare?' · '+bare+' without a resume block':'');
if(b)b.title='Show its '+n+' thread'+(n===1?'':'s')}
/* a zone's line as the build writes it: live, those needing a chase (a row the
   build marked not ok, which is its next action's doing and never its age),
   and the done it counted */
function count(z,f,sel){return z.querySelectorAll(sel).length-(f?f.querySelectorAll(sel).length:0)}
function recount(){var live=0,held=0;document.querySelectorAll('.tview details.zone').forEach(function(z){var f=fold(z,false),
p=f?f.querySelectorAll('.thread:not(.proj)').length:0,l=count(z,f,'.thread:not(.proj)'),meta=z.querySelector(':scope>summary .meta');
live+=l;held+=p;if(meta){var a=count(z,f,'.thread:not(.proj)[data-ok="0"]'),d=/(\d+) done/.exec(meta.textContent);
meta.textContent=l+' live'+(a?' · '+a+' needing a chase':'')+(d?' · '+d[1]+' done':'')}
if(f){if(p)f.querySelector(':scope>summary .n').textContent=p;else f.remove()}
var none=z.querySelector(':scope>p.muted'),units=z.querySelectorAll(':scope>.tunit').length;
if(units&&none)none.remove();if(!units&&!none){none=document.createElement('p');none.className='muted';none.textContent='No live threads.';z.insertBefore(none,fold(z,false))}});
var g=document.querySelector('.tview .gsum'),v=document.querySelector('a.tile[href="#threads"] .val');
if(g)g.textContent=g.textContent.replace(/^\d+ live · \d+ parked/,live+' live · '+held+' parked');if(v)v.textContent=live}
function moved(q){if(!q||(q.verb!=='park'&&q.verb!=='wake'))return false;var park=q.verb==='park',byName=q.file==null,row=null,c=null;
[].forEach.call(document.querySelectorAll('.tview .thread[data-card]'),function(r){if(row||inFold(r)===park)return;var k=cardOf(r);if(!k)return;
if(byName?k.h&&k.pp&&k.pp[0]===q.zone&&k.pp[1]===q.project:!k.h&&k.pa&&k.pa[0]===q.zone&&k.pa[1]===q.file){row=r;c=k}});
if(!row)return false;R.close();
var z=row.closest('details.zone'),dest=park?fold(z,true):z,tail=park?null:fold(z,false),unit=row.closest('.tunit'),other;
if(byName){       /* the project's hub, and every thread parked with it; waking it leaves one parked on its own as it was */
var subs=[].slice.call(unit.querySelectorAll(':scope>.subthreads>.thread')),go=subs.filter(function(r){var k=cardOf(r);return park||(k&&k.held)});
setCard(row,function(k){k.hp=k.s=park?1:0});
go.forEach(function(r){r.classList.add('pending');setCard(r,function(k){if(park){if(!k.s){k.held=1;k.s=1}}else{delete k.held;k.s=0;if(!k.pa)k.pend=1}})});
other=group(dest,c.n);
if(!other&&go.length===subs.length){row.classList.add('pending');place(dest,unit,tail)}
else{if(!other)other=newGroup(unit,dest,tail);setCard(headOf(other),function(k){k.hp=k.s=park?1:0});
var box=other.querySelector(':scope>.subthreads');go.forEach(function(r){place(box,r,null)});recountUnit(other);recountUnit(unit)}}
else{setCard(row,function(k){k.s=park?1:0});row.classList.add('pending');
if(!row.classList.contains('sub'))place(dest,unit,tail);
else{other=group(dest,c.p)||newGroup(unit,dest,tail);place(other.querySelector(':scope>.subthreads'),row,null);recountUnit(other);recountUnit(unit)}}
recount();return true}
window.GarrickActed=function(q,out){if(!out||!out.ok||!moved(q))return;
/* what RELOAD_JS waits for gets the request, so a reload before the rebuild lands moves the row again */
var k=q.file!=null?q.zone+'/'+q.file:q.zone+'/'+q.project+'/'+q.project+'.md';
try{var w=JSON.parse(localStorage.getItem('garrick-expect')||'null');if(w&&w.x.slice(w.x.indexOf(':')+1)===k){w.q=q;localStorage.setItem('garrick-expect',JSON.stringify(w))}}catch(e){}};
if(window.GarrickRedo)moved(window.GarrickRedo);
})();
"""


# Where each card sits and which are hidden: a view preference like the theme
# and the folds, kept in the browser and nowhere else.
#
# A build's own order is a default, not a choice, and it reaches only a window
# that has made none. The two are told apart by one thing: a layout parsed out
# of garrick-status-layout whose `v` is 2. Without it nothing is replayed and
# the page stands as it was built, in whatever order this release gives; with
# it, every card the layout names goes back to the slot and the place that
# layout gives it, and nothing a later release prefers moves it. A card the
# layout has never heard of, one this release added, keeps the place the build
# gave it, which is ahead of the cards the layout then puts back in its slot. So a new default is adopted by Reset view, which clears the layout
# with the rest of the window's own storage, and by nothing else. That is the
# rule #81 set for the settings file: never replace a newer choice, and
# running it again changes nothing.
LAYOUT_JS = r"""
(function(){
var KEY='garrick-status-layout',st={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
var slots={};document.querySelectorAll('[data-slot]').forEach(function(s){slots[s.dataset.slot]=s});
function cards(){return Array.prototype.slice.call(document.querySelectorAll('[data-slot]>.card[id]'))}
function inSlot(el){return el&&el.parentNode&&el.parentNode.hasAttribute&&el.parentNode.hasAttribute('data-slot')}
var L=null;try{L=JSON.parse(st.get(KEY)||'null')}catch(e){}
/* a window that chose a layout keeps it, card for card; one that chose none takes the order the build wrote */
if(L&&L.v===2){Object.keys(L.c||{}).forEach(function(k){var s=slots[k];if(s)(L.c[k]||[]).forEach(function(id){var el=document.getElementById(id);if(inSlot(el))s.appendChild(el)})});
(L.h||[]).forEach(function(id){var el=document.getElementById(id);if(inSlot(el))el.hidden=true})}
function save(){var c={};Object.keys(slots).forEach(function(k){c[k]=Array.prototype.slice.call(slots[k].children).filter(function(e){return e.classList.contains('card')}).map(function(e){return e.id})});
st.set(KEY,JSON.stringify({v:2,c:c,h:cards().filter(function(e){return e.hidden}).map(function(e){return e.id})}));sync()}
function sync(){var h=cards().filter(function(e){return e.hidden});
cards().forEach(function(c){var b=c.querySelector('.totab'),sec=c.closest('section.tab');if(!b||!sec)return;
var to=sec.id==='tab-status'?'Overview':'Status';b.title='Move to '+to;b.setAttribute('aria-label','Move '+c.querySelector('h2').textContent+' to '+to)});
var n=document.getElementById('hidden-cards');if(n){n.hidden=!h.length;n.innerHTML=h.length?'<p class="hint">Hidden cards</p><div class="gacts">'+h.map(function(c){
var t=c.querySelector('h2').textContent.replace(/[&<>"]/g,function(x){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[x]});
return'<button class="act unhide" type="button" data-card="'+c.id+'" title="Show '+t+' again">'+t+'</button>'}).join('')+'</div>':''}}
function toast(t){var el=document.getElementById('toast');if(!el)return;el.textContent=t;el.style.opacity=1;setTimeout(function(){el.style.opacity=0},2600)}
document.addEventListener('click',function(e){
var m=e.target.closest('.head .totab');if(m){e.preventDefault();e.stopPropagation();var mc=m.closest('.card'),ms=mc.closest('section.tab');
var to=ms&&ms.id==='tab-status'?'overview':'status',slot=document.querySelector('#tab-'+to+' [data-slot$="left"]');
if(slot){slot.appendChild(mc);save();toast(mc.querySelector('h2').textContent+' moved to '+(to==='status'?'Status':'Overview')+'.')}return}
var b=e.target.closest('.head .hide,.head .grip');if(b){e.preventDefault();e.stopPropagation();
if(b.classList.contains('hide')){var c=b.closest('.card');c.hidden=true;save();toast(c.querySelector('h2').textContent+' hidden. Bring it back from Settings, or Reset view.')}return}
var u=e.target.closest('.unhide');if(u){var uc=document.getElementById(u.dataset.card),ud=u.closest('dialog');if(ud)ud.close();if(uc){uc.hidden=false;uc.open=true;save();
var us=uc.closest('section.tab');if(us&&window.StatusTab)StatusTab(us.id.slice(4));uc.scrollIntoView({block:'start'})}}},true);
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
if(k.indexOf('garrick-')===0&&k!=='garrick-status-theme'&&k!=='garrick-launchers')ks.push(k)}ks.forEach(function(k){localStorage.removeItem(k)})}catch(x){}
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
var places=[];G.nodes.forEach(function(n){if(places.indexOf(n.z)<0)places.push(n.z)});
/* which place the graph shows: the one asked for last, else Work when there is one, else everything */
var zsel=st.get('garrick-graph-place');if(zsel!=='*'&&places.indexOf(zsel)<0)zsel=places.indexOf('Work')>=0?'Work':'*';
/* the Threads card leads with the zone the graph shows, the others after it by name; everything, or a wiki, puts them all by name */
function leadZone(z){var box=document.querySelector('.tview .zones');if(!box)return;
var all=[].slice.call(box.children).filter(function(d){return d.matches('details.zone[data-zone]')});
all.sort(function(a,b){var x=a.dataset.zone,y=b.dataset.zone;return (x===z?0:1)-(y===z?0:1)||x.localeCompare(y)});
all.forEach(function(d){box.appendChild(d)})}leadZone(zsel);
/* Following the zone in view on the Threads card (#142, FOLLOW_JS) changes the graph and the drop-down for this page
   only. Picking All or a wiki, which the card cannot be in, pauses it until the page reloads. */
var held=false;function cardZone(z){return[].some.call(document.querySelectorAll('.tview .zones>details.zone[data-zone]'),function(d){return d.dataset.zone===z})}
function modeFor(z){return st.get('garrick-graph-mode-'+z)||(G.modes&&G.modes[z])||G.mode}var mode=modeFor(zsel),spin=!reduce&&st.get('garrick-graph-spin')!=='0',parked=st.get('garrick-graph-parked')==='1';
var N=G.nodes,seed=7;function rnd(){seed=(seed*16807)%2147483647;return seed/2147483647}
N.forEach(function(n,i){n.i=i;n.adj=[]});
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
/* the place shown in its zone's colour, from Settings › Zones, with its icon over the drop-down's left edge */
function zmark(zs){var o=zs.options[zs.selectedIndex],w=zs.parentNode,on=false;zs.className='gzsel'+(o&&o.className?' '+o.className:'');
w.querySelectorAll('.gzi').forEach(function(i){i.hidden=i.dataset.z!==zs.value;on=on||!i.hidden});w.classList.toggle('hasi',on)}
/* parked threads and projects stay off the graph unless asked for, as in the lists */
function visible(n){return(mode==='all'||n.c)&&(parked||!n.s)&&(zsel==='*'||n.z===zsel)}
function rebuild(){V=N.filter(visible);var on={};V.forEach(function(n){on[n.i]=1});E=(mode==='all'?G.edges:G.edges.concat(G.ce||[])).filter(function(e){return on[e[0]]&&on[e[1]]});
N.forEach(function(n){n.deg=0});E.forEach(function(e){N[e[0]].deg++;N[e[1]].deg++});anchors();
var drawn={},dg={};V.forEach(function(n){if(n.g>=0)dg[n.g]=1;else drawn[n.g===-1?OTHERK:n.k]=1});
document.querySelectorAll('.glegend [data-k]').forEach(function(s){s.hidden=!drawn[s.dataset.k]});
document.querySelectorAll('.glegend [data-g]').forEach(function(s){s.hidden=!dg[s.dataset.g]});
document.querySelectorAll('.gseg:not(.gzone) button').forEach(function(b){b.classList.toggle('on',b.dataset.m===mode);if(b.dataset.m==='core')b.textContent=(G.cl&&G.cl[zsel])||'Projects and threads'});
var zs=document.querySelector('.gzsel');if(zs){zs.value=zsel;zmark(zs)}
var sum=document.getElementById('gsum');if(sum)sum.textContent=(zsel==='*'?'Every zone and wiki':zsel)+' · '+V.length+' notes, '+E.length+' links · names only'}
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
var dx=q.cx-a.x,dy=q.cy-a.y,d2=dx*dx+dy*dy,inside=a.x>=q.x&&a.x<q.x+q.s&&a.y>=q.y&&a.y<q.y+q.s;
if(!inside&&q.s*q.s<.81*d2){if(d2<=360000){var k=S*alpha*q.m/d2;a.vx-=dx*k;a.vy-=dy*k}return}
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
/* a note in a vault with colour groups of its own takes its group's colour, or grey; elsewhere its kind's */
var OTHERK=G.colors.indexOf(G.other);
function fill(n){return n.g>=0&&G.groups[n.g]?G.groups[n.g][0]:n.g===-1?G.other:G.colors[n.k]||C['--muted']}
/* a ring for a thread whose own next action is overdue or due a chase (lt), never for age alone */
function ring(n){return n.s||!n.lt?null:C['--critical']}
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
if(h.n){var n=h.n;cv.dataset.tip=(n.N||n.n)+' · '+G.kinds.filter(function(k){return k[0]===n.k})[0][1]+(n.d!=null?' · updated '+n.d+'d ago':'')+(n.s?' · parked':'')+' · click for options'}else delete cv.dataset.tip});
cv.addEventListener('pointerup',function(){cv.classList.remove('drag');if(!down)return;if(!down.moved){if(down.n)select(down.n);else close()}drag=null;down=null;wake()});
cv.addEventListener('pointerleave',function(){if(!down){hover=null;delete cv.dataset.tip;wake()}});
/* A row in the threads list lights its node as hovering the node does (#62): found by its note's link among the
   nodes shown, so a node the graph does not show is left alone; nothing is selected, centred or zoomed. */
var lit=null;
window.GarrickGraph={focus:function(u){if(down)return false;if(!u){if(lit&&hover===lit)hover=null;lit=null;wake();return false}
var n=null;V.forEach(function(m){if(m.u===u)n=m});if(!n)return false;lit=hover=n;wake();return true},
/* the place shown, and showing a zone as the drop-down would, without storing it or reordering the card (#142) */
place:function(){return zsel},follow:function(z){if(held||z===zsel||places.indexOf(z)<0)return false;show(z);return true}};
cv.addEventListener('dblclick',function(e){var h=at(e);if(h.n)location.href=h.n.u});
cv.addEventListener('wheel',function(e){if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();idle=0;auto=false;
var r=cv.getBoundingClientRect(),x=e.clientX-r.left-W/2,y=e.clientY-r.top-H/2,k=Math.exp(-e.deltaY*.01);k=Math.max(.2,Math.min(5,scale*k))/scale;px=x-(x-px)*k;py=y-(y-py)*k;scale*=k;wake()},{passive:false});
var esc=Panel.esc;
function kindName(n){var k=G.kinds.filter(function(x){return x[0]===n.k})[0];return k?k[1]:'note'}
function select(n,centre){sel=n;hover=null;delete cv.dataset.tip;
var o={n:n.n,kl:kindName(n),z:n.z,p:n.p,t:n.t,d:n.d,s:n.s,w:n.w,h:n.h,u:n.u,f:n.f,lw:n.lw,dk:n.dk,live:n.live,pa:n.pa,pp:n.pp,hp:n.hp,held:n.held};
var nb=n.adj.map(function(i){return N[i]}).sort(function(a,b){return(b.h-a.h)||(b.c-a.c)||a.n.localeCompare(b.n)});
var links=nb.map(function(m){return'<button data-i="'+m.i+'"><i style="background:'+fill(m)+'"></i><span>'+esc(m.n)+'</span>'+(visible(m)?'':'<small class="muted">'+(m.s&&!parked?'parked':'everything')+'</small>')+'</button>'}).join('');
pop.innerHTML='<button class="x" aria-label="Close">×</button>'+Panel.head(o)+Panel.acts(o)
+(nb.length?'<div class="glinks"><div class="muted" style="font-size:11.5px;padding:2px 4px">Linked notes · '+nb.length+'</div>'+links+'</div>':'<p class="muted">No links to or from this note.</p>');
pop.hidden=false;wake();if(centre){var p=toScreen(n);auto=false;glide(px-(p[0]-W/2)+(W>700?-150:0),py-(p[1]-H/2))}}
function close(){sel=null;pop.hidden=true;wake()}
function glide(tx,ty){var sx=px,sy=py,t0=performance.now();glides++;wake();(function g(t){var k=Math.min(1,(t-t0)/350),e=1-Math.pow(1-k,3);px=sx+(tx-sx)*e;py=sy+(ty-sy)*e;if(k<1)requestAnimationFrame(g);else glides--})(t0)}
pop.addEventListener('click',function(e){if(e.target.closest('.x'))return close();
var b=e.target.closest('button[data-i]');if(b){var m=N[+b.dataset.i];if(!visible(m)){if(!(mode==='all'||m.c)){mode='all';st.set('garrick-graph-mode-'+zsel,mode)}
if(m.s&&!parked){parked=true;st.set('garrick-graph-parked','1');parkBtn()}rebuild();alpha=Math.max(alpha,.3)}select(m,true)}});
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&sel)close()});
function show(z){zsel=z;mode=modeFor(z);if(sel&&!visible(sel))close();rebuild();alpha=Math.max(alpha,.5);auto=true;wake()}
/* a pick is stored, leads the card (#72) and is what a reload opens on */
var zsl=document.querySelector('.gzsel');if(zsl)zsl.onchange=function(){var z=zsl.value;st.set('garrick-graph-place',z);leadZone(z);if(!cardZone(z))held=true;show(z)};
document.querySelectorAll('.gseg:not(.gzone) button').forEach(function(b){b.onclick=function(){mode=b.dataset.m;st.set('garrick-graph-mode-'+zsel,mode);if(sel&&!visible(sel))close();rebuild();alpha=Math.max(alpha,.5);auto=true;wake()}});
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


# Explore follows the zone you are reading on the Threads card (#142). With
# the zones stacked, one under another, the zone in view is the one whose
# section fills most of the window, and it takes over once it has held the
# view about 300 ms, so a zone scrolled quickly past is not followed. Side by
# side, every zone is in view, so scrolling changes nothing: hovering a column
# for as long does, and opening a project or thread inside one does at once.
# The graph takes the zone as if it had been picked in its drop-down, but
# stores nothing and leaves the card's order alone (GarrickGraph.follow), so
# the pick stays what orders the card and what a reload opens on. The zone in
# view when the page opens is where following starts, not a change, so a page
# opens on the pick. Off when Settings › Explore says so, kept in this window.
FOLLOW_JS = r"""
(function(){
var box=document.querySelector('.tview .zones'),G=window.GarrickGraph;if(!box||!G||!G.follow)return;
var KEY='garrick-graph-follow',st={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
function on(){return st.get(KEY)!=='0'}
var cb=document.getElementById('graph-follow');if(cb){cb.checked=on();cb.onchange=function(){st.set(KEY,cb.checked?'1':'0');cancel()}}
var ZONE='.tview .zones>details.zone[data-zone]';
function shown(){return[].filter.call(box.children,function(d){return d.matches(ZONE)}).map(function(d){return{z:d.dataset.zone,r:d.getBoundingClientRect()}})
.filter(function(o){return o.r.width>0&&o.r.height>0})}
function stacked(rs){return rs.every(function(o){return Math.round(o.r.left)===Math.round(rs[0].r.left)})}
function most(rs){var best=null,fill=0,H=window.innerHeight;rs.forEach(function(o){var h=Math.min(o.r.bottom,H)-Math.max(o.r.top,0);if(h>fill){fill=h;best=o.z}});return best}
function inView(){var rs=shown();return rs.length&&stacked(rs)?most(rs):null}
var seen=inView(),wait=null,t=0;
function cancel(){clearTimeout(t);wait=null}
function take(z){cancel();seen=z;G.follow(z)}
/* a zone that differs from `same` is taken once it is still the one wanted 300 ms later */
function want(z,same){if(z===wait)return;cancel();if(!z||z===same||!on())return;wait=z;t=setTimeout(function(){wait=null;take(z)},300)}
function look(){var rs=shown();if(rs.length&&stacked(rs))want(most(rs),seen)}
document.addEventListener('scroll',look,true);window.addEventListener('resize',look);
function column(e){var rs=shown();if(!rs.length||stacked(rs))return undefined;var d=e.target&&e.target.closest&&e.target.closest(ZONE);return d?d.dataset.zone:null}
document.addEventListener('mouseover',function(e){var z=column(e);if(z!==undefined)want(z,G.place())});
document.addEventListener('click',function(e){if(!on()||!(e.target&&e.target.closest&&e.target.closest('.tunit')))return;var z=column(e);if(z)take(z)},true);
})();
"""


def build(ws: Path, vault: Optional[str] = None, now: Optional[dt.datetime] = None, folder: Optional[Path] = None,
          show_graph: bool = True, out: Optional[Path] = None, vaults: Optional[List[Tuple[Path, str]]] = None,
          cmux: bool = False, flags: Tuple[str, ...] = (), launchers: Optional[Tuple[str, ...]] = None,
          also: Tuple[str, ...] = (), moved: Optional[Dict[str, str]] = None,
          managed: Optional[List[Path]] = None, cli: Optional[bool] = None) -> str:
    """The page. `vaults` and `launchers` say what this machine has (main()
    asks obsidian_vaults() and launchers_installed()); `cmux=True` alone
    stands for launchers=("cmux",). `flags` go into the rebuild command as
    given. `also` and `moved` reach effort.py: folders the workspace used to
    live in, and folders renamed or moved since, old path to new. `managed`
    names the files where a managed setting may switch Claude's local
    sessions off (main() passes this Mac's); without it only the record
    Continue keeps is read, as a test needs. `cli` says whether Claude Code's
    command-line tool is here (main() asks handoff.py's find_claude()): with
    it, Open in Claude on a thread goes through Continue's request (#180);
    without it, or unsaid, through the deep link."""
    now = now or dt.datetime.now()
    launch = tuple(launchers) if launchers is not None else (("cmux",) if cmux else ())
    cmux = bool(launch)                       # a card carries its folder when anything can open it
    agent = load_agent(ws)
    folder = folder or jobs_dir(agent)
    link = Links(ws, vault, vaults)
    T, TD, IB, C, R, W = threads(ws), todo(ws), inboxes(ws), check(ws), repos(ws), wikis(ws)
    sched = launchd_jobs()       # only plists that run job.py: the jobs extra's, run or not
    J, L = jobs(folder, now, sched), ledger(agent, folder, now, sched)
    S = sessions(ws)                                       # None without the cmux extra

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
        over: Dict[str, int] = {}
        for e in L["over_budget"]:
            over[str(e.get("job") or "a job")] = over.get(str(e.get("job") or "a job"), 0) + 1
        for job, n in over.items():
            attn.append(("critical", "A call by %s stopped at its per-call budget%s" % (job, "" if n == 1 else ", %d times in 24 hours" % n), "#calls"))
        if L["deny"] is None:
            attn.append(("critical", "The deny list for scheduled calls, headless-settings.json, is missing, does not read or has lost a core entry", "#calls"))
        for job, d in sorted(L["by"].items()):
            hit = sorted(t for t in d["denied"] if denied_by_list(t, L["deny"]))
            if hit:
                attn.append(("critical", "%s tried a tool the deny list forbids: %s" % (job, ", ".join(hit)), "#calls"))
    waiting = sum(n for _, _, n in IB)
    if waiting:
        attn.append(("warning", "%d item%s waiting in the inboxes" % (waiting, "" if waiting == 1 else "s"), "#inboxes"))
    if C and C.get("warnings"):
        attn.append(("warning", "The check found %d warning%s" % (C["warnings"], "" if C["warnings"] == 1 else "s"), "#checks"))
    for j in J:
        if j["idle"]:
            attn.append(("warning", "%s: %s" % (j["name"], j["status"]), "#jobs"))
    for r in R:
        if r["dirty"] and r.get("since") and now - r["since"] > STALE_CHANGES:
            attn.append(("warning", "%s: %s, the oldest changed %s" % (r["name"], say_files(r["dirty"]), age(r["since"], now)), "#repos"))
    notice = release_notice(ws)
    if notice:
        attn.append(("warning", notice[0], notice[1]))
    for f in drifted(ws):
        attn.append(("warning", f, "#threads"))
    attn.sort(key=lambda a: a[0] != "critical")
    worst = "critical" if any(a[0] == "critical" for a in attn) else "warning" if attn else "good"

    live = sum(len(z["rows"]) for z in T.values())
    parked_n = sum(len(z["parked"]) for z in T.values())
    names = short_names(T)
    aging = sum(1 for z in T.values() for r in z["rows"] if r["updated"] and (now.date() - r["updated"]).days > 14)
    week = sum(1 for z in T.values() for r in z["rows"] if r["updated"] and (now.date() - r["updated"]).days <= 7)
    open_actions = sum(sum(t["counts"].values()) for t in TD.values())

    flags_on = preview_flags(ws)
    acting = True       # the buttons that act; only a host that carries them out (the app, Obsidian) shows them
    lists = todo_list(ws, link, now.date())
    ZS = zone_styles(ws)        # each zone's colour and icon, from Settings › Zones
    # What each thread owes, on its own row: its next action, and whether that
    # action makes it urgent. Every card that says a thread is in trouble
    # reads this, and none of them reads its age.
    thread_actions(T, lists, C, ws)
    urgent = {(r["zone"], r["project"], "" if r["note"] == r["hub"] else r["thread"])
              for z in T.values() for r in z["rows"] if r.get("urgent")}
    # The simple home (#175), where Settings › Home chose it: the pieces of
    # work, the questions waiting on the user, what Continue kept, and
    # whether Claude's desktop app can open work on this Mac.
    layout = home_layout(ws)
    simple = layout == "simple"
    if simple:
        HW = works(ws, T, now.date())
        kept = handoff_mod().load(ws).get("sessions")
        kept = kept if isinstance(kept, dict) else {}
        local = handoff_mod().local_off(ws, managed)
        example = example_state(ws)

    # ---- the top row, pinned while the page scrolls: the name and when it was
    # built, the tabs, and the page's controls. There is no sidebar: the tabs
    # move between the work and the machinery, the cards are open on the page,
    # and the Status tab's own figures say whether anything needs attention.
    # With the cmux extra and cmux, the desk's buttons: Open
    # in cmux and Close session on cards, Start up and Shut down here, in the app only.
    DK = S is not None and acting and desk_ready()
    desk_acts = ('<span class="desk-acts apponly"><button class="act" type="button" data-act="%s" data-expect="live:" data-say="Starting up…">Start up</button>'
                 '<button class="act stop" type="button" data-act="%s" data-expect="none:" data-confirm="Click again to shut down" '
                 'data-say="Shutting down: each session wraps, then cmux quits…">Shut down</button></span>'
                 % (E(json.dumps({"verb": "startup"})), E(json.dumps({"verb": "shutdown"})))) if DK else ""
    simple_bar = ""
    if simple:
        simple_bar = ('<button class="sh-dot" type="button" data-more="status" title="%s">'
                      '<span class="dot %s"></span><span class="sh-dw">%s</span></button><button class="sh-morebtn" type="button" data-more="overview" '
                      'title="Threads, Todo, Status and the Guide">More</button>'
                      % ((E("; ".join(t for _, t, _ in attn)) if attn else "Nothing failing, waiting or broken"), worst,
                         "All well" if not attn else "%d thing%s to look at" % (len(attn), "" if len(attn) == 1 else "s")))
    controls = ('<div class="bacts">' + simple_bar + '<button class="cog" type="button" id="rebuild" aria-label="Rebuild the page" '
                'title="Copy the command that rebuilds the page" data-copy="%s" data-say="Copied. Run it in a terminal to rebuild the page.">%s</button>'
                '<button class="cog" type="button" id="open-settings" aria-label="Settings" title="Settings: apps to open projects in, '
                'which Garrick this is, release notes, the view, hidden cards, and how to report a bug">%s</button>%s%s</div>'
                % (E(rebuild_command(ws, vault, show_graph, out, flags)), REBUILD, GEAR, THEME_SEG, desk_acts))

    # ---- hero and tiles
    if attn:
        hero = '<a class="hero go" id="summary" href="#attention"><div class="fig">%s%d</div><div class="lbl">%s attention</div></a>' % (
            ICON[worst], len(attn), "thing needs" if len(attn) == 1 else "things need")
    else:
        hero = '<div class="hero" id="summary"><div class="fig" style="font-size:38px">%sAll clear</div><div class="lbl">Nothing failing, waiting or broken.</div></div>' % ICON["good"]
    # Each tile leads to the card that explains it, in whichever tab that card sits.
    tiles = [("Live threads", "%d" % live, "%d touched this week, %d untouched for 14+ days" % (week, aging), "threads")]
    if TD:
        tiles.append(("Open actions", "%d" % open_actions, "across %d zone%s" % (len(TD), "" if len(TD) == 1 else "s"),
                      "todolist" if lists else "todo"))
    tiles += [("Waiting to be filed", "%d" % waiting, "in the zone and meeting inboxes", "inboxes"),
              ("Check", ("%d<small>errors</small>%d<small>warnings</small>" % (C.get("errors", 0), C.get("warnings", 0)))
               if C and not C.get("failed") else "—", "run just now" if C else "check.py not found", "checks")]
    if L:
        cap = L["caps"]["calls_day"]
        tiles[-1] = ("Assistant calls, 24 h", "%d<small>%s</small>" % (L["day"], "of %g" % cap if cap else "no cap"),
                    "$%.2f at list price · %s" % (L["cost_day"], "$%g max per call" % L["budget"] if L["budget"] else "no per-call budget"),
                    "calls")
    top = '<div class="top" style="--tiles:%d">%s%s</div>' % (len(tiles), hero, "".join(
        '<a class="tile go" href="#%s"><div class="lbl">%s</div><div class="val">%s</div><div class="sub">%s</div></a>' % (h, E(a), b, E(c))
        for a, b, c, h in tiles))

    # ---- attention
    attn_card = ""
    if attn:
        attn_card = '<div class="full">%s</div>' % card("attention", "Needs attention", "%d item%s" % (len(attn), "" if len(attn) == 1 else "s"),
                                                       '<div class="attn">%s</div>' % "".join('<a href="%s"%s>%s<span>%s</span></a>' % (
                                                           E(h), ' target="_blank" rel="noopener"' if h.startswith("https://") else "", ICON[k], E(t))
                                                           for k, t, h in attn),
                                                       fixed=True)

    # ---- threads, one column per zone: a row per project, its threads folding
    # under it; a project with no thread notes is a thread row of its own. With
    # the effort ledger switched on, Time and Cost lay the last 30 days over it.
    EV = None
    store = folder / effort().STORE
    if flags_on["effort"]:
        try:
            EV = Effort(effort().ledger(ws, store, also=[Path(a).expanduser() for a in also], now=now, moved=moved or None), now.date())
        except Exception:                     # a transcript format this reader does not know: no Time and Cost
            EV = None
    said = {t.casefold() for t in (r["thread"] for z in T.values() for r in z["rows"] + z["parked"])}
    project_n: Dict[str, int] = {}
    for zz, data in T.items():
        for p in {r["project"] for r in data["rows"] + data["parked"]}:
            project_n[p.casefold()] = project_n.get(p.casefold(), 0) + 1

    # Age is not urgency: the bar and the figure are the days since the note
    # moved, and nothing about them says a thread is in trouble. What does is
    # the thread's own open actions and errors (thread_actions): a red `todo`
    # chip, for a due date that has passed or a #waiting line whose chase date
    # has come, and a `check` chip, for an error in one of its files that the
    # page can explain and fix (#179).

    def live_dot(state, what):
        return ('<span class="live %s" title="%s"></span>' % (state, E("A session is open in %s, %s" % (what, state)))) if state else ""

    # Recent, on the Threads card, lists by `touched`: the later of `updated:`
    # and an unwrapped checkpoint's day, so work recorded this afternoon and
    # not yet wrapped leads. A row carries it as data-r, a project's row its
    # newest thread's, and TVIEW_JS sorts on it.
    def touched(*rs):
        days = [r["touched"] for r in rs if r.get("touched")]
        return max(days).isoformat() if days else ""

    def row_html(r, sub=False, figures=None, parked=False, place=0):
        days = (now.date() - r["updated"]).days if r["updated"] else None
        k = not parked and bool(r.get("urgent"))
        # The party tags are the card's, not the row's: under a name they read as part of it.
        # Under the name, at most the two chips that say something is owed or
        # broken (#179), beside an unwrapped checkpoint's; the lists they open
        # sit at the foot of the row, shut until a click.
        chips = "" if parked else checkpoint_chip(r) + todo_chip(r, now.date()) + check_chip(r)
        pops = "" if parked else todo_pop(r, now.date(), acting) + check_pop(r, names[(r["zone"], r["project"], r["thread"])])
        under = "" if sub or r["thread"] == r["project"] else E(r["project"]) + chips     # a project that is its own thread says it once
        bar = '<span class="mu"></span>' if parked else \
            '<div class="fresh age mu" title="%s"><i style="width:%.1f%%"></i></div>' % (
                E("%s since its note moved, toward sixty days" % ("%d days" % days if days is not None else "No date")),
                max(3.0, min(100.0, (days if days is not None else 60) / 60 * 100)))
        return ('<div class="thread%s" data-ok="%d" data-card="%s"%s data-r="%s"><div class="t"><a href="%s">%s</a>%s%s</div>%s'
                '<span class="num muted mu" style="text-align:right">%s</span>%s%s</div>'
                % (" sub" if sub else "", 0 if k else 1,
                   E(thread_card(r, names, link, days, cmux, acting, S, now.date(), DK)),
                   ' data-a="%d"%s' % (place, EV.attrs(figures) if EV else "") if sub else "", touched(r),
                   E(link(r["note"])), E(r["thread"]), live_dot(session_in(S, r["note"].parent), "it"),
                   ("<small>%s</small>" % under if under else (chips and "<small>%s</small>" % chips)),
                   bar, "%dd" % days if days is not None else "—", EV.cells(figures) if EV else "", pops)), k

    def project_card(zone, project, items, days):
        hub = items[0]["hub"]
        party = []
        for r in items:
            party += [t for t in r["party"] if t not in party]
        hp = 1 if project in T[zone].get("held", ()) else 0
        c = {"n": project, "kl": "project", "z": zone, "p": "", "t": party, "d": days, "s": hp, "h": 1, "hp": hp,
             "w": project if project.casefold() not in said and project_n.get(project.casefold()) == 1 else "",
             "u": link(hub) if hub else link(items[0]["note"])}
        if acting and hub:
            c["pp"] = [zone, project]        # what Park and Wake act on: the hub, and with it every thread
        if hub:
            subs = sorted({r["thread"] for r in items if r["note"] != r["hub"]})
            c["mg"] = [zone, project, "", files_in(hub.parent), open_naming(hub.parent.parent, set(subs) | {project}),
                       subs]
        if cmux:
            c["f"] = str((hub or items[0]["note"]).parent)
        if DK:
            c["dk"] = [zone, project, ""]
        live = session_in(S, (hub or items[0]["note"]).parent)
        if live:
            c["live"] = live
        return json.dumps(c, separators=(",", ":"), ensure_ascii=False)

    def units(zone, rs, parked=False):
        """The rows of a zone, or of its Parked fold, a unit per project."""
        out, counts = [], {True: 0, False: 0}
        groups: Dict[str, list] = {}
        for r in rs:
            groups.setdefault(r["project"], []).append(r)
        for i, (project, items) in enumerate(sorted(groups.items(), key=lambda kv: kv[0].casefold())):
            alone = len(items) == 1 and items[0]["note"] == items[0]["hub"]
            if alone:
                r = items[0]
                fig = EV.take([(zone, project, r["thread"])] + ([] if parked else [(zone, project, "")])) if EV else None
                html_, k = row_html(r, figures=fig, parked=parked)
                counts[k] = counts.get(k, 0) + 1
                out.append('<div class="tunit" data-a="%d"%s>%s</div>' % (i, EV.attrs(fig) if EV else "", html_))
                continue
            subs, newest = [], None
            figs = []
            for j, r in enumerate(sorted(items, key=lambda r: r["thread"].casefold())):
                fig = EV.take([(zone, project, r["thread"])]) if EV else None
                figs.append(fig)
                html_, k = row_html(r, sub=True, figures=fig, parked=parked, place=j)
                counts[k] = counts.get(k, 0) + 1
                subs.append(html_)
                d = (now.date() - r["updated"]).days if r["updated"] else None
                newest = d if newest is None or (d is not None and d < newest) else newest
            own = EV.take([(zone, project, "")]) if EV else None    # the project's work in no thread, on its own row
            total = None
            if EV:
                total = {f: own[f] + sum(fg[f] for fg in figs) for f in EV.fields}
            sid = "sub-" + re.sub(r"\W+", "-", ("%s-%s%s" % (zone, project, "-parked" if parked else "")).lower()).strip("-")
            k = not parked and any(r.get("urgent") for r in items)      # the project's, from its threads' own actions
            n = len(items)
            hub_link = link(items[0]["hub"]) if items[0]["hub"] else link(items[0]["note"])
            bar = '<span class="mu"></span>' if parked else \
                '<div class="fresh age mu" title="%s"><i style="width:%.1f%%"></i></div>' % (
                    E("%s since its newest thread moved, toward sixty days" % ("%d days" % newest if newest is not None else "No date")),
                    max(3.0, min(100.0, (newest if newest is not None else 60) / 60 * 100)))
            bare = 0 if parked else sum(1 for r in items if not r.get("resume"))
            urg = 0 if parked else sum(1 for r in items if r.get("urgent"))
            head = ('<div class="thread proj" data-ok="%d" data-card="%s" data-r="%s"><div class="t"><button type="button" class="pchev" data-sub="%s" '
                    'aria-expanded="false" title="Show its %d thread%s">%s</button><a href="%s">%s</a>%s <span class="muted subn">%d thread%s%s%s</span></div>'
                    '%s<span class="num muted mu" style="text-align:right">%s</span>%s</div>'
                    % (0 if k else 1, E(project_card(zone, project, items, newest)), touched(*items), sid, n, "" if n == 1 else "s", CHEV,
                       E(hub_link), E(project), live_dot(session_in(S, (items[0]["hub"] or items[0]["note"]).parent), "the project"),
                       n, "" if n == 1 else "s", " · %d needing a chase" % urg if urg else "",
                       " · %d without a resume block" % bare if bare else "", bar,
                       "%dd" % newest if newest is not None else "—", EV.cells(total) if EV else ""))
            out.append('<div class="tunit" data-a="%d"%s>%s<div class="subthreads tsort" id="%s" hidden>%s</div></div>'
                       % (i, EV.attrs(total) if EV else "", head, sid, "".join(subs)))
        return out, counts

    cols = ""
    for z, data in T.items():
        live_units, cnt = units(z, data["rows"])
        held_units, _ = units(z, data["parked"], parked=True) if data["parked"] else ([], None)
        slug = re.sub(r"\W+", "-", z.lower())
        parked_block = ('<details class="parked tsort" id="parked-%s"><summary>%sParked<span class="n">%d</span></summary>%s</details>'
                        % (slug, CHEV, len(data["parked"]), "".join(held_units))) if data["parked"] else ""
        meta = "%d live" % len(data["rows"]) + (" · %d needing a chase" % cnt[True] if cnt[True] else "") + \
            (" · %d done" % data["done"] if data["done"] else "")
        cols += ('<details class="zone tsort" id="zone-%s" data-zone="%s" open><summary>%s<h3%s>%s</h3><span class="meta mu">%s</span>%s</summary>%s%s</details>'
                 % (slug, E(z), CHEV, zone_attr(z, ZS), zone_name(z, ZS), E(meta), EV.zone_meta(z) if EV else "",
                    "".join(live_units) or '<p class="muted">No live threads.</p>', parked_block))
    legend = ('<div class="legend mu"><span><i class="critical"></i>A red <code>todo</code>: an open action is overdue, or a <code>#waiting</code> '
              'chase date has come. <code>check</code>: an error the page can explain and fix</span>'
              '<span><i style="background:var(--base)"></i>Days since the note moved, toward sixty: a figure, not a fault</span></div>')
    # The search box leads the row, New project and New thread follow it, and
    # what it finds takes the columns' place while a query is in it (#140).
    new_bar = ('<div class="mg-new">%s<button class="act" type="button" data-manage="new-project">New project</button>'
               '<button class="act" type="button" data-manage="new-thread">New thread</button></div>' % FIND_BOX)
    threads_card = card("threads", "Threads", "",
                        '<div class="tview" data-tm="updated" data-to="name">%s%s%s%s<div class="zones">%s</div>%s%s<p class="hint gsum mu">%d live · %d parked · by name · hover one for what to do</p></div>'
                        % (new_bar, FIND_LIST, torder_switch(), tview_switch() if EV else "", cols, legend, EV.foot() if EV else "", live, parked_n))


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
    checks_card = card("checks", "Checks", "check.py --quick, run as the page was built", body)

    # ---- open actions and inboxes
    tb = ""
    for z, t in TD.items():
        scale = max(list(t["counts"].values()) + [1]) * 1.08
        opener = ('<a class="act" href="#todolist" data-tz-go="%s" title="Open %s&#39;s list on the Todo tab">Open the list</a>' % (E(z), E(z))
                  if lists else '<a class="act" href="%s" title="Open %s/Todo.md">Open</a>' % (E(link(t["file"])), E(z)))
        tb += ('<div class="zt"><b><a%s href="%s">%s</a></b><span class="muted" style="font-size:12px">changed %s</span>%s</div>'
               % (zone_attr(z, ZS), E(link(t["file"])), zone_name(z, ZS), age(t["when"], now), opener))
        if not t["counts"]:
            tb += '<p class="muted" style="font-size:12px;margin:2px 0">Nothing open.</p>'
        for sec, n in t["counts"].items():
            tb += '<div class="bullet"><span class="ink2">%s</span><div class="bar"><i style="width:%.1f%%"></i></div><span class="num">%d</span></div>' % (E(sec), n / scale * 100, n)
    todo_card = card("todo", "Open actions", "unticked items in each zone's Todo.md", tb) if TD else ""
    ib = "".join('<a class="item" data-ok="%d" href="%s">%s<div class="name%s">%s<small>%s</small></div></a>' % (
        0 if n else 1, E(link(f)), ICON["warning" if n else "good"], zone_class(name, ZS), zone_name(name, ZS),
        "%d waiting" % n if n else "empty") for name, f, n in IB)
    inbox_card = card("inboxes", "Inboxes", "files waiting to be filed; say \"process the inbox\"", '<div class="tiles">%s</div>' % ib)

    # ---- jobs and calls, only when the jobs extra is in use
    jobs_card = calls_card = ""
    if J:
        rows = []
        for j in J:
            strip = "".join('<i class="%s" tabindex="0" data-tip="%s"></i>' % (s, E(t)) for s, t in day_cells(j["runs"], now, j["quiet"]))
            last = age(j["when"], now) if j["when"] else "never"
            said = "running now" if j["running"] else j["status"]      # its lock is held: a run is under way
            # a job not run yet is neither fine nor wrong: a hollow mark, and out of "Only what needs attention"
            rows.append('<div class="row" data-ok="%d">%s<div class="name"><a href="%s">%s</a><small>%s</small></div><div class="strip">%s</div>'
                        '<div class="ink2 num"%s>%s</div><span class="status%s" data-tip="%s">%s%s</span></div>'
                        % (j["state"] in ("good", "none"), ICON[j["state"]], E(link(j["log"])), E(j["name"]), E(j["schedule"]), strip,
                           ' data-tip="took %ss"' % E(str(j["seconds"])) if j["seconds"] is not None else "", E(last), " running" if j["running"] else "",
                           E("Last run: " + j["status"]) if j["running"] else "", ICON[j["state"]], E(said) + (
                               ' <button class="act tacts" type="button" data-act="%s" data-say="Starting %s…">Run now</button>'
                               % (E(json.dumps({"verb": "run", "job": j["name"]})), E(j["name"]))
                               if acting and j["name"] in sched and not j["running"] else "")))
        legend = ('<div class="legend"><span><i class="good"></i>Every run ok</span><span><i class="warning"></i>Some failed, then recovered</span>'
                  '<span><i class="critical"></i>Ended the day failed, or most runs failed</span><span><i></i>No run</span><span>· One cell per day, last %d days</span></div>' % DAYS)
        jobs_card = card("jobs", "Scheduled jobs", "heartbeats and logs in %s" % folder.name, '<div class="rows jobs">%s</div>%s' % ("".join(rows), legend))
    if L:
        c = L["caps"]
        def against(text, cap, unit=""):     # "3 / 48", or "3, no cap" when the cap is 0
            return "%s / %s%g" % (text, unit, cap) if cap else "%s, no cap" % text
        m = (meter(L["day"], c["calls_day"], "Calls, last 24 h", against("%d" % L["day"], c["calls_day"]))
             + meter(L["hour"], c["calls_hour"], "Calls, last hour", against("%d" % L["hour"], c["calls_hour"]))
             + meter(L["cost_day"], c["cost_day"], "Cost, last 24 h", against("$%.2f" % L["cost_day"], c["cost_day"], "$"))
             + '<p class="hint">%s</p>' % E(L["caps_from"]))
        m += '<p class="hint">%s</p>' % E("Each Claude call stops at $%g." % L["budget"] if L["budget"] else
                                          "No per-call budget: GARRICK_MAX_CALL_USD is 0.")

        def refused(tools):
            """A refused tool the deny list names is red; one no allow rule named is amber."""
            return "".join('<span class="chip" title="%s">%s%s</span> ' % (
                "On the deny list" if denied_by_list(t, L["deny"]) else "Not allowed for this job",
                ICON["critical" if denied_by_list(t, L["deny"]) else "warning"].replace("<svg ", '<svg width="12" height="12" '), E(t))
                for t in sorted(tools)) or '<span class="muted">none</span>'
        trs = "".join('<tr data-ok="%d"><td>%s</td><td class="r">%d</td><td class="r">$%.2f</td><td class="r">%s</td><td>%s</td>'
                      '<td class="r">%d</td><td class="r">%d</td></tr>'
                      % (0 if d["denied"] or d["failed"] or d["refused"] else 1, E(job), d["calls"], d["cost"],
                         "%.1f" % (sum(d["turns"]) / len(d["turns"])) if d["turns"] else "–", refused(d["denied"]), d["failed"], d["refused"])
                      for job, d in sorted(L["by"].items(), key=lambda kv: (-kv[1]["cost"], kv[0])))
        table = ('<div class="scroll"><table><thead><tr><th>Job</th><th class="r">Calls</th><th class="r">Cost</th>'
                 '<th class="r" title="Turns per call, on average">Turns</th><th>Refused tools</th>'
                 '<th class="r">Failed</th><th class="r">Capped</th></tr></thead><tbody>%s</tbody></table></div>' % trs) if trs else '<p class="muted">No calls yet.</p>'
        calls_card = card("calls", "Assistant calls", "ledger.jsonl, last %d days, list-price cost" % DAYS,
                          '<div class="meters">%s</div>%s<div style="margin-top:14px">%s</div>' % (m, cost_chart(L), table))

    # ---- repositories and wikis
    def waiting_long(r):
        return bool(r["dirty"] and r.get("since") and now - r["since"] > STALE_CHANGES)
    rr = "".join('<div class="item" data-ok="%d" data-tip="%s">%s<div class="name">%s<small>%s</small></div></div>' % (
        0 if r.get("unread") or waiting_long(r) else 1,
        E("git status failed or took over 30 seconds, so its changes are not known" if r.get("unread") else
          "; ".join(x for x in ("last commit " + (age(r["last"], now) if r["last"] else "never"), say_kinds(r["changes"]),
                                "the oldest change made " + age(r["since"], now) if r["dirty"] and r.get("since") else "") if x)),
        ICON["warning" if r.get("unread") or waiting_long(r) else "good" if not r["dirty"] else "none"], E(r["name"]),
        "could not be read" if r.get("unread") else say_files(r["dirty"]) if r["dirty"] else "all committed") for r in R)
    repos_card = card("repos", "Repositories", "a ring means files changed since the last commit; amber, for over a day",
                      ('<div class="tiles">%s</div>%s' % (rr, "".join(repo_changes(ws, r) for r in R if r["dirty"])))
                      if rr else '<p class="muted">No git repositories found.</p>')
    def newest(w):
        if not w["when"]:
            return "nothing logged yet"
        title = ('<a href="%s">%s</a>' % (E(link(w["page"])), E(w["title"]))) if w["page"] else E(w["title"])
        return "%s · %s" % (E(w["when"].strftime("%d %b %Y").lstrip("0")), title)
    wr = "".join('<div class="row" style="grid-template-columns:1fr"><div class="name"><a href="%s">%s</a><small style="white-space:normal">%s</small></div></div>' % (
        E(link(w["log"])), E(w["name"]), newest(w)) for w in W)
    wikis_card = card("wikis", "Wikis", "newest entry in each log", '<div class="rows">%s</div>' % wr if wr else '<p class="muted">No wiki logs found.</p>')

    # ---- the graph, behind Explore at the foot of the Overview: it keeps every
    # mode it has, and folds shut so the tab opens on the work instead. A
    # window that has opened or shut this card keeps its own choice, as it
    # does for every other fold.
    graph_card = ""
    if show_graph:
        GR = graph(ws, T, link, now, cmux, acting, S, DK, urgent)
        core = sum(1 for n in GR["nodes"] if n["c"])
        legend = "".join('<span data-k="%d"><i style="background:%s"></i>%s</span>' % (i, GR["colors"][i], E({"project": "Projects"}.get(label, label[:1].upper() + label[1:]))) for i, label in GR["kinds"])
        legend += "".join('<span data-g="%d"><i style="background:%s"></i>%s</span>' % (i, E(colour), E(label))
                          for i, (colour, label) in enumerate(GR["groups"]) if any(n.get("g") == i for n in GR["nodes"]))
        legend = ('<div class="legend glegend">%s<span><i class="ring" style="border-color:var(--critical)"></i>Next action overdue '
                  'or due a chase</span><span><i style="opacity:.3;background:var(--muted)"></i>Parked</span></div>' % legend)
        data = script_json(GR)
        places = list(dict.fromkeys(n["z"] for n in GR["nodes"]))
        places = sorted(places, key=lambda z: (z != "Work", z not in T, places.index(z)))      # Work, the other zones, then the wikis
        switch = "".join('<option value="%s"%s>%s</option>' % (E(z), zone_attr(z, ZS), E(z)) for z in places) + '<option value="*">All</option>'
        # a select cannot draw an icon in its options, so the chosen place's icon sits over its left edge
        marks = "".join('<span class="gzi%s" data-z="%s" hidden>%s</span>' % (zone_class(z, ZS), E(z), zone_icon(ZS[z]["icon"]))
                        for z in places if ZS.get(z, {}).get("icon"))
        graph_card = card("graph", "Explore", "the graph of every note, and the links between them",
                          '<div class="gwrap"><canvas id="gcv" role="img" aria-label="Graph of the notes in a zone or wiki, and the links between them"></canvas>'
                          '<div class="gbar"><span class="gzw">' + marks + '<select class="gzsel" aria-label="Place">' + switch + '</select></span>'
                          '<div class="gseg" role="group" aria-label="Notes shown"><button data-m="core">Projects and threads</button>'
                          '<button data-m="all">Everything</button></div><button id="gpark" type="button"></button></div>'
                          '<div class="gbar gcorner"><button id="gspin"></button><button id="gfit">Fit</button></div>'
                          '<div class="gpop" id="gpop" hidden></div></div>%s<p class="hint gsum" id="gsum">%d notes, %d links · %d projects and threads · names only</p>'
                          '<script type="application/json" id="graph-data">%s</script>' % (legend, len(GR["nodes"]), len(GR["edges"]), core, data),
                          open_=False)

    todo_tab = todo_list_card(lists, now.date(), acting, add_projects(T), link, ZS) if lists else ""
    # Four tabs: Overview for where the work stands, Todo for the list, Status
    # for the machinery behind it, and the Guide, Garrick's own docs. Cards can
    # be moved between Overview and Status from their headers, and Reset view
    # puts them back; the Guide holds no cards. The figures at the top count
    # the machinery's state, so they open the Status tab.
    machinery = [c for c in (jobs_card, calls_card, checks_card, repos_card, wikis_card) if c]
    def section(name, hidden, body):
        return '<section class="tab" id="tab-%s"%s>%s</section>' % (name, " hidden" if hidden else "", body)
    # The Overview opens on the Threads card: each live thread with at most
    # its `todo` and `check` chips (#179), listed by name or most recently
    # touched first (#143). Open actions on the left, the inboxes on the right,
    # and the graph behind Explore at the foot. A workspace with no project
    # yet has no work to show, so Start here leads instead. A browser that
    # still holds what it kept for A thought, the card #143 took away, shows it
    # once above the cards (THOUGHT_LEFT).
    #
    # This is the order a window with nothing saved gets. A window that has
    # dragged, moved or hidden a card keeps every card it placed exactly where
    # it placed it (LAYOUT_JS), and Reset view is what adopts this order.
    anything = any(z["rows"] or z["parked"] or z["done"] for z in T.values())
    lead = threads_card if anything else start_card() + threads_card
    overview = section("overview", False, '%s<div class="grid"><div class="slot full" data-slot="top">%s</div>'
                       '<div class="slot stack left" data-slot="left">%s</div><div class="slot stack right" data-slot="right">%s</div>'
                       '<div class="slot full" data-slot="bottom">%s</div></div>' % (THOUGHT_LEFT, lead, todo_card, inbox_card, graph_card))
    # Needs attention leads the Status tab: what it lists is the machinery's.
    status_tab = section("status", True, '%s<div class="onlybar"><label class="switch"><input type="checkbox" id="only"> Only what needs attention</label></div><div class="grid">%s<div class="slot stack left" data-slot="status-left">%s</div>'
                         '<div class="slot stack right" data-slot="status-right">%s</div><div class="slot full" data-slot="status-bottom"></div></div>'
                         % (top, attn_card, "".join(machinery[0::2]), "".join(machinery[1::2])))
    late = sum(z["late"] for z in lists)
    trouble = any(j["state"] == "critical" for j in J) or bool(C and (C.get("errors") or C.get("failed"))) or bool(L and L["refused_today"])
    tabs = ('<div class="tabs" role="tablist">' + ('<button type="button" role="tab" data-tab="home">Home</button>' if simple else "")
            + '<button type="button" role="tab" data-tab="overview">Overview</button>%s'
            '<button type="button" role="tab" data-tab="status">Status%s</button>'
            '<button type="button" role="tab" data-tab="guide">Guide</button></div>'
            % ('<button type="button" role="tab" data-tab="todo">Todo<span class="n">%d</span>%s</button>'
               % (sum(z["open"] for z in lists), '<span class="dot critical" title="overdue"></span>' if late else "") if todo_tab else "",
               '<span class="dot critical" title="something failed"></span>' if trouble else ""))
    header = bar(mark(full=False, attrs=' class="mark" aria-hidden="true"'), E(NAME), now.strftime("%a %d %b, %H:%M"), tabs, controls)
    md = menu_data(T, names, link, cmux, trouble, S, DK, bool(cli))
    if cmux:          # an app to open folders in; the app shows the row only with an assistant among them
        md["intake"] = {"n": "Process the Inbox", "w": "process the inbox", "f": str(ws), "c": sum(n for _, _, n in IB),
                        "b": [[name, n] for name, _, n in IB if n]}   # what waits where, Meetings included
    menu = '<script type="application/json" id="menu-data">%s</script>' % script_json(md)
    # What RELOAD_JS compares a button's expectation with: the parked threads
    # and, with the cmux extra, the folders a session is open in.
    folders = {f for z in T.values() for r in z["rows"] + z["parked"] for f in (r["note"].parent, (r["hub"] or r["note"]).parent)}
    state = {"parked": sorted({"%s/%s" % (r["zone"], r["rel"]) for z in T.values() for r in z["parked"]}
                              | {"%s/%s/%s.md" % (zone, p, p) for zone, z in T.items() for p in z.get("held", ())}),
             "live": sorted(str(f) for f in folders if session_in(S, f))}
    menu += '<script type="application/json" id="state-data">%s</script>' % script_json(state)
    menu += '<script type="application/json" id="manage-data">%s</script>' % script_json(manage_data(T, workspace_context(ws), acting))
    menu += '<script type="application/json" id="find-data">%s</script>' % script_json(find_data(T, link, ZS, cmux, now.date()))
    shared = shared_launchers(ws)
    if shared is not None:
        menu += '<script type="application/json" id="launch-settings">%s</script>' % script_json(shared)
    guide_body, guide_pages = guide_tab(ws)
    home_tabs = ""
    if simple:
        home_tabs = (section("home", False, home_section(HW, now.date(), example, local, your_work_data(ws)))
                     + section("work", True, "".join(work_page(w, now.date(), kept.get(w["key"])) for w in HW)
                               + discovery_pages(ws, now.date())))
        overview = overview.replace('<section class="tab" id="tab-overview">', '<section class="tab" id="tab-overview" hidden>', 1)
    main = ('<main><div class="stale" id="stale"></div>%s%s%s%s%s</main>%s'
            % (home_tabs, overview, section("todo", True, todo_tab) if todo_tab else "", status_tab,
               section("guide", True, guide_body), menu))
    # The menu's script in an element of its own, and the graph's: an error
    # anywhere else on the page stops only the script it is in, and the app
    # still hears what its menu lists.
    # MANAGE_JS after the page's own, so it wraps the GarrickActed that PARK_JS sets,
    # FIND_JS after it, so its results are drawn again once a row has moved,
    # and WORK_JS after all three. The Guide's pages come last of all, after every
    # script, so reading past them never holds up the tabs that show the work.
    scripts = [RELOAD_JS + PANEL_JS + LAYOUT_JS + JS + PARK_JS + TVIEW_JS + TCHIP_JS + TADD_JS + TODO_JS + MENU_SETTINGS_JS + HOME_JS,
               MANAGE_JS, FIND_JS, WORK_JS, NOTIFY_JS, WAIT_JS, SIMPLE_JS, MENU_JS, guide_mod().GUIDE_JS, GRAPH_JS + FOLLOW_JS if show_graph else ""]
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title>%s<style>%s</style></head><body%s data-built="%s" data-launchers="%s"%s><div class="app">%s%s</div>%s'
            '<div id="tip" role="tooltip"></div><div id="toast" role="status"></div><div id="work" role="status" hidden></div>%s%s</body></html>' % (
                E(NAME), favicon(), CSS + SETTINGS_CSS + BAR_CSS + TVIEW_CSS + TADD_CSS + TODO_CSS + MANAGE_CSS + FIND_CSS + WORK_CSS + HOME_CSS + WAIT_CSS + SIMPLE_CSS + guide_mod().GUIDE_CSS + zone_css(),
                (' class="simple" data-tab="home"%s' % (' data-local="%s"' % local if local else "")) if simple else "",
                now.isoformat(timespec="seconds"), E(",".join(launch)), ' data-cli="1"' if cli else "", header, main, settings(ws, launch, tuple(T), ZS, show_graph, sched, layout),
                "".join("<script>%s</script>" % js for js in scripts if js), guide_pages))


def settle(marker: Path, seconds: float, sleep=time.sleep) -> bool:
    """Whether this build should go ahead after a burst of requests: each
    writes its own mark, waits, and builds only if no later one has written
    since. Ten sessions starting at once need one build, not ten. A mark
    that cannot be written or read lets the build go ahead."""
    me = "%d %.6f" % (os.getpid(), time.time())
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(me, encoding="utf-8")
    except OSError:
        return True
    sleep(seconds)
    try:
        return marker.read_text(encoding="utf-8").strip() == me
    except OSError:
        return True


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build the status page for a Garrick workspace.")
    ap.add_argument("--workspace", help="the workspace folder (default: GARRICK_WORKSPACE, or the folder this runs in)")
    ap.add_argument("--out", help="where to write the page (default: System/generated/status.html)")
    ap.add_argument("--obsidian", metavar="VAULT", help="link into Obsidian, with the workspace root opened as this vault "
                    "(by default the page uses the vaults Obsidian has registered)")
    ap.add_argument("--no-obsidian", action="store_true", help="link to the files themselves, even where Obsidian has a vault")
    ap.add_argument("--no-cmux", action="store_true", help="leave Open in cmux out, even where cmux is installed")
    ap.add_argument("--open", action="store_true", help="open the page when it is built")
    ap.add_argument("--no-graph", action="store_true", help="leave the graph out: the page then reads nothing but frontmatter")
    ap.add_argument("--settle", type=float, metavar="SECONDS", help="wait this long, and build only if no other build "
                    "was asked for meanwhile: a burst of requests makes one page")
    ap.add_argument("--also", action="append", default=[], metavar="FOLDER",
                    help="for effort: a folder the workspace used to live in, read as the workspace (repeatable)")
    ap.add_argument("--moved", action="append", default=[], metavar="OLD=NEW",
                    help="for effort: a folder renamed or moved, its old path and its path in the workspace now (repeatable)")
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
    if args.settle and args.settle > 0 and not settle(out.with_name(out.name + ".settle"), args.settle):
        return 0                              # a later request builds it
    out.parent.mkdir(parents=True, exist_ok=True)
    prefs().migrate(ws)          # choices a Garrick before 0.25.0 left in System/generated/, kept where they belong
    tmp = out.with_name(out.name + ".tmp")
    vaults = [] if args.obsidian or args.no_obsidian else obsidian_vaults(ws)
    flags = tuple(f for f, on in (("--no-obsidian", args.no_obsidian and not args.obsidian), ("--no-cmux", args.no_cmux)) if on)
    moved = {}
    for m in args.moved:
        if "=" not in m:
            print("status: --moved %r is not OLD=NEW; left out." % m, file=sys.stderr)
            continue
        old, new = m.split("=", 1)
        moved[old] = new
    flags += tuple(w for a in args.also for w in ("--also", a)) + tuple(w for o, n in moved.items() for w in ("--moved", "%s=%s" % (o, n)))
    tmp.write_text(build(ws, args.obsidian, show_graph=not args.no_graph, out=out.resolve() if args.out else None,
                         vaults=vaults, flags=flags, also=tuple(args.also), moved=moved,
                         managed=handoff_mod().managed_places(), cli=handoff_mod().find_claude() is not None,
                         launchers=tuple(k for k in launchers_installed() if not (args.no_cmux and k == "cmux"))), encoding="utf-8")
    os.replace(tmp, out)
    release_ask(ws)
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
