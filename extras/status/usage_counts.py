#!/usr/bin/env python3
"""usage_counts.py: the App's count of which cards are opened (#651).

One file, `System/garrick-usage.json` in the workspace, beside the other durable settings and never committed (the root
`.gitignore` leaves it out). It holds a card's name, a day and a count, and nothing else:

    {"v": 1, "counts": {"threads": {"2026-11-22": 3}, "checks": {"2026-11-22": 1}}}

The writer builds that file only from values it has checked: a card must be one of `view.CARDS`, a day is a real date, a
count is a whole number. A name, a path, a zone or free text is refused, and nothing is written. An existing file that is
not exactly in that shape is not read into the new one: the counts start over. With the setting `usage-counts` off nothing
is written. `status.py` owns the file. `System/tools/usage.py` reads it. Standard library only.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Optional

FILE = ("System", "garrick-usage.json")
SETTING = "usage-counts"
KEEP_DAYS = 400                 # older days are dropped when a count is written, so the file stays small
MAX_COUNT = 1_000_000
DAY = re.compile(r"\d{4}-\d\d-\d\d")
ID = re.compile(r"[a-z][a-z-]{0,23}")        # what a card's id looks like; anything else in the file is not ours


class Refused(ValueError):
    """A request that carries something that is not a card id."""


def card_ids(ws: Path):
    """The set of card ids the page has, view.py's CARDS, from the workspace's own copy of the tool or the one beside
    this extra. Without view.py nothing is counted."""
    here = Path(__file__).resolve().parent
    for tools in (Path(ws) / "System" / "tools", here.parent / "tools", here.parent.parent / "template" / "System" / "tools"):
        src = tools / "view.py"
        if src.is_file():
            spec = importlib.util.spec_from_file_location("garrick_view_usage", str(src))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return tuple(mod.CARDS)
    raise Refused("System/tools/view.py is missing; update Garrick")


def on(settings: dict) -> bool:
    """Counting is on unless the settings say false."""
    return settings.get(SETTING) is not False


def real_day(day) -> bool:
    """A day as `YYYY-MM-DD`, and a day that exists."""
    if not (isinstance(day, str) and DAY.fullmatch(day)):
        return False
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        return False
    return True


def clean_day(day) -> str:
    if not real_day(day):
        raise Refused("not a day")
    return day


def read(path: Path) -> Dict[str, Dict[str, int]]:
    """The counts in the file, or {} when there is none, it does not read, or any part of it is not a card, a day and a
    whole count: such a file is dropped whole, and no key of it is carried into the next. A card the page no longer has
    reads as a card still, and `record` leaves it out."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not (isinstance(data, dict) and set(data) == {"v", "counts"} and data["v"] == 1 and isinstance(data["counts"], dict)):
        return {}
    out: Dict[str, Dict[str, int]] = {}
    for card, days in data["counts"].items():
        if not (isinstance(card, str) and ID.fullmatch(card) and isinstance(days, dict)):
            return {}
        for day, n in days.items():
            if not (real_day(day) and isinstance(n, int) and not isinstance(n, bool) and 0 < n <= MAX_COUNT):
                return {}
        out[card] = dict(days)
    return out


def record(ws: Path, card, today: Optional[dt.date] = None, settings: Optional[dict] = None, ids=None) -> str:
    """Add one to a card's count for today. Returns "counted", "off" (the setting is off: nothing written) or raises
    Refused for anything that is not a card id, writing nothing. The file is built from checked values alone."""
    if not (isinstance(card, str) and ID.fullmatch(card)):
        raise Refused("not a card")
    if card not in (ids if ids is not None else card_ids(ws)):
        raise Refused("not a card")
    if settings is not None and not on(settings):
        return "off"
    day = clean_day((today or dt.date.today()).isoformat())
    path = Path(ws).joinpath(*FILE)
    known = set(ids if ids is not None else card_ids(ws))
    counts = {c: d for c, d in read(path).items() if c in known}      # a card this release does not have is dropped
    cutoff = (dt.date.fromisoformat(day) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    counts = {c: {d: n for d, n in days.items() if d >= cutoff} for c, days in counts.items()}
    row = counts.setdefault(card, {})
    row[day] = min(MAX_COUNT, row.get(day, 0) + 1)
    body = {"v": 1, "counts": {c: dict(sorted(days.items())) for c, days in sorted(counts.items()) if days}}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".garrick-usage-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(body, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, str(path))
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return "counted"
