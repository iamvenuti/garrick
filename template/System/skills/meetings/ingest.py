#!/usr/bin/env python3
"""Mechanical steps for the meetings skill.

Landing a transcript, rebuilding the index, logging an ingest and stubbing a
person page are easy to get wrong by hand (a stray filename, a table row out
of order, an overwritten page). Everything that takes judgement -- what a
meeting was about, which zone and parties apply, what was decided -- stays
with whoever is running the skill; this script only does the rest.

    python3 ingest.py land   --root PATH --inbox FILE --date YYYY-MM-DD --title "..."
    python3 ingest.py person --root PATH --name "..." [--party TAG]
    python3 ingest.py index  --root PATH
    python3 ingest.py log    --root PATH --slug YYMMDD-slug --title "..." [--zone Z] [--parties a,b]

Standard library only, Python 3.9 or later. On success prints one line; on
refusal, one line to stderr and exits 1.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import email.parser
import hashlib
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

sys.dont_write_bytecode = True  # keep this skill folder free of __pycache__

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

from garrick_lib import (  # noqa: E402
    OffCourse, landing, move_new, parse_frontmatter, workspace_root, write_new, write_over,
)

RAW_EXTS = {".txt", ".md", ".vtt"}
SLUG_RE = re.compile(r"^\d{6}-[a-z0-9][a-z0-9-]*$")


class Refusal(Exception):
    """A refusal worded for whoever is running the skill."""


# --------------------------------------------------------------------------- naming


def slugify(text: str) -> str:
    """Lower-case letters, digits and hyphens only; never empty."""
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "meeting"


def yymmdd(date_iso: str) -> str:
    y, m, d = date_iso.split("-")
    return y[2:] + m + d


def _stems(*folders: Path) -> set:
    out = set()
    for folder in folders:
        if folder.is_dir():
            out |= {p.stem for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")}
    return out


def build_slug(date_iso: str, title: str, taken: Iterable[str]) -> str:
    """`YYMMDD-slug`, the first form not already in `taken`."""
    taken = set(taken)
    base = "%s-%s" % (yymmdd(date_iso), slugify(title))
    slug, n = base, 2
    while slug in taken:
        slug = "%s-%d" % (base, n)
        n += 1
    return slug


def meetings_root(root: Path) -> Path:
    return root / "Wikis" / "Meetings"


@contextlib.contextmanager
def filing(root: Path):
    """Word what garrick_lib's writers raise as a refusal. They land a file in
    the folder that was checked for it or nowhere: a link that leads out of
    that folder, or one put on the way since the check, is refused."""
    try:
        yield
    except OffCourse as exc:
        raise Refusal("%s is a symbolic link that leads out of the folder Garrick checked, or is outside the "
                      "workspace. Garrick never files through such a link, because the file would land somewhere "
                      "other than the folder it checked. Nothing was moved or written." % _rel(root, exc.link))
    except FileExistsError as exc:
        raise Refusal("%s already exists, so nothing was moved or written; another session may have filed it."
                      % _rel(root, Path(exc.filename or "")))


def _rel(root: Path, path: Path) -> str:
    for base in (root, root.resolve()):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    return str(path)


# --------------------------------------------------------------------------- land


SOURCE_ID_KEYS = ("source-id", "message-id", "recording-id")


def source_id(path: Path) -> str:
    """The ID a recording or a mail carries, lower-cased: an .eml's Message-ID,
    or a `source-id`, `message-id` or `recording-id` in a transcript's or a
    saved mail's frontmatter. Empty when it carries none."""
    try:
        if path.suffix.lower() == ".eml":
            with open(path, "rb") as f:
                head = email.parser.BytesHeaderParser().parse(f)
            return str(head.get("Message-ID") or "").strip().strip("<>").lower()
        fm = parse_frontmatter(path)
    except (OSError, ValueError, TypeError):
        return ""
    for key in SOURCE_ID_KEYS:
        if fm.get(key):
            return str(fm[key]).strip().strip("<>").lower()
    return ""


def already_filed(root: Path, path: Path) -> str:
    """The name of a raw record in Meetings that is this recording or mail
    already: the same bytes, or the same source ID. Empty when there is none.
    raw/inbox/ is not filed yet, so it is never looked in."""
    raw = meetings_root(root) / "raw"
    if not raw.is_dir():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    digest, size, sid = hashlib.sha256(data).hexdigest(), len(data), source_id(path)
    for folder, dirs, files in os.walk(raw):
        here = Path(folder)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and here / d != raw / "inbox")
        for f in sorted(files):
            other = here / f
            if f.startswith(".") or other.resolve() == path.resolve():
                continue
            try:
                same = other.stat().st_size == size and hashlib.sha256(other.read_bytes()).hexdigest() == digest
            except OSError:
                continue
            if same or (sid and other.suffix.lower() in (".eml", ".md", ".txt") and source_id(other) == sid):
                return other.relative_to(raw).with_suffix("").as_posix()
    return ""


def refuse_if_filed(root: Path, path: Path) -> None:
    found = already_filed(root, path)
    if found:
        raise Refusal("%s is already filed as %s: the same %s. Nothing was moved; delete this copy, or, to give "
                      "one long record a page per project, split that page instead." % (
                          path.name, found, "recording" if path.suffix.lower() != ".eml" else "mail"))


def land(root: Path, inbox: "str | Path", date_iso: str, title: str) -> Tuple[str, Path]:
    """Move a transcript out of `raw/inbox/` and name it `YYMMDD-slug.ext`.

    Never edits the file's contents. Refuses a file that is not directly in
    `raw/inbox/`, a link, a file that is not a transcript Garrick reads, a bad
    date, a workspace with no Meetings wiki, a link on the way to `raw/`
    that leads out of the wiki, and a recording already filed: the same
    bytes, or the same source ID, as a record in `raw/`.
    """
    inbox_path = Path(inbox)
    if not inbox_path.is_file():
        raise Refusal("%s is not a file." % inbox_path)
    meetings = meetings_root(root)
    inbox_dir = meetings / "raw" / "inbox"
    if inbox_path.is_symlink() or inbox_path.resolve().parent != inbox_dir.resolve():
        raise Refusal("%s is not in Wikis/Meetings/raw/inbox/. land only takes a transcript from there, "
                      "and never a link to one. Nothing was moved." % inbox_path.name)
    with filing(root):
        landing(root, meetings, inbox_dir / inbox_path.name)
    if inbox_path.suffix.lower() not in RAW_EXTS:
        raise Refusal("%s is not a transcript Garrick reads: use .txt, .md or .vtt." % inbox_path.name)
    try:
        datetime.date.fromisoformat(date_iso)
    except ValueError:
        raise Refusal('"%s" is not a date (YYYY-MM-DD).' % date_iso)
    if not title.strip():
        raise Refusal("A meeting needs a title, even a short one, to name the file.")
    raw_dir = meetings / "raw"
    sources_dir = meetings / "wiki" / "sources"
    if not raw_dir.is_dir():
        raise Refusal("%s does not exist; is %s an installed workspace?" % (raw_dir, root))
    refuse_if_filed(root, inbox_path)
    taken = _stems(raw_dir, sources_dir)
    slug = build_slug(date_iso, title, taken)
    dest = raw_dir / ("%s%s" % (slug, inbox_path.suffix.lower()))
    with filing(root):
        move_new(root, meetings, inbox_path, dest)
    return slug, dest


# --------------------------------------------------------------------------- person


def person_slug(name: str) -> str:
    return slugify(name)


def ensure_person(root: Path, name: str, party: str, today: str) -> Tuple[Path, bool]:
    """Create `wiki/people/<slug>.md` if it does not exist yet.

    Never overwrites an existing person page: identity and party, once
    written, are corrected by hand, not regenerated. Returns (path, created).
    """
    path = meetings_root(root) / "wiki" / "people" / ("%s.md" % person_slug(name))
    if path.is_file():
        return path, False
    party_line = "party: %s\n" % party if party else ""
    text = (
        "---\n"
        "title: %s\n"
        "type: person\n"
        "%s"
        "created: %s\n"
        "updated: %s\n"
        "---\n\n"
        "# %s\n\n"
        "<Who they are, and which party, in a sentence.>\n"
    ) % (name, party_line, today, today, name)
    try:
        with filing(root):
            write_new(root, meetings_root(root), path, text.encode("utf-8"))
    except Refusal:
        if path.is_file() and not path.is_symlink():  # another session made it first
            return path, False
        raise
    return path, True


# --------------------------------------------------------------------------- index


def _page_row(root: Path, path: Path) -> Tuple[str, str, str]:
    fm = parse_frontmatter(path)
    title = fm.get("title") or path.stem
    ptype = fm.get("type") or "page"
    updated = fm.get("updated") or fm.get("created") or fm.get("date") or ""
    rel = path.relative_to(meetings_root(root)).as_posix()
    if rel.endswith(".md"):
        rel = rel[:-3]
    return updated, title, "| [[%s\\|%s]] | %s | %s |" % (rel, title, ptype, updated)


# The part of index.md the command writes; everything outside is the user's.
INDEX_START, INDEX_END = "<!-- garrick:index -->", "<!-- /garrick:index -->"
INDEX_HEADER = "| Page | Type | Updated |"


def merge_index(old: Optional[str], table: List[str]) -> str:
    """index.md with `table` between Garrick's markers and the rest kept.
    Without markers, the table Garrick wrote before them (the one headed
    Page, Type, Updated) is replaced; with neither, the block is added at
    the end. A file that does not exist yet gets Garrick's title too."""
    block = [INDEX_START] + table + [INDEX_END]
    if old is None:
        return "\n".join(["# Index", "", "Every page, newest first.", ""] + block) + "\n"
    lines = old.splitlines()
    marks = [l.strip() for l in lines]
    if INDEX_START in marks and INDEX_END in marks[marks.index(INDEX_START):]:
        start = marks.index(INDEX_START)
        end = start + marks[start:].index(INDEX_END) + 1
    elif INDEX_HEADER in marks:
        start = end = marks.index(INDEX_HEADER)
        while end < len(lines) and marks[end].startswith("|"):
            end += 1
    else:
        while lines and not lines[-1].strip():
            lines.pop()
        start = end = len(lines) + 1
        lines.append("")
    return "\n".join(lines[:start] + block + lines[end:]) + "\n"


def rebuild_index(root: Path) -> Tuple[Path, int]:
    """Rewrite the page table in `wiki/index.md` from every page's own
    frontmatter, newest first, between Garrick's markers. Whatever else the
    file holds, a coverage table or notes at the top, is kept as it is."""
    meetings = meetings_root(root)
    pages: List[Path] = []
    for folder in (meetings / "wiki" / "sources", meetings / "wiki" / "people"):
        if folder.is_dir():
            pages += sorted(p for p in folder.glob("*.md"))
    rows = [_page_row(root, p) for p in pages]
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    table = [INDEX_HEADER, "|---|---|---|"] + [r[2] for r in rows]
    index_path = meetings / "wiki" / "index.md"
    with filing(root):
        old = index_path.read_text(encoding="utf-8") if index_path.is_file() else None
        write_over(root, meetings, index_path, merge_index(old, table).encode("utf-8"))
    return index_path, len(rows)


# --------------------------------------------------------------------------- log


def log_head_end(lines: List[str]) -> int:
    """Where the newest entry goes: after Garrick's "One line per ingest"
    line, or, in a log written without it, after the title and the text
    under it, before the first entry or section. Never at the end of a log
    that has entries, which reads newest first."""
    for i, line in enumerate(lines):
        if line.strip().startswith("One line per ingest"):
            return i + 1
    i = 0
    if lines and lines[0].startswith("# "):
        i = 1
    while i < len(lines):
        stripped = lines[i].lstrip()
        if stripped.startswith(("- ", "* ", "#")) or re.match(r"\d+\. ", stripped):
            break
        i += 1
    return i


def append_log(root: Path, slug: str, title: str, zone: str = "", parties: Optional[Iterable[str]] = None,
                today: Optional[str] = None) -> Path:
    """Add one line to `wiki/log.md`, above the earlier entries."""
    today = today or datetime.date.today().isoformat()
    parties = list(parties or [])
    log_path = meetings_root(root) / "wiki" / "log.md"
    text = log_path.read_text(encoding="utf-8") if log_path.is_file() else (
        "# Log\n\nOne line per ingest, newest first.\n"
    )
    lines = text.splitlines()
    head_end = log_head_end(lines)
    while head_end < len(lines) and lines[head_end].strip() == "":
        head_end += 1
    head = lines[:head_end]
    if head and head[-1].strip() != "":
        head.append("")
    where = ", ".join(p for p in parties if p) or "no parties"
    entry = "- %s: [[wiki/sources/%s|%s]] (%s; %s)" % (today, slug, title, zone or "no zone", where)
    rest = lines[head_end:]
    if rest and not rest[0].lstrip().startswith("- "):
        rest = [""] + rest                  # a section or prose below keeps its blank line
    new_lines = head + [entry] + rest
    with filing(root):
        write_over(root, meetings_root(root), log_path, ("\n".join(new_lines) + "\n").encode("utf-8"))
    return log_path


# --------------------------------------------------------------------------- the link an action carries


def vault_of(root: Path, folder: Path) -> Optional[Path]:
    """The Obsidian vault a folder is in: the nearest folder at or above it,
    up to the workspace root, that holds a .obsidian folder."""
    root = root.resolve()
    for f in (folder.resolve(), *folder.resolve().parents):
        if (f / ".obsidian").is_dir():
            return f
        if f == root:
            return None
    return None


def source_link(root: Path, zone: str, slug: str, title: str = "") -> str:
    """How a line in a zone's Todo.md links to a meeting page. `[[<slug>]]`
    when one Obsidian vault holds both, or neither is in one. When the zone
    and the wikis are vaults of their own, a wikilink would point nowhere,
    so it is an obsidian://open link into the wikis' vault instead."""
    page = meetings_root(root) / "wiki" / "sources" / (slug + ".md")
    zone_vault = vault_of(root, root / "Zones" / zone)
    page_vault = vault_of(root, page.parent)
    if zone_vault is None or page_vault is None or zone_vault == page_vault:
        return "[[%s]]" % slug
    rel = page.resolve().relative_to(page_vault).with_suffix("").as_posix()
    url = "obsidian://open?vault=%s&file=%s" % (urllib.parse.quote(page_vault.name), urllib.parse.quote(rel))
    return "[%s](%s)" % ((title or slug).replace("[", "(").replace("]", ")"), url)


# --------------------------------------------------------------------------- CLI


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Mechanical steps for the meetings skill.")
    ap.add_argument("--root", help="workspace folder (default: the one this script sits in)")
    ap.add_argument("--today", help="YYYY-MM-DD to stamp instead of today, for backfilled meetings")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("land", help="move a transcript out of the inbox and name it")
    p.add_argument("--inbox", required=True, help="path to the file in raw/inbox/")
    p.add_argument("--date", required=True, help="YYYY-MM-DD, the date of the meeting")
    p.add_argument("--title", required=True, help="what the meeting was about, for the slug")

    q = sub.add_parser("person", help="create a person page if one does not exist yet")
    q.add_argument("--name", required=True)
    q.add_argument("--party", default="", help="tag from Parties in System/context.md")

    sub.add_parser("index", help="rebuild wiki/index.md from every page's frontmatter")

    l = sub.add_parser("log", help="add one line to wiki/log.md for a finished ingest")
    l.add_argument("--slug", required=True)
    l.add_argument("--title", required=True)
    l.add_argument("--zone", default="")
    l.add_argument("--parties", default="", help="comma-separated tags")

    k = sub.add_parser("link", help="how a Todo.md line in a zone links to a meeting page")
    k.add_argument("--zone", required=True)
    k.add_argument("--slug", required=True)
    k.add_argument("--title", default="", help="the text of the link, when it cannot be a wikilink")

    args = ap.parse_args(argv)
    try:
        root = Path(args.root).expanduser().resolve() if args.root else workspace_root(HERE)
    except FileNotFoundError:
        print("This script is not inside a Garrick workspace.", file=sys.stderr)
        return 1

    today = args.today or datetime.date.today().isoformat()
    try:
        if args.command == "land":
            slug, dest = land(root, args.inbox, args.date, args.title)
            print("%s\t%s" % (slug, dest.relative_to(root)))
        elif args.command == "person":
            path, created = ensure_person(root, args.name, args.party, today)
            print("%s\t%s" % ("created" if created else "exists", path.relative_to(root)))
        elif args.command == "index":
            path, n = rebuild_index(root)
            print("%s: %d page%s" % (path.relative_to(root), n, "" if n == 1 else "s"))
        elif args.command == "link":
            print(source_link(root, args.zone, args.slug, args.title))
        elif args.command == "log":
            parties = [t.strip() for t in args.parties.split(",") if t.strip()]
            path = append_log(root, args.slug, args.title, args.zone, parties, today)
            print(str(path.relative_to(root)))
    except Refusal as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
