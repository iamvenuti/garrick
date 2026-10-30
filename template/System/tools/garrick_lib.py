"""Shared helpers for Garrick's tools.

Standard library only, Python 3.9 or later. The checker (`check.py`),
`scaffold.py` and the installer all import this module, so the public
functions below keep their signatures:

    parse_frontmatter(path) -> dict
    is_path_safe(name) -> (bool, str)
    is_display_name(name) -> (bool, str)
    is_sayable(name) -> (bool, str)
    spoken_forms(name, spoken=None) -> [str]
    spoken_of(folder) -> str
    spoken_clash(a, b, a_spoken=None, b_spoken=None) -> (str, str) or None
    sounds_alike(a, b) -> bool
    tag_for(name, taken=(), zone=None) -> str
    load_context(root) -> dict
    as_sources(value) -> [str] / is_origin(source) -> bool / inbound_only(sources) -> bool
    origin_problems(frontmatter) -> [str] / memory_origin(text) -> {source, created}
    learned_cell(date, sources) -> str / parse_learned(cell) -> (date, [source]) or None
    learned_row(lines, rows, cells, learned) -> str
    memory_folders(root, value=None) -> [Path] / memory_entries(folders) -> [Path]
    walled(context, tag_a, tag_b) -> bool
    workspace_root(start=None) -> Path
    nested_repo(folder) -> bool / is_checkout(folder) -> bool
    live_files(folder) -> [Path]
    link_on_the_way(base, path) -> Path or None
    landing(root, home, path) -> Path
    write_new(root, home, path, data) / write_over(...) / move_new(root, home, src, path)
    resume_lines(text) -> [str] / resume_hash(text) -> str or None
    read_checkpoint(text) -> dict or None
    render_checkpoint(at, base, items) -> (block, key)
    place_checkpoint(text, body) -> str or None
    rebase_checkpoint(text, base) -> str or None
    checkpoint_key(base, content) -> str
    write_if_unchanged(note, text, expect) -> bool
    same_action(line) -> str
    install_wall_hook(zone) -> Path
    work_folder(root, value) -> Path or None
    has_wall_hook(zone) -> bool
    hooks_path(repo) -> str
    skill_links(root, repo) -> [(link, target)]
    init_repo(path, message, identity=None, paths=None)
    foreign_git_env(env=None) -> dict or None
    table_row(cells) -> str
    parse_mail(path) -> dict
    mail_attachments(data) -> [(name, type, bytes)]
    stamp_parties(data, tags) -> bytes; stamped_parties(data) -> [tag]
    parties_for_domain(context, domain) -> [tag]
    is_webmail(domain) -> bool
    status_command(root, settle=None) -> [str] or None
    detach(cmd) -> bool
"""

from __future__ import annotations

import datetime
import email
import email.parser
import email.policy
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import unicodedata
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

PathLike = Union[str, "os.PathLike[str]"]

__all__ = [
    "is_own_address",
    "parse_frontmatter",
    "parse_frontmatter_text",
    "is_path_safe",
    "is_display_name",
    "is_sayable",
    "NAME_LIMIT",
    "spoken_forms",
    "spoken_of",
    "spoken_clash",
    "sounds_alike",
    "normalise_name",
    "TAG_RE",
    "TAG_RULE",
    "tag_for",
    "phonetic_key",
    "edit_distance",
    "load_context",
    "ORIGIN_USER",
    "ORIGIN_PREFIXES",
    "LEARNED_COLUMN",
    "MEMORY_SETTING",
    "CHECK_SETTINGS",
    "as_sources",
    "is_origin",
    "inbound_only",
    "origin_problems",
    "memory_origin",
    "ORIGIN_KEYS",
    "learned_cell",
    "parse_learned",
    "learned_row",
    "memory_folders",
    "memory_entries",
    "knowledge_schema",
    "walled",
    "workspace_root",
    "SKIP_DIRS",
    "NOT_LIVE_DIR_RE",
    "CHECKOUT_TREE",
    "CHECKOUT_MARKS",
    "nested_repo",
    "is_checkout",
    "live_files",
    "link_on_the_way",
    "OffCourse",
    "landing",
    "write_new",
    "write_over",
    "move_new",
    "RESUME_HEADING",
    "RESUME_STOP_RE",
    "resume_lines",
    "resume_hash",
    "CHECKPOINT_HEADING",
    "CHECKPOINT_OPEN",
    "CHECKPOINT_CLOSE",
    "CHECKPOINT_DAYS",
    "CHECKPOINT_KINDS",
    "CHECKPOINT_LABELS",
    "CHECKPOINT_STEMS",
    "CHECKPOINT_ONE",
    "CHECKPOINT_SAID",
    "CHECKPOINT_UNCONFIRMED",
    "checkpoint_key",
    "checkpoint_span",
    "checkpoint_item_line",
    "read_checkpoint",
    "render_checkpoint",
    "place_checkpoint",
    "rebase_checkpoint",
    "said_time",
    "write_if_unchanged",
    "same_action",
    "strip_tag",
    "install_wall_hook",
    "has_wall_hook",
    "hooks_path",
    "WALL_HOOK",
    "WALL_HOOK_NESTED",
    "WALL_HOOK_MARK",
    "ZONE_TEMPLATE",
    "ZONE_TODO",
    "zone_todo",
    "simple_home",
    "INSTRUCTION_FILES",
    "LOCAL_RULES",
    "LOCAL_HEADER",
    "is_instruction_file",
    "local_file",
    "IGNORE_BEGIN",
    "IGNORE_END",
    "MACHINE_IGNORES",
    "machine_made",
    "garrick_ignores",
    "ignore_block",
    "ignore_parts",
    "with_ignore_block",
    "SKILL_FOLDERS",
    "LOCAL_EMAIL",
    "GitError",
    "git",
    "LOCAL_ENV_VARS",
    "git_local_env_vars",
    "foreign_git_env",
    "skill_links",
    "init_repo",
    "table_row",
    "INBOX",
    "MAIL_EXTS",
    "MEDIA_EXTS",
    "parse_mail",
    "parse_mail_bytes",
    "mail_attachments",
    "split_domains",
    "is_domain",
    "is_webmail",
    "parties_for_domain",
]


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:(.*)$")
_ITEM_RE = re.compile(r"^\s*-\s?(.*)$")


def _strip_comment(value: str) -> str:
    """Drop a trailing `# comment` that sits outside quotes."""
    quote = None
    for i, ch in enumerate(value):
        if quote:
            if ch == quote and not (quote == '"' and i and value[i - 1] == "\\"):
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or value[i - 1].isspace()):
            return value[:i].strip()
    return value.strip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner
    return value


def _split_inline(inner: str) -> List[str]:
    """Split the inside of `[a, "b, c", d]` on commas outside quotes."""
    items, buf, quote = [], [], None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))
    return [_unquote(i) for i in items if i.strip()]


def _scalar(value: str):
    value = _strip_comment(value)
    if value == "" or value in ("~", "null", "Null", "NULL"):
        return None
    # An unquoted wikilink looks like a nested list to YAML; people write it
    # anyway, so read it as the link it was meant to be.
    if value.startswith("[[") and value.endswith("]]") and "," not in value:
        return value
    if value.startswith("[") and value.endswith("]"):
        return _split_inline(value[1:-1])
    return _unquote(value)


def parse_frontmatter_text(text: str) -> dict:
    """Parse the YAML frontmatter at the top of `text`. See parse_frontmatter."""
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    body = []
    for line in lines[1:]:
        if line.strip() in ("---", "..."):
            break
        body.append(line)
    else:
        return {}  # never closed: not frontmatter

    result: dict = {}
    current_key: Optional[str] = None
    for line in body:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = _ITEM_RE.match(line)
        if item and current_key is not None and (line[:1].isspace() or line.startswith("-")):
            if not isinstance(result.get(current_key), list):
                result[current_key] = []
            val = _scalar(item.group(1))
            if val is not None:
                result[current_key].append(val)
            continue
        if line[:1].isspace():
            continue  # nested mapping: not used by these templates
        m = _KEY_RE.match(line)
        if not m:
            current_key = None
            continue
        current_key = m.group(1)
        result[current_key] = _scalar(m.group(2))
    return result


def parse_frontmatter(path: PathLike) -> dict:
    """Minimal YAML-frontmatter parser for the fields Garrick's templates use.

    Handles scalars, quoted strings, inline lists `[a, b]`, block lists
    (`- item`) and trailing comments. Values are strings (or lists of
    strings); an empty value is None. Returns {} when the file has no
    frontmatter or cannot be read.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return parse_frontmatter_text(text)


# ---------------------------------------------------------------------------
# Names: what can be stored, what a name may look like, how it is said
#
# Three questions, three answers, because one answer to all three refused
# names people use: a folder name has to be safe to store, a name has to read
# as a name, and a heard name has to find one thread. Only the first is a
# property of the file system; the second is a house style; the third is
# answered by the name itself or, where the writing does not say how to say
# it, by the `spoken` form in the note's frontmatter.
# ---------------------------------------------------------------------------

_APOSTROPHES = "'’"
_HYPHENS = "-‐‑"
_YEAR_RE = re.compile(r"(19|20)\d\d")
# A full stop belongs inside an acronym (U.S., U.S.A), nowhere else in a name.
_ACRONYM_RE = re.compile(r"(?:[^\W\d_]\.)+[^\W\d_]?\Z")
# Characters a folder name cannot hold on a Mac, or in a synced folder.
_UNSAFE = '/\\:*?"<>|'
# Names a synced folder reserves, whatever the extension.
_RESERVED = ({"con", "prn", "aux", "nul"}
             | {"%s%d" % (stem, n) for stem in ("com", "lpt") for n in range(1, 10)})
# A folder name and its note's name both carry it, and a link names it again,
# so the limit is well short of what the file system would take.
NAME_LIMIT = 96
_DIGIT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def is_path_safe(name: str) -> Tuple[bool, str]:
    """Can `name` be stored as a folder, here and in a synced folder?

    Strict, and about storage alone: not empty, no path separator or other
    character a file system refuses, nothing a sync folder reserves or
    strips, no leading dot (hidden) or underscore (a template), and short
    enough that the folder, its note and the links to it stay sane.
    """
    if name is None or not str(name).strip():
        return False, "the name is empty"
    name = str(name)
    if name != name.strip():
        return False, "it starts or ends with a space"
    if name.startswith("_"):
        return False, "it starts with an underscore, which marks a template"
    if name.startswith("."):
        return False, "it starts with a full stop, which hides the folder"
    if name.endswith("."):
        return False, "it ends with a full stop, which a synced folder strips"
    if len(name) > NAME_LIMIT:
        return False, "it is longer than %d characters" % NAME_LIMIT
    for ch in name:
        if ch in _UNSAFE:
            return False, "it contains '%s', which cannot be in a folder name" % ch
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            return False, "it contains a character that cannot be in a folder name"
    if name.split(".")[0].lower() in _RESERVED:
        return False, "%s is a name a synced folder reserves" % name
    return True, ""


def is_display_name(name: str) -> Tuple[bool, str]:
    """May `name` stand as a zone, project or thread name?

    Ordinary business names, which is wider than what can be said as written:
    letters and digits anywhere (Q4 Planning, ISO 27001), spaces, hyphens,
    apostrophes, `&`, and a full stop inside an acronym (U.S. Expansion). No
    other punctuation, since the rest of it is either unsafe to store or a
    separator the spoken grammar already uses, such as the comma in "Acme,
    pricing". At least one letter, which is what a heard name is matched on.
    """
    ok, why = is_path_safe(name)
    if not ok:
        return False, why
    name = str(name)
    if "  " in name:
        return False, "it has a double space"
    for word in name.split(" "):
        if "." in word and not _ACRONYM_RE.match(word):
            return False, "a full stop belongs inside an acronym, as in U.S., not in '%s'" % word
        for ch in word:
            if ch.isalpha() or ch.isdigit() or ch == "&" or ch == "." or ch in _APOSTROPHES or ch in _HYPHENS:
                continue
            if ch == "_":
                return False, "it contains an underscore"
            return False, "it contains '%s', which does not belong in a name" % ch
    if not any(ch.isalpha() for ch in name):
        return False, "it has no letters, so nothing is left to match a heard name on"
    return True, ""


def is_sayable(name: str) -> Tuple[bool, str]:
    """Does `name` say how it is said, or does it need a `spoken` form?

    True for letters, spaces, hyphens, apostrophes, `&` and a year standing as
    a word of its own ("Harbour Summit 2027" is said "twenty twenty-seven").
    False for anything a reader would have to decide how to pronounce: other
    digits (Q4 Planning, ISO 27001) and an acronym's full stops. A name that
    is not sayable is still a good name; it carries `spoken:` in its note's
    frontmatter, and the resolver matches that form alongside the name.
    """
    ok, why = is_display_name(name)
    if not ok:
        return False, why
    for word in str(name).split(" "):
        if _YEAR_RE.fullmatch(word):
            continue
        for ch in word:
            if ch.isdigit():
                return False, "it contains a digit that is not a year, so how to say it is a guess"
            if ch == ".":
                return False, "it contains a full stop, and an acronym is said letter by letter"
    return True, ""


def spoken_forms(name: str, spoken: Optional[str] = None) -> List[str]:
    """What a spoken request can resolve to: the name, and the form the note's
    `spoken` frontmatter gives, where it gives one."""
    forms = [str(name)]
    said = str(spoken or "").strip()
    if said and said.lower() != str(name).lower():
        forms.append(said)
    return forms


def spoken_of(folder: PathLike) -> str:
    """The `spoken` form in the note of a project or thread folder, or ""."""
    folder = Path(folder)
    return str(parse_frontmatter(folder / (folder.name + ".md")).get("spoken") or "").strip()


def spoken_clash(a: str, b: str, a_spoken: Optional[str] = None,
                 b_spoken: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """The first way two sibling names would be heard as one another: a pair of
    forms, one from each, that sound alike. None when they are easy to tell
    apart said aloud."""
    for first in spoken_forms(a, a_spoken):
        for second in spoken_forms(b, b_spoken):
            if sounds_alike(first, second):
                return first, second
    return None


def normalise_name(name: str) -> str:
    """Lower-case letters only, with `&` read as "and", a digit as its word and
    accents dropped."""
    name = unicodedata.normalize("NFKD", name.replace("&", " and "))
    name = "".join(" %s " % _DIGIT_WORDS[int(ch)] if ch.isdigit() else ch for ch in name)
    return "".join(ch for ch in name.lower() if ch.isalpha() and ord(ch) < 0x250)


_DIGRAPHS_START = (("kn", "n"), ("gn", "n"), ("pn", "n"), ("wr", "r"), ("ps", "s"), ("wh", "w"), ("x", "s"))
_DIGRAPHS = (
    ("sch", "sk"), ("tch", "ch"), ("dg", "j"), ("ph", "f"), ("ck", "k"),
    ("qu", "kw"), ("gh", ""), ("sh", "x"), ("ch", "x"), ("th", "0"),
)


def _word_key(word: str) -> str:
    w = normalise_name(word)
    if not w:
        return ""
    for src, dst in _DIGRAPHS_START:
        if w.startswith(src):
            w = dst + w[len(src):]
            break
    w = w.replace("x", "ks")
    for src, dst in _DIGRAPHS:
        w = w.replace(src, dst)
    out = []
    for i, ch in enumerate(w):
        nxt = w[i + 1] if i + 1 < len(w) else ""
        if ch == "c":
            ch = "s" if nxt in "eiy" else "k"
        elif ch == "q":
            ch = "k"
        elif ch == "z":
            ch = "s"
        out.append(ch)
    w = "".join(out)
    first = w[0]
    head = "A" if first in "aeiouy" else first
    rest = [ch for ch in w[1:] if ch not in "aeiouyhw"]
    key = [head]
    for ch in rest:
        if ch != key[-1]:
            key.append(ch)
    return "".join(key)


def phonetic_key(name: str) -> str:
    """A Metaphone-lite key: one code per word, vowels dropped after the first
    letter, common spellings of one sound folded together."""
    words = re.split(r"[\s\-‐‑]+", name.replace("&", " and "))
    return " ".join(k for k in (_word_key(w) for w in words) if k)


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def sounds_alike(a: str, b: str) -> bool:
    """Would two sibling names be confused when spoken?

    True when they are the same once case, spacing and punctuation are gone;
    when their phonetic keys match; or when, both being at least four letters
    long, they are one edit apart.
    """
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ka, kb = phonetic_key(a), phonetic_key(b)
    if ka and (ka == kb or ka.replace(" ", "") == kb.replace(" ", "")):
        return True
    if min(len(na), len(nb)) >= 4 and edit_distance(na, nb) <= 1:
        return True
    return False


# A party's tag: what `party:` in a hub note and `parties:` on a meeting page
# carry, and what the Walls table is written in. One rule, here, because the
# installer takes a tag from each party's name and `scaffold.py party` offers one later;
# two copies of it would let a workspace hold a tag its installer refused.
TAG_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
TAG_RULE = "one lowercase word that starts with a letter, then letters, digits or hyphens"


def tag_for(name: str, taken: Iterable[str] = (), zone: Optional[str] = None) -> str:
    """The tag to offer for a party called `name`: its first word in lower
    case, or, where that is taken, a wider one.

    `taken` is the tags already in Parties. Three widenings, in this order,
    and the first that is valid and free wins: the next word of the name
    (acme, then acme-corp), then the zone folded in (acme-consulting), which
    is what tells one organisation's two capacities apart, then a number
    (acme-2), which is the last resort when the name has no more words.

    "" when the name yields no tag at all, such as 4Birch, whose tag cannot
    start with a digit: there is nothing to offer, and the caller asks.
    """
    held = {str(t).strip().strip("`").lower() for t in taken}
    plain = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    words = [w for w in (re.sub(r"[^a-z0-9]", "", w) for w in plain.split()) if w]
    if not words:
        return ""
    stems = ["-".join(words[:n]) for n in range(1, len(words) + 1)]
    zone_words = [w for w in (re.sub(r"[^a-z0-9]", "", w) for w in
                              unicodedata.normalize("NFKD", zone or "").encode("ascii", "ignore")
                              .decode().lower().split()) if w]
    if zone_words:
        stems += ["%s-%s" % (stem, zone_words[0]) for stem in stems]
    stems += ["%s-%d" % (stems[0], n) for n in range(2, 10)]
    for guess in stems:
        if TAG_RE.match(guess) and guess not in held:
            return guess
    return ""


# ---------------------------------------------------------------------------
# context.md
# ---------------------------------------------------------------------------

def strip_tag(cell: str) -> str:
    """`acme` or `#acme` -> acme."""
    return cell.strip().strip("`").strip().lstrip("#").strip().lower()


def _split_row(line: str) -> List[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current = None
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def _table(lines: List[str]) -> List[Dict[str, str]]:
    """The first Markdown table in `lines`, as dicts keyed by lower-case header."""
    rows: List[Dict[str, str]] = []
    header: Optional[List[str]] = None
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            if header is not None:
                break
            continue
        cells = _split_row(s)
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells)))
    return rows


def _table_header(lines: List[str]) -> Optional[List[str]]:
    """The lower-case header of the first Markdown table in `lines`, or None."""
    for line in lines:
        if line.strip().startswith("|"):
            return [c.lower() for c in _split_row(line.strip())]
    return None


# The sections of context.md read as tables: the columns each is written
# with, and the ones the checks cannot do without.
CONTEXT_TABLES = {
    "zones": (("Zone", "Holds"), ("zone",)),
    "parties": (("Party", "What it is", "Zone", "Tag", "Domains"), ("tag",)),
    "walls": (("Between", "And", "Why"), ()),          # read by position when the names differ
    "people": (("Name", "Party", "Role"), ("name", "party")),
    "aliases": (("Heard", "Means"), ("heard", "means")),
}


def _col(row: Dict[str, str], *names: str) -> str:
    for key, value in row.items():
        for n in names:
            if key == n or key.startswith(n):
                return value
    return ""


def load_context(root: PathLike) -> dict:
    """Parse `System/context.md` of an installed workspace.

    Returns::

        {
          "parties": {tag: {"party": name, "what": ..., "zone": ..., "domains": [...]}},
          "walls":   {frozenset({tag_a, tag_b}), ...},
          "people":  [{"name", "party", "role"}, ...],
          "aliases": {heard (lower case): means},
          "zones":   {zone name: what it holds},
          "me":      [your own addresses, lower case],
          "learned": [{"table", "row", "cell"}, ...],
        }

    `learned` holds each row's Learned cell, where its table has that column
    and the cell is not empty: the rows an assistant added, with where each
    came from. A row typed by hand has none.

    Tags are lower-cased and stripped of backticks. A missing file gives
    empty collections.
    """
    ctx = {"parties": {}, "walls": set(), "people": [], "aliases": {}, "zones": {}, "me": [], "tables": {},
           "learned": []}
    path = Path(root) / "System" / "context.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ctx
    sections = _sections(text)
    for name, (_, columns) in CONTEXT_TABLES.items():
        lines = sections.get(name)
        if lines is None:
            continue
        rows = _table(lines)
        header = _table_header(lines)
        ctx["tables"][name] = {
            "table": header is not None,
            "text": any(l.strip() for l in lines),
            "rows": len(rows),
            "missing": [c for c in columns if header is not None and not any(h.startswith(c) for h in header)],
        }
        column = next((h for h in (header or []) if h.startswith(LEARNED_COLUMN.lower())), None)
        for row in (rows if column else []):
            cell = (row.get(column) or "").strip()
            if cell:
                first = next(iter(row.values()), "")
                ctx["learned"].append({"table": name, "row": strip_tag(first) if name == "walls" else first.strip(),
                                       "cell": cell})

    for addr in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "\n".join(sections.get("me", []))):
        if addr.lower() not in ctx["me"]:
            ctx["me"].append(addr.lower())

    for row in _table(sections.get("parties", [])):
        tag = strip_tag(_col(row, "tag"))
        if not tag:
            continue
        ctx["parties"][tag] = {
            "party": _col(row, "party", "name"),
            "what": _col(row, "what"),
            "zone": _col(row, "zone"),
            "domains": split_domains(_col(row, "domain")),
        }

    for row in _table(sections.get("walls", [])):
        cells = list(row.values())
        a = strip_tag(_col(row, "between") or (cells[0] if cells else ""))
        b = strip_tag(_col(row, "and") or (cells[1] if len(cells) > 1 else ""))
        if a and b:
            ctx["walls"].add(frozenset((a, b)))

    for row in _table(sections.get("people", [])):
        name = _col(row, "name")
        if name:
            ctx["people"].append(
                {"name": name, "party": strip_tag(_col(row, "party")), "role": _col(row, "role")}
            )

    for row in _table(sections.get("aliases", [])):
        heard, means = _col(row, "heard"), _col(row, "means")
        for form in heard.split(","):
            form = form.strip().lower()
            if form and means:
                ctx["aliases"][form] = means

    for row in _table(sections.get("zones", [])):
        zone = _col(row, "zone")
        if zone:
            ctx["zones"][zone] = _col(row, "holds")
    return ctx


# ---------------------------------------------------------------------------
# Origin: where a learned entry came from
#
# What one session learns, a later one reads as fact. So a memory entry the
# assistant keeps, and a row it adds to a table in System/context.md, say where
# they came from: an entry with `source:` and `created:` in its frontmatter, a
# row with a Learned cell, `2026-10-16, user`. A source is `user` (the user
# said it), `file:<path>` (read from a note in the workspace) or
# `inbound:<raw path>` (taken from a mail, a transcript or a page). Rows typed
# by hand carry no Learned cell and stay as they are. Nothing whose only
# source is inbound stands as a belief until a person confirms it.
# ---------------------------------------------------------------------------

ORIGIN_USER = "user"
ORIGIN_PREFIXES = ("file:", "inbound:")
LEARNED_COLUMN = "Learned"
_ISO_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SOURCE_SPLIT_RE = re.compile(r"\s*[,;]\s*(?=(?:user\b|file:|inbound:))")
_LEARNED_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*[,;]\s*(.+)$")


def as_sources(value) -> List[str]:
    """The sources a `source:` value or a Learned cell names: a list as it is,
    and one string split where another source starts, so `inbound:raw/a.eml,
    user` is two."""
    if value is None:
        return []
    items = value if isinstance(value, list) else _SOURCE_SPLIT_RE.split(str(value))
    return [str(s).strip() for s in items if str(s).strip()]


def is_origin(source: str) -> bool:
    """`user`, or `file:` or `inbound:` followed by a path."""
    s = str(source or "").strip()
    return s == ORIGIN_USER or any(s.startswith(p) and s[len(p):].strip() for p in ORIGIN_PREFIXES)


def inbound_only(sources: Iterable[str]) -> bool:
    """Every source given came in from outside: nobody has confirmed it."""
    found = [s for s in (str(x).strip() for x in sources) if s]
    return bool(found) and all(s.startswith("inbound:") for s in found)


def _iso_day(value) -> bool:
    if not _ISO_DAY_RE.match(str(value or "").strip()):
        return False
    try:
        datetime.date.fromisoformat(str(value).strip())
    except ValueError:
        return False
    return True


def origin_problems(fm: dict) -> List[str]:
    """What a memory entry's frontmatter lacks to say where it came from, one
    phrase each; empty when `source:` and `created:` are both there and read."""
    out = []
    sources = as_sources(fm.get("source"))
    if not sources:
        out.append("no `source:`")
    else:
        bad = [s for s in sources if not is_origin(s)]
        if bad:
            out.append("a source that is not `user`, `file:<path>` or `inbound:<raw path>` (%s)" % ", ".join(bad))
    created = fm.get("created")
    if not created:
        out.append("no `created:`")
    elif not _iso_day(created):
        out.append("a `created:` not written YYYY-MM-DD")
    return out


ORIGIN_KEYS = ("source", "created")
MEMORY_METADATA = "metadata"


def memory_origin(text: str) -> dict:
    """`source` and `created` from a memory entry's frontmatter, each from the
    top level or else from a `metadata:` mapping one level down, where an
    assistant keeps keys of its own. Nothing else in the frontmatter is read."""
    fm = parse_frontmatter_text(text)
    out = {k: fm.get(k) for k in ORIGIN_KEYS}
    if all(out.values()) or MEMORY_METADATA not in fm:
        return out
    block: List[str] = []
    inside = False
    for line in text.lstrip("﻿").splitlines()[1:]:
        if line.strip() in ("---", "..."):
            break
        if inside:
            if line.strip() and not line[:1].isspace():
                break
            block.append(line)
        else:
            m = _KEY_RE.match(line)
            inside = bool(m) and m.group(1) == MEMORY_METADATA and not _strip_comment(m.group(2))
    filled = [line for line in block if line.strip()]
    if not filled:
        return out
    indent = min(len(line) - len(line.lstrip()) for line in filled)
    nested = parse_frontmatter_text("---\n%s\n---\n" % "\n".join(line[indent:] for line in block))
    for k in ORIGIN_KEYS:
        if not out[k]:
            out[k] = nested.get(k)
    return out


def learned_cell(date: str, sources) -> str:
    """The Learned cell for a row an assistant adds: `2026-10-16, user`."""
    return "%s, %s" % (date, ", ".join(as_sources(sources)))


def parse_learned(cell: str) -> Optional[Tuple[str, List[str]]]:
    """(date, sources) from a Learned cell; None for an empty cell, a row typed
    by hand; ("", []) for one that does not read."""
    cell = (cell or "").strip().strip("`").strip()
    if not cell:
        return None
    m = _LEARNED_RE.match(cell)
    if not m or not _iso_day(m.group(1)):
        return "", []
    return m.group(1), as_sources(m.group(2))


def learned_row(lines: List[str], rows: List[int], cells: List[str], learned: str) -> str:
    """The row to add to the table whose lines are at `rows` in `lines` (its
    header first, then the separator), with `learned` in its Learned cell.
    Adds the column to the header and the separator, in `lines`, when the
    table has none; every other row is left exactly as it is, since a
    Markdown table reads a short row as one with empty cells at its end."""
    header = _split_row(lines[rows[0]])
    col = next((i for i, c in enumerate(header) if c.lower().startswith(LEARNED_COLUMN.lower())), None)
    if col is None:
        col = max(len(header), len(cells))
        header += [""] * (col - len(header))
        lines[rows[0]] = "| " + " | ".join(header + [LEARNED_COLUMN]) + " |"
        sep = _split_row(lines[rows[1]])
        sep += ["---"] * (col - len(sep))
        lines[rows[1]] = "|" + "|".join(sep + ["---"]) + "|"
    cells = (list(cells) + [""] * col)[:col]
    return table_row(cells + [learned])


# Where an assistant keeps a memory of its own is the harness's business, and
# Garrick does not guess it: `memory` in System/garrick-checks.json names the
# folder, or a list of them, absolute, from your home (`~/...`) or from the
# workspace. Without it, nothing reads a memory. An entry is a Markdown file
# in it; the index a harness keeps beside its entries is not one.
CHECK_SETTINGS = ("System", "garrick-checks.json")
MEMORY_SETTING = "memory"
MEMORY_INDEX = frozenset({"memory.md", "index.md", "readme.md"})


def memory_folders(root: PathLike, value=None) -> List[Path]:
    """The memory folders the workspace names, whether or not they exist.
    `value` is the setting as already read; None reads it from the file."""
    if value is None:
        try:
            data = json.loads(Path(root).joinpath(*CHECK_SETTINGS).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        value = data.get(MEMORY_SETTING) if isinstance(data, dict) else None
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    out = []
    for v in values:
        if isinstance(v, str) and v.strip():
            p = Path(os.path.expanduser(v.strip()))
            out.append(p if p.is_absolute() else Path(root) / p)
    return out


def memory_entries(folders: Iterable[PathLike]) -> List[Path]:
    """Every memory entry in `folders`: each Markdown file, at any depth, but
    for the harness's index and anything in a hidden folder."""
    out: List[Path] = []
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.md")):
            parts = path.relative_to(folder).parts
            if any(p.startswith(".") for p in parts) or path.name.lower() in MEMORY_INDEX or not path.is_file():
                continue
            if path not in out:
                out.append(path)
    return out


# How a Knowledge wiki keeps its raw files and source pages, its index and its
# log: Garrick's layout, unless the wiki declares its own in schema.json.
KNOWLEDGE_SCHEMA = {
    "raw": "raw/{slug}.{ext}",          # also {kind}, {date}, {publisher}, {title}
    "kinds": [],                        # the values {kind} may take, when the pattern has it
    "source": {"type": "source", "fields": ["author", "published", "raw"]},
    "index": "list",                    # or "tables": a table per type
    "log": "line",                      # or "section": a dated section per ingest
}
RAW_PLACEHOLDERS = ("slug", "ext", "kind", "date", "publisher", "title")


def knowledge_schema(root: PathLike) -> Tuple[dict, List[str]]:
    """(the schema, what in it could not be read) for the workspace's
    Knowledge wiki: `Wikis/Knowledge/schema.json` over Garrick's default,
    key by key. What does not read keeps the default, and says so."""
    schema = json.loads(json.dumps(KNOWLEDGE_SCHEMA))
    path = Path(root) / "Wikis" / "Knowledge" / "schema.json"
    if not path.is_file():
        return schema, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return schema, ["schema.json does not read as JSON (%s); Garrick's layout applies" % exc]
    problems = []
    if not isinstance(data, dict):
        return schema, ["schema.json is not an object; Garrick's layout applies"]
    raw = data.get("raw")
    if raw is not None:
        names = re.findall(r"\{(\w+)\}", raw) if isinstance(raw, str) else []
        if not isinstance(raw, str) or not raw.startswith("raw/") or "{ext}" not in raw or ".." in raw \
                or any(n not in RAW_PLACEHOLDERS for n in names) or not ({"slug", "title"} & set(names)):
            problems.append("its raw pattern %r must start raw/, end in {ext}, name {slug} or {title}, and use only "
                            "{%s}" % (raw, "}, {".join(RAW_PLACEHOLDERS)))
        else:
            schema["raw"] = raw
    kinds = data.get("kinds")
    if kinds is not None:
        if isinstance(kinds, list) and all(isinstance(k, str) and re.fullmatch(r"[\w -]+", k) for k in kinds):
            schema["kinds"] = kinds
        else:
            problems.append("its kinds must be a list of folder names")
    if "{kind}" in schema["raw"] and not schema["kinds"]:
        problems.append("its raw pattern names {kind} but it lists no kinds")
        schema["raw"] = KNOWLEDGE_SCHEMA["raw"]
    source = data.get("source")
    if source is not None:
        if isinstance(source, dict) and isinstance(source.get("type", "source"), str) and \
                isinstance(source.get("fields", []), list) and all(isinstance(f, str) for f in source.get("fields", [])):
            schema["source"] = {"type": source.get("type", "source"), "fields": list(source.get("fields", []))}
        else:
            problems.append("its source must say a type and a list of fields")
    for key, allowed in (("index", ("list", "tables")), ("log", ("line", "section"))):
        if key in data:
            if data[key] in allowed:
                schema[key] = data[key]
            else:
                problems.append("its %s must be %s" % (key, " or ".join(allowed)))
    return schema, problems


def walled(context: dict, tag_a: str, tag_b: str) -> bool:
    """Does a wall stand between two party tags?"""
    if not tag_a or not tag_b:
        return False
    a, b = strip_tag(tag_a), strip_tag(tag_b)
    if a == b:
        return False
    return frozenset((a, b)) in context.get("walls", set())


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

def workspace_root(start: Optional[PathLike] = None) -> Path:
    """Walk up from `start` (or the current folder) to the folder that holds
    `System/rules.md`. Raises FileNotFoundError when there is none."""
    here = Path(start) if start is not None else Path.cwd()
    here = here.resolve()
    if here.is_file():
        here = here.parent
    for folder in (here, *here.parents):
        if (folder / "System" / "rules.md").is_file():
            return folder
    raise FileNotFoundError("no workspace (a folder holding System/rules.md) above %s" % here)


# What a walk of a zone leaves out, in one place: the check reads a zone's
# notes through live_files(), and the status page's Todo card reads its
# checkboxes through the same function, so the two cannot drift apart.
#
# Folders no one writes in: git's own, installed packages, caches and build
# output. Skipped by name wherever a tool walks, before git is asked.
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "__pycache__", "dist"})
# Folders whose notes no longer count as live: archives, build output, specs,
# hidden and template folders.
NOT_LIVE_DIR_RE = re.compile(r"^(?:archive|build|render.*|specs|\..*|_.*)$", re.I)
# A Garrick checkout, cloned or unpacked from a release ZIP, which has no .git.
CHECKOUT_TREE = "template"                  # the tree the installer copies
CHECKOUT_MARKS = ("VERSION", "install.py")  # what only Garrick's own source has


def nested_repo(folder: PathLike) -> bool:
    """A git repository of its own inside a project, such as code checked out
    beside the notes about it. The workspace's own repositories are its root,
    its zones and its wikis; anything below them with a `.git` is somebody
    else's files, not the zone's."""
    folder = Path(folder)
    if not (folder / ".git").exists():
        return False
    return not (folder.parent.name in ("Zones", "Wikis") or folder.name == "Wikis")


def is_checkout(folder: PathLike) -> bool:
    """Is `folder` the top of a Garrick checkout? Recognised by the installer,
    the VERSION file it stamps into a workspace, and the tree it copies."""
    folder = Path(folder)
    return ((folder / CHECKOUT_TREE).is_dir()
            and all((folder / name).is_file() for name in CHECKOUT_MARKS))


def live_files(folder: PathLike) -> Iterable[Path]:
    """Every file under `folder` outside archives, build output, hidden and
    template folders, installed packages and caches (SKIP_DIRS), any
    repository of its own kept inside a project, such as a program's code,
    and any Garrick checkout, cloned or unpacked from a release: their files
    are not notes."""
    for dirpath, dirnames, filenames in os.walk(str(folder)):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in SKIP_DIRS and not NOT_LIVE_DIR_RE.match(d)
                             and not os.path.lexists(os.path.join(dirpath, d, ".git"))
                             and not is_checkout(Path(dirpath) / d))
        for name in sorted(filenames):
            yield Path(dirpath) / name


def link_on_the_way(base: PathLike, path: PathLike) -> Optional[Path]:
    """The first symbolic link on the way from `base` down to `path`, `path`
    itself included, or None when there is none. `base` may be a link, and so
    may anything above it: the check starts below it. A path that is not under
    `base`, or that climbs with `..`, is returned whole, as unsafe.

    A command that checked where a file may go calls this just before moving
    or writing it, so a link cannot send the file past the folder it checked."""
    base, path = Path(base), Path(path)
    try:
        parts = path.relative_to(base).parts
    except ValueError:
        return path
    if ".." in parts:
        return path
    step = base
    for part in parts:
        step = step / part
        if step.is_symlink():
            return step
    return None


class OffCourse(Exception):
    """A file that would land somewhere other than the folder checked for it.
    `link` is the symbolic link that would send it there, or the path itself."""

    def __init__(self, link: PathLike):
        super().__init__(str(link))
        self.link = Path(link)


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def landing(root: PathLike, home: PathLike, path: PathLike) -> Path:
    """Where `path` really lands, with every link on the way resolved.

    `home` is the folder a command checked the file may go to: a project, a
    wiki. A link on the way is fine while it keeps the file inside `home` as
    it really is, and `home` inside the workspace `root`; a link that leads
    out, `path` itself being a link, and a path that climbs with `..` raise
    OffCourse. Nothing is created or moved."""
    root, home, path = Path(root), Path(home), Path(path)
    try:
        parts = path.relative_to(home).parts
    except ValueError:
        raise OffCourse(path)
    if not parts or ".." in parts:
        raise OffCourse(path)
    real_home = home.resolve()
    if not _inside(real_home, root.resolve()):
        raise OffCourse(link_on_the_way(root, home) or home)
    if path.is_symlink():
        raise OffCourse(path)
    folder = path.parent.resolve()
    if not _inside(folder, real_home):
        raise OffCourse(link_on_the_way(home, path.parent) or path.parent)
    return folder / path.name


_NEW = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW


def _open_folder(root: Path, home: Path, path: Path) -> Tuple[int, str]:
    """(descriptor of the folder `path` really lands in, its name there).

    The folder is opened one step at a time from the top, following no link,
    so a link put on the way since `landing` checked it makes this fail
    rather than lead somewhere else. Files are then made relative to the
    descriptor, never by path."""
    target = landing(root, home, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in target.parent.parts[1:]:
            step = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = step
    except OSError:
        os.close(fd)
        raise OffCourse(link_on_the_way(home, path.parent) or path.parent)
    return fd, target.name


def _create(folder: int, name: str, path: Path, mode: int = 0o666) -> int:
    try:
        return os.open(name, _NEW, mode, dir_fd=folder)
    except FileExistsError:
        raise FileExistsError(errno.EEXIST, "already exists", str(path))


def write_new(root: PathLike, home: PathLike, path: PathLike, data: bytes) -> Path:
    """Write `data` to `path`, a file that does not exist yet, inside `home`.
    Raises OffCourse as `landing` does, and FileExistsError when anything,
    a file or a link, already stands at `path`. Returns `path`."""
    root, home, path = Path(root), Path(home), Path(path)
    folder, name = _open_folder(root, home, path)
    try:
        with os.fdopen(_create(folder, name, path), "wb") as out:
            out.write(data)
    finally:
        os.close(folder)
    return path


def write_over(root: PathLike, home: PathLike, path: PathLike, data: bytes) -> Path:
    """Replace `path` whole with `data`, or create it, inside `home`. Written
    beside it and renamed over it, so a reader sees the old file or the new
    one, and a link put at `path` since the check is replaced, not followed."""
    root, home, path = Path(root), Path(home), Path(path)
    folder, name = _open_folder(root, home, path)
    tmp = ".%s.%d.tmp" % (name, os.getpid())
    try:
        with os.fdopen(_create(folder, tmp, path), "wb") as out:
            out.write(data)
        os.replace(tmp, name, src_dir_fd=folder, dst_dir_fd=folder)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=folder)
        except OSError:
            pass
        raise
    finally:
        os.close(folder)
    return path


def move_new(root: PathLike, home: PathLike, src: PathLike, path: PathLike) -> Path:
    """Move the file `src` to `path`, which does not exist yet, inside `home`:
    copied byte for byte with its permissions and times, then removed. `src`
    is never read through a link. Raises as `write_new` does, and leaves
    `src` where it was. Returns `path`."""
    root, home, path = Path(root), Path(home), Path(path)
    inp = os.open(str(src), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(inp)
        folder, name = _open_folder(root, home, path)
        try:
            with os.fdopen(_create(folder, name, path, 0o600), "wb") as out:
                try:
                    with os.fdopen(os.dup(inp), "rb") as reader:
                        shutil.copyfileobj(reader, out)
                    out.flush()
                    os.fchmod(out.fileno(), stat.S_IMODE(st.st_mode))
                    os.utime(out.fileno(), ns=(st.st_atime_ns, st.st_mtime_ns))
                except BaseException:
                    os.unlink(name, dir_fd=folder)
                    raise
        finally:
            os.close(folder)
    finally:
        os.close(inp)
    os.unlink(str(src))
    return path


# ---------------------------------------------------------------------------
# The resume point, and the checkpoint beside it
# ---------------------------------------------------------------------------

# A thread note's `## State of play` opens with `### Resume here`, the last
# confirmed resume point, and under it may sit one `### Checkpoint` block:
# what a session recorded as the work happened and has not wrapped yet.
#
# The block's extent is its two markers and nothing else. The heading cannot
# end it: in a real note the resume table is followed by `---` and then every
# dated entry, all of them still inside State of play and none of them a
# heading, so a block read "until the next heading" would swallow the thread's
# whole history and its key would never match its content again. The items are
# the lines between the markers, the key is computed over those lines, and an
# opening marker with no closing one has no extent: it is read and reported,
# never resumed from and never rewritten.

RESUME_HEADING = "### Resume here"
# Where a Resume here block stops: the next heading, or the rule above the
# dated entries. check.py's `resume_block()` reads it by the same rule, and
# tests/test_checkpoint.py holds the two against each other.
RESUME_STOP_RE = re.compile(r"^(#{1,3} |---\s*$)")

CHECKPOINT_HEADING = "### Checkpoint"
CHECKPOINT_OPEN = "<!-- garrick-checkpoint"
CHECKPOINT_CLOSE = "<!-- /garrick-checkpoint -->"
CHECKPOINT_OPEN_RE = re.compile(r"(?m)^<!--[ \t]*garrick-checkpoint[ \t][^\n]*?-->[ \t]*$")
CHECKPOINT_CLOSE_RE = re.compile(r"(?m)^<!--[ \t]*/garrick-checkpoint[ \t]*-->[ \t]*$")
# The sentence a person reads, which carries the time and so is left out of
# the key: the same items written again a minute later are the same items.
CHECKPOINT_SAID = ("Recorded since the resume point above and not yet wrapped. "
                   "Only what is under Decided was decided, in the words quoted.")
CHECKPOINT_UNCONFIRMED = "**Unconfirmed, "
CHECKPOINT_DAYS = 7             # unconfirmed for longer than this, and the check says so

# The kinds, in the order a block writes them: the name a request uses, the
# label the line carries, and the stem of its item ids.
CHECKPOINT_KINDS = (
    ("made", "Made", "m"),
    ("decided", "Decided", "d"),
    ("considering", "Considering", "c"),
    ("next", "Next action", "n"),
    ("action", "To file", "a"),
    ("deadline", "Deadline", "due"),
    ("incomplete", "Incomplete", "i"),
)
CHECKPOINT_LABELS = {kind: label for kind, label, _ in CHECKPOINT_KINDS}
CHECKPOINT_STEMS = {kind: stem for kind, _, stem in CHECKPOINT_KINDS}
# One of each of these in a block, so its id is the stem itself.
CHECKPOINT_ONE = ("next", "deadline", "incomplete")
_CHECKPOINT_KIND_OF = {label: kind for kind, label, _ in CHECKPOINT_KINDS}
_CHECKPOINT_ITEM_RE = re.compile(
    r"^- \*\*([A-Z][A-Za-z ]*)\*\*[ \t]+(.*?)[ \t]*(?:<!--[ \t]*([A-Za-z][A-Za-z0-9-]*)[ \t]*-->)?[ \t]*$")
_CHECKPOINT_FIELD_RE = re.compile(r"(\w+)=(\S+)")


def resume_lines(text: str) -> List[str]:
    """The lines of a note's `### Resume here` block, up to the next heading
    or rule. The same reading as check.py's `resume_block()`, which is why a
    `### Checkpoint` heading under the table ends the block cleanly and every
    reader of a resume point keeps working."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == RESUME_HEADING.lower()), -1)
    if start < 0:
        return []
    out: List[str] = []
    for line in lines[start + 1:]:
        if RESUME_STOP_RE.match(line.strip()):
            break
        out.append(line)
    return out


def _short_hash(parts: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def resume_hash(text: str) -> Optional[str]:
    """The fingerprint of a note's Resume here block, which a checkpoint
    records as the confirmed point it was written against. None where the note
    has no such block. Blank lines and trailing spaces do not change it."""
    lines = [l.rstrip() for l in resume_lines(text) if l.strip()]
    return _short_hash(lines) if lines else None


def checkpoint_key(base: Optional[str], content: Iterable[str]) -> str:
    """A checkpoint's key: its items and the resume point it was written
    against. Never its time, and never the sentence a person reads, so the
    same state written again at any interval has the same key."""
    return _short_hash([base or "-"] + [l.rstrip() for l in content])


def checkpoint_span(text: str) -> Optional[Tuple[int, Optional[int]]]:
    """Where the checkpoint's markers are in `text`: the opening marker's
    first byte, and the byte after the closing one. None where there is no
    opening marker; `(start, None)` where the closing one is missing, which
    leaves the block without an extent."""
    head = CHECKPOINT_OPEN_RE.search(text)
    if head is None:
        return None
    close = CHECKPOINT_CLOSE_RE.search(text, head.end())
    return (head.start(), close.end() if close else None)


def checkpoint_item_line(kind: str, text: str, item_id: str) -> str:
    """One item as a block writes it: its kind in bold, what it holds, and its
    id in a comment Obsidian hides."""
    return "- **%s** %s <!-- %s -->" % (CHECKPOINT_LABELS[kind], text, item_id)


def read_checkpoint(text: str) -> Optional[dict]:
    """The checkpoint block in a note, or None where it has none.

    A dict: `at`, `base` and `key` as the comment line carries them, `items`
    (each with its `id`, `kind`, `text` and the `line` as written), `content`
    (the lines the key covers), `span`, `extra` (a second opening marker),
    `valid`, and `why` where it is not. An invalid block is returned rather
    than hidden: it is shown and reported, never resumed from."""
    head = CHECKPOINT_OPEN_RE.search(text)
    if head is None:
        return None
    fields = dict(_CHECKPOINT_FIELD_RE.findall(head.group(0)))
    block = {"at": fields.get("at"), "base": fields.get("base"), "key": fields.get("key"),
             "span": (head.start(), None), "items": [], "content": [],
             "extra": len(CHECKPOINT_OPEN_RE.findall(text)) > 1, "valid": False, "why": ""}
    close = CHECKPOINT_CLOSE_RE.search(text, head.end())
    if close is None:
        block["why"] = "has no closing %s marker, so where it ends cannot be told" % CHECKPOINT_CLOSE
        return block
    block["span"] = (head.start(), close.end())
    for line in text[head.end():close.start()].splitlines():
        if not line.strip() or line.lstrip().startswith(CHECKPOINT_UNCONFIRMED):
            continue
        block["content"].append(line.rstrip())
        m = _CHECKPOINT_ITEM_RE.match(line.rstrip())
        kind = _CHECKPOINT_KIND_OF.get(m.group(1)) if m else None
        if kind is None or not (m and m.group(3)):
            block["why"] = block["why"] or "holds a line that is not an item: %s" % line.strip()[:60]
            continue
        block["items"].append({"id": m.group(3), "kind": kind,
                               "text": m.group(2).strip(), "line": line.rstrip()})
    if block["why"]:
        return block
    if not (block["at"] and block["base"] and block["key"]):
        block["why"] = "has a comment line that does not carry at, base and key"
        return block
    if checkpoint_key(block["base"], block["content"]) != block["key"]:
        block["why"] = "has been edited since it was written: its key does not match its items"
        return block
    block["valid"] = True
    return block


def said_time(at: str) -> str:
    """A checkpoint's time as the sentence says it: "14:32 on 15 October
    2026". The stamp itself where it cannot be read."""
    try:
        when = datetime.datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return str(at)
    return "%02d:%02d on %d %s %d" % (when.hour, when.minute, when.day,
                                      _MONTH_NAMES[when.month - 1], when.year)


def render_checkpoint(at: str, base: Optional[str], items: List[dict]) -> Tuple[str, str]:
    """(the block from its opening marker to its closing one, its key).

    The comment line carries what a machine needs, the sentence after it what
    a person needs, and then one line an item. Nothing else goes between the
    markers, because the key covers every line that does."""
    content = [item["line"].rstrip() for item in items]
    key = checkpoint_key(base, content)
    head = ["<!-- garrick-checkpoint at=%s base=%s key=%s -->" % (at, base or "-", key),
            "%s%s.** %s" % (CHECKPOINT_UNCONFIRMED, said_time(at), CHECKPOINT_SAID), ""]
    return "\n".join(head + content + [CHECKPOINT_CLOSE]), key


def _under_resume(text: str) -> Optional[int]:
    """The offset just after the last line of the Resume here block: where a
    checkpoint goes, above the rule and the dated entries. None where the note
    has no Resume here block."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == RESUME_HEADING.lower()), -1)
    if start < 0:
        return None
    last = start
    for i in range(start + 1, len(lines)):
        if RESUME_STOP_RE.match(lines[i].strip()):
            break
        if lines[i].strip():
            last = i
    return sum(len(l) for l in lines[:last + 1])


def place_checkpoint(text: str, body: str) -> Optional[str]:
    """`text` with `body`, a block from one marker to the other, in place of
    the checkpoint the note has, or under its Resume here block where it has
    none. Every byte outside the two markers is left as it is, the dated
    entries included. None where there is nowhere to put one: no Resume here
    block, or a block whose closing marker is missing, which is never
    rewritten."""
    found = checkpoint_span(text)
    if found is not None:
        start, end = found
        return None if end is None else text[:start] + body + text[end:]
    at = _under_resume(text)
    if at is None:
        return None
    return text[:at] + "\n" + CHECKPOINT_HEADING + "\n\n" + body + "\n" + text[at:]


def rebase_checkpoint(text: str, base: str) -> Optional[str]:
    """The note with its checkpoint written against `base`: the same items at
    the same time, a new base and the key that follows from it. For the
    interrupt, the one writer that rewrites Resume here without folding the
    checkpoint, so that a hold does not make it stale. None where there is no
    valid block to rebase."""
    block = read_checkpoint(text)
    if block is None or not block["valid"]:
        return None
    body, _ = render_checkpoint(block["at"], base, block["items"])
    return place_checkpoint(text, body)


def write_if_unchanged(note: PathLike, text: str, expect: bytes) -> bool:
    """Write `text` over `note`, so long as the note still holds `expect`: a
    temporary file beside it, the note read again and compared, then a rename.
    False, and nothing written, where the note has moved on since it was read.
    A kill before the rename leaves the note exactly as it was."""
    note = Path(note)
    tmp = note.with_name("." + note.name + ".checkpoint")
    if tmp.exists():
        tmp.unlink()                       # what a kill before a rename left behind
    done = False
    try:
        tmp.write_bytes(text.encode("utf-8"))
        if note.read_bytes() != expect:
            return False
        os.replace(str(tmp), str(note))
        done = True
        return True
    finally:
        if not done and tmp.exists():
            tmp.unlink()


# What `add()` in the status extra's todo_lines.py compares to refuse a line
# the list already holds, and what merges a reworded checkpoint item into the
# one already there: the text read as it would be heard, with the Tasks fields
# and the todo skill's own `· [src]` and `(also in …)` left out. The two are
# held against each other in tests/test_checkpoint.py, so the workspace has
# one reading of "the same action" and not two that drift.
_TASKS_PRIORITY_RE = re.compile(r" *([\U0001F53A⏫\U0001F53C\U0001F53D⏬])️?")
_TASKS_DATE_RE = re.compile(r" *((?:\U0001F4C5|\U0001F4C6|\U0001F5D3|⏳|⌛|\U0001F6EB|➕|✅|❌)️?"
                            r" *\d{4}-\d{2}-\d{2})")
_TASKS_SRC_RE = re.compile(r"\s*·\s*\[src\]\(([^)\s]*)\)")
_TASKS_ALSO_RE = re.compile(r"\s*\(also in ((?:[^()]|\([^()]*\))*)\)")


def same_action(line: str) -> str:
    """Two lines that say the same thing read the same way: one space between
    words, no case, no trailing stop, and the Tasks fields, the `· [src]` and
    the `(also in …)` left out, because a date says when to do a thing and not
    what to do."""
    body = line[6:] if line.startswith(("- [ ] ", "- [x] ")) else line
    body = _TASKS_ALSO_RE.sub("", _TASKS_SRC_RE.sub("", body))
    body = _TASKS_DATE_RE.sub("", _TASKS_PRIORITY_RE.sub("", body))
    return re.sub(r"\s+", " ", body).strip().rstrip(".!").casefold()


# ---------------------------------------------------------------------------
# The pre-commit wall check
# ---------------------------------------------------------------------------

WALL_HOOK_MARK = "Garrick wall check"

# Git runs a hook from the top of the repository, which for a zone is
# Zones/<Zone>/, so the workspace's check.py is two folders up.
WALL_HOOK = """#!/bin/sh
# %s: refuse a commit that would carry walled material into this zone's history.
# Installed by Garrick. The deliberate override, only when you mean it: git commit --no-verify
check="$(git rev-parse --show-toplevel)/../../System/tools/check.py"
if [ ! -f "$check" ]; then
  echo "Commit refused: the wall check is missing ($check). Put it back, or commit with --no-verify if you mean to skip it." >&2
  exit 1
fi
exec python3 "$check" --staged --walls-only
""" % WALL_HOOK_MARK


# A repository inside a project (a product's code, a site, a book) sits at
# any depth below its zone, so its hook looks upward for the workspace.
WALL_HOOK_NESTED = """#!/bin/sh
# %s: refuse a commit that would carry walled material out of this project's own repository.
# Installed by Garrick in a repository inside a project. The deliberate override, only when you mean it: git commit --no-verify
dir="$(git rev-parse --show-toplevel)"
while [ "$dir" != "/" ] && [ ! -f "$dir/System/tools/check.py" ]; do dir="$(dirname "$dir")"; done
check="$dir/System/tools/check.py"
if [ ! -f "$check" ]; then
  echo "Commit refused: the wall check is missing; no System/tools/check.py above this repository. Put it back, or commit with --no-verify if you mean to skip it." >&2
  exit 1
fi
exec python3 "$check" --root "$dir" --staged --walls-only
""" % WALL_HOOK_MARK


def _hooks_dir(zone: PathLike) -> Optional[Path]:
    git_dir = Path(zone) / ".git"
    return git_dir / "hooks" if git_dir.is_dir() else None


def has_wall_hook(zone: PathLike) -> bool:
    """Does this zone's repository run the wall check before every commit?"""
    hooks = _hooks_dir(zone)
    if hooks is None:
        return False
    hook = hooks / "pre-commit"
    try:
        return WALL_HOOK_MARK in hook.read_text(encoding="utf-8", errors="replace") and os.access(hook, os.X_OK)
    except OSError:
        return False


def install_wall_hook(zone: PathLike, nested: bool = False) -> Path:
    """Write the pre-commit wall check into a zone's repository, or with
    `nested` into a repository inside a project, and return its path.

    Refuses (FileExistsError) to replace a pre-commit hook Garrick did not write,
    and (FileNotFoundError) a zone whose `.git` is not a folder."""
    hooks = _hooks_dir(zone)
    if hooks is None:
        raise FileNotFoundError("%s is not a git repository with its own .git folder" % zone)
    hook = hooks / "pre-commit"
    if hook.exists():
        existing = hook.read_text(encoding="utf-8", errors="replace")
        if WALL_HOOK_MARK not in existing:
            raise FileExistsError("%s already has a pre-commit hook; add this line to it: "
                                  "python3 <workspace>/System/tools/check.py --staged --walls-only" % zone)
    hooks.mkdir(parents=True, exist_ok=True)
    hook.write_text(WALL_HOOK_NESTED if nested else WALL_HOOK, encoding="utf-8")
    hook.chmod(0o755)
    return hook


def hooks_path(repo: PathLike) -> str:
    """Where git takes this repository's hooks from, when a setting moves them
    away from `.git/hooks`; then the wall check does not run. "" otherwise."""
    try:
        r = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=str(repo), capture_output=True, text=True)
    except OSError:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


# ---------------------------------------------------------------------------
# Repositories: what the installer makes, and scaffold.py makes again for a zone
# ---------------------------------------------------------------------------

# Every zone starts as a copy of this folder, with the zone's name filled in:
# the installer's zones and the ones scaffold.py adds later alike.
ZONE_TEMPLATE = ("System", "templates", "zone")
# A zone's Todo.md opens with an example line, `<angle bracket>` placeholders
# and all, under a sentence that says so: the shape, for someone who reads the
# list as a file. A workspace on the simple home is for someone who never does,
# and an assistant asked what is owed would tell them the list holds only a
# sample, so its zones start without the two (zone_todo()).
ZONE_TODO = "Todo.md"
_TODO_EXAMPLE_NOTE = re.compile(r"^The line below is an example\b[^\n]*\n", re.M)
_TODO_EXAMPLE_LINE = re.compile(r"^- \[ \] [^\n]*<[^<>\n]+>[^\n]*\n?", re.M)


def zone_todo(text: str, simple: bool) -> str:
    """A zone's Todo.md as the zone template has it, filled in: with its example
    line and the sentence about it, or without both for a workspace on the
    simple home."""
    if not simple:
        return text
    text = _TODO_EXAMPLE_LINE.sub("", _TODO_EXAMPLE_NOTE.sub("", text))
    return re.sub(r"\n{3,}", "\n\n", text)

# The worked example (examples/example-work/ in Garrick's source): a zone of its
# own, with a shared drive beside it in the workspace's top folder that its
# hubs point into. System/tools/example.py archives both into ARCHIVE, a
# folder of the top folder that no repository commits, and brings them back.
EXAMPLE_DRIVE = "Quillfield Shared"
EXAMPLE_MANIFEST = ".example.json"
ARCHIVE = ".archive"


def work_folder(root: PathLike, value) -> Optional[Path]:
    """Where a hub's `folder:` says the project's files are: a path from the
    workspace's top folder, an absolute one, or one starting `~/`. None for a
    key that is absent or empty. Whether the folder is there is the caller's
    question: the check warns, and a page offers nothing to open."""
    if value is None or isinstance(value, (list, dict)):
        return None
    text = str(value).strip().strip('"').strip("'").strip()
    if not text:
        return None
    path = Path(text).expanduser() if text.startswith("~") else Path(text)
    return path if path.is_absolute() else Path(root) / path

# Claude Code looks for skills in .claude/skills and Codex in .agents/skills,
# from the session's folder up to its git repository's root.
SKILL_FOLDERS = (".claude", ".agents")

# The address the installer sets in the workspace's repositories when git has none.
LOCAL_EMAIL = "garrick@localhost"

# Which Garrick a workspace was installed from: the installer writes it, and
# `check.py --version` reads it, so a bug report can say what is installed.
VERSION_STAMP = ("System", "garrick-version.json")
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December")


def read_version(root: PathLike) -> dict:
    """The workspace's version stamp, or {} when it has none."""
    import json
    try:
        stamp = json.loads(Path(root).joinpath(*VERSION_STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return stamp if isinstance(stamp, dict) else {}


def say_version(stamp: dict) -> str:
    """One sentence that says which Garrick a stamp records, read or heard."""
    commit = str(stamp.get("commit") or "")
    if not commit or commit == "unknown":
        return ("Garrick, version unknown: this workspace has no record of the copy it was installed from. "
                "Say the day you downloaded it instead.")
    out = "Garrick %s" % commit
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(stamp.get("date") or ""))
    if m and 1 <= int(m.group(2)) <= 12:
        out += " of %d %s %s" % (int(m.group(3)), _MONTH_NAMES[int(m.group(2)) - 1], m.group(1))
    updates = [u for u in (stamp.get("updates") or []) if isinstance(u, dict)]
    how = stamp.get("from")
    if how == "adopted" and updates:
        how = updates[-1].get("via")    # an adopted workspace keeps "adopted"; its last update says where it came from
    source = {"download": "a download", "clone": "a clone"}.get(how)
    if source:
        out += ", %s %s" % ("from" if updates else "installed from", source)
    if stamp.get("modified"):
        out += " with changes not committed"
    if updates:
        last = updates[-1]
        out += ". Updated%s from %s" % (_on(last.get("on")), last.get("from") or "an unknown version")
    out += "."
    left = stamp.get("left") or []
    if left:
        out += " %d file%s left at an older version." % (len(left), "" if len(left) == 1 else "s")
    return out


def _on(date: object) -> str:
    """" on 6 October 2026", or "" when there is no date to say."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(date or ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        return ""
    return " on %d %s %s" % (int(m.group(3)), _MONTH_NAMES[int(m.group(2)) - 1], m.group(1))


# The stamp also lists, under "files", every file Garrick wrote into the
# workspace, by its path from the top folder and the SHA-256 of its bytes: the
# installer's files, and those of a zone scaffold.py adds later. An update can
# then tell a file still as Garrick wrote it, which it may replace, from one the
# user has changed, which it must leave for a merge. System/context.md holds the
# user's own answers and is never listed; nor is the stamp itself.
# Garrick's instruction files. An update replaces each one while it is as
# Garrick shipped it, and the workspace's own rules and routing live in the
# local file beside it, which Garrick never ships, lists or changes: System/rules.md
# has System/rules.local.md, and every AGENTS.md has an AGENTS.local.md.
INSTRUCTION_FILES = ("AGENTS.md", "System/rules.md", "Wikis/AGENTS.md", "Wikis/*/AGENTS.md", "Zones/*/AGENTS.md")
LOCAL_RULES = "System/rules.local.md"
# The line the split opens each AGENTS.local.md it starts with, under its title.
# Every one carries it, so the check for text copied between instruction files
# passes over it.
LOCAL_HEADER = ("Adds to Garrick's `AGENTS.md` beside it and wins where the two differ. "
                "Garrick never ships or changes this file.")

# The workspace's own settings, where the release notice lives and where the
# installer records the allow rules it wrote (see below), and the assistant's
# own settings, which Garrick adds those rules to and never owns.
SETTINGS = ("System", "garrick-settings.json")
CLAUDE_SETTINGS = (".claude", "settings.json")
ALLOWED_COMMANDS = "allowed-commands"

# Files the installer writes that are the user's from the start: never listed in
# the stamp, never compared or written by an update. The two settings files are
# here because each holds the user's own entries beside Garrick's; an update
# replaces only the entries it wrote, and never the whole file.
UNLISTED = ("System/context.md", "/".join(VERSION_STAMP), LOCAL_RULES,
            "/".join(SETTINGS), "/".join(CLAUDE_SETTINGS))


def is_instruction_file(path: str) -> bool:
    """Whether `path`, from the workspace's top, is one of Garrick's instruction files."""
    import fnmatch
    parts = path.split("/")
    return any(len(parts) == len(p.split("/")) and all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts, p.split("/")))
               for p in INSTRUCTION_FILES)


def local_file(path: str) -> str:
    """The local file beside one of Garrick's instruction files: where the
    workspace's own text for it goes. `System/rules.md` -> `System/rules.local.md`."""
    head, _, name = path.rpartition("/")
    stem = name[:-3] if name.endswith(".md") else name
    return (head + "/" if head else "") + stem + ".local.md"


# A .gitignore cannot have a local file beside it, so Garrick's lines sit
# between two markers and yours go anywhere outside them. An update replaces
# what is between the markers and never reads the rest.
IGNORE_BEGIN = "# >>> Garrick manages the lines below; an update replaces them"
IGNORE_END = "# <<< Garrick"

# The files a machine makes on its own in any folder: Finder's, Python's and
# Obsidian's. Every repository's block starts with them, and they hold nothing
# anybody wrote, so a rename or a deletion clears them rather than refusing.
MACHINE_IGNORES = (".DS_Store\n._*\n__pycache__/\n"
                   "# Obsidian rewrites these on every pan, zoom and click, in whichever folder is opened as a vault.\n"
                   "**/.obsidian/workspace*.json\n**/.obsidian/graph.json\n")


def machine_made(rel: str) -> bool:
    """Whether a path, from the top of its repository, is one MACHINE_IGNORES
    names, as git matches those lines: a line with no slash inside it at any
    depth, `**/` from any folder, and a trailing slash a folder and everything
    in it. `rel` ends in a slash where git reports a folder."""
    import fnmatch
    parts = rel.strip("/").split("/")
    folder = rel.endswith("/")
    for line in MACHINE_IGNORES.splitlines():
        if not line or line.startswith("#"):
            continue
        dir_only = line.endswith("/")
        pat = line.rstrip("/")
        pat = pat[3:] if pat.startswith("**/") else pat
        want = pat.split("/")
        for i in range(len(parts) - len(want) + 1):
            last = i + len(want) == len(parts)
            if dir_only and last and not folder:
                continue                                    # the line names a folder; this is a file
            if all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts[i:i + len(want)], want)):
                return True
    return False


def garrick_ignores(zones) -> Dict[str, str]:
    """Garrick's lines for the .gitignore of every repository the installer
    makes, and the zone template's, which a zone added later copies: {path
    from the top: the lines, without the markers}."""
    common = MACHINE_IGNORES
    inbox = ("# Mail and files wait in Inbox/ until they are filed where they belong; they never enter this history.\nInbox/*\n!Inbox/.gitkeep\n"
             "# When each Inbox and Waiting on line of Todo.md was first seen, for the todo skill's expiry.\n.todo-seen.json\n"
             "# Links to shared cloud folders carry the provider's own path, which is this machine's alone.\n.shared/\n")
    transcripts = ("# Transcripts wait in Meetings/raw/inbox/ until they are filed; they never enter this history.\n"
                   "Meetings/raw/inbox/*\n!Meetings/raw/inbox/.gitkeep\n")
    generated = "# Pages tools write for you, such as the status page: rebuilt, never committed.\nSystem/generated/\n"
    shared = ("# Mail forwarded to one address for every zone waits in Inbox/ until intake moves it to its zone.\n"
              "Inbox/*\n!Inbox/.gitkeep\n")
    example = ("# The example's shared drive, read and never written, and what System/tools/example.py\n"
               "# put away when the example was removed. Neither is ever committed.\n"
               "/%s/\n/%s/\n" % (EXAMPLE_DRIVE, ARCHIVE))
    out = {".gitignore": "# Zones and wikis are their own repositories.\nZones/\nWikis/\n" + generated + shared
                         + example + common,
           "Wikis/.gitignore": common + transcripts}
    for zone in zones:
        out["Zones/%s/.gitignore" % zone] = common + inbox
    out["/".join(ZONE_TEMPLATE + (".gitignore",))] = common + inbox
    return out


def ignore_block(lines: str) -> str:
    """Garrick's lines between the markers, as the installer writes them."""
    return IGNORE_BEGIN + "\n" + lines.rstrip("\n") + "\n" + IGNORE_END + "\n"


def ignore_parts(text: str):
    """(the lines before Garrick's block, the lines inside it or None when
    there is no block, the lines after it). A marker with no partner is not a
    block."""
    lines = text.splitlines()
    begin = next((k for k, x in enumerate(lines) if x.strip() == IGNORE_BEGIN), None)
    end = None if begin is None else next((k for k in range(begin + 1, len(lines)) if lines[k].strip() == IGNORE_END),
                                          None)
    if end is None:
        return lines, None, []
    return lines[:begin], lines[begin + 1:end], lines[end + 1:]


def with_ignore_block(current: str, lines: str) -> str:
    """`current`, a .gitignore, with Garrick's block holding `lines`. A block
    already there is replaced where it stands, and nothing outside it changes.
    A file with no block gets one at the top, and keeps every line of its own
    after it, except a line exactly like one of Garrick's, which the block now
    holds, and a lone marker."""
    before, inside, after = ignore_parts(current)
    block = ignore_block(lines).splitlines()
    if inside is not None:
        out = before + block + after
    else:
        garricks = {x for x in block if x.strip()}
        own = [x for x in before if x not in garricks and x.strip() not in (IGNORE_BEGIN, IGNORE_END)]
        kept = []
        for x in own:
            if x.strip() or (kept and kept[-1].strip()):
                kept.append(x)                       # one blank line at most, none at the start
        while kept and not kept[-1].strip():
            kept.pop()
        out = block + ([""] + kept if kept else [])
    return "\n".join(out) + "\n"


def fingerprint(path: PathLike) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprints(root: PathLike, paths) -> Dict[str, str]:
    """Path from the top folder to SHA-256, for each of `paths` that is a file
    inside `root`. Links, folders and anything under .git are left out."""
    root = Path(root)
    out = {}
    for p in paths:
        p = Path(p)
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in UNLISTED or ".git" in Path(rel).parts or p.is_symlink() or not p.is_file():
            continue
        out[rel] = fingerprint(p)
    return dict(sorted(out.items()))


def record_written(root: PathLike, paths) -> bool:
    """Add files Garrick has just written to the stamp's list. Only a stamp that
    already keeps one: a workspace installed before the list existed has
    nothing to add to, and an update treats every file in it as the user's."""
    import json
    stamp = read_version(root)
    if not isinstance(stamp.get("files"), dict):
        return False
    stamp["files"] = dict(sorted({**stamp["files"], **fingerprints(root, paths)}.items()))
    Path(root).joinpath(*VERSION_STAMP).write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    return True


def installed_changes(root: PathLike, stamp: dict) -> Tuple[int, int, int]:
    """How many files the stamp lists, how many of them have changed since,
    and how many are gone."""
    files = stamp.get("files")
    if not isinstance(files, dict):
        return 0, 0, 0
    changed = gone = 0
    for rel, digest in files.items():
        p = Path(root) / rel
        if not p.is_file():
            gone += 1
        elif fingerprint(p) != digest:
            changed += 1
    return len(files), changed, gone


def say_changes(root: PathLike, stamp: dict) -> str:
    """One sentence on how far the workspace has moved from what Garrick wrote.
    Counts only: a path names a zone, and a zone's name can be a client's."""
    total, changed, gone = installed_changes(root, stamp)
    if not total:
        return ""
    if not changed and not gone:
        return "All %d files Garrick wrote are as it wrote them." % total
    parts = []
    if changed:
        parts.append("%d changed" % changed)
    if gone:
        parts.append("%d gone" % gone)
    return "Of the %d files Garrick wrote, %s since." % (total, " and ".join(parts))


# What the workspace's settings hold, SETTINGS above: choices that stay, unlike
# the preview flags in System/garrick-flags.json, which a release drops.
# {"release-notice": true} lets the status page ask GitHub, at most once a day,
# whether a newer Garrick is out. Off unless the file says true: it is the only
# call Garrick makes on its own. "release-repository" names another repository
# to ask, for a fork, as owner/name. "allowed-commands" lists the allow rules
# the installer wrote into the assistant's own settings, so an update can
# replace its own and leave the ones the user added.
RELEASE_NOTICE = "release-notice"
RELEASE_REPOSITORY = "iamvenuti/garrick"
# What the last question to GitHub found, written by System/tools/release.py.
# In the folder for files a tool rebuilds, so it is never committed.
RELEASE_CACHE = ("System", "generated", "garrick-release.json")
RELEASE_EVERY = datetime.timedelta(days=1)
# The release notes the installer copies in, and every update replaces: the
# newest release named there is the release the workspace runs.
CHANGELOG_COPY = ("System", "garrick-changelog.md")
# Garrick's docs, as the release ships them in docs/: the installer copies the
# pages and the images they show here, and every update replaces them, so the
# assistant can answer from them and the Garrick App's Guide tab can show them
# without fetching anything.
DOCS_COPY = ("System", "garrick-docs")
UPDATE_COMMAND = "python3 System/tools/release.py update"
_REPO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")


def read_settings(root: PathLike) -> dict:
    """System/garrick-settings.json, or {} when it is missing or does not read."""
    import json
    try:
        data = json.loads(Path(root).joinpath(*SETTINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def simple_home(root: PathLike) -> bool:
    """Whether the workspace opens on the simple home, `"home": "simple"` in
    the settings file. One without the key keeps the full page it had."""
    return read_settings(root).get("home") == "simple"


# The status page's builder, where the installer or the status extra put it.
# A tool that changes what the page shows builds it, or asks for a build, so
# the page does not wait for the app, the menu or the evening's schedule.
STATUS_BUILDER = ("System", "status", "status.py")
# Set for a tool by a caller that builds the page itself once the tool is
# done: page_action.py, whose app rebuilds after every reply. The tool then
# asks for no build of its own, so one request makes one page (#243).
CALLER_BUILDS_PAGE = "GARRICK_CALLER_BUILDS_PAGE"


def status_command(root: PathLike, settle: Optional[float] = None) -> Optional[List[str]]:
    """The command that builds `root`'s status page, or None where the status
    extra is not installed. It builds with the flags the last build stored
    (--same-flags), so the page keeps the app's or the plugin's flags (#246).
    With `settle`, the build waits that many seconds and goes ahead only if
    no later one was asked for: a burst makes one page."""
    builder = Path(root).joinpath(*STATUS_BUILDER)
    if not builder.is_file():
        return None
    return ([sys.executable or "python3", str(builder), "--workspace", str(root), "--same-flags"]
            + (["--settle", "%g" % settle] if settle else []))


def detach(cmd: List[str]) -> bool:
    """Start `cmd` in a session of its own, reading and writing nothing, and
    return at once, without waiting on it: whether it started."""
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    except OSError:
        return False
    return True


def release_notice_on(root: PathLike) -> bool:
    return read_settings(root).get(RELEASE_NOTICE) is True


def allowed_commands(root: PathLike) -> List[str]:
    """The allow rules the installer wrote into the assistant's own settings,
    as it recorded them, or [] where the workspace has none. The rules
    themselves are the installer's: nothing here depends on one assistant."""
    found = read_settings(root).get(ALLOWED_COMMANDS)
    return [x for x in found if isinstance(x, str)] if isinstance(found, list) else []


def allow_rules(root: PathLike) -> List[str]:
    """Every command the assistant may run in this workspace without asking,
    as its own settings list them, Garrick's rules and the user's alike. []
    where there is no settings file, or it allows nothing, or it does not
    read."""
    import json
    try:
        data = json.loads(Path(root).joinpath(*CLAUDE_SETTINGS).read_text(encoding="utf-8"))
        allow = data["permissions"]["allow"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return [x for x in allow if isinstance(x, str)] if isinstance(allow, list) else []


def release_repository(root: PathLike) -> str:
    """The repository to ask about releases: the setting, when it reads as
    owner/name, else the one Garrick comes from."""
    named = read_settings(root).get("release-repository")
    return named if isinstance(named, str) and _REPO_NAME.match(named) else RELEASE_REPOSITORY


# The choices a user makes once and keeps: each zone's colour and icon, and
# Settings > Opening a thread, from the status page and its Mac app. They live
# in the settings file above, so they are committed with the workspace: a
# rebuild of System/generated/ keeps them, and so does a workspace restored
# from its own history. Garrick saved them in System/generated/status-settings.json
# up to 0.24.0; migrate_shared_settings() copies those across, once, and never
# over a newer choice. What a window alone remembers -- its theme, its folds,
# the cards it has hidden -- stays in that window's own storage and never
# comes here. The names of the colours, icons and ways to open a thread
# belong to whoever offers them, so nothing here knows one from another: this
# is the one place they are read and written, by the page's build, its
# settings request and the cmux desk, and by the Mac app in Swift, which
# reads the same file by the same keys. "notifications" is Settings ›
# Notifications, which System/tools/notifications.py reads and checks;
# "while-you-wait" is Settings › While you wait, which System/tools/next_up.py
# reads and checks; "home" is Settings › Home, "simple" or "full", what the
# status page opens on: the installer writes "simple" for a new workspace,
# and a workspace without it keeps the page it had; "memory" is Settings ›
# Memory, how pages fade out of the wikis, which System/tools/fade.py reads;
# "catch-up" is the period "catch me up" covers when none is said, which
# System/tools/briefing.py reads and checks; Settings no longer offers it
# (#226), so it is set by hand, and a workspace that set it keeps it.
PREFERENCES = ("zones", "launchers", "default", "notifications", "while-you-wait", "home", "memory", "catch-up")
PREFERENCES_FILE = "/".join(SETTINGS)
SHARED_SETTINGS_WAS = ("System", "generated", "status-settings.json")


def preferences(root: PathLike) -> dict:
    """The kept choices: "zones", each zone's colour and icon; "launchers"
    and "default", how a thread opens. A key nothing is saved under is left
    out, and nothing is checked beyond its shape, so an older or a newer
    Garrick's choice reads as it was saved. What an older Garrick left in
    System/generated/ is read with the settings file until the migration
    copies it across, so no choice is lost in between."""
    return _preferences(root)[0]


def save_preferences(root: PathLike, chosen: dict) -> dict:
    """Keep these choices, leaving every other setting, and every choice not
    named, as it stands; returns the choices as they now are. Anything an
    older Garrick left in System/generated/ is copied across first, so saving
    one choice never loses another. Written beside the file and renamed over
    it, so a reader sees one whole file or the other."""
    unknown = sorted(set(chosen) - set(PREFERENCES))
    if unknown:
        raise ValueError("not a kept choice: %s" % ", ".join(unknown))
    root = Path(root)
    migrate_shared_settings(root)
    saved = read_settings(root)
    saved.update(chosen)
    _write_settings(root, saved)
    return {key: saved[key] for key in PREFERENCES if key in saved}


def migrate_shared_settings(root: PathLike) -> List[str]:
    """Copy the choices Garrick used to save in
    System/generated/status-settings.json into the settings file, where they
    are committed with the workspace. Run it as often as you like: it never
    replaces a newer choice. Where both files hold the same zone, or both say
    how a thread opens, the choice in the file written later wins; a choice
    only one file holds is taken from there. Returns the keys it copied, and
    writes nothing when there is nothing to copy."""
    root = Path(root)
    chosen = _preferences(root)[1]
    if not chosen:
        return []
    saved = read_settings(root)
    saved.update(chosen)
    _write_settings(root, saved)
    return sorted(key for key in chosen if key != "default")


def _preferences(root: PathLike) -> Tuple[dict, dict]:
    """(the choices as they stand, what of them the settings file does not
    hold yet). The settings file is their home; an older Garrick's
    System/generated/status-settings.json is read beside it, and of the two
    the file written later wins, zone by zone and for how a thread opens."""
    root = Path(root)
    saved = read_settings(root)
    mine = {key: saved[key] for key in PREFERENCES if key in saved}
    was = root.joinpath(*SHARED_SETTINGS_WAS)
    try:
        old = json.loads(was.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return mine, {}
    if not isinstance(old, dict):
        return mine, {}
    try:
        theirs_is_older = was.stat().st_mtime <= root.joinpath(*SETTINGS).stat().st_mtime
    except OSError:
        theirs_is_older = False      # no settings file yet: anything saved there is the newer choice
    chosen: dict = {}
    zones = old.get("zones")
    mine_zones = mine["zones"] if isinstance(mine.get("zones"), dict) else {}
    if isinstance(zones, dict):
        take = {zone: style for zone, style in zones.items() if not (theirs_is_older and zone in mine_zones)}
        if take:
            chosen["zones"] = dict(mine_zones, **take)
    if "launchers" in old and not (theirs_is_older and "launchers" in mine):
        chosen["launchers"] = old["launchers"]
        if "default" in old:
            chosen["default"] = old["default"]
    chosen = {key: value for key, value in chosen.items() if mine.get(key) != value}   # the same choice is not a change
    return dict(mine, **chosen), chosen


def _write_settings(root: Path, data: dict) -> None:
    write_over(root, root, root.joinpath(*SETTINGS), (json.dumps(data, indent=1) + "\n").encode("utf-8"))


def release_key(tag: object) -> Optional[tuple]:
    """Sort key for a release, "v0.16.0" or "0.16.0": a pre-release sorts
    before its release. None for anything that is not a version."""
    m = re.match(r"^v?(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.-]+))?$", str(tag or "").strip())
    if not m:
        return None
    pre = m.group(2)
    parts = tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.findall(r"\d+|\D+", pre or ""))
    return tuple(int(x) for x in m.group(1).split(".")), pre is None, parts


def workspace_release(root: PathLike) -> str:
    """The release the workspace runs, such as "0.15.2": the newest release in
    its copy of the release notes, or "" when it has none."""
    try:
        text = Path(root).joinpath(*CHANGELOG_COPY).read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        m = re.match(r"^## \[([^\]]+)\]", line)
        if m and m.group(1).lower() != "unreleased" and release_key(m.group(1)):
            return m.group(1).lstrip("v")
    return ""


def read_release_cache(root: PathLike) -> dict:
    import json
    try:
        data = json.loads(Path(root).joinpath(*RELEASE_CACHE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def release_asked_lately(root: PathLike, now: Optional[datetime.datetime] = None) -> bool:
    """Whether GitHub was asked about this repository's releases in the last day."""
    cache = read_release_cache(root)
    if cache.get("repository") != release_repository(root):
        return False
    try:
        asked = datetime.datetime.fromisoformat(str(cache.get("asked")))
    except ValueError:
        return False
    return datetime.timedelta(0) <= (now or datetime.datetime.now()) - asked < RELEASE_EVERY


def release_due(root: PathLike, now: Optional[datetime.datetime] = None) -> bool:
    """Whether the release notice should ask GitHub again: switched on, and
    not asked in the last day."""
    return release_notice_on(root) and not release_asked_lately(root, now)


def newer_release(root: PathLike) -> Optional[dict]:
    """The release the last question to GitHub found, when it is newer than
    the one the workspace runs: {"version", "tag", "url", "current"}. Reads
    the cache only; never asks."""
    cache = read_release_cache(root)
    tag = str(cache.get("latest") or "")
    if not release_key(tag) or cache.get("repository") != release_repository(root):
        return None
    current = workspace_release(root)
    if current and release_key(current) >= release_key(tag):
        return None
    url = str(cache.get("url") or "")
    if not url.startswith("https://"):
        url = "https://github.com/%s/releases" % cache["repository"]
    return {"version": tag.lstrip("v"), "tag": tag, "url": url, "current": current}


def say_newer_release(root: PathLike) -> str:
    """"Garrick 0.16.0 is out; this workspace runs 0.15.2. To update: …", or
    "" when the last answer from GitHub holds nothing newer. Offline: it reads
    the cache."""
    new = newer_release(root)
    if not new:
        return ""
    runs = ("this workspace runs %s" % new["current"]) if new["current"] else \
        "this workspace does not record which release it runs"
    return "Garrick %s is out; %s. To update: %s" % (new["version"], runs, UPDATE_COMMAND)


# Git's repository-local environment variables, as a git too old to list them
# knew them: only the fallback, since `git rev-parse --local-env-vars` is asked
# first and answers for the git that is installed.
LOCAL_ENV_VARS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
)

_local_env_vars: Optional[Tuple[str, ...]] = None


def git_local_env_vars() -> Tuple[str, ...]:
    """The environment variables git treats as belonging to one repository, as
    this git lists them (`git rev-parse --local-env-vars`), or LOCAL_ENV_VARS
    when it cannot be asked. Asked once and kept."""
    global _local_env_vars
    if _local_env_vars is None:
        names: Tuple[str, ...] = ()
        try:
            r = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                names = tuple(n.strip() for n in r.stdout.split() if n.strip().startswith("GIT_"))
        except (OSError, subprocess.SubprocessError):
            names = ()
        _local_env_vars = names or LOCAL_ENV_VARS
    return _local_env_vars


def foreign_git_env(env: Optional[Dict[str, str]] = None) -> Optional[Dict[str, str]]:
    """The environment for a git process to be run in a repository *other* than
    the one whose commit a hook is checking: `env` (this process's own by
    default) with git's repository-local variables taken out. None when none of
    them is set, so the caller can leave the child to inherit the environment
    untouched.

    A commit made with a pathspec (`git commit -m … -- Todo.md`) runs its hooks
    with GIT_INDEX_FILE pointing at a temporary index inside the committing
    repository. Inherited by a git process started in another repository, that
    index makes the other repository compare its own HEAD against it and report
    its whole tree as changed, which costs one `git show` per file. The
    committing repository keeps the variables: its temporary index is exactly
    what the hook has to read."""
    source = dict(os.environ) if env is None else dict(env)
    names = [n for n in git_local_env_vars() if n in source]
    if not names:
        return None
    for name in names:
        source.pop(name, None)
    return source


class GitError(RuntimeError):
    """A git command that failed, with git's own reason."""


def git(args: List[str], cwd: PathLike) -> str:
    r = subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True, text=True)
    if r.returncode != 0:
        raise GitError("git %s failed in %s: %s" % (" ".join(args), cwd, r.stderr.strip() or r.stdout.strip()))
    return r.stdout.strip()


def skill_links(root: PathLike, repo: PathLike) -> List[Tuple[Path, str]]:
    """The links that let an assistant started anywhere in `repo` find the
    workspace's one skills folder: (link, relative target) for each assistant."""
    target = os.path.relpath(Path(root) / "System" / "skills", Path(repo) / SKILL_FOLDERS[0])
    return [(Path(repo) / folder / "skills", target) for folder in SKILL_FOLDERS]


def init_repo(path: PathLike, message: str, identity: Optional[Dict[str, str]] = None,
              paths: Optional[List[str]] = None) -> None:
    """Make `path` its own git repository on branch main, then commit `paths`,
    or everything, as its first commit. `identity` holds git settings such as
    user.name and user.email, set in this repository alone. Raises GitError."""
    git(["init", "-q"], path)
    git(["symbolic-ref", "HEAD", "refs/heads/main"], path)
    for key, value in (identity or {}).items():
        git(["config", key, value], path)
    git(["add", "--"] + list(paths) if paths else ["add", "-A"], path)
    git(["commit", "-q", "-m", message], path)


def table_row(cells: List[str]) -> str:
    """One row of a Markdown table, with pipes and line breaks made safe."""
    return "| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cells) + " |"


# ---------------------------------------------------------------------------
# Mail: domains, and reading a saved message
# ---------------------------------------------------------------------------

# Each zone has a drop folder for mail and any other file. It is never a project.
INBOX = "Inbox"
MAIL_EXTS = {".eml", ".md", ".txt"}
# Audio and video are never read: a recording comes in as its transcript.
MEDIA_EXTS = frozenset("""
.m4a .mp3 .wav .aac .aif .aiff .flac .ogg .oga .opus .wma .amr .caf .mp4 .m4v .mov .avi .mkv .webm
""".split())

_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")

# Personal webmail: anyone can have an address there, so the domain alone
# never says which party a mail is from. A plus tag on it still can.
WEBMAIL_DOMAINS = frozenset("""
gmail.com googlemail.com outlook.com hotmail.com live.com msn.com passport.com yahoo.com ymail.com
rocketmail.com aol.com aim.com icloud.com me.com mac.com proton.me protonmail.com protonmail.ch pm.me
gmx.com gmx.net gmx.de gmx.at gmx.ch web.de mail.com email.com zoho.com zohomail.com yandex.com yandex.ru
mail.ru fastmail.com fastmail.fm hey.com tutanota.com tutanota.de tuta.io tuta.com qq.com 163.com 126.com
naver.com libero.it virgilio.it tiscali.it alice.it orange.fr wanadoo.fr free.fr laposte.net sfr.fr
t-online.de freenet.de btinternet.com sky.com seznam.cz wp.pl o2.pl onet.pl interia.pl rediffmail.com
""".split())
_WEBMAIL_FAMILIES = ("yahoo.", "hotmail.", "outlook.", "live.", "windowslive.", "gmx.", "aol.", "yandex.")


def split_domains(cell: str) -> List[str]:
    """`acme.example, mail.acme.example` -> ['acme.example', 'mail.acme.example']."""
    out = []
    for part in re.split(r"[,;\s]+", cell or ""):
        d = part.strip().strip("`").strip().lstrip("@").lower().rstrip(".")
        if d and d not in out:
            out.append(d)
    return out


def is_domain(domain: str) -> bool:
    return bool(_DOMAIN_RE.match((domain or "").lower()))


def is_webmail(domain: str) -> bool:
    """Is this a personal webmail domain, which never names a party by itself?"""
    d = (domain or "").lower().strip().rstrip(".")
    return d in WEBMAIL_DOMAINS or d.startswith(_WEBMAIL_FAMILIES)


def is_own_address(ctx: dict, addr: str) -> bool:
    """True when `addr` is one of the addresses in the Me section of
    `System/context.md`, plus tags ignored (`you+acme@x` is `you@x`)."""
    local, _, domain = (addr or "").strip().lower().rpartition("@")
    return bool(domain) and "%s@%s" % (local.split("+", 1)[0], domain) in ctx.get("me", [])


def parties_for_domain(context: dict, domain: str) -> List[str]:
    """The party tags whose Domains cell covers `domain`: the domain itself, or
    one it is a subdomain of. Webmail matches nothing."""
    d = (domain or "").lower().strip().rstrip(".")
    if not d or is_webmail(d):
        return []
    hits = []
    for tag, entry in context.get("parties", {}).items():
        for own in entry.get("domains", []):
            if d == own or d.endswith("." + own):
                hits.append(tag)
                break
    return sorted(hits)


class _TextOfHTML(HTMLParser):
    """Visible text of an HTML body, one line per block."""

    BLOCKS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextOfHTML()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # a broken page still gives what was read before the break
        pass
    lines = [re.sub(r"[ \t\r\f\v ]+", " ", l).strip() for l in "".join(parser.parts).split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


_MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MONTH_RE = "(%s)" % "|".join(sorted(_MONTHS, key=len, reverse=True))


def mail_date(value: str) -> Optional[str]:
    """YYYY-MM-DD from a Date header as mail programs write it, or None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    low = value.lower()
    for pattern, order in ((r"(\d{4})-(\d{2})-(\d{2})", "ymd"),
                           (r"\b(\d{1,2})\.?\s+%s\b\.?,?\s+(\d{4})" % _MONTH_RE, "dmy"),
                           (r"\b%s\b\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})" % _MONTH_RE, "mdy")):
        m = re.search(pattern, low)
        if not m:
            continue
        a, b, c = m.groups()
        try:
            if order == "ymd":
                d = datetime.date(int(a), int(b), int(c))
            elif order == "dmy":
                d = datetime.date(int(c), _MONTHS[b], int(a))
            else:
                d = datetime.date(int(c), _MONTHS[a], int(b))
        except ValueError:
            continue
        return d.isoformat()
    return None


def _addresses(values: List[str]) -> List[Tuple[str, str]]:
    """(name, address) pairs, address lower-cased; entries without an @ dropped.
    Outlook's `;` between addresses and its `<a@x<mailto:a@x>>` are read too."""
    out = []
    values = [re.sub(r"<mailto:[^>]*>", "", v).replace(";", ",") for v in values if v]
    for name, addr in getaddresses(values):
        addr = addr.strip().lower()
        if "@" in addr and (name, addr) not in out:
            out.append((name.strip().replace('"', ""), addr))
    return out


_HEADER_LINE_RE = re.compile(
    r"^\s*(?:>\s*)*\**\s*(from|to|cc|bcc|date|sent|subject|reply-to|delivered-to)\s*\**\s*:\s*\**\s*(.*?)\s*$", re.I)
# A separator some mail programs draw above a quoted message, with no words in it.
_RULE_RE = re.compile(r"^\s*(?:_{5,}|-{5,}|={5,})\s*$")
_FORWARD_RE = re.compile(r"(?im)^\s*(?:-{2,}\s*(?:forwarded message|original message)\s*-{2,}|begin forwarded message:)\s*$")


def _header_block(lines: List[str]) -> Tuple[Dict[str, List[str]], int]:
    """Leading `Key: value` lines, as mail programs write them when saving a
    message as text. Returns the headers and the index of the first body line."""
    headers: Dict[str, List[str]] = {}
    i, last = 0, None
    while i < len(lines) and not lines[i].strip():
        i += 1
    start = i
    while i < len(lines):
        line = lines[i]
        m = _HEADER_LINE_RE.match(line)
        if m:
            last = m.group(1).lower()
            headers.setdefault(last, []).append(m.group(2).strip())
        elif last and line[:1] in (" ", "\t") and line.strip():
            headers[last][-1] += " " + line.strip()
        else:
            break
        i += 1
    if not headers:
        return {}, start
    return headers, i


def _forwarded(body: str) -> List[Tuple[str, str]]:
    """Addresses in the header block of every message forwarded or quoted inline.

    A block counts after a marker line (`---------- Forwarded message
    ----------`, `-----Original Message-----`, `Begin forwarded message:`), and
    also without one: Outlook opens a quoted message with its headers alone,
    and a plain-text copy loses even the rule drawn above them. Such a block is
    a `From:` line at the start of the body or after a blank line or a rule,
    with a `Sent:` or `Date:` line and a `To:` or `Subject:` line in the same
    block. Bold labels (`**From:**`) and `>` quoting are read the same."""
    out: List[Tuple[str, str]] = []
    lines = body.splitlines()
    starts = set()
    for m in _FORWARD_RE.finditer(body):
        after = body[:m.end()].count("\n") + 1
        while after < len(lines) and not lines[after].strip():
            after += 1
        starts.add(after)
    for i, line in enumerate(lines):
        m = _HEADER_LINE_RE.match(line)
        if not m or m.group(1).lower() != "from":
            continue
        if i and lines[i - 1].strip() and not _RULE_RE.match(lines[i - 1]) and not _FORWARD_RE.match(lines[i - 1]):
            continue
        headers, _ = _header_block(lines[i:i + 30])
        if "from" in headers and ("sent" in headers or "date" in headers) and ("to" in headers or "subject" in headers):
            starts.add(i)
    for start in sorted(starts):
        headers, _ = _header_block(lines[start:start + 30])
        for key in ("from", "to", "cc"):
            out += [a for a in _addresses(headers.get(key, [])) if a not in out]
    return out


def _part_text(part) -> str:
    try:
        text = part.get_content()
    except (LookupError, KeyError, ValueError, AssertionError):
        data = part.get_payload(decode=True) or b""
        text = data.decode("utf-8", errors="replace")
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return text if isinstance(text, str) else ""


def _empty_mail() -> dict:
    return {"date": None, "sent": None, "subject": "", "from": [], "to": [], "cc": [], "delivered": [],
            "forwarded": [], "body": "", "attachments": [], "mailing_list": False}


def _attachment_parts(msg):
    """(part, name, type, payload bytes) for each attachment of a parsed message."""
    for part in (msg.iter_attachments() if msg.is_multipart() else []):
        if part.get_content_type() == "message/rfc822":
            inner = part.get_payload()
            inner = inner[0] if isinstance(inner, list) and inner else inner
            data = inner.as_bytes() if hasattr(inner, "as_bytes") else b""
        else:
            data = part.get_payload(decode=True) or b""
        yield part, part.get_filename() or "unnamed", part.get_content_type(), data


RECIPIENT_HEADERS = ("To", "Cc", "Bcc", "Delivered-To", "X-Original-To", "Envelope-To", "Received")
REMOVED = "you@removed.invalid"


def _replace_addresses(text: str, addresses: Iterable[str]) -> str:
    for a in sorted(set(addresses), key=len, reverse=True):
        for form, repl in ((a, REMOVED), (a.replace("@", "%40"), REMOVED.replace("@", "%40"))):
            text = re.sub(re.escape(form), repl, text, flags=re.IGNORECASE)
    return text


_RECIPIENT_KEY_RE = re.compile(r"^(to|cc|bcc|delivered-to|x-original-to|envelope-to)\s*:", re.I)


def _strip_text_recipients(text: str, own: Iterable[str]) -> str:
    """strip_recipients for a mail saved as text or Markdown: the recipient
    keys of its frontmatter, every `To:`/`Cc:` line of a header block in the
    body (its own and each forward's), and each of those addresses, and the
    reader's own, wherever the text still names them."""
    lines = text.splitlines(keepends=True)
    addresses = {a.lower() for a in own if "@" in a}
    keep: List[str] = []
    in_fm = bool(lines) and lines[0].strip() == "---"
    dropping = False
    in_header, seen_body = True, False       # the body may open with a header block
    for i, line in enumerate(lines):
        if in_fm and i > 0 and line.strip() in ("---", "..."):
            in_fm, dropping = False, False
            keep.append(line)
            continue
        if in_fm:
            if dropping and (line[:1] in (" ", "\t") or line.lstrip().startswith("- ")) and line.strip():
                addresses |= {a for _, a in _addresses([line.strip().lstrip("- ").strip("'\"")])}
                continue
            dropping = False
            if i > 0 and _RECIPIENT_KEY_RE.match(line):
                dropping = True
                value = line.split(":", 1)[1].strip().strip("[]")
                addresses |= {a for _, a in _addresses([v.strip().strip("'\"") for v in value.split(",")])}
                continue
            keep.append(line)
            continue
        m = _HEADER_LINE_RE.match(line)
        if m and in_header and m.group(1).lower() in ("to", "cc", "bcc", "delivered-to"):
            addresses |= {a for _, a in _addresses([m.group(2)])}
            dropping = True
            continue
        if dropping and line[:1] in (" ", "\t") and line.strip() and not _HEADER_LINE_RE.match(line):
            addresses |= {a for _, a in _addresses([line.strip()])}
            continue
        dropping = False
        # A header block opens the body, or follows a forward's marker or a From: line after a
        # blank; a blank line ends it. A `To:` in the prose is text, and stays.
        if m and (in_header or m.group(1).lower() == "from"):
            in_header = True
        elif _FORWARD_RE.match(line):
            in_header = True
        elif not line.strip() or not m:
            in_header = not line.strip() and not seen_body
            seen_body = seen_body or bool(line.strip())
        keep.append(line)
    return _replace_addresses("".join(keep), addresses)


def strip_recipients(data: bytes, suffix: str = ".eml", own: Iterable[str] = ()) -> bytes:
    """A mail with the reader's own addresses taken out: the recipient headers
    and `Received` lines go, and every recipient address in a text part (an
    unsubscribe link, a "sent to" footer) becomes you@removed.invalid, as
    does each of `own` (the user's addresses, from context.md), so a
    forward's `From:` goes too. A mail saved as text or Markdown loses its
    frontmatter's recipient keys and the `To:` and `Cc:` lines in its body.
    Knowledge is read in every zone, so what is filed there says nothing
    about who received it. Attachments are left byte for byte."""
    own = [a.lower() for a in own if "@" in a]
    if suffix.lower() != ".eml":
        return _strip_text_recipients(data.decode("utf-8", errors="replace"), own).encode("utf-8")
    m = email.message_from_bytes(data, policy=email.policy.default)
    fields = [str(v) for h in RECIPIENT_HEADERS[:-1] for v in (m.get_all(h) or [])]
    addresses = sorted({a.lower() for _, a in getaddresses(fields) if "@" in a} | set(own), key=len, reverse=True)
    if not addresses and not m.get_all("Received"):
        return data
    for h in RECIPIENT_HEADERS:
        del m[h]
    for part in m.walk():
        if part.is_multipart() or part.get_content_maintype() != "text" or part.get_filename():
            continue
        try:
            text = part.get_content()
        except (LookupError, UnicodeError):
            continue
        new = _replace_addresses(text, addresses)
        if new != text:
            part.set_content(new, subtype=part.get_content_subtype())
    return m.as_bytes()


def mail_attachments(data: bytes) -> List[Tuple[str, str, bytes]]:
    """(name, type, contents) of every attachment in a saved `.eml` message, in
    the order the message lists them. Nothing is written anywhere."""
    msg = email.message_from_bytes(data, policy=email.policy.default)
    return [(name, ctype, payload) for _, name, ctype, payload in _attachment_parts(msg)]


# A mail saved whole into a project's Sources/ as material, not a conversation,
# has no Meetings page to carry its parties, so it carries them itself.
MATERIAL_HEADER = "X-Garrick-Parties"


def stamp_parties(data: bytes, tags: Iterable[str]) -> bytes:
    """A saved `.eml` with one header line added at the top, naming the parties
    it was filed for: `X-Garrick-Parties: acme, birch`. Nothing else changes."""
    first = data[:data.find(b"\n") + 1]
    eol = b"\r\n" if first.endswith(b"\r\n") else b"\n"
    return ("%s: %s" % (MATERIAL_HEADER, ", ".join(tags))).encode("utf-8") + eol + data


def stamped_parties(data: bytes) -> List[str]:
    """The party tags a mail saved as material names in its first
    `X-Garrick-Parties` header, or [] when it has none."""
    try:
        value = email.parser.BytesHeaderParser().parsebytes(data).get(MATERIAL_HEADER)
    except Exception:  # an unreadable message names nobody
        return []
    return [t for t in (strip_tag(x) for x in re.split(r"[,\s]+", str(value or ""))) if t]


def _parse_eml(data: bytes) -> dict:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    out = _empty_mail()
    out["date"] = mail_date(str(msg.get("Date", "") or ""))
    try:
        sent = parsedate_to_datetime(str(msg.get("Date", "") or ""))
        if sent.tzinfo is not None:
            sent = sent.astimezone(datetime.timezone.utc)
        out["sent"] = sent.replace(tzinfo=None).isoformat()
    except (TypeError, ValueError, IndexError):
        out["sent"] = out["date"]
    out["subject"] = re.sub(r"\s+", " ", str(msg.get("Subject", "") or "")).strip()
    for key, headers in (("from", ("From",)), ("to", ("To",)), ("cc", ("Cc",)),
                         ("delivered", ("Delivered-To", "X-Original-To", "Envelope-To"))):
        out[key] = _addresses([str(v) for h in headers for v in (msg.get_all(h) or [])])
    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is None and not msg.is_multipart() and msg.get_content_maintype() == "text":
        body_part = msg
    if body_part is not None:
        text = _part_text(body_part)
        out["body"] = html_to_text(text) if body_part.get_content_subtype() == "html" else text
    precedence = str(msg.get("Precedence", "") or "").strip().lower()
    out["mailing_list"] = bool(msg.get("List-Id") or msg.get("List-Unsubscribe") or precedence in ("bulk", "list"))
    for part, name, ctype, payload in _attachment_parts(msg):
        if ctype == "message/rfc822":
            inner = part.get_payload()
            inner = inner[0] if isinstance(inner, list) and inner else inner
            if hasattr(inner, "get_all"):
                for h in ("From", "To", "Cc"):
                    out["forwarded"] += [a for a in _addresses([str(v) for v in inner.get_all(h) or []])
                                         if a not in out["forwarded"]]
        out["attachments"].append({"name": name, "type": ctype, "bytes": len(payload)})
    out["forwarded"] += [a for a in _forwarded(out["body"]) if a not in out["forwarded"]]
    return out


def _parse_text(text: str) -> dict:
    """A message saved as text or Markdown: optional frontmatter, else a block
    of `From:`, `To:`, `Date:` and `Subject:` lines, then the body."""
    out = _empty_mail()
    if text.startswith("﻿"):
        text = text[1:]
    fm = parse_frontmatter_text(text)
    lines = text.splitlines()
    if fm:
        end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() in ("---", "..."))
        headers = {k.lower(): [", ".join(v) if isinstance(v, list) else str(v)] for k, v in fm.items() if v}
        body_lines = lines[end + 1:]
    else:
        headers, start = _header_block(lines)
        body_lines = lines[start:]
    out["date"] = mail_date((headers.get("date") or headers.get("sent") or [""])[0])
    out["sent"] = out["date"]
    out["subject"] = (headers.get("subject") or headers.get("title") or [""])[0].strip()
    out["from"] = _addresses(headers.get("from", []))
    out["to"] = _addresses(headers.get("to", []))
    out["cc"] = _addresses(headers.get("cc", []))
    out["delivered"] = _addresses(headers.get("delivered-to", []))
    out["body"] = "\n".join(body_lines).strip("\n") + "\n"
    out["forwarded"] = _forwarded(out["body"])
    return out


def parse_mail_bytes(data: bytes, suffix: str = ".eml") -> dict:
    """Read a saved message. Standard library only.

    Returns {"date": "YYYY-MM-DD" or None, "sent" (the date and time, in UTC,
    when the message says; sorts in the order mail was sent), "subject", "from", "to", "cc",
    "delivered", "forwarded", "body", "attachments", "mailing_list"}. Address
    fields are lists of (name, address). `body` is plain text: the text part
    when there is one, else the HTML part stripped to text. `attachments` lists
    each one's name, type and size; nothing is extracted. `mailing_list` is
    true when the headers say it was sent to a list (List-Id, List-Unsubscribe,
    or bulk precedence): a hint, never a verdict.
    """
    if suffix.lower() == ".eml":
        return _parse_eml(data)
    return _parse_text(data.decode("utf-8", errors="replace"))


def parse_mail(path: PathLike) -> dict:
    p = Path(path)
    return parse_mail_bytes(p.read_bytes(), p.suffix)
