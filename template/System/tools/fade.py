#!/usr/bin/env python3
"""Graded oblivion: old meetings and reading fade out of working memory, by
age, kind and use, into pages that stay where a search can still find them.
Nothing is deleted, and nothing moves without a yes.

    python3 System/tools/fade.py propose [--wiki Meetings] [--leave PATH]... [--only PATH]... [--json | --ear]
    python3 System/tools/fade.py apply --wiki Meetings --id ID [--json | --ear]
    python3 System/tools/fade.py keep --page PATH [--json | --ear]
    python3 System/tools/fade.py counts [--json | --ear]
    python3 System/tools/fade.py list --wiki Meetings [--grade dormant|archived] [--json]
    python3 System/tools/fade.py settings
    python3 System/tools/fade.py filters

**Three grades**, each a place inside its wiki, `Wikis/<Wiki>/`:

- *working*: `wiki/...`, its raw record in `raw/...`, listed in
  `wiki/index.md`. Every routing, briefing and search reads it.
- *dormant*: `dormant/wiki/<same path>`, its raw record in `dormant/raw/...`,
  out of `index.md` and listed in `wiki/index-dormant.md`, one line each with
  its date, the day it went dormant and why. A search reaches it when the
  setting says so, and says it did.
- *archived*: `archive/wiki/...` and `archive/raw/...`, in no index. Read
  only when asked. Pages put there by hand are left as they are.

**What decides the grade**, for a page whose `type` or domain belongs to a
kind in the settings: its age, from when the conversation happened (`date:`)
or the material came out (`published:`), or else the date its file name
starts with, and never from the file's own time, so a re-ingest does not
make a page young. A date that gives only a month or a year counts from the
end of it, so nothing fades early. Person, entity and concept pages, the
lists and the lint reports never move; a person or entity page keeps an
`## Earlier` section listing what faded, which the assistant opens with two
lines of its own.

**Pinned** pages never fade: linked from the note of a live thread, from
the notes of a live project, from an open line in a zone's `Todo.md`, or
carrying `pinned: true`. Each pin can be switched off. A page carrying
`superseded:` is kept out of working memory whatever pins it, and never
wakes by use. A dormant page **wakes** when a live thread, a live project or
an open action links it, or a working page links it again (a link written
afresh, without the `dormant/` the fade wrote into it), or it carries
`pinned: true`. An archived page wakes only on `pinned: true`, which "keep
X" writes. Pages that share one raw record move together or not at all.

**Code proposes; the user decides.** `propose` writes the list of what
would go dormant, be archived or wake, and why, grouped, to
`System/generated/fade/<Wiki>.md`, with the derived copies of each page:
the pages that go with it, the notes and ticked actions whose links are
pointed at its new path, those that stay as written, and the person and
entity pages that list it under `## Earlier`. Nothing moves. `apply` takes
the proposal by its id and moves only what that written proposal listed and
still qualifies now, so a retention rule changed since can only make it
move less. On a wiki that has never been faded (no `wiki/index-dormant.md`
yet), `propose` does not print the id: it is only in the written proposal,
so the first fade cannot propose and apply from one command's output. With
nobody watching (GARRICK_HEADLESS=1) `apply` and `keep` are refused.

**Every grade change is a move**, file by file, never an edit: the page and
its raw record are renamed, content unchanged, and every link into them,
from both wikis and every zone's notes, is rewritten to the new path, so
nothing breaks. A link spelt with a path keeps its spelling around the
grade's folder; a bare name gains the path, and keeps what it showed as its
alias. A page that moves is never edited in the same commit; a link that
could mean two notes is left as written. A file another session has
changes in holds every move whose links it carries. One commit per
repository, of the files the fade changed and nothing else; the wikis'
first, and a refused one puts everything back. Where a vault's `.obsidian/`
holds a wiki, `dormant/` and `archive/` join its excluded files, so they
leave the graph and the default search too.

**Settings** are `"memory"` in `System/garrick-settings.json`, merged over
DEFAULTS by `settings()`. The judgment the numbers cannot hold is in
`System/retention.md`, and `retention.local.md` beside it wins: the `nurture`
skill reads both when it proposes, and leaves a page out with `--leave`.

Importable with no side effects: `settings(root)`, `counts(root, memory)`
(what each grade holds now and how many would move, with `memory` laid over
the stored settings, fast enough for a status page build: no git call),
`plan()`, `propose()`, `apply()` and `keep()`.

Exit codes: 0; 1 when a proposal or a commit was refused; 2 for a usage
error or no workspace.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from garrick_lib import (  # noqa: E402
    foreign_git_env,
    knowledge_schema,
    load_context,
    parse_frontmatter_text,
    read_settings,
    strip_tag,
    workspace_root,
)

WIKIS = ("Meetings", "Knowledge")
GRADES = ("working", "dormant", "archived")
FOLDER = {"working": "", "dormant": "dormant", "archived": "archive"}
GRADE_FOLDERS = ("dormant", "archive")
SPOKEN_WIKI = {"Meetings": "the meetings", "Knowledge": "the library"}
PAGE_WORD = {"Meetings": "meeting page", "Knowledge": "library page"}
LISTS = ("index.md", "log.md", "index-dormant.md")
DORMANT_INDEX = "index-dormant.md"
FIXED_FOLDERS = ("people", "entities", "concepts")
FIXED_TYPES = ("person", "entity", "concept")
MAIL_EXTS = (".eml", ".msg", ".mbox")
PROPOSALS = ("System", "generated", "fade")
RETENTION = "System/retention.md"
RETENTION_LOCAL = "System/retention.local.md"
SETTINGS_KEY = "memory"
EXIT_REFUSED = 1
EXIT_USAGE = 2

# What ships. A kind is which pages of a wiki fade at one pace: by `type`, or
# by a domain (a page's own `domain:`, the folder its raw record is kept in
# under raw/, or `mail` for reading that came by mail). Months to dormant and
# to archived; null for never. A workspace adds its own, or changes these, in
# its settings; a kind set to null there is taken out.
DEFAULTS = {
    "wikis": {"Meetings": True, "Knowledge": True},
    "kinds": {
        "meetings": {"wiki": "Meetings", "types": ["meeting", "email"], "domains": [],
                     "dormant": 6, "archived": 18},
        "newsletters": {"wiki": "Knowledge", "types": ["newsletter", "article"],
                        "domains": ["mail", "newsletter", "newsletters", "article", "articles"],
                        "dormant": 3, "archived": 12},
        "reports": {"wiki": "Knowledge", "types": ["source", "report", "standard", "paper"],
                    "domains": ["report", "reports", "standard", "standards", "paper", "papers"],
                    "dormant": 24, "archived": None},
    },
    "pins": {"thread": True, "project": True, "todo": True, "pinned": True},
    "wake": True,
    "reach": "dormant",
    "nightly": {"on": True, "min": 10},
}
REACH = ("working", "dormant")

LINK = re.compile(r"(!?\[\[)([^\[\]|#\n]+)((?:#[^\[\]|\n]*)?)((?:\|[^\[\]\n]*)?)(\]\])")
OBSIDIAN = re.compile(r"(obsidian://open\?(?:[^\s)&]*&)*?file=)([^&\s)#]+)")
OPEN_LINE = re.compile(r"^\s*[-*+] \[ \]")
DONE_WORDS = ("done", "closed", "complete", "completed", "finished")
PARKED_WORDS = ("parked", "paused", "pause", "on-hold", "on hold", "onhold", "hold", "dormant", "suspended",
                "deferred")
NOT_LIVE = re.compile(r"^(?:archive|build|render.*|specs|\..*|_.*)$", re.I)
SKIP = {".git", "node_modules", ".venv", "__pycache__", "dist", ".obsidian", ".trash"}


class Refused(Exception):
    """A refusal, worded for whoever runs the tool."""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _months(value) -> Tuple[bool, Optional[int]]:
    """(whether it reads, the months): a whole number of months, or None for never."""
    if value is None:
        return True, None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value != int(value):
        return False, None
    return True, int(value)


def merged(over, base: Optional[dict] = None) -> dict:
    """`over` laid on `base` (DEFAULTS when none), key by key. Anything that
    does not read keeps the value beneath it, so a hand-edited file never
    empties a setting."""
    out = copy.deepcopy(base if base is not None else DEFAULTS)
    if not isinstance(over, dict):
        return out
    for key in ("wikis", "pins"):
        given = over.get(key)
        if isinstance(given, dict):
            for k, v in given.items():
                if k in out[key] and isinstance(v, bool):
                    out[key][k] = v
    kinds = over.get("kinds")
    if isinstance(kinds, dict):
        for name, spec in kinds.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if spec is None:
                out["kinds"].pop(name, None)
                continue
            if not isinstance(spec, dict):
                continue
            kind = dict(out["kinds"].get(name) or {"wiki": "", "types": [], "domains": [], "dormant": None,
                                                   "archived": None})
            if spec.get("wiki") in WIKIS:
                kind["wiki"] = spec["wiki"]
            for k in ("types", "domains"):
                if isinstance(spec.get(k), list) and all(isinstance(x, str) for x in spec[k]):
                    kind[k] = [x.strip().lower() for x in spec[k] if x.strip()]
            for k in ("dormant", "archived"):
                if k in spec:
                    ok, months = _months(spec[k])
                    if ok:
                        kind[k] = months
            if kind["wiki"] in WIKIS:
                out["kinds"][name] = kind
    if isinstance(over.get("wake"), bool):
        out["wake"] = over["wake"]
    if over.get("reach") in REACH:
        out["reach"] = over["reach"]
    nightly = over.get("nightly")
    if isinstance(nightly, dict):
        if isinstance(nightly.get("on"), bool):
            out["nightly"]["on"] = nightly["on"]
        ok, n = _months(nightly.get("min", out["nightly"]["min"]))
        if ok and n is not None:
            out["nightly"]["min"] = n
    return out


def settings(root: Path) -> dict:
    """The stored `"memory"` settings merged over the defaults."""
    return merged(read_settings(root).get(SETTINGS_KEY))


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def _last_day(year: int, month: int) -> datetime.date:
    nxt = datetime.date(year + (month == 12), month % 12 + 1, 1)
    return nxt - datetime.timedelta(days=1)


def read_date(value) -> Optional[datetime.date]:
    """A frontmatter date: YYYY-MM-DD, or YYYY-MM or YYYY, counted from the
    end of the month or year it names."""
    s = str(value or "").strip().strip("\"'")
    m = re.match(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?(?:$|[T ])", s)
    if not m:
        return None
    try:
        year, month = int(m.group(1)), int(m.group(2)) if m.group(2) else 12
        return datetime.date(year, month, int(m.group(3))) if m.group(3) else _last_day(year, month)
    except ValueError:
        return None


def name_date(name: str) -> Optional[datetime.date]:
    """The date a file's name starts with: YYMMDD- or YYYY-MM-DD."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", name)
    if m:
        return read_date(m.group(1))
    m = re.match(r"^(\d{2})(\d{2})(\d{2})(?:[^\d]|$)", name)
    if m:
        try:
            return datetime.date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def months_since(d: datetime.date, today: datetime.date) -> int:
    n = (today.year - d.year) * 12 + today.month - d.month
    return n - 1 if today.day < d.day else n


# ---------------------------------------------------------------------------
# The pages
# ---------------------------------------------------------------------------

@dataclass
class Page:
    path: str                       # from the workspace's top
    wiki: str
    grade: str
    sub: str                        # below its grade's folder: wiki/sources/x.md
    title: str = ""
    type: str = ""
    date: Optional[datetime.date] = None
    kind: str = ""
    fixed: bool = False             # a person, entity or concept page: never moves
    pinned: bool = False            # `pinned: true`
    superseded: str = ""
    raw: str = ""                   # its raw record, from the workspace's top
    raw_grade: str = ""
    raw_sub: str = ""               # raw/...
    parties: List[str] = field(default_factory=list)
    party: str = ""
    domains: List[str] = field(default_factory=list)
    updated: str = ""
    source: bool = False            # Knowledge: of the source type the wiki's schema names


def wiki_top(root: Path, wiki: str) -> Path:
    return root / "Wikis" / wiki


def place(wiki: str, grade: str, sub: str) -> str:
    """A path from the workspace's top, for `sub` at `grade`."""
    return "/".join(p for p in ("Wikis", wiki, FOLDER[grade], sub) if p)


def walk(folder: Path, md_only: bool = True) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(str(folder)):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP and not d.startswith("."))
        for name in sorted(filenames):
            if not md_only or name.lower().endswith(".md"):
                yield Path(dirpath) / name


def link_target(value) -> str:
    """What a frontmatter link names: `"[[raw/x|y]]"` -> raw/x."""
    s = str(value or "").strip().strip("\"'").strip()
    if s.startswith("[[") and s.endswith("]]"):
        s = s[2:-2]
    return re.split(r"[|#]", s, 1)[0].strip().rstrip("\\").strip()


def tags(value) -> List[str]:
    values = value if isinstance(value, list) else [value] if value else []
    return [strip_tag(str(v)) for v in values if str(v).strip()]


def scan_wiki(root: Path, wiki: str, texts: Optional[Dict[str, str]] = None) -> List[Page]:
    """Every page of a wiki, at each grade, but the lists and the lint
    reports. `texts`, when given, keeps what was read, so the link scan reads
    no page twice."""
    top = wiki_top(root, wiki)
    source_type = knowledge_schema(root)[0]["source"]["type"] if wiki == "Knowledge" else ""
    pages = []
    for grade in GRADES:
        base = top / FOLDER[grade] if FOLDER[grade] else top
        folder = base / "wiki"
        if not folder.is_dir():
            continue
        for path in walk(folder):
            sub = path.relative_to(base).as_posix()
            inner = sub.split("/")[1:]
            if inner[0] == "lint" or (len(inner) == 1 and inner[0] in LISTS):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if texts is not None:
                texts[place(wiki, grade, sub)] = text
            fm = parse_frontmatter_text(text)
            ptype = str(fm.get("type") or "").strip().lower()
            page = Page(place(wiki, grade, sub), wiki, grade, sub, str(fm.get("title") or path.stem), ptype,
                        updated=str(fm.get("updated") or fm.get("created") or fm.get("date") or ""))
            page.fixed = (len(inner) > 1 and inner[0] in FIXED_FOLDERS) or ptype in FIXED_TYPES
            page.pinned = str(fm.get("pinned") or "").strip().lower() == "true"
            page.superseded = str(fm.get("superseded") or "").strip()
            page.parties = tags(fm.get("parties"))
            page.party = strip_tag(str(fm.get("party") or ""))
            fields = ("date",) if wiki == "Meetings" else ("published", "date")
            page.date = next((d for d in (read_date(fm.get(f)) for f in fields) if d), None) or name_date(path.name)
            if fm.get("raw"):
                find_raw(top, page, link_target(fm.get("raw")))
            doms = tags(fm.get("domain")) + tags(fm.get("domains"))
            if page.raw:
                parts = page.raw_sub.split("/")
                if wiki == "Knowledge" and len(parts) > 2:
                    doms.append(parts[1].lower())
                if Path(page.raw).suffix.lower() in MAIL_EXTS:
                    doms.append("mail")
            page.domains = doms
            page.source = wiki == "Knowledge" and ptype == source_type.lower()
            pages.append(page)
    return pages


def find_raw(top: Path, page: Page, target: str) -> None:
    """The raw record a page names, looked for at the page's own grade first."""
    comps = [c for c in target.split("/") if c not in ("", ".", "..")]
    if "raw" not in [c.lower() for c in comps]:
        return
    comps = comps[[c.lower() for c in comps].index("raw"):]
    if len(comps) < 2 or comps[1].lower() == "inbox":
        return
    for grade in [page.grade] + [g for g in GRADES if g != page.grade]:
        base = top / FOLDER[grade] if FOLDER[grade] else top
        f = base.joinpath(*comps)
        hit = f if f.is_file() else None
        if hit is None and f.parent.is_dir():
            hit = next((x for x in sorted(f.parent.iterdir()) if x.is_file() and x.stem == f.name), None)
        if hit is not None:
            page.raw_grade = grade
            page.raw_sub = hit.relative_to(base).as_posix()
            page.raw = place(page.wiki, grade, page.raw_sub)
            return


def kind_of(page: Page, kinds: dict) -> str:
    """The first kind naming one of the page's domains, else the first naming its type."""
    mine = [(n, k) for n, k in kinds.items() if k.get("wiki") == page.wiki]
    for name, k in mine:
        if set(page.domains) & set(k.get("domains") or []):
            return name
    types = {page.type} | ({"source"} if page.source else set())
    for name, k in mine:
        if types & set(k.get("types") or []):
            return name
    return ""


# ---------------------------------------------------------------------------
# Links: every note a wikilink may land on, and every link into a wiki page
# ---------------------------------------------------------------------------

@dataclass
class Ref:
    src: str              # the note that links, from the workspace's top
    written: str          # the link as written
    where: str            # thread, project, todo, done, working, dormant, archived, list, fixed, note
    alone: bool           # whether the link leads to this page and no other


def clean(written: str) -> List[str]:
    w = urllib.parse.unquote(written.strip()).rstrip("\\").strip()
    return [c for c in w.split("/") if c not in ("", ".", "..")]


class Links:
    """The files a link can land on, as Obsidian finds them: by the end of
    their path, case aside, with `.md` or without."""

    def __init__(self, root: Path):
        self.root = root
        self.by_name: Dict[str, List[Tuple[str, List[str], bool, bool]]] = {}
        self.notes: List[str] = []           # every Markdown note a link may come from
        wikis = root / "Wikis"
        if wikis.is_dir():
            for f in walk(wikis, md_only=False):
                self._add(f)
        zones = root / "Zones"
        if zones.is_dir():
            for zone in sorted(z for z in zones.iterdir() if z.is_dir() and not z.name.startswith((".", "_"))):
                for f in walk(zone):
                    if f.relative_to(zone).parts[0] != "Inbox":
                        self._add(f)

    def _add(self, f: Path) -> None:
        rel = f.relative_to(self.root).as_posix()
        low = rel.lower().split("/")
        if rel.lower().endswith(".md"):
            low[-1] = low[-1][:-3]
            self.by_name.setdefault(low[-1], []).append((rel, low, True, False))
            if "/raw/" not in "/" + rel:
                self.notes.append(rel)
        else:
            self.by_name.setdefault(low[-1], []).append((rel, low, False, False))
            stem = os.path.splitext(low[-1])[0]
            if stem != low[-1]:
                self.by_name.setdefault(stem, []).append((rel, low[:-1] + [stem], False, True))

    def resolve(self, written: str) -> List[str]:
        comps = clean(written)
        if not comps:
            return []
        low = [c.lower() for c in comps]
        md = low[-1].endswith(".md")
        if md:
            low[-1] = low[-1][:-3]
        out = []
        for rel, have, is_md, stem_only in self.by_name.get(low[-1], []):
            if (stem_only and "raw" not in low) or (md and not is_md):
                continue
            if len(have) >= len(low) and have[len(have) - len(low):] == low:
                out.append(rel)
        return sorted(set(out))


def links_in(text: str) -> Iterable[Tuple[int, str]]:
    """(line number, target as written) for every wikilink and obsidian:// link."""
    for n, line in enumerate(text.split("\n")):
        if "[[" in line:
            for m in LINK.finditer(line):
                yield n, m.group(2)
        if "obsidian://" in line:
            for m in OBSIDIAN.finditer(line):
                yield n, urllib.parse.unquote(m.group(2))


def note_status(path: Path) -> str:
    try:
        word = str(parse_frontmatter_text(path.read_text(encoding="utf-8", errors="replace")).get("status") or "")
    except OSError:
        return "active"
    word = word.strip().lower()
    return "done" if word in DONE_WORDS else "parked" if word in PARKED_WORDS else "active"


class Where:
    """What kind of note a path is, for pins and waking: a live thread's, a
    live project's, a zone's Todo list, a wiki page at a grade, or a note."""

    def __init__(self, root: Path, pages: Dict[str, Page]):
        self.root = root
        self.pages = pages
        self._status: Dict[str, str] = {}

    def status(self, rel: str) -> str:
        if rel not in self._status:
            self._status[rel] = note_status(self.root / rel)
        return self._status[rel]

    def of(self, rel: str) -> str:
        parts = rel.split("/")
        if parts[0] == "Wikis" and len(parts) > 2:
            page = self.pages.get(rel)
            if page is not None:
                return "fixed" if page.fixed else page.grade
            return "list"
        if parts[0] != "Zones" or len(parts) < 3:
            return "note"
        if len(parts) == 3:
            return "todo" if parts[2] == "Todo.md" else "note"
        project = "/".join(parts[:3])
        hub = "%s/%s.md" % (project, parts[2])
        if not (self.root / hub).is_file() or any(NOT_LIVE.match(p) for p in parts[3:-1]):
            return "note"
        if self.status(hub) != "active":
            return "note"
        if parts[3] == "Threads" and len(parts) > 5:
            note = "%s/Threads/%s/%s.md" % (project, parts[4], parts[4])
            return "thread" if (self.root / note).is_file() and self.status(note) == "active" else "note"
        return "project"


def scan_links(root: Path, links: Links, pages: Dict[str, Page], where: Where,
               texts: Optional[Dict[str, str]] = None) -> Dict[str, List[Ref]]:
    """{page or raw path: every link into it}, from every note in both wikis
    and every zone, raw records aside."""
    raws = {p.raw for p in pages.values() if p.raw}
    refs: Dict[str, List[Ref]] = {}
    for src in links.notes:
        text = (texts or {}).get(src)
        if text is None:
            try:
                text = (root / src).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        if "[[" not in text and "obsidian://" not in text:
            continue
        kind = where.of(src)
        lines = text.split("\n") if kind == "todo" else None
        for n, written in links_in(text):
            hits = [h for h in links.resolve(written) if h in pages or h in raws]
            if not hits:
                continue
            here = kind
            if lines is not None:
                here = "todo" if OPEN_LINE.match(lines[n]) else "done"
            alone = len(links.resolve(written)) == 1
            for h in hits:
                if h != src:
                    refs.setdefault(h, []).append(Ref(src, written, here, alone))
    return refs


def has_grade(written: str) -> bool:
    return any(c.lower() in GRADE_FOLDERS for c in clean(written))


# ---------------------------------------------------------------------------
# The plan: what would move, and why
# ---------------------------------------------------------------------------

@dataclass
class Move:
    page: Page
    to: str
    why: str
    raw_to: str = ""                     # the raw record's new path, when it moves

    @property
    def new(self) -> str:
        return place(self.page.wiki, self.to, self.page.sub)


class Plans(dict):
    """{wiki: Plan}, and the link scan behind them, `refs`, so the scan runs
    once a run."""

    def __init__(self, refs: Dict[str, List[Ref]]):
        super().__init__()
        self.refs = refs


@dataclass
class Plan:
    wiki: str
    on: bool
    pages: List[Page]
    moves: List[Move] = field(default_factory=list)
    kept: List[Tuple[Page, str]] = field(default_factory=list)       # old enough, but pinned
    together: List[Tuple[Page, str]] = field(default_factory=list)   # shares a record that cannot move as one
    left: List[Page] = field(default_factory=list)                   # left out by judgment
    undated: int = 0
    linked: List[Tuple[Page, List[str]]] = field(default_factory=list)  # superseded, still linked live

    def count(self, grade: str) -> int:
        return sum(1 for p in self.pages if p.grade == grade)

    def going(self, to: str) -> int:
        return sum(1 for m in self.moves if m.to == to)


PIN_WORDS = {"thread": "a live thread", "project": "a live project's notes", "todo": "an open action"}


def pins(page: Page, refs: List[Ref], s: dict) -> List[str]:
    """Why a page is pinned, each in a few words with the note: empty when it is not."""
    out = ["pinned: true"] if s["pins"]["pinned"] and page.pinned else []
    for r in refs:
        if r.where in PIN_WORDS and s["pins"][r.where]:
            out.append("%s, %s" % (PIN_WORDS[r.where], r.src))
    return sorted(set(out), key=out.index)


def plan(root: Path, memory: Optional[dict] = None, today: Optional[datetime.date] = None,
         wikis: Iterable[str] = WIKIS, leave: Iterable[str] = (), only: Iterable[str] = ()) -> Plans:
    """What would move in each wiki now, and why. `memory` is the settings,
    merged already; the stored ones when None. Reads files only."""
    s = memory if memory is not None else settings(root)
    today = today or datetime.date.today()
    wikis = [w for w in wikis if wiki_top(root, w).is_dir()]
    texts: Dict[str, str] = {}
    every = {w: scan_wiki(root, w, texts) for w in WIKIS if wiki_top(root, w).is_dir()}
    pages = {p.path: p for ps in every.values() for p in ps}
    links = Links(root)
    refs = scan_links(root, links, pages, Where(root, pages), texts)
    leave = {normal(root, x) for x in leave}
    only = {normal(root, x) for x in only}
    out = Plans(refs)
    for wiki in wikis:
        p = Plan(wiki, bool(s["wikis"].get(wiki, False)), every[wiki])
        for page in p.pages:
            if page.fixed:
                continue
            page.kind = kind_of(page, s["kinds"])
            move = decide(page, refs.get(page.path, []), s, today, p)
            if move is not None and (not only or page.path in only):
                p.moves.append(move)
        together(p)
        for m in list(p.moves):
            if m.page.path in leave:
                p.moves.remove(m)
                p.left.append(m.page)
        for m in p.moves:
            if m.page.raw and m.page.raw_grade != m.to:
                m.raw_to = place(wiki, m.to, m.page.raw_sub)
        out[wiki] = p
    return out


def normal(root: Path, given: str) -> str:
    """A page named from the workspace's top, from its wiki, or absolute."""
    p = Path(given).expanduser()
    if p.is_absolute():
        try:
            return p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return p.as_posix()
    rel = p.as_posix()
    return rel if rel.startswith("Wikis/") else "Wikis/" + rel


def decide(page: Page, refs: List[Ref], s: dict, today: datetime.date, p: Plan) -> Optional[Move]:
    """The one move a page would make now, or None."""
    woken = wake(page, refs, s)
    if woken is not None:
        return woken
    k = s["kinds"].get(page.kind) if page.kind else None
    months = months_since(page.date, today) if page.date else None
    if k is None:
        return None
    if months is None and not page.superseded:
        p.undated += page.grade == "working"
        return None
    dormant_at, archived_at = k.get("dormant"), k.get("archived")
    archive = archived_at is not None and months is not None and months >= archived_at
    old = "%s old; %s %s" % (plural(months, "month") if months is not None else "undated", page.kind,
                              "are archived at %s" % archived_at if archive else "go dormant at %s" % dormant_at)
    if page.superseded:
        why = "superseded: %s" % page.superseded
        live = sorted({r.src for r in refs if r.where in PIN_WORDS})
        if live:
            p.linked.append((page, live))
        if page.grade == "working":
            return Move(page, "archived" if archive and p.on else "dormant", why) if p.on else None
        if page.grade == "dormant" and archive and p.on:
            return Move(page, "archived", why + "; " + old)
        return None
    if page.grade == "working":
        if not p.on:
            return None
        dormant = dormant_at is not None and months >= dormant_at
        if not (archive or dormant):
            return None
        held = pins(page, refs, s)
        if held:
            p.kept.append((page, "; ".join(held)))
            return None
        return Move(page, "archived" if archive else "dormant", old)
    if page.grade == "dormant" and archive and p.on:
        return Move(page, "archived", old)
    return None


def wake(page: Page, refs: List[Ref], s: dict) -> Optional[Move]:
    """A dormant page linked again, or a page someone said to keep. Never a
    superseded one."""
    if page.superseded or page.grade == "working":
        return None
    if page.pinned:
        return Move(page, "working", "pinned: true")
    if page.grade != "dormant" or not s["wake"]:
        return None
    held = pins(page, refs, s)
    if held:
        return Move(page, "working", "linked again from " + "; ".join(held))
    again = sorted({r.src for r in refs if r.where == "working" and r.alone and not has_grade(r.written)})
    if again:
        return Move(page, "working", "linked again from the working page%s %s" % (
            "s" if len(again) > 1 else "", ", ".join(again)))
    return None


def together(p: Plan) -> None:
    """Pages that share a raw record move together, to one grade, or stay."""
    groups: Dict[str, List[Page]] = {}
    for page in p.pages:
        if page.raw and not page.fixed:
            groups.setdefault(page.raw, []).append(page)
    moving = {m.page.path: m for m in p.moves}
    for raw, group in groups.items():
        if len(group) < 2 or not any(g.path in moving for g in group):
            continue
        targets = {(g.grade, moving[g.path].to if g.path in moving else None) for g in group}
        if len(targets) == 1:
            continue
        for g in group:
            if g.path in moving:
                p.moves.remove(moving[g.path])
                others = ", ".join(x.sub for x in group if x is not g)
                p.together.append((g, "shares its record with %s, which would not move with it" % others))


def counts(root: Path, memory: Optional[dict] = None, today: Optional[datetime.date] = None) -> dict:
    """{wiki: {"on", "working", "dormant", "archived", "to_dormant",
    "to_archive", "to_wake"}}, with `memory` laid over the stored settings."""
    s = merged(memory, settings(root)) if memory is not None else settings(root)
    plans = plan(root, s, today)
    out = {}
    for wiki in WIKIS:
        p = plans.get(wiki)
        if p is None:
            out[wiki] = {"on": bool(s["wikis"].get(wiki)), "working": 0, "dormant": 0, "archived": 0,
                         "to_dormant": 0, "to_archive": 0, "to_wake": 0}
            continue
        out[wiki] = {"on": p.on, "working": p.count("working"), "dormant": p.count("dormant"),
                     "archived": p.count("archived"), "to_dormant": p.going("dormant"),
                     "to_archive": p.going("archived"), "to_wake": p.going("working")}
    return out


def would_say(wiki: str, n: dict) -> str:
    """One sentence, for the morning digest and for the ear: how many would move."""
    word = PAGE_WORD[wiki]
    parts = []
    if n.get("to_dormant"):
        parts.append("%s would go dormant" % plural(n["to_dormant"], word))
    if n.get("to_archive"):
        parts.append(("%d to the archive" % n["to_archive"]) if parts
                     else "%s would go to the archive" % plural(n["to_archive"], word))
    if n.get("to_wake"):
        parts.append(("%d would wake" % n["to_wake"]) if parts else "%s would wake" % plural(n["to_wake"], word))
    if not parts:
        return ""
    said = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
    return "%s. Say \"fade %s\"." % (said[:1].upper() + said[1:], SPOKEN_WIKI[wiki])


def plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


# ---------------------------------------------------------------------------
# Derived copies: what each move does to the notes that link it
# ---------------------------------------------------------------------------

def earlier_hosts(root: Path, move: Move, pages: Dict[str, Page], links: Links,
                  refs: Dict[str, List[Ref]]) -> List[str]:
    """The person and entity pages that list a page fading out of working
    under `## Earlier`: those it links, and, for Knowledge, those that cite
    it. A person page is read on both sides of every wall, so it lists a
    meeting only when every party of the meeting is the person's own."""
    page = move.page
    if page.grade != "working" or move.to == "working":
        return []
    out = set()
    try:
        text = (root / page.path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    linked = [h for _, w in links_in(text) for h in links.resolve(w)]
    if page.wiki == "Knowledge":
        linked += [r.src for r in refs.get(page.path, []) if r.where == "fixed"]
    for h in linked:
        host = pages.get(h)
        if host is None or not host.fixed or host.wiki != page.wiki:
            continue
        if page.wiki == "Meetings":
            if not host.party or host.party == "none" or not page.parties or set(page.parties) != {host.party}:
                continue
        out.add(h)
    return sorted(out)


def copies(root: Path, plans_moves: List[Move], pages: Dict[str, Page], links: Links,
           refs: Dict[str, List[Ref]]) -> Dict[str, dict]:
    """For each move, its derived copies: what goes with it, what is pointed
    at its new path, what stays as written, and where it is listed under
    Earlier."""
    moving = {m.page.path for m in plans_moves}
    out = {}
    for m in plans_moves:
        goes, pointed, stays, done = set(), set(), set(), set()
        for r in refs.get(m.page.path, []) + (refs.get(m.page.raw, []) if m.raw_to else []):
            if r.src == m.page.path:
                continue
            if r.src in moving:
                goes.add(r.src)
            elif r.where == "list" and r.src.endswith(("/wiki/index.md", "/wiki/" + DORMANT_INDEX)):
                continue                       # the lists are rebuilt, not pointed
            elif not r.alone:
                stays.add(r.src)
            elif r.where == "done":
                done.add(r.src)
            else:
                pointed.add(r.src)
        out[m.page.path] = {"goes": sorted(goes), "pointed": sorted(pointed - stays), "stays": sorted(stays),
                            "ticked": sorted(done), "earlier": earlier_hosts(root, m, pages, links, refs)}
    return out


# ---------------------------------------------------------------------------
# The proposal: written, and read before anything moves
# ---------------------------------------------------------------------------

def proposal_paths(root: Path, wiki: str) -> Tuple[Path, Path]:
    folder = root.joinpath(*PROPOSALS)
    return folder / ("%s.md" % wiki), folder / ("%s.json" % wiki)


def first_fade(root: Path, wiki: str) -> bool:
    return not (wiki_top(root, wiki) / "wiki" / DORMANT_INDEX).is_file()


def proposal_id(wiki: str, moves: List[Move], today: datetime.date) -> str:
    key = "\n".join(sorted("%s>%s" % (m.page.path, m.to) for m in moves)) + "\n%s\n%s" % (wiki, today.isoformat())
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


TO_WORDS = {"dormant": "To dormant", "archived": "To the archive", "working": "Waking"}


def render_proposal(p: Plan, pid: str, derived: Dict[str, dict], today: datetime.date, first: bool,
                    s: dict) -> str:
    out = ["# What would fade: %s, %s" % (p.wiki, today.isoformat()), ""]
    n = {"to_dormant": p.going("dormant"), "to_archive": p.going("archived"), "to_wake": p.going("working")}
    said = would_say(p.wiki, n).rsplit(" Say ", 1)[0] if p.moves else "Nothing would move."
    out += ["Nothing has moved. %s Read the list. Where it is wrong, change `%s` or the settings and ask "
            "again, or say which pages to keep." % (said, RETENTION_LOCAL), ""]
    if first:
        out += ["This is the first fade on this wiki, so it only proposes. The yes comes later, once the list "
                "has been read.", ""]
    if not p.on:
        out += ["Fading is switched off for this wiki: only pages someone linked again, or said to keep, "
                "would wake.", ""]
    for to in ("dormant", "archived", "working"):
        mine = [m for m in p.moves if m.to == to]
        if not mine:
            continue
        out += ["## %s, %d" % (TO_WORDS[to], len(mine)), ""]
        for kind in sorted({m.page.kind for m in mine}):
            k = s["kinds"].get(kind, {})
            at = lambda v: "never" if v is None else plural(v, "month")
            out += ["### %s: dormant at %s, archived at %s" % (kind or "no kind", at(k.get("dormant")),
                                                               at(k.get("archived"))), ""]
            for m in sorted((m for m in mine if m.page.kind == kind), key=lambda m: (m.page.date or datetime.date.min,
                                                                                    m.page.path)):
                out.append("- `%s`, %s, %s: %s" % (m.page.sub, m.page.title,
                                                   m.page.date.isoformat() if m.page.date else "undated", m.why))
                d = derived.get(m.page.path, {})
                if m.raw_to:
                    out.append("  - its record `%s` moves with it" % m.page.raw_sub)
                if d.get("goes"):
                    out.append("  - goes with it: %s" % ", ".join("`%s`" % x for x in d["goes"]))
                if d.get("pointed"):
                    out.append("  - pointed at the new path: %s" % ", ".join("`%s`" % x for x in d["pointed"]))
                if d.get("ticked"):
                    out.append("  - ticked actions pointed at the new path: %s" % ", ".join("`%s`" % x for x in d["ticked"]))
                if d.get("stays"):
                    out.append("  - stays as written, since its link could mean another note: %s"
                               % ", ".join("`%s`" % x for x in d["stays"]))
                if d.get("earlier"):
                    out.append("  - listed under Earlier on %s" % ", ".join("`%s`" % x for x in d["earlier"]))
            out.append("")
    if p.linked:
        out += ["## Superseded, and still linked from a live note", "",
                "A link somewhere still points at the old version.", ""]
        out += ["- `%s`: %s. Linked from %s" % (pg.sub, pg.superseded, ", ".join("`%s`" % x for x in live))
                for pg, live in p.linked] + [""]
    if p.kept:
        out += ["## Old enough, but pinned, %d" % len(p.kept), ""]
        out += ["- `%s`: %s" % (pg.sub, why) for pg, why in p.kept] + [""]
    if p.together or p.left:
        out += ["## Left where they are", ""]
        out += ["- `%s`: %s" % (pg.sub, why) for pg, why in p.together]
        out += ["- `%s`: left out by judgment" % pg.sub for pg in p.left] + [""]
    if p.undated:
        out += ["%s no date, so age cannot fade %s." % (
            "One page has" if p.undated == 1 else "%d pages have" % p.undated, "it" if p.undated == 1 else "them"), ""]
    if p.moves:
        out += ["To apply exactly this list, and only what still qualifies then:", "",
                "    python3 System/tools/fade.py apply --wiki %s --id %s" % (p.wiki, pid), ""]
    return "\n".join(out).rstrip() + "\n"


def propose(root: Path, wiki: str, today: Optional[datetime.date] = None, leave: Iterable[str] = (),
            only: Iterable[str] = (), memory: Optional[dict] = None) -> dict:
    """Work out what would move in one wiki, write the proposal, move nothing."""
    today = today or datetime.date.today()
    s = memory if memory is not None else settings(root)
    leave = list(leave)
    plans = plan(root, s, today, [wiki], leave, only)
    refs = plans.refs
    if wiki not in plans:
        raise Refused("There is no %s wiki in this workspace." % wiki)
    p = plans[wiki]
    every = {pg.path: pg for w in WIKIS if wiki_top(root, w).is_dir()
             for pg in (p.pages if w == wiki else scan_wiki(root, w))}
    derived = copies(root, p.moves, every, Links(root), refs)
    pid = proposal_id(wiki, p.moves, today)
    first = first_fade(root, wiki)
    md, js = proposal_paths(root, wiki)
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_proposal(p, pid, derived, today, first, s), encoding="utf-8")
    record = {"id": pid, "wiki": wiki, "date": today.isoformat(), "first": first,
              "leave": [normal(root, x) for x in leave],
              "moves": [{"page": m.page.path, "to": m.to, "why": m.why} for m in p.moves]}
    if p.moves:
        js.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    elif js.exists():
        js.unlink()
    n = {"to_dormant": p.going("dormant"), "to_archive": p.going("archived"), "to_wake": p.going("working")}
    return {"wiki": wiki, "id": None if first else (pid if p.moves else None), "first": first,
            "proposal": md.relative_to(root).as_posix(), "counts": n, "said": would_say(wiki, n),
            "moves": record["moves"], "kept": len(p.kept), "undated": p.undated,
            "linked": [pg.path for pg, _ in p.linked]}


# ---------------------------------------------------------------------------
# Applying: moves, links, lists, one commit per repository
# ---------------------------------------------------------------------------

class Journal:
    """Every change a run makes, so a refused commit puts them all back."""

    def __init__(self):
        self.steps: List[Tuple[str, Path, object]] = []

    def write(self, path: Path, text: str) -> None:
        self.steps.append(("write", path, path.read_bytes() if path.exists() else None))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def move(self, old: Path, new: Path) -> None:
        if new.exists():
            raise Refused("%s is there already" % new)
        new.parent.mkdir(parents=True, exist_ok=True)
        os.rename(str(old), str(new))
        self.steps.append(("move", new, old))

    def rollback(self) -> None:
        while self.steps:
            what, path, before = self.steps.pop()
            if what == "write":
                if before is None:
                    path.unlink()
                else:
                    path.write_bytes(before)
            else:
                os.rename(str(path), str(before))


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=str(repo), capture_output=True, text=True,
                          timeout=300, stdin=subprocess.DEVNULL, env=foreign_git_env())


def repo_of(root: Path, path: Path) -> Optional[Path]:
    d = path if path.is_dir() else path.parent
    while True:
        if os.path.lexists(str(d / ".git")):
            return d
        if d == root or root not in d.parents:
            return None
        d = d.parent


def dirty(repo: Path) -> Optional[Set[str]]:
    """Paths from the repository's top that git reports changed or not
    tracked; None when it is mid-merge or does not read."""
    gitdir = repo / ".git"
    if any((gitdir / m).exists() for m in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD")):
        return None
    r = git(repo, "status", "--porcelain", "-z", "--untracked-files=all")
    if r.returncode != 0:
        return None
    out, parts, i = set(), r.stdout.split("\0"), 0
    while i < len(parts):
        entry = parts[i]
        if len(entry) > 3:
            out.add(entry[3:])
            if entry[0] in "RC":
                i += 1
                out.add(parts[i])
        i += 1
    return out


def tracked(repo: Path, rel: str) -> bool:
    return git(repo, "ls-files", "--error-unmatch", "--", rel).returncode == 0


def respell(written: str, old: str, new: str, here: str) -> Tuple[str, bool]:
    """A link's target, which leads to `old`, written to lead to `new`; and
    whether its shape changed, so that what it shows needs an alias. A link
    spelt with the path keeps its spelling around the grade's folder; a
    shorter one gains the path from its wiki's top, or from the wiki's name
    outside it."""
    back = written.rstrip().endswith("\\")
    comps = clean(written)
    old_c, new_c = old.split("/"), new.split("/")
    old_sub, new_sub = old_c[2:], list(new_c[2:])
    if comps and comps[-1].lower() != old_c[-1].lower():
        new_sub[-1] = os.path.splitext(new_sub[-1])[0]          # written without its extension
    if len(comps) >= len(old_sub):
        out, changed = comps[:len(comps) - len(old_sub)] + new_sub, False
    else:
        inside = here.startswith("/".join(old_c[:2]) + "/")
        out, changed = ([] if inside else [old_c[1]]) + new_sub, True
    return "/".join(out) + ("\\" if back else ""), changed


def still_leads(written: str, new: str) -> bool:
    """Whether a link as written lands on `new` too: the end of its path."""
    low = [c.lower() for c in clean(written)]
    have = new.lower().split("/")
    if low and not low[-1].endswith(".md") and have[-1].endswith(".md"):
        have[-1] = have[-1][:-3]
    if low and low[-1] != have[-1]:
        have[-1] = os.path.splitext(have[-1])[0]
    return bool(low) and have[len(have) - len(low):] == low


def relink(text: str, moved: Dict[str, str], links: Links, here: str) -> str:
    """`text` with every link that leads to a moved file, and to nothing
    else, pointed at where it went. Going dormant or to the archive, every
    such link is written with the grade's folder, so that a link written
    afresh later can be told from it; waking, a link that still lands on the
    page is left as it is."""
    if "[[" not in text and "obsidian://" not in text:
        return text
    lines = text.split("\n")
    for n, line in enumerate(lines):
        table = line.lstrip().startswith("|")

        def one(m):
            hits = links.resolve(m.group(2))
            if len(hits) != 1 or hits[0] not in moved:
                return m.group(0)
            if waking(moved[hits[0]]) and still_leads(m.group(2), moved[hits[0]]):
                return m.group(0)
            target, changed = respell(m.group(2), hits[0], moved[hits[0]], here)
            alias = m.group(4)
            if changed and not alias:
                alias = ("\\|" if table else "|") + m.group(2).strip().rstrip("\\").strip()
            return m.group(1) + target + m.group(3) + alias + m.group(5)

        def url(m):
            written = urllib.parse.unquote(m.group(2))
            hits = links.resolve(written)
            if len(hits) != 1 or hits[0] not in moved:
                return m.group(0)
            if waking(moved[hits[0]]) and still_leads(written, moved[hits[0]]):
                return m.group(0)
            target, _ = respell(written, hits[0], moved[hits[0]], "")
            return m.group(1) + urllib.parse.quote(target)

        if "[[" in line:
            line = LINK.sub(one, line)
        if "obsidian://" in line:
            line = OBSIDIAN.sub(url, line)
        lines[n] = line
    return "\n".join(lines)


def waking(new: str) -> bool:
    """Whether a file's new path is at the working grade."""
    return not any(c in GRADE_FOLDERS for c in new.split("/")[2:3])


def drop_lines(text: str, leaving: Set[str], links: Links) -> str:
    """`text` without the lines that link a page in `leaving`: a list's rows."""
    keep = []
    for line in text.split("\n"):
        hits = {h for _, w in links_in(line) for h in links.resolve(w)}
        if not (hits & leaving):
            keep.append(line)
    return "\n".join(keep)


def index_row(page: Page) -> str:
    target = page.sub[:-3] if page.sub.endswith(".md") else page.sub
    return "| [[%s\\|%s]] | %s | %s |" % (target, page.title.replace("|", "-"), page.type or "page", page.updated)


def add_rows(text: str, woken: List[Page]) -> str:
    """`text`, an index, with a row for each woken page in its table, by its
    Updated date, newest first; a line at the end where it has no table."""
    lines = text.rstrip("\n").split("\n")
    for page in woken:
        row = index_row(page)
        sep = next((i for i, l in enumerate(lines) if re.match(r"^\|\s*:?-{3,}", l.strip())), None)
        if sep is None:
            lines.append("- [[%s|%s]]" % (page.sub[:-3], page.title))
            continue
        at = sep + 1
        while at < len(lines) and lines[at].startswith("|"):
            cells = [c.strip() for c in lines[at].strip().strip("|").split("|")]
            if cells and cells[-1] and cells[-1] < page.updated:
                break
            at += 1
        lines.insert(at, row)
    return "\n".join(lines) + "\n"


DORMANT_HEAD = ("# Dormant\n\nPages that have left the index: still here, and found when a search reaches back. "
                "One line each, newest first: the page, its date, the day it went dormant, and why.\n")


def dormant_line(m: Move, today: datetime.date) -> str:
    target = place(m.page.wiki, "dormant", m.page.sub).split("/", 2)[2][:-3]
    return "- [[%s|%s]] · %s · dormant since %s · %s" % (
        target, m.page.title.replace("|", "-"), m.page.date.isoformat() if m.page.date else "undated",
        today.isoformat(), m.why)


def add_dormant(text: str, entering: List[Move], today: datetime.date) -> str:
    if not entering:
        return text
    lines = (text or DORMANT_HEAD).rstrip("\n").split("\n")
    at = next((i for i, l in enumerate(lines) if l.startswith("- ")), None)
    new = [dormant_line(m, today) for m in sorted(entering, key=lambda m: (m.page.date or datetime.date.min,
                                                                         m.page.path), reverse=True)]
    if at is None:
        lines += [""] + new
    else:
        lines[at:at] = new
    return "\n".join(lines) + "\n"


EARLIER = "## Earlier"


def drop_earlier(text: str, waking: Set[str], links: Links) -> str:
    """A person or entity page without the Earlier lines of pages that wake."""
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip() == EARLIER), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    keep = [l for l in lines[start + 1:end]
            if not (l.lstrip().startswith("- ") and {h for _, w in links_in(l) for h in links.resolve(w)} & waking)]
    return "\n".join(lines[:start + 1] + keep + lines[end:])


def add_earlier(text: str, entries: List[str]) -> str:
    """A person or entity page with a line in `## Earlier` for each page that
    faded, the section made at its end when it has none."""
    if not entries:
        return text
    lines = text.rstrip("\n").split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip() == EARLIER), None)
    if start is None:
        lines += ["", EARLIER, ""] + entries
        return "\n".join(lines) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    have = set(lines[start + 1:end])
    new = [e for e in entries if e not in have]
    if lines[end - 1].strip() and not lines[end - 1].lstrip().startswith("- "):
        new = [""] + new
    lines[end:end] = new
    return "\n".join(lines) + "\n"


def earlier_line(m: Move) -> str:
    target = m.new.split("/", 2)[2][:-3]
    return "- [[%s|%s]], %s" % (target, m.page.title.replace("|", "-"),
                                m.page.date.isoformat() if m.page.date else "undated")


def vaults(root: Path, wiki: str) -> List[Tuple[Path, str]]:
    """(vault folder, the wiki's path inside it) for each Obsidian vault that
    holds the wiki: the workspace, Wikis/, or the wiki itself."""
    out = []
    for folder, inside in ((root, "Wikis/%s/" % wiki), (root / "Wikis", "%s/" % wiki), (wiki_top(root, wiki), "")):
        if (folder / ".obsidian").is_dir():
            out.append((folder, inside))
    return out


def ignore_filters(root: Path, wiki: str) -> Dict[Path, str]:
    """{app.json: its new text} for each vault holding the wiki whose
    excluded files lack the wiki's dormant/ and archive/ folders. Filters
    the user set stay as they are, in their order."""
    out = {}
    for folder, inside in vaults(root, wiki):
        app = folder / ".obsidian" / "app.json"
        try:
            data = json.loads(app.read_text(encoding="utf-8")) if app.exists() else {}
        except (OSError, ValueError):
            continue                          # a file that does not read is the user's to fix, never overwritten
        if not isinstance(data, dict):
            continue
        have = data.get("userIgnoreFilters")
        have = list(have) if isinstance(have, list) else []
        want = [inside + f + "/" for f in GRADE_FOLDERS]
        missing = [w for w in want if w not in have]
        if missing:
            data["userIgnoreFilters"] = have + missing
            out[app] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return out


def read_proposal(root: Path, wiki: str) -> Optional[dict]:
    try:
        data = json.loads(proposal_paths(root, wiki)[1].read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def apply(root: Path, wiki: str, pid: str, today: Optional[datetime.date] = None) -> dict:
    """Apply the written proposal `pid`: only what it listed and still
    qualifies. One commit per repository, the wikis' first."""
    if os.environ.get("GARRICK_HEADLESS") == "1":
        raise Refused("A fade waits for a person's yes; it never runs with nobody watching.")
    today = today or datetime.date.today()
    record = read_proposal(root, wiki)
    if record is None or record.get("wiki") != wiki:
        raise Refused("There is no written proposal for %s. Say \"fade %s\" first, and read it."
                      % (wiki, SPOKEN_WIKI[wiki]))
    if str(record.get("id")) != str(pid):
        raise Refused("That is not the proposal written for %s; read the one there now." % wiki)
    s = settings(root)
    listed = {(e.get("page"), e.get("to")) for e in record.get("moves", [])}
    plans = plan(root, s, today, [wiki], record.get("leave", []))
    if wiki not in plans:
        raise Refused("There is no %s wiki in this workspace." % wiki)
    refs = plans.refs
    p = plans[wiki]
    moves = [m for m in p.moves if (m.page.path, m.to) in listed]
    now = {(m.page.path, m.to) for m in moves}
    gone = sorted(path for path, to in listed if (path, to) not in now)
    every = {pg.path: pg for w in WIKIS if wiki_top(root, w).is_dir()
             for pg in (p.pages if w == wiki else scan_wiki(root, w))}
    links = Links(root)
    wikis_repo = repo_of(root, wiki_top(root, wiki))
    if wikis_repo is None:
        raise Refused("No repository holds the %s wiki, so a move could not be undone." % wiki)
    states: Dict[Path, Optional[Set[str]]] = {}

    def state(repo: Path) -> Optional[Set[str]]:
        if repo not in states:
            states[repo] = dirty(repo)
        return states[repo]

    def busy(path: Path) -> str:
        repo = repo_of(root, path)
        if repo is None:
            return "no repository holds it"
        st = state(repo)
        if st is None:
            return "its repository is mid-merge or could not be read"
        rel = path.relative_to(repo).as_posix()
        if rel in st or (path.exists() and not tracked(repo, rel)):
            return "%s has changes not committed, or is not committed at all" % path.name
        return ""

    held: List[Tuple[Move, str]] = []
    for name in ("index.md", DORMANT_INDEX):
        f = wiki_top(root, wiki) / "wiki" / name
        if f.exists() and busy(f):
            raise Refused("The %s wiki's %s has changes not committed; nothing moved." % (wiki, name))

    def hold(m: Move, why: str) -> None:
        if m in moves:
            moves.remove(m)
            held.append((m, why))

    for m in list(moves):
        for f in [m.page.path] + ([m.page.raw] if m.raw_to else []):
            why = busy(root / f)
            if why:
                hold(m, why)
                break
        else:
            for new in [m.new] + ([m.raw_to] if m.raw_to else []):
                if (root / new).exists():
                    hold(m, "%s is there already" % new)
                    break
    # A note another session has changes in holds every move whose change
    # it would carry, and what is left is worked out again.
    while True:
        changes, owners = changes_for(root, wiki, moves, every, links, refs, today)
        blocked = [(path, busy(path)) for path in changes if path.exists() and path.name != "app.json"]
        blocked = [(path, why) for path, why in blocked if why]
        if not blocked:
            break
        before = len(moves)
        for path, why in blocked:
            for m in [m for m in moves if m.page.path in owners.get(path, ())]:
                hold(m, "%s, which links it: %s" % (root_rel(root, path), why))
        if len(moves) == before:
            raise Refused("%s has changes not committed; nothing moved." % root_rel(root, blocked[0][0]))
        if not moves:
            changes = {}
            break
    result = {"wiki": wiki, "id": pid, "moved": [], "held": [{"page": m.page.path, "why": why} for m, why in held],
              "gone": gone, "commits": [], "uncommitted": [], "refused": None}
    if not moves:
        finish_proposal(root, wiki, result, today)
        return result
    journal = Journal()
    try:
        done_raw = set()
        for m in moves:
            journal.move(root / m.page.path, root / m.new)
            if m.raw_to and m.page.raw not in done_raw:
                journal.move(root / m.page.raw, root / m.raw_to)
                done_raw.add(m.page.raw)
        for path, text in changes.items():
            journal.write(path, text)
    except (OSError, Refused) as exc:
        journal.rollback()
        raise Refused("Nothing moved: %s" % exc)
    by_repo: Dict[Path, List[str]] = {}
    for m in moves:
        for f in [m.page.path, m.new] + ([m.page.raw, m.raw_to] if m.raw_to else []):
            by_repo.setdefault(wikis_repo, []).append((root / f).relative_to(wikis_repo).as_posix())
    for path in changes:
        repo = repo_of(root, path)
        if repo is None:
            result["uncommitted"].append({"path": root_rel(root, path), "why": "no repository holds it"})
            continue
        rel = path.relative_to(repo).as_posix()
        if path.name == "app.json" and not tracked(repo, rel):
            result["uncommitted"].append({"path": root_rel(root, path), "why": "Obsidian's settings, not committed"})
            continue
        by_repo.setdefault(repo, []).append(rel)
    order = [wikis_repo] + sorted(r for r in by_repo if r != wikis_repo)
    for repo in order:
        paths = sorted(set(by_repo.get(repo, [])))
        if not paths:
            continue
        message = commit_message(root, repo, wiki, moves, wikis_repo)
        add = git(repo, "add", "-A", "--", *paths)
        c = git(repo, "commit", "-q", "-m", message, "--", *paths) if add.returncode == 0 else add
        if c.returncode != 0:
            why = (c.stderr or c.stdout).strip().splitlines()
            reason = why[-1] if why else "git said no more"
            if repo == wikis_repo:
                git(repo, "reset", "-q", "--", *paths)
                journal.rollback()
                result["refused"] = "the %s commit was refused (%s); nothing moved" % (wiki, reason)
                return result
            result["uncommitted"] += [{"path": root_rel(root, repo / p), "why": "the commit was refused: %s" % reason}
                                      for p in paths]
            continue
        sha = git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
        result["commits"].append({"repo": root_rel(root, repo) or ".", "commit": sha, "paths": paths})
    result["moved"] = [{"page": m.page.path, "to": m.to, "new": m.new, "why": m.why} for m in moves]
    finish_proposal(root, wiki, result, today)
    return result


def root_rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def changes_for(root: Path, wiki: str, moves: List[Move], every: Dict[str, Page], links: Links,
                refs: Dict[str, List[Ref]], today: datetime.date) -> Tuple[Dict[Path, str], Dict[Path, Set[str]]]:
    """({file: its new text}, {file: the pages whose moves change it}) for
    every note a set of moves changes: links pointed at the new paths, the
    index and the dormant index, the Earlier sections, and Obsidian's
    excluded files. Pages that move are never edited."""
    moved: Dict[str, str] = {}
    for m in moves:
        moved[m.page.path] = m.new
        if m.raw_to:
            moved[m.page.raw] = m.raw_to
    leaving_working = {m.page.path for m in moves if m.page.grade == "working"}
    leaving_dormant = {m.page.path for m in moves if m.page.grade == "dormant"}
    entering_dormant = [m for m in moves if m.to == "dormant"]
    waking = [m for m in moves if m.to == "working"]
    hosts: Dict[str, List[str]] = {}
    owners: Dict[str, Set[str]] = {}
    for m in moves:
        for h in earlier_hosts(root, m, every, links, refs):
            hosts.setdefault(h, []).append(earlier_line(m))
            owners.setdefault(h, set()).add(m.page.path)
        for path in (m.page.path, m.page.raw if m.raw_to else ""):
            for r in refs.get(path, []) if path else []:
                owners.setdefault(r.src, set()).add(m.page.path)
    srcs = set(owners)
    index = "Wikis/%s/wiki/index.md" % wiki
    dindex = "Wikis/%s/wiki/%s" % (wiki, DORMANT_INDEX)
    srcs |= {index, dindex}
    srcs -= set(moved)
    out: Dict[Path, str] = {}
    for src in sorted(srcs):
        path = root / src
        try:
            old = path.read_text(encoding="utf-8") if path.exists() else ""
        except (OSError, UnicodeDecodeError):
            continue
        text = old
        if src in hosts or (every.get(src) and every[src].fixed):
            text = drop_earlier(text, {m.page.path for m in waking}, links)
        if src == index:
            text = drop_lines(text, leaving_working, links)
        if src == dindex:
            text = drop_lines(text, leaving_dormant, links)
        text = relink(text, moved, links, src)
        if src == index and waking:
            text = add_rows(text, [m.page for m in waking])
        if src == dindex:
            text = add_dormant(text, entering_dormant, today) if (text or entering_dormant) else DORMANT_HEAD
        if src in hosts:
            text = add_earlier(text, hosts[src])
        if text != old or (src == dindex and not path.exists()):
            out[path] = text
    for app, text in ignore_filters(root, wiki).items():
        out[app] = text
    every_move = {m.page.path for m in moves}
    return out, {root / src: (every_move if src in (index, dindex) else owners.get(src, set())) for src in srcs}


def commit_message(root: Path, repo: Path, wiki: str, moves: List[Move], wikis_repo: Path) -> str:
    if repo == wikis_repo:
        n = {to: sum(1 for m in moves if m.to == to) for to in ("dormant", "archived", "working")}
        said = ", ".join(x for x in ("%d dormant" % n["dormant"] if n["dormant"] else "",
                                     "%d archived" % n["archived"] if n["archived"] else "",
                                     "%d woken" % n["working"] if n["working"] else "") if x)
        body = "\n".join("- %s: %s, %s" % (m.page.sub, m.to, m.why) for m in moves)
        return "%s: faded; %s\n\n%s" % (wiki, said, body)
    label = root_rel(root, repo)
    label = label.split("/", 1)[1] if label.startswith("Zones/") else (label or "Workspace")
    return "%s: links follow %s that moved in the %s wiki" % (label, plural(len(moves), "page"), wiki)


def finish_proposal(root: Path, wiki: str, result: dict, today: datetime.date) -> None:
    """A proposal is applied once: its record goes, and its page says so."""
    md, js = proposal_paths(root, wiki)
    if js.exists():
        js.unlink()
    if md.exists():
        md.write_text(md.read_text(encoding="utf-8").rstrip("\n") + "\n\nApplied %s: %d moved, %d held, %d no longer "
                      "qualified.\n" % (today.isoformat(), len(result["moved"]), len(result["held"]),
                                        len(result["gone"])), encoding="utf-8")


# ---------------------------------------------------------------------------
# Keep: pinned: true, and a page that has faded proposed to wake
# ---------------------------------------------------------------------------

def find_page(root: Path, given: str) -> Page:
    pages = [p for w in WIKIS if wiki_top(root, w).is_dir() for p in scan_wiki(root, w)]
    want = normal(root, given)
    hit = [p for p in pages if p.path == want or p.path == want + ".md"]
    if not hit:
        name = Path(given).name.lower()
        name = name[:-3] if name.endswith(".md") else name
        hit = [p for p in pages if Path(p.path).stem.lower() == name]
    if len(hit) != 1:
        raise Refused("No page is called %s." % given if not hit else
                      "%s could be %s; say which." % (given, " or ".join(p.path for p in hit)))
    return hit[0]


def keep(root: Path, given: str, today: Optional[datetime.date] = None) -> dict:
    """Write `pinned: true` on a page and commit it alone; a page that has
    faded is then proposed to wake, as its own proposal."""
    if os.environ.get("GARRICK_HEADLESS") == "1":
        raise Refused("Keeping a page waits for a person; it never runs with nobody watching.")
    page = find_page(root, given)
    path = root / page.path
    text = path.read_text(encoding="utf-8")
    out = {"page": page.path, "grade": page.grade, "commit": None, "proposal": None}
    if not page.pinned:
        lines = text.split("\n")
        if lines and lines[0].strip() == "---":
            end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
            if end is None:
                raise Refused("%s has frontmatter that does not read." % page.path)
            at = next((i for i in range(1, end) if re.match(r"pinned\s*:", lines[i])), None)
            if at is None:
                lines.insert(end, "pinned: true")
            else:
                lines[at] = "pinned: true"
            new = "\n".join(lines)
        else:
            new = "---\npinned: true\n---\n\n" + text
        repo = repo_of(root, path)
        rel = path.relative_to(repo).as_posix() if repo else ""
        st = dirty(repo) if repo else None
        if repo is None or st is None or rel in st:
            raise Refused("%s has changes not committed, or no repository holds it; nothing written." % page.path)
        path.write_text(new, encoding="utf-8")
        c = git(repo, "commit", "-q", "-m", "%s: keep %s" % (page.wiki, page.sub), "--", rel)
        if c.returncode != 0:
            path.write_text(text, encoding="utf-8")
            raise Refused("The commit was refused: %s" % ((c.stderr or c.stdout).strip().splitlines() or ["no reason"])[-1])
        out["commit"] = git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    if page.grade != "working":
        out["proposal"] = propose(root, page.wiki, today, only=[page.path])
    return out


# ---------------------------------------------------------------------------
# Listing what has faded
# ---------------------------------------------------------------------------

def listing(root: Path, wiki: str, grade: str) -> List[dict]:
    """Every page at a grade, newest first, with its date and, where it has
    one, why it was superseded."""
    rows = [{"page": p.path, "title": p.title, "date": p.date.isoformat() if p.date else "",
             "superseded": p.superseded}
            for p in scan_wiki(root, wiki) if p.grade == grade and not p.fixed]
    return sorted(rows, key=lambda r: (r["date"], r["page"]), reverse=True)


def apply_filters(root: Path) -> List[str]:
    """Add the dormant and archive folders to every vault's excluded files
    now, outside a fade. Not committed: Obsidian's settings are the user's."""
    done = []
    for wiki in WIKIS:
        for app, text in ignore_filters(root, wiki).items():
            app.write_text(text, encoding="utf-8")
            done.append(root_rel(root, app))
    return sorted(set(done))


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def say_proposal(out: dict, ear: bool) -> str:
    if not out["moves"]:
        return "Nothing in %s would move." % SPOKEN_WIKI[out["wiki"]]
    said = out["said"].rsplit(" Say ", 1)[0]
    if ear:
        return "In %s: %s Nothing has moved; the list is written for you to read." % (SPOKEN_WIKI[out["wiki"]], said)
    lines = ["%s: %s Nothing has moved." % (out["wiki"], said), "Proposal: %s" % out["proposal"]]
    if out["first"]:
        lines.append("This is the first fade on this wiki: read the proposal before anything moves; the command "
                     "that applies it is at its end.")
    else:
        lines.append("On a yes: python3 System/tools/fade.py apply --wiki %s --id %s" % (out["wiki"], out["id"]))
    return "\n".join(lines)


def say_applied(r: dict, ear: bool) -> str:
    if r.get("refused"):
        return "Nothing moved: %s." % r["refused"]
    n = len(r["moved"])
    head = "Moved %s in %s" % (plural(n, "page"), r["wiki"]) if n else "Nothing moved in %s" % r["wiki"]
    head += ", %s." % plural(len(r["commits"]), "commit") if n else "."
    if r["held"]:
        head += " %s held: %s." % (plural(len(r["held"]), "page"), "named in the output" if ear else "see below")
    if ear:
        return head
    lines = [head] + ["  %s -> %s" % (m["page"], m["new"]) for m in r["moved"]]
    lines += ["Committed %s in %s" % (c["commit"], c["repo"]) for c in r["commits"]]
    lines += ["Held: %s: %s" % (h["page"], h["why"]) for h in r["held"]]
    lines += ["No longer qualifies, left: %s" % g for g in r["gone"]]
    lines += ["Not committed: %s (%s)" % (u["path"], u["why"]) for u in r["uncommitted"]]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Graded oblivion: propose what fades, apply it on a yes.")
    ap.add_argument("action", nargs="?", default="propose",
                    choices=("propose", "apply", "keep", "counts", "list", "settings", "filters"))
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    ap.add_argument("--wiki", choices=WIKIS)
    ap.add_argument("--id", help="apply: the proposal's id, from the written proposal")
    ap.add_argument("--page", help="keep: the page, from the workspace's top, from its wiki, or by its name")
    ap.add_argument("--leave", action="append", default=[], metavar="PATH", help="propose: a page to leave where it is")
    ap.add_argument("--only", action="append", default=[], metavar="PATH", help="propose: only these pages")
    ap.add_argument("--grade", choices=("dormant", "archived"), default="dormant")
    fmt = ap.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true")
    fmt.add_argument("--ear", action="store_true", help="at most three short sentences, for reading aloud")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    try:
        root = Path(a.root).expanduser().resolve() if a.root else workspace_root(HERE)
        if not (root / "System" / "rules.md").is_file():
            root = workspace_root(root)
    except FileNotFoundError as exc:
        print("fade: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    today = datetime.date.fromisoformat(a.today) if a.today else None
    try:
        if a.action == "settings":
            print(json.dumps(settings(root), indent=1, ensure_ascii=False))
            return 0
        if a.action == "filters":
            done = apply_filters(root)
            print(json.dumps(done) if a.json else ("\n".join("Excluded files added: %s" % d for d in done)
                                                   or "Every vault already leaves them out."))
            return 0
        if a.action == "counts":
            c = counts(root, today=today)
            if a.json:
                print(json.dumps(c, indent=1))
            else:
                said = [would_say(w, n).rsplit(" Say ", 1)[0] for w, n in c.items() if n["on"]]
                said = [x for x in said if x]
                if a.ear:
                    print(" ".join(said) or "Nothing would fade.")
                else:
                    for w, n in c.items():
                        print("%s: %d working, %d dormant, %d archived; would move: %d dormant, %d to the archive, "
                              "%d wake%s" % (w, n["working"], n["dormant"], n["archived"], n["to_dormant"],
                                             n["to_archive"], n["to_wake"], "" if n["on"] else " (fading is off)"))
            return 0
        if a.action == "list":
            if not a.wiki:
                print("fade: list needs --wiki", file=sys.stderr)
                return EXIT_USAGE
            rows = listing(root, a.wiki, a.grade)
            if a.json:
                print(json.dumps(rows, indent=1, ensure_ascii=False))
            else:
                for r in rows:
                    print("%s\t%s\t%s%s" % (r["date"] or "undated", r["page"], r["title"],
                                            "\tsuperseded: %s" % r["superseded"] if r["superseded"] else ""))
            return 0
        if a.action == "propose":
            outs = [propose(root, w, today, a.leave, a.only) for w in ([a.wiki] if a.wiki else WIKIS)
                    if wiki_top(root, w).is_dir()]
            if a.json:
                print(json.dumps(outs if not a.wiki else outs[0], indent=1, ensure_ascii=False))
            else:
                print("\n".join(say_proposal(o, a.ear) for o in outs))
            return 0
        if a.action == "apply":
            if not (a.wiki and a.id):
                print("fade: apply needs --wiki and --id, from the written proposal", file=sys.stderr)
                return EXIT_USAGE
            r = apply(root, a.wiki, a.id, today)
            print(json.dumps(r, indent=1, ensure_ascii=False) if a.json else say_applied(r, a.ear))
            return EXIT_REFUSED if r.get("refused") else 0
        if a.action == "keep":
            if not a.page:
                print("fade: keep needs --page", file=sys.stderr)
                return EXIT_USAGE
            r = keep(root, a.page, today)
            if a.json:
                print(json.dumps(r, indent=1, ensure_ascii=False))
            else:
                said = "Kept: %s is pinned%s." % (r["page"], ", committed %s" % r["commit"] if r["commit"] else "")
                if r["proposal"]:
                    said += " It has faded, so waking it is proposed: say yes to bring it back.\n%s" % \
                        say_proposal(r["proposal"], a.ear)
                print(said)
            return 0
    except Refused as exc:
        print("fade: %s" % exc, file=sys.stderr)
        return EXIT_REFUSED
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
