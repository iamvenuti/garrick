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
from array import array
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

sys.dont_write_bytecode = True  # keep System/tools free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))

from garrick_lib import (  # noqa: E402
    SKIP_DIRS,
    is_checkout,
    live_files,
    nested_repo,
    CHECKPOINT_DAYS,
    CHECKPOINT_HEADING,
    CHECKPOINT_LABELS,
    CHECKOUT_TREE,
    CHECKPOINT_KINDS,
    CHECKPOINT_ONE,
    CHECKPOINT_SAID,
    CHECKPOINT_UNCONFIRMED,
    CONTEXT_TABLES,
    INBOX,
    parse_mail_bytes,
    UNZONED,
    may_flow,
    walled,
    zone_from_frontmatter,
    zone_of,
    LOCAL_HEADER,
    PREFERENCES_FILE,
    SKILL_FOLDERS,
    VERSION_STAMP,
    MEDIA_EXTS,
    WALL_HOOK_MARK,
    as_sources,
    has_wall_hook,
    has_merge_hooks,
    missing_merge_hooks,
    foreign_merge_hooks,
    merge_hook_advice,
    MergeHookNotGarricks,
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
    load_context,
    run_wall_cases,
    zone_roles,
    local_file,
    parse_frontmatter,
    read_settings,
    parse_frontmatter_text,
    read_checkpoint,
    read_version,
    resume_hash,
    said_time,
    say_changes,
    say_newer_release,
    say_version,
    spoken_clash,
    spoken_of,
    stale_bands,
    strip_recipients,
    strip_tag,
    record_refusals,
    refusal_kind,
    ALLOW_RULES,
    allow_add,
    allow_commit,
    allow_finding_id,
    allow_may_write,
    allow_remove,
    allow_stray,
    allow_set,
    work_folder,
    workspace_root,
)
from garrick_lib import (  # noqa: E402
    TODO_ALSO_RE,
)
from garrick_lib import _frontmatter_body  # noqa: E402  (#388)
from garrick_lib import (  # noqa: E402  (#330)
    FRONTMATTER_PLAIN, PERSON_KEYS, PERSON_SHAPE, WALLS_KEYS, WIKI_GIT_REASON, frontmatter_form_problem,
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
    ("cmux", "cmux"),
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
    "cmux": "cmux does not resume the tabs of agent sessions",
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
    fid: str = ""       # the allow-once id, kept from the finding as found when its words are rewritten for an assistant
    token: str = ""     # what the allow-once id is taken over besides path and kind; the message when empty


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
    ref_files: Optional[Dict[str, List[Path]]] = None  # every file a note may point at, by its path, on first use
    ref_wikis: List[Path] = field(default_factory=list)  # each wiki's top folder, set with ref_files
    project_files: Optional[Dict[Path, Path]] = None  # each of those files -> its project
    thread_owners: Optional[Dict[str, set]] = None  # a thread's name, lower case -> the projects that have one
    wiki_links: Optional["PathIndex"] = None  # every wiki page, indexed for links on first use
    project_norm: Optional[tuple] = None  # (count, normalised project path -> (project, hub fields)), on first use
    vault_files: Dict[Path, Dict[str, List[str]]] = field(default_factory=dict)  # each vault's files by name, on first use
    git_view: Dict[Path, str] = field(default_factory=dict)  # staged mode: what git holds, where the disk differs
    settings: dict = field(default_factory=dict)  # System/garrick-checks.json, as far as it reads
    settings_problems: List[str] = field(default_factory=list)  # what in it could not be read
    quick: bool = False  # --quick: leave out the comparison of wording
    zone_notes: Optional[List[Tuple[Path, str]]] = None  # every live note in the zones, read on first use
    ignored: Optional[set] = None  # what the workspace's repositories ignore, listed on first use
    shared_links: Optional["PathIndex"] = None  # the shared files, indexed for links on first use
    template_labels: Optional[tuple] = None     # (test, fingerprint) of the labels the installed templates hold
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
    parties, so unzoned, when the frontmatter can be read two ways
    (frontmatter_form_problem), since a YAML reader may find another zone
    there. Fail closed: nothing on it is used until then."""
    problem = frontmatter_form_problem(text) if text is not None else note_form(ws, page)
    if not problem:
        return fm
    ws.misread.add(page)
    ws.meeting_raw.setdefault(page, fm)           # what the page's own checks name
    return {k: v for k, v in fm.items() if k not in ("parties", "zone")}


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
# The user's own templates, beside the ones Garrick ships: a source of common wording as those are (#470).
TEMPLATES_LOCAL = ("System", "templates.local")


def is_template_path(ws: Workspace, path: Path) -> bool:
    """A template, whose placeholder marks are there for a script to fill: anything
    under System/templates/, or in a folder under Zones/ whose name starts
    with an underscore (`_project`). The originals a Garrick checkout ships
    are never asked about: the checks leave a checkout out whole."""
    parts = Path(rel(ws, path)).parts
    if parts[:2] in (TEMPLATES, TEMPLATES_LOCAL):
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
        elif seen["missing"]:
            out.append(Finding(WARNING, "context", ctx_path,
                               "the %s table has no %s column; it needs %s" % (
                                   title, " or ".join(c.capitalize() for c in seen["missing"]), wanted),
                               "The %s table is missing a column" % title))
    text = read_text(ws.root / ctx_path) or ""
    if re.search(r"(?m)^## Walls\s*$", text):
        out.append(Finding(WARNING, "context", ctx_path,
                           "a Walls table is still there, and nothing reads it; the Walled column of the Zones table holds the policy. "
                           "Take the section out",
                           "A Walls table is left in the context file"))
    if not parties and "parties" not in unread:
        out.append(Finding(WARNING, "context", ctx_path, "the Parties table is empty; no wall can be checked",
                           "The Parties table is empty"))
    if not ws.context["pending"]:
        for zone, flag in sorted(ws.context["zone_flags"].items()):
            if flag not in ("yes", "no"):
                out.append(Finding(WARNING, "context", ctx_path,
                                   "zone %s has no `yes` or `no` in Walled; it is read as walled" % zone,
                                   "The %s zone has no Walled flag" % zone))
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
        elif (zone / ".git").is_dir() and not has_merge_hooks(zone):
            out.append(merge_hooks_finding(ws, zone, "zone"))
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
        elif git_dir.is_dir() and not has_merge_hooks(wiki):
            out.append(merge_hooks_finding(ws, wiki, "wiki"))
    return out


def merge_hooks_finding(ws: Workspace, repo: Path, what: str) -> Finding:
    """A repository with Garrick's pre-commit hook and without its merge hooks: a merge that completes on its own
    runs no pre-commit hook, so the walls are not checked on what it brings in (#497)."""
    names = ", ".join(missing_merge_hooks(repo))
    foreign = [n for n in foreign_merge_hooks(repo) if n in missing_merge_hooks(repo)]
    fix = ("a hook of yours is in the place of %s, which --install-hooks leaves alone: %s" % (", ".join(foreign), merge_hook_advice(foreign))
           if foreign else "run `python3 System/tools/check.py --install-hooks`")
    return Finding(WARNING, "zones" if what != "project repository" else "hooks", rel(ws, repo),
                   "has the pre-commit wall check but not %s, so a merge, a fast-forward or a rebase brings changes in "
                   "with no wall check; %s" % (names, fix),
                   "The %s %s does not check the walls when a merge brings changes in" % (repo.name, what))


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


CMUX_CONFIG = (".config", "cmux", "cmux.json")


def _without_json_comments(text: str) -> str:
    """`text` with `//` and `/* */` comments taken out, outside strings: cmux.json may be JSONC."""
    return re.sub(r'"(?:[^"\\]|\\.)*"|//[^\n]*|/\*.*?\*/', lambda m: m.group(0) if m.group(0)[0] == '"' else " ", text, flags=re.S)


def check_cmux(ws: Workspace) -> List[Finding]:
    """cmux resumes the agent sessions of its tabs itself when it reopens (`terminal.autoResumeAgentSessions`, on by
    default). Warn once when `~/.config/cmux/cmux.json` turns it off: nothing resumes the tabs then (#440)."""
    if not (ws.root / "System" / "cmux").is_dir():
        return []                                # only a workspace with the cmux extra: no other run reads the home folder
    path = Path(os.path.expanduser("~")).joinpath(*CMUX_CONFIG)
    try:
        data = json.loads(_without_json_comments(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []
    nested = data.get("terminal") if isinstance(data, dict) else None
    value = nested.get("autoResumeAgentSessions") if isinstance(nested, dict) else None
    if isinstance(data, dict) and "terminal.autoResumeAgentSessions" in data:
        value = data["terminal.autoResumeAgentSessions"]
    if value is not False:
        return []
    return [Finding(WARNING, "cmux", "~/" + "/".join(CMUX_CONFIG),
                    "turns `terminal.autoResumeAgentSessions` off, so cmux does not resume the agent sessions of its tabs "
                    "when it reopens; set it to true, or delete the key", "cmux does not resume the tabs of agent sessions")]


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
        if (repo / ".git").is_dir() and has_wall_hook(repo) and not has_merge_hooks(repo):
            out.append(merge_hooks_finding(ws, repo, "project repository"))
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
    return out


def check_history(ws: Workspace) -> List[Finding]:
    """A hub or thread note over `note-max-words`, and a Resume here block over `resume-max-words` (#502): each
    finding names the note, its words and the limit. The first is mechanical (history.py moves the older dated
    entries); the second is a rewrite that only the user's yes makes."""
    try:
        import history
    except ImportError:
        return []
    cap = history.limits(ws.root)
    out: List[Finding] = []
    for project, fm in ws.projects:
        notes = [("projects", project / (project.name + ".md"), project.name)]
        notes += [("threads", t / (t.name + ".md"), "%s, %s" % (project.name, t.name)) for t in visible_dirs(project / "Threads")]
        for name, note, spoken in notes:
            text = read_text(note) if note.is_file() else None
            if not text:
                continue
            words = history.note_words(text)
            if words > cap["note-max-words"]:
                out.append(Finding(WARNING, name, rel(ws, note), history.note_over(words, cap["note-max-words"]),
                                   "%s is %d words long, over its limit of %d" % (spoken, words, cap["note-max-words"])))
            block = history.resume_words(text)
            if block > cap["resume-max-words"]:
                out.append(Finding(WARNING, "resume", rel(ws, note), history.resume_over(block, cap["resume-max-words"]),
                                   "The resume point of %s is %d words long, over its limit of %d"
                                   % (spoken, block, cap["resume-max-words"])))
    return out


MEETING_MAX_WORDS = 450


def check_concise_pages(ws: Workspace) -> List[Finding]:
    """A meeting or mail page over `meeting-max-words` words of body (450 unless the settings say), for the pages
    filed on or after the day `meetings-concise` names in System/garrick-settings.json, the day the user turned the
    concise format on (#479). Without that key the check says nothing, and a page filed before it never counts. A
    page's filed day is its `created:`."""
    settings = read_settings(ws.root)
    try:
        start = datetime.date.fromisoformat(str(settings.get("meetings-concise") or "").strip())
    except ValueError:
        return []
    limit = settings.get("meeting-max-words")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        limit = MEETING_MAX_WORDS
    out: List[Finding] = []
    for page, fm in sorted(ws.meetings.items()):
        if fm.get("type") not in ("meeting", "email"):
            continue
        try:
            filed = datetime.date.fromisoformat(str(fm.get("created") or "").strip())
        except ValueError:
            continue
        if filed < start:
            continue
        words = len(body_of(read_text(page) or "").split())
        if words > limit:
            out.append(Finding(WARNING, "meetings", rel(ws, page),
                               "its body is %d words, over the %d of `meeting-max-words`; a page is one line on who was there, "
                               "`## Key points` and `## Actions`, about 350 words" % (words, limit),
                               "A meeting page is %d words long, over its limit of %d" % (words, limit)))
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
    folders. A note may name a file one project over,
    `Deliverables/<deck>.pptx` of the project the work goes on from. Never a
    project outside the zone, nor one under System/; sibling_found holds every
    hit to the same. Worked out once per note; the third part caches each sibling's
    files as they are named on disk, listed on its first hit."""
    zone = project.parent
    if zone not in ws.zones:
        return set(), [], {}
    out: List[Tuple[Path, Path]] = []
    for other, _ in ws.projects:
        if other.parent != zone or other == project:
            continue
        out.append((other, other))
        out.extend((thread, other) for thread in visible_dirs(other / "Threads"))
    return set(), out, {}


def sibling_found(ws: Workspace, siblings: Siblings, path: str) -> bool:
    """Is `path` a file of a sibling project, read from one of its bases? Its
    real path must be one of that project's files as they are named on disk,
    in a project folder that sits in the zone: so a link or `..` leading into
    another zone confirms nothing, and nor does a path or a link spelt in
    another case, which a case-insensitive disk opens but which would read as
    no thread; a folder, every file in it."""
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
        if files:
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


def _anonymous_forms(ws: Workspace, tags: set) -> List[str]:
    """The names of the parties in `tags` that an anonymous project keeps out of its deliverables, as word runs: a
    party's name, a person of it by full name, an alias that means either, and its domains as they are written. A
    tag is not looked for: it can be an everyday word. Used by this check alone; no wall reads a name."""
    forms: List[str] = []
    names = set()
    for tag in tags:
        row = ws.context["parties"].get(tag) or {}
        names.add(" ".join(words(row.get("party") or "")))
        forms += [d.lower() for d in row.get("domains", [])]
    for person in ws.context["people"]:
        if person["party"] in tags and len(words(person["name"])) > 1:
            names.add(" ".join(words(person["name"])))
    for heard, means in ws.context["aliases"].items():
        if " ".join(words(means)) in names:
            names.add(" ".join(words(heard)))
    return sorted(n for n in names if n) + forms


def _names_any(text: str, forms: List[str]) -> bool:
    """Does `text` hold any of `forms`: a word run on word boundaries, or a domain as written?"""
    padded = " " + " ".join(words(text)) + " "
    lower = text.lower()
    return any((" %s " % f in padded) if " " in f or "." not in f else f in lower for f in forms)


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
        forms = _anonymous_forms(ws, others) + [" ".join(words(n)) for n in extra if words(n)]
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
                if _names_any(text, forms):
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
                out += zone_findings(ws, "questions", rel(ws, f), ws.meeting_raw.get(f, ws.meetings[f]), "Meetings question",
                                      "ask it once for each side")
                if party_keys_problem(read_text(f) or ""):
                    out.append(Finding(WARNING, "questions", rel(ws, f), "carries both `party` and `parties`, or spells one in "
                                       "capitals, which a reader could take two ways; the walls read `parties:` alone, so it "
                                       "is placed nowhere", "A Meetings question names its parties two ways"))
        for f in wiki_answers(wiki):
            if f in ws.meeting_answers:
                out += zone_findings(ws, "questions", rel(ws, f), ws.meeting_raw.get(f, ws.meetings[f]), "Meetings answer",
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
        out += zone_findings(ws, "decisions", r, fm, "Meetings decision", "decide it once for each zone")
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
                        if p.suffix.lower() == ".md" and not {"Deliverables", "Sources", "history"} & set(p.relative_to(project).parts)]
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


def zone_findings(ws: Workspace, code: str, r: str, fm: dict, what: str, apart: str) -> List[Finding]:
    """The zone the walls read on a Meetings page or question (`what`): there, a zone of the workspace, and one
    only, for which `apart` is the fix when two are named."""
    zone_names = {z.name for z in ws.zones} | set(ws.context["zones"])
    zone = fm.get("zone")
    if not zone:
        return [Finding(WARNING, code, r, "unfinished: no zone; nothing on it may be used in a project",
                        "One %s has no zone" % what)]
    named = [z.strip() for z in (zone if isinstance(zone, list) else re.split(r"\s*,\s*", str(zone))) if z.strip()]
    if len(named) > 1:
        return [Finding(WARNING, code, r, "names more than one zone, so no zone may use it; " + apart,
                        "A %s names more than one zone" % what)]
    if zone_names and named and named[0] not in zone_names:
        return [Finding(WARNING, code, r, "`zone` %s is not a zone" % named[0], "A %s names an unknown zone" % what)]
    return []


def check_meeting_zones(ws: Workspace) -> List[Finding]:
    """Every page of the Meetings wiki carries one `zone:` (#481). A source page with none, or two, is unfinished.
    An entity or people page takes the zone of the sources it cites, or, a people page with none, of its party's row
    in the Parties table, and is reported with that zone proposed. A page whose sources are in two walled zones is
    reported with its split as the fix: one page per zone, each citing only that zone's sources. A source in an open
    zone forces no split. Read by `party:` nowhere: it only proposes. While the migration to zone walls waits (the
    context is `pending`), an entity or people page with no zone is not asked about: the migration lists them."""
    out = []
    for page, fm in ws.meetings.items():
        if not (is_faded(ws, page) or page in ws.meeting_questions):
            out += zone_findings(ws, "meetings", rel(ws, page), ws.meeting_raw.get(page, fm), "meeting page",
                                 "if it was two conversations, file them as two pages")
    if ws.meeting_links is None:
        ws.meeting_links = meeting_index(ws)
    for page, kind in sorted(page_names(ws).kinds.items()):
        if kind not in ("person page", "entity page") or page.suffix.lower() != ".md" or is_faded(ws, page):
            continue
        text = read_text(page) or ""
        fm = parse_frontmatter_text(text) if text else parse_frontmatter(page)
        own = zone_from_frontmatter(ws.root, fm)
        cited = {m for _, target in extract_links(text) for m in resolve(ws, page, target, ws.meeting_links) if m in ws.meetings}
        cited -= ws.meeting_questions
        zones = {zone_from_frontmatter(ws.root, ws.meetings[m]) for m in cited}
        closed = {z for z in zones | ({own} if own != UNZONED else set()) if walled(ws.context, z)}
        r = rel(ws, page)
        what = "A %s" % kind
        if len(closed) > 1:
            out.append(Finding(WARNING, "meetings", r,
                               "cites sources of %s, which are walled from each other, so no zone may use it; split it into one "
                               "page per zone, each citing only the sources of its zone" % " and ".join(sorted(closed)),
                               "%s draws on two walled zones" % what))
        elif own == UNZONED and not fm.get("zone") and not ws.context["pending"]:       # until the migration, none is asked
            by_sources = {z for z in zones if z != UNZONED}
            # an open source forces no split: with one walled zone among the sources, it is that one
            candidates = {z for z in by_sources if walled(ws.context, z)} or by_sources
            proposal = next(iter(candidates)) if len(candidates) == 1 else party_zone(ws, fm) if not by_sources else UNZONED
            if proposal != UNZONED:
                out.append(Finding(WARNING, "meetings", r,
                                   "no `zone:`; %s, so it takes %s" % (
                                       "the sources it cites are in the %s zone" % proposal if cited else
                                       "its party's row in the Parties table is in the %s zone" % proposal, proposal),
                                   "%s has no zone" % what))
            else:
                out.append(Finding(WARNING, "meetings", r,
                                   "no `zone:`, and nothing says which: its sources are in more than one zone and none is walled, "
                                   "or it cites none and names no party of one zone; give it the zone it belongs to", "%s has no zone" % what))
    return out


def check_meetings(ws: Workspace) -> List[Finding]:
    out = check_splits(ws) + check_meeting_zones(ws)
    for page, fm in ws.meetings.items():
        if is_faded(ws, page) or page in ws.meeting_questions:
            continue                                  # read by the walls only; a question, by check_questions
        r = rel(ws, page)
        if fm and fm.get("type") not in (None, "meeting", "email"):
            out.append(Finding(WARNING, "meetings", r, "`type` is %r, should be meeting or email" % fm.get("type"),
                                   "A meeting page is not marked as a meeting"))
        if not MEETING_NAME_RE.match(page.stem):
            out.append(Finding(WARNING, "meetings", r, "file name should be `YYMMDD-slug.md`",
                                   "A meeting page is misnamed"))
        for problem in bad_dates(fm):
            out.append(Finding(ERROR, "meetings", r, problem, "A meeting page has a date in the wrong form"))
    return out


PEOPLE = ("Wikis", "Meetings", "wiki", "people")
# fade.py writes person pages into dormant/ and archive/ too, and the walls
# read them there as they do in wiki/ (#340).
PEOPLE_FOLDERS = (PEOPLE, ("Wikis", "Meetings", "dormant", "wiki", "people"),
                  ("Wikis", "Meetings", "archive", "wiki", "people"))


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


def check_people(ws: Workspace) -> List[Finding]:
    """A person page is read on both sides of every wall. It says who someone
    is and which party they belong to, and holds nothing learned in a meeting."""
    out = []
    folders = [d for f in PEOPLE_FOLDERS for d in folded_dirs(ws, f)]
    if not any(f.is_dir() for f in folders):
        return out
    for page in sorted(p for f in folders if f.is_dir() for p in f.rglob("*.md")):
        r = rel(ws, page)
        text = read_text(page) or ""
        fm = parse_frontmatter_text(text) if text else parse_frontmatter(page)
        name = str(fm.get("title") or page.stem)
        if fm and fm.get("type") not in (None, "person"):
            out.append(Finding(WARNING, "people", r, "`type` is %r, should be person" % fm.get("type"),
                               "The page for %s is not marked as a person" % name))
        for problem in bad_dates(fm):
            out.append(Finding(ERROR, "people", r, problem, "The page for %s has a date in the wrong form" % name))
    return out


def under_folder(ws: Workspace, path: Path, parts) -> bool:
    """Is `path` at or below the wiki folder `parts`, as git names it, with
    every part compared in any case and Unicode form (#340)?"""
    home = _fold_parts(lexical_folder(ws, parts).parts)
    here = _fold_parts(path.parts)
    return len(here) >= len(home) and here[:len(home)] == home


def _fold_parts(parts) -> Tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", str(x)).casefold() for x in parts)


def lexical_folder(ws: Workspace, parts) -> Path:
    """A wiki folder by its path as git names it: the folder above resolved,
    the folder itself not, so a symbolic link in its place is still found
    there."""
    folder = ws.root.joinpath(*parts)
    return folder.parent.resolve() / folder.name


# ---------------------------------------------------------------------------
# Walls
#
# Detectors, all deterministic, on every text file inside a project:
#   links   a link, an embed or a path to a file, or to a Meetings page, of another walled zone;
#   copies  a staged file that is a whole copy of a file of another walled zone;
#   quotes  eight words shared with a file or Meetings page of another walled zone.
# No name is read. A finding names the file and the zone, never the text it matched:
# the report must not itself carry what the wall kept out.
# ---------------------------------------------------------------------------


# The blocks of combining marks: what NFKD splits off a letter as its accent.
COMBINING_RE = re.compile("[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]")


def words(text: str) -> List[str]:
    """Lower-case words: accents dropped, `&` read as "and", punctuation gone."""
    text = text.replace("&", " and ")
    if not text.isascii():  # plain ASCII has no accents to drop
        text = COMBINING_RE.sub("", unicodedata.normalize("NFKD", text))
    return re.findall(r"[a-z0-9]+", text.lower())


def body_of(text: str) -> str:
    """Text without its frontmatter."""
    if text.startswith("---"):
        m = re.match(r"---[^\n]*\n.*?\n(?:---|\.\.\.)\r?(?:\n|$)", text, re.S)
        if m:
            return text[m.end():]
    return text


# Each word as a number that is the same in every run of the check, unlike
# Python's own hash of a string, so the commit check can keep a file's runs of
# words from one commit to the next (see NoteCache). Sixty bits: Python hashes
# a number that size as itself.
WORD_IDS: Dict[str, int] = {}


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
    """A meeting page with the field the walls read."""
    return bool(fm.get("zone"))


# What separates one candidate path from the next in a code line: white space,
# quotes, brackets, pipes, redirects, separators and `=`. A path with a space
# in it is read as a run of words (below), or as a quoted string.


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


# What may follow a folder's name without being part of a longer name, and what
# ends a path written in a note: white space, a quote, a closing bracket, a
# comma and the like. Anything else after a folder and its slash is part of a
# longer path.
# The folders every project has by Garrick's layout. Written without the
# project's name, one means the note's own project, whether or not that
# project has made it yet.
# The folders an assistant's harness keeps in any project (`.claude/settings.json`, `.agents/skills`). Written
# relative, first, they too mean the note's own project, whoever else holds one (#423).


# The top folders of an operating system: a path written from one leads out of the workspace, unless it passes
# through the workspace's own folder or its Zones/ or Wikis/.
# The folders a home folder holds by the operating system's own layout. `~/Harbour` could be a folder of the
# workspace written from the home folder, so it is still read by its names; `~/Library` cannot.


# Paths every project holds by Garrick's own layout: written by themselves they
# name no project, whoever else holds one.


# What a path under a harness folder may name without naming a subject: the files and folders the harness itself defines.


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
    if target.startswith("obsidian:"):
        target = target.split(":", 2)[2]
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
# What a note points at
# ---------------------------------------------------------------------------
#
# A token is a reference only when the vault resolves it, and nothing is read as
# anything else (docs/principles.md, One memory, walled use). Four rules: a link
# that resolves (link_references); a token that is the exact path of a file
# (reference_tokens, exact_files); eight words in a row shared with a file of
# another walled zone (runs).
# A glob, a folder, a bare word and a path with an entity or an escape in it
# resolve to nothing, so they are text.

LINK_ATTRS = {"href", "src", "srcset", "data", "xlink:href", "poster", "background", "action", "cite", "longdesc"}


AUTOLINK_RE = re.compile(r"<([A-Za-z][A-Za-z0-9+.-]*:[^<>\s]*)>")


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


def without_party_field(text: str) -> str:
    """The file's text with its own frontmatter `party:` and `zone:` fields blanked out: structure, not prose (#465)."""
    if not text.startswith("---"):
        return text
    lines = text.split("\n")
    in_party = False
    for i, line in enumerate(lines[1:], 1):
        if line.rstrip("\r") in ("---", "..."):        # a `---` alone at the margin ends it, as for YAML
            break
        if re.match(r"(?:party|zone)\s*:", line):
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


# What ends a run besides a heading (#498): the bold date that opens a dated entry (`**10 November 2026.**` or
# `**2026-11-10**`, as history.py reads an entry), and a bold label that opens a line and that an installed
# template under System/templates/ holds, such as the thread template's "Where it stands, <D Month YYYY>." A
# thread note is made of these as it is made of headings, and a run that crossed one read two walled notes as
# quoting each other on structure alone. Any other bold opener, a plain date and a log line that starts with a date
# are wording like the rest of the line: a copied log must still be found. With no template to read, no label breaks.
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
BOLD_LABEL_RE = re.compile(r"(?m)^ {0,3}\*\*[^*\n]+\*\*")
ENTRY_DATE_RE = re.compile(r"(?mi)^ {0,3}\*\*(?:\d{1,2} (?:%s) \d{4}|\d{4}-\d{2}-\d{2})[^*\n]*\*\*" % _MONTHS)


# Where no run of words crosses: a Markdown heading, a ledger's header row, or the date that opens an entry (and, with
# the templates' labels, see `breaks`). What each break holds is read on its own, as a heading's words are.
STRUCTURE_RE = re.compile(r"(?mi)%s|%s|%s" % (HEADING_RE.pattern[4:], LEDGER_HEADER_RE.pattern[5:], ENTRY_DATE_RE.pattern[5:]))


def breaks(text: str, labels: Optional[Callable[[str], bool]] = None) -> list:
    """The matches in `text` where no run crosses: STRUCTURE_RE's, and, when `labels` says a bold label opening a
    line is held by an installed template, that label's."""
    found = list(STRUCTURE_RE.finditer(text))
    if labels is not None:
        taken = [(m.start(), m.end()) for m in found]
        for m in BOLD_LABEL_RE.finditer(text):
            if labels(m.group(0)) and not any(a <= m.start() < b for a, b in taken):
                found.append(m)
        found.sort(key=lambda m: m.start())
    return found


def template_labels(ws: "Workspace") -> Tuple[Optional[Callable[[str], bool]], str]:
    """(a test for a bold label held by an installed template, a fingerprint of the labels). The labels are the
    bold openers of lines in System/templates/ and System/templates.local/; a `<placeholder>` in one matches any
    words. None when there are no templates to read."""
    if ws.template_labels is None:
        found = set()
        for top in (TEMPLATES, TEMPLATES_LOCAL):
            folder = ws.root.joinpath(*top)
            for path in (walk_files(folder) if folder.is_dir() else []):
                if path.suffix.lower() == ".md":
                    for m in BOLD_LABEL_RE.finditer(read_text(path) or ""):
                        found.add(" ".join(m.group(0).strip().strip("*").casefold().split()))
        if not found:
            ws.template_labels = (None, "")
        else:
            exact = {f for f in found if "<" not in f}
            loose = [re.compile("^" + ".+?".join(re.escape(x) for x in re.split(r"<[^>]*>", f)) + "$")
                     for f in found if "<" in f]

            def held(label: str) -> bool:
                key = " ".join(label.strip().strip("*").casefold().split())
                return key in exact or any(r.match(key) for r in loose)
            ws.template_labels = (held, hashlib.sha1("\0".join(sorted(found)).encode("utf-8")).hexdigest()[:12])
    return ws.template_labels


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


def runs(text: str, shared: Optional[Callable[[str], bool]] = None, labels: Optional[Callable[[str], bool]] = None) -> set:
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
        out.update(_runs_between_breaks(text[last:start], labels=labels))
        out.update(_checkpoint_runs(text[start:end], labels))
        last = end
    out.update(_runs_between_breaks(text[last:], labels=labels))
    return out


def _runs_between_breaks(text: str, resume_rows: bool = True, labels: Optional[Callable[[str], bool]] = None) -> set:
    """The shingles of `text`, none crossing a heading or a ledger's header,
    nor, with `resume_rows`, a row of the table under a Resume here heading."""
    out: set = set()
    last = 0
    under_resume = False
    for m in breaks(text, labels):
        before = text[last:m.start()]
        out.update(_resume_runs(before) if under_resume else shingles(words(before)))
        out.update(shingles(words(m.group(0))))
        last = m.end()
        if m.group(0).lstrip().startswith("#") or LEDGER_HEADER_RE.match(m.group(0)):
            under_resume = resume_rows and RESUME_HEAD_RE.match(m.group(0)) is not None
        elif under_resume and RESUME_RULE_RE.search(before):
            under_resume = False        # a label or a date below the rule: the block is over
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


def _checkpoint_runs(block: str, labels: Optional[Callable[[str], bool]] = None) -> set:
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
        out.update(_runs_between_breaks(text[last:m.start()], resume_rows=False, labels=labels))
        out.update(shingles(words(next(g for g in m.groups() if g is not None))))
        last = m.end()
    out.update(_runs_between_breaks(text[last:], resume_rows=False, labels=labels))
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


SHARED_FOLDERS = ("System/skills", "System/templates", "System/templates.local", "System/tools", "System/garrick-docs",
                  "Wikis/Knowledge")


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


def wording(ws: Workspace, path: Path, text: str, body: bool) -> set:
    """The runs of words of `text`, the text of the file at `path`: as a
    transcript, a mail or a page reads (transcript_text), and with `body`
    without its frontmatter."""
    text = transcript_text(path, text)
    return runs(body_of(text) if body else text, shared_link(ws, path), template_labels(ws)[0])


LABELS_KEY = "\0labels:"


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
        found = runs(body_of(text) if body else text, ask, template_labels(ws)[0])
        asked[LABELS_KEY + template_labels(ws)[1]] = True        # the templates' labels are read too
        return array("q", sorted(found)).tobytes(), sorted(asked.items())

    def valid(v: tuple) -> bool:
        return all((target == LABELS_KEY + template_labels(ws)[1]) if target.startswith(LABELS_KEY) else link(target) == answer
                   for target, answer in v[1])

    held, _ = ws.cache.get("body" if body else "text", path, make, valid)
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
    # unfinished page may be used anywhere until it has its zone.
    for page, fm in ws.meetings.items():
        add(texts(page, True), page)
        for r in meeting_raws(ws, page, fm):
            add(texts(r, False), page)
    # Every project's own text files, under the zone each is in: a client's brief or data file, and the notes made
    # from them, are that zone's material as much as its meetings are. Template folders are not.
    tags: Dict[Path, frozenset] = {}
    projects: Dict[Path, Path] = {}
    for project, pfm in ws.projects:
        files = list(walk_files(project, unchecked(ws)))
        files += sorted(p for p in view if project in p.parents and not p.exists())  # deleted, but still in git
        for path in files:
            if path.suffix.lower() not in TEXT_SUFFIXES or is_template_path(ws, path):
                continue
            if not add(texts(path, True), path):
                continue  # holds no run: nobody asks what it is written for
            tags[path] = frozenset({zone_of(ws.root, path)} - {None})
            projects[path] = project
    common: set = set()
    beyond: set = set()
    # Wording also found in a shared file is common wording, not a leak. No
    # other file counts, however widely it is read: see SHARED_FILES. A shared
    # file whose working copy differs from git counts only for the wording both
    # versions hold, so an edit left unstaged cannot make a quotation common.
    knowledge = ws.root / "Wikis" / "Knowledge"
    mine = ws.root.joinpath(*TEMPLATES_LOCAL)
    local = lambda p: mine in p.parents  # noqa: E731
    for path in shared_files(ws):
        if path.suffix.lower() in TEXT_SUFFIXES or path.suffix.lower() == ".eml":
            found = {h for h in file_runs(ws, path, False) if h in owners}
            if path in view:
                found &= wording(ws, path, view[path], False)
            if local(path):     # your own templates: wording a meeting holds is not common (#470)
                found = {h for h in found if not any(o in ws.meetings for o in owners[h])}
            common |= found
            if knowledge not in path.parents:
                beyond |= found
    # Wording also found in a template Garrick ships (System/templates/: the zone, project and thread templates) is
    # common wording: a hub made from one template shares its text, and the template is nobody's confidence (#465).
    templates = ws.root.joinpath(*TEMPLATES)
    if templates.is_dir():
        for path in walk_files(templates):
            if path.suffix.lower() in TEXT_SUFFIXES:
                common |= {h for h in file_runs(ws, path, False) if h in owners}
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
    for h in runs(text, shared_link(ws, source), template_labels(ws)[0]):
        if h in exempt:
            continue
        found.update(o for o in index.owners.get(h, ()) if o in ws.meetings and finished(ws.meetings[o]))
    return sorted(found)


def fold_format(text: str) -> str:
    """`text` with Unicode format characters (zero-width spaces and joiners, bidi marks, soft hyphens) taken out
    and every kind of space made a plain one, so a name cut by one still reads as the name. Initials stay a limit."""
    return "".join(" " if unicodedata.category(c) == "Zs" else c for c in text if unicodedata.category(c) != "Cf")


def padded_words(text: str) -> str:
    """`text` as its words, with a space either side, for names_hit."""
    return " %s " % " ".join(words(text))


class PageNames:
    """Every page and record of the Meetings wiki that is not a meeting page, by what to call it (`kinds`), and the
    zone each page and record is in (`zone`), read when a reference resolves to it."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        self.kinds: Dict[Path, str] = {}
        self._zones: Dict[Path, str] = {}
        self._raw_zones: Optional[Dict[Path, set]] = None
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
                self.kinds[page] = "person page" if "people" in inside else "entity page" if "entities" in inside else "wiki page"
        for paths in raw_records(ws).values():
            for record in paths:
                if record not in ws.meetings:
                    self.kinds[record] = "raw record"

    def zone(self, page: Path) -> Optional[str]:
        """The zone a page or record is in: its `zone:`; for a person or entity page with none, the one zone its
        `party:` points at (the Parties table's Zone cell; #481), as a page not yet given a zone; for a raw record,
        the zone of the pages that claim it. `UNZONED` when no one zone is found. A page that names neither a zone
        nor a party holds nobody's material while the migration to zone walls waits (the context is `pending`), as
        it did before, and so does the wiki's own index and log: None."""
        if page not in self._zones:
            ws = self.ws
            kind = self.kinds.get(page)
            if kind is None:
                found = zone_from_frontmatter(ws.root, ws.meetings[page])
            elif kind == "raw record":
                if self._raw_zones is None:
                    self._raw_zones = {}
                    for p, fm in ws.meetings.items():
                        if p not in ws.meeting_questions:
                            for r in meeting_raws(ws, p, fm):
                                self._raw_zones.setdefault(r, set()).add(zone_from_frontmatter(ws.root, fm))
                zones = self._raw_zones.get(page, set())
                found = next(iter(zones)) if len(zones) == 1 else UNZONED
            else:
                fm = parse_frontmatter(page)
                found = zone_from_frontmatter(ws.root, fm)
                if found == UNZONED:
                    found = party_zone(ws, fm)
                    if found == UNZONED and not (fm.get("party") or fm.get("parties")) and not fm.get("zone") \
                            and (kind == "wiki page" or ws.context["pending"]):
                        found = None            # nobody's: its index, its log; and, until the migration, any page not yet placed
            self._zones[page] = found
        return self._zones[page]


def party_zone(ws: Workspace, fm: dict) -> str:
    """The one zone the parties a page names are in, by the Parties table's Zone cells: `UNZONED` when it names none,
    or parties of two zones, or one the table does not know."""
    zones = set()
    for tag in {strip_tag(t) for key in ("party", "parties") for t in as_list(fm.get(key))} - {"none", ""}:
        row = ws.context["parties"].get(tag)
        zones.add((row or {}).get("zone") if (row or {}).get("zone") in ws.context["zone_walled"] else None)
    return zones.pop() if len(zones) == 1 and None not in zones else UNZONED


def page_names(ws: Workspace) -> PageNames:
    """The index of the Meetings wiki's pages by name, built once a run."""
    if ws.page_names is None:
        ws.page_names = PageNames(ws)
    return ws.page_names


def hit_zone(ws: Workspace, hit: Path) -> Optional[str]:
    """The zone of a file a reference lands on: by its path under Zones/, by what the Meetings wiki says of a page
    or record there, None for anything else (System, Knowledge, a file outside the workspace)."""
    if ws.root / "Zones" in hit.parents:
        return zone_of(ws.root, hit)
    if hit in ws.meetings or hit in page_names(ws).kinds:
        return page_names(ws).zone(hit)
    return None


def zone_name(zone: str) -> str:
    return "a zone the workspace does not know" if zone == UNZONED else "the %s zone" % zone


def symlink_finding(ws: Workspace, path: Path) -> Optional[Finding]:
    """A symbolic link in a zone whose target is in another walled zone, or in a Meetings page of one, file or folder:
    reading it reads the other zone, whatever the link is called. None for anything else."""
    dest = zone_of(ws.root, path) if path.is_symlink() else None
    if dest is None:
        return None
    there = zone_of(ws.root, Path(os.path.realpath(path)))
    if there is None or may_flow(ws.context, there, dest):
        return None
    return Finding(ERROR, "walls", rel(ws, path),
                   "is a symbolic link into %s; %s is walled and this file is in %s"
                   % (zone_name(there), "that zone" if there != UNZONED else "a page with no zone", zone_name(dest)),
                   "A note in %s is a symbolic link into %s" % (zone_name(dest), zone_name(there)))


def an(noun: str) -> str:
    """`noun` with its article: a meeting, an entity page."""
    return ("an " if noun[:1] in "aeiou" else "a ") + noun


def zone_findings_for_file(ws: Workspace, path: Path, text: str) -> List[Finding]:
    """Every walls finding for one file of a zone, whose text is `text`: a link, an embed or a path that lands on a
    file of another walled zone, or on a Meetings page of one, or on a page that names no zone. A path in it that the
    system cannot read (one too long to be a name) is a finding of its own, never a crash and never a pass."""
    dest = zone_of(ws.root, path)
    if dest is None or project_of(ws, path) is None:        # a zone's own files, outside any project, are not read
        return []
    r = rel(ws, path)
    try:
        if ws.meeting_links is None:
            ws.meeting_links = meeting_index(ws)
        refs = [("links", w, hits) for w, hits in link_references(ws, path, text, ws.meeting_links)]
        refs += [("writes the path", "`%s`" % t, hits) for t in reference_tokens(text) for hits in [exact_files(ws, path, t)] if hits]
    except OSError as e:
        return [Finding(ERROR, "walls", r,
                        "holds a path the system cannot read (%s), so the file cannot be checked; shorten it or take it out"
                        % (e.strerror or type(e).__name__), "A note in %s holds a path too long to be read" % zone_name(dest))]
    out: List[Finding] = []
    seen: set = set()
    for verb, written, hits in refs:
        for hit in hits:
            there = hit_zone(ws, hit)
            if there is None or hit in seen or may_flow(ws.context, there, dest):
                continue
            seen.add(hit)                      # one finding for a file, however it was written
            noun = meeting_noun(ws, hit) if hit in ws.meetings or hit in page_names(ws).kinds \
                else "note" if hit.suffix.lower() == ".md" else "file"
            if there == UNZONED:
                out.append(Finding(ERROR, "walls", r,
                                   "%s %s, %s that names no zone, so nothing says whose it is; give it a `zone:`" % (verb, written, an(noun)),
                                   "A note in %s uses %s with no zone" % (zone_name(dest), an(noun))))
            else:
                out.append(Finding(ERROR, "walls", r,
                                   "%s %s, %s of %s; that zone is walled and this file is in %s"
                                   % (verb, written, an(noun), zone_name(there), zone_name(dest)),
                                   "A note in %s uses %s of %s" % (zone_name(dest), an(noun), zone_name(there))))
    return out + (wording_findings(ws, path, text, dest) if not ws.quick else [])


def wording_findings(ws: Workspace, path: Path, text: str, dest: str) -> List[Finding]:
    """Wording a file of a project shares with a page of the Meetings wiki of another walled zone, or of none, or
    with a file of another walled zone's project: a run of SHINGLE words held across the wall, a copy by wording.
    Wording also held on the near side (a page or file of the file's own zone, or of an open zone), in a question, in
    this project's own notes, or in one of the shared files every zone reads, is not evidence."""
    r = rel(ws, path)
    index = quote_index(ws)
    project = project_of(ws, path)[0]
    out: List[Finding] = []
    sent = _in_sources(project, path)
    lifted: Dict[Path, int] = {}
    copied: Dict[Path, set] = {}
    crossed_by_file: Dict[Path, bool] = {}

    def crossed(o: Path) -> bool:
        got = crossed_by_file.get(o)
        if got is None:
            got = crossed_by_file[o] = any(not may_flow(ws.context, z, dest) for z in index.tags.get(o, ()))
        return got

    for h in runs(transcript_text(path, text), shared_link(ws, path), template_labels(ws)[0]):
        owners = index.owners.get(h)
        if not owners or h in index.common:
            continue
        pages, files = [], []
        clear = False
        for o in owners:
            if o == path:
                continue
            mfm = ws.meetings.get(o)
            if mfm is not None:
                if not may_flow(ws.context, zone_from_frontmatter(ws.root, mfm), dest):
                    pages.append(o)
                elif o in ws.meeting_questions:
                    continue  # a question restates a record, and is not one: it can show a leak, never vouch for one
                else:
                    clear = True
                    break
            elif sent or (index.project.get(o) == project and not _in_sources(project, o) and not crossed(o)):
                continue  # this project's own note: a leak copied twice must not vouch for itself
            elif crossed(o):
                files.append(o)
            else:
                clear = True
                break
        if clear:
            continue
        for o in pages:
            lifted[o] = lifted.get(o, 0) + 1
        if not pages:
            for o in files:
                copied.setdefault(index.project[o], set()).add(o)
    for page in sorted(lifted):
        there = zone_from_frontmatter(ws.root, ws.meetings[page])
        noun = meeting_noun(ws, page)
        if there == UNZONED:
            out.append(Finding(ERROR, "walls", r, "repeats wording from %s %s, %s that names no zone, so nothing says whose it is; "
                               "give it a `zone:`" % (noun, page.stem, an(noun)), "A note in %s quotes %s with no zone" % (zone_name(dest), an(noun))))
        else:
            out.append(Finding(ERROR, "walls", r, "repeats wording from %s %s, %s of %s; that zone is walled and this file is in %s"
                               % (noun, page.stem, an(noun), zone_name(there), zone_name(dest)),
                               "A note in %s quotes %s of %s" % (zone_name(dest), an(noun), zone_name(there))))
    for other in sorted(copied):
        sources = sorted(copied[other])
        there = zone_of(ws.root, sources[0])
        more = " and %d more of its files" % (len(sources) - 1) if len(sources) > 1 else ""
        out.append(Finding(ERROR, "walls", r,
                           "repeats wording from %s%s, in project %s of %s; that zone is walled and this file is in %s"
                           % (rel(ws, sources[0]), more, other.name, zone_name(there), zone_name(dest)),
                           "A note in %s quotes a file of %s" % (zone_name(dest), zone_name(there))))
    return out


def near_wording(root: Path, pairs: List[Tuple[str, str]]) -> List[bool]:
    """For each (file, source), the file root-relative and the source a lower-cased page stem or root-relative path:
    whether a run of words the file shares with the source is also held by a file or meeting page of the file's own
    zone, the near side that wording_findings does not count as a leak. Read only: it discovers the workspace
    without a cache and writes nothing. The update asks it of the finding a rule it replaces made, whatever that
    finding's own message said. False for anything it cannot place."""
    _BLOBS.clear()
    ws = discover(Path(root).resolve(), None)
    index = quote_index(ws)
    out: List[bool] = []
    for rel_path, source in pairs:
        path = ws.root / rel_path
        found = False
        try:
            text = read_text(path)
            project = project_of(ws, path)
            dest = zone_of(ws.root, path)
            if text and project is not None and dest not in (None, UNZONED):
                project, sent = project[0], _in_sources(project[0], path)
                for h in runs(transcript_text(path, text), shared_link(ws, path), template_labels(ws)[0]):
                    owners = index.owners.get(h)
                    if not owners or h in index.common:
                        continue
                    if not any((o.stem.lower() == source) if o in ws.meetings else (rel(ws, o).lower() == source)
                               for o in owners if o != path):
                        continue
                    for o in owners:
                        if o == path or o in ws.meeting_questions:
                            continue
                        if o in ws.meetings:
                            there = zone_from_frontmatter(ws.root, ws.meetings[o])
                        elif sent or (index.project.get(o) == project and not _in_sources(project, o)):
                            continue
                        else:
                            there = zone_of(ws.root, o)
                        if there == dest:
                            found = True
                            break
                    if found:
                        break
        except (OSError, ValueError):
            found = False
        out.append(found)
    return out


def _in_sources(project: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(project).parts
    except ValueError:
        return False
    return len(parts) >= 2 and parts[0] == "Sources" and not parts[-1].startswith(".")


COPY_MIN = 32   # below this many bytes, identical content proves nothing


ZONE_PLACEHOLDER = (b"{" * 2) + b"ZONE" + (b"}" * 2)   # written in parts, so no placeholder stands in an installed file


def shipped_hashes(ws: Workspace, zone: Optional[str]) -> set:
    """The content hashes of the files Garrick ships, as installed: everything under System/templates/ of the workspace
    (the zone, project and thread templates), and under the folder GARRICK_TEMPLATES_DIR names, which the update sets
    to the release it is installing. Each is hashed as it is and with the zone placeholder filled in as each zone's name, the way
    the installer writes it. Such a file is the same in every zone, so it is never a copy from another one."""
    folders = [ws.root.joinpath(*TEMPLATES)]
    if os.environ.get("GARRICK_TEMPLATES_DIR"):
        folders.append(Path(os.environ["GARRICK_TEMPLATES_DIR"]))
    found = set()
    for folder in folders:
        for here, _, files in os.walk(folder):
            for name in files:
                try:
                    data = (Path(here) / name).read_bytes()
                except OSError:
                    continue
                found.add(hashlib.sha256(data).hexdigest())
                for name_ in {z.name for z in ws.zones} | ({zone} if zone else set()):
                    found.add(hashlib.sha256(data.replace(ZONE_PLACEHOLDER, name_.encode("utf-8"))).hexdigest())
    return found


def copy_findings(ws: Workspace, staged: List[Tuple[Path, bytes]]) -> List[Finding]:
    """A staged file whose bytes are those of a file of another walled zone, or of a Meetings page of one, is a copy
    made whole: the zone wall refuses it whatever it is called. Only the staged files are hashed, and a file of
    another zone only when its size is one of theirs. A Knowledge page is a destination with no zone.

    Not a copy: a file under COPY_MIN bytes (an empty `.gitkeep`), a file Garrick ships (shipped_hashes: the zone
    template's files are identical in every zone), and content that a file of an open zone also holds, since open
    material goes anywhere. Content held only by walled zones stays a copy, however many hold it."""
    want: Dict[int, List[Tuple[Path, str, Optional[str]]]] = {}
    for path, data in staged:
        dest = zone_of(ws.root, path)
        if len(data) >= COPY_MIN and (dest is not None or ws.root / "Wikis" / "Knowledge" in path.parents):
            want.setdefault(len(data), []).append((path, hashlib.sha256(data).hexdigest(), dest))
    if not want:
        return []
    hits: Dict[Path, Tuple[str, str, Optional[str]]] = {}        # staged file -> (hash, zone it copies, its own zone)
    held: Dict[str, set] = {}                                    # hash -> the zones whose files have it
    tops = [z for z in ws.zones] + [ws.root / "Wikis" / "Meetings"]
    for top in tops:
        for here, dirs, files in os.walk(top):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and d != ".git" and not os.path.islink(os.path.join(here, d)))
            for name in files:
                at = Path(here) / name
                try:
                    size = at.stat().st_size
                except OSError:
                    continue
                if size not in want or at.is_symlink():
                    continue
                there = hit_zone(ws, at)         # a raw record is in the zone of the pages that claim it
                if there is None:
                    continue
                try:
                    digest = hashlib.sha256(at.read_bytes()).hexdigest()
                except OSError:
                    continue
                for path, sha, dest in want[size]:
                    if path == at or digest != sha:
                        continue
                    held.setdefault(sha, set()).add(there)
                    if not may_flow(ws.context, there, dest) and path not in hits:
                        hits[path] = (sha, there, dest)
    out: List[Finding] = []
    shipped: Dict[Optional[str], set] = {}
    for path, (sha, there, dest) in sorted(hits.items()):
        if dest not in shipped:
            shipped[dest] = shipped_hashes(ws, dest)
        if sha in shipped[dest] or any(not walled(ws.context, z) for z in held[sha]):
            continue        # Garrick's own text, or held by an open zone, whose material goes anywhere
        out.append(Finding(ERROR, "walls", rel(ws, path),
                           "is a copy, whole, of a file of %s; %s is walled and this file is in %s"
                           % (zone_name(there), "that zone" if there != UNZONED else "a page with no zone",
                              zone_name(dest) if dest is not None else "Knowledge"),
                           "A file in %s is a whole copy of a file of %s"
                           % (zone_name(dest) if dest is not None else "Knowledge", zone_name(there))))
    return out


def unchecked(ws: Workspace) -> set:
    """What the walls leave out of a zone's own files: what git ignores (see ignored), and every Garrick checkout
    kept in a project, whose docs and shipped rules are not the project's notes."""
    if ws.apart is None:
        ws.apart = ignored(ws) | set(checkouts(ws))
    return ws.apart


def check_walls(ws: Workspace) -> List[Finding]:
    """No file of a zone links to, embeds, or writes the path of a file of another walled zone, or a Meetings page of
    one. Files git ignores are left out: they never reach the history the commit hook guards. So is a Garrick
    checkout kept in a project (unchecked), and a zone's Inbox, which no history holds."""
    out = []
    skip = unchecked(ws)
    for project, _ in ws.projects:
        for path in walk_files(project, skip):
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = read_text(path)
            if text:
                out.extend(zone_findings_for_file(ws, path, text))
            elif path.is_symlink() and (found := symlink_finding(ws, path)) is not None:
                out.append(found)
        for here, dirs, _ in os.walk(project):
            out.extend(f for f in (symlink_finding(ws, Path(here) / d) for d in sorted(dirs) if d not in SKIP_DIRS) if f is not None)
    out.extend(form_findings(ws, [(p, None) for p in form_candidates(ws)]))
    out.extend(nested_repositories(ws))
    return out


def check_walls_staged(ws: Workspace, repo: Path) -> List[Finding]:
    """The walls check on what is about to be committed, and nothing else.
    Anything waiting in a zone's Inbox, or in the Meetings inbox, at any depth,
    is refused too: it has not been filed, so no zone has seen it."""
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
        apply_git_view(ws, top_path)
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
            if (top_path / name).is_symlink() and (top_path / name).suffix.lower() not in TEXT_SUFFIXES:
                found = symlink_finding(ws, top_path / name)
                if found is not None:
                    out.append(found)
    staged_texts = [(canonical_path(ws, p), t) for p, t in (staged_files(repo) or [])]
    # The Zones table decides which zone is walled, so a change to it puts every file across a wall or not (#340).
    table = ws.root / "System" / "context.md"
    changed = staged is not None and any(
        (staged[0] / n).resolve() == table.resolve() or (staged[0] / n) == table for n in staged[1])
    if changed and table in ws.git_view:                 # on disk it differs from the index
        out.append(Finding(ERROR, "walls", rel(ws, table),
                           "names different zones and walls on disk from the ones staged; stage that change or "
                           "undo it, so the walls are checked against the table the commit holds",
                           "The Zones table was changed but the change is not staged"))
    # The form of every staged page the walls read.
    out.extend(form_findings(ws, [(path, text) for path, text in staged_texts]))
    # Any staged file that reads as text is read for the walls, whatever its suffix.
    extra = [(canonical_path(ws, p), t) for p, t in staged_other_texts(repo)]
    if not ws.quick:       # the wording check asks only after the runs of words these files hold
        quote_index(ws, set().union(*(wording(ws, path, text, False) for path, text in staged_texts + extra
                                      if zone_of(ws.root, path) is not None and project_of(ws, path) is not None)))
    for path, text in staged_texts + extra:
        out.extend(zone_findings_for_file(ws, path, text))
    raw = _staged_raw(repo)
    blobs: List[Tuple[Path, bytes]] = []
    for name in (raw[1] if raw else []):
        staged_path = canonical_path(ws, raw[0] / wiki_case(name))
        data = _git_bytes(["show", ":" + name], raw[0])
        if data is None:
            continue
        in_zone = zone_of(ws.root, staged_path) is not None
        if in_zone and staged_path.suffix.lower() in TEXT_SUFFIXES and (len(data) > MAX_STAGED_BYTES or text_of(data) is None):
            # a file of the text suffixes that the walls cannot read is refused, not skipped (#398)
            why = ("is over %d bytes" % MAX_STAGED_BYTES if len(data) > MAX_STAGED_BYTES
                   else "holds NUL bytes and no UTF-16 byte order mark")
            out.append(Finding(ERROR, "walls", rel(ws, staged_path),
                               "%s, so the walls cannot read it; save it as UTF-8 text under the size limit, or keep "
                               "it out of the zone" % why, "A file in %s cannot be read by the walls" % zone_name(zone_of(ws.root, staged_path))))
        if len(data) <= MAX_STAGED_BYTES:
            blobs.append((staged_path, data))
    out.extend(copy_findings(ws, blobs))
    return out


# What an honest writer puts at the edge of a path: quotes, brackets, bold marks, a comma or a full stop.
EDGE = "\"'`<>()[]{}*,;:!?|\u201c\u201d\u2018\u2019\u00ab\u00bb"
MAX_TOKEN = 1024      # a path is not longer than this
MAX_SPACED = 8        # words a path with spaces in it may span


def _key(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def reference_index(ws: Workspace) -> Dict[str, List[Path]]:
    """Every file a note may point at, by its path: the files of the projects, the pages of the wikis, and for a
    wiki page the places it stands at in the other grades (grade_places). Built once a run."""
    if ws.ref_files is None:
        found: Dict[str, List[Path]] = {}

        def add(at: Path, page: Path) -> None:
            here = found.setdefault(_key(str(at)), [])
            if page not in here:
                here.append(page)

        for f in project_index(ws).items:
            add(f, f)
        for f in ws.wiki_files:
            add(f, f)
        for zone in ws.zones:             # what a zone put away: a project's files keep the hub's label (#438)
            for folder in sorted(d for d in visible_dirs(zone) if d.name.lower() == "archive"):
                for f in walk_files(folder, nested=True):
                    add(f, f)
        for page in list(ws.meetings) + list(page_names(ws).kinds):
            add(page, page)
            for at in grade_places(ws, page):
                add(at, page)
        ws.ref_files = found
        wikis = ws.root / "Wikis"
        ws.ref_wikis = sorted(d for d in wikis.iterdir() if d.is_dir() and not d.name.startswith(".")) if wikis.is_dir() else []
    return ws.ref_files


def exact_files(ws: Workspace, note: Path, token: str) -> List[Path]:
    """Rule 2: the files of the workspace that `token` is the exact path of, with `.md` or without. Read from the
    note's own folder first, then from the top of the vault, then from the top of each wiki; an absolute path is
    read as it is. One lookup in the index, with no reading of the token."""
    if token.endswith("/") or "//" in token.lstrip("/") or "/./" in token or "\\" in token:
        return []                              # a folder, or a spelling that is not the path itself
    found = reference_index(ws)
    if token.startswith("~"):
        token = os.path.expanduser(token)
    if token.startswith("/"):
        top = str(ws.root.resolve())
        if token == top or token.startswith(top + "/"):
            token = str(ws.root) + token[len(top):]
        bases: List[Optional[Path]] = [None]
    elif token.startswith(("./", "../")):
        bases = [note.parent]
    else:
        zone = ws.root / "Zones" / note.relative_to(ws.root).parts[1] if note.is_relative_to(ws.root / "Zones") and len(note.relative_to(ws.root).parts) > 1 else ws.root
        bases = [note.parent, zone, *vaults_of(ws, note), ws.root, *ws.ref_wikis]
    for base in bases:
        at = os.path.normpath(token if base is None else os.path.join(base, token))
        hits: List[Path] = []
        for form in (at, at + ".md"):
            hits += [h for h in found.get(_key(form), []) if h not in hits]
        if hits:
            return hits
    return []


def reference_tokens(text: str) -> List[str]:
    """Every stretch of `text` that could be the path of a file (rule 2): a word, a word cut at the marks that wrap
    one, a code span or a line of a fenced block whole, a frontmatter value whole, and from each word that holds a
    slash on, a run of up to MAX_SPACED words, for a name with spaces. Only a token with a slash is kept: a name
    with none is in the note's own folder."""
    seen: Dict[str, None] = {}

    def add(token: str) -> None:
        token = token.lstrip(EDGE).rstrip(EDGE + ".")
        if "/" in token and len(token) <= MAX_TOKEN:
            seen.setdefault(token)

    for word in re.split(r"\s+", text):
        add(word)
    for word in re.split(r"[\s\"'`<>()\[\]{}|,;=\u201c\u201d\u2018\u2019\u00ab\u00bb]+", text):
        add(word)
    spans = [body for _, body in code_texts(text)]
    if FRONT_OPEN_RE.match(text):
        block = text.split("\n---", 1)[0]
        spans += [re.sub(r"^\s*(?:-\s+|[^:\n]*:\s+)", "", line).strip().strip("\"'") for line in block.split("\n")[1:]]
    for span in spans:
        add(span)
        words = span.split()
        for i, word in enumerate(words):
            if "/" in word:
                for j in range(i + 2, min(len(words), i + MAX_SPACED) + 1):
                    add(" ".join(words[i:j]))
    return list(seen)


FRONT_OPEN_RE = re.compile(r"\A﻿?---[ \t]*\r?\n")


def link_references(ws: Workspace, note: Path, text: str, meetings: "PathIndex") -> List[Tuple[str, List[Path]]]:
    """Rule 1: (as written, files) for each link that resolves: a wikilink, a Markdown link, an embed, an HTML
    attribute, an autolink or an `obsidian://open?file=` URI, as Obsidian resolves it. A link to a page of the
    Meetings wiki also lands where the page stood in another grade."""
    links = extract_links(text)
    links += [("<%s>" % t, f) for t in AUTOLINK_RE.findall(text) for f in _link_forms(unquote(t))]
    project = project_of(ws, note)
    out = []
    for written, target in dict.fromkeys(links):
        hits = list(link_dests(ws, note, target))
        if project is not None:
            hits += [h for h in hidden_dests(ws, note, project[0], target) if h not in hits]
        hits += [h for h in resolve(ws, note, target, meetings) if h not in hits]
        if hits:
            out.append((written, hits))
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
    zone counts (a Knowledge page must carry none); None where the walls
    read no frontmatter: a raw record, and any other file."""
    if path.suffix.lower() != ".md":
        return None
    here = path.parent.resolve() / path.name
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
    return None


def form_candidates(ws: Workspace) -> List[Path]:
    """Every page whose frontmatter the full walls check reads for its form:
    the wiki pages, the meeting pages and questions."""
    pages = set(ws.wiki_files) | {p for p in ws.meetings if p.exists()}
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


def apply_git_view(ws: Workspace, committing: Path) -> None:
    """Read git's version of every file whose working copy differs (git_view)
    alongside the disk's. A meeting page or a Meetings question counts with
    the parties of both versions, one deleted from disk still counts, and one
    whose zone differs between the two names both, so that it is no zone's
    until they agree."""
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
            if then.get("zone") and now.get("zone") and then.get("zone") != now.get("zone"):
                now["zone"] = [now["zone"], then["zone"]]       # two zones across the two versions: no zone may use it


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
    beyond = None
    raws = [kroot / home for home in RAW_HOMES]
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
    check_hooks, check_cmux,
    check_skills, check_names, check_projects, check_threads, check_history, check_concise_pages, check_resume, check_deliverables, check_anonymous,
    check_todo, check_questions, check_decisions, check_links, check_meetings, check_people, check_walls, check_inbox, check_knowledge,
    check_raw, check_generated, check_recall, check_preferences, check_review, check_updates,
]


def run_checks(root: Path, walls_only: bool = False, staged: Optional[Path] = None, quick: bool = False,
               use_ledger: bool = True) -> List[Finding]:
    """Every check, or with `walls_only` the walls check alone. With `staged`, a
    folder inside a git repository, the walls check alone on what it has staged.
    With `quick`, every check but the comparison of wording: whether a project
    file, a person page or a Knowledge page repeats a meeting. That comparison
    reads every meeting and project file, and is most of the time a full check
    takes on a large workspace; the commit hook still runs it on what is staged.
    Findings the user allowed once (System/walls-allowed.json) are dropped, unless `use_ledger` is off."""
    _committing(Path(staged) if staged is not None else None)
    _BLOBS.clear()
    cache = NoteCache.for_repo(Path(staged)) if staged is not None else None
    ws = discover(Path(root).resolve(), cache)
    ws.quick = quick and staged is None
    findings: List[Finding] = []
    if staged is not None:
        findings = check_walls_staged(ws, Path(staged))
        cache.save()
        if use_ledger:
            findings = drop_allowed(ws, findings, allow_repo_top(Path(staged)),
                                    lambda paths: check_walls_staged(ws, Path(staged)))
    else:
        for check in ([check_walls] if walls_only else ALL_CHECKS):
            try:
                findings.extend(check(ws))
            except Exception as e:      # one check that trips over a file must not stop the others
                name = check.__name__.replace("check_", "", 1)
                findings.append(Finding(ERROR, name, "", "the check stopped: %s: %s" % (type(e).__name__, e),
                                        "A check stopped before it finished"))
        if use_ledger:
            findings = drop_allowed(ws, findings, None, lambda paths: run_path_checks(ws.root, paths))   # the touched files only
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
                if f.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                text = read_text(f)
                if text:
                    findings.extend(zone_findings_for_file(ws, f, text))
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
    try:
        waiting = load_context(root)["pending"] and (Path(root) / "System" / "context.md").is_file()
    except Exception:
        waiting = False
    if waiting:        # in this report only: the findings, and so the JSON, are the same either way
        lines += ["The zone walls migration waits: the Zones table has no Walled column, so each zone's flag is "
                  "worked out from the old party flags. Run the update and read what it shows.", ""]
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
    # a party changed on disk and not staged: the two must agree
    (("on disk from the one staged", "on disk from the ones staged"),
     "Stage that change or undo it, then commit again."),
    # a page that names no zone, nothing says whose it is: give it one, or leave it out
    (("names no zone", "that no page cites"),
     "Give it a `zone:`, or take the mention out, and commit again."),
    # a page not finished, or a mail not yet answered: finish it first
    (("an unfinished", "not filed until the user has answered"),
     "Finish or file it first, or take the mention out, and commit again."),
    # a finding that cannot be read, or that is not a crossing: the message holds the fix
    (("cannot be read", "cannot be checked", "cannot be placed", "cannot read it", "not checked", "symbolic link", "submodule",
      "is reserved", "was not read", "write each key once"),
     "Make that change, then commit again."),
)


def staged_fix(message: str) -> str:
    """The end of one refusal line: the fix that belongs to this finding."""
    low = message.lower()
    if "is walled and" not in low:
        for phrases, fix in STAGED_FIXES:
            if any(p.lower() in low for p in phrases):
                return fix
        if "so the walls" in low or "the walls cannot" in low or "until it does" in low:
            return "Make that change, then commit again."
    return TAKE_OUT


# ---------------------------------------------------------------------------
# Allow once: a finding the user let through, for as long as its file is as it was
# ---------------------------------------------------------------------------
# The ledger is System/walls-allowed.json (garrick_lib.py). The hook reads it once and drops a finding whose path,
# id and git blob id all match an entry. Nothing here writes it but allow_command(); the page's verb only takes an entry away, and
# runs without a terminal.

def finding_rule(f: Finding) -> str:
    """The kind of a finding, as the hook's report and the ledger name it."""
    return refusal_kind(f.message)


def finding_token(f: Finding) -> str:
    """What a finding's id is taken over besides its path and kind: the text of the finding. The one place to
    change if a finding comes to carry the matched text on its own."""
    return f.token or f.message


def finding_id(f: Finding) -> str:
    return f.fid or allow_finding_id(f.path, finding_rule(f), finding_token(f))


def allowable(f: Finding) -> bool:
    """Whether the user may let a finding through: a wall refusal about a file of the workspace, of a kind the
    ledger holds. A finding about something that could not be read, a file waiting in an inbox, or a repository
    the walls cannot place is never allowed."""
    return (f.severity == ERROR and f.check == "walls" and bool(f.path) and not Path(f.path).is_absolute()
            and finding_rule(f) in ALLOW_RULES and staged_fix(f.message) in ALLOWED_FIXES)


# What a refusal ends with when the user may let it through: material to take out (a link, an embed, a path, a copy),
# or a page that names no zone. A refusal whose fix is a change of the hub, a staging, a finished page or
# a file that could not be read is not a judgment about the material, and is never allowed.
ALLOWED_FIXES = {TAKE_OUT, staged_fix("names no zone")}


def index_blobs(top: Path) -> Dict[str, str]:
    """Git's blob id of every file in the index of the repository at `top`, by path in any case: what the commit
    holds, with nothing hashed here."""
    listing = _git(["ls-files", "-s", "-z"], top) or ""
    blobs: Dict[str, str] = {}
    for entry in listing.split("\0"):
        meta, _, name = entry.partition("\t")
        parts = meta.split()
        if name and len(parts) == 3 and parts[2] == "0":
            blobs[name.casefold()] = parts[1]
    return blobs


def disk_blob(path: Path) -> Optional[str]:
    """Git's blob id of a file as it is on disk, from the repository it is in."""
    got = _git(["hash-object", "--", path.name], path.parent)
    return got.strip() if got and got.strip() else None


def drop_allowed(ws: Workspace, findings: List[Finding], top: Optional[Path] = None,
                 rerun: Optional[Callable[[List[str]], List[Finding]]] = None) -> List[Finding]:
    """The findings left once the allowed ones are taken out. With `top`, the repository being committed, a blob
    id comes from its index; without, from the file on disk, and only for the files that have a finding the
    ledger could cover. The ledger is the committed one, read once; a missing or unreadable one drops nothing.

    A file is cleared only when every finding it has is covered. `rerun` is no longer used: no finding leaves a
    second one out."""
    ledger = allow_set(ws.root)
    if not ledger:
        return findings
    covered = {(p, i) for p, i, _ in ledger}
    touched = {f.path for f in findings if allowable(f) and (f.path, finding_id(f)) in covered}
    if not touched:
        return findings
    full = findings
    index: Optional[Dict[str, str]] = None
    disk: Dict[str, Optional[str]] = {}

    def blob_of(path: str) -> Optional[str]:
        nonlocal index
        if top is not None:
            if index is None:
                index = index_blobs(top)
            try:
                name = (ws.root / path).relative_to(top).as_posix()
            except ValueError:
                return None
            return index.get(name.casefold())
        if path not in disk:
            disk[path] = disk_blob(ws.root / path)
        return disk[path]

    kept = [f for f in findings if f.path not in touched]
    for path in sorted(touched):
        kept += [f for f in findings if f.path == path and f.check != "walls"]    # only wall findings are ever dropped
        here = [f for f in full if f.path == path and f.check == "walls"]
        mine = [f for f in here if allowable(f)]
        blob = blob_of(path)
        if blob is not None and mine and all((path, finding_id(f), blob) in ledger for f in mine):
            kept += [f for f in here if not allowable(f)]
        else:
            kept += here or [f for f in findings if f.path == path and f.check == "walls"]
    return kept


def allow_repo_top(folder: Path) -> Optional[Path]:
    top = _git(["rev-parse", "--show-toplevel"], folder)
    return Path(top.strip()).resolve() if top else None


def refused_by_file(findings: List[Finding]) -> Dict[str, List[Finding]]:
    out: Dict[str, List[Finding]] = {}
    for f in findings:
        if f.severity == ERROR:
            out.setdefault(f.path, []).append(f)
    return out


def kind_counts(found: List[Finding]) -> str:
    counts: Dict[str, int] = {}
    for f in found:
        counts[finding_rule(f)] = counts.get(finding_rule(f), 0) + 1
    return ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def shell_word(text: str) -> str:
    return text if re.fullmatch(r"[A-Za-z0-9_./@%+=:,-]+", text) else "'" + text.replace("'", "'\\''") + "'"


def allow_prefix() -> str:
    """The command that allows, written to run from the folder the hook runs in (a zone's), not only from the
    workspace root: this file's path from there. The path argument stays the workspace's."""
    tool = Path(__file__).resolve()
    try:
        shown = os.path.relpath(str(tool), str(Path.cwd()))
    except ValueError:
        shown = str(tool)
    return "python3 %s allow" % shell_word(shown)


def prints_for_assistant(json_out: bool = False, staged: bool = False, ear: bool = False) -> bool:
    """Whether the check prints for an assistant, not a person at a terminal: `--json`, or the stream it prints to
    (stderr for the hook's report, else stdout) not a terminal. The one test for what an assistant is not shown."""
    stream = sys.stderr if staged and not ear else sys.stdout
    try:
        return bool(json_out) or not stream.isatty()
    except (AttributeError, ValueError):
        return True


def hook_fix(message: str) -> str:
    """staged_fix(), for the hook's own lines. The way past the whole check (`git commit --no-verify`) is the
    user's, so it is named only where a person is reading (git runs the hook with no stdin, so stdin says nothing):
    for an assistant the allow command stands in its place."""
    fix = staged_fix(message)
    return fix if not prints_for_assistant(False, True) else fix.replace("; only if you mean it, git commit --no-verify", "")


def report_short(findings: List[Finding]) -> str:
    """The hook's report: a file with one refusal keeps its own line; a file with several gets one line with the
    kind of each and a count. The command that lets one through, once, comes first. The full list is --verbose, from the zone folder."""
    lines = []
    first = None
    for path, found in refused_by_file(findings).items():
        if len(found) == 1:
            f = found[0]
            lines.append("Commit refused: %s %s. %s" % (f.path, f.message, hook_fix(f.message)))
        else:
            lines.append("Commit refused: %s holds %d refusals (%s). Take them out and commit again; "
                         "--verbose lists each." % (path, len(found), kind_counts(found)))
        if first is None:
            first = next((f for f in found if allowable(f)), None)
    if first is not None:        # first, not last: what reads a refusal back (the page, scaffold.py) takes the last line
        prefix = allow_prefix()
        lines.insert(0, "To let a refusal through, once, while the file stays as it is: %s <path> [<id>]; "
                     "with no id it lists each id, for example %s %s %s"
                     % (prefix, prefix, shell_word(first.path), finding_id(first)))
    return "\n".join(lines)


def report_verbose(findings: List[Finding]) -> str:
    """Every refusal on a line of its own, as the hook used to print them, with the id that lets it through."""
    lines = []
    for f in (f for f in findings if f.severity == ERROR):
        line = "Commit refused: %s %s. %s" % (f.path, f.message, hook_fix(f.message))
        lines.append(line + ("  [id %s, %s]" % (finding_id(f), finding_rule(f)) if allowable(f) else ""))
    return "\n".join(lines)


def allow_files(root: Path, path: str):
    """(findings, blob, top) for a file of the workspace: what the wall check says about it now, the blob id of the
    file as that check read it, and the repository it is in. Read from the index when the file is staged, else
    from the file on disk (the walls check of the named file, as an update asks it). None when the file is not
    in a repository of the workspace."""
    file = root / path
    top = _git(["rev-parse", "--show-toplevel"], file.parent if file.parent.is_dir() else root)
    if top is None:
        return None
    top_path = Path(top.strip()).resolve()
    try:
        name = file.resolve().relative_to(top_path).as_posix()
    except ValueError:
        return None
    staged = _git(["diff", "--cached", "--name-only", "-z", "--", name], top_path) or ""
    global _DEDUP_OFF
    _DEDUP_OFF = True            # every finding the file has, the second about a party already named included
    try:
        if staged.strip("\0"):
            found = run_checks(root, staged=top_path, use_ledger=False)
            blob = index_blobs(top_path).get(name.casefold())
        else:
            found = run_path_checks(root, [path])
            blob = disk_blob(file)
    finally:
        _DEDUP_OFF = False
    return [f for f in found if f.path == path and allowable(f)], blob, top_path


STRAY_SAID = " The ledger on disk differed from the committed one; its uncommitted entries were dropped, not committed."


def allow_page(root: Path, path: str, fid: Optional[str], by: str, remove: bool = False) -> Tuple[int, str]:
    """Write or take away one allowance. (0, what was done) or (1, why not). `by` is "terminal" or "page"; the
    caller has settled that it is one (allow_may_write). Without an id, lists the file's findings and
    writes nothing."""
    root = Path(root).resolve()
    path = Path(path).as_posix()
    if path.startswith("/") or ".." in path.split("/") or not path:
        return 1, "name the file by its path from the workspace root, such as Zones/Work/Acme/Notes.md"
    if remove:
        if not fid:
            return 1, "name the finding to take away: allow --remove <path> <id>"
        stray = allow_stray(root)
        if not allow_remove(root, path, fid):
            return 1, "no allowance for %s with the id %s%s" % (path, fid, STRAY_SAID if stray else "")
        said = allow_commit(root, "Walls: take away an allowance")
        return 0, "Allowance taken away.%s%s" % (STRAY_SAID if stray else "", " The ledger was not committed: %s" % said if said else "")
    got = allow_files(root, path)
    if got is None:
        return 1, "%s is not in a repository of this workspace" % path
    found, blob, _ = got
    if not found:
        return 1, "no refusal that can be allowed for %s now" % path
    if not fid:
        return 0, "\n".join("%s  %s  %s" % (finding_id(f), finding_rule(f), f.message) for f in found)
    hit = next((f for f in found if finding_id(f) == fid), None)
    if hit is None:
        return 1, "%s has no refusal with the id %s now" % (path, fid)
    if blob is None:
        return 1, "git has no blob id for %s, so nothing was allowed; stage the file first" % path
    stray = allow_stray(root)
    entry = allow_add(root, path, fid, blob, finding_rule(hit), by)
    said = allow_commit(root, "Walls: allow one %s refusal once" % entry["rule"])
    return 0, "Allowed once: %s, a %s refusal. It holds until the file changes.%s%s" % (
        path, entry["rule"], STRAY_SAID if stray else "", " The ledger was not committed: %s" % said if said else "")


def allow_command(argv: List[str]) -> int:
    """`check.py allow [--root R] [--remove] <path> [<id>]`: from a terminal only."""
    parser = argparse.ArgumentParser(prog="check.py allow", description="Let one wall refusal through, once, while its "
                                     "file stays as it is. Without an id, lists the file's refusals.")
    parser.add_argument("--root", help="workspace root (default: the workspace this script sits in)")
    parser.add_argument("--remove", action="store_true", help="take the allowance away instead")
    parser.add_argument("path", help="the file, from the workspace root")
    parser.add_argument("id", nargs="?", help="the refusal's id, as this command without one lists it")
    args = parser.parse_args(argv)
    if not allow_may_write("terminal"):
        print("check: an allowance is written from a terminal you type in; "
              "nothing was written", file=sys.stderr)
        return 2
    try:
        root = Path(args.root).expanduser().resolve() if args.root else workspace_root(Path(__file__).resolve().parent)
    except FileNotFoundError as exc:
        print("check: %s" % exc, file=sys.stderr)
        return 2
    path = args.path
    if os.path.isabs(path):
        try:
            path = Path(path).resolve().relative_to(root).as_posix()
        except ValueError:
            pass
    code, said = allow_page(root, path, args.id, "terminal", remove=args.remove)
    print(said, file=sys.stderr if code else sys.stdout)
    return code


def report_staged(findings: List[Finding], verbose: bool = False) -> str:
    """For the pre-commit hook: the short report, nothing when clear; with `verbose`, one line per wall broken."""
    return report_verbose(findings) if verbose else report_short(findings)


MERGE_SAID = " and its merge hooks (pre-merge-commit, post-merge, post-rewrite)"


def changed_files(top: Path, specs: List[str]) -> Optional[List[str]]:
    """The files, relative to the top of the repository `top`, that the commits `specs` changed: `A..B` is what
    changed from A to B, a lone commit is what that commit changed. Added, copied, modified, renamed or retyped; a
    file that is gone is not read. None when git cannot say. Read only: git is told to take no lock."""
    names = set()
    for spec in specs:
        if spec.startswith("-"):
            return None
        args = (["diff", "--name-only", "--diff-filter=ACMRT", "-z", spec, "--"] if ".." in spec else
                ["diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "--root", "-m", "--diff-filter=ACMRT", spec, "--"])
        got = _git(args, top)
        if got is None:
            return None
        names.update(n for n in got.split("\0") if n)
    return sorted(names)


def changed_command(root: Path, specs: List[str], after: str = "merge") -> int:
    """`--changed`: after a merge, a fast-forward or a rebase has brought commits in, the walls check on the files
    they changed, read only, as the post-merge and post-rewrite hooks run it. The commits are in, so this refuses
    nothing: it says what the check finds, that the commits are in, and how to undo them, without doing it. Always 0."""
    cwd = Path.cwd()
    top = _git(["rev-parse", "--show-toplevel"], cwd)
    names = changed_files(Path(top.strip()), specs) if top else None
    if names is None:
        return 0
    base = Path(top.strip()).resolve()
    wanted = []
    for name in names:
        try:
            wanted.append((base / name).relative_to(root.resolve()).as_posix())
        except ValueError:
            continue
    if not wanted:
        return 0
    findings = [f for f in run_path_checks(root, wanted) if f.check == "walls" and f.severity == ERROR and f.path in set(wanted)]
    if findings:
        by_file = refused_by_file(findings)
        lines = ["Wall check: %d file%s that the commits just brought in would have been refused. The commits are "
                 "already in, so nothing was refused and nothing was undone:" % (len(by_file), "" if len(by_file) == 1 else "s")]
        lines += ["  %s %s" % (path, found[0].message if len(found) == 1 else "holds %d refusals (%s)" % (len(found), kind_counts(found)))
                  for path, found in by_file.items()]
        if after == "amend":     # an amend sets no ORIG_HEAD: the old commit is where the reflog says
            lines.append("To undo the amend, keeping its changes staged, you can run (it is not run for you): "
                         "git reset --soft HEAD@{1}")
        else:
            lines.append("To undo what was just brought in, you can run (it is not run for you, and it discards "
                         "uncommitted changes): git reset --hard ORIG_HEAD")
        print("\n".join(lines), file=sys.stderr)
    return 0


def install_hooks(root: Path) -> int:
    """The wall check in every zone's repository, in each wiki that is a
    repository, and in every repository inside a project, which checks its staged files against the walls of the
    project's party, as a zone's does."""
    ws = discover(root)
    code = 0
    for zone in ws.zones:
        try:
            hook = install_wall_hook(zone)
            print("%s: wall check installed at %s%s" % (zone.name, rel(ws, hook), MERGE_SAID))
        except MergeHookNotGarricks as exc:      # pre-commit and the other hooks are written; this one is left, and said
            print("%s: wall check installed at .git/hooks/pre-commit; %s" % (zone.name, exc))
        except (FileExistsError, FileNotFoundError) as exc:
            print("%s: %s" % (zone.name, exc), file=sys.stderr)
            code = 1
    for wiki in wiki_repos(ws):
        try:
            hook = install_wall_hook(wiki, wiki=True, root=ws.root)
            print("%s: wall check installed at %s%s" % (rel(ws, wiki), rel(ws, hook), MERGE_SAID))
        except MergeHookNotGarricks as exc:
            print("%s: wall check installed at .git/hooks/pre-commit; %s" % (rel(ws, wiki), exc))
        except (FileExistsError, FileNotFoundError) as exc:
            print("%s: %s" % (rel(ws, wiki), exc), file=sys.stderr)
            code = 1
    for repo, project, pfm in project_repos(ws):
        parties = ", ".join(strip_tag(t) for t in as_list(pfm.get("party"))) or "no party"
        try:
            hook = install_wall_hook(repo, nested=True)
            print("%s: wall check installed at %s%s, on %s's side" % (rel(ws, repo), rel(ws, hook), MERGE_SAID, parties))
        except MergeHookNotGarricks as exc:
            print("%s: wall check installed at .git/hooks/pre-commit, on %s's side; %s" % (rel(ws, repo), parties, exc))
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
    against this workspace's Zones table. 0 when each row run
    gives its expected answer, 1 when one does not, 2 when there is no table."""
    path = root / "System" / "tools" / "walls-cases.md"
    text = read_text(path)
    if text is None:                    # run from a Garrick clone, on a workspace that has not been updated yet
        path = Path(__file__).resolve().with_name("walls-cases.md")
        text = read_text(path)
    if text is None:
        print("check: %s is missing, so there are no cases to run" % path.relative_to(root).as_posix(), file=sys.stderr)
        return 2
    context = load_context(root)
    ran, skipped, failed = run_wall_cases(context, text)
    print("%d wall cases run against this workspace's Zones table, %d failed, %d skipped."
          % (ran, len(failed), len(skipped)))
    for line in failed:
        print("  failed  " + line)
    for line in skipped:
        print("  skipped " + line + ": the table holds no zone for that role")
    roles = zone_roles(context)
    if "near" not in roles or "far" not in roles:
        print("  no wall row ran: the Zones table holds fewer than two walled zones, so nothing was "
              "checked about walls")
        return 1
    return 1 if failed or not ran else 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["allow"]:
        return allow_command(argv[1:])
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
    parser.add_argument("--changed", nargs="+", metavar="REV",
                        help="the walls check, read only, on the files these commits changed in the current folder's "
                             "repository (`A..B` is what changed from A to B), and a report; it refuses nothing, "
                             "for the post-merge and post-rewrite hooks")
    parser.add_argument("--after", choices=("merge", "rebase", "amend"), default="merge",
                        help="with --changed: what brought the commits in, which decides how the report says to undo it")
    parser.add_argument("--staged", action="store_true",
                        help="check only the files staged in the current folder's git repository (implies --walls-only)")
    parser.add_argument("--install-hooks", action="store_true",
                        help="install the pre-commit wall check in every zone's repository, and in each repository inside a project")
    parser.add_argument("--walls-cases", action="store_true",
                        help="run the table of wall cases (System/tools/walls-cases.md) against this workspace's own "
                             "Parties table, with its tags in place of the fixture's")
    parser.add_argument("--version", action="store_true",
                        help="say which Garrick the workspace was installed from, for a bug report")
    parser.add_argument("--verbose", action="store_true",
                        help="with --staged: one line for every refusal, each with the id that lets it through "
                             "(`check.py allow <path> <id>`), not the short report")
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
    if args.changed:
        try:
            return changed_command(root, args.changed, args.after)
        except Exception:       # a report after the fact never fails a merge
            return 0
    if args.walls_cases:
        return walls_cases(root)
    if args.version:
        stamp = read_version(root)
        print(" ".join(s for s in (say_version(stamp), say_changes(root, stamp)) if s))
        newer = say_newer_release(root)        # what GitHub last said, kept on disk; the check never asks
        if newer:
            print(newer)
        for line in stale_bands(root):         # the band's own copy, read as the settings name it
            print(line)
        return 0
    if args.paths:
        findings = run_path_checks(root, args.paths)
    else:
        findings = run_checks(root, walls_only=args.walls_only, staged=Path.cwd() if args.staged else None, quick=args.quick)
    if args.staged and any(f.severity == ERROR for f in findings):
        record_refusals(root, Path.cwd(), [f.message for f in findings if f.severity == ERROR])
    if args.staged and not (args.json or args.ear):
        text = report_staged(findings, args.verbose)
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
