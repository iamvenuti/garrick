#!/usr/bin/env python3
"""Keep a zone's Todo.md short: the three steps of the todo skill that need
no assistant. Each changes Todo.md and the zone's archive/ only, and only
lines it can name; a commit is left to the caller.

    python3 System/skills/todo/todo.py expire  --zone Work [--days 14]
    python3 System/skills/todo/todo.py archive --zone Work
    python3 System/skills/todo/todo.py tidy    --zone Work
    python3 System/skills/todo/todo.py all     --zone Work      the three, in that order

expire   Records, in the zone's .todo-seen.json (never committed), the first
         night each open line under `## Inbox` and `## Waiting on` was seen.
         An Inbox line with no date, or a Waiting on line with no `⏳` day to
         chase, still there after the zone's days (14, or `todo-expire-days`
         in System/garrick-checks.json: a number, or a number per zone)
         moves, unchanged and still open, to archive/Todo-expired-<YYYY>.md,
         so it can be pasted back. A line the user has triaged has left the
         Inbox, carries a date, or waits with a day to chase, so expiry
         never reaches it.
archive  Moves ticked lines (`- [x]`) done before today to
         archive/Todo-<YYYY>.md, so the list is only as long as what is
         open. A line ticked today stays, for the page's *Done today*.
tidy     Moves priority and date fields written mid-line to the end, where
         Obsidian Tasks reads them, and keeps the Inbox in thread order:
         lines that open with the same [[thread]] together, in the order
         each thread first appears, the rest after them.

Each prints one line of what it did, and `--json` a count for a job.
Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent

DAYS = 14
LEDGER = ".todo-seen.json"
PRIORITY = re.compile(r" *([🔺⏫🔼🔽⏬])️?")
DATE = re.compile(r" *((?:📅|📆|🗓|⏳|⌛|🛫|➕|✅|❌)️? *\d{4}-\d{2}-\d{2})")
DONE = re.compile(r"✅️? *(\d{4}-\d{2}-\d{2})")
CHASE = re.compile(r"(?:⏳|⌛)️? *\d{4}-\d{2}-\d{2}")
ANY_DATE = re.compile(r"(?:📅|📆|🗓|⏳|⌛|🛫)️? *\d{4}-\d{2}-\d{2}")
LABEL = re.compile(r"^- \[ \] \[\[([^\]|#]+)")


def key(line: str) -> str:
    """The key the status page's todo_lines gives the same line."""
    return hashlib.sha1(line.rstrip().encode("utf-8")).hexdigest()[:16]


def fields_last(line: str) -> str:
    prio = [m.group(1) for m in PRIORITY.finditer(line)]
    dates = [m.group(1) for m in DATE.finditer(line)]
    if not prio and not dates:
        return line
    return " ".join([DATE.sub("", PRIORITY.sub("", line)).rstrip()] + prio + dates)


def sections(lines: List[str]) -> Dict[str, Tuple[int, int]]:
    """`## ` heading -> (first line under it, the line after its last)."""
    heads = [(i, l[3:].strip()) for i, l in enumerate(lines) if l.startswith("## ")]
    out = {}
    for n, (i, name) in enumerate(heads):
        out[name] = (i + 1, heads[n + 1][0] if n + 1 < len(heads) else len(lines))
    return out


def with_steps(lines: List[str], picked: List[int]) -> List[int]:
    """The picked task lines and the indented lines under each, its sub-steps
    and notes, which move with it."""
    out = set()
    for i in picked:
        out.add(i)
        j = i + 1
        while j < len(lines) and lines[j][:1] in (" ", "\t") and lines[j].strip():
            out.add(j)
            j += 1
    return sorted(out)


def read(zone: Path) -> List[str]:
    return (zone / "Todo.md").read_text(encoding="utf-8").split("\n")


def write(zone: Path, lines: List[str]) -> None:
    path = zone / "Todo.md"
    tmp = path.with_name(".Todo.md.new")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(tmp, path)


def keep_out(zone: Path, name: str, title: str, moved: List[str]) -> Path:
    """Append lines to archive/<name>, a file that opens with its title."""
    path = zone / "archive" / name
    path.parent.mkdir(exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.is_file() else "# %s\n\n" % title
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + "\n".join(moved) + "\n", encoding="utf-8")
    return path


def expire_days(root: Path, zone: str, given: Optional[int]) -> int:
    if given is not None:
        return given
    try:
        value = json.loads((root / "System" / "garrick-checks.json").read_text(encoding="utf-8")).get("todo-expire-days")
    except (OSError, ValueError, AttributeError):
        return DAYS
    if isinstance(value, dict):
        value = value.get(zone, DAYS)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else DAYS


def expire(root: Path, zone: Path, today: datetime.date, days: Optional[int] = None) -> int:
    limit = expire_days(root, zone.name, days)
    lines = read(zone)
    where = sections(lines)
    ledger = zone / LEDGER
    try:
        seen = json.loads(ledger.read_text(encoding="utf-8"))
        seen = seen if isinstance(seen, dict) else {}
    except (OSError, ValueError):
        seen = {}
    inbox = range(*where.get("Inbox", (0, 0)))
    waiting = range(*where.get("Waiting on", (0, 0)))
    watched = [(i, ANY_DATE) for i in inbox] + [(i, CHASE) for i in waiting]       # a line is safe once it carries this
    watched = [(i, safe) for i, safe in watched if lines[i].startswith("- [ ] ") and "<action>" not in lines[i]]
    for i, _ in watched:
        seen.setdefault(key(lines[i]), today.isoformat())
    gone = []
    for i, safe in watched:
        try:
            first = datetime.date.fromisoformat(seen[key(lines[i])])
        except ValueError:
            continue
        if (today - first).days >= limit and not safe.search(lines[i]):
            gone.append(i)
    if gone:
        gone = with_steps(lines, sorted(gone))
        moved = [lines[i] for i in gone]
        keep_out(zone, "Todo-expired-%d.md" % today.year, "%s: actions nobody triaged, %d" % (zone.name, today.year),
                 ["<!-- %s -->" % today.isoformat()] + moved)
        lines = [l for i, l in enumerate(lines) if i not in set(gone)]
        write(zone, lines)
    live = {key(l) for l in lines if l.startswith("- [ ] ")}
    seen = {k: v for k, v in sorted(seen.items()) if k in live}
    tmp = ledger.with_name(LEDGER + ".new")
    tmp.write_text(json.dumps(seen, indent=0) + "\n", encoding="utf-8")
    os.replace(tmp, ledger)
    return len(gone)


def archive(zone: Path, today: datetime.date) -> int:
    lines = read(zone)
    gone = []
    for i, line in enumerate(lines):
        if not line.startswith("- [x] "):
            continue
        m = DONE.search(line)
        when = datetime.date.fromisoformat(m.group(1)) if m else None
        if when is None or when < today:
            gone.append(i)
    if not gone:
        return 0
    n = len(gone)
    by_year: Dict[int, List[str]] = {}
    for i in gone:
        m = DONE.search(lines[i])
        by_year.setdefault(int(m.group(1)[:4]) if m else today.year, []).extend(lines[j] for j in with_steps(lines, [i]))
    gone = with_steps(lines, gone)
    for year, moved in sorted(by_year.items()):
        keep_out(zone, "Todo-%d.md" % year, "%s: done, %d" % (zone.name, year), moved)
    write(zone, [l for i, l in enumerate(lines) if i not in set(gone)])
    return n


def tidy(zone: Path) -> int:
    lines = read(zone)
    changed = 0
    for i, line in enumerate(lines):
        if line.startswith(("- [ ] ", "- [x] ")):
            new = fields_last(line)
            if new != line:
                lines[i] = new
                changed += 1
    start, end = sections(lines).get("Inbox", (0, 0))
    block = [i for i in range(start, end) if lines[i].startswith("- [ ] ")]
    if block and block == list(range(block[0], block[-1] + 1)):      # only a run of task lines is reordered
        items = [lines[i] for i in block]
        order: List[str] = []
        for l in items:
            m = LABEL.match(l)
            t = m.group(1).rsplit("/", 1)[-1].lower() if m else ""
            if m and t not in order:
                order.append(t)

        def rank(l):
            m = LABEL.match(l)
            return order.index(m.group(1).rsplit("/", 1)[-1].lower()) if m else len(order)
        ranked = sorted(items, key=rank)                              # stable: each thread keeps its own order
        if ranked != items:
            changed += sum(1 for a, b in zip(items, ranked) if a != b)
            lines[block[0]:block[-1] + 1] = ranked
    if changed:
        write(zone, lines)
    return changed


def zone_of(root: Path, name: str) -> Path:
    zones = root / "Zones"
    match = [z for z in (zones.iterdir() if zones.is_dir() else []) if z.is_dir() and z.name.lower() == name.lower()]
    if not match or not (match[0] / "Todo.md").is_file():
        raise SystemExit("todo: no zone %s with a Todo.md" % name)
    return match[0]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Expire, archive and tidy a zone's Todo.md.")
    ap.add_argument("command", choices=("expire", "archive", "tidy", "all"))
    ap.add_argument("--zone", required=True)
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    ap.add_argument("--days", type=int, help="days in the Inbox before a line expires (default: the zone's, or 14)")
    ap.add_argument("--today", help="YYYY-MM-DD, for tests")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root).expanduser().resolve() if a.root else HERE.parents[2]
    zone = zone_of(root, a.zone)
    today = datetime.date.fromisoformat(a.today) if a.today else datetime.date.today()
    done = {}
    if a.command in ("expire", "all"):
        done["expired"] = expire(root, zone, today, a.days)
    if a.command in ("archive", "all"):
        done["archived"] = archive(zone, today)
    if a.command in ("tidy", "all"):
        done["tidied"] = tidy(zone)
    if a.json:
        print(json.dumps(dict(done, zone=zone.name)))
    else:
        print("%s: %s." % (zone.name, ", ".join("%d %s" % (n, k) for k, n in done.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
