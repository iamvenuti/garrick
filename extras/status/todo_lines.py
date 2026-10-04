#!/usr/bin/env python3
"""todo_lines.py: read and edit the action lines in a zone's notes, for the
status page's Todo list. Standard library only.

A line is an Obsidian Tasks line: `- [ ]`, optionally opening with
`[[Thread]]: `, then the text, `#tags`, `· [src](…)`, any `(also in …)`, and
the Tasks fields last: priority, `📅` due, `⏳` scheduled (on a `#waiting`
line, the day to chase). The fields stay at the end, because Tasks reads them
nowhere else.

The tasks that count are every top-level `- [ ]` line in the zone's notes,
outside `archive/`, `_template/` and code fences, and not under an
`## Active threads` heading, whose lines are workstreams, not actions.

A line is addressed by its file and `key()`, a hash of its exact text. An
edit made from a page built before the line last changed finds no match and
is refused, rather than landing on a different line. The editing functions
are here for the page's actions, a preview feature; the page itself only reads.
"""
import datetime as dt
import hashlib
import json
import os
import re

PRIORITY = re.compile(r" *([🔺⏫🔼🔽⏬])️?")
DATE = re.compile(r" *((?:📅|📆|🗓|⏳|⌛|🛫|➕|✅|❌)️? *\d{4}-\d{2}-\d{2})")
DUE = re.compile(r"(?:📅|📆|🗓)️? *(\d{4}-\d{2}-\d{2})")
SCHEDULED = re.compile(r"(?:⏳|⌛)️? *(\d{4}-\d{2}-\d{2})")
LABEL = re.compile(r"^\[\[([^\]]*)\]\]:\s*")
UNSURE = re.compile(r"^⚠️ thread\?:\s*")
SRC = re.compile(r"\s*·\s*\[src\]\(([^)\s]*)\)")
ALSO = re.compile(r"\s*\(also in ((?:[^()]|\([^()]*\))*)\)")
MDLINK = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
TAG = re.compile(r"(?<!\S)#[^\s#]+")
SKIP_DIRS = {"archive", "_template", ".obsidian", ".git", ".trash"}
LEDGER = ".todo-seen.json"
SECTIONS = ("Inbox", "This week", "Waiting on", "Soon", "Someday")


def key(line):
    """The same key in every tool that addresses a line."""
    return hashlib.sha1(line.rstrip().encode("utf-8")).hexdigest()[:16]


def fields_last(line):
    """Priority and date fields to the end, in their order, priority first."""
    prio = [m.group(1) for m in PRIORITY.finditer(line)]
    dates = [m.group(1) for m in DATE.finditer(line)]
    if not prio and not dates:
        return line
    return " ".join([DATE.sub("", PRIORITY.sub("", line)).rstrip()] + prio + dates)


def parse(line):
    """The parts of a task line the page shows."""
    body = line[6:].rstrip()
    label = unsure = None
    m = LABEL.match(body)
    if m:
        label = m.group(1)
        body = body[m.end():]
    elif UNSURE.match(body):
        unsure = True
        body = UNSURE.sub("", body)
    src = SRC.search(body)
    also = [(t, u) for part in ALSO.findall(body) for t, u in MDLINK.findall(part)]
    due, sch = DUE.search(body), SCHEDULED.search(body)
    prio = PRIORITY.search(body)
    tags = TAG.findall(body)
    text = ALSO.sub("", SRC.sub("", body))
    text = DATE.sub("", PRIORITY.sub("", text))
    text = TAG.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    thread = None
    if label:
        target, _, alias = label.partition("|")
        thread = (alias or target.split("#", 1)[0].rsplit("/", 1)[-1]).strip()
    return {"thread": thread, "target": label.partition("|")[0].split("#", 1)[0] if label else None,
            "unsure": bool(unsure), "text": text, "src": src.group(1) if src else None, "also": also,
            "due": due.group(1) if due else None, "scheduled": sch.group(1) if sch else None,
            "priority": prio.group(1) if prio else None, "tags": tags,
            "waiting": any(t.startswith("#waiting") for t in tags)}


def notes(zone_dir):
    for d, dirs, files in os.walk(zone_dir):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            if f.endswith(".md"):
                yield os.path.join(d, f)


def _scan(zone_dir):
    """(relative file, `## ` section, line) for every top-level task line in the
    zone's live notes, open or ticked, outside code fences and `Active threads`."""
    for path in notes(zone_dir):
        rel = os.path.relpath(path, zone_dir)
        heading, section, fence = "", None, False
        try:
            lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
        except OSError:
            continue
        for line in lines:
            if line.startswith("```"):
                fence = not fence
                continue
            if fence:
                continue
            if re.match(r"#{1,6} ", line):
                heading = line
                if line.startswith("## "):
                    section = line[3:].strip()
                continue
            if line.startswith(("- [ ] ", "- [x] ")) and "Active threads" not in heading:
                yield rel, section if rel == "Todo.md" else None, line


def tasks(zone_dir):
    """Every open task in a zone: dicts with file (relative), section (the
    `## ` heading it sits under, in Todo.md), line, key, and parse()."""
    return [dict(parse(line), file=rel, section=sec, line=line, key=key(line))
            for rel, sec, line in _scan(zone_dir) if line.startswith("- [ ] ")]


def done_on(zone_dir, day):
    """Lines ticked on `day` and still in the zone's notes (Todo.md keeps them
    until they are archived). Keyed as the open line was, so an undo finds
    them."""
    stamp = re.compile(r"✅\uFE0F? *" + day.isoformat())
    return [dict(parse(_reopened(line)), file=rel, section=sec, line=line, key=key(_reopened(line)))
            for rel, sec, line in _scan(zone_dir) if line.startswith("- [x] ") and stamp.search(line)]


# ------------------------------------------------------------------- editing
class NotFound(Exception):
    pass


def _load(path):
    return open(path, encoding="utf-8").read().split("\n")


def _save(path, lines):
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp, path)


def _find(lines, k, reopen=False):
    for i, l in enumerate(lines):
        if not reopen and l.startswith("- [ ] ") and key(l) == k:
            return i
        if reopen and l.startswith("- [x] ") and key(_reopened(l)) == k:
            return i
    raise NotFound


def _reopened(line):
    return re.sub(r" ✅️? *\d{4}-\d{2}-\d{2}", "", "- [ ] " + line[6:]).rstrip()


def _rekey(zone_dir, old, new):
    """Carry a line's first-seen date to its new text, so an edit made from
    the page does not restart its 14 days in the Inbox."""
    ledger = os.path.join(zone_dir, LEDGER)
    try:
        seen = json.load(open(ledger))
    except (OSError, ValueError):
        return
    if old in seen:
        seen[new] = seen.pop(old)
        with open(ledger + ".new", "w") as f:
            json.dump(dict(sorted(seen.items())), f, indent=0)
        os.replace(ledger + ".new", ledger)


def done(zone_dir, rel, k, today=None):
    """Tick a line as Tasks does: `- [x]` and a `✅` date at the end."""
    today = today or dt.date.today()
    path = os.path.join(zone_dir, rel)
    lines = _load(path)
    i = _find(lines, k)
    text = parse(lines[i])["text"]
    lines[i] = "- [x] " + lines[i][6:].rstrip() + f" ✅ {today.isoformat()}"
    _save(path, lines)
    return text


def undo(zone_dir, rel, k):
    """Untick a line ticked from the page, until it is archived."""
    path = os.path.join(zone_dir, rel)
    lines = _load(path)
    i = _find(lines, k, reopen=True)
    lines[i] = _reopened(lines[i])
    _save(path, lines)
    return parse(lines[i])["text"]


def _section_bounds(lines, name):
    start = next((i for i, l in enumerate(lines) if l.strip() == f"## {name}"), None)
    if start is None:
        return None, None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    return start, end


def _insert_top(lines, name, line):
    """Put a line at the top of a section, under its description, newest first."""
    start, end = _section_bounds(lines, name)
    if start is None:
        raise NotFound
    body = [l for l in lines[start + 1:end] if l.strip() != "*Nothing recorded yet.*"]
    j = 0
    while j < len(body) and not body[j].strip():
        j += 1
    k = j
    while k < len(body) and body[k].strip() and not body[k].startswith("- ["):
        k += 1                                   # the description paragraph
    desc, rest = body[j:k], body[k:]
    while rest and not rest[0].strip():
        rest.pop(0)
    new = [""] + (desc + [""] if desc else []) + [line] + rest
    if new[-1].strip():
        new.append("")                           # a blank line before the next heading
    lines[start + 1:end] = new


def set_date(zone_dir, rel, k, date, today=None):
    """Set or clear a line's date: `⏳` on a `#waiting` line (the day to chase),
    `📅` on any other. A date counts as triage: in Todo.md an Inbox line that
    gets one leaves the Inbox, for This week when it is due within seven days,
    Soon when later, Waiting on when it is a chase. Returns (text, where it
    went or None, the line's new key)."""
    today = today or dt.date.today()
    path = os.path.join(zone_dir, rel)
    lines = _load(path)
    i = _find(lines, k)
    line = lines[i].rstrip()
    p = parse(line)
    field, rx = ("⏳", SCHEDULED) if p["waiting"] else ("📅", DUE)
    new = re.sub(r" *" + rx.pattern, "", line).rstrip()
    if date:
        new = fields_last(f"{new} {field} {date.isoformat()}")
    moved = None
    section = None
    if rel == "Todo.md":
        for j in range(i, -1, -1):
            if lines[j].startswith("## "):
                section = lines[j][3:].strip()
                break
    if section == "Inbox" and date:
        moved = "Waiting on" if p["waiting"] else "This week" if (date - today).days <= 7 else "Soon"
        del lines[i]
        try:
            _insert_top(lines, moved, new)
        except NotFound:
            lines.insert(i, new)
            moved = None
    else:
        lines[i] = new
    _save(path, lines)
    _rekey(zone_dir, k, key(new))
    return p["text"], moved, key(new)
