#!/usr/bin/env python3
"""The status page for a Garrick workspace. An optional extra.

    python3 status.py [--workspace FOLDER] [--out FILE] [--open] [--no-cmux] [--no-graph]
                      [--settle SECONDS] [--also FOLDER ...] [--moved OLD=NEW ...] [--same-flags] [--reuse-check [SECONDS]]

One self-contained HTML file that answers "is anything wrong, and where was I"
at a glance: every live thread by zone with how long since its resume point
moved, what the check found, open actions, what is waiting in the inboxes,
and, if you run scheduled jobs, how they ran and what the assistant spent.
A graph of the notes and the links between them, zone by zone, fills a card
at the top; click a note to open it or copy what to say about it. Hover a
thread in the list for the same actions. Every card can be dragged elsewhere
or hidden, and Reset view puts the page back.

**Show, don't store.** The page reads files the workspace and the jobs extra
already keep, and writes nothing but itself, the flags it was built with, the
check's last result and what effort.py last read of each transcript. It runs
no server, loads nothing from the network and carries no third-party script.
Delete it and nothing is lost: every fact on it lives in a file you own. Each
panel says where its numbers come from and how old they are. The
one call out is the release notice, off until System/garrick-settings.json
switches it on: then a build starts System/tools/release.py, at most once a
day and without waiting for it, and Needs attention names a newer Garrick
once GitHub has said there is one.

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
Your work, the list the Overview opens on (#503), is the one exception: a
piece of work means nothing without its next action, so it also shows the
Resume here block's Next action and Waiting on. It still
lives in System/generated/, never committed and outside the wall check.

**It offers what this machine has**, and asks at every build. Every link to
a note, a file or a folder is a file link (#318), and nothing opens Obsidian
unless it was chosen: in Garrick.app a project's hub or a thread's note opens
as its row does, through the default Settings › Opening a thread picks, and
anything else in the app macOS opens it in, a folder in Finder; in a browser the link is the browser's. In
Garrick.app (see `app/`), projects and threads also offer Reveal in
Finder and Open in Claude, Codex or cmux, for each one installed and switched
on in Settings, where one of them can also be what clicking a thread's name
does; `--no-cmux` leaves cmux out. Open in Claude on a thread hands it over
as Continue does (#180), through page_action.py's
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
the Mac app. Preview features (FLAGS) stay off until
System/garrick-flags.json switches them on. With the cmux extra beside this folder
(../cmux/cmuxlib.py), the page shows which projects and threads have a
session open, and its buttons can drive the desk. `--settle` lets a burst of
build requests make one page; `--also` and `--moved` reach effort.py.
Each build stores the flags that shape the page beside it, in
status.flags.json, and `--same-flags` builds with those, so a page that
scaffold.py or correct.py rebuilds looks as the app or the plugin last drew
it (#246). It cannot be given with those flags; the last build to store wins.
Each build keeps the check's result beside the page too, in
status.check.json, and `--reuse-check`, which those tools also
pass, shows that result, whatever its age, and never runs the check,
saying how old it is wherever its counts show (#260, #298, #382); with no
result kept it says so. A build by hand, on schedule or by the app runs the check. With Effort switched on, status.effort.json beside
the page holds what effort.py read of each transcript, so a build reads only
the transcripts that changed since: every session's working folder and the
paths of the files it wrote, in every zone. Both files go wherever --out
puts the page, named after it, so --out inside a zone puts them where a
commit can carry them into that zone's history.
A build whose status.py is replaced while it runs, as an update replaces it
during a `--settle` wait, writes nothing and builds again from the new file,
so the page is always drawn by the status.py on disk.

Copy this folder into your workspace as `System/status/`, next to
`System/jobs/` if you have it, and run it by hand or on a schedule through
job.py (see docs/extras/status-page.md). Standard library only, Python 3.9 or
later. Not installed by install.py.
"""

from __future__ import annotations

import argparse
import contextlib
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
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

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
# session open, and in the app offers Open and Close session, which the desk
# carries out. Without it, none of that is drawn.
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
# `behind`, a copy the share's colleagues have moved on from, is what the
# ledger expects of a `share` row, so the page leaves it out: Nurture lists it.
DRIFT_SAY = {"drifted": "has drifted from its shared copy", "missing": "is missing, here or on the share",
             "unread": "has a row in published.md that does not read",
             "conflict": "is a copy a sync conflict left on the share"}


def row_anchor(zone: str, project: str, thread: str = "") -> str:
    """The id of a project's or a thread's row on the Threads card, which a
    Needs attention row links (#323): "row-work-acme-review-pricing"."""
    return "row-" + re.sub(r"[^a-z0-9]+", "-", "/".join(x for x in (zone, project, thread) if x).lower()).strip("-")


def attn_row(k: str, t: str, h) -> str:
    """One row of Needs attention: a link to the card that explains it, or,
    for a published file that drifted, to its project's or thread's row,
    which the page opens and unfolds (`data-go`), with Show both beside it in
    the app (#323)."""
    if isinstance(h, dict):
        row = '<a href="%s" data-go="%s">%s<span>%s</span></a>' % (E(h["href"]), E(json.dumps(h["go"])), ICON[k], E(t))
        if h.get("reveal"):
            row = ('<div class="adrift">%s<button class="act apponly" type="button" data-reveal="%s" title="%s">Show both</button></div>'
                   % (row, E(json.dumps(h["reveal"])), E("Show the copy here and the shared copy in Finder, each in its own window")))
        return row
    return '<a href="%s"%s>%s<span>%s</span></a>' % (E(h), ' target="_blank" rel="noopener"' if h.startswith("https://") else "", ICON[k], E(t))


def drift_day(iso: object) -> str:
    """"30 Oct", from the date drift.py recorded; "" for none."""
    d = as_date(iso)
    return "%d %s" % (d.day, d.strftime("%b")) if d else ""


def drifted(ws: Path) -> List[dict]:
    """What drift.py last found worth a look, from System/generated/drift.json,
    which it writes when run from a session or the app: a launchd job may
    not read a cloud folder, so the page never compares anything itself.
    Each with the sentence its Needs attention row says, which copy changed
    and when for one that drifted, and where its row leads: the thread's row
    on the Threads card for a file in a thread, else the project's (#323).
    `both` says drift.json names the two copies, for Show both."""
    try:
        data = json.loads(ws.joinpath(*DRIFT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for f in data.get("files", []) if isinstance(data, dict) else []:
        if not (isinstance(f, dict) and f.get("state") in DRIFT_SAY):
            continue
        project, name = str(f.get("project") or "?"), str(f.get("file") or "")
        thread = str(f.get("thread") or "")
        parts = name.split("/")
        if not thread and len(parts) > 2 and parts[0] == "Threads":
            thread = parts[1]                       # kept in a thread's folder, named from the project's
        where = project + (", " + thread if thread else "")
        here, shared = drift_day(f.get("here_changed")), drift_day(f.get("shared_changed"))
        if f["state"] == "drifted" and here and shared and f.get("newer") in ("here", "shared"):
            first, then = ("the shared copy", "the copy here") if f["newer"] == "shared" else ("the copy here", "the shared copy")
            said = "%s: %s: %s changed on %s, after %s (%s)" % (
                where, parts[-1], first, shared if f["newer"] == "shared" else here, then, here if f["newer"] == "shared" else shared)
        else:
            said = "%s: %s %s" % (where, name or "published.md", DRIFT_SAY[f["state"]])
        out.append({"text": said, "zone": str(f.get("zone") or ""), "project": project, "thread": thread,
                    "ledger": str(f.get("thread") or ""), "file": name,
                    "both": f["state"] == "drifted" and bool(f.get("here")) and bool(f.get("shared"))})
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
    # Lines end where garrick_lib's parse_frontmatter_text ends them, as YAML
    # does: at \n, \r\n or a lone \r, never at U+2028 and the like (#330).
    lines = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict = {}
    key = None
    for line in lines[1:]:
        if line in ("---", "..."):             # a `---` alone at the margin closes it, as for YAML
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
    that page; Your work reads the rest through resume_read()."""
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
    resume_point()). Also `where`, its Where it stands
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
        E("Work recorded at %s that no wrap has folded in yet. Open the thread to read it: "
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
               "time, read from Claude Code's own transcripts. The nightly job, gr-nightly, records them, so days outlive their clean-up."),
}


def preview_flags(ws: Path) -> Dict[str, bool]:
    try:
        data = json.loads(ws.joinpath("System", "garrick-flags.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return {k: data.get(k) is True for k in FLAGS}


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
    what was ticked today, with counts of the open, the late and the
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
                        link=link.attrs(note) if note else "", zone=zone.name,
                        alpha=("%s\u0001%s" % (thread or ("\uffff" if t["unsure"] else ""), plain_text(t["text"]))).casefold())

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
        cls = "late" if r["late"] else "today" if when == today else ""
    name = r["label"] or ("thread?" if r["unsure"] else "")
    thr = ('<a class="thr" %s>%s</a>' % (r["link"], E(name)) if r["link"] and name
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
    tick = ('<button class="tick" type="button" title="%s" aria-label="%s: %s"></button>'
            % ("Reopen" if r["done"] else "Mark done", "Reopen" if r["done"] else "Mark done", E(plain_text(r["text"])[:80])) if actions else "")
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
    one of them is late; `checks`, the error findings
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


# Context debt (#69), beside the check's findings: what Nurture left, weighed
# by kind, as the workspace's own nurture.py keeps it in each day's record.
# The page reads the records through that module and runs nothing. No record
# of the whole workspace yet, or a nurture.py older than the debt, shows
# nothing: a zero would look measured.
DEBT_DAYS = 30


def debt_history(ws: Path, today: dt.date) -> Tuple[List[Tuple[dt.date, dict]], Callable[[str], Tuple[str, str]]]:
    """(day, debt) for the last DEBT_DAYS days that have a record of the
    whole workspace, oldest first, and how nurture.py names a scope and the
    request that nurtures it; [] without a record, or without a nurture.py
    that keeps them."""
    lib = nurture_lib(ws)
    N = lib[0] if lib is not None else None
    if N is None or not callable(getattr(N, "debt_history", None)) or not callable(getattr(N, "scope_said", None)):
        return [], lambda scope: (scope, "")
    try:
        return [(d, x) for d, x in N.debt_history(ws, today, DEBT_DAYS) if isinstance(x, dict)], N.scope_said
    except Exception:
        return [], N.scope_said


def debt_line(history: List[Tuple[dt.date, dict]]) -> str:
    """The one line of the context debt on the Context card (#541, #542): the figure of the latest Nurture record against its
    threshold, red when over it, and when that run was. Nothing before the first record, which would only be guessing a figure."""
    if not history:
        return ""
    day, debt = history[-1]
    total, threshold = debt["total"], debt.get("threshold", 40)
    over = total > threshold
    return '<p class="hint ndebt"><span%s>%s</span> · Last nurture %s</p>' % (
        ' class="over"' if over else "", E("Context debt %s, %s %s" % (debt_points(total), "over" if over else "under" if total < threshold else "at",
                                                                       debt_points(threshold))), E(day.strftime("%a %d %b")))


def debt_points(n):
    return int(n) if float(n).is_integer() else round(n, 2)


def nurture_outcome(ws: Path, day: dt.date) -> Optional[dict]:
    """What Nurture's record for `day` says it fixed, was answered and left,
    as nurture.py's day_outcome() reads it; None without one."""
    lib = nurture_lib(ws)
    N = lib[0] if lib is not None else None
    if N is None or not callable(getattr(N, "day_outcome", None)):
        return None
    try:
        return N.day_outcome(ws, day)
    except Exception:
        return None


def counted(n: int, one: str, many: str = "") -> str:
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


def nurture_said(kinds: Dict[str, int]) -> str:
    """What one pass of Nurture over a scope does with what stands there, by
    kind: "2 walls named, 4 fixes on one yes, 1 question one at a time"."""
    said = [(kinds.get("wall", 0), counted(kinds.get("wall", 0), "wall") + " named"),
            (kinds.get("mechanical", 0), counted(kinds.get("mechanical", 0), "fix", "fixes") + " on one yes"),
            (kinds.get("attribution", 0), counted(kinds.get("attribution", 0), "question") + " one at a time")]
    said.append((kinds.get("correction", 0), counted(kinds.get("correction", 0), "correction") + " to confirm"))
    rest = sum(n for k, n in kinds.items() if k not in ("wall", "mechanical", "attribution", "correction"))
    said.append((rest, "%d for your judgment" % rest))
    return ", ".join(words for n, words in said if n)


# What the Context card says (#530, #542): which scopes need the user, and for how long, from the one-pass forecast (the
# latest Nurture record's standing findings by scope), and one word for the trend over the last TREND_DAYS nights.
# The minutes are a fixed cost per kind, summed and rounded up to five; never a range.
MINUTES_WALL, MINUTES_CALL, MINUTES_STEP = 2, 1, 5
TREND_DAYS, TREND_LEAST, TREND_SHARE = 14, 7, 0.2


def minutes_for(walls: int, calls: int) -> int:
    """About how long a scope takes: two minutes a wall finding and one a judgment call, rounded up to a multiple
    of five, so at least five."""
    raw = walls * MINUTES_WALL + calls * MINUTES_CALL
    return max(MINUTES_STEP, -(-raw // MINUTES_STEP) * MINUTES_STEP)


def scope_order(scope: str) -> Tuple[int, str]:
    """Zones first, by name, then the wikis, then System."""
    return (0 if scope.startswith("Zones/") else 1 if scope.startswith("Wikis/") else 2, scope.casefold())


def needing_you(scopes: Dict[str, Dict[str, int]]) -> List[dict]:
    """One entry for each scope whose standing findings need the user: `walls`, and `calls`, every kind that is
    neither a wall nor mechanical. A scope with only mechanical findings has none."""
    out = []
    for scope in sorted(scopes, key=scope_order):
        kinds = scopes[scope]
        walls = int(kinds.get("wall", 0))
        calls = sum(int(n) for k, n in kinds.items() if k not in ("wall", "mechanical"))
        if walls or calls:
            out.append({"scope": scope, "walls": walls, "calls": calls, "minutes": minutes_for(walls, calls)})
    return out


def need_said(n: dict) -> str:
    parts = [p for p in (counted(n["walls"], "wall finding") if n["walls"] else "",
                         counted(n["calls"], "judgment call") if n["calls"] else "") if p]
    return "%s, about %d minutes" % (" and ".join(parts), n["minutes"])


def trend_word(history: List[Tuple[dt.date, dict]], today: dt.date) -> str:
    """rising, steady or falling over the last TREND_DAYS nights (#530): a least-squares line through the nights
    that have a record, its value at the last such night against its value at the first. More than TREND_SHARE
    apart is rising or falling; else steady. Fewer than TREND_LEAST nights with a record, or a fitted first value
    at or below zero (a share of nothing says nothing), give no word."""
    window = [(d, x["total"]) for d, x in history if d > today - dt.timedelta(days=TREND_DAYS) and isinstance(x.get("total"), (int, float))]
    if len(window) < TREND_LEAST:
        return ""
    xs = [(d - window[0][0]).days for d, _ in window]
    ys = [float(y) for _, y in window]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var else 0.0
    first, last = my + slope * (xs[0] - mx), my + slope * (xs[-1] - mx)
    if first <= 0:
        return ""
    if abs(last - first) > TREND_SHARE * first:
        return "rising" if last > first else "falling"
    return "steady"


def trend_chip(word: str) -> str:
    if not word:
        return ""
    return '<span class="chip%s" id="trend" data-tip="%s">%s</span>' % (
        " late" if word == "rising" else "", E("The context debt over the last %d nights" % TREND_DAYS), E(word.capitalize()))


_FQ = None


def queue_mod():
    """finding_queue.py, beside this file: the plain wording of a finding and the answers to it (#535)."""
    global _FQ
    if _FQ is None:
        spec = importlib.util.spec_from_file_location("garrick_finding_queue", str(Path(__file__).with_name("finding_queue.py")))
        _FQ = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_FQ)
    return _FQ


def forecast_items(ws: Path, day: dt.date) -> List[dict]:
    """The standing findings of the Nurture record of `day` that weigh anything, each with its scope: the one-pass
    forecast, as nurture.py's day_outcome() counts it. The list the card's lines and the queue are both made from, so
    a line's number and its queue's are one. [] without a record or a nurture.py that keeps them."""
    lib = nurture_lib(ws)
    N = lib[0] if lib is not None else None
    if N is None or not getattr(N, "REPORTS", None) or not callable(getattr(N, "debt_settings", None)) or not callable(getattr(N, "debt_scope", None)):
        return []
    try:
        rec = json.loads(Path(ws).joinpath(*N.REPORTS, "%s.json" % day.isoformat()).read_text(encoding="utf-8"))
        weights, _ = N.debt_settings(Path(ws))
    except (OSError, ValueError):
        return []
    out = []
    for f in rec.get("standing") or [] if isinstance(rec, dict) else []:
        kind = str(f.get("kind", "")) if isinstance(f, dict) else ""
        # a wall is on the card whatever its weight: the weight sets the debt figure, not whether a wall shows
        if kind and (kind == "wall" or weights.get(kind, getattr(N, "UNKNOWN_WEIGHT", 1))):
            path = re.sub(r":\d+$", "", str(f.get("path", "")))
            out.append({"kind": kind, "path": path, "line": str(f.get("line") or ""), "check": str(f.get("check") or ""),
                        "scope": N.debt_scope(path)})
    return out


def quick_messages(ws: Path, C: Optional[dict]) -> Dict[Tuple[str, str], str]:
    """The quick check's own text for each finding, by (path, check), a wall's by (path, "wall"): what the queue's
    Details and its figures use where the card has them. Nothing run: the card's check result, as it is."""
    out: Dict[Tuple[str, str], str] = {}
    lib = nurture_lib(ws)
    words = tuple(getattr(lib[0], "WALL_WORDS", ())) if lib is not None else ()
    for f in (C or {}).get("findings", []) if C and not C.get("failed") and not C.get("pending") else []:
        path, message, check = re.sub(r":\d+$", "", str(f.get("path") or "")), str(f.get("message") or ""), str(f.get("check") or "")
        wall = check == "walls" or any(w in message for w in words)
        out.setdefault((path, "wall" if wall else check), message)
    return out


def quick_needs(ws: Path, C: Optional[dict], covered: Dict[str, List[dict]]) -> List[dict]:
    """The quick check's wall findings and errors in a scope no question covers (#535): items for the queue, built
    from the card's own check result, so a wall or an error the check lists is never behind "Nothing needs you."
    A wall is listed, with the check's text, as a record's wall is; any other error is a finding of its own kind."""
    lib = nurture_lib(ws)
    N = lib[0] if lib is not None else None
    if N is None or not callable(getattr(N, "debt_scope", None)) or not C or C.get("failed") or C.get("pending"):
        return []
    words = tuple(getattr(N, "WALL_WORDS", ()))
    out, seen = [], set()
    for f in C.get("findings", []):
        path, message, check = re.sub(r":\d+$", "", str(f.get("path") or "")), str(f.get("message") or ""), str(f.get("check") or "")
        wall = check == "walls" or any(w in message for w in words)
        if not wall and str(f.get("severity") or "") != "error":
            continue
        scope = N.debt_scope(path)
        if covered.get(scope) or (path, wall, message) in seen:
            continue
        seen.add((path, wall, message))
        out.append({"kind": "wall" if wall else "judgment", "check": "" if wall else check, "path": path, "scope": scope,
                    "line": "%s: %s" % (path, message) if path else message, "message": message, "listed": True,
                    "title": check.capitalize() if check else "Check finding"})
    return out


def finding_queues(ws: Path, history: List[Tuple[dt.date, dict]], C: Optional[dict], today: dt.date,
                   said: Callable[[str], Tuple[str, str]]) -> Optional[Dict[str, List[dict]]]:
    """{scope: its questions} for every scope that needs the user, from the forecast's findings, each enriched with
    the quick check's text where it has the same path and check (a wall: the same path); None when this page has no
    queue to build, and the card then keeps its Nurture button. Built for every scope at page build, as the findings
    list was: it shows no more than that list did."""
    if not history:
        return {}
    try:
        fq = queue_mod()
        items = forecast_items(ws, history[-1][0])
        quick = quick_messages(ws, C)
        if C and not C.get("failed") and not C.get("pending"):
            # the quick check is current: a finding it no longer lists is gone now (an answer applied since the record
            # was written), so it is not asked again. A wall is never dropped this way.
            items = [it for it in items if it["kind"] == "wall" or (it["path"], it["check"]) in quick]
        for it in items:
            plain = fq.plain_kind(it)
            message = quick.get((it["path"], "wall" if it["kind"] == "wall" else it["check"]))
            it["ask"] = said(it["scope"])[1]
            if it["kind"] == "wall":
                it["listed"] = message is not None
            if message:
                it["message"] = message
            elif plain in fq.PLAIN_KINDS and it["kind"] != "wall":
                it["message"] = it["line"][len(it["path"]) + 2:] if it["line"].startswith(it["path"] + ": ") else it["line"]
        hidden = fq.later_hidden(ws, today)
        planner = fq.Planner(ws)           # one plan budget for the whole build
        queues = fq.forecast_questions(items, hidden, ws, planner)
        extra = quick_needs(ws, C, queues)
        for it in extra:
            it["ask"] = said(it["scope"])[1]
        for scope, qs in fq.forecast_questions(extra, hidden, ws, planner).items():
            queues.setdefault(scope, qs)
        return queues
    except Exception:
        return None


def scope_title(scope: str, said: Callable[[str], Tuple[str, str]]) -> str:
    """A place as the card's line and the queue's bar name it: a zone by its name, a wiki as "The Meetings wiki"."""
    name = said(scope)[0]
    if name == scope:
        name = scope.split("/", 1)[-1]
    return name[:1].upper() + name[1:]


def work_place(scope: str, said: Callable[[str], Tuple[str, str]]) -> str:
    """A place as the request "work in the answers in <place>" names it: a zone by its name, a wiki as "the Knowledge wiki"."""
    place = said(scope)[0]
    return scope.split("/", 1)[-1] if place == scope else place


def answered_in(qdata: Optional[dict], scope: str) -> int:
    """How many answers wait to be worked in for one place: a zone's own, or the Knowledge wiki's; 0 for any other, and
    never the sum of two."""
    if not qdata:
        return 0
    if scope == "Wikis/Knowledge":
        return int(qdata.get("knowledge_answered") or 0)
    if scope.startswith("Zones/"):
        return int(((qdata.get("buckets") or {}).get(scope.split("/", 1)[1]) or {}).get("answered") or 0)
    return 0


def nurture_lines(ws: Path, history: List[Tuple[dt.date, dict]], said: Callable[[str], Tuple[str, str]]) -> str:
    """Without a findings queue: a line for each place the last Nurture record says needs the user, handing Nurture's
    request to the assistant. Names of places and counts only."""
    if not history:
        return ""
    out = ""
    for n in needing_you((nurture_outcome(ws, history[-1][0]) or {}).get("scopes") or {}):
        name, phrase = said(n["scope"])
        button = request_button("Nurture", phrase, ws, "act dask") if phrase else ""
        out += '<div class="need"><span class="nsay">%s: %s</span>%s</div>' % (E(name[:1].upper() + name[1:]), E(need_said(n)), button)
    return out


def need_lines(ws: Path, history: List[Tuple[dt.date, dict]], said: Callable[[str], Tuple[str, str]],
               queues: Optional[Dict[str, List[dict]]] = None, qdata: Optional[dict] = None, failed: bool = False) -> str:
    """The Context card's lines (#542): one for each zone or wiki that holds something, such as *Work: 6 questions · 4 answers
    about 10 minutes*, with *Go through them*, which opens that place's queue (#535). A place with nothing has no line, and an
    answer waiting to be worked in is no line: closing the queue and the nightly run work it in (#550). Under the title, how many places need the user and
    nothing more, since two places' counts and minutes are never added; with no line at all, *Nothing needs you.*, said only
    once a Nurture record exists, which would otherwise be guessing. Each count is of one place's queue: its questions,
    verdicts, decisions and findings together. Without a queue (a page built without one) a line hands Nurture's request to
    the assistant. Names of places, counts, minutes only: no path, project or finding text of any zone."""
    if queues is None:
        if not history:
            return ""
        return nurture_lines(ws, history, said) or '<p class="hint nonee">Nothing needs you.</p>'
    places = sorted({sc for sc, qs in queues.items() if qs}, key=scope_order)
    out = ""
    for scope in places:
        qs = queues.get(scope) or []
        walls = sum(1 for q in qs if q["id"] == "wall")
        said_ = [counted(len(qs), "question"), "about %d minutes" % minutes_for(walls, len(qs) - walls)]
        buttons = '<button class="act primary" type="button" data-qopen="%s">Go through them</button>' % E(scope)
        out += ('<div class="need" data-scope="%s" data-n="%d"><span class="nsay"><b>%s</b>: %s</span><span class="nbtn">%s</span></div>'
                % (E(scope), len(qs), E(scope_title(scope, said)), E(" · ".join(said_)), buttons))
    if failed:              # the findings read failed: the wiki's own questions above, Nurture's lines for the rest, never "Nothing needs you."
        out += nurture_lines(ws, history, said)
    if not out:
        return '<p class="hint nonee" id="nsum">Nothing needs you.</p>' if history and not failed else ""
    zones = ('<label class="nzone">Zone <select id="nzone" aria-label="Zone"><option value="*">All</option>%s</select></label>'
             % "".join('<option value="%s">%s</option>' % (E(sc), E(scope_title(sc, said))) for sc in places) if len(places) > 1 else "")
    return ('<div class="nhead"><p class="hint nsum" id="nsum" data-some="1">%s need%s you.</p>%s</div>%s'
            % (E(counted(len(places), "place")), "s" if len(places) == 1 else "", zones, out))


def override_times(ws: Path) -> List[str]:
    """When each wall override of the last 30 days fell, from garrick_lib's read of the refusal record; [] when
    this workspace's library has no such read."""
    read = getattr(workspace_lib(ws), "refusal_override_times", None)
    try:
        return list(read(ws)) if read else []
    except Exception:
        return []


def override_note(ws: Path, go: str = "") -> str:
    """The line for a wall override the user has not seen (#530), hidden until CHECKS_JS finds one newer than the
    last time this browser opened the card. The page holds the times only: no count, path, name or text. `go` is the
    place whose queue holds most wall findings (#541): the line opens that queue; without one it is plain text."""
    return '<p class="hint dnew" id="newover" data-over="%s"%s hidden></p>' % (E(json.dumps(override_times(ws))), ' data-go="%s"' % E(go) if go else "")


def wall_place(queues: Optional[Dict[str, List[dict]]]) -> str:
    """The scope whose queue holds the most wall findings, the first by scope_order on a tie; "" with none or no
    queue. A name the page already carries for its queues, never a count of two places."""
    best, most = "", 0
    for scope in sorted(queues or {}, key=scope_order):
        n = sum(1 for q in queues[scope] if q.get("id") == "wall")
        if n > most:
            best, most = scope, n
    return best


CHECKS_JS = r"""
(function(){var card=document.getElementById('checks'),KEY='garrick-checks-seen';
var st={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,x){try{localStorage.setItem(k,x)}catch(e){}}};
function usable(){try{localStorage.setItem('garrick-probe','1');localStorage.removeItem('garrick-probe');return true}catch(e){return false}}
var note=document.getElementById('newover');
function seen(){if(note)note.hidden=true;st.set(KEY,new Date().toISOString())}
function say(t0,n){var d=new Date(t0),days=(Date.now()-d.getTime())/864e5,w=days<6?d.toLocaleDateString('en-GB',{weekday:'long'}):d.toLocaleDateString('en-GB',{day:'numeric',month:'short'});
return n+' wall override'+(n===1?'':'s')+' since '+(new Date().toDateString()===d.toDateString()?'earlier today':w)}
if(note&&usable()){var s=st.get(KEY),t0=s?Date.parse(s):NaN,over=[];try{over=JSON.parse(note.dataset.over||'[]')}catch(e){}
var n=isNaN(t0)?0:over.filter(function(x){return Date.parse(x)>t0}).length;
if(n){note.textContent='';var go=note.dataset.go;
if(go){var a=document.createElement('a');a.href='#';a.setAttribute('data-qopen',go);a.setAttribute('data-seen','');a.textContent=say(t0,n);note.appendChild(a)}else note.textContent=say(t0,n);
note.hidden=false}
else st.set(KEY,new Date().toISOString())}
if(card){var sum=card.querySelector('summary');if(sum)sum.addEventListener('click',function(){if(usable())seen()})}
document.addEventListener('click',function(e){var t=e.target;if(t&&t.closest&&t.closest('[data-seen]')&&usable())seen()});
})();
"""

CONTEXT_JS = r"""
(function(){var card=document.getElementById('checks');if(!card)return;
var sel=document.getElementById('nzone'),sum=document.getElementById('nsum'),tn=document.getElementById('qp-tab-n'),KEY='garrick-context-zone';
var lines=[].slice.call(card.querySelectorAll('.need[data-scope]'));
function ss(k,v){try{if(v===undefined)return sessionStorage.getItem(k);sessionStorage.setItem(k,v)}catch(e){return null}}
/* The Zone menu filters the lines. Each line is one place's own, so what shows is a place's count or nothing, and a number for the tab is a single place's, never a sum */
function apply(){var z=sel?sel.value:'*',shown=lines.filter(function(l){var on=z==='*'||l.dataset.scope===z;l.hidden=!on;return on});
if(sum&&sum.dataset.some)sum.textContent=shown.length+' place'+(shown.length===1?' needs you.':'s need you.');
if(tn)tn.textContent=z!=='*'&&shown.length&&shown[0].dataset.n!=='0'?shown[0].dataset.n:''}
if(sel){var k=ss(KEY);if(k&&lines.some(function(l){return l.dataset.scope===k}))sel.value=k;
sel.onchange=function(){ss(KEY,sel.value);apply()}}
apply();
window.GarrickQuestions={open:function(){if(window.StatusTab)StatusTab('questions');window.scrollTo(0,0);var b=card.querySelector('.need:not([hidden]) [data-qopen]');if(b)b.focus()}}})();
"""

DEBT_CSS = r"""
/* The Context card's lines: what needs the user, place by place, and the context debt in one line under the last nurture */
.ndebt{margin:12px 0 0}.ndebt .over{color:var(--critical);font-weight:600}
.nhead{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:0 0 6px}.nsum{margin:0}
.nzone{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--ink2)}
.nzone select{font:inherit;font-size:13px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:4px 8px}
.need[hidden]{display:none}.nbtn{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.need{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 0;border-top:1px solid var(--line)}
.need:first-of-type{border-top:0}.nsay{font-size:13.5px}.nonee{margin:0}.dnew a{color:var(--critical);font-weight:600}
dialog.findings{width:min(720px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow:auto;border:1px solid var(--line);border-radius:14px;background:var(--surface);color:var(--ink);padding:20px 22px;box-shadow:0 18px 60px rgba(0,0,0,.25)}
dialog.findings::backdrop{background:rgba(0,0,0,.28)}.fhead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 14px}.fhead h3{margin:0;font-size:16px}
"""


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
    colour and with its icon from Settings › Zones; All, Late and No date
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
                     '<span class="n">%d</span></summary><div class="trows">%s</div></details>'
                     % (slug, CHEV, len(z["done"]), "".join(todo_row(r, today, actions) for r in z["done"])))
        add = ('<button type="button" class="act primary tadd-open" data-zone="%s" title="Add an action to %s/Todo.md">＋ Add</button>'
               % (E(z["zone"]), E(z["zone"]))) if actions and z["file"] else ""
        opener = ('<a class="act" href="%s" title="Open %s/Todo.md">Open Todo.md</a>' % (E(link(z["file"])), E(z["zone"]))
                  if link and z["file"] else "")
        summ = ('<b>%d</b> open · <span class="%s"><b>%d</b> late</span> · <b>%d</b> without a date'
                % (z["open"], "bad" if z["late"] else "", z["late"], z["undated"]))
        panes += '<div class="tz" data-zone="%s"><div class="tsum">%s<span class="tsum-acts">%s%s</span></div>%s</div>' % (
            E(z["zone"]), summ, add, opener, body)
    zones = "".join('<button type="button" data-tz="%s"%s>%s<span class="n">%d</span></button>'
                    % (E(z["zone"]), zone_attr(z["zone"], styles), zone_name(z["zone"], styles), z["open"])
                    for z in lists)
    bar = ('<div class="tbar"><div class="seg zseg" role="group" aria-label="Zone"%s>%s</div>'
           '<div class="seg fseg" role="group" aria-label="Show"><button type="button" data-tf="all">All</button>'
           '<button type="button" data-tf="late">Late</button><button type="button" data-tf="nodate">No date</button></div>'
           '<div class="seg sseg" role="group" aria-label="Sort"><button type="button" data-ts="alpha" title="By thread, then by the action">A–Z</button>'
           '<button type="button" data-ts="date" title="Dated lines first, soonest first; then the rest, A–Z">Due date</button></div></div>'
           % (" hidden" if len(lists) < 2 else "", zones))      # a box and a date chip explain themselves (#235)
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
    body, held = gd.guide(ws.joinpath(*gd.DOCS), ref)
    return zone_flags(ws) + body, held


ZONE_RULE = ("Each zone is either <b>walled</b> or <b>open</b>. What is in a walled zone stays in that zone; what is in an open "
             "zone may go anywhere. Knowledge and System reach every zone, and a conversation that touches two walled zones "
             "is split before it is filed.")


def zone_flags(ws: Path) -> str:
    """The Guide's Walls block: the rule in three sentences, and one line per zone, walled or open, with the command
    that changes it. Read-only: the page flips nothing; the flag is changed with scaffold.py. Nothing without zones."""
    ctx = workspace_context(ws)
    flags = ctx.get("zone_walled") or {}
    if not flags:
        return ""
    rows = "".join('<li><b>%s</b>: %s <code>python3 System/tools/scaffold.py zone --name %s --%s</code></li>'
                   % (E(z), "walled" if w else "open", E(z), "open" if w else "walled") for z, w in sorted(flags.items()))
    note = ('<p class="muted">These flags are read from your Parties and Zones tables until the update to zone walls is '
            'accepted.</p>' if ctx.get("pending") else "")
    return ('<section class="gd-zones" id="guide-zones"><h2>Walls</h2><p>%s</p><ul>%s</ul>%s</section>' % (ZONE_RULE, rows, note))


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
        """The whole, in one line under the columns; its title holds what no
        row showed, by kind, so the card's figures add up, and how they are
        counted (#228)."""
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
        tip = ("%sClaude Code sessions, read from their transcripts; Codex is not counted yet. Active time counts the gaps "
               "between messages up to five minutes. A project's figure includes its work in no thread. Scheduled jobs are in "
               "Assistant calls." % ((" · ".join(parts) + ". ") if parts else ""))
        return ('<p class="hint me efoot" title="%s"><b>Last %d days: %s active · %s at list price · %d session%s</b></p>'
                % (E(tip), self.DAYS, E(say_time(self.total["seconds"])), E(say_cost(self.total["cost"])), self.total["sessions"],
                   "" if self.total["sessions"] == 1 else "s"))


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
.efoot{margin-top:10px;cursor:help}.efoot b{font-weight:600;color:var(--ink2)}
.chip.tchip{font:inherit;font-size:12px;line-height:1.45;background:none;cursor:pointer}.chip.tchip:hover{border-color:var(--base)}
.chip.todo.ok{color:var(--good);border-color:color-mix(in srgb,var(--good) 45%,transparent)}.chip.tchip[aria-expanded="true"]{background:var(--wash)}
.tpop{grid-column:1/-1;margin:2px 0 4px 16px;padding:4px 6px;background:var(--surface);border:1px solid var(--line);border-radius:10px;font-size:13px}
.tpop[hidden]{display:none}.tpop-h{margin:4px 8px 2px;font-size:12px;color:var(--muted)}.tpop .trows{padding:0}.tpop .lateby{color:var(--critical)}
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
document.querySelectorAll('.tview,.yrows').forEach(function(v){v.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('button.tchip');if(!b)return;
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
.act.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}.act.primary:hover{filter:brightness(1.08);color:var(--accent-ink)}
dialog.tadd{width:min(520px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow:auto;border:1px solid var(--line);border-radius:14px;background:var(--surface);color:var(--ink);padding:20px 22px;box-shadow:0 18px 60px rgba(0,0,0,.25)}
dialog.tadd::backdrop{background:rgba(0,0,0,.28)}
.tadd h3{margin:0 0 14px;font-size:16px}.tadd .tlab{display:flex;align-items:center;gap:8px;margin:14px 0 6px;font-size:12px;font-weight:600;color:var(--ink2)}
.tadd .tlab .hint{font-weight:400}.tadd input[type=text],.tadd input[type=search],.tadd input[type=date]{font:inherit;font-size:13px;color:var(--ink);background:var(--raise);border:1px solid var(--line);border-radius:8px;padding:7px 10px}
.tadd #tadd-text{width:100%}.tadd #tadd-filter{margin-left:auto;width:150px;padding:4px 8px;font-size:12px}
.ttrees{border:1px solid var(--line);border-radius:10px;background:var(--raise);max-height:260px;overflow:auto;padding:6px 8px}
.tnode{display:inline-flex;align-items:center;gap:7px;padding:4px 2px;font-size:13px;cursor:pointer}.tnode input{accent-color:var(--accent);margin:0}
.tproj{display:flex;flex-wrap:wrap;align-items:center;gap:2px 4px;border-top:1px solid var(--grid)}.tproj small{color:var(--muted);font-size:12px}
.tsep{font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);padding:10px 2px 2px;border-top:1px solid var(--grid)}
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
+(k==='thread'?'<button class="act" type="button" data-manage="move" data-mg="'+m+'">Move…</button>':'')
+'<button class="act" type="button" data-manage="delete" data-mg="'+m+'">Delete…</button></div>'};
function dialog(title,body,buttons){var d=document.getElementById('gmanage');if(d)d.remove();d=document.createElement('dialog');d.id='gmanage';
d.className='tadd gmanage';d.innerHTML='<h3>'+esc(title)+'</h3>'+body+'<p class="mg-msg" id="mg-msg"></p><div class="mg-row">'+buttons+'</div>';
document.body.appendChild(d);d.addEventListener('close',function(){d.remove()});d.addEventListener('click',function(e){if(e.target===d)d.close()});
d.showModal();var c=d.querySelector('[data-cancel]');if(c){c.onclick=function(){d.close()};}return d}
function field(id,label,value){return'<label class="tlab" for="'+id+'">'+esc(label)+'</label><input type="text" id="'+id+'" value="'+esc(value||'')+'" autocomplete="off">'}
/* a chosen value the list does not hold is added and selected, never dropped for the first option (#353) */
function select(id,label,opts,chosen){if(chosen&&!opts.some(function(x){return(Array.isArray(x)?x[0]:x)===chosen}))opts=[[chosen,chosen+' (not yet on the page)']].concat(opts);
return'<label class="tlab" for="'+id+'">'+esc(label)+'</label><select id="'+id+'">'
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
function projects(){var p=(D.zones[val(d,'mg-zone')]||{}).projects||[];d.querySelector('#mg-p').innerHTML=p.length?select('mg-project','Project',p,mg&&mg[0]===val(d,'mg-zone')?mg[1]:''):'<p class="mg-msg">No project in this zone yet: make one first.</p>'}
d.querySelector('#mg-zone').onchange=projects;projects();watch(d);d.querySelector('#mg-name').focus();
d.querySelector('[data-go]').onclick=function(){var q={verb:'new-thread',zone:val(d,'mg-zone'),project:val(d,'mg-project'),name:val(d,'mg-name')};
if(!q.project||!q.name)return bad(d,'Pick a project and give the thread a name.');if(busy(d,q.zone))return;
d.close();if(act)send(q,'Making '+q.name+' in '+q.project+'…');else copy('new thread '+q.name+' in '+q.project,'Copied “new thread '+q.name+' in '+q.project+'”. Paste it to your assistant.')}}
function newProject(){var zs=zoneNames(),z=zoneOf(),NEW='__new__';if(!zs.length){say('There is no zone yet.');return}
/* D.first is the name a project's first thread gets when none is typed: ask.py's FIRST_THREAD, put in the page's data */
var first=D.first||'',
d=dialog('New project',select('mg-zone','Zone',zs,z)+field('mg-name','Name, one you can say')+DUP+'<div id="mg-pt"></div>'
+'<div id="mg-np" hidden>'+field('mg-newparty','The party’s name')+'<p class="mg-msg mg-dup" id="mg-pdup" role="status" hidden></p>'+field('mg-what','What it is')+'</div>'
+'<label class="tlab" for="mg-thread">Its first thread, if you want one</label><input type="text" id="mg-thread" autocomplete="off" placeholder="'
+esc(first?'Empty gives '+first:'Empty gives a first thread of its own')+'">',
CANCEL+'<button class="act primary" type="button" data-go>'+(act?'Make it':'Copy the phrase')+'</button>');
function names(){return((D.zones[val(d,'mg-zone')]||{}).parties||[]).map(function(x){return x[1]})}
/* a party name close to one this zone has, by the test the project names get: it warns, and Make it still makes it */
function pdup(){var m=d.querySelector('#mg-pdup'),n=val(d,'mg-newparty'),F=window.GarrickFind,hits=F&&n?names().filter(function(x){return F.soundsAlike(n,x)}):[];
m.hidden=!hits.length;m.innerHTML=hits.length?'Already there: '+esc(hits.join('; '))+'.':''}
function pick(){d.querySelector('#mg-np').hidden=val(d,'mg-party')!==NEW;pdup()}
function parties(){var p=(D.zones[val(d,'mg-zone')]||{}).parties||[];
d.querySelector('#mg-pt').innerHTML=select('mg-party','For',[['','None']].concat(p,[[NEW,'New party…']]),'');d.querySelector('#mg-party').onchange=pick;pick()}
d.querySelector('#mg-zone').onchange=parties;parties();watch(d);d.querySelector('#mg-newparty').addEventListener('input',pdup);d.querySelector('#mg-name').focus();
d.querySelector('[data-go]').onclick=function(){var pt=val(d,'mg-party'),np=pt===NEW,th=val(d,'mg-thread'),w=val(d,'mg-what'),z2=val(d,'mg-zone'),nm=val(d,'mg-name'),q;
if(!nm)return bad(d,'A project needs a name.');
/* two shapes, one request each: only the New party… choice sends the verb that adds a party (#522) */
if(np){var r={verb:'new-project-party',zone:z2,name:nm};r.new_party=val(d,'mg-newparty');if(!r.new_party)return bad(d,'Give the new party a name.');
if(th)r.thread=th;if(w)r.party_what=w;q=r}
else{var o={verb:'new-project',zone:z2,name:nm};if(pt)o.party=pt;if(th)o.thread=th;q=o}
if(busy(d,q.zone))return;
d.close();if(act)send(q,'Making '+q.name+'…');else copy('new project '+q.name+(np?' for new party '+q.new_party+(w?' (what '+w+')':''):pt?' for '+pt:'')+' in '+q.zone+(th?', first thread '+th:''),'Copied the phrase. Paste it to your assistant.')}}
function rename(mg){var old=mg[2]||mg[1],kind=mg[2]?'thread':'project';
var d=dialog('Rename '+old,field('mg-name','New name, one you can say',old)+'<p class="mg-msg">Its folder, its note and every link to it in '+esc(mg[0])+' follow, in one commit. The old name stays a heard name for it.</p>',
CANCEL+'<button class="act primary" type="button" data-go>'+(act?'Rename':'Copy the phrase')+'</button>');var i=d.querySelector('#mg-name');i.focus();i.select();
d.querySelector('[data-go]').onclick=function(){var to=val(d,'mg-name');if(!to||to===old)return bad(d,'Give it a new name.');
var q={verb:'rename',zone:mg[0],project:mg[1],to:to};if(mg[2])q.thread=mg[2];if(busy(d,q.zone))return;d.close();
if(act)send(q,'Renaming '+old+'…');else copy('rename '+old+' to '+to,'Copied “rename '+old+' to '+to+'”. Paste it to your assistant.')}}
/* Move…: a thread to another project of its zone, from the zone's live list of projects (#354) */
function move(mg){var name=mg[2],l=((D.zones[mg[0]]||{}).projects||[]).filter(function(p){return p!==mg[1]});
if(!l.length){say('There is no other project in '+mg[0]+' to move it to.');return}
var d=dialog('Move '+name,select('mg-project','To project',l,'')+'<p class="mg-msg">Its folder, its note and every link to it in '+esc(mg[0])+' follow, in one commit. It stays in '+esc(mg[0])+'; a project walled from it is refused.</p>',
CANCEL+'<button class="act primary" type="button" data-go>'+(act?'Move':'Copy the phrase')+'</button>');
d.querySelector('[data-go]').onclick=function(){var to=val(d,'mg-project');if(!to)return bad(d,'Pick a project.');
var q={verb:'move',zone:mg[0],project:mg[1],thread:name,to:to};if(busy(d,q.zone))return;d.close();
if(act)send(q,'Moving '+name+'…');else copy('move '+name+' to '+to,'Copied “move '+name+' to '+to+'”. Paste it to your assistant.')}}
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
var v=b.dataset.manage;if(v==='new-project')newProject();else if(v==='new-thread')newThread(mg);else if(v==='rename'&&mg)rename(mg);else if(v==='move'&&mg&&mg[2])move(mg);else if(v==='delete'&&mg)del(mg)},true);
/* the dialogs' project lists follow a rename or a new project at once, as the rows do (#353) */
function listed(q){var z=D.zones&&D.zones[q.zone];if(!z)return;var l=z.projects||(z.projects=[]);
if(q.verb==='rename'&&!q.thread){var i=l.indexOf(q.project);if(i>=0&&q.to&&l.indexOf(q.to)<0)l[i]=q.to;l.sort(function(a,b){return a.toLowerCase()<b.toLowerCase()?-1:1})}
else if((q.verb==='new-project'||q.verb==='new-project-party')&&q.name&&l.indexOf(q.name)<0){l.push(q.name);l.sort(function(a,b){return a.toLowerCase()<b.toLowerCase()?-1:1})}}
/* Undo, for a minute after a deletion or a rename from the page: the app rebuilds the page after
   every request, so the commit to revert is kept in this browser until then */
var prev=window.GarrickActed;window.GarrickActed=function(q,out){
if(q&&out&&out.ok)listed(q);
if(q&&out&&out.ok&&(q.verb==='delete'&&q.confirm||q.verb==='rename'||q.verb==='move')){var m=out.commit?[0,out.commit]:/commit ([0-9a-f]{7,40})/.exec(out.say||'');   /* the reply's commit (#184), or the one it names */
try{localStorage.setItem('garrick-undo',JSON.stringify({zone:q.zone,commit:m?m[1]:'',what:q.verb==='delete'?'Deleted '+q.confirm:q.verb==='move'?'Moved '+q.thread+' to '+q.to:'Renamed '+(q.thread||q.project)+' to '+q.to,until:Date.now()+60000}))}catch(e){}}
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
.tfind kbd{position:absolute;right:8px;top:50%;transform:translateY(-50%);font:inherit;font-size:12px;line-height:16px;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 5px;pointer-events:none}
.tfind input:focus~kbd,.tfind input:not(:placeholder-shown)~kbd{display:none}
@media (hover:none){.tfind kbd{display:none}}
.tview.finding .zones,.tview.finding .tmodes,.tview.finding .efoot,.tview.finding .gsum{display:none!important}
.tfound-n{margin:0 0 6px}
.sres{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px;padding:6px 4px;border-top:1px solid var(--grid);border-radius:6px;font-size:13px;transition:background .1s}
.sres:hover,.sres.on{background:var(--wash)}.sres .t{min-width:0}
.sres .t a{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sres .t small{display:block;color:var(--muted);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
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
/* a rename from the page (#184): found by its new name at once, and again on a reload before the rebuild */
function renamed(q){if(!q||q.verb!=='rename'||!q.to)return;(D.items||[]).forEach(function(it){if(it.z!==q.zone)return;
if(q.thread?(it.k==='t'&&it.p===q.project&&it.n===q.thread):(it.k==='p'&&it.n===q.project)){it.n=q.to;delete it.sp}
if(!q.thread&&it.p===q.project){it.p=q.to;delete it.psp}
if(it.c){if(it.c.n===(q.thread||q.project))it.c.n=q.to;if(!q.thread&&it.c.p===q.project)it.c.p=q.to}
it._own=words([it.n,it.sp].join(' '));it._all=it._own.concat(words([it.k==='p'?'':it.p,it.psp,it.z].join(' ')))})}
if(window.GarrickRedo)renamed(window.GarrickRedo);
/* drawn again once Park or Wake has moved a row, so a match says what it now is */
var prev=window.GarrickActed;window.GarrickActed=function(q,out){if(out&&out.ok)renamed(q);var r=prev?prev(q,out):undefined;if(box.value)render();return r};
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
# request with no reply after ACTION_LOST seconds, past the longest page_action.py
# takes (a test pins the sum), is taken as lost. ZONE_VERBS are the requests page_action.py
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
# host sets window.GarrickReads as the page loads. An older app, which
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
ACTION_KEEP = ("rename", "move", "delete", "new-project", "new-project-party", "new-thread", "undo")
ZONE_VERBS = ("todo-done", "todo-undo", "todo-date", "todo-add", "park", "wake", "new-project", "new-project-party", "new-thread", "rename", "move",
              "delete", "undo", "answer", "later", "continue", "fix", "suggestion", "start", "stop-using",
              "bring-back", "files")

WORK_CSS = r"""
#work{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:10;display:flex;flex-direction:column;gap:6px;width:max-content;max-width:90vw}
#work[hidden]{display:none}#work .wk{display:flex;gap:10px;align-items:flex-start;background:var(--ink);color:var(--surface);font-size:13px;padding:9px 14px;border-radius:10px}
#work .wbody{display:flex;flex-direction:column;gap:2px;min-width:0}#work small,#work .wt{color:color-mix(in srgb,var(--surface) 72%,transparent);font-size:12px}
#work .wt{font-weight:inherit;font-variant-numeric:tabular-nums;margin-left:4px}#work .bad{box-shadow:inset 3px 0 0 var(--critical)}
#work .ask{box-shadow:inset 3px 0 0 var(--accent)}#work .wagain{align-self:flex-start;margin-top:4px;background:none;border:1px solid currentColor;border-radius:6px;color:inherit;font:inherit;font-size:12px;padding:2px 8px;cursor:pointer}
#work .wspin{flex:none;width:11px;height:11px;margin-top:3px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:wspin .8s linear infinite}
@keyframes wspin{to{transform:rotate(360deg)}}@media (prefers-reduced-motion:reduce){#work .wspin{animation:none;border-right-color:currentColor;opacity:.6}}
#work .wx{flex:none;background:none;border:0;color:inherit;font:inherit;font-size:16px;line-height:1;padding:0 2px;cursor:pointer;opacity:.7}#work .wx:hover{opacity:1}
#work .wdet{margin-top:4px;font-size:12px}#work .wdet summary{cursor:pointer;color:color-mix(in srgb,var(--surface) 72%,transparent)}#work .wdet p{margin:4px 0 0;overflow-wrap:anywhere}
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
BATCH=@BATCH@,SENTFOR=180,Q=[],HOV=null,TICKS=['todo-done','todo-undo'],KEEP=@KEEP@;
try{W=JSON.parse(sessionStorage.getItem(KEY)||'[]')||[]}catch(e){}
try{SEEN=JSON.parse(sessionStorage.getItem(KEY+'-seen')||'[]')||[]}catch(e){}
try{OPS=JSON.parse(sessionStorage.getItem(KEY+'-ops')||'{}')||{}}catch(e){}
try{Q=JSON.parse(sessionStorage.getItem(KEY+'-ticks')||'[]')||[]}catch(e){}
function keep(){try{sessionStorage.setItem(KEY,JSON.stringify(W));sessionStorage.setItem(KEY+'-seen',JSON.stringify(SEEN.slice(-60)));sessionStorage.setItem(KEY+'-ops',JSON.stringify(OPS));
sessionStorage.setItem(KEY+'-ticks',JSON.stringify(Q))}catch(e){}}
/* the ticks this window has sent, by zone, note and key, with their verb and time, read from the storage each time it is asked:
   a second copy of the page, or a rebuild that read the queue before a flush was stored, may hold a tick this one has sent (#524) */
function sentRead(){var s={},n=Date.now();try{s=JSON.parse(sessionStorage.getItem(KEY+'-sent')||'{}')||{}}catch(e){}
Object.keys(s).forEach(function(i){if(!s[i]||n-s[i].t>SENTFOR*1000)delete s[i]});return s}
function sentWrite(s){try{sessionStorage.setItem(KEY+'-sent',JSON.stringify(s))}catch(e){}}
function sentId(q,k){return JSON.stringify([q.zone,q.file,k])}
function sentHas(q,k){var s=sentRead()[sentId(q,k)];return!!s&&s.v===q.verb}
/* the oldest of what was sent goes first once there are too many */
function sentAdd(q,keys){var s=sentRead(),n=Date.now();keys.forEach(function(k){s[sentId(q,k)]={v:q.verb,t:n}});sentWrite(s)}
function sentDrop(q,keys){var s=sentRead();keys.forEach(function(k){delete s[sentId(q,k)]});sentWrite(s)}
/* when a batch saved: a build may have read the note between its send and its save, so the later of the two is what a page is compared with (#538) */
function sentDone(v,z,f,keys,t){var s=sentRead();keys.forEach(function(k){var x=s[sentId({zone:z,file:f},k)];if(x&&x.v===v)x.d=t});sentWrite(s)}
/* a line this window ticked or reopened keeps its state across a rebuild until a page built after it arrives: every entry sent or saved
   later than the page's data-built is drawn as sent. A page with no readable build time is left as the note has it (#538) */
function sentPaint(){var b=Date.parse(document.body&&document.body.getAttribute('data-built')||'');if(isNaN(b))return;var s=sentRead();
Object.keys(s).forEach(function(i){var x=s[i],a=null;if(!x||TICKS.indexOf(x.v)<0||Math.max(x.t||0,x.d||0)<=b)return;
try{a=JSON.parse(i)}catch(e){return}if(a&&typeof a[0]==='string'&&typeof a[2]==='string')paint(a[0],a[2],x.v==='todo-done')})}
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
if(b){b.title=d?'Reopen':'Mark done';b.setAttribute('aria-label',b.title+String(b.getAttribute('aria-label')||'').replace(/^[^:]*/,''))}})}
function words(z,k){var r=rows(z,k)[0],b=r&&r.querySelector('.tick'),s=b?String(b.getAttribute('aria-label')||'').replace(/^[^:]*:\s*/,''):'';
return s.length>60?s.slice(0,59)+'…':s}
/* a batch refused as a whole: its boxes back as they were, and a click on one of them meanwhile dropped, since the row is back too */
function back(e){var z=e.q.zone,d=e.q.verb!=='todo-done';(e.q.keys||[]).forEach(function(k){paint(z,k,d)});sentDrop(e.q,e.q.keys||[]);
Q=Q.filter(function(x){return!(x.q.zone===z&&(e.q.keys||[]).indexOf(x.q.key)>=0)})}
/* A failure in plain words, with one next step the page already has (#511): the tool's own text is under Details, closed.
   The rules' sentence for a wall is said as it stands, since it is already plain and says nothing more. */
function plain(e){var o=e.out,k=o.outcome||'',t=o.say||'';
if(/^A wall holds /.test(t))return{say:t,next:'',raw:'',act:''};
if(e.q.verb==='continue')return{say:'Claude did not open.',next:'Try again',raw:t,act:'retry'};
if(k==='lost')return{say:'This page did not hear back, so we cannot tell whether this went through.',next:'Refresh',raw:t,act:'refresh'};
if(k==='unknown')return{say:'We cannot tell whether this went through.',next:'Refresh',raw:t,act:'refresh'};
if(k==='refused')return{say:'This was not saved: the check refused it.',next:'Show why',raw:t,act:'why'};
return{say:'This was not saved: the action stopped before it finished.',next:'Try again',raw:t,act:'retry'}}
function shown(e,now){return!!e.out||!e.q.keys||!!e.shown||now-e.t0>=TOAST*1000}
function render(){var now=Date.now(),html='';if(box){html=W.map(function(e,i){if(!shown(e,now))return'';
if(e.out&&!e.out.ok&&!e.out.again){var f=plain(e);
return'<div class="wk bad" data-i="'+i+'"><div class="wbody"><small>'+esc(e.say.replace(/…$/,''))+', '+took(e.done-e.t0)+'</small><span>'+esc(f.say)+'</span>'
+(f.next?'<button type="button" class="wagain" data-next="'+i+'">'+esc(f.next)+'</button>':'')
+(f.raw?'<details class="wdet" data-d="'+i+'"'+(e.open?' open':'')+'><summary>Details</summary><p>'+esc(f.raw)+'</p>'+(e.lines&&e.lines.length?'<p>'+esc(e.lines.filter(String).join(' · '))+'</p>':'')+'</details>':(e.lines&&e.lines.length?'<small>'+esc(e.lines.filter(String).join(' · '))+'</small>':''))
+'</div><button type="button" class="wx" data-wx="'+i+'" aria-label="Dismiss" title="Dismiss">×</button></div>'}
if(e.out)return'<div class="wk '+(e.out.ok?'ok':'ask')+'" data-i="'+i+'"><div class="wbody"><small>'+esc(e.say.replace(/…$/,''))+', '+took(e.done-e.t0)+'</small><span>'+esc(e.out.say)
+'</span>'+(e.out.again?'<button type="button" class="wagain" data-again="'+i+'">Do it again</button>':'')+'</div><button type="button" class="wx" data-wx="'+i+'" aria-label="Dismiss" title="Dismiss">×</button></div>';
return'<div class="wk"><span class="wspin" aria-hidden="true"></span><div class="wbody"><span>'+esc(e.say)+'<span class="wt" data-t0="'+e.t0+'" aria-hidden="true">'+took(now-e.t0)+'</span></span>'
+((e.phase===undefined?now-e.t0>=WHY*1000&&['continue','start'].indexOf(e.q.verb)<0:e.phase==='checking')?'<small>Committing: the wall check can take a minute.</small>':'')+'</div></div>'}).join('');
box.innerHTML=html;box.hidden=!html;document.body.style.setProperty('--work-h',html?box.offsetHeight+8+'px':'0px')}hold()}
/* each second: the time so far, why after WHY, a request with no reply after LOST given up, a batch's own toast once it has taken TOAST,
   and a card that says saved gone TOAST after it came, unless the pointer is on it */
function sweep(){var now=Date.now(),changed=false;W.slice().forEach(function(e){
if(e.out){if(e.fade&&now>=e.fade&&HOV!==e){W.splice(W.indexOf(e),1);changed=true}return}
if(now-e.t0>LOST*1000){e.out={ok:false,outcome:'lost',say:'No reply after '+took(LOST*1000)+'. Look at git status in '+e.q.zone+' before trying again.'};e.done=now;changed=true}
else if(!e.why&&now-e.t0>=WHY*1000){e.why=1;changed=true}
if(e.q.keys&&!e.shown&&now-e.t0>=TOAST*1000){e.shown=1;changed=true}});if(changed)keep();return changed}
/* the ticks queued in a zone go as one request once the zone is free and BATCH seconds have passed since the last of them:
   the ones for the same verb and note as the oldest, the rest after it, with whatever was ticked meanwhile */
function flush(){var now=Date.now(),sent=false;
Q.map(function(x){return x.q.zone}).filter(function(z,i,a){return a.indexOf(z)===i}).forEach(function(z){var mine=Q.filter(function(x){return x.q.zone===z});
if(running(z)||mine.some(function(x){return now-x.t<BATCH*1000}))return;
var one=mine[0].q,go=mine.filter(function(x){return x.q.verb===one.verb&&x.q.file===one.file}),all=go;
go=go.filter(function(x){return!sentHas(x.q,x.q.key)});     /* a tick this window has already sent is never sent twice */
Q=Q.filter(function(x){return all.indexOf(x)<0});if(!go.length){sent=true;return}
var keys=go.map(function(x){return x.q.key}),n=keys.length;sentAdd(one,keys);var q={verb:one.verb,zone:z,file:one.file,keys:keys,op:mint()};host.postMessage({act:q});
W.push({q:q,op:q.op,say:(q.verb==='todo-done'?'Ticking ':'Reopening ')+(n===1?'it…':n+' lines…'),t0:now,lines:keys.map(function(k){return words(z,k)})});sent=true});
if(sent)keep();return sent}
function tick(){var sent=flush();if(sweep()||sent)render();else if(box)[].forEach.call(box.querySelectorAll('.wt'),function(t){t.textContent=took(Date.now()-t.dataset.t0)});poll();run()}
/* the record: ask for the open set on load, and every POLL seconds while an entry of ours is running; only Python reads the file.
   Never asked of a host that has not said it can answer a request that reads: an older one would toast and rebuild the page for each */
function poll(first){var now=Date.now();if(!window.GarrickReads||OPS.durable===false)return;
if(!first&&(now-(OPS.asked||0)<POLL*1000-200||!W.some(function(e){return!e.out})))return;
OPS.asked=now;keep();host.postMessage({act:{verb:'operations'}})}
function heard(out){if(!out||!out.ok||out.durable===false){OPS.durable=false;if(!OPS.said){OPS.said=1;toast('Actions are not recoverable here: if this page reloads while one is running, look at git status in its zone.')}keep();run();return}
OPS.durable=true;OPS.verbs=out.verbs||[];OPS.lost=out.lost||'';reconcile(out.ops||[]);keep();render();run()}
function reconcile(ops){var now=Date.now(),by={};ops.forEach(function(r){by[r.op]=r});
ops.forEach(function(r){var e=W.filter(function(x){return x.op===r.op})[0],end=r.state==='completed'||r.state==='failed',keys=TICKS.indexOf(r.verb)>=0&&r.keys&&r.keys.length?r.keys:null;
if(!e){if(SEEN.indexOf(r.op)>=0||ZONED.indexOf(r.verb)<0)return;
e={q:{verb:r.verb,zone:r.zone,op:r.op},op:r.op,say:r.label||'Working…',t0:Math.round(r.at*1000)};W.push(e);
if(keys){e.q.keys=keys;e.lines=keys.map(function(k){return words(r.zone,k)});if(!end)keys.forEach(function(k){paint(r.zone,k,r.verb==='todo-done')})}}
/* a batch that saved while the page was away: the same small notice as one heard here, and no card */
if(end&&keys&&r.outcome==='saved'){sentDone(r.verb,r.zone,e.q.file||r.file,keys,Math.round((r.done||r.at)*1000));if(!e.out){W.splice(W.indexOf(e),1);toast(r.say||'Saved')}mark(r.op);return}
if(end){if(!e.out){e.out={ok:r.outcome==='saved',outcome:r.outcome||'',say:r.say||''};e.done=Math.round((r.done||r.at)*1000);if(e.out.ok)e.fade=now+TOAST*1000;else if(e.q.keys)back(e)}mark(r.op)}
else if(!e.out)e.phase=r.phase||''});
W.forEach(function(e){if(e.out||!e.op||by[e.op]||(OPS.verbs||[]).indexOf(e.q.verb)<0||now-e.t0<=UNKNOWN*1000)return;
e.out={ok:false,outcome:'lost',say:(OPS.lost||'No record of this action was found. Look at git status in {zone} before trying again.').replace('{zone}',e.q.zone)};e.done=now;mark(e.op)})}
function run(){var on=W.some(function(e){return!e.out||e.fade})||Q.length>0;if(on&&!timer)timer=setInterval(tick,1000);if(!on&&timer){clearInterval(timer);timer=null}}
window.GarrickBusy=function(z){var e=running(z);return e?e.say:''};
window.GarrickHeld=function(q){var e=zoned(q)&&running(q.zone);if(e)toast(q.zone+' is still busy: '+e.say);return!!e};
window.GarrickAct=function(q,said,lines){if(!zoned(q))return false;if(GarrickHeld(q))return true;q=Object.assign({},q,{op:q.op||mint()});host.postMessage({act:q});
W.push({q:q,op:q.op,say:said||'Working…',t0:Date.now(),lines:lines||undefined});keep();render();run();return true};
/* a tick or an untick (#107): queued, never refused for a busy zone, and sent with the ones made within BATCH seconds of it.
   A second click on a line still queued takes the first back, and nothing is sent for it */
window.GarrickTick=function(q){if(!q||TICKS.indexOf(q.verb)<0||typeof q.zone!=='string'||typeof q.key!=='string')return false;
var was=Q.filter(function(x){return x.q.zone===q.zone&&x.q.file===q.file&&x.q.key===q.key})[0];
if(!was&&sentHas(q,q.key)){keep();return true}   /* already sent, for this verb: the line is as asked */
if(was){if(was.q.verb!==q.verb)Q.splice(Q.indexOf(was),1)}else Q.push({q:{verb:q.verb,zone:q.zone,file:q.file,key:q.key},t:Date.now()});
keep();run();return true};
/* the reply, from the host: a quick one is the host's toast, as before; a slow one stays here, and the toast steps aside.
   A batch of ticks that saved is one small notice however long it took; one refused stays, naming its lines, with their boxes back.
   A refused rename, deletion, new project, new thread or undo stays too, however quick (KEEP, #177) */
var prev=window.GarrickActed;window.GarrickActed=function(q,out){if(q&&q.verb==='operations'){heard(out);return}
var e=zoned(q)&&(W.filter(function(x){return!x.out&&q.op&&x.op===q.op})[0]||(/^ask-/.test(q.op||'')?null:running(q.zone)));
if(e&&e.q.verb===q.verb){var now=Date.now();
if(out&&out.state==='running'&&!out.outcome){   /* an identical request is already under way: this entry becomes that one, and nothing was saved */
W.splice(W.indexOf(e),1);if(out.op&&!W.some(function(x){return x.op===out.op})&&SEEN.indexOf(out.op)<0){var j={q:{verb:q.verb,zone:q.zone,op:out.op},op:out.op,say:out.say||'Working…',t0:now};
if(e.q.keys){j.q.keys=e.q.keys;j.lines=e.lines}W.push(j)}
keep();render();run();return}
/* a success is the record's outcome "saved"; with no record, the reply's ok, as before. A request the record holds already
   comes back asking whether it is meant again (`again`), and stays, however quick, with the button that confirms it */
/* Saved means saved (#511): a reply with no outcome for an action the record keeps is not worded as saved. The record is asked
   for, and says it; until then the action stays running. The other wrappers get the reply as they always did, so
   a row's follow-ups (the list, the undo record) are made as for a plain ok reply */
if(out&&out.ok&&!out.outcome&&!out.again&&(OPS.verbs||[]).indexOf(q.verb)>=0){poll(true);keep();render();run();if(prev)return prev(q,out);return}
mark(e.op,out&&out.op);var ok=out&&out.outcome?out.outcome==='saved':!!(out&&out.ok),again=out&&out.again||'';
if(e.q.keys&&ok&&!again){sentDone(e.q.verb,e.q.zone,e.q.file,e.q.keys,now);W.splice(W.indexOf(e),1);toast(out.say||'Saved')}
else if(now-e.t0>TOAST*1000||again||e.q.keys||!ok){e.out={ok:ok,outcome:out&&out.outcome||'',say:out&&out.say||'That did not work.',again:again};e.done=now;
if(ok&&!again)e.fade=now+TOAST*1000;else if(e.q.keys&&!again)back(e);var t=document.getElementById('toast');if(t)t.style.opacity=0}else W.splice(W.indexOf(e),1);keep();render();run()}
if(prev)return prev(q,out)};
/* Do it again: the same request, once more, with `confirm` naming the action it was asked about (operations.py) */
if(box)box.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('[data-again]');
if(a&&a.dataset.again!==undefined){var w=W[+a.dataset.again];if(w&&w.out&&w.out.again){W.splice(W.indexOf(w),1);keep();render();
GarrickAct(Object.assign({},w.q,{op:'',confirm:w.out.again}),w.say,w.lines)}return}
var n=e.target.closest&&e.target.closest('[data-next]');
if(n&&n.dataset.next!==undefined){var u=W[+n.dataset.next];if(!u||!u.out)return;var a=plain(u).act;
if(a==='why'){u.open=true;keep();render()}
else if(a==='refresh'){W.splice(W.indexOf(u),1);keep();render();host.postMessage({rebuild:true});toast('Refreshing the page…')}
else if(a==='retry'){W.splice(W.indexOf(u),1);keep();render();GarrickAct(Object.assign({},u.q,{op:''}),u.say,u.lines)}return}
var x=e.target.closest&&e.target.closest('[data-wx]');if(!x)return;W.splice(+x.dataset.wx,1);keep();render()});
if(box)box.addEventListener('toggle',function(e){var d=e.target;if(d&&d.dataset&&d.dataset.d!==undefined&&W[+d.dataset.d])W[+d.dataset.d].open=d.open},true);
/* the pointer on a card that says saved holds it; off it, the card has TOAST seconds more */
if(box){box.addEventListener('mouseover',function(e){var c=e.target.closest&&e.target.closest('[data-i]');HOV=c?W[+c.dataset.i]||null:null});
box.addEventListener('mouseout',function(e){var to=e.relatedTarget,c=to&&to.closest&&to.closest('[data-i]');if(c&&HOV&&W[+c.dataset.i]===HOV)return;
if(HOV&&HOV.fade)HOV.fade=Date.now()+TOAST*1000;HOV=null})}
/* a rebuilt page draws each line as the note has it: a tick sent since the page was built, then one still queued, or on its way, is drawn as clicked */
sentPaint();
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
.todotab .tbar .seg .n{font-size:12px;color:var(--muted)}
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
.trow.done .tick::after{content:"";width:9px;height:5px;border-left:2px solid var(--accent-ink);border-bottom:2px solid var(--accent-ink);transform:translateY(-1px) rotate(-45deg)}
.trow.done .ttext{text-decoration:line-through;color:var(--muted)}.trow.done .thr{color:var(--muted)}
.ttext{font-size:13.5px;line-height:1.45;overflow-wrap:anywhere}
.ttext code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--wash);padding:0 3px;border-radius:4px}
.thr{display:inline-block;font-size:12px;font-weight:620;color:var(--accent);margin-right:7px;white-space:nowrap}.thr.unsure{color:var(--muted);font-weight:500}
.tmeta{display:flex;flex-wrap:wrap;gap:3px 12px;margin-top:3px;font-size:12px;color:var(--muted)}
.tmeta .prio{color:var(--critical)}.tmeta .moved{color:var(--accent);font-weight:560}
.tdate{border:1px solid var(--line);background:var(--raise);border-radius:7px;font:inherit;font-size:12px;padding:3px 9px;color:var(--ink2);white-space:nowrap;font-variant-numeric:tabular-nums}
button.tdate{cursor:pointer}button.tdate:hover{border-color:var(--base);color:var(--ink)}
.tdate.none{color:var(--muted);border-style:dashed;background:none}.tdate:empty{visibility:hidden}
.ro .tdate.none:not(:empty){border-style:solid}.nohost button.tdate{pointer-events:none}.nohost button.tdate.none{visibility:hidden}
.tdate.late{color:var(--critical);border-color:color-mix(in srgb,var(--critical) 45%,transparent)}
.tdate.today{color:var(--accent);border-color:color-mix(in srgb,var(--accent) 45%,transparent)}
.trow.done .tdate{visibility:hidden}
.tempty{color:var(--muted);font-size:12.5px;margin:2px 8px 10px}
.todotab[data-tf="late"] .trow:not(.late),.todotab[data-tf="nodate"] .trow:not(.undated){display:none}
.todotab[data-tf="late"] .tempty,.todotab[data-tf="nodate"] .tempty,.tgroup.empty{display:none}
.dmenu{position:fixed;z-index:11;background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:0 6px 24px rgba(0,0,0,.16);padding:6px;width:236px}
.dmenu .dh{font-size:12px;color:var(--muted);padding:4px 8px 2px;text-transform:uppercase;letter-spacing:.05em}
.dmenu button{display:flex;justify-content:space-between;align-items:baseline;width:100%;border:0;background:none;font:inherit;font-size:13px;color:var(--ink2);padding:6px 8px;border-radius:6px;cursor:pointer;text-align:left}
.dmenu button:hover,.dmenu button:focus-visible{background:var(--wash);color:var(--ink);outline:none}
.dmenu button small{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
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
/* a zone's "Open" on the Overview opens the tab on that zone */
document.addEventListener('click',function(e){var g=e.target.closest&&e.target.closest('[data-tz-go]');if(g)zone(g.dataset.tzGo)},true);
/* what a button sends: Garrick's request, page_action.py's to carry out */
function send(verb,r,more,said){var q={verb:verb,zone:r.dataset.z,file:r.dataset.f,key:r.dataset.k};for(var k in more||{})q[k]=more[k];
if(window.GarrickAct&&GarrickAct(q,said))return;host.postMessage({act:q});say(said)}
/* a zone still busy with another request (WORK_JS) says so, and the row stays as it is */
function held(verb,r){return!!(window.GarrickHeld&&GarrickHeld({verb:verb,zone:r.dataset.z}))}
/* where a line is drawn: the Todo tab, and the list a thread's todo chip opens on the Threads card (#179) and on a Your work row (#523), which tick and date the same way */
var places=[todo].concat([].slice.call(document.querySelectorAll('.tview,.yrows')));
function twins(r){return[].filter.call(document.querySelectorAll('.trow'),function(x){return x===r||x.dataset.z===r.dataset.z&&x.dataset.f===r.dataset.f&&x.dataset.k===r.dataset.k})}
/* a tick is queued with the ticks around it (WORK_JS's GarrickTick, #107), even while the zone is busy; without it, sent at once as before.
   Every place the line is drawn is struck through with it */
function onTick(e){var b=e.target.closest('.tick');if(!b||!host)return;var r=b.closest('.trow');if(r.classList.contains('pending'))return;
var d=!r.classList.contains('done'),verb=d?'todo-done':'todo-undo';
if(!(window.GarrickTick&&GarrickTick({verb:verb,zone:r.dataset.z,file:r.dataset.f,key:r.dataset.k}))){if(held(verb,r))return;send(verb,r,null,d?'Ticking it…':'Reopening it…')}
twins(r).forEach(function(x){var t=x.querySelector('.tick');x.classList.toggle('done',d);if(t){t.title=d?'Reopen':'Mark done';t.setAttribute('aria-label',t.title+t.getAttribute('aria-label').replace(/^[^:]*/,''))}})}
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
if(n<0||(w&&n===0)){b.classList.add('late');r.classList.add('late')}else if(n===0)b.classList.add('today');
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
else if(want==='named')now=(S.notes||[]).indexOf(key)>=0?'named':'none';     /* a rename (#184): the page has the new note */
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
var ask=document.getElementById('menu-askkey'),NOTE={hotkey:'Opens the menu or the panel from any app',askhotkey:'Opens the Ask box from any app',
dictationkey:'Click, then press the shortcut your dictation tool starts on. Pause the tool first if it takes the keys'};
var dict=document.getElementById('menu-dictation'),dkey=document.getElementById('menu-dictkey'),FIELD={hotkey:'menu-hotkey',askhotkey:'menu-askkey',dictationkey:'menu-dictkey'};
/* what the box does once it opens, said under the choice */
var DICT={off:'Once the Ask box opens, start dictation in it too',macos:'Starts macOS Dictation in the box, with no permission needed',
key:'Pressed for your dictation tool once the box has the cursor. Needs the Accessibility permission. A tool that listens only while its key is held cannot be started this way'};
var FIND={on:'On. Right-click a project or thread folder in Finder, and choose Garrick.',
off:'Off. Switch on Garrick under Extensions, Finder, in System Settings. After the app is rebuilt, macOS may need it switched on again',
missing:'This build of the app has no Finder extension. Build the app again with make-app.sh'};
function note(which,s){var n=document.getElementById(FIELD[which]+'-note');if(n)n.textContent=s||NOTE[which]}
function fill(){var a=window.GarrickApp||{};show.checked=!!a.menubar;login.checked=!!a.login;login.disabled=a.login==null;
/* an app built before the panel says no style, and its row stays hidden; one built before the Ask hotkey, that row */
if(style){style.closest('.launcher-row').style.display='style' in a?'':'none';style.value=a.style||'icon';style.disabled=!a.menubar}
var onb=document.getElementById('menu-ask');if(onb){onb.closest('.launcher-row').style.display='ask' in a?'':'none';onb.checked=a.ask!==false}
if(ask){ask.closest('.launcher-row').style.display='askhotkey' in a?'':'none';ask.value=a.askhotkey||''}
var said=a.said||{};note('hotkey',said.hotkey);note('askhotkey',said.askhotkey||(a.askdefault?NOTE.askhotkey+'. ⌘G until you set another':''));
/* how the Ask box closes (#411): the last ticked box cannot be unticked, and says why */
var ce=document.getElementById('menu-askclose-esc'),cc=document.getElementById('menu-askclose-click');
if(ce&&cc){var cm=a.askclose||'escape',WHY='At least one way to close the Ask box stays on';ce.closest('.launcher-row').style.display='askclose' in a?'':'none';
ce.checked=cm!=='click';cc.checked=cm!=='escape';ce.disabled=cm==='escape';cc.disabled=cm==='click';ce.title=ce.disabled?WHY:'';cc.title=cc.disabled?WHY:''}
/* an app built before #35 says no dictation, and both its rows stay hidden */
if(dict){var m=a.dictation||'off',dn=document.getElementById('menu-dictation-note');dict.closest('.launcher-row').style.display='dictation' in a?'':'none';
dict.value=m;if(dn)dn.textContent=said.dictation||DICT[m]||DICT.key;
if(dkey){dkey.closest('.launcher-row').style.display='dictation' in a&&m==='key'?'':'none';dkey.value=a.dictationkey||'';note('dictationkey',said.dictationkey)}}
/* the Finder extension (#346): an app built before it says nothing, and its row stays hidden */
var fin=document.getElementById('menu-finder');
if(fin){var fs=a.finder,fn=document.getElementById('menu-finder-note');fin.closest('.launcher-row').style.display='finder' in a?'':'none';fin.hidden=fs==='missing';
if(fn)fn.textContent=FIND[fs]||FIND.off}
if(a.login==null)document.getElementById('menu-login-note').textContent='Needs macOS 13 or later';key.value=a.hotkey||''}
window.GarrickAppSet=function(a){window.GarrickApp=a;fill()};fill();
/* the app's settings: kept by the app, so a change here does not rebuild the page */
function tell(e,o){e.stopPropagation();host.postMessage({app:o})}
show.addEventListener('change',function(e){tell(e,{menubar:show.checked})});
if(style)style.addEventListener('change',function(e){tell(e,{style:style.value})});
var askb=document.getElementById('menu-ask');if(askb)askb.addEventListener('change',function(e){e.stopPropagation();host.postMessage({act:{verb:'settings',ask:askb.checked}})});
if(dict)dict.addEventListener('change',function(e){tell(e,{dictation:dict.value})});
function closeWith(e){var ce=document.getElementById('menu-askclose-esc'),cc=document.getElementById('menu-askclose-click');
if(!ce.checked&&!cc.checked){(e.target||ce).checked=true;return}tell(e,{askclose:ce.checked&&cc.checked?'both':ce.checked?'escape':'click'})}
['menu-askclose-esc','menu-askclose-click'].forEach(function(id){var c=document.getElementById(id);if(c)c.addEventListener('change',closeWith)});
var finb=document.getElementById('menu-finder');if(finb)finb.addEventListener('click',function(e){tell(e,{finder:'settings'})});
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


def check_file(out: Path) -> Path:
    """Where the check's last result for the page at `out` is kept: beside it, never committed."""
    return out.with_name(out.stem + ".check.json")


def effort_file(out: Path) -> Path:
    """Where the effort ledger keeps what it read of each transcript, for the
    page at `out`: beside it, never committed."""
    return out.with_name(out.stem + ".effort.json")


def kept_check(store: Path, ws: Path, now: dt.datetime) -> Optional[dict]:
    """The result a build kept in `store` for this workspace, of whatever age,
    marked `kept` and carrying `at`, when the check ran; None when there is
    none, or it cannot be read (#382)."""
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
        at, result = float(data["at"]), data["result"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if data.get("workspace") != str(ws) or not isinstance(result, dict) or result.get("failed"):
        return None
    if now.timestamp() < at:
        return None                           # from the future: not a result to trust
    return dict(result, at=at, kept=True)


def kept_said(C: Optional[dict], now: dt.datetime) -> str:
    """How old a kept check result is, in the Checks card's words, for every
    place that shows its counts (#298): "" when this build ran the check."""
    if not (C and C.get("kept")):
        return ""
    return "As the check found it %s" % age(dt.datetime.fromtimestamp(C["at"]), now)


def check(ws: Path, store: Optional[Path] = None, reuse: Optional[float] = None,
          now: Optional[dt.datetime] = None) -> Optional[dict]:
    """check.py's findings, run as the page is built. With `--quick`, where the
    workspace's check.py has it: every check but the comparison of wording
    with the meetings, which on a large workspace is most of a full run's
    time, and which the commit hook and a scheduled full check still make.

    With `store`, a result is kept there for the next build, and with `reuse`
    as well, the one kept there is shown, whatever its age, and the check is
    never run: what scaffold.py's and correct.py's rebuilds ask for (#260,
    #382), so a thread a session made reaches the page in seconds. The
    builds that run the check keep it fresh. With no result kept, such a
    build says there is none yet (`pending`) rather than claim a pass. A
    check that did not run is never kept."""
    tool = ws / "System" / "tools" / "check.py"
    if not tool.is_file():
        return None
    now = now or dt.datetime.now()
    if store is not None and reuse:
        kept = kept_check(store, ws, now)
        return kept if kept is not None else {"failed": True, "pending": True}
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
    if store is not None:
        try:
            write_page(store, json.dumps({"workspace": str(ws), "at": now.timestamp(), "result": data}, ensure_ascii=False) + "\n")
        except OSError:
            pass                              # the next build runs the check again
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
        # --no-optional-locks: the page only reads, so git status never takes
        # index.lock to refresh the index, and a commit a session makes in the
        # same moment never finds it held.
        def git(*args):
            try:
                proc = subprocess.run(["git", "--no-optional-locks", "-C", str(folder), *args], capture_output=True,
                                      text=True, timeout=30)
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
# A dated line with no link first, as the knowledge skill wrote its log before
# 0.51.0: its title is its text up to the first parenthesis or semicolon. And
# a dated `## ` heading, as a wiki whose schema.json says `"log": "section"`
# keeps it: its title is the rest of the heading, or the first line under it (#322).
LOG_DATED = re.compile(r"^\s*-\s+(\d{4}-\d\d-\d\d):\s+(.*)$")
LOG_SECTION = re.compile(r"^##\s+(\d{4}-\d\d-\d\d)\b[\s:·,—–-]*(.*)$")
LOG_NOT_READ = "log not read"


def log_entries(text: str) -> Tuple[List[Tuple[dt.date, int, str, str]], bool]:
    """(date, -line, title, page target or "") for every entry a wiki's log
    holds, in the three forms (#322); and whether it holds lines that look
    like entries, a list item or a `## ` section, so a log that reads as none
    of them says so rather than "nothing logged yet"."""
    lines = text.splitlines()
    entries, tried = [], False
    for n, line in enumerate(lines):
        m = LOG_ENTRY.match(line)
        if m:
            when = as_date(m.group(1))
            if when:
                target = m.group(2).strip()
                entries.append((when, -n, (m.group(3) or target.rsplit("/", 1)[-1]).strip(), target))
                continue
        m = LOG_DATED.match(line) or LOG_SECTION.match(line)
        if m and as_date(m.group(1)):
            rest = m.group(2).strip()
            if not rest and line.startswith("##"):          # the section's first line says what it holds
                rest = next((l.strip().lstrip("-* ").strip() for l in lines[n + 1:n + 6] if l.strip() and not l.startswith("#")), "")
                k = LOG_ENTRY.match("- %s: %s" % (m.group(1), rest))
                if k:
                    target = k.group(2).strip()
                    entries.append((as_date(m.group(1)), -n, (k.group(3) or target.rsplit("/", 1)[-1]).strip(), target))
                    continue
            title = plain_text(re.split(r"[(;]", rest, 1)[0]).strip(" .,:") or "an entry"
            entries.append((as_date(m.group(1)), -n, title, ""))
            continue
        tried = tried or line.lstrip().startswith(("- ", "* ")) or line.startswith("## ")
    return entries, tried


def wikis(ws: Path) -> List[dict]:
    """Per wiki: its log, how many entries it holds, and the newest entry's
    date and title. Nothing else from the line: not its zone, not its parties.
    An entry with a link opens its page; a log whose entries it cannot read
    at all says so (`unread`)."""
    out = []
    for w in visible_dirs(ws / "Wikis"):
        log = w / "wiki" / "log.md"
        if not log.is_file():
            continue
        entries, tried = log_entries(log.read_text(encoding="utf-8", errors="replace"))
        row = {"name": w.name, "log": log, "count": len(entries), "when": None, "title": "", "page": None,
               "unread": tried and not entries}
        if entries:
            when, _, title, target = max(entries)   # the newest; on a tie, the line nearer the top
            page = None
            if target:
                page = (w / (target if target.endswith(".md") else target + ".md")).resolve()
                if not (str(page).startswith(str(w.resolve()) + os.sep) and page.is_file()):
                    page = None
            row.update(when=when, title=title[:100] + ("…" if len(title) > 100 else ""), page=page)
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
def git_ignored(root: Path) -> set:
    """The folders (paths relative to the zone `root`) that the zone's own git
    ignores, from one `git ls-files` over the zone (#399), asked for before the
    walk so that an ignored folder is never entered. A path git cannot encode
    as text (a name that is not valid UTF-8) is read back as the walk reads it,
    with surrogateescape. A zone that is not a repository of its own, or a Mac
    with no git, ignores nothing."""
    if not (root / ".git").exists():
        return set()
    try:
        done = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return set()
    if done.returncode != 0:
        return set()
    return {os.fsdecode(x).rstrip("/") for x in done.stdout.split(b"\0") if x.endswith(b"/")}


# What a note is, in the order the legend shows them. Colours are fixed so a
# kind looks the same in every workspace; none is amber or red, which the
# rings use for threads gone quiet. Threads take the brand blue, the light
# theme's accent, which also draws the lines of a selected note. A mail page
# (`type: email` in the Meetings wiki) has its own kind beside meetings.
KINDS = [("project", "project", "#e07b39"), ("thread", "thread", "#3d73e0"),
         ("note", "other notes", "#9aa0a6"), ("meeting", "meeting", "#7a5af8"), ("mail", "mail", "#c94f9c"),
         ("person", "person", "#13a38a"), ("source", "source", "#7c9a2d"), ("concept", "concept", "#8c6d1f"),
         ("entity", "entity", "#4b6584"), ("decision", "decision", "#0b7f97")]

# Each place's kinds come from Garrick's own model of it first: a page whose
# type names a kind of the model's wikis takes it in any wiki, so a Meetings
# page of `type: entity` is an entity. A type the model does not know, shared
# by at least KIND_FROM_PAGES pages of one wiki, is a kind of its own, named
# from the type (`domain`, Domains), coloured from PAGE_COLOURS (#250). Any
# other page is drawn as other notes. A place's hubs are what its core view
# joins: a zone's projects and threads, the people and entities in Meetings
# (#320), the concepts and entities in any other wiki. A place opens on its
# hubs, but Meetings on its people (OPENS): entities are in the legend there,
# off until turned on.
WIKI_KINDS = ("meeting", "mail", "person", "source", "concept", "entity", "decision")
HUBS = {"": ("project", "thread"), "Meetings": ("person", "entity"), "*": ("concept", "entity")}
OPENS = {"Meetings": ("person",)}
KIND_FROM_PAGES = 3
# Colours for the kinds found from pages, after KINDS's: none near a shipped
# kind's, amber, red or another of these, and each at least 2.9 to 1 against
# the card in both themes. A type keeps the colour its name hashes to, or the
# next one free, so a kind does not change colour when another one comes.
PAGE_COLOURS = ("#0099b8", "#a83fbf", "#2f9e44", "#a14a6b", "#6b8fcf", "#9b5d3a")
# How the legend names each kind: plural, as a filter reads (#250).
KIND_SAID = {"project": "Projects", "thread": "Threads", "note": "Other notes", "meeting": "Meetings", "mail": "Mail",
             "person": "People", "source": "Sources", "concept": "Concepts", "entity": "Entities", "decision": "Decisions"}
WIKI_LABEL = 40          # characters of a wiki page's title drawn on the graph; the card has it whole


# The longest name a kind found from pages takes: page_action.py's GRAPH_FOUND
# holds a kind Settings › Graph colours saves to the same shape (#291).
FOUND_KIND_MAX = 60


def found_kind(typed: str) -> str:
    """A page's `type:`, lower case, as the kind it would found (#250): its
    letters, digits, spaces, hyphens and underscores, with no space, hyphen or
    underscore at either end, cut to FOUND_KIND_MAX. Every name this gives is
    one Settings › Graph colours can save (#291). "" for none."""
    word = re.sub(r"[^\w -]+", "", typed).strip(" _-")
    return word[:FOUND_KIND_MAX].rstrip(" _-")


def wiki_kind(wiki: str, kind: str, parts: tuple, source_type: str = "source") -> str:
    if wiki == "Meetings":
        return kind if kind in WIKI_KINDS else "note"
    if kind in (source_type, "source") and (not parts or parts[0] == "sources"):
        return "source"
    if kind == "concept" or (parts and parts[0] == "concepts" and kind in ("", "concept")):
        return "concept"
    if kind == "entity" or (parts and parts[0] == "entities" and kind in ("", "entity")):
        return "entity"
    return kind if kind in ("meeting", "mail", "person") else "note"


def plural(word: str) -> str:
    """A kind as the legend says it: `domain` reads "Domains", `case study` "Case studies"."""
    w = KIND_SAID.get(word)
    if w:
        return w
    w = word[:-1] + "ies" if re.search(r"[^aeiou]y$", word) else word + "es" if re.search(r"(s|x|z|ch|sh)$", word) else word + "s"
    return w[:1].upper() + w[1:]


def page_kinds(found: Dict[str, Dict[str, int]]) -> List[Tuple[str, str, str]]:
    """The kinds found from pages (#250): each type no model kind takes that
    KIND_FROM_PAGES pages of one wiki share, by name, as KINDS lists them."""
    types = sorted({t for counts in found.values() for t, c in counts.items() if c >= KIND_FROM_PAGES})
    taken: Dict[int, str] = {}
    out = []
    for t in types:
        at = int(hashlib.sha1(t.encode("utf-8")).hexdigest(), 16) % len(PAGE_COLOURS)
        free = [(at + i) % len(PAGE_COLOURS) for i in range(len(PAGE_COLOURS)) if (at + i) % len(PAGE_COLOURS) not in taken]
        slot = free[0] if free else at            # more kinds than colours: two share one
        taken[slot] = t
        out.append((t, t, PAGE_COLOURS[slot]))
    return out


def short_label(title: str, limit: int = WIKI_LABEL) -> str:
    """A title cut at a word to about `limit` characters, with an ellipsis."""
    if len(title) <= limit:
        return title
    cut = title[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-–—")
    return (cut or title[:limit]) + "…"


def vault_of(ws: Path, folder: Path) -> Optional[Path]:
    """The Obsidian vault a folder's notes belong to: the nearest folder at or
    above it, up to the workspace root, that holds a .obsidian folder."""
    return todo_lines().vault_of(ws, folder)


def vault_filters(vault: Optional[Path]) -> List[object]:
    """A vault's ignore filters (.obsidian/app.json, userIgnoreFilters), a path
    prefix or a /regex/ each, read as the Todo card reads them: what Obsidian
    leaves off its graph, Explore leaves off too. Nothing else of the vault's
    is read, so the graph looks the same with Obsidian or without it (#292).
    Empty outside a vault, or when the file is missing or does not read."""
    return todo_lines().ignore_filters(vault) if vault is not None else []


def ignored(rel: str, filters: List[object]) -> bool:
    return todo_lines().ignored(rel, filters)


def graph(ws: Path, T: Dict[str, dict], link: "Links", now: dt.datetime, cmux: bool = False, actions: bool = False,
          desk: Optional[Dict[str, str]] = None, drive: bool = False, urgent: Optional[set] = None) -> dict:
    """Every note in the zones and the wikis, and the [[links]] between them.
    From a note it keeps its title, kind, place, party tags and, for a thread,
    how long since it moved; from its body only the targets of its links.
    Instructions (AGENTS.md) are not notes, and each zone's Todo.md has the
    Todo card, so neither is drawn. A parked thread, with the notes in
    its folder, and a project with no live thread left, with everything in it,
    are marked `s` and drawn only when the page is asked to show them.

    Every note is coloured by its kind, in every place, whether or not it
    sits inside an Obsidian vault (#292). A vault's ignore filters
    (.obsidian/app.json) leave notes out, as Obsidian's graph does: a filter
    for what to draw, not a colour. Every note in a project carries the
    folder an app opens it in (`f`), its thread's or else its project's,
    where an app can open one. A thread whose own next action is late, named by zone,
    project and thread in `urgent`, is marked `lt` and draws the one ring the
    graph has: age alone never marks a note. Every note carries its path from
    its place's folder, without `.md` (`m`), and `pr` maps each place to that
    folder from the workspace's, so Preview can name the note it reads (#206)."""
    places = [(z.name, z) for z in visible_dirs(ws / "Zones")]
    places += [(w.name, w / "wiki") for w in visible_dirs(ws / "Wikis") if (w / "wiki").is_dir()]
    names = short_names(T)
    held = {(r["zone"], r["project"], r["thread"]) for z in T.values() for r in z["parked"]}
    hubs_parked = {zone: set(data.get("held", ())) for zone, data in T.items()}
    awake = {(r["zone"], r["project"]) for z in T.values() for r in z["rows"]}
    asleep = {(zone, project) for zone, project, _ in held} - awake
    vaults: Dict[Path, List[object]] = {}             # vault -> its ignore filters
    notes = []
    for place, root in places:
        in_zone = root.parent.name == "Zones"
        vault = vault_of(ws, root)
        if vault is not None and vault not in vaults:
            vaults[vault] = vault_filters(vault)
        filters = vaults[vault] if vault is not None else []
        found_in = []                                 # (folder, files), in walk order
        # What the zone's git ignores is known before the walk, so an ignored folder is never entered.
        left_out = git_ignored(root) if in_zone else set()
        for folder, dirs, files in os.walk(root):
            # A folder that tops a repository of its own (a `.git` folder, or the file a worktree has) is not walked.
            dirs[:] = sorted(d for d in dirs if walked(root, folder, d, in_zone) and not (Path(folder) / d / ".git").exists()
                             and Path(folder, d).relative_to(root).as_posix() not in left_out)
            found_in.append((folder, files))
        for folder, files in found_in:
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
    found: Dict[str, Dict[str, int]] = {}             # wiki -> type no model kind takes -> its pages (#250)
    typed_at: List[Tuple[int, str, str]] = []
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
        typed = kind
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
        # i, adj, deg, lp and tw to each node in the browser, so none of those is used here.
        # tw holds a name's widths; it was lw, which a note in a project carries for what an app
        # resumes, so such a note was never named once zoomed in (#252).
        index[path] = len(nodes)
        title = as_text(fm.get("title")).strip() or path.stem
        hub = kind in HUBS.get(wiki, HUBS["*"]) if wiki else kind in HUBS[""]
        typed = found_kind(typed) if wiki and kind == "note" else ""
        if typed and typed not in kinds:
            seen = found.setdefault(wiki, {})
            seen[typed] = seen.get(typed, 0) + 1
            typed_at.append((len(nodes), wiki, typed))      # a kind of its own once enough pages share it (#250)
        nodes.append({"n": short_label(title) if wiki else title, "k": kinds.index(kind), "z": place, "p": project,
                      "t": party, "d": days, "s": 1 if parked else 0,
                      "c": 1 if hub else 0, "h": 1 if kind == "project" else 0,
                      "w": say, "u": link(path), "m": path.relative_to(root).as_posix()[:-3]})
        if link.place(path):
            nodes[-1]["pl"] = link.place(path)       # a hub or a thread's note: a double-click opens it as its row (#318)
        if moving and urgent and (place, project, folder_thread) in urgent:
            nodes[-1]["lt"] = 1                  # its next action is late
        if wiki and nodes[-1]["n"] != title:
            nodes[-1]["N"] = title                   # the whole title, for the card and the tooltip
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
    every = KINDS + page_kinds(found)
    keys = [k for k, _, _ in every]
    for i, wiki, typed in typed_at:
        if found[wiki][typed] >= KIND_FROM_PAGES:
            nodes[i]["k"] = keys.index(typed)
    # A link that is not a whole path resolves to the shortest path that ends
    # in it after a slash, and else to the shortest note of its name; among
    # paths as long, the first walked. Each note goes in once under every such
    # ending, so a link is a lookup, not a pass over every note (#260).
    by_base: Dict[str, Path] = {}
    by_tail: Dict[str, Path] = {}
    for p in sorted(rel, key=lambda q: len(rel[q])):
        by_base.setdefault(p.stem.lower(), p)
        parts = rel[p].split("/")
        for i in range(1, len(parts)):
            by_tail.setdefault("/".join(parts[i:]), p)
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
                hit = by_tail.get(target)
            if hit is None:
                hit = by_base.get(target.split("/")[-1].lower())
            if hit is not None and hit != path:
                a, b = index[path], index[hit]
                edges.add((min(a, b), max(a, b)))
    used = sorted({n["k"] for n in nodes})        # each kind the legend offers as a filter (#250)
    # In a wiki's core view the hubs are joined when one page links both: two
    # people in the same meeting, a person and the entity met in it (#320),
    # two concepts cited by the same source. The third number is how many
    # pages do. A page that joins is any not of the kinds the place opens on
    # (OPENS), or not a hub where it names none: so in Meetings an entity's
    # page still joins two people, as before entities were hubs.
    wikis = {place for place, root, _ in notes if root.parent.name != "Zones"}
    opens = {place: {keys.index(k) for k in OPENS[place] if k in keys} for place in wikis if place in OPENS}
    neighbours: Dict[int, set] = {}
    for a, b in edges:
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    co: Dict[Tuple[int, int], int] = {}
    for i, n in enumerate(nodes):
        if n["z"] not in wikis or (n["k"] in opens[n["z"]] if n["z"] in opens else n["c"]):
            continue
        hubs = sorted(j for j in neighbours.get(i, ()) if j != i and nodes[j]["c"] and nodes[j]["z"] == n["z"])
        for x in range(len(hubs)):
            for y in range(x + 1, len(hubs)):
                co[(hubs[x], hubs[y])] = co.get((hubs[x], hubs[y]), 0) + 1
    counts: Dict[str, int] = {}
    for n in nodes:
        counts[n["z"]] = counts.get(n["z"], 0) + 1
    return {"nodes": nodes, "edges": sorted(edges), "colors": [c for _, _, c in every],
            "kinds": [[i, every[i][1]] for i in used], "keys": keys, "known": len(KINDS),
            "mode": "all" if len(nodes) <= 150 else "core",
            "modes": {z: "all" if c <= 150 else "core" for z, c in counts.items()},
            "pr": {place: root.relative_to(ws).as_posix() for place, root in places},
            "ce": [[a, b, w] for (a, b), w in sorted(co.items())],
            "op": {place: sorted(ks) for place, ks in opens.items()}}


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


# The label prefixes of the plists Garrick ships: `garrick.`, which every one
# has carried, and `gr-`, the prefix of the jobs' own names since #275.
GARRICK_LABELS = ("garrick.", "gr-")
GARRICK_PREFIX = "gr-"
# Garrick's jobs by the names they ran under before #275 and #276, and the
# names they run under now: agent.py's RENAMED and RETIRED, kept here too so
# the page reads the jobs folder without the jobs extra; a test holds them
# equal. A renamed job's old heartbeat and logs are read under its new name;
# a retired job's are not, and its row only goes once the nightly is there.
RENAMED_JOBS = {"backup": "gr-backup", "nurture": "gr-nightly", "reading-sweep": "gr-reading-sweep",
                "todo-sweep": "gr-todo-sweep", "whats-open": "gr-whats-open"}
RETIRED_JOBS = {"status": "gr-nightly"}


def garrick_job(label: Optional[str], name: Optional[str] = None) -> bool:
    """Whether a job is one of those Garrick ships, rather than one the user
    added: its launchd label starts with one of GARRICK_LABELS. A job with no
    plist has no label, and is Garrick's only when its name has Garrick's
    prefix, as a renamed job's does before its new plist is loaded."""
    if label:
        return str(label).startswith(GARRICK_LABELS)
    return bool(name) and str(name).startswith(GARRICK_PREFIX)


RENAMED_FROM = "GARRICK_RENAMED_FROM"     # set in a renamed plist by update.py's commands: the old name


def superseded(folder: Path, sched: Dict[str, dict]) -> Tuple[Dict[str, List[Tuple[str, float]]], set]:
    """Garrick's jobs that run under a new name now (#275): new name ->
    [(old name, cutoff)], the old names whose runs from before `cutoff`
    (epoch seconds) are read under the new one, and the old names no longer
    shown as a row of their own.

    Only what is Garrick's moves. The old name is folded in only when the
    new name's plist carries GARRICK_RENAMED_FROM naming it, which update.py's
    commands write into a plist it found running Garrick's own script under
    that name, or when a run under the new name recorded it (job.py's
    `renamed_from`), and only while no plist runs the old name. The cutoff is
    the first run under the new name (`renamed_at`), or before it the
    renamed plist's last change: a run under the old name after it is not
    Garrick's, and the old name keeps a row of its own while it has one. The
    retired evening build, `status`, is hidden once the nightly is there (a
    plist or a heartbeat), no plist runs `status`, and no `status` run has
    finished since the nightly's first run; its runs are never the
    nightly's. Nothing outside the jobs folder decides it, so deleting the
    plist set aside as .retired changes nothing."""
    earlier: Dict[str, List[Tuple[str, float]]] = {}
    hidden = set()

    def beat(name: str) -> dict:
        try:
            got = json.loads((folder / (name + ".heartbeat.json")).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return got if isinstance(got, dict) else {}

    def finished(name: str) -> Optional[float]:
        hb = beat(name)
        if isinstance(hb.get("finished_ts"), (int, float)):
            return float(hb["finished_ts"])
        try:
            return dt.datetime.strptime(str(hb.get("finished"))[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return None

    for old, new in RENAMED_JOBS.items():
        if old in sched:
            continue
        hb = beat(new)
        plist = sched.get(new) or {}
        cutoff = None
        if hb.get("renamed_from") == old and isinstance(hb.get("renamed_at"), (int, float)):
            cutoff = float(hb["renamed_at"])
        elif (plist.get("env") or {}).get(RENAMED_FROM) == old and plist.get("plist"):
            try:
                cutoff = Path(plist["plist"]).stat().st_mtime
            except OSError:
                cutoff = None
        if cutoff is None:
            continue
        earlier.setdefault(new, []).append((old, cutoff))
        last = finished(old)
        if last is None or last < cutoff:
            hidden.add(old)
    def first_run(name: str) -> Optional[float]:
        """When the job first ran, as far as its logs and heartbeat go back."""
        hb = beat(name)
        seen = [float(hb["renamed_at"])] if isinstance(hb.get("renamed_at"), (int, float)) else []
        if finished(name) is not None:
            seen.append(finished(name))
        for path in (folder / (name + ".log.1"), folder / (name + ".log")):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            m = next((LOGLINE.match(line) for line in text.splitlines() if LOGLINE.match(line)), None)
            if m:
                seen.append(dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp())
        return min(seen) if seen else None

    for old, new in RETIRED_JOBS.items():
        if old in sched or not (new in sched or (folder / (new + ".heartbeat.json")).is_file()):
            continue
        first, last = first_run(new), finished(old)
        if first is None or last is None or last < first:
            hidden.add(old)
    return earlier, hidden


def launchd_jobs(folder: Optional[Path] = None) -> Dict[str, dict]:
    """Job name -> what its launchd plist says: the schedule in words, how
    long before a missing run is late, whether it calls the assistant
    (--agent), the environment it runs with, its label, and the line its
    GARRICK_ABOUT gives, empty when it gives none. Only plists that run job.py;
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
        env = env if isinstance(env, dict) else {}
        out[args[at + 1]] = {"schedule": words, "late": late, "agent": "--agent" in flags, "env": env, "plist": plist,
                             "label": str(p.get("Label") or plist.stem), "about": env["GARRICK_ABOUT"].strip() if isinstance(env.get("GARRICK_ABOUT"), str) else ""}
    return out


def history(folder: Path, name: str, now: dt.datetime,
            earlier: Tuple[Tuple[str, float], ...] = ()) -> List[Tuple[dt.datetime, int, bool]]:
    """(when, exit, quiet) for each run the job's logs record in the last DAYS
    days, and those the logs of the names it ran under before record from
    before each one's cutoff (superseded())."""
    since = now - dt.timedelta(days=DAYS)
    runs = []
    for n, cutoff in (*earlier, (name, None)):
        for path in (folder / (n + ".log.1"), folder / (n + ".log")):
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                m = LOGLINE.match(line)
                if not m:
                    continue
                when = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                if when >= since and (cutoff is None or when.timestamp() < cutoff):
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
    with the schedule its plist gives. A heartbeat with no plist is a job a
    hook or a session starts: "started by a session", and the user's. Each
    row carries its plist's label, GARRICK_ABOUT and --agent, and whether it
    is Garrick's (garrick_job). A job of Garrick's that ran under an older
    name is one row under its new name, with the older runs in its strip
    (superseded())."""
    sched = launchd_jobs() if sched is None else sched
    earlier, hidden = superseded(folder, sched) if folder.is_dir() else ({}, set())
    beats: Dict[str, Tuple[dict, Optional[dt.datetime]]] = {}
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
        beats[name] = (hb, when)
    for new, olds in earlier.items():             # the newest heartbeat of a renamed job, under its new name
        got = ([beats[new]] if new in beats else []) + [beats[o] for o, cut in olds if o in beats and o in hidden]
        if got:
            beats[new] = max(got, key=lambda b: b[1] or dt.datetime.min)
    out = []
    for name, (hb, when) in sorted(beats.items()):
        if name in hidden:
            continue
        olds = tuple(earlier.get(name, ()))
        code = int(hb.get("exit", -1)) if str(hb.get("exit", "")).lstrip("-").isdigit() else -1
        env = sched[name].get("env", {}) if name in sched else {}
        # job.py says itself whether the exit was fine (`ok`, `quiet`); an older
        # heartbeat leaves it to the codes and the plist's GARRICK_QUIET_EXITS.
        quiet = set(quiet_exits(env)) | ({code} if hb.get("quiet") is True or (hb.get("ok") is True and code not in OK_EXITS) else set())
        words, limit = (sched[name]["schedule"], sched[name]["late"]) if name in sched else ("started by a session", None)
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
        running = lock_held(folder / (name + ".lock"), now)
        steps = hb["steps"] if isinstance(hb.get("steps"), list) else None
        unrun = [x for x in steps or [] if isinstance(x, dict) and str(x.get("skipped") or "").startswith("not executable")]
        if unrun and state == "good":             # the job is fine, but a step of yours never runs (#276)
            state, status = "warning", "%s skipped: %s" % (unrun[0].get("step"), unrun[0]["skipped"])
        live = steps_now(folder, name) if running else None
        if live is not None:                      # the nightly building this page mid-run says what failed so far
            steps = live
            if failed_steps(live):
                state, status = "critical", "%s failed in the run under way" % failed_steps(live)
        out.append({"name": name, "when": when, "seconds": hb.get("seconds"), "state": state, "status": status,
                    "title": job_title(name, hb, env), "code": code, "since": failing_since(hb, when),
                    "reason": hb["reason"] if isinstance(hb.get("title"), str) and isinstance(hb.get("reason"), str) else "",
                    "schedule": words, "runs": history(folder, name, now, olds), "log": job_log(folder, name, olds),
                    "quiet": tuple(sorted(quiet)), "running": running,
                    "idle": state == "warning" and status.startswith("idle"), "steps": steps,
                    **plist_facts(sched.get(name), name)})
    beaten = {j["name"] for j in out}
    for name, plist in sched.items():
        if name not in beaten:
            olds = tuple(earlier.get(name, ()))
            running = lock_held(folder / (name + ".lock"), now)
            live = steps_now(folder, name) if running else None
            state, status = ("critical", "%s failed in the run under way" % failed_steps(live)) if failed_steps(live) \
                else ("none", "not run yet")
            out.append({"name": name, "when": None, "seconds": None, "state": state, "status": status,
                        "title": job_title(name, {}, plist.get("env", {})), "code": None, "since": None, "reason": "",
                        "schedule": plist["schedule"], "runs": history(folder, name, now, olds),
                        "log": job_log(folder, name, olds),
                        "quiet": quiet_exits(plist.get("env", {})), "running": running,
                        "idle": False, "steps": live, **plist_facts(plist, name)})
    return sorted(out, key=lambda j: j["name"].casefold())


def job_title(name: str, hb: dict, env: Optional[dict] = None) -> str:
    """A job's plain name for the Overview (#559): the `title` job.py wrote into the heartbeat, else the plist's
    GARRICK_JOB_TITLE, else the name without its `gr-` prefix, hyphens as spaces, first letter capitalised."""
    for given in ((hb or {}).get("title"), (env or {}).get("GARRICK_JOB_TITLE")):
        if isinstance(given, str) and given.strip():
            return given.strip()[:60]
    base = name[3:] if name.startswith("gr-") and len(name) > 3 else name
    base = re.sub(r"[-_]+", " ", base).strip()
    return base[:1].upper() + base[1:] if base else name


def failing_since(hb: dict, when: Optional[dt.datetime]) -> Optional[dt.date]:
    """The day a job began to fail, from its heartbeat's `failing_since`, else the day its last run finished."""
    try:
        return dt.datetime.strptime(str(hb.get("failing_since"))[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        return when.date() if when else None


def step_reason(steps: Optional[List[dict]]) -> str:
    """The first step that failed, as job.py words it: "Recall timed out", "Effort failed"; "" when none did."""
    for x in steps or []:
        if isinstance(x.get("exit"), int) and x["exit"] != 0:
            name = re.sub(r"[-_]+", " ", str(x.get("step"))).strip()
            return "%s %s" % ((name[:1].upper() + name[1:])[:40], "timed out" if x["exit"] == 124 else "failed")
    return ""


def steps_now(folder: Path, name: str) -> Optional[List[dict]]:
    """The steps a run still going has reported so far (job.py's
    `<name>.steps.json`, which the nightly job writes after each step), or
    None. The nightly rebuilds this page as its last step, before its
    heartbeat is written, so this is how a step that failed tonight shows."""
    try:
        data = json.loads((folder / (name + ".steps.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else None


def failed_steps(steps: Optional[List[dict]]) -> str:
    """The steps that failed, in words, as job.py says them: `effort (exit 1)`."""
    return ", ".join("%s (exit %s)" % (x.get("step"), x.get("exit")) for x in steps or []
                     if isinstance(x.get("exit"), int) and x["exit"] != 0)


def job_log(folder: Path, name: str, earlier: Tuple[Tuple[str, float], ...] = ()) -> Path:
    """The job's log; before a renamed job's first run under its new name,
    the log it left under the newest of its old ones."""
    for n in (name, *(o for o, _ in reversed(earlier))):
        if (folder / (n + ".log")).is_file():
            return folder / (n + ".log")
    return folder / (name + ".log")


def plist_facts(plist: Optional[dict], name: Optional[str] = None) -> dict:
    """What a job's row takes from its plist: the label, the line it gives in
    GARRICK_ABOUT, whether it calls the assistant (None with no plist), and
    whether it is Garrick's."""
    plist = plist or {}
    label = plist.get("label")
    return {"label": label, "about": plist.get("about", ""), "agent": plist.get("agent"),
            "garrick": garrick_job(label, name)}


def log_tail(path: Path, lines: int = 30, width: int = 300) -> List[str]:
    """The last lines of a job's log, read from its end, each cut to `width`
    characters; none when there is no log. A read that starts mid-file drops
    its first line, which is likely a part of one."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            start = max(0, f.tell() - 64 * 1024)
            f.seek(start)
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    got = text.splitlines()[1 if start else 0:]
    return [line[:width] for line in got[-lines:]]


# A job's name opens its panel below its row, and closes it again (#273).
JOBS_JS = r"""
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('button.jname'),p=b&&document.getElementById(b.getAttribute('aria-controls'));
if(!p)return;p.hidden=!p.hidden;b.setAttribute('aria-expanded',String(!p.hidden))});
"""


def job_panel(j: dict, i: int, ok: bool, log_link: str) -> str:
    """What a job's name opens below its row: what it does, its schedule, its
    plist's label, whether it calls the assistant, its last runs and the end
    of its log, with Open log for the whole file."""
    facts = [("Schedule", j["schedule"])]
    if j.get("label"):
        facts.append(("Label", j["label"]))
    if j.get("agent") is not None:
        facts.append(("Assistant", "calls it" if j["agent"] else "not called"))
    runs = sorted(j["runs"], key=lambda r: r[0], reverse=True)[:5]
    said = "".join('<li>%s · %s</li>' % (E(w.strftime("%a %d %b %H:%M")), E(
        "ok" if c == 0 else "skipped" if c == 75 else "exit %d, quiet" % c if q or c in j["quiet"] else "exit %d" % c)) for w, c, q in runs)
    tail = log_tail(j["log"])
    # A job of several steps (the nightly, #276) says how each went on its last run.
    steps = "".join('<li>%s · %s</li>' % (E(str(s.get("step"))), E(
        "skipped: %s" % s["skipped"] if s.get("skipped") else "ok" if s.get("exit") == 0 else "exit %s" % s.get("exit")))
        for s in j.get("steps") or [] if isinstance(s, dict))
    return ('<div class="jpanel" id="jp-%d" data-ok="%d" hidden>%s<dl>%s</dl>%s<h4>Last runs</h4>%s<h4>Log</h4>%s'
            '<div class="gacts"><a class="act" href="%s">Open log</a></div></div>'
            % (i, ok, '<p>%s</p>' % E(j["about"]) if j.get("about") else "",
               "".join("<dt>%s</dt><dd>%s</dd>" % (E(k), E(v)) for k, v in facts),
               '<h4>Steps, last run</h4><ul>%s</ul>' % steps if steps else "",
               '<ul>%s</ul>' % said if said else '<p class="muted">None in %d days.</p>' % DAYS,
               '<pre>%s</pre>' % E("\n".join(tail)) if tail else '<p class="muted">No log yet.</p>', E(log_link)))


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
    # Ask's calls count against Ask's own caps (#282), so the jobs' meters
    # count the jobs' calls alone. An agent.py from before that has one
    # budget for every call, and the meters count them all, as it does.
    ask = getattr(agent, "ASK", None) if hasattr(agent, "cap_reached") else None
    jobs = [e for e in calls if ask is None or e.get("job") != ask]
    day = [e for e in jobs if now.timestamp() - e["ts"] < 86400]
    hour = [e for e in jobs if now.timestamp() - e["ts"] < 3600]
    earlier, _ = superseded(folder, sched)
    was = {old: (new, cut) for new, olds in earlier.items() for old, cut in olds}   # a renamed job's calls from before its cutoff

    def whose(e: dict) -> str:
        name = e.get("job", "?")
        new, cut = was.get(name, (None, 0))
        return new if new and e["ts"] < cut else name
    by = {}
    for e in entries:
        j = by.setdefault(whose(e), {"calls": 0, "cost": 0.0, "failed": 0, "refused": 0, "denied": set(), "turns": []})
        if e.get("refused"):
            j["refused"] += 1
            continue
        j["calls"] += 1
        j["cost"] += float(e.get("cost_usd") or 0)
        # A request ended with Ask's Stop is billed with exit 1, but it did not fail (#294).
        j["failed"] += 1 if e.get("exit") and e.get("subtype") != "stopped" else 0
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
            "over_budget": [e for e in calls if now.timestamp() - e["ts"] < 86400 and e.get("subtype") == "error_max_budget_usd"],
            "budget": call_budget(agent, sched), "deny": deny_list(agent), "ask_job": ask,
            "ask": ask_calls(agent, calls, now) if ask and any(e.get("job") == ask for e in entries) else None}


# Which of Ask's own caps refused a call, from the reason agent.py wrote for
# it, in the words the box uses (ask.capped()): the first that the reason
# holds. A cap set below zero is named by its variable.
ASK_CAP_WORDS = (("in the last hour", "requests an hour"), ("_ASK_HOUR", "requests an hour"),
                 ("spent in", "spending a day"), ("_ASK_COST_DAY", "spending a day"),
                 ("in the last 24 hours", "requests a day"), ("_ASK_DAY", "requests a day"))


def ask_cap(reason) -> str:
    """Which of Ask's caps refused a call, said as the box says it, or ""."""
    return next((said for key, said in ASK_CAP_WORDS if key in str(reason)), "")


def ask_cap_stopped(cap: str, n: int) -> str:
    """The Needs attention line for Ask's calls a cap of its own refused: which
    cap, never "the spending cap" when it was the requests an hour (#294)."""
    times = "" if n == 1 else " %d times in 24 hours" % n
    return "Ask's limit on %s stopped it%s" % (cap, times) if cap else "One of Ask's limits stopped it%s" % times


def ask_calls(agent, calls: List[dict], now: dt.datetime) -> dict:
    """The ask box's calls against its own caps (#282), shown once the
    ledger holds a line of Ask's. Ask runs in the Garrick App's environment,
    not a launchd plist's, so its caps are the GARRICK_CAP_ASK_* this page
    was built with, or agent.py's defaults."""
    mine = [e for e in calls if e.get("job") == agent.ASK]
    day = [e for e in mine if now.timestamp() - e["ts"] < 86400]
    hour = [e for e in mine if now.timestamp() - e["ts"] < 3600]
    named = any(var in os.environ for var in agent.CAP_VARS[agent.ASK].values())
    return {"caps": agent.caps(agent.ASK), "day": len(day), "hour": len(hour),
            "cost_day": sum(float(e.get("cost_usd") or 0) for e in day),
            "caps_from": "Ask's own caps, from the GARRICK_CAP_ASK_* settings the page was built with; the app may run under others."
                         if named else "Ask's own caps, agent.py's defaults; GARRICK_CAP_ASK_* in the app's environment changes them."}


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
# Garrick.app runs it. An app without one is
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
    """Every link the page makes to a file or a folder (#318): a file:// URL
    to the path as it stands in the workspace, never resolved, so a link that
    is itself a symlink stays one and Garrick.app refuses it, as it refuses a
    cited record that is. Nothing here asks Obsidian, or any other app, where
    a note should open: Garrick.app opens a hub or a thread's note as its row
    does and anything else in the app macOS opens it in, and a browser follows the link."""

    def __init__(self, ws: Path):
        self.ws = ws

    def __call__(self, path: Path) -> str:
        return Path(os.path.abspath(str(path))).as_uri()

    def place(self, path: Path) -> Optional[str]:
        """The folder of the project or thread whose note `path` is: a hub,
        `Zones/<zone>/<project>/<project>.md` or `System/<project>/<project>.md`,
        or a thread's note, `.../Threads/<thread>/<thread>.md`. None for any
        other file, which opens as itself."""
        p = Path(os.path.abspath(str(path)))
        try:
            parts = p.relative_to(Path(os.path.abspath(str(self.ws)))).parts
        except ValueError:
            return None
        if p.suffix != ".md" or len(parts) < 3 or p.stem != p.parent.name:
            return None
        hub = (parts[0] == "Zones" and len(parts) == 4) or (parts[0] == "System" and len(parts) == 3)
        thread = len(parts) >= 5 and parts[-3] == "Threads" and parts[0] in ("Zones", "System")
        return str(p.parent) if hub or thread else None

    def attrs(self, path: Path) -> str:
        """An <a>'s href to `path`, and where it is a hub or a thread's note,
        its place, `data-place`: the page hands such a link to the host, which
        opens it as the row of that project or thread opens (#318)."""
        place = self.place(path)
        return 'href="%s"%s' % (E(self(path)), ' data-place="%s"' % E(place) if place else "")


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
    "good": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="var(--good)"/><path d="M4.8 8.2l2.1 2.1 4.3-4.6" fill="none" stroke="var(--accent-ink)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "warning": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5l7 12.5H1z" fill="var(--warning)" stroke="var(--warning)" stroke-width="1.5" stroke-linejoin="round"/><path d="M8 6v3.6" stroke="var(--accent-ink)" stroke-width="1.7" stroke-linecap="round"/><circle cx="8" cy="11.9" r="1" fill="var(--accent-ink)"/></svg>',
    "critical": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="var(--critical)"/><path d="M5.4 5.4l5.2 5.2M10.6 5.4l-5.2 5.2" stroke="var(--accent-ink)" stroke-width="1.8" stroke-linecap="round"/></svg>',
    "none": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="var(--muted)" stroke-width="1.6"/></svg>',
}
# Status in words (#551): a pill with a line icon and a word, never a colour alone. `Fine`, `Look soon`, `Late`,
# `Act now` and `Waiting` are the only five; the class sets the colour, the word carries the meaning.
_PILL_PATHS = {
    "check": '<circle cx="8" cy="8" r="6"/><path d="M5.4 8.2l1.8 1.8 3.4-3.7"/>',
    "clock": '<circle cx="8" cy="8" r="6"/><path d="M8 4.6V8l2.2 1.4"/>',
    "late": '<circle cx="8" cy="8" r="6"/><path d="M8 4.8v3.8M8 11.2h.01"/>',
    "alert": '<path d="M8 2.2l6 10.6H2z"/><path d="M8 6.6v2.8M8 11.4h.01"/>',
    "pause": '<circle cx="8" cy="8" r="6"/><path d="M6.6 5.8v4.4M9.4 5.8v4.4"/>',
}
PILLS = {"good": ("good", "Fine", "check"), "look": ("warn", "Look soon", "clock"), "late": ("crit", "Late", "late"),
         "act": ("crit", "Act now", "alert"), "wait": ("idle", "Waiting", "pause")}
STATE_PILL = {"good": "good", "warning": "look", "critical": "act", "none": "wait"}     # ICON's states, in words


def pill(state: str, extra: str = "") -> str:
    """The pill for a state: one of PILLS, or one of ICON's (good, warning, critical, none). `extra` is added to its class."""
    cls, word, icon = PILLS[STATE_PILL.get(state, state)]
    return ('<span class="st %s%s"><svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" '
            'stroke-linecap="round" stroke-linejoin="round">%s</svg>%s</span>' % (cls, " " + extra if extra else "", _PILL_PATHS[icon], word))


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
    its own next action is late (`lt`), which is the one
    thing that marks a thread; its age never does. Where an app to open it in is installed (`cmux`, for any
    of LAUNCHERS), also the thread's folder. With the cmux extra (`desk`, the
    sessions open), the session's state, and with `drive` (the extra and
    cmux) what the desk opens and closes."""
    card = {"n": r["thread"], "kl": "thread", "z": r["zone"], "p": r["project"], "t": r["party"], "d": days,
            "s": 1 if r["status"] == "parked" else 0, "w": names[(r["zone"], r["project"], r["thread"])], "h": 0,
            "u": link(r["note"]), "r": 1 if r.get("resume") else 0,
            "rd": (today - r["resumed"]).days if today and r.get("resumed") else None}
    if r.get("late"):
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


def first_thread() -> str:
    """The name a project's first thread gets when none is typed: ask.py's FIRST_THREAD, read from its file so that
    the dialog and the Ask box name it once. "" when ask.py is not beside this file."""
    src = Path(__file__).with_name("ask.py")
    try:
        found = re.search(r'^FIRST_THREAD = "([^"\n]+)"', src.read_text(encoding="utf-8"), re.M)
    except OSError:
        return ""
    return found.group(1) if found else ""


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
    return {"zones": zones, "acting": acting, "first": first_thread()}


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


def set_head(name: str, key: str, lede: str = "") -> str:
    """A Settings section's heading, with the "?" for its explanation, and
    under it the one plain sentence, always shown, that says what the
    section is for (#205). The heading is also the section's name in the
    list beside them (settings_nav())."""
    return '<h3>%s%s</h3>%s' % (E(name), help_button(name, key), '<p class="setlede">%s</p>' % lede if lede else "")


def allowed_settings(rows: List[dict]) -> str:
    """Settings › Allowed by you (#542): what the user let through the wall check, once, each with Remove, as the Context tab
    listed it; "" with none. Remove is the page's `walls-unallow`; nothing here allows anything."""
    body = questions_mod().allowed_rows(rows)
    if not body:
        return ""
    return ('<section class="setsec" id="allowed-settings">%s%s<ul>%s</ul></section>'
            % (set_head("Allowed by you", "allowed", "A finding you chose to let through, once, for the file as it was."),
               help_text("allowed", "Editing the file ends the allowance. Remove puts the refusal back at the next commit. "
                                    "Only <code>check.py allow</code>, typed in a terminal, adds one."), body))


def menu_settings() -> str:
    """Settings › Menu bar, shown in Garrick.app
    only: the icon or a panel at a screen edge, opening at login, the
    shortcut that opens either, the one that opens the Ask box, whether it
    answers, and the dictation the box starts once it opens. The app keeps
    them all, so they hold when the window is closed."""
    return ('<section class="setsec apponly" id="menu-settings" hidden>' + set_head("Menu bar", "menu", 'Keep your live projects '
            'one click away from any app: in the menu bar, or in a panel at the edge of the screen.') + help_text("menu", 'A menu of the live '
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
            '<div class="launcher-row" style="display:none"><label class="launcher-choice"><input type="checkbox" id="menu-ask"> <span>Answer in the Ask box'
            '<small>Keeps a warm assistant session that spends model calls. Off, no Ask box, no key held, and the panel\'s field opens your assistant</small></span></label></div>'
            '<div class="launcher-row" style="display:none"><label class="launcher-choice" for="menu-askkey"><span>Ask hotkey<small id="menu-askkey-note">'
            'Opens the Ask box from any app</small></span></label>'
            '<span class="hotkey"><input type="text" id="menu-askkey" readonly placeholder="None" aria-label="Ask hotkey">'
            '<button class="act" type="button" id="menu-askkey-clear">Clear</button></span></div>'
            '<div class="launcher-row" style="display:none"><span class="launcher-choice"><span>Close the Ask box with'
            '<small id="menu-askclose-note">One way always stays on</small></span></span>'
            '<span class="askclose"><label><input type="checkbox" id="menu-askclose-esc"> Escape</label> '
            '<label><input type="checkbox" id="menu-askclose-click"> A click outside it</label></span></div>'
            '<div class="launcher-row" style="display:none"><label class="launcher-choice" for="menu-dictation"><span>Then start dictation'
            '<small id="menu-dictation-note">Once the Ask box opens, start dictation in it too</small></span></label>'
            '<select id="menu-dictation" class="menu-style"><option value="off">Off</option><option value="macos">macOS Dictation</option>'
            '<option value="fn">Press Fn</option><option value="fn2">Press Fn twice</option><option value="key">Press a shortcut</option></select></div>'
            '<div class="launcher-row" style="display:none"><label class="launcher-choice" for="menu-dictkey"><span>Dictation shortcut'
            '<small id="menu-dictkey-note">Click, then press the shortcut your dictation tool starts on. Pause the tool first if it takes the keys</small></span></label>'
            '<span class="hotkey"><input type="text" id="menu-dictkey" readonly placeholder="Click, then press keys" aria-label="Dictation shortcut">'
            '<button class="act" type="button" id="menu-dictkey-clear">Clear</button></span></div>'
            '<div class="launcher-row" style="display:none"><label class="launcher-choice" for="menu-finder"><span>Finder menu'
            '<small id="menu-finder-note">Right-click a project or thread folder in Finder to open it from there</small></span></label>'
            '<button class="act" type="button" id="menu-finder">Open Login Items &amp; Extensions</button></div></section>')


def copy(label: str, text: str, say: str) -> str:
    """A button that copies a phrase for your assistant, or a command for your
    terminal. The page acts on nothing itself."""
    return '<button class="act" type="button" data-copy="%s" data-say="%s">%s</button>' % (E(text), E(say), E(label))


def request_button(label: str, phrase: str, folder: Path, cls: str = "act") -> str:
    """A button named for a request, such as Process the Inbox (#234). In the
    app it opens the assistant the menu's rows open, at `folder`, with the
    request typed in (JS's data-request); in a browser it copies the request."""
    return ('<button class="%s" type="button" data-request="%s" data-folder="%s" title="%s">%s</button>'
            % (cls, E(phrase), E(str(folder)), E("Hand “%s” to your assistant" % phrase), E(label)))


# The changelog the workspace was installed with: install.py copies the
# release's CHANGELOG.md here, so the page knows the release it runs, for
# About Garrick and the Guide's links, without fetching anything.
CHANGELOG = ("System", "garrick-changelog.md")
GEAR = ('<svg viewBox="0 0 20 20" width="17" height="17" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.5" '
        'stroke-linejoin="round" d="M8.6 2.5h2.8l.4 2.1 1.5.9 2-.8 1.4 2.4-1.6 1.4v1.8l1.6 1.4-1.4 2.4-2-.8-1.5.9-.4 2.1H8.6l-.4-2.1'
        '-1.5-.9-2 .8-1.4-2.4 1.6-1.4V8.5L3.3 7.1l1.4-2.4 2 .8 1.5-.9z"/><circle cx="10" cy="10" r="2.4" fill="none" '
        'stroke="currentColor" stroke-width="1.5"/></svg>')


REBUILD = ('<svg viewBox="0 0 20 20" width="17" height="17" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.6" '
           'stroke-linecap="round" stroke-linejoin="round" d="M16 10a6 6 0 1 1-1.8-4.3M16 3.5v3.4h-3.4"/></svg>')


def plain_text(s: str) -> str:
    """A line of Markdown as a reader hears it, for a label or a sort key: a
    link's text and never its address, so a Todo line's source, whatever its
    form, is its title (#318)."""
    return re.sub(r"[*_`]", "", guide_mod().plain(s))


def md_inline(s: str) -> str:
    """A line of Markdown, through guide.py's renderer: a link keeps its text, since the page links only to Garrick."""
    return guide_mod().inline(s)


def release_number(ws: Path) -> str:
    """"Garrick 0.43.0": the release the workspace runs, the newest in its
    copy of the release notes, through its own garrick_lib. A workspace
    whose tools cannot say it gets the sentence `check.py --version` gives."""
    lib = workspace_lib(ws)
    read = getattr(lib, "workspace_release", None)
    try:
        number = read(ws) if callable(read) else ""
    except Exception:
        number = ""
    return "Garrick %s" % number if number else installed_version(ws)


def release_choice(ws: Optional[Path]) -> Tuple[bool, int]:
    """(whether the check for a newer Garrick is on, its cadence in days),
    from the settings file through the workspace's own garrick_lib. Off and
    daily where it cannot be read."""
    lib = workspace_lib(ws)
    on, every = getattr(lib, "release_notice_on", None), getattr(lib, "release_every", None)
    try:
        return (bool(on(ws)) if callable(on) else False,
                7 if callable(every) and every(ws).days == 7 else 1)
    except Exception:
        return False, 1


def release_controls(on: bool, every: int) -> str:
    """Settings › About Garrick's Check for updates button and its switch
    (#410), in the app only. The button asks GitHub now, which is the
    click's consent; the switch and its cadence are saved when Settings
    closes, with the rest, as `release-notice` and `release-notice-every`.
    RELEASE_JS fills the line and the report."""
    option = lambda days, label: '<option value="%d"%s>%s</option>' % (days, " selected" if every == days else "", label)
    return ('<div class="setrel apponly" id="release-settings"><p class="setrelrow"><button type="button" class="act" '
            'id="rel-check">Check for updates</button><span class="hint" id="rel-line" role="status"></span></p>'
            '<div class="setrelbox" id="rel-detail" hidden></div>'
            '<p class="setrelrow"><label><input type="checkbox" id="rel-on"%s> <span>Check for a newer Garrick</span></label> '
            '<select id="rel-every" aria-label="How often"%s>%s%s</select></p>'
            '</div>'
            % (" checked" if on else "", "" if on else " disabled", option(1, "Daily"), option(7, "Weekly")))


def stale_band_lines(ws: Optional[Path]) -> str:
    """The band kept outside the workspace, when it is from another commit than
    the workspace runs: `check.py --version` says the same. Read through the
    workspace's own garrick_lib, and nothing when its tools cannot say."""
    found = getattr(workspace_lib(ws), "stale_bands", None) if ws is not None else None
    try:
        lines = found(ws) if callable(found) else []
    except Exception:
        lines = []
    return "".join('<p class="setver" id="band-stale">%s</p>' % E(line) for line in lines)


def about_garrick(version: str, ws: Optional[Path] = None) -> str:
    """Settings › About Garrick (#227): the release this is, and three links
    to Garrick's GitHub page, opened in the browser, where nothing is sent
    until you submit it yourself: the bug form, with the version filled in;
    an idea; and the release notes. A way past the wall check is reported
    privately, as SECURITY.md says, and the bug form points there. The page
    never calls out: a newer release is asked for at build and by the nightly
    job, only with the release notice switched on, by System/tools/release.py
    (release_ask), and by the Check for updates button, on a click."""
    invented = "Use invented names (Acme, Birch), never a real client's."
    links = [("Report a bug", "/issues/new?" + urllib.parse.urlencode({"template": "bug.yml", "garrick": version}), invented),
             ("Suggest a change", "/discussions/new?category=ideas", invented),
             ("Release notes", "/releases", "")]
    rows = "".join('<a class="setlink" href="%s" target="_blank" rel="noopener"%s><b>%s</b></a>'
                   % (E(PROJECT + path), ' title="%s"' % E(tip) if tip else "", E(label)) for label, path, tip in links)
    return ('<section class="setsec" id="about-settings">%s%s<p class="setver" id="garrick-version">%s</p>%s%s'
            '<div class="setlinks">%s</div></section>'
            % (set_head("About Garrick", "about"), help_text("about", 'These open GitHub in your browser. Nothing is sent '
               'until you submit it there. Use invented names (Acme, Birch), never a real client&#39;s. Check for updates '
               'asks GitHub for the newest release when you press it, and updates when there is a newer one. Check for a newer Garrick '
               'is off by default, since it is the only call Garrick makes on its own: it tells you in a notice and on the Repositories card, and never updates.'),
               E(version), stale_band_lines(ws), release_controls(*release_choice(ws)) if ws is not None else "", rows))


# Each row of Opening a thread carries the icon its way carries on Explore's
# cards (#227): the app's own, which Garrick.app sets as --icon-<key> with
# .appicons, and Preview's magnifier. A browser, whose cards keep the words,
# shows none.
LAUNCH_ICON = '<i class="lico" aria-hidden="true" style="--ic:%s"></i>'
GLASS = ('<svg class="lico lglass" viewBox="0 0 16 16" aria-hidden="true"><circle cx="6.8" cy="6.8" r="4.6" fill="none" '
         'stroke="currentColor" stroke-width="1.6"/><path d="M10.2 10.2L14 14" stroke="currentColor" stroke-width="1.8" '
         'stroke-linecap="round"/></svg>')


# Which assistant a cmux tab starts (#279): the cmux extra's `agent` setting,
# in System/desk.json, which the desk reads for every tab it opens. Settings
# shows it under Open in cmux while that is switched on, and saves it through
# the desk itself (page_action.py), so the two never disagree.
DESK_AGENTS = (("claude", "Claude Code"), ("codex", "Codex"))


def desk_agent(ws: Path) -> str:
    """The assistant a new cmux tab starts, as the desk reads it: `agent` in
    System/desk.json, or the file GARRICK_DESK_CONFIG names; claude when it
    is not set or the file does not read."""
    f = Path(os.environ.get("GARRICK_DESK_CONFIG") or ws / "System" / "desk.json").expanduser()
    try:
        agent = json.loads(f.read_text(encoding="utf-8")).get("agent")
    except (OSError, ValueError, AttributeError):
        agent = None
    return agent if agent in dict(DESK_AGENTS) else "claude"


def launcher_choices(installed: Tuple[str, ...], why: Optional[Dict[str, Optional[str]]] = None,
                     agent: Optional[str] = None) -> str:
    """Settings › Opening a thread: the note's own link, *Open the note* in
    the app macOS opens a .md file in, whatever is installed (#318), then each app Garrick
    can open a project in, with a checkbox (offered on the cards) and a radio
    (what clicking a thread's name does), each with its card icon. Explore's
    Preview has the box alone, after the note's link (#219). A launcher that
    cannot work here is disabled with the reason on it, before any click
    rather than after: not installed, or installed without the launcher it
    opens a folder through. How each app takes the resume phrase is in the
    docs, not here (#227). Kept in this viewer's own storage, so the page
    still writes nothing. `agent`, given where the desk can open cmux tabs,
    adds which assistant a tab starts under Open in cmux (#279); the app
    saves that one in System/desk.json when Settings closes."""
    why = launcher_state() if why is None else why
    rows = [("note", "Open the note", True, "", LAUNCH_ICON % "var(--icon-note)")]
    rows += [(k, VERB[k], k in installed, "" if k in installed else E(why[k]) if why.get(k) else LEFT_OUT,
              LAUNCH_ICON % "var(--icon-%s)" % k)
             for k, _, _, _ in LAUNCHERS]
    row = ('<div class="launcher-row"><label class="launcher-choice"><input type="checkbox" data-launcher="%s"%s> %s<span>%s%s</span></label>'
           '<label class="launcher-default" title="What clicking a thread does"><input type="radio" name="garrick-default" value="%s"%s> Default</label></div>')
    html = [row % (k, "" if ok else " disabled", icon, E(label), "<small>%s</small>" % note if note else "", k, "" if ok else " disabled")
            for k, label, ok, note, icon in rows]
    # Explore's Preview (#219), after the note it reads: a box and no Default, since it opens
    # nothing, and only where the host reads a note for the page, as the card offers it
    html.insert(1, '<div class="launcher-row apponly"><label class="launcher-choice"><input type="checkbox" data-launcher="preview"> '
                   '%s<span>Preview</span></label></div>' % GLASS)
    if agent is not None:
        at = next(i for i, h in enumerate(html) if 'data-launcher="cmux"' in h) + 1
        html.insert(at, '<div class="launcher-row apponly" id="desk-agent-row"><label class="launcher-choice" for="desk-agent">'
                        '<span>A cmux tab starts<small>Saved in System/desk.json</small></span></label>'
                        '<select id="desk-agent" class="menu-style">%s</select></div>'
                        % "".join('<option value="%s"%s>%s</option>' % (k, " selected" if k == agent else "", label)
                                  for k, label in DESK_AGENTS))
    html = "".join(html)
    return ('<section class="setsec" id="launcher-settings">%s%s%s</section>'
            % (set_head("Opening a thread", "launchers", "Which apps a project or thread can open in, and what clicking a "
                        "thread&#39;s name does."), help_text("launchers", 'Tick what project and thread cards offer; Default is what '
               'clicking a thread&#39;s name does. A greyed row says why it cannot work here. Preview reads the note without opening '
               'anything. Saved as you change it.'),
               html))


def follow_settings() -> str:
    """Settings › Explore: whether the graph follows the zone you are reading
    on the Threads card (#142, FOLLOW_JS), on until switched off. Kept in this
    window, as the graph's other choices are, so it is not known when the page
    is built; only on a page with the graph. Explore's colours are no switch
    here: every place takes its kinds' colours (#292)."""
    row = '<div class="launcher-row"><label class="launcher-choice"><input type="checkbox" id="%s"%s> <span>%s<small>%s</small></span></label></div>'
    return ('<section class="setsec" id="follow-settings">%s%s%s</section>'
            % (set_head("Explore", "explore", "Whether the graph follows the zone you are reading."),
               help_text("explore", 'Scroll the Threads card from one zone into the next and Explore '
               'switches to it once it has filled the window for a moment. With the zones side by side, point at a column or open a '
               'project or thread in it. The switch is for this page only: the zone you pick in Explore&#39;s drop-down still leads '
               'the card and is what the page opens on. Picking a wiki pauses it until the page reloads. Kept in this window.'),
               row % ("graph-follow", " checked", "Follow the zone in view", "Explore shows the zone you are reading on the Threads card")))


def preview_section(flags: Dict[str, bool]) -> str:
    """Settings › Preview features: each flag's name and whether it is on,
    what it does as the row's tooltip (#227), since it is switched in a file."""
    def chip(k: str, on: bool) -> str:
        return "on" if on else "off"
    rows = "".join('<div class="flagrow" title="%s"><b>%s</b><span class="chip%s">%s</span></div>'
                   % (E(FLAGS[k][1]), E(FLAGS[k][0]), " on" if on else "", chip(k, on)) for k, on in flags.items())
    return ('<section class="setsec" id="preview-settings">%s%s%s</section>'
            % (set_head("Preview features", "preview", "Off until you switch them on in a file."), rows,
               help_text("preview", 'In Garrick&#39;s source but not yet released, so they may still change. Switch one on in '
               '<code>System/garrick-flags.json</code>, for example <code>{"effort": true}</code>, and rebuild the page. '
               'Point at a feature for what it does.')))


# The foot of Settings, under the last section: the cards hidden in this
# window, when there are any, then Reset view, its explanation as its tooltip
# and behind its "?".
VIEW_HELP = "Cards dragged or hidden, folds, the graph's view and the open tab are remembered in this window only."
VIEW = ('<div class="setfoot"><div class="setrule"><div class="hiddencards" id="hidden-cards" hidden></div><div class="gacts">'
        '<button class="act" type="button" id="reset-view" title="%s">Reset view</button>%s</div>%s</div></div>'
        % (E(VIEW_HELP + " Reset view puts every card back in place and shown, in the order this Garrick builds, "
                         "folds, graph and filter as built."),
           help_button("Reset view", "view"), help_text("view", E(VIEW_HELP))))


# Settings is one column of sections, read in order and grouped by what
# people come for (#205), with the list of them beside it: a click there
# brings a section into view, and the one being read is marked as the column
# scrolls (JS). Each section is filed under a group's key in settings().
SET_GROUPS = (("look", "How Garrick looks and opens things"), ("tell", "What it tells you"),
              ("keep", "How it keeps older material"), ("walls", "Walls"), ("about", "About Garrick"))
SET_SECTION = re.compile(r'<section class="setsec[^"]*" id="([^"]+)"[^>]*><h3>([^<]+)<')


def settings_nav(groups: List[Tuple[str, str, List[str]]]) -> str:
    """The list of Settings' sections, by group, each a link named as the
    section's heading. A section a host hides (.apponly in a browser, Menu
    bar until the app answers) is taken out of the list by JS when Settings
    opens, and a group with none left goes with it."""
    out = ""
    for key, title, secs in groups:
        items = "".join('<li><a href="#%s" data-setgo="%s">%s</a></li>' % (m.group(1), m.group(1), m.group(2))
                        for m in (SET_SECTION.match(h) for h in secs) if m)
        if items:
            out += ('<div class="setnavgrp"><p class="setnavh" id="sn-%s">%s</p><ul aria-labelledby="sn-%s">%s</ul></div>'
                    % (key, E(title), key, items))
    return '<nav class="setnav" aria-label="Settings sections">%s</nav>' % out


def settings(ws: Path, installed: Tuple[str, ...] = (), zones: Tuple[str, ...] = (),
             styles: Optional[Dict[str, dict]] = None, graph: bool = False,
             link: Optional["Links"] = None,
             kinds: Optional[List[Tuple[str, str, str]]] = None, kind_styles: Optional[Dict[str, str]] = None,
             allowed: Optional[List[dict]] = None) -> str:
    """The Settings dialog: which apps to open
    projects in, whether Explore follows the zone in view (with the graph),
    each zone's colour and icon, the colour of each kind of note Explore
    draws (`kinds`, with the graph), the menu bar; which notices
    this Mac shows; how older material fades (`link` opens the full list);
    About Garrick, and the preview features with which are switched on;
    Reset view at the foot. Each section shows its choices and one line at
    most saying what they are for; how a feature works is behind its "?"
    and in docs/extras/status-page.md (#227)."""
    agent = desk_agent(ws) if "cmux" in installed and CMUXLIB.is_file() else None
    filed = {"look": [launcher_choices(installed, agent=agent),
                      follow_settings() if graph else "", zone_settings(list(zones), styles or {}),
                      graph_colour_settings(kinds or [], kind_styles or {}) if graph else "", menu_settings()],
             "tell": [notify_settings(ws, CMUXLIB.is_file())],
             "keep": [memory_settings(ws, link)],
             "walls": [allowed_settings(allowed or [])],
             "about": [about_garrick(release_number(ws), ws), preview_section(preview_flags(ws))]}
    groups = [(key, title, [h for h in filed[key] if h]) for key, title in SET_GROUPS]
    main = "".join('<div class="setgroup" role="group" aria-labelledby="sg-%s"><p class="setgrp" id="sg-%s">%s</p>%s</div>'
                   % (key, key, E(title), "".join(secs)) for key, title, secs in groups if secs)
    return ('<dialog id="settings" class="settings" aria-labelledby="settings-title"><div class="sethead">'
            '<button class="sclose" type="button" id="close-settings" title="Close" aria-label="Close Settings">&#215;</button>'
            '<h2 id="settings-title" tabindex="-1" autofocus>Settings</h2></div><div class="setbody">%s'
            '<div class="setmain" id="settings-main">%s%s</div></div></dialog>' % (settings_nav(groups), main, VIEW))


# Explore's Preview (#219, NOTE_JS) is switched on and off beside them, in the
# same section and the same saved choice, though it opens nothing: it reads the
# note over the graph. It is never what clicking a thread does.
LAUNCH_KEYS = ("note", "preview") + tuple(k for k, _, _, _ in LAUNCHERS)


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
    default = data.get("default") if data.get("default") in LAUNCH_KEYS and data.get("default") != "preview" else "note"
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
            '.zrow,.gkrow{display:flex;align-items:center;gap:8px;padding:3px 0}.zrow .zprev,.gkrow .zprev{flex:1;min-width:0;font-size:13px;font-weight:560;'
            'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gkrow .zprev .zsw{display:inline-block;vertical-align:-.15em;margin-right:.5em}\n'
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


def swatch_pick(kind: str, label: str, owner: str, chosen: Optional[str], names, none_label: str, none_face: str, draw) -> str:
    """A button that shows the choice, over a palette that shows every one:
    a select's list cannot draw a colour or an icon. The select stays,
    hidden, as what the row reads and saves. `draw` draws one of `names`;
    the first cell, drawn as `none_face` and said as `none_label`, takes the
    choice away. Settings › Zones and Settings › Graph colours share it."""
    said = lambda n: n[:1].upper() + n[1:]
    options = '<option value="">%s</option>' % E(none_label) + "".join(
        '<option value="%s"%s>%s</option>' % (E(n), " selected" if n == chosen else "", E(said(n))) for n in names)
    face = (draw(chosen) if chosen else none_face) + '<span>%s</span>' % E(said(chosen) if chosen else none_label)
    cells = '<button type="button" class="zcell" data-v="" title="%s">%s</button>' % (E(none_label), none_face) + "".join(
        '<button type="button" class="zcell" data-v="%s" title="%s">%s</button>' % (E(n), E(said(n)), draw(n)) for n in names)
    return ('<span class="zpick"><select class="z%s" hidden aria-hidden="true" tabindex="-1">%s</select>'
            '<button type="button" class="zbtn" aria-haspopup="true" aria-expanded="false" aria-label="%s for %s">%s</button>'
            '<span class="zpop zp-%s" hidden role="group" aria-label="%s for %s">%s</span></span>'
            % (kind, options, label, E(owner), face, kind, label, E(owner), cells))


def zone_settings(zones: List[str], styles: Dict[str, dict]) -> str:
    """Settings › Zones: a row per zone, its name drawn as chosen, a colour
    and an icon. In the app only: what is chosen is saved for every viewer,
    and for the cmux desk, through page_action.py when Settings closes."""
    if not zones:
        return ""
    def pick(kind, zone, chosen):
        if kind == "col":
            return swatch_pick("col", "Colour", zone, chosen, ZONE_COLOURS, "No colour", zone_swatch(""), zone_swatch)
        return swatch_pick("ico", "Icon", zone, chosen, ZONE_ICONS, "No icon", '<i class="znone"></i>', zone_icon)
    rows = "".join('<div class="zrow" data-zone="%s"><span class="zprev%s">%s</span>%s%s</div>'
                   % (E(z), zone_class(z, styles), zone_name(z, styles),
                      pick("col", z, styles.get(z, {}).get("color")), pick("ico", z, styles.get(z, {}).get("icon")))
                   for z in zones)
    return ('<section class="setsec apponly" id="zone-settings">%s%s%s<script type="application/json" id="zone-icons">%s</script></section>'
            % (set_head("Zones", "zones", "A colour and an icon for each zone, so you can tell them apart at a glance."),
               help_text("zones", 'A colour and an icon for each zone, '
               'shown wherever the page names it. With the cmux extra, a tab the desk opens takes its zone&#39;s colour too. '
               'Saved for every viewer when you close Settings, in <code>%s</code>, which is committed with your '
               'workspace.' % E(prefs().FILE)), rows, script_json({k: zone_icon(k) for k in ZONE_ICONS})))


# Settings › Graph colours (#291): a colour for each kind of note Explore
# draws, from the zones' sixteen less the three that read as the graph's ring
# for a late next action (--critical) and the page's warnings, so no kind
# looks like one; KINDS keeps clear of them for the same reason. Saved beside the zones, in the workspace's own
# settings file: {"graph": {"project": "Teal", "thread": "Indigo"}}. A kind
# left out keeps its shipped colour (KINDS, PAGE_COLOURS); a chosen one is
# drawn in its light ink in the light theme and its dark ink in the dark.
GRAPH_OFF = ("Red", "Crimson", "Amber")
GRAPH_COLOURS = tuple(k for k in ZONE_COLOURS if k not in GRAPH_OFF)


def graph_styles(ws: Path) -> Dict[str, str]:
    """Settings › Graph colours as saved: {kind: one of GRAPH_COLOURS}. A
    colour is matched whatever its case; one the graph does not offer, or a
    value that is not a name, is dropped, and its kind keeps its default."""
    given = prefs().read(ws).get("graph")
    if not isinstance(given, dict):
        return {}
    named = {k.lower(): k for k in GRAPH_COLOURS}
    return {k: named[c.lower()] for k, c in given.items()
            if isinstance(k, str) and isinstance(c, str) and c.lower() in named}


def graph_colours(keys: List[str], shipped: List[str], chosen: Dict[str, str]) -> List[str]:
    """Each kind's colour as the page draws it: a chosen colour as the page's
    variable for it (zone_css()), which holds a shade for each theme, else
    the kind's shipped colour. The canvas reads the variable (GRAPH_JS)."""
    return ["var(--zc-%s)" % chosen[k].lower() if k in chosen else c for k, c in zip(keys, shipped)]


def graph_colour_settings(kinds: List[Tuple[str, str, str]], chosen: Dict[str, str]) -> str:
    """Settings › Graph colours (#291): a row for each kind the legend can
    show, (key, as the legend says it, shipped colour), its dot drawn as
    chosen, and the palette Settings › Zones uses, Default first; Reset
    colours puts every kind back. In the app only: what is chosen is saved
    for every viewer, through page_action.py, when Settings closes. Only on
    a page with the graph."""
    if not kinds:
        return ""
    dot = lambda colour: '<i class="zsw" style="background:%s"></i>' % E(colour)
    rows = "".join('<div class="gkrow" data-kind="%s" data-def="%s"><span class="zprev">%s%s</span>%s</div>'
                   % (E(k), E(c), dot(graph_colours([k], [c], chosen)[0]), E(said),
                      swatch_pick("col", "Colour", said, chosen.get(k), GRAPH_COLOURS, "Default", dot(c), zone_swatch))
                   for k, said, c in kinds)
    return ('<section class="setsec apponly" id="graph-colour-settings">%s%s%s<div class="gacts">'
            '<button class="act" type="button" id="graph-reset">Reset colours</button></div></section>'
            % (set_head("Graph colours", "graphcol", "A colour for each kind of note in Explore."),
               help_text("graphcol", 'Each kind of note in Explore&#39;s legend takes the colour chosen here, in its legend dot '
               'and on the graph, with a shade for the light theme and one for the dark. <em>Default</em> keeps the colour Garrick '
               'ships. Red, Crimson and Amber are not offered, since the rings for a late next action use them. Saved for every '
               'viewer when you close Settings, in <code>%s</code>, which is committed with your workspace.' % E(prefs().FILE)),
               rows))


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


def notify_settings(ws: Path, desk: bool = False) -> str:
    """Settings › Notifications (#110, #227): notices go to this Mac and
    nowhere else, so the section is the six notices you can be told of,
    each on or off, the minutes a long task takes, and quiet hours, with
    what they do in one sentence. A session in cmux gets its notice on its
    own tab, with no switch for it. In the app only: what is chosen goes to
    page_action.py when Settings closes (NOTIFY_JS). `desk` says the cmux
    extra is here, whose Desk replies also get through at night. A job
    whose plist sets GARRICK_NOTIFY or GARRICK_NOTIFY_CMD sends its own way,
    which the explanation behind the "?" says, rather than a line of state."""
    lib = notify_lib(ws)
    if lib is None or not hasattr(lib, "TELL"):
        return ""
    cfg = lib.settings(ws)
    def box(attr, on, label=""):
        return '<input type="checkbox" %s%s%s>' % (attr, " checked" if on else "", ' aria-label="%s"' % E(label) if label else "")
    after = ('<input type="number" id="n-after" min="0" max="%d" value="%d" aria-label="Minutes a task must run">'
             % (lib.AFTER_MAX, cfg["after"]))
    words = {"finished": 'a long task finishes, <span class="nsafter">after %s min</span>' % after}
    tell = "".join('<label>%s <span>%s</span></label>' % (box('data-nt="%s"' % e, cfg["tell"][e], label if e == "finished" else ""),
                                                          words.get(e, E(label)))
                   for e, label in lib.TELL)
    q = cfg["quiet"]
    rule = "At night only &#8220;a session needs me&#8221;%s get%s through." % ((" and the desk", "") if desk else ("", "s"))
    help_html = ('A notice names the zone or thread and what happened, never what a note or a meeting says. In cmux it lands on '
                 'the session&#39;s own tab. &#8220;A session needs me&#8221; and &#8220;a long task finishes&#8221; need hooks in '
                 'Claude Code or Codex: ask your assistant to set up notifications. With every choice off, Garrick sends nothing. '
                 'A scheduled job whose launchd plist sets GARRICK_NOTIFY or GARRICK_NOTIFY_CMD sends its notices its own way. '
                 'Saved in <code>%s</code> when you close Settings.' % E(prefs().FILE))
    return ('<section class="setsec apponly" id="notify-settings">%s%s<div class="nsimple"><div class="nsrow">'
            '<span class="nslab">Tell me when</span><span class="nsopts nscol">%s</span></div>'
            '<div class="nsrow nsq"><label>%s Quiet from</label><input type="time" id="n-from" value="%s" aria-label="Quiet from">'
            '<span>to</span><input type="time" id="n-to" value="%s" aria-label="Quiet until"></div><p class="hint nsrule">%s</p>'
            '</div><p class="hint" id="n-said" role="status" hidden></p></section>'
            % (set_head("Notifications", "notify", "Notices appear on this Mac."), help_text("notify", help_html),
               tell, box('id="n-quiet"', q["on"]), E(q["from"]), E(q["to"]), rule))


def script_json(data) -> str:
    """JSON safe inside a <script> element: with <, > and & written as escapes,
    no title can close the element or open a comment in it."""
    return (json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def rebuild_command(ws: Path, show_graph: bool = True, out: Optional[Path] = None,
                    flags: Tuple[str, ...] = ()) -> str:
    """The command that builds this page again, with the flags it was built
    with, absolute and quoted so it runs from any folder."""
    words = ["python3", str(Path(__file__).resolve()), "--workspace", str(ws)]
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


def card(id_: str, title: str, meta: str, body: str, open_: bool = True, fixed: bool = False, chip: str = "") -> str:
    """A folding card. Unless fixed, its header has a grip to drag it elsewhere
    and a button to hide it; the browser remembers both."""
    tools = "" if fixed else ('<span class="tools"><span class="grip" draggable="true" title="Drag to move" aria-hidden="true">%s</span>'
                              '<button class="totab" type="button" title="Move to…" aria-label="Move %s to another tab" aria-haspopup="menu">%s</button>'
                              '<button class="hide" type="button" title="Hide this card" aria-label="Hide %s">%s</button></span>'
                              % (GRIP, E(title), MOVE, E(title), CLOSE))
    return ('<details class="card" id="%s"%s><summary class="head">%s<h2>%s</h2>%s<span class="meta">%s</span>%s</summary>'
            '<div class="body">%s</div></details>' % (id_, " open" if open_ else "", CHEV, E(title), chip, E(meta), tools, body))


REPO_LIST_CAP = 30   # paths shown per kind; the count above stays exact


def repo_changes(ws: Path, r: dict) -> str:
    """One repository's changed files, by kind, to read and nothing more. No
    button commits them: another session may be halfway through that work.
    The docs say so once, rather than every repository with changes (#232)."""
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
    return ('<details class="notes changes"><summary>%s: %s</summary>%s<div class="gacts">%s</div></details>'
            % (E(r["name"]), E(say_files(r["dirty"])), "".join(groups), button))


def meter(value: float, cap: float, label: str, right: str, tip: str = "") -> str:
    pct = 0 if not cap else min(100.0, value / cap * 100)
    kind = "critical" if pct >= 90 else "warning" if pct >= 70 else ""
    return ('<div class="m"%s><span class="ink2">%s</span><span class="num">%s</span><div class="meter %s"><i style="width:%.1f%%"></i></div></div>'
            % (' data-tip="%s"' % E(tip) if tip else "", E(label), E(right), kind, pct))


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
# recently touched first. Todo and the inboxes sit beside it, and the
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


def age_said(days, what: str) -> str:
    """The title of a Threads row's day figure, which the card's legend used
    to explain (#228): how long since the note moved, and that it marks
    nothing."""
    if days is None:
        return "No date on %s" % what
    return "%d day%s since %s moved: a figure, not a fault" % (days, "" if days == 1 else "s", what)


def row_id(r: dict, scope: str = "") -> str:
    """A row's own name for the lists its chips open, the same on every build,
    so a list left open stays open across the rebuild a tick brings. A card
    that draws a thread's chip again (Your work) gives its own `scope`, so
    the page never holds two lists under one id."""
    return hashlib.sha1(("%s%s/%s" % (scope, r["zone"], r["rel"])).encode("utf-8")).hexdigest()[:10]


def todo_chip(r: dict, today: dt.date, scope: str = "") -> str:
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
            % ("late" if late else "ok", row_id(r, scope), E(tip + ". Click to list them"), n))


def todo_pop(r: dict, today: dt.date, actions: bool, scope: str = "") -> str:
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
            % (row_id(r, scope), head, "".join(todo_row(dict(a, label=None, unsure=False), today, actions, said_late=True)
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
    """A workspace with no projects: the one request that makes the first one."""
    ask = "help me prepare my next supplier call"
    return card("start", "Start here", "nothing is set up yet, and nothing needs to be",
                '<p>Ask your assistant for the thing you actually need, in your own words. There is no tag, zone or '
                'thread to learn first.</p><p class="hsay">“%s”</p><div class="hacts">%s</div>'
                '<p class="hint">Your next step is that one request. Your assistant asks you one question, then sets up '
                'your first project and saves the brief in it. Your work then lists here, with what to do next.</p>'
                % (E(ask), copy("Copy the request", ask, "Copied the request. Paste it to your assistant.")))


HOME_CSS = r"""
.chip.late{color:var(--critical);border-color:color-mix(in srgb,var(--critical) 45%,transparent)}
.hacts{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
.hsay{font-family:var(--sans);font-size:17px;margin:12px 0}
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


# The example's manifest in its zone, as garrick_lib.EXAMPLE_MANIFEST names it:
# a zone is the example only with one that names it, as System/tools/example.py
# reads it (present()), never by its name alone.
EXAMPLE_MANIFEST = ".example.json"
NOBODY = {"", "nobody", "no one", "noone", "none", "nothing", "-", "—", "n/a", "no"}
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


# ---- the wikis' questions (#224, #542): what they may show is questions_panel.py's -------------
_QP = None


def questions_mod():
    """questions_panel.py, beside this file: what the wikis' questions may show,
    placed by the walls, the tab's button and the user's allowances."""
    global _QP
    if _QP is None:
        spec = importlib.util.spec_from_file_location("garrick_status_questions", str(Path(__file__).with_name("questions_panel.py")))
        _QP = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_QP)
    return _QP


def questions_data(ws: Path, C: Optional[dict], today: dt.date, link: "Links") -> Optional[dict]:
    """What the Context card asks of the wikis, or None: no tab. Any fault leaves it out
    rather than a page that shows what it could not place."""
    try:
        return questions_mod().build(ws, C, today, link)
    except Exception:
        return None


def allowed_data(ws: Path, link: "Links") -> list:
    """What the user allowed once, for the Context tab's Allowed by you; none on any fault."""
    try:
        return questions_mod().read_allowed(ws, link)
    except Exception:
        return []


# A Resume block's Next action ends with whose it is ("…; Robin's", "…; the
# assistant's"), which the home has no use for: every row there is the user's.
OWNER_TAIL = re.compile(r"[;,]\s*(?:the\s+)?[A-Z]?[\w.-]+(?:\s+[\w.-]+){0,2}[\u2019']s\s*\.?\s*$")


# The same owner said first: "Robin's: send the sheet", "The assistant's: …" (a possessive head, always taken), or
# "Robin: send the sheet" where Robin is a person or party the workspace knows. Any other label before a colon
# ("Note:", "Q3:", "Decide:") is the user's own text and stays.
OWNER_HEAD = re.compile(r"^\s*(?P<who>(?:[Tt]he\s+[\w.-]+|[A-Z][\w.-]*(?:\s+[A-Z][\w.-]*){0,2}))(?P<poss>[\u2019']s)?:\s+(?=\S)")


def known_owners(ctx: Optional[dict], me: str = "") -> set:
    """The names a bare "Name:" head may be: the people and parties of System/context.md (full name and first
    name), and the user's own name, lower case."""
    names = set()
    for person in (ctx or {}).get("people") or []:
        full = str(person.get("name") or "").strip()
        if full:
            names.update((full.casefold(), full.split()[0].casefold()))
    for party in ((ctx or {}).get("parties") or {}).values():
        full = str((party or {}).get("party") or "").strip()
        if full:
            names.add(full.casefold())
    if (me or "").strip():
        names.update((me.strip().casefold(), me.split()[0].casefold()))
    return names


def without_owner(text: Optional[str], owners: Optional[set] = None) -> Optional[str]:
    """A next action without the whose-it-is the Resume block adds, at its tail or at its head. A possessive
    head is always removed; a bare "Name:" only when Name is in `owners`."""
    if not text:
        return text
    said = OWNER_TAIL.sub("", text).rstrip() or text
    head = OWNER_HEAD.match(said)
    if head and (head.group("poss") or head.group("who").casefold() in (owners or set())):
        return said[head.end():].strip() or said
    return said


def waiting_on(text: str) -> Optional[str]:
    """Who a piece of work waits on, from its Waiting on row: None where the
    row says nobody, is empty, or is still the template's placeholder."""
    said = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", filled(text)).strip().rstrip(".")
    if said.casefold() in NOBODY or re.match(r"(?i)^(nobody|no one|none)\b", said):
        return None
    return said


_AS = None


def ask_scope_mod():
    """ask_scope.py, beside this file: its reading of the user's own name."""
    global _AS
    if _AS is None:
        spec = importlib.util.spec_from_file_location("garrick_status_ask_scope", str(Path(__file__).with_name("ask_scope.py")))
        _AS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_AS)
    return _AS


def waits_on_user(waiting: Optional[str], name: str) -> bool:
    """Whether a Waiting on row opens with the user (#343): their full name,
    their first name alone, "me", "you" or "the user", then the end of the
    text, a comma, a colon or a semicolon. `name` is what `## Me` opens with
    (ask_scope.user_name); with no name, nothing is the user's and every
    non-empty row stays a waiting one."""
    name = (name or "").strip()
    if not waiting or not name:          # a name of spaces only is no name
        return False
    return _user_form(waiting, name) is not None


def _user_form(waiting: str, name: str):
    """The match of the user's name (full, first, "me", "you", "the user") at the start of a Waiting on row,
    followed by the end, a comma, a colon, a semicolon or a possessive ('s, \u2019s); None when it is not theirs."""
    forms = [name, name.split()[0], "me", "you", "the user"]
    for f in forms:
        m = re.match(r"(?i)%s(?:\s*(?:$|[,:;])|['\u2019]s\b)" % re.escape(f), waiting)
        if m:
            return m
    return None


def user_ask(waiting: Optional[str], name: str) -> str:
    """What a row that waits on the user asks of them, after their name: "the agenda to the client" from "Alex: the
    agenda to the client", and the quoted words from "Alex's \"update Garrick\"" (#559). Empty when nothing follows."""
    name = (name or "").strip()
    m = _user_form(waiting or "", name) if waiting and name else None
    if not m:
        return ""
    rest = waiting[m.end():].strip(" \t,:;")
    rest = re.sub(r"^[\"\u201c\u2018']+|[\"\u201d\u2019']+$", "", rest).strip()
    return rest


def waiting_badge(waiting: str) -> str:
    """The first clause of a Waiting on row, for the badge (#342): the text
    before the first colon or semicolon. The whole row is the badge's title
    and the work's own page."""
    lead = re.match(r"\s*\*\*[^*]+\*\*", waiting)             # a colon inside bold is not the cut: the pair stays whole
    start = lead.end() if lead else 0
    clause = waiting[:start] + re.split(r"[:;]", waiting[start:], maxsplit=1)[0]
    if clause.count("**") % 2:                                  # an unpaired marker would be drawn as it is
        clause = clause.replace("**", "")
    return clause.strip() or waiting


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


def work_id(name: str, key: str) -> str:
    """The id of a piece of work's row: its name and its note's key, "<Zone>/<note from the zone>"."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return "pw-%s-%s" % (slug, hashlib.sha1(key.encode("utf-8")).hexdigest()[:6])


def works(ws: Path, T: Dict[str, dict], today: dt.date) -> List[dict]:
    """Every live piece of work, most recent first, for the Overview's Your work list.
    Read from what Garrick keeps already: the thread note's Resume here block
    (Next action, Waiting on), its `updated:` date and an unwrapped
    checkpoint's (`touched`), and the zone's Todo.md lines that open with its
    link (thread_actions(), run first)."""
    example = example_zone(ws)
    try:
        me = ask_scope_mod().user_name(ws)
    except Exception:
        me = ""
    owners = known_owners(workspace_context(ws), me)
    out = []
    for zone, data in T.items():
        for r in data["rows"]:
            read = r.get("read") or {}
            rows = read.get("rows") or {}
            nxt = filled(rows.get("Next action"))
            if not nxt and r.get("next"):
                nxt = r["next"]["text"]
            key = "%s/%s" % (zone, r["rel"])
            waiting = waiting_on(rows.get("Waiting on", ""))
            out.append({
                "id": work_id(work_name_for(r), key),
                "name": work_name_for(r), "zone": zone, "project": r["project"], "thread": r["thread"],
                "note": r["note"], "hub": r["hub"], "rel": r["rel"], "key": key,
                "example": zone == example, "next": without_owner(nxt, owners), "waiting": waiting,
                "mine": waits_on_user(waiting, me), "ask": user_ask(waiting, me), "moved": r.get("touched") or r.get("updated"),
                "actions": r.get("actions") or [], "row": r,         # the lines and the card the Threads card shows for this thread
            })
    out.sort(key=lambda w: (-(w["moved"] or dt.date.min).toordinal(), w["name"].casefold()))
    return out


def act_button(req: str, label: str, say: str, cls: str = "act", extra: str = "") -> str:
    """A button that asks page_action.py for `req`, a request already in JSON."""
    return '<button class="%s" type="button" data-act="%s" data-say="%s"%s>%s</button>' % (cls, E(req), E(say), extra, E(label))


# --------------------------------------------------------------------------- the page

CSS = r"""
:root{color-scheme:light;--display:"Baskervville","Libre Baskerville",Baskerville,"Baskerville Old Face",Georgia,serif;--sans:"Plus Jakarta Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
--page:#f4f2ed;--side:#ecebe6;--surface:#fbfaf7;--raise:#fff;--sunk:#efede7;--ink:#16150f;--ink2:#45443f;--muted:#6b6963;
--line:rgba(22,21,15,.10);--line2:rgba(22,21,15,.18);--grid:#e4e1d9;--base:#b9b5aa;--accent:#2f5fc4;--accent-ink:#fff;--track:#d3ddf3;--wash:rgba(47,95,196,.09);
--good:#1d7a3a;--good-wash:rgba(29,122,58,.10);--warning:#9a5b00;--warning-wash:rgba(196,128,10,.13);--critical:#b42f2f;--critical-wash:rgba(180,47,47,.10);--none:#e6e3dc;
--shadow:0 1px 2px rgba(22,21,15,.05),0 4px 16px rgba(22,21,15,.04);--mark-ink:#1e2833;--mark-blue:#3d73e0}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0f0f0e;--side:#141413;--surface:#1a1a19;--raise:#222120;--sunk:#141413;
--ink:#f3f1ec;--ink2:#cfccc4;--muted:#a29f97;--line:rgba(255,255,255,.09);--line2:rgba(255,255,255,.16);--grid:#2c2c2a;--base:#44443f;--accent:#7ea3ee;--accent-ink:#0f0f0e;--track:#1f3568;--wash:rgba(126,163,238,.13);
--good:#6fcf8a;--good-wash:rgba(111,207,138,.12);--warning:#e8a93a;--warning-wash:rgba(232,169,58,.13);--critical:#f08a8a;--critical-wash:rgba(240,138,138,.12);--none:#2a2a28;--shadow:none;--mark-ink:#f5f0e6;--mark-blue:#8eb1f5}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0f0f0e;--side:#141413;--surface:#1a1a19;--raise:#222120;--sunk:#141413;
--ink:#f3f1ec;--ink2:#cfccc4;--muted:#a29f97;--line:rgba(255,255,255,.09);--line2:rgba(255,255,255,.16);--grid:#2c2c2a;--base:#44443f;--accent:#7ea3ee;--accent-ink:#0f0f0e;--track:#1f3568;--wash:rgba(126,163,238,.13);
--good:#6fcf8a;--good-wash:rgba(111,207,138,.12);--warning:#e8a93a;--warning-wash:rgba(232,169,58,.13);--critical:#f08a8a;--critical-wash:rgba(240,138,138,.12);--none:#2a2a28;--shadow:none;--mark-ink:#f5f0e6;--mark-blue:#8eb1f5}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.55 var(--sans);-webkit-font-smoothing:antialiased}
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
.head{display:flex;align-items:center;gap:10px;padding:14px 16px}.head h2{font:700 16px/1.25 var(--sans);margin:0}
.head .meta{color:var(--muted);font-size:12px;margin-left:auto;text-align:right}
.chev{width:16px;height:16px;flex:none;color:var(--muted);transition:transform .15s}details[open]>summary .chev{transform:rotate(90deg)}
.body{padding:0 16px 16px}.muted{color:var(--muted)}.ink2{color:var(--ink2)}.num{font-variant-numeric:tabular-nums}
.row{display:grid;align-items:center;gap:12px;padding:8px 2px;border-top:1px solid var(--grid)}.rows>.row:first-child{border-top:0}
.jobs .row{grid-template-columns:18px minmax(0,1fr) 180px 86px 140px}.jobs .row .status{overflow:hidden;text-overflow:ellipsis}
.jgroup h3{margin:12px 0 2px;font-size:12px;font-weight:600;color:var(--muted)}.jgroup:first-child h3{margin-top:0}.jgroup>h3+.row{border-top:0}
.jname{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer;text-align:left}.jname:hover{color:var(--accent)}
.jobs .name small{overflow:hidden;text-overflow:ellipsis}.jobs .name small.about{color:var(--ink2)}
.jpanel{margin:0 0 8px 30px;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--raise);font-size:12.5px}
.jpanel p{margin:0 0 6px}.jpanel dl{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:0}.jpanel dt{color:var(--muted)}.jpanel dd{margin:0}
.jpanel h4{margin:8px 0 2px;font-size:12px;font-weight:600;color:var(--muted)}.jpanel ul{margin:0;padding-left:18px}
.jpanel pre{margin:0;max-height:240px;overflow:auto;font:12px/1.4 ui-monospace,Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.row>svg,.item>svg{width:16px;height:16px}
.name{font-weight:560;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.name small{display:block;font-weight:400;color:var(--muted);font-size:12px}
.strip{display:flex;gap:2px}.strip i{width:11px;height:18px;border-radius:3px;background:var(--none);flex:none}
.strip i.good{background:var(--good)}.strip i.warning{background:var(--warning)}.strip i.critical{background:var(--critical)}.strip i:hover,.strip i:focus{outline:2px solid var(--ink)}
.status{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--ink2);white-space:nowrap}.status svg{width:14px;height:14px;flex:none}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px;color:var(--muted);font-size:12px}.legend>span{display:inline-flex;align-items:center;gap:6px}.legend>span>i{flex:none}
.legend i{width:10px;height:10px;border-radius:2px;background:var(--none)}.legend i.good{background:var(--good)}.legend i.warning{background:var(--warning)}.legend i.critical{background:var(--critical)}
.attn{display:flex;flex-direction:column;gap:6px}.attn a{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:10px;background:var(--raise);border:1px solid var(--line)}
.attn a:hover{text-decoration:none;border-color:var(--base)}.attn svg{width:16px;height:16px;flex:none}
.attn .adrift{display:flex;align-items:center;gap:6px}.attn .adrift>a{flex:1;min-width:0}.attn .adrift>.act{flex:none}
.zones{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:0 22px}
.zone>summary{display:flex;align-items:baseline;gap:8px;padding:10px 0 8px}
.zone>summary h3{margin:0;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink2)}.zone>summary .meta{margin-left:auto;font-size:12px;color:var(--muted)}
.thread{display:grid;grid-template-columns:minmax(0,1fr) 80px 34px;align-items:center;gap:10px;padding:6px 0;border-top:1px solid var(--grid);font-size:13px}
.thread .t{min-width:0}.thread .t a{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.thread .t small{display:block;color:var(--muted);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip{display:inline-flex;align-items:center;font-size:12px;padding:0 6px;border-radius:999px;border:1px solid var(--line);color:var(--ink2);margin-left:4px}
.fresh{height:6px;border-radius:3px;background:var(--grid);position:relative}.fresh i{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:var(--good)}
.fresh.warning i{background:var(--warning)}.fresh.critical i{background:var(--critical)}.fresh.age i{background:var(--base)}
.group>summary{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;font-size:13px}.group>summary:hover{background:var(--wash)}
.group>summary .counts{margin-left:auto;display:flex;gap:6px}
.group ul{list-style:none;margin:2px 0 8px;padding:0 0 0 32px}.group li{display:flex;gap:8px;padding:5px 0;color:var(--ink2);font-size:12.5px;border-top:1px solid var(--grid)}
.group li:first-child{border-top:0}.group li svg{width:14px;height:14px;flex:none;margin-top:2px}
.group li .cline{flex:1 1 auto;min-width:0;overflow-wrap:anywhere}.group li .act{flex:none;align-self:flex-start;font-size:12px;padding:2px 8px}
.clean{display:flex;align-items:center;gap:8px;color:var(--ink2);padding:8px 2px}.clean svg{width:16px;height:16px}
.bullet{display:grid;grid-template-columns:110px minmax(0,1fr) 40px;align-items:center;gap:10px;font-size:12.5px;padding:5px 0}
.bar{position:relative;height:10px;background:var(--track);border-radius:3px}.bar i{position:absolute;left:0;top:0;bottom:0;background:var(--accent);border-radius:3px}
.tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.item{display:flex;align-items:center;gap:9px;padding:8px 10px;border-radius:10px;background:var(--raise);border:1px solid var(--line);min-width:0}
.meters{display:flex;flex-direction:column;gap:12px}.meters .m{display:grid;grid-template-columns:1fr auto;gap:4px 10px;font-size:12px}.meters .m .meter{grid-column:1/-1}
table{border-collapse:collapse;width:100%;font-size:12.5px}th{text-align:left;color:var(--muted);font-weight:500;font-size:12px;padding:6px;border-bottom:1px solid var(--grid)}
td{padding:6px;border-bottom:1px solid var(--grid)}tr:last-child td{border-bottom:0}th.r,td.r{text-align:right;font-variant-numeric:tabular-nums}.scroll{overflow-x:auto}
.thread{border-radius:6px;transition:background .1s}.thread:hover,.thread.on{background:var(--wash)}
.act{font:inherit;font-size:12px;font-weight:560;line-height:1;padding:5px 8px;border-radius:7px;border:1px solid var(--line);background:var(--raise);color:var(--ink2);white-space:nowrap;cursor:pointer}
.act:hover{color:var(--ink);border-color:var(--base)}.act.wide{display:block;width:100%;padding:8px;font-size:12px}
.parked>summary{display:flex;align-items:center;gap:6px;padding:8px 0 4px;font-size:12px;color:var(--muted)}.parked>summary .n{margin-left:auto}
.parked .chev{width:13px;height:13px}.parked .thread{opacity:.8}
.pchev{box-sizing:border-box;width:16px;border:0;background:none;padding:0 3px 0 0;margin:0;cursor:pointer;color:var(--muted);line-height:0;vertical-align:-2px}
.pchev .chev{width:13px;height:13px}.pchev[aria-expanded="true"] .chev{transform:rotate(90deg)}
/* a project with no chevron keeps its room, so every name starts in one column */
.tunit>.thread:not(.proj)>.t{padding-left:16px}
.thread:not(.proj)>.t{display:flex;flex-wrap:wrap;align-items:center;column-gap:6px}.thread:not(.proj)>.t>a{flex:0 1 auto;min-width:0;max-width:none}
.thread:not(.proj)>.t>.live{flex:none}.thread:not(.proj)>.t>.tchips{flex:none;display:inline-flex;align-items:center;gap:4px}
.thread:not(.proj)>.t>small{flex:0 0 100%;min-width:0}.tchips .chip{margin:0}
.thread .t .subn{font-size:12px}.thread.proj .t>a{display:inline}.thread.sub{padding-left:20px;border-top:1px dashed var(--grid);font-size:12.5px}
.gsum{margin:6px 0 0}
.onlybar{display:flex;justify-content:flex-end;margin:-4px 0 12px}
.phead{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.phead h4{margin:0;min-width:0}
.phead .pflip{flex:none;font-size:12px;padding:3px 8px}.gpop .phead{padding-right:30px}
.gzsel{font:inherit;font-size:12px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:5px 26px 5px 10px;
appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);
background-position:calc(100% - 13px) 50%,calc(100% - 9px) 50%;background-size:4px 4px;background-repeat:no-repeat;cursor:pointer}
.tabs{display:flex;gap:2px;margin:0 0 18px;border-bottom:1px solid var(--line)}
.tabs button{border:0;background:none;font:inherit;font-size:13.5px;font-weight:560;color:var(--ink2);padding:8px 12px 9px;border-bottom:2px solid transparent;margin-bottom:-1px;cursor:pointer;display:inline-flex;gap:7px;align-items:center}
.tabs button:hover{color:var(--ink)}.tabs button.on{color:var(--ink);border-bottom-color:var(--accent)}
.tabs .n{font-size:12px;color:var(--muted);font-weight:500;font-variant-numeric:tabular-nums}
.nohost .tacts{display:none}.nohost .tadd-open{display:none}
.tick{width:18px;height:18px;margin-top:1px;border-radius:5px;border:1.5px solid var(--base);background:var(--raise);cursor:pointer;padding:0;display:grid;place-items:center}
.tick:hover{border-color:var(--accent)}
.flagrow{display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:6px 0;border-top:1px solid var(--line);font-size:13px}
.flagrow{cursor:help}.chip.on{color:var(--good);border-color:var(--good)}
#toast{position:fixed;left:50%;bottom:calc(22px + var(--work-h,0px));transform:translateX(-50%);background:var(--ink);color:var(--surface);font-size:13px;padding:9px 14px;border-radius:10px;opacity:0;transition:opacity .15s;pointer-events:none;z-index:10;max-width:90vw}
@media (hover:none){.head .tools{opacity:1}}
#tip{position:fixed;pointer-events:none;z-index:9;background:var(--ink);color:var(--surface);font-size:12px;padding:6px 9px;border-radius:7px;max-width:280px;opacity:0}
.only [data-ok="1"]{display:none}
.only .rows:not(:has([data-ok="0"]))::after,.only .zone:not(:has([data-ok="0"]))::after,.only .tiles:not(:has([data-ok="0"]))::after{content:"Nothing wrong here.";display:block;color:var(--muted);font-size:12px;padding:8px 2px}
.slot{display:flex;flex-direction:column;gap:16px;min-width:0}.slot.full{grid-column:span 12}.slot .card{grid-column:auto}
.slot:not(:has(>.card:not([hidden]):not(.nowait))){display:none}
/* one column takes the width when the other is empty, except while a card is dragged: then both show, side by side */
body:not(.dragging) .grid:not(:has(.stack.right>.card:not([hidden]):not(.nowait))) .stack.left,body:not(.dragging) .grid:not(:has(.stack.left>.card:not([hidden]):not(.nowait))) .stack.right{grid-column:span 12}
.stack .zones{grid-template-columns:1fr}[hidden]{display:none!important}
.head .tools{display:flex;gap:2px;align-items:center;opacity:0;transition:opacity .12s;margin-left:2px}
.head:hover .tools,.head:focus-within .tools{opacity:1}
.moveto{position:absolute;z-index:30;min-width:150px;background:var(--surface);border:1px solid var(--line);border-radius:10px;box-shadow:var(--shadow);padding:4px;display:flex;flex-direction:column}
.moveto button{font:inherit;font-size:13px;color:var(--ink);background:none;border:0;border-radius:6px;padding:6px 10px;text-align:left;cursor:pointer}.moveto button:hover{background:var(--wash)}
.tabs .dot.tr,.unhide .dot.tr{display:inline-block;margin-left:6px;vertical-align:middle}
.grip,.hide,.totab{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;color:var(--muted);border:0;background:none;padding:0;cursor:pointer}
.grip{cursor:grab}.grip:hover,.hide:hover,.totab:hover{background:var(--wash);color:var(--ink)}.grip svg,.hide svg,.totab svg{width:14px;height:14px}
.dragging .slot{display:flex!important;min-height:64px;border-radius:14px;outline:2px dashed var(--grid);outline-offset:4px}
.ph{border:2px dashed var(--accent);border-radius:14px;background:var(--wash);flex:none}.card.lifted{display:none}
.hint{font-size:12px;color:var(--muted);margin:0}
.changes .hint{margin:6px 0 2px}.paths{margin:0;padding-left:18px;font-size:12px}.paths code{word-break:break-all}
.zt{display:flex;align-items:baseline;gap:8px;margin:8px 0 2px}.zt .act{margin-left:auto;align-self:center}a.act:hover{text-decoration:none}
.gwrap{position:relative;height:560px;border-radius:10px;background:var(--raise);border:1px solid var(--line);overflow:hidden}
.gwrap canvas{display:block;width:100%;height:100%;touch-action:none;cursor:grab}.gwrap canvas.drag{cursor:grabbing}.gwrap canvas.hot{cursor:pointer}
.gbar{position:absolute;left:10px;top:10px;right:10px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;pointer-events:none}
.gbar.gcorner{left:auto;top:auto;bottom:10px;justify-content:flex-end}.gbar>*{pointer-events:auto}
.gbar .gfind{font:inherit;font-size:12px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:5px 9px;width:150px;min-width:0}
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
.act[data-k=note]{--ic:var(--icon-note)}
.act[data-k=finder]{--ic:var(--icon-finder)}.act[data-k=cmux]{--ic:var(--icon-cmux)}.act[data-k=codex]{--ic:var(--icon-codex)}.act[data-k=claude]{--ic:var(--icon-claude)}
.appicons .gacts{align-items:center}
.appicons .act[data-k]{width:34px;height:34px;padding:0;font-size:0;color:transparent;border-color:transparent;border-radius:8px;background:transparent var(--ic) center/26px no-repeat}
.appicons .act[data-k][data-d]{background-color:color-mix(in srgb,var(--accent) 22%,transparent)}
.appicons .act[data-k]:hover{border-color:var(--base)}
.gpop .glinks{display:flex;flex-direction:column;margin-top:8px;border-top:1px solid var(--grid);padding-top:6px}
.gpop .glinks button{display:flex;align-items:center;gap:7px;text-align:left;border:0;background:none;color:var(--ink2);font:inherit;font-size:12.5px;padding:4px;border-radius:6px;cursor:pointer}
.gpop .glinks button:hover{background:var(--wash);color:var(--ink)}.gpop .glinks i{width:8px;height:8px;border-radius:50%;flex:none}
.gpop .glinks span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gpop .glinks small{white-space:nowrap;font-size:12px}
.legend i.ring{background:none;border-radius:50%;border:2px solid}
.glegend>button{display:inline-flex;align-items:center;gap:6px;border:0;background:none;padding:0;font:inherit;color:inherit;cursor:pointer}.glegend>button>i{flex:none}
.glegend>button:hover{color:var(--ink)}.glegend>button[aria-pressed="false"]{opacity:.5}
.glegend>button[aria-pressed="false"]>i{background:none!important;border:1.5px solid var(--muted)}
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
.cols em{position:absolute;top:-16px;font-style:normal;font-size:12px;color:var(--ink2)}
.ticks{display:flex;gap:2px;font-size:12px;color:var(--muted);margin-top:4px}.ticks span{flex:1;text-align:center}
.act.armed{background:var(--critical);border-color:var(--critical);color:var(--accent-ink)}
@media (max-width:1180px){.top{grid-template-columns:repeat(2,minmax(0,1fr))}.hero{grid-column:span 2}.stack,.stack.left{grid-column:span 12}}
@media (max-width:820px){main{padding:16px}
.jobs .row{grid-template-columns:18px minmax(0,1fr) auto}.jobs .row>:nth-child(4){display:none}.jobs .row .strip{grid-column:2/-1;grid-row:2}.tiles{grid-template-columns:1fr}
.gwrap{height:440px}.gpop{left:10px;right:10px;top:auto;bottom:10px;width:auto;max-height:55%}}
"""

# The top row both pages share: the mark and name with how long ago the page was
# built (the date and time on hover), the tabs, and the controls, pinned while the
# page scrolls. Each page passes its own tabs and controls.
def bar(mark_svg: str, name: str, built: str, tabs: str, controls: str) -> str:
    return ('<header class="bar"><div class="brand">%s<div class="bname"><h1>%s</h1><p title="Built %s">Built <span id="age">just now</span></p></div></div>'
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
.bar h1{font:700 18px/1.1 var(--sans);margin:0;letter-spacing:-.01em;white-space:nowrap}
.bar .bname p{margin:2px 0 0;color:var(--muted);font-size:12px;white-space:nowrap}
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
dialog.settings .setsec{margin-top:26px}dialog.settings .setsec:first-of-type{margin-top:0}
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
.launcher-choice input{width:16px;height:16px;accent-color:var(--accent)}.lico{display:none}
.appicons .lico{display:inline-block;flex:none;width:20px;height:20px;margin-left:-4px;background:var(--ic) center/20px no-repeat}.appicons svg.lico{width:16px;height:16px;margin:0 2px 0 -2px;color:var(--ink2)}.launcher-choice small{display:block;font-size:12px;color:var(--muted)}
.launcher-choice input:disabled~span{color:var(--muted)}
.notes{margin-top:8px;border:1px solid var(--line);border-radius:10px;padding:6px 10px}.notes summary{cursor:pointer;font-size:13px;font-weight:600}
.notes div{max-height:240px;overflow:auto;font-size:12.5px;color:var(--ink2)}.notes h5{margin:10px 0 2px;font-size:12px}.notes ul{margin:4px 0;padding-left:18px}
.notes li{margin:3px 0}.notes p{margin:6px 0}.notes code{font-size:12px}
dialog.settings{max-height:calc(100vh - 48px);overflow:hidden}dialog.settings h2:focus{outline:none}
dialog.settings{background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:16px;max-width:1040px;width:calc(100% - 32px);padding:0;box-shadow:var(--shadow)}
dialog.settings::backdrop{background:rgba(0,0,0,.35)}dialog.settings h2{margin:0;font:700 20px/1.2 var(--sans)}
dialog.settings h3{display:flex;align-items:center;gap:6px;margin:0 0 4px;font-size:15px}
dialog.settings .setver{margin:0;font-size:13px;color:var(--ink2)}dialog.settings .hint{margin-top:12px}dialog.settings .hint a{color:var(--accent)}
dialog.settings .gacts{margin:8px 0 2px}
/* Settings (#205): a wide sheet, its head, then the list of sections beside one column of them that scrolls, its
   lines kept to a comfortable length; where the window is narrow the list is a strip across the top */
dialog.settings[open]{display:flex;flex-direction:column}
.sethead{flex:none;padding:16px 56px 12px 24px;border-bottom:1px solid var(--line)}
.setbody{flex:1 1 auto;min-height:0;display:grid;grid-template-columns:212px minmax(0,1fr)}
.setnav{position:relative;overflow:auto;padding:14px 12px 18px 16px;border-right:1px solid var(--line)}
.setnavgrp+.setnavgrp{margin-top:14px}.setnavh{margin:0 0 4px 8px;font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
.setnav ul{list-style:none;margin:0;padding:0}.setnav a{display:block;padding:5px 8px;border-radius:7px;font-size:13px;color:var(--ink2);text-decoration:none}
.setnav a:hover{background:var(--wash);color:var(--ink)}.setnav a:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.setnav a[aria-current]{background:var(--wash);color:var(--ink);font-weight:600;box-shadow:inset 2px 0 0 var(--accent)}
.setmain{position:relative;overflow:auto;overscroll-behavior:contain;padding:18px 32px 28px}.setmain>*{max-width:46rem}
.setgroup+.setgroup{margin-top:30px;padding-top:16px;border-top:1px solid var(--line)}
.setgrp{margin:0 0 12px;font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
dialog.settings .setlede{margin:0 0 8px;font-size:13px;line-height:1.45;color:var(--ink2)}
@media (max-width:759px){.setbody{grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(0,1fr)}
.setnav{display:flex;gap:4px;overflow-x:auto;overflow-y:hidden;padding:6px 12px;border-right:0;border-bottom:1px solid var(--line)}
.setnavgrp+.setnavgrp{margin-top:0}.setnavh{display:none}.setnav ul{display:flex;gap:2px}.setnav a{white-space:nowrap}
.setnav a[aria-current]{box-shadow:inset 0 -2px 0 var(--accent)}.setmain{padding:14px 16px 22px}.sethead{padding:14px 52px 10px 16px}}
/* a section's explanation, word for word, behind the "?" beside its heading; each row's own line always shows */
.qhelp{flex:none;width:17px;height:17px;padding:0;display:inline-flex;align-items:center;justify-content:center;font:inherit;font-size:12px;font-weight:600;line-height:1;color:var(--muted);background:none;border:1px solid var(--line);border-radius:50%;cursor:pointer}
.qhelp:hover,.qhelp[aria-expanded="true"]{color:var(--ink);border-color:var(--muted)}.qhelp:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
dialog.settings .sethelp{margin:2px 0 6px}
.setfoot{margin-top:30px}dialog.settings .setsec:focus{outline:none}.setrule{padding-top:10px;border-top:1px solid var(--line)}
dialog.settings .setfoot .gacts{align-items:center;margin:0}dialog.settings .hiddencards .gacts{margin:4px 0 0}.setfoot .hiddencards{margin:0 0 10px}
.setlinks{margin-top:8px;border-bottom:1px solid var(--line)}.setlink{display:block;padding:5px 2px;border-top:1px solid var(--line);color:var(--ink);text-decoration:none}
.setrel{margin:8px 0}.setrelrow{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;margin:6px 0}.setrelrow .hint{margin:0}
.setrelbox{margin:6px 0;padding:8px 10px;border:1px solid var(--line);border-radius:8px;font-size:13px}.setrelbox p{margin:3px 0}.setrelbox ul{margin:3px 0 3px 18px;padding:0}
.setrelbox a{color:var(--accent)}.wallstext{max-height:260px;overflow:auto;white-space:pre-wrap;font-size:12px;margin:6px 0}
.setlink:hover{background:var(--wash)}.setlink b{display:block;font-size:13px;font-weight:600}.setlink small{display:block;font-size:12px;color:var(--muted)}
/* Settings › Notifications: the six notices, the minutes a long task takes, and quiet hours */
#notify-settings [hidden]{display:none!important}
#notify-settings .nsimple{display:flex;flex-direction:column;gap:8px;margin:4px 0 6px;font-size:13px}
#notify-settings .nsrow{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px}
#notify-settings .nslab{flex:0 0 92px;font-weight:560;color:var(--ink2)}
#notify-settings .nsopts{display:flex;flex-wrap:wrap;align-items:center;gap:4px 14px;flex:1;min-width:0}
#notify-settings .nsopts.nscol{flex-direction:column;align-items:flex-start;gap:5px}
#notify-settings .nsimple label{display:inline-flex;align-items:center;gap:6px}
#notify-settings .nsimple input[type=checkbox]{accent-color:var(--accent)}
#notify-settings .nsafter{white-space:nowrap}#notify-settings .nsq{align-items:center;gap:6px}#notify-settings .nsrule{margin:-4px 0 0 24px;font-size:12px}
#notify-settings input[type=time],#notify-settings input[type=number]{font:inherit;font-size:12.5px;
color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:7px;padding:4px 7px}
#notify-settings input[type=number]{width:52px;padding:2px 5px}
#n-said{margin-top:8px}#n-said.bad{color:var(--critical,#C0392B)}
"""

# What a note's panel in the graph and a thread's card in the list both show,
# built in one place, so the two offer the same actions under the same labels.
# Each action opens a file or copies a phrase; none acts on the workspace.
# Inside Garrick.app (extras/status/app/), which answers to
# window.webkit.messageHandlers.garrick, a project or thread with a folder
# (`f`, there only where cmux is installed) also gets Open in cmux: a cmux tab
# in that folder, with the phrase that resumes it on the clipboard. There, the app takes
# the place of Copy "open X"; a browser, which can only copy, keeps it.
# Open in Claude on a thread (`oc`, its note) is the one launcher that acts
# (#180): where the build found Claude Code's command-line tool (the body's
# data-cli), it sends Continue's request, page_action.py's
# `continue`, and the working card says "Opening <thread> in Claude…" until
# the desktop app has opened on Claude's answer, or the refusal stays there in
# its own words. Without the tool, and for a project of several threads, it
# is the deep link, which leaves "open X" typed in for you to send.
PANEL_JS = r"""
/* Which apps a card offers and what clicking a thread's name does. In the
   app, the settings saved for every viewer (#launch-settings, written by
   page_action.py from what Settings sends) come first; a browser keeps its own. */
var GarrickPrefs=(function(){
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick,KEYS=['note','preview','finder','cmux','codex','claude'];
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
/* Open in Claude on a thread, where the build found Claude Code's CLI: Continue's request (#180) */
function cont(o){return o.oc&&document.body.dataset.cli?{verb:'continue',zone:o.oc[0],file:o.oc[1]}:null}
function going(o){return'Opening '+o.n+' in Claude…'}
/* What the page says the moment the button is pressed: that it is opening, never that it
   opened. The host says what opened, and only it can: a cold Claude is started and waited
   for, Codex and cmux say the clipboard now holds the phrase, Finder names the phrase it
   cannot take, and a failure says what is left to do. An app built before 0.28.0 says
   nothing back, and then this line is all there is. */
function launch(k,o,pl){var p=phrase(o),say=k==='finder'?'Showing '+o.n+' in Finder…':'Opening '+o.n+' in '+LABEL[k]+'…';
var l=pl?pl.l:k==='finder'?'Reveal in Finder':'Open in '+LABEL[k],txt=pl?(pl.i||'')+esc(pl.l)+(pl.t?TICK:''):l,mk=pl?' data-way="'+k+'"':' data-k="'+k+'"'+dmark(k,o),cls=pl?'act ymi':'act';
var q=k==='claude'&&cont(o);if(q)return'<button class="'+cls+'" type="button"'+mk+' title="'+l+'" aria-label="'+l+'" data-act="'+esc(JSON.stringify(q))+'" data-say="'+esc(going(o))+'">'+txt+'</button>';
if(k==='cmux'&&o.dk)return'<button class="'+cls+'" type="button"'+mk+' title="'+l+'" aria-label="'+l+'" data-act="'+desk(o,'open')+'"'
+(o.f?' data-expect="'+esc('live:'+o.f)+'"':'')+' data-say="'+esc('Opening '+o.n+' in cmux…')+'">'+txt+'</button>';
return'<button class="'+cls+'" type="button" data-launch="'+k+'"'+mk+' title="'+l+'" aria-label="'+l+'" data-folder="'+esc(o.f)+'" data-phrase="'+esc(p)+'" data-say="'+esc(say)+'">'+txt+'</button>'}
/* the cmux extra's desk: open a session for the thread, or close the project's */
function deskReq(o,v){var q={verb:v,zone:o.dk[0],project:o.dk[1]};if(o.dk[2])q.thread=o.dk[2];return q}
function desk(o,v){return esc(JSON.stringify(deskReq(o,v)))}
/* data-k names the app, so Garrick.app can draw the button as its icon, as its menu bar does; data-d marks the default */
function dmark(k,o){var d=GarrickPrefs.def();if(!d||!o.f||chosen().indexOf(d)<0)d='note';return k===d?' data-d':''}
function noteLink(o,pl){if(pl)return'<a class="act ymi" href="'+esc(o.u)+'" data-way="note" title="'+pl.l+'" aria-label="'+pl.l+'">'+(pl.i||'')+esc(pl.l)+(pl.t?TICK:'')+'</a>';
return'<a class="act" href="'+esc(o.u)+'" data-k="note"'+dmark('note',o)+' title="Open the note" aria-label="Open the note">Open</a>'}
function acts(o,pre){var a=(pre||'')+(prefs().note===false?'':noteLink(o));
if(o.f&&host)chosen().forEach(function(k){a+=launch(k,o)});
/* the phrase to copy only where nothing opens it: a browser, or a host with no app offered */
if(o.w&&!(o.f&&host&&chosen().length))a+=copy('open '+o.w);return'<div class="gacts">'+a+'</div>'}
/* One way to resume, for a row of Your work (#523, #559): a text button, Resume, which runs Settings' Default, and beside it a
   menu of labelled rows, each with a 16 px icon, the default ticked: the ways that are on and installed, then a divider and the
   folder and the note. One way on: Resume alone. The rows carry no data-k, so the app never draws them as its icons. */
var IC={cmux:'<path d="M3 4.5l3.5 3.5L3 11.5M8.5 12h4.5"/>',claude:'<path d="M8 2.5v11M2.5 8h11M4.2 4.2l7.6 7.6M11.8 4.2l-7.6 7.6"/>',codex:'<path d="M6 4L2.5 8 6 12M10 4l3.5 4L10 12"/>',finder:'<path d="M2 4.5h4l1.2 1.5H14v6.5H2z"/>',note:'<path d="M4 2.5h5.5L12 5v8.5H4zM9.5 2.5V5H12"/>'};
function ico(k){return'<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'+IC[k]+'</svg>'}
var TICK='<svg class="ytick" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5l3 3 6-7"/></svg>';
var RESUME={cmux:'Resume in cmux',claude:'Resume in Claude',codex:'Resume in Codex',finder:'Open folder',note:'Open the note'};
function opener(o){var ways=(prefs().note===false?[]:['note']).concat(o.f&&host?chosen():[]),d=GarrickPrefs.def();
if(!ways.length)ways=['note'];if(ways.indexOf(d)<0)d=ways[0];
function one(k,pl){return k==='note'?noteLink(o,pl):launch(k,o,pl)}
var main=one(d,{l:'Resume'});
if(ways.length<2)return'<span class="ysplit">'+main+'</span>';
function row(k){return one(k,{l:RESUME[k],i:ico(k),t:k===d}).replace(/^<(button|a) /,'<$1 role="menuitem" ')}
var apps=['cmux','claude','codex'].filter(function(k){return ways.indexOf(k)>=0}),rest=['finder','note'].filter(function(k){return ways.indexOf(k)>=0});
var items=apps.map(row).join('')+(apps.length&&rest.length?'<hr class="ydiv" role="separator">':'')+rest.map(row).join('');
return'<span class="ysplit">'+main+'<details class="ymore"><summary class="act" title="Other ways to resume" aria-label="Other ways to resume" aria-haspopup="menu">▾</summary><div class="ymenu" role="menu">'+items+'</div></details></span>'}
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
return{esc:esc,acts:acts,head:head,opener:opener}})();
"""

JS = r"""
(function(){var root=document.documentElement,st={get:function(k){try{return localStorage.getItem(k)}catch(e){return null}},set:function(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
function theme(t){if(t==='auto')root.removeAttribute('data-theme');else root.setAttribute('data-theme',t);document.querySelectorAll('.seg button').forEach(function(b){b.classList.toggle('on',b.dataset.t===t)});st.set('garrick-status-theme',t)}
theme(st.get('garrick-status-theme')||'auto');document.querySelectorAll('.seg button').forEach(function(b){b.onclick=function(){theme(b.dataset.t)}});
var only=document.getElementById('only');only.checked=st.get('garrick-status-only')==='1';function apply(){var t=document.getElementById('tab-status')||document.body;t.classList.toggle('only',only.checked);st.set('garrick-status-only',only.checked?'1':'0')}only.onchange=apply;apply();
document.querySelectorAll('details[id]').forEach(function(d){var s=st.get('garrick-fold-'+d.id);if(s==='0')d.open=false;if(s==='1')d.open=true;d.addEventListener('toggle',function(){st.set('garrick-fold-'+d.id,d.open?'1':'0')})});
var h=(Date.now()-new Date(document.body.dataset.built))/36e5,el=document.getElementById('age');if(el)el.textContent=h<1?Math.max(1,Math.round(h*60))+' min ago':h<48?Math.round(h)+' h ago':Math.round(h/24)+' days ago';
if(h>36){var s=document.getElementById('stale');s.style.display='block';s.textContent='';
var m=document.createElement('span');m.textContent='This page is '+Math.round(h)+' hours old, so what it shows may have changed. ';s.appendChild(m);
var rb=document.createElement('button');rb.type='button';rb.className='act';rb.textContent='Refresh';rb.onclick=function(){var c=document.getElementById('rebuild');if(c)c.click()};s.appendChild(rb);
var d=document.createElement('details');d.className='stdet';var sm=document.createElement('summary');sm.textContent='Details';d.appendChild(sm);
var dp=document.createElement('p');dp.textContent='Built '+document.body.dataset.built+'. Refresh rebuilds it in the Mac app; in a browser it copies the command to run status.py again.';d.appendChild(dp);s.appendChild(d)}
var tip=document.getElementById('tip');function show(e){var t=e.target.closest&&e.target.closest('[data-tip]');if(!t){tip.style.opacity=0;return}tip.textContent=t.dataset.tip;tip.style.opacity=1;
var r=t.getBoundingClientRect(),x=e.type==='focusin'?r.left+r.width/2:e.clientX,y=e.type==='focusin'?r.top:e.clientY,w=tip.offsetWidth;tip.style.left=Math.min(innerWidth-w-8,Math.max(8,x-w/2))+'px';tip.style.top=(y-tip.offsetHeight-12)+'px'}
document.addEventListener('mousemove',show);document.addEventListener('focusin',show);document.addEventListener('scroll',function(){tip.style.opacity=0},true);
var toast=document.getElementById('toast');function say(s){toast.textContent=s;toast.style.opacity=1;clearTimeout(say.t);say.t=setTimeout(function(){toast.style.opacity=0},2600)}
/* In Garrick.app the app copies, opens cmux and rebuilds; in a browser
   the page copies and nothing else. */
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
if(!host)document.body.classList.add('nohost');      /* a browser cannot act: its action buttons stay hidden */
/* Every link to a file goes to the host over its bridge (#318): the app shows the page with read access to its own
   folder only, so WebKit drops a navigation to any other file before the app sees it. A link to a project's hub or
   a thread's note carries its place (data-place), and the host opens it as the row of that project or thread opens;
   any other file the host opens as macOS does, a folder in Finder. Capture, so it is heard wherever the link sits;
   a handler that took the click first, such as a thread's name opening its default, keeps it. The attribute as
   written is read, never a.href, which resolves "#checks" against the page into a file link of its own. */
document.addEventListener('click',function(e){if(!host||e.defaultPrevented||e.button!==0)return;
var a=e.target.closest&&e.target.closest('a[href]');if(!a||!/^file:/i.test(a.getAttribute('href')||''))return;e.preventDefault();
host.postMessage({open:a.href,place:a.dataset.place||undefined})},true);
/* A drifted file's line in Needs attention (#323) leads to the row of its thread, or of its project where the thread
   has none on the card: on its tab, its folds open, scrolled to and with its card open, as a match found opens.
   Show both asks the host to reveal the copy here and the shared copy; only the app answers it. */
document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('.attn a[data-go]');if(!a)return;
var g;try{g=JSON.parse(a.dataset.go)}catch(x){return}var row=document.getElementById(g.row)||document.getElementById(g.up);if(!row)return;
e.preventDefault();e.stopPropagation();var sec=row.closest('section.tab');if(sec&&window.StatusTab)StatusTab(sec.id.slice(4));
for(var d=row.closest('details');d;d=d.parentNode&&d.parentNode.closest?d.parentNode.closest('details'):null)d.open=true;
var sub=row.closest('.subthreads');if(sub&&sub.hidden){var b=document.querySelector('.pchev[data-sub="'+sub.id+'"]');if(b)b.click();else sub.hidden=false}
row.scrollIntoView({block:'center'});var l=row.querySelector('.t>a');if(l)l.focus({preventScroll:true})},true);
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.attn [data-reveal]');if(!b||!host)return;
var q;try{q=JSON.parse(b.dataset.reveal)}catch(x){return}host.postMessage({reveal:q});say('Showing both copies in Finder…')});
function put(text){if(host){host.postMessage({copy:text});return Promise.resolve()}
if(navigator.clipboard&&window.isSecureContext){return navigator.clipboard.writeText(text)}var a=document.createElement('textarea');a.value=text;a.style.position='fixed';a.style.opacity=0;document.body.appendChild(a);a.select();try{document.execCommand('copy')}finally{document.body.removeChild(a)}return Promise.resolve()}
window.GarrickCopy=put;window.GarrickSay=say;      /* what HOME_JS copies the thought with, and says it in */
/* The assistant a request goes to, as the app's assistant() picks it for the menu's Process the Inbox: the
   default for clicking a thread when it is Claude, Codex or cmux, else the first of those switched on; none, null */
var ASKS={claude:'Claude',codex:'Codex',cmux:'cmux'};
window.GarrickAssistant=function(){var P=window.GarrickPrefs,on=P?P.launchers():{},d=P?P.def():'note';
var a=(document.body.dataset.launchers||'').split(',').filter(function(k){return ASKS[k]&&on[k]!==false});return a.indexOf(d)>=0?d:a[0]||null};
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
/* A button named for a request, Process the Inbox or Nurture Work (#234): in the app, to the assistant the menu's
   rows open, at the folder given, with the request typed in; in a browser, or with no assistant on, copied. */
var q=t.closest('button[data-request]');if(q){var a=host&&GarrickAssistant(),p=q.dataset.request;
if(a){host.postMessage({launch:a,folder:q.dataset.folder,phrase:p});say('Opening '+ASKS[a]+' on “'+p+'”…');return}
put(p).then(function(){say('Copied “'+p+'”. Paste it to your assistant.')},function(){say(p)});return}
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
window.StatusTab=function(n){if(n==='parties')n='questions';   /* an old link or a saved tab to the Parties view opens Context */
if(!document.getElementById('tab-'+n))n='overview';
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
var sdChanged=false,lpChanged=false,daChanged=false;sd.addEventListener('change',function(){sdChanged=true});
/* leaving Settings after a change rebuilds the page in the app, so what was chosen shows at once; a change
   to the apps or the zones is saved for every viewer first, through page_action.py, which rebuilds the page after it */
sd.addEventListener('close',function(){document.body.appendChild(toast);if(!sdChanged||!host)return;
/* Notifications that would be refused stay in the dialog, unsent, with the reason, rather than lost to a rebuild */
var N=window.GarrickNotify,bad=N&&N.changed()&&N.problem();if(bad){say(bad+' Nothing was saved yet.');return}
sdChanged=false;var q=sdReq();if(q)host.postMessage({act:q});else host.postMessage({rebuild:true})});
/* What Settings has to save, as one request: the apps, the zones, the graph's colours, the notifications,
   Memory, each only when it changed. null when there is nothing. */
function sdReq(){var N=window.GarrickNotify,n=!!(N&&N.changed()),M=window.GarrickMemory,m=!!(M&&M.changed()),R=window.GarrickRelease,rl=!!(R&&R.changed());
if(!(lpChanged||zChanged||gChanged||daChanged||n||m||rl))return null;
var q=lpChanged?GarrickPrefs.request():{verb:'settings'};if(zChanged)q.zones=zreq();if(gChanged)q.graph=greq();if(n)q.notifications=N.request();
if(daChanged){q['desk-agent']=document.getElementById('desk-agent').value;daChanged=false}
if(m){q.memory=M.request();M.saved()}
if(rl){var rq=R.request();q['release-notice']=rq.on;q['release-notice-every']=rq.every;R.saved()}
lpChanged=zChanged=gChanged=false;if(n)N.saved();return q}
sd.addEventListener('click',function(e){if(e.target!==sd)return;var r=sd.getBoundingClientRect();   /* the backdrop, not the padding */
if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)sdShut()});
/* Settings' list of sections (#205): a link brings its section to the top of the column and gives it the focus,
   and the section being read is marked aria-current as the column scrolls. A section the host hides (.apponly in a
   browser, Menu bar until the app answers) is taken out of the list, and a group with none left goes with it. */
var sm=document.getElementById('settings-main'),snav=sd.querySelector('.setnav'),snHold=null,snWait=0;
function snShown(s){return!!s&&!s.hidden&&getComputedStyle(s).display!=='none'}
function snMark(id){snav.querySelectorAll('a[data-setgo]').forEach(function(a){if(a.dataset.setgo!==id){a.removeAttribute('aria-current');return}
if(a.hasAttribute('aria-current'))return;a.setAttribute('aria-current','true');var n=snav;        /* kept in view, down the list or along the strip */
if(a.offsetTop<n.scrollTop||a.offsetTop+a.offsetHeight>n.scrollTop+n.clientHeight)n.scrollTop=a.offsetTop-12;
if(a.offsetLeft<n.scrollLeft||a.offsetLeft+a.offsetWidth>n.scrollLeft+n.clientWidth)n.scrollLeft=a.offsetLeft-12})}
function snSpy(){if(snHold){snMark(snHold);return}var secs=[].filter.call(sm.querySelectorAll('.setsec'),snShown),top=sm.getBoundingClientRect().top+48,cur=secs[0];if(!cur)return;
if(sm.scrollTop+sm.clientHeight>=sm.scrollHeight-2)cur=secs[secs.length-1];else secs.forEach(function(s){if(s.getBoundingClientRect().top<=top)cur=s});snMark(cur.id)}
function snSync(){snav.querySelectorAll('a[data-setgo]').forEach(function(a){a.parentNode.hidden=!snShown(document.getElementById(a.dataset.setgo))});
snav.querySelectorAll('.setnavgrp').forEach(function(g){g.hidden=!g.querySelector('li:not([hidden])')});
sm.querySelectorAll('.setgroup').forEach(function(g){g.hidden=![].some.call(g.querySelectorAll('.setsec'),snShown)});snSpy()}
sm.addEventListener('scroll',function(){if(!snWait)snWait=requestAnimationFrame(function(){snWait=0;snSpy()})},{passive:true});
['wheel','touchstart','pointerdown','keydown'].forEach(function(t){sm.addEventListener(t,function(){snHold=null},{passive:true})});
snav.addEventListener('click',function(e){var a=e.target.closest('a[data-setgo]'),s=a&&document.getElementById(a.dataset.setgo);if(!s)return;e.preventDefault();
snHold=s.id;sm.scrollTop=s.offsetTop-12;snMark(s.id);if(!s.hasAttribute('tabindex'))s.setAttribute('tabindex','-1');s.focus({preventScroll:true})});
window.StatusSettings={open:function(){if(sd.open)return;sd.appendChild(toast);sd.showModal();snHold=null;snSync()}};
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
say((c.checked?'Showing ':'Hiding ')+c.parentNode.querySelector('span').firstChild.textContent.trim()+'.');daRow()}});radios();
/* which assistant a cmux tab starts (#279): shown while Open in cmux is on, saved through the desk when Settings closes */
var daSel=document.getElementById('desk-agent');function daRow(){var r=document.getElementById('desk-agent-row'),c=sd.querySelector('input[data-launcher="cmux"]');
if(r)r.style.display=!c||c.disabled||!c.checked?'none':''}daRow();if(daSel)daSel.onchange=function(){daChanged=true;say('A cmux tab now starts '+daSel.options[daSel.selectedIndex].text+'.')};
/* Settings › Zones: each row draws its zone as chosen; every zone's choice goes with the request when Settings closes */
var zChanged=false,zIcons={};try{zIcons=JSON.parse(document.getElementById('zone-icons').textContent)}catch(e){}
function zpick(r,k){return r.querySelector(k).value}
sd.querySelectorAll('.zrow').forEach(function(r){r.querySelectorAll('select').forEach(function(s){s.onchange=function(){zChanged=true;
var c=zpick(r,'.zcol'),p=r.querySelector('.zprev');p.className='zprev'+(c?' zc zc-'+c.toLowerCase():'');p.innerHTML=zIcons[zpick(r,'.zico')]||'';
p.appendChild(document.createTextNode(r.dataset.zone))}})});
/* Each choice is a button over a palette: the palette sets the hidden select and runs its onchange */
function zface(b,s){var o=s.options[s.selectedIndex],c=[].filter.call(b.nextSibling.querySelectorAll('.zcell'),function(x){return x.dataset.v===s.value})[0];
b.innerHTML=(c?c.innerHTML:'')+'<span></span>';b.lastChild.textContent=o?o.textContent:''}
function zshut(except){sd.querySelectorAll('.zpop').forEach(function(p){if(p!==except&&!p.hidden){p.hidden=true;p.previousSibling.setAttribute('aria-expanded','false')}})}
sd.querySelectorAll('.zpick').forEach(function(k){var s=k.querySelector('select'),b=k.querySelector('.zbtn'),p=k.querySelector('.zpop');
function mark(){p.querySelectorAll('.zcell').forEach(function(c){c.classList.toggle('on',c.dataset.v===s.value)})}mark();
b.onclick=function(e){e.stopPropagation();zshut(p);p.hidden=!p.hidden;b.setAttribute('aria-expanded',String(!p.hidden));if(!p.hidden){mark();var on=p.querySelector('.zcell.on')||p.querySelector('.zcell');on.focus()}};
p.onclick=function(e){var c=e.target.closest('.zcell');if(!c)return;e.stopPropagation();if(s.value!==c.dataset.v){s.value=c.dataset.v;s.onchange();sdChanged=true}zface(b,s);mark();p.hidden=true;b.setAttribute('aria-expanded','false');b.focus()};
p.onkeydown=function(e){if(e.key==='Escape'){e.preventDefault();e.stopPropagation();p.hidden=true;b.setAttribute('aria-expanded','false');b.focus()}}});
sd.addEventListener('click',function(e){if(!e.target.closest('.zpick'))zshut(null)});
/* each "?" shows or hides its section's explanation where it stands */
sd.addEventListener('click',function(e){var q=e.target.closest('.qhelp'),p=q&&document.getElementById(q.getAttribute('aria-controls'));if(!p)return;
p.hidden=!p.hidden;q.setAttribute('aria-expanded',String(!p.hidden))});
function zreq(){var o={};sd.querySelectorAll('.zrow').forEach(function(r){var s={},c=zpick(r,'.zcol'),i=zpick(r,'.zico');if(c)s.color=c;if(i)s.icon=i;o[r.dataset.zone]=s});return o}
/* Settings › Graph colours (#291): each kind's dot drawn as chosen, Default its shipped colour; Reset colours puts every
   kind back. The whole section goes with the request when Settings closes, a kind on Default left out. */
var gChanged=false;function gdot(r){r.querySelector('.zprev .zsw').style.background=zpick(r,'.zcol')?'var(--zc-'+zpick(r,'.zcol').toLowerCase()+')':r.dataset.def}
sd.querySelectorAll('.gkrow').forEach(function(r){r.querySelector('.zcol').onchange=function(){gChanged=true;gdot(r)}});
var gReset=document.getElementById('graph-reset');if(gReset)gReset.onclick=function(){sd.querySelectorAll('.gkrow').forEach(function(r){var s=r.querySelector('.zcol');s.value='';gdot(r);zface(r.querySelector('.zbtn'),s)});
gChanged=sdChanged=true;say('Every kind of note back to its default colour.')};
function greq(){var o={};sd.querySelectorAll('.gkrow').forEach(function(r){var c=zpick(r,'.zcol');if(c)o[r.dataset.kind]=c});return o}
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


# Settings › Notifications (#110, #227), in the app: the six boxes, the
# minutes and quiet hours read into the shape notifications.py keeps, sent
# with what else Settings changed when it closes (JS's sdReq), where
# page_action.py checks them through notifications.py's clean().
NOTIFY_JS = r"""
(function(){var sec=document.getElementById('notify-settings');if(!sec)return;var changed=false;
function val(id){var e=document.getElementById(id);return e?e.value.trim():''}
function request(){var t={};sec.querySelectorAll('[data-nt]').forEach(function(c){t[c.dataset.nt]=c.checked});
var qt=document.getElementById('n-quiet');
return{tell:t,after:Math.max(0,Math.min(240,parseInt(val('n-after'),10)||0)),
quiet:{on:!!(qt&&qt.checked),from:val('n-from')||'22:00',to:val('n-to')||'07:00'}}}
/* what notifications.py's clean() would refuse, said before anything is sent */
function problem(){var r=request(),t=/^([01]\d|2[0-3]):([0-5]\d)$/;return t.test(r.quiet.from)&&t.test(r.quiet.to)?'':'Quiet hours are times such as 22:00.'}
sec.addEventListener('change',function(){changed=true});
sec.addEventListener('input',function(e){if(e.target.matches('input[type=number],input[type=time]'))changed=true});
window.GarrickNotify={changed:function(){return changed},request:request,problem:problem,saved:function(){changed=false}};
})();
"""


# ---- Settings › About Garrick: Check for updates (#410) ----------------------------
# The button asks page_action.py's `release-check`, which asks GitHub now: the click
# is the consent for that one request, not for the update (#557). A newer release
# is offered: the line says which, with a link to its notes, and two buttons.
# *Update now* posts `release-update`, with a progress line while it runs;
# *Not now* posts nothing and keeps nothing, so the next check or a reload offers
# it again. page_action.py refuses `release-update` unless the running release is older. The report is drawn from the reply's
# counts and lists with textContent, in the words the update itself uses. The
# switch and the cadence are read back by sdReq when Settings closes.
RELEASE_JS = r"""
(function(){var sec=document.getElementById('release-settings');if(!sec)return;
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick,btn=document.getElementById('rel-check'),
line=document.getElementById('rel-line'),box=document.getElementById('rel-detail'),on=document.getElementById('rel-on'),every=document.getElementById('rel-every'),
changed=false,busy=false;
function put(t){line.textContent=t}
function at(r){var d=r&&r.asked?new Date(r.asked):null;return d&&!isNaN(d)?' Asked at '+d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})+'.':''}
function add(tag,text,into){var e=document.createElement(tag);e.textContent=text;(into||box).appendChild(e);return e}
function items(head,list,said){if(!list||!list.length)return;add('p',head);var ul=add('ul','');list.forEach(function(x){add('li',said?said(x):x,ul)})}
function go(m){if(busy)return;busy=true;btn.disabled=true;box.hidden=true;put('Updating\u2026 this takes a minute.');host.postMessage({act:{verb:'release-update',held:m}})}
/* a Garrick file with changes not committed: nothing was applied, and the three answers are asked here */
function held(r){var p=add('p',r.line||'');items('These files, by repository:',r.uncommitted,function(x){return x.path+' ('+(x.repo==='.'?'the workspace':x.repo)+')'});
var row=add('p','');[['Commit these and update','commit'],['Update the rest','rest'],['Cancel','']].forEach(function(b){var e=document.createElement('button');e.type='button';e.textContent=b[0];
e.onclick=function(){if(b[1])go(b[1]);else{box.textContent='';box.hidden=true;put('Nothing was changed.')}};row.appendChild(e);row.appendChild(document.createTextNode(' '))})}
function show(r){box.textContent='';box.hidden=true;if(!r||r.state!=='updated'&&r.state!=='stopped'&&r.state!=='waits'&&r.state!=='held')return;box.hidden=false;
if(r.state==='held'){held(r);return}
var p=add('p',r.line||'');if(r.url){p.appendChild(document.createTextNode(' '));var a=document.createElement('a');a.href=r.url;a.target='_blank';a.rel='noopener';a.textContent='Release notes';p.appendChild(a)}
if(r.state==='updated')add('p',(r.replaced||0)+' file'+(r.replaced===1?'':'s')+' replaced, '+(r.added||0)+' added.');
if(r.state==='waits'&&r.text){var pre=add('pre','');pre.textContent=r.text;pre.className='wallstext'}
items('Written as .new beside the file you changed. Merge each, then remove the .new.',r.new,function(x){return x+'.new'});
if((r.new&&r.new.length)||(r.split&&r.split.length))add('p','Say \u201cmerge the update\u201d to your assistant.');
items('Instruction files you changed, left as they are (Split):',r.split);
items('Skipped:',r.skipped,function(x){return x[0]+': '+x[1]});
items('Left for you:',r.then);items('The check found:',r.problems)}
function done(){busy=false;btn.disabled=false}
/* a newer release: ask first. Nothing is posted until Update now is pressed; Not now changes and stores nothing */
function offer(r){box.textContent='';box.hidden=false;put(r.line+at(r));
if(r.url){var p=add('p','');var a=document.createElement('a');a.href=r.url;a.target='_blank';a.rel='noopener';a.textContent='Release notes';p.appendChild(a)}
var row=add('p','');[['Update now',1],['Not now',0]].forEach(function(b){var e=document.createElement('button');e.type='button';e.textContent=b[0];
e.onclick=function(){if(b[1]){if(busy)return;go()}else{box.textContent='';box.hidden=true;done()}};row.appendChild(e);row.appendChild(document.createTextNode(' '))});
busy=false;btn.disabled=false}
btn.onclick=function(){if(busy)return;if(!host){put('Only the Garrick app can ask GitHub.');return}busy=true;btn.disabled=true;box.hidden=true;put('Asking GitHub\u2026');
host.postMessage({act:{verb:'release-check'}})};
sec.addEventListener('change',function(e){if(e.target===on||e.target===every){changed=true;every.disabled=!on.checked}});
var prev=window.GarrickActed;window.GarrickActed=function(q,out){
if(q&&q.verb==='release-check'){var r=out&&out.release;if(!(out&&out.ok&&r)){put((out&&out.say)||'Could not ask GitHub. Nothing was changed.');done();return}
if(r.state==='newer'){offer(r);return}
put(r.line+at(r));done();return}
if(q&&q.verb==='release-update'){var u=out&&out.release;if(!(out&&out.ok&&u)){put((out&&out.say)||'The update could not start. Nothing was changed.');done();return}
put(u.line);show(u);done();return}
if(prev)return prev(q,out)};
window.GarrickRelease={changed:function(){return changed},request:function(){return{on:!!on.checked,every:parseInt(every.value,10)===7?7:1}},saved:function(){changed=false}};
})();
"""
# ---- end of Settings › About Garrick: Check for updates ------------------------------


# ---- Settings › Memory (#108) -----------------------------------------------------
# One block, kept apart from the rest of Settings: how pages fade out of the
# wikis' working memory, and what that would do now. System/tools/fade.py, the
# workspace's own, owns the keys, their defaults and the counting; this block
# draws what its settings() returns, kinds and all, and asks its counts() what
# the form would do, through page_action.py's `memory-preview`, which only
# reads, so a change can be judged before it is saved. Settings closing sends
# the form as `memory` with the rest (JS's sdReq asks window.GarrickMemory),
# and nothing moves until a pass is asked for. Without fade.py, or when it
# fails, the section is left out or says why, and the page builds as before.
_FADE: Dict[Path, object] = {}
MEMORY_WIKIS = ("Meetings", "Knowledge")
MEMORY_PINS = (("thread", "A live thread links it"), ("project", "A live project's notes link it"),
               ("todo", "An open action in a Todo list links it"), ("pinned", "Its frontmatter says pinned: true"))
MEMORY_MONTHS = (1, 240)          # what the form offers; fade.py and page_action.py have the last word
MEMORY_MIN = (1, 1000)


@contextlib.contextmanager
def tools_path(ws: Path):
    """The workspace's System/tools/ first on the path while fade.py is
    loaded or asked, as it would be run there; the path and the modules it
    imported put back after, so nothing of one workspace stays for another."""
    path, before = list(sys.path), set(sys.modules)
    sys.path.insert(0, str(ws / "System" / "tools"))
    try:
        yield
    finally:
        sys.path[:] = path
        for k in set(sys.modules) - before:
            sys.modules.pop(k, None)


def fade_lib(ws: Path):
    """The workspace's own System/tools/fade.py, loaded once per workspace,
    as nurture_lib() loads nurture.py; None when there is none, it does not
    load, or it lacks settings() and counts()."""
    if ws not in _FADE:
        lib, src = None, ws / "System" / "tools" / "fade.py"
        if src.is_file():
            name = "garrick_status_fade"
            try:
                with tools_path(ws):
                    spec = importlib.util.spec_from_file_location(name, str(src))
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[name] = mod             # its dataclasses look their module up by name
                    spec.loader.exec_module(mod)
                if callable(getattr(mod, "settings", None)) and callable(getattr(mod, "counts", None)):
                    lib = mod
            except Exception:
                lib = None
        _FADE[ws] = lib
    return _FADE[ws]


def memory_said(w: str, c: dict) -> str:
    """One wiki's line: "Meetings: 600 working · 17 dormant · next pass
    moves 5". MEMORY_JS says it the same way when the counts come back for
    unsaved values."""
    grades = "%s: %d working · %d dormant" % (w, c.get("working", 0), c.get("dormant", 0))
    if c.get("archived"):
        grades += " · %d archived" % c["archived"]
    if not c.get("on", True):
        return grades + " · off"
    moves = sum(c.get(k, 0) for k in ("to_dormant", "to_archive", "to_wake"))
    return grades + (" · next pass moves %d" % moves if moves else " · nothing to move")


def memory_list(values) -> str:
    return ", ".join(str(v) for v in values) if isinstance(values, list) else ""


def said_html(text: str) -> str:
    """A sentence fade.py words for the page, escaped, its `code` drawn as code."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", E(text))


def memory_settings(ws: Path, link: Optional["Links"] = None) -> str:
    """Settings › Manage older material, the Memory section (#108), cut to
    its choices (#227): one line saying what it does; per wiki, the switch
    that lets old pages fade, each of its kinds' months, and one line of
    counts, with a link to the full list the last review wrote (`link`).
    Under one closed Advanced: which pages each kind takes, what keeps a
    page working, bringing a page back, how far search reaches unasked, and
    the morning digest's line. How the grades, the steps and age work is
    behind the "?" and in the docs; how age is counted and what wakes a page
    are fade.py's own sentences (AGE_SAID, WAKE_SAID), shown as they are, so
    the page cannot promise what the code does not do. In the app only, as
    the other sections that save are."""
    lib = fade_lib(ws)
    if lib is None:
        return ""
    age = getattr(lib, "AGE_SAID", None)
    head = set_head("Manage older material", "memory", "Old meetings and reading leave the index after the months set here; "
                    "nothing is deleted, and nothing moves until you say &#8220;fade the meetings&#8221; or &#8220;fade the "
                    "library&#8221;.") + help_text("memory", (
        'A page older than its kind&#39;s months goes dormant: out of the index, still found when a search reaches back. Later '
        'it moves to the archive, found only when you ask. &#8220;What would fade&#8221; writes the full list; &#8220;fade the '
        'meetings&#8221; or &#8220;fade the library&#8221; moves exactly that list and keeps every link working. %s'
        'Saved in <code>%s</code> when you close Settings.' % (said_html(age) + " " if isinstance(age, str) else "", E(prefs().FILE))))
    try:
        with tools_path(ws):
            cfg = lib.settings(ws)
            grades = lib.counts(ws)
        wikis, kinds, pins = cfg["wikis"], cfg["kinds"], cfg["pins"]
    except Exception as e:
        return ('<section class="setsec apponly" id="memory-settings">%s<p class="hint">Memory cannot be set here: '
                '<code>System/tools/fade.py</code> did not give its settings (%s).</p></section>'
                % (head, E(type(e).__name__)))
    box = lambda attr, on, label: '<input type="checkbox" %s%s aria-label="%s">' % (attr, " checked" if on else "", E(label))
    num = lambda attr, value, low, high, label, off=False: (
        '<input type="number" %s min="%d" max="%d" value="%s" aria-label="%s"%s>'
        % (attr, low, high, E(str(value)), E(label), " disabled" if off else ""))

    def full_list(w):
        paths = getattr(lib, "proposal_paths", None)
        path = paths(ws, w)[0] if callable(paths) else ws / "System" / "generated" / "fade" / ("%s.md" % w)
        return (' <a class="mfull" href="%s">Full list</a>' % E(link(path))) if link is not None and path.is_file() else ""

    blocks, advanced = "", ""
    for w in MEMORY_WIKIS:
        kind_rows = ""
        for name, k in kinds.items():
            if k.get("wiki") != w:
                continue
            never = k.get("archived") is None
            dormant = k.get("dormant") if isinstance(k.get("dormant"), int) else 6
            kind_rows += (
                '<div class="mkind" data-mkind="%s" data-mwiki="%s"><span class="mkname">%s</span>'
                '<label>dormant after %s months</label><label>archived after %s</label><label class="mnever">%s never</label></div>'
                % (E(name), E(w), E(name[:1].upper() + name[1:]),
                   num('data-mk="dormant"', dormant, MEMORY_MONTHS[0], MEMORY_MONTHS[1], "%s: months to dormant" % name),
                   num('data-mk="archived"', dormant if never else k.get("archived"), MEMORY_MONTHS[0], MEMORY_MONTHS[1],
                       "%s: months to archived" % name, never),
                   box('data-mk="never"', never, "%s: never archived" % name)))
            advanced += ('<div class="mlists" data-mkl="%s"><b>%s</b>'
                         '<label class="mlist">Types <input type="text" data-mk="types" value="%s" placeholder="none" aria-label="%s types"></label>'
                         '<label class="mlist">Domains <input type="text" data-mk="domains" value="%s" placeholder="none" aria-label="%s domains"></label></div>'
                         % (E(name), E(name[:1].upper() + name[1:]), E(memory_list(k.get("types"))), E(name),
                            E(memory_list(k.get("domains"))), E(name)))
        blocks += ('<div class="mwiki" data-mw="%s"><div class="launcher-row"><label class="launcher-choice">%s <span>Let old %s pages fade'
                   '</span></label></div>%s%s</div>'
                   % (E(w), box('data-mwikion="%s"' % w, wikis.get(w, True) is not False, "%s pages fade" % w), E(w), kind_rows,
                      '<p class="mcount"><span data-mc="line">%s</span>%s</p>' % (E(memory_said(w, grades[w])), full_list(w))
                      if w in grades else ""))
    pin_rows = "".join('<label class="mpin">%s <span>%s</span></label>' % (box('data-mpin="%s"' % key, pins.get(key, True) is not False, said), E(said))
                       for key, said in MEMORY_PINS)
    wake = getattr(lib, "WAKE_SAID", None)
    nightly = cfg.get("nightly") or {}
    reach = cfg.get("reach", "dormant")
    return ('<section class="setsec apponly" id="memory-settings">%s<div class="mgrades" id="m-prev" aria-live="polite">%s</div>'
            '<p class="hint" id="m-prevsaid" hidden></p>'
            '<details class="madv"><summary>Advanced</summary>'
            '<h4 class="nsub">Which pages each kind takes</h4><p class="hint">Its <code>type</code> or domain, separated by commas.</p>%s'
            '<h4 class="nsub">What keeps a page working</h4><p class="hint mlede">While any of these holds, a page stays working, however '
            'old. Person, organisation and topic pages, and the wiki&#39;s own lists, never move.</p><div class="mpins">%s</div>'
            '<h4 class="nsub">Bringing a page back</h4>'
            '<div class="launcher-row"><label class="launcher-choice">%s <span>Propose bringing back a dormant page that active work links again'
            '<small>Off, only <code>pinned: true</code> brings a page back</small></span></label></div>%s'
            '<h4 class="nsub">Search and the morning digest</h4>'
            '<div class="launcher-row"><span class="mreach">Without being asked, search reads <select id="m-reach" aria-label="How far search reaches unasked">'
            '<option value="working"%s>working pages only</option><option value="dormant"%s>working and dormant pages</option></select></span></div>'
            '<div class="launcher-row"><label class="launcher-choice">%s <span>Say what would fade in the morning digest'
            '<small>Once at least this many pages would</small></span></label><span class="mafter">%s pages</span></div></details></section>'
            % (head, blocks, advanced, pin_rows,
               box('id="m-wake"', cfg.get("wake", True) is not False, "Propose bringing back a dormant page that active work links again"),
               '<p class="hint msaid">%s</p>' % said_html(wake) if isinstance(wake, str) else "",
               " selected" if reach == "working" else "", " selected" if reach != "working" else "",
               box('id="m-night"', nightly.get("on", True) is not False, "Say what would fade in the morning digest"),
               num('id="m-min"', nightly.get("min", 10), MEMORY_MIN[0], MEMORY_MIN[1], "Smallest count worth a line")))


MEMORY_CSS = r"""
/* Settings › Manage older material: per wiki its switch, its kinds' months and its count; the rest under Advanced */
#memory-settings input[type=number]{font:inherit;font-size:12.5px;width:56px;padding:2px 5px;color:var(--ink);background:var(--surface);
border:1px solid var(--line);border-radius:7px}#memory-settings input[type=number]:disabled{opacity:.45}
#memory-settings input[type=text],#memory-settings select{font:inherit;font-size:12.5px;padding:2px 6px;color:var(--ink);background:var(--surface);
border:1px solid var(--line);border-radius:7px;min-width:0}
#memory-settings input[type=checkbox]{accent-color:var(--accent)}
.mgrades{display:flex;flex-direction:column;gap:8px}.mwiki{border-bottom:1px solid var(--line);padding-bottom:8px}
.mkind{display:flex;flex-wrap:wrap;align-items:center;gap:4px 12px;margin:2px 0 2px 28px;font-size:12.5px;color:var(--ink2)}
.mkind label{display:flex;align-items:center;gap:5px}.mkname{flex:0 0 92px;font-weight:560;color:var(--ink)}
.mcount{margin:4px 0 0 28px;font-size:12.5px;color:var(--ink2)}.mcount .mfull{margin-left:6px}
.madv{margin-top:8px}.madv>summary{display:block;list-style:none;cursor:pointer;font-size:12.5px;font-weight:560;color:var(--ink2);padding:3px 0}
.madv>summary::-webkit-details-marker{display:none}.madv>summary::before{content:'\203A';display:inline-block;width:12px;transition:transform .15s}
.madv[open]>summary::before{transform:rotate(90deg)}
.mlists{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;margin:4px 0;font-size:12.5px}.mlists b{flex:0 0 92px;font-weight:560}
.mlist{display:flex;align-items:center;gap:6px;color:var(--ink2);flex:1 1 160px;min-width:0}.mlist input{flex:1 1 0;width:0;min-width:0}
.mpins{display:flex;flex-direction:column;gap:3px;margin:0 0 6px}.mpin{display:flex;align-items:center;gap:6px;font-size:12.5px}
.mreach,.mafter{font-size:12.5px;color:var(--ink2)}.mreach{display:flex;flex-wrap:wrap;align-items:center;gap:4px}.mreach select{max-width:100%}
.mafter{white-space:nowrap}#memory-settings{min-width:0;overflow-wrap:anywhere}
#memory-settings .msaid,#memory-settings .mlede{margin:6px 0}
"""

# Read back into the shape fade.py keeps. A number out of range is brought into
# range here, and a kind's archive months never come before its dormant ones,
# so nothing the form can hold is refused when Settings closes. In a host that
# answers `memory-preview` (window.GarrickReadsMemory), a change is counted
# again from the unsaved values and each wiki's line said again, as
# memory_said() says it; elsewhere the counts are the saved ones.
MEMORY_JS = r"""
(function(){var sec=document.getElementById('memory-settings');if(!sec||!sec.querySelector('#m-prev'))return;
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick,changed=false,timer=null,said=document.getElementById('m-prevsaid');
function n(e){var v=parseInt(e.value,10);if(isNaN(v))v=parseInt(e.defaultValue,10);return Math.max(+e.min,Math.min(+e.max,v))}
function list(e){return e?e.value.split(',').map(function(x){return x.trim()}).filter(function(x){return x}):[]}
function request(){var m={wikis:{},kinds:{},pins:{},wake:document.getElementById('m-wake').checked,reach:document.getElementById('m-reach').value,
nightly:{on:document.getElementById('m-night').checked,min:n(document.getElementById('m-min'))}};
sec.querySelectorAll('[data-mwikion]').forEach(function(c){m.wikis[c.dataset.mwikion]=c.checked});
sec.querySelectorAll('[data-mpin]').forEach(function(c){m.pins[c.dataset.mpin]=c.checked});
sec.querySelectorAll('.mkind').forEach(function(f){var q=function(k){return f.querySelector('[data-mk="'+k+'"]')},d=n(q('dormant')),
l=sec.querySelector('[data-mkl="'+f.dataset.mkind+'"]'),t=function(k){return l&&l.querySelector('[data-mk="'+k+'"]')};
m.kinds[f.dataset.mkind]={wiki:f.dataset.mwiki,types:list(t('types')),domains:list(t('domains')),dormant:d,archived:q('never').checked?null:Math.max(d,n(q('archived')))}});
return m}
function line(w,c){var g=w+': '+(c.working||0)+' working · '+(c.dormant||0)+' dormant'+(c.archived?' · '+c.archived+' archived':'');
if(c.on===false)return g+' · off';var mv=(c.to_dormant||0)+(c.to_archive||0)+(c.to_wake||0);return g+(mv?' · next pass moves '+mv:' · nothing to move')}
function paint(counts){sec.querySelectorAll('#m-prev [data-mw]').forEach(function(w){var c=counts[w.dataset.mw],e=w.querySelector('[data-mc="line"]');
if(c&&e)e.textContent=line(w.dataset.mw,c)})}
function tell(t){said.textContent=t;said.hidden=false}
function ask(){if(!host||!window.GarrickReadsMemory){tell('Counted as saved; closing Settings saves the change and counts again.');return}
tell('Counting…');clearTimeout(timer);timer=setTimeout(function(){host.postMessage({act:{verb:'memory-preview',memory:request()}})},250)}
function sync(){sec.querySelectorAll('.mkind').forEach(function(f){var a=f.querySelector('[data-mk="archived"]'),d=f.querySelector('[data-mk="dormant"]');
a.disabled=f.querySelector('[data-mk="never"]').checked;if(!a.disabled&&n(a)<n(d))a.value=n(d)})}
sec.addEventListener('change',function(){changed=true;sync();ask()});
sec.addEventListener('input',function(e){if(e.target.matches('input[type=number],input[type=text]')){changed=true;ask()}});
var prev=window.GarrickActed;window.GarrickActed=function(q,out){if(q&&q.verb==='memory-preview'){
if(out&&out.ok&&out.counts){paint(out.counts);tell('With these changes, not saved yet.')}else tell((out&&out.say)||'Could not count.');return}
if(prev)return prev(q,out)};
window.GarrickMemory={changed:function(){return changed},request:request,saved:function(){changed=false}};
})();
"""
# ---- end of Settings › Memory -----------------------------------------------------


# Park and Wake land on the threads list at once, with no wait for the
# rebuild: Garrick.app hands page_action.py's reply to
# window.GarrickActed, and a request that was done moves its row. It runs
# after JS, whose rows it moves and binds through window.ThreadRows.
PARK_JS = r"""
(function(){var R=window.ThreadRows||{bind:function(){},chev:function(){},close:function(){}};
/* Park and Wake land on the list at once. When the host says the request was done (window.GarrickActed, called by
   Garrick.app with the request and page_action.py's reply), the row moves to its zone's
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
if(t)t.textContent=n+' thread'+(n===1?'':'s')+(urg?' · '+urg+' late':'')+(bare?' · '+bare+' without a resume block':'');
if(b)b.title='Show its '+n+' thread'+(n===1?'':'s')}
/* a zone's line as the build writes it: live, those late (a row whose todo
   chip is red, which is its next action's doing and never its age), and the
   done it counted */
function count(z,f,sel){return z.querySelectorAll(sel).length-(f?f.querySelectorAll(sel).length:0)}
function recount(){var live=0,held=0;document.querySelectorAll('.tview details.zone').forEach(function(z){var f=fold(z,false),
p=f?f.querySelectorAll('.thread:not(.proj)').length:0,l=count(z,f,'.thread:not(.proj)'),meta=z.querySelector(':scope>summary .meta');
live+=l;held+=p;if(meta){var a=count(z,f,'.thread:not(.proj) .tchip.todo.late'),d=/(\d+) done/.exec(meta.textContent);
meta.textContent=l+' live'+(a?' · '+a+' late':'')+(d?' · '+d[1]+' done':'')}
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


# A rename from the page lands at once (#184), as Park and Wake do: when the
# host says it was done, every row of the thread, or of the project and its
# threads, takes the new name, its link and its card's paths (the note it
# opens, the folder, what Park, Open in Claude, Rename…, Delete… and the desk
# act on), and moves to its place by name; the hover card is closed, so the
# next one shows the new name. The Find box follows (FIND_JS), and RELOAD_JS
# keeps the request beside what it waits for, `named:<zone>/<note>`, so a
# reload before the rebuild renames the rows again.
RENAME_JS = r"""
(function(){var R=window.ThreadRows||{bind:function(){},chev:function(){},close:function(){}};
function cardOf(r){try{return JSON.parse(r.dataset.card)}catch(e){return null}}
/* a path as Python's urllib.parse.quote writes it into the links the page holds */
function pq(s){return encodeURIComponent(s).replace(/[!'()*]/g,function(c){return'%'+c.charCodeAt(0).toString(16).toUpperCase()}).replace(/%2F/g,'/')}
function bare(p){return p.replace(/\.md$/,'')}
function link(u,from,to){if(!u)return u;var a=[[pq(bare(from)),pq(bare(to))],[pq(from),pq(to)]];
for(var i=0;i<a.length;i++){var k=u.length-a[i][0].length;if(k>=0&&u.slice(k)===a[i][0])return u.slice(0,k)+a[i][1]}return u}
function relOf(c){return c.kl==='project'?c.n+'/'+c.n+'.md':((c.oc||c.pa||[])[1]||'')}
function nameOf(el){var a=el.querySelector('.t>a');return a?a.textContent.toLowerCase():''}
function place(el){var box=el.parentNode;if(!box)return;var kind=el.classList.contains('tunit')?'tunit':'thread',n=nameOf(el);
var after=[].filter.call(box.children,function(x){return x!==el&&x.classList.contains(kind)&&nameOf(x)>n})[0]||
[].filter.call(box.children,function(x){return x.matches('details.parked')})[0]||null;box.insertBefore(el,after)}
/* the new paths of a row's note: a thread's own folder and note, or anything under the project */
function moveRel(rel,q){var P=q.project,N=q.to;if(q.thread){var T=q.thread;
return rel===P+'/Threads/'+T+'/'+T+'.md'?P+'/Threads/'+N+'/'+N+'.md':rel}
if(rel===P+'/'+P+'.md')return N+'/'+N+'.md';return rel.indexOf(P+'/')===0?N+'/'+rel.slice(P.length+1):rel}
function moveDir(f,from,to){if(!f)return f;var a=from.replace(/\/[^\/]*$/,''),b=to.replace(/\/[^\/]*$/,'');
return f.length>=a.length&&f.slice(f.length-a.length)===a?f.slice(0,f.length-a.length)+b:f}
function renamed(q){if(!q||q.verb!=='rename'||!q.to)return false;var hit=false,moved=[];
[].forEach.call(document.querySelectorAll('.tview .thread[data-card]'),function(r){var c=cardOf(r);if(!c||c.z!==q.zone)return;
var mine=q.thread?c.kl==='thread'&&c.p===q.project&&c.n===q.thread:(c.kl==='project'&&c.n===q.project)||c.p===q.project;
if(!mine){if(q.thread&&c.kl==='project'&&c.n===q.project&&c.mg&&c.mg[5]){c.mg[5]=c.mg[5].map(function(t){return t===q.thread?q.to:t}).sort();r.dataset.card=JSON.stringify(c)}return}
hit=true;var old=relOf(c),rel=moveRel(old,q),was=q.thread||q.project,own=c.n===was;
if(own){c.n=q.to;delete c.sp}if(c.w)c.w=c.w===was?q.to:c.w.split(was).join(q.to);
if(!q.thread&&c.p===q.project)c.p=q.to;
c.u=link(c.u,old,rel);c.f=moveDir(c.f,old,rel);['pa','oc'].forEach(function(k){if(c[k]&&c[k][1]===old)c[k][1]=rel});
if(c.pp&&c.pp[1]===q.project)c.pp[1]=q.to;if(c.mg){if(q.thread){if(c.mg[2]===q.thread)c.mg[2]=q.to}else c.mg[1]=q.to}
if(c.dk){if(q.thread){if(c.dk[2]===q.thread)c.dk[2]=q.to}else c.dk[1]=q.to}
r.dataset.card=JSON.stringify(c);var a=r.querySelector('.t>a');if(a){if(own)a.textContent=q.to;a.setAttribute('href',c.u||'')}
var sm=r.querySelector('.t>small');if(sm&&!q.thread&&sm.textContent===q.project)sm.textContent=q.to;
moved.push(r.classList.contains('sub')?r:(r.closest('.tunit')||r))});
if(!hit)return false;R.close();moved.forEach(place);return true}
window.GarrickRenamed=renamed;
var prev=window.GarrickActed;window.GarrickActed=function(q,out){
if(out&&out.ok&&renamed(q)&&window.GarrickExpect){var rel=q.thread?q.project+'/Threads/'+q.to+'/'+q.to+'.md':q.to+'/'+q.to+'.md';
GarrickExpect('named:'+q.zone+'/'+rel);try{var w=JSON.parse(localStorage.getItem('garrick-expect')||'null');if(w){w.q=q;localStorage.setItem('garrick-expect',JSON.stringify(w))}}catch(e){}}
if(prev)return prev(q,out)};
if(window.GarrickRedo&&window.GarrickRedo.verb==='rename')renamed(window.GarrickRedo);
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
function sync(){var h=cards().filter(function(e){return e.hidden});dots(h);
var n=document.getElementById('hidden-cards');if(n){n.hidden=!h.length;n.innerHTML=h.length?'<p class="hint">Hidden cards</p><div class="gacts">'+h.map(function(c){
var t=c.querySelector('h2').textContent.replace(/[&<>"]/g,function(x){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[x]});
return'<button class="act unhide" type="button" data-card="'+c.id+'" title="Show '+t+' again">'+t+(sev(c)?'<span class="dot tr '+sev(c)+'" title="needs attention"></span>':'')+'</button>'}).join('')+'</div>':''}}
/* Trouble sits on the card that shows it, hidden or not: a tab carries a dot for the cards it holds, worst first (#443) */
var TR=[];try{TR=JSON.parse(document.getElementById('trouble-data').textContent)}catch(e){}
function sev(c){var w='';TR.forEach(function(t){var el=document.getElementById(t[1]);if(el&&(el===c||c.contains(el))&&w!=='critical')w=t[0]});return w}
function dots(){var w={};TR.forEach(function(t){var el=document.getElementById(t[1]),sec=el&&el.closest('section.tab');if(sec&&w[sec.id]!=='critical')w[sec.id]=t[0]});
document.querySelectorAll('.tabs [data-tab]').forEach(function(b){var d=b.querySelector('.dot.tr'),s=w['tab-'+b.dataset.tab];if(d&&!s)d.remove();
else if(s){if(!d){d=document.createElement('span');b.appendChild(d)}d.className='dot tr '+s;d.title=s==='critical'?'something failed':'needs attention'}})}
/* Move to…: a short menu of the other tabs that have slots, under the button; the card goes to that tab's left slot */
function closeMove(){var o=document.querySelector('.moveto');if(o)o.remove()}
function moveMenu(b){var c=b.closest('.card'),here=c.closest('section.tab'),was=document.querySelector('.moveto'),again=was&&was.dataset.card===c.id;closeMove();if(again)return;
var o=document.createElement('div');o.className='moveto';o.setAttribute('role','menu');o.dataset.card=c.id;
document.querySelectorAll('main>section.tab').forEach(function(t){var tb=document.querySelector('.tabs [data-tab="'+t.id.slice(4)+'"]');if(t===here||!tb||!t.querySelector('[data-slot]'))return;
var i=document.createElement('button');i.type='button';i.setAttribute('role','menuitem');i.dataset.to=t.id;i.textContent=tb.firstChild.textContent;o.appendChild(i)});
var r=b.getBoundingClientRect();o.style.top=(r.bottom+window.scrollY+4)+'px';o.style.left=Math.max(8,r.right+window.scrollX-150)+'px';document.body.appendChild(o)}
function toast(t){var el=document.getElementById('toast');if(!el)return;el.textContent=t;el.style.opacity=1;setTimeout(function(){el.style.opacity=0},2600)}
document.addEventListener('click',function(e){
var m=e.target.closest('.head .totab');if(m){e.preventDefault();e.stopPropagation();moveMenu(m);return}
var pick=e.target.closest('.moveto [data-to]');if(pick){e.preventDefault();e.stopPropagation();var mc=document.getElementById(pick.parentNode.dataset.card),sl=document.querySelector('#'+pick.dataset.to+' [data-slot$="left"]');
if(mc&&sl){sl.appendChild(mc);save();toast(mc.querySelector('h2').textContent+' moved to '+pick.textContent+'.')}closeMove();return}
closeMove();
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

# Preview (#206): a node's note read inside Garrick, over the graph, as Quick
# Look reads a file. The card offers it where the host reads a note for it
# (window.GarrickReadsNotes, set by Garrick.app); a
# browser cannot read one, so it never offers it, and neither does a card
# while Settings › Opening a thread has it switched off (#219: `preview`,
# among the launchers). The card draws it as a magnifier. The note is read by
# page_action.py's `note-read`, drawn there by guide.py's renderer, and
# `note-open` opens it in the app the Mac uses for a .md file, which is not
# a launcher Settings chooses. A <dialog> shown modal holds it, so the card
# and the graph underneath keep their selection, place and zoom while it is
# open, and get them back as they were: it closes on Close, Escape, which it
# keeps from the card, or a click outside it, and hands the keyboard back to
# the Preview it was opened from. It never edits, and nothing stays open.
NOTE_CSS = r"""
/* Preview on the card, a magnifier: as tall as the card's words outside the app, and in Garrick.app, whose
   ways to open a note are icons (.appicons), on the same square as they are */
.act.nv-glass{display:inline-flex;align-items:center;justify-content:center;padding:4px 6px}.act.nv-glass svg{display:block;width:13px;height:13px}
.appicons .act.nv-glass{width:34px;height:34px;padding:0;border-color:transparent;border-radius:8px;background:transparent}
.appicons .act.nv-glass svg{width:20px;height:20px}.appicons .act.nv-glass:hover{border-color:var(--base)}
dialog.nview{padding:0;border:0;background:transparent;color:var(--ink);width:min(820px,calc(100vw - 32px));max-width:none;max-height:none;overflow:visible}
dialog.nview::backdrop{background:rgba(0,0,0,.32)}
.nv-panel{display:flex;flex-direction:column;min-height:160px;max-height:calc(100vh - 64px);background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:0 18px 60px rgba(0,0,0,.3);overflow:hidden}
.nv-head{display:flex;flex-wrap:wrap;align-items:flex-start;gap:8px 12px;padding:14px 16px 12px 24px;border-bottom:1px solid var(--grid)}
.nv-t{flex:1 1 260px;min-width:0}.nv-t h3{margin:0;font:700 19px/1.25 var(--sans);overflow-wrap:anywhere}
.nv-path{display:block;margin-top:3px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}
.nv-acts{display:flex;gap:6px;flex:none}.nv-acts .act{font-size:12px;padding:5px 10px}
.nv-said{margin:0;padding:14px 24px 0;font-size:13px;color:var(--ink2)}.nv-said:empty{display:none}.nv-said.bad{color:var(--critical)}
.nv-body{flex:1 1 auto;min-height:0;overflow:auto;padding:6px 24px 26px;line-height:1.6;font-size:14.5px;overflow-wrap:break-word}
.nv-body:focus{outline:none}.nv-body:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.nv-body>:not(.gd-table){max-width:70ch}
.nv-body h1{font:700 26px/1.2 var(--sans);margin:18px 0 12px}.nv-body h2{font:700 20px/1.25 var(--sans);margin:24px 0 8px}
.nv-body h3{font-size:16px;margin:20px 0 6px}.nv-body :is(h4,h5,h6){font-size:14.5px;margin:16px 0 4px}
.nv-body code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--raise);border:1px solid var(--line);border-radius:4px;padding:0 4px}
.nv-body pre{background:var(--raise);border:1px solid var(--line);border-radius:10px;padding:12px 14px;overflow:auto}
.nv-body pre code{border:0;padding:0;background:none;white-space:pre}
.nv-body blockquote{margin:12px 0;padding:2px 16px;border-left:3px solid var(--accent);color:var(--ink2);background:var(--wash);border-radius:0 8px 8px 0}
.nv-body ul,.nv-body ol{padding-left:22px}.nv-body li{margin:3px 0}.nv-body hr{border:0;border-top:1px solid var(--grid);margin:18px 0}
.nv-props{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:2px 14px;margin:14px 0 6px;padding:10px 12px;font-size:12.5px;line-height:1.45;background:var(--raise);border:1px solid var(--line);border-radius:10px}
.nv-props div{display:contents}.nv-props dt{color:var(--muted)}.nv-props dd{margin:0;color:var(--ink2)}.nv-none{color:var(--muted)}
@media (max-width:560px){.nv-head{padding-left:16px}.nv-said{padding-left:16px}.nv-body{padding:4px 16px 20px}}
"""

NOTE_JS = r"""
(function(){var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick,dlg=null,cur=null,back=null,down=null;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
/* only where the host reads a note for the page: a browser, or an app built before it, offers no Preview; and only while
   Settings › Opening a thread offers it (PANEL_JS's GarrickPrefs, #219): switched off, nothing here opens the preview */
function able(){var P=window.GarrickPrefs;return!!host&&!!window.GarrickReadsNotes&&!(P&&P.launchers().preview===false)}
/* a magnifier, as the card's other actions are icons, named Preview for the pointer and the screen reader */
var GLASS='<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="6.8" cy="6.8" r="4.6" fill="none" stroke="currentColor" stroke-width="1.6"/>'
+'<path d="M10.2 10.2L14 14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
function button(path,title){return path&&able()?'<button class="act nv-glass" type="button" data-note="'+esc(path)+'" data-title="'+esc(title)+'" title="Preview" aria-label="Preview" aria-haspopup="dialog">'+GLASS+'</button>':''}
function el(s){return dlg.querySelector(s)}
function make(){dlg=document.createElement('dialog');dlg.className='nview';dlg.setAttribute('role','dialog');dlg.setAttribute('aria-modal','true');dlg.setAttribute('aria-labelledby','nview-h');
dlg.innerHTML='<div class="nv-panel"><div class="nv-head"><div class="nv-t"><h3 id="nview-h"></h3><small class="nv-path"></small></div>'
+'<div class="nv-acts"><button class="act" type="button" data-nv="open">Open in default app</button><button class="act" type="button" data-nv="close">Close</button></div></div>'
+'<p class="nv-said" role="status" aria-live="polite"></p><div class="nv-body" tabindex="0" aria-label="The note"></div></div>';
document.body.appendChild(dlg);
/* outside the panel is the dialog itself, behind its backdrop: a press that starts and ends there closes it, and text selected
   in the note and dragged past its edge does not */
dlg.addEventListener('pointerdown',function(e){down=e.target});
dlg.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-nv]');if(b){if(b.dataset.nv==='open')openIn(cur&&cur.path);else shut();return}
if(e.target===dlg&&down===dlg)shut()});
/* Escape is the preview's alone, and never reaches the card underneath, whose own Escape closes it */
dlg.addEventListener('keydown',function(e){if(e.key==='Escape'){e.preventDefault();e.stopPropagation();shut()}});
dlg.addEventListener('cancel',function(e){e.preventDefault();shut()})}
function said(s,bad){var p=el('.nv-said');p.textContent=s||'';p.classList.toggle('bad',!!bad)}
/* the note asked for, named and placed at once, its body once the host has read it */
function read(path,title,btn){if(!dlg)make();cur={path:path};back=btn||null;
el('#nview-h').textContent=title||path.split('/').pop().replace(/\.md$/,'');el('.nv-path').textContent=path;
el('.nv-body').innerHTML='';el('[data-nv="open"]').hidden=false;said('Reading the note…');if(!dlg.open)dlg.showModal();el('.nv-body').focus();
host.postMessage({act:{verb:'note-read',path:path}})}
function openIn(path){if(!path)return;said('Opening it…');
host.postMessage({act:{verb:'note-open',path:path}})}
function shut(){if(!dlg||!dlg.open)return;dlg.close();cur=null;down=null;
var b=back&&document.contains(back)?back:document.querySelector('#gpop button[data-note]');back=null;if(b)b.focus({preventScroll:true})}
/* a reply for a note no longer shown is dropped. A note that is not there has nothing to open, so Open in default app goes */
function heard(q,out){if(!cur||!dlg.open||q.path!==cur.path)return;if(out&&out.missing)el('[data-nv="open"]').hidden=true;
if(q.verb==='note-open'){if(out&&out.ok)shut();else said((out&&out.say)||'That did not open.',true);return}
if(out&&out.ok&&typeof out.html==='string'){said('');el('.nv-body').innerHTML=out.html;el('.nv-body').scrollTop=0}
else said((out&&out.say)||'That note could not be read.',true)}
var prev=window.GarrickActed;window.GarrickActed=function(q,out){if(q&&(q.verb==='note-read'||q.verb==='note-open')){heard(q,out);return}
if(prev)return prev(q,out)};
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('button[data-note]');if(!b||!able())return;e.preventDefault();read(b.dataset.note,b.dataset.title,b)});
window.GarrickNote={button:button,shown:function(){return!!(dlg&&dlg.open)}};
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
/* which place the graph shows: the one asked for last, else Work when there is one, else the first. All went in #250,
   so a window that stored it, *, falls back too */
var zsel=st.get('garrick-graph-place');if(places.indexOf(zsel)<0)zsel=places.indexOf('Work')>=0?'Work':places[0]||'';
/* the Threads card leads with the zone the graph shows, the others after it by name; a wiki puts them all by name */
function leadZone(z){var box=document.querySelector('.tview .zones');if(!box)return;
var all=[].slice.call(box.children).filter(function(d){return d.matches('details.zone[data-zone]')});
all.sort(function(a,b){var x=a.dataset.zone,y=b.dataset.zone;return (x===z?0:1)-(y===z?0:1)||x.localeCompare(y)});
all.forEach(function(d){box.appendChild(d)})}leadZone(zsel);
/* Following the zone in view on the Threads card (#142, FOLLOW_JS) changes the graph and the drop-down for this page
   only. Picking a wiki, which the card cannot be in, pauses it until the page reloads. */
var held=false;function cardZone(z){return[].some.call(document.querySelectorAll('.tview .zones>details.zone[data-zone]'),function(d){return d.dataset.zone===z})}
/* The kinds shown, kept for each place (#250): the ones last chosen in its legend; else as the view #250 replaced
   was left, every kind for Everything and the hubs for the other; else the hubs, or every kind the model knows where
   the place is small (G.modes) or has no hub. A kind found from the pages starts hidden. */
function kindsFor(z){var o={},s=st.get('garrick-graph-kinds-'+z),m=st.get('garrick-graph-mode-'+z),all={},hub={},model={},k;
var op=(G.op||{})[z];      /* Meetings opens on its people, though its entities are hubs too (#320) */
G.nodes.forEach(function(n){if(n.z!==z)return;all[n.k]=1;if(n.c&&(!op||op.indexOf(n.k)>=0))hub[n.k]=1;if(n.k<G.known)model[n.k]=1});
if(s)try{JSON.parse(s).forEach(function(x){var i=G.keys.indexOf(x);if(i>=0)o[i]=1});return o}catch(e){}
var pick=m==='all'?all:m==='core'?hub:((G.modes&&G.modes[z])||G.mode)==='all'?model:hub;for(k in pick)return pick;for(k in model)return model;return all}
function keep(){st.set('garrick-graph-kinds-'+zsel,JSON.stringify(Object.keys(ks).map(function(k){return G.keys[k]})))}
var ks=kindsFor(zsel),spin=!reduce&&st.get('garrick-graph-spin')!=='0',parked=st.get('garrick-graph-parked')==='1',q='',mt={},hits=[],hi=-1,more={};
/* Settings › Explore no longer offers Obsidian's graph colours (#292): what a window saved for it is dropped, unread */
try{localStorage.removeItem('garrick-graph-obsidian')}catch(e){}
var N=G.nodes,seed=7;function rnd(){seed=(seed*16807)%2147483647;return seed/2147483647}
N.forEach(function(n,i){n.i=i;n.adj=[]});
G.edges.forEach(function(e){N[e[0]].adj.push(e[1]);N[e[1]].adj.push(e[0])});
var places=[];N.forEach(function(n){if(places.indexOf(n.z)<0)places.push(n.z);n.r=(n.h?7:n.c?5:4)+Math.min(5,Math.sqrt(n.adj.length)*.8)});
/* A page that was left in 3D (#372) opens flat: its stored value is dropped, unread */
try{localStorage.removeItem('garrick-graph-3d')}catch(e){}
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
function visible(n){return!!ks[n.k]&&(parked||!n.s)&&n.z===zsel}
/* With only hubs drawn, two are joined where one page links both (ce, from graph()); with any other kind drawn, the
   lines are the notes' own links (#250) */
function rebuild(){V=N.filter(visible);var on={};V.forEach(function(n){on[n.i]=1});E=(V.every(function(n){return n.c})?G.edges.concat(G.ce||[]):G.edges).filter(function(e){return on[e[0]]&&on[e[1]]});
N.forEach(function(n){n.deg=0});E.forEach(function(e){N[e[0]].deg++;N[e[1]].deg++});anchors();
/* the legend offers every kind the place has, pressed when shown */
var have={};N.forEach(function(n){if(n.z===zsel&&(parked||!n.s))have[n.k]=1});
document.querySelectorAll('.glegend [data-k]').forEach(function(s){var k=+s.dataset.k;s.hidden=!have[k];s.setAttribute('aria-pressed',ks[k]?'true':'false')});
var zs=document.querySelector('.gzsel');if(zs){zs.value=zsel;zmark(zs)}
var sum=document.getElementById('gsum');if(sum)sum.textContent=zsel+' · '+V.length+' notes, '+E.length+' links · names only';seek()}
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
if(alpha>.05&&++ticks%10===0&&V.length>1){var bx=box2([0]),la=(bx[1]-bx[0]+40)/(bx[3]-bx[2]+40);pull=Math.max(.7,Math.min(4,pull*Math.pow(asp/la,.3)))}
var q=pull;V.forEach(function(n){var g=(n.deg?.04:.08)*alpha;n.vx-=(n.x-n.ax)*g/q;n.vy-=(n.y-n.ay)*g*q;if(n===drag)return;n.vx*=.6;n.vy*=.6;n.x+=n.vx;n.y+=n.vy});
var mx=0,my=0;V.forEach(function(n){mx+=n.x;my+=n.y});mx/=V.length||1;my/=V.length||1;if(!drag)V.forEach(function(n){n.x-=mx;n.y-=my});
alpha=Math.max(0,alpha-(alpha>.02?.005:.0005)*(V.length>BIG?2:1))}
function tick(){step()}
function toScreen(n){var c=Math.cos(theta),s=Math.sin(theta);return[W/2+px+scale*(n.x*c-n.y*s),H/2+py+scale*(n.x*s+n.y*c),0,1]}
function toWorld(x,y){var c2=Math.cos(theta),s2=Math.sin(theta),u2=(x-W/2-px)/scale,v2=(y-H/2-py)/scale;return[u2*c2+v2*s2,-u2*s2+v2*c2]}
/* Fit: the box the visible notes fill, as drawn, over the whole sway while it
   sways, scaled the same both ways into the card and centred in it. Room is
   kept for the buttons at the top and the names under the lowest notes. */
function box2(turns){var b=[1e9,-1e9,1e9,-1e9];(turns||(spin?[-SWAY,SWAY,theta]:[theta])).forEach(function(t){var c=Math.cos(t),s=Math.sin(t);
V.forEach(function(n){var x=n.x*c-n.y*s,y=n.x*s+n.y*c;if(x<b[0])b[0]=x;if(x>b[1])b[1]=x;if(y<b[2])b[2]=y;if(y>b[3])b[3]=y})});return b}
function box(){return box2()}
function fit(now){if(!W||!H||!V.length)return;var b=box(),l=34,r=34,t=top,u=36,
k=Math.min((W-l-r)/Math.max(1,b[1]-b[0]),(H-t-u)/Math.max(1,b[3]-b[2]),2.2),
x=l+(W-l-r)/2-W/2-k*(b[0]+b[1])/2,y=t+(H-t-u)/2-H/2-k*(b[2]+b[3])/2;
if(now){scale=k;px=x;py=y;return false}var going=Math.abs(k-scale)>scale*.001||Math.abs(x-px)>.2||Math.abs(y-py)>.2;
scale+=(k-scale)*.08;px+=(x-px)*.08;py+=(y-py)*.08;return going}
/* the theme's colours, and each kind's chosen in Settings › Graph colours (#291), a variable with a shade for each theme */
function cvar(c){var m=/^var\((--[\w-]+)\)$/.exec(c||'');return m&&m[1]}
function colors(){var cs=getComputedStyle(document.documentElement);['--ink','--ink2','--muted','--base','--accent','--warning','--critical','--raise'].concat(G.colors.map(cvar).filter(Boolean)).forEach(function(v){C[v]=cs.getPropertyValue(v).trim()})}
/* a note takes its kind's colour, in every place (#292): the one chosen for the theme in use, or the one shipped (#291) */
function fill(n){var c=G.colors[n.k],v=cvar(c);return(v?C[v]:c)||C['--muted']}
/* a ring for a thread whose own next action is late (lt), never for age alone */
function ring(n){return n.s||!n.lt?null:C['--critical']}
function draw(){ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
var f=sel||hover,near={},M=q?mt:null;if(f){near[f.i]=1;f.adj.forEach(function(i){near[i]=1})}
var P={};V.forEach(function(n){P[n.i]=toScreen(n)});
E.forEach(function(e){var a=P[e[0]],b=P[e[1]],hot=f&&(e[0]===f.i||e[1]===f.i);
ctx.globalAlpha=(f&&!hot||!f&&M&&!(M[e[0]]&&M[e[1]])?.12:(N[e[0]].s||N[e[1]].s)?.25:.55);ctx.strokeStyle=hot?C['--accent']:C['--base'];ctx.lineWidth=hot?1.6:1;
ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke()});
var zs=Math.max(.7,Math.min(1.6,scale));
V.forEach(function(n){var p=P[n.i],r=n.r*zs;ctx.globalAlpha=(f&&!near[n.i]||!f&&M&&!M[n.i]?.15:n.s?.3:1);
ctx.fillStyle=fill(n);ctx.beginPath();ctx.arc(p[0],p[1],r,0,6.283);ctx.fill();
var rc=ring(n);if(rc){ctx.strokeStyle=rc;ctx.lineWidth=2.2;ctx.beginPath();ctx.arc(p[0],p[1],r+3.2,0,6.283);ctx.stroke()}
if(n===sel){ctx.strokeStyle=C['--ink'];ctx.lineWidth=2;ctx.beginPath();ctx.arc(p[0],p[1],r+(rc?6.4:3),0,6.283);ctx.stroke()}});
ctx.textAlign='left';ctx.textBaseline='top';ctx.lineJoin='round';
names(P,f,near,zs).forEach(function(l){var n=l.n;ctx.globalAlpha=(f&&!near[n.i]||!f&&M&&!M[n.i]?.2:n.s?.45:1);ctx.font=l.font;
ctx.strokeStyle=C['--raise'];ctx.lineWidth=3.5;ctx.strokeText(n.n,l.x,l.y);ctx.fillStyle=l.big?C['--ink']:C['--ink2'];ctx.fillText(n.n,l.x,l.y)});
ctx.globalAlpha=1}
/* Which names to draw, and where. They are placed most wanted first: the note
   in focus, its linked notes, projects, hubs, then every other note drawn, the
   most linked first, at any zoom: a kind is drawn because it was asked for (#252).
   A name whose box would cover one already placed tries above its note, then
   beside it, and is left out when none of those is free, unless it is the
   note in focus or a project, which are always named. A name keeps the side it
   had while that stays free, so names do not hop as the graph moves. The
   list comes back least wanted first, so the most wanted is drawn on top.
   Of the notes that are neither in focus, linked, found, projects nor hubs,
   at most BIG on the card are tried a frame, the most linked first: measured
   with 2,000 notes drawn, a frame took 6.6 ms trying them all and 2.3 ms so,
   and with 650 it was 2.2 ms and 1.6 ms. Zooming in leaves the rest off the
   card, which frees the count for those still on it (#252). */
var FONT='system-ui,-apple-system,sans-serif';
function names(P,f,near,zs){var want=[],out=[],cells={},M=q?mt:null,few=M&&hits.length<=20;
/* a hub of the kinds its place opens on is named before the rest: in Meetings its people, then its entities with the other notes (#320) */
var op=(G.op||{})[zsel];V.forEach(function(n){want.push([n===f?0:f&&near[n.i]||M&&M[n.i]?1:n.h?2:n.c&&(!op||op.indexOf(n.k)>=0)?3:4,n])});
want.sort(function(a,b){return a[0]-b[0]||b[1].deg-a[1].deg||a[1].i-b[1].i});
function each(b,fn){for(var x=Math.floor(b[0]/64);x<=Math.floor(b[2]/64);x++)for(var y=Math.floor(b[1]/64);y<=Math.floor(b[3]/64);y++)if(fn(x+' '+y))return true;return false}
function free(b){return!each(b,function(k){return(cells[k]||[]).some(function(o){return b[0]<o[2]&&o[0]<b[2]&&b[1]<o[3]&&o[1]<b[3]})})}
var tried=0;want.forEach(function(e){var n=e[1],p=P[n.i],big=n.h||n===f;if(p[0]<-200||p[0]>W+200||p[1]<-40||p[1]>H+40||e[0]===4&&++tried>BIG){n.lp=-1;return}
var font=(big?'600 12px ':'11px ')+FONT,lw=n.tw||(n.tw={});if(lw[font]==null){ctx.font=font;lw[font]=ctx.measureText(n.n).width}
var w=lw[font],h=big?14:13,r=n.r*zs*p[3]+(ring(n)?6:3),at=[[p[0]-w/2,p[1]+r+1],[p[0]-w/2,p[1]-r-1-h],[p[0]+r+4,p[1]-h/2],[p[0]-r-4-w,p[1]-h/2]],
tries=n.lp>=0?[n.lp,0,1,2,3]:[0,1,2,3],pad=n.lp>=0?-1:1,got=-1,box=null;
for(var i=0;i<tries.length&&got<0;i++){var x=Math.max(2,Math.min(W-w-2,at[tries[i]][0])),y=at[tries[i]][1],b=[x-2-pad,y-pad,x+w+2+pad,y+h+pad];
if(free(b)){got=tries[i];box=[x,y,b]}}
if(got<0&&(n===f||n.h||few&&M[n.i])){got=0;box=[Math.max(2,Math.min(W-w-2,at[0][0])),at[0][1]];box.push([box[0]-2,box[1],box[0]+w+2,box[1]+h])}
n.lp=got;if(got<0)return;each(box[2],function(k){(cells[k]||(cells[k]=[])).push(box[2])});out.push({n:n,x:box[0],y:box[1],font:font,big:big})});
return out.reverse()}
/* One frame. The loop runs only while something moves: the layout settling,
   the fit easing, a drag, a glide, or the sway (with its pause after a touch).
   When all is still it stops, and any touch, button or new size wakes it. */
function frame(t){if(!running)return;var dt=Math.min(64,t-(last||t)),moving=alpha>0||!!drag||glides>0;last=t;
if(alpha>0){tick();if(V.length<=BIG)tick()}if(auto&&fit())moving=true;
idle+=dt;if(spin&&!hover&&!sel&&!drag){moving=true;if(idle>2500){phase+=dt*.0002;theta=SWAY*Math.sin(phase)}}
if((frame.k=(frame.k||0)+1)%30===0||!C['--ink'])colors();draw();if(moving)requestAnimationFrame(frame);else running=false}
function size(){var r=wrap.getBoundingClientRect();W=r.width;H=r.height;dpr=window.devicePixelRatio||1;cv.width=W*dpr;cv.height=H*dpr;
if(bar&&bar.offsetHeight)top=bar.offsetTop+bar.offsetHeight+14;/* the buttons, however many lines they wrap to */
var a=W>120&&H>top+120?Math.max(.5,Math.min(3,(W-68)/(H-top-36))):asp;if(Math.abs(Math.log(a/asp))>.15){asp=a;return true}}
function wake(){if(shown&&!running){running=true;last=0;requestAnimationFrame(frame)}}
function start(){shown=true;wake()}function stop(){shown=false;running=false}
function at(e){var r=cv.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,best=null,bd=1e9;
/* the note closest to the pointer */
V.forEach(function(n){var p=toScreen(n),d=Math.hypot(p[0]-x,p[1]-y);if(d<n.r*Math.max(.7,Math.min(1.6,scale))+5&&d<bd){bd=d;best=n}});return{x:x,y:y,n:best}}
var down=null;
cv.addEventListener('pointerdown',function(e){var h=at(e);idle=0;down={x:h.x,y:h.y,n:h.n,px:px,py:py,moved:false};if(h.n){drag=h.n;alpha=Math.max(alpha,.25)}cv.classList.add('drag');cv.setPointerCapture(e.pointerId);wake()});
cv.addEventListener('pointermove',function(e){var h=at(e);idle=0;if(down||h.n!==hover)wake();
if(down){if(Math.hypot(h.x-down.x,h.y-down.y)>4)down.moved=true;
if(drag&&down.moved){var w=toWorld(h.x,h.y);drag.x=w[0];drag.y=w[1];drag.vx=drag.vy=0;alpha=Math.max(alpha,.2)}
else if(!drag&&down.moved){auto=false;
px=down.px+h.x-down.x;py=down.py+h.y-down.y}return}
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
cam:{screen:toScreen,world:toWorld,notes:function(){return V}},
place:function(){return zsel},follow:function(z){if(held||z===zsel||places.indexOf(z)<0)return false;show(z);return true}};
/* a double-click opens the note: in a host, over its bridge, as every file link goes (#318); in a browser, as a link */
cv.addEventListener('dblclick',function(e){var h=at(e),hb=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
if(!h.n||!h.n.u)return;if(!hb||!/^file:/i.test(h.n.u)){location.href=h.n.u;return}hb.postMessage({open:h.n.u,place:h.n.pl||undefined})});
cv.addEventListener('wheel',function(e){if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();idle=0;auto=false;
var r=cv.getBoundingClientRect(),x=e.clientX-r.left-W/2,y=e.clientY-r.top-H/2,k=Math.exp(-e.deltaY*.01);k=Math.max(.2,Math.min(5,scale*k))/scale;px=x-(x-px)*k;py=y-(y-py)*k;scale*=k;wake()},{passive:false});
var esc=Panel.esc;
/* the note behind a node, from the workspace's folder, for Preview (#206, NOTE_JS) */
function notePath(n){return n.m!=null&&G.pr&&G.pr[n.z]?G.pr[n.z]+'/'+n.m+'.md':''}
function kindName(n){var k=G.kinds.filter(function(x){return x[0]===n.k})[0];return k?k[1]:'note'}
function select(n,centre){sel=n;hover=null;delete cv.dataset.tip;
var o={n:n.n,kl:kindName(n),z:n.z,p:n.p,t:n.t,d:n.d,s:n.s,w:n.w,h:n.h,u:n.u,f:n.f,lw:n.lw,dk:n.dk,live:n.live,pa:n.pa,pp:n.pp,hp:n.hp,held:n.held};
var nb=n.adj.map(function(i){return N[i]}).sort(function(a,b){return(b.h-a.h)||(b.c-a.c)||a.n.localeCompare(b.n)});
/* each linked note's dot in its kind's colour as the page holds it, so a chosen colour follows the theme (#291) */
var links=nb.map(function(m){return'<button data-i="'+m.i+'"><i style="background:'+esc(G.colors[m.k]||'var(--muted)')+'"></i><span>'+esc(m.n)+'</span>'+(visible(m)?'':'<small class="muted">'+esc(m.z!==zsel?m.z:m.s&&!parked?'parked':'hidden')+'</small>')+'</button>'}).join('');
pop.innerHTML='<button class="x" aria-label="Close">×</button>'+Panel.head(o)+Panel.acts(o,window.GarrickNote?GarrickNote.button(notePath(n),n.N||n.n):'')
+(nb.length?'<div class="glinks"><div class="muted" style="font-size:12px;padding:2px 4px">Linked notes · '+nb.length+'</div>'+links+'</div>':'<p class="muted">No links to or from this note.</p>');
pop.hidden=false;wake();if(centre){var p=toScreen(n);auto=false;glide(px-(p[0]-W/2)+(W>700?-150:0),py-(p[1]-H/2))}}
function close(){sel=null;pop.hidden=true;wake()}
function glide(tx,ty){var sx=px,sy=py,t0=performance.now();glides++;wake();(function g(t){var k=Math.min(1,(t-t0)/350),e=1-Math.pow(1-k,3);px=sx+(tx-sx)*e;py=sy+(ty-sy)*e;if(k<1)requestAnimationFrame(g);else glides--})(t0)}
pop.addEventListener('click',function(e){if(e.target.closest('.x'))return close();
/* a linked note not drawn is shown: its place, as following shows one, and its kind (#250) */
var b=e.target.closest('button[data-i]');if(b){var m=N[+b.dataset.i];if(!visible(m)){if(m.z!==zsel){if(!cardZone(m.z))held=true;show(m.z)}if(!ks[m.k]){ks[m.k]=1;keep()}
if(m.s&&!parked){parked=true;st.set('garrick-graph-parked','1');parkBtn()}rebuild();alpha=Math.max(alpha,.3)}select(m,true)}});
/* Escape closes the card, unless a preview is open over it: that Escape is the preview's (NOTE_JS) */
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&sel&&!(window.GarrickNote&&GarrickNote.shown()))close()});
function redo(){if(sel&&!visible(sel))close();rebuild();alpha=Math.max(alpha,.5);auto=true;wake()}
function show(z){zsel=z;ks=kindsFor(z);if(fq)fq.value='';q='';hi=-1;redo()}
/* a pick is stored, leads the card (#72) and is what a reload opens on */
var zsl=document.querySelector('.gzsel');if(zsl)zsl.onchange=function(){var z=zsl.value;st.set('garrick-graph-place',z);leadZone(z);if(!cardZone(z))held=true;show(z)};
/* the legend is the filter: a kind's button shows or hides it, kept for the place (#250) */
document.querySelectorAll('.glegend [data-k]').forEach(function(b){b.onclick=function(){var k=+b.dataset.k;if(ks[k])delete ks[k];else ks[k]=1;keep();redo()}});
/* Find a note (#250): from the second letter, the notes whose name holds what is typed, whatever its case and accents,
   keep their colour and their names, and the rest dim. Enter goes to each in turn and opens its card; Escape clears.
   A match in a kind not shown is counted beside the box, and the count shows that kind. Nothing is stored. */
function fold(s){return String(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase()}
function kindSaid(k){var b=document.querySelector('.glegend [data-k="'+k+'"]');return b&&b.textContent||G.keys[k]}
function seek(){mt={};hits=[];more={};if(q)N.forEach(function(n){if(n.z!==zsel||!(parked||!n.s)||fold(n.N||n.n).indexOf(q)<0)return;if(ks[n.k]){mt[n.i]=1;hits.push(n)}else more[n.k]=(more[n.k]||0)+1});
hits.sort(function(a,b){return(b.h-a.h)||(b.c-a.c)||(a.N||a.n).localeCompare(b.N||b.n)});
var mk=Object.keys(more),c=0;mk.forEach(function(k){c+=more[k]});if(fm){fm.hidden=!c;fm.textContent=c?c+' more in '+(mk.length===1?kindSaid(mk[0]):mk.length+' hidden kinds'):''}wake()}
var fq=document.getElementById('gfind'),fm=document.getElementById('gfmore');
if(fq){fq.value='';fq.addEventListener('input',function(){var v=fold(fq.value.trim());q=v.length>=2?v:'';hi=-1;seek()});
fq.addEventListener('keydown',function(e){if(e.isComposing)return;if(e.key==='Enter'){e.preventDefault();if(hits.length){hi=(hi+1)%hits.length;select(hits[hi],true)}}
else if(e.key==='Escape'&&(fq.value||q)){e.preventDefault();e.stopPropagation();fq.value='';q='';hi=-1;seek()}})}
if(fm)fm.onclick=function(){Object.keys(more).forEach(function(k){ks[k]=1});keep();redo()};
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
rebuild();for(var i=0;i<(V.length>BIG?160:400);i++)tick();colors();fit(true);
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


# ---- Overview › Waiting on you now (#474) -----------------------------------------
# The assistant sessions stopped on a question or an approval, oldest first. The
# rows come from agents_working.py, the same read that keeps the Mac awake; the
# app hands the page the same minute's result (window.GarrickWaiting), so the
# card shows nothing older than a minute. A row names the thread the session's
# folder belongs to (or the folder), what it waits for and for how long, and
# never the question's text: agents_working.py does not read it.

def waiting_mod():
    spec = importlib.util.spec_from_file_location("garrick_agents_working", str(Path(__file__).resolve().parent / "agents_working.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def waiting_rows(ws: Path) -> List[dict]:
    """The waiting sessions now, oldest first; none where the transcripts cannot be read."""
    try:
        rows = waiting_mod().rows_json(Path(os.environ.get("GARRICK_HOME") or Path.home()), ws)
    except Exception:
        return []
    return [r for r in rows if r.get("state") == "waiting"]


def waited(since: str, now: dt.datetime) -> str:
    """How long a session has waited, in words: 3 min, 2 h."""
    try:
        t = dt.datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return ""
    s = max(0, (now.astimezone(dt.timezone.utc) - t).total_seconds()) if now.tzinfo else \
        max(0, (dt.datetime.now(dt.timezone.utc) - t).total_seconds())
    return "less than a minute" if s < 60 else "%d min" % (s // 60) if s < 3600 else "%d h" % round(s / 3600) if s < 86400 * 2 \
        else "%d days" % round(s / 86400)


def waiting_row(r: dict, now: dt.datetime) -> str:
    """One waiting session. Go to it only for a session in a cmux tab; the desktop app and any other
    terminal get the app and the folder named, since bringing a running session forward is not
    something they offer."""
    where = r.get("where")
    app = "Codex" if r.get("agent") == "codex" else "Claude Code"
    go = ('<button class="act apponly" type="button" data-wgo="%s">Go to it</button>' % E(r["id"])) if where == "cmux" else \
        '<span class="wwhere">%s</span>' % E("%s, in %s" % ("Claude's desktop app" if where == "desktop" else app,
                                                         Path(r.get("folder") or "").name or "a folder"))
    return ('<div class="wrow" data-id="%s"><span class="wico acc">%s</span><span class="wname">%s</span><span class="wwhat">%s</span>'
            '<span class="wfor" data-since="%s">%s</span>%s</div>'
            % (E(r["id"]), WAIT_ICON, E(r.get("thread") or Path(r.get("folder") or "").name or "A session"), E(r.get("waiting_for") or "an answer"),
               E(r.get("since") or ""), E(waited(r.get("since") or "", now)), go))


# ---- Overview › the lead sentence and what is waiting (#551) ------------------------------------
WAIT_ICON = ('<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
             'stroke-linejoin="round"><circle cx="8" cy="8" r="6"/><path d="M8 4.6V8l2.2 1.4"/></svg>')
NEED_ICON = {"critical": ("crit", _PILL_PATHS["alert"]), "warning": ("warn", _PILL_PATHS["clock"]), "late": ("crit", _PILL_PATHS["late"])}
NUMBER_WORDS = ("Nothing", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten")


def lead_said(n: int) -> str:
    """The Overview's lead sentence for `n` things that wait on the user: "Three things need you.",
    "Nothing needs you right now." Past ten the figure is a numeral."""
    if n <= 0:
        return "Nothing needs you right now."
    if n == 1:
        return "One thing needs you."
    return "%s things need you." % (NUMBER_WORDS[n] if n < len(NUMBER_WORDS) else n)


def attn_need(level: str, line: str, href, **over) -> dict:
    """One line of the attention list, as one thing that waits. A published file that drifted names its own row.
    `over` is what the page knows beyond the line (#559): its kind, its figure, the zone it belongs to, the day it
    began and the button's words. A critical line is Broken; a warning is To do. The button says where it goes."""
    link = href["href"] if isinstance(href, dict) else href
    need = {"kind": "problem" if level == "critical" else "other", "group": "broken" if level == "critical" else "todo",
            "level": level, "zone": "", "text": line, "late": "", "href": link, "tz": "", "count": 1,
            "blank": link.startswith("https://"), "label": "See the details", "go": "See the details"}
    need.update(over)
    if "go" not in over:
        need["go"] = need["label"]
    return need


def late_need(z: dict, today: dt.date) -> dict:
    """One zone's late actions, as one thing that waits: its count, and since when the oldest has been late. It
    belongs to that zone only; nothing here adds one zone to another."""
    oldest = None
    for _, rows in z["groups"]:
        for r in rows:
            if r["late"] and r["when"] is not None and (oldest is None or r["when"] < oldest["when"]):
                oldest = r
    n = z["late"]
    return {"kind": "late", "group": "todo", "level": "late", "zone": z["zone"], "count": n,
            "text": "%d late action%s" % (n, "" if n == 1 else "s"),
            "late": late_said(oldest, today).replace("was due", "oldest was due").replace("to chase", "oldest to chase") if oldest else "",
            "href": "#todolist", "tz": z["zone"], "label": "Open the list", "go": "Open the late actions"}


def needs_you(attn: List[tuple], lists: List[dict], today: dt.date, detail: Optional[Dict[str, dict]] = None) -> List[dict]:
    """What waits on the user, apart from the sessions that wait for an answer (the card draws those live):
    what failed first, then each zone's late actions, then the warnings. The lead sentence counts these and the
    sessions; the card lists them, in the same order, so the two always agree. `detail` is what the build knows
    of a line beyond its text (job_need, the inbox count, a repository's files), keyed by that text."""
    detail = detail or {}
    out = [attn_need(k, t, h, **detail.get(t, {})) for k, t, h in attn if k == "critical"]
    out += [late_need(z, today) for z in lists if z["late"]]
    out += [attn_need(k, t, h, **detail.get(t, {})) for k, t, h in attn if k != "critical"]
    return out


def day_name(d: dt.date) -> str:
    """A date as a day: Fri 13 Nov."""
    return "%s %d %s" % (d.strftime("%a"), d.day, d.strftime("%b"))


def job_need(j: dict) -> dict:
    """A failed job, in plain words (#559): its title, why in a few words, and the day it began to fail. The button
    goes to the log. A job that did not run on time says so and since when it last ran."""
    since = "since %s" % day_name(j["since"]) if j.get("since") else ""
    if str(j["status"]).startswith("late"):
        return {"kind": "job", "text": "%s did not run on time" % j["title"],
                "late": "last ran %s" % day_name(j["when"].date()) if j.get("when") else "", "label": "See the log"}
    why = step_reason(j.get("steps")) if "failed in the run under way" in str(j["status"]) else ""
    why = why or j.get("reason") or ("it exited with code %d" % j["code"] if isinstance(j.get("code"), int) and j["code"] > 0 else "it did not finish")
    return {"kind": "job", "text": "%s failed: %s" % (j["title"], why), "late": since, "label": "See the log"}


def need_row(n: dict) -> str:
    """One thing that waits, as a row of the card: an icon, one sentence, its zone, how long, one button."""
    cls, path = NEED_ICON[n["level"]]
    icon = ('<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
            'stroke-linejoin="round">%s</svg>' % path)
    where = '<span class="wwhat">%s</span>' % E(n["zone"]) if n["zone"] else ""
    late = '<span class="wfor">%s</span>' % E(n["late"]) if n["late"] else ""
    go = '<a class="act" href="%s"%s%s>%s</a>' % (E(n["href"]), ' data-tz-go="%s"' % E(n["tz"]) if n["tz"] else "",
                                                  ' target="_blank" rel="noopener"' if n.get("blank") else "", E(n["label"]))
    return '<div class="wrow wneed"><span class="wico %s">%s</span><span class="wname">%s</span>%s%s%s</div>' % (cls, icon, E(n["text"]), where, late, go)


def need_groups(needs: List[dict]) -> str:
    """The rows in two groups (#559): Broken (a job that failed, an error the check found) and To do (late
    actions, the inboxes, files not committed, warnings). With a row in Broken, To do starts folded and says how
    many it holds."""
    broken = [n for n in needs if n.get("group") == "broken"]
    todo = [n for n in needs if n.get("group") != "broken"]
    html = ""
    if broken:
        html += ('<section class="wgroup" data-g="broken" aria-label="Broken"><h3 class="wgh">Broken <span class="wgn">%d</span></h3>%s</section>'
                 % (len(broken), "".join(need_row(n) for n in broken)))
    if todo:
        rows = "".join(need_row(n) for n in todo)
        html += ('<details class="wgroup" data-g="todo"><summary class="wgh">To do <span class="wgn">%d</span></summary>%s</details>' % (len(todo), rows)
                 if broken else
                 '<section class="wgroup" data-g="todo" aria-label="To do"><h3 class="wgh">To do <span class="wgn">%d</span></h3>%s</section>' % (len(todo), rows))
    return html


# The kinds a lead line counts, in a fixed order: (kind, singular, plural). Each is a figure of its own.
LEAD_KINDS = (("job", "%d job failed", "%d jobs failed"), ("errors", "%d error", "%d errors"),
              ("problem", "%d problem", "%d problems"), ("late", "%d late action", "%d late actions"),
              ("inbox", "%d in the inboxes", "%d in the inboxes"), ("files", "%d file not committed", "%d files not committed"),
              ("warnings", "%d warning", "%d warnings"), ("other", "%d other thing to look at", "%d other things to look at"))


def lead_counts(items: List[dict]) -> List[str]:
    """The lead line's parts: counts by kind, in the fixed order of LEAD_KINDS, each kind once."""
    total: Dict[str, int] = {}
    for i in items:
        k = i.get("kind") if i.get("kind") in dict((x[0], 1) for x in LEAD_KINDS) else ("other" if i.get("level") != "critical" else "problem")
        total[k] = total.get(k, 0) + int(i.get("count") or 1)
    return [(one if total[k] == 1 else many) % total[k] for k, one, many in LEAD_KINDS if total.get(k)]


def lead_block(items: List[dict], sessions: int) -> str:
    """The Overview's lead: one sentence, one line of counts by kind, and one primary button to the first thing.
    The card below lists the rows; this line never repeats them. WAITING_JS redraws it when the sessions that
    wait change, from the same figures (data-n is what the build counted)."""
    n = len(items) + sessions
    static = lead_counts(items)
    reasons = list(static)
    if sessions:
        reasons.append("%d session%s waiting for you" % (sessions, " is" if sessions == 1 else "s are"))
    why = " · ".join(reasons)
    first = items[0] if items else None
    href, label, tz = (first["href"], first["go"], first["tz"]) if first else ("#waiting-now", "See who is waiting", "")
    go = ('<a class="btn primary" id="lead-go" href="%s"%s%s>%s%s</a>'
          % (E(href), ' data-tz-go="%s"' % E(tz) if tz else "", ' target="_blank" rel="noopener"' if first and first.get("blank") else "",
             E(label), ARROW)) if n else '<a class="btn primary" id="lead-go" href="#" hidden></a>'
    return ('<div class="lead" id="lead" role="region" aria-labelledby="lead-h" data-n="%d" data-why="%s" data-first="%d"><div><h2 id="lead-h">%s</h2>'
            '<p id="lead-why">%s</p></div>%s</div>'
            % (len(items), E(" · ".join(static)), 1 if first else 0, E(lead_said(n)), E(why), go))


ARROW = ('<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
         'stroke-linejoin="round" width="16" height="16"><path d="M3 8h10M9 4l4 4-4 4"/></svg>')


def tab_badge(id_: str, n: int, one: str, many: str, warn: bool, shown: str = "%d") -> str:
    """A count on a tab. A count that means something is late or waits on the user is drawn in the warning colour,
    and every count says what it is to a screen reader. An empty one is built hidden, so a script can fill it."""
    return ('<span class="n%s" id="%s" aria-label="%d%s"%s>%s</span>'
            % (" warn" if warn and n else "", id_, n, one if n == 1 else many, "" if n else " hidden", (shown % n) if n else ""))


GRAPH_ICON = ('<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
              'stroke-linejoin="round" width="16" height="16"><circle cx="4" cy="4" r="1.8"/><circle cx="12" cy="5" r="1.8"/><circle cx="7" cy="12" r="1.8"/>'
              '<path d="M5.5 4.3l5 .6M4.6 5.7l1.7 4.6M10.8 6.5L8.3 10.4"/></svg>')


def work_name_lines(w: dict) -> str:
    """The name column, in two lines: the thread in bold, then its zone and project in grey under it. A project of
    one thread has the project in bold and the zone alone below; the example zone's tag stays on the bold line."""
    one = w["name"] == w["project"]
    below = E(w["zone"]) if one else "%s / %s" % (E(w["zone"]), E(w["project"]))
    return ('<span class="yname"><span class="yline"><b>%s</b>%s</span><small class="yzone">%s</small></span>'
            % (E(w["project"] if one else w["thread"]), '<span class="ytag">Example</span>' if w["example"] else "", below))


def work_state(w: dict, today: dt.date) -> str:
    """A piece of work's state as one word (PILLS): Late when its next action or one of its lines is late, Act now
    when it waits on the user, Waiting when it waits on somebody else, Look soon when it has no next step or has not
    moved for two weeks, and Fine otherwise."""
    if w["row"].get("late") or any(a["late"] for a in w["actions"]):
        return "late"
    if w["waiting"] and w.get("mine"):
        return "act"
    if w["waiting"]:
        return "wait"
    if not w["next"] or (w["moved"] and (today - w["moved"]).days > 14):
        return "look"
    return "good"


def touched_said(moved: Optional[dt.date], today: dt.date) -> str:
    """When a piece of work was last touched, in words: today, yesterday, 6 days ago."""
    if moved is None:
        return "Not touched yet"
    days = (today - moved).days
    return "Touched today" if days <= 0 else "Touched yesterday" if days == 1 else "Touched %d days ago" % days


_TICKED = re.compile(r"`([^`\n]+)`")
YOUR_WORK_SHOWN = 10           # rows the card shows before Show all


def path_name(inner: str) -> str:
    """The last part of a path, as a person names the file: no folders, no date prefix, no extension."""
    name = inner.strip().rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)
    name = re.sub(r"^\d{6}(?:\d{2})?\s*[-\u2013]\s*", "", name).strip()
    return name or inner.strip()


def plain_next(text: str) -> str:
    """A next step for the Your work card (#559): the first letter capitalised, and a path in backticks shown as its
    file name with the whole path as its title, so a row never wraps on a long path. Other backticks stay code."""
    text = text[:1].upper() + text[1:] if text else text
    out, pos = [], 0
    for m in _TICKED.finditer(text):
        inner = m.group(1)
        out.append(md_inline(text[pos:m.start()]))
        if "/" in inner or re.search(r"\.[A-Za-z0-9]{1,5}$", inner):
            out.append('<span class="ypath" title="%s">%s</span>' % (E(inner), E(path_name(inner))))
        else:
            out.append(md_inline(m.group(0)))
        pos = m.end()
    out.append(md_inline(text[pos:]))
    return "".join(out)


def work_why(w: dict) -> Tuple[str, str]:
    """The reason beside a state (#559), as (its HTML, what the title says): who the piece of work waits on, or, when
    it waits on the user, what it asks of them. Empty when it waits on nobody."""
    if not w["waiting"]:
        return "", ""
    if w.get("mine"):
        ask = w.get("ask") or ""
        return E(ask), ask
    return "Waiting on %s" % md_inline(waiting_badge(w["waiting"])), "Waiting on %s" % w["waiting"]


def work_list_card(W: List[dict], today: dt.date, acting: bool = False, card_of=None) -> str:
    """Your work, the Overview's opening list: each live piece of work with its next action, who it waits on, its
    open actions and the way to open it (#503, #523). The rows are the ones works() builds; nothing is read or kept
    for this card. A project of one thread is one piece of work, as page_action.py's work_name() counts it.
    The `todo N` chip and its list are the thread's on the Threads card, drawn from the same lines; the way to open
    is that card's own (PANEL_JS's Panel.opener), which follows Settings, drawn by YOURWORK_JS from the card's data
    (`card_of(row)`, the JSON thread_card() gives the Threads card). In a browser the row copies the phrase instead.
    The State column is two lines at most (#559): the state's word, then the reason and the chip on one line, cut with an
    ellipsis (its title has the whole text); a row that is Fine says nothing there. The first ten rows show, then Show all."""
    rows = ""
    for n, w in enumerate(W):
        nxt = plain_next(w["next"]) if w["next"] else '<span class="muted">No next step written yet</span>'
        state = work_state(w, today)
        word, whole = work_why(w)
        row = dict(w["row"], actions=w.get("actions") or [])
        chip = todo_chip(row, today, "yw")
        pop = todo_pop(row, today, acting, "yw")
        reason = ('<span class="ywait" title="%s">%s</span>' % (E(whole), word)) if word else ""
        sep = '<span class="ydot" aria-hidden="true">\u00b7</span>' if word and chip else ""
        why = ('<span class="ywhy">%s%s%s</span>' % (reason, sep, '<span class="tchips">%s</span>' % chip if chip else "")) if word or chip \
            else ""
        phrase = "Where am I on %s?" % w["name"]
        data = card_of(w["row"]) if card_of else ""
        go = ('<span class="yopen apponly" data-card="%s"></span>' % E(data) if data else "") + \
            '<span class="webonly">%s</span>' % copy("Copy \u201cWhere am I?\u201d", phrase, "Copied \u201c%s\u201d. Paste it to your assistant." % phrase)
        rows += ('<div class="yrow%s" data-w="%s" role="row"%s><span class="ycell" role="cell">%s</span>'
                 '<span class="ycell ynext" role="cell">%s<small class="ymeta">%s</small></span>'
                 '<span class="ycell ystate" role="cell">%s%s</span><span class="ycell yact" role="cell">%s</span>%s</div>'
                 % (" yextra" if n >= YOUR_WORK_SHOWN else "", E(w["id"]), " hidden" if n >= YOUR_WORK_SHOWN else "", work_name_lines(w), nxt,
                    E(touched_said(w["moved"], today)), "" if state == "good" else pill(state), why, go, pop))
    head = ('<div class="yhead" role="row"><span role="columnheader">Thread</span><span role="columnheader">Next step</span>'
            '<span role="columnheader">State</span><span role="columnheader"><span class="sr">Action</span></span></div>')
    foot = ('<div class="yfoot"><button class="act" type="button" id="yall" aria-expanded="false" data-n="%d">Show all %d</button></div>'
            % (len(W), len(W))) if len(W) > YOUR_WORK_SHOWN else ""
    return card("your-work", "Your work", "%d piece%s, most recent first" % (len(W), "" if len(W) == 1 else "s"),
                '<div class="yrows" role="table" aria-label="Your work">%s%s</div>%s' % (head, rows, foot))


YOURWORK_CSS = r"""
.yhead,.yrow{display:grid;grid-template-columns:minmax(150px,.9fr) minmax(220px,2.4fr) minmax(150px,1fr) 120px;gap:6px 18px;align-items:start;padding:12px 0;border-bottom:1px solid var(--line)}
.yhead{padding:0 0 8px;font-size:13px;font-weight:600;color:var(--muted)}.yrow:last-child{border-bottom:0}.ycell{min-width:0}
.yrow:hover{background:color-mix(in srgb,var(--sunk) 55%,transparent)}
.yname{display:flex;flex-direction:column;min-width:0;overflow-wrap:anywhere}.ynext{overflow-wrap:anywhere;color:var(--ink2)}
.ymeta{display:block;margin-top:2px;font-size:13px;color:var(--muted)}
.yzone{font-size:13px;font-weight:400;color:var(--muted)}.yline{font-weight:600;color:var(--ink)}
.ystate{display:flex;flex-direction:column;align-items:flex-start;gap:6px}
.ywhy{display:flex;flex-wrap:nowrap;align-items:center;gap:6px;min-width:0;max-width:100%}.ywhy:empty{display:none}.ywhy .tchips{display:inline-flex;gap:4px;flex:none}.ywhy .chip{margin:0}
.ywait{color:var(--ink2);font-size:13px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ydot{color:var(--muted);flex:none}
.ystate:empty{display:none}.ypath{white-space:nowrap}.yfoot{display:flex;justify-content:center;padding:10px 0 0}.ytag{margin-left:6px;padding:0 6px;border-radius:8px;font-size:12px;font-weight:400;background:var(--wash);color:var(--accent)}
.yact{justify-self:end;position:relative}.yopen{display:inline-flex;align-items:center;gap:4px}
.ysplit{display:inline-flex;align-items:stretch}.ysplit>.act{border-top-right-radius:0;border-bottom-right-radius:0}
.ymore{position:relative;display:inline-flex}.ymore>summary.act{display:inline-flex;align-items:center;padding:0 8px;list-style:none;border-left-width:0;border-top-left-radius:0;border-bottom-left-radius:0}
.ymore>summary::-webkit-details-marker{display:none}
.ymenu{position:absolute;right:0;top:100%;z-index:6;margin-top:4px;display:flex;flex-direction:column;gap:2px;padding:6px;border:1px solid var(--line);border-radius:10px;background:var(--raise);box-shadow:var(--shadow);white-space:nowrap;min-width:180px}
.ymenu .act{justify-content:flex-start;gap:8px;border-color:transparent;background:transparent;text-align:left}.ymenu .act svg{width:16px;height:16px;flex:none}
.ymenu .act .ytick{margin-left:auto;color:var(--accent)}.ymenu .ydiv{border:0;border-top:1px solid var(--line);margin:4px 0;width:100%}
.yrow .tpop{grid-column:1/-1}
@media(max-width:720px){.yhead{display:none}.yrow{grid-template-columns:1fr auto;padding:14px 0}.ynext,.ystate{grid-column:1/-1}}
"""

# Draws each row's way to open from the card's data, as the Threads card's hover card does, and again when the
# pointer enters the row, so a change in Settings shows without a rebuild. One list open at a time.
YOURWORK_JS = r"""
(function(){
/* Show all (#559): the first ten rows show, the rest wait behind one button. The choice is this viewer's alone, kept in
   localStorage; with no storage the card opens on its ten. */
var all=document.getElementById('yall'),KEY='garrick-your-work-all';
if(all){var more=[].slice.call(document.querySelectorAll('#your-work .yextra'));
function kept(){try{return localStorage.getItem(KEY)==='1'}catch(e){return false}}
function keep(v){try{localStorage.setItem(KEY,v?'1':'0')}catch(e){}}
function show(on){more.forEach(function(r){r.hidden=!on});all.setAttribute('aria-expanded',on?'true':'false');all.textContent=on?'Show fewer':'Show all '+all.dataset.n}
show(kept());all.addEventListener('click',function(){var on=all.getAttribute('aria-expanded')!=='true';show(on);keep(on)})}
if(typeof Panel==='undefined'||!Panel.opener)return;
/* Draws each row's way to open from the card's data, as the Threads card's hover card does, and again when the
   pointer enters the row, so a change in Settings shows without a rebuild. One list open at a time. */
function draw(el){var o;try{o=JSON.parse(el.dataset.card)}catch(e){return}if(!el.querySelector('details[open]'))el.innerHTML=Panel.opener(o)}
[].forEach.call(document.querySelectorAll('.yrow'),function(r){var y=r.querySelector('.yopen[data-card]');if(!y)return;draw(y);r.addEventListener('mouseenter',function(){draw(y)})});
document.addEventListener('click',function(e){[].forEach.call(document.querySelectorAll('.ymore[open]'),function(d){if(!d.contains(e.target)||e.target.closest('.ymenu .act'))d.open=false})});
/* Enter on Resume resumes (it is a button). Alt+Down opens the menu, the arrows move in it, Escape shuts it */
document.addEventListener('keydown',function(e){var sp=e.target.closest&&e.target.closest('.ysplit');if(!sp)return;var d=sp.querySelector('details.ymore');if(!d)return;
var items=[].slice.call(d.querySelectorAll('.ymenu .act'));
if(e.altKey&&e.key==='ArrowDown'){e.preventDefault();d.open=true;if(items[0])items[0].focus();return}
if(!d.open)return;
if(e.key==='Escape'){d.open=false;d.querySelector('summary').focus();return}
if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();var at=items.indexOf(document.activeElement),n=e.key==='ArrowDown'?at+1:at-1;items[(n+items.length)%items.length].focus()}})})();
"""


def waiting_card(rows: List[dict], now: dt.datetime, needs: Optional[List[dict]] = None) -> str:
    """The Waiting on you now card: what waits on the user, each with an icon, one sentence, its zone, how late and
    one button. First the things the page knows from its records (`needs`: what failed, each zone's late actions,
    the warnings), then one row per waiting session, oldest first, which the app keeps current."""
    rows = sorted(rows, key=lambda r: (r.get("since") or "", r["id"]))
    needs = needs or []
    total = len(rows) + len(needs)
    meta = ("%d item%s" if needs else "%d session%s") % (total, "" if total == 1 else "s") if total else ""
    html = card("waiting-now", "Waiting on you now", meta,
                '<div class="wneeds" id="wneeds">%s</div><div class="wrows" id="wrows" aria-live="polite">%s</div>'
                % (need_groups(needs), "".join(waiting_row(r, now) for r in rows)))
    # Built out of sight (the class, since a card's own Hide uses `hidden`) when nothing waits (#510); GarrickWaiting shows it with the first row and hides it with the last.
    return html if total else html.replace('<details class="card" id="waiting-now"', '<details class="card nowait" id="waiting-now"', 1)


WAITING_CSS = r"""
.sh-livetag{display:inline-block;margin-right:6px;padding:0 6px;border-radius:8px;font-size:12px;font-weight:600;background:var(--wash);color:var(--accent)}
.wrow{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;padding:7px 0;border-bottom:1px solid var(--line)}
.wrow:last-child{border-bottom:0}.wname{font-weight:600}.wwhat,.wfor,.wwhere{color:var(--ink2);font-size:12.5px}
.wrow .act{margin-left:auto}
/* out of sight but in the accessibility tree, so its aria-live region announces the first row (#510) */
#waiting-now.nowait{position:absolute;width:1px;height:1px;margin:-1px;padding:0;border:0;overflow:hidden;clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap}
"""

WAITING_JS = r"""
(function(){var ex=document.getElementById('explore-go');if(ex)ex.addEventListener('click',function(){var g=document.getElementById('graph');if(!g)return;g.hidden=false;g.open=true;g.scrollIntoView({block:'start'})});
var box=document.getElementById('wrows');if(!box)return;var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
var ICON='<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6"/><path d="M8 4.6V8l2.2 1.4"/></svg>',
ARROW='<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><path d="M3 8h10M9 4l4 4-4 4"/></svg>',
NUM=['Nothing','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten'];
function since(s){var t=Date.parse(s);if(!t)return'';var m=Math.max(0,Math.floor((Date.now()-t)/60000));return m<1?'less than a minute':m<60?m+' min':m<2880?Math.round(m/60)+' h':Math.round(m/1440)+' days'}
function span(c,t){var e=document.createElement('span');e.className=c;e.textContent=t;return e}
function row(r){var d=document.createElement('div');d.className='wrow';d.dataset.id=r.id;
var name=r.thread||(r.folder||'').split('/').pop()||'A session',app=r.agent==='codex'?'Codex':'Claude Code',i=span('wico acc','');i.innerHTML=ICON;d.appendChild(i);
d.appendChild(span('wname',name));d.appendChild(span('wwhat',r.waiting_for||'an answer'));
var f=span('wfor',since(r.since));f.dataset.since=r.since||'';d.appendChild(f);
if(r.where==='cmux'){var b=document.createElement('button');b.type='button';b.className='act apponly';b.dataset.wgo=r.id;b.textContent='Go to it';d.appendChild(b)}
else d.appendChild(span('wwhere',(r.where==='desktop'?"Claude's desktop app":app)+', in '+((r.folder||'').split('/').pop()||'a folder')));
return d}
/* the lead sentence says what the card lists: what the build counted, and the sessions now */
function lead(sess){var L=document.getElementById('lead');if(!L)return;var st=+L.dataset.n||0,t=st+sess,h=document.getElementById('lead-h'),w=document.getElementById('lead-why'),g=document.getElementById('lead-go');
h.textContent=t<1?'Nothing needs you right now.':t===1?'One thing needs you.':(t<NUM.length?NUM[t]:t)+' things need you.';
var why=L.dataset.why?L.dataset.why.split(' · '):[];if(sess)why.push(sess+(sess===1?' session is':' sessions are')+' waiting for you');
w.textContent=why.join(' · ');
if(g){g.hidden=t<1;if(L.dataset.first!=='1'&&sess){g.setAttribute('href','#waiting-now');g.removeAttribute('data-tz-go');g.innerHTML='See who is waiting'+ARROW}}
var n=document.getElementById('tabn-overview');if(n){n.textContent=t||'';n.hidden=!t;n.setAttribute('aria-label',t+(t===1?' thing needs you':' things need you'))}}
function show(rows){rows=(rows||[]).filter(function(r){return r&&r.state==='waiting'}).sort(function(a,b){return(a.since||'')<(b.since||'')?-1:1});
box.textContent='';
rows.forEach(function(r){box.appendChild(row(r))});
var nd=document.getElementById('wneeds'),fixed=nd?nd.querySelectorAll('.wneed').length:0,total=rows.length+fixed;
var card=document.getElementById('waiting-now');if(card)card.classList.toggle('nowait',!total);
var m=document.querySelector('#waiting-now .meta');if(m)m.textContent=total?total+(fixed?(total===1?' item':' items'):(total===1?' session':' sessions')):'';
lead(rows.length)}
box.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-wgo]');if(b&&host)host.postMessage({waitingGo:b.dataset.wgo})});
setInterval(function(){box.querySelectorAll('.wfor').forEach(function(f){var t=since(f.dataset.since);if(t)f.textContent=t})},30000);
window.GarrickWaiting=function(data){show(data&&data.sessions?data.sessions:data)};
})();
"""


# ---- The look (#551): the font, and the rules that come last ---------------------------
# Plus Jakarta Sans (SIL OFL 1.1), Latin subset, three weights, kept in fonts/ beside this file and
# embedded in the page as data: URLs, so the page never asks the network for a font. A copy of this
# folder without fonts/ draws in the system's own sans-serif.
FONT_FILES = (("PlusJakartaSans-Regular.woff2", 400), ("PlusJakartaSans-SemiBold.woff2", 600), ("PlusJakartaSans-Bold.woff2", 700))
_FONT_CSS: Optional[str] = None


def font_css(folder: Optional[Path] = None) -> str:
    """The @font-face rules, each file embedded; "" where a file is missing or does not read, so the page
    keeps the system-ui stack of --sans instead of a half-embedded face."""
    global _FONT_CSS
    if folder is None and _FONT_CSS is not None:
        return _FONT_CSS
    import base64
    where = folder or Path(__file__).resolve().parent / "fonts"
    rules = []
    try:
        for name, weight in FONT_FILES:
            data = base64.b64encode((where / name).read_bytes()).decode("ascii")
            rules.append('@font-face{font-family:"Plus Jakarta Sans";font-style:normal;font-weight:%d;font-display:swap;'
                         'src:url(data:font/woff2;base64,%s) format("woff2")}' % (weight, data))
    except OSError:
        rules = []
    out = "\n".join(rules) + "\n" if rules else ""
    if folder is None:
        _FONT_CSS = out
    return out


# Last in the page's CSS, so each rule here settles what the blocks before it say at the same weight.
LOOK_CSS = r"""
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.hero .fig,.tile .val{font-family:var(--display)}
.hero .lbl,.tile .lbl,.tile .sub,.hint,.head .meta,.name small,.thread .t small,.tmeta,th,.legend{font-size:13px}
button.act,a.act,.tabs button,.seg button,.cog,.gbar button,.gbar .gfind,.gzsel,.switch,.zbtn,.moveto button{min-height:40px}
button.act,a.act{display:inline-flex;align-items:center;justify-content:center}
.appicons .act[data-k]{width:40px;height:40px}
.grip,.hide,.totab,.tick,.pchev,button.chip,.jname{position:relative}
.grip::after,.hide::after,.totab::after,.tick::after,.pchev::after,button.chip::after,.jname::after{content:"";position:absolute;inset:-9px -6px}
.trow.done .tick::after{inset:auto}
.act,.btn,.tabs button,.seg button,.cog,.chip,.card,.thread,.trow,.yrow{transition:background-color .18s ease,border-color .18s ease,color .18s ease}
/* status in words: a pill with an icon and a word, colour as support only */
.st{display:inline-flex;align-items:center;gap:6px;padding:2px 10px 2px 8px;border-radius:999px;font-size:13px;font-weight:600;line-height:1.45;white-space:nowrap;flex:none}
.st svg,.status .st svg{width:15px;height:15px;flex:none}
.st.good{color:var(--good);background:var(--good-wash)}.st.warn{color:var(--warning);background:var(--warning-wash)}
.st.crit{color:var(--critical);background:var(--critical-wash)}.st.idle{color:var(--ink2);background:var(--sunk)}
.item>.st{margin-left:auto}.chip .st{padding:0 8px 0 6px;margin-right:4px}
.jobs .row{grid-template-columns:18px minmax(0,1fr) 180px 86px minmax(200px,auto)}
@media (max-width:820px){.jobs .row{grid-template-columns:18px minmax(0,1fr) auto}}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
/* the Overview's lead: one sentence, its reasons, one button */
.lead{display:flex;align-items:flex-end;justify-content:space-between;gap:16px 24px;flex-wrap:wrap;margin:0 0 24px}
.lead h2{margin:0;font:700 30px/1.2 var(--sans);letter-spacing:-.02em;max-width:30ch;text-wrap:balance}
.lead p{margin:6px 0 0;color:var(--ink2);font-size:16px;max-width:70ch}.lead p:empty{display:none}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:40px;padding:0 16px;border-radius:8px;border:1px solid var(--line2);background:var(--raise);color:var(--ink);font:600 14px/1 var(--sans);cursor:pointer;text-decoration:none;white-space:nowrap}
.btn:hover{border-color:var(--ink2);text-decoration:none}.btn svg{flex:none}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}.btn.primary:hover{filter:brightness(1.08)}
/* Waiting on you now: an icon, one sentence, its zone, how late, one button */
.wrow{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:center;padding:10px 0}.wrow .wname{flex:1 1 220px}.wrow .wwhat,.wrow .wfor,.wrow .wwhere{flex:none}
.wico{width:36px;height:36px;border-radius:9px;display:grid;place-items:center;background:var(--wash);color:var(--accent)}.wico svg{width:18px;height:18px}
.wico.crit{background:var(--critical-wash);color:var(--critical)}.wico.warn{background:var(--warning-wash);color:var(--warning)}
.wrow .act{margin-left:auto}.wname{overflow-wrap:anywhere}.wico{flex:none}
/* the two groups of what waits (#559): Broken, then To do, which starts folded when something is broken */
.wgroup{margin:0 0 6px}.wgh{display:flex;align-items:baseline;gap:8px;margin:10px 0 2px;font-size:13px;font-weight:600;color:var(--muted);cursor:default;list-style:none}
details.wgroup>summary.wgh{cursor:pointer}details.wgroup>summary.wgh::-webkit-details-marker{display:none}
details.wgroup>summary.wgh::before{content:"\25B8";font-size:13px}details.wgroup[open]>summary.wgh::before{content:"\25BE"}
.wgn{font-weight:600;color:var(--ink2)}
/* a tab's count */
.tabs .n{min-width:22px;height:20px;padding:0 6px;border-radius:10px;background:var(--sunk);color:var(--ink2);font-size:12px;font-weight:700;display:inline-grid;place-items:center}
.tabs .n.warn{background:var(--warning-wash);color:var(--warning)}.tabs .n:empty,.tabs .n[hidden]{display:none}
/* a tab or a hidden card that holds trouble says so in words (LAYOUT_JS sets the dot's class and title) */
.tabs .dot.tr,.unhide .dot.tr{width:auto;height:auto;border-radius:999px;padding:0 8px;font-size:12px;font-weight:600;line-height:20px}
.tabs .dot.tr::after,.unhide .dot.tr::after{content:"Look soon"}.tabs .dot.tr.critical::after,.unhide .dot.tr.critical::after{content:"Act now"}
.tabs .dot.tr.warning,.unhide .dot.tr.warning{background:var(--warning-wash);color:var(--warning)}
.tabs .dot.tr.critical,.unhide .dot.tr.critical{background:var(--critical-wash);color:var(--critical)}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important;scroll-behavior:auto!important}}
"""


def build(ws: Path, now: Optional[dt.datetime] = None, folder: Optional[Path] = None,
          show_graph: bool = True, out: Optional[Path] = None,
          cmux: bool = False, flags: Tuple[str, ...] = (), launchers: Optional[Tuple[str, ...]] = None,
          also: Tuple[str, ...] = (), moved: Optional[Dict[str, str]] = None,
          managed: Optional[List[Path]] = None, cli: Optional[bool] = None, page_at: Optional[Path] = None,
          reuse_check: Optional[float] = None, waiting_now: Optional[List[dict]] = None) -> str:
    """The page. `launchers` says what this machine has (main() asks
    launchers_installed()); `cmux=True` alone
    stands for launchers=("cmux",). `flags` go into the rebuild command as
    given. `also` and `moved` reach effort.py: folders the workspace used to
    live in, and folders renamed or moved since, old path to new. `managed`
    names the files where a managed setting may switch Claude's local
    sessions off (main() passes this Mac's); without it only the record
    Continue keeps is read, as a test needs. `cli` says whether Claude Code's
    command-line tool is here (main() asks handoff.py's find_claude()): with
    it, Open in Claude on a thread goes through Continue's request (#180);
    without it, or unsaid, through the deep link. `page_at` is where the page
    goes (main() passes it): beside it the build keeps the check's result,
    which a build given `reuse_check` shows, whatever its age, instead of
    running the check (#382), and what the effort ledger read
    of each transcript, so one unchanged is not read again (#260). Without it
    nothing is kept, the check always runs and every transcript is read.
    `waiting_now` is the sessions waiting on the user now (main() reads them with
    waiting_rows()); without it the Overview's card is empty, so a build never
    reads this Mac's transcripts by itself."""
    now = now or dt.datetime.now()
    _NURTURE.pop(ws, None)                    # what nurture.py reads, it reads afresh each build
    launch = tuple(launchers) if launchers is not None else (("cmux",) if cmux else ())
    cmux = bool(launch)                       # a card carries its folder when anything can open it
    agent = load_agent(ws)
    folder = folder or jobs_dir(agent)
    link = Links(ws)
    T, TD, IB, C, R, W = (threads(ws), todo(ws), inboxes(ws), check(ws, check_file(page_at) if page_at else None, reuse_check, now),
                           repos(ws), wikis(ws))
    sched = launchd_jobs()       # only plists that run job.py: the jobs extra's, run or not
    J, L = jobs(folder, now, sched), ledger(agent, folder, now, sched)
    S = sessions(ws)                                       # None without the cmux extra
    qdata = questions_data(ws, C, now.date(), link)        # the Context tab (#224), None where it cannot be placed
    allowed = allowed_data(ws, link)                       # the Context tab's Allowed by you (#447): what the user let through, once

    # ---- what needs attention, worst first
    attn = []
    detail: Dict[str, dict] = {}               # what the Overview's rows know of a line beyond its text (#559), by that text
    check_age = kept_said(C, now)              # a kept result's counts say how old they are, wherever they show (#298)
    of_kept = " (%s)" % (check_age[:1].lower() + check_age[1:]) if check_age else ""
    if C and C.get("pending"):
        attn.append(("warning", "No check result yet", "#checks"))
        detail["No check result yet"] = {"label": "See the check"}
    elif C and C.get("failed"):
        attn.append(("critical", "The check did not run", "#checks"))
        detail["The check did not run"] = {"label": "See the check"}
    elif C and C.get("errors"):
        said_errors = "The check found %d error%s%s" % (C["errors"], "" if C["errors"] == 1 else "s", of_kept)
        attn.append(("critical", said_errors, "#checks"))
        detail[said_errors] = {"kind": "errors", "count": C["errors"], "label": "See the errors"}
    for j in J:
        if j["state"] == "critical":
            line = "%s: %s" % (j["name"], j["status"])
            attn.append(("critical", line, "#jobs"))
            detail[line] = job_need(j)
    if L:
        stopped: Dict[str, int] = {}          # one line per job, however many calls it lost
        capped_ask: Dict[str, int] = {}       # and one per cap of Ask's own, named (#294)
        for e in L["refused_today"]:
            job = str(e.get("job") or "a job")
            if L.get("ask_job") and job == L["ask_job"]:
                cap = ask_cap(e.get("refused"))
                capped_ask[cap] = capped_ask.get(cap, 0) + 1
                continue
            stopped[job] = stopped.get(job, 0) + 1
        for job, n in stopped.items():
            attn.append(("critical", "The spending cap stopped %s%s" % (job, "" if n == 1 else " %d times in 24 hours" % n), "#calls"))
        for cap, n in capped_ask.items():
            attn.append(("critical", ask_cap_stopped(cap, n), "#calls"))
        for tk, tt, th in attn:
            if th == "#calls" and tt not in detail:
                detail[tt] = {"label": "See the calls"}
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
        said_inbox = "%d item%s waiting in the inboxes" % (waiting, "" if waiting == 1 else "s")
        attn.append(("warning", said_inbox, "#inboxes"))
        detail[said_inbox] = {"kind": "inbox", "count": waiting, "label": "Open the inbox"}
    if C and C.get("warnings"):
        said_warn = "The check found %d warning%s%s" % (C["warnings"], "" if C["warnings"] == 1 else "s", of_kept)
        attn.append(("warning", said_warn, "#checks"))
        detail[said_warn] = {"kind": "warnings", "count": C["warnings"], "label": "See the warnings"}
    for j in J:
        if j["idle"]:
            line = "%s: %s" % (j["name"], j["status"])
            attn.append(("warning", line, "#jobs"))
            detail[line] = {"text": "%s has done nothing for a while" % j["title"], "label": "See the log"}
    for r in R:
        if r["dirty"] and r.get("since") and now - r["since"] > STALE_CHANGES:
            line = "%s: %s, the oldest changed %s" % (r["name"], say_files(r["dirty"]), age(r["since"], now))
            attn.append(("warning", line, "#repos"))
            # the zone in its column, never in the sentence (#559)
            detail[line] = {"kind": "files", "count": r["dirty"], "zone": r["name"], "tz": "", "label": "See the changes",
                            "text": "%d file%s not committed" % (r["dirty"], "" if r["dirty"] == 1 else "s"),
                            "late": "oldest changed %s" % age(r["since"], now)}
    notice = release_notice(ws)
    if notice:
        attn.append(("warning", notice[0], notice[1]))
        detail[notice[0]] = {"label": "See the release notes"}
    for f in drifted(ws):
        # a drift row leads to the row of its project, or of the thread the file is in, and offers Show both (#323)
        go = {"row": row_anchor(f["zone"], f["project"], f["thread"]), "up": row_anchor(f["zone"], f["project"])}
        attn.append(("warning", f["text"], {"href": "#" + go["row"], "go": go,
                                            "reveal": {"zone": f["zone"], "project": f["project"], "thread": f["ledger"],
                                                       "file": f["file"]} if f["both"] else None}))
        detail[f["text"]] = {"label": "See the file"}
    attn.sort(key=lambda a: a[0] != "critical")
    worst = "critical" if any(a[0] == "critical" for a in attn) else "warning" if attn else "good"
    # Where each trouble shows (#443): on its own card, so a tab carries a dot for the cards it holds. A newer Garrick
    # and a drifted shared file show at the head of the Repositories card; a thread's row, on its own.
    troubled = [(k, "repos" if isinstance(h, dict) or h.startswith("https://") else h.lstrip("#"), t) for k, t, h in attn]

    live = sum(len(z["rows"]) for z in T.values())
    parked_n = sum(len(z["parked"]) for z in T.values())
    names = short_names(T)
    aging = sum(1 for z in T.values() for r in z["rows"] if r["updated"] and (now.date() - r["updated"]).days > 14)
    week = sum(1 for z in T.values() for r in z["rows"] if r["updated"] and (now.date() - r["updated"]).days <= 7)
    open_actions = sum(sum(t["counts"].values()) for t in TD.values())

    flags_on = preview_flags(ws)
    acting = True       # the buttons that act; only a host that carries them out (the app) shows them
    lists = todo_list(ws, link, now.date())
    ZS = zone_styles(ws)        # each zone's colour and icon, from Settings › Zones
    GS = graph_styles(ws)       # each kind's colour, from Settings › Graph colours (#291)
    GK: List[Tuple[str, str, str]] = []
    # What each thread owes, on its own row: its next action, and whether that
    # action makes it urgent. Every card that says a thread is in trouble
    # reads this, and none of them reads its age.
    thread_actions(T, lists, C, ws)
    urgent = {(r["zone"], r["project"], "" if r["note"] == r["hub"] else r["thread"])
              for z in T.values() for r in z["rows"] if r.get("late")}      # Explore's ring: a late next action (#233)
    # Your work, the Overview's opening list (#503): the pieces of work, from what Garrick keeps already.
    HW = works(ws, T, now.date())

    # ---- the top row, pinned while the page scrolls: the name and when it was
    # built, the tabs, and the page's controls. There is no sidebar: the tabs
    # move between the work and the machinery, the cards are open on the page,
    # and the Status tab's own figures say whether anything needs attention.
    # With the cmux extra and cmux, the desk's buttons: Open
    # in cmux and Close session on cards, in the app only.
    DK = S is not None and acting and desk_ready()
    controls = ('<div class="bacts"><button class="cog" type="button" id="rebuild" aria-label="Rebuild the page" '
                'title="Copy the command that rebuilds the page" data-copy="%s" data-say="Copied. Run it in a terminal to rebuild the page.">%s</button>'
                '%s<button class="cog" type="button" id="open-settings" aria-label="Settings" title="Settings">%s</button>%s</div>'
                % (E(rebuild_command(ws, show_graph, out, flags)), REBUILD,
                   ('<button class="cog" type="button" id="explore-go" aria-label="Explore the graph" title="Explore the graph">%s</button>' % GRAPH_ICON)
                   if show_graph else "", GEAR, THEME_SEG))

    # ---- hero and tiles
    if attn:
        hero = '<a class="hero go" id="summary" href="#%s"><div class="fig">%s%d</div><div class="lbl">%s attention</div></a>' % (
            troubled[0][1], ICON[worst], len(attn), "thing needs" if len(attn) == 1 else "things need")
    else:
        hero = '<div class="hero" id="summary"><div class="fig" style="font-size:38px">%sAll clear</div><div class="lbl">Nothing failing, waiting or broken.</div></div>' % ICON["good"]
    # Each tile leads to the card that explains it, in whichever tab that card sits.
    tiles = [("Live threads", "%d" % live, "%d touched this week, %d untouched for 14+ days" % (week, aging), "threads")]
    if TD:
        tiles.append(("Todo", "%d" % open_actions, "across %d zone%s" % (len(TD), "" if len(TD) == 1 else "s"),
                      "todolist" if lists else "todo"))
    tiles += [("Inboxes", "%d" % waiting, "", "inboxes"),
              ("Context", ("%d<small>errors</small>%d<small>warnings</small>" % (C.get("errors", 0), C.get("warnings", 0)))
               if C and not C.get("failed") else "—", check_age if C else "check.py not found", "checks")]
    if L:
        cap = L["caps"]["calls_day"]
        tiles[-1] = ("Assistant calls, 24 h", "%d<small>%s</small>" % (L["day"], "of %g" % cap if cap else "no cap"),
                    "$%.2f at list price · %s" % (L["cost_day"], "$%g max per call" % L["budget"] if L["budget"] else "no per-call budget"),
                    "calls")
    top = '<div class="top" style="--tiles:%d">%s%s</div>' % (len(tiles), hero, "".join(
        '<a class="tile go" href="#%s"><div class="lbl">%s</div><div class="val">%s</div><div class="sub">%s</div></a>' % (h, E(a), b, E(c))
        for a, b, c, h in tiles))

    # ---- threads, one column per zone: a row per project, its threads folding
    # under it; a project with no thread notes is a thread row of its own. With
    # the effort ledger switched on, Time and Cost lay the last 30 days over it.
    EV = None
    store = folder / effort().STORE
    if flags_on["effort"]:
        try:
            EV = Effort(effort().ledger(ws, store, also=[Path(a).expanduser() for a in also], now=now, moved=moved or None,
                                        kept=effort_file(page_at) if page_at else None), now.date())
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
        # On the name's line, at its right, at most the two chips that say
        # something is owed or broken (#179), beside an unwrapped checkpoint's
        # (#186): the name gives way to its ellipsis before they do. The lists
        # they open sit at the foot of the row, shut until a click. The text
        # under a name, its project's, keeps its own line.
        chips = "" if parked else checkpoint_chip(r) + todo_chip(r, now.date()) + check_chip(r)
        pops = "" if parked else todo_pop(r, now.date(), acting) + check_pop(r, names[(r["zone"], r["project"], r["thread"])])
        under = "" if sub or r["thread"] == r["project"] else E(r["project"])     # a project that is its own thread says it once
        bar = '<span class="mu"></span>' if parked else \
            '<div class="fresh age mu" title="%s"><i style="width:%.1f%%"></i></div>' % (
                E("%s since its note moved, toward sixty days" % ("%d days" % days if days is not None else "No date")),
                max(3.0, min(100.0, (days if days is not None else 60) / 60 * 100)))
        return ('<div class="thread%s" data-ok="%d" data-card="%s"%s data-r="%s" id="%s"><div class="t"><a href="%s">%s</a>%s%s</div>%s'
                '<span class="num muted mu" style="text-align:right" title="%s">%s</span>%s%s</div>'
                % (" sub" if sub else "", 0 if k else 1,
                   E(thread_card(r, names, link, days, cmux, acting, S, now.date(), DK)),
                   ' data-a="%d"%s' % (place, EV.attrs(figures) if EV else "") if sub else "", touched(r),
                   row_anchor(r["zone"], r["project"], "" if r["note"] == r["hub"] else r["thread"]),
                   E(link(r["note"])), E(r["thread"]), live_dot(session_in(S, r["note"].parent), "it"),
                   ('<span class="tchips">%s</span>' % chips if chips else "") + ("<small>%s</small>" % under if under else ""),
                   bar, E(age_said(days, "its note")), "%dd" % days if days is not None else "—",
                   EV.cells(figures) if EV else "", pops)), k

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
            late = 0 if parked else sum(1 for r in items if r.get("late"))
            head = ('<div class="thread proj" data-ok="%d" data-card="%s" data-r="%s" id="%s"><div class="t"><button type="button" class="pchev" data-sub="%s" '
                    'aria-expanded="false" title="Show its %d thread%s">%s</button><a href="%s">%s</a>%s <span class="muted subn">%d thread%s%s%s</span></div>'
                    '%s<span class="num muted mu" style="text-align:right" title="%s">%s</span>%s</div>'
                    % (0 if k else 1, E(project_card(zone, project, items, newest)), touched(*items), row_anchor(zone, project), sid, n, "" if n == 1 else "s", CHEV,
                       E(hub_link), E(project), live_dot(session_in(S, (items[0]["hub"] or items[0]["note"]).parent), "the project"),
                       n, "" if n == 1 else "s", " · %d late" % late if late else "",
                       " · %d without a resume block" % bare if bare else "", bar, E(age_said(newest, "its newest thread")),
                       "%dd" % newest if newest is not None else "—", EV.cells(total) if EV else ""))
            out.append('<div class="tunit" data-a="%d"%s>%s<div class="subthreads tsort" id="%s" hidden>%s</div></div>'
                       % (i, EV.attrs(total) if EV else "", head, sid, "".join(subs)))
        return out, counts

    cols = ""
    for z, data in T.items():
        live_units, _ = units(z, data["rows"])
        held_units, _ = units(z, data["parked"], parked=True) if data["parked"] else ([], None)
        slug = re.sub(r"\W+", "-", z.lower())
        parked_block = ('<details class="parked tsort" id="parked-%s"><summary>%sParked<span class="n">%d</span></summary>%s</details>'
                        % (slug, CHEV, len(data["parked"]), "".join(held_units))) if data["parked"] else ""
        late = sum(1 for r in data["rows"] if r.get("late"))      # a red todo; a check has its own chip
        meta = "%d live" % len(data["rows"]) + (" · %d late" % late if late else "") + \
            (" · %d done" % data["done"] if data["done"] else "")
        cols += ('<details class="zone tsort" id="zone-%s" data-zone="%s" open><summary>%s<h3%s>%s</h3><span class="meta mu">%s</span>%s</summary>%s%s</details>'
                 % (slug, E(z), CHEV, zone_attr(z, ZS), zone_name(z, ZS), E(meta), EV.zone_meta(z) if EV else "",
                    "".join(live_units) or '<p class="muted">No live threads.</p>', parked_block))
    # The search box leads the row, New project and New thread follow it, and
    # what it finds takes the columns' place while a query is in it (#140).
    new_bar = ('<div class="mg-new">%s<button class="act" type="button" data-manage="new-project">New project</button>'
               '<button class="act" type="button" data-manage="new-thread">New thread</button></div>' % FIND_BOX)
    threads_card = card("threads", "Threads", "",
                        '<div class="tview" data-tm="updated" data-to="name">%s%s%s%s<div class="zones">%s</div>%s<p class="hint gsum mu">%d live · %d parked · by name · hover one for what to do</p></div>'
                        % (new_bar, FIND_LIST, torder_switch(), tview_switch() if EV else "", cols, EV.foot() if EV else "", live, parked_n))


    # ---- checks
    if C is None:
        body = '<p class="muted">No <code>System/tools/check.py</code> in this workspace.</p>'
    elif C.get("pending"):
        body = '<p class="muted">No check result yet. A build by hand, on schedule or by the app runs the check and keeps it.</p>'
    elif C.get("failed"):
        body = '<div class="clean">%sThe check did not run. Run <code>python3 System/tools/check.py</code> to see why.</div>' % ICON["critical"]
    else:
        body = ""
    # A caption says what is wrong, so a folded card still tells it (#231), and nothing when nothing is.
    listed_kept = ""
    found = " · ".join("%d %s%s" % (n, w, "" if n == 1 else "s") for n, w in
                       (((C or {}).get("errors", 0), "error"), ((C or {}).get("warnings", 0), "warning")) if n)
    if check_age:                              # a tool's rebuild showed the last result rather than run the check (#260)
        body = '<p class="hint ckept">%s; a build by hand or on schedule runs it again.</p>' % E(check_age) + body
        listed_kept = '<p class="hint ckept">%s; a build by hand or on schedule runs it again.</p>' % E(check_age)
    # The card says what needs the user (#530); the figure is one line (#541), the list is the queue's questions.
    history, said_scope = debt_history(ws, now.date())
    listed = bool(C) and not C.get("failed") and not C.get("pending")
    queues = finding_queues(ws, history, C, now.date(), said_scope)
    fq = None
    if queues is not None or qdata:
        try:
            fq = queue_mod()
        except Exception:              # no queue module: the card goes without a queue, as before
            fq = None
    queues_failed = queues is None
    asked = fq.asked_questions(qdata, fq.later_hidden(ws, now.date())) if fq and qdata else {}
    work_places = {sc: work_place(sc, said_scope) for sc in ["Wikis/Knowledge"] + ["Zones/" + z for z in (qdata or {}).get("buckets", {})]} if qdata else {}
    if fq and qdata:        # answers the night could not work in come back as a question of their own place (#550)
        for sc, held in fq.held_answers(ws, work_places, {sc: answered_in(qdata, sc) for sc in work_places}, fq.later_hidden(ws, now.date())).items():
            asked.setdefault(sc, []).extend(held)
    if fq and qdata and (queues is not None or any(asked.values())):
        # the wiki's own questions join the findings, each in the queue of its own zone or wiki (#542). A findings read
        # that failed leaves `queues` None: start from nothing so the wiki's questions still show, and Nurture's lines
        # stand for the findings (need_lines' `failed`), so a failed read never reads as "Nothing needs you."
        queues = fq.with_asked(queues if queues is not None else {}, asked)
    elif queues is None:
        fq = None
    queue_names = {sc: scope_title(sc, said_scope) for sc in (queues or {})}
    checks_card = card("checks", "Context", ("no result yet" if C.get("pending") else "did not run") if C and C.get("failed") else found,
                       need_lines(ws, history, said_scope, queues, qdata, failed=queues_failed and queues is not None)
                       + debt_line(history) + override_note(ws, wall_place(queues)) + (listed_kept if listed else body),
                       chip=trend_chip(trend_word(history, now.date())))
    queue_view = fq.dialog(str(ws), {sc: qs for sc, qs in queues.items() if qs}, queue_names, now.date().isoformat(), work_places) if fq else ""

    # ---- open actions and inboxes
    tb = ""
    for z, t in TD.items():
        scale = max(list(t["counts"].values()) + [1]) * 1.08
        # one way to the zone's list (#235): the Todo tab, which keeps Open Todo.md for the file
        opener = ('<a class="act" href="#todolist" data-tz-go="%s" title="Open %s&#39;s list on the Todo tab">Open</a>' % (E(z), E(z))
                  if lists else '<a class="act" href="%s" title="Open %s/Todo.md">Open</a>' % (E(link(t["file"])), E(z)))
        tb += '<div class="zt"><b%s>%s</b>%s</div>' % (zone_attr(z, ZS), zone_name(z, ZS), opener)
        if not t["counts"]:
            tb += '<p class="muted" style="font-size:12px;margin:2px 0">Nothing open.</p>'
        for sec, n in t["counts"].items():
            tb += '<div class="bullet"><span class="ink2">%s</span><div class="bar"><i style="width:%.1f%%"></i></div><span class="num">%d</span></div>' % (E(sec), n / scale * 100, n)
    todo_card = card("todo", "Todo", "", tb) if TD else ""
    ib = "".join('<a class="item" data-ok="%d" href="%s"><div class="name%s">%s<small>%s</small></div>%s</a>' % (
        0 if n else 1, E(link(f)), zone_class(name, ZS), zone_name(name, ZS),
        "%d waiting" % n if n else "empty", pill("wait" if n else "good")) for name, f, n in IB)
    waits = ('<div class="gacts">%s</div>' % request_button("Process the Inbox", "process the inbox", ws)) if any(n for _, _, n in IB) else ""
    inbox_card = card("inboxes", "Inboxes", "", '<div class="tiles">%s</div>%s' % (ib, waits))

    # ---- jobs and calls, only when the jobs extra is in use
    jobs_card = calls_card = ""
    if J:
        groups = {True: [], False: []}         # Garrick's jobs and the user's, by the plist's label (garrick_job)
        for i, j in enumerate(J):
            strip = "".join('<i class="%s" tabindex="0" data-tip="%s"></i>' % (s, E(t)) for s, t in day_cells(j["runs"], now, j["quiet"]))
            last = age(j["when"], now) if j["when"] else "never"
            said = "running now" if j["running"] else j["status"]      # its lock is held: a run is under way
            ok = j["state"] in ("good", "none")
            about = '<small class="about" data-tip="%s">%s</small>' % (E(j["about"]), E(j["about"])) if j["about"] else ""
            # a job not run yet is neither fine nor wrong: a hollow mark, and out of "Only what needs attention"
            # the name opens the job's panel below its row (#273), never its log through file://
            groups[j["garrick"]].append((ok,
                '<div class="row" data-ok="%d">%s<div class="name"><button type="button" class="jname" aria-expanded="false" '
                'aria-controls="jp-%d">%s</button>%s<small>%s</small></div><div class="strip">%s</div>'
                '<div class="ink2 num"%s>%s</div><span class="status%s" data-tip="%s">%s%s</span></div>%s'
                % (ok, ICON[j["state"]], i, E(j["name"]), about, E(j["schedule"]), strip,
                   ' data-tip="took %ss"' % E(str(j["seconds"])) if j["seconds"] is not None else "", E(last), " running" if j["running"] else "",
                   E("Last run: " + j["status"]) if j["running"] else "", pill("late" if j["status"].startswith("late") else j["state"]), E(said) + (
                       ' <button class="act tacts" type="button" data-act="%s" data-say="Starting %s…">Run now</button>'
                       % (E(json.dumps({"verb": "run", "job": j["name"]})), E(j["name"]))
                       if acting and j["name"] in sched and not j["running"] else ""),
                   job_panel(j, i, ok, link(j["log"])))))
        behind = sum(1 for j in J if j["state"] == "critical" and j["status"].startswith("late"))   # not run on time
        failed = sum(1 for j in J if j["state"] == "critical") - behind
        jobs_card = card("jobs", "Scheduled jobs", " · ".join("%d %s" % (n, w) for n, w in ((failed, "failed"), (behind, "late")) if n),
                         '<div class="rows jobs">%s</div>' % "".join(     # each cell's tooltip says its day (#232)
                             '<div class="jgroup" data-ok="%d"><h3>%s</h3>%s</div>' % (all(ok for ok, _ in rows), head, "".join(r for _, r in rows))
                             for head, rows in (("Garrick's", groups[True]), ("Yours", groups[False])) if rows))
    if L:
        c = L["caps"]
        def against(text, cap, unit=""):     # "3 / 48", or "3, no cap" when the cap is 0
            return "%s / %s%g" % (text, unit, cap) if cap else "%s, no cap" % text
        # where the caps were read, in the meters' tooltip; the per-call budget a figure beside them (#232)
        jobs_word = "Job calls" if L.get("ask") else "Calls"     # with Ask on caps of its own, these are the jobs'
        m = (meter(L["day"], c["calls_day"], jobs_word + ", last 24 h", against("%d" % L["day"], c["calls_day"]), L["caps_from"])
             + meter(L["hour"], c["calls_hour"], jobs_word + ", last hour", against("%d" % L["hour"], c["calls_hour"]), L["caps_from"])
             + meter(L["cost_day"], c["cost_day"], ("Job cost" if L.get("ask") else "Cost") + ", last 24 h",
                     against("$%.2f" % L["cost_day"], c["cost_day"], "$"), L["caps_from"]))
        A = L.get("ask")
        if A:                                   # Ask's own caps, beside the jobs' (#282)
            k = A["caps"]
            m += (meter(A["hour"], k["calls_hour"], "Ask, last hour", against("%d" % A["hour"], k["calls_hour"]), A["caps_from"])
                  + meter(A["day"], k["calls_day"], "Ask, last 24 h", against("%d" % A["day"], k["calls_day"]), A["caps_from"])
                  + meter(A["cost_day"], k["cost_day"], "Ask cost, last 24 h", against("$%.2f" % A["cost_day"], k["cost_day"], "$"),
                          A["caps_from"]))
        m += ('<div class="m" data-tip="What one Claude call may spend before it is stopped: GARRICK_MAX_CALL_USD">'
               '<span class="ink2">Per call</span><span class="num">%s</span></div>' % ("$%g max" % L["budget"] if L["budget"] else "no cap"))

        def refused(tools):
            """A refused tool the deny list names is red; one no allow rule named is amber."""
            return "".join('<span class="chip" title="%s">%s%s</span> ' % (
                "On the deny list" if denied_by_list(t, L["deny"]) else "Not allowed for this job",
                pill("critical" if denied_by_list(t, L["deny"]) else "warning"), E(t))
                for t in sorted(tools)) or '<span class="muted">none</span>'
        trs = "".join('<tr data-ok="%d"><td>%s</td><td class="r">%d</td><td class="r">$%.2f</td><td class="r">%s</td><td>%s</td>'
                      '<td class="r">%d</td><td class="r">%d</td></tr>'
                      % (0 if d["denied"] or d["failed"] or d["refused"] else 1, E(job), d["calls"], d["cost"],
                         "%.1f" % (sum(d["turns"]) / len(d["turns"])) if d["turns"] else "–", refused(d["denied"]), d["failed"], d["refused"])
                      for job, d in sorted(L["by"].items(), key=lambda kv: (-kv[1]["cost"], kv[0])))
        table = ('<div class="scroll"><table><thead><tr><th>Job</th><th class="r">Calls</th><th class="r">Cost</th>'
                 '<th class="r" title="Turns per call, on average">Turns</th><th>Refused tools</th>'
                 '<th class="r">Failed</th><th class="r">Capped</th></tr></thead><tbody>%s</tbody></table></div>' % trs) if trs else '<p class="muted">No calls yet.</p>'
        calls_card = card("calls", "Assistant calls", "",
                          '<div class="meters">%s</div>%s<div style="margin-top:14px">%s</div>' % (m, cost_chart(L), table))

    # ---- repositories and wikis
    def waiting_long(r):
        return bool(r["dirty"] and r.get("since") and now - r["since"] > STALE_CHANGES)
    rr = "".join('<div class="item" data-ok="%d" data-tip="%s"><div class="name">%s<small>%s</small></div>%s</div>' % (
        0 if r.get("unread") or waiting_long(r) else 1,
        E("git status failed or took over 30 seconds, so its changes are not known" if r.get("unread") else
          "; ".join(x for x in ("last commit " + (age(r["last"], now) if r["last"] else "never"), say_kinds(r["changes"]),
                                "the oldest change made " + age(r["since"], now) if r["dirty"] and r.get("since") else "") if x)),
        E(r["name"]), "could not be read" if r.get("unread") else say_files(r["dirty"]) if r["dirty"] else "all committed",
        pill("warning" if r.get("unread") or waiting_long(r) else "good" if not r["dirty"] else "none")) for r in R)
    changed = sum(1 for r in R if r["dirty"])
    notices = "".join(attn_row(k, t, h) for k, t, h in attn if isinstance(h, dict) or h.startswith("https://"))
    repos_card = card("repos", "Repositories", "%d with changes" % changed if changed else "",
                      ('<div class="attn" id="notices">%s</div>' % notices if notices else "")
                      + (('<div class="tiles">%s</div>%s' % (rr, "".join(repo_changes(ws, r) for r in R if r["dirty"])))
                         if rr else '<p class="muted">No git repositories found.</p>'))
    def newest(w):
        if not w["when"]:
            return LOG_NOT_READ if w.get("unread") else "nothing logged yet"
        title = ('<a href="%s">%s</a>' % (E(link(w["page"])), E(w["title"]))) if w["page"] else E(w["title"])
        return "%s · %s" % (E(w["when"].strftime("%d %b %Y").lstrip("0")), title)
    wr = "".join('<div class="row" style="grid-template-columns:1fr"><div class="name"><a href="%s">%s</a><small style="white-space:normal">%s</small></div></div>' % (
        E(link(w["log"])), E(w["name"]), newest(w)) for w in W)
    wikis_card = card("wikis", "Wikis", "", '<div class="rows">%s</div>' % wr if wr else '<p class="muted">No wiki logs found.</p>')

    # ---- the graph, behind Explore at the foot of the Overview: it keeps every
    # mode it has, and folds shut so the tab opens on the work instead. A
    # window that has opened or shut this card keeps its own choice, as it
    # does for every other fold.
    graph_card = ""
    if show_graph:
        GR = graph(ws, T, link, now, cmux, acting, S, DK, urgent)
        GK = [(k, plural(k), c) for k, c in zip(GR["keys"], GR["colors"])]    # each kind as shipped, for Settings (#291)
        GR["colors"] = graph_colours(GR["keys"], GR["colors"], GS)
        core = sum(1 for n in GR["nodes"] if n["c"])
        # each kind a toggle that shows or hides it (#250), then the two states
        legend = "".join('<button type="button" data-k="%d" aria-pressed="true"><i style="background:%s"></i>%s</button>'
                         % (i, GR["colors"][i], E(plural(GR["keys"][i]))) for i, _ in GR["kinds"])
        legend = ('<div class="legend glegend">%s<span><i class="ring" style="border-color:var(--critical)"></i>Next action late'
                  '</span><span><i style="opacity:.3;background:var(--muted)"></i>Parked</span></div>' % legend)
        data = script_json(GR)
        places = list(dict.fromkeys(n["z"] for n in GR["nodes"]))
        places = sorted(places, key=lambda z: (z != "Work", z not in T, places.index(z)))      # Work, the other zones, then the wikis
        # one place at a time, the zones and the wikis under a heading each (#250)
        zoned = [z for z in places if GR["pr"].get(z, "").startswith("Zones/")]
        switch = "".join('<optgroup label="%s">%s</optgroup>' % (head, "".join(
            '<option value="%s"%s>%s</option>' % (E(z), zone_attr(z, ZS), E(z)) for z in group))
            for head, group in (("Zones", zoned), ("Wikis", [z for z in places if z not in zoned])) if group)
        # a select cannot draw an icon in its options, so the chosen place's icon sits over its left edge
        marks = "".join('<span class="gzi%s" data-z="%s" hidden>%s</span>' % (zone_class(z, ZS), E(z), zone_icon(ZS[z]["icon"]))
                        for z in places if ZS.get(z, {}).get("icon"))
        graph_card = card("graph", "Explore", "",
                          '<div class="gwrap"><canvas id="gcv" role="img" aria-label="Graph of the notes in a zone or wiki, and the links between them"></canvas>'
                          '<div class="gbar"><span class="gzw">' + marks + '<select class="gzsel" aria-label="Place">' + switch + '</select></span>'
                          '<input type="search" class="gfind" id="gfind" placeholder="Find a note" aria-label="Find a note on the graph" autocomplete="off" spellcheck="false">'
                          '<button id="gfmore" type="button" hidden></button><button id="gpark" type="button"></button></div>'
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
    on_context = bool(qdata and checks_card)           # Checks sits under the findings it explains (#443)
    here = [checks_card] if on_context else []
    machinery = [c for c in (jobs_card, calls_card, None if on_context else checks_card, repos_card, wikis_card) if c]
    def slots(name, left="", right=""):
        return ('<div class="grid"><div class="slot stack left" data-slot="%s-left">%s</div>'
                '<div class="slot stack right" data-slot="%s-right">%s</div></div>' % (name, left, name, right))
    def section(name, hidden, body):
        return '<section class="tab" id="tab-%s"%s>%s</section>' % (name, " hidden" if hidden else "", body)
    # The Overview opens on the Threads card: each live thread with at most
    # its `todo` and `check` chips (#179), listed by name or most recently
    # touched first (#143). Todo on the left, the inboxes on the right,
    # and the graph behind Explore at the foot. A workspace with no project
    # yet has no work to show, so Start here leads instead. A browser that
    # still holds what it kept for A thought, the card #143 took away, shows it
    # once above the cards (THOUGHT_LEFT).
    #
    # This is the order a window with nothing saved gets. A window that has
    # dragged, moved or hidden a card keeps every card it placed exactly where
    # it placed it (LAYOUT_JS), and Reset view is what adopts this order.
    anything = any(z["rows"] or z["parked"] or z["done"] for z in T.values())
    needs = needs_you(attn, lists, now.date(), detail)          # what waits on the user, from what the page knows; the lead counts it (#551)
    lead = waiting_card(waiting_now or [], now, needs) + ((work_list_card(HW, now.date(), acting, lambda r: thread_card(
                                                        r, names, link, (now.date() - r["updated"]).days if r["updated"] else None,
                                                        cmux, acting, S, now.date(), DK)) if HW else "") + threads_card
                                                    if anything else start_card() + threads_card)
    overview = section("overview", False, '%s<div class="grid"><div class="slot full" data-slot="top">%s</div>'
                       '<div class="slot stack left" data-slot="left">%s</div><div class="slot stack right" data-slot="right">%s</div>'
                       '<div class="slot full" data-slot="bottom">%s</div></div>' % (THOUGHT_LEFT + lead_block(needs, len(waiting_now or [])), lead, todo_card,
                          inbox_card, graph_card))
    # Every tab with content has a left and a right slot below its own content (#443).
    status_tab = section("status", True, '%s<div class="onlybar"><label class="switch"><input type="checkbox" id="only"> Only what needs attention</label></div><div class="grid"><div class="slot stack left" data-slot="status-left">%s</div>'
                         '<div class="slot stack right" data-slot="status-right">%s</div><div class="slot full" data-slot="status-bottom"></div></div>'
                         % (top, "".join(machinery[0::2]), "".join(machinery[1::2])))
    late = sum(z["late"] for z in lists)
    trouble = any(j["state"] == "critical" for j in J) or bool(C and (C.get("errors") or (C.get("failed") and not C.get("pending")))) or bool(L and L["refused_today"])
    tabs = ('<div class="tabs" role="tablist"><button type="button" role="tab" data-tab="overview">Overview</button>%s'
            '<button type="button" role="tab" data-tab="status">Status</button>%s'
            '<button type="button" role="tab" data-tab="guide">Guide</button></div>'
            % ('<button type="button" role="tab" data-tab="todo">Todo<span class="n">%d</span>%s</button>'
               % (sum(z["open"] for z in lists), '<span class="dot critical" title="late"></span>' if late else "") if todo_tab else "",
               questions_mod().tab_button() if qdata else ""))
    # Each tab a count (#551). A count of something late or that needs you takes the warning colour and says so to a screen reader.
    sessions_n = len(waiting_now or [])
    tabs = tabs.replace('data-tab="overview">Overview</button>', 'data-tab="overview">Overview%s</button>'
                        % tab_badge("tabn-overview", len(needs) + sessions_n, " thing needs you", " things need you", True), 1)
    tabs = tabs.replace('data-tab="status">Status</button>', 'data-tab="status">Status%s</button>'
                        % tab_badge("tabn-status", len(attn), " thing needs attention", " things need attention", bool(attn)), 1)
    tabs = tabs.replace('<span class="dot critical" title="late"></span>', tab_badge("tabn-late", late, " action is late", " actions are late", True, "%d late"), 1)
    header = bar(mark(full=False, attrs=' class="mark" aria-hidden="true"'), E(NAME), now.strftime("%a %d %b, %H:%M"), tabs, controls)
    md = menu_data(T, names, link, cmux, trouble, S, DK, bool(cli))
    if qdata:
        md["questions"] = questions_mod().counts_of(qdata)       # the open count of each zone, for the menu's Questions row
    if cmux:          # an app to open folders in; the app shows the row only with an assistant among them
        md["intake"] = {"n": "Process the Inbox", "w": "process the inbox", "f": str(ws), "c": sum(n for _, _, n in IB),
                        "b": [[name, n] for name, _, n in IB if n]}   # what waits where, Meetings included
    menu = '<script type="application/json" id="menu-data">%s</script>' % script_json(md)
    menu += '<script type="application/json" id="trouble-data">%s</script>' % script_json([list(t) for t in troubled])
    # What RELOAD_JS compares a button's expectation with: the parked threads
    # and, with the cmux extra, the folders a session is open in.
    folders = {f for z in T.values() for r in z["rows"] + z["parked"] for f in (r["note"].parent, (r["hub"] or r["note"]).parent)}
    state = {"parked": sorted({"%s/%s" % (r["zone"], r["rel"]) for z in T.values() for r in z["parked"]}
                              | {"%s/%s/%s.md" % (zone, p, p) for zone, z in T.items() for p in z.get("held", ())}),
             "live": sorted(str(f) for f in folders if session_in(S, f)),
             # every live and parked note by its path, for a rename from the page (#184)
             "notes": sorted({"%s/%s" % (r["zone"], r["rel"]) for z in T.values() for r in z["rows"] + z["parked"]}
                             | {"%s/%s/%s.md" % (r["zone"], r["project"], r["project"]) for z in T.values()
                                for r in z["rows"] + z["parked"] if r["hub"]})}
    menu += '<script type="application/json" id="state-data">%s</script>' % script_json(state)
    menu += '<script type="application/json" id="manage-data">%s</script>' % script_json(manage_data(T, workspace_context(ws), acting))
    menu += '<script type="application/json" id="find-data">%s</script>' % script_json(find_data(T, link, ZS, cmux, now.date()))
    shared = shared_launchers(ws)
    if shared is not None:
        menu += '<script type="application/json" id="launch-settings">%s</script>' % script_json(shared)
    guide_body, guide_pages = guide_tab(ws)
    main = ('<main><div class="stale" id="stale"></div>%s%s%s%s%s</main>%s'
            % (overview, section("todo", True, todo_tab + slots("todo")) if todo_tab else "", status_tab,
               section("questions", True, questions_mod().tab(slots("context", "".join(here)))) if qdata else "",
               section("guide", True, guide_body), menu))
    # The menu's script in an element of its own, and the graph's: an error
    # anywhere else on the page stops only the script it is in, and the app
    # still hears what its menu lists.
    # MANAGE_JS after the page's own, so it wraps the GarrickActed that PARK_JS sets,
    # FIND_JS after it, so its results are drawn again once a row has moved,
    # and WORK_JS after all three. NOTE_JS, Explore's Preview, in an element of its
    # own before the graph's, whose cards offer it. The Guide's pages come last of
    # all, after every script, so reading past them never holds up the tabs that show the work.
    scripts = [RELOAD_JS + PANEL_JS + LAYOUT_JS + JS + PARK_JS + RENAME_JS + TVIEW_JS + TCHIP_JS + TADD_JS + TODO_JS + MENU_SETTINGS_JS + HOME_JS + YOURWORK_JS + JOBS_JS,
               MANAGE_JS, FIND_JS, WORK_JS, WAITING_JS, NOTIFY_JS, MEMORY_JS, RELEASE_JS, MENU_JS, CHECKS_JS, queue_mod().QUEUE_JS if queue_view else "", CONTEXT_JS if qdata or 'id="nzone"' in checks_card else "", questions_mod().CX_JS if allowed else "", guide_mod().GUIDE_JS,
               NOTE_JS if show_graph else "", GRAPH_JS + FOLLOW_JS if show_graph else ""]
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title>%s<style>%s</style></head><body data-built="%s" data-launchers="%s"%s><div class="app">%s%s</div>%s'
            '<div id="tip" role="tooltip"></div><div id="toast" role="status"></div><div id="work" role="status" hidden></div>%s%s</body></html>' % (
                E(NAME), favicon(), font_css() + CSS + DEBT_CSS + (queue_mod().QUEUE_CSS if queue_view else "") + SETTINGS_CSS + BAR_CSS + TVIEW_CSS + TADD_CSS + TODO_CSS + MANAGE_CSS + FIND_CSS + WORK_CSS + HOME_CSS + YOURWORK_CSS + WAITING_CSS + (questions_mod().CX_CSS if allowed else "") + MEMORY_CSS + guide_mod().GUIDE_CSS + zone_css()
                + (NOTE_CSS if show_graph else "") + LOOK_CSS,
                now.isoformat(timespec="seconds"), E(",".join(launch)), ' data-cli="1"' if cli else "", header, main, settings(ws, launch, tuple(T), ZS, show_graph, link, GK, GS, allowed) + queue_view,
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


# What this file was when the build loaded it. A build that finds it changed
# just before it writes has drawn the page with code an update has since
# replaced, and builds again from the file on disk instead (#213).
SELF = Path(__file__).resolve()
RERUN = "GARRICK_STATUS_RERUN"      # set for the build started again, so it starts again only once


def own_stamp() -> Optional[Tuple[int, int, int]]:
    """This file as it is on disk now: its inode, size and modification time."""
    try:
        st = os.stat(str(SELF))
    except OSError:
        return None
    return (st.st_ino, st.st_size, st.st_mtime_ns)


STARTED = own_stamp()


def rerun(argv: Optional[List[str]]) -> int:
    """status.py changed while this build ran, so the page it drew is the old
    code's and is not written. The build starts again from the file on disk,
    without --settle, since its wait is over: in place of this process when
    it was run as a command, as a process of its own when main() was called
    with arguments. A build already started again that finds the file
    changed once more writes nothing and leaves the page to the next build,
    so a file that keeps changing cannot keep it going."""
    if os.environ.get(RERUN):
        print("status: status.py changed again while the page was being built, so nothing was written; "
              "the next build draws it.", file=sys.stderr)
        return 75
    words, given = [], list(sys.argv[1:] if argv is None else argv)
    while given:
        w = given.pop(0)
        if w == "--settle":
            given[:1] = []
        elif not w.startswith("--settle="):
            words.append(w)
    python = sys.executable or "python3"
    cmd = [python, str(SELF)] + words
    env = dict(os.environ, **{RERUN: "1"})
    print("status: status.py changed while the page was being built; building it again with the new one.", file=sys.stderr)
    if argv is None:
        sys.stdout.flush()
        sys.stderr.flush()
        os.execvpe(python, cmd, env)
    return subprocess.call(cmd, env=env)


def write_page(out: Path, text: str) -> None:
    """Put the page in place whole. Each build writes a temporary file of its
    own beside it and renames that over the page, so builds that overlap never
    share one: the last to finish wins, and none fails on another's rename. A
    write that fails takes its temporary file away with it."""
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), prefix=out.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        mask = os.umask(0o022)
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)         # as a plain write would leave it, not mkstemp's owner-only
        os.replace(tmp, str(out))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# The options that shape the page. A build stores the ones it was given beside
# the page, and a build with --same-flags draws with them, as scaffold.py's and
# correct.py's do: the page a tool rebuilds stays as the app or the plugin
# last drew it, whatever flags they pass (#246).
PAGE_FLAGS = ("no_cmux", "no_graph", "also", "moved")
# Flags a Garrick before 0.51.0 took, which an app or a plugin built then may
# still pass, or a page built then may have stored: read and ignored, so the
# build that meets them still draws the page, and never stored again (#318).
GONE_FLAGS = ("obsidian", "no_obsidian")


def flags_file(out: Path) -> Path:
    """Where the flags of the page at `out` are kept: beside it, never committed."""
    return out.with_name(out.stem + ".flags.json")


def page_words(args: argparse.Namespace, moved: Dict[str, str]) -> List[str]:
    """The command-line words that gave this build its page flags."""
    words = [f for f, on in (("--no-cmux", args.no_cmux), ("--no-graph", args.no_graph)) if on]
    return (words + [w for a in args.also for w in ("--also", a)]
            + [w for o, n in moved.items() for w in ("--moved", "%s=%s" % (o, n))])


def stored_words(path: Path) -> List[str]:
    """The page flags the last build stored, or [] where none did or the file
    is not one a build wrote."""
    try:
        words = json.loads(path.read_text(encoding="utf-8")).get("args")
    except (OSError, ValueError, AttributeError):
        return []
    return words if isinstance(words, list) and all(isinstance(w, str) for w in words) else []


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build the status page for a Garrick workspace.")
    ap.add_argument("--workspace", help="the workspace folder (default: GARRICK_WORKSPACE, or the folder this runs in)")
    ap.add_argument("--out", help="where to write the page (default: System/generated/status.html). The files a build "
                    "keeps go beside it, named after it: status.check.json, the check's last result, and status.effort.json, "
                    "every session's working folder and the paths it wrote, in every zone. Inside a zone, a commit can carry "
                    "them into its history")
    ap.add_argument("--obsidian", metavar="VAULT", help=argparse.SUPPRESS)       # GONE_FLAGS: read and ignored
    ap.add_argument("--no-obsidian", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-cmux", action="store_true", help="leave Open in cmux out, even where cmux is installed")
    ap.add_argument("--open", action="store_true", help="open the page when it is built")
    ap.add_argument("--no-graph", action="store_true", help="leave the graph out: the page then reads nothing but frontmatter")
    ap.add_argument("--settle", type=float, metavar="SECONDS", help="wait this long, and build only if no other build "
                    "was asked for meanwhile: a burst of requests makes one page")
    ap.add_argument("--also", action="append", default=[], metavar="FOLDER",
                    help="for effort: a folder the workspace used to live in, read as the workspace (repeatable)")
    ap.add_argument("--moved", action="append", default=[], metavar="OLD=NEW",
                    help="for effort: a folder renamed or moved, its old path and its path in the workspace now (repeatable)")
    ap.add_argument("--reuse-check", type=float, nargs="?", const=float("inf"), metavar="SECONDS", help="show the check's last result, kept beside the "
                    "page, whatever its age, and never run the check: a tool's rebuild. The value is accepted and ignored")
    ap.add_argument("--same-flags", action="store_true", help="build with the page flags the last build stored, as a tool's "
                    "rebuild does; not with --no-cmux, --no-graph, --also or --moved")
    args = ap.parse_args(argv)
    given = ["--" + k.replace("_", "-") for k in PAGE_FLAGS if getattr(args, k)]
    if args.same_flags and given:
        ap.error("--same-flags builds with the flags the last build stored; leave out %s" % ", ".join(given))
    ws = find_workspace(args.workspace)
    generated = ws / "System" / "generated"
    out = Path(args.out).expanduser() if args.out else generated / "status.html"
    inside = str(out.resolve()).startswith(str(ws) + os.sep)
    if inside and not str(out.resolve()).startswith(str(generated.resolve()) + os.sep):
        print("status: %s is inside the workspace but not in System/generated/; this page shows every zone, "
              "so keep it where git and the wall check leave it alone." % out, file=sys.stderr)
    if inside and (ws / ".git").exists():
        try:
            probe = subprocess.run(["git", "--no-optional-locks", "-C", str(ws), "check-ignore", "-q", "--no-index",
                                    "System/generated/status.html"],
                                   capture_output=True, text=True)
        except OSError:                       # no git on this PATH: nothing to check against
            probe = None
        if probe is not None and probe.returncode == 1:
            print("status: the workspace's .gitignore does not name System/generated/; add that line so the page "
                  "is never committed.", file=sys.stderr)
    if args.settle and args.settle > 0 and not settle(out.with_name(out.name + ".settle"), args.settle):
        return 0                              # a later request builds it
    if not (ws / "System").is_dir():          # deleted during the wait: build nothing, and make no folder again
        print("status: %s is no longer a workspace; nothing built." % ws, file=sys.stderr)
        return 1
    if args.same_flags:                       # read after the wait, so a build made meanwhile counts
        try:
            kept = ap.parse_args(stored_words(flags_file(out)))
        except SystemExit:
            print("status: %s does not hold flags a build stored; built without them." % flags_file(out), file=sys.stderr)
            kept = ap.parse_args([])
        for k in PAGE_FLAGS:
            setattr(args, k, getattr(kept, k))
    out.parent.mkdir(parents=True, exist_ok=True)
    prefs().migrate(ws)          # choices a Garrick before 0.25.0 left in System/generated/, kept where they belong
    flags = ("--no-cmux",) if args.no_cmux else ()
    moved = {}
    for m in args.moved:
        if "=" not in m:
            print("status: --moved %r is not OLD=NEW; left out." % m, file=sys.stderr)
            continue
        old, new = m.split("=", 1)
        moved[old] = new
    flags += tuple(w for a in args.also for w in ("--also", a)) + tuple(w for o, n in moved.items() for w in ("--moved", "%s=%s" % (o, n)))
    page = build(ws, show_graph=not args.no_graph, out=out.resolve() if args.out else None,
                 flags=flags, also=tuple(args.also), moved=moved,
                 managed=handoff_mod().managed_places(), cli=handoff_mod().find_claude() is not None,
                 launchers=tuple(k for k in launchers_installed() if not (args.no_cmux and k == "cmux")),
                 page_at=out, reuse_check=args.reuse_check, waiting_now=waiting_rows(ws))
    if STARTED is not None and own_stamp() != STARTED:
        return rerun(argv)                    # an update replaced this file meanwhile: the page is the new code's to draw
    write_page(out, page)
    if not args.same_flags:                   # a build that used the stored flags leaves them to the build that stored them
        try:
            write_page(flags_file(out), json.dumps({"args": page_words(args, moved)}, ensure_ascii=False) + "\n")
        except OSError as e:
            print("status: the flags this page was built with were not kept (%s); a tool's rebuild draws it without them." % e,
                  file=sys.stderr)
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
