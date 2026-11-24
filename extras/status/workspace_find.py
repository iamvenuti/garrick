#!/usr/bin/env python3
"""workspace_find.py: where the workspace is, and the zone folders in it, before a view model exists (#650).

The page is a program that has to find its workspace before it can load anything of it, and it must say "Garrick needs
updating" where the workspace's own tools are older than the page. Both happen before `System/tools/view.py` is loaded,
and both must work when it is missing, so neither can be a reader of the core. They are this extra's, by design: this
module ships in the same folder as `status.py` (`System/status/`), updates with it, and holds the two things that run
first.

It never loads or runs anything from a candidate folder. A folder is a workspace when it holds `System/rules.md` and
`Zones/`, which is a look at two names and nothing else; code in it is read only after that, and only by the page.

Standard library only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

sys.dont_write_bytecode = True


def is_workspace(folder: Path) -> bool:
    """Whether a folder holds `System/rules.md` and a `Zones/` folder."""
    return (folder / "System" / "rules.md").is_file() and (folder / "Zones").is_dir()


def find_workspace(given: Optional[str]) -> Path:
    """The folder named, or the one this runs in. A named folder must hold System/rules.md and Zones/, so a mistyped path stops
    here instead of gaining a System/generated/ of its own."""
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


def subfolders(folder: Path) -> List[Path]:
    """The folders in `folder` whose names do not start with `.` or `_`, by name; none where it is not a folder."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def zone_folders(ws: Path) -> List[Path]:
    """The zone folders of a workspace, by name: what the page lists while the core's view of the work is missing."""
    return subfolders(ws / "Zones")


def zone_folder(ws: Path, name: str) -> Path:
    """Where a zone's folder is, by its name. A path, never a read."""
    return ws / "Zones" / name
