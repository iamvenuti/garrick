#!/usr/bin/env python3
"""usage.py: what the Garrick App is used for, from records that already exist (#651).

    python3 System/tools/usage.py [--days N] [--root FOLDER]

Prints, for the last N days (30 unless said):
- how often each card of the App was opened, from `System/garrick-usage.json`, which the App keeps while the setting
  `usage-counts` is on (it is, unless it was switched off): a card's name, a day and a count, nothing else;
- the wraps, by outcome, and what Ask did, by outcome, from the operations journal (`operations.jsonl`) and the App's
  action log (`page-actions.log`), both in the jobs folder. They are counted for each zone on its own: no figure adds two
  zones together. Nothing new records either; where a record does not say, the report says it could not count.

Each source it could not read is named. It runs with the status extra absent: it reads the files and nothing else, and it
writes nothing. Standard library only.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

USAGE_FILE = ("System", "garrick-usage.json")
SETTING = "usage-counts"
OUTCOMES = ("saved", "refused", "conflict", "failed")
DAY = re.compile(r"\d{4}-\d\d-\d\d")
# One line of page-actions.log: "2026-11-22 10:00:00  wrap zone="Work" ...  ->  ok: said  (ask)".
LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d) \d\d:\d\d:\d\d  (\S+)(.*?)  ->  (ok|refused): .*?(?:  \(([a-z]+)[;)][^\n]*)?$")
ZONE_FIELD = re.compile(r' zone=("(?:[^"\\]|\\.)*")')


def jobs_folder() -> Path:
    """The jobs folder, where the operations journal and the action log are kept."""
    set_to = os.environ.get("GARRICK_JOBS_DIR")
    if set_to:
        return Path(set_to).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "garrick-jobs"
    return Path.home() / ".local" / "state" / "garrick-jobs"


def _lib():
    import importlib.util
    mod = sys.modules.get("garrick_lib")
    if mod is None:
        spec = importlib.util.spec_from_file_location("garrick_lib", str(Path(__file__).with_name("garrick_lib.py")))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["garrick_lib"] = mod
        spec.loader.exec_module(mod)
    return mod


def counting_on(root: Path) -> bool:
    """The setting: on unless the settings file says false. A settings file that does not read is no switch-off."""
    try:
        return _lib().read_settings(root).get(SETTING) is not False
    except Exception:
        return True


def _real_day(day) -> bool:
    if not (isinstance(day, str) and DAY.fullmatch(day)):
        return False
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        return False
    return True


def read_counts(root: Path) -> Tuple[Optional[Dict[str, Dict[str, int]]], str]:
    """(card -> day -> count, "") from the counts file; (None, why) when there is no file or it does not read as the
    App writes it. A file that does not read gives nothing: no key of it is trusted."""
    path = Path(root).joinpath(*USAGE_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "no counts file"
    except (OSError, ValueError):
        return None, "the counts file does not read"
    counts = data.get("counts") if isinstance(data, dict) and data.get("v") == 1 else None
    if not isinstance(counts, dict):
        return None, "the counts file is not the App's"
    out: Dict[str, Dict[str, int]] = {}
    for card, days in counts.items():
        if not isinstance(card, str) or not isinstance(days, dict):
            return None, "the counts file is not the App's"
        for day, n in days.items():
            if not (_real_day(day) and isinstance(n, int) and not isinstance(n, bool) and n >= 0):
                return None, "the counts file is not the App's"
        out[card] = dict(days)
    return out, ""


def card_opens(counts: Dict[str, Dict[str, int]], since: str) -> Dict[str, int]:
    """Opens per card on or after `since` (a YYYY-MM-DD day; the days compare as text)."""
    return {card: n for card, n in sorted((c, sum(v for d, v in days.items() if d >= since)) for c, days in counts.items()) if n}


def _bump(table: Dict[str, Dict[str, int]], zone: str, outcome: str) -> None:
    row = table.setdefault(zone, {})
    row[outcome] = row.get(outcome, 0) + 1


def read_journal(folder: Path, since: dt.date, workspace: str) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, int]], str]:
    """(wraps, ask) from operations.jsonl, each zone -> outcome -> count, and why not when it cannot be read. One entry per
    operation, its last record; a record of another workspace, or one that has not finished, is left out."""
    path = folder / "operations.jsonl"
    wraps: Dict[str, Dict[str, int]] = {}
    ask: Dict[str, Dict[str, int]] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return wraps, ask, "no operations journal"
    except OSError:
        return wraps, ask, "the operations journal does not read"
    latest: Dict[str, dict] = {}
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("op"), str):
            latest[rec["op"]] = rec
    cut = dt.datetime.combine(since, dt.time()).timestamp()
    for rec in latest.values():
        if rec.get("workspace") != workspace or rec.get("outcome") not in ("saved", "refused", "crashed", "unknown", "lost"):
            continue
        when = rec.get("done") or rec.get("at")
        if not isinstance(when, (int, float)) or when < cut:
            continue
        outcome = "saved" if rec["outcome"] == "saved" else "refused" if rec["outcome"] == "refused" else "failed"
        zone = rec.get("zone") if isinstance(rec.get("zone"), str) and rec.get("zone") else "(no zone)"
        if rec.get("verb") == "wrap":
            _bump(wraps, zone, outcome)
        if rec.get("via") == "ask":
            _bump(ask, zone, outcome)
    return wraps, ask, ""


def read_action_log(folder: Path, since: dt.date, journaled=frozenset()) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, int]], str]:
    """(wraps, ask) from page-actions.log. The log says ok or refused only, so a wrap that did not save is counted as
    refused here, whatever it was. A verb the journal keeps (`journaled`) is counted from the journal alone, so no
    action is counted twice."""
    path = folder / "page-actions.log"
    wraps: Dict[str, Dict[str, int]] = {}
    ask: Dict[str, Dict[str, int]] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return wraps, ask, "no action log"
    except OSError:
        return wraps, ask, "the action log does not read"
    for line in lines:
        m = LOG_LINE.match(line)
        if not m or m.group(1) < since.isoformat():
            continue
        day, verb, middle, ok, via = m.groups()
        z = ZONE_FIELD.search(middle)
        try:
            zone = json.loads(z.group(1)) if z else "(no zone)"
        except ValueError:
            zone = "(no zone)"
        outcome = "saved" if ok == "ok" else "refused"
        if verb in journaled:
            continue
        if verb == "wrap":
            _bump(wraps, zone or "(no zone)", outcome)
        if via == "ask":
            _bump(ask, zone or "(no zone)", outcome)
    return wraps, ask, ""


def merge(*tables: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    """Tables of one kind from two sources, added zone by zone: a zone's figures are never added to another's."""
    out: Dict[str, Dict[str, int]] = {}
    for table in tables:
        for zone, row in table.items():
            for outcome, n in row.items():
                out.setdefault(zone, {})[outcome] = out.get(zone, {}).get(outcome, 0) + n
    return out


def table_lines(table: Dict[str, Dict[str, int]]) -> List[str]:
    if not table:
        return ["  none"]
    return ["  %s: %s" % (zone, ", ".join("%s %d" % (o, table[zone][o]) for o in sorted(table[zone], key=lambda k: (OUTCOMES.index(k) if k in OUTCOMES else 9, k))))
            for zone in sorted(table)]


def report(root: Path, days: int = 30, today: Optional[dt.date] = None, folder: Optional[Path] = None) -> Tuple[str, List[str]]:
    """(the report, the sources it could not read)."""
    root = Path(root)
    today = today or dt.date.today()
    since = today - dt.timedelta(days=max(1, days) - 1)
    folder = folder or jobs_folder()
    failed: List[str] = []
    out = ["Garrick usage, %d day%s: %s to %s" % (days, "" if days == 1 else "s", since.isoformat(), today.isoformat()), ""]
    out.append("Card opens")
    if not counting_on(root):
        out.append("  No card data: counting card opens is switched off.")
    else:
        counts, why = read_counts(root)
        if counts is None:
            out.append("  No card data: %s." % why)
            if why != "no counts file":
                failed.append("System/garrick-usage.json: %s" % why)
        else:
            opens = card_opens(counts, since.isoformat())
            out += ["  %-14s %d" % (card, n) for card, n in sorted(opens.items(), key=lambda kv: (-kv[1], kv[0]))] or ["  none in this period"]
    workspace = _workspace_id(root)
    jw, ja, why_j = read_journal(folder, since, workspace)
    lw, la, why_l = read_action_log(folder, since, set(_operations().RECORDED))
    for why in (why_j, why_l):
        if why:
            failed.append(why)
    out += ["", "Wraps, by outcome, for each zone", *table_lines(merge(jw, lw)),
            "", "Ask actions, by outcome, for each zone", *table_lines(merge(ja, la)),
            "  The autonomy level is in neither record, so it is not counted."]
    if failed:
        out += ["", "Could not read: " + "; ".join(failed) + "."]
    return "\n".join(out) + "\n", failed


def _operations():
    import importlib.util
    mod = sys.modules.get("garrick_operations")
    if mod is None:
        spec = importlib.util.spec_from_file_location("garrick_operations", str(Path(__file__).with_name("operations.py")))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["garrick_operations"] = mod
        spec.loader.exec_module(mod)
    return mod


def _workspace_id(root: Path) -> str:
    return _operations().workspace_id(str(root))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="What the Garrick App is used for, from the records it keeps.")
    ap.add_argument("--days", type=int, default=30, help="how many days back, today included (default 30)")
    ap.add_argument("--root", default=None, help="the workspace (default: the one this tool is in)")
    args = ap.parse_args(argv)
    if args.days < 1:
        ap.error("--days is at least 1")
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent.parent
    text, _ = report(root, args.days)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
