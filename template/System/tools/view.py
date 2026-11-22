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
     "left": [...]}                            # what the page still reads for itself, by name

    ZONE   {"name": "Work",
            "linked": false,                   # the folder is a link, so it is no zone: no work, no inbox
            "done": 1,                         # how many threads are done
            "held": ["Acme"],                  # projects parked as a whole
            "projects": {"Acme": PROJECT},
            "open_links": [["Pricing"]],       # for each open Todo line that links a note, the notes it links
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

Walls. Every record carries its zone. A count is of one zone or one wiki; nothing here adds
two together. `build(root, scope=["Work"])` holds the records of those zones alone, and no
wiki. A zone folder that is a link is no zone, and an Inbox or a note that resolves outside
the zone it sits in is left out, so a link into another zone shows none of that zone's work.

`left` names what the page reads for itself because no core module owns it yet: the jobs
folder, the operations journal, the App's own files under `System/`, the Todo lists, the
check's kept result, the waiting sessions, the settings.
"""
import datetime as dt
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

API = 1
DONE = {"done", "closed", "archived", "complete", "completed"}
PARKED = {"parked", "dormant", "paused", "on-hold"}
# The verbs that may act on a piece of work, as the page offers them; each must be declared in operations.DECLARED.
PIECE_VERBS = ("park", "wake", "rename", "move", "delete", "continue", "open", "close")
# The cards of the page, by the id each carries (`<details class="card" id=...>`): the one set the App counts opens of (#651).
# Never a thread's or a project's: a row of the Threads card has a name in it, and a name is never counted.
CARDS = ("start", "your-work", "waiting-now", "threads", "checks", "jobs", "calls", "repos", "wikis", "graph")
# What the page reads for itself, by name, until a core module owns it.
LEFT = ("jobs folder state", "operations journal", "System/ files of the App", "Todo lists", "the check's kept result",
        "waiting sessions", "settings", "wiki lists", "repositories")

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
    try:
        text = (zone / "Todo.md").read_text(encoding="utf-8", errors="replace")
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
        if hub_path.is_file():           # what the project card's dialogs say: its files, and the layout change it offers
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
                           "parked" if state == "parked" else "row", held, hub_path if hub_path.is_file() else None, True)
            (parked if state == "parked" else rows).append(piece)
        # The hub's own resume point beside its threads: a row of Your work and no row of the Threads card.
        if any(r.beside for r in found) and not hub_parked and hub_state not in DONE:
            hubs.append(_piece(root, judge, links, zone, project, project.name, hub_path, hub_path, pfm, pfm, hub_state, "hub", False,
                               hub_path if hub_path.is_file() else None, True))
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


def build(root, scope: Optional[List[str]] = None) -> dict:
    """The view model of the workspace at `root`. `scope` names the zones whose records may be shown: None is every
    zone and the Meetings wiki's inbox, a list is those zones alone and no wiki. Reads; never writes."""
    root = Path(root)
    base = (root / "Zones")
    real = {z.name for z in _work().zones(root)}
    wanted = None if scope is None else set(scope)
    zones: List[dict] = []
    inbox: List[dict] = []
    for zone in _visible_dirs(base):
        if wanted is not None and zone.name not in wanted:
            continue
        if zone.name not in real:
            # A link is no zone: it has no work, and its Inbox would be another folder's.
            zones.append({"name": zone.name, "linked": True, "done": 0, "held": [], "projects": {}, "open_links": [], "work": []})
            continue
        zones.append(_zone_work(root, zone))
        q = _queue_inbox(zone.name, "zone", zone / "Inbox", zone.resolve(), root)
        if q:
            inbox.append(q)
    if wanted is None:
        wiki = root / "Wikis" / "Meetings"
        q = _queue_inbox("Meetings", "wiki", wiki / "raw" / "inbox", wiki.resolve(), root)
        if q:
            inbox.append(q)
    return {"api": API, "zones": zones, "queues": {"inbox": inbox}, "left": list(LEFT)}


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
