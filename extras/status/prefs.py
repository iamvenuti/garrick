#!/usr/bin/env python3
"""prefs.py: the choices the page keeps, read and written in one place.

Each zone's colour and icon, and Settings > Opening a thread, are choices a
user makes once and expects to keep, so they live in the workspace's own
settings file, `System/garrick-settings.json`, and are committed with it.
`garrick_lib.py`, in the workspace's `System/tools/`, is the accessor:
`preferences()`, `save_preferences()` and `migrate_shared_settings()`. It
belongs to the workspace, not to this extra, so the cmux desk and anything
else reads the same choices without the page being installed.

This file only finds that accessor, so `status.py`, `page_action.py` and
`ask.py` have one way to the choices and none of their own: the workspace's
own copy of `garrick_lib.py` first, then the one beside this folder (an extra
sits in `System/`, a step from `System/tools/`), then a Garrick clone's
`template/`, which is what the tests run against. Standard library only.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
# What the page tells the user, and what the Mac app reads in Swift. The
# accessor owns it; a test keeps the three in step.
FILE = "System/garrick-settings.json"


class NoAccessor(Exception):
    """No garrick_lib.py to read the choices through."""


_LIBS: Dict[Optional[Path], object] = {}


def _places(ws: Optional[Path]):
    if ws is not None:
        yield Path(ws) / "System" / "tools" / "garrick_lib.py"       # the workspace's own
    yield HERE.parent / "tools" / "garrick_lib.py"                   # System/status/ beside System/tools/
    yield HERE.parent.parent / "template" / "System" / "tools" / "garrick_lib.py"


def lib(ws: Optional[Path] = None):
    """The first garrick_lib with the accessor in it, or None."""
    key = None if ws is None else Path(ws)
    if key not in _LIBS:
        found = None
        for src in _places(key):
            if not src.is_file():
                continue
            try:
                spec = importlib.util.spec_from_file_location("garrick_prefs_lib", str(src))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                continue
            if callable(getattr(mod, "preferences", None)) and callable(getattr(mod, "save_preferences", None)):
                found = mod
                break
        _LIBS[key] = found
    return _LIBS[key]


def read(ws: Path) -> dict:
    """The choices as saved: {"zones": …, "launchers": …, "default": …}, each
    key left out when nothing is saved under it. {} when they cannot be read."""
    found = lib(ws)
    try:
        return found.preferences(ws) if found is not None else {}
    except Exception:
        return {}


def save(ws: Path, chosen: dict) -> dict:
    """Keep these choices, leaving the rest of the file as it is."""
    found = lib(ws)
    if found is None:
        raise NoAccessor("cannot find System/tools/garrick_lib.py, which keeps the settings")
    return found.save_preferences(ws, chosen)


def migrate(ws: Path) -> List[str]:
    """Copy anything a Garrick before 0.25.0 left in
    System/generated/status-settings.json into the committed settings file,
    without replacing a newer choice. Best effort: a workspace that cannot be
    written to keeps reading what it has."""
    found = lib(ws)
    try:
        return found.migrate_shared_settings(ws) if found is not None else []
    except Exception:
        return []
