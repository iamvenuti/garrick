"""The page's old reads, frozen as v0.76.0 had them (#650): the oracle the view model's shadow test compares against.

These are `status.py`'s own functions for the Threads card, the Your work rows and the inbox rows, copied word for word
before the page moved onto the view model. They read the workspace by themselves, which the page no longer does; they
stay here only so that a test can say the view model and the old code agree. They borrow the page's small helpers
(`frontmatter`, `tags`, `as_date`, `visible_dirs`, `work_reader`), which the page still holds. Never edited: a difference
the view model should keep is written into the shadow test as a named display rule, not changed here.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def old_reads(status):
    """The old functions, bound to the page module `status`, as a namespace."""
    g = {"dt": dt, "re": re, "os": os, "subprocess": subprocess, "Path": Path, "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple}
    for name in ("frontmatter", "as_text", "tags", "as_date", "visible_dirs", "work_reader", "workspace_lib", "PARKED", "DONE"):
        g[name] = getattr(status, name)
    exec(compile(SOURCE, "old_status_reads", "exec"), g)
    return g


SOURCE = r'''
MONTH = {m.lower(): i + 1 for i, m in enumerate(("January February March April May June July August September "
                                                  "October November December").split())}

SPOKEN_DATE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b")

RESUME = re.compile(r"^#{1,6}\s+Resume here\b", re.I)

RESUME_ROW = re.compile(r"^\|\s*([^|]*?)\s*\|\s*(.*?)\s*\|\s*$")

ENTRY_LINE = re.compile(r"^\*\*(?:[A-Z][a-z]+ \d\d:\d\d, )?(\d{1,2} [A-Za-z]{3,9}\.? \d{4})\.\*\*\s*(.*\S)\s*$")

PLACEHOLDER = re.compile(r"^<[^>]*>$")

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

def thread_row(ws: Path, zone: Path, project: Path, name: str, note: Path, hub: Path, pfm: dict, fm: dict, state: str) -> dict:
    """One row of threads(): a thread note's, or a hub's own."""
    read = resume_read(note)
    has_block, resumed = read["block"], read["date"]
    mark = checkpoint_mark(note, ws)
    updated = as_date(fm.get("updated"))
    when = [d for d in (updated, mark["at"].date() if mark and mark["at"] else None) if d]
    return {"zone": zone.name, "project": project.name, "thread": name, "note": note,
            "rel": note.relative_to(zone).as_posix(), "hub": hub if hub.is_file() else None,
            "party": tags(fm.get("party") or pfm.get("party")),
            "updated": updated, "status": state,
            "resume": has_block, "resumed": resumed,
            "checkpoint": mark, "touched": max(when) if when else None,
            "spoken": as_text(fm.get("spoken")).strip(), "read": read,
            "heading": as_text(pfm.get("layout")).strip().lower() == "thread-first"}

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
    try:
        reader = work_reader(ws)
    except FileNotFoundError:
        # A half-finished update: this page is new and System/tools has no work.py yet. The page builds and says so.
        return {zone.name: {"rows": [], "parked": [], "done": 0, "folder": zone, "held": [], "finished": [], "projects": {},
                            "hubs": [], "needs_update": True} for zone in visible_dirs(ws / "Zones")}
    for zone in visible_dirs(ws / "Zones"):
        rows, parked, done, asleep, finished, projects, hubs = [], [], 0, [], [], {}, []
        for (_, name_), found in reader.by_project(reader.pieces(ws, zone=zone.name)).items():
            project = zone / name_
            hub = found[0].hub
            hub_path = project / (project.name + ".md")
            pfm = frontmatter(hub, ws) if hub else {}
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
                                      "hub": hub, "party": tags(pfm.get("party"))}
            for name, note in notes:
                fm = pfm if note == hub_path else frontmatter(note, ws)
                state = as_text(fm.get("status")).strip().lower()
                if state in DONE:
                    done += 1
                    finished.append({"zone": zone.name, "project": project.name, "thread": name, "note": note,
                                     "hub": hub, "status": "done",
                                     "party": tags(fm.get("party") or pfm.get("party")),
                                     "updated": as_date(fm.get("updated")), "spoken": as_text(fm.get("spoken")).strip()})
                    continue
                held = hub_parked and note != hub_path          # parked with its project, whatever its own status
                state = "parked" if state in PARKED or held else state
                row = thread_row(ws, zone, project, name, note, hub_path, pfm, fm, state)
                if held:
                    row["held"] = True
                (parked if state == "parked" else rows).append(row)
            # The hub's own resume point beside its threads: a row of Your work and no row of the Threads card.
            if any(r.beside for r in found) and not hub_parked and hub_state not in DONE:
                hubs.append(thread_row(ws, zone, project, project.name, hub_path, hub_path, pfm, pfm, hub_state))
        # By name, as you would look for one; the freshness bar carries the age.
        by_name = lambda r: (r["thread"].casefold(), r["project"].casefold())  # noqa: E731
        rows.sort(key=by_name)
        parked.sort(key=by_name)
        finished.sort(key=by_name)
        out[zone.name] = {"rows": rows, "parked": parked, "done": done, "folder": zone, "held": asleep,
                          "finished": finished, "projects": projects, "hubs": hubs}
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

_OPEN: Dict[Path, List[str]] = {}

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
'''
