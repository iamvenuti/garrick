#!/usr/bin/env python3
"""Recall: a local keyword index over the notes, the wikis and past sessions,
ranked, with the walls applied before anything is returned (#341).

    python3 System/tools/recall.py build [--root DIR] [--rebuild]
    python3 System/tools/recall.py search "words" [--project DIR] [--after YYYY-MM-DD]
                                         [--zone Z] [--wiki W] [--sessions] [--archived]
                                         [--limit N] [--json]
    python3 System/tools/recall.py stats [--project DIR]
    python3 System/tools/recall.py extract [--claude DIR] [--codex DIR]
    python3 System/tools/recall.py nightly

Python standard library only (Python 3.9 floor). An index is a cache, never a
record: one gitignored SQLite file inside each zone (`Zones/<Zone>/.recall.sqlite`)
and each wiki (`Wikis/<Wiki>/.recall.sqlite`), and `System/.recall.sqlite` for
the sessions opened at the root or in System/. Deleting every index loses
nothing; `build` makes them again from the files they cover. An index never
sits in a cloud-synced folder, because sync corrupts an open SQLite file; one
that would is kept in memory instead.

Each row carries its zone and its parties. A search drops the rows whose
parties are walled from the project's party before it ranks anything.

Other code (the Ask agent's `search` tool) calls `search()`. Its signature and
the fields of `Result` are stable.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple, Union

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fade  # noqa: E402
from garrick_lib import (  # noqa: E402
    NOT_LIVE_DIR_RE,
    SKIP_DIRS,
    load_context,
    parse_frontmatter_text,
    strip_tag,
    walled,
    workspace_root,
)

PathLike = Union[str, Path]

INDEX_NAME = ".recall.sqlite"
SESSIONS_DIR = ".sessions"
TOKENIZER = "unicode61 remove_diacritics 2"
SCHEMA_VERSION = "2"
CHUNK_CHARS = 4000
RRF_K = 60
RAW_WEIGHT = 0.5
RECENCY_DAYS = 180.0
RECENCY_BONUS = 0.003          # one step of exp(-age/180) is worth about ten ranks at the top
SUPERSEDED_FACTOR = 0.5
CANDIDATES = 100               # per list, per index, per grade
MAX_WORDS = 12
MAX_FILE_BYTES = 1_500_000
RAW_EXTS = (".md", ".txt", ".eml", ".vtt", ".srt", ".csv")
WIKIS = ("Meetings", "Knowledge")
SYNCED = ("CloudStorage", "Mobile Documents", "Dropbox", "OneDrive", "Google Drive")
FTS_MISSING_SAID = "FTS5 is not in this Python's SQLite; searching by plain text, which ranks less well."


@dataclasses.dataclass(frozen=True)
class Result:
    """One hit. `path` is relative to the workspace root, with forward slashes.
    `source` names where it came from: a zone ("Work"), a wiki ("Meetings",
    "Knowledge") or "sessions". `date` is YYYY-MM-DD or "". `grade` is
    "working", "dormant" or "archived"; a dormant hit is "from older notes"."""
    id: str
    path: str
    title: str
    date: str
    source: str
    snippet: str
    score: float
    grade: str = "working"


# ---------------------------------------------------------------------------
# FTS5
# ---------------------------------------------------------------------------

def fts5_available() -> bool:
    """Whether this Python's SQLite has FTS5. Tests replace this to try the
    fallback."""
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
        finally:
            con.close()
        return True
    except sqlite3.Error:
        return False


# ---------------------------------------------------------------------------
# Where a path belongs
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Place:
    """Where a path sits in a workspace. `zone` is "" for the root and System/;
    `project` is "" above a project folder; `thread` is "" outside a thread."""
    zone: str
    project: str
    thread: str


def locate(root: Path, path: PathLike) -> Optional[Place]:
    """Place of a folder or file below `root`. None when it is not below the
    workspace, which the caller treats as unreadable."""
    base = root.resolve()
    p = Path(path)
    p = (p if p.is_absolute() else base / p).resolve()
    try:
        parts = p.relative_to(base).parts
    except ValueError:
        return None
    if len(parts) >= 2 and parts[0] == "Zones" and not parts[1].startswith("."):
        # A project is a folder. A file at the zone's top (Todo.md) belongs to the zone.
        project = parts[2] if len(parts) >= 3 and not parts[2].startswith(".") \
            and (len(parts) > 3 or (base / parts[0] / parts[1] / parts[2]).is_dir()) else ""
        thread = parts[4] if project and len(parts) >= 5 and parts[3] == "Threads" else ""
        return Place(parts[1], project, thread)
    if not parts or parts[0] == "System":
        return Place("", "", "")
    return None


def known_tags(ctx: dict) -> Set[str]:
    return {strip_tag(t) for t in ctx.get("parties", {})}


def listed_tags(value, known: Set[str]) -> Optional[List[str]]:
    """The party tags a frontmatter value names, each of them a tag the Parties
    table lists. None when any of them is not (`birch, acme` is one word to
    the YAML reader, and no wall names it): a value that cannot be read
    plainly is a value that cannot be placed. Nothing given is an empty list."""
    values = value if isinstance(value, list) else [value] if value else []
    out: List[str] = []
    for v in values:
        tag = strip_tag(str(v))
        if not tag:
            continue
        if tag not in known:
            return None
        out.append(tag)
    return out


def note_parties(fm: dict, known: Set[str]) -> Optional[List[str]]:
    """Party tags of a note's `party:` and `parties:` together, or None when
    either holds something that is not a listed tag."""
    one, many = listed_tags(fm.get("party"), known), listed_tags(fm.get("parties"), known)
    if one is None or many is None:
        return None
    return sorted(set(one + many))


def fingerprint(path: Path) -> str:
    """What an edit that keeps the size and the modified time still moves, so
    a note's parties are read again after one. The change time cannot be set
    back, and costs no read; where it means something else (Windows) the
    frontmatter, where a policy comes from, is hashed instead."""
    if os.name != "nt":
        try:
            return str(path.stat().st_ctime_ns)
        except OSError:
            return ""
    return fm_hash(path)


def fm_hash(path: Path) -> str:
    """A hash of a file's frontmatter block."""
    try:
        with open(str(path), "rb") as fh:
            head = fh.read(65536)
    except OSError:
        return ""
    end = head.find(b"\n---", 3) if head.startswith(b"---") else -1
    block = head[:end + 4] if end != -1 else head
    return hashlib.sha1(block).hexdigest()[:16]


class Hubs:
    """Party tags of the hub and thread notes, read once per run."""

    def __init__(self, root: Path):
        self.root = root
        self.known = known_tags(load_context(root))
        self.cache: Dict[Tuple[str, str, str], List[str]] = {}

    def parties(self, place: Place) -> List[str]:
        if not place.zone or not place.project:
            return []
        key = (place.zone, place.project, place.thread)
        if key not in self.cache:
            top = self.root / "Zones" / place.zone / place.project
            tags: Set[str] = set()
            for path in [top / (place.project + ".md")] + (
                    [top / "Threads" / place.thread / (place.thread + ".md")] if place.thread else []):
                found = self._read(path)
                if found is None:           # a party that is not a listed tag: the place has no party
                    tags = set()
                    break
                tags |= set(found)
            self.cache[key] = sorted(tags)
        return self.cache[key]

    def _read(self, path: Path) -> Optional[List[str]]:
        try:
            return note_parties(parse_frontmatter_text(path.read_text(encoding="utf-8", errors="replace")),
                                self.known)
        except OSError:
            return []


# ---------------------------------------------------------------------------
# The index file
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Scope:
    """What one index covers: a zone, a wiki, or `System` for root sessions."""
    kind: str       # zone, wiki, system
    name: str

    def folder(self, root: Path) -> Path:
        if self.kind == "zone":
            return root / "Zones" / self.name
        if self.kind == "wiki":
            return root / "Wikis" / self.name
        return root / "System"

    def label(self) -> str:
        return "sessions" if self.kind == "system" else self.name


_IGNORE_SAID: Set[str] = set()
_IGNORED: Dict[str, bool] = {}     # per folder, for this run


def git_ignores(path: Path) -> bool:
    """May `path` be written without git ever seeing it? True when git ignores
    it, or when no repository holds it. A repository whose answer cannot be had
    (no git, a timeout) counts as not ignoring it: the file is not written."""
    path = Path(path)
    folder = path.parent
    while not folder.is_dir() and folder != folder.parent:
        folder = folder.parent
    try:
        done = subprocess.run(["git", "-C", str(folder), "check-ignore", "-q", "--", str(path)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        code = done.returncode
    except (OSError, subprocess.SubprocessError):
        code = 128
    if code == 0:
        return True
    if code == 1:
        return False
    # Not a repository, or git could not say: fine only when nothing above is one.
    return not any((d / ".git").is_file() or (d / ".git" / "HEAD").exists() for d in [folder] + list(folder.parents))


def safe_to_write(path: Path) -> bool:
    """git_ignores(), and one line on stderr the first time it says no."""
    key = str(path.parent)
    if key not in _IGNORED:
        _IGNORED[key] = git_ignores(path)
    if _IGNORED[key]:
        return True
    if key not in _IGNORE_SAID:
        _IGNORE_SAID.add(key)
        print("recall: %s is not ignored by git, so nothing is written there; add the lines "
              "`.recall.sqlite*` and `.sessions/` to its .gitignore (check.py reports it)." % path.parent,
              file=sys.stderr)
    return False


def synced(path: Path) -> bool:
    return any(part in SYNCED or part.startswith("OneDrive") for part in path.resolve().parts)


SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE files(path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER, attrs TEXT);
CREATE TABLE policies(pid INTEGER PRIMARY KEY, kind TEXT, zone TEXT, project TEXT, parties TEXT,
                      UNIQUE(kind, zone, project, parties));
CREATE TABLE owners(raw TEXT, page TEXT, ok INTEGER, PRIMARY KEY(raw, page));
CREATE TABLE docs(id INTEGER PRIMARY KEY, path TEXT, kind TEXT, src TEXT, title TEXT, date TEXT, grade TEXT,
                  superseded INTEGER, pid INTEGER, owner TEXT, body TEXT);
CREATE INDEX docs_path ON docs(path);
CREATE INDEX docs_owner ON docs(owner);
"""


class Index:
    def __init__(self, root: Path, scope: Scope, fts: bool):
        self.root, self.scope, self.fts = root, scope, fts
        self.path = scope.folder(root) / INDEX_NAME
        self.con = self._open()

    YOUNG_SECONDS = 15.0

    def _open(self) -> sqlite3.Connection:
        folder = self.path.parent
        if not folder.is_dir():
            return self._memory()
        if synced(folder) or not safe_to_write(self.path):
            return self._memory()
        try:
            if self.path.exists():
                con = sqlite3.connect(str(self.path))
                state = self._state(con)
                if state == "ready":
                    self._private(self.path)
                    return con
                con.close()
                try:
                    young = time.time() - self.path.stat().st_mtime < self.YOUNG_SECONDS
                except OSError:
                    young = False
                if state == "empty" and young:      # another process may be making it right now
                    return self._memory()
            return self._replace()
        except (sqlite3.Error, OSError):
            return self._memory()

    def _replace(self) -> sqlite3.Connection:
        """Make the index in a file of its own and move it into place in one
        step, so a process that is opening the old one never finds it half made."""
        tmp = self.path.with_name("%s.new-%d" % (INDEX_NAME, os.getpid()))
        for suffix in ("", "-journal"):
            try:
                os.remove(str(tmp) + suffix)
            except OSError:
                pass
        con = sqlite3.connect(str(tmp))
        self._create(con)
        con.close()
        self._private(tmp)
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                os.remove(str(self.path) + suffix)
            except OSError:
                pass
        os.replace(str(tmp), str(self.path))
        return sqlite3.connect(str(self.path))

    @staticmethod
    def _private(path: Path) -> None:
        try:
            os.chmod(str(path), 0o600)
        except OSError:
            pass

    def _memory(self) -> sqlite3.Connection:
        con = sqlite3.connect(":memory:")
        self._create(con)
        return con

    def _state(self, con: sqlite3.Connection) -> str:
        """ready, stale (made by another version or setting), or empty (no
        meta table: unreadable, or still being made)."""
        try:
            rows = dict(con.execute("SELECT key, value FROM meta").fetchall())
        except sqlite3.Error:
            return "empty"
        ok = rows.get("version") == SCHEMA_VERSION and rows.get("fts") == ("1" if self.fts else "0") \
            and rows.get("tokenizer") == TOKENIZER
        return "ready" if ok else "stale"

    def _create(self, con: sqlite3.Connection) -> None:
        con.executescript(SCHEMA)
        if self.fts:
            con.execute("CREATE VIRTUAL TABLE fts USING fts5(title, body, content='docs', content_rowid='id', "
                        "tokenize='%s')" % TOKENIZER)
        con.executemany("INSERT INTO meta VALUES (?, ?)", [("version", SCHEMA_VERSION), ("tokenizer", TOKENIZER),
                                                           ("fts", "1" if self.fts else "0")])
        con.commit()

    def close(self) -> None:
        try:
            self.con.close()
        except sqlite3.Error:
            pass

    # -- rows ---------------------------------------------------------------

    def policy(self, kind: str, zone: str, project: str, parties: List[str]) -> int:
        key = (kind, zone, project, "|".join(parties))
        row = self.con.execute("SELECT pid FROM policies WHERE kind=? AND zone=? AND project=? AND parties=?",
                               key).fetchone()
        if row:
            return row[0]
        return self.con.execute("INSERT INTO policies(kind, zone, project, parties) VALUES (?,?,?,?)", key).lastrowid

    def drop(self, path: str) -> None:
        rows = self.con.execute("SELECT id, title, body FROM docs WHERE path=?", (path,)).fetchall()
        if self.fts:
            for i, title, body in rows:
                self.con.execute("INSERT INTO fts(fts, rowid, title, body) VALUES('delete', ?, ?, ?)",
                                 (i, title, body))
        self.con.execute("DELETE FROM docs WHERE path=?", (path,))
        self.con.execute("DELETE FROM files WHERE path=?", (path,))
        self.con.execute("DELETE FROM owners WHERE page=?", (path,))

    def add(self, path: str, kind: str, src: str, title: str, date: str, grade: str, superseded: bool, pid: int,
            owner: str, bodies: List[str]) -> None:
        for body in bodies:
            i = self.con.execute("INSERT INTO docs(path, kind, src, title, date, grade, superseded, pid, owner, "
                                 "body) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (path, kind, src, title, date, grade, int(superseded), pid, owner, body)).lastrowid
            if self.fts:
                self.con.execute("INSERT INTO fts(rowid, title, body) VALUES (?,?,?)", (i, title, body))


# ---------------------------------------------------------------------------
# What each scope covers
# ---------------------------------------------------------------------------

def read_text(path: Path) -> Optional[str]:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def body_of(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def chunks(text: str, size: int = CHUNK_CHARS) -> List[str]:
    """About `size` characters at a time, cut at a line break where one is near."""
    text = text.strip()
    out = []
    while len(text) > size:
        cut = text.rfind("\n", size // 2, size)
        cut = cut if cut > 0 else size
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        out.append(text)
    return out


def first_heading(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("#"):
            return line.lstrip("# ").strip()
    return ""


def iso(d: Optional[datetime.date]) -> str:
    return d.isoformat() if d else ""


def stamp(path: Path) -> Tuple[int, int]:
    st = path.stat()
    return st.st_mtime_ns, st.st_size


def zone_entries(root: Path, zone: str) -> Iterable[Tuple[str, Path]]:
    """Markdown notes of a zone, and the sessions extracted for it. What git
    would not read as the zone's own is left out: hidden folders, Inbox,
    build output, a nested checkout, a link."""
    top = root / "Zones" / zone
    for dirpath, dirnames, filenames in os.walk(str(top)):
        here = Path(dirpath)
        keep = []
        for d in sorted(dirnames):
            if d in SKIP_DIRS or d.startswith(".") or (here == top and d == "Inbox"):
                continue
            if NOT_LIVE_DIR_RE.match(d) and d.lower() != "archive":
                continue
            if (here / d / ".git").exists() or (here / d).is_symlink():
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            if name.lower().endswith(".md") and not name.startswith("."):
                yield (here / name).relative_to(root).as_posix(), here / name
    sessions = top / SESSIONS_DIR
    if sessions.is_dir():
        for p in sorted(sessions.glob("*.md")):
            yield p.relative_to(root).as_posix(), p


def wiki_entries(root: Path, wiki: str) -> Tuple[List[Tuple[str, Path]], List[Tuple[str, Path]]]:
    """(pages, raw records) of a wiki, at every grade."""
    top = root / "Wikis" / wiki
    pages, raws = [], []
    for grade in fade.GRADES:
        base = top / fade.FOLDER[grade] if fade.FOLDER[grade] else top
        for path in fade.walk(base / "wiki"):
            sub = path.relative_to(base).as_posix()
            inner = sub.split("/")[1:]
            if inner and (inner[0] == "lint" or (len(inner) == 1 and inner[0] in fade.LISTS)):
                continue
            pages.append((path.relative_to(root).as_posix(), path))
        for path in fade.walk(base / "raw", md_only=False):
            sub = path.relative_to(base).as_posix().split("/")
            if len(sub) > 1 and sub[1].lower() == "inbox":
                continue
            if path.suffix.lower() in RAW_EXTS:
                raws.append((path.relative_to(root).as_posix(), path))
    return pages, raws


def system_entries(root: Path) -> Iterable[Tuple[str, Path]]:
    sessions = root / "System" / SESSIONS_DIR
    if sessions.is_dir():
        for p in sorted(sessions.glob("*.md")):
            yield p.relative_to(root).as_posix(), p


def grade_of(rel: str, wiki: str) -> str:
    parts = rel.split("/")
    if len(parts) > 2 and parts[0] == "Wikis":
        if parts[2] == "dormant":
            return "dormant"
        if parts[2] == "archive":
            return "archived"
    return "working"


class Refresher:
    """Brings one index up to date with the files it covers, by modified time
    and size, and by what a file takes from another (a hub's party, the page
    that owns a raw record). A file is read only when one of them changed."""

    def __init__(self, idx: Index, hubs: Hubs):
        self.idx, self.hubs, self.root = idx, hubs, idx.root

    def run(self, rebuild: bool = False) -> None:
        con = self.idx.con
        if rebuild:
            con.executescript("DELETE FROM docs; DELETE FROM files; DELETE FROM owners; DELETE FROM policies;")
            if self.idx.fts:
                con.execute("INSERT INTO fts(fts) VALUES('delete-all')")
        known = {r[0]: (r[1], r[2], r[3]) for r in con.execute("SELECT path, mtime, size, attrs FROM files")}
        seen: Set[str] = set()
        scope = self.idx.scope
        if scope.kind == "wiki":
            pages, raws = wiki_entries(self.root, scope.name)
            self._each(pages, known, seen, self.page_derived, self.page)
            self._each(raws, known, seen, self.raw_derived, self.raw)
        elif scope.kind == "system":
            self._each(system_entries(self.root), known, seen, self.session_derived, self.session)
        else:
            self._each(zone_entries(self.root, scope.name), known, seen, self.note_derived, self.note)
        for gone in set(known) - seen:
            self.idx.drop(gone)
        con.commit()

    def _each(self, entries, known, seen, derived, index) -> None:
        for rel, path in entries:
            seen.add(rel)
            try:
                m, s = stamp(path)
            except OSError:
                continue
            attrs = derived(rel, path)
            old = known.get(rel)
            if old and old[0] == m and old[1] == s and old[2] == attrs:
                continue
            self.idx.drop(rel)
            index(rel, path)
            self.idx.con.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?)", (rel, m, s, attrs))

    # -- zone notes and sessions --------------------------------------------

    def note_derived(self, rel: str, path: Path) -> str:
        if SESSIONS_DIR in rel.split("/"):
            return self.session_derived(rel, path)
        place = self.place(rel)
        return json.dumps([self.hubs.parties(place), place.project, fingerprint(path)])

    def place(self, rel: str) -> Place:
        """Place of a zone note from its path below the root, which the walk
        made: no link was followed, so nothing needs resolving."""
        parts = rel.split("/")
        project = parts[2] if len(parts) > 3 and not parts[2].startswith(".") else ""
        thread = parts[4] if project and len(parts) >= 5 and parts[3] == "Threads" else ""
        return Place(parts[1], project, thread)

    def note(self, rel: str, path: Path) -> None:
        if SESSIONS_DIR in rel.split("/"):
            return self.session(rel, path)
        text = read_text(path)
        if text is None:
            return
        place = self.place(rel)
        fm = parse_frontmatter_text(text)
        body = body_of(text)
        own = note_parties(fm, self.hubs.known)
        if own is None:
            return                                  # a party no wall names: the note is used nowhere
        parties = sorted(set(self.hubs.parties(place)) | set(own))
        stat_date = datetime.date.fromtimestamp(path.stat().st_mtime)
        date = next((d for d in (fade.read_date(fm.get(f)) for f in ("date", "updated", "created")) if d), None) \
            or fade.name_date(path.name) or stat_date
        title = str(fm.get("title") or "") or first_heading(body) or path.stem
        grade = "archived" if "archive" in [x.lower() for x in rel.split("/")[:-1]] else "working"
        pid = self.idx.policy("zone", place.zone, place.project, parties)
        self.idx.add(rel, "note", "zone", title, iso(date), grade, bool(str(fm.get("superseded") or "").strip()),
                     pid, "", [body.strip()])

    def session_where(self, path: Path) -> Tuple[List[Place], dict]:
        """The projects a session worked in (of its own zone only) and its header."""
        try:
            with open(str(path), encoding="utf-8", errors="replace") as fh:
                head = fh.read(4000)
        except OSError:
            return [], {}
        fm = parse_frontmatter_text(head)
        zone = (locate(self.root, path) or Place("", "", "")).zone
        given = fm.get("project") if isinstance(fm.get("project"), list) else [fm.get("project")]
        found = [locate(self.root, str(g)) for g in given if g]
        return [p for p in found if p is not None and p.zone == zone and p.project], fm

    def session_parties(self, where: List[Place]) -> Tuple[List[str], str]:
        tags = sorted({t for p in where for t in self.hubs.parties(p)})
        return tags, where[0].project if where else ""

    def session_derived(self, rel: str, path: Path) -> str:
        where, _ = self.session_where(path)
        return json.dumps([self.session_parties(where), fingerprint(path)])

    def session(self, rel: str, path: Path) -> None:
        text = read_text(path)
        if text is None:
            return
        where, fm = self.session_where(path)
        zone = (locate(self.root, path) or Place("", "", "")).zone
        parties, project = self.session_parties(where)
        pid = self.idx.policy("session" if zone else "system", zone, project, parties)
        title = str(fm.get("title") or "") or path.stem
        self.idx.add(rel, "chunk", "session", title, iso(fade.name_date(path.name)), "working", False, pid, "",
                     chunks(body_of(text)))

    # -- wiki pages and their raw records -----------------------------------

    @staticmethod
    def page_derived(rel: str, path: Path) -> str:
        return fingerprint(path)

    def page(self, rel: str, path: Path) -> None:
        wiki = rel.split("/")[1]
        grade = grade_of(rel, wiki)
        text = read_text(path)
        if text is None:
            return
        fm = parse_frontmatter_text(text)
        parties = note_parties(fm, self.hubs.known)
        given = fm.get("zone") if isinstance(fm.get("zone"), list) else [fm.get("zone")]
        zones = sorted({str(z).strip().lower() for z in given if z and str(z).strip()})
        # A Knowledge page that names a zone or a party is a conversation filed in the wrong
        # wiki: it follows the Meetings policy, and an unfinished one is used nowhere.
        conversation = wiki == "Meetings" or bool(zones) or bool(fm.get("party")) or bool(fm.get("parties"))
        usable = not (parties is None or (conversation and (not zones or not parties)))
        self.claim(rel, wiki, grade, fm, usable)
        if not usable:
            return                                  # an unfinished page, or a party no wall names
        body = body_of(text)
        date = next((d for d in (fade.read_date(fm.get(f)) for f in fade.DATE_FIELDS[wiki]) if d), None) \
            or fade.name_date(path.name)
        title = str(fm.get("title") or "") or first_heading(body) or path.stem
        pid = self.idx.policy("meetings" if conversation else "knowledge", "|".join(zones), "", parties)
        self.idx.add(rel, "note", wiki.lower(), title, iso(date), grade,
                     bool(str(fm.get("superseded") or "").strip()), pid, "", [body.strip()])

    def claim(self, rel: str, wiki: str, grade: str, fm: dict, usable: bool) -> None:
        """A page names the raw record it rests on. A record may have several
        claimants, finished or not; each is kept, so that the record follows
        the strictest of them whatever order the pages are read in."""
        if not fm.get("raw"):
            return
        probe = fade.Page(rel, wiki, grade, "")
        fade.find_raw(self.root / "Wikis" / wiki, probe, fade.link_target(fm.get("raw")))
        if probe.raw:
            self.idx.con.execute("INSERT OR REPLACE INTO owners VALUES (?,?,?)", (probe.raw, rel, int(usable)))

    def owner_row(self, rel: str):
        """(first claimant, policy id, title, date, superseded) for a raw record,
        or None when it has no claimant or any claimant is unfinished or unlisted."""
        con = self.idx.con
        claims = con.execute("SELECT page, ok FROM owners WHERE raw=? ORDER BY page", (rel,)).fetchall()
        if not claims or not all(ok for _, ok in claims):
            return None
        rows = []
        for page, _ in claims:
            row = con.execute("SELECT pid, title, date, superseded FROM docs WHERE path=? LIMIT 1", (page,)).fetchone()
            if row is None:
                return None
            rows.append((page,) + tuple(row))
        pols = [con.execute("SELECT kind, zone, project, parties FROM policies WHERE pid=?", (r[1],)).fetchone()
                for r in rows]
        if len(rows) == 1 or None in pols:
            pid = rows[0][1]
        else:
            kind = "meetings" if any(p[0] == "meetings" for p in pols) else pols[0][0]
            zones = sorted({z for p in pols for z in p[1].split("|") if z})
            parties = sorted({x for p in pols for x in p[3].split("|") if x})
            pid = self.idx.policy(kind, "|".join(zones), "", parties)
        first = rows[0]
        return (first[0], pid, first[2], first[3], first[4])

    def raw_derived(self, rel: str, path: Path) -> str:
        return json.dumps(self.owner_row(rel))

    def raw(self, rel: str, path: Path) -> None:
        owner = self.owner_row(rel)
        text = read_text(path) if owner else None
        if owner is None or text is None:
            return                                  # a record no finished page owns
        page, pid, title, date, superseded = owner
        self.idx.add(rel, "chunk", "raw", title, date, grade_of(rel, rel.split("/")[1]), bool(superseded), pid,
                     page, chunks(text))


# ---------------------------------------------------------------------------
# Who is searching, and what they may read
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Searcher:
    root: Path
    everything: bool           # a session at the root or in System/
    zone: str                  # lower-case, "" at the root
    project: str
    parties: Set[str]
    zones: Set[str]            # lower-case zones the search may reach


def searcher(root: Path, project: Optional[PathLike], zone: Optional[str], zone_names: List[str],
             hubs: Hubs) -> Optional[Searcher]:
    if project is None:
        place = Place("", "", "")
    else:
        # Only a literal None is the root. An empty string, ".", or a place no
        # zone owns (a wiki, Zones/ itself, a folder outside) is nobody's.
        if str(project).strip() in ("", ".") or Path(project) == Path("."):
            return None
        found = locate(root, project)
        if found is None:
            return None
        place = found
    if not place.zone:
        return Searcher(root, True, "", "", set(), {z.lower() for z in zone_names})
    own = next((z for z in zone_names if z.lower() == place.zone.lower()), None)
    if own is None:
        return None
    wanted = {own.lower()}
    if zone:
        match = next((z for z in zone_names if z.lower() == zone.lower()), None)
        if match is None:
            return None
        wanted.add(match.lower())
    return Searcher(root, False, own.lower(), place.project, set(hubs.parties(place)), wanted)


def permitted(s: Searcher, ctx: dict, kind: str, zone: str, project: str, parties: List[str]) -> bool:
    """May this row be read from here? The same Walls table the commit hook
    reads. A row that cannot be placed is not readable."""
    if kind == "knowledge":
        return True
    if kind == "system":
        return s.everything                     # sessions opened at the root or in System/
    zones = [z for z in zone.lower().split("|") if z]
    if kind == "meetings":
        if not zones or not parties:
            return False
        if s.everything:
            return True
        if not all(z in s.zones for z in zones) or not s.parties:
            return False
        return not any(walled(ctx, a, b) for a in s.parties for b in parties)
    # zone notes and sessions
    if not zones or zones[0] not in s.zones:
        return False
    if s.everything:
        return True
    if not parties or not s.parties:
        # Nothing says whose it is, or nothing says whose the search is: only the
        # same project (or the zone's own top level) may read it.
        return zones[0] == s.zone and project == s.project
    return not any(walled(ctx, a, b) for a in s.parties for b in parties)


@dataclasses.dataclass(frozen=True)
class RowPolicy:
    """What a row says about whose it is, handed to a caller's `admit`.
    `kind` is "meetings", "knowledge", "zone" (a note), "session" or "system"; `zones`
    and `parties` are lower-case tuples, empty when the row names none."""
    kind: str
    zones: Tuple[str, ...]
    project: str
    parties: Tuple[str, ...]


def allowed_pids(idx: Index, s: Searcher, ctx: dict,
                 admit: Optional[Callable[[RowPolicy], bool]] = None) -> List[int]:
    out = []
    for pid, kind, zone, project, parties in idx.con.execute("SELECT pid, kind, zone, project, parties FROM policies"):
        plist = [p for p in parties.split("|") if p]
        if not permitted(s, ctx, kind, zone, project, plist):
            continue
        if admit is not None:
            try:
                ok = bool(admit(RowPolicy(kind, tuple(z for z in zone.lower().split("|") if z), project,
                                          tuple(plist))))
            except Exception:
                ok = False                       # fail closed
            if not ok:
                continue
        out.append(pid)
    return out


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def query_words(words: str) -> List[str]:
    seen: List[str] = []
    for w in re.findall(r"\w+", words, re.UNICODE):
        if w.lower() not in seen:
            seen.append(w.lower())
    return seen[:MAX_WORDS]


def fts_query(words: List[str]) -> str:
    return " OR ".join('"%s"' % w for w in words)


@dataclasses.dataclass
class Hit:
    rowid: int
    path: str
    kind: str
    src: str
    title: str
    date: str
    grade: str
    superseded: int
    owner: str
    scope: Scope
    rank: int = 0


BM25_K1 = 1.2
BM25_B = 0.75
MAX_MATCHED = 20000


def tokens(text: str) -> List[str]:
    return re.findall(r"\w+", plain(text), re.UNICODE)


def candidates(idx: Index, words: List[str], kind: str, grades: List[str], pids: List[int],
               after: Optional[str], sessions: bool, wiki: Optional[str],
               only_sessions: bool = False) -> List[Hit]:
    """Best rows of one list in one index, best first. Only rows the walls
    allow are in the query, and the ranking (BM25) takes its document count,
    document frequencies and average length from those rows alone: a walled
    row changes neither what is found nor in what order."""
    if not pids:
        return []
    where = ["d.kind = ?", "d.grade IN (%s)" % ",".join("?" * len(grades)), "d.pid IN (%s)" % ",".join(
        str(int(p)) for p in pids)]
    args: list = [kind] + list(grades)
    if not sessions:
        where.append("d.src != 'session'")
    if only_sessions:
        where.append("d.src = 'session'")
    if after:
        where.append("d.date != '' AND d.date >= ?")
        args.append(after)
    cond = " AND ".join(where)
    cols = "d.id, d.path, d.kind, d.src, d.title, d.date, d.grade, d.superseded, d.owner"
    terms = [plain(w) for w in words]
    texts: Dict[int, Tuple[tuple, List[str], List[str], int]] = {}
    if idx.fts:
        total, chars = idx.con.execute("SELECT COUNT(*), COALESCE(SUM(length(d.title) + length(d.body)), 0) "
                                       "FROM docs d WHERE " + cond, args).fetchone()
        df = {}
        for w in words:
            df[plain(w)] = idx.con.execute(
                "SELECT COUNT(*) FROM fts JOIN docs d ON d.id = fts.rowid WHERE fts MATCH ? AND " + cond,
                ['"%s"' % w] + args).fetchone()[0]
        rows = idx.con.execute("SELECT %s, d.body FROM fts JOIN docs d ON d.id = fts.rowid WHERE fts MATCH ? "
                               "AND %s ORDER BY d.id LIMIT %d" % (cols, cond, MAX_MATCHED),
                               [fts_query(words)] + args).fetchall()
        for r in rows:
            texts[r[0]] = (r[:-1], tokens(r[4]), tokens(r[-1]), len(r[4]) + len(r[-1]))
    else:
        total = chars = 0
        df = {t: 0 for t in terms}
        for r in idx.con.execute("SELECT %s, d.body FROM docs d WHERE %s" % (cols, cond), args):
            total += 1
            chars += len(r[4]) + len(r[-1])
            title, body = tokens(r[4]), tokens(r[-1])
            present = set(title) | set(body)
            for t in terms:
                if t in present:
                    df[t] += 1
            if any(t in present for t in terms):
                texts[r[0]] = (r[:-1], title, body, len(r[4]) + len(r[-1]))
    avg = (chars / total) if total else 1.0
    scored = []
    for rowid, (head, title, body, length) in texts.items():
        counts_t, counts_b = collections.Counter(title), collections.Counter(body)
        score = 0.0
        for t in terms:
            tf = 2.0 * counts_t.get(t, 0) + counts_b.get(t, 0)
            if not tf:
                continue
            idf = math.log(1.0 + (total - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * tf * (BM25_K1 + 1.0) / (tf + BM25_K1 * (1.0 - BM25_B + BM25_B * length / avg))
        scored.append((score, Hit(*head, scope=idx.scope)))
    scored.sort(key=lambda t: (-t[0], t[1].path, t[1].rowid))
    return one_per_file([h for _, h in scored])[:CANDIDATES]


def one_per_file(hits: List[Hit]) -> List[Hit]:
    seen: Set[str] = set()
    out = []
    for h in hits:
        if h.path not in seen:
            seen.add(h.path)
            out.append(h)
    return out


def snippet(idx: Index, words: List[str], rowid: int) -> str:
    row = None
    if idx.fts:
        row = idx.con.execute("SELECT snippet(fts, 1, '', '', ' ... ', 24) FROM fts WHERE fts MATCH ? AND rowid = ?",
                              (fts_query(words), rowid)).fetchone()
        if row and row[0] and row[0].strip():
            return " ".join(row[0].split())
    body = (idx.con.execute("SELECT body FROM docs WHERE id=?", (rowid,)).fetchone() or ("",))[0]
    flat = plain(body)
    at = min([flat.find(plain(w)) for w in words if flat.find(plain(w)) >= 0] or [0])
    return " ".join(body[max(0, at - 80): at + 160].split())


def age_days(date: str, today: datetime.date) -> Optional[float]:
    d = fade.read_date(date)
    return max(0.0, float((today - d).days)) if d else None


def fuse(lists: List[Tuple[float, List[Hit]]], today: datetime.date) -> List[Tuple[float, Hit]]:
    """Reciprocal rank fusion over the lists, then the recency bonus and the
    superseded discount. A raw record folds into the page that owns it."""
    scores: Dict[str, float] = collections.defaultdict(float)
    keep: Dict[str, Hit] = {}
    for weight, hits in lists:
        for rank, h in enumerate(hits, 1):
            key = h.owner or h.path
            scores[key] += weight / (RRF_K + rank)
            if key not in keep or (h.kind == "note" and keep[key].kind != "note"):
                keep[key] = h
    out = []
    for key, value in scores.items():
        h = keep[key]
        age = age_days(h.date, today)
        if age is not None:
            value += RECENCY_BONUS * math.exp(-age / RECENCY_DAYS)
        if h.superseded:
            value *= SUPERSEDED_FACTOR
        out.append((value, h))
    out.sort(key=lambda t: (-t[0], t[1].path))
    return out


# ---------------------------------------------------------------------------
# The interface
# ---------------------------------------------------------------------------

def zone_names(root: Path) -> List[str]:
    top = root / "Zones"
    return sorted(p.name for p in top.iterdir() if p.is_dir() and not p.name.startswith(".")) if top.is_dir() else []


def open_scope(root: Path, scope: Scope, hubs: Hubs, fts: bool) -> Optional[Index]:
    if not scope.folder(root).is_dir():
        return None
    idx = Index(root, scope, fts)
    try:
        Refresher(idx, hubs).run()
    except sqlite3.Error:
        idx.close()
        return None
    return idx


def reach_of(root: Path) -> str:
    try:
        return fade.settings(root)["reach"]
    except Exception:
        return "working"


def search(words: str, *, project: Optional[PathLike], after: Optional[str] = None,
           zone: Optional[str] = None, wiki: Optional[str] = None, sessions: bool = False,
           limit: int = 10, root: Optional[PathLike] = None, archived: bool = False,
           admit: Optional[Callable[[RowPolicy], bool]] = None) -> List[Result]:
    """Ranked hits for `words`, best first, at most `limit`.

    `project` is the folder of the project the session works in (absolute, or
    relative to the workspace root), for example `Zones/Work/Acme`. Its zone
    and its hub's `party:` decide which rows may be returned. `None` means a
    session opened at the workspace root or in `System/`, which has no party
    and may read every zone and `System/.sessions/`. Only a literal `None` is
    that: an empty string, ".", a folder that is not below the workspace, a
    place that belongs to no zone (a wiki, `Zones/` itself) or a zone that
    does not exist returns [].

    `after` keeps only hits dated on or after YYYY-MM-DD. `zone` adds another
    zone's index (the project's own zone is always searched; a root session
    searches every zone); `wiki` limits the search to one wiki (with `sessions=True` the sessions
    are added to it, and no zone notes). `sessions=True`
    adds extracted sessions: the project's own zone's, or from a root session
    all of them. `archived=True` adds archived pages after the rest. `root` is
    the workspace root; it defaults to the one above `project`, or above the
    current folder.

    THE WALLS ARE APPLIED INSIDE THIS FUNCTION, BEFORE ANYTHING IS RETURNED.
    A row whose parties are walled from the project's party is dropped before
    ranking, so it is not returned, not counted and not in a snippet. A
    Meetings page with no zone or no parties is dropped too, and so is a
    Meetings page of a zone the search was not asked to reach. A Knowledge page
    that names a zone or a party follows the Meetings rule. Other Knowledge
    is not filtered. A `party:` that holds anything but listed tags puts the
    row (or a project hub's files) in the no-party case. Counts and headers built from the returned list therefore
    include only what the caller may see; a caller must never count rows
    any other way.

    `admit` is an extra wall for a caller that is not a project (the Ask
    server calls with `project=None`). It gets each row's `RowPolicy` and
    returns True to keep it. It is applied together with the project's own
    wall, before ranking and before the oversample window, so BM25's counts
    and the candidates are computed over admitted rows alone and a refused row
    changes neither what is found nor in what order. It can only narrow: a row
    the walls refuse is never admitted by it, and an error in it refuses the
    row.

    Working pages are searched first. Dormant pages join only when the
    working ones return fewer than `limit` and the `reach` setting allows it;
    their `grade` is "dormant" ("from older notes"). Archived pages join only
    with `archived=True`.
    """
    terms = query_words(words or "")
    if not terms or limit < 1:
        return []
    try:
        base = Path(root) if root is not None else workspace_root(
            project if project is not None and Path(project).is_absolute() else None)
    except FileNotFoundError:
        return []
    base = base.resolve()
    ctx = load_context(base)
    hubs = Hubs(base)
    names = zone_names(base)
    who = searcher(base, project, zone, names, hubs)
    if who is None:
        return []
    fts = fts5_available()
    scopes: List[Scope] = []
    if wiki:
        match = next((w for w in WIKIS if w.lower() == wiki.lower()), None)
        if match is None:
            return []
        scopes.append(Scope("wiki", match))
    else:
        scopes += [Scope("wiki", w) for w in WIKIS]
    if not wiki:
        scopes += [Scope("zone", z) for z in names if z.lower() in who.zones]
    elif sessions:
        scopes += [Scope("zone", z) for z in names if z.lower() in who.zones]
    if sessions and who.everything:
        scopes.append(Scope("system", "System"))
    today = datetime.date.today()
    reach = reach_of(base)
    indexes = [i for i in (open_scope(base, sc, hubs, fts) for sc in scopes) if i is not None]
    try:
        tiers = [["working"]]
        if reach == "dormant":
            tiers.append(["dormant"])
        if archived:
            tiers.append(["archived"])
        found: List[Tuple[float, Hit, Index]] = []
        for number, grades in enumerate(tiers):
            if number > 0 and grades == ["dormant"] and len(found) >= limit:
                continue
            lists: List[Tuple[float, List[Hit]]] = []
            for idx in indexes:
                pids = allowed_pids(idx, who, ctx, admit)
                for kind, weight in (("note", 1.0), ("chunk", RAW_WEIGHT)):
                    if kind == "note" and idx.scope.kind == "system":
                        continue
                    hits = candidates(idx, terms, kind, grades, pids, after, sessions, wiki,
                                      only_sessions=bool(wiki) and idx.scope.kind != "wiki")
                    if hits:
                        lists.append((weight, hits))
            tier = [(v, h) for v, h in fuse(lists, today)]
            by_scope = {i.scope: i for i in indexes}
            found += [(v, h, by_scope[h.scope]) for v, h in tier]
        out: List[Result] = []
        for value, h, idx in found[:limit]:
            out.append(Result(id="%s:%s" % (h.scope.label(), h.path), path=h.path, title=h.title, date=h.date,
                              source=h.scope.label() if h.src != "session" else "sessions",
                              snippet=snippet(idx, terms, h.rowid), score=round(value, 6), grade=h.grade))
        return out
    finally:
        for idx in indexes:
            idx.close()


def stats(project: Optional[PathLike] = None, root: Optional[PathLike] = None) -> List[dict]:
    """One line per index: where it is and how many rows the caller may read.
    Rows behind a wall are not counted."""
    base = (Path(root) if root is not None else workspace_root()).resolve()
    ctx, hubs, names = load_context(base), Hubs(base), zone_names(base)
    who = searcher(base, project, None, names, hubs)
    if who is None:
        return []
    fts = fts5_available()
    out = []
    scopes = [Scope("wiki", w) for w in WIKIS] + [Scope("zone", z) for z in names if z.lower() in who.zones]
    if who.everything:
        scopes.append(Scope("system", "System"))
    for sc in scopes:
        idx = open_scope(base, sc, hubs, fts)
        if idx is None:
            continue
        try:
            pids = allowed_pids(idx, who, ctx)
            n = idx.con.execute("SELECT COUNT(DISTINCT path) FROM docs WHERE pid IN (%s)" % ",".join(
                str(int(p)) for p in pids)).fetchone()[0] if pids else 0
            out.append({"index": sc.label(), "file": idx.path.relative_to(base).as_posix(), "files": n,
                        "fts": idx.fts, "memory": not idx.path.exists()})
        finally:
            idx.close()
    return out


def build(root: Optional[PathLike] = None, rebuild: bool = False) -> List[str]:
    """Bring every index up to date (or make it again with `rebuild`). Says
    which were built, and counts nothing."""
    base = (Path(root) if root is not None else workspace_root()).resolve()
    hubs, names = Hubs(base), zone_names(base)
    fts = fts5_available()
    done = []
    for sc in [Scope("wiki", w) for w in WIKIS] + [Scope("zone", z) for z in names] + [Scope("system", "System")]:
        if not sc.folder(base).is_dir():
            continue
        idx = Index(base, sc, fts)
        try:
            Refresher(idx, hubs).run(rebuild=rebuild)
            done.append(sc.label())
        except sqlite3.Error:
            done.append("%s (failed)" % sc.label())
        finally:
            idx.close()
    return done


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

NOWHERE = Path("/nowhere/outside/the/workspace")


def cwd_project(root: Path) -> Optional[Path]:
    """The place a search made from the command line works in. It comes from
    the process's real folder alone, never from an argument, and only when
    that folder is really inside `root` (an explicit `--root` never changes
    the scope). The result is a folder `locate` places in a zone, None (the
    root) only for the workspace root or a folder inside `System/`, and
    NOWHERE, which reads nothing, for everything else.

    When the environment names the folder the session was opened in
    (`CLAUDE_PROJECT_DIR`; Codex sets nothing of the kind), the scope is the
    narrower of that folder and this one. A session that changed folder to
    somewhere outside the one it was opened in reads nothing, so `cd` to the
    workspace root does not widen a project session. A marker that is not a
    folder inside the workspace reads nothing."""
    try:
        here = Path.cwd().resolve()
    except OSError:
        return NOWHERE
    root = root.resolve()
    try:
        if workspace_root(here).resolve() != root:
            return NOWHERE
    except FileNotFoundError:
        return NOWHERE
    place = locate(root, here)
    if place is None:
        return NOWHERE
    marker = os.environ.get("CLAUDE_PROJECT_DIR")
    if marker:
        try:
            home = Path(marker).resolve()
            if locate(root, home) is None or not (home == here or home in here.parents):
                return NOWHERE
        except OSError:
            return NOWHERE
    if place.zone:
        return here
    # The root or System/. Only a folder really at the root or inside System/.
    rel = here.relative_to(root).parts
    return None if (not rel or rel[0] == "System") else NOWHERE


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="recall.py", description=__doc__.split("\n")[0])
    ap.add_argument("--root", help="the workspace (default: the one above this folder)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="bring every index up to date")
    b.add_argument("--rebuild", action="store_true", help="make every index again from the files")
    s = sub.add_parser("search", help="ranked search")
    s.add_argument("words")
    s.add_argument("--after", metavar="YYYY-MM-DD")
    s.add_argument("--zone")
    s.add_argument("--wiki")
    s.add_argument("--sessions", action="store_true")
    s.add_argument("--archived", action="store_true")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--json", action="store_true")
    t = sub.add_parser("stats", help="the indexes, and how many files you may read in each")
    e = sub.add_parser("extract", help="write new sessions to .sessions/ folders")
    e.add_argument("--claude", help="Claude Code's projects folder")
    e.add_argument("--codex", help="Codex's sessions folder")
    sub.add_parser("nightly", help="extract new sessions, then bring every index up to date")
    args = ap.parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else workspace_root()
    except FileNotFoundError as why:
        print(str(why), file=sys.stderr)
        return 2
    if not fts5_available():
        print(FTS_MISSING_SAID)
    if args.cmd == "build":
        print("built: " + ", ".join(build(root, args.rebuild)))
        return 0
    if args.cmd == "nightly":
        import recall_sessions
        print(recall_sessions.extract_all(root))
        print("built: " + ", ".join(build(root)))
        return 0
    if args.cmd == "extract":
        import recall_sessions
        print(recall_sessions.extract_all(root, args.claude, args.codex))
        return 0
    if args.cmd == "stats":
        project = cwd_project(root)
        for row in stats(project, root):
            print("%s: %d files%s (%s)" % (row["index"], row["files"], ", in memory" if row["memory"] else "",
                                          "fts5" if row["fts"] else "plain text"))
        return 0
    project = cwd_project(root)
    if project == NOWHERE:
        print("This folder is not a place Recall reads from, so nothing was searched. Open the session in a "
              "project, or at the workspace root.", file=sys.stderr)
    hits = search(args.words, project=project, after=args.after, zone=args.zone, wiki=args.wiki,
                  sessions=args.sessions, limit=args.limit, root=root, archived=args.archived)
    if args.json:
        print(json.dumps([dataclasses.asdict(h) for h in hits], indent=2))
        return 0
    older = [h for h in hits if h.grade != "working"]
    print("%d result%s for %r%s" % (len(hits), "" if len(hits) == 1 else "s", args.words,
                                    "; %d from older notes" % len(older) if older else ""))
    for n, h in enumerate(hits, 1):
        print("%d. %s  [%s%s%s]" % (n, h.title, h.source, ", " + h.date if h.date else "",
                                  ", from older notes" if h.grade == "dormant" else
                                  ", archived" if h.grade == "archived" else ""))
        print("   " + h.path)
        print("   " + h.snippet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
