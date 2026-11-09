#!/usr/bin/env python3
"""Mechanical steps for the meetings skill.

Landing a transcript, rebuilding the index, logging an ingest and stubbing a
person page are easy to get wrong by hand (a stray filename, a table row out
of order, an overwritten page). Everything that takes judgement -- what a
meeting was about, which zone and parties apply, what was decided -- stays
with whoever is running the skill; this script only does the rest.

    python3 ingest.py land   --root PATH --inbox FILE --date YYYY-MM-DD --title "..."
    python3 ingest.py person --root PATH --name "..." [--party TAG] [--organisation ENTITY]
    python3 ingest.py index  --root PATH
    python3 ingest.py log    --root PATH --slug YYMMDD-slug --title "..." [--zone Z] [--parties a,b]
    python3 ingest.py split   --root PATH --inbox FILE --part "cedar:1-40" --part "maple:41-80" --part "cedar,maple:81-100" [--yes]
    python3 ingest.py extract --root PATH --raw FILE --lines 12-30 --parties cedar [--yes]

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
from garrick_lib import hats_of, load_context, organisation_link, organisation_named  # noqa: E402  (the person page's entity link)
from garrick_lib import labels as record_labels, strip_tag, write_new  # noqa: E402

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


# A fade moves pages and their raw records into dormant/ and archive/ inside
# their wiki (System/tools/fade.py). A name stays taken there: a new page
# with a faded page's name would make every link to either mean both.
FADED = ("dormant", "archive")


def taken_stems(wiki: Path, *subs: str) -> set:
    """Every name used in these folders of a wiki, at every grade."""
    return _stems(*[wiki.joinpath(*([g] if g else []), *sub.split("/")) for g in ("",) + FADED for sub in subs])


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
    raw/inbox/ is not filed yet, so it is never looked in. A record that
    faded with its page is still filed, under dormant/ or archive/."""
    raw = meetings_root(root) / "raw"
    if not raw.is_dir():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    digest, size, sid = hashlib.sha256(data).hexdigest(), len(data), source_id(path)
    for grade in ("",) + FADED:
        found = _filed_in(meetings_root(root) / grade / "raw" if grade else raw, raw, path, digest, size, sid)
        if found:
            return (grade + "/" if grade else "") + found
    return ""


def _filed_in(raw: Path, inbox_raw: Path, path: Path, digest: str, size: int, sid: str) -> str:
    if not raw.is_dir():
        return ""
    for folder, dirs, files in os.walk(raw):
        here = Path(folder)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and here / d != inbox_raw / "inbox")
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
    if not raw_dir.is_dir():
        raise Refusal("%s does not exist; is %s an installed workspace?" % (raw_dir, root))
    refuse_if_filed(root, inbox_path)
    taken = taken_stems(meetings, "raw", "wiki/sources")
    slug = build_slug(date_iso, title, taken)
    dest = raw_dir / ("%s%s" % (slug, inbox_path.suffix.lower()))
    with filing(root):
        move_new(root, meetings, inbox_path, dest)
    return slug, dest


# --------------------------------------------------------------------------- person


def person_slug(name: str) -> str:
    return slugify(name)


def ensure_person(root: Path, name: str, party: str, today: str, organisation: str = "",
                  why: Optional[List[str]] = None) -> Tuple[Path, bool]:
    """Create `wiki/people/<slug>.md` if it does not exist yet.

    Never overwrites an existing person page: identity and party, once
    written, are corrected by hand, not regenerated. Returns (path, created).

    A new page links the entity page of where the person works,
    `organisation:` (#330). With `organisation`, the entity page the user
    named, by its file name, its link, or a title or alias one page alone
    goes by, as garrick_lib's organisation_named() finds it: never made
    here. Without, the entity page of its party, when exactly one entity
    page names that party (organisation_link). Nothing otherwise: the link
    is identity alone, and both leave it out where a walled party is not named, such as for a
    name the People table places under two parties, one of them walled. Why a named entity
    page was not linked goes into `why`, when given.
    """
    path = meetings_root(root) / "wiki" / "people" / ("%s.md" % person_slug(name))
    if path.is_file():
        return path, False
    party_line = "party: %s\n" % party if party else ""
    if organisation:
        link, problem = organisation_named(root, load_context(root), name, party, organisation)
        if problem and why is not None:
            why.append(problem)
    else:
        link = organisation_link(root, load_context(root), name, party) if party else ""
    if link:
        party_line += 'organisation: "%s"\n' % link
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
    for folder in (meetings / "wiki" / "sources", meetings / "wiki" / "people", meetings / "wiki" / "decisions"):
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
    if lines and lines[0].strip() == "---":           # frontmatter is never written into
        end = next((j for j in range(1, len(lines)) if lines[j].rstrip("\r") in ("---", "...")), None)
        i = end + 1 if end is not None else 0
        while i < len(lines) and not lines[i].strip():
            i += 1
    if i < len(lines) and lines[i].startswith("# "):
        i += 1
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


# --------------------------------------------------------------------------- split and extract
#
# A conversation that carries two walled parties is cut in the inbox, before it is a record, into a file for each
# label set: one for each party alone and one for what belongs to both. A record already filed is never edited:
# an extract is a new file cut from it, with its own page and label set, and the original keeps its full labels.
# The helper does the cutting, by line numbers, and writes each file's frontmatter. Which passage belongs to which
# party is never decided here, and never by speaker or timestamp alone: whoever runs the skill proposes the cuts
# and the user decides. Nothing is written without `--yes`, and a run with nobody to answer never writes.


def parse_ranges(spec: str) -> List[Tuple[int, int]]:
    """`1-40,60-70` or `5` as inclusive 1-based line ranges, in the order written."""
    out = []
    for piece in [p.strip() for p in (spec or "").split(",") if p.strip()]:
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", piece)
        if not m:
            raise Refusal('"%s" is not a line range: write 1-40, or 12.' % piece)
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b < a:
            raise Refusal('"%s" is not a line range: lines count from 1 and run forward.' % piece)
        out.append((a, b))
    if not out:
        raise Refusal("A cut needs at least one line range.")
    return out


def _tags_of(root: Path, spec: str) -> List[str]:
    """The parties of one cut, sorted: each a tag of the Parties table, none two hats of one company."""
    ctx = load_context(root)
    tags = sorted({strip_tag(t) for t in (spec or "").split(",") if strip_tag(t)})
    if not tags:
        raise Refusal("A cut needs the parties it is written for.")
    unknown = [t for t in tags if t not in ctx.get("parties", {})]
    if unknown:
        raise Refusal("`%s` is not a tag in the Parties table, so no wall can see it." % unknown[0])
    if hats_of(ctx, tags):
        raise Refusal("`%s` and `%s` are one company in two hats: a record never names both." % hats_of(ctx, tags)[0])
    return tags


def _lines(path: Path) -> Tuple[List[str], int]:
    """(the file's lines, each with its ending, and the count of leading lines that are its frontmatter)."""
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise Refusal("%s cannot be read as text." % path.name)
    lines = text.splitlines(keepends=True)
    head = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                head = i + 1
                break
    return lines, head


# The only keys a cut takes from the original's frontmatter: mechanical ones. A title, an attendee
# line, a summary or any free text can name a party the cut is not written for, so none is carried.
CARRY_KEYS = ("date", "type", "language", "duration")
# and each only with a value of its own shape, so no free text rides in under a mechanical key
CARRY_SHAPES = {"date": r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?", "language": r"[a-z]{2,3}(-[A-Za-z]{2})?",
                "duration": r"\d+(\.\d+)?\s*(s|m|min|h)?", "type": r"(meeting|call|transcript|mail|note)"}


def _carried(line: str) -> bool:
    key, sep, value = line.partition(":")
    key, value = key.strip().lower(), value.strip().strip("\"'")
    return (bool(sep) and not line[:1].isspace() and key in CARRY_KEYS
            and re.fullmatch(CARRY_SHAPES[key], value) is not None)


def _neutral_stem(stem: str) -> str:
    """A cut's name keeps only the date its original's name opens with: the rest of a name is free text, and can
    name a party the cut is not written for."""
    m = re.match(r"(\d{6}|\d{4}-\d{2}-\d{2})(?!\d)", stem)
    return m.group(1) if m else "cut"


def _origin(stem: str) -> str:
    """What links a cut or an extract to the file it came from, without naming it: a short hash of its name."""
    return hashlib.sha1(stem.encode("utf-8")).hexdigest()[:10]


def _header(suffix: str, tags: List[str], extra: List[Tuple[str, str]], lines: List[str], head: int,
            title: str = "") -> str:
    """The cut's own head: the original's mechanical keys (CARRY_KEYS) only, then ours, with a title of its own:
    the one given, or a neutral one built from the date and the cut's parties.
    A .vtt keeps WEBVTT first and our keys as header lines under it, as the format allows."""
    keep = [l if l.endswith("\n") else l + "\n" for l in (lines[1:head - 1] if head else []) if _carried(l)]
    date = next((l.split(":", 1)[1].strip().strip("\"'") for l in keep if l.split(":", 1)[0].strip().lower() == "date"), "")
    title = " ".join((title or "").split()) or "Meeting%s, %s" % (" " + date if date else "", ", ".join(tags))
    own = ["title: %s\n" % ('"%s"' % title.replace('"', "'") if ":" in title or "#" in title else title),
           "parties: [%s]\n" % ", ".join(tags)] + ["%s: %s\n" % kv for kv in extra]
    if suffix == ".vtt":
        return "WEBVTT\n" + "".join("%s\n" % l.rstrip("\n").replace("[", "(").replace("]", ")") for l in own) + "\n"
    return "---\n" + "".join(keep) + "".join(own) + "---\n\n"


def _take(lines: List[str], head: int, ranges: List[Tuple[int, int]], suffix: str) -> str:
    out = []
    for a, b in ranges:
        if a <= head:
            raise Refusal("Lines %d-%d reach into the file's own frontmatter, which is carried over, never cut." % (a, b))
        if b > len(lines):
            raise Refusal("Line %d is past the end of the file, which has %d lines." % (b, len(lines)))
        out += lines[a - 1:b]
    body = "".join(out)
    return body if body.endswith("\n") else body + "\n"


def _headless(yes: bool) -> None:
    if yes and os.environ.get("GARRICK_HEADLESS"):
        raise Refusal("A scheduled run has nobody to ask, so it writes nothing: the user's yes is given in a session.")


def _name(stem: str, tags: List[str], middle: str = "") -> str:
    return "-".join([stem] + ([middle] if middle else []) + tags)


def split_plan(root: Path, inbox: "str | Path", parts: List[str], drop: str = "") -> Tuple[Path, List[dict]]:
    """Check a split of an inbox transcript by label set and say what it would make: [{name, tags, ranges, lines}].
    Every line must belong to a cut (or be dropped by name, or be blank) and to one only."""
    src = Path(inbox)
    meetings = meetings_root(root)
    inbox_dir = meetings / "raw" / "inbox"
    if not src.is_file() or src.is_symlink() or src.resolve().parent != inbox_dir.resolve():
        raise Refusal("%s is not a file in Wikis/Meetings/raw/inbox/. Only a transcript there is split: once it is a "
                      "record it is never cut, only extracted from." % src.name)
    if src.suffix.lower() not in RAW_EXTS:
        raise Refusal("%s is not a transcript Garrick reads: use .txt, .md or .vtt." % src.name)
    if len(parts) < 2:
        raise Refusal("A split has at least two cuts, such as --part cedar:1-40 --part maple:41-80.")
    lines, head = _lines(src)
    plan, seen, owner = [], set(), {}
    for spec in parts:
        who, _, rng = spec.partition(":")
        tags, ranges = _tags_of(root, who), parse_ranges(rng)
        if tuple(tags) in seen:
            raise Refusal("Two cuts are written for the same parties (%s): put their lines in one." % ", ".join(tags))
        seen.add(tuple(tags))
        for a, b in ranges:
            for n in range(a, min(b, len(lines)) + 1):
                if n in owner:
                    raise Refusal("Line %d is in two cuts; a line belongs to one label set." % n)
                owner[n] = tuple(tags)
        plan.append({"name": _name(_neutral_stem(src.stem), tags) + src.suffix.lower(), "tags": tags, "ranges": ranges,
                     "lines": sum(min(b, len(lines)) - a + 1 for a, b in ranges)})
    if drop:
        for a, b in parse_ranges(drop):
            for n in range(a, min(b, len(lines)) + 1):
                if n in owner:
                    raise Refusal("Line %d is in a cut and also dropped." % n)
                owner[n] = ()
    loose = [n for n in range(head + 1, len(lines) + 1) if n not in owner and lines[n - 1].strip()]
    if loose:
        raise Refusal("%d line%s belong to no cut, starting at line %d. The original is deleted once it is split, so "
                      "every line goes into a cut or is dropped by name with --drop." % (len(loose), "" if len(loose) == 1 else "s", loose[0]))
    taken = taken_stems(meetings, "raw", "raw/inbox", "wiki/sources")
    for p in plan:                                  # a second split of the same day and parties is numbered
        stem, n = Path(p["name"]).stem, 2
        name = stem
        while name in taken:
            name, n = "%s-%d" % (stem, n), n + 1
        taken.add(name)
        p["name"] = name + src.suffix.lower()
    return src, plan


def split(root: Path, inbox: "str | Path", parts: List[str], drop: str = "", yes: bool = False,
          titles: Optional[List[str]] = None) -> Tuple[List[dict], bool]:
    """Cut an inbox transcript into one file per label set, in the inbox, each with its own frontmatter, and remove
    the original: an inbox is no record. With no `yes` it says what it would make and writes nothing.
    Returns (the plan, whether it wrote)."""
    _headless(yes)
    src, plan = split_plan(root, inbox, parts, drop)
    if not yes:
        return plan, False
    lines, head = _lines(src)
    meetings, made = meetings_root(root), []
    try:
        with filing(root):
            for i, p in enumerate(plan):
                title = titles[i] if titles and i < len(titles) else ""
                text = _header(src.suffix.lower(), p["tags"], [("split-of", _origin(src.stem))], lines, head, title) + _take(lines, head, p["ranges"], src.suffix.lower())
                made.append(write_new(root, meetings, src.parent / p["name"], text.encode("utf-8")))
    except BaseException:
        for path in made:
            path.unlink()
        raise
    src.unlink()
    return plan, True


def extract_plan(root: Path, raw: "str | Path", lines_spec: str, parties: str) -> Tuple[Path, dict]:
    meetings = meetings_root(root)
    src = Path(raw)
    raw_dir = meetings / "raw"
    inbox_dir = raw_dir / "inbox"
    try:
        under = src.resolve().relative_to(raw_dir.resolve())
    except ValueError:
        under = None
    if under is None or not src.is_file() or src.is_symlink() or src.resolve().parent == inbox_dir.resolve():
        raise Refusal("%s is not a filed record in Wikis/Meetings/raw/. An extract is cut from a record; a transcript "
                      "still in the inbox is split." % src.name)
    if src.suffix.lower() not in RAW_EXTS:
        raise Refusal("%s is not a transcript Garrick reads: use .txt, .md or .vtt." % src.name)
    tags, ranges = _tags_of(root, parties), parse_ranges(lines_spec)
    held = record_labels(root, src.resolve().relative_to(root.resolve()))
    if held is None:
        raise Refusal("%s has no page that cites it, so it has no label set to narrow." % src.name)
    wider = [t for t in tags if t not in held]
    if wider:
        raise Refusal("An extract is never wider than its record: `%s` is not on %s, which is written for %s."
                      % (wider[0], src.name, ", ".join(sorted(held))))
    lines, head = _lines(src)
    for a, b in ranges:
        _take(lines, head, [(a, b)], src.suffix.lower())          # the same bounds checks
    stem = _name(_neutral_stem(src.stem), tags, "extract")
    taken = taken_stems(meetings, "raw", "raw/inbox", "wiki/sources")
    n, name = 2, stem
    while name in taken:
        name, n = "%s-%d" % (stem, n), n + 1
    return src, {"name": name + src.suffix.lower(), "tags": tags, "ranges": ranges, "of": _origin(src.stem),
                 "lines": sum(b - a + 1 for a, b in ranges), "held": sorted(held)}


def extract(root: Path, raw: "str | Path", lines_spec: str, parties: str, yes: bool = False, title: str = "") -> Tuple[dict, bool]:
    """A new file in the inbox cut from a filed record, with its own label set. The record is only read: it is never
    edited, and keeps its full labels. With no `yes` it writes nothing. Returns (the plan, whether it wrote)."""
    _headless(yes)
    src, plan = extract_plan(root, raw, lines_spec, parties)
    if not yes:
        return plan, False
    lines, head = _lines(src)
    text = _header(src.suffix.lower(), plan["tags"], [("extract-of", plan["of"])], lines, head, title) + _take(lines, head, plan["ranges"], src.suffix.lower())
    with filing(root):
        write_new(root, meetings_root(root), meetings_root(root) / "raw" / "inbox" / plan["name"], text.encode("utf-8"))
    return plan, True


def _say_ranges(ranges: List[Tuple[int, int]]) -> str:
    return ",".join("%d-%d" % r if r[0] != r[1] else str(r[0]) for r in ranges)


# --------------------------------------------------------------------------- the link an action carries


def source_link(root: Path, zone: str, slug: str, title: str = "") -> str:
    """How a line in a zone's Todo.md links to a meeting page: a Markdown link
    to the page's file, relative to the zone's Todo.md,
    `[<title>](../../Wikis/Meetings/wiki/sources/<slug>.md)`, which every
    Markdown reader follows, Obsidian included, whichever folders it opens as
    vaults. Never an obsidian: link, which opens Obsidian whatever the user
    chose (#318). Lines written before keep theirs: the readers take both."""
    page = meetings_root(root) / "wiki" / "sources" / (slug + ".md")
    rel = os.path.relpath(str(page), str(root / "Zones" / zone)).replace(os.sep, "/")
    return "[%s](%s)" % ((title or slug).replace("[", "(").replace("]", ")"), urllib.parse.quote(rel))


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
    q.add_argument("--organisation", default="",
                   help="the entity page of where they work: its file name in wiki/entities/, or a title or alias")

    sub.add_parser("index", help="rebuild wiki/index.md from every page's frontmatter")

    l = sub.add_parser("log", help="add one line to wiki/log.md for a finished ingest")
    l.add_argument("--slug", required=True)
    l.add_argument("--title", required=True)
    l.add_argument("--zone", default="")
    l.add_argument("--parties", default="", help="comma-separated tags")

    k = sub.add_parser("link", help="how a Todo.md line in a zone links to a meeting page")
    k.add_argument("--zone", required=True)
    k.add_argument("--slug", required=True)
    k.add_argument("--title", default="", help="the text of the link (default: the slug)")

    sp = sub.add_parser("split", help="cut an inbox transcript into a file for each label set (writes only with --yes)")
    sp.add_argument("--inbox", required=True, help="path to the file in raw/inbox/")
    sp.add_argument("--part", action="append", default=[], metavar="TAGS:LINES",
                    help="one cut: the parties it is written for and its lines, such as cedar,maple:81-100")
    sp.add_argument("--title", action="append", default=[], help="a title for each cut, in the order of the --part flags; "
                    "without one a cut gets a neutral title from the date and its parties")
    sp.add_argument("--drop", default="", help="lines to leave out of every cut, named on purpose")
    sp.add_argument("--yes", action="store_true", help="the user said yes in this session: write the files, remove the original")

    ex = sub.add_parser("extract", help="a new inbox file cut from a filed record, with its own label set (writes only with --yes)")
    ex.add_argument("--raw", required=True, help="the filed record under raw/")
    ex.add_argument("--lines", required=True, help="the lines to take, such as 12-30,44-50")
    ex.add_argument("--parties", required=True, help="comma-separated tags the extract is written for; never wider than the record")
    ex.add_argument("--title", default="", help="the extract's own title; without one it gets a neutral title")
    ex.add_argument("--yes", action="store_true", help="the user said yes in this session: write the file")

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
            why: List[str] = []
            path, created = ensure_person(root, args.name, args.party, today, args.organisation, why)
            print("%s\t%s" % ("created" if created else "exists", path.relative_to(root)))
            for line in why:
                print("no organisation link: %s" % line, file=sys.stderr)
            if args.organisation and not created:
                print("no organisation link: the page was there already, and is changed by hand or by Nurture",
                      file=sys.stderr)
        elif args.command == "index":
            path, n = rebuild_index(root)
            print("%s: %d page%s" % (path.relative_to(root), n, "" if n == 1 else "s"))
        elif args.command == "split":
            plan, wrote = split(root, args.inbox, args.part, args.drop, args.yes, args.title)
            for p in plan:
                print("%s\t%s\tlines %s (%d)" % (p["name"], ",".join(p["tags"]), _say_ranges(p["ranges"]), p["lines"]))
            print("Split %s and removed it." % Path(args.inbox).name if wrote else
                  "Nothing was written. Show the user these cuts; on their yes, run it again with --yes.")
        elif args.command == "extract":
            plan, wrote = extract(root, args.raw, args.lines, args.parties, args.yes, args.title)
            print("%s\t%s\tlines %s (%d) of %s, written for %s" % (plan["name"], ",".join(plan["tags"]), _say_ranges(plan["ranges"]),
                                                              plan["lines"], plan["of"], ", ".join(plan["held"])))
            print("Wrote it in raw/inbox/; %s is unchanged." % Path(args.raw).name if wrote else
                  "Nothing was written. Show the user this cut; on their yes, run it again with --yes.")
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
