#!/usr/bin/env python3
"""The view model: what the App shows, built by the core, so the App only draws it (#650).

`build(root)` returns one JSON-serialisable document for a workspace: its pieces of work
(from `work.py`'s one reader) with their state, what each may do (from
`operations.DECLARED`), and the queues the page shows. It reads notes and folders and
writes nothing. Standard library only, and no assistant.

The App's page, `System/status/status.py`, takes this document and draws it. What a
card means is decided here; how it looks is decided there. A change to wording or layout
cannot change what is true, and what is true can be tested without drawing a page.

The shape (every field name is stable; `docs/architecture.md` has one example)

    {"api": 1,
     "zones": [ZONE, ...],                     # by name, one per folder of Zones/
     "queues": {"inbox": [INBOX, ...]},        # the places that hold files waiting to be sorted
     "today": "2026-11-22",                    # the day the Todo part counts as ticked today
     "wikis": [WIKI, ...],                     # each wiki's log: how many entries, and the newest (none in a scoped build)
     "repos": [REPO, ...],                     # the root, each zone, the wikis: what each has uncommitted
     "graph": GRAPH,                           # Explore's notes and the links between them
     "example": "Example" | null,              # the zone the worked example is in, by its marker
     "system": [SYSTEM, ...],                  # the projects kept in System/, outside any zone
     "left": [...]}                            # what the page still reads for itself, by name

    ZONE   {"name": "Work",
            "linked": false,                   # the folder is a link, so it is no zone: no work, no inbox
            "done": 1,                         # how many threads are done
            "held": ["Acme"],                  # projects parked as a whole
            "projects": {"Acme": PROJECT},
            "open_links": [["Pricing"]],       # for each open Todo line that links a note, the notes it links
            "todo": TODO,                      # the zone's open actions (not for a zone that is a link)
            "questions": [QUESTION, ...],      # what Garrick asked and waits on, oldest first (not for a zone that is a link)
            "work": [PIECE, ...]}              # live, then parked, then done, then hubs; each by name

    PROJECT {"status": "live" | "parked" | "done", "spoken": "", "own": false, "heading": false,
             "hub": "Zones/Work/Acme/Acme.md" | null, "party": ["acme"],
             "files": 4, "layout": ["split"]}      # the last two: only with a hub file; what its dialogs say

    PIECE  {"id": "Work/Acme/Pricing",         # "Zone/Project" for a hub, "Zone/Project/Thread" for a thread
            "zone": "Work", "project": "Acme", "thread": "Pricing",
            "shown": "row" | "parked" | "done" | "hub",
            "state": "live" | "parked" | "done" | "<the note's own word>",
            "held": false,                     # parked with its project, whatever its own status
            "note": "Zones/Work/Acme/Threads/Pricing/Pricing.md",    # from the workspace
            "rel": "Acme/Threads/Pricing/Pricing.md",                # from the zone
            "hub": "Zones/Work/Acme/Acme.md" | null,
            "party": ["acme"], "updated": "2026-11-02" | null, "spoken": "", "heading": false,
            "files": 3, "open": 1,                                   # a thread's own: files a delete takes, open lines naming it
            "resume": true, "resumed": "2026-11-02" | null,          # None of these for a done piece
            "checkpoint": {"at": "...", "said": "09:30", "full": "...", "stale": false} | null,
            "touched": "2026-11-02" | null,
            "read": {"block": true, "date": null, "where": "", "rows": {}, "entry": null, "about": ""},
            "actions": ["park", "rename", ...]}   # the declared verbs that apply to it

    INBOX  {"place": "Work", "kind": "zone" | "wiki", "folder": "Zones/Work/Inbox", "count": 2}

    QUESTION {"file": "Acme/Needs you/q.md", "zone": "Work", "ask": "Which one?", "options": ["Acme", "Birch"],
              "asked": "2026-11-20" | null, "own": "", "work": "Acme", "intake": false}   # the work it blocks, and its file from the zone

    TODO   {"file": "Zones/Work/Todo.md" | null,    # null where the zone has no Todo.md
            "order": ["Inbox", "Soon"],           # its `## ` headings, in order
            "tasks": [TASK, ...],                 # every open line of the zone's notes, as a Todo.md and the thread notes hold them
            "done": [TASK, ...]}                  # the lines ticked today and still in the notes
    TASK   {"file": "Todo.md" | "Acme/Threads/Pricing/Pricing.md", "section": "Soon" | null, "line": "- [ ] ...", "key": "0f3a...",
            "text": "...", "thread": "Pricing" | null, "target": "Pricing" | null, "unsure": false, "src": null, "also": [],
            "due": "2026-11-25" | null, "scheduled": null, "priority": null, "tags": [], "waiting": false,
            "note": "Zones/Work/Acme/Threads/Pricing/Pricing.md" | null,   # the note the line names or sits in
            "label": "Pricing" | null, "project": "Acme", "tname": "Pricing"}

    GRAPH  {"places": [{"name": "Work", "folder": "Zones/Work", "zone": true}],   # a zone, or a wiki's `wiki/` folder (zone: false)
            "notes": [{"place": "Work", "zone": true, "path": "Zones/Work/Acme/Acme.md", "rel": "Acme/Acme.md",
                       "type": "project", "status": "active", "updated": "2026-11-02" | null, "party": ["acme"], "title": "Acme"}],
            "edges": [[0, 1]]}                                                    # indexes into `notes`, smaller first, once

    WIKI   {"name": "Meetings", "folder": "Wikis/Meetings", "log": "Wikis/Meetings/wiki/log.md", "count": 12,
            "when": "2026-11-20" | null, "title": "Weekly review", "markdown": false,  # the newest entry; `markdown`: the page reads the title as plain words
            "page": "wiki/sources/review.md" | null,                                   # from the wiki's real folder
            "unread": false}                                                           # the log has lines that look like entries and none read

    REPO   {"name": "Work", "folder": "Zones/Work" | "", "dirty": 2, "changes": [["Acme/Acme.md", ["unstaged"]]],
            "unread": false, "since": "2026-11-21T09:12:00" | null, "last": "2026-11-20T17:30:00" | null}

    SYSTEM {"name": "Sys", "notes": ["System/Sys/Sys.md", "System/Sys/Threads/Job/Job.md"]}   # the hub, then each thread note

Walls. Every record carries its zone. A count is of one zone or one wiki; nothing here adds
two together. `build(root, scope=["Work"])` holds the records of those zones alone, and no
wiki. A zone folder that is a link is no zone, and an Inbox or a note that resolves outside
the zone it sits in is left out, so a link into another zone shows none of that zone's work.

`left` names what the page reads for itself because no core module owns it yet: the waiting sessions. The App's own files under `System/` and the check's kept result are read by `view_app.py` (`app_reader()`
below). The jobs folder and this Mac's launchd agents are read by `view_jobs.py` (`jobs_reader()` below), not part of
`build()`: they are this Mac's. The settings are read by `view_settings.py` (`settings()` below), not part of
`build()`: Settings is the page's own and names every zone's walled flag.

`build(root, only=(...))` builds the parts named (`PARTS`) and leaves the rest out, for a caller that needs one.
"""
import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

API = 1
DONE = {"done", "closed", "archived", "complete", "completed"}
PARKED = {"parked", "dormant", "paused", "on-hold"}
# The verbs that may act on a piece of work, as the page offers them; each must be declared in operations.DECLARED.
PIECE_VERBS = ("park", "wake", "rename", "move", "delete", "continue", "open", "close")
# The cards of the page, by the id each carries (`<details class="card" id=...>`): the one set the App counts opens of (#651).
# Never a thread's or a project's: a row of the Threads card has a name in it, and a name is never counted.
CARDS = ("start", "your-work", "waiting-now", "threads", "checks", "jobs", "calls", "repos", "wikis", "graph")
# What the page reads for itself, by name, until a core module owns it.
LEFT = ("waiting sessions",)

# The parts of the document, for `build(only=...)`: each is built by its own reader, and a part not asked for is not read.
PARTS = ("work", "inbox", "system", "todo", "questions", "wikis", "repos", "example", "graph")

_MODS: dict = {}


def _sibling(name: str, key: str):
    """A module beside this file, loaded once."""
    if key not in _MODS:
        mod = sys.modules.get(key)
        if mod is None:
            spec = importlib.util.spec_from_file_location(key, str(Path(__file__).with_name(name)))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[key] = mod
            try:
                spec.loader.exec_module(mod)
            except BaseException:
                sys.modules.pop(key, None)
                raise
        _MODS[key] = mod
    return _MODS[key]


def _work():
    return _sibling("work.py", "garrick_work")


def _operations():
    return _sibling("operations.py", "garrick_operations")


def _lib():
    return _work()._lib()


def _todo():
    return _sibling("view_todo.py", "garrick_view_todo")


# --------------------------------------------------------------------------- small readers

def as_text(value) -> str:
    """A frontmatter value as one string: a list joined, nothing as ''."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def as_date(value) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(as_text(value).strip()[:10])
    except ValueError:
        return None


def tags(value) -> List[str]:
    """Party tags from `acme`, `[acme, birch]`, `#acme` or a block list."""
    items = value if isinstance(value, list) else re.split(r"[,\[\]]", as_text(value))
    out = []
    for t in items:
        t = re.sub(r"\s+#.*$", "", as_text(t)).strip().strip("[]\"'").lstrip("#").strip()
        if t and t not in out:
            out.append(t)
    return out


def _iso(day) -> Optional[str]:
    return day.isoformat() if day else None


MONTH = {m.lower(): i + 1 for i, m in enumerate(("January February March April May June July August September "
                                                  "October November December").split())}
SPOKEN_DATE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b")
RESUME = re.compile(r"^#{1,6}\s+Resume here\b", re.I)
RESUME_ROW = re.compile(r"^\|\s*([^|]*?)\s*\|\s*(.*?)\s*\|\s*$")
ENTRY_LINE = re.compile(r"^\*\*(?:[A-Z][a-z]+ \d\d:\d\d, )?(\d{1,2} [A-Za-z]{3,9}\.? \d{4})\.\*\*\s*(.*\S)\s*$")
PLACEHOLDER = re.compile(r"^<[^>]*>$")
# The checkpoint beside a resume point: `### Checkpoint` under Resume here, what a session recorded as the work happened
# and has not wrapped yet. Only its comment line is read, which carries when it was written and the hash of the resume
# point it was written against; no content of the block reaches the page.
CHECKPOINT_MARK = re.compile(r"(?m)^<!--[ \t]*garrick-checkpoint[ \t]([^\n]*?)-->[ \t]*$")
CHECKPOINT_FIELD = re.compile(r"(\w+)=(\S+)")
MONTH_NAMES = tuple(m.capitalize() for m in sorted(MONTH, key=MONTH.get))


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
    """A thread note's resume point, read once: `block`, whether it has a `### Resume here` block, and `date`, the date
    the block gives itself: the first date on its "Where it stands" line, or anywhere in the block before its table.
    Also `where`, its Where it stands line; `rows`, its table by row name (Next action, Waiting on, ...), each as
    written and "" where it is still the template's placeholder; `entry`, the newest dated entry below it, (its date,
    its words); and `about`, the note's opening sentence under its title."""
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


def checkpoint_mark(note: Path, judge: bool = True) -> Optional[dict]:
    """The unwrapped checkpoint in a note, as its comment line carries it: `at`, when it was written, `said` and `full`,
    that time short and long, and `stale`, whether the resume point has moved since. None where the note has no
    checkpoint. Stale needs `resume_hash` of the core library, so where `judge` is False (a workspace with no library
    of its own, `can_judge()`) a block reads as current: the time it carries is true either way, and only the second
    claim would be a guess."""
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
    lib = _lib()
    base = None
    if judge and callable(getattr(lib, "resume_hash", None)):
        try:
            base = lib.resume_hash(body)
        except Exception:
            base = None
    said = "%02d:%02d" % (when.hour, when.minute) if when else "an unreadable time"
    full = "%s on %d %s %d" % (said, when.day, MONTH_NAMES[when.month - 1], when.year) if when else said
    return {"at": when, "said": said, "full": full,
            "stale": bool(base and fields.get("base") and fields["base"] != base)}


# --------------------------------------------------------------------------- the pieces of work

def can_judge(root: Path) -> bool:
    """Whether the workspace has the core library of its own, which tells a checkpoint written against an older resume
    point from a current one. A workspace with none (an update that stopped half way) judges nothing, as the page always
    did: a display rule, kept."""
    return (Path(root) / "System" / "tools" / "garrick_lib.py").is_file()


# --------------------------------------------------------------------------- what a card's manage dialogs need

def layout_offers(folder: Path, heading: bool, hub: bool) -> List[str]:
    """The change of layout a card offers (#604, #632): the project's switch and nothing else, as `scaffold.py layout`
    makes it. `split` for a project that is one job, `join` for one that is separate jobs, `mend` (a Join) for a one-job
    project where a thread holds papers of its own; a thread offers none, since
    the project's switch decides for every thread under it. A project with no hub offers none."""
    if not hub or folder.parent.name == "Threads":
        return []
    if heading:
        return ["join"]
    return ["mend"] if mixed_papers(folder) else ["split"]


def _keeps_papers(folder: Path) -> bool:
    """The same test as check.py's `keeps_papers` (N1): a tracked file a Join would move, so not a `.gitkeep`, a
    `.DS_Store` or a `published.md` ledger with no row."""
    if not folder.is_dir():
        return False
    try:
        listing = subprocess.run(["git", "ls-files", "-z", "--", "."], cwd=str(folder), capture_output=True,
                                 text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    for name in (n for n in listing.split("\0") if n):
        path = folder / name
        if Path(name).name in (".gitkeep", ".DS_Store") or path.is_symlink() or not path.is_file():
            continue
        if name == "published.md" and folder.name == "Deliverables":
            rows = 0
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = []
            for l in lines:
                if l.strip().startswith("|"):
                    cells = [c.strip() for c in l.strip().strip("|").split("|")]
                    if len(cells) > 1 and cells[1] and not set(cells[0]) <= set("-: ") and cells[0].lower() != "date":
                        rows += 1
            if not rows:
                continue
        return True
    return False


def mixed_papers(project: Path) -> bool:
    """Is this one-job project mixed: a thread holds papers of its own, and the threads do not look like separate
    jobs (the hub keeps its resume point, and some thread keeps none)? The check names the same case, and the fix it
    names is the Join, not the Split (#632)."""
    threads = sorted(d for d in (project / "Threads").glob("*") if d.is_dir() and not d.name.startswith("."))
    holding = [t for t in threads if any(_keeps_papers(t / k) for k in ("Sources", "Deliverables"))]
    if not holding or len(holding) == len(threads):
        return False
    try:
        hub = (project / (project.name + ".md")).read_text(encoding="utf-8")
    except OSError:
        return False
    return any(l.strip().lower() in ("### resume here", "### outcome") for l in hub.splitlines())


def files_in(folder: Path) -> int:
    """How many files deleting a folder would take, for the warning."""
    return sum(len([f for f in fs if not f.startswith(".")]) for d, _, fs in os.walk(folder) if ".git" not in Path(d).parts)


def open_links(zone: Path) -> List[List[str]]:
    """For each open line of the zone's Todo.md that links to a note, the names of the notes it links to (the last part
    of each link, without an alias or a heading). Names only: no line's words are kept."""
    todo = zone / "Todo.md"
    if not _work()._within(todo, zone.resolve()):         # a Todo.md that is a link out of the zone is no part of it
        return []
    try:
        text = todo.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        if not re.match(r"\s*- \[ \]", line):
            continue
        targets = [t.split("|")[0].split("#")[0].rsplit("/", 1)[-1] for t in re.findall(r"\[\[([^\]]+)\]\]", line)]
        if targets:
            out.append(targets)
    return out


def open_naming(links: List[List[str]], names: set) -> int:
    """How many open lines of a zone's Todo.md link to one of `names`, as scaffold.py's delete would remove them.
    `links` is the zone's `open_links`."""
    return sum(1 for targets in links if any(t in names for t in targets))



def actions_for(shown: str, state: str) -> List[str]:
    """The declared verbs that apply to a piece: a live piece may be parked, a parked one woken, and a done one
    only renamed, moved or deleted. Each is in operations.DECLARED, so a verb the table lacks is never offered."""
    declared = _operations().DECLARED
    if shown == "done":
        wanted = ("rename", "move", "delete")
    elif shown == "parked":
        wanted = ("wake", "rename", "move", "delete", "continue", "open", "close")
    elif shown == "hub":
        wanted = ("park", "continue", "open", "close")
    else:
        wanted = ("park", "rename", "move", "delete", "continue", "open", "close")
    return [v for v in PIECE_VERBS if v in wanted and v in declared]


def _allowed(root) -> "Callable[[Path, Path], bool]":
    """A test of a path that may be a link, for the readers that take what a zone holds (#650, 0.78.0): `allowed(path,
    inside)` is False where the path resolves to a place of this workspace other than `inside`, another zone's or a
    wiki's file, which the zone's own record must never show. A link that leads outside the workspace altogether, to a
    shared folder the user keeps beside it, crosses no wall and is read as it always was."""
    top = Path(root).resolve()

    def allowed(path: Path, inside: Path) -> bool:
        try:
            real = Path(path).resolve()
        except (OSError, RuntimeError):
            return False
        if real == inside or inside in real.parents:
            return True
        return not (real == top or top in real.parents)
    return allowed


def _rel(path: Optional[Path], root: Path) -> Optional[str]:
    if path is None:
        return None
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return None


def _checkpoint_json(mark: Optional[dict]) -> Optional[dict]:
    if not mark:
        return None
    return {"at": mark["at"].isoformat() if mark["at"] else None, "said": mark["said"], "full": mark["full"],
            "stale": mark["stale"]}


def _read_json(read: dict) -> dict:
    entry = read["entry"]
    return {"block": read["block"], "date": _iso(read["date"]), "where": read["where"], "rows": dict(read["rows"]),
            "entry": [_iso(entry[0]), entry[1]] if entry else None, "about": read["about"]}


def _piece(root: Path, judge: bool, links: List[List[str]], zone: Path, project: Path, name: str, note: Path, hub_path: Path, pfm: dict, fm: dict,
           state: str, shown: str, held: bool, hub: Optional[Path], deep: bool) -> dict:
    """One piece of work as the page's row reads it. `deep` reads the note's resume point and checkpoint; a done
    piece is not read, as it never was."""
    out = {"id": "/".join(x for x in (zone.name, project.name, "" if note == hub_path else name) if x),
           "zone": zone.name, "project": project.name, "thread": name, "shown": shown, "state": state,
           "held": held, "note": _rel(note, root), "rel": _rel(note, zone), "hub": _rel(hub, root),
           "party": tags(fm.get("party") or pfm.get("party")), "updated": _iso(as_date(fm.get("updated"))),
           "spoken": as_text(fm.get("spoken")).strip(), "heading": as_text(pfm.get("layout")).strip().lower() == "thread-first",
           "actions": actions_for(shown, state)}
    if deep:
        read = resume_read(note)
        mark = checkpoint_mark(note, judge)
        updated = as_date(fm.get("updated"))
        when = [d for d in (updated, mark["at"].date() if mark and mark["at"] else None) if d]
        out.update({"resume": read["block"], "resumed": _iso(read["date"]), "checkpoint": _checkpoint_json(mark),
                    "touched": _iso(max(when)) if when else None, "read": _read_json(read)})
        if note != hub_path:
            # what the card's Rename, Move and Delete dialogs say: the files a delete would take, and the open lines it would remove
            out.update({"files": files_in(note.parent), "open": open_naming(links, {name})})
    return out


def _zone_work(root: Path, zone: Path) -> dict:
    """The zone's record: its pieces of work, by the one reader."""
    reader = _work()
    lib = _lib()
    rows, parked, finished, hubs, asleep, projects = [], [], [], [], [], {}
    done = 0
    judge = can_judge(root)
    links = open_links(zone)
    for (_, name_), found in reader.by_project(reader.pieces(root, zone=zone.name)).items():
        project = zone / name_
        hub = found[0].hub
        hub_path = project / (project.name + ".md")
        pfm = (lib.parse_frontmatter(hub) or {}) if hub else {}
        hub_state = as_text(pfm.get("status")).strip().lower() if hub else ""
        hub_parked = hub_state in PARKED
        if hub_parked:
            asleep.append(project.name)
        heading = any(r.kind == "heading" for r in found)     # no piece of work of its own
        # The page shows a hub as its project's single thread only when it says `type: project`.
        shown = reader.own_needs_type(found)
        own = any(r.own for r in shown)
        notes = [(r.thread or project.name, r.note) for r in shown if r.thread or r.own]
        projects[project.name] = {"status": "done" if hub_state in DONE else "parked" if hub_parked else "live",
                                  "spoken": as_text(pfm.get("spoken")).strip(), "own": own, "heading": heading,
                                  "hub": _rel(hub, root), "party": tags(pfm.get("party"))}
        if hub is not None:              # what the project card's dialogs say: its files, and the layout change it offers
            projects[project.name].update({"files": files_in(project), "layout": layout_offers(project, heading, True)})
        for name, note in notes:
            fm = pfm if note == hub_path else (lib.parse_frontmatter(note) or {})
            state = as_text(fm.get("status")).strip().lower()
            if state in DONE:
                done += 1
                finished.append(_piece(root, judge, links, zone, project, name, note, hub_path, pfm, fm, "done", "done", False, hub, False))
                continue
            held = hub_parked and note != hub_path          # parked with its project, whatever its own status
            state = "parked" if state in PARKED or held else state
            piece = _piece(root, judge, links, zone, project, name, note, hub_path, pfm, fm, state,
                           "parked" if state == "parked" else "row", held, hub, True)
            (parked if state == "parked" else rows).append(piece)
        # The hub's own resume point beside its threads: a row of Your work and no row of the Threads card.
        if any(r.beside for r in found) and not hub_parked and hub_state not in DONE:
            hubs.append(_piece(root, judge, links, zone, project, project.name, hub_path, hub_path, pfm, pfm, hub_state, "hub", False,
                               hub, True))
    # By name, as you would look for one; the freshness bar carries the age.
    by_name = lambda p: (p["thread"].casefold(), p["project"].casefold())  # noqa: E731
    rows.sort(key=by_name)
    parked.sort(key=by_name)
    finished.sort(key=by_name)
    return {"name": zone.name, "linked": False, "done": done, "held": asleep, "projects": projects,
            "open_links": links, "work": rows + parked + finished + hubs}


def _visible_dirs(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def _queue_inbox(place: str, kind: str, folder: Path, inside: Path, root: Path) -> Optional[dict]:
    """One place's files waiting: None where there is no folder, or it resolves outside the place it belongs to."""
    if not folder.is_dir() or not _work()._within(folder, inside):
        return None
    n = sum(1 for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    return {"place": place, "kind": kind, "folder": _rel(folder, root), "count": n}


def system_projects(root: Path) -> List[dict]:
    """The projects kept in System/ (#650): each folder there whose hub note says `type: project`, with the paths, from
    the workspace, of the hub and of every thread note under it, in the order the page matches a Todo line's label
    against them. Such a project has no Todo.md of its own: its actions live in a zone's, opening with its thread's
    link. A folder with no hub, or a hub that is not a project, is no project. System/ belongs to no zone: a scoped build
    holds none of it."""
    lib = _lib()
    out: List[dict] = []
    for project in _visible_dirs(Path(root) / "System"):
        hub = project / (project.name + ".md")
        if not hub.is_file() or as_text((lib.parse_frontmatter(hub) or {}).get("type")).strip().lower() != "project":
            continue
        notes = [hub] + [t / (t.name + ".md") for t in _visible_dirs(project / "Threads")]
        out.append({"name": project.name, "notes": [_rel(n, root) for n in notes if n.is_file()]})
    return out


# ---- the questions that wait (#503, #634): a question Garrick asked is a file in the `Needs you` folder of the work it
# blocks. Each is one zone's, and nothing here adds one zone to another.
QUESTION_BOX = "Needs you"
QUESTION_OPTION = re.compile(r"^\s*-\s+\[(?![ xX]\])([^\]]+)\]\s+(\S.*?)\s*$")


def questions_in(folder: Path, zone: Path, today: dt.date) -> List[dict]:
    """The open questions in one piece of work's `Needs you` folder, and the ones put off whose day has come. One put
    off to a later day, an answered one, a file with no bold line to ask, and a file that is a link into another zone or a wiki are
    left out. The zone's own box holds only what an inbox run asked (#634)."""
    out: List[dict] = []
    box = folder / QUESTION_BOX
    if not box.is_dir():
        return out
    lib, inside, within = _lib(), zone.resolve(), _allowed(zone.parent.parent)
    for f in sorted(box.glob("*.md")):
        if f.name.startswith((".", "_")) or not within(f, inside):
            continue
        fm = lib.parse_frontmatter(f) or {}
        if folder == zone and not as_text(fm.get("intake")).strip():
            continue
        state = as_text(fm.get("status")).strip().lower() or "open"
        later = as_date(fm.get("later"))
        if state not in ("open", "later") or (state == "later" and not (later is not None and later <= today)):
            continue
        try:
            body = re.sub(r"\A---\n.*?\n---\n", "", f.read_text(encoding="utf-8", errors="replace"), count=1, flags=re.S)
        except OSError:
            continue
        ask, opts = "", []
        for line in body.splitlines():
            m = QUESTION_OPTION.match(line)
            if m:
                opts.append(m.group(1).strip())
            elif not ask and re.match(r"^\s*\*\*.+\*\*\s*$", line):
                ask = line.strip().strip("*").strip()
        if ask:
            out.append({"file": f.relative_to(zone).as_posix(), "zone": zone.name, "ask": ask, "options": opts,
                        "asked": _iso(as_date(fm.get("asked"))), "own": as_text(fm.get("own")).strip(), "work": folder.name,
                        "intake": bool(as_text(fm.get("intake")).strip()) and folder == zone})
    return out


def zone_questions(zone: Path, today: dt.date) -> List[dict]:
    """Every open question of one zone, oldest first: the zone's own box, then each project's and each thread's. A project
    or thread folder that is a link into another zone or a wiki is not read."""
    inside = zone.resolve()
    within = _allowed(zone.parent.parent)
    found = questions_in(zone, zone, today)
    for project in _visible_dirs(zone):
        if not within(project, inside):
            continue
        if (project / (project.name + ".md")).is_file():
            found += questions_in(project, zone, today)
        for thread in _visible_dirs(project / "Threads"):
            if within(thread, inside) and (thread / (thread.name + ".md")).is_file():
                found += questions_in(thread, zone, today)
    found.sort(key=lambda q: (q["asked"] or "9999-12-31", q["file"]))
    return found


# ---- the wikis' logs: one line per ingest in each wiki's log, `- 2026-09-24: [[wiki/sources/slug|Title]] (...)`.
LOG_ENTRY = re.compile(r"^\s*-\s+(\d{4}-\d\d-\d\d):\s+\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")
# A dated line with no link first, as the knowledge skill wrote its log before 0.51.0: its title is its text up to the
# first parenthesis or semicolon. And a dated `## ` heading, as a wiki whose schema.json says `"log": "section"` keeps it:
# its title is the rest of the heading, or the first line under it (#322).
LOG_DATED = re.compile(r"^\s*-\s+(\d{4}-\d\d-\d\d):\s+(.*)$")
LOG_SECTION = re.compile(r"^##\s+(\d{4}-\d\d-\d\d)\b[\s:·,—–-]*(.*)$")


def log_entries(text: str) -> Tuple[List[tuple], bool]:
    """(date, -line, title, page target or "", markdown) for every entry a wiki's log holds, in the three forms (#322);
    and whether it holds lines that look like entries, a list item or a `## ` section, so a log that reads as none of them
    says so rather than "nothing logged yet". `markdown` is True where the title is a line of Markdown the page reads as
    plain words (the two forms with no link), and False where it is a link's alias or a page's name."""
    lines = text.splitlines()
    entries, tried = [], False
    for n, line in enumerate(lines):
        m = LOG_ENTRY.match(line)
        if m:
            when = as_date(m.group(1))
            if when:
                target = m.group(2).strip()
                entries.append((when, -n, (m.group(3) or target.rsplit("/", 1)[-1]).strip(), target, False))
                continue
        m = LOG_DATED.match(line) or LOG_SECTION.match(line)
        if m and as_date(m.group(1)):
            rest = m.group(2).strip()
            if not rest and line.startswith("##"):          # the section's first line says what it holds
                rest = next((l.strip().lstrip("-* ").strip() for l in lines[n + 1:n + 6] if l.strip() and not l.startswith("#")), "")
                k = LOG_ENTRY.match("- %s: %s" % (m.group(1), rest))
                if k:
                    target = k.group(2).strip()
                    entries.append((as_date(m.group(1)), -n, (k.group(3) or target.rsplit("/", 1)[-1]).strip(), target, False))
                    continue
            entries.append((as_date(m.group(1)), -n, re.split(r"[(;]", rest, 1)[0], "", True))
            continue
        tried = tried or line.lstrip().startswith(("- ", "* ")) or line.startswith("## ")
    return entries, tried


def wiki_records(root: Path) -> List[dict]:
    """Per wiki: its log, how many entries it holds, and the newest entry's date and title. Nothing else from the line: not
    its zone, not its parties. An entry with a link opens its page, named from the wiki's real folder; a log whose entries
    it cannot read at all says so (`unread`). A log that is a link into another zone or wiki is not read."""
    within = _allowed(root)
    out = []
    for w in _visible_dirs(Path(root) / "Wikis"):
        log = w / "wiki" / "log.md"
        real = w.resolve()
        if not log.is_file() or not within(log, real):
            continue
        try:
            entries, tried = log_entries(log.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        row = {"name": w.name, "folder": _rel(w, root), "log": _rel(log, root), "count": len(entries), "when": None,
               "title": "", "markdown": False, "page": None, "unread": tried and not entries}
        if entries:
            when, _, title, target, markdown = max(entries)   # the newest; on a tie, the line nearer the top
            page = None
            if target:
                found = (w / (target if target.endswith(".md") else target + ".md")).resolve()
                if str(found).startswith(str(real) + os.sep) and found.is_file():
                    page = found.relative_to(real).as_posix()
            row.update(when=_iso(when), title=title, markdown=markdown, page=page)
        out.append(row)
    return out


# ---- the repositories: the root, each zone, the wikis' repository and any wiki with one of its own.
# How `git status --porcelain` marks a file, as the Repositories card says it. A file staged and then edited again is
# both staged and not staged.
UNMERGED = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


def changed_files(porcelain: str) -> List[Tuple[str, Tuple[str, ...]]]:
    """(path, kinds) for every file `git status --porcelain -z` lists: one entry per file, a rename under its new name. A
    count of these is a count of files, never of commits."""
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


def oldest_change(folder: Path, changes) -> Optional[dt.datetime]:
    """When the longest-waiting uncommitted change was made: the oldest modification time among the changed files still
    on disk. A deleted file has none and is passed over."""
    times = []
    for path, _ in changes:
        try:
            times.append((folder / path).stat().st_mtime)
        except OSError:
            continue
    return dt.datetime.fromtimestamp(min(times)) if times else None


def repo_records(root: Path, scope: Optional[set] = None) -> List[dict]:
    """The root, each zone, and the wikis: the installer makes one repository at Wikis/ for both. A wiki with a repository
    of its own is listed too. When git fails or runs out of time, the repository is `unread`, never clean: an empty answer
    is not a count of nothing. A zone folder that is a link is no zone and has no repository here. A scope holds the
    repositories of its zones alone: not the root's, and not the wikis'."""
    root = Path(root)
    real = {z.name for z in _work().zones(root)}
    places: List[Tuple[str, Path]] = [] if scope is not None else [("Workspace", root)]
    places += [(z.name, z) for z in _visible_dirs(root / "Zones") if z.name in real and (scope is None or z.name in scope)]
    if scope is None:
        places += [("Wikis", root / "Wikis")] + [(w.name, w) for w in _visible_dirs(root / "Wikis")]
    out = []
    for name, folder in places:
        if not (folder / ".git").exists():
            continue
        # --no-optional-locks: the page only reads, so git status never takes index.lock to refresh the index, and a commit a
        # session makes in the same moment never finds it held.
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
        since = oldest_change(folder, changes)
        out.append({"name": name, "folder": "" if folder == root else _rel(folder, root), "dirty": len(changes),
                    "changes": [[p, list(k)] for p, k in changes], "unread": porcelain is None,
                    "since": since.isoformat() if since else None,
                    "last": dt.datetime.fromtimestamp(int(ct)).isoformat() if ct.isdigit() else None})
    return out


# The worked example's marker in its zone, as garrick_lib.EXAMPLE_MANIFEST names it.
EXAMPLE_MANIFEST = ".example.json"


def example_zone(root: Path, scope: Optional[set] = None) -> Optional[str]:
    """The zone the worked example is in, or None: the first zone whose `.example.json` names it, read as
    `System/tools/example.py`'s present() does. A zone folder that is a link is no zone, and a marker that is a link into
    another zone or a wiki is not read."""
    root = Path(root)
    real = {z.name for z in _work().zones(root)}
    for zone in _visible_dirs(root / "Zones"):
        manifest = zone / EXAMPLE_MANIFEST
        if zone.name not in real or (scope is not None and zone.name not in scope):
            continue
        if not manifest.is_file() or not _allowed(root)(manifest, zone.resolve()):
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("zone") == zone.name:
            return zone.name
    return None


# ---- the graph Explore draws: every note in the zones and the wikis, and the [[links]] between them.
WIKILINK = re.compile(r"\[\[([^\]|#^]+)")
# Folders that hold no notes of their own: an inbox, raw records, superseded versions, generated pages. Compared without
# regard to case.
GRAPH_SKIP_DIRS = {"inbox", "raw", "archive", "generated"}


def walked(root: Path, folder: str, name: str, in_zone: bool) -> bool:
    """Whether the graph reads the folder `name` inside `folder`. A zone's own Inbox is left out. A project or a thread is
    read whatever it is called, so one named Archive or raw stays on the graph; anywhere else a folder named for an inbox,
    raw records, old versions or generated pages is left out."""
    if name.startswith((".", "_")):
        return False
    depth = Path(folder).relative_to(root).parts
    if in_zone and not depth:
        return name != "Inbox"                                # every other folder here is a project
    if in_zone and len(depth) == 2 and depth[1] == "Threads":
        return True                                           # a thread
    return name.casefold() not in GRAPH_SKIP_DIRS


def git_ignored(root: Path) -> set:
    """The folders (paths relative to the zone `root`) that the zone's own git ignores, from one `git ls-files` over the
    zone (#399), asked for before the walk so that an ignored folder is never entered. A path git cannot encode as text (a
    name that is not valid UTF-8) is read back as the walk reads it, with surrogateescape. A zone that is not a repository
    of its own, or a Mac with no git, ignores nothing."""
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


def graph_records(root: Path, scope: Optional[set] = None) -> dict:
    """Every note in the zones and the wikis, and the [[links]] between them. From a note it keeps its place, its path,
    its `type`, `status`, `updated`, party tags and title; from its body only the targets of its links, resolved to the
    notes they name. Instructions (AGENTS.md) are not notes, and each zone's Todo.md has the Todo card, so neither is
    listed. A vault's ignore filters (.obsidian/app.json) leave notes out, as Obsidian's graph does. A link to a note is
    `[a, b]`, the indexes of two notes, once.

    Walls. A zone folder that is a link is no zone, and a note that is a link whose real path is in another place of the
    workspace is not listed, so a link never brings another place's notes onto the graph; a link to a file outside the
    workspace altogether is listed, as it always was. A scope holds its zones' notes alone,
    and no wiki: a link names only a note the scope holds."""
    root = Path(root)
    vt = _todo()
    real = {z.name for z in _work().zones(root)}
    lib = _lib()
    within = _allowed(root)
    places: List[Tuple[str, Path, bool]] = [(z.name, z, True) for z in _visible_dirs(root / "Zones")
                                            if z.name in real and (scope is None or z.name in scope)]
    if scope is None:
        places += [(w.name, w / "wiki", False) for w in _visible_dirs(root / "Wikis") if (w / "wiki").is_dir()]
    vaults: Dict[Path, list] = {}                     # vault -> its ignore filters
    notes: List[Tuple[str, Path, Path, bool]] = []
    for place, folder, in_zone in places:
        vault = vt.vault_of(root, folder)
        if vault is not None and vault not in vaults:
            vaults[vault] = vt.ignore_filters(vault) if vault is not None else []
        filters = vaults[vault] if vault is not None else []
        inside = folder.resolve() if in_zone else folder.parent.resolve()     # a wiki's own folder, raw records and all
        found_in = []                                 # (folder, files), in walk order
        # What the zone's git ignores is known before the walk, so an ignored folder is never entered.
        left_out = git_ignored(folder) if in_zone else set()
        for here, dirs, files in os.walk(folder):
            # A folder that tops a repository of its own (a `.git` folder, or the file a worktree has) is not walked.
            dirs[:] = sorted(d for d in dirs if walked(folder, here, d, in_zone) and not (Path(here) / d / ".git").exists()
                             and Path(here, d).relative_to(folder).as_posix() not in left_out)
            found_in.append((here, files))
        for here, files in found_in:
            for f in sorted(files):
                if not f.endswith(".md") or f == "AGENTS.md" or f.startswith((".", "_")):
                    continue
                if here == str(folder) and (f in ("index.md", "log.md") and folder.name == "wiki"
                                            or f == "Todo.md" and folder.parent.name == "Zones"):
                    continue
                path = Path(here) / f
                if path.is_symlink() and not within(path, inside):
                    continue
                if filters and vt.ignored(path.relative_to(vault).as_posix(), filters):
                    continue
                notes.append((place, folder, path, in_zone))
    rel = {path: path.relative_to(root).with_suffix("").as_posix() for _, _, path, _ in notes}
    by_rel = {r: p for p, r in rel.items()}
    # A link that is not a whole path resolves to the shortest path that ends in it after a slash, and else to the shortest
    # note of its name; among paths as long, the first walked. Each note goes in once under every such ending, so a link is
    # a lookup, not a pass over every note (#260).
    by_base: Dict[str, Path] = {}
    by_tail: Dict[str, Path] = {}
    for p in sorted(rel, key=lambda q: len(rel[q])):
        by_base.setdefault(p.stem.lower(), p)
        parts = rel[p].split("/")
        for i in range(1, len(parts)):
            by_tail.setdefault("/".join(parts[i:]), p)
    index = {path: i for i, (_, _, path, _) in enumerate(notes)}
    records, edges = [], set()
    for place, folder, path, in_zone in notes:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        fm = lib.parse_frontmatter_text(text) if text else {}
        records.append({"place": place, "zone": in_zone, "path": _rel(path, root), "rel": path.relative_to(folder).as_posix(),
                        "type": as_text(fm.get("type")).strip().lower(), "status": as_text(fm.get("status")).strip().lower(),
                        "updated": _iso(as_date(fm.get("updated"))), "party": tags(fm.get("party") or fm.get("parties")),
                        "title": as_text(fm.get("title")).strip()})
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
    return {"places": [{"name": place, "folder": _rel(folder, root), "zone": in_zone} for place, folder, in_zone in places],
            "notes": records, "edges": [list(e) for e in sorted(edges)]}


def system_lookup(projects: List[dict]) -> Dict[str, str]:
    """The notes of the projects kept in System/ by the names a Todo line's link may use: the path from the workspace
    without its suffix, and the note's own name, both lower-cased; the first note to claim a name keeps it."""
    out: Dict[str, str] = {}
    for project in projects:
        for rel in project["notes"]:
            out.setdefault(Path(rel).with_suffix("").as_posix().lower(), rel)
            out.setdefault(Path(rel).stem.lower(), rel)
    return out


def build(root, scope: Optional[List[str]] = None, only: Optional[Iterable[str]] = None, today: Optional[dt.date] = None) -> dict:
    """The view model of the workspace at `root`. `scope` names the zones whose records may be shown: None is every
    zone and the Meetings wiki's inbox, a list is those zones alone and no wiki. `only` names the parts to build, from
    `PARTS`; None builds them all, and a part not named is left out of the document, so a caller that needs one part does
    not pay for the rest. `today` is the day the Todo part counts as ticked today (the day it is run, by default). Reads; never writes."""
    root = Path(root)
    base = (root / "Zones")
    real = {z.name for z in _work().zones(root)}
    wanted = None if scope is None else set(scope)
    parts = set(PARTS) if only is None else set(only)
    zones: List[dict] = []
    inbox: List[dict] = []
    today = today or dt.date.today()
    system = system_projects(root) if wanted is None and parts & {"system", "todo"} else []
    lookup = system_lookup(system)
    if parts & {"work", "inbox", "todo", "questions"}:
        for zone in _visible_dirs(base):
            if wanted is not None and zone.name not in wanted:
                continue
            if zone.name not in real:
                # A link is no zone: it has no work, and its Inbox would be another folder's.
                zones.append({"name": zone.name, "linked": True, "done": 0, "held": [], "projects": {}, "open_links": [], "work": []})
                continue
            record = _zone_work(root, zone) if "work" in parts else {"name": zone.name, "linked": False}
            if "todo" in parts:
                record["todo"] = _todo().zone_todo(zone, root, today, lookup, _lib().live_files, _allowed(root))
            if "questions" in parts:
                record["questions"] = zone_questions(zone, today)
            zones.append(record)
            if "inbox" in parts:
                q = _queue_inbox(zone.name, "zone", zone / "Inbox", zone.resolve(), root)
                if q:
                    inbox.append(q)
        if wanted is None and "inbox" in parts:
            wiki = root / "Wikis" / "Meetings"
            q = _queue_inbox("Meetings", "wiki", wiki / "raw" / "inbox", wiki.resolve(), root)
            if q:
                inbox.append(q)
    out = {"api": API, "zones": zones, "queues": {"inbox": inbox}}
    if parts & {"todo", "questions"}:
        out["today"] = today.isoformat()
    if "system" in parts:
        out["system"] = system
    if "wikis" in parts:
        out["wikis"] = wiki_records(root) if wanted is None else []
    if "repos" in parts:
        out["repos"] = repo_records(root, wanted)
    if "example" in parts:
        out["example"] = example_zone(root, wanted)
    if "graph" in parts:
        out["graph"] = graph_records(root, wanted)
    out["left"] = list(LEFT)
    return out


def _settings():
    return _sibling("view_settings.py", "garrick_view_settings")


def settings(root, extras=None, jobs=None, only=None) -> dict:
    """What the Settings dialog shows, as one document (`view_settings.read`): the choices, the fade settings, the notices,
    the channels, the read guard, the preview flags, this computer's role. `extras` is the status extra's folder, `jobs`
    this Mac's launchd agents as the page reads them, `only` the parts to read. Reads; never writes."""
    return _settings().read(root, extras, jobs, only)


def _fm_value(raw: str):
    """One frontmatter value for the small parser: a trailing comment
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


def frontmatter(path: Path, lib=None) -> dict:
    """The note's frontmatter, as the page's own helper read it before 0.81.0 (#650): `lib.parse_frontmatter` (the workspace's own
    garrick_lib) when one is given, a small parser otherwise that also drops trailing comments and reads block lists.
    Only the frontmatter is ever read from a note here. {} where the note does not read."""
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
            out[key] = (out[key] if isinstance(out.get(key), list) else []) + [_fm_value(item.group(1))]
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:(.*)$", line)
        key = m.group(1) if m else None
        if m:
            out[key] = _fm_value(m.group(2))
    return out


def jobs_reader():
    """The reader of the jobs folder and this Mac's launchd agents (`view_jobs`). Not part of `build()`: they are this Mac's."""
    return _sibling("view_jobs.py", "garrick_view_jobs")


def app_reader():
    """The reader of the files the App keeps under `System/` and of the check's kept result (`view_app`). Not part of `build()`:
    they name every zone, or are this Mac's."""
    return _sibling("view_app.py", "garrick_view_app")


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Print the view model of a workspace as JSON.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--zone", action="append", help="show this zone alone (repeatable)")
    args = ap.parse_args(argv)
    print(json.dumps(build(Path(args.root).resolve(), args.zone), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
