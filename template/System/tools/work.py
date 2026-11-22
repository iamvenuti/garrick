#!/usr/bin/env python3
"""One reader of the piece of work, shared by every part of Garrick.

A workspace holds zones, a zone holds projects, and a project holds threads. Which of
those is a piece of work, which is a heading over separate pieces, and where each one
keeps its resume point and its papers, is decided here and nowhere else. `next_up`,
`briefing`, the status page, the Ask box, `intake` and the nightly jobs read the
workspace through `pieces()`, so a change to the unit of work is taught once.

Standard library only, and no assistant: the tool reads folders and notes and writes
nothing.

The rules
- A project is a folder in a zone with a hub note, `<Project>/<Project>.md`, or thread
  notes, `<Project>/Threads/<Thread>/<Thread>.md`. Folders that start with `.` or `_`,
  `archive`, `Inbox`, `Sources` and `Deliverables` are not projects. A thread folder
  without its note is not a thread.
- A hub whose frontmatter says `layout: thread-first` is a heading: one record, kind
  `heading`, and it has no resume point of its own.
- Any other hub is a piece of work when the project has no thread notes (the project is
  its own single thread: `own`), or when it holds a `### Resume here` block beside its
  threads (`beside`). `hub_keeps_resume()` is the one answer to the second.
- Each thread note is a piece of work.

The record, `Work`, one per piece or heading. Its field names are stable: the status
page's view model builds on them.
- `identity`: "Zone/Project" for a hub, "Zone/Project/Thread" for a thread.
- `zone`, `project`: folder names. `thread`: the thread's name, or None for a hub.
- `kind`: "piece" or "heading".
- `status`: the note's own `status:`, lower-cased, "" when it has none.
- `hub_status`: the hub's `status:`, the same way, "" with no hub. A parked project
  parks its threads: the reader reports the hub's status, and the caller decides what
  its own words for parked and done are.
- `note`: the resume note, a Path. `folder`: the papers folder, a Path: the project's
  for a hub, the thread's for a thread (for a `beside` hub, the project's folder, which
  also holds `Threads/`).
- `hub`: the hub note, or None. `typed`: the hub says `type: project`.
- `own`: the hub is the project's single thread. `beside`: the hub keeps its own resume
  point beside its threads. `keeps_resume`: the hub holds a `### Resume here` block (always
  true for `beside`, never for a heading); a thread's is False.

Walls. `pieces(root)` returns each record with its zone; `pieces(root, zone="Work")`
returns that zone's alone. Nothing inside a zone is followed out of it: a link to a
folder that resolves outside the zone is left out. Nothing here adds two zones into
one figure.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

RESUME_HEADING = "### Resume here"
# Folders of a zone that are not projects.
NOT_PROJECTS = frozenset({"archive", "Inbox", "Sources", "Deliverables"})

_LIB = None


def _lib():
    """garrick_lib, beside this file: the one parser of a note's frontmatter."""
    global _LIB
    if _LIB is None:
        _LIB = sys.modules.get("garrick_lib")
        if _LIB is None or not callable(getattr(_LIB, "parse_frontmatter", None)):
            src = Path(__file__).with_name("garrick_lib.py")
            spec = importlib.util.spec_from_file_location("garrick_lib", str(src))
            _LIB = importlib.util.module_from_spec(spec)
            sys.modules["garrick_lib"] = _LIB
            spec.loader.exec_module(_LIB)
    return _LIB


def hub_keeps_resume(text: str, fm: Optional[dict] = None) -> bool:
    """Does a project's hub hold a resume point of its own, the main line of a project that is one
    piece of work? It does while it has a `### Resume here` block; an `### Outcome` in that place
    ends it, and a heading (`layout: thread-first`) never has one. It stands beside the project's
    threads, so every reader of resume points reads it whether the project has threads or not."""
    if str((fm or {}).get("layout") or "").strip().lower() == "thread-first":
        return False
    return any(l.strip().lower() == RESUME_HEADING.lower() for l in text.splitlines())


@dataclass(frozen=True)
class Work:
    identity: str
    zone: str
    project: str
    thread: Optional[str]
    kind: str
    status: str
    hub_status: str
    note: Path
    folder: Path
    hub: Optional[Path]
    typed: bool
    own: bool
    beside: bool
    keeps_resume: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _text(value) -> str:
    return str(value or "").strip().lower()


def _dirs(folder: Path, inside: Path) -> List[Path]:
    """The visible folders of `folder`, by name, none of which resolves outside `inside`."""
    try:
        found = sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
    except OSError:
        return []
    return [p for p in found if _within(p, inside)]


def _within(path: Path, inside: Path) -> bool:
    try:
        real = path.resolve()
    except (OSError, RuntimeError):
        return False
    return real == inside or inside in real.parents


def _note(path: Path, inside: Path) -> bool:
    return path.is_file() and _within(path, inside)


def zones(root: Path) -> List[Path]:
    """The zone folders of a workspace, by name."""
    try:
        return sorted(p for p in (Path(root) / "Zones").iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
    except OSError:
        return []


def project_pieces(root: Path, zone: Path, project: Path) -> List[Work]:
    """The records of one project of one zone."""
    lib = _lib()
    inside = zone.resolve()
    hub = project / (project.name + ".md")
    hub = hub if _note(hub, inside) else None
    pfm = lib.parse_frontmatter(hub) if hub else {}
    hub_status = _text(pfm.get("status")) if hub else ""
    typed = _text(pfm.get("type")) == "project"
    heading = _text(pfm.get("layout")) == "thread-first"
    threads = [(t, t / (t.name + ".md")) for t in _dirs(project / "Threads", inside)] if _within(project / "Threads", inside) else []
    threads = [(t, n) for t, n in threads if _note(n, inside)]
    base = dict(zone=zone.name, project=project.name, hub=hub, typed=typed, hub_status=hub_status)
    out: List[Work] = []
    keeps = bool(hub) and hub_keeps_resume(hub.read_text(encoding="utf-8", errors="replace"), pfm)
    if hub is not None:
        if heading:
            out.append(Work(identity="%s/%s" % (zone.name, project.name), thread=None, kind="heading", status=hub_status,
                            note=hub, folder=project, own=False, beside=False, keeps_resume=False, **base))
        elif not threads:
            out.append(Work(identity="%s/%s" % (zone.name, project.name), thread=None, kind="piece", status=hub_status,
                            note=hub, folder=project, own=True, beside=False, keeps_resume=keeps, **base))
        elif keeps:
            out.append(Work(identity="%s/%s" % (zone.name, project.name), thread=None, kind="piece", status=hub_status,
                            note=hub, folder=project, own=False, beside=True, keeps_resume=True, **base))
    for folder, note in threads:
        out.append(Work(identity="%s/%s/%s" % (zone.name, project.name, folder.name), thread=folder.name, kind="piece",
                        status=_text(lib.parse_frontmatter(note).get("status")), note=note, folder=folder, own=False,
                        beside=False, keeps_resume=False, **base))
    return out


def pieces(root: Path, zone: Optional[str] = None) -> List[Work]:
    """Every piece of work and heading of a workspace, or of one zone, by zone, project and thread. A project
    whose hub and thread notes are all missing has no record."""
    out: List[Work] = []
    for z in zones(Path(root)):
        if zone is not None and z.name != zone:
            continue
        inside = z.resolve()
        for project in _dirs(z, inside):
            if project.name in NOT_PROJECTS:
                continue
            out += project_pieces(Path(root), z, project)
    return out


def by_project(records: List[Work]) -> Dict[tuple, List[Work]]:
    """The records grouped by (zone, project), in the order given."""
    out: Dict[tuple, List[Work]] = {}
    for r in records:
        out.setdefault((r.zone, r.project), []).append(r)
    return out


def work_root(path: Path) -> Path:
    """The workspace a note or folder inside a zone belongs to: the folder above `Zones`."""
    for p in [Path(path)] + list(Path(path).parents):
        if p.parent.name == "Zones":
            return p.parent.parent
    return Path(path)


def own_needs_type(records: List[Work]) -> List[Work]:
    """A display filter, kept from the status page: a hub is a row of the page, as its project's single thread,
    only when it says `type: project`. Every other reader counts a hub with no `type:` as a piece of work."""
    return [r for r in records if not (r.own and not r.typed)]
