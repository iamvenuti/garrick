#!/usr/bin/env python3
"""briefing.py: what changed in a zone's threads over a period, gathered for
"catch me up". It lists and orders; it never decides what matters.

    python3 System/tools/briefing.py --zone Work                  the period the settings keep, the last day
    python3 System/tools/briefing.py --zone Work --since 2026-10-19
    python3 System/tools/briefing.py --zone Work --days 3
    python3 System/tools/briefing.py --zone Work --period week     since Monday
    python3 System/tools/briefing.py --zone Work --project Acme --thread "Birch Entry/Launch"
    python3 System/tools/briefing.py --zone Work --zone Personal   more zones, only when named

It prints JSON and changes nothing. The `threads` skill's *Catch up* runs it,
reads `System/briefing.md` (and `System/briefing.local.md`, which wins) for
what deserves attention, and writes the briefing from what it printed.

**One zone at a time.** `--zone` names it, and is repeated for more. A
workspace with a single zone needs none. `--project` and `--thread` narrow
the zone to what they name; a thread is named by its folder, `Pricing`, or
with its project, `Acme/Pricing`. The skill resolves a heard name first, as
for every thread command, and passes the folder names here.

**The period** runs from the start of a day to now: `--since` that day,
`--days N` the last N days (1 is since yesterday), `--period` one of PERIODS,
or, with none of them, the period kept in System/garrick-settings.json under
"catch-up", the last day until it is changed.

**What it reads, per thread** (a thread note, or a project with no threads,
whose hub is its thread):

- the zone's git history of the thread's folder in the period: each commit's
  hash, time, author, subject, body and the files it touched there, newest
  first, and what is changed and not committed;
- the Resume here block now, its rows read out, and, where it changed in the
  period, the block as it stood at the period's start;
- the dated entries added in the period: those the note holds now and did
  not hold then, or, with no history to compare, those dated in the period;
- a waiting `### Checkpoint` block, read with garrick_lib's reader, and
  whether it predates the Resume here block it was written against;
- the zone's `Todo.md` lines that open with the thread's link, read through
  the todo skill's todo.py (`classify()`, `link_of()`, `done_on()`), split
  into `added` (new in the period, still open), `ticked` (done in the
  period, from the list or the zone's `archive/Todo-<YYYY>.md`) and `open`
  (open from before). Each is said as next_up.py says a line, so no meeting
  is quoted from it;
- the meeting pages the thread note already links, as links and nothing
  more: a meeting is never opened, quoted or summarised here, so the walls
  hold as they do for every other thread command.

**What is listed.** A live thread that changed in the period, newest change
first. A thread named with `--thread` is listed whether or not it changed.
A parked thread only when it, or its project, is named. A finished thread
only when it changed. The live threads in scope that did not change are
named under "quiet", and the parked ones left out are counted, never named.

Importable: `gather()`, `period()`, `settings()`, `clean()`, and PERIODS
for the status page's Catch up dialog. Exit codes: 0; 2 for a usage
error, no workspace or no such zone. Standard library only, Python 3.9 or
later.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import garrick_lib as gl  # noqa: E402

KEY = "catch-up"
# Each period a catch-up can cover by default: its key, how the dialog names it,
# and the words a request carries for it, which the skill hears back.
PERIODS = (
    ("day", "The last day", "since yesterday"),
    ("week", "This week, since Monday", "this week"),
    ("7-days", "The last seven days", "for the last seven days"),
    ("14-days", "The last two weeks", "for the last two weeks"),
)
PERIOD_KEYS = tuple(k for k, _, _ in PERIODS)
PERIOD_LABELS = {k: label for k, label, _ in PERIODS}
PERIOD_WORDS = {k: words for k, _, words in PERIODS}
DEFAULTS = {"period": "day"}
DAYS = (1, 366)
GUIDANCE = ("System/briefing.md", "System/briefing.local.md")
SKIP = {"archive", "Inbox", "Sources", "Deliverables"}
PARKED, DONE = "parked", "done"
EXIT_USAGE = 2

DATED = re.compile(r"^\*\*(\d{1,2} [A-Za-z]+ \d{4}|\d{4}-\d\d-\d\d)\.?\*\*")
ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
MDLINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
SEP = "\x1e"
FIELD = "\x1f"


# ---- settings -------------------------------------------------------------------

def clean(given) -> dict:
    """The "catch-up" setting, checked. Raises ValueError with the sentence
    to show. Settings no longer offers it (#226): it is set by hand."""
    if not isinstance(given, dict):
        raise ValueError("Catch up: not a set of choices")
    unknown = sorted(set(given) - set(DEFAULTS))
    if unknown:
        raise ValueError("Catch up has no setting called %s" % ", ".join(repr(k) for k in unknown))
    out = dict(DEFAULTS)
    if "period" in given:
        if given["period"] not in PERIOD_KEYS:
            raise ValueError("Catch up has no period called %r; it is one of %s" % (given["period"], ", ".join(PERIOD_KEYS)))
        out["period"] = given["period"]
    return out


def settings(root: Path) -> dict:
    """The choices as saved, a missing or unreadable one taken from DEFAULTS."""
    saved = gl.read_settings(root).get(KEY)
    out = dict(DEFAULTS)
    if isinstance(saved, dict):
        for key in DEFAULTS:
            if key in saved:
                try:
                    out[key] = clean({key: saved[key]})[key]
                except ValueError:
                    pass
    return out


def period(today: datetime.date, since: Optional[datetime.date] = None, days: Optional[int] = None,
           named: Optional[str] = None, default: str = "day") -> Tuple[datetime.date, str]:
    """(the first day the period covers, how it was given). `since` wins, then
    `days`, then `named`, then the default period."""
    if since is not None:
        return min(since, today), "since"
    if days is not None:
        return today - datetime.timedelta(days=days), "days"
    key, how = named or default, "period" if named else "settings"
    if key == "week":
        return today - datetime.timedelta(days=today.weekday()), how
    return today - datetime.timedelta(days={"day": 1, "7-days": 7, "14-days": 14}.get(key, 1)), how


def said_day(day: datetime.date, today: datetime.date) -> str:
    if day == today:
        return "today"
    if day == today - datetime.timedelta(days=1):
        return "yesterday"
    name = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[day.weekday()]
    return "%s %d %s" % (name, day.day, MONTHS[day.month - 1].capitalize())


# ---- the todo skill's reading -----------------------------------------------------

def todo_lib():
    """The todo skill's script, whose reading of a Todo.md is the only one."""
    src = HERE.parent / "skills" / "todo" / "todo.py"
    if not src.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("garrick_briefing_todo", str(src))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:
        return None
    needed = ("classify", "read", "plain", "key", "link_of", "done_on")
    return mod if all(callable(getattr(mod, n, None)) for n in needed) else None


def next_up_lib():
    """next_up.py, for saying a Todo line without the meeting in it, as the band says it."""
    src = HERE / "next_up.py"
    try:
        spec = importlib.util.spec_from_file_location("garrick_briefing_next_up", str(src))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:
        return None
    return mod if callable(getattr(mod, "said", None)) and callable(getattr(mod, "meeting_names", None)) else None


# ---- git --------------------------------------------------------------------------

def git(repo: Path, *args: str) -> Optional[str]:
    """git's output in `repo`, or None where there is no git or it failed."""
    if not (repo / ".git").exists():
        return None
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60,
                              env=gl.foreign_git_env())
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def stamp(day: datetime.date) -> str:
    return "%s 00:00:00" % day.isoformat()


def commits(repo: Path, rel: str, since: datetime.date) -> Optional[List[dict]]:
    out = git(repo, "log", "--since=" + stamp(since), "--name-only",
              "--format=" + SEP + FIELD.join(("%H", "%h", "%aI", "%an", "%s", "%b")) + FIELD, "--", rel)
    if out is None:
        return None
    found = []
    for chunk in out.split(SEP)[1:]:
        parts = chunk.split(FIELD)
        if len(parts) < 7:
            continue
        files = [f for f in parts[6].splitlines() if f.strip()]
        found.append({"hash": parts[0], "short": parts[1], "when": parts[2], "author": parts[3],
                      "subject": parts[4], "body": parts[5].strip(), "files": files})
    return found


def uncommitted(repo: Path, rel: str) -> List[str]:
    out = git(repo, "status", "--porcelain", "--untracked-files=all", "--", rel)
    return [line[3:] for line in (out or "").splitlines() if len(line) > 3]


def before(repo: Path, rel: str, since: datetime.date) -> Tuple[Optional[str], bool]:
    """(the file as it stood when the period began, whether history could
    tell). None with True: the file did not exist then."""
    head = git(repo, "rev-parse", "--verify", "-q", "HEAD")
    if head is None:
        return None, False
    when = git(repo, "log", "-1", "--before=" + stamp(since), "--format=%H", "--", rel)
    if when is None:
        return None, False
    if not when.strip():
        return None, True
    text = git(repo, "show", "%s:%s" % (when.strip(), rel))
    return text, text is not None


# ---- a note ------------------------------------------------------------------------

def as_date(text: str) -> Optional[datetime.date]:
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        pass
    parts = text.split()
    if len(parts) == 3 and parts[1].lower() in MONTHS:
        try:
            return datetime.date(int(parts[2]), MONTHS.index(parts[1].lower()) + 1, int(parts[0]))
        except ValueError:
            return None
    return None


def entries(text: str) -> List[dict]:
    """The dated entries under the rule below Resume here, newest first as
    written: each opens with `**27 September 2026.**` and runs to the next."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == gl.RESUME_HEADING.lower()), -1)
    if start < 0:
        return []
    rule = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == "---"), -1)
    if rule < 0:
        return []
    out: List[dict] = []
    for line in lines[rule + 1:]:
        if re.match(r"^#{1,2} ", line):
            break
        m = DATED.match(line.strip())
        if m:
            day = as_date(m.group(1))
            out.append({"date": day.isoformat() if day else None, "said": m.group(1), "text": line.strip()})
        elif out:
            out[-1]["text"] = (out[-1]["text"] + "\n" + line).rstrip()
    for e in out:
        e["text"] = e["text"].strip()
    return out


def resume(text: Optional[str]) -> Optional[dict]:
    if text is None:
        return None
    lines = gl.resume_lines(text)
    if not lines:
        return None
    rows = {}
    for line in lines:
        m = ROW.match(line.strip())
        if m and m.group(1).strip() and not set(m.group(1).strip()) <= set("-: "):
            rows[m.group(1).strip()] = m.group(2).strip()
    body = "\n".join(l.rstrip() for l in lines).strip()
    return {"text": body, "rows": rows}


def checkpoint(text: str) -> Optional[dict]:
    block = gl.read_checkpoint(text)
    if block is None:
        return None
    return {"at": block["at"], "valid": block["valid"], "why": block["why"] or None,
            "stale": bool(block["base"]) and block["base"] != gl.resume_hash(text),
            "items": [{"kind": i["kind"], "text": i["text"]} for i in block["items"]]}


def meeting_links(text: str, names: set) -> List[str]:
    """The meeting pages a note links, by the link it gives, and nothing else of them."""
    out: List[str] = []
    for m in WIKILINK.finditer(text):
        target = m.group(1).strip()
        if "meetings/" in target.casefold() or target.rsplit("/", 1)[-1].casefold() in names:
            out.append(target)
    for m in MDLINK.finditer(text):
        if "/meetings/" in "/" + m.group(2).casefold():
            out.append(m.group(2))
    seen, kept = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            kept.append(t)
    return kept


# ---- the threads of a zone ----------------------------------------------------------

def visible(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def notes(zone: Path) -> List[dict]:
    """Every thread in a zone: a thread note, or a project with no thread
    note, whose hub is its thread. A parked project parks its threads."""
    out = []
    for project in visible(zone):
        if project.name in SKIP:
            continue
        hub = project / (project.name + ".md")
        hub_state = str(gl.parse_frontmatter(hub).get("status") or "").strip().lower() if hub.is_file() else ""
        found = [(t.name, t / (t.name + ".md")) for t in visible(project / "Threads")]
        found = [(name, note) for name, note in found if note.is_file()]
        if not found and hub.is_file():
            out.append({"project": project.name, "thread": None, "note": hub, "folder": project, "status": hub_state})
        for name, note in found:
            state = str(gl.parse_frontmatter(note).get("status") or "").strip().lower()
            out.append({"project": project.name, "thread": name, "note": note, "folder": note.parent,
                        "status": PARKED if hub_state == PARKED and state != DONE else state})
    return out


def wanted(row: dict, projects: List[str], threads: List[str]) -> Tuple[bool, bool]:
    """(in scope, named directly). Nothing named: the whole zone is in scope."""
    p, t = row["project"].casefold(), (row["thread"] or row["project"]).casefold()
    direct = any(n == t or n == "%s/%s" % (p, t) for n in threads)
    in_project = p in projects
    if not projects and not threads:
        return True, False
    return direct or in_project, direct


# ---- one thread ---------------------------------------------------------------------

def todo_lines(todo, nu, zone: Path, since: datetime.date, today: datetime.date, base: Optional[str],
               known: bool, meetings: set) -> Dict[str, List[Tuple[str, dict]]]:
    """Every task line of the zone that opens with a link, keyed by that
    link, each said and split into added, ticked and open."""
    out: Dict[str, Dict[str, List[dict]]] = {}
    if todo is None or not (zone / "Todo.md").is_file():
        return out
    try:
        lines = todo.read(zone)
    except OSError:
        return out
    states = todo.classify(lines, today)
    late = {line: n for n, line in states["overdue"]}
    due, chase = set(states["due"]), set(states["chase"])
    then = {gl.same_action(l) for l in (base or "").split("\n") if l.startswith(("- [ ] ", "- [x] "))}
    archived: List[str] = []
    for year in range(since.year, today.year + 1):
        path = zone / "archive" / ("Todo-%d.md" % year)
        try:
            archived += path.read_text(encoding="utf-8").split("\n")
        except OSError:
            pass

    def said(line):
        return nu.said(todo, line, meetings) if nu is not None else todo.plain(line)

    def put(line, kind, extra):
        link = todo.link_of(line)
        if not link or "<action>" in line:
            return
        item = {"said": said(line), "key": todo.key(line)}
        item.update(extra)
        out.setdefault(link, {"added": [], "ticked": [], "open": []})[kind].append(item)

    seen = set()
    for line in lines + archived:
        if line.startswith("- [x] "):
            day = todo.done_on(line)
            if day and since <= day <= today and line not in seen:
                seen.add(line)
                put(line, "ticked", {"done": day.isoformat()})
        elif line.startswith("- [ ] ") and line in lines and line not in seen:
            seen.add(line)
            state = ("overdue" if line in late else "due" if line in due else "chase" if line in chase else None)
            extra = {"state": state}
            if line in late:
                extra["late"] = late[line]
            m = re.search(r"(?:📅|📆|🗓)️? *(\d{4}-\d\d-\d\d)", line)
            if m:
                extra["due"] = m.group(1)
            made = re.search(r"➕️? *(\d{4}-\d\d-\d\d)", line)
            new = (known and gl.same_action(line) not in then) or bool(made and made.group(1) >= since.isoformat())
            put(line, "added" if new else "open", extra)
    return out


def lines_for(found: Dict[str, Dict[str, List[dict]]], row: dict, root_zone: Path, shared: bool) -> Dict[str, List[dict]]:
    """A thread's lines: those whose link is its note's path, or its name.
    Where another thread of the zone has the same name, a line linked by the
    name alone could be either one's: it is listed with `"either": true`, for
    the briefing to say so rather than guess."""
    name = (row["thread"] or row["project"]).casefold()
    rel = row["note"].relative_to(root_zone).as_posix()[:-3].casefold()
    out: Dict[str, List[dict]] = {"added": [], "ticked": [], "open": []}
    for link, kinds in found.items():
        l = link.casefold()
        by_path = "/" in l and (l == rel or rel.endswith("/" + l))
        if not (by_path or l == name):
            continue
        for k in out:
            out[k] += [dict(item, either=True) if shared and not by_path else item for item in kinds[k]]
    return out


def thread(root: Path, zone: Path, row: dict, since: datetime.date, today: datetime.date,
           found: Dict[str, Dict[str, List[dict]]], meetings: set, named: bool, shared: bool = False) -> dict:
    rel_folder = row["folder"].relative_to(zone).as_posix()
    rel_note = row["note"].relative_to(zone).as_posix()
    try:
        text = row["note"].read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    history = commits(zone, rel_folder, since)
    then, known = before(zone, rel_note, since)
    now_block, then_block = resume(text), resume(then)
    now_entries = entries(text)
    if known:
        old = {e["text"] for e in entries(then or "")}
        added = [e for e in now_entries if e["text"] not in old]
    else:
        added = [e for e in now_entries if e["date"] and e["date"] >= since.isoformat()]
    cp = checkpoint(text)
    todo = lines_for(found, row, zone, shared)
    dirty = uncommitted(zone, rel_folder)
    times = ([c["when"][:10] for c in history or []] + [t["done"] for t in todo["ticked"]]
             + [e["date"] for e in added if e["date"]] + ([today.isoformat()] if dirty else []))
    if cp and cp["at"]:
        times.append(str(cp["at"])[:10])
    cp_new = bool(cp and cp["at"] and str(cp["at"])[:10] >= since.isoformat())
    changed = bool(history or added or todo["added"] or todo["ticked"] or dirty or cp_new)
    resumed = None
    if now_block is not None:
        resumed = {"now": now_block["text"], "rows": now_block["rows"],
                   "changed": bool(known and (then_block or {}).get("text") != now_block["text"])}
        if resumed["changed"] and then_block is not None:
            resumed["before"] = then_block["text"]
        if not known:
            resumed["changed"] = None                       # no history to tell
    return {"zone": zone.name, "project": row["project"], "thread": row["thread"],
            "note": row["note"].relative_to(root).as_posix(), "status": row["status"] or "active",
            "named": named, "changed": changed, "last": max(times) if times else None,
            "history": history is not None, "commits": history or [], "uncommitted": dirty,
            "resume": resumed, "entries": added, "checkpoint": cp, "todo": todo,
            "meetings": meeting_links(text, meetings)}


# ---- the whole --------------------------------------------------------------------------

def zones_of(root: Path, given: List[str]) -> List[Path]:
    """The zones named, by folder, any case. With none named, the one zone
    there is; more than one, and the caller must say which."""
    present = visible(root / "Zones")
    if not given:
        if len(present) == 1:
            return present
        raise ValueError("name a zone: %s" % ", ".join(z.name for z in present) if present else "this workspace has no zone")
    out = []
    for name in given:
        hit = [z for z in present if z.name.casefold() == name.strip().casefold()]
        if not hit:
            raise ValueError("no zone called %s; the zones are %s" % (name, ", ".join(z.name for z in present)))
        if hit[0] not in out:
            out.append(hit[0])
    return out


def gather(root: Path, zones: Optional[List[str]] = None, since: Optional[datetime.date] = None,
           days: Optional[int] = None, named_period: Optional[str] = None, projects: Optional[List[str]] = None,
           threads: Optional[List[str]] = None, today: Optional[datetime.date] = None) -> dict:
    """Everything a briefing rests on, as one dict. Raises ValueError for a
    zone, a period or a name that does not read."""
    root = Path(root).resolve()
    today = today or datetime.date.today()
    if days is not None and not DAYS[0] <= days <= DAYS[1]:
        raise ValueError("--days is a whole number from %d to %d" % DAYS)
    if named_period is not None and named_period not in PERIOD_KEYS:
        raise ValueError("no period called %s; it is one of %s" % (named_period, ", ".join(PERIOD_KEYS)))
    chosen = settings(root)
    first, how = period(today, since, days, named_period, chosen["period"])
    places = zones_of(root, list(zones or []))
    want_p = [p.strip().casefold() for p in projects or [] if p.strip()]
    want_t = [re.sub(r"\s*[,/]\s*", "/", t.strip()).casefold() for t in threads or [] if t.strip()]
    todo, nu = todo_lib(), next_up_lib()
    meetings = nu.meeting_names(root) if nu is not None else set()
    listed, quiet, parked_out, matched = [], [], 0, set()
    for zone in places:
        rows = notes(zone)
        base, known = before(zone, "Todo.md", since=first)
        found = todo_lines(todo, nu, zone, first, today, base, known, meetings)
        names = [(r["thread"] or r["project"]).casefold() for r in rows]
        for row in rows:
            scope, direct = wanted(row, want_p, want_t)
            if not scope:
                continue
            p, t = row["project"].casefold(), (row["thread"] or row["project"]).casefold()
            matched.update(n for n in want_t if n in (t, "%s/%s" % (p, t)))
            if p in want_p:
                matched.add(p)
            named = direct or p in want_p
            if row["status"] == PARKED and not named:
                parked_out += 1
                continue
            got = thread(root, zone, row, first, today, found, meetings, direct,
                         names.count((row["thread"] or row["project"]).casefold()) > 1)
            if got["changed"] or direct:
                if row["status"] == DONE and not got["changed"]:
                    continue
                listed.append(got)
            elif row["status"] not in (DONE, PARKED):
                quiet.append({"zone": zone.name, "project": row["project"], "thread": row["thread"],
                              "note": got["note"]})
    listed.sort(key=lambda r: (r["last"] or "", r["zone"], r["project"], r["thread"] or ""), reverse=True)
    listed.sort(key=lambda r: r["last"] is None)            # those that did not change, named, last
    unmatched = [n for n in want_p + want_t if n not in matched]
    return {"zones": [z.name for z in places], "today": today.isoformat(),
            "period": {"since": first.isoformat(), "said": "since " + said_day(first, today), "given": how,
                       "default": chosen["period"]},
            "named": {"projects": projects or [], "threads": threads or []}, "unmatched": unmatched,
            "guidance": [g for g in GUIDANCE if (root / g).is_file()],
            "threads": listed, "quiet": quiet, "parked_left_out": parked_out}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="What changed in a zone's threads over a period, as JSON.")
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    ap.add_argument("--zone", action="append", default=[], help="the zone; repeat it for more")
    ap.add_argument("--project", action="append", default=[], help="only this project; repeat it for more")
    ap.add_argument("--thread", action="append", default=[], help="only this thread, Pricing or Acme/Pricing")
    when = ap.add_mutually_exclusive_group()
    when.add_argument("--since", help="YYYY-MM-DD, the first day the period covers")
    when.add_argument("--days", type=int, help="the last N days; 1 is since yesterday")
    when.add_argument("--period", choices=PERIOD_KEYS, help="a period by name; week is since Monday")
    ap.add_argument("--today", help="YYYY-MM-DD, for tests")
    a = ap.parse_args(argv)
    root = Path(a.root).expanduser().resolve() if a.root else HERE.parents[1]
    if not (root / "System" / "rules.md").is_file():
        print("briefing: %s is not a Garrick workspace" % root, file=sys.stderr)
        return EXIT_USAGE
    try:
        today = datetime.date.fromisoformat(a.today) if a.today else None
        since = datetime.date.fromisoformat(a.since) if a.since else None
        found = gather(root, a.zone, since, a.days, a.period, a.project, a.thread, today)
    except ValueError as e:
        print("briefing: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    print(json.dumps(found, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
