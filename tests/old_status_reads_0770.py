"""The page's reads that 0.78.0 moved onto the view model, frozen as v0.77.0 had them (#650): the oracle the shadow tests
compare against, as `old_status_reads.py` is for 0.77.0's three sections.

Each area below is `status.py`'s own code for one section of the page, copied word for word before the section moved.
They read the workspace by themselves, which the page no longer does; they stay here only so that a test can say the
view model and the old code agree. They borrow the page's small helpers, which the page still holds (`HELPERS`). Never
edited: a difference the view model should keep is written into the shadow test as a named display rule, not changed here.

    old = old_reads(status, "SYSTEM")        # a namespace holding the area's old functions
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HELPERS = ("frontmatter", "as_text", "tags", "as_date", "visible_dirs", "work_reader", "workspace_lib", "PARKED", "DONE",
           "todo_lines", "outbox_mod", "machine_role", "line_place", "plain_text", "md_inline", "E")


def old_reads(status, *areas):
    """The old functions of the areas named, bound to the page module `status`, as a namespace."""
    g = {"dt": dt, "re": re, "os": os, "json": json, "hashlib": hashlib, "subprocess": subprocess, "Path": Path, "Dict": Dict,
         "List": List, "Optional": Optional, "Tuple": Tuple}
    for name in HELPERS:
        if hasattr(status, name):
            g[name] = getattr(status, name)
    for area in areas:
        exec(compile(AREAS[area], "old_status_reads_0770:" + area, "exec"), g)
    return g


SYSTEM = r'''
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
'''

TODO = r'''
def line_place(note: Path, zone: Path) -> Tuple[str, str]:
    """The project and the thread a line belongs to, from the note it points at or sits in (#596): a thread's note,
    or any file in its folder, gives both; a project's hub, or a file in the project and not in a thread, gives the
    project alone. A note outside the zone's projects, or not placed, gives neither."""
    try:
        parts = Path(os.path.abspath(str(note))).relative_to(Path(os.path.abspath(str(zone)))).parts
    except ValueError:
        return "", ""
    if len(parts) >= 4 and parts[1] == "Threads":
        return parts[0], parts[2]
    if len(parts) >= 2 and parts[0] not in ("Inbox", "archive") and not parts[0].startswith("."):
        return parts[0], ""
    return "", ""

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
    role = machine_role(ws)
    for zone in visible_dirs(ws / "Zones"):
        todo_md = zone / "Todo.md"
        waits = outbox_mod().pending_marks(ws, zone.name) if role == "roaming" else {}
        held = [dict(h, role=role) for h in outbox_mod().held_requests(ws, zone.name)] if role in ("server", "roaming") else []
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
            project, tname = line_place(note, zone) if note and not t["unsure"] else ("", "")
            return dict(t, when=when, late=late, done=done, field=field if when else "", label=thread, waits=waits.get(t["key"], ""),
                        project=project, tname=tname,
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
        out.append(dict({"zone": zone.name, "file": todo_md if todo_md.is_file() else None, "groups": groups,
                         "done": sorted(done, key=lambda r: r["alpha"]), "open": len(rows),
                         "late": sum(1 for r in rows if r["late"]), "undated": sum(1 for r in rows if r["when"] is None)},
                        **({"held": held} if held else {})))
    return out
'''

AREAS = {"SYSTEM": SYSTEM, "TODO": TODO}
