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
    python3 System/skills/todo/todo.py distil  --zone Work --changes <file or -> [--yes] [--dry-run]
    python3 System/skills/todo/todo.py proposals --zone Work [--drop <id>]
    python3 System/skills/todo/todo.py followup --zone Work [--answers <file or ->] [--json]

expire   Records, in the zone's .todo-seen.json (never committed), the first
         night each open line under `## Inbox` and `## Waiting on` was seen.
         An Inbox line with no date, or a Waiting on line with no `⏳` day to
         chase, still there after the zone's days (14, or `todo-expire-days`
         in System/garrick-checks.json: a number, or a number per zone)
         moves, still open, to archive/Todo-expired-<YYYY>.md, so it can be
         pasted back. A line keeps its words; a relative link in it, such
         as its meeting source, is written again from archive/ so it still
         leads to the page, and one more `../` comes off when it is pasted
         back into Todo.md. A line the user has triaged has left the
         Inbox, carries a date, or waits with a day to chase, so expiry
         never reaches it.
archive  Moves ticked lines (`- [x]`) done before today to
         archive/Todo-<YYYY>.md, so the list is only as long as what is
         open, their relative links written again from there as expire's. A line ticked today stays, for the page's *Done today*.
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

distil   Applies, or proposes, the changes one thread's material makes to its
         open lines (the Distil section of SKILL.md). The assistant gives it a
         JSON file: {"thread": "<the link label>", "party": "<Party>" for a
         line that names no thread, "source": "[<short title>](<link>)",
         "done": [<words of a line>], "changed": [{"line", "text", "merge"?}],
         "new": [{"text", "date"?, "waiting"?, "blocks"?}], "retired":
         [{"line", "reason"?}]}. A line is found by its words, among the open
         lines of that thread only; a line of another thread is never touched.
         An `## Inbox` line is changed at once. A line the user moved to
         another section is only proposed, to .todo-proposals.json (never
         committed), unless `--yes` says the user has seen the before and after
         and agreed, and never in a headless run. A retired line goes, still
         open, to archive/Todo-expired-<YYYY>.md with `superseded by <source>`;
         nothing is deleted. `--dry-run` writes nothing and prints what would
         happen. The commit is left to the caller.
proposals Prints the proposals waiting for the zone, and with `--drop <id>`
         (more than once if needed) takes applied ones out.

followup Looks, with no assistant, for the reply to each open Waiting on line
         whose `⏳` day is today or past (the Follow up section of SKILL.md).
         For each such line no follow-up has looked at since it last changed:
         the zone's own Meetings pages filed since the line was first seen,
         each one the wall permits this zone to read, and the items of the
         zone's Inbox/ whose sender names the line's person, by any form
         System/context.md lists for them. The result goes to the zone's
         .todo-followups.json (never committed): the line, the result, the
         source and the day it looked. No evidence is *no sign*. With
         evidence the line waits as `pending` for a judgement, which
         `--answers` records: a JSON file, {"answers": [{"key", "result":
         "delivered" | "in part" | "no sign", "source"}]}, a source being one
         of those the script found for that line. Todo.md is never changed.
         `digest` names the counts as one line.

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
import urllib.parse
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


# A Markdown link by a path relative to the note it is in, such as a line's
# meeting source, `[title](../../Wikis/Meetings/wiki/sources/<slug>.md)` (#318):
# its target, which may hold a pair of parentheses, as `a(1).md`.
RELATIVE_LINK = re.compile(r"(\]\()((?:[^()\s]|\([^()\s]*\))+)(\))")
INLINE_CODE = re.compile(r"`[^`\n]*`")


def relinked(line: str, here: Path, there: Path) -> str:
    """`line`, moved from a note in folder `here` to one in folder `there`,
    with the path of each relative link written again from `there`, so it
    still leads where it led; its query or anchor stays as written. A
    wikilink, a web link, an anchor, a path from the top and anything in
    inline code are left as they are."""
    def one(m):
        target = m.group(2)
        if re.match(r"^[A-Za-z][\w+.-]*:|^[#/]", target):
            return m.group(0)
        cut = min([i for i in (target.find("?"), target.find("#")) if i >= 0] or [len(target)])
        path, rest = target[:cut], target[cut:]
        if not path:
            return m.group(0)
        full = os.path.normpath(os.path.join(str(here), urllib.parse.unquote(path)))
        again = os.path.relpath(full, str(there)).replace(os.sep, "/")
        return m.group(1) + urllib.parse.quote(again, safe="/()") + rest + m.group(3)

    if "](" not in line:
        return line
    parts, codes = INLINE_CODE.split(line), INLINE_CODE.findall(line) + [""]
    return "".join(RELATIVE_LINK.sub(one, part) + code for part, code in zip(parts, codes))


def keep_out(zone: Path, name: str, title: str, moved: List[str]) -> Path:
    """Append lines to archive/<name>, a file that opens with its title,
    each relative link written again from there (relinked())."""
    path = zone / "archive" / name
    path.parent.mkdir(exist_ok=True)
    moved = [relinked(line, zone, path.parent) for line in moved]
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
        when = done_on(line)          # none, or a day no calendar has: archived as undated
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


TASK_LINK = re.compile(r"^- \[[ x]\] \[\[([^\]|#]+)")


def link_of(line: str) -> Optional[str]:
    """The thread a task line opens with, open or ticked: the link's path as
    written (`Pricing`, or `Acme/Threads/Pricing/Pricing` where another
    project has a Pricing too). None for a line that opens with no link.
    System/tools/briefing.py finds a thread's lines with it."""
    m = TASK_LINK.match(line)
    return m.group(1).strip() if m else None


def done_on(line: str) -> Optional[datetime.date]:
    """The day a ticked line was done, from its `✅` date. None for an open
    line, or a ticked one with no date."""
    m = DONE.search(line) if line.startswith("- [x] ") else None
    try:
        return datetime.date.fromisoformat(m.group(1)) if m else None
    except ValueError:
        return None


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
# The `(also in …)` a sweep folds onto a line, Markdown links inside it, and
# the `·` before it: the pattern garrick_lib.TODO_ALSO_RE holds, copied here
# because this file stands alone.
ALSO = re.compile(r"\s*·?\s*\(also in ((?:[^()]|\([^()]*\))*)\)")
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
    text = ALSO.sub("", text)
    text = re.sub(r"\s*·\s*\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = DATE.sub("", PRIORITY.sub("", text))
    text = re.sub(r"(?:^|\s)#[\w/-]+", "", text)
    text = re.sub(r"\s+", " ", text.replace("**", "")).split(" — ", 1)[0].strip(" ·")      # the action, not its aside
    return "%s: %s" % (label, text) if label else text


def day_of(m) -> Optional[datetime.date]:
    """The date a DUE or CHASE_ON match holds, or None: no match, or a date
    no calendar has, as 2026-02-30."""
    try:
        return datetime.date.fromisoformat(m.group(1)) if m else None
    except ValueError:
        return None


def classify(lines: List[str], today: datetime.date) -> dict:
    """The open lines a digest names, read once for every reader: "overdue",
    (days late, line) pairs; "due", due today; "chase", waiting lines whose
    chase day has come; and the counts "undated" and "no_chase". The example
    line, `<action>`, counts as none. System/tools/next_up.py ranks from the
    same reading. For a reader that lists every open line, the Ask box's
    actions (#316), the rest are here too: "later", (date, line) pairs due
    after today; "open", the lines with no date of either kind; and
    "waiting", (chase date or "", line) pairs waiting with no chase come due.
    A line that has only a chase date and is not waiting counts as none.
    A date that is no day of the calendar, 2026-04-31, counts as no date:
    the line is read as undated, or as waiting with no chase date, and the
    rest of the list is read as before."""
    where = sections(lines)
    waiting = set(range(*where.get("Waiting on", (0, 0))))
    out = {"overdue": [], "due": [], "chase": [], "undated": 0, "no_chase": 0, "later": [], "open": [], "waiting": []}
    for i, line in enumerate(lines):
        if not line.startswith("- [ ] ") or "<action>" in line:
            continue
        theirs = i in waiting or "#waiting" in line
        d, c = day_of(DUE.search(line)), day_of(CHASE_ON.search(line))
        if theirs:
            if c and c <= today:
                out["chase"].append(line)
            else:
                out["waiting"].append((c.isoformat() if c else "", line))
                if not c:
                    out["no_chase"] += 1
        elif d and d < today:
            out["overdue"].append(((today - d).days, line))
        elif d and d == today:
            out["due"].append(line)
        elif d:
            out["later"].append((d.isoformat(), line))
        elif not c:
            out["undated"] += 1
            out["open"].append(line)
    return out


def digest(zone: Path, today: datetime.date) -> str:
    """A short morning summary of a zone's list, plain text, a few lines a section."""
    lines = read(zone)
    inbox = set(range(*sections(lines).get("Inbox", (0, 0))))
    found = classify(lines, today)
    overdue = [(-late, "%s (%dd late)" % (plain(line), late)) for late, line in found["overdue"]]
    due = [plain(line) for line in found["due"]]
    chase = [plain(line) for line in found["chase"]]
    undated, no_chase = found["undated"], found["no_chase"]
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
    said = followup_say(followup_counts(zone, today))
    if said:
        out += ["", said]
    if open_inbox:
        out += ["", "Inbox · %d untriaged" % len(open_inbox)]
        if len(open_inbox) > 10:
            out.append("The oldest three:")
            out.extend("- " + plain(l) for l in oldest(zone, today, 3))
    if expired:
        out += ["", "Expired today · %d, still open in archive/%s" % (expired, gone.name)]
    block("Proposed changes", [proposal_said(p) for p in proposal_view(zone) if not p.get("stale")])
    out += ["", "%d undated · %d waiting with no chase date" % (undated, no_chase)]
    return "\n".join(out)


PROPOSALS = ".todo-proposals.json"
THREAD_CAP = 5
SOURCE = re.compile(r"\s*·\s*\[[^\]]*\]\([^)\s]*\)")
TAG = re.compile(r"(?<!\S)#(?!\d+(?![\w/-]))[^\s#]+")
BLOCKS = re.compile(r"\s+—\s+blocks:\s*(.+?)\s*$")
UNITS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def thread_cap(root: Path, zone: str) -> int:
    """Open lines a thread should hold at most: `todo-thread-cap` in System/garrick-checks.json,
    5 otherwise, `0` for none. A soft cap: it warns, it never drops a line."""
    value = setting(root, "todo-thread-cap", zone)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else THREAD_CAP


def words(line: str) -> str:
    """The words of a task line, as a person says them: no thread link, no sources, tags or fields,
    one space, no case, no stop at the end."""
    text = line[6:] if line.startswith(("- [ ] ", "- [x] ")) else line
    text = re.sub(r"^\[\[[^\]]*\]\]:\s*", "", text)
    text = ALSO.sub("", SOURCE.sub("", text))
    text = BLOCKS.sub("", TAG.sub("", DATE.sub("", PRIORITY.sub("", text))))
    return re.sub(r"\s+", " ", text).strip().rstrip(".!").casefold()


def thread_index(zone: Optional[Path]) -> Dict[str, List[str]]:
    """The zone's thread names: each folder name under `<Project>/Threads/`, case-folded, with the projects
    that have a thread of it. Reads this zone's own folder only; `{}` for none."""
    found: Dict[str, List[str]] = {}
    if zone is None:
        return found
    try:
        projects = sorted(p for p in Path(zone).iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return found
    for project in projects:
        try:
            threads = [t for t in (project / "Threads").iterdir() if t.is_dir()]
        except OSError:
            continue
        for thread in threads:
            found.setdefault(thread.name.casefold(), []).append(project.name.casefold())
    return found


def thread_key(target: str, index: Optional[Dict[str, List[str]]] = None) -> str:
    """The one name of a thread, from a link target in either form, case-folded: `project/threads/name` for a
    long link (`Acme/Threads/Pricing/Pricing`, or the note's path without the file name), and for a short
    one (`Pricing`) when exactly one project of the zone has a thread of that name. A short name that two
    projects share stays short, so it matches no long form: it fails closed."""
    target = target.strip().casefold()
    parts = [p for p in target.split("/") if p]
    if "threads" in parts[:-1]:
        at = parts.index("threads")
        if at >= 1:
            return "%s/threads/%s" % ("/".join(parts[:at]), parts[at + 1])
        return target
    if len(parts) == 1 and index:
        owners = index.get(parts[0], [])
        if len(owners) == 1:
            return "%s/threads/%s" % (owners[0], parts[0])
    return target


def thread_of(line: str, index: Optional[Dict[str, List[str]]] = None) -> str:
    """The name of the thread a line opens with (see `thread_key`), or "" for a line that opens with none.
    Two projects' threads of one name never share it."""
    m = TASK_LINK.match(line)
    return thread_key(m.group(1), index) if m else ""


def target_of(label: str, index: Optional[Dict[str, List[str]]] = None) -> str:
    """The same name, from the link label a plan gives (`Pricing`, `[[Acme/Threads/Pricing/Pricing|Pricing]]`)."""
    return thread_key(label.strip().strip("[]").split("|", 1)[0].split("#", 1)[0], index)


def spoken(n: int) -> str:
    return UNITS[n] if 0 <= n < len(UNITS) else str(n)


def reword_line(line: str, text: str) -> str:
    """An open line with new words, keeping its thread link, its tags, its sources and its fields; where
    the new text carries a source, a date or a tag of its own, the old one of that kind goes. `text` is
    the whole description after the thread link. The status page's todo_lines.reword() does the same."""
    new_text = re.sub(r"^-\s*\[[ xX]\]\s*", "", re.sub(r"\s+", " ", text or "").strip())
    body = line[6:]
    m = re.match(r"^(?:\[\[[^\]]*\]\]|⚠️ thread\?):\s*", body)
    prefix = body[:m.end()] if m else ""
    rest = body[len(prefix):]
    carried = re.match(r"^\[\[[^\]]*\]\]:\s*", new_text)
    if carried:
        new_text = new_text[carried.end():]
    keep = []
    if not SOURCE.search(new_text):
        keep += [x.group(0).strip() for x in SOURCE.finditer(rest)]
    else:
        keep += [x.group(0).strip() for x in SOURCE.finditer(rest) if x.group(0).strip() not in new_text]
    if not ALSO.search(new_text):
        keep += [x.group(0).strip() for x in ALSO.finditer(rest)]
    keep += [t for t in TAG.findall(rest) if t not in new_text]
    fields = ([] if PRIORITY.search(new_text) else [x.group(1) for x in PRIORITY.finditer(rest)])
    fields += ([] if DATE.search(new_text) else [x.group(1) for x in DATE.finditer(rest)])
    return fields_last("- [ ] " + prefix + " ".join([new_text] + keep + fields))


def read_proposals(zone: Path) -> List[dict]:
    try:
        found = json.loads((zone / PROPOSALS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in found if isinstance(p, dict) and p.get("id")] if isinstance(found, list) else []


def write_proposals(zone: Path, found: List[dict]) -> None:
    path = zone / PROPOSALS
    if not found:
        if path.is_file():
            path.unlink()
        return
    tmp = zone / (PROPOSALS + ".new")
    tmp.write_text(json.dumps(found, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def proposal_view(zone: Path) -> List[dict]:
    """The zone's proposals, each with `stale` set when its line is no longer open in Todo.md."""
    lines = read(zone) if (zone / "Todo.md").is_file() else []
    live = {key(l) for l in lines if l.startswith("- [ ] ")}
    return [dict(p, stale=p.get("key") not in live) for p in read_proposals(zone)]


def proposal_said(p: dict) -> str:
    """What one proposal would change, before and after, as a person reads it."""
    after = {"edit": "reword to: " + str(p.get("text", "")), "retire": "retire, " + str(p.get("reason", "")),
             "done": "tick it"}.get(p.get("kind"), "")
    return "%s -> %s" % (plain(p.get("line", "- [ ] ")), after)


def proposal_text(p: dict) -> str:
    return "- [%s] %s%s" % (p.get("id", ""), "(gone) " if p.get("stale") else "", proposal_said(p))


MIN_MATCH = 12


def find_line(lines: List[str], said: str, pool: List[int]) -> Tuple[Optional[int], str]:
    """The one line of `pool` the words say: (its index, "") or (None, why). The whole line text, or a unique
    part of it at least MIN_MATCH characters long; anything shorter is refused, never guessed."""
    want = words("- [ ] " + said) if not said.startswith("- [") else words(said)
    exact = [i for i in pool if words(lines[i]) == want]
    if not exact and len(want) < MIN_MATCH:
        return None, "too short to match safely: give %d characters or the whole line" % MIN_MATCH
    found = exact or [i for i in pool if want and want in words(lines[i])]
    if not found:
        return None, "no open line of the thread says that"
    if len(found) > 1:
        return None, "several lines of the thread say that"
    return found[0], ""


def number(n: int, what: str) -> str:
    return "%s %s" % (spoken(n), what)


def distil(root: Path, zone: Path, plan: dict, today: datetime.date, yes: bool = False, dry: bool = False) -> dict:
    """Apply one thread's changes to the zone's Todo.md, or propose them. Returns the counts, the notes the
    caller says aloud, the proposals made and a spoken line. Writes nothing with `dry`."""
    if not isinstance(plan, dict):
        raise SystemExit("todo: the changes are not a JSON object")
    thread = plan.get("thread") if isinstance(plan.get("thread"), str) and plan.get("thread").strip() else None
    party = plan.get("party") if isinstance(plan.get("party"), str) and plan.get("party").strip() else None
    source = plan.get("source") if isinstance(plan.get("source"), str) and plan.get("source").strip() else ""
    names = thread_index(zone)
    label = None
    if thread:
        label = thread.strip().strip("[]")
        mine = target_of(label, names)
    else:
        mine = ""
    headless = os.environ.get("GARRICK_HEADLESS") == "1" or os.environ.get("GARRICK_BACKGROUND") == "1"
    may_change = yes and not headless
    lines = read(zone)
    where = sections(lines)
    inbox = set(range(*where.get("Inbox", (0, 0))))
    counts = {"ticked": 0, "reworded": 0, "added": 0, "merged": 0, "retired": 0, "proposed": 0}
    notes: List[str] = []
    proposals: List[dict] = []
    moved_out: List[str] = []
    gone: set = set()

    def pool() -> List[int]:
        return [i for i, l in enumerate(lines) if l.startswith("- [ ] ") and i not in gone and mine and thread_of(l, names) == mine]

    def propose(kind: str, i: int, **more) -> None:
        item = dict(more, kind=kind, thread=label or party or "", line=lines[i], key=key(lines[i]),
                    made=today.isoformat())
        item["id"] = hashlib.sha1(json.dumps([kind, item["key"], more], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
        proposals.append(item)
        counts["proposed"] += 1

    def direct(i: int) -> bool:
        return i in inbox or may_change

    said_party = party.strip().casefold() if party and not thread else ""

    def tickable() -> List[int]:
        """A thread's plan reaches its own open lines; a party's plan, the open lines with no thread link that
        open with that party's name."""
        if mine:
            return pool()
        return [i for i, l in enumerate(lines) if l.startswith("- [ ] ") and i not in gone and said_party
                and not thread_of(l, names) and l[6:].casefold().startswith(said_party + ":")]

    for said in plan.get("done") or []:                  # 1. what is now done
        if not isinstance(said, str):
            continue
        i, why = find_line(lines, said, tickable())
        if i is None:
            notes.append("done: %s: %s" % (said[:40], why))
        elif not (direct(i) if mine else may_change):
            propose("done", i)
        else:
            lines[i] = "- [x] " + lines[i][6:].rstrip() + " ✅ " + today.isoformat()
            counts["ticked"] += 1
    for item in plan.get("changed") or []:                # 2. what changed
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not mine:
            notes.append("changed: needs a thread and the new text")
            continue
        i, why = find_line(lines, str(item.get("line") or ""), pool())
        if i is None:
            notes.append("changed: %s: %s" % (str(item.get("line"))[:40], why))
            continue
        new = reword_line(lines[i], item["text"])
        if new == lines[i].rstrip():
            notes.append("changed: %s: already says that" % str(item.get("line"))[:40])
        elif not direct(i):
            propose("edit", i, text=item["text"], merge=bool(item.get("merge")))
        elif any(j != i and l.startswith("- [ ] ") and j not in gone and thread_of(l, names) == mine and words(l) == words(new)
                 for j, l in enumerate(lines)):
            notes.append("changed: %s: another line says that" % str(item.get("line"))[:40])
        else:
            lines[i] = new
            counts["merged" if item.get("merge") else "reworded"] += 1
    for item in plan.get("retired") or []:                # 4, before 3, so the cap sees the room it makes
        if not isinstance(item, dict) or not mine:
            notes.append("retired: needs a thread")
            continue
        reason = item.get("reason") if isinstance(item.get("reason"), str) and item.get("reason").strip() else source
        i, why = find_line(lines, str(item.get("line") or ""), pool())
        if i is None:
            notes.append("retired: %s: %s" % (str(item.get("line"))[:40], why))
        elif not reason:
            notes.append("retired: %s: no source says what replaced it" % str(item.get("line"))[:40])
        elif not direct(i):
            propose("retire", i, reason=reason)
        else:
            reason = " ".join(reason.split())
            reason = reason if reason.lower().startswith("superseded by") else "superseded by " + reason
            block = with_steps(lines, [i])
            first = lines[i].rstrip() + " · " + reason
            moved_out += [first] + [lines[j] for j in block[1:]]
            gone.update(block)
            counts["retired"] += 1
    adds = [a for a in (plan.get("new") or []) if isinstance(a, dict) and isinstance(a.get("text"), str) and a["text"].strip()]
    if adds and not (label or party):
        notes.append("new: no thread and no party to open the line with")
        adds = []
    cap = thread_cap(root, zone.name)
    pending: List[str] = []
    for a in adds:                                         # 3. what is new
        text = re.sub(r"\s+", " ", a["text"]).strip()
        waiting = bool(a.get("waiting"))
        if waiting:
            blocked = a.get("blocks")
            blocker = [i for i in pool() if "#waiting" not in lines[i] and isinstance(blocked, str) and blocked.strip()
                       and words(blocked) in words(lines[i])] if mine else []
            if not blocker:
                notes.append("new: %s: a Waiting on line must name an open line of yours in this thread" % text[:40])
                continue
            text = "%s — blocks: %s" % (text, " ".join(blocked.split()))
        date = a.get("date") if isinstance(a.get("date"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", a["date"]) else None
        prefix = "[[%s]]: " % label if label else "%s: " % party
        line = "- [ ] " + prefix + text + (" · " + source if source else "") + (" #waiting" if waiting else "")
        if date:
            line = fields_last("%s %s %s" % (line, "⏳" if waiting else "📅", date))
        if any(words(p) == words(line) and p.startswith("- [ ] " + prefix) for p in pending):
            counts["merged"] += 1
            continue
        same = [i for i, l in enumerate(lines) if l.startswith("- [ ] " + prefix) and i not in gone and words(l) == words(line)]
        if same:                                           # a repeat: its source goes on the line, nothing is added
            i = same[0]
            if not source or source in lines[i]:
                counts["merged"] += 1
            elif direct(i):
                lines[i] = fields_last(lines[i].rstrip() + " (also in %s)" % source)
                counts["merged"] += 1
            else:
                propose("edit", i, text=re.sub(r"^\[\[[^\]]*\]\]:\s*", "", lines[i][6:].rstrip()) + " (also in %s)" % source,
                        merge=True)
            continue
        pending.append(line)
        counts["added"] += 1
    held = len(pool()) + len(pending) if mine else 0
    if cap and held > cap:
        notes.append("%s holds %s, over the cap of %d: merge before adding" % (label, number(held, "open lines"), cap))
    name = plan.get("name") if isinstance(plan.get("name"), str) and plan.get("name").strip() else (
        (label.split("|", 1)[1] if "|" in label else label.split("#", 1)[0].rsplit("/", 1)[-1]) if label else party)
    sentence = say(name or "the list", counts)
    out = {"zone": zone.name, "counts": counts, "notes": notes, "proposed": proposals, "say": sentence, "open": held}
    if dry:
        return out
    if any(counts[k] for k in ("ticked", "reworded", "added", "merged", "retired")):
        lines = [l for i, l in enumerate(lines) if i not in gone]
        if pending:
            lines = _insert_inbox(lines, pending)
        if moved_out:
            keep_out(zone, "Todo-expired-%d.md" % today.year, "%s: actions nobody triaged, %d" % (zone.name, today.year),
                     ["<!-- %s retired -->" % today.isoformat()] + moved_out)
        write(zone, lines)
    if proposals:
        have = {p["id"] for p in read_proposals(zone)}
        write_proposals(zone, read_proposals(zone) + [p for p in proposals if p["id"] not in have])
    return out


def _insert_inbox(lines: List[str], new: List[str]) -> List[str]:
    """`new` last in the Inbox, under whatever it already holds. The example line and the empty-list
    placeholder go with the first real line."""
    where = sections(lines)
    if "Inbox" not in where:
        raise SystemExit("todo: the list has no Inbox section")
    start, end = where["Inbox"]
    keep = [i for i in range(start, end)
            if not (lines[i].startswith("- [ ] ") and "<action>" in lines[i]) and lines[i].strip() != "*Nothing recorded yet.*"]
    body = [lines[i] for i in keep]
    while body and not body[-1].strip():
        body.pop()
    if not any(l.strip() for l in body):
        body = [""]
    body = body + new + [""]
    return lines[:start] + body + lines[end:]


def say(label: str, counts: dict) -> str:
    """The spoken report: "Distilled Acme, pricing: one added, two merged, one retired." """
    parts = [number(counts[k], name) for k, name in (("added", "added"), ("ticked", "done"), ("reworded", "reworded"),
                                                      ("merged", "merged"), ("retired", "retired"), ("proposed", "proposed"))
             if counts[k]]
    return "Distilled %s: %s." % (label, ", ".join(parts)) if parts else "Distilled %s: nothing to change." % label


FOLLOWUPS = ".todo-followups.json"
RESULTS = ("delivered", "in part", "no sign")      # what a follow-up can say of a line; "pending" is a line with evidence, not yet judged
MOST_EVIDENCE = 5                                  # sources kept for one line
MOST_READ = 400_000                                # bytes of one page or mail looked at
SHORTEST = 3                                       # a name shorter than this is never looked for, as Ask's is not
MEETING_PAGES = ("Wikis", "Meetings", "wiki", "sources")
_LIB: Dict[str, object] = {}


def tools_lib(root: Path):
    """garrick_lib.py, for the wall check and the context: the workspace's own copy first, then the one beside this
    skill (System/tools/), which in a Garrick clone is template/System/tools/. None where neither loads."""
    import importlib.util
    for src in (root / "System" / "tools" / "garrick_lib.py", HERE.parents[1] / "tools" / "garrick_lib.py"):
        if not src.is_file():
            continue
        if str(src) in _LIB:
            return _LIB[str(src)]
        name = "garrick_todo_lib_%s" % hashlib.sha1(str(src.resolve()).encode("utf-8")).hexdigest()[:8]
        try:
            spec = importlib.util.spec_from_file_location(name, str(src))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop(name, None)
            continue
        if all(callable(getattr(mod, f, None)) for f in ("load_context", "decide", "zone_of", "parse_frontmatter")):
            _LIB[str(src)] = mod
            return mod
    return None


def read_followups(zone: Path) -> Dict[str, dict]:
    """The zone's follow-up records by line key; {} where there are none or the file does not read."""
    try:
        found = json.loads((zone / FOLLOWUPS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}


def write_followups(zone: Path, found: Dict[str, dict]) -> None:
    path = zone / FOLLOWUPS
    if not found:
        if path.is_file():
            path.unlink()
        return
    tmp = zone / (FOLLOWUPS + ".new")
    tmp.write_text(json.dumps(dict(sorted(found.items())), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _norm(text: str) -> str:
    return " ".join(str(text).replace("’", "'").split()).lower()


def person_forms(ctx: dict) -> List[Tuple[str, bool, str]]:
    """(form, counts only with a capital, the person's name) for every way the People and Aliases tables of
    System/context.md name a person, as the Ask box reads them: the full name, a first name alone (capitalised), and
    each alias whose meaning is either."""
    out: List[Tuple[str, bool, str]] = []
    for person in ctx.get("people", []):
        name = person.get("name") or ""
        words = name.split()
        if not words:
            continue
        out.append((name, False, name))
        if len(words) > 1:
            out.append((words[0], True, name))
    by_form: Dict[str, List[str]] = {}
    for form, _, name in out:
        by_form.setdefault(_norm(form), []).append(name)
    for heard, means in (ctx.get("aliases") or {}).items():
        for name in by_form.get(_norm(means), []):
            out.append((heard, False, name))
    return [(f, cap, n) for f, cap, n in out if len(_norm(f)) >= SHORTEST]


def _pattern(form: str) -> str:
    return r"(?<!\w)%s(?!\w)" % r"\s+".join(re.escape(w) for w in _norm(form).split())


def name_hits(text: str, forms: List[Tuple[str, bool, str]]) -> List[Tuple[int, int, str]]:
    """(start, end, person) for each place a person's form stands whole in `text`, longest first at one place."""
    out = []
    for form, capital, name in forms:
        for m in re.finditer(_pattern(form), text, re.I):
            if capital and not text[m.start()].isupper():
                continue
            out.append((m.start(), m.end(), name))
    return sorted(out, key=lambda h: (h[0], h[0] - h[1]))


def person_of(line: str, forms: List[Tuple[str, bool, str]]) -> str:
    """The person a Waiting on line is about: the first one its words name, "" when none. A first name that two or more
    people share names nobody, unless the line also holds a full name; then the first unshared name is the person."""
    hits = name_hits(plain(line), forms)
    spans: Dict[Tuple[int, int], set] = {}
    for start, end, name in hits:
        spans.setdefault((start, end), set()).add(name)
    ordered = sorted(spans.items())
    if not ordered:
        return ""
    if len(ordered[0][1]) > 1:
        text = plain(line)
        full = any(" " in _norm(text[x:y]) for x, y in spans)
        if not full:
            return ""
    for _, names in ordered:
        if len(names) == 1:
            return next(iter(names))
    return ""


def _day_text(value) -> Optional[datetime.date]:
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _title_of(fm: dict, path: Path) -> str:
    value = fm.get("title")
    return " ".join(str(value).split()) if isinstance(value, str) and value.strip() else path.stem


def meeting_evidence(root: Path, zone: str, person: str, since: datetime.date, ctx: dict, lib,
                     forms: List[Tuple[str, bool, str]]) -> List[dict]:
    """The Meetings pages of this zone filed after `since` that name `person`. A page is looked at only when its
    own `zone:` is this zone and the wall's decide() permits this zone to read it: a page of another zone, or of none,
    is never opened. Newest first."""
    folder = root.joinpath(*MEETING_PAGES)
    mine = [f for f in forms if f[2] == person]
    found = []
    for page in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        if page.is_symlink() or not page.is_file():
            continue
        try:
            page_zone = lib.zone_of(root, page)
            if str(page_zone or "").casefold() != zone.casefold() or lib.decide({zone}, {page_zone}, "read", ctx) != "permit":
                continue
            fm = lib.parse_frontmatter(page)
            day = _day_text(fm.get("created")) or _day_text(fm.get("date"))
            if day is None or day <= since:      # a page filed the day the line was first seen may be its own source
                continue
            if page.stat().st_size > MOST_READ:
                continue
            text = page.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        if name_hits(text, mine):
            held = _day_text(fm.get("date")) or day
            found.append((held, day, {"path": page.relative_to(root).as_posix(), "title": _title_of(fm, page),
                                      "date": held.isoformat(), "kind": "meeting"}))
    return [e for _, _, e in sorted(found, key=lambda t: (t[0], t[1], t[2]["path"]), reverse=True)]


FROM = re.compile(r"^from:[ \t]*(.+)$", re.I | re.M)
SENT = re.compile(r"^date:[ \t]*(.+)$", re.I | re.M)


def inbox_items(root: Path, zone: Path, person: str, since: datetime.date, ctx: dict, lib,
                forms: List[Tuple[str, bool, str]]) -> List[Tuple[datetime.date, Path, str]]:
    """(day sent, the item, its header) for each item in this zone's Inbox/ sent on or after `since` whose sender names
    `person`, newest first. Only this zone's own Inbox is listed, and each item is checked against the wall for this
    zone before it is opened."""
    import email.utils
    inbox = zone / "Inbox"
    mine = [f for f in forms if f[2] == person]
    found = []
    for item in sorted(inbox.iterdir()) if inbox.is_dir() else []:
        if item.name.startswith(".") or item.is_symlink() or not item.is_file() or item.suffix.lower() not in (".eml", ".md", ".txt"):
            continue
        try:
            item_zone = lib.zone_of(root, item)
            if str(item_zone or "").casefold() != zone.name.casefold() or lib.decide({zone.name}, {item_zone}, "read", ctx) != "permit":
                continue
            with item.open("rb") as fh:
                head = fh.read(20_000).decode("utf-8", errors="replace")
            mtime = datetime.date.fromtimestamp(item.stat().st_mtime)
        except (OSError, ValueError):
            continue
        top = head.split("\n\n", 1)[0] if item.suffix.lower() == ".eml" else head
        sender = FROM.search(top)
        if not sender or not name_hits(sender.group(1), mine):
            continue
        day = mtime
        sent = SENT.search(top)
        if sent:
            try:
                day = email.utils.parsedate_to_datetime(sent.group(1).strip()).date()
            except (TypeError, ValueError, IndexError):
                day = _day_text(sent.group(1)) or mtime
        if day >= since:
            found.append((day, item, top))
    return sorted(found, key=lambda t: (t[0], t[1].name), reverse=True)


def inbox_evidence(root: Path, zone: Path, person: str, since: datetime.date, ctx: dict, lib,
                   forms: List[Tuple[str, bool, str]]) -> List[dict]:
    """The items in this zone's Inbox/ sent on or after `since` whose sender names `person`, as evidence."""
    out = []
    for day, item, top in inbox_items(root, zone, person, since, ctx, lib, forms):
        subject = re.search(r"^subject:[ \t]*(.+)$", top, re.I | re.M)
        out.append({"path": item.relative_to(root).as_posix(), "title": " ".join(subject.group(1).split()) if subject else item.stem,
                    "date": day.isoformat(), "kind": "inbox"})
    return out


def sender_address(root: Path, zone: Path, person: str) -> str:
    """The address `person` wrote from, read from the From line of the items in this zone's own Inbox/ whose display name
    is their full name as People writes it (case aside; never a first name or an alias alone), or "" when none does or
    when two or more different addresses do. Code builds a chase's recipient from this and from nothing the assistant
    wrote."""
    import email.utils
    lib = tools_lib(root)
    if not lib or not person:
        return ""
    ctx = lib.load_context(root)
    found: Dict[str, str] = {}
    for _, _, top in inbox_items(root, zone, person, datetime.date.min, ctx, lib, person_forms(ctx)):
        sender = FROM.search(top)
        shown, address = email.utils.parseaddr(sender.group(1)) if sender else ("", "")
        if _norm(shown) != _norm(person):
            continue
        if re.fullmatch(r"[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+", address):
            found[address.casefold()] = address
    return next(iter(found.values())) if len(found) == 1 else ""


WAITING_TAG = re.compile(r"(?:^|\s)#waiting")


def due_waiting(lines: List[str], today: datetime.date) -> List[str]:
    """The lines a follow-up is about: open, tagged `#waiting`, chase day today or past. The status page's Follow-ups row
    reads the same test (todo_lines.py's `waiting`), so a digest and the page count the same lines."""
    return [l for l in classify(lines, today)["chase"] if WAITING_TAG.search(l)]


def followup(root: Path, zone: Path, today: datetime.date) -> dict:
    """Follow up on a zone's due Waiting on lines, with no model. A line is due when it is open, waiting, and its `⏳`
    day is today or past; it is looked at once, until it changes (a changed line has another key). For each: the
    zone's own Meetings pages and Inbox items since the line was first seen (`.todo-seen.json`) that name its person.
    With none, the line is recorded as *no sign*. With some, it is recorded as `pending`, with those sources, for the
    judgement call to answer. A line the ledger had not seen is entered in it now and looked at on the next run.
    Nothing in Todo.md changes. Returns followup_counts() and {"zone", "pending": [{"key", "line", "person",
    "evidence"}], "unseen"}."""
    lines = read(zone)
    due = due_waiting(lines, today)
    seen = read_seen(zone)
    records = read_followups(zone)
    live = {key(l) for l in due}
    for k in [k for k in records if k not in live]:
        del records[k]                                     # a line that changed, was ticked or moved on is looked at afresh
    lib = tools_lib(root)
    ctx = lib.load_context(root) if lib else {}
    forms = person_forms(ctx)
    out = {"zone": zone.name}
    unseen = 0
    new = False
    for line in due:
        k = key(line)
        rec = records.get(k)
        if rec and rec.get("result") in RESULTS:
            continue
        first = _day_text(seen.get(k))
        if first is None:
            seen[k] = today.isoformat()                    # first seen now, as expiry would record it; looked at tomorrow
            new = True
            unseen += 1
            continue
        person = person_of(line, forms)
        if not person:
            continue                                       # a line that names nobody is not looked at, and says so
        evidence = []
        if person and lib:
            evidence = meeting_evidence(root, zone.name, person, first, ctx, lib, forms) + inbox_evidence(root, zone, person, first, ctx, lib, forms)
            evidence = sorted(evidence, key=lambda e: e["date"], reverse=True)[:MOST_EVIDENCE]
        base = {"line": line, "person": person, "since": first.isoformat(), "looked": today.isoformat()}
        records[k] = dict(base, result="pending" if evidence else "no sign", source="", title="", date="", evidence=evidence)
    if new:
        write_seen(zone, seen)
    write_followups(zone, records)
    out.update(followup_counts(zone, today))
    out["pending"] = [{"key": key(l), "line": l, "person": records[key(l)]["person"], "evidence": records[key(l)]["evidence"]}
                      for l in due if records.get(key(l), {}).get("result") == "pending"]
    out["unseen"] = unseen
    return out


def followup_counts(zone: Path, today: datetime.date) -> dict:
    """The follow-up records of the zone's due lines, counted, with nothing looked at: {"due", "delivered", "in_part",
    "no_sign", "waiting", "unlooked"}: `waiting` is a due line with evidence that no judgement has answered, `unlooked` one
    no follow-up has looked at."""
    due = due_waiting(read(zone), today) if (zone / "Todo.md").is_file() else []
    records = read_followups(zone)
    out = {"due": len(due), "delivered": 0, "in_part": 0, "no_sign": 0, "waiting": 0, "unlooked": 0}
    for line in due:
        result = (records.get(key(line)) or {}).get("result")
        if result == "delivered":
            out["delivered"] += 1
        elif result == "in part":
            out["in_part"] += 1
        elif result == "no sign":
            out["no_sign"] += 1
        elif result == "pending":
            out["waiting"] += 1
        else:
            out["unlooked"] += 1
    return out


def record_answers(zone: Path, answers: List[dict], today: datetime.date) -> dict:
    """Record the judgement call's answers: [{"key", "result", "source"?}]. Code decides what each may mean. The key
    must be a line waiting for its answer; the result one of RESULTS; and a source, for *delivered* and *in part*, one of
    the sources code found for that line, never a path the answer brings. An answer that fails any of these is
    left out and the line stays pending. Returns the counts and the keys that were left out."""
    records = read_followups(zone)
    done = {"delivered": 0, "in part": 0, "no sign": 0, "left_out": []}
    for a in answers if isinstance(answers, list) else []:
        a = a if isinstance(a, dict) else {}
        rec = records.get(a.get("key"))
        result = a.get("result")
        if not rec or rec.get("result") != "pending" or result not in RESULTS:
            done["left_out"].append(str(a.get("key")))
            continue
        evidence = rec.get("evidence") or []
        chosen = next((e for e in evidence if e.get("path") == a.get("source")), None)
        if result != "no sign" and chosen is None:
            done["left_out"].append(str(a.get("key")))
            continue
        rec.update(result=result, looked=today.isoformat(), evidence=[])
        rec.update(source=chosen["path"] if chosen and result != "no sign" else "",
                   title=chosen["title"] if chosen and result != "no sign" else "",
                   date=chosen["date"] if chosen and result != "no sign" else "")
        done[result] += 1
    write_followups(zone, records)
    return done


def followup_say(found: dict) -> str:
    """The digest's line, "Follow-ups: 1 reply found, 2 to chase.", or "" when there is nothing to say. A reply
    found is a line the call judged delivered or in part; to chase is a line with no sign, or with evidence not yet judged. A line no follow-up has looked at is not counted."""
    replied = found.get("delivered", 0) + found.get("in_part", 0)
    chase = found.get("no_sign", 0) + found.get("waiting", 0)
    parts = []
    if replied:
        parts.append("%d repl%s found" % (replied, "y" if replied == 1 else "ies"))
    if chase:
        parts.append("%d to chase" % chase)
    return "Follow-ups: %s." % ", ".join(parts) if parts else ""


def zone_of(root: Path, name: str) -> Path:
    zones = root / "Zones"
    match = [z for z in (zones.iterdir() if zones.is_dir() else []) if z.is_dir() and z.name.lower() == name.lower()]
    if not match or not (match[0] / "Todo.md").is_file():
        raise SystemExit("todo: no zone %s with a Todo.md" % name)
    return match[0]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Expire, archive and tidy a zone's Todo.md.")
    ap.add_argument("command", choices=("expire", "archive", "tidy", "all", "oldest", "digest", "distil", "proposals", "followup"))
    ap.add_argument("--answers", help="followup: the judgement's answers as JSON, or - for standard input")
    ap.add_argument("--changes", help="distil: the JSON file of changes, or - for standard input")
    ap.add_argument("--yes", action="store_true", help="distil: the user has seen the before and after of the lines they moved, and agreed")
    ap.add_argument("--dry-run", action="store_true", help="distil: write nothing, say what would happen")
    ap.add_argument("--drop", action="append", default=[], help="proposals: an applied proposal's id")
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
    if a.command == "proposals":
        if a.drop:
            write_proposals(zone, [p for p in read_proposals(zone) if p["id"] not in set(a.drop)])
        found = proposal_view(zone)
        if a.json:
            print(json.dumps({"zone": zone.name, "proposals": found}, ensure_ascii=False))
        else:
            print("\n".join(proposal_text(p) for p in found) if found else "%s: no proposals." % zone.name)
        return 0
    if a.command == "followup":
        if a.answers:
            try:
                raw = sys.stdin.read() if a.answers == "-" else Path(a.answers).read_text(encoding="utf-8")
                got = json.loads(raw)
            except (OSError, ValueError) as e:
                raise SystemExit("todo: cannot read the answers: %s" % e)
            out = record_answers(zone, got.get("answers") if isinstance(got, dict) else got, today)
            print(json.dumps(dict(out, zone=zone.name)) if a.json else "%s: %d delivered, %d in part, %d no sign%s." % (
                zone.name, out["delivered"], out["in part"], out["no sign"],
                ", %d left out" % len(out["left_out"]) if out["left_out"] else ""))
            return 0
        out = followup(root, zone, today)
        print(json.dumps(out, ensure_ascii=False) if a.json else "%s: %d due, %d to judge, %d no sign, %d replies found." % (
            zone.name, out["due"], len(out["pending"]), out["no_sign"], out["delivered"] + out["in_part"]))
        return 0
    if a.command == "distil":
        if not a.changes:
            raise SystemExit("todo: distil needs --changes")
        try:
            raw = sys.stdin.read() if a.changes == "-" else Path(a.changes).read_text(encoding="utf-8")
            plan = json.loads(raw)
        except (OSError, ValueError) as e:
            raise SystemExit("todo: cannot read the changes: %s" % e)
        out = distil(root, zone, plan, today, yes=a.yes, dry=a.dry_run)
        print(json.dumps(out, ensure_ascii=False) if a.json else "\n".join([out["say"]] + out["notes"]))
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
