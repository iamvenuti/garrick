#!/usr/bin/env python3
"""view_app.py: the files the App keeps under `System/`, and the check's kept result, as plain values (#650).

The App's page reads a handful of small files that belong to no zone: what the drift check found, the installer's version
stamp, what the last run of Process the Inbox left, the release notes, the check's last result, the Nurture record of a
day, the check settings, and a zone's follow-up records. Until 0.81.0 the page (`extras/status/status.py`) read each one
for itself while it worked out what the file means. This module is the one reader: it reads the same files, writes
nothing, starts no process and opens no socket, and `status.py` keeps what each value means and how it is worded.

It is not part of `view.build()`. These files name every zone, or are this Mac's, so a document built for one zone holds
none of them. `view.app_reader()` is the way the page reaches it. Each reader takes the folder, or the file, that the
page's own reader took, and works nothing out more widely.

A file that is missing, is not JSON or does not read gives the empty value of its shape (`{}`, `None`, ""), never an
exception and never a path or the text of an error. What each file means is the page's: only the read is here. The page
still writes its own files (the page, its flags, the check's kept result): a file the page both reads and writes has its
read here and its write there.

    DRIFT     {"files": [{"state": "drifted", "project": "Acme", "file": "Threads/Pricing/memo.docx", ...}]}   # drift.py's own file
    STAMP     {"from": "release", "tag": "v0.80.0", ...}                  # System/garrick-version.json
    INBOX     {"at": "2026-11-20T09:00:00", "state": "done", "say": "...", "places": {...}}       # status-inbox.json, or None
    CHECK     {"workspace": "/w", "at": 1763000000.0, "result": {...}}    # the kept check result, or None
    REPORT    {"standing": [{"kind": "wall", "path": "Zones/Work/a.md:3", ...}]}      # Nurture's record of one day
    SETTINGS  {"todo-chase-days": {"Work": 3}}                              # System/garrick-checks.json
    FOLLOWUPS {"<line key>": {...}}                                          # a zone's .todo-followups.json
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Optional

sys.dont_write_bytecode = True

API = 1
DRIFT = ("System", "generated", "drift.json")
STAMP = ("System", "garrick-version.json")
INBOX_STATE = ("System", "generated", "status-inbox.json")
CHANGELOG = ("System", "garrick-changelog.md")
CHECK_SETTINGS = ("System", "garrick-checks.json")
FOLLOWUPS = ".todo-followups.json"


def _object(path: Path) -> Optional[dict]:
    """The JSON object in a file, or None where it is missing, does not read or is not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def drift(root: Path) -> dict:
    """DRIFT: what drift.py last found worth a look, from `System/generated/drift.json`; {} for none."""
    return _object(Path(root).joinpath(*DRIFT)) or {}


def version_stamp(root: Path) -> dict:
    """STAMP: the installer's stamp, `System/garrick-version.json`; {} for none."""
    return _object(Path(root).joinpath(*STAMP)) or {}


def inbox_run(root: Path) -> Optional[dict]:
    """INBOX: what the last background run of Process the Inbox left for the page, as written; None for none. Whether it is
    recent, and whether a run it says is going still is, is the page's to say."""
    return _object(Path(root).joinpath(*INBOX_STATE))


def kept_check(store: Path) -> Optional[dict]:
    """CHECK: the result a build kept in `store`, as written; None for none. Whose it is, and how old, is the page's to say."""
    return _object(Path(store))


def changelog(root: Path) -> Optional[str]:
    """The release notes this workspace was installed with, `System/garrick-changelog.md`, as text; None for none."""
    try:
        return Path(root).joinpath(*CHANGELOG).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def nurture_report(root: Path, parts, day: dt.date) -> Optional[dict]:
    """REPORT: Nurture's record of `day`, in the folder `parts` names under the workspace (nurture.py's own REPORTS, which
    the caller passes: the record's place is Nurture's to say); None for none."""
    return _object(Path(root).joinpath(*parts, "%s.json" % day.isoformat()))


def check_settings(root: Path) -> dict:
    """SETTINGS: `System/garrick-checks.json`; {} for none."""
    return _object(Path(root).joinpath(*CHECK_SETTINGS)) or {}


def follow_ups(folder: Path) -> dict:
    """FOLLOWUPS: the zone folder's `.todo-followups.json`, as the todo skill's script wrote it; {} for none."""
    return _object(Path(folder) / FOLLOWUPS) or {}
