#!/usr/bin/env python3
"""logs.py: the one log of the remote access service (preview).

A line holds the time, the tool, the grant id, the outcome and how long it took, and nothing else. There is no field for free text, so
there is nowhere for a token, a pairing code, a search, a note or a record to go: a value that does not fit its field is replaced
by a dash. The file lives in the state folder, mode 0600, outside the workspace and outside git, and is cut to a new file at one
megabyte.

Standard library only; runs on the Python that macOS ships (3.9) as well as on the extra's own runtime.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

sys.dont_write_bytecode = True

OUTCOMES = ("ok", "error", "refused", "denied", "started", "stopped")
NAME = re.compile(r"^[a-z][a-z0-9_.:-]{0,39}$")
GRANT = re.compile(r"^g-[0-9a-f]{12}$")
LIMIT = 1_000_000


def _state():
    key = "garrick_remote_state"
    mod = sys.modules.get(key)
    if mod is None:
        spec = importlib.util.spec_from_file_location(key, str(Path(__file__).resolve().parent / "state.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return mod


def line(tool: str, grant: str, outcome: str, ms: int, when: Optional[dt.datetime] = None) -> str:
    """One log line, from values that are each checked against the form they must have."""
    when = when or dt.datetime.now().astimezone()
    return json.dumps({"t": when.isoformat(timespec="seconds"),
                       "tool": tool if isinstance(tool, str) and NAME.match(tool) else "-",
                       "grant": grant if isinstance(grant, str) and GRANT.match(grant) else "-",
                       "outcome": outcome if outcome in OUTCOMES else "error",
                       "ms": int(ms) if isinstance(ms, (int, float)) and 0 <= ms < 10 ** 9 else 0}, sort_keys=True)


def write(tool: str, grant: str, outcome: str, ms: int = 0) -> None:
    """Append a line. A log that cannot be written never stops a call."""
    try:
        st = _state()
        folder = st.ensure_home()
        path = folder / st.LOG_FILE
        if path.exists() and path.stat().st_size > LIMIT:
            os.replace(str(path), str(folder / (st.LOG_FILE + ".1")))
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, st.MODE_FILE)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(line(tool, grant, outcome, ms) + "\n")
    except Exception:
        pass
