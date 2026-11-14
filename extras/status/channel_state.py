#!/usr/bin/env python3
"""channel_state.py: what the Telegram receiver tells the status page (#570).

The receiver (extras/fetch/telegram_receiver.py) is a service, not a timed job. It writes one small file in the jobs
folder, `telegram-status.json`, every few seconds while it runs and when something changes:

    {"pid": 123, "beat": <epoch>, "last_received": <epoch or null>, "state": "running|conflict|stopped|unpaired",
     "why": "...", "queued": n, "running": n, "waiting": n}

The page reads it with `row()`: running or down (a beat older than STALE seconds is down, which is how a crash
shows), and when the last message arrived. It names no chat, no sender and no word of any message.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

sys.dont_write_bytecode = True

FILE = "telegram-status.json"
STALE = 45              # seconds without a beat: the service is down
BEAT = 10               # seconds between beats


def jobs_dir() -> Path:
    given = os.environ.get("GARRICK_JOBS_DIR")
    if given:
        return Path(given).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "garrick-jobs"
    return Path.home() / ".local" / "state" / "garrick-jobs"


def path() -> Path:
    return jobs_dir() / FILE


def write(**fields) -> None:
    p = path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            now = json.loads(p.read_text(encoding="utf-8"))
            now = now if isinstance(now, dict) else {}
        except (OSError, ValueError):
            now = {}
        now.update(fields, pid=os.getpid(), beat=time.time())
        tmp = p.with_name(p.name + ".new")
        tmp.write_text(json.dumps(now), encoding="utf-8")
        os.replace(str(tmp), str(p))
    except OSError:
        pass


def read() -> Optional[dict]:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def ago(then: float, now: float) -> str:
    seconds = max(0, int(now - then))
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return "%d minutes ago" % round(seconds / 60)
    if seconds < 129600:
        return "%d hours ago" % round(seconds / 3600)
    return "%d days ago" % round(seconds / 86400)


def row(now: Optional[float] = None) -> dict:
    """{"state": "off|running|down|conflict|unpaired", "said": a sentence, "last": when the last message arrived or ""}.
    `off` when the receiver has never run here: Telegram is opt-in."""
    now = now or time.time()
    data = read()
    if data is None:
        return {"state": "off", "said": "Telegram is not set up.", "last": ""}
    last = ago(data["last_received"], now) if isinstance(data.get("last_received"), (int, float)) else "no message yet"
    state = data.get("state")
    if state in ("conflict", "unpaired"):
        return {"state": state, "said": str(data.get("why") or "The receiver did not start."), "last": last}
    alive = isinstance(data.get("beat"), (int, float)) and now - data["beat"] <= STALE and state == "running"
    if not alive:
        return {"state": "down", "said": "The Telegram receiver is down. Last message: %s." % last, "last": last}
    return {"state": "running", "said": "The Telegram receiver is running. Last message: %s." % last, "last": last}
