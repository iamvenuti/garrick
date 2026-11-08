#!/usr/bin/env python3
"""Check a Garrick workspace against every rule a machine can check.

    python3 System/tools/check.py [--root PATH] [--ear] [--json] [--quick]
    python3 System/tools/check.py --staged --walls-only      (the pre-commit hook)
    python3 System/tools/check.py --paths FILE [FILE ...]    (only these files' findings; what an update runs)
    python3 System/tools/check.py --install-hooks
    python3 System/tools/check.py --version                  (which Garrick, for a bug report, and whether a
                                                              newer one is out, as GitHub last said; never asks)

Plain text by default: findings grouped by check, one line each, then a
count. `--ear` gives at most three short sentences for reading aloud.
`--json` is for other programs. Exit code 1 when there is any error, 2 when
no workspace is found.

`--quick` runs every check but the comparison of wording with the meetings
(does a project file, person page or Knowledge page repeat one?), which is
most of the time a full check takes on a large workspace. `--walls-only` runs
the walls check alone. `--staged` checks only the files
staged in the git repository of the current folder, as they are staged, and
prints one line per wall broken: it is what each zone's pre-commit hook runs.
It keeps what it read of the other files in that repository's git folder, so
the next commit reads only what changed since (see NoteCache). That repository
alone keeps git's repository-local variables; every other repository is read
with them taken out, so the temporary index git builds for a commit of named
files reaches nowhere else (see `_git_env` and `foreign_git_env`).
`--install-hooks` writes that hook into every zone's repository, and into
every git repository inside a project.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import marshal
import os
import posixpath
import re
import subprocess
import sys
import time
import unicodedata
from fnmatch import filter as fnmatch_filter
from functools import lru_cache
from array import array
from bisect import bisect_left
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote
from urllib.parse import urlsplit as _urlsplit


def urlsplit(url: str):
    """urllib's urlsplit, that never raises on a note's text. An address whose
    host part holds `[` or `]` (`obsidian://[open?file=…`) is not a valid IPv6
    host, and urllib raises ValueError on it, which stopped the whole check.
    Such an address is read with its brackets percent-encoded, so its query
    still names what it names (parse_qs decodes them back)."""
    try:
        return _urlsplit(url)
    except ValueError:
        return _urlsplit(url.replace("[", "%5B").replace("]", "%5D"))

def _safe_fnmatch(names, pattern):
    """fnmatch's filter, the same on every Python and never raising. A bracket
    class whose range is out of order (`[pick-harvest]`, which is ordinary
    bracketed text, holds `k-h`) is read as literal brackets: Python 3.9's `re`
    refuses such a class and 3.13 reads it as matching nothing, so neither is a
    reading to rely on. The token's literal readings are resolved elsewhere."""
    def bad(m):
        body = m.group(1).lstrip("!^")
        return any(body[i - 1] > body[i + 1] for i in range(1, len(body) - 1) if body[i] == "-")
    if any(bad(m) for m in re.finditer(r"\[([^\]]*)\]", pattern)):
        pattern = pattern.replace("[", "\0").replace("]", "[]]").replace("\0", "[[]")
    try:
        return fnmatch_filter(names, pattern)
    except re.error:
        return [n for n in names if n == pattern]


sys.dont_write_bytecode = True  # keep System/tools free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))

from garrick_lib import (  # noqa: E402
    CHECKOUT_TREE,
    SKIP_DIRS,
    is_checkout,
    live_files,
    nested_repo,
    CHECKPOINT_DAYS,
    CHECKPOINT_HEADING,
    CHECKPOINT_KINDS,
    CHECKPOINT_LABELS,
    CHECKPOINT_ONE,
    CHECKPOINT_SAID,
    CHECKPOINT_UNCONFIRMED,
    CONTEXT_TABLES,
    INBOX,
    LOCAL_HEADER,
    PREFERENCES_FILE,
    SKILL_FOLDERS,
    VERSION_STAMP,
    MEDIA_EXTS,
    WALL_HOOK_MARK,
    as_sources,
    has_wall_hook,
    inbound_only,
    is_origin,
    memory_entries,
    memory_folders,
    memory_origin,
    origin_problems,
    parse_learned,
    install_wall_hook,
    is_domain,
    is_display_name,
    is_instruction_file,
    is_sayable,
    is_webmail,
    knowledge_schema,
    fingerprint,
    foreign_git_env,
    garrick_ignores,
    ignore_parts,
    labels,
    load_context,
    mail_labels,
    meeting_labels,
    run_wall_cases,
    wall_roles,
    local_file,
    mail_attachments,
    parse_frontmatter,
    parse_frontmatter_text,
    parse_mail_bytes,
    read_checkpoint,
    read_version,
    resume_hash,
    said_time,
    say_changes,
    say_newer_release,
    say_version,
    spoken_clash,
    spoken_of,
    stamped_parties,
    strip_recipients,
    strip_tag,
    KNOWLEDGE,
    blocked,
    is_walled,
    hats_of,
    decide,
    work_folder,
    workspace_root,
)
from garrick_lib import (  # noqa: E402
    MEETINGS_ENTITIES, ENTITY_LINK_RE, entity_page, entity_pages, party_entities, people_parties, short_form_parties, tag_list,
    TODO_ALSO_RE,
)
from garrick_lib import _listed  # noqa: E402  (#340)
from garrick_lib import _frontmatter_body  # noqa: E402  (#388)
from garrick_lib import (  # noqa: E402  (#330)
    FRONTMATTER_PLAIN, PERSON_KEYS, PERSON_PLAIN, PERSON_SHAPE, WALLS_KEYS, WIKI_GIT_REASON, frontmatter_form_problem,
    entity_names, entity_parties, entity_rel, first_line, links_in, name_group, named_in, org_key, organisation_link,
    organisation_proposal,
)


ERROR = "error"
WARNING = "warning"

# Order in which checks appear in the report, with their headings.
CHECKS = [
    ("claude-md", "Instruction files"),
    ("instructions", "Instruction drift"),
    ("settings", "Check settings"),
    ("placeholders", "Unfinished install"),
    ("context", "Context"),
    ("memory", "Learned entries"),
    ("zones", "Zones"),
    ("hooks", "Commit hooks"),
    ("skills", "Skills"),
    ("names", "Names"),
    ("projects", "Projects"),
    ("threads", "Threads"),
    ("resume", "Resume points"),
    ("deliverables", "Deliverables"),
    ("anonymous", "Anonymous projects"),
    ("todo", "To-do lists"),
    ("questions", "Questions"),
    ("decisions", "Decisions"),
    ("links", "Links"),
    ("meetings", "Meeting pages"),
    ("people", "Person pages"),
    ("walls", "Walls"),
    ("sources", "Project sources"),
    ("inbox", "Inboxes"),
    ("knowledge", "Knowledge wiki"),
    ("raw", "Raw records"),
    ("generated", "Generated files"),
    ("recall", "Recall indexes and sessions"),
    ("preferences", "Kept choices"),
    ("review", "Review record"),
    ("updates", "Updates to merge"),
]

# How a group of findings is said aloud when there is more than one.
EAR_GROUP = {
    "updates": "{n} files Garrick ships need attention",
    "claude-md": "{n} CLAUDE files could switch off the instructions",
    "instructions": "the instruction files have drifted in {n} places",
    "settings": "the check settings have {n} problems",
    "placeholders": "{n} files still hold installer placeholders",
    "context": "the context file has {n} problems",
    "memory": "{n} learned entries do not say where they came from, or came only from outside",
    "zones": "the zone folders have {n} gaps",
    "hooks": "git skips the hooks of {n} repositories",
    "skills": "{n} things need fixing in the skills",
    "names": "{n} names are hard to say or sound alike",
    "projects": "{n} things need fixing in project hub notes",
    "threads": "{n} things need fixing in thread notes",
    "resume": "{n} resume points are out of date or name files that are not there",
    "deliverables": "{n} deliverables lack their date",
    "anonymous": "{n} files in anonymous projects name a party",
    "todo": "the to-do lists have {n} problems",
    "questions": "{n} things need fixing in question files",
    "decisions": "{n} things need fixing on decision pages",
    "links": "{n} links cross a boundary or lead somewhere fragile",
    "meetings": "{n} things need fixing on meeting pages",
    "people": "{n} things need fixing on person pages",
    "walls": "the walls were crossed in {n} places",
    "sources": "{n} project sources came from mail that is not filed in Meetings",
    "inbox": "{n} files in the inboxes need attention",
    "knowledge": "{n} Knowledge pages carry parties or meeting material",
    "raw": "{n} raw records were changed",
    "generated": "{n} generated files could end up in the workspace history",
    "recall": "{n} search index or session files could end up in the workspace history",
    "preferences": "{n} of the choices you keep are not in the workspace history",
    "review": "the review record has {n} entries outside its fixed form",
}

# Files of markup or data: their indentation is layout, not an indented code block, and a bare name in a string or a
# stylesheet is a name, not a path (a path written in one is still read).
MARKUP_SUFFIXES = {".html", ".htm", ".json"}
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".csv", ".tsv", ".html", ".htm", ".json", ".yaml", ".yml", ".vtt"}
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")
COMMIT_RE = re.compile(r"[0-9a-fA-F]{7,40}")
CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
WIKILINK_RE = re.compile(r"!?\[\[([^\[\]\n]+?)\]\]")
URI_RE = re.compile(r"obsidian://[^\s)\]>\"'`]+")
# A Markdown link's destination, in angle brackets (where it may hold spaces)
# or bare, where it may hold balanced parentheses, as Obsidian writes a file
# called `Brief (1).pdf`, then an optional title. Each pattern below stays
# linear on any input: no two of its branches can match the same character,
# and a run that cannot close is bounded.
MDLINK_RE = re.compile(r"\]\(\s*(?:<([^<>\n]*)>|((?:[^()\s<>]|\([^()\s<>]*\))+))(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)")
# A reference-style link's definition, `[1]: <path>` or `[1]: path`, and an
# HTML anchor's href.
REFDEF_RE = re.compile(r"(?m)^ {0,3}\[[^\]\n]+\]:[ \t]*(?:<([^<>\n]*)>|(\S+))")
HREF_RE = re.compile(r"(?i)<a\b(?:[^<>\"']|\"[^\"]*\"|'[^']*')*?\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))")
# An HTML tag, name and attributes, up to its `>`, or a `<` outside a quoted
# value, or the end of the text. A quoted value runs to its closing quote, or to
# the end of the text when none closes it. Nothing follows the repeat, so it
# never backtracks: each branch starts on a different character.
TAG_RE = re.compile(r"<([A-Za-z][^\s<>/\"']*)((?:[^<>\"']|\"[^\"]*\"?|'[^']*'?)*)")
# Every attribute of a tag, in any case and any quoting. Whatever it holds is
# read as a path: `src`, `href`, `srcset`, `data`, `poster`, `formaction` and
# the rest all name files, and a list of names would always be one short.
ATTR_RE = re.compile(r"(?<![\w:.-])([A-Za-z_:][-\w:.]*)\s*=\s*(?:\"([^\"]*)\"?|'([^']*)'?|([^\s\"'>]+))")
# Where a code span or a fenced block opens, as CommonMark reads them: a span
# closes on a run of backticks as long as the one that opened it, and a
# fence is three or more backticks or tildes, closed by a run of the same
# character at least as long.
BACKTICKS_RE = re.compile(r"`+")
MAX_CODE_PATH = 1000  # a code span longer than this is not a path: its body is not read
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
DELIVERABLE_RE = re.compile(r"^(\d{2})(\d{2})(\d{2}) - \S")
MEETING_NAME_RE = re.compile(r"^\d{6}-[a-z0-9][a-z0-9-]*$")
MAX_SCAN_BYTES = 2_000_000
MAX_STAGED_BYTES = 50_000_000     # a staged text file is read whole up to this; above it, it is refused


@dataclass
class Finding:
    severity: str
    check: str
    path: str
    message: str
    ear: str = ""


@dataclass
class Workspace:
    root: Path
    context: dict
    zones: List[Path] = field(default_factory=list)
    projects: List[Tuple[Path, dict]] = field(default_factory=list)  # (folder, hub frontmatter)
    meetings: Dict[Path, dict] = field(default_factory=dict)  # meeting page or Meetings question -> frontmatter
    meeting_questions: set = field(default_factory=set)  # the Meetings questions among them (#224), and the answers
    meeting_answers: set = field(default_factory=set)  # the raw answers among those (#224): raw/answers/, read as the question's parties
    meeting_decisions: set = field(default_factory=set)  # the decision pages among those (#224): wiki/decisions/, read as the question's parties
    wiki_files: List[Path] = field(default_factory=list)  # every .md under Wikis/
    quote_index: Optional["QuoteIndex"] = None  # built on first use by the walls check
    meeting_links: Optional["PathIndex"] = None  # the meeting pages, indexed for links on first use
    index_files: Optional[set] = None  # staged mode: the files the commit holds (git's index), by real path; None reads the disk
    page_names: Optional["PageNames"] = None  # every page of the Meetings wiki, of every kind and grade, by name, on first use
    project_links: Optional["PathIndex"] = None  # every project's files, indexed for links on first use
    project_dirs: Optional["DirIndex"] = None  # every project's folders, indexed on first use
    project_files: Optional[Dict[Path, Path]] = None  # each of those files -> its project
    thread_owners: Optional[Dict[str, set]] = None  # a thread's name, lower case -> the projects that have one
    wiki_links: Optional["PathIndex"] = None  # every wiki page, indexed for links on first use
    project_norm: Optional[tuple] = None  # (count, normalised project path -> (project, hub fields)), on first use
    label_cache: dict = field(default_factory=dict)  # garrick_lib.labels()'s per-run cache (#398)
    vault_files: Dict[Path, Dict[str, List[str]]] = field(default_factory=dict)  # each vault's files by name, on first use
    mail_index: Optional[Dict[Tuple[str, int, str], List["MailRecord"]]] = None  # built on first use
    source_findings: Optional[List["Finding"]] = None  # the Sources/ findings, computed once
    git_view: Dict[Path, str] = field(default_factory=dict)  # staged mode: what git holds, where the disk differs
    settings: dict = field(default_factory=dict)  # System/garrick-checks.json, as far as it reads
    settings_problems: List[str] = field(default_factory=list)  # what in it could not be read
    quick: bool = False  # --quick: leave out the comparison of wording
    zone_notes: Optional[List[Tuple[Path, str]]] = None  # every live note in the zones, read on first use
    forms: Dict[frozenset, dict] = field(default_factory=dict)  # name_forms, by the walled tags asked for
    ignored: Optional[set] = None  # what the workspace's repositories ignore, listed on first use
    shared_links: Optional["PathIndex"] = None  # the shared files, indexed for links on first use
    checkouts: Optional[List[Path]] = None  # the Garrick checkouts inside a project, found on first use
    apart: Optional[set] = None  # what the checks leave out of a project's own files, listed on first use
    raw_records: Optional[Dict[str, List[Path]]] = None  # Meetings raw records by stem, any depth, on first use
    cache: Optional["NoteCache"] = None  # staged mode: what the last commits read, kept between them
    entity_index: Optional[List[dict]] = None  # Meetings entity pages by name, as staged too, on first use (#330)
    misread: set = field(default_factory=set)  # meeting pages whose frontmatter reads two ways: no parties for the walls
    meeting_raw: Dict[Path, dict] = field(default_factory=dict)  # those pages' frontmatter as written, for their own checks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rel(ws: Workspace, path: Path) -> str:
    try:
        return path.relative_to(ws.root).as_posix()
    except ValueError:
        return str(path)


# SKIP_DIRS (folders no one writes in) and nested_repo() come from garrick_lib,
# which the status page's Todo card reads a zone through as well.


def walk_files(top: Path, skip: Optional[set] = None, nested: bool = False) -> Iterable[Path]:
    """Every file under `top`, skipping SKIP_DIRS, nested repositories unless
    `nested` is set, and the files and folders in `skip` (see ignored)."""
    for dirpath, dirnames, filenames in os.walk(top):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and (nested or not nested_repo(here / d))
                             and not (skip and here / d in skip))
        for name in sorted(filenames):
            if not (skip and here / name in skip):
                yield here / name


def text_of(data: bytes, strict: bool = False) -> Optional[str]:
    """A file's bytes as text, or None when they are not text. UTF-8 is the
    rule; a file that opens with a UTF-16 or UTF-32 byte order mark (Excel's
    Unicode text, a Windows .csv or .txt) is decoded as that. Other bytes with
    a NUL in the first 8 KB are binary. With `strict`, UTF-8 that does not
    decode is not text either."""
    if data[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"):
        enc = "utf-32"
    elif data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        enc = "utf-16"
    else:
        enc = None
    if enc:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            return None
    if b"\0" in data[:8192]:
        return None
    if strict:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return data.decode("utf-8", errors="replace")


def read_text(path: Path) -> Optional[str]:
    """The file's text, or None when it is binary, huge or unreadable."""
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    return text_of(data)


class NoteCache:
    """What the commit check read from each file the last time, kept between
    commits in the git folder of the repository being committed.

    The hook compares the wording of what is staged with every meeting, raw
    record and project file, and reading them all, not comparing them, is most
    of its time on a large workspace. So it keeps, for each file, its
    frontmatter and its runs of words, under the file's size, modification
    time and inode, and reads again only the files whose stamp has changed:
    after the first commit, the check's time follows what changed since the
    last one, not the size of the workspace. Nothing is kept for a file
    changed in the last RACY_SECONDS, which a second change could leave with
    the same stamp, nor across a change to these tools or to Python. A cache
    that does not read is no cache: everything is read again, and the
    findings are the same either way."""

    FORMAT = 1
    RACY_SECONDS = 2
    NAME = "garrick-walls.cache"

    def __init__(self, path: Optional[Path]):
        self.path = path
        self.entries: Dict[str, tuple] = {}  # kind and path -> (stamp, value), as loaded
        self.kept: Dict[str, tuple] = {}  # what this run used or made: all that is saved
        self.changed = False
        self.whole = False  # this run asked after every file the wording check reads
        if path is None:
            return
        self.made_by = self.version()
        try:
            data = marshal.loads(path.read_bytes())
            if isinstance(data, dict) and data.get("version") == self.made_by and isinstance(data.get("entries"), dict):
                self.entries = data["entries"]
        except Exception:  # missing, unreadable or from another version: start again
            pass

    @staticmethod
    def version() -> tuple:
        tools = Path(__file__).resolve().parent
        code = hashlib.sha256()
        for name in ("check.py", "garrick_lib.py"):
            try:
                code.update((tools / name).read_bytes())
            except OSError:
                pass
        return (NoteCache.FORMAT, tuple(sys.version_info[:2]), code.hexdigest())

    @classmethod
    def for_repo(cls, repo: Path) -> "NoteCache":
        found = _git(["rev-parse", "--absolute-git-dir"], repo)
        return cls(Path(found.strip()) / cls.NAME if found else None)

    def get(self, kind: str, path: Path, make: Callable[[], object], fresh: Optional[Callable[[object], bool]] = None):
        """What `make` gives for the file at `path`, from the cache while the
        file's stamp is unchanged and `fresh`, if given, accepts it."""
        key = kind + "\0" + str(path)
        try:
            st = path.stat()
        except OSError:
            return make()
        stamp = (st.st_size, st.st_mtime_ns, st.st_ino)
        hit = self.entries.get(key)
        if hit is not None and hit[0] == stamp and (fresh is None or fresh(hit[1])):
            self.kept[key] = hit
            return hit[1]
        value = make()
        if time.time() - st.st_mtime > self.RACY_SECONDS:
            self.kept[key] = (stamp, value)
            self.changed = True
        return value

    def save(self) -> None:
        """Write what this run kept. When it asked after every file (`whole`),
        what it did not ask for is gone, and only its own is kept."""
        if self.path is None or not (self.changed or (self.whole and len(self.kept) < len(self.entries))):
            return
        entries = self.kept if self.whole else dict(self.entries, **self.kept)
        tmp = self.path.with_name(self.path.name + ".%d.tmp" % os.getpid())
        try:
            tmp.write_bytes(marshal.dumps({"version": self.made_by, "entries": entries}))
            os.replace(str(tmp), str(self.path))
        except (OSError, ValueError):
            try:
                tmp.unlink()
            except OSError:
                pass


def note_frontmatter(ws: "Workspace", path: Path) -> dict:
    """The frontmatter of the note at `path`; in staged mode, from the cache
    while the note is unchanged."""
    if ws.cache is None:
        return parse_frontmatter(path)
    fm = ws.cache.get("fm", path, lambda: parse_frontmatter(path))
    return {k: list(v) if isinstance(v, list) else v for k, v in fm.items()}  # a copy: callers may change it


def note_form(ws: "Workspace", path: Path, keys: Optional[Tuple[str, ...]] = None) -> str:
    """garrick_lib's frontmatter_form_problem() for the file at `path`; in
    staged mode, from the cache while the file is unchanged."""
    def make() -> str:
        try:
            return frontmatter_form_problem(path.read_text(encoding="utf-8", errors="replace"), keys)
        except OSError:
            return ""
    if ws.cache is None:
        return make()
    return ws.cache.get("form" if keys is None else "form:" + ",".join(keys), path, make)


def meeting_view(ws: "Workspace", page: Path, fm: dict, text: Optional[str] = None) -> dict:
    """A meeting page's frontmatter as the walls read it: without its zone and
    parties, so unfinished, when the frontmatter can be read two ways
    (frontmatter_form_problem), since a YAML reader may find other parties
    there, or when a party or its zone is one the walls do not know
    (walls_value_problem). Fail closed: nothing on it is used until then."""
    problem = frontmatter_form_problem(text) if text is not None else note_form(ws, page)
    if not problem and not walls_value_problem(ws, fm):
        return fm
    ws.misread.add(page)
    ws.meeting_raw.setdefault(page, fm)           # what the page's own checks name: its unknown party, its zone
    return {k: v for k, v in fm.items() if k not in ("parties", "zone")}


WALLS_VALUE = "the walls read no party or zone they know here"


def walls_value_problem(ws: "Workspace", fm: dict, project_file: bool = False, note: bool = False) -> str:
    """Which of the keys the walls read holds a value they do not know, or
    "": a `party:` or `parties:` value that is no tag in the Parties table
    nor `none`, or a `zone:` that is no zone of the workspace. Such a value
    is read as no party, which would turn the walls off where a YAML reader,
    or the writer, meant one; so it turns them on (#330)."""
    for key in ("party", "parties"):
        for v in as_list(fm.get(key)):
            tag = strip_tag(str(v))
            if note and tag == "none":      # a hub or thread note says whose it is: `none` is nobody, so no label
                return "`%s:` names `none`, which is no party of a project" % key
            if tag and tag != "none" and tag not in ws.context["parties"]:
                return "`%s:` names no tag from the Parties table, nor `none`" % key
    zone = fm.get("zone")
    zones = {z.name for z in ws.zones} | set(ws.context["zones"])
    if zone not in (None, "") and (not isinstance(zone, str) or zone.strip() not in zones):
        return "`zone:` names no zone of this workspace"
    return ""


def folder_elsewhere(ws: "Workspace", project: Path, where: Path) -> str:
    """Where a hub's `folder:` lands when that is another zone or a wiki, in
    words ("the Personal zone", "the Meetings wiki", "Wikis/"); "" when it is
    in the project's own zone or outside both."""
    try:
        real = where.resolve()
    except OSError:
        return ""

    def inside(top: Path) -> Optional[Tuple[str, ...]]:
        try:
            return real.relative_to(top.resolve()).parts
        except (OSError, ValueError):
            return None

    wiki = inside(ws.root / "Wikis")
    if wiki is not None:
        return "the %s wiki" % wiki[0] if wiki else "Wikis/"
    zone = inside(ws.root / "Zones")
    if zone is None:
        return ""
    own = project.parent.name if project.parent.parent == ws.root / "Zones" else None
    if not zone:
        return "Zones/"
    return "" if zone[0] == own else "the %s zone" % zone[0]


def visible_dirs(folder: Path) -> List[Path]:
    """Sub-folders that are real content: not hidden, not templates."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def project_dirs(zone: Path) -> List[Path]:
    """A zone's projects: every visible folder but its Inbox and an archive."""
    return [p for p in visible_dirs(zone) if p.name != INBOX and p.name.lower() != "archive"]


def as_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)] if str(value).strip() else []


def party_name(ws: Workspace, tag: str) -> str:
    entry = ws.context["parties"].get(tag)
    return entry["party"] if entry and entry.get("party") else tag


# Where a wiki keeps the pages that faded, each in the same layout as the wiki
# itself (`dormant/wiki/...`, `dormant/raw/...`): dormant, listed only in
# `wiki/index-dormant.md`, and archived, in no index. Neither is working
# memory, so no check reports on them but two: the walls read them as they read
# a working page, and their raw records stay protected (check_raw). A link into
# one still lands.
FADED = ("dormant", "archive")
# Where a wiki keeps its raw records: beside its working pages, and beside the
# pages that faded. A record moves between them with its page, as a git
# rename, and stays protected wherever it lands (check_raw).
RAW_HOMES = ("raw",) + tuple(grade + "/raw" for grade in FADED)


def is_faded(ws: Workspace, path: Path) -> bool:
    """A page or record of a wiki that faded: anywhere under its dormant/ or
    archive/ folder."""
    parts = Path(rel(ws, path)).parts
    return len(parts) > 3 and parts[0] == "Wikis" and parts[2] in FADED


def grade_places(ws: Workspace, path: Path) -> List[Path]:
    """Where a wiki's page or record stands in the grades it is not in: one
    that fades or wakes moves between `<wiki>/<path>`, `<wiki>/dormant/<path>`
    and `<wiki>/archive/<path>`. Fade rewrites the wikilinks to it, but not a
    link in code (#256), a Markdown link or an HTML anchor, which go on naming
    the place it left; a link index finds it there too (#297)."""
    parts = Path(rel(ws, path)).parts
    if len(parts) < 4 or parts[0] != "Wikis":
        return []
    here = parts[2] if parts[2] in FADED else ""
    sub = parts[3:] if here else parts[2:]
    return [ws.root.joinpath(*parts[:2], *((grade,) if grade else ()), *sub)
            for grade in ("",) + FADED if grade != here]


GENERATED = ("System", "generated")


def is_generated(ws: Workspace, path: Path) -> bool:
    """Output a tool wrote for you, such as the status page: never committed,
    never read as material the workspace shares. Skipping it can only make a
    check stricter, so a file put there by mistake loses nothing but its
    place in git."""
    return Path(rel(ws, path)).parts[:2] == GENERATED


TEMPLATES = ("System", "templates")


def is_template_path(ws: Workspace, path: Path) -> bool:
    """A template, whose placeholder marks are there for a script to fill: anything
    under System/templates/, or in a folder under Zones/ whose name starts
    with an underscore (`_project`). The originals a Garrick checkout ships
    are never asked about: the checks leave a checkout out whole (set_apart)."""
    parts = Path(rel(ws, path)).parts
    if parts[:2] == TEMPLATES:
        return True
    return bool(parts) and parts[0] == "Zones" and any(p.startswith("_") for p in parts[1:-1])


def say(n: int) -> str:
    words = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"]
    if n < len(words):
        return words[n]
    if n < 100:
        return str(n)
    return "Over %d" % (n // 100 * 100)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def _link_forms(raw: str) -> List[str]:
    """The relative paths a link or an attribute value may name: without a
    heading, then without a query too, and a `file://` address as the path it
    holds. Nothing for a web or other address, or for no path."""
    target = raw.strip().split("#", 1)[0]
    if re.match(r"(?i)^file:", target):
        target = re.sub(r"(?i)^file:(?://[^/]*)?", "", target)
    elif not target or re.match(r"^[a-z][a-z0-9+.-]*:", target):
        return []  # web or obsidian URI, handled above or not ours
    forms = [target, target.split("?", 1)[0]]
    forms += [lexical(f) for f in forms if ".." in f]
    return [f for i, f in enumerate(forms) if f and f not in forms[:i]]


def lexical(path: str) -> str:
    """`path` with its `.` and `..` names settled by the words alone, a
    leading `..` that has nothing to cancel kept: `Deliverables/../../Harbour/x`
    is `../Harbour/x`. Only the first 2048 characters are read."""
    if not path or path.startswith("/") or ".." not in path[:2048]:
        return ""
    return posixpath.normpath(path[:2048]) if path[:2048].strip("/") else ""


def extract_links(text: str) -> List[Tuple[str, str]]:
    """(as written, target) for every wikilink, obsidian:// URI, relative
    Markdown link (inline, in angle brackets or by reference) and HTML
    anchor, and the file an HTML tag names by `src`, `srcset`, `data`, `href`,
    `xlink:href`, `poster` or `background`, in `text`. Targets are vault-relative or file-relative paths
    without the alias or heading."""
    links = []
    for m in WIKILINK_RE.finditer(text):
        target = m.group(1).split("|", 1)[0].rstrip("\\").split("#", 1)[0].strip()
        if target:
            links.append((m.group(0), target))
    for m in URI_RE.finditer(text):
        uri = m.group(0)
        query = parse_qs(urlsplit(uri).query)
        vault = (query.get("vault") or [""])[0]
        for key in ("file", "path"):
            for value in query.get(key, []):
                target = unquote(value).split("#", 1)[0]
                links.append((uri, "obsidian:%s:%s" % (vault, target) if key == "file" else target))
    for regex in (MDLINK_RE, REFDEF_RE):
        for m in regex.finditer(text):
            found = next((g for g in m.groups() if g is not None), "")
            for target in _link_forms(unquote(found.strip())):
                links.append((m.group(0).strip(), target))
    for tag in TAG_RE.finditer(text):
        name = tag.group(1).lower()
        for attr in ATTR_RE.finditer(tag.group(2)):
            key = attr.group(1).lower()
            found = next((g for g in attr.groups()[1:] if g is not None), "")
            value = html.unescape(found).strip().strip("\"'` ")
            if key not in LINK_ATTRS and len(re.sub(r"[^A-Za-z]", "", value)) < 3 and "/" not in value and "\\" not in value:
                continue                   # `data-edge-to="x"`, `[0]`: an attribute that is no address and holds no name
            values = [value]
            if key == "srcset":
                # A list: each URL, then an optional descriptor. A name may hold
                # a comma or a space, so each piece is read whole as well.
                pieces = [p.strip() for p in value.split(",") if p.strip()]
                values += pieces + [piece.split()[0] for piece in pieces]
            url = re.search(r"(?i)\burl\s*=\s*(.*)", value)
            if url:
                values.append(url.group(1).strip().strip("\"'` "))
            for n, one in enumerate(values):
                # As written: the attribute's value, or for a piece of a list the
                # piece, cut short, so the text kept grows with the list and not with
                # its square.
                shown = (found if n == 0 else one)[:200]
                for target in _link_forms(unquote(one)):
                    links.append(('<%s %s="%s">' % (name, key, shown), target))
    return links


def tag_texts(text: str) -> List[Tuple[str, str]]:
    """(as written, what it holds) for every HTML tag in `text`: its name and
    attributes, up to the `>` or the end of the text."""
    return [("<%s>" % m.group(1).lower(), html.unescape(m.group(2))) for m in TAG_RE.finditer(text)]


def code_texts(text: str, limit: Optional[int] = MAX_CODE_PATH) -> List[Tuple[str, str]]:
    """(as written, what it holds) for every code span in `text`, whatever the
    length of its backtick run, and every line of every fenced block, opened
    with backticks or tildes, as CommonMark reads them."""
    out: List[Tuple[str, str]] = []
    para: List[str] = []

    def spans() -> None:
        # Each run of backticks opens a span that the next run of the same
        # length closes; a run with none after it is plain text. One pass
        # over the runs, each length's next run found by a pointer: linear
        # whatever the paragraph holds.
        block = "\n".join(para)
        para.clear()
        # Every run closes at its full length: a backslash escapes nothing
        # inside a code span, so `C:\` is whole. Only a run taken as an
        # opener loses a backtick to a backslash before it.
        runs = [(m.start(), m.end()) for m in BACKTICKS_RE.finditer(block)]
        by_length: Dict[int, List[int]] = {}
        for i, (start, end) in enumerate(runs):
            by_length.setdefault(end - start, []).append(i)
        pointer = {n: 0 for n in by_length}
        i = 0
        while i < len(runs):
            start, end = runs[i]
            if start and block[start - 1] == "\\":
                start += 1  # an escaped backtick is text; the rest of the run may still open
            n = end - start
            same = by_length.get(n, [])
            while n and pointer[n] < len(same) and same[pointer[n]] <= i:
                pointer[n] += 1
            if not n or pointer[n] == len(same):
                i += 1
                continue  # nothing closes it: plain text
            j = same[pointer[n]]
            body = block[end:runs[j][0]]
            if limit is None or len(body) <= limit:
                body = body.replace("\n", " ")
                if body.startswith(" ") and body.endswith(" ") and body.strip():
                    body = body[1:-1]
                out.append((" ".join(block[start:runs[j][1]].split()), body))
            i = j + 1

    fence = ""
    for line in text.split("\n"):
        if fence:
            if re.match(r"^ {0,3}%s{%d,}\s*$" % (re.escape(fence[0]), len(fence)), line):
                fence = ""
            elif line.strip():
                out.append(("`%s`" % line.strip(), line))
            continue
        m = FENCE_RE.match(line)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            spans()
            fence = m.group(1)
        elif not line.strip():
            spans()
        else:
            para.append(line)
    spans()
    return out


def _strip_md(parts: Tuple[str, ...]) -> Tuple[str, ...]:
    if parts and parts[-1].lower().endswith(".md"):
        parts = parts[:-1] + (parts[-1][:-3],)
    return parts


class PathIndex:
    """Files a link may point at, indexed once: by the last part of each path,
    for links matched the way Obsidian matches them, and by resolved path, for
    exact ones. A link then costs the few files that share its last part, not
    a pass over every file: thousands of notes stay seconds, not minutes.

    `places`, when given, names more paths a file is found at besides its
    own, such as where a wiki page stood before it faded (grade_places): a
    link to one of them lands on the file as a link to its own path does."""

    def __init__(self, ws: Workspace, candidates: Iterable[Path],
                 places: Optional[Callable[[Path], List[Path]]] = None):
        self.items = list(candidates)
        self.places = places
        self.by_last: Dict[str, List[Tuple[Tuple[str, ...], Path]]] = {}
        for c in self.items:
            for at in [c] + (places(c) if places else []):
                have = tuple(x.lower() for x in _strip_md(Path(rel(ws, at)).parts))
                if have:
                    self.by_last.setdefault(have[-1], []).append((have, c))
        self._exact: Optional[Dict[Path, List[Tuple[int, Path]]]] = None
        self.reach: Dict[Path, int] = {}  # a file matched by its tail only by a tail this long (project_index)

    def exact(self) -> Dict[Path, List[Tuple[int, Path]]]:
        """Resolved path -> (position, file); built on the first exact link."""
        if self._exact is None:
            self._exact = {}
            folders: Dict[Path, Path] = {}  # a place's folder, resolved once for every file in it
            for i, c in enumerate(self.items):
                try:
                    self._exact.setdefault(c.resolve(), []).append((i, c))
                    for at in self.places(c) if self.places else []:
                        if at.parent not in folders:
                            folders[at.parent] = at.parent.resolve()
                        self._exact.setdefault(folders[at.parent] / at.name, []).append((i, c))
                except (OSError, RuntimeError):
                    continue
        return self._exact


def resolve(ws: Workspace, source: Path, target: str, candidates) -> List[Path]:
    """Which of `candidates` (files, or a PathIndex of them) could `target`,
    written in `source`, point at?

    Absolute and ./ ../ paths resolve exactly. Everything else matches the way
    Obsidian does: a page whose path ends with the link's path.
    """
    index = candidates if isinstance(candidates, PathIndex) else PathIndex(ws, candidates)
    vault = None
    if target.startswith("obsidian:"):
        _, vault, target = target.split(":", 2)
    if target.startswith("~"):
        target = os.path.expanduser(target)
    if target.startswith("/") or target.startswith("./") or target.startswith("../"):
        base = Path(target) if target.startswith("/") else source.parent / target
        hits = _exact_hits(index, base)
        return hits or _anchored_hits(ws, index, target)
    parts = _strip_md(tuple(p for p in target.replace("\\", "/").split("/") if p and p != "."))
    if not parts:
        return []
    tries = [((vault,) + parts)] if vault else []
    tries.append(parts)
    for want in tries:
        want = tuple(x.lower() for x in want)
        hits = list(dict.fromkeys(c for have, c in index.by_last.get(want[-1], [])
                                  if len(have) >= len(want) and have[-len(want):] == want
                                  and len(want) >= index.reach.get(c, 0)))
        if hits:
            return hits
    return _anchored_hits(ws, index, target)


def _exact_hits(index: "PathIndex", base: Path) -> List[Path]:
    """The files of `index` at `base`, with or without `.md`."""
    try:
        exact = base.resolve()
    except (OSError, RuntimeError):
        return []
    forms = [exact, Path(str(exact) + ".md")]
    try:
        forms.append(exact.with_suffix(".md"))
    except ValueError:
        pass
    found: Dict[int, Path] = {}
    for form in forms:
        for i, c in index.exact().get(form, []):
            found[i] = c
    return [found[i] for i in sorted(found)]


def _anchored_hits(ws: Workspace, index: "PathIndex", target: str) -> List[Path]:
    """A path written from outside the workspace, such as one from the home
    folder or another machine's: read from wherever it names the workspace's
    own folder, or from `Zones/` or `Wikis/` on, as a path from the top."""
    parts = [p for p in target.replace("\\", "/").split("/") if p and p != "."]
    starts = [i + 1 for i, p in enumerate(parts) if p == ws.root.name]
    starts += [i for i, p in enumerate(parts) if p in ("Zones", "Wikis") and i > 0]
    found: List[Path] = []
    for start in starts:
        if start < len(parts):
            found += [h for h in _exact_hits(index, ws.root.joinpath(*parts[start:])) if h not in found]
    return found


# ---------------------------------------------------------------------------
# Settings
#
# System/garrick-checks.json switches on the checks that only some workspaces
# want, and holds what a check cannot know by itself. It is optional: without
# it every check runs as Garrick ships it. Every key is optional too.
# ---------------------------------------------------------------------------

SETTINGS = ("System", "garrick-checks.json")
SETTING_KINDS = {
    "word-budgets": dict,    # {"root": words, "other": words} for the AGENTS.md files
    "parent-links": list,    # zones whose notes each carry `parent:`, a link to their thread or hub
    "note-links": list,      # zones whose hub and thread notes name other notes as links, never as code
    "todo-labels": list,     # zones whose every open action opens with its thread's link
    "retired-skills": dict,  # retired skill -> the skill that does its job now
    "raw-accepted": dict,    # raw record -> the last commit in which a change to it was accepted
    "as-shipped": list,      # path prefixes of files Garrick ships that are never changed here
    "todo-expire-days": (int, dict),     # days an untriaged Todo line waits, or {zone: days}: the todo skill's
    "todo-inbox-order": (str, dict),     # "first-seen" or "thread", or {zone: either}: the todo skill's
    "todo-chase-days": (int, dict),      # days ahead a swept Waiting on line's ⏳ is set, 0 for none, or {zone: days}
    "memory": (str, list),   # the folder, or folders, where the assistant keeps a memory of its own
    "nurture-weights": dict,             # finding kind -> its weight in the context debt: nurture.py's
    "nurture-threshold": (int, float),   # the context debt over which the morning digest says so
}
AS_SHIPPED = ["System/tools/"]


def load_settings(root: Path) -> Tuple[dict, List[str]]:
    """(settings, problems). Settings of the wrong kind are left out, and a
    file that does not read gives none: the check then runs as shipped."""
    path = root.joinpath(*SETTINGS)
    if not path.is_file():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, ["does not read as JSON (%s); every check runs as shipped until it does" % exc]
    if not isinstance(data, dict):
        return {}, ["should hold one JSON object; every check runs as shipped until it does"]
    out, problems = {}, []
    for key, value in data.items():
        kind = SETTING_KINDS.get(key)
        if kind is None:
            problems.append("`%s` is not a setting; the ones there are: %s" % (key, ", ".join(SETTING_KINDS)))
        elif not isinstance(value, kind) or (list in (kind if isinstance(kind, tuple) else (kind,))
                                              and isinstance(value, list) and not all(isinstance(v, str) for v in value)):
            problems.append("`%s` should be %s" % (key, "a list of names" if kind is list else "an object" if kind is dict
                                                   else "a folder, or a list of folders" if list in kind
                                                   else "a number" if float in kind
                                                   else "a %s, or an object with one per zone" % ("number" if int in kind else "word")))
        else:
            out[key] = value
    return out, problems


def check_settings(ws: Workspace) -> List[Finding]:
    """The settings file reads, and what it names exists."""
    r = "/".join(SETTINGS)
    out = [Finding(ERROR, "settings", r, p, "The check settings cannot be read") for p in ws.settings_problems]
    zones = {z.name for z in ws.zones}
    for key in ("parent-links", "note-links", "todo-labels"):
        for name in ws.settings.get(key, []):
            if name not in zones:
                out.append(Finding(WARNING, "settings", r, "`%s` names zone %s, which has no folder under Zones/" % (key, name),
                                   "The check settings name a zone that does not exist"))
    budgets = ws.settings.get("word-budgets", {})
    for key, value in budgets.items():
        if key not in ("root", "other") or not isinstance(value, int) or value <= 0:
            out.append(Finding(WARNING, "settings", r,
                               "`word-budgets` takes `root` and `other`, each a number of words; `%s` is left out" % key,
                               "A word budget in the check settings cannot be read"))
    for folder in memory_folders(ws.root, ws.settings.get("memory") or []):
        if not folder.is_dir():
            out.append(Finding(WARNING, "settings", r,
                               "`memory` names %s, which is not a folder; no memory entry is checked there" % folder,
                               "The check settings name a memory folder that is not there"))
    for key in ("retired-skills", "raw-accepted"):
        for name, value in ws.settings.get(key, {}).items():
            if not isinstance(value, str) or not value.strip():
                out.append(Finding(WARNING, "settings", r, "`%s` gives %s no value" % (key, name),
                                   "A line in the check settings has no value"))
            elif key == "raw-accepted" and not COMMIT_RE.fullmatch(value.strip()):
                out.append(Finding(WARNING, "settings", r, "`raw-accepted` gives %s `%s`, which is not a commit; it is left out" % (name, value.strip()),
                                   "An accepted raw change does not name a commit"))
    return out


def setting_zones(ws: Workspace, key: str) -> List[Path]:
    names = set(ws.settings.get(key, []))
    return [z for z in ws.zones if z.name in names]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover(root: Path, cache: Optional[NoteCache] = None, light: bool = False) -> Workspace:
    """The workspace as the checks read it. `light` stops after the zones, the
    projects and the settings: the wiki pages and the meetings are not indexed,
    for a run over named paths that needs neither (run_path_checks, #412)."""
    ws = Workspace(root=root, context=load_context(root), cache=cache)
    ws.settings, ws.settings_problems = load_settings(root)
    ws.zones = visible_dirs(root / "Zones")
    for zone in ws.zones:
        for project in project_dirs(zone):
            ws.projects.append((project, note_frontmatter(ws, project / (project.name + ".md"))))
    # A project about the workspace itself may live in System/, in no zone.
    for folder in visible_dirs(root / "System"):
        fm = note_frontmatter(ws, folder / (folder.name + ".md"))
        if fm.get("type") == "project":
            ws.projects.append((folder, fm))
    if light:
        return ws
    wikis = root / "Wikis"
    if wikis.is_dir():
        for path in walk_files(wikis):
            if path.suffix.lower() == ".md":
                ws.wiki_files.append(path)
    # The meeting pages that faded too: a project must not use one across a
    # wall any more than a working one. Only the walls read them (is_faded).
    for sources in meeting_sources(root):
        if sources.is_dir():
            for page in sorted(sources.rglob("*.md")):
                ws.meetings[page] = meeting_view(ws, page, note_frontmatter(ws, page))
    # A Meetings question (#224) carries a conversation's material under its
    # zone and parties, as a page does, so the walls read it with the pages:
    # a project may not link or quote one across a wall, nor an unfinished one.
    for question in wiki_questions(root / "Wikis" / "Meetings"):
        ws.meetings[question] = meeting_view(ws, question, note_frontmatter(ws, question))
        ws.meeting_questions.add(question)
    # A raw answer (#224) is the question's parties' material too: whoever
    # may not see the question may not see what was said in answer to it.
    # A page that faded keeps its zone and parties, so a raw answer or a decision at any grade is read too.
    homes = [root / "Wikis" / "Meetings"] + [root / "Wikis" / "Meetings" / g for g in FADED]
    for home in homes:
        for answer in wiki_answers(home):
            ws.meetings[answer] = meeting_view(ws, answer, note_frontmatter(ws, answer))
            ws.meeting_questions.add(answer)
            ws.meeting_answers.add(answer)
    # A decision page (#224, point 5) carries its question's zone and parties
    # and is read as the question is: the walls hold it to those, not to a
    # `party:` of its own.
    for home in homes:
        for decision in wiki_decisions(home):
            ws.meetings[decision] = meeting_view(ws, decision, note_frontmatter(ws, decision))
            ws.meeting_questions.add(decision)
            ws.meeting_decisions.add(decision)
    return ws


def meeting_index(ws: Workspace) -> "PathIndex":
    """The meeting pages, indexed for links: each at its own place and at the
    places it stands at in the other grades (grade_places), so that a link
    written before it faded, or before it woke, still lands on it (#297)."""
    return PathIndex(ws, ws.meetings, lambda page: grade_places(ws, page))


def meeting_sources(root: Path) -> List[Path]:
    """The folders that hold meeting pages: the working one, then the faded."""
    meetings = root / "Wikis" / "Meetings"
    return [meetings / "wiki" / "sources"] + [meetings / grade / "wiki" / "sources" for grade in FADED]


# Where a wiki keeps the questions only the user can answer (#224): one file
# each, `questions/<YYMMDD> - <slug>.md`, beside raw/ and wiki/ and in neither,
# since a question is neither the record nor a page, and changes as it is answered.
WIKI_QUESTIONS = "questions"


def wiki_questions(wiki: Path) -> List[Path]:
    """The question files of one wiki, at any depth, found as meeting pages
    are (discover()): every `.md` under `questions/`, whatever its name, so
    a question moved into a subfolder or renamed is still read by the walls."""
    folder = wiki / WIKI_QUESTIONS
    if not folder.is_dir():
        return []
    return sorted(f for f in folder.rglob("*.md") if f.is_file())


# A question answered is a raw record first (#224): the user's words, filed
# word for word in raw/answers/ beside the other raw records, never edited.
WIKI_ANSWERS = ("raw", "answers")


def wiki_answers(wiki: Path) -> List[Path]:
    """The raw answers of one wiki, at any depth under raw/answers/, found as
    the questions are: every `.md` there, whatever its name."""
    folder = wiki.joinpath(*WIKI_ANSWERS)
    if not folder.is_dir():
        return []
    return sorted(f for f in folder.rglob("*.md") if f.is_file())


# A decision (#224, point 5): the user's answer settled, as a page of the
# Meetings wiki, `wiki/decisions/<YYMMDD> - <slug>.md`. Its `zone:` and
# `parties:` are its question's, copied and never widened.
WIKI_DECISIONS = ("wiki", "decisions")
DECISION_STATUSES = ("valid", "superseded", "withdrawn")
DECISION_SECTIONS = ("Decision", "Assumptions", "Options turned down", "Revisit when")
DECISION_NAME = re.compile(r"^\d{6} - \S.*$")


def wiki_decisions(wiki: Path) -> List[Path]:
    """The decision pages of one wiki, at any depth under wiki/decisions/."""
    folder = wiki.joinpath(*WIKI_DECISIONS)
    if not folder.is_dir():
        return []
    return sorted(f for f in folder.rglob("*.md") if f.is_file())


def meeting_noun(ws: Workspace, page: Path, kind: str = "meeting") -> str:
    """How a finding names a file the walls read in the Meetings wiki: an
    answer for a raw answer and a question for a question file (#224),
    `kind` for a meeting page."""
    if page in ws.meeting_answers:
        return "reply"
    if ws.page_names is not None and page in ws.page_names.kinds:
        return ws.page_names.kinds[page]
    if page in ws.meeting_decisions:
        return "decision"
    return "question" if page in ws.meeting_questions else kind


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

CLAUDE_NAMES = {"claude.md", "claude.local.md"}


def check_claude_md(ws: Workspace) -> List[Finding]:
    out = []
    for path in walk_files(ws.root):
        if path.name.lower() in CLAUDE_NAMES:
            out.append(Finding(ERROR, "claude-md", rel(ws, path),
                               "Claude Code stops reading AGENTS.md while this file exists; delete it or rename it AGENTS.md",
                               "There is a CLAUDE file in the workspace, which switches off the instructions"))
    user_level = Path.home() / ".claude" / "CLAUDE.md"
    for folder in ws.root.resolve().parents:
        for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"):
            path = folder / name
            if path.is_file() and path.resolve() != user_level.resolve():
                out.append(Finding(WARNING, "claude-md", str(path),
                                   "a CLAUDE file above the workspace can stop Claude Code reading AGENTS.md here",
                                   "A CLAUDE file above the workspace may switch off the instructions"))
    return out


# Instruction files route and point; they do not restate. Past a budget, an
# AGENTS.md is carrying something that belongs in the file it points to.
ROOT_INSTRUCTIONS = ("AGENTS.md", "System/rules.md", "System/context.md")
# The workspace's own text for the root ones, beside Garrick's (see local_file).
ROOT_LOCALS = ("AGENTS.local.md", "System/rules.local.md")
WORD_BUDGET_ROOT = 800
WORD_BUDGET_OTHER = 1000
# System/rules.md is loaded into every session, on every request. Procedure
# that only one kind of request needs belongs in the skill that runs it.
RULES_CHAR_BUDGET = 8000
COPY_MIN_CHARS = 80
# The heading under which the update's split leaves what it could not place.
SPLIT_REVIEW_RE = re.compile(r"^## From your earlier .+, to review\s*$")


def local_beside(ws: Workspace, path: Path) -> Optional[Path]:
    """The local file beside one of Garrick's instruction files, or None for
    any other file."""
    r = rel(ws, path)
    return ws.root / local_file(r) if is_instruction_file(r) else None


def instruction_files(ws: Workspace) -> List[Path]:
    """Every instruction file there is: Garrick's, the context, and the local
    file beside each of Garrick's."""
    files = [ws.root / p for p in ROOT_INSTRUCTIONS]
    files += [z / "AGENTS.md" for z in ws.zones]
    files += [ws.root / "Wikis" / "AGENTS.md"]
    wikis = ws.root / "Wikis"
    if wikis.is_dir():
        files += sorted(w / "AGENTS.md" for w in wikis.iterdir() if w.is_dir() and not w.name.startswith("."))
    files += [local for local in (local_beside(ws, f) for f in list(files)) if local is not None]
    return [f for f in files if f.is_file()]



def text_blocks(text: str) -> List[str]:
    """A Markdown text as its blocks: each bullet or numbered list, table and
    paragraph, split at blank lines and where one kind gives way to another."""
    blocks, current, kind = [], [], None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append("\n".join(current))
            current, kind = [], None
            continue
        this = "table" if stripped.startswith("|") else "list" if re.match(r"(?:[-*+]|\d+[.)])\s", stripped) \
            else "heading" if stripped.startswith("#") else "text"
        if kind == "list" and this == "text" and line[:1].isspace():
            this = "list"                    # an item carried on to the next line
        if current and this != kind:
            blocks.append("\n".join(current))
            current = []
        current.append(line)
        kind = this
    if current:
        blocks.append("\n".join(current))
    return blocks

def check_instructions(ws: Workspace) -> List[Finding]:
    """An AGENTS.md that grows, a sentence copied between instruction files, or a
    hand-kept list of skills that no longer matches the folder: each one drifts."""
    out = []
    # Every repository opens with an AGENTS.md: the root, and each wiki. The
    # zones are checked with the rest of a zone.
    wikis = ws.root / "Wikis"
    needed = [ws.root] + ([wikis] if (wikis / ".git").exists() else [])
    needed += [w for w in visible_dirs(wikis) if w.name in ("Meetings", "Knowledge") or (w / ".git").exists()]
    for folder in needed:
        if not (folder / "AGENTS.md").is_file():
            where = rel(ws, folder) if folder != ws.root else "the workspace root"
            out.append(Finding(ERROR, "instructions", rel(ws, folder / "AGENTS.md"),
                               "missing; an assistant started in %s gets no instructions" % where,
                               "An instruction file is missing"))
    files = instruction_files(ws)
    texts = {f: f.read_text(encoding="utf-8", errors="replace") for f in files}
    budgets = ws.settings.get("word-budgets", {})
    for f, text in texts.items():
        if f.name not in ("AGENTS.md", "AGENTS.local.md"):
            continue
        budget = WORD_BUDGET_ROOT if f.parent == ws.root else WORD_BUDGET_OTHER
        wanted = budgets.get("root" if f.parent == ws.root else "other")
        if isinstance(wanted, int) and wanted > 0:
            budget = wanted
        words = len(text.split())
        if words > budget:
            out.append(Finding(WARNING, "instructions", rel(ws, f),
                               "%d words, over its %d: move what it restates back to the file it points to" % (words, budget),
                               "An instruction file has grown past its budget"))
    rules_file = ws.root / "System" / "rules.md"
    if rules_file in texts and len(texts[rules_file]) > RULES_CHAR_BUDGET:
        out.append(Finding(WARNING, "instructions", rel(ws, rules_file),
                           "%d characters, above the %d it is allowed: it is loaded into every session, so move a "
                           "procedure only one kind of request needs into the skill that runs it" % (
                               len(texts[rules_file]), RULES_CHAR_BUDGET),
                           "The rules file has grown past its budget"))
    # The same sentence in two files, one of them at the root: one is a copy.
    # Zone and wiki files may share boilerplate, since each stands alone in its own repository,
    # and so may the local files over the line the split opens each one with.
    root_files = {ws.root / p for p in ROOT_INSTRUCTIONS + ROOT_LOCALS + ("Wikis/AGENTS.md", "Wikis/AGENTS.local.md")}

    def copy_norm(line: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"^\s*(?:[-*>]|\d+\.)\s*", "", line)).strip().lower()

    header = copy_norm(LOCAL_HEADER)
    seen: Dict[str, set] = {}
    for f, text in texts.items():
        for line in text.splitlines():
            norm = copy_norm(line)
            if len(norm) >= COPY_MIN_CHARS and not norm.startswith(("|", "```")) and norm != header:
                seen.setdefault(norm, set()).add(f)
    for norm, where in sorted(seen.items()):
        if len(where) > 1 and where & root_files:
            names = " and ".join(sorted(rel(ws, w) for w in where))
            out.append(Finding(WARNING, "instructions", names,
                               "the same text in both: \"%s…\"; keep it in one and point from the other" % norm[:60],
                               "Two instruction files say the same thing"))
    # A list of skills names every one of them. A list is several names in
    # one block (one bullet list, one table, one paragraph); names spread over
    # separate sentences each point at one procedure, and are pointers.
    # Garrick's file and the local file beside it are read together.
    skills = {p.parent.name for p in (ws.root / "System" / "skills").glob("*/SKILL.md")}
    for f, text in texts.items():
        if f.name.endswith(".local.md"):
            continue  # read with the file it sits beside
        pair = [g for g in (f, local_beside(ws, f)) if g is not None and g in texts]
        listing = []
        named = set()
        for g in pair:
            for block in text_blocks(texts[g]):
                in_block = {s for s in skills if "`%s`" % s in block}
                if len(in_block) >= 3 and g not in listing:
                    listing.append(g)
        if listing:                             # a list, and every name the pair gives, wherever it stands
            named = {s for s in skills if any("`%s`" % s in texts[g] for g in pair)}
        if named and named != skills:
            out.append(Finding(WARNING, "instructions", " and ".join(rel(ws, g) for g in listing),
                               "lists skills but not %s; list the folder instead of naming them" % ", ".join(sorted(skills - named)),
                               "An instruction file lists skills that no longer match the folder"))
    # A zone's instructions that name its projects' hub notes name every one
    # of them, and only notes that exist: its AGENTS.md and AGENTS.local.md together.
    for zone in ws.zones:
        pair = [g for g in (zone / "AGENTS.md", zone / "AGENTS.local.md") if texts.get(g)]
        if not pair:
            continue
        projects = [p.name for p in project_dirs(zone) if (p / (p.name + ".md")).is_file()]
        listed = [name for g in pair for name in re.findall(r"`([^`/]+)/[^`]*\.md`", texts[g])]
        if not any(name in projects for name in listed):
            continue  # this zone keeps no list of its projects
        lister = next(g for g in reversed(pair) if any(n in projects for n in re.findall(r"`([^`/]+)/[^`]*\.md`", texts[g])))
        for name in projects:
            if name not in listed:
                out.append(Finding(WARNING, "instructions", rel(ws, lister),
                                   "lists project hub notes but not %s/%s.md; list the folder instead of naming them" % (name, name),
                                   "The %s instructions list projects that no longer match the folder" % zone.name))
        for f in pair:
            for m in re.finditer(r"`([^`/]+/[^`]*\.md)`", texts[f]):
                path = m.group(1)
                if path.split("/")[0] in {"..", "System", "Zones", "Wikis"} | {z.name for z in ws.zones}:
                    continue  # a path from another folder, not one of this zone's notes
                if not (zone / path).exists():
                    out.append(Finding(WARNING, "instructions", rel(ws, f), "lists %s, which does not exist" % path,
                                       "The %s instructions name a note that is not there" % zone.name))
    out += split_findings(ws, texts)
    return out


def split_findings(ws: Workspace, texts: Dict[Path, str]) -> List[Finding]:
    """Garrick's instruction files stay as shipped, and the workspace's own
    text lives in the local file beside each. One that differs from what
    Garrick shipped, a local file Garrick's file does not point to, and
    passages a split left to settle."""
    out = []
    files = read_version(ws.root).get("files")
    for f, text in texts.items():
        local = local_beside(ws, f)
        if local is None:
            continue
        r = rel(ws, f)
        want = files.get(r) if isinstance(files, dict) else None
        if isinstance(want, str):
            try:
                changed = fingerprint(f) != want
            except OSError:
                changed = False
            if changed:
                out.append(Finding(WARNING, "instructions", r,
                                   "differs from what Garrick shipped; Garrick's instruction files stay as shipped, so "
                                   "put your own text in %s. The update's split moves it there and puts Garrick's "
                                   "back (say \"update Garrick\")" % rel(ws, local),
                                   "One of Garrick's instruction files was changed here"))
        if local in texts and local.name not in text:
            out.append(Finding(WARNING, "instructions", rel(ws, local),
                               "%s does not point to it, so an assistant may never read it; update Garrick, "
                               "whose %s does" % (r, f.name),
                               "A local instruction file is not pointed to"))
    for f, text in texts.items():
        if not f.name.endswith(".local.md"):
            continue
        lines = text.splitlines()
        at = next((i for i, line in enumerate(lines) if SPLIT_REVIEW_RE.match(line)), None)
        if at is None:
            continue
        end = next((i for i in range(at + 1, len(lines)) if re.match(r"^#{1,2} ", lines[i])), len(lines))
        n = sum(1 for line in lines[at + 1:end] if re.match(r"^### \d+\. ", line))
        out.append(Finding(WARNING, "instructions", rel(ws, f),
                           "still holds %s from the split to settle, under \"%s\"; take them one at a time with "
                           "your assistant (say \"finish the update\")" % (
                               "%d passage%s" % (n, "" if n == 1 else "s") if n else "passages", lines[at][3:].strip()),
                           "The split left passages to settle"))
    return out


def check_placeholders(ws: Workspace, only: Optional[List[Path]] = None) -> List[Finding]:
    """Installer placeholders left unfilled, in a file's name or its text.
    Files git ignores are not the install's: a package's own templates may
    hold the same marks. Nor is a Garrick checkout kept in a project, whose
    templates hold them by design (set_apart). With `only`, those files and
    no others, left out by the same rules."""
    out = []
    apart = set_apart(ws)
    if only is None:
        files = walk_files(ws.root, apart)
    else:
        files = [f for f in only if f.is_file() and f not in apart and not (apart & set(f.parents))]
    for path in files:
        if is_template_path(ws, path) or is_generated(ws, path):
            continue
        if rel(ws, path) == "/".join(VERSION_STAMP):
            continue    # it lists the templates' files, whose names hold placeholders by design
        found = PLACEHOLDER_RE.findall(rel(ws, path))
        if path.suffix.lower() in TEXT_SUFFIXES or path.suffix == "":
            text = read_text(path)
            if text and path.suffix.lower() in (".md", ".markdown"):
                text = CODE_RE.sub("", text)     # a note may quote a placeholder as code
            if text:
                found += PLACEHOLDER_RE.findall(text)
        if found:
            names = ", ".join(sorted(set(found)))
            out.append(Finding(ERROR, "placeholders", rel(ws, path),
                               "unfilled %s; the install did not finish" % names,
                               "A file still holds installer placeholders"))
    return out


# What a section the checks cannot read leaves undone, said after its fix.
CONTEXT_EFFECT = {
    "people": "; until then the wall check sees no one's name",
    "parties": "; until then no wall can be checked",
    "aliases": "; until then no heard name resolves",
    "zones": "; until then no zone folder is checked against it",
}


def check_context(ws: Workspace) -> List[Finding]:
    out = []
    ctx_path = "System/context.md"
    if not (ws.root / ctx_path).is_file():
        return [Finding(ERROR, "context", ctx_path, "missing; walls and aliases cannot be read", "The context file is missing")]
    parties = ws.context["parties"]
    unread = set()
    for name, (shown, _) in CONTEXT_TABLES.items():
        seen = ws.context.get("tables", {}).get(name)
        if not seen:
            continue
        title = name.capitalize()
        wanted = ", ".join(shown)
        if seen["text"] and not seen["table"]:
            unread.add(name)
            out.append(Finding(ERROR, "context", ctx_path,
                               "%s is written as prose or a list; the checks cannot read anything in it. "
                               "Make it a table: %s%s" % (title, wanted, CONTEXT_EFFECT.get(name, "")),
                               "The %s section of the context file is not a table" % title))
        elif [c for c in seen["missing"] if c != "walled"]:
            out.append(Finding(WARNING, "context", ctx_path,
                               "the %s table has no %s column; it needs %s" % (
                                   title, " or ".join(c.capitalize() for c in seen["missing"] if c != "walled"), wanted),
                               "The %s table is missing a column" % title))
    text = read_text(ws.root / ctx_path) or ""
    if "walled" in (ws.context.get("tables", {}).get("parties") or {}).get("missing", []):
        out.append(Finding(WARNING, "context", ctx_path,
                           "the Parties table has no Walled column, so the walls migration has not run and every party "
                           "is read as walled; run the update (`python3 install.py --update`) and read what it shows",
                           "The walls migration is pending"))
    if re.search(r"(?m)^## Walls\s*$", text):
        out.append(Finding(WARNING, "context", ctx_path,
                           "a Walls table is still there, and nothing reads it; the Walled column holds the policy. "
                           "Take the section out",
                           "A Walls table is left in the context file"))
    if not parties and "parties" not in unread:
        out.append(Finding(WARNING, "context", ctx_path, "the Parties table is empty; no wall can be checked",
                           "The Parties table is empty"))
    for tag, entry in sorted(parties.items()):
        if entry.get("flag") not in ("yes", "no"):
            out.append(Finding(WARNING, "context", ctx_path,
                               "party `%s` has no `yes` or `no` in Walled; it is read as walled" % tag,
                               "Party %s has no Walled flag" % (entry.get("party") or tag)))
    for zone, tag in sorted(ws.context["zone_parties"].items()):
        if tag not in parties:
            out.append(Finding(ERROR, "context", ctx_path,
                               "zone %s names `%s` as its party, which is not a tag in Parties" % (zone, tag),
                               "The %s zone names an unknown party" % zone))
    zone_names = {z.name for z in ws.zones}
    for tag, entry in sorted(parties.items()):
        z = entry.get("zone", "").strip()
        if z and zone_names and z not in zone_names:
            out.append(Finding(WARNING, "context", ctx_path,
                               "party `%s` belongs to zone %s, which has no folder under Zones/" % (tag, z),
                               "Party %s belongs to a zone that does not exist" % entry.get("party", tag)))
    owners: Dict[str, List[str]] = {}
    for tag, entry in sorted(parties.items()):
        for domain in entry.get("domains", []):
            owners.setdefault(domain, []).append(tag)
            name = entry.get("party") or tag
            if is_webmail(domain):
                out.append(Finding(WARNING, "context", ctx_path,
                                   "%s is listed for %s, but personal webmail never names a party; take it out" % (domain, name),
                                   "A webmail domain is listed for %s" % name))
            elif not is_domain(domain):
                out.append(Finding(WARNING, "context", ctx_path, "%r in %s's Domains is not a mail domain" % (domain, name),
                                   "A domain listed for %s is not a mail domain" % name))
    for domain, tags in sorted(owners.items()):
        if len(tags) > 1:
            out.append(Finding(WARNING, "context", ctx_path,
                               "%s is listed for %s; mail from it will always be asked about" % (domain, " and ".join(tags)),
                               "One domain is listed for two parties"))
    for person in ws.context["people"]:
        if person["party"] and person["party"] not in parties:
            out.append(Finding(WARNING, "context", ctx_path,
                               "%s belongs to `%s`, which is not a tag in Parties" % (person["name"], person["party"]),
                               "%s belongs to an unknown party" % person["name"]))
    if "none" in parties:
        out.append(Finding(ERROR, "context", ctx_path,
                           "the Parties table has a row for `none`, which is reserved: it says a page is nobody's, "
                           "so it is never a party's tag; take the row out",
                           "The Parties table defines the reserved tag none"))
    listed = set(ws.context["zones"])
    for zone in ws.zones:
        if listed and zone.name not in listed:
            out.append(Finding(WARNING, "context", ctx_path, "zone %s is not in the Zones table" % zone.name,
                               "The %s zone is missing from the context file" % zone.name))
    # One name, two tags: the same organisation in two hats. Both stay walled, or the name alone
    # can carry one hat's material into the other's.
    by_name: Dict[str, List[str]] = {}
    for tag, entry in sorted(parties.items()):
        key = " ".join(words(entry.get("party") or ""))
        if key:
            by_name.setdefault(key, []).append(tag)
    for tags in (t for t in by_name.values() if len(t) > 1):
        for tag in tags:
            if not is_walled(ws.context, tag):
                out.append(Finding(WARNING, "context", ctx_path,
                                   "`%s` shares its name with `%s` and is open; both hats stay walled" % (
                                       tag, next(t for t in tags if t != tag)),
                                   "Two parties share a name and one is open"))
    if not re.search(r"(?m)^## Aliases\s*$", text):
        out.append(Finding(WARNING, "context", ctx_path,
                           "no `## Aliases` table (| Heard | Means |); names that arrive mangled by dictation have nothing to match",
                           "The context file has no aliases table"))
    return out


ORIGIN_FIX = "add `source:` (user, file:<path> or inbound:<raw path>) and `created:` (YYYY-MM-DD) to its frontmatter"
INBOUND_FIX = ("its only source is inbound, and nothing that came in from outside stands as a belief until a person "
               "confirms it: ask, then add `user` to its source, or delete it")


def check_memory(ws: Workspace) -> List[Finding]:
    """Every learned entry says where it came from. A memory entry, in the
    folders `memory` names in the check settings, carries `source:` and
    `created:`; a row with a Learned cell in System/context.md has one that
    reads. Either whose only source is inbound is reported too. Without the
    setting no memory is read: where a harness keeps one is not Garrick's to
    guess. A row typed by hand has no Learned cell, and nothing is said."""
    out = []
    for path in memory_entries(memory_folders(ws.root, ws.settings.get("memory") or [])):
        origin = memory_origin(read_text(path) or "")
        r = rel(ws, path)
        problems = origin_problems(origin)
        if problems:
            out.append(Finding(WARNING, "memory", r, "a learned entry with no origin: %s; %s" % (
                "; ".join(problems), ORIGIN_FIX), "A memory entry does not say where it came from"))
        elif inbound_only(as_sources(origin.get("source"))):
            out.append(Finding(WARNING, "memory", r, "a learned entry whose %s" % INBOUND_FIX,
                               "A memory entry came only from a mail, a transcript or a page"))
    ctx_path = "System/context.md"
    for entry in ws.context.get("learned", []):
        read = parse_learned(entry["cell"])
        where = "the %s row %s" % (entry["table"].capitalize(), entry["row"] or "with no name")
        if read is None:
            continue
        date, sources = read
        if not date or not sources or not all(is_origin(s) for s in sources):
            out.append(Finding(WARNING, "memory", ctx_path,
                               "%s has a Learned cell that does not read as `YYYY-MM-DD, source`: `%s`" % (where, entry["cell"]),
                               "A learned row in the context file does not say where it came from"))
        elif inbound_only(sources):
            out.append(Finding(WARNING, "memory", ctx_path, "%s is learned, and %s" % (where, INBOUND_FIX),
                               "A row in the context file came only from a mail, a transcript or a page"))
    return out


def check_zones(ws: Workspace) -> List[Finding]:
    out = []
    if not (ws.root / "Zones").is_dir():
        return [Finding(ERROR, "zones", "Zones", "no Zones folder", "There is no Zones folder")]
    if not ws.zones:
        out.append(Finding(WARNING, "zones", "Zones", "no zones yet", "There are no zones yet"))
    for zone in ws.zones:
        r = rel(ws, zone)
        if not (zone / ".git").exists():
            out.append(Finding(ERROR, "zones", r, "not its own git repository; run `git init` inside it",
                               "The %s zone is not its own repository" % zone.name))
        elif (zone / ".git").is_dir() and not has_wall_hook(zone):
            out.append(Finding(WARNING, "zones", r,
                               "no pre-commit wall check; run `python3 System/tools/check.py --install-hooks`",
                               "The %s zone does not check the walls before a commit" % zone.name))
        for name in ("AGENTS.md", "Todo.md"):
            if not (zone / name).is_file():
                out.append(Finding(ERROR, "zones", r, "has no %s" % name,
                                   "The %s zone has no %s" % (zone.name, "to-do list" if name == "Todo.md" else "instructions")))
        if not (zone / INBOX).is_dir():
            out.append(Finding(WARNING, "zones", r, "has no %s/ folder; mail and files for this zone have nowhere to land" % INBOX,
                               "The %s zone has no inbox" % zone.name))
    wikis = ws.root / "Wikis"
    for wiki in [wikis] + visible_dirs(wikis):
        git_dir = wiki / ".git"
        if os.path.lexists(str(git_dir)) and (git_dir.is_symlink() or not git_dir.is_dir()):
            out.append(Finding(WARNING, "zones", rel(ws, wiki),
                               "its .git is a file or a link pointing elsewhere; Garrick checks a wiki only when "
                               "its .git is a folder inside it, so commits here are refused",
                               "The %s wiki's .git is not a folder inside it" % wiki.name))
        elif git_dir.is_dir() and not has_wall_hook(wiki):
            out.append(Finding(WARNING, "zones", rel(ws, wiki),
                               "no pre-commit wall check; a hand edit committed here is read by the next full check "
                               "alone. Run `python3 System/tools/check.py --install-hooks`",
                               "The %s wiki does not check the walls before a commit" % wiki.name))
    return out


def wiki_repos(ws: Workspace) -> List[Path]:
    """The wikis that are a git repository of their own: `Wikis/` and each
    wiki under it with a `.git` folder (#340)."""
    wikis = ws.root / "Wikis"
    return [w for w in [wikis] + visible_dirs(wikis) if (w / ".git").is_dir()]


def hooks_elsewhere(repo: Path) -> Optional[Tuple[str, Path]]:
    """(the setting, the folder it names) when `core.hooksPath` sends git
    anywhere but the repository's own hooks folder, whichever config sets it:
    the repository's, the user's or the system's. None when it is unset, names
    the repository's own hooks, or `repo` is not the top of a repository."""
    if not _own_repo(repo):
        return None
    value = (_git(["config", "--get", "core.hooksPath"], repo) or "").strip()
    if not value:
        return None
    common = (_git(["rev-parse", "--git-common-dir"], repo) or "").strip() or ".git"
    own = repo / common / "hooks"
    where = Path(os.path.expanduser(value))
    if not where.is_absolute():
        where = repo / where  # git reads a relative hooks path from the top of the working tree
    try:
        if os.path.samefile(where, own):
            return None
    except OSError:
        if os.path.realpath(where) == os.path.realpath(own):
            return None
    return value, where


# What marks the history of Garrick's copy of a piece of work's files, kept
# in the project's Files/ folder (#189, the status extra's work_files.py).
GARRICK_HISTORY = "garrick-history"


def project_repos(ws: Workspace) -> List[Tuple[Path, Path, dict]]:
    """(repository, its project, the project's hub frontmatter) for every git
    repository inside a project: a product's code, a site, a book. Each is
    found at its top; nothing below one is looked in."""
    out = []
    for project, pfm in ws.projects:
        for folder, dirs, _ in os.walk(project):
            here = Path(folder)
            keep = []
            for d in sorted(dirs):
                if d in SKIP_DIRS or d.startswith("."):
                    continue
                if (here / d / ".git" / GARRICK_HISTORY).is_file():
                    continue            # Garrick's own copy of a work's files (#189): never pushed, no hook to guard it
                if (here / d / ".git").exists():
                    out.append((here / d, project, pfm))
                else:
                    keep.append(d)
            dirs[:] = keep
    return out


def has_remote(repo: Path) -> bool:
    return bool((_git(["remote"], repo) or "").strip())


def check_hooks(ws: Workspace) -> List[Finding]:
    """A zone's wall check sits in its own .git/hooks, and git runs the hooks
    there only while `core.hooksPath` is unset or names that folder. Set
    anywhere else, in the repository, for the user or for the whole machine,
    every commit skips the check and nothing says so."""
    out = []
    wikis = ws.root / "Wikis"
    repos = [(z, True) for z in ws.zones] + [(w, False) for w in [wikis] + visible_dirs(wikis)]
    for repo, is_zone in repos:
        if not (repo / ".git").exists():
            continue
        found = hooks_elsewhere(repo)
        if found is None:
            continue
        value, where = found
        hook = where / "pre-commit"
        try:
            text = hook.read_text(encoding="utf-8", errors="replace")
            runs = WALL_HOOK_MARK in text and os.access(hook, os.X_OK)
            if runs and (is_zone or '--root "$dir"' in text):
                continue  # the folder it names runs the wall check too
            if runs:
                # A zone's hook looks for the check two folders up, which a wiki is not under (#340).
                out.append(Finding(WARNING, "hooks", rel(ws, repo),
                                   "git takes its hooks from %s (core.hooksPath), and the wall check there is the "
                                   "zone's, which looks for the check two folders up and refuses every commit in a "
                                   "wiki; use `git config core.hooksPath .git/hooks` in %s, and "
                                   "`python3 System/tools/check.py --install-hooks`" % (value, rel(ws, repo)),
                                   "Git runs a zone's wall check on the %s repository" % repo.name))
                continue
        except OSError:
            pass
        what = "the wall check in its .git/hooks" if is_zone or has_wall_hook(repo) else "any hook in its own .git/hooks"
        out.append(Finding(WARNING, "hooks", rel(ws, repo),
                           "git takes its hooks from %s (core.hooksPath), so %s never runs before a commit; "
                           "run `git config core.hooksPath .git/hooks` in %s" % (value, what, rel(ws, repo)),
                           ("Git skips the wall check in the %s zone" % repo.name) if is_zone
                           else "Git skips the hooks of the %s repository" % repo.name))
    # A repository inside a project is the likeliest to be pushed somewhere
    # public, and the zone's hook never sees its commits.
    for repo, project, _ in project_repos(ws):
        if not (repo / ".git").is_dir() or has_wall_hook(repo) or not has_remote(repo):
            continue
        out.append(Finding(WARNING, "hooks", rel(ws, repo),
                           "a repository inside %s, with a remote, and no wall check before its commits; "
                           "run `python3 System/tools/check.py --install-hooks`" % project.name,
                           "A repository inside %s pushes without a wall check" % project.name))
    return out


MODEL_VERSION_RE = re.compile(r"\d")
VENDORED = "VENDORED.md"


def skill_repos(ws: Workspace) -> List[Path]:
    """The folders an assistant's session can start in and look up from for
    skills: the root, each zone, and the wikis' repository or repositories."""
    wikis = ws.root / "Wikis"
    out = [ws.root] + list(ws.zones)
    out += [w for w in [wikis] + visible_dirs(wikis) if (w / ".git").exists()]
    return out


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def check_skills(ws: Workspace) -> List[Finding]:
    """Both assistants find every skill in System/skills from wherever a
    session starts, through the repository's skill link or the user's own;
    a retired skill stays retired; a skill names a model by tier, not version;
    a skill copied from elsewhere names the commit it came from."""
    out = []
    folder = ws.root / "System" / "skills"
    skills = sorted(p.parent.name for p in folder.glob("*/SKILL.md"))
    home = Path.home()
    for repo in skill_repos(ws):
        where = rel(ws, repo) if repo != ws.root else "the workspace root"
        for f in SKILL_FOLDERS:
            missing = [s for s in skills
                       if not (_same(repo / f / "skills" / s, folder / s) or _same(home / f / "skills" / s, folder / s))]
            if missing:
                out.append(Finding(WARNING, "skills", rel(ws, repo / f / "skills"),
                                   "a session started in %s finds no %s; link `%s/skills` to System/skills"
                                   % (where, ", ".join(missing), f),
                                   "An assistant cannot find some skills"))
        # A repository with skills of its own shows the same ones to both assistants.
        seen = [{p.name for p in (repo / f / "skills").iterdir() if (p / "SKILL.md").is_file()}
                if (repo / f / "skills").is_dir() else None for f in SKILL_FOLDERS]
        if all(s is not None for s in seen) and len({frozenset(s) for s in seen}) > 1:
            only = sorted(set.union(*seen) - set.intersection(*seen))
            out.append(Finding(WARNING, "skills", rel(ws, repo),
                               "%s show different skills (only in one: %s); point one at the other"
                               % (" and ".join("`%s/skills`" % f for f in SKILL_FOLDERS), ", ".join(only)),
                               "The two assistants see different skills"))
    retired = {k: v for k, v in ws.settings.get("retired-skills", {}).items() if isinstance(v, str)}
    if retired:
        live = [ws.root / p for p in ROOT_INSTRUCTIONS + ROOT_LOCALS] + [z / n for z in ws.zones
                                                                           for n in ("AGENTS.md", "AGENTS.local.md")]
        for sub in ("skills", "templates", "tools"):
            live += [p for p in walk_files(ws.root / "System" / sub) if p.suffix in (".md", ".py", ".sh")]
        texts = [(p, read_text(p) or "") for p in live if p.is_file()]
        for name, by in sorted(retired.items()):
            if (folder / name).exists():
                out.append(Finding(ERROR, "skills", rel(ws, folder / name),
                                   "is back; it was retired for `%s`" % by, "A retired skill is back"))
            for f in SKILL_FOLDERS:
                link = home / f / "skills" / name
                if os.path.lexists(link):
                    out.append(Finding(WARNING, "skills", str(link),
                                       "still links the retired skill %s; remove the link" % name,
                                       "A retired skill is still linked"))
            pattern = re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(name))
            for p, text in texts:
                hit = next((i for i, line in enumerate(text.splitlines(), 1)
                            if pattern.search(line) and "retired" not in line.lower()), None)
                if hit:
                    out.append(Finding(WARNING, "skills", "%s:%d" % (rel(ws, p), hit),
                                       "still sends work to `%s`, which was retired; point it at `%s`" % (name, by),
                                       "An instruction still names a retired skill"))
    for s in skills:
        model = parse_frontmatter(folder / s / "SKILL.md").get("model")
        if isinstance(model, str) and MODEL_VERSION_RE.search(model):
            out.append(Finding(WARNING, "skills", "System/skills/%s/SKILL.md" % s,
                               "`model` is %s, a version; name a tier, such as sonnet or opus, so the skill "
                               "follows each new release" % model,
                               "The %s skill is pinned to one model version" % s))
        vendored = folder / s / VENDORED
        if vendored.is_file() and not re.search(r"Commit:\s*`?[0-9a-f]{7,40}\b", read_text(vendored) or ""):
            out.append(Finding(WARNING, "skills", rel(ws, vendored),
                               "names no source commit (`Commit: <hash>`); without it nobody can tell what to update from",
                               "A copied skill does not say where it came from"))
    return out


def _check_siblings(ws: Workspace, folders: List[Path], level: str, out: List[Finding]) -> None:
    """The three naming questions, folder by folder: can it be stored and does
    it read as a name (`is_display_name`, an error either way), does it say how
    it is said or carry a `spoken` form (a warning), and can a sibling be told
    from it by ear, through either's spoken form."""
    for folder in folders:
        ok, why = is_display_name(folder.name)
        if not ok:
            out.append(Finding(ERROR, "names", rel(ws, folder), "%s name will not work: %s" % (level, why),
                               "The %s name %s will not work" % (level, folder.name)))
            continue
        said, why = is_sayable(folder.name)
        spoken = spoken_of(folder)
        note = folder / (folder.name + ".md")
        where = rel(ws, note if note.is_file() else folder)
        if level == "zone":
            if not said:
                out.append(Finding(ERROR, "names", rel(ws, folder),
                                   "zone name does not say how it is said: %s, and a zone has no note to carry "
                                   "a `spoken` form" % why,
                                   "The zone name %s cannot be said as written" % folder.name))
        elif not said and not spoken:
            out.append(Finding(WARNING, "names", where,
                               "%s name does not say how it is said: %s; give the note a `spoken:` form, so "
                               "asking for it by ear finds it" % (level, why),
                               "The %s %s has no spoken form" % (level, folder.name)))
        elif spoken:
            ok, why = is_sayable(spoken)
            if not ok:
                out.append(Finding(WARNING, "names", where,
                                   "`spoken: %s` does not say how it is said either: %s" % (spoken, why),
                                   "The spoken form of %s cannot be said as written" % folder.name))
    for i, a in enumerate(folders):
        for b in folders[i + 1:]:
            clash = spoken_clash(a.name, b.name, spoken_of(a), spoken_of(b))
            if clash:
                heard = "" if clash == (a.name, b.name) else ", said \"%s\" and \"%s\"" % clash
                out.append(Finding(WARNING, "names", rel(ws, a.parent),
                                   "%ss \"%s\" and \"%s\" sound alike%s" % (level, a.name, b.name, heard),
                                   "The %ss %s and %s sound alike" % (level, a.name, b.name)))


def check_names(ws: Workspace) -> List[Finding]:
    out: List[Finding] = []
    _check_siblings(ws, ws.zones, "zone", out)
    for zone in ws.zones:
        _check_siblings(ws, project_dirs(zone), "project", out)
    for project, _ in ws.projects:
        _check_siblings(ws, visible_dirs(project / "Threads"), "thread", out)
    return out


# The values the templates and the threads skill write, and nothing else: a
# thread is set aside with parked and closed with done. A project takes the
# same three, since one with no thread notes is parked as a thread of its own.
# Any other word reads as live to every tool, whatever it meant.
THREAD_STATUSES = ("active", "parked", "done")
PROJECT_STATUSES = THREAD_STATUSES
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad_dates(fm: dict) -> List[str]:
    """`created` and `updated` values that are not a real YYYY-MM-DD date."""
    out = []
    for key in ("created", "updated"):
        value = fm.get(key)
        if value is None:
            continue
        text = value.strip() if isinstance(value, str) else ""
        try:
            ok = bool(ISO_DATE_RE.match(text)) and bool(datetime.date(int(text[:4]), int(text[5:7]), int(text[8:])))
        except ValueError:
            ok = False
        if not ok:
            out.append("`%s` is %r, should be a date written YYYY-MM-DD" % (key, value))
    return out


def bad_status(fm: dict, allowed: Tuple[str, ...]) -> Optional[str]:
    """The `status` value when it is set to anything but one of `allowed`."""
    value = fm.get("status")
    if value is None:
        return None  # read as active by every tool
    if isinstance(value, str) and value.strip().lower() in allowed:
        return None
    return "`status` is %r, should be %s" % (value, " or ".join(", ".join(allowed).rsplit(", ", 1)))


def in_system(ws: Workspace, project: Path) -> bool:
    """A project about the workspace itself, kept in System/ rather than a zone."""
    return project.parent == ws.root / "System"


def renamed_note(folder: Path) -> str:
    """When `<Name>.md` is missing but `<Name>-v2.md` (or later) is there, a
    hint saying so: hub and thread notes are found by their exact name."""
    found = sorted(p.name for p in folder.glob("*.md") if re.fullmatch(re.escape(folder.name) + r"-v\d+\.md", p.name))
    return "; %s is there, but these notes are found by name, so rename it back" % found[-1] if found else ""


def own_resume(text: str) -> bool:
    """Does a hub hold the project's resume point itself, as a project that
    is one thread does: a `### Resume here` block, or its `### Outcome`?"""
    return any(l.strip().lower() in ("### resume here", "### outcome") for l in text.splitlines())


def link_names(text: str) -> set:
    """The last part of every wikilink in `text`, lower-cased, without .md."""
    out = set()
    for m in WIKILINK_RE.finditer(text):
        target = m.group(1).split("|", 1)[0].split("#", 1)[0].strip().rstrip("\\")
        if target:
            out.add(_strip_md(tuple(target.split("/")))[-1].strip().lower())
    return out


def section(text: str, heading: str) -> str:
    """The body of a `## <heading>` section, up to the next `## ` heading."""
    m = re.search(r"(?ms)^## %s[ \t]*$(.*?)(?=^## |\Z)" % re.escape(heading), text)
    return m.group(1) if m else ""


LAYOUTS = ("thread-first",)
# The only folders a thread-first project keeps outside its threads.
THREAD_FIRST_ALLOWED = {"threads", "archive"}


def check_projects(ws: Workspace) -> List[Finding]:
    out = []
    for project, fm in ws.projects:
        hub = project / (project.name + ".md")
        r = rel(ws, hub)
        system = in_system(ws, project)
        spoken = "%s, %s" % (project.parent.name, project.name)
        if not hub.is_file():
            out.append(Finding(ERROR, "projects", rel(ws, project), "no hub note %s.md%s" % (project.name, renamed_note(project)),
                               "Project %s has no hub note" % spoken))
            continue
        if fm.get("type") != "project":
            out.append(Finding(ERROR, "projects", r, "frontmatter `type` is %r, should be project" % fm.get("type"),
                               "The %s hub note is not marked as a project" % project.name))
        if fm.get("zone") != project.parent.name and not (system and fm.get("zone") is None):
            out.append(Finding(ERROR, "projects", r,
                               "frontmatter `zone` is %r but the project sits in %s" % (fm.get("zone"), project.parent.name),
                               "The %s hub note names the wrong zone" % project.name))
        status = bad_status(fm, PROJECT_STATUSES)
        if status:
            out.append(Finding(ERROR, "projects", r, status, "Project %s has a status no tool reads" % project.name))
        for problem in bad_dates(fm):
            out.append(Finding(ERROR, "projects", r, problem, "The %s hub note has a date in the wrong form" % project.name))
        threads = visible_dirs(project / "Threads")
        tags = [strip_tag(t) for t in as_list(fm.get("party"))]
        if not tags and not system:
            out.append(Finding(ERROR, "projects", r,
                               "no `party`; set `party:` in this hub to a tag from the Parties table. Until it does, no "
                               "file of the project can be committed, and it cannot draw on the Meetings wiki",
                               "Project %s has no party" % project.name))
        for tag in tags:
            if tag not in ws.context["parties"]:
                out.append(Finding(ERROR, "projects", r, "`party` %s is not a tag in the Parties table" % tag,
                                   "Project %s names an unknown party" % project.name))
        text = read_text(hub) or ""
        if not threads and not own_resume(text):
            out.append(Finding(WARNING, "projects", rel(ws, project),
                               "no threads; every piece of work belongs to one, or, in a project that is one thread, "
                               "to the hub's own `### Resume here` block",
                               "Project %s has no threads" % project.name))
        # The hub is the project's index: it links every thread, and lists a
        # finished one under ## Finished.
        linked = link_names(text)
        finished = section(text, "Finished").lower()
        for thread in threads:
            if thread.name.lower() not in linked:
                out.append(Finding(WARNING, "projects", r, "does not link the thread %s; the hub lists every thread" % thread.name,
                                   "The %s hub note does not list the thread %s" % (project.name, thread.name)))
            elif str(parse_frontmatter(thread / (thread.name + ".md")).get("status") or "").strip().lower() == "done" \
                    and thread.name.lower() not in finished:
                out.append(Finding(WARNING, "projects", r,
                                   "the finished thread %s is not listed under `## Finished`" % thread.name,
                                   "The %s hub note does not list the finished thread %s" % (project.name, thread.name)))
        # Where the project's files are, when they are not in the project: a
        # folder left in place, such as a shared drive. Read, never written.
        if "folder" in fm:
            where = work_folder(ws.root, fm.get("folder"))
            if where is None:
                out.append(Finding(WARNING, "projects", r,
                                   "`folder` is empty; name the folder the project's files are in, or take the key out",
                                   "The %s hub note names no folder for its files" % project.name))
            elif not where.is_dir():
                out.append(Finding(WARNING, "projects", r,
                                   "`folder` is %s, which is %s" % (str(fm.get("folder")).strip(),
                                                                    "a file, not a folder" if where.exists() else "not there"),
                                   "The %s hub note points at a folder that is not there" % project.name))
            else:
                # The work's page lists the folder's file names, so a folder in
                # another zone or a wiki would show them across a zone's walls.
                crossed = folder_elsewhere(ws, project, where)
                if crossed:
                    out.append(Finding(WARNING, "projects", r,
                                       "`folder` is %s, which is %s; the work's page would list that folder's file "
                                       "names here. Name a folder outside the zones and wikis, or in this project's zone"
                                       % (str(fm.get("folder")).strip(), crossed),
                                       "The %s hub note points into %s" % (project.name, crossed)))
        layout = fm.get("layout")
        if layout is not None and layout not in LAYOUTS:
            out.append(Finding(WARNING, "projects", r, "`layout` is %r; the one there is: %s" % (layout, ", ".join(LAYOUTS)),
                               "The %s hub note names a layout no check knows" % project.name))
        elif layout == "thread-first":
            for folder in visible_dirs(project):
                if folder.name.lower() not in THREAD_FIRST_ALLOWED:
                    out.append(Finding(WARNING, "projects", rel(ws, folder),
                                       "the project is thread-first, so everything sits inside a thread: move it into "
                                       "Threads/<Thread>/, and give material with no thread a thread of its own",
                                       "Project %s keeps a folder outside its threads" % project.name))
    return out


def check_threads(ws: Workspace) -> List[Finding]:
    out = []
    for project, pfm in ws.projects:
        ptags = {strip_tag(t) for t in as_list(pfm.get("party"))}
        for thread in visible_dirs(project / "Threads"):
            note = thread / (thread.name + ".md")
            r = rel(ws, note)
            spoken = "%s, %s" % (project.name, thread.name)
            if not note.is_file():
                out.append(Finding(ERROR, "threads", rel(ws, thread), "no thread note %s.md%s" % (thread.name, renamed_note(thread)),
                                   "Thread %s has no note" % spoken))
                continue
            fm = parse_frontmatter(note)
            if fm.get("type") != "thread":
                out.append(Finding(ERROR, "threads", r, "frontmatter `type` is %r, should be thread" % fm.get("type"),
                                   "Thread %s is not marked as a thread" % spoken))
            status = bad_status(fm, THREAD_STATUSES)
            if status:
                out.append(Finding(ERROR, "threads", r, status, "Thread %s has a status no tool reads" % spoken))
            for problem in bad_dates(fm):
                out.append(Finding(ERROR, "threads", r, problem, "Thread %s has a date in the wrong form" % spoken))
            text = read_text(note) or ""
            lines = [l.strip() for l in text.splitlines()]
            try:
                sop = lines.index("## State of play")
            except ValueError:
                sop = -1
            done = str(fm.get("status") or "").strip().lower() == "done"
            if done:
                # A finished thread keeps an Outcome where the resume point was.
                outcome = next((i for i, l in enumerate(lines) if l.lower() == "### outcome"), -1)
                if outcome < 0:
                    out.append(Finding(ERROR, "threads", r, "status is done but there is no `### Outcome` block",
                                       "Thread %s is done but has no outcome" % spoken))
                elif sop >= 0 and outcome < sop:
                    out.append(Finding(ERROR, "threads", r, "`### Outcome` sits outside `## State of play`",
                                       "Thread %s has its outcome in the wrong place" % spoken))
            else:
                resume = next((i for i, l in enumerate(lines) if l.lower() == "### resume here"), -1)
                if sop < 0:
                    out.append(Finding(ERROR, "threads", r, "no `## State of play` section",
                                       "Thread %s has no state of play" % spoken))
                if resume < 0:
                    out.append(Finding(ERROR, "threads", r, "no `### Resume here` block",
                                       "Thread %s has no resume point" % spoken))
                elif sop >= 0 and resume < sop:
                    out.append(Finding(ERROR, "threads", r, "`### Resume here` sits outside `## State of play`",
                                       "Thread %s has its resume point in the wrong place" % spoken))
            link = str(fm.get("project") or "")
            if link and project.name.lower() not in link.lower():
                out.append(Finding(WARNING, "threads", r, "`project` is %s but the thread sits in %s" % (link, project.name),
                                   "Thread %s points at the wrong project" % spoken))
            ttags = {strip_tag(t) for t in as_list(fm.get("party"))}
            for tag in sorted(ttags - set(ws.context["parties"])):
                out.append(Finding(ERROR, "threads", r, "`party` %s is not a tag in the Parties table" % tag,
                                   "Thread %s names an unknown party" % spoken))
            if "none" in ttags:
                out.append(Finding(ERROR, "threads", r,
                                   "`party` is `none`; a thread says whose it is, and `none` is nobody, so no label",
                                   "Thread %s names no party" % spoken))
    return out


RESUME_END_RE = re.compile(r"^(#{1,3} |---\s*$)")
TICK_RE = re.compile(r"`([^`\n]+)`")
PATHLIKE_RE = re.compile(r"^[\w./~ ()&',+-]+(\.[A-Za-z0-9]{1,5}|/)$")
COMMAND_RE = re.compile(r"^(python3?|bash|sh|node|open|cd|git|gh)\s")


def resume_block(text: str) -> List[str]:
    """The lines of a note's `### Resume here` block, up to the next heading or rule."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "### resume here"), -1)
    if start < 0:
        return []
    out = []
    for line in lines[start + 1:]:
        if RESUME_END_RE.match(line.strip()):
            break
        out.append(line)
    return out


# A Resume here block as the thread template leaves it: its date and table
# cells still hold the template's <angle-bracket> prompts.
# The labels of its table's rows, as the thread template ships them.
RESUME_LABELS = ("Live artifact", "Rebuild with", "Next action", "Keep in mind", "Waiting on", "Deadline")
RESUME_PROMPT_RE = re.compile(r"^\s*\|\s*(%s)\s*\|\s*<" % "|".join(re.escape(label) for label in RESUME_LABELS))
RESUME_DATE_PROMPT = "**Where it stands, <"


# A line that says its file sits on a shared or synced drive: the path is
# read there, not here, and the check cannot see it.
SHARE_RE = re.compile(r"\b(?:share|shared|sharepoint|onedrive|google drive|dropbox)\b", re.I)
# A part inside an Office file, which is a zip: `xl/workbook.xml`, `word/document.xml`.
OFFICE_PART_RE = re.compile(r"^(?:xl|ppt|word|docProps|customXml|_rels)/")
STALE_DAYS = 14
# Files that are not work on a thread: archives, build output, scripts and hidden files.
NOT_WORK_RE = re.compile(r"(?:^|/)(?:archive|render[^/]*|build)/|\.(?:py|sh)$|(?:^|/)\.", re.I)


def live_status(fm: dict) -> bool:
    return str(fm.get("status") or "").strip().lower() not in ("done", "parked")


def path_bases(ws: Workspace, project: Path, note: Path) -> List[Path]:
    """Where a relative path written in a note may start: the note's folder and
    those above it in the project, the project's own folders, the zone, the
    workspace, the wikis and the skills."""
    bases, d = [], note.parent
    while d == project or project in d.parents:
        bases.append(d)
        d = d.parent
    bases += [x for x in visible_dirs(project) if x not in bases]
    bases += [project.parent, ws.root / "Zones", ws.root, ws.root / "Wikis"] + visible_dirs(ws.root / "Wikis")
    bases += [ws.root / "System" / "skills"]
    return bases


def local_base_count(project: Path, note: Path) -> int:
    """How many of path_bases() are the note's own: its folder and those above
    it in the project, and the project's own folders."""
    bases, d = [], note.parent
    while d == project or project in d.parents:
        bases.append(d)
        d = d.parent
    return len(bases) + len([x for x in visible_dirs(project) if x not in bases])


Siblings = Tuple[set, List[Tuple[Path, Path]], Dict[Path, set]]


def sibling_bases(ws: Workspace, project: Path, note: Path) -> Siblings:
    """Where a path into another project of the same zone may start, as
    (base, the sibling project): each sibling's own folder and its threads'
    folders, with the tags `note` is written for. A note may name a file one
    project over, `Deliverables/<deck>.pptx` of the project the work goes on
    from. Never a project outside the zone, nor one under System/, nor a
    project or thread whose party is walled from the note's; sibling_found
    holds every hit to the same, so a path found only there is reported as
    missing. Worked out once per note; the third part caches each sibling's
    files as they are named on disk, listed on its first hit."""
    zone = project.parent
    if zone not in ws.zones:
        return set(), [], {}
    pfm = next((fm for folder, fm in ws.projects if folder == project), {})
    mine, _ = file_tags(ws, project, {strip_tag(t) for t in as_list(pfm.get("party"))}, note)
    out: List[Tuple[Path, Path]] = []
    for other, _ in ws.projects:
        if other.parent != zone or other == project:
            continue
        hub = project_file_tags(ws, other, other / (other.name + ".md"))
        if blocked(ws.context, mine, hub):
            continue
        out.append((other, other))
        for thread in visible_dirs(other / "Threads"):
            if not blocked(ws.context, mine, project_file_tags(ws, other, thread / (thread.name + ".md"))):
                out.append((thread, other))
    return mine, out, {}


def sibling_found(ws: Workspace, siblings: Siblings, path: str) -> bool:
    """Is `path` a file of a sibling project, read from one of its bases? Its
    real path must be one of that project's files as they are named on disk,
    in a project folder that sits in the zone: so a link or `..` leading into
    a walled project or another zone confirms nothing, and nor does a path
    or a link spelt in another case, which a case-insensitive disk opens but
    which would read as no thread. The file must be written for no party
    walled from the note's, read from its real path; a folder, every file
    in it."""
    mine, bases, listed = siblings
    for base, other in bases:
        candidate = base / path
        try:
            if not candidate.exists():
                continue
            home = other.resolve()
            if home.parent != other.parent.resolve():
                continue  # the project folder is itself a link out of the zone
            real = candidate.resolve()
        except (OSError, RuntimeError):
            continue
        if other not in listed:
            listed[other] = {home / f.relative_to(other) for f in walk_files(other, nested=True)}
        if real in listed[other]:
            files = [real]
        else:
            # A folder counts when it holds files, every one of them clear.
            files = [f for f in listed[other] if real in f.parents] if real.is_dir() else []
        if files and not any(blocked(ws.context, mine, project_file_tags(ws, other, other / f.relative_to(home)))
                             for f in files):
            return True
    return False


def ticked_paths(line: str) -> List[str]:
    """The `backticked` paths on one line: not placeholders, commands, web
    addresses, globs, Office parts, scratch folders or a bare name."""
    out = []
    for m in TICK_RE.finditer(line):
        path = m.group(1).strip()
        if (path.startswith(("<", "/tmp/", "/private/", "/var/")) or "://" in path or "*" in path
                or COMMAND_RE.match(path) or OFFICE_PART_RE.match(path) or not PATHLIKE_RE.match(path)
                or "/" not in path.rstrip("/")):
            continue
        out.append(path)
    return out


# What ends a path written in prose or in a link: a space, a bracket, a quote,
# a comma, a pipe. A path inside a file name that holds one is read in pieces,
# which can only add paths to look at (#340).
_PATH_SPLIT_RE = re.compile(r"[\s`()\[\]<>\"'“”‘’,;|*{}]+")
_PATH_TAIL_RE = re.compile(r"(?::\d+)+$|#.*$")


def path_tokens(line: str) -> List[str]:
    """Every path-like token on a line, backticked or not: one with a `/` in
    it, read as it is and with any `%xx` undone, a `:12` or `#heading` taken
    off, a backslash read as a slash, a `file://` address as its path, and
    invisible marks dropped. Web addresses and other schemes are not paths."""
    out = []
    for raw in _PATH_SPLIT_RE.split(line):
        for token in {raw, unquote(raw)}:
            token = "".join(ch for ch in token if unicodedata.category(ch) != "Cf")
            if token.startswith("file://"):
                token = token[len("file://"):]
            elif "://" in token:
                continue
            token = _PATH_TAIL_RE.sub("", token.replace("\\", "/")).rstrip(".,:!?")
            if "/" in token.rstrip("/") and token not in out:
                out.append(token)
    return out


def _folded(parts) -> Tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", str(x)).casefold() for x in parts)


_LINK_SPAN_RE = re.compile(r"\]\([^)\n]*\)|\[\[[^\]\n]*\]\]|<[^>\n]*>|file://\S*")


def _marked_spans(line: str) -> List[Tuple[int, int]]:
    """Where a path on `line` is marked as one: between backticks, as a link
    target, or as a `file://` address."""
    return [m.span() for rx in (TICK_RE, _LINK_SPAN_RE) for m in rx.finditer(line)]


def _bare_path(token: str, line: str, spans: List[Tuple[int, int]]) -> bool:
    """A path-like word in prose: not marked as a path, with no file
    extension, so `work/life balance` is words and not a place."""
    if token.startswith(("~", "/")) or re.search(r"\.[A-Za-z0-9]{1,5}$", token.rstrip("/")):
        return False
    folded, text = token.casefold(), line.casefold()
    if len(text) != len(line) or folded not in text:    # folding moved the spans (ß), or read after rewriting: never bare
        return False
    return not any(folded in text[a:b] for a, b in spans)


def other_zone_paths(ws: Workspace, note: Path, bases: List[Path], lines: List[str],
                     local: int = 0) -> List[str]:
    """The paths in `lines`, backticked or not, that land in a zone other than
    the note's. Zone names are compared folded (case, Unicode form), so a
    case-insensitive disk opens `personal/` as `Personal/`. A path is first
    read from the note's own folder and project (the first `local` of `bases`):
    where it is there, it is that file, and it is across a zone only if it
    leads there by a link. Else, from any place a path may start, cleaned of
    `..` or with every link resolved, it lands in another zone or not. Zones
    never reference each other unless asked (#340). A bare word in prose, not
    marked as a path and with no extension, counts only when the path it names
    is there in the other zone ("work/life balance" is not a path)."""
    try:
        mine = next((z.resolve() for z in ws.zones if z.resolve() in note.resolve().parents), None)
        others = [_folded(z.resolve().parts) for z in ws.zones if z.resolve() != mine]
    except (OSError, RuntimeError):
        return []
    if mine is None:
        return []

    def lands(start: Path) -> bool:
        try:
            forms = [Path(os.path.normpath(str(start))), start.resolve()]
        except (OSError, RuntimeError):
            forms = [Path(os.path.normpath(str(start)))]
        return any(f[:len(z)] == z for z in others for f in (_folded(x.parts) for x in forms))

    def crosses(variants: List[str], bare: bool = False) -> bool:
        first = variants[0]
        if first.startswith(("~", "/")):
            return any(lands(Path(v).expanduser()) for v in variants)
        present = [b / v for v in variants for b in bases[:local] if (b / v).exists()]
        if bare:
            # Prose: only a path that is there, from any place one may start.
            return any(lands(b / v) for v in variants for b in bases if (b / v).exists())
        return any(lands(start) for start in (present or [b / v for v in variants for b in bases]))

    names = [z.name for z in ws.zones if z.resolve() != mine]
    out = []
    for line in lines:
        spans = _marked_spans(line)
        for path in path_tokens(line):
            if path not in out and crosses([path], _bare_path(path, line, spans)) \
                    and not any(same_path_text(path, o) for o in out):
                out.append(path)
        # A zone's name may hold a space or an apostrophe (rules.md allows both),
        # which splits a path in pieces. So the line is also searched for each
        # other zone's name followed by `/`, written as it is, with the path
        # before it and the words after it; it is a crossing unless the path
        # that starts there is in the note's own project (#340).
        plain = "".join(ch for ch in unquote(line).replace("\\", "/") if unicodedata.category(ch) != "Cf")
        plain = unicodedata.normalize("NFC", plain)
        for name in names:
            spelled = re.escape(unicodedata.normalize("NFC", name)).replace("\\ ", r"\s+").replace("'", "['’]")
            # The name followed by `/`, or a whole path part after a `/`.
            for m in re.finditer(r"(?:(?<=/)%s(?![\w])|%s/)" % (spelled, spelled), plain, re.I):
                before = re.search(r"[\w.~%/-]*$", plain[:m.start()]).group(0)
                rest = re.split(r"[`()\[\]<>\"|\n]", plain[m.end():], 1)[0]
                full = _PATH_TAIL_RE.sub("", before + name + ("/" if m.group(0).endswith("/") else "") + rest)
                full = full.rstrip(" .,:!?")
                variants = [full] + [full[:i].rstrip() for i in range(len(full) - 1, 0, -1) if full[i] == " "]
                variants = [v for v in variants if "/" in v]
                shown = full[:60]
                # Fail closed: a line that was rewritten to be read (escapes,
                # invisible marks) keeps its offsets unknown, so it is not bare.
                bare = (plain == line and not any(a <= m.start() < b for a, b in _marked_spans(line))
                        and all(_bare_path(v, line, []) for v in variants))
                if variants and not any(same_path_text(shown, o) for o in out) and crosses(variants, bare):
                    out.append(shown)
    return out


def same_path_text(a: str, b: str) -> bool:
    """One path written twice, in any case or Unicode form, one maybe with
    words of prose after it."""
    x, y = _folded([a])[0], _folded([b])[0]
    return x.startswith(y) or y.startswith(x)


def zone_crossings(ws: Workspace, note: Path, bases: List[Path], lines: List[str], spoken: str,
                   where: str, local: int = 0) -> List[Finding]:
    return [Finding(ERROR, "links", rel(ws, note),
                    "%s names `%s`, a path in another zone; zones never reference each other unless asked"
                    % (where, path), "Thread %s names a path in another zone" % spoken)
            for path in other_zone_paths(ws, note, bases, lines, local)]


def unfound_paths(ws: Workspace, project: Path, note: Path, line: str, bases: List[Path],
                  inside: List[Optional[List[str]]], shared: bool,
                  siblings: Optional[List[Optional[Siblings]]] = None) -> List[str]:
    """The `backticked` paths on one line that are not there. Placeholders,
    commands, web addresses, globs, Office parts and anything on another
    machine are not paths, and a line that says its file sits on a shared drive
    is left alone: the check does not read one. Nor is anything under
    System/generated/, which a tool writes only in some states. `inside` caches
    the project's own files, nested repositories included, listed on the first
    path not found. A path not in the project is looked for in the other
    projects of its zone, and never beyond; `siblings` caches where
    (sibling_bases), worked out on the first path not found. The Resume here block and
    the checkpoint beside it are read the same way, which is why this is one
    function and not two."""
    out = []
    for path in ticked_paths(line):
        if is_generated(ws, Path(path).expanduser() if path.startswith(("~", "/")) else ws.root / path):
            continue  # the tools' own, there or not as their state says
        if path.startswith(("~", "/")):
            found = Path(path).expanduser().exists()
        else:
            found = any((b / path).exists() for b in bases)
            if not found:
                # Relative to a folder the line names elsewhere: any file in
                # the project whose path ends the same way, code checked out
                # inside it too, since this only asks whether the file exists.
                if inside[0] is None:
                    inside[0] = ["/" + f.relative_to(project).as_posix() for f in walk_files(project, nested=True)]
                tail = "/" + path.strip("./").rstrip("/")
                found = any(f.endswith(tail) or (path.endswith("/") and tail + "/" in f) for f in inside[0])
            if not found:
                siblings = siblings if siblings is not None else [None]
                if siblings[0] is None:
                    siblings[0] = sibling_bases(ws, project, note)
                found = sibling_found(ws, siblings[0], path)
        if not found and (shared or SHARE_RE.search(line)):
            continue  # on a shared drive, which the check does not read
        if not found:
            out.append(path)
    return out


def resume_findings(ws: Workspace, project: Path, note: Path, block: List[str], spoken: str,
                    files: List[Optional[PathIndex]], shared: bool) -> List[Finding]:
    """Findings for one Resume here block: still the template's, a link that
    leads nowhere, a file path that is not there."""
    out = []
    unfilled = [m.group(1) for m in (RESUME_PROMPT_RE.match(line) for line in block) if m]
    if unfilled or any(RESUME_DATE_PROMPT in line for line in block):
        out.append(Finding(WARNING, "resume", rel(ws, note),
                           "Resume here is still the template's (%s not filled in); say \"wrap %s\" to fill it"
                           % (", ".join(unfilled).lower() or "its date", spoken.rsplit(", ", 1)[-1]),
                           "Thread %s has no real resume point yet" % spoken))
    bases = path_bases(ws, project, note)
    out += zone_crossings(ws, note, bases, block, spoken, "Resume here", local_base_count(project, note))
    inside: List[Optional[List[str]]] = [None]  # the project's files, listed on the first path not found
    siblings: List[Optional[Siblings]] = [None]  # the zone's other projects, likewise
    for line in block:
        for m in WIKILINK_RE.finditer(re.sub(r"`[^`]*`", "", line)):
            target = m.group(1).split("|")[0].split("#")[0].strip().rstrip("\\")
            if not target or target.startswith("<") or "://" in target:
                continue
            if files[0] is None:
                files[0] = PathIndex(ws, walk_files(ws.root))
            if not resolve(ws, note, target, files[0]):
                out.append(Finding(WARNING, "resume", rel(ws, note),
                                   "Resume here links [[%s]], which leads nowhere" % target,
                                   "Thread %s points at a note that is not there" % spoken))
        for path in unfound_paths(ws, project, note, line, bases, inside, shared, siblings):
            out.append(Finding(WARNING, "resume", rel(ws, note),
                               "Resume here names `%s`, which is not there" % path,
                               "Thread %s names a file that is not there" % spoken))
    return out


# ---------------------------------------------------------------------------
# The checkpoint beside a resume point
# ---------------------------------------------------------------------------

# `### Checkpoint` under Resume here: what a session recorded as the work
# happened and has not wrapped yet. The check reads the block and never
# changes it. A hand edit is the user's, and the next wrap folds the block in
# and removes it; everything here is a warning, because unconfirmed work in
# the note is better than unconfirmed work nowhere.
CHECKPOINT_HEAD_RE = re.compile(r"(?mi)^###[ \t]+Checkpoint[ \t]*$")
RESUME_HEAD_RE = re.compile(r"(?mi)^###[ \t]+Resume here[ \t]*$")
STATE_OF_PLAY_RE = re.compile(r"(?mi)^##[ \t]+State of play[ \t]*$")
SECTION_RE = re.compile(r"(?m)^##[ \t]+")
# A path into the Meetings wiki, written as a path: `Wikis/Meetings/...` or
# `Meetings/...`. A bare [[link]] that answers to a page there is resolved.
MEETINGS_IN_PATH_RE = re.compile(r"(?i)(?:\bWikis[\\/])?\bMeetings[\\/]")
# A Decided line as the tool writes it: the words quoted, then who said them
# and when. Either half missing and the decision has no source.
DECIDED_RE = re.compile(r'^"(?P<said>[^"]*)"(?P<by>.*)$')
# Where a date sits on the lines that may carry one: last on a To file line,
# first on a Deadline one. Neither reads a comma, so "by hand, no date given"
# is not a date claimed badly.
CHECKPOINT_DATES = {"action": re.compile(r",[ \t]+by[ \t]+([^,]+)$"),
                    "deadline": re.compile(r"^([^,]*),")}


def _now() -> datetime.datetime:
    """Now, with this machine's offset: the one clock the check reads, for how
    long a checkpoint has gone unconfirmed."""
    return datetime.datetime.now().astimezone()


def checkpoint_age(at: str) -> Optional[int]:
    """How many days ago a checkpoint was written, or None where its stamp
    cannot be read."""
    try:
        when = datetime.datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return None
    now = _now()
    if when.tzinfo is None:
        now = now.replace(tzinfo=None)
    return (now - when).days


def checkpoint_findings(ws: Workspace, project: Path, note: Path, text: str, spoken: str, status: str,
                        files: List[Optional[PathIndex]], shared: bool) -> List[Finding]:
    """Findings for the checkpoint beside a resume point: where the block sits,
    whether it can be read at all, whether the resume point moved out from
    under it, whether its items still name what they say, and how long it has
    gone unconfirmed. A parked thread keeps its checkpoint silently; a finished
    one is holding work that is on no list."""
    out: List[Finding] = []
    heads = [m.start() for m in CHECKPOINT_HEAD_RE.finditer(text)]
    block = read_checkpoint(text)
    if not heads and block is None:
        return out
    name = spoken.rsplit(", ", 1)[-1]
    said_at = said_time(block["at"]) if block and block.get("at") else "an unreadable time"

    def warn(message: str, said: str) -> None:
        out.append(Finding(WARNING, "resume", rel(ws, note), message, said))

    if len(heads) > 1 or (block is not None and block["extra"]):
        warn("it has more than one `%s` block, and one thread has one unwrapped checkpoint; keep the newer "
             "and delete the rest, or say \"wrap %s\" to fold them in" % (CHECKPOINT_HEADING, name),
             "Thread %s has more than one checkpoint" % spoken)
    resume = RESUME_HEAD_RE.search(text)
    if heads and resume is not None and min(heads) < resume.start():
        warn("its `%s` block sits above Resume here; State of play opens with the confirmed resume point, "
             "and the checkpoint goes under it" % CHECKPOINT_HEADING,
             "Thread %s has its checkpoint above its resume point" % spoken)
    play = STATE_OF_PLAY_RE.search(text)
    if heads and play is not None:
        after = SECTION_RE.search(text, play.end())
        stop = after.start() if after else len(text)
        if any(not play.end() <= h < stop for h in heads):
            warn("its `%s` block sits outside `## State of play`, where nothing that reads the resume point "
                 "will find it" % CHECKPOINT_HEADING,
                 "Thread %s has its checkpoint outside State of play" % spoken)
    if block is None:
        return out

    # Meeting material is reported whether the block can be read or not: a
    # checkpoint carries none, and an invalid block is still in the note.
    for line in block["content"]:
        hit = "a path into the Meetings wiki" if MEETINGS_IN_PATH_RE.search(line) else None
        if hit is None:
            for m in WIKILINK_RE.finditer(re.sub(r"`[^`]*`", "", line)):
                target = m.group(1).split("|")[0].split("#")[0].strip().rstrip("\\")
                if not target or target.startswith("<") or "://" in target:
                    continue
                if files[0] is None:
                    files[0] = PathIndex(ws, walk_files(ws.root))
                wiki = ws.root / "Wikis" / "Meetings"
                if any(wiki == f or wiki in f.parents for f in resolve(ws, note, target, files[0])):
                    hit = "[[%s]]" % target
                    break
        if hit is not None:
            warn("its checkpoint names %s; a checkpoint carries no meeting material, and a decision that "
                 "rests on a meeting waits for the wrap, where the wall check runs" % hit,
                 "Thread %s has a checkpoint naming meeting material" % spoken)
    # Like meeting material, whether the block can be read or not (#340).
    out += zone_crossings(ws, note, path_bases(ws, project, note), block["content"], spoken, "its checkpoint",
                          local_base_count(project, note))
    if not block["valid"]:
        warn("the checkpoint %s; read it, do not resume from it, and say \"wrap %s\" to settle it"
             % (block["why"], name), "Thread %s has a checkpoint that cannot be read" % spoken)
        return out

    if block["base"] != resume_hash(text):
        warn("the checkpoint from %s was written against an older resume point, so a wrap or a hand edit has "
             "left it behind; read it, do not resume from it, and wrap %s to settle it" % (said_at, name),
             "Thread %s has a checkpoint older than its resume point" % spoken)
    bases = path_bases(ws, project, note)
    inside: List[Optional[List[str]]] = [None]
    siblings: List[Optional[Siblings]] = [None]
    for item in block["items"]:
        if item["kind"] == "made":
            for path in unfound_paths(ws, project, note, item["text"], bases, inside, shared, siblings):
                warn("its checkpoint records making `%s`, which is not there; the item stands as a note that "
                     "the file has gone, and the wrap asks about it" % path,
                     "Thread %s has a checkpoint naming a file that is not there" % spoken)
        if item["kind"] == "decided":
            m = DECIDED_RE.match(item["text"])
            missing = "no words quoted" if m is None else ("nobody named" if not m.group("by").strip() else "")
            if missing:
                warn("its checkpoint's Decided item `%s` has %s, and a decision is recorded in the words it "
                     "was made in, with who made it" % (item["id"], missing),
                     "Thread %s has a checkpoint decision with no source" % spoken)
        pattern = CHECKPOINT_DATES.get(item["kind"])
        found = pattern.search(item["text"]) if pattern else None
        given = found.group(1).strip() if found else ""
        if given and given != "no date given" and not ISO_DATE_RE.match(given):
            warn("its checkpoint's %s item gives `%s` as a date, and a date in a checkpoint is an ISO date "
                 "somebody gave; with none it says \"no date given\""
                 % (CHECKPOINT_LABELS[item["kind"]], given[:40]),
                 "Thread %s has a checkpoint date that is not a date" % spoken)
    days = checkpoint_age(block["at"])
    if days is not None and days > CHECKPOINT_DAYS:
        warn("its checkpoint from %s has gone %d days unconfirmed; wrap %s to settle it, or drop it: until it "
             "is wrapped its To file actions are on no list" % (said_at, days, name),
             "Thread %s has a checkpoint more than a week old" % spoken)
    if status == "done":
        warn("it is finished and still holds the checkpoint from %s, so whatever that block has not filed is "
             "on no list; read it and file what is left" % said_at,
             "Thread %s is finished with an unwrapped checkpoint" % spoken)
    return out


def stale_resume(ws: Workspace, project: Path, notes: List[Path]) -> Optional[Finding]:
    """A resume point left behind: files added to the project more than
    STALE_DAYS days after the newest `updated` of its hub and the notes
    holding its resume points. Only files git saw added count, with renames
    followed, since a rename or a sweep of small fixes is not work."""
    dates = []
    for n in notes:
        value = parse_frontmatter(n).get("updated")
        if isinstance(value, str) and ISO_DATE_RE.match(value.strip()):
            try:
                dates.append(datetime.date.fromisoformat(value.strip()))
            except ValueError:
                pass
    if not dates or _repo_top(ws, project) is None:
        return None
    resume = max(dates)
    log = _git(["log", "--diff-filter=A", "-M", "--name-only", "--format=%ad", "--date=short",
                "--since", resume.isoformat(), "--", "."], project) or ""
    newest = day = None
    for line in log.splitlines():
        if re.match(r"^\d{4}-\d{2}-\d{2}$", line):
            day = datetime.date.fromisoformat(line)
        elif line and day and not NOT_WORK_RE.search(line):
            newest = max(newest or day, day)
    if newest and (newest - resume).days > STALE_DAYS:
        return Finding(WARNING, "resume", rel(ws, project / (project.name + ".md")),
                       "files were added on %s, but the resume point was last updated on %s; wrap the thread "
                       "so it says where things stand" % (newest.isoformat(), resume.isoformat()),
                       "The resume point of %s may be out of date" % project.name)
    return None


def check_resume(ws: Workspace) -> List[Finding]:
    """A resume point is the signpost a cold resume follows first. Every link
    and file path in a live thread's Resume here block must still lead
    somewhere: a deliverable renamed or moved shows here the day it happens,
    not when someone opens the thread months later. Placeholders, commands,
    web addresses and anything on another machine are not paths. A hub that
    keeps the resume point of a project that is one thread is read the same
    way, and a resume point that work has left behind is reported.

    The checkpoint beside the block is read too, on every thread and not only
    a live one: a finished thread still holding one has unfiled work nobody
    can see (checkpoint_findings)."""
    out = []
    files: List[Optional[PathIndex]] = [None]  # every file in the workspace, indexed on the first link
    for project, pfm in ws.projects:
        hub = project / (project.name + ".md")
        if not hub.is_file():
            continue
        shared = bool(str(pfm.get("share") or "").strip())
        state = str(pfm.get("status") or "").strip().lower()
        live = live_status(pfm)
        holding = [hub]
        hub_text = read_text(hub) or ""
        block = resume_block(hub_text)
        if live and block:
            out += resume_findings(ws, project, hub, block, project.name, files, shared)
        out += checkpoint_findings(ws, project, hub, hub_text, project.name, state, files, shared)
        for thread in visible_dirs(project / "Threads"):
            note = thread / (thread.name + ".md")
            text = read_text(note) if note.is_file() else None
            if not text:
                continue
            spoken = "%s, %s" % (project.name, thread.name)
            own = str(parse_frontmatter(note).get("status") or "").strip().lower()
            # A parked project holds every thread in it parked, whatever its
            # own note says, and a finished one holds them finished.
            out += checkpoint_findings(ws, project, note, text, spoken, own if live else state, files, shared)
            block = resume_block(text)
            if block:
                holding.append(note)
            if not live or own in ("done", "parked"):
                continue  # finished, or set aside: nobody resumes it until it is woken
            out += resume_findings(ws, project, note, block, spoken, files, shared)
        if live:
            stale = stale_resume(ws, project, holding)
            if stale:
                out.append(stale)
    return out


# What sits in a Deliverables/ folder without being a deliverable: build
# intermediates, a readme or ledger about the folder, scripts, hidden and
# lock files. They keep the names they have.
NOT_DELIVERABLE_RE = re.compile(r"^(?:build|render.*|specs|archive|published\.md|readme\.md)$|^[.~]|\.(?:py|sh)$", re.I)
BUILD_CONTAINER_RE = re.compile(r"^(?:render.*|build.*\.(?:py|sh)|deploy\.sh)$", re.I)


def deliverable_folders(project: Path) -> List[Path]:
    """A project's Deliverables/ and each thread's own, as a thread-first
    project keeps them, and the archive/ in each: a deliverable keeps its
    date when it is archived."""
    out = [project / "Deliverables"]
    out += [t / "Deliverables" for t in visible_dirs(project / "Threads")]
    out += [f / a for f in list(out) if f.is_dir() for a in os.listdir(f) if a.lower() == "archive"]
    return [f for f in out if f.is_dir()]


def undated(folder: Path, depth: int = 0) -> List[Path]:
    """Entries of a Deliverables/ folder that should carry their date and do
    not. A folder of build output is an intermediate by what it holds; an
    undated folder holding dated entries groups deliverables, and its entries
    are read instead; any other folder is a deliverable in itself."""
    out = []
    for path in sorted(folder.iterdir()):
        if NOT_DELIVERABLE_RE.search(path.name):
            continue
        m = DELIVERABLE_RE.match(path.name)
        if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
            continue
        if path.is_dir():
            inside = [p.name for p in path.iterdir()]
            if any(BUILD_CONTAINER_RE.match(x) for x in inside):
                continue
            if depth == 0 and any(DELIVERABLE_RE.match(x) for x in inside):
                out += undated(path, 1)
                continue
        out.append(path)
    return out


def check_deliverables(ws: Workspace) -> List[Finding]:
    out = []
    for project, _ in ws.projects:
        for folder in deliverable_folders(project):
            for path in undated(folder):
                out.append(Finding(WARNING, "deliverables", rel(ws, path),
                                   "name does not start with its creation date, `YYMMDD - <name>`",
                                   "A deliverable in %s lacks its date" % project.name))
        # What left the workspace: a row drift.py cannot read is a file nobody watches.
        # A history row (`withdrawn`, `replaced` or `sent` before its date) reads, and is not watched on purpose.
        found = [f / "published.md" for f in [project / "Deliverables"] + [t / "Deliverables" for t in visible_dirs(project / "Threads")]
                 if (f / "published.md").is_file()]
        if found:
            from drift import ledger_rows
        for ledger in found:
            for line in ledger_rows(ledger)[1]:
                out.append(Finding(WARNING, "deliverables", rel(ws, ledger),
                                   "a row does not read as `| YYYY-MM-DD | `file` | `destination` | recipients | "
                                   "share or here |`, so its file is not watched for drift: %s" % line[:80],
                                   "A row of what %s published does not read" % project.name))
    return out


# ---------------------------------------------------------------------------
# Anonymous projects
# ---------------------------------------------------------------------------

OFFICE_SUFFIXES = {".docx", ".xlsx", ".pptx"}


def office_text(path: Path) -> str:
    """The XML text inside an Office file, which is a zip of XML parts; an
    unreadable one gives nothing."""
    import zipfile
    try:
        with zipfile.ZipFile(str(path)) as z:
            return "\n".join(z.read(n).decode("utf-8", errors="replace") for n in z.namelist()
                             if n.endswith(".xml") and not n.startswith("docProps/")  # who saved it, not what it says
                             and z.getinfo(n).file_size <= MAX_SCAN_BYTES)
    except Exception:     # a damaged file: zlib, EOF and zip errors alike
        return ""


def check_anonymous(ws: Workspace) -> List[Finding]:
    """A project marked `anonymous` in its hub makes things that name nobody,
    such as templates built from real cases: nothing in its deliverables names
    another party of its zone, or one of their people, aliases or domains.
    `anonymous` may also list further names to keep out. What it received, in
    Sources/, may name anyone. Party tags are not looked for, since a tag can
    be an everyday word."""
    out = []
    for project, fm in ws.projects:
        value = fm.get("anonymous")
        extra = [str(v) for v in value] if isinstance(value, list) else []
        if not (value is True or extra or str(value).strip().lower() == "true"):
            continue
        own = {strip_tag(t) for t in as_list(fm.get("party"))}
        zone = project.parent.name
        others = {t for t, e in ws.context["parties"].items()
                  if t not in own and e.get("zone", "").strip() in ("", zone)}
        forms = []
        for tag, found in name_forms(ws, others).items():
            name = " ".join(words(ws.context["parties"][tag].get("party") or ""))
            forms += [f for f in found if f[1] != " ".join(words(tag)) or f[1] == name]
        forms += [(False, " ".join(words(n))) for n in extra if words(n)]
        if not forms:
            continue
        for folder in deliverable_folders(project):
            for path in walk_files(folder):
                if path.name.startswith((".", "~")):
                    continue
                suffix = path.suffix.lower()
                text = path.stem
                if suffix in TEXT_SUFFIXES:
                    text += "\n" + (read_text(path) or "")
                elif suffix in OFFICE_SUFFIXES:
                    text += "\n" + re.sub(r"<[^>]+>", " ", office_text(path))
                if names_hit(text, forms):
                    out.append(Finding(WARNING, "anonymous", rel(ws, path),
                                       "names another party of its zone, one of their people, or a name the hub keeps out; "
                                       "%s is anonymous, so what it makes names nobody" % project.name,
                                       "A deliverable of %s names someone" % project.name))
    return out


# ---------------------------------------------------------------------------
# To-do lists
# ---------------------------------------------------------------------------

TODO_LABEL_RE = re.compile(r"^- \[ \] \[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]:")
# Obsidian Tasks reads its fields from the end of a line only: a date with
# any text after it stays part of the description, unread.
TASKS_FIELD_RE = re.compile(r"(?:\s*(?:[🔺⏫🔼🔽⏬]\uFE0F?|(?:📅|📆|🗓|⏳|⌛|🛫|➕|✅|❌)\uFE0F? *\d{4}-\d{2}-\d{2}|#(?!\d+(?![\w/-]))[^\s#]+))$")
TASKS_DATE_RE = re.compile(r"(?:📅|📆|🗓|⏳|⌛|🛫|➕)\uFE0F? *\d{4}-\d{2}-\d{2}")
# Every task line of a list, ticked or not, and the `<angle bracket>` placeholder
# that marks the example line a new zone's Todo.md opens with to show the shape.
# The example is a task like any other, so it goes when a real action arrives.
TODO_TASK_RE = re.compile(r"^- \[[ xX]\] ")
TODO_EXAMPLE_RE = re.compile(r"<[^<>\n]+>")
INBOX_GROWTH = 20  # open actions added to a list's Inbox in a week, past which triage is not keeping up
TODO_LONG = 200  # characters of a line as Obsidian shows it, past which it is a log entry rather than an action
# A Tasks field wherever it stands on a line, a source the sweep folded onto
# it, and a link as Obsidian shows it: its alias, or its target.
TODO_FIELD_ANY_RE = re.compile(r"\s*(?:[🔺⏫🔼🔽⏬]\uFE0F?|(?:📅|📆|🗓|⏳|⌛|🛫|➕|✅|❌)\uFE0F? *\d{4}-\d{2}-\d{2})")
TODO_WIKILINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]")
TODO_MDLINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def tasks_description(line: str) -> str:
    """A task line without the fields and tags at its end."""
    d = line.rstrip()
    m = TASKS_FIELD_RE.search(d)
    while m:
        d = d[:m.start()].rstrip()
        m = TASKS_FIELD_RE.search(d)
    return d


def inbox_count(text: str) -> int:
    n, sec = 0, None
    for line in text.splitlines():
        if line.startswith("## "):
            sec = line[3:].strip().lower()
        elif sec == "inbox" and line.startswith("- [ ] "):
            n += 1
    return n


def todo_action(line: str) -> str:
    """A task line as the action it names: no box, no dates or priority
    wherever they stand, no tags at its end, no source the sweep folded onto
    it, spaces collapsed and case folded. A line ticked as it was written
    gives what it gave while it was open."""
    text = TODO_FIELD_ANY_RE.sub("", line.rstrip()[6:])
    text = TODO_ALSO_RE.sub("", tasks_description(text))
    return " ".join(text.split()).casefold()


def todo_shown(line: str) -> str:
    """A task line as Obsidian shows it: no box, no fields or tags at its end,
    no folded sources, each link as its text."""
    text = TODO_ALSO_RE.sub("", tasks_description(line)[6:])
    text = TODO_MDLINK_RE.sub(r"\1", TODO_WIKILINK_RE.sub(r"\1", text))
    return " ".join(text.split())


def todo_opened(zone: Path) -> Optional[set]:
    """Every action the zone's history holds as an open line of its Todo.md,
    as `todo_action` gives it, read in one git process for the whole history:
    every line a commit added, and nothing else. None when there is no history
    of the list to read: no repository, no commit, or a list never committed."""
    data = _git_bytes(["-c", "log.showRoot=true", "log", "-p", "-U0", "--no-color", "--no-ext-diff", "--no-renames",
                       "--format=", "--", "Todo.md"], zone)
    if not data:
        return None
    return {todo_action(l[1:]) for l in data.decode("utf-8", "replace").splitlines() if l.startswith("+- [ ] ")}


def system_threads(ws: Workspace) -> set:
    """The hub and thread note names, lower-cased, of every project kept in
    System/. Such a project has no Todo.md of its own: its actions live in a
    zone's, opening with its thread's link."""
    out = set()
    for project, _ in ws.projects:
        if in_system(ws, project):
            out.add(project.name.lower())
            out.update(t.name.lower() for t in visible_dirs(project / "Threads") if (t / (t.name + ".md")).is_file())
    return out


def check_todo(ws: Workspace) -> List[Finding]:
    """Each zone's Todo.md: an open action that opens with a thread's link
    leads to a live note, in the zone or a project in System/; its dates come
    last, where Obsidian Tasks reads them; the example action a new list is
    started with is gone once a real one has arrived; the Inbox does not grow
    by more than INBOX_GROWTH in a week. In a zone the check settings name
    under `todo-labels`, every open action opens with its thread's link.
    The list holds actions, not records: a ticked line was once open in the
    zone's history, and no line runs past TODO_LONG characters."""
    out = []
    strict = set(setting_zones(ws, "todo-labels"))
    system = system_threads(ws)
    for zone in ws.zones:
        todo = zone / "Todo.md"
        text = read_text(todo) if todo.is_file() else None
        if text is None:
            continue
        r = rel(ws, todo)
        open_lines = [l for l in text.splitlines() if l.startswith("- [ ] ")]
        stems = {p.stem.lower() for p, _ in zone_notes(ws, zone)} | system
        broken, unlabelled = set(), 0
        for line in open_lines:
            m = TODO_LABEL_RE.match(line)
            if not m:
                unlabelled += 1
            elif m.group(1).strip().startswith("<"):
                continue  # the template's example line, still to be replaced
            elif m.group(1).strip().rsplit("/", 1)[-1].lower() not in stems:
                broken.add(m.group(1).strip())
        if broken:
            out.append(Finding(WARNING, "todo", r,
                               "open actions name %s, which lead to no live note; the thread was renamed or archived"
                               % ", ".join("[[%s]]" % b for b in sorted(broken)),
                               "Open actions in %s name a thread that is not there" % zone.name))
        if zone in strict and unlabelled:
            out.append(Finding(WARNING, "todo", r,
                               ("1 open action does not open with its thread's link, `[[Thread]]: `" if unlabelled == 1 else
                                "%d open actions do not open with their thread's link, `[[Thread]]: `" % unlabelled),
                               "Open actions in %s do not name their thread" % zone.name))
        tasks = [l for l in text.splitlines() if TODO_TASK_RE.match(l)]
        examples = [l for l in tasks if TODO_EXAMPLE_RE.search(l)]
        real = len(tasks) - len(examples)
        if examples and real:
            out.append(Finding(WARNING, "todo", r,
                               "the example action the list was started with is still here, under %d real one%s; "
                               "it is a task like any other, so anything that counts open actions counts it and "
                               "anything that reads the nearest deadline trips over its `<YYYY-MM-DD>`: take it out"
                               % (real, "" if real == 1 else "s"),
                               "The %s list still holds the example action it was started with" % zone.name))
        unread = sum(1 for l in open_lines if TASKS_DATE_RE.search(tasks_description(l)))
        if unread:
            out.append(Finding(WARNING, "todo", r,
                               "%d open action%s a date with text after it, which Obsidian Tasks does not read; "
                               "put the dates last" % (unread, " has" if unread == 1 else "s have"),
                               "Some actions in %s have a date that is not read" % zone.name))
        long = sum(1 for l in tasks if not TODO_EXAMPLE_RE.search(l) and len(todo_shown(l)) > TODO_LONG)
        if long:
            out.append(Finding(WARNING, "todo", r,
                               "%d line%s longer than %d characters; a line names one action, and what came of "
                               "it goes in the thread note's dated entry" % (long, " is" if long == 1 else "s are", TODO_LONG),
                               "Some lines in the %s list read as log entries" % zone.name))
        ticked = [l for l in tasks if l[3] in "xX" and not TODO_EXAMPLE_RE.search(l)]
        opened = todo_opened(zone) if ticked and (zone / ".git").exists() else None
        if opened is not None:
            records = [l for l in ticked if todo_action(l) not in opened]
            if records:
                threads = sorted({m.group(1).strip() for m in (re.match(r"^- \[[xX]\] \[\[([^\]|#]+)", l)
                                                                  for l in records) if m})
                out.append(Finding(WARNING, "todo", r,
                                   "%d ticked line%s never open in the zone's history%s: a record of work already "
                                   "done, or an outcome written onto the tick. Both belong in the thread note's dated "
                                   "entry; take the line out, or put it back as it was written with only its tick and "
                                   "its ✅ date" % (len(records), " was" if len(records) == 1 else "s were",
                                                    " (%s)" % ", ".join("[[%s]]" % t for t in threads) if threads else ""),
                                   "The %s list holds records of work done, not actions" % zone.name))
        if (zone / ".git").exists():
            then = _git(["log", "-1", "--before=7.days", "--format=%H", "--", "Todo.md"], zone)
            old = _git(["show", "%s:Todo.md" % then.strip()], zone) if then and then.strip() else None
            if old is not None:
                grew = inbox_count(text) - inbox_count(old)
                if grew > INBOX_GROWTH:
                    out.append(Finding(WARNING, "todo", r,
                                       "the Inbox grew by %d open actions in a week; triage is not keeping up" % grew,
                                       "The %s to-do Inbox is growing faster than it is sorted" % zone.name))
    return out


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

CLOUD_PATH_RE = re.compile(r"Library/CloudStorage/")
TICKED_NOTE_RE = re.compile(r"(?<!`)`([^`\n*~/][^`\n*]*?\.md)`(?!`)")


# live_files(), the walk that says which files of a zone are notes, comes from
# garrick_lib: the status page's Todo card reads a zone through it too.


def zone_notes(ws: Workspace, zone: Optional[Path] = None) -> List[Tuple[Path, str]]:
    """(note, text) for every live Markdown note in the zones, read once, or
    in one zone. What waits in a zone's Inbox/ is not a note yet."""
    if ws.zone_notes is None:
        ws.zone_notes = []
        for z in ws.zones:
            for path in live_files(z):
                if path.suffix.lower() == ".md" and path.relative_to(z).parts[0] != INBOX:
                    ws.zone_notes.append((path, read_text(path) or ""))
    if zone is None:
        return ws.zone_notes
    return [(p, t) for p, t in ws.zone_notes if zone in p.parents]


QUESTION_STATUSES = ("open", "answered", "later")
# A wiki question (#224) can also be closed, with nothing to work in, or done,
# once the pages its answer changes are worked in. The home reads neither.
WIKI_QUESTION_STATUSES = QUESTION_STATUSES + ("closed", "done")
QUESTION_OPTION = re.compile(r"^\s*-\s+\[(?![ xX]\])([^\]]+)\]\s+\S")


def question_findings(ws: Workspace, f: Path, reader: str, say: str,
                      statuses: Tuple[str, ...] = QUESTION_STATUSES, wiki: Optional[Path] = None) -> List[Finding]:
    """What a question file needs before `reader` can ask it: `type:
    question`, a status it reads (open, answered or later; in a wiki also
    closed or done), a `later:` date
    when it is put off, an `answer:` once answered, and a bold line that is the
    question. A file without them is left out, so the question is never seen."""
    out = []
    r = rel(ws, f)
    fm = parse_frontmatter(f)
    if fm.get("type") != "question":
        out.append(Finding(WARNING, "questions", r, "frontmatter `type` is %r, should be question" % fm.get("type"), say))
    status = str(fm.get("status") or "").strip().lower()
    if status not in statuses:
        out.append(Finding(WARNING, "questions", r, "`status` is %r; %s reads %s" % (
            fm.get("status"), reader, ", ".join(statuses)), say))
    if status == "later" and not re.match(r"^\d{4}-\d\d-\d\d$", str(fm.get("later") or "")):
        out.append(Finding(WARNING, "questions", r, "put off with no `later:` date, so it never comes back", say))
    if status == "answered" and not str(fm.get("answer") or "").strip():
        out.append(Finding(WARNING, "questions", r, "answered, with no `answer:`", say))
    if wiki is not None and status in ("answered", "done") and str(fm.get("answer") or "").strip():
        record = raw_answer_there(wiki, fm.get("answer"))
        if record is None:
            out.append(Finding(WARNING, "questions", r, "%s, but its `answer:` points at no raw answer in raw/answers/, "
                               "so the page it changes has nothing to cite" % status, say))
        elif not own_answer(record, f, fm):
            out.append(Finding(WARNING, "questions", r, "%s, but its `answer:` is not a record of this question, "
                               "with its zone and parties, so the page it changes may not cite it" % status, say))
    try:
        body = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    if not re.search(r"(?m)^\s*\*\*.+\*\*\s*$", body):
        out.append(Finding(WARNING, "questions", r, "no bold line to ask, so %s leaves it out" % reader, say))
    return out


def raw_answer_there(wiki: Path, value) -> Optional[Path]:
    """The file a wiki question's `answer:` links in the wiki's raw/answers/
    (#224), written with or without its extension; None when there is none."""
    m = re.fullmatch(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]", str(value).strip())
    if not m:
        return None
    target = m.group(1).strip()
    folder = wiki.joinpath(*WIKI_ANSWERS).resolve()
    for name in (target, target + ".md"):
        p = (wiki / name).resolve()
        if p.is_file() and folder in p.parents:
            return p
    return None


def own_answer(record: Path, question: Path, qfm: dict) -> bool:
    """Whether a raw answer is this question's own: it carries the question's
    zone and parties, and its `question:` link lands on the question's file."""
    rfm = parse_frontmatter(record)
    if frontmatter_form_problem(read_text(record) or "") or rfm.get("type") != "answer":
        return False
    if str(rfm.get("zone") or "").strip() != str(qfm.get("zone") or "").strip():
        return False
    if sorted(strip_tag(t) for t in as_list(rfm.get("parties"))) != sorted(strip_tag(t) for t in as_list(qfm.get("parties"))):
        return False
    wiki = question.parent
    while wiki.name != WIKI_QUESTIONS and wiki != wiki.parent:
        wiki = wiki.parent
    wiki = wiki.parent
    m = re.fullmatch(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]", str(rfm.get("question") or "").strip())
    if not m:
        return False
    return any((wiki / n).resolve() == question.resolve() for n in (m.group(1).strip(), m.group(1).strip() + ".md"))


def check_questions(ws: Workspace) -> List[Finding]:
    """A Needs you question (#175) is a file in the folder of the work it
    blocks, `Needs you/<YYMMDD> - <slug>.md`, which the status page's simple
    home reads and answers. A wiki question (#224) is the same file in the
    wiki's own `questions/`, for what an ingest or a lint found that only the
    user can settle, and belongs to no thread. Both are held to what
    question_findings() asks. A Meetings question also carries the `zone`
    and `parties` the walls read, as a meeting page does: without both it is
    unfinished, and nothing in it may be used. A Knowledge question carries
    neither, which check_knowledge() holds it to with every Knowledge file."""
    out = []
    for project, _ in ws.projects:
        for box in [project / "Needs you"] + [t / "Needs you" for t in visible_dirs(project / "Threads")]:
            if not box.is_dir():
                continue
            for f in sorted(box.glob("*.md")):
                if f.name.startswith((".", "_")):
                    continue
                out += question_findings(ws, f, "the home", "A Needs you question the home cannot read")
    for wiki in visible_dirs(ws.root / "Wikis"):
        for f in wiki_questions(wiki):
            out += question_findings(ws, f, "Garrick", "A %s question Garrick cannot read" % wiki.name,
                                     WIKI_QUESTION_STATUSES, wiki)
            if f in ws.meeting_questions:
                out += party_findings(ws, "questions", rel(ws, f), ws.meeting_raw.get(f, ws.meetings[f]), "Meetings question",
                                      "ask it once for each side")
                if party_keys_problem(read_text(f) or ""):
                    out.append(Finding(WARNING, "questions", rel(ws, f), "carries both `party` and `parties`, or spells one in "
                                       "capitals, which a reader could take two ways; the walls read `parties:` alone, so it "
                                       "is placed nowhere", "A Meetings question names its parties two ways"))
        for f in wiki_answers(wiki):
            if f in ws.meeting_answers:
                out += party_findings(ws, "questions", rel(ws, f), ws.meeting_raw.get(f, ws.meetings[f]), "Meetings answer",
                                      "file it once for each side")
    return out


# A decision's status moves only on the user's say-so (#224, point 5). The user's
# own save through the panel files their words as a raw answer the same day; a
# hand edit of `status:` with no such record that day is the assistant's guess,
# or a slip, and is warned about. A change older than this is no longer asked about.
DECISION_STATUS_DAYS = 30


def decision_sections(text: str) -> set:
    """The `## ` headings of a decision page, outside fences."""
    names, fence = set(), None
    for line in body_of(text).splitlines():
        m = re.match(r"^\s*(`{3,}|~{3,})", line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            continue
        if fence is None:
            h = re.match(r"^##\s+(.+?)\s*#*\s*$", line)
            if h:
                names.add(h.group(1).strip())
    return names


def link_target(value) -> str:
    """The target of a `[[link]]` or a bare path, without brackets or `.md`, for comparing."""
    v = str(value or "").strip()
    m = re.fullmatch(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]", v)
    v = (m.group(1) if m else v).strip()
    return v[:-3] if v.endswith(".md") else v


def day_record(wiki: Path, day: str, fm: dict) -> bool:
    """Whether the wiki holds a raw answer dated `day` (YYYY-MM-DD) that is the
    one for this decision's own question: it names the same question as the
    decision's `question:`, and carries the decision's zone and parties. Any
    other record that day does not count."""
    want = link_target(fm.get("question"))
    if not want:
        return False
    parties = sorted(strip_tag(t) for t in as_list(fm.get("parties")))
    short = day[2:4] + day[5:7] + day[8:10]
    for f in wiki_answers(wiki):
        rfm = parse_frontmatter(f)
        if rfm.get("type") != "answer" or frontmatter_form_problem(read_text(f) or ""):
            continue
        if str(rfm.get("answered") or "").strip() != day and not f.name.startswith(short + " - "):
            continue
        # only the raw record `question-decide` files carries the marker: an answer filed by `question-answer`
        # is not the act that settles a decision
        if str(rfm.get("outcome") or "").strip() != "decision":
            continue
        if link_target(rfm.get("question")) == want and str(rfm.get("zone") or "").strip() == str(fm.get("zone") or "").strip() \
                and sorted(strip_tag(t) for t in as_list(rfm.get("parties"))) == parties:
            return True
    return False


def decision_events(ws: Workspace, wiki: Path) -> List[dict]:
    """What git, and the disk against git's last commit, show of the decision
    pages of one wiki (renames followed): {"path", "day", "kind": "new" |
    "status", "what", "fm"}. A page new to the history, or moved into the
    folder, is "new" (its day is its own `decided:`); a page whose `status:`
    changed, in place or with a rename in the same commit, is "status"
    (its day is the commit's, or today's for an uncommitted change). Changes
    older than DECISION_STATUS_DAYS are no longer asked about."""
    top = _git(["rev-parse", "--show-toplevel"], wiki)
    if not top:
        return []
    top_path = Path(top.strip()).resolve()
    try:
        spec = (wiki.resolve() / Path(*WIKI_DECISIONS)).relative_to(top_path).as_posix()
    except ValueError:
        return []
    today = datetime.date.today()
    out: List[dict] = []

    def fm_of(text: Optional[str]) -> dict:
        return parse_frontmatter_text(text) if text is not None else {}

    def state(text: Optional[str]) -> str:
        return str(fm_of(text).get("status") or "").strip().lower()

    def add(path: str, day: str, old: Optional[str], new: Optional[str], moved_in: bool = False) -> None:
        if not path.endswith(".md") or new is None:
            return
        if old is None or moved_in:
            out.append({"path": path, "day": str(fm_of(new).get("decided") or "").strip()[:10], "kind": "new",
                        "what": state(new) or "none", "fm": fm_of(new)})
        elif state(old) != state(new):
            out.append({"path": path, "day": day, "kind": "status", "fm": fm_of(new),
                        "what": "%s to %s" % (state(old) or "none", state(new) or "none")})
    # -m --first-parent: a merge commit is read against its first parent too, since a plain log shows no diff for
    # a merge and a status set in one would pass unseen.
    log = _git(["log", "-m", "--first-parent", "--format=%x01%H %cs", "-M", "--name-status", "-z", "--", spec], top_path) or ""
    for commit, st, path, before in name_status(log):
        sha, _, day = (commit or "").partition(" ")
        try:
            if (today - datetime.date.fromisoformat(day.strip())).days > DECISION_STATUS_DAYS:
                continue
        except ValueError:
            continue
        new = _git(["show", "%s:%s" % (sha, path)], top_path)
        if st[:1] == "A":
            add(path, day.strip(), None, new)
        elif st[:1] == "M":
            add(path, day.strip(), _git(["show", "%s^:%s" % (sha, path)], top_path), new)
        elif st[:1] == "R":
            inside = (before or "").startswith(spec + "/")
            add(path, day.strip(), _git(["show", "%s^:%s" % (sha, before)], top_path) if inside else None, new, moved_in=not inside)
    diff = _git(["diff", "HEAD", "-M", "--name-status", "-z", "--", spec], top_path) or ""
    for _, st, path, before in name_status(diff):
        disk = read_text(top_path / path)
        if st[:1] == "A":
            add(path, today.isoformat(), None, disk)
        elif st[:1] == "M":
            add(path, today.isoformat(), _git(["show", "HEAD:%s" % path], top_path), disk)
        elif st[:1] == "R":
            inside = (before or "").startswith(spec + "/")
            add(path, today.isoformat(), _git(["show", "HEAD:%s" % before], top_path) if inside else None, disk, moved_in=not inside)
    for path in (_git(["ls-files", "--others", "--exclude-standard", "-z", "--", spec], top_path) or "").split("\0"):
        if path:
            add(path, today.isoformat(), None, read_text(top_path / path))
    out_unique, seen = [], set()
    for e in out:
        key = (e["path"], e["kind"], e["what"], e["day"])
        if key not in seen:
            seen.add(key)
            out_unique.append(e)
    for e in out_unique:
        e["top"] = top_path
    return out_unique


def party_keys_problem(text: str) -> bool:
    """Whether a Meetings question or decision spells its party keys so that
    a reader could take them two ways: `party:` beside `parties:`, or either
    in capitals. The walls read `parties:` alone there."""
    m = re.match(r"---\n(.*?)\n---", text or "", re.S)
    if not m:
        return False
    keys = [k for k in re.findall(r"(?m)^([A-Za-z_][\w-]*)\s*:", m.group(1)) if k.lower() in ("party", "parties")]
    return bool(keys) and (len({k.lower() for k in keys}) > 1 or any(k != k.lower() for k in keys))


def check_decisions(ws: Workspace) -> List[Finding]:
    """A decision page (#224, point 5) is `wiki/decisions/<YYMMDD> - <slug>.md`
    in the Meetings wiki, `type: decision`, with its question's `zone:` and
    `parties:`, a `status:` of valid, superseded or withdrawn, the raw answer
    it rests on in `source:`, and four sections. Its zone and parties are its
    raw answer's, never wider. A change of `status:` with no raw answer dated
    the same day is warned about: only the user settles a decision."""
    out = []
    wiki = ws.root / "Wikis" / "Meetings"
    for f in sorted(ws.meeting_decisions):
        r = rel(ws, f)
        text = read_text(f) or ""
        fm = ws.meeting_raw.get(f, ws.meetings.get(f, {}))
        raw = parse_frontmatter_text(text)
        if raw.get("type") != "decision":
            out.append(Finding(WARNING, "decisions", r, "frontmatter `type` is %r, should be decision" % raw.get("type"),
                               "A decision page is not marked as one"))
        status = str(raw.get("status") or "").strip().lower()
        if status not in DECISION_STATUSES:
            out.append(Finding(WARNING, "decisions", r, "`status` is %r; a decision is %s" % (raw.get("status"), ", ".join(DECISION_STATUSES)),
                               "A decision page has a status Garrick does not read"))
        if not DECISION_NAME.match(f.stem):
            out.append(Finding(WARNING, "decisions", r, "file name should be `YYMMDD - slug.md`", "A decision page is misnamed"))
        out += party_findings(ws, "decisions", r, fm, "Meetings decision", "decide it once for each side")
        have = decision_sections(text)
        lacking = [n for n in DECISION_SECTIONS if n not in have]
        if lacking:
            out.append(Finding(WARNING, "decisions", r, "no `## %s` section" % "`, `## ".join(lacking),
                               "A decision page lacks one of its four sections"))
        record = raw_answer_there(wiki, raw.get("source")) if raw.get("source") else None
        if record is None:
            out.append(Finding(WARNING, "decisions", r, "rests on no raw answer: `source:` points at none in raw/answers/",
                               "A decision page cites no raw answer"))
        else:
            rfm = parse_frontmatter(record)
            if str(rfm.get("zone") or "").strip() != str(raw.get("zone") or "").strip() or \
                    sorted(strip_tag(t) for t in as_list(rfm.get("parties"))) != sorted(strip_tag(t) for t in as_list(raw.get("parties"))):
                out.append(Finding(WARNING, "decisions", r, "carries a zone or parties that are not its raw answer's, which it must copy exactly",
                                   "A decision page carries other parties than its raw answer"))
        if party_keys_problem(text):
            out.append(Finding(WARNING, "decisions", r, "carries both `party` and `parties`, or spells one in capitals, which a "
                               "reader could take two ways; the walls read `parties:` alone, so it is placed nowhere",
                               "A decision page names its parties two ways"))
    for e in decision_events(ws, wiki):
        r = rel(ws, e["top"] / e["path"])
        if e["kind"] == "new":
            if e["what"] != "valid":
                out.append(Finding(WARNING, "decisions", r, "is new with `status: %s`; a decision starts valid, by your own save, "
                                   "and only you move it on" % e["what"], "A new decision page does not start valid"))
            elif not (e["day"] and day_record(wiki, e["day"], e["fm"])):
                out.append(Finding(WARNING, "decisions", r, "is new, with no raw answer dated %s for its own question, zone and "
                                   "parties; only your own answer settles a decision" % (e["day"] or "its day"),
                                   "A new decision page has no raw answer of its own"))
        elif not day_record(wiki, e["day"], e["fm"]):
            out.append(Finding(WARNING, "decisions", r,
                               "`status:` changed (%s) on %s, with no raw answer dated that day for its own question; only your "
                               "own answer settles a decision, so file it, or put the status back" % (e["what"], e["day"]),
                               "A decision's status changed without a raw answer the same day"))
    return out


def check_links(ws: Workspace) -> List[Finding]:
    """Links that cross a boundary or lead somewhere fragile: a link from one
    zone into another; an absolute path into a cloud-synced folder; a link to
    a name both wikis hold, which Obsidian resolves to either. In the zones
    the check settings name: a note with no `parent:` link to its thread or
    hub (`parent-links`), and a note named as code rather than linked
    (`note-links`)."""
    out = []
    zones = {z.name: z for z in ws.zones}
    for path, text in zone_notes(ws):
        zone = next(z for z in ws.zones if z in path.parents)
        r = rel(ws, path)
        if path.name != "AGENTS.md" and ("[[" in text or "](" in text or "obsidian:" in text):
            for written, target in extract_links(text):
                other = None
                parts = [p for p in target.replace("\\", "/").split("/") if p and p != "."]
                if target.startswith("obsidian:"):
                    other = target.split(":", 2)[1]
                elif len(parts) > 1 and parts[0] == "Zones":
                    other = parts[1]
                elif target.startswith(("./", "../")):
                    try:
                        dest = (path.parent / target).resolve()
                    except (OSError, RuntimeError):
                        dest = None
                    other = next((n for n, z in zones.items() if dest and (z == dest or z.resolve() in dest.parents)), None)
                if other in zones and other != zone.name:
                    out.append(Finding(ERROR, "links", r,
                                       "links %s, in the %s zone; zones never reference each other unless asked" % (written, other),
                                       "A note in %s links into the %s zone" % (zone.name, other)))
                    break
        if CLOUD_PATH_RE.search(text):
            line = next(i for i, l in enumerate(text.splitlines(), 1) if CLOUD_PATH_RE.search(l))
            out.append(Finding(WARNING, "links", "%s:%d" % (r, line),
                               "writes the absolute path of a cloud-synced folder; reach it through a link inside the "
                               "workspace, since the provider renames that folder",
                               "A note in %s writes a cloud folder's full path" % zone.name))
    out += wiki_name_links(ws)
    for zone in setting_zones(ws, "parent-links"):
        out += parent_links(ws, zone)
    for zone in setting_zones(ws, "note-links"):
        out += note_refs(ws, zone)
    return out


def wiki_name_links(ws: Workspace) -> List[Finding]:
    """A page name both wikis hold resolves to either in Obsidian, by the
    shortest path. A link to one must name its wiki: `[[Meetings/wiki/...]]`."""
    out = []
    wikis = ws.root / "Wikis"
    by_suffix: Dict[Tuple[str, str], List[Path]] = {}
    for page in ws.wiki_files:
        parts = Path(rel(ws, page)).parts  # Wikis/<wiki>/wiki/<folder>/<name>.md
        if len(parts) == 5 and parts[2] == "wiki":
            by_suffix.setdefault((parts[3], page.stem.lower()), []).append(page)
    both = {k: v for k, v in by_suffix.items() if len({Path(rel(ws, p)).parts[1] for p in v}) > 1}
    if not both:
        return out
    registry = wikis / "Registry"
    for (folder, name), pages in sorted(both.items()):
        if registry.is_dir() and not (registry / (pages[0].stem + ".md")).is_file():
            out.append(Finding(WARNING, "links", "Wikis/Registry",
                               "wiki/%s/%s is in both wikis with no Registry note to say which holds what"
                               % (folder, pages[0].stem),
                               "A name both wikis hold has no registry note"))
    index = PathIndex(ws, [p for v in both.values() for p in v])
    names = {name for _, name in both}
    others = [p for p in ws.wiki_files if "raw" not in Path(rel(ws, p)).parts[:3] and p != registry / "index.md"
              and not is_faded(ws, p)]
    others += [ws.root / p for p in ROOT_INSTRUCTIONS + ROOT_LOCALS if (ws.root / p).is_file()]
    others += [p for project, _ in ws.projects if in_system(ws, project)
               for p in live_files(project) if p.suffix.lower() == ".md"]
    scanned = list(zone_notes(ws)) + [(p, read_text(p) or "") for p in others]
    for path, text in scanned:
        if "[[" not in text or not any(n in text.lower() for n in names):
            continue
        # A wiki's own pages link inside that wiki, which is where a link
        # from one of them lands first (see check_knowledge).
        parts = Path(rel(ws, path)).parts
        own = parts[1] if parts[0] == "Wikis" and len(parts) > 2 else None
        for m in WIKILINK_RE.finditer(re.sub(r"`[^`\n]*`", "", text)):
            target = m.group(1).split("|", 1)[0].split("#", 1)[0].strip().rstrip("\\")
            if target.split("/", 1)[0] in ("Meetings", "Knowledge", "Wikis") or target.startswith(("./", "../", "/")):
                continue
            hits = {Path(rel(ws, h)).parts[1] for h in resolve(ws, path, target, index)}
            if len(hits) > 1 and own not in hits:
                out.append(Finding(WARNING, "links", rel(ws, path),
                                   "links [[%s]], a name both wikis hold, so Obsidian picks one; name the wiki, "
                                   "[[Meetings/...]] or [[Knowledge/...]]" % target,
                                   "A link names a page both wikis hold"))
                break
    return out


PARENT_RE = re.compile(r'^parent:\s*["\']?\[\[([^\]|#]+)', re.M)
PROJECT_LINK_RE = re.compile(r'^project:\s*["\']?\[\[([^\]|#]+)', re.M)


def links_hub(fm_text: str, zone: str, project: str) -> bool:
    """Does a thread note's `project:` link its own hub: `[[<Project>]]`,
    `[[<Project>/<Project>]]` or `[[Zones/<its zone>/<Project>/<Project>]]`?
    The thread template writes the first, and it places the note in the graph
    as a `parent:` would. A path to a hub of the same name in another zone is
    not its hub."""
    m = PROJECT_LINK_RE.search(fm_text)
    if not m:
        return False
    target = m.group(1).strip()
    target = target[:-3] if target.endswith(".md") else target
    return target in (project, "%s/%s" % (project, project), "Zones/%s/%s/%s" % (zone, project, project))


def parent_links(ws: Workspace, zone: Path) -> List[Finding]:
    """Every live note in a project, other than its hub and the ledger of
    what it published, carries `parent:`, a link to its thread note or hub
    that leads to a live note, so the graph attaches it to its project
    whatever its prose says. A thread note whose `project:` links its hub
    needs no `parent:` as well. The ledger, `Deliverables/published.md` in the
    project or in a thread of a thread-first one, is a table for drift.py, and
    its folder already says whose it is."""
    out = []
    notes = zone_notes(ws, zone)
    stems = {p.stem for p, _ in notes}
    for path, text in notes:
        parts = path.relative_to(zone).parts
        if len(parts) < 2 or not (zone / parts[0] / (parts[0] + ".md")).is_file() or path == zone / parts[0] / (parts[0] + ".md"):
            continue  # loose in the zone, outside any project, or the hub itself
        if parts[-2:] == ("Deliverables", "published.md") and (len(parts) == 3 or len(parts) == 5 and parts[1] == "Threads"):
            continue  # the ledger of what was published
        block = parse_frontmatter_block(text)
        m = PARENT_RE.search(block)
        if not m and len(parts) == 4 and parts[1] == "Threads" and parts[3] == parts[2] + ".md" \
                and links_hub(block, zone.name, parts[0]):
            continue  # a thread note, whose `project:` links its hub
        if not m:
            out.append(Finding(WARNING, "links", rel(ws, path), "no `parent:`, a link to its thread note or hub",
                               "A note in %s does not say which thread it belongs to" % zone.name))
        elif m.group(1).strip().rsplit("/", 1)[-1] not in stems and not (zone / (m.group(1).strip() + ".md")).is_file():
            out.append(Finding(WARNING, "links", rel(ws, path),
                               "`parent: [[%s]]` leads to no live note" % m.group(1).strip(),
                               "A note in %s names a parent that is not there" % zone.name))
    return out


def parse_frontmatter_block(text: str) -> str:
    """The frontmatter of `text`, as text."""
    m = re.match(r"---[^\n]*\n(.*?)\n(?:---|\.\.\.)", text, re.S)
    return m.group(1) if m else ""


def note_refs(ws: Workspace, zone: Path) -> List[Finding]:
    """A hub or thread note names another note as a wikilink, never as a
    path in backticks, which draws no link in the graph. Only a path that
    reaches a live note counts. Deliverables/ and Sources/ are left alone:
    their wording is final, or received."""
    out = []
    for project in project_dirs(zone):
        hub = project / (project.name + ".md")
        if not hub.is_file():
            continue
        scan = [hub] + [p for folder in ("Threads", "Notes") for p in live_files(project / folder)
                        if p.suffix.lower() == ".md" and not {"Deliverables", "Sources"} & set(p.relative_to(project).parts)]
        subs = visible_dirs(project)
        for path in scan:
            text = read_text(path) or ""
            fence = found = False
            for line in body_of(text).splitlines():
                if line.lstrip().startswith(("```", "~~~")):
                    fence = not fence
                if fence or found:
                    continue
                for ref in TICKED_NOTE_RE.findall(line):
                    bases, d = [], path.parent
                    while d == project or project in d.parents:
                        bases.append(d)
                        d = d.parent
                    bases += subs + ([zone] if "/" in ref else [])
                    hit = next((b / ref for b in bases if (b / ref).is_file()), None)
                    if hit is not None and not {p.lower() for p in hit.relative_to(zone).parts[:-1]} & {"archive"}:
                        out.append(Finding(WARNING, "links", rel(ws, path),
                                           "names `%s` as code; write it as a wikilink, so the graph sees it" % ref,
                                           "A note in %s names another note as code" % zone.name))
                        found = True
                        break
    return out


def link_stem(value: str) -> str:
    """A link's target as a bare name: `[[raw/2026/x.txt|X]]` reads x."""
    return Path(str(value).strip().strip("[]").split("|", 1)[0].split("#", 1)[0].strip()).stem


def check_splits(ws: Workspace) -> List[Finding]:
    """Pages that share a raw record are a declared split: each names every
    other in `split-with:`, so each is read with its own parties and a
    brief or a wall never takes one for the whole call. Two pages on one
    record without it are one conversation filed twice, or a split nobody
    declared."""
    out = []
    by_raw: Dict[Path, List[Path]] = {}
    for page, fm in ws.meetings.items():
        if not any(fm.get(k) for k in RAW_FIELDS) or is_faded(ws, page):
            continue                                  # only working pages that name their record
        for raw in meeting_raws(ws, page, fm):
            by_raw.setdefault(raw, []).append(page)
    for raw, pages in sorted(by_raw.items()):
        pages = sorted(set(pages))
        if len(pages) < 2:
            continue
        for page in pages:
            named = {link_stem(v) for v in as_list(ws.meetings[page].get("split-with"))}
            missing = [o.stem for o in pages if o != page and o.stem not in named]
            if missing:
                out.append(Finding(ERROR, "meetings", rel(ws, page),
                                   "shares its raw record %s with %s, and its split-with does not name %s; each page of "
                                   "a split names every other, or the two are one conversation filed twice"
                                   % (raw.name, ", ".join(o.stem for o in pages if o != page), ", ".join(missing)),
                                   "Two meeting pages share one record without saying they split it"))
    return out


def party_findings(ws: Workspace, code: str, r: str, fm: dict, what: str, apart: str) -> List[Finding]:
    """The zone and parties the walls read, on a meeting page or a Meetings
    question (`what`): both there, a zone that is one, parties the Parties
    table knows, and not both sides of a wall, for which `apart` is the fix."""
    out = []
    zone_names = {z.name for z in ws.zones} | set(ws.context["zones"])
    zone = fm.get("zone")
    tags = [strip_tag(t) for t in as_list(fm.get("parties"))]
    missing = [k for k, v in (("zone", zone), ("parties", tags)) if not v]
    if missing:
        out.append(Finding(WARNING, code, r,
                           "unfinished: no %s; nothing on it may be used in a project" % " or ".join(missing),
                           "One %s has no %s" % (what, " or ".join(missing))))
    if zone and zone_names and zone not in zone_names:
        out.append(Finding(WARNING, code, r, "`zone` %s is not a zone" % zone,
                           "A %s names an unknown zone" % what))
    for tag in tags:
        if tag not in ws.context["parties"]:
            out.append(Finding(ERROR, code, r,
                               "party `%s` is not a tag in the Parties table, so no wall can see it" % tag,
                               "A %s names an unknown party" % what))
    both = hats_of(ws.context, tags)
    if both:
        out.append(Finding(WARNING, code, r,
                           "names both %s and %s, one company in two hats, so no project of either may use it; "
                           % tuple(both[0]) + apart,
                           "A %s names one company under both hats" % what))
    return out


def check_meetings(ws: Workspace) -> List[Finding]:
    out = check_splits(ws)
    for page, fm in ws.meetings.items():
        if is_faded(ws, page) or page in ws.meeting_questions:
            continue                                  # read by the walls only; a question, by check_questions
        r = rel(ws, page)
        out += party_findings(ws, "meetings", r, ws.meeting_raw.get(page, fm), "meeting page",
                              "if it was two conversations, file them as two pages")
        if fm and fm.get("type") not in (None, "meeting", "email"):
            out.append(Finding(WARNING, "meetings", r, "`type` is %r, should be meeting or email" % fm.get("type"),
                                   "A meeting page is not marked as a meeting"))
        if not MEETING_NAME_RE.match(page.stem):
            out.append(Finding(WARNING, "meetings", r, "file name should be `YYMMDD-slug.md`",
                                   "A meeting page is misnamed"))
        for problem in bad_dates(fm):
            out.append(Finding(ERROR, "meetings", r, problem, "A meeting page has a date in the wrong form"))
    out += cited_across_walls(ws)
    out += check_entities(ws)
    return out


def check_entities(ws: Workspace) -> List[Finding]:
    """An entity page in Meetings may name the party it stands for, `party:`,
    and a person page of that party links it. One entity page per party at
    most, subfolders included: with two, a person page could link either, so
    it links neither. A tag not in Parties is one no wall can see, and a page
    naming two parties a wall keeps apart stands for neither."""
    out = []
    for rel_, page in entity_pages(ws.root):
        fm = parse_frontmatter(page)
        tags = sorted(set(tag_list(fm.get("party"))))
        for tag in tags:
            if tag != "none" and tag not in ws.context["parties"]:
                out.append(Finding(WARNING, "meetings", rel(ws, page),
                                   "party `%s` is not a tag in the Parties table, so no wall can see it and no "
                                   "person page links it" % tag, "An entity page names an unknown party"))
        hit = next(iter(hats_of(ws.context, tags)), None)
        if hit:
            out.append(Finding(WARNING, "meetings", rel(ws, page),
                               "`party:` names both %s and %s, one company in two hats; an organisation in two roles "
                               "gets one entity page per role" % hit, "An entity page names two hats of one company"))
    folder = ws.root.joinpath(*MEETINGS_ENTITIES)
    for tag, rels in sorted(party_entities(ws.root).items()):
        if len(rels) < 2:
            continue
        for one in rels:
            others = ", ".join("wiki/entities/%s" % o for o in rels if o != one)
            out.append(Finding(WARNING, "meetings", rel(ws, folder / (one + ".md")),
                               "names party %s, and so does %s; one entity page per party, and until there is one "
                               "no person page links either" % (tag, others),
                               "Two entity pages stand for one party"))
    in_the_way = untagged_in_the_way(ws)
    for e in entity_index(ws):
        if not e["tagged"] and not e["misread"] and e["rel"] in in_the_way:   # a misread one is the walls' to refuse
            out.append(Finding(WARNING, "meetings", rel(ws, e["path"]),
                               "%s; write `party: none` for an organisation that is not a party, or its tag, and "
                               "until it says one no tool links a person page to it" % NO_ENTITY_PARTY,
                               "An entity page does not say whose it is"))
    return out + same_named_entities(ws)


NO_ENTITY_PARTY = "no `party:`"


def untagged_in_the_way(ws: Workspace) -> set:
    """The rel of each entity page with no `party:` that stops a person page's
    `organisation:` (#330): one a person page's first line names, by any name
    it goes by, as the proposal reads it (a shorter name inside a longer one
    included); one going by the name of the entity page #319's party default
    would link; or one a person page links by hand. Only those are warned:
    most entity pages are topics or events no person page points at, and an
    untagged page nothing points at stops nothing. Nothing of the person page
    is said."""
    index = entity_index(ws)
    if all(e["tagged"] for e in index):
        return set()
    entities = party_entities(ws.root)
    hit = set()
    for page, text in person_pages(ws):
        fm = parse_frontmatter_text(text)
        rels = []
        if organisation_keys(fm):
            for l in [l for k in organisation_keys(fm) for v in as_list(fm.get(k)) for l in links_in(v)]:
                target = entity_page(ws.root, entity_rel(l)) if entity_rel(l) else None
                rels += [e["rel"] for e in index if target is not None and same_page(e["path"], target)]
        else:
            rels += named_in(first_line(text), index, every=True)
            tags = sorted(set(tag_list(fm.get("party"))))
            if len(tags) == 1 and len(entities.get(tags[0], [])) == 1:
                rels += entities[tags[0]]
        hit |= {e["rel"] for e in name_group(index, rels) if not e["tagged"]}
    return hit


def same_named_entities(ws: Workspace) -> List[Finding]:
    """Two entity pages whose titles, `aliases:` or file names are one name,
    as garrick_lib's org_key() spells it (#330). A first line naming it is
    asked about rather than proposed, and a person page linking either is
    read against the parties of both, so the warning says why."""
    out = []
    index = entity_index(ws)
    for e in index:
        others = sorted(o["rel"] for o in name_group(index, [e["rel"]]) if o["rel"] != e["rel"])
        if others:
            out.append(Finding(WARNING, "meetings", rel(ws, e["path"]),
                               "goes by a name that %s goes by too, in its title, `aliases:` or file name; one entity "
                               "page per organisation, and until there is one a first line naming it is asked about, "
                               "and a link to either is read against the parties of both"
                               % ", ".join("wiki/entities/%s" % o for o in others),
                               "Two entity pages go by one name"))
    return out


def entity_index(ws: Workspace) -> List[dict]:
    """garrick_lib's entity_names(), once a run, with what git holds for an
    entity page read beside the disk's in staged mode."""
    if ws.entity_index is None:
        ws.entity_index = entity_names(ws.root, ws.git_view)
    return ws.entity_index


def cited_across_walls(ws: Workspace) -> List[Finding]:
    """A page of the Meetings wiki written for one party, such as a person or
    an organisation it keeps a page on, with `party` in its frontmatter,
    cites no meeting walled from that party. One organisation in two roles
    gets one page per role, and a meeting cited by both would make the two
    one history. A Meetings question is read the same way, for its parties:
    the pages it would change and the record it came from are its links."""
    out = []
    wiki = ws.root / "Wikis" / "Meetings" / "wiki"
    sources = wiki / "sources"
    if ws.meeting_links is None:
        ws.meeting_links = meeting_index(ws)
    for page in ws.wiki_files:
        question = page in ws.meeting_questions
        if not question and (wiki not in page.parents or sources in page.parents or page.parent == wiki):
            continue
        text = read_text(page) or ""
        tags = {strip_tag(t) for t in as_list(parse_frontmatter_text(text).get("parties" if question else "party"))}
        tags -= {"none"}
        if not tags:
            continue
        for written, target in extract_links(text):
            hits = [m for m in resolve(ws, page, target, ws.meeting_links)
                    if blocked(ws.context, tags, [strip_tag(b) for b in as_list(ws.meetings[m].get("parties"))])]
            if hits:
                b = sorted(blocked(ws.context, tags, [strip_tag(t) for t in as_list(ws.meetings[hits[0]].get("parties"))]))[0]
                decided = page in ws.meeting_decisions
                out.append(Finding(WARNING, "decisions" if decided else "questions" if question else "meetings", rel(ws, page),
                                   "cites %s, a %s with %s; %s is walled and this page does not name it"
                                   % (hits[0].stem, meeting_noun(ws, hits[0]), b, b),
                                   "A Meetings decision cites a meeting across a wall" if decided
                                   else "A Meetings question cites a meeting across a wall" if question
                                   else "A page for one party cites a meeting across a wall"))
                break
    return out


PEOPLE = ("Wikis", "Meetings", "wiki", "people")
# fade.py writes person pages into dormant/ and archive/ too, and the walls
# read them there as they do in wiki/ (#340).
PEOPLE_FOLDERS = (PEOPLE, ("Wikis", "Meetings", "dormant", "wiki", "people"),
                  ("Wikis", "Meetings", "archive", "wiki", "people"))
ENTITY_FOLDERS = (MEETINGS_ENTITIES, ("Wikis", "Meetings", "dormant", "wiki", "entities"),
                  ("Wikis", "Meetings", "archive", "wiki", "entities"))


def folded_dirs(ws: Workspace, parts) -> List[Path]:
    """Every folder at `parts` under the workspace, a part matching in any case
    or Unicode form, so a person page in `Wiki/People/` is found as one in
    `wiki/people/` is (#340). The folder as spelt comes first."""
    here = [ws.root]
    for part in parts:
        want = unicodedata.normalize("NFC", part).casefold()
        nxt = []
        for base in here:
            try:
                names = sorted(os.listdir(str(base)))
            except OSError:
                continue
            nxt += [base / n for n in names if unicodedata.normalize("NFC", n).casefold() == want]
        here = nxt
    out = [d for d in here if d.is_dir() or d.is_symlink()]
    exact = ws.root.joinpath(*parts)
    return sorted(out, key=lambda d: (d != exact, str(d)))


def check_people(ws: Workspace) -> List[Finding]:
    """A person page is read on both sides of every wall. It says who someone
    is and which party they belong to, and holds nothing learned in a meeting."""
    out = []
    folders = [d for f in PEOPLE_FOLDERS for d in folded_dirs(ws, f)]
    if not any(f.is_dir() for f in folders):
        return out
    common = entities = None
    for page in sorted(p for f in folders if f.is_dir() for p in f.rglob("*.md")):
        r = rel(ws, page)
        text = read_text(page) or ""
        fm = parse_frontmatter_text(text) if text else parse_frontmatter(page)
        name = str(fm.get("title") or page.stem)
        tags = [strip_tag(t) for t in as_list(fm.get("party"))]
        if not tags:
            out.append(Finding(WARNING, "people", r,
                               "no `party`: write the tag of the party they belong to, or `party: none` if they have none",
                               "The page for %s does not say which party they belong to" % name))
        elif tags != ["none"]:
            for tag in tags:
                if tag not in ws.context["parties"]:
                    out.append(Finding(ERROR, "people", r,
                                       "party `%s` is not a tag in the Parties table, so no wall can see it" % tag,
                                       "The page for %s names an unknown party" % name))
        if fm and fm.get("type") not in (None, "person"):
            out.append(Finding(WARNING, "people", r, "`type` is %r, should be person" % fm.get("type"),
                               "The page for %s is not marked as a person" % name))
        for problem in bad_dates(fm):
            out.append(Finding(ERROR, "people", r, problem, "The page for %s has a date in the wrong form" % name))
        if entities is None:
            entities = party_entities(ws.root)
        out += organisation_findings(ws, page, fm, name, entities, text)
        if ws.quick:
            continue
        if common is None:
            common = quote_index(ws).common
        heard = meeting_wording(ws, body_of(text), common, page)
        if heard:
            more = " and %d more" % (len(heard) - 1) if len(heard) > 1 else ""
            asked = heard[0] in ws.meeting_questions
            out.append(Finding(WARNING, "people", r,
                               "repeats eight or more words from %s %s%s; a person page is read on both sides of "
                               "every wall, so it says who they are and nothing learned in a meeting"
                               % (meeting_noun(ws, heard[0]), heard[0].stem, more),
                               "The page for %s repeats a Meetings question" % name if asked
                               else "The page for %s repeats what was said in a meeting" % name))
    return out


NO_ORGANISATION = "no `organisation:` link to the entity page of its party"
NO_EMPLOYER = "no `organisation:` link to the entity page of where they work"
ORGANISATION_ASK = "no `organisation:` link, and its first line could mean more than one entity page"


def organisation_target(ws: Workspace, value) -> Tuple[str, Optional[Path]]:
    """What an `organisation:` value says: "" and the entity page it leads to,
    or a problem in words and None. It is exactly `[[wiki/entities/<slug>]]`:
    no alias, no heading, no other path, and never a link reached through a
    symbolic link, so it carries the entity page's identity and nothing else."""
    values = as_list(value)
    m = ENTITY_LINK_RE.match(values[0].strip()) if len(values) == 1 else None
    if not m or any(p in (".", "..") for p in m.group(1).split("/")):
        return ("`organisation:` is exactly \"[[wiki/entities/<slug>]]\": one link, with no alias, heading or other "
                "path, since a person page carries identity alone"), None
    page = entity_page(ws.root, m.group(1))
    if page is None:
        return "`organisation:` [[wiki/entities/%s]] leads to no entity page in wiki/entities/" % m.group(1), None
    return "", page


def organisation_wall(ws: Workspace, fm: dict, names, entity: Optional[Path]) -> Optional[Tuple[str, str]]:
    """The first two walled parties that a person page's `organisation:`
    joins, through the page's own party, the entity page's (on disk and as
    staged), those of every entity page that goes by one of its names, with a
    page naming no party read as the party it is named after (garrick_lib's
    entity_parties), or the People rows for any name the page goes by; None
    if none."""
    theirs = set()
    if entity is not None:
        theirs = set(tag_list(parse_frontmatter(entity).get("party")))
        if entity in ws.git_view:
            theirs |= set(tag_list(parse_frontmatter_text(ws.git_view[entity]).get("party")))
        theirs |= entity_parties(ws.context, same_name(ws, entity))
    ours = set(tag_list(fm.get("party"))) | set(tag_list(fm.get("parties")))
    every = sorted(t for t in ours | theirs | people_parties(ws.context, names) if t in ws.context["parties"])
    both = [t for t in every if is_walled(ws.context, t)]
    return (both[0], both[1]) if len(both) > 1 else None


def same_name(ws: Workspace, entity: Path) -> List[dict]:
    """The entity pages that go by a name `entity` goes by, itself included
    (garrick_lib's name_group): a link to one is read against them all."""
    index = entity_index(ws)
    return name_group(index, [e["rel"] for e in index if same_page(e["path"], entity)])


def same_page(a: Path, b: Path) -> bool:
    """One page under two paths, whatever case either is written in: the
    same file, or, for one git holds and the disk no longer does, the same
    path resolved."""
    try:
        return os.path.samefile(str(a), str(b))
    except OSError:
        return a.resolve() == b.resolve()


def organisation_findings(ws: Workspace, page: Path, fm: dict, name: str,
                          entities: Dict[str, List[str]], text: str = "") -> List[Finding]:
    """A person page links the entity page of where the person works as
    `organisation:` (#330), whatever its party. One with none is told the
    link garrick_lib's organisation_proposal() offers, from its first line or
    else its party's entity page, or that its first line could mean more than
    one; nothing where a wall stands in the way. A link that joins two
    parties a wall keeps apart is the walls check's (organisation_walls), so
    it is not said here as well."""
    r, names = rel(ws, page), (name, page.stem)
    if "organisation" not in fm:
        want, choices = organisation_proposal(ws.root, ws.context, names, fm.get("party"), text,
                                              entities, entity_index(ws))
        if choices:
            return [Finding(WARNING, "people", r, "%s: %s" % (ORGANISATION_ASK, ", ".join(
                "[[wiki/entities/%s]]" % c for c in choices)), "Where %s works could be more than one page" % name)]
        if not want:
            if short_form_parties(ws.context, names):
                return [Finding(WARNING, "people", r,
                                "no `organisation:` link: its name could be a short form of a person the People table "
                                "has under parties a wall keeps apart, so none is proposed and a link by hand is "
                                "refused; give the page the full name it is known by, or ask which person it is",
                                "The page for %s could be a person known under two walled parties" % name)]
            return []
        default = want == organisation_link_default(ws, names, fm, entities)
        return [Finding(WARNING, "people", r, "%s, %s" % (NO_ORGANISATION if default else NO_EMPLOYER, want),
                        "The page for %s does not link the entity page of %s" % (name, "its party" if default
                                                                                 else "where they work"))]
    problem, entity = organisation_target(ws, fm.get("organisation"))
    if problem:
        return [Finding(WARNING, "people", r, problem, "The page for %s links its entity page wrongly" % name)]
    return []


def organisation_link_default(ws: Workspace, names, fm: dict, entities: Dict[str, List[str]]) -> str:
    """#319's link, the entity page of the page's own party, which holds when
    the page's first line names no entity page."""
    return organisation_link(ws.root, ws.context, names, fm.get("party"), entities, entity_index(ws))


def organisation_walls(ws: Workspace, pages: List[Tuple[Path, str]]) -> List[Finding]:
    """A person page whose `organisation:` joins it to two walled parties:
    an entity page of a walled party other than the page's, or any entity
    page on a page the People table has under two walled parties; or whose
    `organisation:`, in any case or form, opens no one entity page that says
    whose it is (organisation_entity). A person page is read on every side of
    a wall, so this is refused like any other file that crosses one, by the
    full check and by the commit hook."""
    out = []
    for page, text in pages:
        fm = parse_frontmatter_text(text)
        if person_shape_problem(text):
            out.append(Finding(ERROR, "walls", rel(ws, page),
                               PERSON_SHAPE + ", and `- item` lines under a key with no value, with no key but %s "
                               "and no link but in `organisation`, and `pinned` only true or false; a YAML reader can find a link in any other form, "
                               "and Obsidian draws one from any property" % ", ".join(PERSON_KEYS),
                               "A person page's frontmatter is not plain lines"))
            continue
        if organisation_keys(fm):
            problem, entity = organisation_entity(ws, fm)
            if problem:
                out.append(Finding(ERROR, "walls", rel(ws, page), problem,
                                   "A person page's organisation link is not one entity page"))
                continue
            hit = organisation_wall(ws, fm, (str(fm.get("title") or page.stem), page.stem), entity) if entity else None
            if hit:
                out.append(Finding(ERROR, "walls", rel(ws, page),
                                   "`organisation:` joins this person to two walled parties, and a person page "
                                   "carries identity alone; take the link out: %s is walled and this page does not name it" % hit[1:],
                                   "A person page links an entity page across a wall"))
                continue
        # A link in the page's text draws a graph edge in Obsidian as
        # `organisation:` does, so it is read the same way (#340).
        linked, problem = text_entity_pages(ws, text)
        if problem:
            out.append(Finding(ERROR, "walls", rel(ws, page), problem, "A person page links in a form the walls do not read"))
            continue
        for entity in linked:
            problem = entity_page_problem(ws, entity, TEXT_LINK)
            hit = None if problem else organisation_wall(ws, fm, (str(fm.get("title") or page.stem), page.stem), entity)
            if hit:
                out.append(Finding(ERROR, "walls", rel(ws, page),
                                   "a link in its text joins this person to two walled parties, and a person "
                                   "page carries identity alone; take the link out: %s is walled and this page does not name it"
                                   % hit[1:], "A person page links an entity page across a wall"))
                break
            if problem:
                out.append(Finding(ERROR, "walls", rel(ws, page), problem,
                                   "A person page links an entity page wrongly"))
                break
    return out


TEXT_LINK = "a link in the page's text opens an entity page"
TEXT_PLAIN = ("a link in a person page's text is written `[[wiki/<folder>/<name>]]` or `[[<name>]]`, each with an "
              "optional `|alias` or `#heading`, and opens a page that is there; the walls read no other form of link")
# One plain link: a wikilink to a page by its path under wiki/, or by its bare
# name, with an alias and a heading allowed. No `.md`, `..`, `./` or other path.
_PLAIN_NAME = r"[^\[\]|#/\\\n<>]+"
# An alias or heading is text, so it holds no bracket, parenthesis, angle bracket
# or address that could start another kind of link (#340).
_PLAIN_TAIL = r"(?:(?!://)[^\[\]\n<>()|#])*"
PLAIN_LINK_RE = re.compile(r"\[\[(?:(?:(?P<grade>dormant|archive)/)?(?P<folder>wiki)/(?P<dir>%s)/)?(?P<name>%s)"
                           r"(?:#%s)?(?:\|%s)?\]\]" % (_PLAIN_NAME, _PLAIN_NAME, _PLAIN_TAIL, _PLAIN_TAIL))
# Anything that could be a link in any reader's hands: a wikilink or an embed, a
# Markdown link (inline or by reference), a definition, an HTML tag or an
# autolink, an Obsidian address. Whatever is left of a person page's text once
# the plain links are taken out must hold none (#340).
LINKLIKE_RE = re.compile(r"\[\[|\]\]|\]\(|\]\[|\]:|!\[|<[^\s<>][^<>]*>|obsidian:", re.I)


# The sentence ingest.py leaves a new person page to fill in, in the angle
# brackets that would otherwise read as a tag; exactly this, and nothing like it.
PERSON_PLACEHOLDER = "<Who they are, and which party, in a sentence.>"


def person_text(text: str) -> str:
    """A person page's text after its frontmatter; the whole of it where it
    has none. The shape check has already refused a frontmatter not closed."""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[0].rstrip() == "---":
        end = next((i for i, l in enumerate(lines[1:], 1) if l == "---"), None)
        if end is not None:
            return "\n".join(lines[end + 1:])
    return "\n".join(lines)


def wiki_name_index(ws: Workspace) -> Dict[str, List[Path]]:
    """The pages under each wiki's `wiki/` folder by file name, folded as a
    reader opens a bare link: no `.md`, case and Unicode form ignored."""
    index: Dict[str, List[Path]] = {}
    for page in ws.wiki_files:
        if page.suffix.lower() != ".md" or page.is_symlink() or not page.is_file():
            continue
        parts = rel(ws, page).split("/")
        if len(parts) > 3 and parts[0] == "Wikis" and (parts[2] == "wiki" or (
                parts[2] in GRADE_DIRS and len(parts) > 4 and parts[3] == "wiki")):
            index.setdefault(unicodedata.normalize("NFC", page.stem).casefold(), []).append(page)
    return index


GRADE_DIRS = ("dormant", "archive")


def wiki_folder_page(ws: Workspace, grade: str, folder: str, name: str) -> Optional[Path]:
    """`[<grade>/]wiki/<folder>/<name>.md` of the Meetings wiki, else the
    Knowledge wiki, as the folders spell them, reached through no symbolic
    link; `grade` is `dormant`, `archive` or nothing, as fade.py writes it."""
    for wiki in ("Meetings", "Knowledge"):
        path = ws.root / "Wikis" / wiki
        for part in ([grade] if grade else []) + ["wiki", folder, name + ".md"]:
            hit = _listed(path, part) if path.is_dir() and not path.is_symlink() else None
            if hit is None:
                path = None
                break
            path = path / hit
            if path.is_symlink():
                path = None
                break
        if path is not None and path.is_file():
            return path
    return None


def is_entity_path(ws: Workspace, page: Path) -> bool:
    """Is `page` an entity page of the Meetings wiki, at any grade? By its
    path from the workspace, however a link in the way is spelt."""
    parts = [unicodedata.normalize("NFC", x).casefold() for x in rel(ws, page).split("/")]
    if parts[:2] != ["wikis", "meetings"]:
        return False
    rest = parts[2:]
    if rest[:1] and rest[0] in GRADE_DIRS:
        rest = rest[1:]
    return len(rest) > 2 and rest[0] == "wiki" and rest[1] == "entities"


def unreadable_text(left: str) -> str:
    """Why a person page's text, with its plain links taken out, is refused:
    what tripped it, quoted, and how to write it instead."""
    m = LINKLIKE_RE.search(left)
    start = m.start()
    back = max(left.rfind("[", 0, start), left.rfind("<", 0, start))
    if back >= 0 and start - back <= 30:
        start = back                        # the construct from where it opens
    at = left[start:start + 40].replace("\0", "[[…]]").replace("\n", " ")
    return ("its text holds `%s`, which the walls read as a link they cannot follow. Write a link as %s; "
            "write a web address bare, with no angle brackets and no Markdown link, and leave out square "
            "brackets and `<` `>` in other text. %s" % (at, "`[[wiki/<folder>/<name>]]` or `[[<name>]]`", TEXT_PLAIN))


def text_entity_pages(ws: Workspace, text: str) -> Tuple[List[Path], str]:
    """The entity pages a person page links in its text, as (pages, problem).
    Fail closed (#340): every link-like thing in the text is one plain wikilink
    (PLAIN_LINK_RE) to a page that is there, or the problem is the page's, and
    names the plain form. Rather than guess which other forms a reader opens,
    none is read: a path with `..` or `.md`, a Markdown link, a reference, an
    HTML tag, an autolink, an address all fail. A plain link opens the page
    by its path under wiki/, or by its bare file name, as Obsidian does."""
    body = person_text(text).replace(PERSON_PLACEHOLDER, "")
    plains = list(PLAIN_LINK_RE.finditer(body))
    left = PLAIN_LINK_RE.sub("\0", body)
    if LINKLIKE_RE.search(left):
        return [], unreadable_text(left)
    pages: List[Path] = []
    index = None
    for m in plains:
        name = unicodedata.normalize("NFC", m.group("name")).strip()
        if not name or name in (".", "..") or name.lower().endswith(".md"):
            return pages, "its text holds a link the walls cannot read: " + TEXT_PLAIN
        if m.group("folder"):
            if m.group("dir").strip() in (".", ".."):
                return pages, "its text holds a link the walls cannot read: " + TEXT_PLAIN
            found = [wiki_folder_page(ws, m.group("grade") or "", m.group("dir").strip(), name)]
        else:
            if index is None:
                index = wiki_name_index(ws)
            found = index.get(name.casefold(), [None])
        if None in found:
            return pages, "its text links `%s`, which is not a page that is there; %s" % (m.group(0), TEXT_PLAIN)
        pages += [f for f in found if is_entity_path(ws, f)]
    return pages, ""


ORGANISATION_ONE = "`organisation:` must be one link to an entity page"


# What str.splitlines() ends a line at and YAML reads as text (#330).
_LINE_BREAKS = frozenset("\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")
_SHAPE_KEY = re.compile(r"^([a-z][a-z0-9_-]*):(?: +(.*?))? *$")
_SHAPE_ITEM = re.compile(r"^(?:  )?- +(.*?) *$")
_FLOW_ITEM = re.compile(r"""^(?:[A-Za-z0-9_#. -]+|"[^"\\,]*"|'[^',]*')$""")


def _plain_scalar(value: str) -> bool:
    """A value as one plain or simply quoted scalar: double quotes with no
    escape inside, single quotes with no quote inside, a wikilink
    `[[...]]` written bare, or a plain word that opens with none of the
    characters that start another kind of YAML node and holds no `: `, nor
    ends in `:`, which would make it a mapping."""
    if value.startswith('"'):
        return re.fullmatch(r'"[^"\\]*"', value) is not None
    if value.startswith("'"):
        return re.fullmatch(r"'[^']*'", value) is not None
    if value.startswith("[["):
        return re.fullmatch(r"\[\[[^\[\]{}]+\]\]", value) is not None
    if ": " in value or value.endswith(":"):
        return False                      # YAML reads `organisation: x` there as a mapping
    return value[:1] not in set("{[]}&*|>!%@`?#,'\"") and not value.startswith("- ") and value != "-"


def _flow_list(value: str) -> bool:
    """A one-line flow list of plain or simply quoted words, `[acme, birch]`,
    with no brackets, braces, `&`, `*` or `:` inside it."""
    m = re.fullmatch(r"\[([^\[\]{}&*:]*)\]", value)
    if m is None:
        return False
    inner = m.group(1).strip()
    return not inner or all(_FLOW_ITEM.match(item.strip()) for item in inner.split(","))


def _holds_link(value: str) -> bool:
    """Does a frontmatter value hold a wikilink or a Markdown link?"""
    return "[[" in value or "](" in value


def person_shape_problem(text: str) -> bool:
    """Is a person page's frontmatter anything but the strict shape every
    tool here writes (#330)? A YAML reader can find an `organisation:` in
    forms a line reader never sees: a byte-order mark, a value on the next
    line or after a comment, a quoted, escaped, tagged or `?` key, an anchor
    and a merge key, a block scalar holding `---`, the whole frontmatter as
    one flow mapping. So, rather than guess at YAML, only this passes, from
    a `---` that opens the file (a byte-order mark aside) to the next `---`
    at the left margin: blank lines; `key: value` lines, the key lower-case
    ASCII and unquoted, the value empty, one plain or simply quoted scalar
    (_plain_scalar) or a one-line flow list of words (_flow_list), with a
    ` # comment` after it allowed; and
    `- item` lines, at the margin or two spaces in, straight under a key
    with no value. No key twice, no key but the schema's (PERSON_KEYS), no
    link in any value but `organisation`'s, no list under `organisation`,
    no tab, no lone carriage return, and
    no character str.splitlines() ends a line at but YAML reads as text
    (U+2028, U+2029, U+0085, \v, \f, \x1c to \x1e).
    A file with no frontmatter has nothing to misread."""
    if text.startswith("﻿"):
        text = text[1:]
    first = text.split("\n", 1)[0].rstrip("\r")
    if first != "---":
        return first.strip().startswith("---") or first.strip() == "..."
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")[1:]
    end = next((i for i, l in enumerate(lines) if l == "---"), None)
    if end is None:
        return True
    keys, open_key = set(), None
    for line in lines[:end]:
        if "\t" in line or "\r" in line or any(ch in _LINE_BREAKS for ch in line):
            return True
        if not line.strip():
            open_key = None
            continue
        item = _SHAPE_ITEM.match(line)
        if item and open_key is not None and line[:1] in (" ", "-"):
            if open_key == "organisation" or not _plain_scalar(item.group(1)) or _holds_link(item.group(1)):
                return True
            continue
        m = _SHAPE_KEY.match(line)
        if m is None:
            return True
        key, value = m.group(1), m.group(2) or ""
        # Only the keys the schema has (#340): Obsidian draws a graph edge
        # from a link in any property, so a key of another name, or spelled
        # with a lookalike letter, could carry one the walls never read.
        if key in keys or key not in PERSON_KEYS or (key != "organisation" and _holds_link(value)):
            return True
        keys.add(key)
        if value[:1] in ('"', "'", "["):
            value = re.sub(r"(?<=[\]\"'])[ ]+#.*$", "", value)     # a comment after a quoted value, as the schema shows
        if value and not (_plain_scalar(value) or _flow_list(value)):
            return True
        if key == "pinned" and value.strip().strip("\"'") not in ("true", "false"):
            return True         # fade.py keep writes `pinned: true`; nothing else is a pin
        open_key = key if not value else None
    return False


def organisation_keys(fm: dict) -> List[str]:
    """The keys of a person page's frontmatter that say where the person
    works, however written: `organisation`, `Organisation`, `organization`."""
    return [k for k in fm if str(k).strip().lower() in ("organisation", "organization")]


def organisation_entity(ws: Workspace, fm: dict) -> Tuple[str, Optional[Path]]:
    """The entity page a person page's `organisation:` opens, for the walls:
    ("", page), ("", None) for a key with nothing in it, or (problem, None).
    The link is read as garrick_lib's entity_rel() reads it, so an alias, a
    heading, `.md`, a full path or a Markdown link is checked against the page
    it opens. Fail closed: more than one link, under one key or several, a
    value that is no link, one that opens no entity page or opens it through
    a symbolic link, and one to an entity page that says no `party:` at all
    (#330), are refused."""
    values = [v for k in organisation_keys(fm) for v in as_list(fm.get(k)) if str(v).strip()]
    if not values:
        return "", None
    links = [l for v in values for l in links_in(v)]
    if len(links) != 1 or any(not links_in(v) for v in values):
        return ORGANISATION_ONE + ", one value holding one link", None
    page = entity_page(ws.root, entity_rel(links[0])) if entity_rel(links[0]) else None
    if page is None:
        return ORGANISATION_ONE + " in wiki/entities/, reached by no symbolic link", None
    problem = entity_page_problem(ws, page, ORGANISATION_ONE)
    return (problem, None) if problem else ("", page)


def entity_page_problem(ws: Workspace, page: Path, what: str) -> str:
    """Why a person page may not link this entity page, or "": its frontmatter
    can be read two ways, it says no party the Parties table knows, or a page
    that goes by its name holds letters the checks do not read. `what` opens
    the sentence, naming the link."""
    listed = False
    for e in entity_index(ws):
        if same_page(e["path"], page):
            listed = True
        if same_page(e["path"], page) and e["misread"]:
            return what + " whose frontmatter is plain key: value lines"
        if same_page(e["path"], page) and (not e["tagged"] or any(t not in ws.context["parties"] for t in e["parties"])):
            return (what + " that says whose it is: give it `party: none`, or its party's tag from the "
                    "Parties table, before a person page links it")
    if not listed:
        # A dormant or archived entity page is in no index: read as one is (#340).
        body = ws.git_view.get(page, read_text(page) or "")
        tags = tag_list(parse_frontmatter_text(body).get("party"))
        if frontmatter_form_problem(body):
            return what + " whose frontmatter is plain key: value lines"
        if not tags or any(t not in ws.context["parties"] for t in tags):
            return (what + " that says whose it is: give it `party: none`, or its party's tag from the "
                    "Parties table, before a person page links it")
    if any(e["suspect"] for e in same_name(ws, page)):
        return (what + " whose names hold only letters the checks read: one written in lookalike "
                "letters, or with an invisible mark, may stand for another organisation")
    return ""


def person_pages(ws: Workspace) -> List[Tuple[Path, str]]:
    """Every person page and its text, `.md` in any case, as the commit
    hook's staged_people() finds one. Symbolic links to a
    page or a folder are passed over, as they may lead out of the wiki; the
    walls refuse them instead (person_links)."""
    out = []
    for folder in [d for parts in PEOPLE_FOLDERS for d in folded_dirs(ws, parts)]:
        if not folder.is_dir() or folder.is_symlink():
            continue
        for here, dirs, files in os.walk(str(folder)):
            dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(here, d)))
            for f in sorted(files):
                path = Path(here) / f
                if f.lower().endswith(".md") and not path.is_symlink():
                    out.append((path, read_text(path) or ""))
    return sorted(out)


def person_link_finding(ws: Workspace, path: Path) -> Finding:
    """The refusal of a symbolic link where the walls read person pages."""
    return Finding(ERROR, "walls", rel(ws, path),
                   PERSON_PLAIN + ", not a symbolic link: the walls do not follow one, so where it leads is never "
                   "checked; put the page itself there", "A person page is reached through a symbolic link")


def person_links(ws: Workspace) -> List[Path]:
    """Every symbolic link where a person page could be read: `wiki/people`
    itself, a folder under it, or a page in it (`.md` in any case). Fail
    closed: person_pages() passes them over, so each is a walls error."""
    out = []
    for folder in [d for parts in PEOPLE_FOLDERS for d in folded_dirs(ws, parts)]:
        if folder.is_symlink():
            out.append(folder)
            continue
        if not folder.is_dir():
            continue
        for here, dirs, files in os.walk(str(folder)):
            out += [Path(here) / d for d in dirs if os.path.islink(os.path.join(here, d))]
            dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(here, d)))
            out += [Path(here) / f for f in files if f.lower().endswith(".md") and os.path.islink(os.path.join(here, f))]
    return sorted(out)


def under_folder(ws: Workspace, path: Path, parts) -> bool:
    """Is `path` at or below the wiki folder `parts`, as git names it, with
    every part compared in any case and Unicode form (#340)?"""
    home = _fold_parts(lexical_folder(ws, parts).parts)
    here = _fold_parts(path.parts)
    return len(here) >= len(home) and here[:len(home)] == home


def _same_folder(ws: Workspace, path: Path, parts) -> bool:
    return _fold_parts(path.parts) == _fold_parts(lexical_folder(ws, parts).parts)


def _fold_parts(parts) -> Tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", str(x)).casefold() for x in parts)


def lexical_folder(ws: Workspace, parts) -> Path:
    """A wiki folder by its path as git names it: the folder above resolved,
    the folder itself not, so a symbolic link in its place is still found
    there."""
    folder = ws.root.joinpath(*parts)
    return folder.parent.resolve() / folder.name


def staged_people(ws: Workspace, staged: List[Tuple[Path, str]],
                  links: frozenset = frozenset(), removed: frozenset = frozenset(),
                  every: bool = False) -> List[Tuple[Path, str]]:
    """The person pages a commit's wall check reads: each staged one, but for
    the symbolic links in `links`, which are refused for what they are, and,
    where an entity page is staged or removed (`removed`: the paths the index
    deletes, a rename's old path among them), every person page that links it,
    as git holds it, since a party changed on the entity page can put the link
    across a wall without the person page changing, and a link left to a page
    that is gone leads nowhere (#340). With `every`, all of them: the
    People or Parties table changed, which can put any page across a wall. An
    entity page staged or removed reads all of them for the same reason."""
    def under(path: Path, parts) -> bool:
        # By the path git stages it at, not where it leads: a symbolic link
        # under people/ is a person page here, and refused (staged_person_links).
        return path.suffix.lower() == ".md" and under_folder(ws, path, parts) and not _same_folder(ws, path, parts)
    out = [(path, text) for path, text in staged if any(under(path, f) for f in PEOPLE_FOLDERS) and path not in links]
    # An entity page at any grade, staged, edited, deleted or renamed away, can
    # change what a link in any person page opens or whose it is (#340).
    entities = [path for path, _ in staged if any(under(path, f) for f in ENTITY_FOLDERS)]
    entities += [path for path in sorted(removed) if any(under(path, f) for f in ENTITY_FOLDERS)]
    if not entities and not every:
        return out
    # A page staged, deleted or renamed away can change what any link in any
    # person page opens, by its path or by a bare name, in a form this would
    # have to guess at. So every person page is read again (#340).
    have = {path.resolve() for path, _ in out}
    for page, text in person_pages(ws):
        if page.resolve() not in have:
            out.append((page, ws.git_view.get(page, text)))
    return out


# ---------------------------------------------------------------------------
# Walls
#
# Three detectors, all deterministic, on every text file inside a project:
#   links   a link to a meeting page whose parties are walled from the project's;
#   names   a party, person or alias from the far side of a wall, by name;
#   quotes  wording lifted from a walled meeting page or its raw transcript.
# A finding names the file and the walled party, never the text it matched:
# the report must not itself carry what the wall kept out.
# ---------------------------------------------------------------------------

# Quotes are found as shared runs of SHINGLE consecutive words, after lower-
# casing and dropping punctuation. Eight words is long enough that ordinary
# prose rarely repeats a run by chance, and short enough to catch a lifted
# sentence or a quoted commitment. A run also needs MIN_CONTENT_WORDS words that
# are not STOPWORDS, so stock phrases made of little words ("let me know if you
# have any questions") never count, while numbers, names and terms do.
SHINGLE = 8
MIN_CONTENT_WORDS = 4
STOPWORDS = frozenset("""
a about after all also am an and any are as at be because been before being but by can could did do does
doing don done for from get got had has have having he her here him his how i if in into is it its just
know let like me more most my no not now of off on one only or our out over re s she so some such t than
that the their them then there these they this those through to too up us very want was we well were what
when where which while who why will with would yes yet you your ll ve d m okay ok right yeah think going
go see say said really thing things thanks thank good
""".split())

# First names that are also everyday words are not matched on their own.
COMMON_WORD_NAMES = frozenset("""
will mark may june april august bill frank grace hope pat sue rich dawn faith joy rose summer
chase hunter art max page ray bob sky april autumn
""".split())

VTT_TIMING_RE = re.compile(r"(?m)^\s*(?:WEBVTT.*|\d+|[\d:.]+\s*-->.*)\s*$")
VTT_TAG_RE = re.compile(r"<[^>\n]*>")
# What a browser never shows: comments, styles and scripts; then the tags,
# with their names and attributes.
HTML_HIDDEN_RE = re.compile(r"<!--.*?-->|<(script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)
HTML_TAG_RE = re.compile(r"</?[A-Za-z!?][^>]*>")


# The blocks of combining marks: what NFKD splits off a letter as its accent.
COMBINING_RE = re.compile("[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]")


def words(text: str) -> List[str]:
    """Lower-case words: accents dropped, `&` read as "and", punctuation gone."""
    text = text.replace("&", " and ")
    if not text.isascii():  # plain ASCII has no accents to drop
        text = COMBINING_RE.sub("", unicodedata.normalize("NFKD", text))
    return re.findall(r"[a-z0-9]+", text.lower())


def html_text(text: str) -> str:
    """An HTML page as a reader sees it: no comments, styles or scripts, no
    tags or attributes, and entities read as the characters they stand for.
    Two pages built from one slide template share their code, not wording."""
    return html.unescape(HTML_TAG_RE.sub(" ", HTML_HIDDEN_RE.sub(" ", text)))


def transcript_text(path: Path, text: str) -> str:
    """A file as the words that were said or written: a transcript without
    its timings and voice tags, so a sentence split across two cues still
    reads as one run of words; a saved mail as its subject and text, decoded
    from however the message was encoded; an HTML page as its visible text."""
    if path.suffix.lower() in (".html", ".htm"):
        text = html_text(text)
    elif path.suffix.lower() == ".vtt":
        text = VTT_TAG_RE.sub(" ", VTT_TIMING_RE.sub(" ", text))
    elif path.suffix.lower() == ".eml":
        try:
            mail = parse_mail_bytes(text.encode("utf-8", errors="replace"), ".eml")
            text = mail["subject"] + "\n" + mail["body"]
        except Exception:  # an unreadable message still counts as its raw text
            pass
    return text


def body_of(text: str) -> str:
    """Text without its frontmatter."""
    if text.startswith("---"):
        m = re.match(r"---[^\n]*\n.*?\n(?:---|\.\.\.)\r?(?:\n|$)", text, re.S)
        if m:
            return text[m.end():]
    return text


def without_party_field(text: str) -> str:
    """The file's text with its own frontmatter `party:` field blanked out."""
    if not text.startswith("---"):
        return text
    lines = text.split("\n")
    in_party = False
    for i, line in enumerate(lines[1:], 1):
        if line.rstrip("\r") in ("---", "..."):        # a `---` alone at the margin ends it, as for YAML
            break
        if re.match(r"party\s*:", line):
            lines[i], in_party = "", True
        elif in_party and (line[:1].isspace() or line.startswith("-")):
            lines[i] = ""
        else:
            in_party = False
    return "\n".join(lines)


# Dates are not content either. Two notes written on the same day share "24
# September 2026" and the words around it by chance, so month and day names,
# years and the days of a month do not count toward MIN_CONTENT_WORDS.
CALENDAR = frozenset("""
january february march april june july august september october november december
jan feb mar apr jun jul aug sep sept oct nov dec
monday tuesday wednesday thursday friday saturday sunday
""".split())


def is_content(token: str) -> bool:
    if token in STOPWORDS or token in CALENDAR:
        return False
    return not (token.isdigit() and (len(token) <= 2 or (len(token) == 4 and token[:2] in ("19", "20"))))


# Each word as a number that is the same in every run of the check, unlike
# Python's own hash of a string, so the commit check can keep a file's runs of
# words from one commit to the next (see NoteCache). Sixty bits: Python hashes
# a number that size as itself.
WORD_IDS: Dict[str, int] = {}


def word_id(token: str) -> int:
    found = WORD_IDS.get(token)
    if found is None:
        found = WORD_IDS[token] = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big") >> 4
    return found


def shingles(tokens: List[str]) -> Iterable[int]:
    """A hash for each run of SHINGLE words that carries enough content words."""
    content = [is_content(t) for t in tokens]
    known = WORD_IDS.get
    ids = [known(t) or word_id(t) for t in tokens]
    for i in range(len(tokens) - SHINGLE + 1):
        if sum(content[i:i + SHINGLE]) >= MIN_CONTENT_WORDS:
            yield hash(tuple(ids[i:i + SHINGLE]))


HEADING_RE = re.compile(r"(?m)^ {0,3}#{1,6}[ \t].*$")
# The header row of a published ledger's table, as System/templates/published.md
# ships it and drift.py reads it. Its words are the ledger's structure, as a
# heading's are, and the separator row under it holds no words, so without a
# break a run would cross from the header into the first row's date cell and
# two walled ledgers dated alike would read as quoting each other (#221). Only
# this exact header is a break: the header of any other table is not.
LEDGER_HEADER_RE = re.compile(r"(?mi)^[ \t]*\|[ \t]*date[ \t]*\|[ \t]*file[ \t]*\|[ \t]*destination[ \t]*\|"
                              r"[ \t]*recipients[ \t]*\|[ \t]*authoritative[ \t]*\|[ \t]*$")
# Where no run of words crosses: a Markdown heading, or a ledger's header row.
STRUCTURE_RE = re.compile(r"(?mi)%s|%s" % (HEADING_RE.pattern[4:], LEDGER_HEADER_RE.pattern[5:]))

# What `scaffold.py checkpoint` writes around a person's items, exactly as
# render_checkpoint() writes it: the opening marker, with its stamp, base and
# key, the line under it, which carries the generated time and CHECKPOINT_SAID,
# and the closing marker. No shared file holds that sentence, so two
# checkpoints in walled projects read as quoting each other on it alone (#225).
# These lines are not read at all, and an item is read as its own words, after
# its kind and before its id. Only the exact shapes the tool writes, none with
# room for a word of anyone's, and only inside a block that opens with the one
# marker and closes with the other: a line shaped like them anywhere else, or
# with anything more in it, is wording like any other.
CHECKPOINT_STAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}(?::\d{2})?)?"
CHECKPOINT_WRITTEN_OPEN_RE = re.compile(
    r"(?m)^<!-- garrick-checkpoint at=%s base=(?:[0-9a-f]{12}|-) key=[0-9a-f]{12} -->[ \t]*$" % CHECKPOINT_STAMP)
CHECKPOINT_WRITTEN_CLOSE_RE = re.compile(r"(?m)^<!-- /garrick-checkpoint -->[ \t]*$")
# The months as said_time() says them, so this line can never disagree with it.
_SAID_MONTHS = "|".join(said_time("2026-%02d-01T00:00:00" % month).split()[3] for month in range(1, 13))
CHECKPOINT_WRITTEN_SAID_RE = re.compile(
    r"^%s\d{2}:\d{2} on \d{1,2} (?:%s) \d{4}\.\*\* %s[ \t]*$"
    % (re.escape(CHECKPOINT_UNCONFIRMED), _SAID_MONTHS, re.escape(CHECKPOINT_SAID)))
# An item, with the id checkpoint_id() gives its kind: the stem alone for the
# kinds a block holds one of, the stem and a number for the rest.
CHECKPOINT_ITEM_RE = re.compile(
    r"(?m)^- (?:%s)[ \t]*$" % "|".join(
        r"\*\*%s\*\*(?P<item_%s>[^\n]*?)<!-- %s -->" % (re.escape(label), kind,
                                                       re.escape(stem) if kind in CHECKPOINT_ONE
                                                       else re.escape(stem) + r"[1-9][0-9]*")
        for kind, label, stem in CHECKPOINT_KINDS))


def checkpoint_spans(text: str) -> List[Tuple[int, int]]:
    """Where each checkpoint block written by the tool sits in `text`: from
    the first byte of its opening marker to the byte after its closing one.
    An opening marker with no closing one after it, or another opening marker
    before it, is no block."""
    spans: List[Tuple[int, int]] = []
    for head in CHECKPOINT_WRITTEN_OPEN_RE.finditer(text):
        if spans and head.start() < spans[-1][1]:
            continue
        close = CHECKPOINT_WRITTEN_CLOSE_RE.search(text, head.end())
        if close is None:
            break
        if CHECKPOINT_WRITTEN_OPEN_RE.search(text, head.end(), close.start()):
            continue                  # the next opening marker is the block's, if any
        spans.append((head.start(), close.end()))
    return spans


# A row of the table in a Resume here block, by the label the thread template
# gives it. The labels are the template's structure, as a heading is, and the
# cells under them are often short and common ("Nothing to rebuild", a Next
# action that opens with the owner's name), so a run that took in one row's
# cell and the next row's label read two walled thread notes as quoting each
# other on wording no shared file holds (#262). Each such row is a break: its
# label is not read, and its cell is read with whatever follows it up to the
# next row's label, so a run is still found inside one cell or running on below it. Only these exact labels, and only between a
# `### Resume here` heading and the rule that closes its block: any other
# table, or a row below the rule, runs into the next line as it stands.
RESUME_ROW_RE = re.compile(r"(?m)^[ \t]*\|[ \t]*(?:%s)[ \t]*\|(?P<cell>[^\n]*)$"
                           % "|".join(re.escape(label) for label in RESUME_LABELS))
# The rule under a Resume here block's table, where the block ends (see resume_block).
RESUME_RULE_RE = re.compile(r"(?m)^[ \t]*---[ \t]*$")

WEB_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I)


MDLINK_LABEL_RE = re.compile(r"\[([^\[\]\n]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")


def without_link_targets(text: str, shared: Optional[Callable[[str], bool]] = None) -> str:
    """`text` as a reader sees it: a wikilink reduced to its alias, a Markdown
    link to its text, an address to nothing. Where a link points is not
    wording; the link check reads it, and two notes that point at the same
    page share no words by doing so. With `shared`, which says whether a
    link's target is a shared file, a link to one loses its text too: it is
    the title of a page every side reads, so two notes that list the same
    Knowledge pages share no words by doing so either."""
    def wikilink(m) -> str:
        target, bar, alias = m.group(1).partition("|")
        if not bar or (shared and shared(target.rstrip("\\").split("#", 1)[0].strip())):
            return " "
        return " %s " % alias

    text = WIKILINK_RE.sub(wikilink, text)
    if shared:
        text = MDLINK_LABEL_RE.sub(lambda m: " " if shared(m.group(2)) else m.group(0), text)
    return WEB_RE.sub(" ", MDLINK_RE.sub("] ", text))


def runs(text: str, shared: Optional[Callable[[str], bool]] = None) -> set:
    """Every shingle of `text`, links reduced to the words a reader sees (see
    without_link_targets), and no run crossing a Markdown heading: the
    headings of a note are its template's structure ("State of play", "Resume
    here"), and the words either side of one were not written as one sentence.
    A published ledger's header row is a break in the same way (see
    LEDGER_HEADER_RE); what its rows hold is read like any other text. So is
    each row of a Resume here table (see RESUME_ROW_RE), read as its cell
    alone. So is a checkpoint block the tool wrote (see
    CHECKPOINT_WRITTEN_OPEN_RE): its markers and the line under the opening
    one are never read, each of its items is read without its kind and its
    id, and any other line in it is read as it stands."""
    text = without_link_targets(text, shared)
    out: set = set()
    last = 0
    for start, end in checkpoint_spans(text):
        out.update(_runs_between_breaks(text[last:start]))
        out.update(_checkpoint_runs(text[start:end]))
        last = end
    out.update(_runs_between_breaks(text[last:]))
    return out


def _runs_between_breaks(text: str, resume_rows: bool = True) -> set:
    """The shingles of `text`, none crossing a heading or a ledger's header,
    nor, with `resume_rows`, a row of the table under a Resume here heading."""
    out: set = set()
    last = 0
    under_resume = False
    for m in STRUCTURE_RE.finditer(text):
        out.update(_resume_runs(text[last:m.start()]) if under_resume else shingles(words(text[last:m.start()])))
        out.update(shingles(words(m.group(0))))
        last = m.end()
        under_resume = resume_rows and RESUME_HEAD_RE.match(m.group(0)) is not None
    out.update(_resume_runs(text[last:]) if under_resume else shingles(words(text[last:])))
    return out


def _resume_runs(text: str) -> set:
    """The shingles of what stands under a `### Resume here` heading, up to
    the next break: no run crosses into a row of its table above the rule
    that closes the block, and no label is read. A cell runs on into what
    follows it, up to the next row's label, so a line that goes on below a
    cell, or the text under the table, is read with the cell it continues."""
    rule = RESUME_RULE_RE.search(text)
    stop = rule.start() if rule else len(text)
    out: set = set()
    last = 0
    for m in RESUME_ROW_RE.finditer(text, 0, stop):
        out.update(shingles(words(text[last:m.start()])))
        last = m.start("cell")
    out.update(shingles(words(text[last:])))
    return out


def _checkpoint_runs(block: str) -> set:
    """The shingles of one checkpoint block, from its opening marker to its
    closing one. The two markers and the line straight under the opening one
    are not read; an item is read as its own words; anything else is read."""
    lines = block.split("\n")
    body = lines[1:-1]
    if body and CHECKPOINT_WRITTEN_SAID_RE.match(body[0]):
        body = body[1:]
    text = "\n".join(body)
    out: set = set()
    last = 0
    for m in CHECKPOINT_ITEM_RE.finditer(text):
        out.update(_runs_between_breaks(text[last:m.start()], resume_rows=False))
        out.update(shingles(words(next(g for g in m.groups() if g is not None))))
        last = m.end()
    out.update(_runs_between_breaks(text[last:], resume_rows=False))
    return out


@dataclass
class QuoteIndex:
    """Where each run of words was said or written, and which runs are common.

    `owners` maps a shingle to what holds it: meeting pages, finished or not,
    whose page or raw record has it, and the text files of every project.
    `tags` gives each project file the party tags it is written for, and
    `project` its project. `common` holds the shingles that also appear in one
    of the shared files (SHARED_FILES, SHARED_FOLDERS), which every side reads,
    so repeating one is never evidence of a leak; `common_beyond_knowledge`
    the ones found in a shared file outside the Knowledge wiki."""
    owners: Dict[int, set]
    common: set
    common_beyond_knowledge: set = field(default_factory=set)
    tags: Dict[Path, frozenset] = field(default_factory=dict)
    project: Dict[Path, Path] = field(default_factory=dict)


# The files every side reads, whose wording is common rather than a leak: the
# instruction files, the rules and the context, the skills, templates and
# tools, and the Knowledge wiki, which holds published material. A list, not
# "System/ and whatever is in it": an interview record, a page a tool rebuilds
# into System/generated/ or a note dropped into System/ can carry what one
# party said, and would then exempt whatever it repeats from the wall check.
# The local file beside an instruction file is read with it, by every side.
# The changelog and the docs are there for the same reason: they are Garrick's
# published release notes and documentation, so a note that describes a
# Garrick feature tends to borrow their wording, on whichever side of a wall
# it sits.
SHARED_FILES = ("AGENTS.md", "Wikis/AGENTS.md", "Wikis/Meetings/AGENTS.md", "System/rules.md", "System/context.md",
                "AGENTS.local.md", "Wikis/AGENTS.local.md", "Wikis/Meetings/AGENTS.local.md", "System/rules.local.md",
                "System/garrick-changelog.md")
SHARED_FOLDERS = ("System/skills", "System/templates", "System/tools", "System/garrick-docs", "Wikis/Knowledge")

# A Garrick checkout kept inside the workspace is where those files come from.
# The repository in the project about it, or a release unpacked to read, holds
# the shipped original of every file above, under `template/`, with the
# changelog at its top; the installer copies them into the positions
# SHARED_FILES and SHARED_FOLDERS name. So a checkout's copies are shared
# where they sit: shipped wording is wording every side reads whether or not
# this workspace has installed it yet. Otherwise a checkout cannot commit a
# new template, or a line added to the rules, whose words the workspace's own
# notes already use, which is the whole purpose of shipping it.
#
# Only what it ships. A checkout's documentation, examples and tests are
# ordinary files of the project that keeps it, and the commit hook reads them
# as such: that is what keeps real material out of a repository on its way to
# being public. That holds for its docs/ too, though the installer ships them
# as System/garrick-docs: a page being written is where real material would
# leave for the public repository, so it counts as shared only once installed.
# How a checkout is recognised (is_checkout, CHECKOUT_TREE) comes from garrick_lib.
CHECKOUT_APART = {"System/garrick-changelog.md": "CHANGELOG.md"}  # shipped from the top, not the tree


def checkouts(ws: Workspace) -> List[Path]:
    """Every Garrick checkout inside a project, each found at its top, with
    nothing below one looked in. A project is where one is kept, and a project
    is where it counts: the walls are checked on a project's files, and a
    commit made inside the checkout is checked as that project's."""
    if ws.checkouts is None:
        found: List[Path] = []
        for project, _ in ws.projects:
            if is_checkout(project):
                found.append(project)
                continue
            for folder, dirs, _ in os.walk(project):
                here = Path(folder)
                keep = []
                for d in sorted(dirs):
                    if d in SKIP_DIRS:
                        continue
                    if is_checkout(here / d):
                        found.append(here / d)
                    else:
                        keep.append(d)
                dirs[:] = keep
        ws.checkouts = found
    return ws.checkouts


def shared_files(ws: Workspace) -> List[Path]:
    """Every shared file that exists: SHARED_FILES, and all under
    SHARED_FOLDERS, in the workspace and in each Garrick checkout it keeps,
    where the checkout holds them before an install moves them."""
    out = [ws.root / name for name in SHARED_FILES]
    for name in SHARED_FOLDERS:
        folder = ws.root / name
        if folder.is_dir():
            out += list(walk_files(folder))
    for checkout in checkouts(ws):
        tree = checkout / CHECKOUT_TREE
        out += [tree / name for name in SHARED_FILES]
        out += [checkout / shipped for shipped in CHECKOUT_APART.values()]
        for name in SHARED_FOLDERS:
            folder = tree / name
            if folder.is_dir():
                out += list(walk_files(folder))
    return [p for p in out if p.is_file()]


def shared_link(ws: Workspace, source: Path) -> Callable[[str], bool]:
    """For a file at `source`: does a link it holds lead to a shared file?"""
    if ws.shared_links is None:
        ws.shared_links = PathIndex(ws, shared_files(ws))
    index = ws.shared_links

    def test(target: str) -> bool:
        if target.startswith("obsidian://"):
            return any(resolve(ws, source, t, index) for _, t in extract_links(target))
        target = unquote(target).split("#", 1)[0]
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target):
            return False  # an address, not a file here
        return bool(resolve(ws, source, target, index))
    return test


# The fields of a meeting page that name its raw record.
RAW_FIELDS = ("raw", "transcript")


def raw_homes(ws: Workspace) -> List[Path]:
    """The Meetings wiki's raw folders: raw/, and the one beside each grade
    of faded pages, where a record goes with its page."""
    meetings = ws.root / "Wikis" / "Meetings"
    return [meetings / home for home in RAW_HOMES]


def raw_records(ws: Workspace) -> Dict[str, List[Path]]:
    """Every file under the Meetings raw/, and under the raw folders of its
    faded pages, at any depth, by stem; raw/inbox/ is not filed yet. In staged
    mode, a record deleted from disk but still in git counts too."""
    if ws.raw_records is not None:
        return ws.raw_records
    homes = raw_homes(ws)
    inbox = homes[0] / "inbox"
    found = set()
    for raw in homes:
        if raw.is_dir():
            for folder, dirs, files in os.walk(raw):
                here = Path(folder)
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and here / d != inbox)
                found |= {here / f for f in files if not f.startswith(".")}
        found |= {p for p in ws.git_view if raw in p.parents and inbox not in p.parents and p != inbox}
    index: Dict[str, List[Path]] = {}
    for p in sorted(found):
        index.setdefault(p.stem, []).append(p)
    ws.raw_records = index
    return index


def meeting_raws(ws: Workspace, page: Path, fm: dict) -> List[Path]:
    """The raw records behind a meeting page. A `raw` (or `transcript`) link
    with a path names one record exactly, at any depth under raw/, or under
    the raw folder of a grade of faded pages (`dormant/raw/`), with or without
    its extension. A bare name, and the page's own slug, find the records of
    that name directly in a raw folder, and only when there are none there,
    in its subfolders: a record in a subfolder is never claimed by a page
    whose link names another. A Meetings question claims none: the record
    that raised it is its `origin:`, which belongs to the page filed from it,
    under that page's parties."""
    if page in ws.meeting_questions:
        return []
    homes = raw_homes(ws)
    index = raw_records(ws)
    found, stems = set(), set()
    linked = False

    def under(p: Path) -> str:
        """`p`'s path inside the raw folder that holds it."""
        return next(p.relative_to(h).as_posix() for h in homes if h in p.parents)

    for key in RAW_FIELDS:
        for value in as_list(fm.get(key)):
            target = value.strip().strip("[]").split("|", 1)[0].split("#", 1)[0].strip()
            if not target:
                continue
            linked = True
            inside = target
            for prefix in ("Wikis/Meetings/", "Meetings/"):
                if inside.startswith(prefix):
                    inside = inside[len(prefix):]
                    break
            home = next((h for h in RAW_HOMES if inside.startswith(h + "/")), None)
            pathed = home is not None or target.startswith(("Meetings/raw/", "Wikis/Meetings/raw/"))
            tail = inside[len(home) + 1:] if home else target
            if "/" in tail or pathed:
                exact = {p for p in index.get(Path(tail).stem, []) if under(p) in
                         (tail, Path(tail).with_suffix("").as_posix()) or Path(under(p)).with_suffix("").as_posix() == tail}
                found |= exact
                if not exact and "/" not in tail:
                    stems.add(Path(tail).stem)
            else:
                stems.add(Path(tail).stem)
    if not linked:
        stems.add(page.stem)
    for stem in stems:
        candidates = index.get(stem, [])
        top = [p for p in candidates if p.parent in homes]
        found |= set(top or candidates)
    return sorted(found)

def finished(fm: dict) -> bool:
    """A meeting page with both of the fields the walls read."""
    return bool(fm.get("zone")) and bool(as_list(fm.get("parties")))


def wording(ws: Workspace, path: Path, text: str, body: bool) -> set:
    """The runs of words of `text`, the text of the file at `path`: as a
    transcript, a mail or a page reads (transcript_text), and with `body`
    without its frontmatter."""
    text = transcript_text(path, text)
    return runs(body_of(text) if body else text, shared_link(ws, path))


def file_runs(ws: Workspace, path: Path, body: bool) -> Iterable[int]:
    """wording() of the file at `path` as it is on disk. In staged mode it
    comes from the cache while the file is unchanged, and while every link it
    holds still leads to a shared file, or not, as it did: a page added to the
    Knowledge wiki can change which of its words a reader sees."""
    if ws.cache is None:
        return wording(ws, path, read_text(path) or "", body)
    link = shared_link(ws, path)

    def make() -> tuple:
        asked: Dict[str, bool] = {}

        def ask(target: str) -> bool:
            asked[target] = link(target)
            return asked[target]

        text = transcript_text(path, read_text(path) or "")
        found = runs(body_of(text) if body else text, ask)
        return array("q", sorted(found)).tobytes(), sorted(asked.items())

    held, _ = ws.cache.get("body" if body else "text", path, make,
                           lambda v: all(link(target) == answer for target, answer in v[1]))
    found = array("q")
    found.frombytes(held)
    return found


def quote_index(ws: Workspace, wanted: Optional[set] = None) -> QuoteIndex:
    """The QuoteIndex of the whole workspace. With `wanted`, the runs of words
    the files being committed hold, the index of those runs alone: the commit
    check asks after no other, so a file that holds none of them is passed
    over once its runs are known, and the cache knows them (see NoteCache)."""
    if ws.quote_index is not None:
        return ws.quote_index
    if wanted is not None and not wanted:
        ws.quote_index = QuoteIndex({}, set())  # nothing to ask after
        return ws.quote_index
    owners: Dict[int, set] = {}

    def add(found: List[Iterable[int]], owner: Path) -> bool:
        """Say that `owner` holds the runs `found`; whether it holds one."""
        held = False
        for hs in found:
            for h in (hs if wanted is None else wanted.intersection(hs)):
                owners.setdefault(h, set()).add(owner)
                held = True
        return held

    # In staged mode a file can hold one text on disk and another in git (see
    # git_view): both count as where its wording was said or written.
    view = ws.git_view

    def texts(path: Path, body: bool) -> List[Iterable[int]]:
        out = [file_runs(ws, path, body)] if path.exists() else []
        if path in view:
            out.append(wording(ws, path, view[path], body))
        return out

    # Every meeting page and its raw record, finished or not: nothing on an
    # unfinished page may be used anywhere until it has its zone and parties.
    for page, fm in ws.meetings.items():
        add(texts(page, True), page)
        for r in meeting_raws(ws, page, fm):
            add(texts(r, False), page)
    # Every project's own text files, under the party each is written for: a
    # client's brief or data file, and the notes made from them, are that
    # party's material as much as its meetings are. Template folders are not.
    tags: Dict[Path, frozenset] = {}
    projects: Dict[Path, Path] = {}
    for project, pfm in ws.projects:
        ptags = party_tags(ws, project / (project.name + ".md"), pfm)
        thread_tags: Dict[str, set] = {}
        files = list(walk_files(project, set_apart(ws)))
        files += sorted(p for p in view if project in p.parents and not p.exists())  # deleted, but still in git
        for path in files:
            if path.suffix.lower() not in TEXT_SUFFIXES or is_template_path(ws, path):
                continue
            if not add(texts(path, True), path):
                continue  # holds no run: nobody asks what it is written for
            parts = path.relative_to(project).parts
            ftags = set(ptags)
            if len(parts) > 2 and parts[0] == "Threads":
                if parts[1] not in thread_tags:
                    note = project / "Threads" / parts[1] / (parts[1] + ".md")
                    thread_tags[parts[1]] = party_tags(ws, note)
                ftags |= thread_tags[parts[1]]
            tags[path] = frozenset(ftags)
            projects[path] = project
    common: set = set()
    beyond: set = set()
    # Wording also found in a shared file is common wording, not a leak. No
    # other file counts, however widely it is read: see SHARED_FILES. A shared
    # file whose working copy differs from git counts only for the wording both
    # versions hold, so an edit left unstaged cannot make a quotation common.
    knowledge = ws.root / "Wikis" / "Knowledge"
    for path in shared_files(ws):
        if path.suffix.lower() in TEXT_SUFFIXES or path.suffix.lower() == ".eml":
            found = {h for h in file_runs(ws, path, False) if h in owners}
            if path in view:
                found &= wording(ws, path, view[path], False)
            common |= found
            if knowledge not in path.parents:
                beyond |= found
    ws.quote_index = QuoteIndex(owners, common, beyond, tags, projects)
    if ws.cache is not None:
        ws.cache.whole = True
    return ws.quote_index


def meeting_wording(ws: Workspace, text: str, exempt: set, source: Path) -> List[Path]:
    """The finished meeting pages whose page or raw record shares a run of
    SHINGLE words with `text`, the text of the file at `source`, leaving out
    the runs in `exempt`."""
    index = quote_index(ws)
    found = set()
    for h in runs(text, shared_link(ws, source)):
        if h in exempt:
            continue
        found.update(o for o in index.owners.get(h, ()) if o in ws.meetings and finished(ws.meetings[o]))
    return sorted(found)


def name_forms(ws: Workspace, walled_tags: set) -> Dict[str, List[Tuple[bool, str]]]:
    """For each walled party, the forms that name it: (case-sensitive, form).

    Case-insensitive forms are word sequences, matched on `words()`: the party's
    name, tag and mail domains, its people's full names, and the aliases that
    mean either. A
    person's first name alone is matched only as written, capitalised, and not
    when it is an everyday word. A form that also names a party on this side of
    the wall is dropped: it cannot tell the two apart, and so is a form that is
    a run of whole words inside a near-side form of that same walled party,
    which is a person declared on both sides as herself.

    The forms come back longest first, so the one a finding names is the most
    telling form the text holds: "Dana Rossi" where the note writes her name in
    full, her party's tag `rossi` only where the full name is not there to be
    found.
    """
    key = frozenset(walled_tags)
    if key not in ws.forms:
        ws.forms[key] = _name_forms(ws, walled_tags)
    return ws.forms[key]


def _in_near_side(form: str, near_side: set) -> bool:
    padded = " %s " % form
    return any(padded in (" %s " % ns) for ns in near_side)


def _name_forms(ws: Workspace, walled_tags: set) -> Dict[str, List[Tuple[bool, str]]]:
    ctx = ws.context
    forms: Dict[str, set] = {tag: set() for tag in ctx["parties"]}
    firsts: Dict[str, set] = {tag: set() for tag in ctx["parties"]}
    means: Dict[str, str] = {}
    for tag, entry in ctx["parties"].items():
        for form in [entry.get("party") or "", tag] + list(entry.get("domains", [])):
            key = " ".join(words(form))
            if key:
                forms[tag].add(key)
                means[key] = tag
    for person in ctx["people"]:
        tag = person["party"]
        if tag not in forms:
            continue
        key = " ".join(words(person["name"]))
        if key:
            forms[tag].add(key)
            means[key] = tag
        first = person["name"].split()[0] if len(person["name"].split()) > 1 else ""
        if len(first) >= 3 and first.lower() not in COMMON_WORD_NAMES and first[:1].isupper():
            firsts[tag].add(first)
    for heard, meaning in ctx["aliases"].items():
        tag = means.get(" ".join(words(meaning)))
        key = " ".join(words(heard))
        if tag and key:
            forms[tag].add(key)
    near_people = {" ".join(words(p["name"])) for p in ctx["people"]
                   if p["party"] in forms and p["party"] not in walled_tags}
    near_side = set()
    for tag in forms:
        if tag not in walled_tags:
            near_side |= forms[tag] | {f.lower() for f in firsts[tag]}
    out: Dict[str, List[Tuple[bool, str]]] = {}
    for tag in sorted(walled_tags):
        if tag not in forms:
            continue
        both = near_people & forms[tag]
        found = [(False, f) for f in sorted(forms[tag])
                 if f not in near_side and not _in_near_side(f, both)]
        found += [(True, f) for f in sorted(firsts[tag])
                  if f.lower() not in near_side and not _in_near_side(f.lower(), both) and f.lower() not in forms[tag]]
        # Longest first. Which form a finding names decides whether it reads as
        # a tag hit or a name hit, so it must be the most telling form the text
        # holds and not whichever one the alphabet put first.
        out[tag] = sorted(found, key=lambda f: (-len(f[1].split()), -len(f[1]), f[1]))
    return out


def fold_format(text: str) -> str:
    """`text` with Unicode format characters (zero-width spaces and joiners, bidi marks, soft hyphens) taken out
    and every kind of space made a plain one, so a name cut by one still reads as the name. Initials stay a limit."""
    return "".join(" " if unicodedata.category(c) == "Zs" else c for c in text if unicodedata.category(c) != "Cf")


def padded_words(text: str) -> str:
    """`text` as its words, with a space either side, for names_hit."""
    return " %s " % " ".join(words(text))


def name_hit(text: str, forms: List[Tuple[bool, str]], padded: Optional[str] = None) -> Optional[str]:
    """The first of `forms` that `text` holds, or None. `name_forms` gives them
    longest first, so that is the most telling form the text holds. `padded` is
    padded_words(text), when the caller has it already."""
    if padded is None:
        padded = padded_words(text)
    for case_sensitive, form in forms:
        if case_sensitive:
            if re.search(r"(?<![\w])%s(?![\w])" % re.escape(form), text):
                return form
        elif " %s " % form in padded:
            return form
    return None


def names_hit(text: str, forms: List[Tuple[bool, str]], padded: Optional[str] = None) -> bool:
    """Does `text` hold one of `forms`? `padded` is padded_words(text), when
    the caller has it already."""
    return name_hit(text, forms, padded) is not None


def as_tag(ws: Workspace, tag: str, hit: str) -> str:
    """How to say that the party's tag, not one of its names, is what matched:
    ` (as "rossi")`, or nothing when a name matched, or when the tag reads as
    the party's name does and saying it twice tells nobody anything.

    Only ever the tag. The party's name and its tag are already in the
    refusal; a person's name, an alias and a mail domain are not, and naming
    one would put a walled name into a report that has never carried one."""
    tag_form = " ".join(words(tag))
    name_form = " ".join(words(ws.context["parties"].get(tag, {}).get("party") or ""))
    return ' (as "%s")' % tag if hit == tag_form and tag_form != name_form else ""


def party_tags(ws: Workspace, note: Path, fm: Optional[dict] = None) -> set:
    """The party tags a hub or thread note declares. In staged mode, where git
    holds another version of the note, the tags of both: the more parties a
    file belongs to, the more walls stand around its wording."""
    tags = note_party_tags(note_frontmatter(ws, note) if fm is None else fm)
    if note in ws.git_view:
        tags |= note_party_tags(parse_frontmatter_text(ws.git_view[note]))
    return tags


def note_party_tags(fm: dict) -> set:
    """The tags a note's `party:` and `parties:` name together, as garrick_lib's labels() reads them (a hub or a
    thread note should carry `party:` alone, and is refused with a finding when it carries `parties:`)."""
    return {strip_tag(t) for key in ("party", "parties") for t in as_list(fm.get(key))}


def zone_party(ws: Workspace, project: Path, ptags: set) -> set:
    """The party every file of the project's zone carries, once the hub names a party at all."""
    named = ws.context["zone_parties"].get(project.parent.name)
    return {named} if named and ptags else set()


def file_tags(ws: Workspace, project: Path, ptags: set, path: Path) -> Tuple[set, str]:
    """The party tags a project file is written for, and how to say where it is."""
    tags = set(ptags) | zone_party(ws, project, ptags)
    parts = Path(rel(ws, path)).parts
    where = project.name
    if len(parts) > 5 and parts[3] == "Threads":
        thread = parts[4]
        note = project / "Threads" / thread / (thread + ".md")
        tags |= note_party_tags(note_frontmatter(ws, note))
        where = "%s's %s thread" % (project.name, thread)
    return tags, where


# What separates one candidate path from the next in a code line: white space,
# quotes, brackets, pipes, redirects, separators and `=`. A path with a space
# in it is read as a run of words (below), or as a quoted string.
CODE_TOKEN_RE = re.compile(r"[^\s\"'`()<>|;,=&{}\[\]]+")
QUOTED_RE = re.compile(r"\"([^\"]*)\"|'([^']*)'")
SHELL_BREAK_RE = re.compile(r"[;|&<>]")
MAX_RUN_WORDS = 8  # words a path with spaces in it may span in a code line


def _without_position(token: str) -> str:
    """`token` with a trailing `:12`, `:12:3` or `:12:3:` taken off, in one
    pass from the end."""
    end = len(token)
    while end and token[end - 1] == ":":
        end -= 1
    while True:
        i = end
        while i and token[i - 1].isdigit():
            i -= 1
        if 0 < i < end and token[i - 1] == ":":
            end = i - 1
        else:
            return token[:end]


def _forms(raw: str) -> List[str]:
    """The paths one candidate may mean: as written, without a heading, a
    query or a line position, and without trailing punctuation."""
    base = raw.split("#", 1)[0].strip()
    if re.match(r"(?i)^file:", base):
        base = re.sub(r"(?i)^file:(?://[^/]*)?", "", base)
    plain = base.split("?", 1)[0]
    forms = [base, base.rstrip(".:,;"), plain, _without_position(plain).rstrip(".:,;")]
    forms += [unquote(f) for f in forms if "%" in f]
    forms += [lexical(f) for f in forms if ".." in f]
    return [f for i, f in enumerate(forms) if f and f not in forms[:i]]


def code_paths(text: str, is_file: Optional[Callable[[str], bool]] = None) -> List[Tuple[str, str]]:
    """(as written, target) for every path written as code in `text`: a code
    span, or a line of a fenced block, that holds a slash (code_texts). The
    whole of the span or line is read as a path, and so is each slash-bearing
    token of it, each quoted string, and each run of up to eight words that
    holds a slash, since `cat Harbour/Notes.md` names a file as
    `Harbour/Notes.md` does and a file name may hold spaces. A trailing `:12`
    or `?x` is taken off as well as kept. Nothing resolves these as a link
    does, but a person or an assistant follows one just the same, and Nurture
    may turn one into a link. A target that ends in `/` names a folder and is
    left out, unless its last segment has an extension or `is_file` says a file
    has exactly that path: matched by name it would find a note of that name."""
    out = []
    for written, body in code_texts(text):
        candidates = [body.strip().strip("\"'")]
        candidates += [a or b for a, b in QUOTED_RE.findall(body)]
        shell = body.replace("\\ ", "\0")                      # `Bid\ model.md` is one word
        candidates += [t.replace("\0", " ") for t in CODE_TOKEN_RE.findall(shell)]
        for segment in SHELL_BREAK_RE.split(shell.replace("=", " ")):
            words = [w.strip("\"'`()").replace("\0", " ") for w in segment.split()]
            for i in range(len(words)):
                for j in range(i + 2, min(len(words), i + MAX_RUN_WORDS) + 1):
                    if any("/" in w for w in words[i:j]):
                        candidates.append(" ".join(words[i:j]))
        seen = set()
        for candidate in candidates:
            for target in _forms(candidate):
                if target in seen:
                    continue
                seen.add(target)
                target = re.sub(r"/[*?]+$", "/", target)  # `Demo.md/*`: a glob tail
                slashed = target.endswith("/")
                if slashed:
                    # A folder path is never matched by name to a note (the
                    # folder reading follows it). A last segment with an
                    # extension is a file written with a stray slash: it is
                    # read as the same token without it.
                    target = target.rstrip("/")
                    if target in seen or not (re.search(r"\.[A-Za-z0-9]{1,5}$", target)
                                              or (is_file is not None and is_file(target))):
                        continue  # no extension, and no file of exactly that name: a folder
                    seen.add(target)
                    if lexical(target) and lexical(target) not in seen:  # as _forms settles it
                        seen.add(lexical(target))
                        out.append((written, lexical(target)))
                if ("/" in target or slashed) and not re.match(r"^[a-z][a-z0-9+.-]*:", target):
                    out.append((written, target))
    return out


def project_index(ws: Workspace) -> "PathIndex":
    """Every file of every project, indexed for links once a run, with the
    project each belongs to. What git ignores counts: a link into a walled
    project lands there whether or not git keeps the file. But a path to an
    ignored file matches it by its tail only when the tail reaches the
    project's folder: a copy, a worktree or a build kept in a project holds
    files such as `System/rules.md`, and a path in another note that only ends
    the same way does not point into it. A Garrick checkout kept in a project
    does not count: it is Garrick's shipped files, not the project's notes
    (set_apart). In staged mode, a file deleted from disk but still in git
    counts too."""
    if ws.project_links is None:
        owner: Dict[Path, Path] = {}
        skip = set(checkouts(ws))
        hidden = ignored(ws)
        reach: Dict[Path, int] = {}
        for project, _ in ws.projects:
            for path in walk_files(project, skip, nested=True):
                owner.setdefault(path, project)
                if hidden and (path in hidden or any(up in hidden for up in path.parents)):
                    reach[path] = len(path.relative_to(project.parent).parts)   # the project's folder and on (#399)
            for path in sorted(p for p in ws.git_view if project in p.parents and not p.exists()):
                owner.setdefault(path, project)
        ws.project_files = owner
        ws.project_links = PathIndex(ws, owner)
        ws.project_links.reach = reach
    return ws.project_links


@dataclass
class DirIndex:
    """Every folder of every project, nested repositories included, and the
    folders above them up to the workspace. A Garrick checkout is left out, as
    project_index leaves it. `by_name` maps a folder's lower-cased name to its
    folders, `child` a (parent, lower-cased name) to the folder, `names` a
    folder to the lower-cased names of its folders and `owner` a folder to its
    project (None above the projects)."""
    by_name: Dict[str, List[Path]] = field(default_factory=dict)
    child: Dict[Tuple[Path, str], Path] = field(default_factory=dict)
    names: Dict[Path, set] = field(default_factory=dict)
    owner: Dict[Path, Optional[Path]] = field(default_factory=dict)
    memo: Dict[tuple, frozenset] = field(default_factory=dict)
    links: Dict[str, List[Tuple[Path, Path]]] = field(default_factory=dict)  # a symlinked folder's lower-cased name -> (its parent, the folder it leads to)
    hidden: set = field(default_factory=set)  # folders git ignores: a path reaches one only when it names the project (#399)

    def add(self, folder: Path, project: Optional[Path]) -> None:
        if folder in self.owner:
            return
        self.owner[folder] = project
        name = folder.name.lower()
        self.by_name.setdefault(name, []).append(folder)
        self.child[(folder.parent, name)] = folder
        self.names.setdefault(folder.parent, set()).add(name)


def project_dir_index(ws: Workspace) -> DirIndex:
    """The folders a path written in a note may lead into (DirIndex), built once
    a run. In staged mode, the folders of a file deleted from disk but still in
    git count too."""
    if ws.project_dirs is None:
        idx = DirIndex()
        skip = set(checkouts(ws))
        ignores = ignored(ws)
        for apart in skip:  # named, so a path into one ends there; never entered
            idx.names.setdefault(apart.parent, set()).add(apart.name.lower())
        pending_links: List[Tuple[Path, str]] = []
        for project, _ in ws.projects:
            for above in project.parents:
                if above not in idx.owner:
                    try:
                        pending_links += [(above, e.name) for e in os.scandir(above) if e.is_symlink() and e.is_dir()]
                    except OSError:
                        pass
                idx.add(above, None)
                if above == ws.root:
                    break
            for dirpath, dirnames, _ in os.walk(project):
                here = Path(dirpath)
                pending_links += [(here, d) for d in dirnames if (here / d).is_symlink() and here / d not in skip]
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and here / d not in skip)
                idx.add(here, project)
                if ignores and (here in ignores or here.parent in idx.hidden):
                    idx.hidden.add(here)
            for path in ws.git_view:
                if project in path.parents:
                    for above in path.parents:
                        if above == project:
                            break
                        idx.add(above, project)
        # A symbolic link to a folder is a name for the folder it leads to, when
        # that is inside the workspace. One that leads out of it (a shared
        # drive) is never followed.
        real_root = Path(os.path.realpath(ws.root))
        for parent, name in pending_links:
            try:
                target = Path(os.path.realpath(parent / name)).relative_to(real_root)
            except ValueError:
                continue
            folder = ws.root.joinpath(*target.parts)
            if folder in idx.owner:
                idx.links.setdefault(name.lower(), []).append((parent, folder))
                idx.names.setdefault(parent, set()).add(name.lower())
        ws.project_dirs = idx
    return ws.project_dirs


# What may follow a folder's name without being part of a longer name, and what
# ends a path written in a note: white space, a quote, a closing bracket, a
# comma and the like. Anything else after a folder and its slash is part of a
# longer path.
PATH_ENDERS = set("'\"`)]}>,;|&:")
UNSEEN = dict.fromkeys(list(range(0x200b, 0x2010)) + list(range(0x202a, 0x202f)) + list(range(0x2060, 0x2065)) + [0xfeff, 0xad])
SPACES = {ord(c): " " for c in "\u00a0\u202f\u3000\u1680\u180e"} | {c: " " for c in range(0x2000, 0x200b)}
# The folders every project has by Garrick's layout. Written without the
# project's name, one means the note's own project, whether or not that
# project has made it yet.
LAYOUT_FOLDERS = ("deliverables", "sources", "threads", "notes")
# The folders an assistant's harness keeps in any project (`.claude/settings.json`, `.agents/skills`). Written
# relative, first, they too mean the note's own project, whoever else holds one (#423).
HARNESS_FOLDERS = (".claude", ".agents", ".codex")
DIR_NAME_MAX = 255  # the longest a file name can be


def plain_text(text: str) -> str:
    """`text` as a person reads a path in it: zero-width characters gone,
    every kind of space a space, a backslash before a space gone, and `%20`
    and the like undone."""
    text = text.translate(UNSEEN).translate(SPACES).replace("\\ ", " ")
    return unquote(text) if "%" in text else text


def _namey(c: str) -> bool:
    return c.isalnum() or c in "_-."


def _ends_path(c: str) -> bool:
    return c.isspace() or c in PATH_ENDERS


def _step(idx: DirIndex, here: Optional[frozenset], name: str, key: tuple) -> frozenset:
    """The folders called `name` inside any of `here` (any folder at all when
    `here` is None), remembered by `key`."""
    got = idx.memo.get(key)
    if got is None:
        low = name.lower()
        named = idx.by_name.get(low, ())
        if here is None:
            got = frozenset(named)
        elif len(named) <= len(here):
            got = frozenset(f for f in named if f.parent in here)
        else:
            got = frozenset(c for p in here for c in (idx.child.get((p, low)),) if c is not None)
        led = idx.links.get(low)
        if led:
            got = got | frozenset(f for p, f in led if here is None or p in here)
        idx.memo[key] = got
    return got


def _run(idx: DirIndex, text: str, start: int, end: int, here: Optional[frozenset], ctx: str = ""):
    """From `start`, how far the written path follows folders: (the folders
    reached, how many names led there, whether the path goes on past them with
    a name). `ctx` says where `here` is, for the memory. A path that ends
    at a folder, with or without its slash, or goes on only with white space
    or a closing quote, is a path to a folder and does not go on."""
    pos = start
    key: tuple = (ctx,)
    reached: Optional[frozenset] = None
    count = 0
    while pos < end:
        slash = text.find("/", pos, end)
        stop = end if slash == -1 else slash
        seg = text[pos:stop]
        if not seg:
            pos = stop + 1
            continue
        if len(seg) > DIR_NAME_MAX:
            nxt = frozenset()
        else:
            key = key + (seg.lower(),)
            nxt = _step(idx, here, seg, key)
        if nxt:
            reached, here, count = nxt, nxt, count + 1
            if slash == -1:
                return reached, count, False
            pos = slash + 1
            continue
        if here is None:
            return None, 0, False
        # No folder of that name. A folder's name with a space or a closing
        # quote after it is a path to the folder, with something after it.
        known = set().union(*(idx.names.get(f, ()) for f in here))
        low = seg.lower()
        for i in range(1, len(seg) + 1):
            if (i == len(seg) or not _namey(seg[i])) and low[:i] in known:
                return reached, count, False
        return reached, count, not _ends_path(seg[0])
    return reached, count, False


# The top folders of an operating system: a path written from one leads out of the workspace, unless it passes
# through the workspace's own folder or its Zones/ or Wikis/.
SYSTEM_TOPS = frozenset({"users", "home", "library", "system", "applications", "volumes", "private", "tmp", "var", "etc",
                         "opt", "usr", "mnt", "srv", "root", "network", "cores", "bin", "sbin", "dev", "proc", "run", "media"})
# The folders a home folder holds by the operating system's own layout. `~/Harbour` could be a folder of the
# workspace written from the home folder, so it is still read by its names; `~/Library` cannot.
HOME_FOLDERS = frozenset({"library", "documents", "downloads", "desktop", "applications", "pictures", "music", "movies",
                          "public", "appdata", "onedrive"})


def _folder_key(name: str) -> str:
    """A folder's name as the resolver reads it: case, `-`, `_` and spaces do not tell two names apart."""
    return re.sub(r"[-_\s]+", "", name.lower())


def _workspace_names(ws: Workspace, idx: DirIndex) -> frozenset:
    """The names (_folder_key) of every zone, project and thread folder of the workspace, once a run."""
    got = getattr(idx, "top_names", None)
    if got is None:
        names = set()
        zones = ws.root / "Zones"
        try:
            names |= {_folder_key(e.name) for e in os.scandir(zones) if e.is_dir()}
        except OSError:
            pass
        projects = {project for project, _ in ws.projects}
        for folder in idx.owner:
            if folder in projects:
                names.add(_folder_key(folder.name))
            elif folder.parent.name.lower() == "threads" and folder.parent.parent in projects:
                names.add(_folder_key(folder.name))
        for project in projects:
            names.add(_folder_key(project.parent.name))
        got = idx.top_names = frozenset(names)
    return got


def _outside_workspace(ws: Workspace, idx: DirIndex, rest: str) -> bool:
    """Does the absolute path `rest`, which holds no mark of the workspace, lead out of it: `~/` and a folder every
    home folder holds, or `/…` from an operating system's top folder, and only when no zone, project or thread of
    this workspace has that name. A workspace with a project called `Home` or `Library` reads `/Home/…` and
    `~/Library/…` by its names, as before. What is still read by names: every other first segment, and any
    path whose first system folder is also a zone, project or thread name (any case; `-`, `_` and spaces alike).
    A later segment is not looked at: `~/Library/<anything>` is outside the workspace whatever the segments after
    it are called, which is the case the rule exists for."""
    if rest.startswith("~/"):
        first = rest[2:].split("/", 1)[0]
        listed = first.lower() in HOME_FOLDERS or first.startswith(".")
    else:
        first = rest[1:].split("/", 1)[0]
        listed = rest.startswith("/") and first.lower() in SYSTEM_TOPS
    return listed and _folder_key(first) not in _workspace_names(ws, idx)


def dir_crossings(ws: Workspace, source: Path, text: str, whole: bool) -> List[List[Tuple[Path, bool]]]:
    """(folder, whether the path names its project) for each project folder that a path written in `text` leads
    into and goes on past with a name. A path is read from each start in
    `text` when `whole` is False (a code line, a tag), and from its first
    character when True (a link). It ends at the next `; | & < >`. It is read
    from the folders above the note (`./`, `../`), from the workspace (a path
    from `Zones/` or the workspace's own folder, with or without what is in
    front) or by its last names: a folder anywhere whose names end the same
    way. Nothing in a Garrick checkout counts."""
    idx = project_dir_index(ws)
    text = plain_text(text)
    breaks = [m.start() for m in SHELL_BREAK_RE.finditer(text)]
    root_name, found = ws.root.name, []
    starts = [0] if whole else [m.start() for m in CODE_TOKEN_RE.finditer(text)]
    for start in starts:
        k = bisect_left(breaks, start)
        end = breaks[k] if k < len(breaks) else len(text)
        first = text.find("/", start, min(end, start + DIR_NAME_MAX + 1))
        head = text[start:start + 8].lower()
        if first == -1 and not head.startswith(("file:", "~")):
            continue
        window = text[start:min(end, start + 4096)]
        settled = lexical(window)
        if settled and settled != window:
            # `x/../Harbour/…` is `Harbour/…`; a `..` left in front is read from the note and by its names alone.
            for variant in {settled, settled.lstrip("./") if settled.startswith("../") else settled}:
                found += dir_crossings(ws, source, variant, True)
            continue
        word = window.split(None, 1)[0] if window.strip() else ""
        if "/".join(_strip_md(tuple(x.lower() for x in word.split("/") if x and x != "."))) in SHARED_PROJECT_PATHS:
            continue  # every project holds this one: the file reading says how
        if harness_path(ws, source, word) and text[max(0, start - 1):start] not in tuple("=:&?#%"):
            continue  # `.claude/…` from any project: its own, wherever a tail of it would land (#423)
        tries: List[Tuple[int, Optional[frozenset], str]] = []
        rest = window
        if head.startswith("file:"):
            rest = re.sub(r"(?i)^file:(?://[^/]*)?", "", rest)
            start += len(window) - len(rest)
        if rest.startswith(("/", "~")):
            for m in re.finditer(r"(?<=/)([^/]{1,%d})(?=/|$)" % DIR_NAME_MAX, rest[:4096]):
                name = m.group(1)
                if name == root_name:
                    tries.append((start + m.end() + 1, frozenset({ws.root}), "@"))
                elif name in ("Zones", "Wikis"):
                    tries.append((start + m.start(), frozenset({ws.root}), "@"))
            if rest.startswith("~/"):
                name = rest[2:].split("/", 1)[0]
                if name == root_name:
                    tries.append((start + 2 + len(name) + 1, frozenset({ws.root}), "@"))
            # A site-relative or home-relative path is also read by its names alone, unless it is a path outside the
            # workspace: one from the home folder, or from an operating system's own top folder, with no workspace
            # folder in it. That leads out of the workspace, so a project that ends the same way is none of its business.
            if not (not tries and _outside_workspace(ws, idx, rest)):
                tries.append((start + (2 if rest.startswith("~/") else 1), None, ""))
        elif rest.startswith(("./", "../")):
            base, pos = source.parent, start
            while True:
                part = text[pos:pos + 3]
                if part.startswith("./"):
                    pos += 2
                elif part.startswith("../"):
                    base, pos = base.parent, pos + 3
                else:
                    break
            if base in idx.owner:
                tries.append((pos, frozenset({base}), "@" + str(base)))
        else:
            tries.append((start, None, ""))
        group: List[Tuple[Path, bool]] = []
        for pos, here, ctx in tries:
            reached, count, goes_on = _run(idx, text, pos, end, here, ctx)
            if reached and goes_on:
                for folder in reached:
                    project = idx.owner.get(folder)
                    if project is not None:
                        # It names the project when it is read from a fixed place, or its names reach the project's folder.
                        names = bool(ctx) or count >= len(folder.relative_to(project).parts) + 1
                        if not names and folder.parent == project and folder.name.lower() in LAYOUT_FOLDERS:
                            continue  # `Deliverables/…` from any project: its own folder, made or not yet
                        if not names and folder in idx.hidden:
                            continue  # a copy or a build git ignores: a path that only ends the same way does not lead into it
                        group.append((folder, names))
        if group:
            found.append(group)
    return found


def project_file_tags(ws: Workspace, project: Path, path: Path) -> set:
    """The party tags a file of `project` is written for: its zone's, its hub's, and its
    thread's when it is in one. Read with party_tags, so in staged mode a
    party changed on disk but not in git still counts, as the quote index
    reads it."""
    pfm = next((fm for folder, fm in ws.projects if folder == project), None)
    tags = party_tags(ws, project / (project.name + ".md"), pfm or {})
    if not tags:
        return set()        # a hub that names no party labels nothing under it: never its thread's
    tags |= zone_party(ws, project, tags)
    parts = path.relative_to(project).parts
    if len(parts) > 2 and parts[0] == "Threads":
        tags |= party_tags(ws, project / "Threads" / parts[1] / (parts[1] + ".md"))
    return tags


# Paths every project holds by Garrick's own layout: written by themselves they
# name no project, whoever else holds one.
SHARED_PROJECT_PATHS = ("deliverables/published",)


# What a path under a harness folder may name without naming a subject: the files and folders the harness itself defines.
HARNESS_VOCABULARY = frozenset({"settings.json", "settings.local.json", "skills", "agents", "commands", "hooks",
                                "config.toml", "agents.md", "claude.md", "skill.md", "\u2026"})


def harness_path(ws: Workspace, source: Path, target: str) -> bool:
    """Is `target`, written in the note `source`, a relative path whose first name is a folder every project may
    hold (`.claude/settings.json`, `.agents/skills`), with no `..` in it, and does it mean the note's own? It does
    when every name after the folder is the harness's own vocabulary (HARNESS_VOCABULARY), or when the note's
    project, or the repository the note sits in, has that same path. Any other (`.claude/skills/<a subject>/…`) is
    read as before: a name that is a walled project's is refused. A project's name before the folder, `./`, `../`,
    `/`, `~`, a leading `\\` and any address leave it a path into that project (#423)."""
    if re.match(r"(?i)^[a-z][a-z0-9+.-]*:", target) or target.startswith("\\"):
        return False                  # an address (`obsidian:`, `file:`) is read from a vault or the disk, not the note
    written = unquote(target).replace("\\", "/")
    if written.startswith(("/", "./", "../", "~")):
        return False
    parts = [x for x in written.split("/") if x]
    if not parts or parts[0].lower() not in HARNESS_FOLDERS or any(x in ("..", ".") for x in parts) or "%" in written:
        return False
    if all(x.lower() in HARNESS_VOCABULARY for x in parts[1:]):
        return True
    owner = project_of(ws, source)
    if owner is None:
        return False
    project = owner[0]
    bases = [project]
    for up in source.parents:
        if up == project or project not in up.parents:
            break
        if (up / ".git").exists():
            bases.append(up)
            break
    stem = re.sub(r"(?i)\.md$", "", "/".join(parts))
    return any(_held_by(base, rel) for base in bases for rel in ("/".join(parts), stem, stem + ".md"))


def _held_by(base: Path, rel: str) -> bool:
    """Is `rel` a file or folder of `base` itself: there, with no symbolic link on the way, and with its real path
    inside the real path of `base`? A link that leads into another project is that project's, not `base`'s."""
    here = base
    try:
        for name in rel.split("/"):
            here = here / name
            if here.is_symlink():
                return False
        if not here.exists():
            return False
        real = Path(os.path.realpath(here))
        top = Path(os.path.realpath(base))
        return real == top or top in real.parents
    except (OSError, ValueError):
        return False


def names_project(ws: Workspace, target: str, hit: Path, project: Path) -> bool:
    """Does `target`, a link or a path that lands on `hit`, a file of
    `project`, say which project it means? It does when it is a path from the
    top or from the note, when it reaches the project's folder, when it is
    the project's hub, or when it reaches a thread no other project has a
    thread of the same name for."""
    if target.startswith(("/", "./", "../", "~")):
        return True
    written = target.split(":", 2)[2] if target.startswith("obsidian:") else target
    depth = len([x for x in written.replace("\\", "/").split("/") if x and x != "."])
    rel_parts = hit.relative_to(project).parts
    if depth > len(rel_parts) or (len(rel_parts) == 1 and rel_parts[0].lower() == project.name.lower() + ".md"):
        return True
    if len(rel_parts) >= 3 and rel_parts[0] == "Threads" and (
            depth >= len(rel_parts) - 1 or Path(rel_parts[-1]).stem.lower() == rel_parts[1].lower()):
        if ws.thread_owners is None:
            ws.thread_owners = {}
            for folder, _ in ws.projects:
                for thread in visible_dirs(folder / "Threads"):
                    ws.thread_owners.setdefault(thread.name.lower(), set()).add(folder)
        return ws.thread_owners.get(rel_parts[1].lower()) == {project}
    return False


def vaults_of(ws: Workspace, path: Path) -> List[Path]:
    """Every Obsidian vault a note can be read in: each folder at or above
    it, up to the workspace's top, that holds a `.obsidian` folder. Garrick
    makes none; the user opens the workspace, `Wikis/` or a zone as a vault,
    and may open more than one. With none opened yet, the workspace's top,
    the widest a vault can be."""
    found = []
    for folder in path.parents:
        if (folder / ".obsidian").is_dir():
            found.append(folder)
        if folder == ws.root or ws.root not in folder.parents:
            break
    return found or [ws.root]


def vault_files(ws: Workspace, vault: Path) -> Dict[str, List[str]]:
    """The files Obsidian indexes in a vault, by lower-cased file name, each
    as its path in the vault: everything outside hidden folders, nested
    repositories, Garrick checkouts, `node_modules` and `dist` included, as
    Obsidian does. In staged mode, a file deleted from disk but still in git
    counts too."""
    if vault not in ws.vault_files:
        by_name: Dict[str, List[str]] = {}

        def add(path: Path) -> None:
            try:
                by_name.setdefault(path.name.lower(), []).append(path.relative_to(vault).as_posix())
            except ValueError:
                pass

        for dirpath, dirnames, filenames in os.walk(vault):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if not name.startswith("."):
                    add(Path(dirpath) / name)
        for path in ws.git_view:
            if not path.exists():
                add(path)
        ws.vault_files[vault] = by_name
    return ws.vault_files[vault]


def obsidian_dest(ws: Workspace, vault: Path, source: Path, linkpath: str) -> List[Path]:
    """The file a link opens in `vault`, as Obsidian's own resolution
    (getLinkpathDest) finds it: `./` and `../` from the note's folder; else
    the files of the link's name, lower-cased, with `.md` added when the name
    has no dot; one alone wins; else one whose path in the vault is the link
    exactly; else those whose path ends with the link, as plain text, those
    under the note's folder first, as a plain prefix, then each group by
    length, shortest first. All the files tied for first are returned: which
    of them Obsidian takes is not known, so each counts."""
    linkpath = linkpath.replace("\\", "/")
    if linkpath.startswith(("./", "../")):
        base = Path(os.path.normpath(str(source.parent / linkpath)))
        return [f for f in (base, Path(str(base) + ".md")) if f.is_file() or f in ws.git_view][:1]
    name = linkpath.rsplit("/", 1)[-1].lower()
    if "." in name:
        # As written first, then as a note: `[[Sizing v1.2]]` is `Sizing v1.2.md`.
        return _dest(ws, vault, source, name, linkpath.lower()) or \
            _dest(ws, vault, source, name + ".md", linkpath.lower() + ".md")
    return _dest(ws, vault, source, name + ".md", linkpath.lower() + ".md")


def _dest(ws: Workspace, vault: Path, source: Path, name: str, want: str) -> List[Path]:
    """obsidian_dest's lookup, for one form of the link's name."""
    found = vault_files(ws, vault).get(name, [])
    if len(found) == 1:
        return [vault / found[0]]
    exact = [f for f in found if f.lower() == want.lstrip("/")]
    if exact:
        return [vault / exact[0]]
    found = [f for f in found if f.lower().endswith(want)]
    if not found:
        return []
    try:
        folder = source.parent.relative_to(vault).as_posix()
    except ValueError:
        folder = ""
    folder = "" if folder == "." else folder.lower()
    best = min((not f.lower().startswith(folder), len(f)) for f in found)
    return [vault / f for f in found if (not f.lower().startswith(folder), len(f)) == best]


def path_dests(ws: Workspace, target: str) -> List[Path]:
    """The files a path from the top of the disk, or from the home folder,
    names in the workspace: the path itself when it is inside the workspace,
    else read from where it reaches the workspace's folder, `Zones/` or
    `Wikis/` (_anchored_hits). A few lookups, no index: an export full of
    site-relative links must not hold a commit."""
    path = Path(os.path.normpath(os.path.expanduser(target)))
    forms = [path, Path(str(path) + ".md")]
    root = ws.root.resolve()
    found = []
    for form in forms:
        try:
            inside = form == ws.root or ws.root in form.parents or root in form.resolve().parents
        except (OSError, RuntimeError):
            inside = False
        if inside and (form.is_file() or form in ws.git_view):
            found.append(form)
    if found:
        return found[:1]
    parts = [p for p in path.as_posix().split("/") if p]
    starts = [i + 1 for i, p in enumerate(parts) if p == ws.root.name]
    starts += [i for i, p in enumerate(parts) if p in ("Zones", "Wikis") and i > 0]
    for start in starts:
        base = ws.root.joinpath(*parts[start:]) if start < len(parts) else None
        for form in ([base, Path(str(base) + ".md")] if base else []):
            if form.is_file() or form in ws.git_view:
                found.append(form)
    return found


def hidden_dests(ws: Workspace, source: Path, project: Path, target: str) -> List[Path]:
    """The files in a hidden folder (`.Quay/x`) a link names by its path. Obsidian opens none, but whoever follows
    the path does, so the walls read it: from the note's folder, the project's, its zone's and the workspace's."""
    written = target.split("#")[0].split("|")[0].replace("\\", "/")
    parts = [x for x in written.split("/") if x not in ("", ".")]
    if not parts or ".." in parts or not any(x.startswith(".") for x in parts):
        return []
    out = []
    for base in (source.parent, project, project.parent, ws.root, ws.root / "Zones"):
        for name in (written.lstrip("/"), written.lstrip("/") + ".md"):
            cand = base / name
            try:
                if cand.is_file() and ws.root / "Zones" in cand.parents and cand not in out:
                    out.append(cand)
            except OSError:
                continue
    return out


def link_dests(ws: Workspace, source: Path, target: str) -> List[Path]:
    """Every file a link may open: Obsidian's pick in each vault the note is
    in (obsidian_dest), and, for a path from the top or from outside the
    workspace, the file it names (resolve)."""
    out: List[Path] = []
    if target.startswith("obsidian:"):
        _, _, target = target.split(":", 2)
    if target.startswith(("/", "~")):
        out += path_dests(ws, target)
        target = target.lstrip("/")
    for vault in vaults_of(ws, source):
        out += [d for d in obsidian_dest(ws, vault, source, target) if d not in out]
    return out


# ---------------------------------------------------------------------------
# The tokens that name a Meetings page
# ---------------------------------------------------------------------------
#
# Forms were once matched one at a time: a slash path, a path from `./`, a bare
# name. Each new form found a way past. Now every token, however it is written
# and wherever (a code span, a code line, a link), goes through one function
# that turns it into its plain form (plain_forms), and one resolver answers
# whether the plain form names a page of the Meetings wiki (PageNames.named): by
# its whole path, by any tail of it, or by its name alone. The index holds every
# page of every kind (sources, people, entities, decisions, questions, answers,
# raw records) in every grade (live, dormant/, archive/). A token that names a
# page across a wall is refused whatever its form.

_COMMAND_RE = re.compile(r"^[A-Za-z][\w.+-]*$")
_OPTION_RE = re.compile(r"^(-[\w-]*|\d+)$")
_WRAP = "\"'`<>() \t"       # what may wrap a token; brackets and braces may be a glob's (see _unbracket)
_PUNCT = ".,;:"
_SIGILS = "@!$*#~"
# What may follow a name and is not part of it: a position or a range (`:3`,
# `:3-5`, `:L3`), a section (`::Heading`), a line (`@3`) or a backup's `~`.
_SUFFIX_RE = re.compile(r"(?:::[^/]*|:L?\d+(?:[-:]L?\d+)*:?|@\d+(?:-\d+)?|~|\^[\w-]+)$")
_QUERY_RE = re.compile(r"\?(?=[\w.%-]*=)")
_REPEATS = ((re.compile(r"(?:\./)+"), "./"), (re.compile(r"\A(?:\.\./){2,}"), "../"), (re.compile(r"(?<![:/])/{2,}"), "/"))
_LOOKALIKE = str.maketrans({**{c: "/" for c in "⁄∕⧸╱╲／⼃"},
                            **{c: "." for c in "․‧．。܁܂"},
                            **{c: "-" for c in "‐‑‒–—―−﹘﹣－"}})
_GLOBS = set("*?[")
# `HEAD:` or `host:` in front of a name, but not a position after it (`kai-ross:3`, `:L3`, `:3-5`).
_WORD_PREFIX = r"^[A-Za-z][\w.+-]*:(?!/|L?\d+(?:[-:]L?\d+)*:?$)"
MAX_READ = 4096  # characters of one token read in one go; a longer one is read in bounded parts
# Default_Ignorable_Code_Point, the ones outside the categories dropped by name, and the blank braille cell.
_IGNORABLE = ({0x34f, 0xad, 0x115f, 0x1160, 0x17b4, 0x17b5, 0x3164, 0xffa0, 0x2800}
              | set(range(0x180b, 0x1810)) | set(range(0xfe00, 0xfe10)) | set(range(0xe0100, 0xe01f0))
              | set(range(0x2060, 0x2070)) | set(range(0x200b, 0x2010)))
_COMMENT_RE = re.compile(r"(?s)<!--.*?-->|%%.*?%%")
_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>")
_WORDY = re.compile(r"[A-Za-z]")


def _clean(text: str) -> str:
    """`text` without what a reader does not see: control characters (a tab or
    a line break is a space), format characters, combining marks and every
    default-ignorable character."""
    if text.isascii() and text.isprintable():
        return text
    text = text.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    return "".join(c for c in text if ord(c) not in _IGNORABLE and unicodedata.category(c) not in ("Cc", "Cf", "Mn", "Me"))


_FOLD_SEPARATORS = re.compile(r"[-_\s]+")


@lru_cache(maxsize=1 << 16)
def fold_name(part: str) -> str:
    """A name as the index and a token both fold it: Unicode compatibility and
    case folded, invisible characters gone, lookalike slashes, dots and dashes
    plain, and `-`, `_` and spaces one. Printable ASCII takes a short path with
    the same result: NFKC leaves it as it is, it holds nothing invisible, and
    its case folds as `lower()`."""
    if part.isascii() and part.isprintable():
        text = part.translate(_LOOKALIKE).lower()
    else:
        text = _clean(unicodedata.normalize("NFKC", part)).translate(_LOOKALIKE).casefold()
    return _FOLD_SEPARATORS.sub("-", text)


def _wrapper(c: str) -> bool:
    """May `c` wrap a token at either end? An ASCII quote, backtick, angle bracket
    or parenthesis, a space, or any opening or closing punctuation (a curly
    quote, a guillemet, a corner bracket) but a bracket or a brace, which a glob
    may use."""
    return c in _WRAP or (c not in "[]{}" and unicodedata.category(c) in ("Pi", "Pf", "Ps", "Pe"))


def _strip_wrap(text: str) -> str:
    start, end = 0, len(text)
    while start < end and _wrapper(text[start]):
        start += 1
    while end > start and _wrapper(text[end - 1]):
        end -= 1
    return text[start:end]


def _unbracket(text: str) -> str:
    """`text` without brackets that wrap all of it (`[[x]]`, `[x]`); `[k]ai`
    is a glob's, and stays."""
    m = re.fullmatch(r"\[+([^\[\]]*)\]+", text.strip())
    return _strip_wrap(m.group(1)) if m else text


def render(text: str) -> str:
    """`text` as a reader sees it: HTML entities undone and inline tags gone."""
    if "&" in text or "<" in text or "%%" in text or "~~" in text or "==" in text:
        text = _COMMENT_RE.sub("", html.unescape(text))
        text = _TAG_RE.sub("", text).replace("~~", "").replace("==", "")
    return text


def plain_forms(raw: str) -> List[str]:
    """The plain forms a token may mean (see _plain), folded to compare."""
    return list(_plain(raw, True))


def plain_cased(raw: str) -> List[str]:
    """The same forms, as the token spells them, to look for a file by."""
    return list(_plain(raw, False))


def _dots(raw: str) -> str:
    """`raw`, a path, with its `.` and `..` names settled over the whole of it, in
    one pass: `a/b/../c` is `a/c`. A `..` with nothing before it goes."""
    out: List[str] = []
    for seg in raw.split("/"):
        if seg == ".":
            continue
        if seg == "..":
            if out and out[-1] not in ("", ".."):
                out.pop()
            continue
        out.append(seg)
    return "/".join(out)


def _parts(raw: str) -> List[str]:
    """`raw` in parts of at most MAX_READ characters: itself if short; else its first
    and its last MAX_READ characters, and each stretch between `#`, `?`, `:` and
    white space, those too long cut the same way. No head or tail is dropped."""
    if len(raw) <= MAX_READ:
        return [raw]
    out = [raw[:MAX_READ], raw[-MAX_READ:]]
    settled = _dots(raw) if "/" in raw else raw        # the whole token, `.` and `..` settled, read first
    if settled != raw:
        out += _parts(settled) if len(settled) <= MAX_READ else [settled[:MAX_READ], settled[-MAX_READ:]]
    for piece in re.split(r"[#?:]+", raw)[:5000] + re.split(r"\s+", raw)[:5000]:
        if len(piece) > MAX_READ:
            out += [piece[:MAX_READ], piece[-MAX_READ:]]
        elif piece:
            out.append(piece)
    segs = settled.split("/") if "/" in settled else []
    for i in range(0, min(len(segs), 20000), 4):        # the middle of a long path: windows of eight names
        out.append("/".join(segs[i:i + 8]))
    return list(dict.fromkeys(out))


def _texts(raw: str) -> List[str]:
    """`raw` as the text to read: normalised, and read again with its HTML
    entities undone and its tags gone, if it holds any."""
    for pattern, plain in _REPEATS:
        raw = pattern.sub(plain, raw)
    seen = _parts(raw)
    seen += [render(x) for x in seen if "&" in x or "<" in x or "%%" in x or "~~" in x or "==" in x]
    out = []
    for text in seen:
        text = plain_text(text)
        text = re.sub(r"[ªº]+$", "", text)                 # NFKC would make them letters
        text = _clean(unicodedata.normalize("NFKC", text)).translate(_LOOKALIKE)
        if text not in out:
            out.append(text)
    return out


# Bold round a folder's name. Two or three stars, a name that starts with a letter or digit and holds no glob
# character, and the same stars again. a pattern that starts with `**/`, and `*.md`, are globs and stay so.
EMPHASIS_RE = re.compile(r"(\*{2,3})([A-Za-z0-9][^*?\[\]{}]*/)\1")


@lru_cache(maxsize=1 << 18)
def _plain(raw: str, fold: bool) -> Tuple[str, ...]:
    """Every plain form `raw`, a token as written, may mean as a path: each
    reading of it that is not certain. Its text is normalised (Unicode folded, a
    full-width slash is a slash, invisible characters gone, HTML entities
    undone and tags dropped, a percent escape decoded); then, whichever are
    possible, with a backslash read as `/` or dropped before a mark, with a
    leading `*` kept as a glob or taken off, with trailing marks kept (a glob's
    `*`, `?`) or taken off, and with a `word:` in front (`HEAD:`, `host:`) kept
    or taken off. Each is read by _reading. Bounded: runs of `./` collapse
    first, and only the last 4096 characters are read."""
    out: List[str] = []
    web = re.match(r"(?i)\s*[<(\[\"'`]*https?://", raw) is not None
    if len(raw) <= MAX_READ and not (web and not re.search(r"(?i)/(?:wiki|raw|wikis)/", raw)):   # the name as written first: a page's may hold `#`, `%`, `(`
        said = _strip_wrap(raw.replace("\\", "/"))
        bold = EMPHASIS_RE.fullmatch(said)
        said = bold.group(2) if bold else said        # bold round a folder's name is emphasis, not a glob
        literal = _trim(said, False)
        parts = [x for x in literal.split("/") if x not in ("", ".")]
        if parts:
            out.append("/".join(fold_name(x) for x in parts) if fold else "/".join(parts))
        shown = _SUFFIX_RE.sub("", said.rstrip("/"))
        shown = re.sub(r"(?i)\.(?:md|markdown)$", "", shown)
        raw_parts = [x for x in shown.split("/") if x not in ("", ".")]
        if raw_parts:                                                # and with nothing taken off it (`Delta+`)
            form = "/".join(fold_name(x) for x in raw_parts) if fold else "/".join(raw_parts)
            if form not in out:
                out.append(form)
    for text in _texts(raw):
        stripped = _strip_wrap(text)
        modes = [(bs, star, tail, pref)
                 for bs in ((0, 1) if "\\" in text else (0,))
                 for star in ((0, 1) if stripped.lstrip(_SIGILS.replace("*", "")).startswith("*") else (0,))
                 for tail in ((0, 1) if any(c in stripped for c in "*?]}") else (0,))
                 for pref in ((0, 1) if re.match(_WORD_PREFIX, stripped) else (0,))]
        for mode in modes:
            for form in _reading(text, fold, *mode):
                if form not in out:
                    out.append(form)
    return tuple(out)


def _trim(head: str, keep_glob: bool) -> str:
    """`head` without what trails a name and is not part of it: any mark or symbol
    (a glob's `*`, `?`, `]` and `}` kept when `keep_glob`), a position, `.md`,
    a possessive."""
    for _ in range(8):
        before = head
        end = len(head)
        while end and (head[end - 1] in "/ \t" or (unicodedata.category(head[end - 1])[0] in "PS"
                                                    and not (keep_glob and head[end - 1] in "*?]}"))):
            end -= 1
        head = _SUFFIX_RE.sub("", head[:end])
        head = re.sub(r"['’]s$", "", head)
        if head.lower().endswith(".md"):
            head = head[:-3]
        elif head.lower().endswith(".markdown"):
            head = head[:-9]
        if head == before:
            break
    return head


def _reading(text: str, fold: bool, bs: int, star: int, tail: int, pref: int) -> List[str]:
    """The plain forms one reading gives: quotes and brackets off, `file:`,
    `path:` and a web address's host off, a sigil (`@ ! $ * # ~`) before it
    off, `#heading`, `?query=` and `|alias` off, a leading command and its
    options off, every leading `./` off, `//` read as `/`, a trailing `/` off,
    a position (`:3`, `:3-5`, `:L3`, `@3`, `::Heading`, a trailing `~`) off and
    `.md` off. The token as it stands comes back too: a page's name may hold a
    space (a decision's). With `fold`, each form is lower case and its names
    fold (fold_name); its segments are joined by `/`. A web address names a
    page only by a path with a `wiki`, `raw` or `Wikis` segment."""
    if bs == 0:
        text = re.sub(r"\\([^A-Za-z0-9])", r"\1", text)
    text = text.replace("\\", "/")
    text = _strip_wrap(text)
    text = re.sub(r"^(?:~~|==|%%)+|(?:~~|==|%%)+$", "", text)         # strike, highlight, comment marks
    text = re.sub(r"^(\*{1,3}|_{1,3})(.+)\1$", r"\2", text)       # bold or italic
    text = _unbracket(text)
    text = re.sub(r"(?i)^(?:file|path):(?://[^/]*)?", "", text)
    web = bool(re.match(r"(?i)^https?://", text))
    text = _strip_wrap(re.sub(r"(?i)^[a-z][a-z0-9+.-]*://[^/]*", "", text))
    sigils = _SIGILS.replace("*", "") if star else _SIGILS
    text = text.lstrip(sigils)
    if pref:
        text = re.sub(_WORD_PREFIX, "", text)
    text = _QUERY_RE.split(text, 1)[0]
    for mark in ("#", "|"):
        text = text.split(mark, 1)[0]
    text = _strip_wrap(text)
    if not text:
        return []
    words = text.split()
    heads = [text]
    for i in range(1, min(len(words), 4)):
        if _COMMAND_RE.match(words[0]) and all(_OPTION_RE.match(w) for w in words[1:i]):
            heads.append(" ".join(words[i:]))
    out: List[str] = []
    for head in heads:
        head = _unbracket(_strip_wrap(head)).lstrip(sigils)
        head = _trim(head, bool(tail))
        parts: List[str] = []
        for part in head.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part.strip())
        if web and not {p.lower() for p in parts} & {"wiki", "raw", "wikis"}:
            continue
        for shown in (parts, [_unmark(x) for x in parts]):       # `*x*` is emphasis or a glob: both
            form = "/".join(fold_name(p) for p in shown) if fold else "/".join(shown)
            if form and form not in out:
                out.append(form)
    return out


LINK_ATTRS = {"href", "src", "srcset", "data", "xlink:href", "poster", "background", "action", "cite", "longdesc"}


def _link_like(written: str) -> bool:
    """Is a link, as written, one a reader follows? An attribute of an HTML tag
    that is no address (`id="status"`) is not."""
    m = re.match(r"<[^\s>]+\s+([\w:.-]+)=", written)
    return m is None or m.group(1).lower() in LINK_ATTRS


def _unmark(part: str) -> str:
    """A name without emphasis marks round it (`_kai-ross_`, `~~x~~`, `==x==`,
    `**x**`). A `*` at one end alone is a glob's."""
    lead = re.match(r"(?:\*+|_+|~~|==)", part)
    trail = re.search(r"(?:\*+|_+|~~|==)$", part[lead.end():] if lead else part)
    if lead and lead.group(0).startswith("*") and not trail:
        lead = None
    rest = part[lead.end():] if lead else part
    trail = re.search(r"(?:\*+|_+|~~|==)$", rest)
    if trail and (lead or not trail.group(0).startswith("*")):
        rest = rest[:trail.start()]
    return rest or part


def distinctive(name: str) -> bool:
    """Is a bare name distinctive enough to name a page: does it hold anything
    but letters (a digit, a separator, a `#`)? A plain word (`status`) is not."""
    return not name.isalpha()


def body_tokens(body: str, runs, first_words=frozenset()) -> List[str]:
    """The tokens one code body may hold: all of it, each quoted string, each
    word, and with `runs` each run of up to eight words that starts after a
    command, at a path or at a date (a decision's name has spaces in it). A
    body is read whole however long it is."""
    candidates = [body.strip()]
    candidates += [a or b for a, b in QUOTED_RE.findall(body)]
    shell = body.replace("\\ ", "\0")
    candidates += [t.replace("\0", " ") for t in CODE_TOKEN_RE.findall(shell)]
    if runs:
        for segment in SHELL_BREAK_RE.split(shell.replace("=", " ")):
            for words in ([w.strip("\"'`()").replace("\0", " ") for w in segment.split()],
                          [w.strip("\"'`").replace("\0", " ") for w in segment.split()]):    # and with the brackets kept
                for i in range(len(words)):
                    if i < 4 or "/" in words[i] or (len(words[i]) == 6 and words[i].isdigit()) or (
                            first_words and fold_name(words[i]) in first_words):
                        for j in range(i + 2, min(len(words), i + MAX_RUN_WORDS) + 1):
                            candidates.append(" ".join(words[i:j]))
    return [c for c in dict.fromkeys(candidates) if c]


HTML_CODE_RE = re.compile(r"(?is)<(code|pre)\b[^>]*>(.*?)</\1\s*>|<!--(.*?)-->")


def other_code_texts(text: str, indented: bool = True) -> List[Tuple[str, str]]:
    """(as written, what it holds) for code a reader sees that code_texts does
    not read: an indented code block (four spaces or a tab, each line), HTML
    `<code>` and `<pre>` and a comment (each line)."""
    out = []
    for line in text.split("\n") if indented else ():
        if line[:4] == "    " or line[:1] == "\t":
            if line.strip():
                out.append((line.strip(), line))
    for m in HTML_CODE_RE.finditer(text):
        body = m.group(2) if m.group(2) is not None else m.group(3)
        for line in (body or "").split("\n"):
            if line.strip():
                out.append((line.strip(), line))
    return out


def code_names(text: str, runs: bool = False, first_words=frozenset(), indented: bool = True) -> List[Tuple[str, str]]:
    """(as written, token) for every token that code may hold which may name a
    Meetings page, with or without a slash: in a code span of any length, a
    code line, an indented block, `<code>`, `<pre>` and a comment. One code
    text is read once. With `indented` false (a file of markup or data, which
    has no indented code block) an indented line is not code."""
    out: List[Tuple[str, str]] = []
    done = set()
    for written, body in code_texts(text, None) + other_code_texts(text, indented):
        if (written, body) in done:
            continue
        done.add((written, body))
        out += [(written, c) for c in body_tokens(body, runs, first_words)]
    return out


AUTOLINK_RE = re.compile(r"<([A-Za-z][A-Za-z0-9+.-]*:[^<>\s]*)>")
PROSE_WORD_RE = re.compile(r"[^\s`<>()\[\]\"'|;,{}]+")
PROSE_START_RE = re.compile(r"(?i)(?:^|[^\w])(?:wikis|wiki|raw|meetings|dormant|archive|decisions|questions|answers|sources|people|entities)/")
# A key of a note's own frontmatter says what the note is, not what it names.
OWN_KEYS = {"party", "parties", "zone", "type", "status", "created", "updated", "date", "pinned"}
WIKILINK_ANY_RE = re.compile(r"\[\[((?:[^\[\]\n]|\[[^\[\]\n]*\])+?)\]\]")   # with a glob's [class] in it
BROKEN_DEST_RE = re.compile(r"\]\(\s*([^()<>\n]*\n[^()<>]{0,300}?)\s*\)")


def markdown_targets(text: str) -> List[Tuple[str, str]]:
    """(as written, target) for every Markdown link, by reference too, as it
    stands: a target that opens with something like a scheme (`kai-ross:3`) is
    read as a name with a line suffix, not left as a web address, unless it is
    one (`://`, `mailto:`). An `obsidian://` address is left to uri_targets."""
    out = []
    for regex in (MDLINK_RE, REFDEF_RE):
        for m in regex.finditer(text):
            plain = next((g for g in m.groups() if g is not None), "").strip()
            if "%" in plain and not plain.startswith("#"):          # a name may hold `%`: as written too
                out.append((m.group(0).strip(), plain))
            found = unquote(plain)
            if found and not found.startswith("#") and not re.match(r"(?i)^(?:obsidian://|mailto:|tel:)", found) and (
                    not re.match(r"(?i)^[a-z][a-z0-9+.-]*://", found) or re.match(r"(?i)^https?://", found)):
                out.append((m.group(0).strip(), found))
    for m in BROKEN_DEST_RE.finditer(text):                    # a destination broken over lines
        out.append((m.group(0).strip(), re.sub(r"\s+", "", m.group(1))))
    return out


def uri_targets(text: str) -> List[Tuple[str, str]]:
    """Every `obsidian://` address in the text, as it stands: named reads all
    its query values."""
    return [(u, u) for u in dict.fromkeys(URI_RE.findall(text))]


FM_OPEN_RE = re.compile(r"\A﻿?---[ \t]*\r?\n")
FM_CLOSE_RE = re.compile(r"(?m)^(?:---|\.\.\.)[ \t]*$")
FM_KEY_RE = re.compile(r"""^(?:\?\s*)?(?:"([^"]*)"|'([^']*)'|([^:#"'][^:]*?))\s*:(?:\s+(.*))?$""")
FM_SPLIT_RE = re.compile(r"[\s,;\[\]{}()\"'|>]+")


_YAML_ESC = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "a": "\a", "b": "\b", "e": "\x1b", "f": "\f", "v": "\v",
             "N": "\x85", "_": "\xa0", "L": "\u2028", "P": "\u2029", " ": " ", '"': '"', "/": "/", "\\": "\\"}
YAML_DQ_RE = re.compile(r'"((?:[^"\\]|\\.)*)"', re.S)
YAML_SQ_RE = re.compile(r"'((?:[^']|'')*)'", re.S)


def _yaml_double(m) -> str:
    """A double-quoted YAML scalar as YAML reads it: a line break and the white
    space round it one space, and `\\xNN`, `\\uNNNN`, `\\UNNNNNNNN` and the
    one-letter escapes decoded."""
    body = re.sub(r"\\\n\s*", "", m.group(1))                  # an escaped line break joins the lines
    body = re.sub(r"[ \t]*\n\s*", " ", body)

    def esc(e):
        t = e.group(1)
        if len(t) > 1:
            try:
                return chr(int(t[1:], 16))
            except (ValueError, OverflowError):
                return e.group(0)
        return _YAML_ESC.get(t, t)
    return re.sub(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)", esc, body)


def _yaml_single(m) -> str:
    return re.sub(r"[ \t]*\n\s*", " ", m.group(1).replace("''", "'"))


def frontmatter_names(text: str) -> List[Tuple[str, str]]:
    """(as written, token) for every scalar of a note's frontmatter, at any
    depth and in any shape (a nested map, a list, a flow map, a block scalar,
    a quoted key, a key with a space, an explicit `?` key, JSON): the whole
    value, each quoted string in it, and each of its words, split at `,`, `;`
    and spaces. Only the values of the note's own keys (OWN_KEYS), at the left
    margin, are left out."""
    m = FM_OPEN_RE.match(text)
    if m:
        blocks, body = [], text[m.end():]
        for _ in range(8):                     # a document after the first is read too
            end = FM_CLOSE_RE.search(body)
            blocks.append(body[:end.start()] if end else body[:20000])
            body = body[end.end():].lstrip("\n") if end else ""
            again = FM_OPEN_RE.match(body)
            if not again:
                break
            body = body[again.end():]
        block = "\n".join(blocks)
    elif text.lstrip("﻿ \t\r\n").startswith("{"):
        block = text.lstrip("﻿ \t\r\n")[:20000]
    else:
        return []
    out: List[Tuple[str, str]] = []
    decoded = YAML_SQ_RE.sub(_yaml_single, YAML_DQ_RE.sub(_yaml_double, block)) if ('"' in block or "'" in block) else block
    for variant in dict.fromkeys([block, decoded]):
        out += _frontmatter_lines(variant)
    return list(dict.fromkeys(out))


def _frontmatter_lines(block: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    skipping = False
    for line in block.split("\n")[:2000]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if skipping and (indent > 0 or stripped.startswith("-")):
            continue
        skipping = False
        key = FM_KEY_RE.match(stripped)
        if key:
            name = (key.group(1) or key.group(2) or key.group(3) or "").strip().lower()
            value = (key.group(4) or "").strip()
            if indent == 0 and name in OWN_KEYS:
                skipping = True
                continue
        else:
            value = re.sub(r"^(?:[-?:]\s+)+", "", stripped)
        if key and name not in OWN_KEYS and len(name) <= 200:     # a key may be a page's name
            out.append((name, name))
        pieces = [value] + [a or b for a, b in QUOTED_RE.findall(value)] + re.split(r"[,;{}\[\]()\"'|>]+\s*|:\s+", value) + FM_SPLIT_RE.split(value)
        out += [(p, p) for p in dict.fromkeys(x.strip() for x in pieces) if p]
    return out


def _slashy(word: str) -> bool:
    """Does a word hold a slash, in any form a path is written: `/`, a lookalike,
    `%2F`, `%5C`, or a backslash?"""
    if "/" in word or "\\" in word:
        return True
    if "%" in word and ("/" in unquote(word) or "\\" in unquote(word)):
        return True
    return not word.isascii() and "/" in unicodedata.normalize("NFKC", word).translate(_LOOKALIKE)


def prose_paths(text: str, spaced: bool = False) -> List[Tuple[str, str]]:
    """(as written, word) for every word of the text, anywhere, that holds a
    slash: a path in plain prose. Only one that names a Meetings page by its
    whole path or by a tail of two names or more is refused (PageNames.named
    with `min_parts`), so a bare name in prose stays unread. With `spaced`, a
    word that starts a path into a wiki is also read with the up to eight words
    after it, since a decision's name has spaces in it."""
    text = text[:1 << 22]
    words = PROSE_WORD_RE.findall(text)
    out = [(w, w) for w in dict.fromkeys(words) if _slashy(w)]
    for w in dict.fromkeys(words):             # `harvest-co—the page`, `harvest-co:yes`: each side of a dash or colon
        if _slashy(w) and re.search("[\u2013\u2014:!?]", w) and not re.match(r"(?i)[a-z][a-z0-9+.-]*://", w):
            out += [(w, piece) for piece in re.split("[\u2013\u2014:!?]+", w) if piece and _slashy(piece)]
    if spaced:
        for i, word in enumerate(words):
            if PROSE_START_RE.search(word) or PROSE_START_RE.search(unquote(word)):
                for j in range(i + 2, min(len(words), i + MAX_RUN_WORDS + 1) + 1):
                    run = " ".join(words[i:j])
                    out.append((run, run))
                    if re.search("[\u2013\u2014:!?]", words[j - 1]):
                        out.append((run, " ".join(words[i:j - 1] + [re.split("[\u2013\u2014:!?]+", words[j - 1])[0]])))
    return out


GLOB_FILE_MAX = 5000  # distinct globs one file may hold; a file with more cannot be read


class PageNames:
    """Every page and record of the Meetings wiki, indexed once a run for
    tokens that name one: by the last part of each place it stands at. A page
    is found at its own place and at the places it stands in the other grades
    (grade_places): a token written before it faded or woke still names it.
    Only the names are read to build it; the parties a page is written for
    (`tags_of`) are read when a token names it. `kinds` says what to call a
    page that is no meeting page. Names fold (fold_name)."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        self.kinds: Dict[Path, str] = {}
        self.by_last: Dict[str, List[Tuple[Tuple[str, ...], Path]]] = {}
        self.entries: List[Tuple[Tuple[str, ...], Path]] = []
        self._tags: Dict[Path, set] = {}
        self._globs: Dict[str, List[Path]] = {}
        self.globs_read: set = set()         # the distinct globs this file holds; walls_for_file sets it again
        self._tails: Optional[Dict[int, Dict[str, List[Path]]]] = None
        self._trigrams: Optional[Dict[str, set]] = None
        self._paths: List[str] = []
        self._budget = GLOB_FILE_MAX
        self._full: Optional[Dict[int, Dict[str, List[Path]]]] = None
        self.spaced = False                # does any page's name hold a space? (a decision's does)
        self.first_words: set = set()      # the first word of each such name, folded
        self._raw_tags: Optional[Dict[Path, set]] = None
        self._entities: Optional[Dict[Path, dict]] = None
        for page in ws.meetings:
            self._add(page, None)
        # Every other page of the wiki, in any grade: `.md` in any case, and `.markdown`.
        wiki = ws.root / "Wikis" / "Meetings"
        for here, dirs, files in os.walk(wiki):
            at = Path(here)
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (at / d).is_symlink() and d.lower() != "raw")
            for name in sorted(files):
                page = at / name
                if name.startswith(".") or Path(name).suffix.lower() not in (".md", ".markdown") or page in ws.meetings \
                        or page.is_symlink():
                    continue
                inside = [x.lower() for x in page.relative_to(wiki).parts[:-1]]
                self._add(page, "person page" if "people" in inside else "entity page" if "entities" in inside else "wiki page")
        for paths in raw_records(ws).values():
            for record in paths:
                if record not in ws.meetings:
                    self._add(record, "raw record")

    def _add(self, page: Path, kind: Optional[str]) -> None:
        if kind:
            self.kinds[page] = kind
        for at in [page] + grade_places(self.ws, page):
            have = tuple(Path(rel(self.ws, at)).parts)
            names = [have]
            low = have[-1].lower()
            if low.endswith(".md"):
                names = [have[:-1] + (have[-1][:-3],)]
            elif low.endswith(".markdown"):
                names = [have[:-1] + (have[-1][:-9],)]
            elif "." in have[-1]:
                names.append(have[:-1] + (have[-1].rsplit(".", 1)[0],))
            for name in names:
                # the name as written, folded; and as a token of it is read (punctuation and sigils off)
                lasts = {fold_name(name[-1])}
                read = _reading(_texts(name[-1])[0], True, 0, 0, 0, 0) if name[-1] else []
                if read:
                    lasts.add(read[0].rsplit("/", 1)[-1])
                for last in lasts:
                    full = tuple(fold_name(x) for x in name[:-1]) + (last,)
                    self.by_last.setdefault(full[-1], []).append((full, page))
                    self.entries.append((full, page))
                if " " in page.name:
                    self.spaced = True
                    self.first_words.add(fold_name(page.name.split()[0]))

    def tags_of(self, page: Path) -> set:
        """The parties a page or record is written for; none when it is
        nobody's (a person with no party, an entity page named after none)."""
        if page not in self._tags:
            ws = self.ws
            kind = self.kinds.get(page)
            if kind is None:
                fm = ws.meetings[page]
                tags = {strip_tag(t) for t in as_list(fm.get("parties"))}
            elif kind == "person page":
                fm = parse_frontmatter(page)
                names = [str(fm.get("title") or page.stem), page.stem.replace("-", " ")]
                tags = page_party_tags(ws, fm) | people_parties(ws.context, names)
            elif kind == "wiki page":
                tags = page_party_tags(ws, parse_frontmatter(page))
            elif kind == "entity page":
                tags = self._entity_tags(page)
            else:
                tags = self._record_tags(page)
            self._tags[page] = tags - {"none", ""}
        return self._tags[page]

    def _entity_tags(self, page: Path) -> set:
        ws = self.ws
        if self._entities is None:
            self._entities = {e["path"]: e for e in entity_index(ws)}
        known = self._entities.get(page)
        if known is not None:
            return (set(known["parties"]) | page_party_tags(ws, parse_frontmatter(page))
                    | entity_parties(ws.context, name_group(entity_index(ws), [known["rel"]])))
        fm = parse_frontmatter(page)
        mine = page_party_tags(ws, fm) - {"none"}
        return mine | entity_parties(ws.context, [{"parties": mine, "names": [str(fm.get("title") or page.stem), page.stem]}])

    def _record_tags(self, record: Path) -> set:
        """A raw record is written for the parties of each meeting page that
        claims it."""
        if self._raw_tags is None:
            ws = self.ws
            self._raw_tags = {}
            for page, fm in ws.meetings.items():
                if page not in ws.meeting_questions:
                    mine = {strip_tag(t) for t in as_list(fm.get("parties"))}
                    for found in meeting_raws(ws, page, fm):
                        self._raw_tags.setdefault(found, set()).update(mine)
        return self._raw_tags.get(record, set())

    def _may_match(self, form: str) -> bool:
        """Does the glob `form` match a page? Only a glob that does counts towards GLOB_FILE_MAX, so a file of code,
        full of `*` and `[`, is not refused for them. Every literal stretch of its last name (three letters or more)
        must lie in the path of one page, which a trigram index of the paths tests at once; what survives is matched
        for real (_glob). A glob whose stretches cannot rule it out, or whose class may span names (`entities[/]harvest-co`),
        is matched for real."""
        if "{" in form and ("[" in form or "]" in form):
            return self._matches(form)
        # A brace list is read as a `*`, which is at least as wide. A bracket class that can match a `/` (it holds one,
        # spans one in a range, or is negated) spans names and keeps the glob; any other class matches one character.
        # A `[` never closed and a `]` outside a class are plain characters.
        flat = original = form
        while "{" in flat:
            wider = re.sub(r"\{[^{}]*\}", "*", flat)
            if wider == flat:
                break
            flat = wider
        form, flat, i = flat, "", 0
        while i < len(form):
            if form[i] != "[":
                flat += form[i]
                i += 1
                continue
            j = i + 1
            if form[j:j + 1] in ("!", "^"):
                j += 1
            if form[j:j + 1] == "]":
                j += 1
            end = form.find("]", j)
            if end < 0:
                flat += form[i:]
                break
            body = form[i + 1:end]
            if body[:1] in ("!", "^") or "/" in body or any(
                    body[k] == "-" and body[k - 1] <= "/" <= body[k + 1] for k in range(1, len(body) - 1)):
                return self._matches(original)
            flat += "?"
            i = end + 1
        last = flat.rsplit("/", 1)[-1]
        stretches = [t.lower() for t in re.split(r"[*?]", last) if len(t) >= 3]
        if not stretches:
            return self._matches(original)
        if self._trigrams is None:
            self._paths = ["/".join(have).lower() for have, _ in self.entries]
            self._trigrams = {}
            for i, path in enumerate(self._paths):
                for k in {path[j:j + 3] for j in range(len(path) - 2)}:
                    self._trigrams.setdefault(k, set()).add(i)
        lists = []
        for stretch in stretches:
            for k in {stretch[j:j + 3] for j in range(len(stretch) - 2)}:
                found = self._trigrams.get(k)
                if not found:
                    return False
                lists.append(found)
        lists.sort(key=len)
        near = set(lists[0])
        for more in lists[1:]:
            near &= more
            if not near:
                return False
        if not any(all(t in self._paths[i] for t in stretches) for i in near):
            return False
        return self._matches(original)

    def _matches(self, form: str) -> bool:
        """Does the glob match a page, matched for real? Each such matching of a glob not yet matched is paid from a
        budget of GLOB_FILE_MAX, the work the limit has always allowed; past it a glob counts without being matched."""
        if form in self._globs or self._budget > 0:
            if form not in self._globs:
                self._budget -= 1
            return bool(self._glob(form))
        return True

    def _glob(self, form: str) -> List[Path]:
        """The pages a glob (`kai-*`, `wiki/*/x`, `kai-{ross,x}`, `[kj]ai-r?ss`)
        matches by full path, by tail or by name, fnmatch's way. A glob whose
        own letters, its wildcards and extension left out, number fewer than
        three names every page and so none."""
        if form in self._globs:
            return self._globs[form]
        literal = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", re.sub(r"[*?\[\]{},]", "", form))
        found: Dict[Path, None] = {}
        if sum(c.isalpha() for c in literal) >= 3:
            if self._tails is None:
                self._tails, self._full = {}, {}
                for have, page in self.entries:
                    for n in range(1, len(have) + 1):
                        self._tails.setdefault(n, {}).setdefault("/".join(have[-n:]), []).append(page)
                    self._full.setdefault(len(have), {}).setdefault("/".join(have), []).append(page)
            patterns = [form]
            cut = False
            for _ in range(12):            # the brace lists, expanded exactly while that stays small
                more = [p[:m.start()] + alt + p[m.end():] for p in patterns
                        for m in [re.search(r"\{([^{}]*)\}", p)] if m for alt in m.group(1).split(",")]
                if not more:
                    break
                patterns = more
                if len(patterns) > 512:
                    cut = True
                    break
            if any("{" in p for p in patterns[:512]):
                cut = True
            if cut:                        # cut short: every brace list as a `*` instead, an over-approximation
                wild = form
                for _ in range(12):
                    wild = re.sub(r"\{[^{}]*\}", "*", wild)
                own = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", re.sub(r"[*?\[\]{},]", "", wild))
                patterns = patterns[:512] + ([wild] if sum(c.isalpha() for c in own) >= 3 else [])
            for pattern in patterns:
                cut = pattern.split("/")
                k = len(cut)
                for n in sorted({k} | {n for n in self._full if n < k}):
                    # a page whose whole path is n names long is matched by the last n names of a longer glob
                    pool = (self._tails.get(k) if n == k else self._full.get(n)) or {}
                    want = pattern if n == k else "/".join(cut[-n:])
                    for key in _safe_fnmatch(pool, want):
                        found.update(dict.fromkeys(pool[key]))
        if len(self._globs) > 50000:
            self._globs.clear()
        self._globs[form] = list(found)
        return self._globs[form]

    def named(self, token: str, min_parts: int = 1, bare: bool = True) -> List[Path]:
        """The pages a token names, whatever its form: by name when it is one
        name, or when its last two names are a page's last two. With
        `min_parts`, a token of fewer names than that names none. With `bare`
        false, one name alone names a page only if it is distinctive (see
        distinctive): a single plain word is not read as a page's name."""
        tokens = [token]
        if token.lower().startswith("obsidian://"):
            parts = urlsplit(html.unescape(token))
            tokens = [unquote(v) for q in (parts.query, parts.fragment) for values in parse_qs(q).values() for v in values]
            min_parts, bare = 1, True
        elif token.lower().startswith("obsidian:"):
            rest = token[9:].lstrip("/")
            query = parse_qs(urlsplit("x://x/?" + re.split("[?#]", rest, 1)[1]).query) if re.search("[?#]", rest) else {}
            tokens = [rest] + [unquote(v) for values in query.values() for v in values]
            if token.count(":") >= 2:
                tokens.append(token.split(":", 2)[2])
            min_parts, bare = 1, True
        found: Dict[Path, None] = {}
        explicit = any(re.search(r"(?i)\.(?:md|markdown)(?:[^\w.]|$)", t) for t in tokens)   # `quartz.md` names that file
        for form in [f for t in tokens for f in plain_forms(t)]:
            want = tuple(form.split("/"))
            if len(want) < min_parts:
                continue
            if not (len(want) == 1 and not bare and not explicit and not distinctive(want[0])):
                for have, page in self.by_last.get(want[-1], ()):        # the name itself first, whatever it holds
                    if len(want) == 1 or (len(have) >= 2 and have[-2:] == want[-2:]):
                        found[page] = None
            if _GLOBS & set(form) or "{" in form:
                # A glob with fewer than three letters of its own names no page (see _glob): `*`, `?:` or `[0]` in a
                # stylesheet or a script is code, and it does not count towards the limit.
                if sum(c.isalpha() for c in re.sub(r"\.[A-Za-z0-9]{1,5}$", "", re.sub(r"[*?\[\]{},]", "", form))) < 3:
                    continue
                if not self._may_match(form):
                    continue                   # a run of words from code that holds a `*` or a `[`: it names no page (#422)
                self.globs_read.add(form)
                if len(self.globs_read) <= GLOB_FILE_MAX:
                    found.update(dict.fromkeys(self._glob(form)))
        return list(found)


def page_party_tags(ws: Workspace, fm: dict) -> set:
    """The parties a page's `party:` and `parties:` name, as the Parties table
    knows them: a tag, a party's name in the table (`Birch & Co`), a list in
    brackets or quoted, or `none`. A value that is there and reads as none of
    these is every party's: the page is walled from every project."""
    known = ws.context.get("parties", {})
    names = {}
    for tag, entry in known.items():
        cell = str(entry.get("party") if isinstance(entry, dict) else entry or "")
        names[re.sub(r"[*`]", "", cell).strip().lower()] = tag
    out: set = set()
    for key in ("party", "parties"):
        if key not in fm:
            continue
        for item in (fm[key] if isinstance(fm[key], list) else [fm[key]]):
            text = str(item).strip().strip("\"'").strip()
            pieces = [x.strip().strip("\"'").strip() for x in text[1:-1].split(",")] if text.startswith("[") and text.endswith("]") else [text]
            for piece in pieces:
                if not piece or piece.lower() == "none":
                    continue
                tag = strip_tag(piece)
                tag = tag if tag in known else names.get(piece.lower())
                if tag is None:
                    return set(known) or {"?"}
                out.add(tag)
    return out


def page_names(ws: Workspace) -> PageNames:
    """The index of the Meetings wiki's pages by name, built once a run."""
    if ws.page_names is None:
        ws.page_names = PageNames(ws)
    return ws.page_names


def own_file(ws: Workspace, note: Path, project: Path, token: str) -> bool:
    """Does `token` name a file of the note's own project, read from the note's
    folder, its thread's or the project's? Then it is that file, not a page of
    the Meetings wiki that shares its name."""
    thread = next((p for p in note.parents if p.parent.name == "Threads" and norm_path(project) in map(norm_path, p.parents)), None)
    for form in plain_cased(token):
        for base in (note.parent, thread, project):
            if base is None:
                continue
            for name in (form, form + ".md"):
                try:
                    one = base / name
                    if one.is_file() and not one.is_symlink() and norm_path(Path(os.path.realpath(project))) in map(norm_path, Path(os.path.realpath(one)).parents):
                        if ws.index_files is None or os.path.realpath(one).casefold() in ws.index_files:
                            return True
                except (OSError, ValueError):
                    continue
    return False


def symlink_finding(ws: Workspace, project: Path, ptags: set, path: Path) -> Optional[Finding]:
    """A symbolic link in a project whose target is in the Meetings wiki, or in
    another project walled from this one, file or folder: reading it reads the
    far side, whatever the link is called. None for anything else."""
    if not path.is_symlink():
        return None
    target = Path(os.path.realpath(path))
    wiki = Path(os.path.realpath(ws.root / "Wikis" / "Meetings"))
    tags, where = file_tags(ws, project, ptags, path)
    if norm_path(target) == norm_path(wiki) or norm_path(wiki) in map(norm_path, target.parents):
        return Finding(ERROR, "walls", rel(ws, path),
                       "is a symbolic link into the Meetings wiki, which holds every party's material; link to the page "
                       "by its name instead", "A note in %s is a symbolic link into the Meetings wiki" % where)
    here = Path(os.path.realpath(project))
    for other, _ in ws.projects:
        root = Path(os.path.realpath(other))
        if norm_path(root) == norm_path(here) or not (norm_path(target) == norm_path(root)
                                                      or norm_path(root) in map(norm_path, target.parents)):
            continue
        inside = other.joinpath(*target.parts[len(root.parts):]) if norm_path(target) != norm_path(root) else other / "_"
        far = sorted(blocked(ws.context, tags, project_file_tags(ws, other, inside)))
        if far:
            b = far[0]
            return Finding(ERROR, "walls", rel(ws, path),
                           "is a symbolic link into a project of %s; %s is walled and this project does not name it"
                           % (party_name(ws, b), b), "A note in %s is a symbolic link into a project of %s" % (where, party_name(ws, b)))
    return None


def walls_for_file(ws: Workspace, project: Path, ptags: set, path: Path, text: str) -> List[Finding]:
    """Every walls finding for one project file, whose text is `text`. A path in
    it that the system cannot read (one too long to be a name) is a finding of
    its own, never a crash and never a pass."""
    try:
        return _walls_for_file(ws, project, ptags, path, text)
    except OSError as e:
        return [Finding(ERROR, "walls", rel(ws, path),
                        "holds a path the system cannot read (%s), so the file cannot be checked; shorten it or take it out"
                        % (e.strerror or type(e).__name__), "A note in %s holds a path too long to be read" % project.name)]


def _walls_for_file(ws: Workspace, project: Path, ptags: set, path: Path, text: str) -> List[Finding]:
    """Every walls finding for one project file, whose text is `text`."""
    out: List[Finding] = []
    if ws.meeting_links is None:
        ws.meeting_links = meeting_index(ws)
    meetings = ws.meeting_links
    tags, where = file_tags(ws, project, ptags, path)
    r = rel(ws, path)
    zone = project.parent.name
    reported: set = set()  # walled parties and meetings already named for this file
    unlabelled_hits: set = set()  # linked files with no label already named
    linked = symlink_finding(ws, project, ptags, path)
    if linked is not None:
        out.append(linked)

    # Links, and paths written as code (code_paths), which whoever reads the
    # note follows just the same.
    def exact_file(target: str) -> bool:
        # A slash-ended token with no extension is a file only when a regular
        # file has exactly that path (no `.md` added, no bare name), or when a
        # segment of it names a project's folder (0.56.0's rule, unchanged).
        if target.startswith(("/", "~")):
            try:
                if Path(os.path.expanduser(target)).is_file():
                    return True
            except (OSError, ValueError):
                pass
        parts = [x.lower() for x in target.replace("\\", "/").split("/") if x and x not in (".", "..")]
        named = {project.name.lower() for project, _ in ws.projects}
        for project, _ in ws.projects:
            try:
                named |= {e.name.lower() for e in os.scandir(project / "Threads") if e.is_dir()}
            except OSError:
                pass
        if set(parts) & {"wikis", "wiki", "raw"}:
            return True  # a path into a wiki
        stems = {_strip_md(Path(rel(ws, f)).parts)[-1].lower() for f in ws.wiki_files
                 if "Meetings" in Path(rel(ws, f)).parts[:3]}
        stems |= {page.stem.lower() for page in ws.meetings}
        if parts and parts[-1] in stems:
            return True  # it names a Meetings page, whatever its type or grade
        if set(parts) & named:
            return True  # a segment names a project's or a thread's folder: read as before, never as a bare folder name
        if not parts:
            return False
        if target.startswith(("/", "~")):  # read from where it reaches the workspace, as a path from outside is
            starts = [i + 1 for i, x in enumerate(parts) if x == ws.root.name.lower()]
            starts += [i for i, x in enumerate(parts) if x in ("zones", "wikis") and i > 0]
            tails = [parts[i:] for i in starts if i < len(parts)]
        else:
            tails = [parts]
        project_index(ws)
        known = ws.project_files or {}
        for f in known:
            have = [x.lower() for x in Path(rel(ws, f)).parts]
            if any(have[-len(t):] == t for t in tails if t and len(t) <= len(have)):
                return True
        return False

    targets = [("links", w, t) for w, t in extract_links(text)] + [("writes the path", w, t) for w, t in code_paths(text, exact_file)]
    seen = set()
    # Every token, from a link or from code, with a slash or without, is also
    # read by name (plain_forms, PageNames): whatever its form, one that names a
    # page of the Meetings wiki is read against that page's parties.
    names = page_names(ws)
    names.globs_read = set()
    resolved = set(targets)
    told: set = set()                          # tokens that have a finding
    last, prev = len(out), None
    seen_tokens = set()
    # (verb, as written, token, names at least, whether one bare name will do): a
    # link may be to a bare name; code, frontmatter and prose read one only if
    # it is distinctive.
    named = [(v, w, t, 1, v == "links" and _link_like(w)) for v, w, t in targets]
    named += [("writes the path", w, t, 1, False) for w, t in code_names(text, names.spaced, names.first_words, path.suffix.lower() not in MARKUP_SUFFIXES)]
    shown = render(text)
    for body in dict.fromkeys([text, shown]):
        named += [("links", w, t, 1, True) for w, t in markdown_targets(body)]
        named += [("links", m.group(0), m.group(1), 1, True) for m in WIKILINK_ANY_RE.finditer(body)
                  if not m.group(1).lstrip().startswith("#")]
        named += [("links", "<%s>" % t, t, 1, True) for t in AUTOLINK_RE.findall(body)]
        named += [("links", w, t, 1, True) for w, t in uri_targets(body)]
        named += [("writes the path", w, t, 2, False) for w, t in prose_paths(body, names.spaced)]
    before = {n[1:] for n in named}
    named += [("links", w, t, 1, False) for w, t in frontmatter_names(text)]
    named = [n for n in named if not (n[1:] in seen_tokens or seen_tokens.add(n[1:]))]
    # A spaced display name in a frontmatter value (`Dana Whitlock`) is a name, not a pointer to a person's page: names are
    # tested by the People rule, and a person known on both sides of a wall has no side to take. Its reading with the
    # spaces joined by hyphens only happens to equal a slug. A token written with the slug's own hyphens, a path and a
    # link are read as before, and so is a slug a line fold has split (`kai- ross`).
    fm_bare = {n[1:] for n in named if n[1:] not in before and not re.search(r"[/\\]", n[2]) and re.search(r"\s", n[2])
               and not re.search(r"[-_\u2010-\u2015]\s|\s[-_\u2010-\u2015]", n[2])}
    for verb, written, target, parts, bare in named if names.by_last else []:
        found = list(resolve(ws, path, target, meetings)) if meetings.items and (verb, written, target) in resolved else []
        named_pages = names.named(target, parts, bare)
        if (written, target, parts, bare) in fm_bare:
            named_pages = [p for p in named_pages if names.kinds.get(p) != "person page"]
        if named_pages and not found and own_file(ws, path, project, target):
            continue                           # it is a file of this project, not a page that shares its name
        found += sorted((p for p in named_pages if p not in found),
                        key=lambda p: (p not in ws.meetings, ("person page", "entity page", "wiki page", "raw record").index(names.kinds.get(p, "raw record"))
                                       if p not in ws.meetings else 0))
        for page in found:
            if any(f.severity == ERROR for f in out[last:]):
                told.add(prev)
            last, prev = len(out), written
            key = (written, page)
            if key in seen:
                continue
            seen.add(key)
            if page in reported and (verb, written, target) not in resolved:
                continue                       # a reading of the token the older readings have told already
            if page not in ws.meetings and written in told:
                continue                       # one finding for a token: the first page it names, a record after its page
            mfm = ws.meetings.get(page)
            synthesized = mfm is None
            if mfm is None:                    # a person page, an entity page or a raw record: its parties, in its place
                if not names.tags_of(page):
                    if "raw" in page.relative_to(ws.root).parts[:4] and "Meetings" in page.parts:
                        # a raw record no page cites has no label: nobody's confidence is ever safe to assume
                        reported.add(page)
                        out.append(Finding(ERROR, "walls", r,
                                           "uses %s, a raw record that no page cites, so nothing says whose it is" % page.stem,
                                           "A note in %s uses a raw record with no label" % where))
                    continue                   # nobody's
                mfm = {"parties": sorted(names.tags_of(page)), "zone": zone}
            # labels, not `parties:` alone: a page whose `party:` and `parties:` disagree reads as neither
            label = frozenset(strip_tag(t) for t in as_list(mfm.get("parties"))) if synthesized else meeting_labels(mfm)
            mtags = sorted(label) if label else []
            if not mtags or not mfm.get("zone"):
                reported.add(page)
                noun = meeting_noun(ws, page, "meeting page")
                why = ("frontmatter that is not plain key: value lines, so its parties cannot be read"
                       if page in ws.misread else "no zone or parties")
                out.append(Finding(ERROR, "walls", r,
                                   "uses %s, an unfinished %s (%s)" % (page.stem, noun, why),
                                   "A note in %s uses an unfinished %s" % (where, noun)))
                continue
            if not tags:
                out.append(Finding(ERROR, "walls", r,
                                   "uses %s %s, but the project has no party to check the walls against"
                                   % (meeting_noun(ws, page), page.stem),
                                   "A note in %s uses a %s before the project has a party" % (where, meeting_noun(ws, page))))
                continue
            hits = sorted(blocked(ws.context, tags, mtags))
            if hits:
                b = hits[0]
                reported |= {b, page}
                out.append(Finding(ERROR, "walls", r,
                                   "%s %s, a %s with %s; %s is walled and this project does not name it"
                                   % (verb, written, meeting_noun(ws, page), b, b),
                                   "A note in %s uses a %s with %s" % (where, meeting_noun(ws, page), party_name(ws, b))))
            elif mfm.get("zone") != zone:
                out.append(Finding(WARNING, "walls", r,
                                   "uses %s %s from zone %s; cross-zone work happens only when asked"
                                   % (meeting_noun(ws, page), page.stem, mfm.get("zone")),
                                   "A note in %s uses a %s from the %s zone" % (where, meeting_noun(ws, page), mfm.get("zone"))))

    if len(names.globs_read) > GLOB_FILE_MAX:
        out.append(Finding(ERROR, "walls", r,
                           "holds more than %d distinct globs (`*`, `?`, `[..]`), so it cannot be read; write the names "
                           "out or take the globs out" % GLOB_FILE_MAX, "A note in %s holds too many globs to be read" % where))

    # Links and paths into a project's files, this one's included, whose
    # parties are walled from this file's: a thread of this project may be
    # written for a party walled from this thread's.
    #
    # A link is read as Obsidian reads it, in the vault the note is in
    # (obsidian_dest): when the file it opens is across a wall, it is
    # refused. A path written as code is followed by a reader, not by
    # Obsidian: one that lands in this project means it; one that lands on a
    # single file, or only on files across a wall, or that names the far
    # project, is refused; one that lands across a wall and also on a wiki
    # page or a project with no wall, a path every project may hold such as
    # `Deliverables/published.md`, is a warning.
    # Folders: a path that leads into a folder of a project across a wall and
    # goes on past it with a name is refused, whatever the name, since a name
    # that cannot be read plainly (a `;`, a space, a glob, a `%20`, a long run of
    # words) cannot be told from a file there. A path that ends at the folder
    # is a path to a folder, which is not read.
    folders = [("writes the path", w, b, False) for w, b in code_texts(text) if "/" in b or "file:" in b.lower()]
    folders += [("links", w, b, False) for w, b in tag_texts(text) if "/" in b or "file:" in b.lower()]
    folders += [("links", w, t, True) for w, t in extract_links(text) if not w.startswith("[[")]
    if tags and (targets or folders):
        index = project_index(ws)
        named: Dict[Tuple[str, Path], int] = {}  # (written, project) -> its finding's place in out

        def record(severity: str, verb: str, written: str, what: str, ear: str, b: str, other: Path) -> None:
            # One finding for each (written, project), the worst of its readings:
            # a warning never stands in for the refusal of another.
            key = ("<tag>" if written.startswith("<") else written, other)  # a tag is one finding, however it was read
            earlier = named.get(key)
            if earlier is not None and (severity == WARNING or out[earlier].severity == ERROR):
                return
            if severity == ERROR:
                reported.add(b)  # a warning must not stand in for the name check's refusal
            found = Finding(severity, "walls", r, "%s %s%s; %s is walled and this project does not name it" % (verb, written, what, b),
                            "A note in %s uses %s" % (where, ear))
            if earlier is None:
                named[key] = len(out)
                out.append(found)
            else:
                out[earlier] = found

        for verb, written, target in targets:
            if harness_path(ws, path, target):
                continue  # `.claude/settings.json` from any project: its own, made or not yet (#423)
            code = verb != "links"
            hits = resolve(ws, path, target, index) if code else link_dests(ws, path, target)
            if not code:
                hits = hits + [h for h in hidden_dests(ws, path, project, target) if h not in hits]
            far_hits, near = [], []
            for hit in hits:
                owner = project_of(ws, hit)
                if ((owner is None or owner[0] != project) and (ws.root / "Zones" in hit.parents
                                                                 or ws.root / "Wikis" / "Knowledge" in hit.parents)
                        and unlabelled_target(ws, owner, hit)) \
                        or (owner is not None and owner[0] == project and notes_disagree(ws, project, hit)):
                    # a file of the zones with no label (a zone's own file, a folder of dots, a project that names no
                    # party): nothing says whose it is, so no project may link or embed it
                    if hit not in unlabelled_hits:
                        unlabelled_hits.add(hit)
                        out.append(Finding(ERROR, "walls", r,
                                           "%s %s, a file that names no party, so nothing says whose it is"
                                           % (verb, written),
                                           "A note in %s uses a file with no label" % where))
                    continue
                if owner is None:
                    continue  # not a project's: a wiki page or System's, which the meeting check reads
                other = owner[0]
                pair = sorted(blocked(ws.context, tags, project_file_tags(ws, other, hit)))
                if pair:
                    far_hits.append((hit, other, pair[0]))
                else:
                    near.append((hit, other))
            if not far_hits:
                continue
            severity = ERROR
            if code:
                if any(o == project for _, o in near):
                    continue  # it means a file of this project
                if ws.wiki_links is None:
                    ws.wiki_links = PathIndex(ws, ws.wiki_files)
                elsewhere = bool(near) or bool(resolve(ws, path, target, ws.wiki_links)) or \
                    "/".join(_strip_md(tuple(x.lower() for x in target.replace("\\", "/").split("/") if x and x != "."))) in SHARED_PROJECT_PATHS
                if elsewhere and not any(names_project(ws, target, h, o) for h, o, _ in far_hits):
                    severity = WARNING
            hit, other, b = far_hits[0]
            noun = "note" if hit.suffix.lower() == ".md" else "file"
            record(severity, verb, written, ", a %s of %s" % (noun, b), "a %s of %s" % (noun, party_name(ws, b)), b, other)
        # The folder reading: the backstop for what the readings above could not tell.
        for verb, written, body, whole in folders:
            for group in dir_crossings(ws, path, body, whole):
                far_dirs: Dict[Path, tuple] = {}
                elsewhere = own = False
                for folder, names in group:
                    other = project_dir_index(ws).owner.get(folder)
                    if other is None:
                        continue
                    pair = sorted(blocked(ws.context, tags, project_file_tags(ws, other, folder / "_")))
                    if pair:
                        prev = far_dirs.get(other)
                        far_dirs[other] = (pair[0], names or (prev[1] if prev else False))
                    elif other == project:
                        own = True
                    else:
                        elsewhere = True
                if own:
                    continue  # it means a folder of this project
                for other, (b, names) in far_dirs.items():
                    record(WARNING if elsewhere and not names else ERROR, verb, written,
                           ", a path that leads into a project of %s" % b, "a path into a project of %s" % party_name(ws, b),
                           b, other)
    far = {t for t in ws.context["parties"] if tags and decide(tags, {t}, "write", ws.context) == "deny"}

    # Names. Sources/ holds what a party sent, which may name anyone; it is exempt.
    in_sources = "Sources" in Path(rel(ws, path)).parts[3:-1]
    if far and not in_sources:
        scanned = fold_format(without_party_field(text)) + "\n" + path.name
        padded = padded_words(scanned)
        for b, forms in name_forms(ws, far).items():
            if b in reported or not forms:
                continue
            hit = name_hit(scanned, forms, padded)
            if hit is None:
                continue
            reported.add(b)
            out.append(Finding(ERROR, "walls", r,
                               "names %s%s, or one of its people; %s is walled and this project does not name it"
                               % (party_name(ws, b), as_tag(ws, b, hit), b),
                               "A note in %s names %s" % (where, party_name(ws, b))))

    # Quotes: a run of words held only across a wall, by a meeting page or its
    # raw record or by another project's file, or held by an unfinished page.
    # Wording also held on the near side of the wall, by a meeting or a file
    # of another project, or by this project's own Sources/, is not evidence of
    # a leak, and nor is wording found in one of the shared files every side
    # reads. This project's own notes are neither: a leak copied twice must
    # not vouch for itself. A note of a thread of this project written for a
    # party walled from this file's is the far side, as another project's is. A file in Sources/ is what a party sent, which may
    # repeat what another party sent too: like the name check, the file check
    # leaves it out, and only meetings count against it.
    if ws.quick:
        return out  # --quick leaves the wording to the full check and the commit hook
    index = quote_index(ws)
    sent = _in_sources(project, path)
    lifted: Dict[Path, int] = {}
    unfinished: Dict[Path, int] = {}
    copied: Dict[Path, set] = {}  # another project -> its files the wording came from
    crossed_by_page: Dict[Path, bool] = {}      # whether this file's tags are walled from a page's, worked out once a file

    def crossed(o: Path) -> bool:
        got = crossed_by_page.get(o)
        if got is None:
            got = crossed_by_page[o] = bool(blocked(ws.context, tags, index.tags.get(o, ())))
        return got

    for h in runs(transcript_text(path, text), shared_link(ws, path)):
        owners = index.owners.get(h)
        if not owners or h in index.common:
            continue
        pages, open_pages, files = [], [], []
        clear = False
        for o in owners:
            if o == path:
                continue
            mfm = ws.meetings.get(o)
            if mfm is not None:
                if not finished(mfm):
                    open_pages.append(o)
                elif blocked(ws.context, tags, [strip_tag(m) for m in as_list(mfm.get("parties"))]):
                    pages.append(o)
                elif o in ws.meeting_questions:
                    continue  # a question restates a record, and is not one: it can show a leak, never vouch for one
                else:
                    clear = True
                    break
            elif sent or (index.project.get(o) == project and not _in_sources(project, o)
                          and not crossed(o)):
                continue  # this project's own note, written for no party walled from this file's
            elif crossed(o):
                files.append(o)
            else:
                clear = True
                break
        if clear:
            continue
        for o in pages:
            lifted[o] = lifted.get(o, 0) + 1
        for o in open_pages:
            unfinished[o] = unfinished.get(o, 0) + 1
        if not pages and not open_pages:  # a meeting holds it too: that is the one to name
            for o in files:
                copied.setdefault(index.project[o], set()).add(o)
    for page in sorted(lifted):
        if page in reported:
            continue
        mtags = [strip_tag(m) for m in as_list(ws.meetings[page].get("parties"))]
        b = sorted(blocked(ws.context, tags, mtags))[0]
        noun = meeting_noun(ws, page)
        out.append(Finding(ERROR, "walls", r,
                           "repeats wording from %s %s, a %s with %s; %s is walled and this project does not name it"
                           % (noun, page.stem, noun, b, b),
                           "A note in %s quotes a %s with %s" % (where, noun, party_name(ws, b))))
    for page in sorted(unfinished):
        if page in reported:
            continue
        noun = meeting_noun(ws, page, "meeting page")
        out.append(Finding(ERROR, "walls", r,
                           "repeats wording from %s, an unfinished %s (no zone or parties)" % (page.stem, noun),
                           "A note in %s quotes an unfinished %s" % (where, noun)))
    for other in sorted(copied):
        sources = sorted(copied[other])
        b = sorted(blocked(ws.context, tags, index.tags[sources[0]]))[0]
        more = " and %d more of its files" % (len(sources) - 1) if len(sources) > 1 else ""
        out.append(Finding(ERROR, "walls", r,
                           "repeats wording from %s%s, in project %s for %s; %s is walled and this project does not name it"
                           % (rel(ws, sources[0]), more, other.name, b, b),
                           "A note in %s quotes a file of %s" % (where, party_name(ws, b))))
    return out


def norm_path(path: Path) -> str:
    """A path as one spelling: Unicode form NFC and case folded, so a folder made in NFD by Finder, a name git
    stages in NFC and a folder renamed in case only (`core.ignorecase`) are the same project (#398)."""
    return unicodedata.normalize("NFC", str(path)).casefold()


def project_of(ws: Workspace, path: Path) -> Optional[Tuple[Path, dict]]:
    """The project a path is in, found by its normalised spelling, whichever way the path was written."""
    index = ws.project_norm
    if index is None or index[0] != len(ws.projects):
        index = ws.project_norm = (len(ws.projects), {norm_path(p): (p, fm) for p, fm in ws.projects})
    for parent in path.parents:
        hit = index[1].get(norm_path(parent))
        if hit is not None:
            return hit
    return None


def canonical_path(ws: Workspace, path: Path) -> Path:
    """`path` with the spelling of its project's folder as the disk has it, so that relative_to() and every
    comparison on the project's files agree with a path git staged in another case or Unicode form."""
    index = ws.project_norm
    project_of(ws, path)
    index = ws.project_norm
    for parent in path.parents:
        hit = index[1].get(norm_path(parent))
        if hit is not None:
            return hit[0].joinpath(*path.parts[len(parent.parts):])
    return path


# ---------------------------------------------------------------------------
# Mail behind a project's sources
#
# Mail is recorded in Meetings, where the walls can read its parties; what goes
# into a project's Sources/ is an attachment. A file in Sources/ with the same
# bytes as an attachment came from that mail, so the mail must be filed with a
# finished page, and its parties must not be walled from the project's. The
# same holds for a whole mail saved into Sources/, unless intake saved it there
# as material: then its parties are in its own X-Garrick-Parties header.
# ---------------------------------------------------------------------------

MIN_ATTACHMENT_BYTES = 32  # below this, identical bytes prove nothing
MAX_SOURCE_BYTES = 50_000_000


@dataclass
class MailRecord:
    path: Path  # the saved message
    page: Optional[Path]  # its Meetings page; None while it waits in an inbox or has none


def _digest(data: bytes) -> Tuple[int, str]:
    return len(data), hashlib.sha256(data).hexdigest()


def mail_index(ws: Workspace) -> Dict[Tuple[str, int, str], List[MailRecord]]:
    """("mail" or "attachment", size, sha256) -> the mails it belongs to: every
    .eml in the Meetings raw records, and every one waiting in a zone Inbox."""
    if ws.mail_index is not None:
        return ws.mail_index
    owner: Dict[Path, List[Path]] = {}
    for page, fm in ws.meetings.items():
        for raw in meeting_raws(ws, page, fm):
            owner.setdefault(raw, []).append(page)
    # A mail split into a page per project is a record per page: what each
    # page's project may take from it is read with that page's parties.
    records: List[MailRecord] = []
    records += [MailRecord(p, page) for paths in raw_records(ws).values() for p in paths
                if p.suffix.lower() == ".eml" and p.is_file() for page in sorted(owner.get(p) or [None], key=str)]
    for inbox in [zone / INBOX for zone in ws.zones] + [ws.root / INBOX]:
        if inbox.is_dir():
            records += [MailRecord(p, None) for p in sorted(inbox.iterdir())
                        if p.is_file() and p.suffix.lower() == ".eml"]
    index: Dict[Tuple[str, int, str], List[MailRecord]] = {}
    for rec in records:
        try:
            data = rec.path.read_bytes()
            parts = mail_attachments(data)
        except Exception:  # an unreadable message has nothing to match
            continue
        index.setdefault(("mail",) + _digest(data), []).append(rec)
        for _, _, payload in parts:
            if len(payload) >= MIN_ATTACHMENT_BYTES:
                index.setdefault(("attachment",) + _digest(payload), []).append(rec)
    ws.mail_index = index
    return index


def _finished(ws: Workspace, rec: MailRecord) -> bool:
    fm = ws.meetings.get(rec.page, {}) if rec.page else {}
    return bool(fm.get("zone")) and bool(as_list(fm.get("parties")))


def sources_for_file(ws: Workspace, project: Path, ptags: set, path: Path, data: bytes) -> List[Finding]:
    """Findings for one file in a project's Sources/, from its bytes."""
    is_mail = path.suffix.lower() == ".eml"
    ptags = set(ptags) | zone_party(ws, project, ptags)
    if not is_mail and len(data) < MIN_ATTACHMENT_BYTES:
        return []
    stamped = stamped_parties(data) if is_mail else []
    if stamped:  # saved as material: no Meetings page, its parties in the mail
        r = rel(ws, path)
        if not ptags:
            return [Finding(ERROR, "walls", r,
                            "is a mail saved as material, but the project has no party to check the walls against",
                            "A file in %s is a mail, before the project has a party" % project.name)]
        carried, _ = mail_labels(ws.context, data)      # the header's tags and its addresses' parties together
        if carried is None:
            return [Finding(ERROR, "walls", r,
                            "is a mail saved as material, but its `X-Garrick-Parties` header names `none` or "
                            "a party the Parties table lacks, so the walls cannot be checked",
                            "A file in %s is a mail with a party header no wall can read" % project.name)]
        if decide(ptags, carried, "file", ws.context) == "confirm":
            return [Finding(ERROR, "walls", r,
                            "is a mail saved as material from a party that is always asked about; it is not filed until "
                            "the user has answered, and a commit does not answer",
                            "A file in %s is a mail that needs an answer first" % project.name)]
        hits = sorted(blocked(ws.context, ptags, carried))
        if hits:
            b = hits[0]
            return [Finding(ERROR, "walls", r,
                            "is a mail saved as material for %s; %s is walled and this project does not name it" % (b, b),
                            "A file in %s is a mail with %s" % (project.name, party_name(ws, b)))]
        return []
    recs = mail_index(ws).get(("mail" if is_mail else "attachment",) + _digest(data), [])
    if is_mail:
        recs = [r for r in recs if r.page is not None or r.path.parent.name != INBOX]
    elif not recs:
        return []
    r = rel(ws, path)
    what = "a mail" if is_mail else "an attachment of a mail"
    filed = [rec for rec in recs if _finished(ws, rec)]
    if not filed:
        return [Finding(ERROR, "sources", r,
                        "is %s that has no finished page in Meetings; file the mail as a conversation first, so the "
                        "walls can see its parties" % what,
                        "A file in %s's sources came from mail that is not filed" % project.name)]
    if not ptags:
        return [Finding(ERROR, "walls", r,
                        "came from mail %s, but the project has no party to check the walls against" % filed[0].page.stem,
                        "A file in %s came from mail before the project has a party" % project.name)]
    hits = []
    for rec in filed:
        mtags = [strip_tag(t) for t in as_list(ws.meetings[rec.page].get("parties"))]
        hits.append(sorted(blocked(ws.context, ptags, mtags)))
    if all(hits):  # every mail it could have come from has a walled party the project does not name
        b = hits[0][0]
        return [Finding(ERROR, "walls", r,
                        "came from mail %s, a mail with %s; %s is walled and this project does not name it" % (filed[0].page.stem, b, b),
                        "A file in %s came from a mail with %s" % (project.name, party_name(ws, b)))]
    zone = project.parent.name
    if all(ws.meetings[rec.page].get("zone") != zone for rec in filed):
        mzone = ws.meetings[filed[0].page].get("zone")
        return [Finding(WARNING, "walls", r, "came from mail filed in zone %s; cross-zone work happens only when asked" % mzone,
                        "A file in %s came from a mail in the %s zone" % (project.name, mzone))]
    return []


def _in_sources(project: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(project).parts
    except ValueError:
        return False
    return len(parts) >= 2 and parts[0] == "Sources" and not parts[-1].startswith(".")


def all_sources_findings(ws: Workspace) -> List[Finding]:
    if ws.source_findings is None:
        out: List[Finding] = []
        for project, pfm in ws.projects:
            ptags = {strip_tag(t) for t in as_list(pfm.get("party"))}
            if in_system(ws, project) and not ptags:
                continue                   # System/ is no zone: a project there has no party, and no hook guards it
            for path in walk_files(project / "Sources", set_apart(ws)):
                try:
                    if not _in_sources(project, path) or path.stat().st_size > MAX_SOURCE_BYTES:
                        continue
                    data = path.read_bytes()
                except OSError:
                    continue
                out.extend(sources_for_file(ws, project, ptags, path, data))
        ws.source_findings = out
    return ws.source_findings


def check_sources(ws: Workspace) -> List[Finding]:
    """Nothing in a project's Sources/ came from mail that skipped Meetings."""
    return [f for f in all_sources_findings(ws) if f.check == "sources"]


def check_walls(ws: Workspace) -> List[Finding]:
    """No project file links to, names, or quotes a party or meeting on the far
    side of a wall from the project's party, or came from a mail that is.
    Files git ignores are left out: they never reach the history the commit
    hook guards, and an installed package's files are not the project's. So
    is a Garrick checkout kept in the project (set_apart)."""
    out = []
    for project, pfm in ws.projects:
        ptags = {strip_tag(t) for t in as_list(pfm.get("party"))}
        if in_system(ws, project) and not ptags:
            continue                       # System/ is no zone: a project there has no party, and no hook guards it
        for path in walk_files(project, set_apart(ws)):
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = read_text(path)
            if text:
                out.extend(walls_for_file(ws, project, ptags, path, text))
            elif path.is_symlink() and (found := symlink_finding(ws, project, ptags, path)) is not None:
                out.append(found)
        for here, dirs, _ in os.walk(project):
            out.extend(f for f in (symlink_finding(ws, project, ptags, Path(here) / d) for d in sorted(dirs)
                                   if d not in SKIP_DIRS) if f is not None)
    out.extend(f for f in all_sources_findings(ws) if f.check == "walls")
    out.extend(person_link_finding(ws, p) for p in person_links(ws))
    out.extend(organisation_walls(ws, person_pages(ws)))
    out.extend(form_findings(ws, [(p, None) for p in form_candidates(ws)]))
    out.extend(nested_repositories(ws))
    return out


def nested_repositories(ws: Workspace) -> List[Finding]:
    """A `.git` anywhere under Wikis/ that is not a wiki's own: a submodule or a
    clone whose pages the hook of the wiki does not read (#340)."""
    wikis = ws.root / "Wikis"
    if not wikis.is_dir():
        return []
    own = {wikis / ".git"} | {wikis / d.name / ".git" for d in visible_dirs(wikis)}
    out = []
    for here, dirs, files in os.walk(str(wikis)):
        for name in sorted(set(dirs) | set(files)):
            if name == ".git" and Path(here, name) not in own:
                out.append(Finding(WARNING, "walls", rel(ws, Path(here)),
                                   "holds a .git that is not a wiki's own, a submodule or a clone, so its pages are "
                                   "in no history the wall check reads", "A repository sits inside a wiki"))
        dirs[:] = sorted(d for d in dirs if d != ".git")
    return out


def form_scope(ws: Workspace, path: Path) -> Optional[Tuple[str, ...]]:
    """Which keys of a page's frontmatter the walls read, for
    frontmatter_form_problem(): () for every key on an entity page, a meeting
    page at any grade, a Meetings question, a project hub and a thread note;
    WALLS_KEYS on any other page of the two wikis, where only a party or a
    zone counts (a Knowledge page must carry none, and a Meetings page
    written for a party cites no meeting across a wall); None where the walls
    read no frontmatter: a raw record, a person page, which has its own
    shape (person_shape_problem), and any other file."""
    if path.suffix.lower() != ".md":
        return None
    here = path.parent.resolve() / path.name
    if any(under_folder(ws, here, f) for f in PEOPLE_FOLDERS):
        return None
    meetings = lexical_folder(ws, ("Wikis", "Meetings"))
    for wiki in (meetings, lexical_folder(ws, ("Wikis", "Knowledge"))):
        if not under_folder(ws, here, ("Wikis", wiki.name)):
            continue
        inner = _fold_parts(here.parts)[len(wiki.parts):]
        if wiki == meetings and inner[:2] == WIKI_ANSWERS:
            return ()                       # a raw answer is read by the walls as its question is (#224)
        faded = wiki == meetings and inner[:1] and inner[0] in FADED
        if wiki == meetings and (inner[:2] == WIKI_DECISIONS or (faded and inner[1:3] == WIKI_DECISIONS)):
            return ()                       # so is a decision page, which carries its question's zone and parties
        if faded and inner[1:3] == WIKI_ANSWERS:
            return ()                       # and a raw answer that faded with it
        if "raw" in inner[:-1]:
            return None
        if wiki == meetings and (inner[0] == WIKI_QUESTIONS or inner[:2] in (("wiki", "entities"), ("wiki", "sources"))
                                 or (inner[0] in FADED and inner[1:3] in (("wiki", "sources"), ("wiki", "entities")))):
            return ()
        return WALLS_KEYS
    owner = project_of(ws, here) or project_of(ws, path)
    if owner is None:
        return None
    project = owner[0].parent.resolve() / owner[0].name
    hub = here == project / (project.name + ".md")
    thread = here.parent.parent == project / "Threads" and here.name == here.parent.name + ".md"
    return () if hub or thread else None


def form_candidates(ws: Workspace) -> List[Path]:
    """Every page whose frontmatter the full walls check reads for its form:
    the wiki pages, the meeting pages and questions, and each project's hub
    and thread notes."""
    pages = set(ws.wiki_files) | {p for p in ws.meetings if p.exists()}
    for project, _ in ws.projects:
        pages.add(project / (project.name + ".md"))
        pages.update(t / (t.name + ".md") for t in visible_dirs(project / "Threads"))
    return sorted(p for p in pages if p.is_file())


def form_findings(ws: Workspace, pages: List[Tuple[Path, Optional[str]]]) -> List[Finding]:
    """A page the walls read (form_scope) whose frontmatter can be read two
    ways (garrick_lib's frontmatter_form_problem): a key quoted, tagged,
    written with `?`, anchored, aliased, merged or in a flow, or given twice;
    a value opening a block, a tag, an anchor, an alias, or a list or quote
    not closed on its line; an indented line YAML reads as more of a value;
    or a frontmatter no plain `---` line closes. YAML honours each, so the
    page could say one party to the walls and another to every other
    reader. Or one whose party or zone the walls do not know
    (walls_value_problem). Refused, by the full check and the commit hook
    (#330). Each is (path, its text, or None to read it from disk)."""
    out = []
    for path, text in pages:
        scope = form_scope(ws, path)
        if scope is None:
            continue
        keys = scope or None
        problem = frontmatter_form_problem(text, keys) if text is not None else note_form(ws, path, keys)
        if problem:
            out.append(Finding(ERROR, "walls", rel(ws, path),
                               "%s: %s; write each key once, at the left margin, as `key: value`"
                               % (FRONTMATTER_PLAIN, problem), "A page's frontmatter can be read two ways"))
            continue
        fm = parse_frontmatter_text(text) if text is not None else note_frontmatter(ws, path)
        owner = project_of(ws, path)
        problem = walls_value_problem(ws, fm, owner is not None, owner is not None and path.stem == path.parent.name)
        if problem:
            out.append(Finding(ERROR, "walls", rel(ws, path),
                               "%s: %s; until it does, the walls read nothing on it as safe to use"
                               % (WALLS_VALUE, problem), "A page names a party or zone the walls do not know"))
        elif owner is not None and path.stem == path.parent.name and fm.get("parties") is not None:
            out.append(Finding(ERROR, "walls", rel(ws, path),
                               "a hub or thread note says whose it is with `party:` alone; rename `parties:` to `party:` "
                               "(a list is fine: `party: [acme, cedar]`)",
                               "A hub or thread note carries parties: instead of party:"))
    return out


# The folder names the walls match a wiki's paths by. On a case-insensitive disk
# git keeps the case typed for a folder it does not yet track, so
# `Meetings/Wiki/People/pat.md` is the page `wiki/people/pat.md` to every reader
# but a comparison by exact case. In a wiki repository each folder of a staged
# path that is one of these names in any case is read as the name itself (#340).
WIKI_FOLDER_NAMES = {n.casefold(): n for n in (
    "Wikis", "Meetings", "Knowledge", "wiki", "raw", "inbox", "dormant", "archive", "people", "entities",
    "sources", "questions", "concepts", "lint")}
_WIKI_REPO = False


def wiki_case(name: str) -> str:
    """`name`, a path inside a wiki repository, with each folder that is one of
    WIKI_FOLDER_NAMES in any case or Unicode form spelt as the name; the file
    itself is left as it is. Only where the repository being checked is a
    wiki."""
    if not _WIKI_REPO:
        return name
    parts = name.split("/")
    return "/".join([WIKI_FOLDER_NAMES.get(unicodedata.normalize("NFC", x).casefold(), x) for x in parts[:-1]]
                    + parts[-1:])


def _staged_raw(repo: Path) -> Optional[Tuple[Path, List[str]]]:
    top = _git(["rev-parse", "--show-toplevel"], repo)
    if top is None:
        return None
    top_path = Path(top.strip()).resolve()
    names = _git(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"], top_path)
    if names is None:
        return None
    return top_path, [n for n in names.split("\0") if n]


def staged_names(repo: Path) -> Optional[Tuple[Path, List[str]]]:
    """(top of the repository holding `repo`, every path added, copied, modified
    or renamed in its index, as the walls read it: wiki_case). None when it is
    not a repository."""
    raw = _staged_raw(repo)
    return None if raw is None else (raw[0], [wiki_case(n) for n in raw[1]])


def staged_gitlinks(repo: Path) -> List[str]:
    """Every path the index of the repository holding `repo` holds as a
    gitlink (mode 160000), a submodule: its pages are another repository's,
    which no hook of this one reads (#340)."""
    top = _git(["rev-parse", "--show-toplevel"], repo)
    if top is None:
        return []
    listing = _git(["ls-files", "--stage", "-z"], Path(top.strip()).resolve()) or ""
    return [e.split("\t", 1)[1] for e in listing.split("\0") if e.startswith("160000 ") and "\t" in e]


def staged_removed(repo: Path) -> frozenset:
    """The paths the index deletes in the repository holding `repo`, a
    rename's old path among them: pages the commit no longer holds (#340)."""
    top = _git(["rev-parse", "--show-toplevel"], repo)
    if top is None:
        return frozenset()
    top_path = Path(top.strip()).resolve()
    names = _git(["diff", "--cached", "--name-only", "-z", "--no-renames", "--diff-filter=D"], top_path)
    return frozenset(top_path / wiki_case(n) for n in (names or "").split("\0") if n)


def staged_links(repo: Path) -> Optional[Tuple[Path, set]]:
    """(top of the repository holding `repo`, the paths added, copied,
    modified, renamed or changed in type in its index that git holds as
    symbolic links). None when it is not a repository."""
    top = _git(["rev-parse", "--show-toplevel"], repo)
    if top is None:
        return None
    top_path = Path(top.strip()).resolve()
    raw = _git(["diff", "--cached", "--raw", "-z", "--no-abbrev", "--diff-filter=ACMRT"], top_path)
    if raw is None:
        return None
    fields, out, i = raw.split("\0"), set(), 0
    while i < len(fields):
        head = fields[i]
        if not head.startswith(":"):
            i += 1
            continue
        parts = head[1:].split()
        paths = 2 if parts[-1][:1] in ("R", "C") else 1
        name = fields[i + paths] if i + paths < len(fields) else ""
        if len(parts) >= 2 and parts[1] == "120000" and name:
            out.add(wiki_case(name))
        i += 1 + paths
    return top_path, out


def staged_person_links(ws: Workspace, repo: Path) -> Tuple[List[Finding], frozenset]:
    """The refusal of each symbolic link staged at or under `wiki/people`, by
    the path git stages it at, and those paths."""
    links = staged_links(repo)
    if links is None:
        return [], frozenset()
    top_path, names = links
    hits = sorted(top_path / n for n in names if any(under_folder(ws, top_path / n, f) for f in PEOPLE_FOLDERS))
    return [person_link_finding(ws, h) for h in hits], frozenset(hits)


def staged_files(repo: Path) -> Optional[List[Tuple[Path, str]]]:
    """(path, staged text) for every text file added, copied, modified or renamed
    in the index of the repository holding `repo`. None when it is not one."""
    staged = _staged_raw(repo)
    if staged is None:
        return None
    top_path, names = staged
    _BLOBS.clear()      # the index is read afresh by whoever asks first
    out = []
    for name in names:
        path = top_path / wiki_case(name)
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        data = _git_bytes(["show", ":" + name], top_path)
        if data is None:
            continue
        text = text_of(data) if len(data) <= MAX_STAGED_BYTES else None
        if text is None:
            continue
        out.append((path, text))
    return out


_BLOBS: Dict[Tuple[str, Tuple[str, ...]], Optional[bytes]] = {}   # what `git show :path` printed, once a run


def _git_bytes(args: List[str], cwd: Path) -> Optional[bytes]:
    # A staged file is read by several checks of one run: git is asked for it once. run_checks starts each run empty.
    keep = len(args) == 2 and args[0] == "show" and args[1].startswith(":")
    if keep and (str(cwd), tuple(args)) in _BLOBS:
        return _BLOBS[(str(cwd), tuple(args))]
    try:
        res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, timeout=60,
                             env=_git_env(cwd))
    except (OSError, subprocess.SubprocessError):
        return None
    got = res.stdout if res.returncode == 0 else None
    if keep:
        _BLOBS[(str(cwd), tuple(args))] = got
    return got


def git_view(ws: Workspace, committing: Path) -> Dict[Path, str]:
    """For every text file in the workspace's repositories whose working copy
    differs from git, or is gone from disk: the text git holds.

    The commit check reads the files it is not committing, the meetings and the
    other projects a quotation could come from, from disk. An edit left
    unstaged would then decide what the check sees, though the commit leaves
    that file as git holds it. So git's version counts too: for the repository
    being committed, its index, which is what the commit will hold; for every
    other, its last commit."""
    out: Dict[Path, str] = {}
    tops = workspace_repos(ws)
    if committing is not None and committing not in tops:
        # A repository inside a project, such as a Garrick checkout: its own
        # shipped files are shared wording, so an edit it leaves unstaged must
        # not decide what the check reads there either.
        tops = tops + [committing]
    for top in tops:
        if top == committing:
            names, spec = _git(["diff", "--name-only", "--no-renames", "-z"], top), ":%s"
        elif _git(["rev-parse", "--verify", "-q", "HEAD"], top) is not None:
            names, spec = _git(["diff", "HEAD", "--name-only", "--no-renames", "-z"], top), "HEAD:%s"
        else:
            continue  # nothing committed yet: the disk is all there is
        for name in (names or "").split("\0"):
            if not name or Path(name).suffix.lower() not in TEXT_SUFFIXES | {".eml"}:
                continue
            data = _git_bytes(["show", spec % name], top)
            text = text_of(data) if data is not None and len(data) <= MAX_STAGED_BYTES else None
            if text is None:
                continue  # deleted in git too, or not text
            out[top / name] = text
    return out


def apply_git_view(ws: Workspace, committing: Path) -> List[Finding]:
    """Read git's version of every file whose working copy differs (git_view)
    alongside the disk's. A meeting page or a Meetings question counts with
    the parties of both versions, and one deleted from disk still counts. A
    project or thread note in the repository being committed whose party
    differs from the one staged is refused: which party the commit is written
    for must not depend on an edit it leaves out."""
    ws.git_view = git_view(ws, committing)
    folders = meeting_sources(ws.root)
    asked = ws.root / "Wikis" / "Meetings" / WIKI_QUESTIONS
    answered = [ws.root.joinpath("Wikis", "Meetings", *g, *WIKI_ANSWERS) for g in [()] + [(x,) for x in FADED]]
    decided = [ws.root.joinpath("Wikis", "Meetings", *g, *WIKI_DECISIONS) for g in [()] + [(x,) for x in FADED]]
    for path, text in sorted(ws.git_view.items()):
        is_answer = any(a in path.parents for a in answered)
        is_decision = any(d in path.parents for d in decided)
        question = asked in path.parents or is_answer or is_decision
        if (question or any(f in path.parents for f in folders)) and path.suffix.lower() == ".md":
            then = meeting_view(ws, path, parse_frontmatter_text(text), text)
            if path not in ws.meetings:
                if not path.exists():
                    ws.meetings[path] = then
                    if question:
                        ws.meeting_questions.add(path)
                    if is_answer:
                        ws.meeting_answers.add(path)
                    if is_decision:
                        ws.meeting_decisions.add(path)
                continue
            now = ws.meetings[path]
            if path in ws.misread:
                now.pop("parties", None)
                now.pop("zone", None)
                continue
            parties = as_list(now.get("parties"))
            now["parties"] = parties + [p for p in as_list(then.get("parties")) if p not in parties]
    out = []
    for project, _ in ws.projects:
        notes = [project / (project.name + ".md")]
        notes += [t / (t.name + ".md") for t in visible_dirs(project / "Threads")]
        for note in notes:
            if note not in ws.git_view or committing not in note.parents:
                continue
            staged = {strip_tag(t) for t in as_list(parse_frontmatter_text(ws.git_view[note]).get("party"))}
            disk = {strip_tag(t) for t in as_list(note_frontmatter(ws, note).get("party"))}
            if staged != disk:
                out.append(Finding(ERROR, "walls", rel(ws, note),
                                   "names a different party on disk from the one staged; stage that change or undo "
                                   "it, so the walls are checked against the party the commit holds",
                                   "A party was changed but the change is not staged"))
    return out


def in_inbox(name: str, inbox: Tuple[str, ...]) -> bool:
    """Is `name`, a path inside a repository, anywhere below `inbox`, other
    than the inbox's own placeholder?"""
    parts = Path(name).parts
    n = len(inbox)
    return len(parts) > n and parts[:n] == inbox and parts[n:] != (".gitkeep",)


def repository_problem(ws: Workspace, top: Path) -> str:
    """Why the repository at `top` cannot be checked as part of the workspace,
    or "". The root, a zone and a repository inside a zone are as they were.
    One in or at the wikis is accepted only when its top resolves to exactly
    `Wikis/` or `Wikis/<wiki>` and its git directory is `<top>/.git`: a linked
    worktree put under Wikis/, or a GIT_WORK_TREE or `core.worktree` that moves
    the tree under another top, would leave the staged paths matching none of
    the places the walls read, and pass unread (#340)."""
    try:
        rtop = top.resolve()
        root = ws.root.resolve()
        wikis = (ws.root / "Wikis").resolve()
        zones = [z.resolve() for z in ws.zones]
        wiki_tops = {wikis} | {(ws.root / "Wikis" / d.name).resolve() for d in visible_dirs(ws.root / "Wikis")}
    except (OSError, RuntimeError):
        return "cannot be placed"
    if rtop == root or any(rtop == z or z in rtop.parents for z in zones):
        return ""
    if rtop not in wiki_tops:
        if rtop == wikis or wikis in rtop.parents:
            return ("is a repository inside the wikis that is not one of them, a linked worktree for one; its files "
                    "match none of the places the walls read")
        return "is not part of the workspace at %s" % ws.root
    if (top / ".git").is_symlink() or (top / ".git").is_file():
        return "has a .git that is %s" % WIKI_GIT_REASON.split("; ", 1)[0].replace("its .git is ", "", 1) \
            + "; " + WIKI_GIT_REASON.split("; ", 1)[1]
    gitdir = _git(["rev-parse", "--git-dir"], top)
    if gitdir is None or (top / gitdir.strip()).resolve() != (top / ".git").resolve():
        return ("has a git directory that is not its own .git, as with a linked worktree, GIT_WORK_TREE or "
                "core.worktree, so the paths it stages do not match the wiki the walls read")
    return ""


def _set_wiki_repo(ws: Workspace, top: Path, ok: bool) -> None:
    """Whether the repository being checked is a wiki, for wiki_case()."""
    global _WIKI_REPO
    try:
        rtop, wikis = top.resolve(), (ws.root / "Wikis").resolve()
        _WIKI_REPO = ok and (rtop == wikis or wikis in rtop.parents or rtop in {
            (ws.root / "Wikis" / d.name).resolve() for d in visible_dirs(ws.root / "Wikis")})
    except (OSError, RuntimeError):
        _WIKI_REPO = False


def check_walls_staged(ws: Workspace, repo: Path) -> List[Finding]:
    """The walls check on what is about to be committed, and nothing else.
    Anything waiting in a zone's Inbox, or in the Meetings inbox, at any depth,
    is refused too: it has not been filed, so no wall has seen its parties yet."""
    out = []
    global _WIKI_REPO
    _WIKI_REPO = False
    raw = _staged_raw(repo)
    problem = repository_problem(ws, raw[0]) if raw is not None else ""
    if raw is not None:
        _set_wiki_repo(ws, raw[0], not problem)
    staged = staged_names(repo)
    zones = {z.resolve() for z in ws.zones}
    minbox = ws.root.joinpath(*MEETINGS_INBOX).resolve()
    if staged is not None:
        top_path, names = staged
        if not problem and _WIKI_REPO:
            for link in staged_gitlinks(repo):
                out.append(Finding(ERROR, "walls", wiki_case(link),
                                   "is a submodule, a repository of its own whose pages no hook of this one reads; "
                                   "a wiki holds its pages itself", "A wiki holds a submodule"))
        if problem:
            # Never no findings: a hook that checked another place's files
            # would pass what it never read (#340).
            return [Finding(ERROR, "walls", str(top_path),
                            "this repository %s, so its staged files were not checked; commit from the wiki's own "
                            "folder, or install the hook from the workspace it belongs to" % problem,
                            "A commit was made in a repository the walls cannot place")]
        out.extend(apply_git_view(ws, top_path))
        listed = _git(["ls-files", "-z"], top_path)
        ws.index_files = {os.path.realpath(top_path / n).casefold() for n in listed.split("\0") if n} if listed is not None else set()
        try:
            minbox_rel = minbox.relative_to(top_path).parts
        except ValueError:
            minbox_rel = None  # the Meetings inbox is in another repository
        for name in names:
            if (top_path in zones or top_path == ws.root.resolve()) and in_inbox(name, (INBOX,)):
                out.append(Finding(ERROR, "inbox", rel(ws, top_path / name),
                                   "is waiting in the inbox to be filed, and never goes into any history; "
                                   "unstage it and file it where it belongs",
                                   "A file from the %s inbox was about to be committed" % top_path.name))
                continue
            if minbox_rel and in_inbox(name, minbox_rel):
                out.append(Finding(ERROR, "inbox", rel(ws, top_path / name),
                                   "is waiting in the Meetings inbox to be ingested, and never goes into the history; "
                                   "unstage it and ingest it with the meetings skill",
                                   "A transcript from the Meetings inbox was about to be committed"))
                continue
            owner = project_of(ws, top_path / name)
            if owner is not None and (top_path / name).is_symlink() and (top_path / name).suffix.lower() not in TEXT_SUFFIXES:
                found = symlink_finding(ws, owner[0], {strip_tag(t) for t in as_list(owner[1].get("party"))}, top_path / name)
                if found is not None:
                    out.append(found)
            if owner is None or not _in_sources(owner[0], top_path / name):
                continue
            try:
                res = subprocess.run(["git", "show", ":" + name], cwd=str(top_path), capture_output=True, timeout=60,
                                     env=_git_env(top_path))
            except (OSError, subprocess.SubprocessError):
                continue
            if res.returncode == 0 and len(res.stdout) <= MAX_SOURCE_BYTES:
                project, pfm = owner
                ptags = {strip_tag(t) for t in as_list(pfm.get("party"))}
                out.extend(sources_for_file(ws, project, ptags, top_path / name, res.stdout))
    staged_texts = [(canonical_path(ws, p), t) for p, t in (staged_files(repo) or [])]
    refused, links = staged_person_links(ws, repo)
    out.extend(refused)
    # The People and Parties tables decide which names stand for which party,
    # so a change to them puts every person page across a wall or not (#340).
    table = ws.root / "System" / "context.md"
    changed = staged is not None and any(
        (staged[0] / n).resolve() == table.resolve() or (staged[0] / n) == table for n in staged[1])
    if changed and table in ws.git_view:                 # on disk it differs from the index
        out.append(Finding(ERROR, "walls", rel(ws, table),
                           "names different parties and people on disk from the ones staged; stage that change or "
                           "undo it, so the walls are checked against the table the commit holds",
                           "The People or Parties table was changed but the change is not staged"))
    out.extend(organisation_walls(ws, staged_people(ws, staged_texts, links, staged_removed(repo), changed)))
    # The form of every staged page the walls read, and of the hub and thread
    # note each staged project file is checked against.
    forms = [(path, text) for path, text in staged_texts if path not in links]
    have = {path for path, _ in forms}
    for path, _ in staged_texts:
        owner = project_of(ws, path)
        if owner is None:
            continue
        project = owner[0]
        notes = [project / (project.name + ".md")]
        inner = path.relative_to(project).parts if project in path.parents else ()
        if len(inner) > 2 and inner[0] == "Threads":
            notes.append(project / "Threads" / inner[1] / (inner[1] + ".md"))
        for note in notes:
            if note not in have and note.is_file():
                have.add(note)
                forms.append((note, None))
    out.extend(form_findings(ws, forms))
    # Any staged file that reads as text is read for the walls, whatever its suffix; a project that names no party
    # takes no file at all, of any kind (no label, no permit).
    extra = [(canonical_path(ws, p), t) for p, t in staged_other_texts(repo)]
    files = [(path, text, project_of(ws, path)) for path, text in staged_texts + extra]
    files = [f for f in files if f[2] is not None]  # not inside a project: no party, so no wall to hold
    known = set(ws.context["parties"])
    if "none" in known:
        out.append(Finding(ERROR, "walls", "System/context.md",
                           "the Parties table has a row for `none`, which is reserved; take the row out before anything "
                           "is committed, so no wall is read against it",
                           "The Parties table defines the reserved tag none"))
    unlabelled_reported: set = set()
    raw = _staged_raw(repo)
    for name in (raw[1] if raw else []):
        staged_path = canonical_path(ws, raw[0] / wiki_case(name))
        owner = project_of(ws, staged_path)
        if owner is None or in_system(ws, owner[0]):
            continue
        ptags = {strip_tag(t) for t in as_list(owner[1].get("party"))}
        if not ptags or ptags - known or hub_unreadable(ws, owner[0]):
            unlabelled_reported.add(staged_path)
            out.append(unlabelled_finding(ws, owner[0], staged_path, ptags - known))
        elif staged_path.suffix.lower() in TEXT_SUFFIXES:
            # a file of the text suffixes that the walls cannot read is refused, not skipped (#398)
            data = _git_bytes(["show", ":" + name], raw[0])
            if data is not None and (len(data) > MAX_STAGED_BYTES or text_of(data) is None):
                why = ("is over %d bytes" % MAX_STAGED_BYTES if len(data) > MAX_STAGED_BYTES
                       else "holds NUL bytes and no UTF-16 byte order mark")
                out.append(Finding(ERROR, "walls", rel(ws, staged_path),
                                   "%s, so the walls cannot read it; save it as UTF-8 text under the size limit, or keep "
                                   "it out of the project" % why, "A file in %s cannot be read by the walls" % owner[0].name))
    # A hub or thread note whose parties changed puts every file already in the project, or the thread, under the
    # new ones: they are checked now, not only the files staged with it (#398).
    seen = {path for path, _, _ in files}
    for path, text, project in recheck_after_party_change(ws, repo, staged_texts):
        if path not in seen:
            seen.add(path)
            files.append((path, text, project))
    # The wording check asks only after the runs of words these files hold:
    # the index is built for those alone, from the cache where it can be.
    if not ws.quick:
        quote_index(ws, set().union(*(wording(ws, path, text, False) for path, text, _ in files)))
    for path, text, (project, pfm) in files:
        ptags = {strip_tag(t) for t in as_list(pfm.get("party"))}
        if (not ptags or ptags - known or hub_unreadable(ws, project)) and not in_system(ws, project):
            if path not in unlabelled_reported:
                out.append(unlabelled_finding(ws, project, path, ptags - known))
            if ptags:
                continue
        out.extend(walls_for_file(ws, project, ptags, path, text))
    return out


def unlabelled_target(ws: Workspace, owner, hit: Path) -> bool:
    """Does a file a link lands on have no label (garrick_lib's labels())? A file of no project: labels() says. A file
    of a project: its tags (git-aware, as the hook reads them) are empty or unknown, or its hub or thread note
    carries `party:` and `parties:` that disagree, which labels() reads as neither. A Knowledge page with no party
    key is free; one with a party key has no label."""
    if owner is None:
        return labels(ws.root, hit, ws.context, ws.label_cache) is None
    project = owner[0]
    tags = project_file_tags(ws, project, hit)
    if not tags or not tags <= set(ws.context["parties"]):
        return True
    return notes_disagree(ws, project, hit)


def notes_disagree(ws: Workspace, project: Path, hit: Path) -> bool:
    """Do the hub or the thread note a file of `project` is under carry `party:` and `parties:` that disagree?"""
    notes = [project / (project.name + ".md")]
    parts = hit.relative_to(project).parts
    if len(parts) > 2 and parts[0] == "Threads":
        notes.append(project / "Threads" / parts[1] / (parts[1] + ".md"))
    for note in notes:
        fm = note_frontmatter(ws, note)
        if fm.get("party") is not None and fm.get("parties") is not None and \
                {strip_tag(t) for t in as_list(fm.get("party"))} != {strip_tag(t) for t in as_list(fm.get("parties"))}:
            return True
    return False


def hub_unreadable(ws: Workspace, project: Path) -> bool:
    """Does the hub's `party:` and `parties:` read two ways (garrick_lib's labels())? It then labels nothing."""
    key = ("hub_unreadable", str(project))      # worked out once a run: every file of a project asks the same hub
    if key not in ws.label_cache:
        ws.label_cache[key] = labels(ws.root, project / (project.name + ".md"), ws.context, ws.label_cache) is None
    return ws.label_cache[key]


def unlabelled_finding(ws: Workspace, project: Path, path: Path, unknown: set) -> Finding:
    """No label, no permit: the hub is named as the fix."""
    hub = rel(ws, project / (project.name + ".md"))
    why = ("names no party the Parties table holds (%s)" % ", ".join(sorted(unknown))) if unknown else "names no party"
    return Finding(ERROR, "walls", rel(ws, path),
                   "is in a project whose hub %s, so the walls cannot be checked; set `party:` in %s to a tag from the "
                   "Parties table" % (why, hub),
                   "A file in %s is committed before the project has a party" % project.name)


def staged_other_texts(repo: Path) -> List[Tuple[Path, str]]:
    """(path, text) of each staged file the text suffixes leave out that still decodes as UTF-8 text (a script, a
    log, a mail, a notebook, a file with no extension): what a person can read in it, the walls read. Office files
    and PDFs do not decode, and stay unread, as docs/principles.md says."""
    staged = _staged_raw(repo)
    if staged is None:
        return []
    top_path, names = staged
    out = []
    for name in names:
        path = top_path / wiki_case(name)
        if path.suffix.lower() in TEXT_SUFFIXES:
            continue
        data = _git_bytes(["show", ":" + name], top_path)
        text = text_of(data, strict=True) if data and len(data) <= MAX_STAGED_BYTES else None
        if text is None:
            continue
        out.append((path, text))
    return out


def recheck_after_party_change(ws: Workspace, repo: Path, staged_texts: List[Tuple[Path, str]]):
    """(path, text, (project, hub fields)) for every file already committed in a project, or in a thread, whose hub
    or thread note is staged with other parties than HEAD holds."""
    staged = _staged_raw(repo)
    if staged is None:
        return []
    top_path = staged[0]
    out = []
    for path, text in staged_texts:
        owner = project_of(ws, path)
        if owner is None:
            continue
        project = owner[0]
        inner = path.relative_to(project).parts
        if len(inner) == 1 and inner[0] == project.name + ".md":
            scope = project
        elif len(inner) == 3 and inner[0] == "Threads" and inner[2] == inner[1] + ".md":
            scope = project / "Threads" / inner[1]
        else:
            continue
        before = _git_bytes(["show", "HEAD:" + path.relative_to(top_path).as_posix()], top_path)
        if before is None:
            continue
        old = {strip_tag(t) for t in as_list(parse_frontmatter_text(before.decode("utf-8", errors="replace")).get("party"))}
        old |= {strip_tag(t) for t in as_list(parse_frontmatter_text(before.decode("utf-8", errors="replace")).get("parties"))}
        new = {strip_tag(t) for t in as_list(parse_frontmatter_text(text).get("party"))}
        new |= {strip_tag(t) for t in as_list(parse_frontmatter_text(text).get("parties"))}
        if old == new:
            continue
        listed = _git_bytes(["ls-files", "-z", "--", scope.relative_to(top_path).as_posix()], top_path)
        for name in (listed.decode("utf-8", errors="replace").split("\0") if listed else []):
            if not name:
                continue
            target = top_path / name
            data = _git_bytes(["show", ":" + name], top_path)
            text = text_of(data, strict=True) if data and len(data) <= MAX_STAGED_BYTES else None
            if text is None:
                continue
            out.append((target, text, owner))
    return out


def _own_repo(folder: Path) -> bool:
    """Is `folder` the top of its own git repository?"""
    top = _git(["rev-parse", "--show-toplevel"], folder) if (folder / ".git").exists() else None
    return top is not None and Path(top.strip()).resolve() == folder.resolve()


MEETINGS_INBOX = ("Wikis", "Meetings", "raw", "inbox")


def _repo_top(ws: Workspace, folder: Path) -> Optional[Path]:
    """The top of the git repository holding `folder`, when it is the workspace's
    own (the root, or a repository inside it); None otherwise."""
    top = _git(["rev-parse", "--show-toplevel"], folder)
    if top is None:
        return None
    top_path = Path(top.strip()).resolve()
    root = ws.root.resolve()
    return top_path if top_path == root or root in top_path.parents else None


def workspace_repos(ws: Workspace) -> List[Path]:
    """The tops of the workspace's own repositories: its zones', its wikis' and
    its root's, resolved."""
    tops = set()
    for folder in list(ws.zones) + [ws.root / "Wikis" / "Meetings", ws.root / "Wikis" / "Knowledge", ws.root]:
        top = _repo_top(ws, folder) if folder.is_dir() else None
        if top is not None:
            tops.add(top)
    return sorted(tops)


def ignored(ws: Workspace) -> set:
    """Every file and folder the workspace's own repositories ignore, listed
    once: what git would never commit, such as an installed package's README
    or a build's output, which the commit hook therefore never sees. A
    repository's list counts only for its own files: the root ignores the
    zones and the wikis whole, because each is a repository of its own, and
    that never hides them. The inboxes are ignored by design, and the inbox
    checks read them directly, never through this."""
    if ws.ignored is None:
        ws.ignored = set()
        wikis = ws.root / "Wikis"
        areas = list(ws.zones) + [wikis] + visible_dirs(wikis)
        for repo in [ws.root, wikis] + visible_dirs(wikis) + list(ws.zones):
            if not (repo / ".git").exists():
                continue
            # Named outright, so a `.git` that is not a repository fails here
            # rather than lending the folder the ignores of one above it.
            listing = _git(["--git-dir=" + str(repo / ".git"), "--work-tree=" + str(repo), "ls-files", "-z", "--others",
                            "--ignored", "--exclude-standard", "--directory"], repo) or ""
            for name in listing.split("\0"):
                path = repo / name.rstrip("/")
                if name and not any(a == path or path in a.parents for a in areas):
                    ws.ignored.add(path)
    return ws.ignored


def set_apart(ws: Workspace) -> set:
    """What the checks that read a project's own files leave out: what git
    ignores (see ignored), and every Garrick checkout kept in a project. A
    checkout cloned with its `.git` is a repository of its own and is never
    walked; one unpacked from a release ZIP has no `.git`, and is left out
    the same way, so its docs, examples and shipped rules are not read as the
    project's notes. Its shipped tree still counts as shared wording (see
    shared_files), and a commit of its files is still checked as the
    project's, by the commit hook, whichever repository makes it."""
    if ws.apart is None:
        ws.apart = ignored(ws) | set(checkouts(ws))
    return ws.apart


def check_inbox(ws: Workspace) -> List[Finding]:
    """Mail and files in a zone's Inbox, and transcripts in the Meetings inbox,
    are waiting to be filed. They never enter any history, a recording comes
    in as its transcript, and once filed no copy stays behind."""
    out = []
    by_size: Optional[Dict[int, List[Path]]] = None
    inboxes: List[Tuple[Path, str]] = []  # (folder, how to say it)
    for zone in ws.zones:
        inbox = zone / INBOX
        if not inbox.is_dir():
            continue
        inboxes.append((inbox, "the %s inbox" % zone.name))
        if _own_repo(zone):
            listing = _git(["ls-files", "-z", "--", INBOX], zone) or ""
            for name in sorted(n for n in listing.split("\0") if n and Path(n).name != ".gitkeep"):
                out.append(Finding(ERROR, "inbox", rel(ws, zone / name),
                                   "committed into the %s zone's history from its inbox, which is never committed: "
                                   "`git rm --cached` it, then file it where it belongs" % zone.name,
                                   "Something in the %s inbox was committed" % zone.name))
    shared = ws.root / INBOX               # mail sent to one address for every zone, waiting for its zone
    if shared.is_dir():
        inboxes.append((shared, "the workspace's inbox"))
        if _own_repo(ws.root):
            listing = _git(["ls-files", "-z", "--", INBOX], ws.root) or ""
            for name in sorted(n for n in listing.split("\0") if n and Path(n).name != ".gitkeep"):
                out.append(Finding(ERROR, "inbox", rel(ws, ws.root / name),
                                   "committed into the workspace's history from its inbox, which is never committed: "
                                   "`git rm --cached` it, then file it where it belongs",
                                   "Something in the workspace's inbox was committed"))
    minbox = ws.root.joinpath(*MEETINGS_INBOX)
    if minbox.is_dir():
        inboxes.append((minbox, "the Meetings inbox"))
        top = _repo_top(ws, minbox)
        if top is not None:
            listing = _git(["ls-files", "-z", "--", minbox.resolve().relative_to(top).as_posix()], top) or ""
            for name in sorted(n for n in listing.split("\0") if n and Path(n).name != ".gitkeep"):
                out.append(Finding(ERROR, "inbox", rel(ws, top / name),
                                   "committed from the Meetings inbox, which is never committed: "
                                   "`git rm --cached` it, then ingest it with the meetings skill",
                                   "Something in the Meetings inbox was committed"))
    for inbox, spoken in inboxes:
        for path in sorted(p for p in inbox.iterdir() if p.is_file() and not p.name.startswith(".")):
            if path.suffix.lower() in MEDIA_EXTS:
                out.append(Finding(WARNING, "inbox", rel(ws, path),
                                   "audio or video is never read; put its transcript (.txt, .md or .vtt) in "
                                   "Wikis/Meetings/raw/inbox/ instead",
                                   "A recording in %s cannot be read" % spoken))
                continue
            if by_size is None:
                # Where a filed item ends up: a Meetings or Knowledge raw record, or a project's Sources/.
                by_size = {}
                places = [ws.root / "Wikis" / w / "raw" for w in ("Meetings", "Knowledge")]
                places += [project / "Sources" for project, _ in ws.projects]
                for place in places:
                    for r in (walk_files(place) if place.is_dir() else []):
                        if r.is_file() and not r.name.startswith(".") and r.parent.name != "inbox":
                            by_size.setdefault(r.stat().st_size, []).append(r)
            data = path.read_bytes()
            # Mail filed as reading is frozen without the reader's addresses, so compare that form too.
            forms = [data]
            if path.suffix.lower() in (".eml", ".md", ".txt"):
                forms += [strip_recipients(data, path.suffix), strip_recipients(data, path.suffix, ws.context.get("me", []))]
            twin = next((r for f in forms for r in by_size.get(len(f), []) if r.read_bytes() == f), None)
            if twin is not None:
                out.append(Finding(WARNING, "inbox", rel(ws, path),
                                   "already filed as %s; this copy was left behind, so delete it" % rel(ws, twin),
                                   "Something in %s was filed but not moved" % spoken))
    return out


_FM_KEY = re.compile(r"""^(\s*)((?:-\s+)*)([A-Za-z0-9_][A-Za-z0-9_ .-]*?)\s*:(?:\s+(.*))?$""")
_FM_DQ = re.compile(r'''^"(?:[^"\\]|\\.)*"\s*(?:#.*)?$''')
_FM_SQ = re.compile(r"""^'(?:[^']|'')*'\s*(?:#.*)?$""")
_FM_ITEM = r"""\s*(?:"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s,\[\]{}:\\"'&!*?][^,\[\]{}:\\"']*)?\s*"""
_FM_LIST = re.compile(r"^\[(?:%s(?:,%s)*)?\]\s*(?:#.*)?$" % (_FM_ITEM, _FM_ITEM))


def _frontmatter_value_ok(value: str) -> bool:
    """A value the allowlist reads: empty, a block scalar's opener, a quoted scalar, a one-line flow list whose
    items are plain scalars (none holding `{ [ ] : \\`, none starting `& ! * ?`) or quoted scalars (which may
    hold anything), or a plain scalar that does not start with a flow, anchor, tag, alias or key mark."""
    v = value.strip()
    if not v or v[0] in "|>":
        return True
    if v[0] == '"':
        return bool(_FM_DQ.match(v))
    if v[0] == "'":
        return bool(_FM_SQ.match(v))
    if v[0] == "[":
        return bool(_FM_LIST.match(v))
    return v[0] not in "{&!*?" and not v.startswith("<<")


# A character some YAML readers take as a line break or cannot print: C0 and C1 controls but tab, and U+2028 and
# U+2029. `a party: b` after one is a key to such a reader (#388).
_FM_ODD_CHAR = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029]")


def scan_frontmatter(text: str, names) -> tuple:
    """Read a Knowledge page's frontmatter against an allowlist (#388): (names among `names` used as keys,
    whether any line cannot be read plainly). A line is blank, a comment, `key: value` or `key:` with an
    unquoted key of letters, digits, `_`, space, `.` and `-`, a block list item `- value`, or a line of a block
    scalar (`|` or `>`) opened above; a value is a plain or quoted scalar or a one-line flow list of scalars.
    Anything else could spell `parties` in a way a scan cannot see, so the page is refused. A key with no value
    and nothing under it is not counted."""
    body = _frontmatter_body(text) or []
    found, unreadable, block = [], False, None
    for i, line in enumerate(body):
        if _FM_ODD_CHAR.search(line):
            unreadable = True
        indent = len(line) - len(line.lstrip())
        if block is not None and (not line.strip() or indent > block):
            continue
        block = None
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _FM_KEY.match(line)
        if m:
            value = (m.group(4) or "")
            if not _frontmatter_value_ok(value):
                unreadable = True
            if value.strip()[:1] in ("|", ">") and value.strip():
                block = indent
            key = m.group(3).strip().lower()
            if key in names:
                plain = value.split(" #")[0].strip()
                nested = False
                for nxt in body[i + 1:]:
                    if nxt.strip() and not nxt.lstrip().startswith("#"):
                        nested = (len(nxt) - len(nxt.lstrip())) > indent or nxt.lstrip().startswith("- ")
                        break
                if plain not in ("", "[]", "''", '""', "null", "~") or nested:
                    found.append(key)
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and "\t" not in line[:indent] and _frontmatter_value_ok(item.group(1)):
            if item.group(1).strip()[:1] in ("|", ">"):
                block = indent
            continue
        unreadable = True
    return found, unreadable


def check_knowledge(ws: Workspace) -> List[Finding]:
    """Knowledge holds published material, which every side may use. A page
    carries no party and no zone, links nowhere into Meetings, and neither it
    nor its raw record repeats a meeting: wording found here counts as common
    to every side, so a conversation copied in would cross every wall."""
    out = []
    kroot = ws.root / "Wikis" / "Knowledge"
    mroot = ws.root / "Wikis" / "Meetings"
    if not kroot.is_dir():
        return out
    kfiles = PathIndex(ws, walk_files(kroot))
    mfiles = PathIndex(ws, (p for p in ws.wiki_files if mroot in p.parents), lambda p: grade_places(ws, p))
    raws = [kroot / home for home in RAW_HOMES]
    beyond = None
    schema, problems = knowledge_schema(ws.root)
    for problem in problems:
        out.append(Finding(WARNING, "knowledge", "Wikis/Knowledge/schema.json", problem,
                           "The Knowledge wiki's schema has a problem"))
    sources = kroot / "wiki" / "sources"
    stype, sfields = schema["source"]["type"], schema["source"]["fields"]
    known_types = {stype, "concept", "entity"}
    declared = (kroot / "schema.json").is_file()      # a wiki that declares its layout is held to it
    for path in walk_files(kroot):
        suffix = path.suffix.lower()
        if suffix not in TEXT_SUFFIXES and suffix != ".eml":
            continue
        text = read_text(path) or ""
        if not any(raw in path.parents for raw in raws) and suffix != ".eml":
            fm = {}
            if suffix == ".md":  # read once; a page too big to scan still has its fields read
                fm = parse_frontmatter_text(text) if text else parse_frontmatter(path)
                if isinstance(fm.get("type"), list):   # a stray `- [..]` line reads as a list; not a kind of page
                    fm["type"] = str(fm["type"])
            if suffix == ".md" and fm and path.parent == sources and declared:
                lacking = [f for f in sfields if not as_list(fm.get(f))]
                if fm.get("type") != stype or lacking:
                    out.append(Finding(WARNING, "knowledge", rel(ws, path),
                                       "a source page %s; the wiki's schema asks for `type: %s` and %s" % (
                                           "has `type: %s`" % fm.get("type") if fm.get("type") != stype
                                           else "has no %s" % ", ".join("`%s`" % f for f in lacking),
                                           stype, ", ".join("`%s`" % f for f in sfields)),
                                       "A Knowledge source page does not follow the wiki's schema"))
            elif suffix == ".md" and fm.get("type") and fm.get("type") not in known_types \
                    and kroot / "wiki" in path.parents \
                    and not (fm.get("type") == "report" and kroot / "wiki" / "lint" in path.parents):
                # A lint report, `wiki/lint/<date>.md`, is the knowledge skill's own output.
                out.append(Finding(WARNING, "knowledge", rel(ws, path),
                                   "`type: %s` is not a kind of page the wiki's schema knows (%s); the graph draws it "
                                   "as other notes" % (fm.get("type"), ", ".join(sorted(known_types))),
                                   "A Knowledge page has a type the schema does not know"))
            carried = [k for k in ("party", "parties", "zone") if as_list(fm.get(k))]
            unreadable = False
            if suffix == ".md":
                named, unreadable = scan_frontmatter(text, ("party", "parties", "zone"))
                carried += [k for k in named if k not in carried]
            if carried:
                carried.sort(key=("party", "parties", "zone").index)
                out.append(Finding(ERROR, "knowledge", rel(ws, path),
                                   "carries %s; Knowledge holds published material, which carries nobody's confidence. "
                                   "Take the field out, or file the item in Meetings if it is a conversation"
                                   % " and ".join("`%s`" % k for k in carried),
                                   "A Knowledge page carries parties"))
            if unreadable:
                out.append(Finding(ERROR, "knowledge", rel(ws, path),
                                   "frontmatter the check cannot read plainly; Knowledge carries nobody's confidence. "
                                   "Write each key on a line of its own, unquoted and without tags, anchors or braces",
                                   "A Knowledge page has frontmatter the check cannot read"))
            for problem in ([] if is_faded(ws, path) else bad_dates(fm)):
                out.append(Finding(ERROR, "knowledge", rel(ws, path), problem,
                                   "A Knowledge page has a date in the wrong form"))
            for written, target in extract_links(text):
                explicit = "Meetings/" in target.replace("\\", "/") or target.startswith("obsidian:Meetings:")
                if not explicit and resolve(ws, path, target, kfiles):
                    continue  # the link lands inside Knowledge, which is where Obsidian looks first
                if resolve(ws, path, target, mfiles):
                    out.append(Finding(ERROR, "knowledge", rel(ws, path),
                                       "links %s, a Meetings page; Knowledge must not carry anyone's confidence" % written,
                                       "A Knowledge page links into Meetings"))
        if ws.quick:
            continue
        if beyond is None:
            beyond = quote_index(ws).common_beyond_knowledge
        heard = meeting_wording(ws, body_of(transcript_text(path, text)), beyond, path)
        if heard:
            more = " and %d more" % (len(heard) - 1) if len(heard) > 1 else ""
            noun = meeting_noun(ws, heard[0])
            out.append(Finding(WARNING, "knowledge", rel(ws, path),
                               "shares eight or more words in a row with %s %s%s; wording in Knowledge is common to "
                               "every side, so a conversation copied here crosses every wall. If the %s quoted "
                               "this published text, nothing needs changing" % (noun, heard[0].stem, more, noun),
                               "A Knowledge page repeats a Meetings question" if noun == "question"
                               else "A Knowledge page repeats a meeting"))
    return out


# The repository whose commit is being checked, in staged mode: the one whose
# git processes keep git's repository-local variables. None otherwise, when no
# commit is in hand and those variables, if the environment holds any, speak
# for no repository here.
_COMMITTING: Optional[Path] = None

# The top of the repository each folder belongs to, once looked up (see _own_top).
_OWN_TOP: Dict[Path, Optional[Path]] = {}


def _committing(repo: Optional[Path]) -> None:
    """Remember whose commit this run is checking, as the top of its repository.
    `None` forgets it: every git process then runs without git's
    repository-local variables."""
    global _COMMITTING
    _OWN_TOP.clear()        # a repository may have been made since the last run
    _COMMITTING = Path(repo).resolve() if repo is not None else None
    if _COMMITTING is None:
        return
    # Asked inside the committing repository, so with its own environment.
    top = _git(["rev-parse", "--show-toplevel"], _COMMITTING)
    if top and top.strip():
        _COMMITTING = Path(top.strip()).resolve()


def _own_top(folder: Path) -> Optional[Path]:
    """The nearest folder at `folder` or above it holding a `.git`: the top of
    the repository that folder belongs to, as far as the filesystem can say,
    and None when there is none above it. Kept per folder, and a walk, so it
    costs no git process.

    Which repository a folder belongs to is the question, and containment is no
    answer to it: the workspace's root repository holds every zone and both
    wikis, and each of those is a repository of its own."""
    resolved = Path(folder).resolve()
    if resolved not in _OWN_TOP:
        _OWN_TOP[resolved] = next((c for c in [resolved, *resolved.parents] if (c / ".git").exists()), None)
    return _OWN_TOP[resolved]


def _git_env(repo: Path) -> Optional[Dict[str, str]]:
    """The environment for a git process to be run against `repo`: this
    process's own for the repository being committed, whose temporary index the
    hook has to read, and one stripped of git's repository-local variables for
    every other repository (`foreign_git_env`). None leaves the child to
    inherit this process's environment.

    A folder goes with the commit when the repository it belongs to is the one
    being committed, which is its own top and not merely a folder above it. A
    project or a thread inside the committing zone is the zone's and keeps the
    variables; a zone inside the root repository, or a repository inside a
    project, is its own and does not."""
    if _COMMITTING is not None:
        resolved = Path(repo).resolve()
        if resolved == _COMMITTING or _own_top(resolved) == _COMMITTING:
            return None
    return foreign_git_env()


def _git(args: List[str], cwd: Path) -> Optional[str]:
    try:
        res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60,
                             env=_git_env(cwd))
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def name_status(data: str) -> Iterable[Tuple[Optional[str], str, str, Optional[str]]]:
    """(commit, status, path, renamed from) for each entry of git's
    `--name-status -z` output, from `log` (each commit opened by a line
    `\\x01<hash>`, as `--format=%x01%H` writes it) or from `diff` (no commit)."""
    tokens = data.split("\0")
    commit = None
    i = 0
    while i < len(tokens):
        token = tokens[i].lstrip("\n")
        i += 1
        if not token:
            continue
        if token.startswith("\x01"):
            commit = token[1:]
            continue
        if token[:1] in "RC" and i + 1 < len(tokens):
            yield commit, token, tokens[i + 1], tokens[i]
            i += 2
        elif i < len(tokens):
            yield commit, token, tokens[i], None
            i += 1


def check_raw(ws: Workspace) -> List[Finding]:
    """A raw record is never changed after its first commit, unless the check
    settings accept that change (`raw-accepted`): then only a later one counts.

    A rename that keeps the content byte for byte is not a change: a name heard
    wrong gets corrected, and a record moves with its page when the page fades
    or wakes. A rename that also changes the content is an edit, reported under
    the record's new name, and so is an earlier change to a record since moved."""
    out = []
    accepted = {k: v.strip() for k, v in ws.settings.get("raw-accepted", {}).items()
                if isinstance(v, str) and COMMIT_RE.fullmatch(v.strip())}     # a commit, never an option for git
    wikis = ws.root / "Wikis"
    if not wikis.is_dir():
        return out
    root = ws.root.resolve()
    tops: Dict[Path, Optional[Path]] = {}
    for wiki in visible_dirs(wikis):
        if not any((wiki / home).is_dir() for home in RAW_HOMES):
            continue
        # One pathspec for each home, so that a move from one to another is
        # seen whole: a rename out of the pathspecs shows as a deletion.
        specs: Dict[Path, List[str]] = {}
        inbox = None
        for home in RAW_HOMES:
            folder = wiki / home
            where = (folder if folder.is_dir() else wiki).resolve()
            if where not in tops:
                top = _git(["rev-parse", "--show-toplevel"], where)
                tops[where] = Path(top.strip()).resolve() if top else None
            top_path = tops[where]
            if top_path is None:
                continue  # not a git repository, or git is not installed: nothing to compare against
            if top_path != root and root not in top_path.parents:
                continue  # the repository belongs to something outside the workspace
            try:
                spec = (folder.resolve() if folder.is_dir() else where / home).relative_to(top_path).as_posix()
            except ValueError:
                continue
            specs.setdefault(top_path, []).append(spec)
            if home == "raw":
                inbox = (top_path, spec + "/inbox/")
        for top_path, paths in specs.items():
            after: Dict[str, Optional[set]] = {}

            def counts(name: str, commit: Optional[str]) -> bool:
                """Whether a change to `name` in `commit` counts: it does
                unless the check settings accept a change to that record in
                that commit or one before it."""
                ok = accepted.get(rel(ws, top_path / name))
                if commit is None or not ok:
                    return True
                if ok not in after:
                    later = _git(["rev-list", ok + "..HEAD"], top_path)
                    after[ok] = set(later.split()) if later is not None else None
                    if later is None:
                        out.append(Finding(WARNING, "raw", rel(ws, top_path / name),
                                           "the check settings accept a change to it in commit %s, which git does not know" % ok,
                                           "An accepted change names a commit git does not know"))
                return after[ok] is None or commit in after[ok]

            changed: Dict[str, str] = {}
            log = _git(["log", "-z", "-M", "--reverse", "--diff-filter=DMR", "--name-status", "--format=%x01%H",
                        "--", *paths], top_path) or ""
            # What is uncommitted, staged or not, against the last commit.
            diff = _git(["diff", "HEAD", "-z", "-M", "--diff-filter=DMR", "--name-status", "--", *paths], top_path) or ""
            waiting = inbox[1] if inbox and inbox[0] == top_path else None
            # Oldest first, so that a change follows its record through every
            # later move, and the newest change to a name is the one reported.
            for commit, status, name, before in [*name_status(log), *name_status(diff)]:
                if before is not None and waiting and before.startswith(waiting):
                    continue                                # filed out of the inbox: its first commit as a record
                if before is not None:
                    earlier = changed.pop(before, None)     # the record keeps its history under its new name
                    if status != "R100" and counts(name, commit):
                        changed[name] = "edited"
                    elif earlier:
                        changed[name] = earlier
                elif counts(name, commit):
                    changed[name] = "deleted" if status.startswith("D") else "edited"
            for name, how in sorted(changed.items()):
                if waiting and name.startswith(waiting):
                    continue
                out.append(Finding(ERROR, "raw", rel(ws, top_path / name),
                                   "raw record %s after its first commit; restore it from git and correct the summary instead" % how,
                                   "A raw record in %s was %s" % (wiki.name, how)))
    return out


def check_generated(ws: Workspace) -> List[Finding]:
    """System/generated/ holds pages a tool rebuilds, such as the status page,
    which shows every zone at once. It must never enter the workspace's git
    history: the root repository ignores it, and nothing in it is tracked."""
    out = []
    folder = ws.root / Path(*GENERATED)
    if not (ws.root / ".git").exists():
        return out
    def git(*args):
        try:
            return subprocess.run(["git", "-C", str(ws.root), *args], capture_output=True, text=True, timeout=30,
                                  env=_git_env(ws.root))
        except (OSError, subprocess.TimeoutExpired):
            return None
    tracked = git("ls-files", "--", "/".join(GENERATED))
    for line in (tracked.stdout.splitlines() if tracked and tracked.returncode == 0 else []):
        out.append(Finding(ERROR, "generated", line,
                           "generated output is committed; run `git rm --cached` on it and let the .gitignore keep it out",
                           "A generated file is in the workspace history"))
    probe = "/".join(GENERATED) + "/probe.html"
    ignored = git("check-ignore", "-q", "--no-index", probe)
    if folder.is_dir() and ignored is not None and ignored.returncode == 1:
        out.append(Finding(WARNING, "generated", ".gitignore",
                           "the root repository does not ignore System/generated/; add that line to .gitignore",
                           "The generated folder is not ignored"))
    return out


RECALL_FILE_RE = re.compile(r"(?:^|/)(?:\.recall\.sqlite[^/]*|\.sessions/.*)$")


def check_recall(ws: Workspace) -> List[Finding]:
    """Recall's search indexes (`.recall.sqlite*`) are a cache, and the
    sessions it extracts (`.sessions/`) are private to this Mac (#341). Neither
    may be staged or committed in any repository of the workspace: the root's,
    a zone's, or the wikis'."""
    out = []
    repos = [ws.root] + list(ws.zones)
    wikis = ws.root / "Wikis"
    repos += [wikis] + (sorted(p for p in wikis.iterdir() if p.is_dir()) if wikis.is_dir() else [])
    for repo in repos:
        if not (repo / ".git").exists():
            continue
        try:
            r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, text=True, timeout=60,
                               env=_git_env(repo))
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode != 0:
            continue
        for name in r.stdout.split("\0"):
            if name and RECALL_FILE_RE.search(name):
                path = (repo / name).relative_to(ws.root).as_posix() if repo != ws.root else name
                out.append(Finding(ERROR, "recall", path,
                                   "a search index or an extracted session is staged or committed; run `git rm --cached` "
                                   "on it and let the .gitignore keep it out",
                                   "A Recall index or session file is in the workspace history"))
    return out


def check_preferences(ws: Workspace) -> List[Finding]:
    """The choices made once and kept -- each zone's colour and icon, and how
    a thread opens -- are saved in the settings file, which is committed with
    the workspace. That is what carries them through a rebuild of
    System/generated/, which is never committed, and through a workspace
    restored from its own history. A settings file left out of git loses
    them."""
    out = []
    if not (ws.root / PREFERENCES_FILE).is_file() or not (ws.root / ".git").exists():
        return out
    try:
        tracked = subprocess.run(["git", "-C", str(ws.root), "ls-files", "--", PREFERENCES_FILE],
                                 capture_output=True, text=True, timeout=30, env=_git_env(ws.root))
    except (OSError, subprocess.TimeoutExpired):
        return out
    if tracked.returncode == 0 and not tracked.stdout.strip():
        out.append(Finding(WARNING, "preferences", PREFERENCES_FILE,
                           "the choices kept here are not in the workspace's history, so a restore loses them; "
                           "`git add` it and commit it",
                           "The settings file is not committed"))
    return out


# The review record, System/nurture-review.md (#258): the nurture skill's
# guided review keeps its decisions there, in the root repository, which no
# wall hook checks. So each cell is one of a fixed few, and nothing in it can
# carry a file name, an answer or a reason in someone's words.
REVIEW_RECORD = "System/nurture-review.md"
REVIEW_KEY_RE = re.compile(r"^[0-9a-f]{12}$")            # nurture.py's key for a finding
REVIEW_TOOLS = ("check.py", "wiki_lint.py", "drift.py", "fade.py")
REVIEW_SOURCES = REVIEW_TOOLS + ("audit",)
REVIEW_DECISION_RE = re.compile(r"^(?:fixed [0-9a-f]{7,40}|answered|deferred to \d{4}-\d{2}-\d{2}|skipped|source failed)$")
REVIEW_REASONS = ("another session holds the file", "waiting on someone", "needs the user's own records",
                  "source did not run", "not now")
REVIEW_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REVIEW_COUNTS = ("fixed", "answered", "deferred")       # the frontmatter's counts, which the status page shows


def check_review(ws: Workspace) -> List[Finding]:
    """Each row of the review record's table is an Id that is a key from
    `nurture.py --json`, or the tool's name for a source that did not run; a
    Source of tool names; a Decision and a Reason from the fixed sets; and a
    date; and in the frontmatter, `fixed`, `answered` and `deferred`, where
    given, are whole numbers. A finding names the row and the column, or the
    key, never what the cell says."""
    out = []
    text = read_text(ws.root / REVIEW_RECORD)
    if text is None:
        return out
    fm = parse_frontmatter_text(text)
    for key in REVIEW_COUNTS:
        if key in fm and fm[key] not in (None, "") and not re.fullmatch(r"\d+", str(fm[key]).strip(), re.ASCII):
            out.append(Finding(WARNING, "review", REVIEW_RECORD,
                               "`%s` in the frontmatter is not a whole number; it counts decisions and holds "
                               "nothing else" % key, "A count in the review record is not a number"))
    row = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and (cells[0] == "Id" or set("".join(cells)) <= set("-: ")):
            continue                                   # the header and the line under it
        row += 1
        wrong = []
        if len(cells) != 5:
            wrong.append("does not have the five columns Id, Source, Decision, Reason and Date")
        else:
            key, source, decision, reason, date = cells
            failed = decision == "source failed"
            if not (key in REVIEW_TOOLS if failed else REVIEW_KEY_RE.match(key)):
                wrong.append("has an Id that is not a key from `nurture.py --json`"
                             + (", nor the name of the tool that did not run" if failed else ""))
            if not all(s.strip() in REVIEW_SOURCES for s in source.split(",")):
                wrong.append("has a Source that is not %s" % ", ".join(REVIEW_SOURCES))
            if not REVIEW_DECISION_RE.match(decision):
                wrong.append("has a Decision that is not fixed and a commit, answered, deferred to a date, "
                             "skipped or source failed")
            if reason and reason not in REVIEW_REASONS:
                wrong.append("has a Reason that is not one of the skill's own")
            if not REVIEW_DATE_RE.match(date):
                wrong.append("has a Date not written YYYY-MM-DD")
        for problem in wrong:
            out.append(Finding(WARNING, "review", REVIEW_RECORD,
                               "row %d %s; the record holds keys and fixed words only, and an answer goes into "
                               "the files it changes" % (row, problem),
                               "A row of the review record is outside its fixed form"))
    return out


def check_updates(ws: Workspace) -> List[Finding]:
    """An update leaves Garrick's newer version of a file you changed beside it,
    as `<name>.new`, for you and your assistant to merge. Until then the file
    keeps the older version's wording. Only files Garrick ships can have one:
    those the version stamp lists, and System/rules.md. A stamp with no list,
    from before 0.4.0 and not yet updated, means walking the workspace."""
    out = []
    stamp_path = ws.root.joinpath(*VERSION_STAMP)
    stamp = read_version(ws.root)
    if stamp_path.is_file() and not stamp:
        out.append(Finding(WARNING, "updates", "/".join(VERSION_STAMP),
                           "does not read as JSON; `check.py --version` cannot say which Garrick this is, and an "
                           "update cannot tell your changes from Garrick's",
                           "The version stamp cannot be read"))
    files = stamp.get("files")
    if isinstance(files, dict):
        # Garrick's own code is changed in Garrick, never here: an update
        # would find the change and leave its newer version beside it.
        prefixes = ws.settings.get("as-shipped", AS_SHIPPED)
        for path, want in sorted(files.items()):
            if not isinstance(want, str) or not any(path.startswith(p) for p in prefixes):
                continue
            here = ws.root / path
            try:
                have = fingerprint(here) if here.is_file() else None
            except OSError:
                have = None
            if have is None:
                out.append(Finding(WARNING, "updates", path,
                                   "is missing; it is Garrick's, so take it back from an update",
                                   "A file Garrick ships is missing"))
            elif have != want:
                out.append(Finding(WARNING, "updates", path,
                                   "differs from what Garrick shipped; it is Garrick's, so change it in Garrick instead, "
                                   "or the next update leaves its version beside yours as .new",
                                   "A file Garrick ships was changed here"))
    if isinstance(files, dict):
        candidates = sorted(set(files) | {"System/rules.md"})
    else:
        candidates = sorted(rel(ws, new.with_suffix("")) for new in walk_files(ws.root)
                            if new.suffix == ".new" and new.with_suffix("").is_file())
    for path in candidates:
        if (ws.root / (path + ".new")).is_file():
            out.append(Finding(WARNING, "updates", path + ".new",
                               "Garrick's newer %s waits to be merged into yours; merge it, then delete the .new "
                               "(say \"update Garrick\")" % path,
                               "An update left a file to merge"))
    # Garrick's lines in a .gitignore sit between its markers, and an update
    # replaces them: a line changed there is lost at the next one. A file with
    # no block yet gets one from the next update, its own lines kept.
    for path, lines in sorted(garrick_ignores([z.name for z in ws.zones]).items()):
        try:
            text = (ws.root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        inside = ignore_parts(text)[1]
        if inside is not None and [x.rstrip() for x in inside] != lines.rstrip("\n").splitlines():
            out.append(Finding(WARNING, "updates", path,
                               "the lines between Garrick's markers differ from what Garrick ships, and the next "
                               "update puts Garrick's back; move your own lines outside the markers",
                               "A .gitignore has changes inside Garrick's block"))
    return out


# The checks a run over named paths makes whole, because each reads a handful of
# fixed files and walks no notes (run_path_checks).
PATH_CHECKS = [check_instructions, check_settings, check_context, check_skills]


ALL_CHECKS = [
    check_claude_md, check_instructions, check_settings, check_placeholders, check_context, check_memory, check_zones,
    check_hooks,
    check_skills, check_names, check_projects, check_threads, check_resume, check_deliverables, check_anonymous,
    check_todo, check_questions, check_decisions, check_links, check_meetings, check_people, check_walls, check_sources, check_inbox, check_knowledge,
    check_raw, check_generated, check_recall, check_preferences, check_review, check_updates,
]


def run_checks(root: Path, walls_only: bool = False, staged: Optional[Path] = None, quick: bool = False) -> List[Finding]:
    """Every check, or with `walls_only` the walls check alone. With `staged`, a
    folder inside a git repository, the walls check alone on what it has staged.
    With `quick`, every check but the comparison of wording: whether a project
    file, a person page or a Knowledge page repeats a meeting. That comparison
    reads every meeting and project file, and is most of the time a full check
    takes on a large workspace; the commit hook still runs it on what is staged."""
    _committing(Path(staged) if staged is not None else None)
    _BLOBS.clear()
    cache = NoteCache.for_repo(Path(staged)) if staged is not None else None
    ws = discover(Path(root).resolve(), cache)
    ws.quick = quick and staged is None
    findings: List[Finding] = []
    if staged is not None:
        findings = check_walls_staged(ws, Path(staged))
        cache.save()
    else:
        for check in ([check_walls] if walls_only else ALL_CHECKS):
            try:
                findings.extend(check(ws))
            except Exception as e:      # one check that trips over a file must not stop the others
                name = check.__name__.replace("check_", "", 1)
                findings.append(Finding(ERROR, name, "", "the check stopped: %s: %s" % (type(e).__name__, e),
                                        "A check stopped before it finished"))
    order = {c: i for i, (c, _) in enumerate(CHECKS)}
    findings.sort(key=lambda f: (order.get(f.check, 99), f.severity != ERROR, f.path, f.message))
    return findings


def run_path_checks(root: Path, paths: List[str]) -> List[Finding]:
    """The findings a whole run reports for the named files (root-relative), and
    no others, without reading the rest of the workspace (#412): what an update
    asks of the files it wrote.

    It makes four kinds of check. The placeholders check, on those files alone.
    The instructions, settings, context and skills checks, whole, since each
    reads a few fixed files and walks no notes. The walls check, per file
    (walls_for_file and form_findings, the readings of the full run), for a
    file in a project or in a wiki; only then are the wiki pages and the
    meetings indexed. A path under a zone or a wiki that is not a zone's
    instruction file is read as a project file would be, never passed over.

    It does not run what only a whole run can see: a finding that rests on the
    notes round a file (links, meetings, people, knowledge, raw records, inboxes,
    the history), nor check_claude_md and check_updates, which look for files
    that an update does not write. A caller that needs those runs the whole check."""
    _BLOBS.clear()
    root = Path(root).resolve()
    ws = discover(root, None, light=True)
    wanted = {Path(p).as_posix() for p in paths}
    files = [root / p for p in sorted(wanted)]
    findings: List[Finding] = []
    for check in PATH_CHECKS:
        try:
            findings.extend(check(ws))
        except Exception as e:
            name = check.__name__.replace("check_", "", 1)
            findings.append(Finding(ERROR, name, "", "the check stopped: %s: %s" % (type(e).__name__, e),
                                    "A check stopped before it finished"))
    try:
        findings.extend(check_placeholders(ws, files))
    except Exception as e:
        findings.append(Finding(ERROR, "placeholders", "", "the check stopped: %s: %s" % (type(e).__name__, e),
                                "A check stopped before it finished"))
    wikis = root / "Wikis"
    areas = [wikis] + list(ws.zones)
    reads = [f for f in files if f.is_file() and not f.is_symlink() and any(a in f.parents for a in areas)
             and (f.name != "AGENTS.md" or project_of(ws, f) is not None or wikis in f.parents)]
    if reads:
        try:
            ws = discover(root, None)            # the walls read the meetings and the wiki pages
            for f in reads:
                owner = project_of(ws, f)
                if owner is None or f.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                text = read_text(f)
                project, pfm = owner
                ptags = {strip_tag(t) for t in as_list(pfm.get("party"))}
                if text and not (in_system(ws, project) and not ptags):
                    findings.extend(walls_for_file(ws, project, ptags, f, text))
            findings.extend(form_findings(ws, [(f, None) for f in reads if f.suffix.lower() == ".md"]))
        except Exception as e:
            findings.append(Finding(ERROR, "walls", "", "the check stopped: %s: %s" % (type(e).__name__, e),
                                    "A check stopped before it finished"))
    findings = [f for f in findings if f.path in wanted or not f.path]
    order = {c: i for i, (c, _) in enumerate(CHECKS)}
    findings.sort(key=lambda f: (order.get(f.check, 99), f.severity != ERROR, f.path, f.message))
    return findings


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def _counts(findings: List[Finding]) -> Tuple[int, int]:
    errors = sum(1 for f in findings if f.severity == ERROR)
    return errors, len(findings) - errors


def _plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def report_text(findings: List[Finding], root: Path) -> str:
    lines = ["Garrick check: %s" % root, ""]
    titles = dict(CHECKS)
    current = None
    for f in findings:
        if f.check != current:
            if current is not None:
                lines.append("")
            lines.append(titles.get(f.check, f.check))
            current = f.check
        lines.append("  %-7s %s: %s" % (f.severity, f.path, f.message))
    if findings:
        lines.append("")
    errors, warnings = _counts(findings)
    if not findings:
        lines.append("No problems found.")
    else:
        lines.append("%s, %s." % (_plural(errors, "error"), _plural(warnings, "warning")))
    return "\n".join(lines)


def report_ear(findings: List[Finding]) -> str:
    """At most three short sentences, answer first."""
    errors, warnings = _counts(findings)
    if not findings:
        return "All clear."
    if errors:
        head = "%s problem%s" % (say(errors), "" if errors == 1 else "s")
        if warnings:
            head += " and %s warning%s" % (say(warnings).lower(), "" if warnings == 1 else "s")
    else:
        head = "No problems, %s warning%s" % (say(warnings).lower(), "" if warnings == 1 else "s")
    sentences = [head + "."]

    groups: List[Tuple[str, List[Finding]]] = []
    for sev in (ERROR, WARNING):
        for check, _ in CHECKS:
            members = [f for f in findings if f.check == check and f.severity == sev]
            if members:
                groups.append((check, members))

    def spoken(group: Tuple[str, List[Finding]]) -> str:
        check, members = group
        if len(members) == 1 and members[0].ear:
            text = members[0].ear
        else:
            text = EAR_GROUP[check].format(n=say(len(members)).lower())
        return text[0].upper() + text[1:] + "."

    if len(groups) <= 2:
        sentences += [spoken(g) for g in groups]
    else:
        rest = sum(len(m) for _, m in groups[1:])
        sentences.append(spoken(groups[0]))
        sentences.append("%s more in the full report." % say(rest))
    return " ".join(sentences[:3])


# What a refusal ends with: the fix for its own kind of finding, never a fix that does not apply. The first
# phrase that a finding's message holds picks it; every one ends in "commit again", which the status page's
# commit actions read to tell a wall's refusal from any other line (extras/status/page_action.py).
TAKE_OUT = "Take it out and commit again; only if you mean it, git commit --no-verify."
STAGED_FIXES = (
    # a project with no party, or a hub that names none the table holds: the fix is the hub's, not the file's
    (("has no party to check the walls against", "no party the Parties table holds", "whose hub names no party",
      "before the project has a party"),
     "Name a party in the project's hub (`party:`), then commit again."),
    # a party changed on disk and not staged: the two must agree
    (("on disk from the one staged", "on disk from the ones staged"),
     "Stage that change or undo it, then commit again."),
    # a file that names no party, nothing says whose it is: label what it belongs to, or leave it out
    (("a file that names no party", "that no page cites"),
     "Name a party for it, or take the mention out, and commit again."),
    # a page not finished, or a mail not yet answered: finish it first
    (("an unfinished", "not filed until the user has answered"),
     "Finish or file it first, or take the mention out, and commit again."),
    # a finding that cannot be read, or that is not a crossing: the message holds the fix
    (("cannot be read", "cannot be checked", "cannot be placed", "cannot read it", "not checked", "symbolic link", "submodule",
      "is reserved", "was not read", "write each key once", "rename `parties:`", "name a party or zone"),
     "Make that change, then commit again."),
)


def staged_fix(message: str) -> str:
    """The end of one refusal line: the fix that belongs to this finding."""
    low = message.lower()
    if "is walled and" not in low and "repeats wording" not in low:
        for phrases, fix in STAGED_FIXES:
            if any(p.lower() in low for p in phrases):
                return fix
        if "so the walls" in low or "the walls cannot" in low or "until it does" in low:
            return "Make that change, then commit again."
    return TAKE_OUT


def report_staged(findings: List[Finding]) -> str:
    """For the pre-commit hook: one plain line per wall broken, nothing when clear."""
    return "\n".join(
        "Commit refused: %s %s. %s" % (f.path, f.message, staged_fix(f.message))
        for f in findings if f.severity == ERROR)


def install_hooks(root: Path) -> int:
    """The wall check in every zone's repository, in each wiki that is a
    repository, and in every repository inside a project, which checks its staged files against the walls of the
    project's party, as a zone's does."""
    ws = discover(root)
    code = 0
    for zone in ws.zones:
        try:
            hook = install_wall_hook(zone)
            print("%s: wall check installed at %s" % (zone.name, rel(ws, hook)))
        except (FileExistsError, FileNotFoundError) as exc:
            print("%s: %s" % (zone.name, exc), file=sys.stderr)
            code = 1
    for wiki in wiki_repos(ws):
        try:
            hook = install_wall_hook(wiki, wiki=True, root=ws.root)
            print("%s: wall check installed at %s" % (rel(ws, wiki), rel(ws, hook)))
        except (FileExistsError, FileNotFoundError) as exc:
            print("%s: %s" % (rel(ws, wiki), exc), file=sys.stderr)
            code = 1
    for repo, project, pfm in project_repos(ws):
        parties = ", ".join(strip_tag(t) for t in as_list(pfm.get("party"))) or "no party"
        try:
            hook = install_wall_hook(repo, nested=True)
            print("%s: wall check installed at %s, on %s's side" % (rel(ws, repo), rel(ws, hook), parties))
        except (FileExistsError, FileNotFoundError) as exc:
            print("%s: %s" % (rel(ws, repo), exc), file=sys.stderr)
            code = 1
    return code


def report_json(findings: List[Finding], root: Path) -> str:
    errors, warnings = _counts(findings)
    return json.dumps({"root": str(root), "errors": errors, "warnings": warnings,
                       "findings": [asdict(f) for f in findings]}, indent=2)


def walls_cases(root: Path) -> int:
    """`--walls-cases`: the decide() rows of System/tools/walls-cases.md, run
    against this workspace's Parties table. 0 when each row run
    gives its expected answer, 1 when one does not, 2 when there is no table."""
    path = root / "System" / "tools" / "walls-cases.md"
    text = read_text(path)
    if text is None:                    # run from a Garrick clone, on a workspace that has not been updated yet
        path = Path(__file__).resolve().with_name("walls-cases.md")
        text = read_text(path)
    if text is None:
        print("check: %s is missing, so there are no cases to run" % path.relative_to(root).as_posix(), file=sys.stderr)
        return 2
    ran, skipped, failed = run_wall_cases(load_context(root), text)
    print("%d wall cases run against this workspace's Parties table, %d failed, %d skipped."
          % (ran, len(failed), len(skipped)))
    for line in failed:
        print("  failed  " + line)
    for line in skipped:
        print("  skipped " + line + ": the tables hold no tag for that role")
    roles = wall_roles(load_context(root))
    if "near" not in roles or "far" not in roles:
        print("  no wall row ran: the Parties table holds fewer than two walled parties, so nothing was "
              "checked about walls")
        return 1
    return 1 if failed or not ran else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check a Garrick workspace against its rules.")
    parser.add_argument("--root", help="workspace root (default: the workspace this script sits in, else the current folder's)")
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument("--ear", action="store_true", help="at most three short sentences, for reading aloud")
    fmt.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--walls-only", action="store_true", help="run the walls check alone")
    parser.add_argument("--quick", action="store_true",
                        help="leave out the comparison of wording with the meetings, the slow part on a large workspace")
    parser.add_argument("--paths", nargs="+", metavar="PATH",
                        help="report only the findings for these files (relative to the root), reading no more of "
                             "the workspace than they need; what an update asks of the files it wrote")
    parser.add_argument("--staged", action="store_true",
                        help="check only the files staged in the current folder's git repository (implies --walls-only)")
    parser.add_argument("--install-hooks", action="store_true",
                        help="install the pre-commit wall check in every zone's repository, and in each repository inside a project")
    parser.add_argument("--walls-cases", action="store_true",
                        help="run the table of wall cases (System/tools/walls-cases.md) against this workspace's own "
                             "Parties table, with its tags in place of the fixture's")
    parser.add_argument("--version", action="store_true",
                        help="say which Garrick the workspace was installed from, for a bug report")
    args = parser.parse_args(argv)

    try:
        if args.root:
            root = Path(args.root).expanduser().resolve()
            if not (root / "System" / "rules.md").is_file():
                root = workspace_root(root)
        else:
            try:
                root = workspace_root(Path(__file__).resolve().parent)
            except FileNotFoundError:
                root = workspace_root()
    except FileNotFoundError as exc:
        print("check: %s" % exc, file=sys.stderr)
        return 2

    if args.install_hooks:
        return install_hooks(root)
    if args.walls_cases:
        return walls_cases(root)
    if args.version:
        stamp = read_version(root)
        print(" ".join(s for s in (say_version(stamp), say_changes(root, stamp)) if s))
        newer = say_newer_release(root)        # what GitHub last said, kept on disk; the check never asks
        if newer:
            print(newer)
        return 0
    if args.paths:
        findings = run_path_checks(root, args.paths)
    else:
        findings = run_checks(root, walls_only=args.walls_only, staged=Path.cwd() if args.staged else None, quick=args.quick)
    if args.staged and not (args.json or args.ear):
        text = report_staged(findings)
        if text:
            print(text, file=sys.stderr)
    elif args.json:
        print(report_json(findings, root))
    elif args.ear:
        print(report_ear(findings))
    else:
        print(report_text(findings, root))
    return 1 if any(f.severity == ERROR for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
