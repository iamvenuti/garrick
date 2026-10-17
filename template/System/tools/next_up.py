#!/usr/bin/env python3
"""next_up.py: one thing worth doing while a long turn runs, ranked by plain rules.

    python3 System/tools/next_up.py                       every zone, as JSON
    python3 System/tools/next_up.py --zone Work           the session's zone, which
                                                          "same zone only" narrows to
    python3 System/tools/next_up.py --exclude Zones/Work/Acme/Threads/Pricing
                                                          never the thread the turn works on
    python3 System/tools/next_up.py --say                 the first pick, said in one line

It prints the list, best first, and changes nothing. The Garrick band runs it
once a turn has run past the threshold, and the threads skill runs it for
"what's next" in a session without the band, so both offer the same first
pick. No model is asked: the order is six rules, each a source that can be
switched off in Settings › While you wait.

1. stack    the top of the interruption stack, System/generated/interrupted.json,
            read only with the status extra (System/status/page_action.py),
            which keeps it
2. due      Todo lines overdue or due today, the quickest first: a reply or a
            chase before a line that names a deliverable, then the latest
3. chase    `#waiting` and Waiting on lines whose `⏳` chase day has come
4. inbox    what waits in a zone's Inbox, or the Meetings inbox, one pick each
5. parked   a parked thread, or a parked project, untouched for longer than
            `parked-days` (30): park or finish?
6. wrap     a live thread whose Resume here block is older than `wrap-days`
            (14): wrap?

The Todo lines are read through System/skills/todo/todo.py's own reading, the
one its digest uses, so there is one Todo reader. A pick names a thread and an
action in a few words and never quotes a meeting: a link to a meeting page,
a source link, an aside after " — " and a quotation are left out. A pick in
the folder named by `--exclude`, the thread the running turn works on, is
never made. With "same zone only" switched on and `--zone` given, only that
zone's picks are made; otherwise every zone's.

Each pick is {"id", "rule", "source", "say", "zone", "project", "thread",
"note"}, with "tick", the request page_action.py takes on stdin to tick it,
on a Todo line. The settings are in System/garrick-settings.json under
"while-you-wait": {"on", "threshold" (seconds), "same-zone", "sources" (in
their order), "parked-days", "wrap-days"}; clean() checks them as the status
page saves them. Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import garrick_lib as gl  # noqa: E402

KEY = "while-you-wait"
SOURCES = ("stack", "due", "chase", "inbox", "parked", "wrap")
SOURCE_LABELS = {
    "stack": "The interruption stack",
    "due": "Todo lines due today or late",
    "chase": "Chases that have come due",
    "inbox": "What waits in an Inbox",
    "parked": "Parked threads left alone",
    "wrap": "Live threads not wrapped lately",
}
DEFAULTS = {"on": True, "threshold": 45, "same-zone": False, "sources": list(SOURCES), "parked-days": 30, "wrap-days": 14}
THRESHOLD = (10, 600)           # seconds a turn runs before the band offers anything
DAYS = (1, 365)
STACK_FILE = ("System", "generated", "interrupted.json")
STATUS_EXTRA = ("System", "status", "page_action.py")
SKIP = {"archive", "Inbox", "Sources", "Deliverables"}
PARKED, DONE = "parked", "done"

# A line that asks for a reply or a chase is a few minutes' work; one that
# names a deliverable is not. Plain words, no model.
QUICK = re.compile(r"\b(reply|replies|answer|respond|chase|confirm|call|ring|send|email|e-mail|mail|message|ask|ping|"
                   r"remind|book|forward|accept|decline|tick|pay)\b", re.I)
DELIVERABLE = re.compile(r"\b(draft|write|build|prepare|finish|deck|slides|report|brief|proposal|model|workbook|"
                         r"spreadsheet|document|redline|review)\b", re.I)
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
QUOTED = re.compile(r"\s*(“[^”]*”|\"[^\"]*\")")
ISO = re.compile(r"\b(\d{4}-\d\d-\d\d)\b")
SPOKEN_DATE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")


# ---- settings -----------------------------------------------------------------

def clean(given) -> dict:
    """Settings › While you wait as the page sends it, checked: every key
    named, each the right kind and in range. Raises ValueError with the
    sentence the page shows."""
    if not isinstance(given, dict):
        raise ValueError("While you wait: not a set of choices")
    unknown = sorted(set(given) - set(DEFAULTS))
    if unknown:
        raise ValueError("While you wait has no setting called %s" % ", ".join(repr(k) for k in unknown))
    out = dict(DEFAULTS, sources=list(SOURCES))
    for flag in ("on", "same-zone"):
        if flag in given:
            if not isinstance(given[flag], bool):
                raise ValueError("While you wait: %s is on or off" % flag)
            out[flag] = given[flag]
    for name, (low, high), what in (("threshold", THRESHOLD, "seconds"), ("parked-days", DAYS, "days"),
                                    ("wrap-days", DAYS, "days")):
        if name in given:
            value = given[name]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError("While you wait: %s is a whole number of %s from %d to %d" % (name, what, low, high))
            out[name] = value
    if "sources" in given:
        sources = given["sources"]
        if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources) or len(set(sources)) != len(sources):
            raise ValueError("While you wait: the sources are a list of names, each once")
        bad = [s for s in sources if s not in SOURCES]
        if bad:
            raise ValueError("While you wait has no source called %s" % ", ".join(repr(s) for s in bad))
        out["sources"] = list(sources)
    return out


def settings(root: Path) -> dict:
    """The choices as saved, each one that is missing or does not read taken
    from DEFAULTS, so a hand-edited file never stops the band."""
    saved = gl.read_settings(root).get(KEY)
    out = dict(DEFAULTS, sources=list(SOURCES))
    if not isinstance(saved, dict):
        return out
    for key in DEFAULTS:
        if key in saved:
            try:
                out[key] = clean({key: saved[key]})[key]
            except ValueError:
                pass
    return out


# ---- reading the workspace ----------------------------------------------------

def todo_lib():
    """The todo skill's script, whose reading of a Todo.md is the only one."""
    src = HERE.parent / "skills" / "todo" / "todo.py"
    if not src.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("garrick_next_up_todo", str(src))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:
        return None
    return mod if callable(getattr(mod, "classify", None)) else None


def visible(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def as_date(value) -> Optional[datetime.date]:
    if isinstance(value, datetime.date):
        return value
    m = ISO.search(str(value or ""))
    try:
        return datetime.date.fromisoformat(m.group(1)) if m else None
    except ValueError:
        return None


def block_date(text: str) -> Optional[datetime.date]:
    """The date a Resume here block gives itself, on its first lines, before
    its table: an ISO date or "6 October 2026". Nothing else of it is read."""
    for line in gl.resume_lines(text)[:12]:
        if line.startswith("|"):
            break
        found = as_date(line)
        if found:
            return found
        for day, month, year in SPOKEN_DATE.findall(line):
            number = next((i + 1 for i, m in enumerate(MONTHS) if m[:3] == month.lower()[:3]), None)
            try:
                if number:
                    return datetime.date(int(year), number, int(day))
            except ValueError:
                continue
    return None


def touched(note: Path, fm: dict) -> datetime.date:
    """When a note last moved: its `updated:`, else the file's own time."""
    return as_date(fm.get("updated")) or datetime.date.fromtimestamp(note.stat().st_mtime)


def threads(root: Path) -> List[dict]:
    """Every project and thread note, with what the rules need: its zone,
    project, thread, path from the root, status (a parked project parks its
    threads), and its dates. A project with no thread note is its own single
    thread."""
    out = []
    for zone in visible(root / "Zones"):
        for project in visible(zone):
            if project.name in SKIP:
                continue
            hub = project / (project.name + ".md")
            pfm = gl.parse_frontmatter(hub) if hub.is_file() else {}
            hub_state = str(pfm.get("status") or "").strip().lower()
            found = [(t.name, t / (t.name + ".md")) for t in visible(project / "Threads")]
            found = [(name, note) for name, note in found if note.is_file()]
            if hub.is_file() and hub_state == PARKED:
                out.append(row(root, zone, project, None, hub, pfm, PARKED, whole=True))
                continue
            if not found and hub.is_file():
                out.append(row(root, zone, project, None, hub, pfm, hub_state))
            for name, note in found:
                fm = gl.parse_frontmatter(note)
                out.append(row(root, zone, project, name, note, fm, str(fm.get("status") or "").strip().lower()))
    return out


def row(root: Path, zone: Path, project: Path, thread: Optional[str], note: Path, fm: dict, status: str,
        whole: bool = False) -> dict:
    try:
        text = note.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return {"zone": zone.name, "project": project.name, "thread": thread, "note": note.relative_to(root).as_posix(),
            "status": status, "whole": whole, "touched": touched(note, fm), "resumed": block_date(text)}


def meeting_names(root: Path) -> set:
    """The names of the Meetings wiki's pages, so a Todo line's link to one is
    left out of what is said."""
    names = set()
    wiki = root / "Wikis" / "Meetings"
    for top, dirs, files in os.walk(str(wiki)):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        names.update(f[:-3].casefold() for f in files if f.endswith(".md"))
    return names


def said(todo, line: str, meetings: set) -> str:
    """A Todo line in a few words, through the todo skill's plain(): its
    thread, then the action, with no meeting in it."""
    head = re.match(r"^- \[[ x]\] (\[\[[^\]]+\]\]:\s*)?", line)
    start = head.end() if head else 0

    def keep(m):
        target = m.group(1).strip()
        if "meetings/" in target.casefold() or target.rsplit("/", 1)[-1].casefold() in meetings:
            return ""
        return m.group(0)
    body = QUOTED.sub("", WIKILINK.sub(keep, line[start:]))
    return todo.plain(line[:start] + body)


def label_of(line: str) -> Optional[str]:
    m = re.match(r"^- \[ \] \[\[([^\]|#]+)", line)
    return m.group(1).rsplit("/", 1)[-1].strip() if m else None


# ---- the rules ------------------------------------------------------------------

def pick(rule: str, say: str, zone: Optional[str], note: Optional[str] = None, project: Optional[str] = None,
         thread: Optional[str] = None, ident: str = "", **extra) -> dict:
    out = {"id": "%s:%s" % (rule, ident or note or zone), "rule": SOURCES.index(rule) + 1, "source": rule,
           "say": say, "zone": zone, "project": project, "thread": thread, "note": note}
    out.update(extra)
    return out


def from_stack(root: Path) -> List[dict]:
    """The held threads, top first; next_up() keeps the first the running
    turn leaves. A note no longer there, or a path out of its zone, is passed
    over, as page_action.py passes over it."""
    if not root.joinpath(*STATUS_EXTRA).is_file():
        return []
    try:
        entries = json.loads(root.joinpath(*STACK_FILE).read_text(encoding="utf-8")).get("stack")
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) for k in ("zone", "project", "file")):
            continue
        note = "Zones/%s/%s" % (e["zone"], e["file"])
        if ".." in Path(note).parts or not (root / note).is_file():
            continue
        name = e.get("thread") or e["project"]
        when = str(e.get("at") or "")
        held = (" since " + when[11:16]) if re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d", when) else ""
        out.append(pick("stack", "Back to %s, on hold%s" % (name, held), e["zone"], note, e["project"], e.get("thread")))
    return out


def from_todo(root: Path, today: datetime.date, notes: List[dict]) -> Dict[str, List[dict]]:
    todo = todo_lib()
    due, chase = [], []
    if todo is None:
        return {"due": due, "chase": chase}
    meetings = meeting_names(root)
    for zone in visible(root / "Zones"):
        if not (zone / "Todo.md").is_file():
            continue
        try:
            found = todo.classify(todo.read(zone), today)
        except (OSError, ValueError):
            continue
        place = [r for r in notes if r["zone"] == zone.name]

        def where(line):
            name = label_of(line)
            hit = [r for r in place if name and (r["thread"] or r["project"]).casefold() == name.casefold()]
            r = hit[0] if len(hit) == 1 else None
            return {"note": r["note"] if r else "Zones/%s/Todo.md" % zone.name,
                    "project": r["project"] if r else None, "thread": r["thread"] if r else None}

        def tick(line):
            return {"verb": "todo-done", "zone": zone.name, "file": "Todo.md", "key": todo.key(line)}
        for late, line in found["overdue"]:
            words = said(todo, line, meetings)
            due.append((quickness(words), -late, pick("due", "%s (%s, %s late)" % (words, zone.name, days(late)), zone.name,
                                                      ident=todo.key(line), tick=tick(line), **where(line))))
        for line in found["due"]:
            words = said(todo, line, meetings)
            due.append((quickness(words), 0, pick("due", "%s (%s, due today)" % (words, zone.name), zone.name,
                                                  ident=todo.key(line), tick=tick(line), **where(line))))
        for line in found["chase"]:
            words = said(todo, line, meetings)
            chase.append(pick("chase", "Chase: %s (%s)" % (words, zone.name), zone.name, ident=todo.key(line),
                              tick=tick(line), **where(line)))
    due.sort(key=lambda t: (t[0], t[1]))
    return {"due": [p for _, _, p in due], "chase": chase}


def quickness(words: str) -> int:
    action = words.split(": ", 1)[-1]
    if QUICK.search(action):
        return 0
    return 2 if DELIVERABLE.search(action) else 1


def days(n: int) -> str:
    return "1 day" if n == 1 else "%d days" % n


def from_inboxes(root: Path) -> List[dict]:
    places = [(z.name, z / "Inbox", "%s's Inbox" % z.name) for z in visible(root / "Zones")]
    places.append((None, root / "Wikis" / "Meetings" / "raw" / "inbox", "the Meetings inbox"))
    out = []
    for zone, folder, name in places:
        n = sum(1 for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")) if folder.is_dir() else 0
        if n:
            out.append(pick("inbox", "%d %s in %s: say “process the inbox”" % (n, "file" if n == 1 else "files", name),
                            zone, folder.relative_to(root).as_posix()))
    return sorted(out, key=lambda p: -int(p["say"].split(" ", 1)[0]))


def from_parked(notes: List[dict], today: datetime.date, limit: int) -> List[dict]:
    out = []
    for r in notes:
        if r["status"] != PARKED:
            continue
        idle = (today - r["touched"]).days
        if idle > limit:
            name = r["project"] if r["whole"] else "%s (%s)" % (r["thread"] or r["project"], r["project"])
            out.append((-idle, pick("parked", "Park or finish? %s, untouched %s" % (name, days(idle)), r["zone"], r["note"],
                                    r["project"], r["thread"])))
    return [p for _, p in sorted(out, key=lambda t: t[0])]


def from_unwrapped(notes: List[dict], today: datetime.date, limit: int) -> List[dict]:
    out = []
    for r in notes:
        if r["status"] in (PARKED, DONE):
            continue
        when = r["resumed"] or r["touched"]
        old = (today - when).days
        if old > limit:
            name = r["thread"] or r["project"]
            where = " (%s)" % r["project"] if r["thread"] else ""
            out.append((-old, pick("wrap", "Wrap? %s%s, resume point %s old" % (name, where, days(old)), r["zone"],
                                   r["note"], r["project"], r["thread"])))
    return [p for _, p in sorted(out, key=lambda t: t[0])]


def inside(note: Optional[str], folder: Optional[str]) -> bool:
    return bool(note and folder) and (note == folder or note.startswith(folder + "/"))


def next_up(root: Path, zone: Optional[str] = None, exclude: Optional[str] = None,
            today: Optional[datetime.date] = None) -> dict:
    """The ranked picks, and the settings they were made under."""
    root = Path(root).resolve()
    today = today or datetime.date.today()
    chosen = settings(root)
    if exclude:
        ex = Path(exclude)
        ex = ex.resolve() if ex.is_absolute() else (root / ex).resolve()
        if ex.suffix == ".md":
            ex = ex.parent
        try:
            exclude = ex.relative_to(root).as_posix()
        except ValueError:
            exclude = None
    notes = threads(root)
    todo = None
    picks: List[dict] = []
    for source in chosen["sources"]:
        if source == "stack":
            found = from_stack(root)
        elif source in ("due", "chase"):
            todo = todo if todo is not None else from_todo(root, today, notes)
            found = todo[source]
        elif source == "inbox":
            found = from_inboxes(root)
        elif source == "parked":
            found = from_parked(notes, today, chosen["parked-days"])
        else:
            found = from_unwrapped(notes, today, chosen["wrap-days"])
        picks += found
    picks = [p for p in picks if not inside(p["note"], exclude)]
    narrowed = bool(chosen["same-zone"] and zone)
    if narrowed:
        picks = [p for p in picks if p["zone"] is not None and p["zone"].casefold() == zone.casefold()]
    seen, out = set(), []
    for p in picks:
        if p["id"] in seen or (p["source"] == "stack" and any(o["source"] == "stack" for o in out)):
            continue                    # the top of the stack alone: the first the running turn leaves
        seen.add(p["id"])
        out.append(p)
    return {"on": chosen["on"], "threshold": chosen["threshold"], "zone": zone, "same_zone": narrowed,
            "exclude": exclude, "settings": chosen, "picks": out}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="What to do while a long turn runs, ranked by plain rules.")
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    ap.add_argument("--zone", help="the session's zone; with \"same zone only\" on, only its picks")
    ap.add_argument("--exclude", help="the thread the running turn works on: its folder or its note")
    ap.add_argument("--today", help="YYYY-MM-DD, for tests")
    ap.add_argument("--say", action="store_true", help="the first pick in one line, for the ear")
    a = ap.parse_args(argv)
    root = Path(a.root).expanduser().resolve() if a.root else HERE.parents[1]
    if not (root / "System" / "rules.md").is_file():
        print("next_up: %s is not a Garrick workspace" % root, file=sys.stderr)
        return 2
    today = datetime.date.fromisoformat(a.today) if a.today else None
    found = next_up(root, a.zone, a.exclude, today)
    if a.say:
        print(found["picks"][0]["say"] if found["picks"] else "Nothing is waiting.")
    else:
        print(json.dumps(found, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
