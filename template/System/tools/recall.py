#!/usr/bin/env python3
"""Recall: a local keyword index over the notes, the wikis and past sessions.
The wall stands at the store, not at the result (#341, #358, #398).

    python3 System/tools/recall.py build [--root DIR] [--rebuild]
    python3 System/tools/recall.py search "words" [--scope S] [--after YYYY-MM-DD]
                                         [--zone Z] [--wiki W] [--sessions] [--archived] [--raw]
                                         [--limit N] [--json]
    python3 System/tools/recall.py read ID [--scope S]
    python3 System/tools/recall.py stats [--scope S]
    python3 System/tools/recall.py extract [--claude DIR] [--codex DIR]
    python3 System/tools/recall.py nightly

Python standard library only (Python 3.9 floor). A scope is a zone. For each
scope a session can hold, Recall writes one scope index holding the rows that
scope may read and no others. `garrick_lib.zone_of()` says which zone a record
is in and `garrick_lib.may_flow()` says whether the scope's zone may read it;
Recall keeps no wall test of its own. A row of a walled zone is never in
another zone's index file, so it cannot rank, count, order or be quoted: a
search across a wall is impossible, not refused.

The scopes: `root` (a session opened at the workspace root or in System/), and
one for each zone. A zone scope reads its own zone, every open zone, Knowledge
and System; the root reads everything. The index of a zone scope is a cache
beside the zone (`Zones/<Zone>/.recall.sqlite`). The root scope has no file: it
is made in memory, since a file of every zone's rows could be opened by any
session. Deleting every index loses nothing; `build` makes them again, and a
search brings its own scope's index up to date first, admitting or dropping
each changed file. An index is made again when a zone's flag changes. An index
never sits in a cloud-synced folder, because sync corrupts an open SQLite file;
one that would is kept in memory. No list of what was admitted is stored.

A past session's transcript takes the zone of the folder it was opened in. A
root session's transcript, and one that worked in another zone's folder, spans
zones: only the root scope reads it. A Meetings page uses its `zone:`; a page
with none, or two, or one the Zones table does not know, is in no scope.

A session's tools open only its scope's index. The command line takes a scope,
never a folder: with none it uses the scope of the folder the session was opened
in, and a scope it names may only be that one (a root session may name any).
`GARRICK_RECALL_SCOPE` can only narrow a root session, never widen another.
The root scope comes only from `CLAUDE_PROJECT_DIR` naming the root: a bare
working folder at the root or in `System/` is refused. This is a wall for what
Recall returns, not for a session that can read files itself.
`read(id)` answers only for an id that is in the scope index, and answers an
unknown id and a walled one the same way.

A raw record (a transcript, a frozen report) is indexed as chunks, but a search
ranks pages only, and goes to the raw chunks when no page matches, marking those
results "from the raw record" (#478). `--raw` puts the chunks back in the ranking
for one search. A wiki sets its own default in `Wikis/<Wiki>/schema.json`,
`"recall": {"raw": "fallback" | "always" | "never"}`, with `fallback` the default:
`always` for a wiki whose raw records are the only copy of the text. The chunks
are rows of the same scope index, so a search over them admits exactly what the
page search admits, and read() reads them as it reads a page.

Other code (the Ask agent's `search` tool) calls `search()` and `read()`. The
signature of `search()` and the fields of `Result` are stable.
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
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fade  # noqa: E402
from garrick_lib import (  # noqa: E402
    NOT_LIVE_DIR_RE,
    SKIP_DIRS,
    UNZONED,
    may_flow,
    load_context,
    parse_frontmatter_text,
    workspace_root,
    zone_of,
)

PathLike = Union[str, Path]

INDEX_NAME = ".recall.sqlite"
SCOPE_ENV = "GARRICK_RECALL_SCOPE"      # a session started with its scope names it here; a folder cannot change it
SESSIONS_DIR = ".sessions"
TOKENIZER = "unicode61 remove_diacritics 2"
SCHEMA_VERSION = "4"
CHUNK_CHARS = 4000
RRF_K = 60
RAW_WEIGHT = 0.5
RAW_MODES = ("fallback", "always", "never")    # a wiki's `"recall": {"raw": ...}`; the first is the default (#478)
RAW_SAID = "from the raw record"
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
NEAR_DICE = 0.7                # how alike two spellings must be (shared trigrams) to count as one word
NEAR_ROWS = 200




@dataclasses.dataclass(frozen=True)
class Result:
    """One hit. `path` is relative to the workspace root, with forward slashes.
    `source` names where it came from: a zone ("Work"), a wiki ("Meetings",
    "Knowledge") or "sessions". `date` is YYYY-MM-DD or "". `grade` is
    "working", "dormant" or "archived"; a dormant hit is "from older notes".
    `raw` is True for a raw record's chunk, "from the raw record" (#478), and
    `owner` then names the page that cites it: the record is in the zone that page is in."""
    id: str
    path: str
    title: str
    date: str
    source: str
    snippet: str
    score: float
    grade: str = "working"
    raw: bool = False
    owner: str = ""


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


def trigram_available() -> bool:
    """Whether this Python's SQLite has the FTS5 trigram tokenizer (3.34 and
    later). Tests replace this to try the fallback."""
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE t USING fts5(a, tokenize='trigram')")
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


# ---------------------------------------------------------------------------
# Scopes: what one session may hold
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Scope:
    """What one scope index covers. `root` reads every zone; a zone scope reads
    its own zone, every open zone, Knowledge and System."""
    kind: str                  # root, zone
    zone: str = ""             # the zone's own spelling; "" for root

    @property
    def key(self) -> str:
        return "root" if self.kind == "root" else self.zone.lower()

    def label(self) -> str:
        return self.key

    def file(self, root: Path) -> Path:
        if self.kind == "root":
            return root / "System" / INDEX_NAME
        return root / "Zones" / self.zone / INDEX_NAME

    @property
    def zones(self) -> Set[str]:
        return {self.zone.lower()} if self.zone else set()


ROOT = Scope("root")


def zone_names(root: Path) -> List[str]:
    top = root / "Zones"
    return sorted(p.name for p in top.iterdir() if p.is_dir() and not p.name.startswith(".")) if top.is_dir() else []


def scopes_of(root: Path, ctx: dict) -> List[Scope]:
    """Every scope a session can hold: the root, then one for each zone."""
    return [ROOT] + [Scope("zone", zone) for zone in zone_names(root)]


def project_path(root: Path, place: Place) -> str:
    parts = ["Zones", place.zone, place.project] + (["Threads", place.thread] if place.thread else [])
    return "/".join(parts)


def scope_for_project(root: Path, ctx: dict, project: Optional[PathLike], cache: Optional[dict] = None) -> Optional[Scope]:
    """The scope a session opened in `project` holds. Only a literal None is
    the root. An empty string, ".", a place no zone owns (a wiki, Zones/
    itself, a folder outside) or a zone's top level: no scope at all. A
    folder in a zone holds that zone's scope."""
    if project is None:
        return ROOT
    if str(project).strip() in ("", ".") or Path(project) == Path("."):
        return None
    place = locate(root, project)
    if place is None:
        return None
    if not place.zone:
        return ROOT
    if not place.project:
        return None
    zone = next((z for z in zone_names(root) if z.lower() == place.zone.lower()), None)
    return Scope("zone", zone) if zone else None


def scope_named(root: Path, ctx: dict, key: str) -> Optional[Scope]:
    key = (key or "").strip().lower()
    return next((s for s in scopes_of(root, ctx) if s.key == key), None)


def policy_stamp(ctx: dict, scope: Scope) -> str:
    """What the flags were when an index was made: a zone changing between
    walled and open makes every index again, because a file that was admitted
    may no longer be."""
    flags = sorted((z, bool(w)) for z, w in (ctx.get("zone_walled") or {}).items())
    return hashlib.sha1(json.dumps([scope.key, flags]).encode()).hexdigest()


# ---------------------------------------------------------------------------
# The index file
# ---------------------------------------------------------------------------

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
CREATE TABLE docs(id INTEGER PRIMARY KEY, path TEXT, kind TEXT, src TEXT, home TEXT, label TEXT, title TEXT,
                  date TEXT, grade TEXT, superseded INTEGER, owner TEXT, body TEXT);
CREATE TABLE claims(raw TEXT, page TEXT, PRIMARY KEY(raw, page));
CREATE INDEX docs_path ON docs(path);
CREATE INDEX docs_owner ON docs(owner);
"""


class Index:
    """One scope's index file. It holds the rows its scope may read and no
    others: a refresh admits a file through the zone rule or leaves it out."""

    def __init__(self, root: Path, scope: Scope, fts: bool, tri: bool, ctx: dict):
        self.root, self.scope, self.ctx = root, scope, ctx
        self.fts = fts
        self.tri = bool(tri and fts)
        self.stamp = policy_stamp(ctx, scope)
        self.path = scope.file(root)
        self.con = self._open()
        try:
            self.con.execute("PRAGMA secure_delete=ON")      # a row that leaves is overwritten, not just unlinked
        except sqlite3.Error:
            pass

    YOUNG_SECONDS = 15.0

    def _open(self) -> sqlite3.Connection:
        folder = self.path.parent
        if not folder.is_dir() or self.scope.kind == "root":
            return self._memory()       # the root scope holds every zone's rows: never a file on disk
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
        tmp = self.path.with_name("%s.new-%d" % (self.path.name, os.getpid()))
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

    def reset(self) -> None:
        """Make the index again, empty, in a new file: nothing that was in the
        old one stays in any page of it."""
        try:
            self.con.close()
        except sqlite3.Error:
            pass
        try:
            self.con = self._replace() if self.path.parent.is_dir() and not synced(self.path.parent) \
                and safe_to_write(self.path) else self._memory()
        except (sqlite3.Error, OSError):
            self.con = self._memory()
        try:
            self.con.execute("PRAGMA secure_delete=ON")
        except sqlite3.Error:
            pass

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

    def _meta(self) -> List[Tuple[str, str]]:
        return [("version", SCHEMA_VERSION), ("tokenizer", TOKENIZER), ("fts", "1" if self.fts else "0"),
                ("tri", "1" if self.tri else "0"), ("policy", self.stamp), ("scope", self.scope.key)]

    def _state(self, con: sqlite3.Connection) -> str:
        """ready, stale (made by another version, setting or set of walls), or
        empty (no meta table: unreadable, or still being made)."""
        try:
            rows = dict(con.execute("SELECT key, value FROM meta").fetchall())
        except sqlite3.Error:
            return "empty"
        return "ready" if rows == dict(self._meta()) else "stale"

    def _create(self, con: sqlite3.Connection) -> None:
        con.executescript(SCHEMA)
        if self.fts:
            con.execute("CREATE VIRTUAL TABLE fts USING fts5(title, body, content='docs', content_rowid='id', "
                        "tokenize='%s')" % TOKENIZER)
        if self.tri:
            con.execute("CREATE VIRTUAL TABLE fts_tri USING fts5(title, body, content='docs', content_rowid='id', "
                        "tokenize='trigram')")
        con.executemany("INSERT INTO meta VALUES (?, ?)", self._meta())
        con.commit()

    def close(self) -> None:
        try:
            self.con.close()
        except sqlite3.Error:
            pass

    # -- rows ---------------------------------------------------------------

    def tables(self) -> List[str]:
        return (["fts"] if self.fts else []) + (["fts_tri"] if self.tri else [])

    def drop(self, path: str) -> None:
        rows = self.con.execute("SELECT id, title, body FROM docs WHERE path=?", (path,)).fetchall()
        for table in self.tables():
            for i, title, body in rows:
                self.con.execute("INSERT INTO %s(%s, rowid, title, body) VALUES('delete', ?, ?, ?)" % (table, table),
                                 (i, title, body))
        self.con.execute("DELETE FROM docs WHERE path=?", (path,))
        self.con.execute("DELETE FROM files WHERE path=?", (path,))
        self.con.execute("DELETE FROM claims WHERE page=?", (path,))

    def add(self, path: str, kind: str, src: str, home: str, label: str, title: str, date: str, grade: str,
            superseded: bool, owner: str, bodies: List[str]) -> None:
        for body in bodies:
            i = self.con.execute("INSERT INTO docs(path, kind, src, home, label, title, date, grade, superseded, "
                                 "owner, body) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                 (path, kind, src, home, label, title, date, grade, int(superseded), owner,
                                  body)).lastrowid
            for table in self.tables():
                self.con.execute("INSERT INTO %s(rowid, title, body) VALUES (?,?,?)" % table, (i, title, body))


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


def session_projects(head: str) -> Optional[List[str]]:
    """The projects a session's header names: its `project:` line is a one-line
    JSON list of strings (a name may hold `#`, `:` or a quote). None when the
    line is there and is anything else. No line is no project."""
    m = re.search(r"(?m)^project:[ \t]*(.*)$", head.split("\n---", 2)[0] if head.startswith("---") else "")
    if not m:
        return []
    try:
        value = json.loads(m.group(1))
    except ValueError:
        return None
    return value if isinstance(value, list) and all(isinstance(v, str) and v for v in value) else None


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
    """Brings one scope index up to date with the files it covers, by modified
    time and size, and by what a file takes from another (the page that owns a
    raw record). A file is admitted by may_flow() from its zone to the scope's,
    or it is not in the index: the row for a file that stops being admitted is
    dropped, and the index is made again so that nothing of it is left in the
    file."""

    def __init__(self, idx: Index):
        self.idx, self.root, self.ctx = idx, idx.root, idx.ctx
        self.scope = idx.scope
        self.cache: dict = {}

    def run(self, rebuild: bool = False) -> None:
        if rebuild:
            self.idx.reset()
        con = self.idx.con
        known = {r[0]: (r[1], r[2], r[3]) for r in con.execute("SELECT path, mtime, size, attrs FROM files")}
        seen: Set[str] = set()
        pages: List[Tuple[str, Path]] = []
        raws: List[Tuple[str, Path]] = []
        for wiki in WIKIS:
            p, r = wiki_entries(self.root, wiki)
            pages += p
            raws += r
        self._each(pages, known, seen, self.page_derived, self.page)
        self._each(raws, known, seen, self.raw_derived, self.raw)
        for zone in zone_names(self.root):
            if self.scope.kind == "root" or zone == self.scope.zone or self.admit(zone_of(self.root, "Zones/%s/x" % zone)):
                self._each(zone_entries(self.root, zone), known, seen, self.note_derived, self.note)
        if self.scope.kind == "root":
            self._each(system_entries(self.root), known, seen, self.session_derived, self.session)
        gone = set(known) - seen
        if gone and any((self.root / g).exists() for g in gone):
            # A file is still there but this scope no longer admits it. Its row would leave
            # bytes in the file; make the index again, so that a walled row is in no page of it.
            self.idx.reset()
            self.cache = {}
            self.run()
            return
        for path in gone:
            self.idx.drop(path)
        con.commit()

    def _each(self, entries, known, seen, derived, index) -> None:
        for rel, path in entries:
            try:
                m, s = stamp(path)
            except OSError:
                continue
            attrs = derived(rel, path)
            if attrs is None:
                continue                            # not admitted: no row, no trace
            old = known.get(rel)
            if old and old[0] == m and old[1] == s and old[2] == attrs:
                seen.add(rel)
                continue
            self.idx.drop(rel)
            if index(rel, path):
                seen.add(rel)
                self.idx.con.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?)", (rel, m, s, attrs))

    # -- the one question ----------------------------------------------------

    def admit(self, zone: Optional[str]) -> bool:
        """May this scope read a record of `zone`? The root reads every zone
        the Zones table holds; a page with no zone it can name is in no scope.
        A zone scope asks may_flow(). None is no zone: Knowledge and System."""
        if zone == UNZONED:
            return False
        if self.scope.kind == "root":
            return zone is None or zone in (self.ctx.get("zone_walled") or {})
        return may_flow(self.ctx, zone, self.scope.zone)

    def admit_session(self, zone: Optional[str]) -> bool:
        """A past session takes the zone of the folder it was opened in. One that spans zones
        (a root session, or one that worked in another zone's folder: `zone` is "") is read
        from the root scope only, since what it read is known only from what it typed."""
        if zone is None:
            return False
        if zone == "":
            return self.scope.kind == "root"
        return self.admit(zone)

    # -- zone notes and sessions --------------------------------------------

    def note_derived(self, rel: str, path: Path) -> Optional[str]:
        if SESSIONS_DIR in rel.split("/"):
            return self.session_derived(rel, path)
        zone = zone_of(self.root, rel)
        if not self.admit(zone):
            return None
        return json.dumps([zone, fingerprint(path)])

    def note(self, rel: str, path: Path) -> bool:
        if SESSIONS_DIR in rel.split("/"):
            return self.session(rel, path)
        text = read_text(path)
        if text is None:
            return False
        if not self.admit(zone_of(self.root, rel)):
            return False
        fm = parse_frontmatter_text(text)
        body = body_of(text)
        zone = rel.split("/")[1]
        stat_date = datetime.date.fromtimestamp(path.stat().st_mtime)
        date = next((d for d in (fade.read_date(fm.get(f)) for f in ("date", "updated", "created")) if d), None) \
            or fade.name_date(path.name) or stat_date
        title = str(fm.get("title") or "") or first_heading(body) or path.stem
        grade = "archived" if "archive" in [x.lower() for x in rel.split("/")[:-1]] else "working"
        self.idx.add(rel, "note", "zone", "zone:" + zone.lower(), zone, title, iso(date), grade,
                     bool(str(fm.get("superseded") or "").strip()), "", [body.strip()])
        return True

    def session_zone(self, path: Path, rel: str) -> Tuple[Optional[str], dict]:
        """The zone of a session: that of the folder it sits in. "" (spans zones) when it sits in System/,
        when its `project:` line does not read back plainly, or when it worked in a project of another zone.
        None when it cannot be read."""
        try:
            with open(str(path), encoding="utf-8", errors="replace") as fh:
                head = fh.read(4000)
        except OSError:
            return None, {}
        fm = parse_frontmatter_text(head)
        zone = (locate(self.root, path) or Place("", "", "")).zone
        given = session_projects(head)
        if not zone or given is None:
            return "", fm
        for g in given:
            place = locate(self.root, str(g))
            if place is None or not place.project or place.zone != zone:
                return "", fm
        return zone_of(self.root, rel), fm

    def session_derived(self, rel: str, path: Path) -> Optional[str]:
        zone, _ = self.session_zone(path, rel)
        if not self.admit_session(zone):
            return None
        return json.dumps([zone, fingerprint(path)])

    def session(self, rel: str, path: Path) -> bool:
        text = read_text(path)
        if text is None:
            return False
        zone, fm = self.session_zone(path, rel)
        if not self.admit_session(zone):
            return False
        zone = (locate(self.root, path) or Place("", "", "")).zone
        title = str(fm.get("title") or "") or path.stem
        self.idx.add(rel, "chunk", "session", "zone:" + zone.lower() if zone else "system",
                     zone if zone else "sessions", title, iso(fade.name_date(path.name)), "working", False, "",
                     chunks(body_of(text)))
        return True

    # -- wiki pages and their raw records -----------------------------------

    def page_derived(self, rel: str, path: Path) -> Optional[str]:
        zone = self.page_zone(rel, path)
        if not self.admit(zone):
            return None
        return json.dumps([zone, fingerprint(path)])

    def page_zone(self, rel: str, path: Path) -> Optional[str]:
        """The zone of a wiki page: a Meetings page's `zone:`, UNZONED when it has none. A Knowledge page is in
        no zone; one that carries a `zone:` or a party anyway is someone's, not published: UNZONED, in no scope."""
        zone = zone_of(self.root, rel)
        if rel.split("/")[1] == "Knowledge":
            text = read_text(path)
            fm = parse_frontmatter_text(text) if text is not None else {"zone": 1}
            if any(fm.get(k) for k in ("zone", "party", "parties")):
                return UNZONED
        return zone

    def page(self, rel: str, path: Path) -> bool:
        wiki = rel.split("/")[1]
        text = read_text(path)
        if text is None:
            return False
        fm = parse_frontmatter_text(text)
        if not self.admit(self.page_zone(rel, path)):
            return False                            # a page of a zone this scope may not read, or of none
        body = body_of(text)
        date = next((d for d in (fade.read_date(fm.get(f)) for f in fade.DATE_FIELDS[wiki]) if d), None) \
            or fade.name_date(path.name)
        title = str(fm.get("title") or "") or first_heading(body) or path.stem
        self.idx.add(rel, "note", wiki.lower(), wiki.lower(), wiki, title, iso(date), grade_of(rel, wiki),
                     bool(str(fm.get("superseded") or "").strip()), "", [body.strip()])
        if wiki == "Knowledge" and fm.get("raw"):
            probe = fade.Page(rel, wiki, grade_of(rel, wiki), "")
            fade.find_raw(self.root / "Wikis" / wiki, probe, fade.link_target(fm.get("raw")))
            if probe.raw:
                self.idx.con.execute("INSERT OR REPLACE INTO claims VALUES (?,?)", (probe.raw, rel))
        return True

    def owner_row(self, rel: str):
        """(first citing page, its title, date, superseded) for a raw record, or
        None unless every page that cites it is in this index: a page this
        scope may not read keeps the record out. A Knowledge record has the
        page that names it as its `raw:`."""
        con = self.idx.con
        if rel.split("/")[1] == "Knowledge":
            pages = sorted(self.claims().get(rel, []))      # every page that names it, an unadmitted one included
        else:
            cites = self.cites()
            if self.stem_count(Path(rel).stem.lower()) != 1:
                return None                         # the citing index knows a record by its stem alone: a stem two files share has no one owner
            pages = sorted({r for r in (_rel(self.root, p) for p in cites.get(Path(rel).stem.lower(), [])) if r})
        if not pages:
            return None
        first = None
        for page in pages:
            row = con.execute("SELECT title, date, superseded FROM docs WHERE path=? LIMIT 1", (page,)).fetchone()
            if row is None:
                return None
            first = first or (page,) + tuple(row)
        return first

    def claims(self) -> Dict[str, List[str]]:
        """Each Knowledge raw record to the pages that name it as their `raw:`, at every grade and whether or not this
        scope may read the page, made once a run: a page this scope may not read keeps its record out, as for Meetings."""
        key = ("claims", str(self.root))
        if key not in self.cache:
            found: Dict[str, List[str]] = {}
            pages, _ = wiki_entries(self.root, "Knowledge")
            for rel, path in pages:
                text = read_text(path)
                fm = parse_frontmatter_text(text) if text is not None else {}
                if not fm.get("raw"):
                    continue
                probe = fade.Page(rel, "Knowledge", grade_of(rel, "Knowledge"), "")
                fade.find_raw(self.root / "Wikis" / "Knowledge", probe, fade.link_target(fm.get("raw")))
                if probe.raw:
                    found.setdefault(probe.raw, []).append(rel)
            self.cache[key] = found
        return self.cache[key]

    def cites(self) -> Dict[str, List[Path]]:
        """Each raw record's stem to the Meetings pages that cite it, at every grade, made once a run."""
        key = ("cites", str(self.root))
        if key not in self.cache:
            index: Dict[str, List[Path]] = {}
            pages: List[Path] = []
            for grade in ("", "dormant", "archive"):
                wiki = self.root / "Wikis" / "Meetings" / grade / "wiki"
                pages += sorted(wiki.rglob("*.md")) if wiki.is_dir() else []
            for page in pages:
                text = read_text(page)
                if text is None:
                    continue
                for stem in set(re.findall(r"\[\[(?:raw/)?([^\]|#]+?)(?:\.\w+)?(?:[|#][^\]]*)?\]\]", text)) | \
                        set(re.findall(r"raw/([^\s\]|#)\"']+?)(?:\.\w+)?(?=[\s\]|#)\"']|$)", text)):
                    index.setdefault(Path(stem).name.lower(), []).append(page)
            self.cache[key] = index
        return self.cache[key]

    def stem_count(self, stem: str) -> int:
        counts = self.cache.get(("rawstems", str(self.root)))
        if counts is None:
            counts = {}
            base = self.root / "Wikis"
            try:
                for wiki in base.iterdir():
                    raw = wiki / "raw"
                    if raw.is_dir() and not raw.is_symlink():
                        for dirpath, dirs, files in os.walk(str(raw)):
                            for f in files:
                                key = Path(f).stem.lower()
                                counts[key] = counts.get(key, 0) + 1
            except OSError:
                pass
            self.cache[("rawstems", str(self.root))] = counts
        return counts.get(stem, 0)

    def raw_derived(self, rel: str, path: Path) -> Optional[str]:
        owner = self.owner_row(rel)           # a record is read where the pages that cite it are: all of them admitted here
        if owner is None:
            return None
        named = sorted(self.claims().get(rel, [])) if rel.split("/")[1] == "Knowledge" else []
        return json.dumps([owner, named] if named else [owner])     # a new claimer, walled or not, changes the row

    def raw(self, rel: str, path: Path) -> bool:
        owner = self.owner_row(rel)
        text = read_text(path) if owner else None
        if owner is None or text is None:
            return False                            # a record no admitted page owns
        page, title, date, superseded = owner
        wiki = rel.split("/")[1]
        self.idx.add(rel, "chunk", "raw", wiki.lower(), wiki, title, date, grade_of(rel, wiki), bool(superseded),
                     page, chunks(text))
        return True


def _rel(root: Path, p: Path) -> str:
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return ""


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


def tokens(text: str) -> List[str]:
    return re.findall(r"\w+", plain(text), re.UNICODE)


# ---------------------------------------------------------------------------
# Names: a word that settles to a party, person or alias is searched in every form
# ---------------------------------------------------------------------------

def spelling_forms(ctx: dict) -> Dict[str, List[str]]:
    """Every spelling the Parties, People and Aliases tables give a name, with
    and without spaces, under each of them. "Acme Corp", "acme corp" and
    "acmecorp" are three tokenizations of one name, and the tokenizer reads
    them as different words."""
    def forms(name: str) -> Set[str]:
        toks = tokens(name)
        return {" ".join(toks), "".join(toks)} if toks else set()

    groups: List[Set[str]] = []
    for e in ctx.get("parties", {}).values():
        groups.append(forms(str(e.get("party") or "")))
    for p in ctx.get("people", []):
        groups.append(forms(str(p.get("name") or "")))
    for heard, means in ctx.get("aliases", {}).items():
        groups.append(forms(heard) | forms(str(means)))
    table: Dict[str, Set[str]] = {}
    for g in groups:
        g = {f for f in g if f}
        if len(g) < 1:
            continue
        merged = set(g)
        for f in list(g):
            merged |= table.get(f, set())
        for f in merged:
            table[f] = merged
    return {k: sorted(v) for k, v in table.items() if len(v) > 1}


def build_terms(words: List[str], forms: Dict[str, List[str]]) -> List[List[str]]:
    """The query as terms, each a list of the spellings that count as it. Runs
    of up to three words that settle to a known name are one term."""
    ws = [" ".join(tokens(w)) for w in words]
    ws = [w for w in ws if w]
    out: List[List[str]] = []
    i = 0
    while i < len(ws):
        for n in (3, 2, 1):
            seg = ws[i:i + n]
            if len(seg) < n:
                continue
            hit = forms.get(" ".join(seg)) or forms.get("".join(seg))
            if hit:
                out.append(sorted(set(hit) | {" ".join(seg)}))
                i += n
                break
        else:
            out.append([ws[i]])
            i += 1
    return out


def fts_query(variants: Iterable[str]) -> str:
    return " OR ".join('"%s"' % v for v in variants if v)


def dice(a: str, b: str) -> float:
    ta = {a[i:i + 3] for i in range(len(a) - 2)}
    tb = {b[i:i + 3] for i in range(len(b) - 2)}
    return 2.0 * len(ta & tb) / (len(ta) + len(tb)) if ta and tb else 0.0


def widen(idx: "Index", terms: List[List[str]]) -> List[List[str]]:
    """For a term this index has no row for, the near spellings it does have:
    the trigram table finds the rows that share most of the word's trigrams,
    and the words in them that are alike enough (Dice over trigrams) join the
    term. Only the scope's own rows are ever looked at."""
    if not (idx.fts and idx.tri):
        return terms
    out = []
    for variants in terms:
        try:
            exact = idx.con.execute("SELECT 1 FROM fts WHERE fts MATCH ? LIMIT 1", (fts_query(variants),)).fetchone()
        except sqlite3.Error:
            exact = True
        if exact:
            out.append(variants)
            continue
        near: Set[str] = set()
        for v in variants:
            if " " in v or len(v) < 4:
                continue
            tri = sorted({v[i:i + 3] for i in range(len(v) - 2)})
            try:
                rows = idx.con.execute(
                    "SELECT d.title, d.body FROM fts_tri JOIN docs d ON d.id = fts_tri.rowid WHERE fts_tri MATCH ? "
                    "ORDER BY fts_tri.rank LIMIT %d" % NEAR_ROWS, (" OR ".join('"%s"' % t for t in tri),)).fetchall()
            except sqlite3.Error:
                continue
            for title, body in rows:
                for tok in set(tokens(title)) | set(tokens(body)):
                    if tok != v and abs(len(tok) - len(v)) <= 2 and dice(v, tok) >= NEAR_DICE \
                            and re.sub(r"\d", "", tok) != re.sub(r"\d", "", v):
                        near.add(tok)
        out.append(variants + sorted(near)[:8])
    return out


@dataclasses.dataclass
class Hit:
    rowid: int
    path: str
    kind: str
    src: str
    label: str
    title: str
    date: str
    grade: str
    superseded: int
    owner: str
    rank: int = 0


BM25_K1 = 1.2
BM25_B = 0.75
MAX_MATCHED = 20000


def occurrences(variant: str, uni: collections.Counter, grams: Dict[int, collections.Counter],
                toks: List[str]) -> int:
    vt = variant.split()
    if len(vt) == 1:
        return uni.get(vt[0], 0)
    n = len(vt)
    if n not in grams:
        grams[n] = collections.Counter(tuple(toks[i:i + n]) for i in range(len(toks) - n + 1))
    return grams[n].get(tuple(vt), 0)


def term_tf(variants: List[str], title: List[str], body: List[str], cache: dict) -> Tuple[int, int]:
    if "t" not in cache:
        cache["t"] = (collections.Counter(title), {})
        cache["b"] = (collections.Counter(body), {})
    tt = sum(occurrences(v, cache["t"][0], cache["t"][1], title) for v in variants)
    tb = sum(occurrences(v, cache["b"][0], cache["b"][1], body) for v in variants)
    return tt, tb


def candidates(idx: Index, terms: List[List[str]], kind: str, grades: List[str], after: Optional[str],
               sessions: bool, wiki: Optional[str], zone: Optional[str] = None,
               raw_homes: Optional[Iterable[str]] = None) -> List[Hit]:
    """Best rows of one list in the scope's index, best first. Every row in
    the index is one the scope may read, so the ranking (BM25) takes its
    document count, document frequencies and average length from rows that
    were all admitted: a walled row, never being here, changes neither what is
    found nor in what order."""
    where = ["d.kind = ?", "d.grade IN (%s)" % ",".join("?" * len(grades))]
    args: list = [kind] + list(grades)
    if kind == "chunk":
        homes = sorted(raw_homes or ())         # a raw record's chunks only for the wikis this search may rank them in (#478)
        where.append("(d.src != 'raw'" + (" OR d.home IN (%s))" % ",".join("?" * len(homes)) if homes else ")"))
        args += homes
    if not sessions:
        where.append("d.src != 'session'")
    if wiki:
        where.append("(d.home = ? OR d.src = 'session')")
        args.append(wiki.lower())
    if zone:
        where.append("(d.home NOT LIKE 'zone:%' OR d.home = ?)")
        args.append("zone:" + zone.lower())
    if after:
        where.append("d.date != '' AND d.date >= ?")
        args.append(after)
    cond = " AND ".join(where)
    cols = "d.id, d.path, d.kind, d.src, d.label, d.title, d.date, d.grade, d.superseded, d.owner"
    texts: Dict[int, Tuple[tuple, List[str], List[str], int]] = {}
    df = [0] * len(terms)
    if idx.fts:
        total, chars = idx.con.execute("SELECT COUNT(*), COALESCE(SUM(length(d.title) + length(d.body)), 0) "
                                       "FROM docs d WHERE " + cond, args).fetchone()
        for n, variants in enumerate(terms):
            df[n] = idx.con.execute(
                "SELECT COUNT(*) FROM fts JOIN docs d ON d.id = fts.rowid WHERE fts MATCH ? AND " + cond,
                [fts_query(variants)] + args).fetchone()[0]
        flat = [v for variants in terms for v in variants]
        rows = idx.con.execute("SELECT %s, d.body FROM fts JOIN docs d ON d.id = fts.rowid WHERE fts MATCH ? "
                               "AND %s ORDER BY d.id LIMIT %d" % (cols, cond, MAX_MATCHED),
                               [fts_query(flat)] + args).fetchall()
        for r in rows:
            texts[r[0]] = (r[:-1], tokens(r[5]), tokens(r[-1]), len(r[5]) + len(r[-1]))
    else:
        total = chars = 0
        for r in idx.con.execute("SELECT %s, d.body FROM docs d WHERE %s" % (cols, cond), args):
            total += 1
            chars += len(r[5]) + len(r[-1])
            title, body = tokens(r[5]), tokens(r[-1])
            cache: dict = {}
            hit = False
            for n, variants in enumerate(terms):
                if sum(term_tf(variants, title, body, cache)):
                    df[n] += 1
                    hit = True
            if hit:
                texts[r[0]] = (r[:-1], title, body, len(r[5]) + len(r[-1]))
    avg = (chars / total) if total else 1.0
    scored = []
    for rowid, (head, title, body, length) in texts.items():
        cache = {}
        score = 0.0
        for n, variants in enumerate(terms):
            tt, tb = term_tf(variants, title, body, cache)
            tf = 2.0 * tt + tb
            if not tf:
                continue
            idf = math.log(1.0 + (total - df[n] + 0.5) / (df[n] + 0.5))
            score += idf * tf * (BM25_K1 + 1.0) / (tf + BM25_K1 * (1.0 - BM25_B + BM25_B * length / avg))
        if score > 0:
            scored.append((score, Hit(*head)))
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


def snippet(idx: Index, terms: List[List[str]], rowid: int) -> str:
    flat = [v for variants in terms for v in variants]
    if idx.fts:
        row = idx.con.execute("SELECT snippet(fts, 1, '', '', ' ... ', 24) FROM fts WHERE fts MATCH ? AND rowid = ?",
                              (fts_query(flat), rowid)).fetchone()
        if row and row[0] and row[0].strip():
            return " ".join(row[0].split())
    body = (idx.con.execute("SELECT body FROM docs WHERE id=?", (rowid,)).fetchone() or ("",))[0]
    low = plain(body)
    at = min([low.find(v) for v in flat if low.find(v) >= 0] or [0])
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

def open_scope(root: Path, scope: Scope, ctx: dict, fts: bool, tri: bool) -> Optional[Index]:
    """The scope's index, brought up to date: each changed file is admitted
    or dropped by the zone rule before anything is searched."""
    folder = scope.file(root).parent
    if not folder.is_dir():
        return None
    purge_orphans(root, ctx)
    idx = Index(root, scope, fts, tri, ctx)
    try:
        Refresher(idx).run()
    except sqlite3.Error:
        idx.close()
        return None
    return idx


def purge_orphans(root: Path, ctx: dict) -> None:
    """Remove every index file that is not a current scope's: the root's file of an older version, a side's file of the party walls. Such a
    file holds rows its scope would no longer admit."""
    live = {str(sc.file(root)) for sc in scopes_of(root, ctx) if sc.kind != "root"}
    folders = [root / "System"] + [root / "Zones" / z for z in zone_names(root)]
    for folder in folders:
        try:
            names = os.listdir(str(folder))
        except OSError:
            continue
        for name in names:
            if not name.startswith(INDEX_NAME) or ".new-" in name:
                continue
            base_name = re.sub(r"-(journal|wal|shm)$", "", name)
            if str(folder / base_name) in live:
                continue
            try:
                os.remove(str(folder / name))
            except OSError:
                pass


def raw_mode_of(root: Path, wiki: str) -> str:
    """How a wiki's raw records are searched, from `"recall": {"raw": ...}` in `Wikis/<wiki>/schema.json`:
    `fallback` unless it reads as one of RAW_MODES (#478)."""
    try:
        data = json.loads((root / "Wikis" / wiki / "schema.json").read_text(encoding="utf-8"))
        mode = data["recall"]["raw"]
    except (OSError, ValueError, KeyError, TypeError):
        return RAW_MODES[0]
    return mode if mode in RAW_MODES else RAW_MODES[0]


def reach_of(root: Path) -> str:
    try:
        return fade.settings(root)["reach"]
    except Exception:
        return "working"


def resolve(base: Path, ctx: dict, project: Optional[PathLike], scope: Optional[Union[Scope, str]]) -> Optional[Scope]:
    """The one scope a call may use. A folder gives its zone's scope; a scope that is also asked for must be that one, unless the folder is
    the root's, which may take any scope it names."""
    mine = scope_for_project(base, ctx, project)
    if scope is None:
        return mine
    if mine is None:
        return None
    asked = scope if isinstance(scope, Scope) else scope_named(base, ctx, str(scope))
    if asked is None:
        return None
    if mine.kind == "root" or asked == mine:
        return asked
    return None


def search(words: str, *, project: Optional[PathLike], after: Optional[str] = None,
           zone: Optional[str] = None, wiki: Optional[str] = None, sessions: bool = False,
           limit: int = 10, root: Optional[PathLike] = None, archived: bool = False,
           scope: Optional[Union[Scope, str]] = None, raw: Optional[Union[str, bool]] = None) -> List[Result]:
    """Ranked hits for `words`, best first, at most `limit`.

    `project` is the folder of the project the session works in (absolute, or
    relative to the workspace root), for example `Zones/Work/Acme`. It gives
    the session's scope: its zone's. `None` means a session opened at the
    workspace root or in `System/`, which holds the root scope, every zone and
    `System/.sessions/`.
    Only a literal `None` is that: an empty string, ".", a folder that is not
    below the workspace, a place that belongs to no zone (a wiki, `Zones/`
    itself), a zone's top level, or a zone that does not exist returns [].
    `scope` (a `Scope`, or its key such as `work`) names the scope instead, for a caller that holds one: it
    may only be the folder's own, unless the folder is the root's.

    `after` keeps only hits dated on or after YYYY-MM-DD. `zone` keeps one
    zone's notes (and the wikis'): a session of one zone may name its own and
    no other, since a search never reaches past its scope. `wiki` limits the
    search to one wiki (with `sessions=True` the sessions are added to it, and
    no zone notes). `sessions=True` adds extracted sessions: the scope's own
    zone's, or from the root all of them. `archived=True` adds archived pages
    after the rest. `root` is the workspace root; it defaults to the one above
    `project`, or above the current folder.

    THE WALL IS AT THE STORE. Only the scope's own index is opened, and it
    holds the rows the zone rule admitted for the scope and no others, so no
    result, count, rank or snippet can depend on a walled row. Nothing is
    filtered after the search.

    Names are expanded before the query: a word that settles to a party,
    person or alias in `System/context.md` is searched in every spelling the
    tables give, with and without spaces; a word the scope's rows do not have is
    widened to near spellings through a trigram table where SQLite carries one.

    Raw records (#478): by default only pages are ranked, and the raw chunks of
    a wiki are searched when no page matches, each result marked `raw` ("from
    the raw record"). `raw` overrides every wiki's own setting, `"always"` (or
    True) putting the chunks into the ranking, `"never"` leaving them out; None
    follows each wiki's `"recall": {"raw": ...}`. The chunks are rows of the same
    scope index, so what they may show is what the pages may show.

    Working pages are searched first. Dormant pages join only when the
    working ones return fewer than `limit` and the `reach` setting allows it;
    their `grade` is "dormant" ("from older notes"). Archived pages join only
    with `archived=True`.
    """
    plain_words = query_words(words or "")
    if not plain_words or limit < 1:
        return []
    try:
        base = Path(root) if root is not None else workspace_root(
            project if project is not None and Path(project).is_absolute() else None)
    except FileNotFoundError:
        return []
    base = base.resolve()
    ctx = load_context(base)
    held = resolve(base, ctx, project, scope)
    if held is None:
        return []
    if zone and held.kind == "zone" and zone.lower() != held.zone.lower():
        return []
    if wiki:
        wiki = next((w for w in WIKIS if w.lower() == wiki.lower()), None)
        if wiki is None:
            return []
    idx = open_scope(base, held, ctx, fts5_available(), trigram_available())
    if idx is None:
        return []
    try:
        terms = widen(idx, build_terms(plain_words, spelling_forms(ctx)))
        today = datetime.date.today()
        tiers = [["working"]]
        if reach_of(base) == "dormant":
            tiers.append(["dormant"])
        if archived:
            tiers.append(["archived"])
        if raw is True:
            raw = "always"
        modes = {w.lower(): (raw if raw in RAW_MODES else raw_mode_of(base, w)) for w in WIKIS}
        always = {w for w, m in modes.items() if m == "always"}
        later = {w for w, m in modes.items() if m == "fallback"}

        def ranked(homes: Set[str]) -> List[Tuple[float, Hit]]:
            found: List[Tuple[float, Hit]] = []
            for number, grades in enumerate(tiers):
                if number > 0 and grades == ["dormant"] and len(found) >= limit:
                    continue
                lists: List[Tuple[float, List[Hit]]] = []
                for kind, weight in (("note", 1.0), ("chunk", RAW_WEIGHT)):
                    hits = candidates(idx, terms, kind, grades, after, sessions, wiki,
                                      zone if held.kind == "root" else None, homes)
                    if hits:
                        lists.append((weight, hits))
                found += fuse(lists, today)
            return found
        found = ranked(always)
        if later and not found:
            found = ranked(always | later)          # no page holds an answer: the raw record, marked (#478)
        out: List[Result] = []
        for value, h in found[:limit]:
            out.append(Result(id="%s:%s" % (h.label, h.path), path=h.path, title=h.title, date=h.date,
                              source=h.label if h.src != "session" else "sessions",
                              snippet=snippet(idx, terms, h.rowid), score=round(value, 6), grade=h.grade,
                              raw=h.kind == "chunk" and h.src == "raw",
                              owner=h.owner if h.kind == "chunk" and h.src == "raw" else ""))
        return out
    finally:
        idx.close()


def read(id: str, *, project: Optional[PathLike], root: Optional[PathLike] = None,
         scope: Optional[Union[Scope, str]] = None) -> Optional[str]:
    """The text of a file, by the `id` of a result, when the id is in the
    scope's index. An id that is not there, whether no such file exists or
    the scope may not read it, answers the same: None. The scope is chosen as
    `search()` chooses it."""
    try:
        base = Path(root) if root is not None else workspace_root(
            project if project is not None and Path(project).is_absolute() else None)
    except FileNotFoundError:
        return None
    base = base.resolve()
    ctx = load_context(base)
    held = resolve(base, ctx, project, scope)
    if held is None or not isinstance(id, str) or ":" not in id:
        return None
    idx = open_scope(base, held, ctx, fts5_available(), trigram_available())
    if idx is None:
        return None
    try:
        label, _, path = id.partition(":")
        row = idx.con.execute("SELECT path FROM docs WHERE label = ? AND path = ? LIMIT 1", (label, path)).fetchone()
        if row is None:
            return None
        return read_text(base / row[0])
    finally:
        idx.close()


def stats(project: Optional[PathLike] = None, root: Optional[PathLike] = None,
          scope: Optional[Union[Scope, str]] = None) -> List[dict]:
    """One line for the scope's index: where it is and how many files it
    holds. Rows behind a wall are not in it, so not counted."""
    base = (Path(root) if root is not None else workspace_root()).resolve()
    ctx = load_context(base)
    held = resolve(base, ctx, project, scope)
    if held is None:
        return []
    idx = open_scope(base, held, ctx, fts5_available(), trigram_available())
    if idx is None:
        return []
    try:
        n = idx.con.execute("SELECT COUNT(DISTINCT path) FROM docs").fetchone()[0]
        return [{"index": held.label(), "file": idx.path.relative_to(base).as_posix(), "files": n,
                 "fts": idx.fts, "trigram": idx.tri, "memory": not idx.path.exists()}]
    finally:
        idx.close()


def build(root: Optional[PathLike] = None, rebuild: bool = False) -> List[str]:
    """Bring every scope index up to date (or make it again with `rebuild`).
    Says which were built, and counts nothing."""
    base = (Path(root) if root is not None else workspace_root()).resolve()
    ctx = load_context(base)
    purge_orphans(base, ctx)
    fts, tri = fts5_available(), trigram_available()
    done = []
    for sc in scopes_of(base, ctx):
        if sc.kind == "root" or not sc.file(base).parent.is_dir():
            continue
        idx = Index(base, sc, fts, tri, ctx)
        try:
            Refresher(idx).run(rebuild=rebuild)
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
            held = locate(root, home)
            if held is None or not (home == here or home in here.parents):
                return NOWHERE
            if held.zone and not held.project:
                return NOWHERE                  # opened at a zone's top: no project's scope, whatever folder it moves to
        except OSError:
            return NOWHERE
    if place.zone:
        return here
    # The root or System/. Only a folder really at the root or inside System/.
    # The root scope is a root session's by the harness's own record (the marker names the root)
    # and by nothing else: a bare working folder at the root or in System/ is refused.
    rel = here.relative_to(root).parts
    if marker and (not rel or rel[0] == "System"):
        return None
    return NOWHERE


def cli_scope(root: Path, asked: Optional[str]) -> Tuple[Optional[Scope], Optional[str]]:
    """(scope, problem) for a command-line call. The scope is the one of the
    folder the session was opened in (cwd_project). A scope named with
    --scope may only be that one; a session at the root may name any."""
    ctx = load_context(root)
    project = cwd_project(root)
    mine = scope_for_project(root, ctx, project) if project != NOWHERE else None
    pinned = os.environ.get(SCOPE_ENV, "").strip()
    if pinned and mine is not None:
        # An environment variable a session can set only narrows: from the root scope to another,
        # never from a scope to a different one.
        want = scope_named(root, ctx, pinned)
        if want is None or (mine.kind != "root" and want != mine):
            mine = None
        else:
            mine = want
    if mine is None:
        return None, ("This folder is not a place Recall reads from, so nothing was searched. Open the session in a "
                      "project of a zone, or at the workspace root.")
    if asked is None:
        return mine, None
    want = scope_named(root, ctx, asked)
    if want is None:
        return None, "There is no scope called %r. The scopes are: %s." % (
            asked, ", ".join(s.key for s in scopes_of(root, ctx) if mine.kind == "root" or s == mine))
    if mine.kind != "root" and want != mine:
        return None, "This session holds the scope %s, and a session may not name another." % mine.key
    return want, None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="recall.py", description=__doc__.split("\n")[0])
    ap.add_argument("--root", help="the workspace (default: the one above this folder)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="bring every scope index up to date")
    b.add_argument("--rebuild", action="store_true", help="make every index again from the files")
    s = sub.add_parser("search", help="ranked search")
    s.add_argument("words")
    s.add_argument("--scope", help="the scope to search (the session's own; a root session may name any)")
    s.add_argument("--after", metavar="YYYY-MM-DD")
    s.add_argument("--zone")
    s.add_argument("--wiki")
    s.add_argument("--sessions", action="store_true")
    s.add_argument("--archived", action="store_true")
    s.add_argument("--raw", action="store_true", help="rank raw records' chunks beside the pages, not only when no page matches")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--json", action="store_true")
    r = sub.add_parser("read", help="the text of a search result, by its id")
    r.add_argument("id")
    r.add_argument("--scope")
    t = sub.add_parser("stats", help="the scope's index, and how many files it holds")
    t.add_argument("--scope")
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
    held, problem = cli_scope(root, args.scope)
    if args.cmd == "stats":
        if held is not None:
            for row in stats(None, root, scope=held):
                print("%s: %d files%s (%s)" % (row["index"], row["files"], ", in memory" if row["memory"] else "",
                                              "fts5" if row["fts"] else "plain text"))
        else:
            print(problem, file=sys.stderr)
        return 0
    if args.cmd == "read":
        text = read(args.id, project=None, root=root, scope=held) if held is not None else None
        if text is None:
            print("Not found in this scope: %s" % args.id, file=sys.stderr)
            return 1
        print(text)
        return 0
    if held is None:
        print(problem, file=sys.stderr)
    hits = search(args.words, project=None, after=args.after, zone=args.zone, wiki=args.wiki,
                  sessions=args.sessions, limit=args.limit, root=root, archived=args.archived,
                  scope=held, raw="always" if args.raw else None) if held is not None else []
    if args.json:
        print(json.dumps([dataclasses.asdict(h) for h in hits], indent=2))
        return 0
    older = [h for h in hits if h.grade != "working"]
    print("%d result%s for %r%s" % (len(hits), "" if len(hits) == 1 else "s", args.words,
                                    "; %d from older notes" % len(older) if older else ""))
    for n, h in enumerate(hits, 1):
        print("%d. %s  [%s%s%s]" % (n, h.title, h.source, ", " + h.date if h.date else "",
                                  ", " + RAW_SAID if h.raw else
                                  ", from older notes" if h.grade == "dormant" else
                                  ", archived" if h.grade == "archived" else ""))
        print("   " + h.path)
        print("   " + h.snippet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
