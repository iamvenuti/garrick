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
import re
import sys
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


def land(root: Path, inbox: "str | Path", date_iso: str, title: str) -> Tuple[str, Path]:
    """Move a transcript out of `raw/inbox/` and name it `YYMMDD-slug.ext`.

    Never edits the file's contents. Refuses a file that is not directly in
    `raw/inbox/`, a link, a file that is not a transcript Garrick reads, a bad
    date, a workspace with no Meetings wiki, and a link on the way to `raw/`
    that leads out of the wiki.
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


def rebuild_index(root: Path) -> Tuple[Path, int]:
    """Rewrite `wiki/index.md` from every page's own frontmatter, newest first."""
    meetings = meetings_root(root)
    pages: List[Path] = []
    for folder in (meetings / "wiki" / "sources", meetings / "wiki" / "people"):
        if folder.is_dir():
            pages += sorted(p for p in folder.glob("*.md"))
    rows = [_page_row(root, p) for p in pages]
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    lines = ["# Index", "", "Every page, newest first.", "", "| Page | Type | Updated |", "|---|---|---|"]
    lines += [r[2] for r in rows]
    index_path = meetings / "wiki" / "index.md"
    with filing(root):
        write_over(root, meetings, index_path, ("\n".join(lines) + "\n").encode("utf-8"))
    return index_path, len(rows)


# --------------------------------------------------------------------------- log


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
    head_end = len(lines)
    for i, line in enumerate(lines):
        if line.strip().startswith("One line per ingest"):
            head_end = i + 1
            break
    while head_end < len(lines) and lines[head_end].strip() == "":
        head_end += 1
    head = lines[:head_end]
    if head and head[-1].strip() != "":
        head.append("")
    where = ", ".join(p for p in parties if p) or "no parties"
    entry = "- %s: [[wiki/sources/%s|%s]] (%s; %s)" % (today, slug, title, zone or "no zone", where)
    new_lines = head + [entry] + lines[head_end:]
    with filing(root):
        write_over(root, meetings_root(root), log_path, ("\n".join(new_lines) + "\n").encode("utf-8"))
    return log_path


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
