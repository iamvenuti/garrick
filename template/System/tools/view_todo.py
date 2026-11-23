#!/usr/bin/env python3
"""The Todo reader of the view model (#650): each zone's open action lines, as the Todo tab draws them.

`view.py` loads this module for its `todo` part. It reads the notes of one zone and writes nothing. The App's own
`todo_lines.py` keeps the editing half and a copy of this reading half, because an extra updates on its own; a test holds
the two to the same answer, line for line.

A line is an Obsidian Tasks line: `- [ ]`, optionally opening with `[[Thread]]: `, then the text, `#tags`, `· [src](...)`,
any `(also in ...)`, and the Tasks fields last: priority, `📅` due, `⏳` scheduled (on a `#waiting` line, the day to
chase). The tasks that count are every top-level `- [ ]` line in the zone's notes, outside code fences and not under an
`## Active threads` heading. The zone's notes are what the check reads as its notes, `garrick_lib.live_files()`; of
those, a note the vault's Obsidian excludes (`userIgnoreFilters` in `.obsidian/app.json`) is left out too, and the
zone's `Todo.md` always counts.

Walls. A note that is a link whose real path is outside the zone is no note of the zone, so a line of another zone
never shows through a link. A task carries its zone's name only through the zone record it sits in.
"""
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

PRIORITY = re.compile(r" *([🔺⏫🔼🔽⏬])️?")
DATE = re.compile(r" *((?:📅|📆|🗓|⏳|⌛|🛫|➕|✅|❌)️? *\d{4}-\d{2}-\d{2})")
DUE = re.compile(r"(?:📅|📆|🗓)️? *(\d{4}-\d{2}-\d{2})")
SCHEDULED = re.compile(r"(?:⏳|⌛)️? *(\d{4}-\d{2}-\d{2})")
LABEL = re.compile(r"^\[\[([^\]]*)\]\]:\s*")
UNSURE = re.compile(r"^⚠️ thread\?:\s*")
SRC = re.compile(r"\s*·\s*\[src\]\(([^)\s]*)\)")
ALSO = re.compile(r"\s*\(also in ((?:[^()]|\([^()]*\))*)\)")
MDLINK = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
# A tag holds a character that is not a digit, as in Obsidian: `#351` and `#351,` are text.
TAG = re.compile(r"(?<!\S)#(?!\d+(?![\w/-]))[^\s#]+")


def key(line: str) -> str:
    """The same key in every tool that addresses a line."""
    return hashlib.sha1(line.rstrip().encode("utf-8")).hexdigest()[:16]


def parse(line: str) -> dict:
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
    also = [[t, u] for part in ALSO.findall(body) for t, u in MDLINK.findall(part)]
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


def _reopened(line: str) -> str:
    return re.sub(r" ✅️? *\d{4}-\d{2}-\d{2}", "", "- [ ] " + line[6:]).rstrip()


def vault_of(top, folder) -> Optional[Path]:
    """The Obsidian vault a folder's notes belong to: the nearest folder at or above it, up to `top` (the workspace
    root), that holds a .obsidian folder."""
    folder, top = Path(folder), Path(top)
    for f in (folder, *folder.parents):
        if (f / ".obsidian").is_dir():
            return f
        if f == top or f == f.parent:
            return None
    return None


def ignore_filters(vault) -> list:
    """The vault's Excluded files (.obsidian/app.json, `userIgnoreFilters`): a path prefix or a /regex/ each. Empty when
    there are none or they do not read."""
    out: list = []
    if vault is None:
        return out
    try:
        with open(os.path.join(str(vault), ".obsidian", "app.json"), encoding="utf-8") as f:
            data = json.load(f)
        for flt in data.get("userIgnoreFilters") or []:
            if not isinstance(flt, str) or not flt:
                continue
            try:
                out.append(re.compile(flt[1:-1]) if len(flt) > 2 and flt.startswith("/") and flt.endswith("/") else flt)
            except re.error:
                continue
    except (OSError, ValueError, AttributeError, TypeError):
        return []
    return out


def ignored(rel: str, filters: list) -> bool:
    """Whether a path inside the vault, `/`-separated, is one Obsidian excludes."""
    return any(f.search(rel) if hasattr(f, "search") else rel.startswith(f) for f in filters)


def notes(zone_dir, live_files: Callable, within: Callable) -> List[str]:
    """Every Markdown note of the zone, as the module's docstring says: through `live_files`, leaving out a vault's
    excluded notes and any note that is a link out of the zone (`within(path, inside)`)."""
    zone = Path(os.path.abspath(str(zone_dir)))
    ws = zone.parent.parent if zone.parent.name == "Zones" else None
    vault = vault_of(ws or zone, zone)
    filters = ignore_filters(vault)
    inside = zone.resolve()
    out = []
    for path in (str(p) for p in live_files(zone_dir)):
        if not path.endswith(".md"):
            continue
        if os.path.islink(path) and not within(Path(path), inside):
            continue
        if filters and os.path.relpath(path, str(zone_dir)) != "Todo.md":
            rel = Path(os.path.abspath(path)).relative_to(vault).as_posix()
            if ignored(rel, filters):
                continue
        out.append(path)
    return out


def scan(zone_dir, paths: List[str]):
    """(relative file, `## ` section, line) for every top-level task line in the notes, open or ticked, outside code
    fences and `Active threads`."""
    for path in paths:
        rel = os.path.relpath(path, str(zone_dir))
        heading, section, fence = "", None, False
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().split("\n")
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


def tasks(zone_dir, paths: List[str]) -> List[dict]:
    """Every open task in a zone: dicts with file (relative), section (the `## ` heading it sits under, in Todo.md),
    line, key, and parse()."""
    return [dict(parse(line), file=rel, section=sec, line=line, key=key(line))
            for rel, sec, line in scan(zone_dir, paths) if line.startswith("- [ ] ")]


def done_on(zone_dir, paths: List[str], day) -> List[dict]:
    """Lines ticked on `day` and still in the zone's notes (Todo.md keeps them until they are archived). Keyed as the
    open line was, so an undo finds them."""
    stamp = re.compile(r"✅️? *" + day.isoformat())
    return [dict(parse(_reopened(line)), file=rel, section=sec, line=line, key=key(_reopened(line)))
            for rel, sec, line in scan(zone_dir, paths) if line.startswith("- [x] ") and stamp.search(line)]


def line_place(parts) -> tuple:
    """The project and the thread a line belongs to, from the note it points at or sits in (#596), given the note's
    path from its zone as parts: a thread's note, or any file in its folder, gives both; a project's hub, or a file in the
    project and not in a thread, gives the project alone. A note outside the zone's projects, or not placed, gives
    neither."""
    parts = tuple(parts)
    if len(parts) >= 4 and parts[1] == "Threads":
        return parts[0], parts[2]
    if len(parts) >= 2 and parts[0] not in ("Inbox", "archive") and not parts[0].startswith("."):
        return parts[0], ""
    return "", ""


def zone_todo(zone: Path, root: Path, today, system: Dict[str, str], live_files: Callable, within: Callable) -> dict:
    """One zone's Todo record: where its `Todo.md` is, its `## ` headings in order, its open actions and what was
    ticked `today`. Each action carries the note its line names or sits in (`note`, from the workspace), the name the
    page shows (`label`), and the project and thread of that note. `system` maps a lower-cased link target to a note of a
    project kept in System/ (from the workspace)."""
    zone = Path(zone)
    inside = zone.resolve()
    todo_md = zone / "Todo.md"
    has_todo = todo_md.is_file() and within(todo_md, inside)
    paths = notes(zone, live_files, within)
    known: Dict[str, str] = {}
    for n in paths:
        rel = Path(n).relative_to(zone).with_suffix("").as_posix()
        known.setdefault(rel.lower(), Path(n).relative_to(root).as_posix())
        known.setdefault(Path(n).stem.lower(), Path(n).relative_to(root).as_posix())
    for name, n in system.items():
        known.setdefault(name, n)

    def place(t: dict) -> dict:
        if t["file"] != "Todo.md":
            label, note = Path(t["file"]).stem, (zone / t["file"]).relative_to(root).as_posix()
        elif t["target"]:
            label = t["thread"]
            note = known.get(t["target"].lower()) or known.get(t["target"].rsplit("/", 1)[-1].lower())
        else:
            label, note = None, None
        project, tname = "", ""
        if note and not t["unsure"]:
            try:
                project, tname = line_place(Path(os.path.abspath(str(root / note))).relative_to(os.path.abspath(str(zone))).parts)
            except ValueError:
                pass
        return dict(t, note=note, label=label, project=project, tname=tname)

    open_ = [place(t) for t in tasks(zone, paths) if t["text"] and "<action>" not in t["text"]]
    done = [place(t) for t in done_on(zone, paths, today) if t["text"] and "<action>" not in t["text"]]
    order: List[str] = []
    if has_todo:
        try:
            order = [l[3:].strip() for l in todo_md.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("## ")]
        except OSError:
            order = []
    return {"file": todo_md.relative_to(root).as_posix() if has_todo else None, "order": order, "tasks": open_, "done": done}
