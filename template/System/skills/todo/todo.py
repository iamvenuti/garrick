#!/usr/bin/env python3
"""Keep a zone's Todo.md short: the three steps of the todo skill that need
no assistant. Each changes Todo.md and the zone's archive/ only, and only
lines it can name; a commit is left to the caller.

    python3 System/skills/todo/todo.py expire  --zone Work [--days 14]
    python3 System/skills/todo/todo.py archive --zone Work
    python3 System/skills/todo/todo.py tidy    --zone Work
    python3 System/skills/todo/todo.py all     --zone Work      the three, in that order
    python3 System/skills/todo/todo.py oldest  --zone Work [--count 3]
    python3 System/skills/todo/todo.py digest  --zone Work

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
         Obsidian Tasks reads them, keeping each moved line's first-seen
         date, and keeps the Inbox in thread order: lines that open with the
         same [[thread]] together, the rest after them. The threads come in
         the order each first appears, or, with `todo-inbox-order` set to
         "thread" (for every zone, or per zone), by name, the alias after
         `|` when there is one, as a Tasks query sorted by description shows
         them.
oldest   Prints the open Inbox lines first seen longest ago, the next to
         expire, for a digest that names them.
digest   Prints a morning summary of the list in plain text: what is
         overdue, due today and come due to chase, the Inbox (and its three
         oldest lines when it holds more than ten), what expired today, and
         how many lines carry no date. The nightly job can send it.

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


def setting(root: Path, key: str, zone: str):
    """A key of System/garrick-checks.json, or its value for this zone."""
    try:
        value = json.loads((root / "System" / "garrick-checks.json").read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError, AttributeError):
        return None
    return value.get(zone) if isinstance(value, dict) else value


def chase_days(root: Path, zone: str) -> int:
    """Days ahead the sweep sets `⏳` on a Waiting on line when its source gives
    none: `todo-chase-days`, 7 otherwise; 0 means it writes none."""
    value = setting(root, "todo-chase-days", zone)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 7


def inbox_order(root: Path, zone: str) -> str:
    return "thread" if setting(root, "todo-inbox-order", zone) == "thread" else "first-seen"


def read_seen(zone: Path) -> Dict[str, str]:
    try:
        seen = json.loads((zone / LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return seen if isinstance(seen, dict) else {}


def write_seen(zone: Path, seen: Dict[str, str]) -> None:
    tmp = zone / (LEDGER + ".new")
    tmp.write_text(json.dumps(dict(sorted(seen.items())), indent=0) + "\n", encoding="utf-8")
    os.replace(tmp, zone / LEDGER)


def expire_days(root: Path, zone: str, given: Optional[int]) -> int:
    if given is not None:
        return given
    value = setting(root, "todo-expire-days", zone)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else DAYS


def expire(root: Path, zone: Path, today: datetime.date, days: Optional[int] = None) -> int:
    limit = expire_days(root, zone.name, days)
    lines = read(zone)
    where = sections(lines)
    seen = read_seen(zone)
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
    write_seen(zone, {k: v for k, v in seen.items() if k in live})
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


def thread_name(line: str) -> str:
    """The name a Tasks query sorts a line by: the alias after `|`, else the
    link's last part, case-folded."""
    m = re.match(r"^- \[ \] \[\[([^\]]+)\]\]", line)
    link = m.group(1) if m else ""
    return (link.split("|", 1)[1] if "|" in link else link.split("#", 1)[0].rsplit("/", 1)[-1]).strip().casefold()


def tidy(zone: Path, by: str = "first-seen") -> int:
    lines = read(zone)
    changed = 0
    seen, rekeyed = read_seen(zone), False
    for i, line in enumerate(lines):
        if line.startswith(("- [ ] ", "- [x] ")):
            new = fields_last(line)
            if new != line:
                if key(line) in seen:                                   # the move does not restart its days
                    seen.setdefault(key(new), seen.pop(key(line)))
                    rekeyed = True
                lines[i] = new
                changed += 1
    if rekeyed:
        write_seen(zone, seen)
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

        def by_name(l):
            return (0, thread_name(l)) if LABEL.match(l) else (1, "")
        ranked = sorted(items, key=by_name if by == "thread" else rank)     # stable: each thread keeps its own order
        if ranked != items:
            changed += sum(1 for a, b in zip(items, ranked) if a != b)
            lines[block[0]:block[-1] + 1] = ranked
    if changed:
        write(zone, lines)
    return changed


def oldest(zone: Path, today: datetime.date, count: int = 3) -> List[str]:
    """The open Inbox lines first seen longest ago, oldest first; a line not
    yet seen counts as seen today."""
    lines = read(zone)
    seen = read_seen(zone)
    inbox = [lines[i] for i in range(*sections(lines).get("Inbox", (0, 0))) if lines[i].startswith("- [ ] ")]
    return sorted(inbox, key=lambda l: seen.get(key(l), today.isoformat()))[:max(count, 0)]


DUE = re.compile(r"(?:📅|📆|🗓)️? *(\d{4}-\d{2}-\d{2})")
CHASE_ON = re.compile(r"(?:⏳|⌛)️? *(\d{4}-\d{2}-\d{2})")
CAP = 6


def plain(line: str) -> str:
    """A task line as a person reads it aloud: its thread, then the action,
    without links, tags, sources or fields."""
    text = line[6:]
    m = re.match(r"^\[\[([^\]]+)\]\]:\s*", text)
    label = ""
    if m:
        link = m.group(1)
        label = (link.split("|", 1)[1] if "|" in link else link.split("#", 1)[0].rsplit("/", 1)[-1]).strip()
        text = text[m.end():]
    text = re.sub(r"\s*·?\s*\(also in [^)]*\)", "", text)
    text = re.sub(r"\s*·\s*\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = DATE.sub("", PRIORITY.sub("", text))
    text = re.sub(r"(?:^|\s)#[\w/-]+", "", text)
    text = re.sub(r"\s+", " ", text.replace("**", "")).split(" — ", 1)[0].strip(" ·")      # the action, not its aside
    return "%s: %s" % (label, text) if label else text


def digest(zone: Path, today: datetime.date) -> str:
    """A short morning summary of a zone's list, plain text, a few lines a section."""
    lines = read(zone)
    where = sections(lines)
    waiting = set(range(*where.get("Waiting on", (0, 0))))
    inbox = set(range(*where.get("Inbox", (0, 0))))
    overdue, due, chase, undated, no_chase = [], [], [], 0, 0
    for i, line in enumerate(lines):
        if not line.startswith("- [ ] ") or "<action>" in line:
            continue
        theirs = i in waiting or "#waiting" in line
        d, c = DUE.search(line), CHASE_ON.search(line)
        if theirs:
            if c and c.group(1) <= today.isoformat():
                chase.append(plain(line))
            elif not c:
                no_chase += 1
        elif d and d.group(1) < today.isoformat():
            late = (today - datetime.date.fromisoformat(d.group(1))).days
            overdue.append((-late, "%s (%dd late)" % (plain(line), late)))
        elif d and d.group(1) == today.isoformat():
            due.append(plain(line))
        elif not d and not c:
            undated += 1
    open_inbox = [i for i in inbox if lines[i].startswith("- [ ] ")]
    expired = 0
    gone = zone / "archive" / ("Todo-expired-%d.md" % today.year)
    if gone.is_file():
        mark = "<!-- %s -->" % today.isoformat()
        tail = gone.read_text(encoding="utf-8").split(mark)[1:]
        expired = sum(1 for part in tail for l in part.split("<!--", 1)[0].splitlines() if l.startswith("- [ ] "))

    out = ["Todo · %s" % zone.name]

    def block(title, items):
        if items:
            out.append("")
            out.append("%s · %d" % (title, len(items)))
            out.extend("- " + x for x in items[:CAP])
            if len(items) > CAP:
                out.append("… and %d more" % (len(items) - CAP))
    block("Overdue", [x for _, x in sorted(overdue)])
    block("Due today", due)
    block("Chase, they owe you", chase)
    if open_inbox:
        out += ["", "Inbox · %d untriaged" % len(open_inbox)]
        if len(open_inbox) > 10:
            out.append("The oldest three:")
            out.extend("- " + plain(l) for l in oldest(zone, today, 3))
    if expired:
        out += ["", "Expired today · %d, still open in archive/%s" % (expired, gone.name)]
    out += ["", "%d undated · %d waiting with no chase date" % (undated, no_chase)]
    return "\n".join(out)


def zone_of(root: Path, name: str) -> Path:
    zones = root / "Zones"
    match = [z for z in (zones.iterdir() if zones.is_dir() else []) if z.is_dir() and z.name.lower() == name.lower()]
    if not match or not (match[0] / "Todo.md").is_file():
        raise SystemExit("todo: no zone %s with a Todo.md" % name)
    return match[0]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Expire, archive and tidy a zone's Todo.md.")
    ap.add_argument("command", choices=("expire", "archive", "tidy", "all", "oldest", "digest"))
    ap.add_argument("--zone", required=True)
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    ap.add_argument("--days", type=int, help="days in the Inbox before a line expires (default: the zone's, or 14)")
    ap.add_argument("--today", help="YYYY-MM-DD, for tests")
    ap.add_argument("--count", type=int, default=3, help="how many lines `oldest` prints (default 3)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root).expanduser().resolve() if a.root else HERE.parents[2]
    zone = zone_of(root, a.zone)
    today = datetime.date.fromisoformat(a.today) if a.today else datetime.date.today()
    if a.command == "digest":
        text = digest(zone, today)
        print(json.dumps({"zone": zone.name, "digest": text}) if a.json else text)
        return 0
    if a.command == "oldest":
        found = oldest(zone, today, a.count)
        print(json.dumps({"zone": zone.name, "oldest": found}) if a.json else "\n".join(found))
        return 0
    done = {}
    if a.command in ("expire", "all"):
        done["expired"] = expire(root, zone, today, a.days)
    if a.command in ("archive", "all"):
        done["archived"] = archive(zone, today)
    if a.command in ("tidy", "all"):
        done["tidied"] = tidy(zone, inbox_order(root, zone.name))
    if a.json:
        print(json.dumps(dict(done, zone=zone.name)))
    else:
        print("%s: %s." % (zone.name, ", ".join("%d %s" % (n, k) for k, n in done.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
