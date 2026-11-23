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

AREAS = {"SYSTEM": SYSTEM}
