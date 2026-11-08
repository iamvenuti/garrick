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
    is_walled(context, tag) -> bool / blocked(context, scope, labels) -> {walled tags the scope lacks}
    decide(scope, labels, action, context) -> permit | deny | confirm
    labels(root, path, context=None, cache=None) -> frozenset or None
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
import shlex
import shutil
import stat
import subprocess
import sys
import unicodedata
import urllib.parse
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
    "blocked",
    "is_walled",
    "hats_of",
    "named_together",
    "decide",
    "always_asked",
    "labels",
    "meeting_labels",
    "wall_cases",
    "mail_labels",
    "wall_roles",
    "run_wall_cases",
    "KNOWLEDGE",
    "MEETINGS_ENTITIES",
    "tag_list",
    "party_entities",
    "ENTITY_LINK_RE",
    "entity_page",
    "entity_pages",
    "name_words",
    "name_keys",
    "TODO_ALSO_RE",
    "names_meet",
    "person_forms",
    "people_parties",
    "short_form_parties",
    "organisation_link",
    "org_words",
    "org_key",
    "entity_names",
    "name_group",
    "entity_parties",
    "suspect_name",
    "entity_rel",
    "links_in",
    "named_in",
    "first_line",
    "organisation_named",
    "organisation_proposal",
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
    "said_time",
    "write_if_unchanged",
    "same_action",
    "strip_tag",
    "install_wall_hook",
    "has_wall_hook",
    "hooks_path",
    "WALL_HOOK",
    "WALL_HOOK_NESTED",
    "WALL_HOOK_WIKI",
    "WIKI_GIT_REASON",
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
    "FRONTMATTER_PLAIN",
    "FORM_PROBLEMS",
    "PERSON_PLAIN",
    "PERSON_KEYS",
    "PERSON_SHAPE",
    "WALLS_KEYS",
    "frontmatter_form_problem",
    "with_ignore_block",
    "SKILL_FOLDERS",
    "LOCAL_EMAIL",
    "GitError",
    "git",
    "LOCAL_ENV_VARS",
    "git_local_env_vars",
    "foreign_git_env",
    "own_repo_env",
    "has_own_git_dir",
    "wall_hook_problem",
    "staged_walls_refusal",
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


def _frontmatter_lines(text: str) -> List[str]:
    """`text` as lines, ended where a YAML reader ends them: at \n, \r\n or
    a lone \r. str.splitlines() also breaks at U+2028, U+2029, U+0085 and
    the like, which YAML reads as text, so a quoted value holding one could
    hide every key after it from this reader and from no other (#330)."""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _frontmatter_body(text: str) -> Optional[List[str]]:
    """The lines between the `---` that opens `text` and the one that closes
    its frontmatter, or None when it has none. Only a line that is `---` or
    `...` and nothing else, at the left margin, closes it, as YAML reads a
    document's end: an indented `---` inside a block scalar, or one with
    anything after it, does not (#330)."""
    lines = _frontmatter_lines(text)
    if not lines or lines[0].strip() != "---":
        return None
    body = []
    for line in lines[1:]:
        if line in ("---", "..."):
            return body
        body.append(line)
    return None  # never closed: not frontmatter


FRONTMATTER_PLAIN = "frontmatter must be plain key: value lines"
# What the walls say of a person page they cannot read (check.py), and so,
# with FRONTMATTER_PLAIN, what a refusal calls a page's form, not a wall.
PERSON_SHAPE = "a person page's frontmatter must be plain `key: value` lines"
PERSON_PLAIN = "a person page must be a plain file in wiki/people"
# The only keys a person page has (#340), as ingest.py writes it. `organisation`
# is the one that may hold a link; the walls read no other key for one.
# `pinned` is fade.py keep's pin. `aliases:` and `tags:` stay out: an alias changes which page a link opens, and a
# tag joins pages in Obsidian's graph, so either could join a person to a walled party with no link written.
PERSON_KEYS = ("title", "type", "party", "organisation", "created", "updated", "pinned")
FORM_PROBLEMS = (FRONTMATTER_PLAIN, PERSON_SHAPE, PERSON_PLAIN)
# What opens a YAML node other than a plain key at the left margin: a quoted
# key, an explicit `?` key, a tag, an anchor, an alias, a merge key, a flow
# mapping or sequence. YAML honours each as a key this reader never sees.
_NODE_OPENERS = ('"', "'", "?", "!", "&", "*", "<<", "{", "[")
# The keys the walls read on a page that is not theirs alone to read.
WALLS_KEYS = ("party", "parties", "zone")


_ITEM_LINE = re.compile(r"-(?:[ \t]+(.*))?$")


def _value_problem(value: str) -> str:
    """What makes one value, its ` # comment` taken off, readable two ways,
    or "": a YAML node marker this reader takes for text (a block scalar
    `|` or `>`, a tag `!`, an anchor `&`, an alias `*`), a flow list that
    does not close on its line, or a quote that does not close on it."""
    if value[:1] in ("|", ">", "!", "&", "*"):
        return "opens with `%s`, which a YAML reader takes for more than the text" % value[0]
    if value.startswith("[") and not value.endswith("]"):
        return "opens a list that does not close on its line"
    if value[:1] in ('"', "'"):
        closed = re.match(r'"(?:[^"\\]|\\.)*"' if value[0] == '"' else r"'(?:[^']|'')*'", value)
        if closed is None:
            return "opens a quote that does not close on its line"
        if value[closed.end():].strip():
            return "has text after its closing quote"
    return ""


def frontmatter_form_problem(text: str, keys: Optional[Tuple[str, ...]] = None) -> str:
    """What makes the frontmatter of `text` readable two ways, or "" (#330):
    a frontmatter that opens with `---` and is closed by no line of `---`
    or `...` alone; a line at the left margin that opens with one of
    _NODE_OPENERS; a key given twice, of which YAML keeps the last and this
    reader may keep another; a value that opens with a YAML node marker, or a
    list or a quote it does not close on its line (_value_problem); or an
    indented line, or a `- item`, anywhere but as an item straight under a
    key with no value, where YAML would read it as more of the value and
    this reader reads nothing. With `keys`, only those keys' values, lines
    and repeats count (the opening lines count on every page). Not the
    person page's strict shape (check.py's person_shape_problem)."""
    lines = _frontmatter_lines(text)
    opened = bool(lines) and lines[0].strip() == "---"
    body = _frontmatter_body(text)
    if opened and body is None and (keys is None or any(l.strip() in ("---", "...") for l in lines[1:])):
        return "no line of `---` alone, at the left margin, closes it"

    def counts(key: Optional[str]) -> bool:
        return key is None or keys is None or key in keys
    seen, key, empty = set(), None, False          # the last key, and whether its value was empty
    for line in body or []:
        if not line.strip():
            continue
        margin = not line[:1].isspace()
        bare = line.lstrip()
        if margin and bare.startswith("#"):
            continue
        item = _ITEM_LINE.match(bare)
        if item:
            if not (key is not None and empty):
                if counts(key):
                    return "a `- item` line stands under %s" % ("`%s`, which has a value" % key if key else "no key")
                continue
            if counts(key):
                problem = _value_problem(_strip_comment(item.group(1) or ""))
                if problem:
                    return "an item of `%s` %s" % (key, problem)
            continue
        if not margin:
            if counts(key):
                return "an indented line stands under %s, which a YAML reader reads as part of it" % (
                    "`%s`" % key if key else "no key")
            continue
        if line.startswith(_NODE_OPENERS):
            opener = next(o for o in _NODE_OPENERS if line.startswith(o))
            return "a line opens with `%s`, which a YAML reader takes for a key written another way" % opener
        m = _KEY_RE.match(line)
        if m is None:
            key, empty = None, False
            continue
        key = m.group(1)
        if key in seen and counts(key):
            return "`%s` is given twice, and a YAML reader keeps the last" % key
        seen.add(key)
        value = _strip_comment(m.group(2))
        empty = value == ""
        if counts(key):
            problem = _value_problem(value)
            if problem:
                return "`%s` %s" % (key, problem)
    return ""


def parse_frontmatter_text(text: str) -> dict:
    """Parse the YAML frontmatter at the top of `text`. See parse_frontmatter."""
    body = _frontmatter_body(text)
    if body is None:
        return {}

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


def _page_text(path: PathLike) -> str:
    """The text of the file at `path` as parse_frontmatter reads it, or ""."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


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
    "zones": (("Zone", "Holds", "Party", "New parties"), ("zone",)),
    "parties": (("Party", "What it is", "Zone", "Tag", "Walled", "Domains"), ("tag", "walled")),
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
          "parties": {tag: {"party": name, "what": ..., "zone": ..., "domains": [...], "walled": bool, "flag": the Walled cell as written}},
          "zone_parties": {zone name: party tag, ...},   # the one party every file of a zone carries
          "zone_default": {zone name: "walled" | "open"},   # what `scaffold.py party` proposes there
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
    ctx = {"parties": {}, "zone_parties": {}, "zone_default": {}, "people": [], "aliases": {}, "zones": {}, "me": [], "tables": {},
           "learned": [], "pending": None}
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
                ctx["learned"].append({"table": name, "row": first.strip(),
                                       "cell": cell})

    for addr in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "\n".join(sections.get("me", []))):
        if addr.lower() not in ctx["me"]:
            ctx["me"].append(addr.lower())

    # A Parties table with no Walled column and no Walls table declares nothing: every party reads as open.
    has_flags = any(h.startswith("walled") for h in (_table_header(sections.get("parties", [])) or []))
    for row in _table(sections.get("parties", [])):
        tag = strip_tag(_col(row, "tag"))
        if not tag:
            continue
        ctx["parties"][tag] = {
            "party": _col(row, "party", "name"),
            "what": _col(row, "what"),
            "zone": _col(row, "zone"),
            "domains": split_domains(_col(row, "domain")),
            "walled": _col(row, "walled").strip().strip("`*").strip().lower() != "no" and has_flags,   # only a plain `no` opens a party
            "flag": _col(row, "walled").strip().strip("`*").strip().lower(),
        }

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
            ctx["zone_parties"][zone] = strip_tag(_col(row, "party"))
            ctx["zone_default"][zone] = "open" if _col(row, "new parties").strip().strip("`*").lower() == "open" else "walled"

    # A party's zone is compared with a zone's folder name, so it is written as that name: `**Work**` or `work` in
    # the Zone cell is Work, the folder under Zones/ first, then the Zones table. A zone neither knows is kept as
    # written, markup taken off, and matches nothing.
    canon = {z.casefold(): z for z in ctx["zones"]}
    try:
        canon.update({d.name.casefold(): d.name for d in (Path(root) / "Zones").iterdir() if d.is_dir()})
    except OSError:
        pass
    for row in ctx["parties"].values():
        written = row["zone"].replace("*", "").strip().strip("`").strip()
        row["zone"] = canon.get(written.casefold(), written)
    for key in ("zone_parties", "zone_default"):
        ctx[key] = {canon.get(z.casefold(), z): v for z, v in ctx[key].items()}
    ctx["zone_parties"] = {z: t for z, t in ctx["zone_parties"].items() if t}
    ctx["pending"] = _pending_pairs(sections)
    return ctx


def _pending_pairs(sections: Dict[str, List[str]]) -> Optional[set]:
    """The pairs of the old Walls table while the update's flag migration has not run: the Parties table has no
    Walled column and a Walls table is there. Until the user says yes to the migration the old rule stays in
    force, so a workspace updated without an answer changes no verdict (migrate_walls.py). None otherwise: a
    context with a Walled column, or with neither table, is read by its flags."""
    header = _table_header(sections.get("parties", [])) or []
    if "walls" not in sections or not header or any(h.startswith("walled") for h in header):
        return None
    pairs = set()
    for row in _table(sections["walls"]):
        cells = list(row.values())
        a = strip_tag(row.get("between") or (cells[0] if cells else ""))
        b = strip_tag(row.get("and") or (cells[1] if len(cells) > 1 else ""))
        if a and b:
            pairs.add(frozenset((a, b)))
    return pairs


def _self():
    """This module's own functions as the old rule needs them, however the module was loaded."""
    import types
    return types.SimpleNamespace(always_asked=always_asked, _labels_of=_labels_of, parse_frontmatter=parse_frontmatter)


def _old_rule():
    """migrate_walls.py, beside this file: the one place the pairs rule lives. Loaded by path, so a caller that
    imported this file from elsewhere (the status page, Ask) finds it too."""
    mod = sys.modules.get("garrick_migrate_walls")
    if mod is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("garrick_migrate_walls", str(Path(__file__).with_name("migrate_walls.py")))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["garrick_migrate_walls"] = mod
        spec.loader.exec_module(mod)
    return mod


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
        if line in ("---", "..."):
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


# ---------------------------------------------------------------------------
# Walls: one decision for every enforcement point (#398)
# ---------------------------------------------------------------------------
#
# The policy is the Parties table of System/context.md (a Walled column, `yes`
# or `no`) and the Zones table (the one party a zone's files carry). Every
# point that enforces it (the pre-commit check, Ask, the status page's actions,
# intake, Nurture, scaffold) asks decide() and holds no wall test of its own;
# what a record's labels are, labels() says, once. A finding that names the
# parties in the way asks blocked(), which decide() itself is made of.

KNOWLEDGE = "*knowledge"   # what labels() gives a Knowledge page with no party: read by every scope, takes only material with no party
ACTIONS = ("read", "write", "file")


def _tagset(value) -> set:
    """A scope or a set of labels as plain tags: none of them empty."""
    if value is None:
        return set()
    if isinstance(value, str):
        value = [value]
    return {t for t in (strip_tag(str(v)) for v in value) if t}


def is_walled(context: dict, tag: str) -> bool:
    """Is a party walled? A tag the Parties table lacks is, as is a row with no plain `no`."""
    if context.get("pending") is not None:
        return any(tag in pair for pair in context["pending"])
    return bool((context.get("parties", {}).get(tag) or {}).get("walled", True))


def blocked(context: dict, scope, labels) -> set:
    """The walled tags in `labels` that `scope` lacks: what stops material
    labelled `labels` from going into a record whose parties are `scope`."""
    if context.get("pending") is not None:
        return _old_rule().legacy_blocked(context, scope, labels)
    held = _tagset(scope)
    return {t for t in _tagset(labels) if t != KNOWLEDGE and t not in held and is_walled(context, t)}


def named_together(root: PathLike, context: dict, tags) -> bool:
    """Do `tags` hold one walled party at most, or does some project of the workspace name every walled
    one of them? Naming two walled parties on one hub is the yes that lets their material meet."""
    walled_ = {t for t in _tagset(tags) if is_walled(context, t)}
    if len(walled_) < 2:
        return True
    zones = Path(root) / "Zones"
    for zone in sorted(zones.iterdir()) if zones.is_dir() else []:
        for project in sorted(zone.iterdir()) if zone.is_dir() and not zone.name.startswith(".") else []:
            if project.is_dir() and not project.name.startswith((".", "_")) and project.name != "Inbox":
                got = labels(root, project)
                if got and walled_ <= set(got):
                    return True
    return False


def hats_of(context: dict, tags) -> List[Tuple[str, str]]:
    """The pairs of tags in `tags` whose Parties rows share a name: one company under two hats."""
    tags = sorted(_tagset(tags))
    return [(a, b) for i, a in enumerate(tags) for b in tags[i + 1:]
            if always_asked(context, a) and always_asked(context, b) and _name(context, a) == _name(context, b)]


def _name(context: dict, tag: str) -> str:
    return " ".join(re.findall(r"\w+", str((context.get("parties", {}).get(tag) or {}).get("party") or "").lower()))


def always_asked(context: dict, tag: str) -> bool:
    """Is a party one that shares its name with another tag (one company, two
    hats)? Saying its name never says which, so a mail from it is asked about."""
    name = _name(context, tag)
    return bool(name) and any(t != tag and _name(context, t) == name for t in context.get("parties", {}))


def decide(scope, labels, action: str, context: dict) -> str:
    """`permit`, `deny` or `confirm`: may `scope` use a record labelled `labels`?

    One rule: material goes into a record whose parties are `scope` only when every walled party on it is one of
    them. `scope` is None for a project not yet chosen (filing). `labels` is None when they cannot be derived: no
    label, no permit (`deny` to read and write, `confirm` to file). A tag the Parties table lacks is `deny`.
    A Knowledge page (KNOWLEDGE) is read by every scope and takes only material with no party. Filing asks
    (`confirm`) on an item with no label or from a party that is always asked about, and before a project is
    chosen on one with two walled parties.
    """
    if action not in ACTIONS:
        raise ValueError("action is read, write or file, not %r" % (action,))
    if context.get("pending") is not None:
        return _old_rule().legacy_decide(scope, labels, action, context, _self())
    known = set(context.get("parties", {}))
    mine, theirs = _tagset(scope), _tagset(labels)
    if (scope is not None and mine - known - {KNOWLEDGE}) or (labels is not None and theirs - known - {KNOWLEDGE}):
        return "deny"
    if labels is None:
        return "deny" if action != "file" else "confirm"
    parties = theirs - {KNOWLEDGE}
    asked = not theirs or any(always_asked(context, t) for t in parties)
    if action == "read":
        return "permit" if theirs and (not parties or (mine - {KNOWLEDGE} and not blocked(context, mine, parties))) else "deny"
    if scope is None and action == "file":      # intake, before a project is chosen
        return "confirm" if asked or sum(is_walled(context, t) for t in parties) > 1 else "permit"
    if not mine:
        return "deny"                           # a record with no party takes nothing
    if mine == {KNOWLEDGE}:
        return "deny" if parties else "permit"
    if blocked(context, mine, parties):
        return "deny"
    return "confirm" if action == "file" and asked else "permit"


def wall_cases(text: str) -> Dict[str, List[List[str]]]:
    """The tables of a wall-cases file (tests/walls/cases.md): each `##`
    heading to the rows under it, a row as its cells, header and rule left out."""
    out: Dict[str, List[List[str]]] = {}
    heading = ""
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        elif line.startswith("|") and heading:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: ") or cells[0] in ("Id", "Role"):
                continue
            out.setdefault(heading, []).append(cells)
    return out


def mail_labels(context: dict, data: bytes) -> Tuple[Optional[frozenset], bool]:
    """(the parties a saved mail is written for, whether its header and its
    addresses disagree). The labels are the union of its `X-Garrick-Parties`
    header and the parties of the domains it carries; a header tag that is
    unknown or `none` makes them None. A mail with neither has none."""
    known = set(context.get("parties", {}))
    header = set(stamped_parties(data))
    if header and (header - known or header & {"none"}):
        return None, True
    domains = set()
    mail = parse_mail_bytes(data)
    for key in ("from", "to", "cc"):
        for _, addr in mail.get(key, []):
            if not is_own_address(context, addr) and not is_webmail(addr.rpartition("@")[2]):
                domains |= set(parties_for_domain(context, addr.rpartition("@")[2]))
    union = header | domains
    return (frozenset(union) if union else None), bool(header and domains and header != domains)


def wall_roles(context: dict) -> Dict[str, str]:
    """The tags that stand for the roles of the wall cases (tests/walls/cases.md)
    in a Parties table: `near` and `far`, two walled parties that share no name;
    `other`, an open party; `hat` and `hat2`, two walled parties of one name;
    `zone`, the party a zone names; `ghost`, a tag the table lacks; `knowledge`.
    A role the table has no tag for is left out."""
    parties = sorted(context.get("parties", {}))
    roles = {"ghost": "ghost-not-in-parties", "knowledge": KNOWLEDGE}
    while roles["ghost"] in parties:
        roles["ghost"] += "-x"
    walled_ = [t for t in parties if is_walled(context, t)]
    twins = [(a, b) for a in walled_ for b in walled_ if a < b and hats_of(context, [a, b])]
    plain = [t for t in walled_ if not always_asked(context, t)]
    if len(plain) >= 2:
        roles["near"], roles["far"] = plain[:2]
    open_ = [t for t in parties if not is_walled(context, t)]
    if open_:
        roles["other"] = open_[0]
    if twins:
        roles["hat"], roles["hat2"] = twins[0]
    zoned = sorted(set(context.get("zone_parties", {}).values()) & set(parties))
    if zoned:
        roles["zone"] = zoned[0]
    return roles


def run_wall_cases(context: dict, text: str) -> Tuple[int, List[str], List[str]]:
    """The decide() rows of a wall-cases file, run against a Parties table with its own tags in place of the fixture's roles. Returns (rows run,
    rows skipped because the table has no tag for a role, the rows that failed)."""
    roles = wall_roles(context)
    ran, skipped, failed = 0, [], []
    for ident, scope, labels_, action, expect, source in wall_cases(text).get("decide()", []):
        def tags(cell):
            cell = cell.strip()
            if cell in ("?", "*"):
                return None
            return set() if cell == "-" else {roles[c.strip()] for c in cell.split(",")}
        try:
            mine, theirs = (None if scope.strip() == "*" else tags(scope)), tags(labels_)
        except KeyError as missing:
            skipped.append("%s (no %s)" % (ident, missing.args[0]))
            continue
        ran += 1
        try:
            got = decide(mine, theirs, action, context)
        except ValueError:
            got = "error"
        if got != expect:
            failed.append("%s: %s on %s from %s is %s, not %s (%s)" % (ident, action, labels_, scope, got, expect, source))
    return ran, skipped, failed


def _labels_of(fm: dict, alone: bool = False) -> Optional[set]:
    """The tags a frontmatter names in `party:` and `parties:`; None when both
    are there and disagree, which reads two ways and so reads as neither."""
    one, many = tag_list(fm.get("party")), tag_list(fm.get("parties"))
    if fm.get("party") is not None and fm.get("parties") is not None and set(one) != set(many):
        return None
    return set(many or one)


def _note_labels(path: Path) -> set:
    try:
        return _labels_of(parse_frontmatter(path)) or set()
    except OSError:
        return set()


_PARTY_KEY_RE = re.compile(r"(?im)^[ \t]*[\"']?[ \t]*(?:party|parties|zone)[ \t]*[\"']?[ \t]*:")


def _party_like_key(path: Path) -> bool:
    """Does the frontmatter of a page hold a key that reads as `party`, `parties` or `zone` in any case, quoted, with
    a space before the colon or indented? Knowledge pages carry none; one that does is not published."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    if not text.startswith("---"):
        return False
    block = re.split(r"(?m)^---[ \t]*$", text, maxsplit=2)
    return bool(_PARTY_KEY_RE.search(block[1] if len(block) > 1 else text[:4000]))


def meeting_labels(fm: dict) -> Optional[frozenset]:
    """The parties a Meetings page's frontmatter names, or None when they
    cannot all be stated: a finished page has a zone and a list of `parties:`; a
    person or entity page may have its `party:` alone; `party:` and `parties:`
    that disagree read two ways, so neither."""
    got = _labels_of(fm)
    if not got:
        return None
    kind = str(fm.get("type") or "").strip().lower()
    if kind in ("person", "entity") and fm.get("parties") is None:
        return frozenset(got)
    if fm.get("zone") and isinstance(fm.get("parties"), list):
        return frozenset(got)
    return None


def labels(root: PathLike, path: PathLike, context: Optional[dict] = None,
           cache: Optional[dict] = None) -> Optional[frozenset]:
    """The parties a record is written for, derived here and nowhere else, or
    None when they cannot be derived (decide() reads None as no label).

    In this order: a Knowledge page's own `parties:` (a page with none is
    KNOWLEDGE's, read by every scope); a Meetings page's own `parties:`
    or `party:` (a finished page has a zone; a person or entity page may have
    its `party:` alone); a raw record's, the pages that cite it; a mail in an
    inbox, its `X-Garrick-Parties` header or the domains it carries; a file in
    a project, its hub's and its thread note's (a project folder, every
    thread's; a hub that names no party gives None). A record whose `party:`
    and `parties:` both exist and disagree reads two ways: None. Pass a dict
    as `cache` to derive each hub, thread note and citation index once per run.
    """
    root, path = Path(root), Path(path)
    cache = {} if cache is None else cache
    try:
        parts = (path if path.is_absolute() else root / path).relative_to(root).parts
    except ValueError:
        return None
    if any(p in ("..", "") for p in parts):
        return None
    if len(parts) >= 3 and parts[0] == "Zones":
        # a folder as the disk spells it: another case or Unicode form (Finder's NFD, an ignorecase rename) is the same one
        zone = _listed(root / "Zones", parts[1]) or parts[1]
        project = _listed(root / "Zones" / zone, parts[2]) or parts[2]
        rest = list(parts[3:])
        if len(rest) >= 2 and rest[0].casefold() == "threads":
            rest[0] = _listed(root / "Zones" / zone / project, rest[0]) or rest[0]
            rest[1] = _listed(root / "Zones" / zone / project / rest[0], rest[1]) or rest[1]
        parts = ("Zones", zone, project) + tuple(rest)
    full = root.joinpath(*parts)
    if len(parts) > 3 and parts[0] == "Wikis" and parts[2] in ("dormant", "archive"):
        parts = parts[:2] + parts[3:]       # a faded page or record is labelled as the working one it was
    if parts[:2] == ("Wikis", "Knowledge"):
        fm = parse_frontmatter(full) if full.suffix == ".md" and full.is_file() else {}
        if full.suffix == ".md" and full.is_file() and _party_like_key(full):
            return None             # a page that carries a party key in any spelling is someone's, not published
        got = _labels_of(fm)
        context = context if context is not None else load_context(root)
        none = _old_rule().LEGACY_PUBLIC if context.get("pending") is not None else KNOWLEDGE
        return None if got is None else frozenset(got or {none})
    if parts[:3] == ("Wikis", "Meetings", "wiki"):
        if full.suffix != ".md" or not full.is_file():
            return None
        return meeting_labels(parse_frontmatter(full))
    if parts[:3] == ("Wikis", "Meetings", "raw"):
        key = ("cites", str(root))
        if key not in cache:
            index: Dict[str, List[Path]] = {}
            pages = []
            for grade in ("", "dormant", "archive"):
                wiki = root / "Wikis" / "Meetings" / grade / "wiki"
                pages += sorted(wiki.rglob("*.md")) if wiki.is_dir() else []
            for page in pages:
                try:
                    text = page.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for stem in set(re.findall(r"\[\[(?:raw/)?([^\]|#]+?)(?:\.\w+)?(?:[|#][^\]]*)?\]\]", text)) | \
                        set(re.findall(r"raw/([^\s\]|#)\"']+?)(?:\.\w+)?(?=[\s\]|#)\"']|$)", text)):
                    index.setdefault(Path(stem).name.lower(), []).append(page)
            cache[key] = index
        pages = cache[key].get(full.stem.lower(), [])
        if not pages:
            return None
        out: set = set()
        for page in pages:
            got = labels(root, page, context, cache)
            if got is None:
                return None
            out |= got
        return frozenset(out)
    if len(parts) >= 3 and parts[0] == "Zones" and parts[2] != "Inbox" and not parts[2].startswith("."):
        project = root / "Zones" / parts[1] / parts[2]
        if not project.is_dir():
            return None
        context = context if context is not None else load_context(root)
        if context.get("pending") is not None:
            return _old_rule().legacy_project_labels(root, _self(), parts, cache)
        hub = ("hub", str(project))
        if hub not in cache:
            fm = parse_frontmatter(project / (project.name + ".md"))
            cache[hub] = _labels_of(fm)         # the note named after the folder, whatever its type, as the hook finds it
        found = cache[hub]
        if not found:
            return None                         # a hub that names no party labels nothing
        out = set(found)
        if len(parts) >= 5 and parts[3] == "Threads":      # a thread's file adds its thread note's parties, no other thread's
            got = _labels_of(parse_frontmatter(project / "Threads" / parts[4] / (parts[4] + ".md")))
            if got is None:
                return None
            out |= got
        context = context if context is not None else load_context(root)
        zone_party = context.get("zone_parties", {}).get(parts[1])
        return frozenset(out | ({zone_party} if zone_party else set()))
    if len(parts) >= 3 and parts[0] == "Zones" and parts[2] == "Inbox" and full.suffix.lower() == ".eml" and full.is_file():
        try:
            data = full.read_bytes()
        except OSError:
            return None
        context = context if context is not None else load_context(root)
        return mail_labels(context, data)[0]
    return None


# ---------------------------------------------------------------------------
# Meetings: the entity page a person page links
# ---------------------------------------------------------------------------
#
# A Meetings entity page may name the one party it stands for, `party: acme`,
# and a person page of that party links it as `organisation:`. Both pages are
# read on every side of a wall, so the link carries identity alone, and it is
# written only where it cannot say more than the person page's own `party:`
# says already. ingest.py writes it on a new page, check.py warns where it is
# missing or wrong, and nurture.py offers it for a page written before.

MEETINGS_ENTITIES = ("Wikis", "Meetings", "wiki", "entities")


def tag_list(value) -> List[str]:
    """A frontmatter `party:` as its tags: one, a list, or none."""
    values = value if isinstance(value, list) else [value] if value else []
    return [t for t in (strip_tag(str(v)) for v in values) if t]


ENTITY_LINK_RE = re.compile(r"^\[\[wiki/entities/((?:[^\[\]|#^/\\\n]+/)*[^\[\]|#^/\\\n]+)\]\]$")


def _listed(folder: Path, name: str) -> Optional[str]:
    """`name` as the folder lists it: the entry spelled exactly so, else the
    one entry that differs from it in case or Unicode form alone, else None.
    On a disk that ignores case (macOS) `ACME.md` opens `acme.md`; this gives
    back `acme.md`, so every comparison sees one page under one path (#330)."""
    try:
        entries = os.listdir(str(folder))
    except OSError:
        return None
    if name in entries:
        return name
    fold = unicodedata.normalize("NFC", name).casefold()
    hits = [e for e in entries if unicodedata.normalize("NFC", e).casefold() == fold]
    return hits[0] if len(hits) == 1 else None


def entity_page(root: PathLike, rel: str) -> Optional[Path]:
    """The entity page `wiki/entities/<rel>.md` of the Meetings wiki, as the
    folder spells it, whatever case `rel` is written in (_listed), or None
    when it is not there, is reached through a symbolic link at any step from
    `entities/` down, or `rel` steps out of the folder (`.`, `..`)."""
    parts = rel.split("/")
    if not rel or any(p in ("", ".", "..") for p in parts):
        return None
    path = Path(root).joinpath(*MEETINGS_ENTITIES)
    if path.is_symlink() or not path.is_dir():
        return None
    for part in parts[:-1] + [parts[-1] + ".md"]:
        name = _listed(path, part)
        if name is None:
            return None
        path = path / name
        if path.is_symlink():
            return None
    return path if path.is_file() else None


def entity_pages(root: PathLike, held: Optional[Iterable[Path]] = None) -> List[Tuple[str, Path]]:
    """(rel, path) for every entity page under the Meetings wiki's
    `wiki/entities/`, subfolders included, `rel` without `.md`. A symbolic
    link, to a page or a folder, is passed over: it may lead out of the wiki.
    `held` is the paths git holds that the disk may not (the commit hook's
    index, #340): one under `wiki/entities/` that is no longer on disk is a
    page of the commit all the same, so it is listed too."""
    folder = Path(root).joinpath(*MEETINGS_ENTITIES)
    out: List[Tuple[str, Path]] = []
    if not folder.is_dir() or folder.is_symlink():
        return out
    for here, dirs, files in os.walk(str(folder)):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(here, d)))
        for f in sorted(files):
            path = Path(here) / f
            if f.endswith(".md") and not f.startswith(".") and not path.is_symlink() and path.is_file():
                out.append((path.relative_to(folder).with_suffix("").as_posix(), path))
    seen = {rel for rel, _ in out}
    for path in sorted(held or ()):
        if folder not in path.parents or path.suffix != ".md" or path.name.startswith(".") or os.path.lexists(str(path)):
            continue
        rel = path.relative_to(folder).with_suffix("").as_posix()
        if rel not in seen and not any(part.startswith(".") for part in path.relative_to(folder).parts):
            seen.add(rel)
            out.append((rel, path))
    return out


def party_entities(root: PathLike) -> Dict[str, List[str]]:
    """{tag: [the rel of each entity page that stands for it]}, from the
    Meetings wiki's `wiki/entities/`, subfolders included. A page there
    counts when its `type:` is `entity` or missing, since the folder holds
    entity pages; it names one party in `party:`; and it carries no
    `parties:`, as Ask reads a page's `party:` alone (ask_scope.PARTY_ALONE).
    One naming several, `none` or nothing stands for no party here.
    One whose frontmatter can be read two ways (frontmatter_form_problem)
    stands for none either."""
    out: Dict[str, List[str]] = {}
    for rel, page in entity_pages(root):
        text = _page_text(page)
        fm = parse_frontmatter_text(text)
        if str(fm.get("type") or "entity").strip().lower() != "entity" or fm.get("parties") is not None \
                or frontmatter_form_problem(text):
            continue
        tags = sorted(set(tag_list(fm.get("party"))))
        if len(tags) == 1 and tags[0] != "none":
            out.setdefault(tags[0], []).append(rel)
    return out


# Letters NFKD leaves whole, folded as a reader would spell them in ASCII.
_NAME_FOLD = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "đ": "d", "ð": "d", "þ": "th",
                            "ł": "l", "ı": "i", "ħ": "h", "ŋ": "n", "ĸ": "k", "ſ": "s"})
_QUOTED = re.compile(r"[\"“”„«»(]([^\"“”„«»()]+)[\"“”„«»)]")
_SIGNS_AS = re.compile(r"\bsigns as ([^;,()\"“”]+)", re.I)


def name_words(name) -> List[str]:
    """A name's words, folded so that spellings of one name meet: NFKD, which
    turns full-width letters plain and splits accents off, the accents
    dropped, lower case, ø, æ, ß and their like spelled out, and anything
    that is not a letter or a digit a break between words."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower().translate(_NAME_FOLD)
    return re.findall(r"[a-z0-9]+", text)


# Two letters a reader writes for one: ü as ue, ö and ø as oe, ä and æ as ae,
# ß as ss. Each is folded to its first letter, on both sides of a comparison,
# so `Soeren Kjaer` meets `Søren Kjær` and `Gruen` meets `Grün` (#330).
_PAIRS = (("ae", "a"), ("oe", "o"), ("ue", "u"), ("ss", "s"))


def _fold_pairs(word: str) -> str:
    for a, b in _PAIRS:
        word = word.replace(a, b)
    return word


def _name_readings(name) -> List[List[str]]:
    """A name's words as written, and, where one comma splits it in two, read
    the other way round too, so `Whitlock, Dana` is also `Dana Whitlock`.
    Each word has its two-letter spellings of one letter folded (_PAIRS)."""
    text = str(name or "")
    out = [name_words(text)]
    head, comma, tail = text.partition(",")
    if comma and "," not in tail:
        out.append(name_words(tail) + name_words(head))
    return [[_fold_pairs(x) for x in w] for w in out if w]


def name_keys(name) -> set:
    """The keys a name is matched by, for names_meet(). Loose on purpose: it
    errs toward finding a second hat, so a page that might be one of two
    walled people links neither.

    Exact keys, which meet the same key: all its words run together, and its
    first and last words, so a middle name or initial does not keep two
    spellings apart. Then keys that meet only their partner, `<` a short form
    and `>` the full one it may stand for: a name of one word stands for any
    name opening with that word (`Eli` for `Eli Cohen`), an initial and a
    surname for a name with that initial and surname (`D. Whitlock`), and a
    first name and an initial for one with that name and last initial
    (`Dana W.`). Each reading of the name counts (_name_readings)."""
    keys = set()
    for w in _name_readings(name):
        keys.add("all:" + "".join(w))
        if len(w) == 1:
            keys.add("<first:" + w[0])
            continue
        first, last = w[0], w[-1]
        keys |= {"ends:%s|%s" % (first, last), ">first:" + first,
                 ">init:%s|%s" % (first[0], last), ">linit:%s|%s" % (first, last[0])}
        if len(first) == 1:
            keys.add("<init:%s|%s" % (first, last))
        if len(last) == 1:
            keys.add("<linit:%s|%s" % (first, last))
    return keys


def names_meet(a: set, b: set) -> bool:
    """Do two sets of name_keys() stand for one name? An exact key or a short
    form both share, or a short form in one and its full form in the other.
    Two full forms alone never meet: `David Whitlock` is not `Dana Whitlock`."""
    if any(not k.startswith(">") for k in a & b):
        return True
    turn = {"<": ">", ">": "<"}
    return any(turn[k[0]] + k[1:] in b for k in a if k[:1] in turn)


def person_forms(context: dict, row: dict) -> List[str]:
    """Every name a People row goes by: the name as written, without its
    quoted nickname, the nickname alone, a `signs as` name in the row, and
    each heard form in the Aliases table that means one of those."""
    name = str(row.get("name") or "")
    forms = [name, _QUOTED.sub(" ", name)] + _QUOTED.findall(name)
    for cell in (name, str(row.get("role") or "")):
        forms += [m.strip() for m in _SIGNS_AS.findall(cell)]
    keys = set().union(*(name_keys(f) for f in forms))
    forms += [heard for heard, means in context.get("aliases", {}).items() if names_meet(name_keys(means), keys)]
    return [f for f in forms if name_words(f)]


def people_parties(context: dict, names) -> set:
    """The tags the People table gives any of `names`, a page's title and its
    file name say, by every name each row goes by (person_forms), as
    names_meet() matches them. A row found brings every row of the same name
    with it, so a nickname or a `signs as` written on one hat's row alone
    still finds the other hat. A name that is a short form of a person under
    parties a wall keeps apart, which names_meet() does not read, brings both
    hats (_short_of_two_hats)."""
    return (_listed_parties(context, names) | _short_of_two_hats(context, names)) - {""}


def short_form_parties(context: dict, names) -> set:
    """The tags of a person under parties a wall keeps apart that `names` is
    only a short form of (_short_of_two_hats) and people_parties() would not
    have found otherwise: a page to ask about, not to link (#340)."""
    return _short_of_two_hats(context, names) - _listed_parties(context, names) - {""}


def _listed_parties(context: dict, names) -> set:
    keys = set().union(set(), *(name_keys(n) for n in ([names] if isinstance(names, str) else names)))
    if not keys:
        return set()
    rows = [(p, set().union(set(), *(name_keys(f) for f in person_forms(context, p)))) for p in context.get("people", [])]
    hit = [i for i, (_, forms) in enumerate(rows) if names_meet(keys, forms)]
    named = set().union(set(), *(name_keys(rows[i][0].get("name")) for i in hit))
    found = {strip_tag(p.get("party") or "") for i, (p, _) in enumerate(rows)
             if i in hit or names_meet(named, name_keys(p.get("name")))}
    return found - {""}


def _short_of_two_hats(context: dict, names) -> set:
    """The tags of every person the People table has under parties a wall
    keeps apart, when a page's name shares a word with their surname. Fail
    closed (#340): names are folded (case, accents, `æ`, `ø`, `ß`, punctuation)
    and split into words, and any page that holds a surname word of such a
    person, in any order, with any title, initial or note beside it (`Blake`,
    `Mr Blake`, `Blake Rowan`, `Rowan Blake (Birch)`), is read as that person:
    it links neither hat's entity page and is asked about. The one exception
    is a page whose whole folded name is another row of the People table. A
    surname is the last word of each name a row goes by (person_forms)."""
    pages = [name_words(n) for n in ([names] if isinstance(names, str) else names)]
    pages = [w for w in pages if w]
    if not pages:
        return set()
    persons: Dict[str, List[dict]] = {}
    for p in context.get("people", []):
        persons.setdefault(" ".join(name_words(p.get("name"))), []).append(p)
    out = set()
    for whole, rows in persons.items():
        tags = {strip_tag(p.get("party") or "") for p in rows} - {""}
        if not _any_wall(context, tags):
            continue
        surnames = {w[-1] for p in rows for f in person_forms(context, p) for w in [name_words(f)] if w}
        for page in pages:
            if " ".join(page) in persons and " ".join(page) != whole:
                continue                     # another row of the table, exactly
            if surnames & set(page):
                out |= tags
    return out


def organisation_link(root: PathLike, context: dict, names, party,
                      entities: Optional[Dict[str, List[str]]] = None,
                      index: Optional[List[dict]] = None) -> str:
    """The `organisation:` a person page carries by default, the entity page
    of its own party, `[[wiki/entities/<rel>]]`, or "" when it carries none.
    `names` is the person's name, or the names a page goes by (its title and
    its file name). Where a page's first line or the user says where the
    person works, organisation_proposal() and organisation_named() decide
    instead (#330); this is what holds when nothing else is known. Fail
    closed, at every step:

    - the page names exactly one party, a tag in the Parties table, not `none`;
    - where the People table has rows for the name, under any name the row
      goes by and in any short form names_meet() reads as it, one of them is
      that party, and no two of them are walled from each other: one page a
      name shares between two hats links neither hat's entity page;
    - exactly one entity page stands for that party alone;
    - no entity page that goes by the same name (name_group) names a party
      walled from it, or two parties walled from each other, names no party
      at all, or goes by a name with letters name_words() cannot read.
    """
    tags = sorted(set(tag_list(party)))
    if len(tags) != 1 or tags[0] == "none" or tags[0] not in context.get("parties", {}):
        return ""
    tag, rows = tags[0], people_parties(context, names)
    if rows and (tag not in rows or _any_wall(context, rows)):
        return ""
    pages = (party_entities(root) if entities is None else entities).get(tag, [])
    if len(pages) != 1:
        return ""
    group = name_group(entity_names(root) if index is None else index, [pages[0]])
    if _unlinkable(context, group) or _any_wall(context, {tag} | rows | entity_parties(context, group)):
        return ""
    return "[[wiki/entities/%s]]" % pages[0]


# ---------------------------------------------------------------------------
# Meetings: the entity page of where a person works (#330)
# ---------------------------------------------------------------------------
#
# A person page's `party:` names whose confidence it holds, not where the
# person works. `organisation:` names the employer's entity page, whatever
# the party: from `ingest.py person --organisation`, or proposed by Nurture
# from the page's first line, "Identity architect at Birch & Co". An entity
# page is found by its title, its `aliases:` and its file name, spelled
# loosely (org_words), and every page that goes by the same name is read
# with it: a link to one is a link to the name, so a second page under a
# variant spelling, with no `party:`, cannot carry a link past a wall that
# the first page's party would stop. A page saying `party: none` is walled
# from nobody, unless it is named after a party (entity_parties); a page
# with no `party:` at all is never linked by a tool (_unlinkable).

def org_words(name) -> List[str]:
    """An organisation's name as words spelled so that its variants meet:
    name_words() (case, accents, ø, æ, ß, full-width letters, any mark
    between words), then `and` dropped, so `&` and `and` meet, each two-letter
    spelling of one letter folded (_PAIRS), and a plural's `s`, or `ies`
    for `y`, taken off. Loose on purpose: two pages it puts under one name are
    read as one name, which errs toward a question or a wall."""
    out = []
    for w in name_words(name):
        if w == "and":
            continue
        w = _fold_pairs(w)
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 2 and w.endswith("s"):
            w = w[:-1]
        out.append(w)
    return out


def org_key(name) -> str:
    """The key two spellings of one organisation's name share: org_words()
    run together, so `Birch-Co`, `BirchCo` and `Birch & Co` meet."""
    return "".join(org_words(name))


def _as_values(value) -> List[str]:
    values = value if isinstance(value, list) else [value] if value not in (None, "") else []
    return [str(v).strip() for v in values if str(v).strip()]


def suspect_name(name) -> bool:
    """Does a name hold a letter, or an invisible mark, that name_words()
    drops rather than reads: a Cyrillic or Greek letter that looks Latin, a
    zero-width space, a soft hyphen? Such a name is matched by what is left
    of it, so it may stand for another; no tool links by it (#330)."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower().translate(_NAME_FOLD)
    return any(not ("a" <= ch <= "z" or "0" <= ch <= "9")
               and (unicodedata.category(ch)[0] == "L" or unicodedata.category(ch) == "Cf") for ch in text)


def entity_names(root: PathLike, texts: Optional[Dict[Path, str]] = None) -> List[dict]:
    """Every entity page under the Meetings wiki's `wiki/entities/`, as
    {rel, path, title, names, keys, parties, tagged, misread, suspect}: the names it
    goes by (its title, its file name, each of its `aliases:`), their
    org_key()s, every tag its `party:` or `parties:` names but `none`,
    whether it says `party:` at all (`party: none` counts), and whether one
    of its names is a suspect_name(). `texts` is what git holds for a page,
    where it differs from the disk: both are read, what either says counts,
    and it is tagged only when both say `party:` in frontmatter that cannot
    be read two ways (frontmatter_form_problem)."""
    out = []
    for rel, page in entity_pages(root, texts):
        seen = [_page_text(page)] + ([texts[page]] if texts and page in texts else [])
        views = [parse_frontmatter_text(t) for t in seen]
        names, parties, title, tagged = [Path(rel).name], set(), "", True
        # One whose frontmatter can be read two ways says whose it is to no
        # one: a link to it is refused as to a page with no `party:` (#330).
        misread = any(frontmatter_form_problem(t) for t in seen)
        tagged = not misread
        for fm in views:
            said = str(fm.get("title") or "").strip()
            title = title or said
            names += ([said] if said else []) + _as_values(fm.get("aliases")) + _as_values(fm.get("alias"))
            parties |= set(tag_list(fm.get("party"))) | set(tag_list(fm.get("parties")))
            tagged = tagged and bool(tag_list(fm.get("party")))
        keys = {org_key(n) for n in names} - {""}
        out.append({"rel": rel, "path": page, "title": title or Path(rel).name, "names": names, "keys": keys,
                    "parties": parties - {"none"}, "tagged": tagged, "misread": misread,
                    "suspect": any(suspect_name(n) for n in names)})
    return out


def name_group(index: List[dict], rels) -> List[dict]:
    """The entity pages `rels` name, and every other that goes by one of their
    names, by org_key(): what a link to any of them stands for."""
    rels = set(rels)
    keys = set().union(set(), *(e["keys"] for e in index if e["rel"] in rels))
    return [e for e in index if e["rel"] in rels or e["keys"] & keys]


_QUALIFIER = re.compile(r"[(\[]([^()\[\]]*)[)\]]")
_LEADING = ("the",)


def _party_names(context: dict, tag: str, row) -> List[Tuple[List[str], bool]]:
    """The names a party goes by, each as org_words() and whether a page
    opening with its first word is read as the party's: its cell in the
    Parties table, without its markup; every name in brackets in it, read as
    a name of its own whatever its lead word, so `**Seventh Gate**
    (product Lanternfish)` is `Seventh Gate`, `Lanternfish` and, without its
    first-word rule, `product Lanternfish`; each heard form the Aliases table
    gives for one of those; and its tag."""
    cell = str(row.get("party") if isinstance(row, dict) else row or "")
    cell = cell.replace("*", " ").replace("`", " ")
    strong = [_QUALIFIER.sub(" ", cell)]
    weak = []
    for q in _QUALIFIER.findall(cell):
        words = q.split()
        if len(words) > 1:
            weak.append(q)
            strong.append(" ".join(words[1:]))
        elif words:
            strong.append(q)
    keys = {org_key(n) for n in strong + weak} - {""}
    strong += [heard for heard, means in context.get("aliases", {}).items() if org_key(means) in keys]
    strong.append(tag.replace("-", " "))
    out = []
    for n, first in [(n, True) for n in strong] + [(n, False) for n in weak]:
        words = org_words(n)
        while words and words[0] in _LEADING:
            words = words[1:]
        if words:
            out.append((words, first))
    return out


def _named_after(name_words_: List[str], party: List[str], first: bool = True) -> bool:
    """Is a page's name, as org_words(), named after a party's: the same run
    together, holding all of the party name's words, or, where `first`,
    opening with its first word (`Acme` and `Acme Corporation` for `Acme
    Corp`)."""
    words = list(name_words_)
    while words and words[0] in _LEADING:
        words = words[1:]
    if not words:
        return False
    return ("".join(words) == "".join(party) or set(party) <= set(words) or (first and words[0] == party[0]))


def entity_parties(context: dict, group: List[dict]) -> set:
    """The parties a wall reads for a group of entity pages: each page's own
    `party:` and `parties:` tags, and, for a page naming none (`party: none`
    or no `party:` at all), every party it is named after (_named_after) by
    any name it goes by: a page called `Acme`, `The Acme Corp` or `Acme Corp
    Ltd` is Acme's whether or not it says so. A customer's page, named after
    no party, is nobody's."""
    out = set()
    named: Optional[Dict[str, List[Tuple[List[str], bool]]]] = None
    for e in group:
        if e["parties"]:
            out |= e["parties"]
            continue
        if named is None:
            named = {tag: _party_names(context, tag, row) for tag, row in context.get("parties", {}).items()}
        words = [org_words(n) for n in e["names"]]
        out |= {tag for tag, forms in named.items() if any(_named_after(w, f, first) for w in words for f, first in forms)}
    return out


def _unlinkable(context: dict, group: List[dict]) -> str:
    """Why no tool links a person page to a group of entity pages, or "": one
    of its pages says no `party:` at all, names a tag the Parties table does
    not carry, which no wall can see, or goes by a suspect_name()."""
    for e in group:
        if not e.get("tagged", True):
            return "wiki/entities/%s needs a `party:`, `none` or a party's tag, before it is linked" % e["rel"]
        if any(t not in context.get("parties", {}) for t in e["parties"]):
            return "wiki/entities/%s names a party the Parties table does not carry" % e["rel"]
        if e.get("suspect"):
            return "wiki/entities/%s goes by a name with letters no tool reads; write the link by hand" % e["rel"]
    return ""


def _any_wall(context: dict, tags: set) -> bool:
    """Do `tags` hold two walled parties? A person or a page that stands for two of them is not told apart."""
    return sum(is_walled(context, t) for t in set(tags)) > 1


def named_in(line: str, index: List[dict], every: bool = False) -> List[str]:
    """The rel of each entity page a line names, by any name it goes by, as
    org_words() spell them, word for word or run together (`Birch-Co`). A
    name inside a longer one named there gives way to it: `Acme Labs` is
    not `Acme` as well. With `every`, those that gave way too, which the
    walls read all the same."""
    words = org_words(line)
    spans = []
    for e in index:
        for key in e["keys"]:
            for i in range(len(words)):
                run = ""
                for j in range(i, len(words)):
                    run += words[j]
                    if run == key:
                        spans.append((i, j + 1, e["rel"]))
                    if not key.startswith(run):
                        break
    if every:
        return sorted({r for _, _, r in spans})
    keep = {r for a, b, r in spans
            if not any(x <= a and b <= y and y - x > b - a for x, y, _ in spans)}
    return sorted(keep)


def first_line(text: str) -> str:
    """The first line of a page's body that says something: not its
    frontmatter, a heading, a blank line, or a line in angle brackets left
    for someone to fill in."""
    if text.startswith("\ufeff"):
        text = text[1:]
    if text.startswith("---"):
        m = re.match(r"---[^\n]*\n.*?\n(?:---|\.\.\.)[^\n]*(?:\n|$)", text, re.S)
        text = text[m.end():] if m else text
    for line in text.splitlines():
        said = line.strip()
        if said and not said.startswith("#") and not (said.startswith("<") and said.endswith(">")):
            return said
    return ""


def _person_tags(context: dict, names, party) -> Optional[set]:
    """The parties a person page answers to, or None when it may link
    nothing: exactly one tag, `none` or one in the Parties table, and no two
    of it and the People table's rows for the name walled from each other."""
    tags = sorted(set(tag_list(party)))
    if len(tags) != 1 or (tags[0] != "none" and tags[0] not in context.get("parties", {})):
        return None
    every = ({tags[0]} - {"none"}) | people_parties(context, names)
    return None if _any_wall(context, every) else every


_MD_LINK = re.compile(r"^\[[^\[\]]*\]\(\s*<?([^()<>]+?)>?\s*\)$")
_WIKI_LINK = re.compile(r"^\[\[([^\[\]]+)\]\]$")
_LINKS = re.compile(r"\[\[[^\[\]]*\]\]|\[[^\[\]]*\]\([^()]*\)")


def links_in(value) -> List[str]:
    """Every link a frontmatter value holds, a wikilink or a Markdown link,
    in each string of a list too."""
    return [l for v in _as_values(value) for l in _LINKS.findall(v)]


def entity_rel(value) -> str:
    """The entity page an `organisation:` link names, as a path under
    `wiki/entities/` without `.md`, or "" when it names none there. Read
    loosely, so that a wall is checked against the page the link opens: a
    wikilink or a Markdown link, an alias, a heading or a block after it,
    `.md`, `./`, the wiki's own folders or the workspace's in front, and
    spaces round any part. A bare name is not an entity page's path."""
    text = str(value or "").strip().strip("\"'").strip()
    m = _WIKI_LINK.match(text) or _MD_LINK.match(text)
    if m:
        text = m.group(1)
    text = re.split(r"[|#^]", text, 1)[0].strip().replace("\\", "/")
    try:
        text = urllib.parse.unquote(text)
    except Exception:
        pass
    parts = [p.strip() for p in text.split("/") if p.strip() not in ("", ".")]
    lower = [p.lower() for p in parts]
    for i in range(len(lower) - 1):
        if lower[i] == "wiki" and lower[i + 1] == "entities":
            parts = parts[i + 2:]
            break
    else:
        return ""
    if parts and parts[-1].lower().endswith(".md"):
        parts[-1] = parts[-1][:-3].strip()
    return "/".join(parts) if parts and all(parts) else ""


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(str(a), str(b))
    except OSError:
        return False


def organisation_named(root: PathLike, context: dict, names, party, entity: str,
                       index: Optional[List[dict]] = None) -> Tuple[str, str]:
    """The `organisation:` for an entity the user named, as `ingest.py person
    --organisation` takes it: its file name in `wiki/entities/` (`birch-co`),
    its link, or a title or alias one page alone goes by. ("<link>", "") or
    ("", why there is none). Never an entity page made here: one not found is
    said so. Fail closed, as organisation_proposal() is, on the person's
    party, on two hats, and on the entity's name group."""
    index = entity_names(root) if index is None else index
    value = entity_rel(entity) or entity.strip()
    if not entity_rel(entity) and value.lower().endswith(".md"):
        value = value[:-3].strip()                  # `birch-co.md`: the file, named without its folder
    found = entity_page(root, value)
    page = next((e for e in index if found is not None and _same_file(e["path"], found)), None)
    if page is None:
        hits = [e for e in index if org_key(value) and org_key(value) in e["keys"]]
        if not hits:
            return "", "no entity page in wiki/entities/ goes by %s; one is written by hand, never here" % entity
        if len(hits) > 1:
            return "", "%s could be %s; name one by its file name" % (
                entity, " or ".join("wiki/entities/%s" % e["rel"] for e in hits))
        page = hits[0]
    group = name_group(index, [page["rel"]])
    why = _unlinkable(context, [page] + [e for e in group if e is not page])
    if why:
        return "", why
    every = _person_tags(context, names, party)
    if every is None:
        return "", "the page names no one known party, or the People table has the name on both sides of a wall"
    if _any_wall(context, every | entity_parties(context, group)):
        return "", "two walled parties meet between this person and that entity page"
    return "[[wiki/entities/%s]]" % page["rel"], ""


def organisation_proposal(root: PathLike, context: dict, names, party, text: str,
                          entities: Optional[Dict[str, List[str]]] = None,
                          index: Optional[List[dict]] = None) -> Tuple[str, List[str]]:
    """What a person page with no `organisation:` is offered: ("<link>", [])
    for one, ("", [rel, ...]) for the entity pages to ask between, or ("", [])
    for nothing. From the page's first line (first_line), matched against
    every entity page's names (named_in): one page, one proposal; two pages
    named, or one name two pages go by, asked about. Where the line names
    none, #319's default, the entity page of the page's party
    (organisation_link). Nothing at all, and no question, when:

    - the page names no party, several, or one not in the Parties table;
    - the People table has the name under two walled parties, or under one
      walled from the page's;
    - any entity page the line names, a shorter name inside a longer one
      included, or one going by the same name, names a party walled from the
      person's, or two walled from each other, is named after one
      (entity_parties), says no `party:` at all, or goes by a suspect_name();
    - the line itself holds a suspect_name().
    """
    every = _person_tags(context, names, party)
    if every is None:
        return "", []
    index = entity_names(root) if index is None else index
    line = first_line(text)
    if suspect_name(line):
        return "", []
    named = named_in(line, index)
    if not named:
        return organisation_link(root, context, names, party, entities, index), []
    seen = name_group(index, named_in(line, index, every=True))   # those that gave way are read too
    if _unlinkable(context, seen) or _any_wall(context, every | entity_parties(context, seen)):
        return "", []
    group = name_group(index, named)
    if len(group) == 1:
        return "[[wiki/entities/%s]]" % group[0]["rel"], []
    return "", [e["rel"] for e in group]


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
# The `(also in …)` the todo skill folds onto a line, whose sources are
# Markdown links, one level of parentheses inside it; TODO_ALSO_RE takes the
# `·` before it as well. todo.py, which stands alone, holds the same pattern,
# and tests/test_todo.py holds the two together.
_ALSO_IN = r"\(also in ((?:[^()]|\([^()]*\))*)\)"
_TASKS_ALSO_RE = re.compile(r"\s*" + _ALSO_IN)
TODO_ALSO_RE = re.compile(r"\s*·?\s*" + _ALSO_IN)


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


# A wiki's repository is `Wikis/`, or each wiki under it, and `Wikis/` may be a
# link to a folder elsewhere, so the hook cannot find the workspace by looking
# upward from where git says it is. The installer writes the workspace in: the
# hook uses it when it holds the check, looks upward when it does not, and
# refuses the commit when it finds neither (#340).
WALL_HOOK_WIKI = """#!/bin/sh
# %s: refuse a commit that would carry walled material into this wiki's history.
# Installed by Garrick. The deliberate override, only when you mean it: git commit --no-verify
top="$(git rev-parse --show-toplevel)"
real="$(cd "$top" && pwd -P)"
gitdir="$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)"
# A workspace is the right one when this repository is exactly its Wikis, or a
# wiki under it, with its own .git, and its check is not inside this repository.
ours() {
  [ -f "$1/System/tools/check.py" ] || return 1
  tools="$(cd "$1/System/tools" && pwd -P)" || return 1
  case "$tools" in "$real"|"$real"/*) return 1 ;; esac
  wikis="$(cd "$1/Wikis" 2>/dev/null && pwd -P)" || return 1
  [ "$real" = "$wikis" ] && return 0
  for wiki in "$1"/Wikis/*/; do
    case "$(basename "$wiki")" in _*|.*) continue ;; esac
    [ -d "$wiki" ] && [ "$(cd "$wiki" && pwd -P)" = "$real" ] && return 0
  done
  return 1
}
if [ -L "$real/.git" ] || [ -f "$real/.git" ]; then
  echo "Commit refused: this wiki's .git is a file or a link pointing elsewhere (a linked worktree, --separate-git-dir), not a folder inside it. Garrick checks a wiki only when its .git is a folder inside it." >&2
  exit 1
fi
if [ "$gitdir" != "$real/.git" ]; then
  echo "Commit refused: git is told to use another work tree (GIT_WORK_TREE, core.worktree), so the wall check cannot place the files. Commit from the wiki's own folder." >&2
  exit 1
fi
dir="$(dirname "$top")"
while [ "$dir" != "/" ] && ! ours "$dir"; do dir="$(dirname "$dir")"; done
if ! ours "$dir"; then
  dir=%s
  if [ -z "$dir" ] || ! ours "$dir"; then
    echo "Commit refused: no workspace found whose Wikis, or whose wiki (a folder not starting with _ or a dot), is this repository, so the wall check cannot run. Run python3 System/tools/check.py --install-hooks in the workspace, or commit with --no-verify if you mean to skip it." >&2
    exit 1
  fi
fi
exec python3 "$dir/System/tools/check.py" --root "$dir" --staged --walls-only
"""


WIKI_GIT_REASON = ("its .git is a file or a link pointing elsewhere (a linked worktree, --separate-git-dir); "
                   "Garrick checks a wiki only when its .git is a folder inside it")


def wiki_hook_text(root: Optional[PathLike] = None) -> str:
    """The wiki's pre-commit hook, with the workspace root written into it."""
    return WALL_HOOK_WIKI % (WALL_HOOK_MARK, shlex.quote(str(root)) if root else "''")


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


def install_wall_hook(zone: PathLike, nested: bool = False, wiki: bool = False,
                      root: Optional[PathLike] = None) -> Path:
    """Write the pre-commit wall check into a zone's repository, or with
    `nested` into a repository inside a project, or with `wiki` into a wiki's,
    which is told the workspace `root`, and return its path.

    Refuses (FileExistsError) to replace a pre-commit hook Garrick did not write,
    and (FileNotFoundError) a zone whose `.git` is not a folder."""
    hooks = _hooks_dir(zone)
    if wiki and (Path(zone) / ".git").exists() and (Path(zone) / ".git").is_symlink() or (
            wiki and (Path(zone) / ".git").is_file()):
        raise FileNotFoundError("%s: %s" % (zone, WIKI_GIT_REASON))
    if hooks is None:
        raise FileNotFoundError("%s is not a git repository with its own .git folder" % zone)
    hook = hooks / "pre-commit"
    if hook.exists():
        existing = hook.read_text(encoding="utf-8", errors="replace")
        if WALL_HOOK_MARK not in existing:
            raise FileExistsError("%s already has a pre-commit hook; add this line to it: "
                                  "python3 <workspace>/System/tools/check.py --staged --walls-only" % zone)
    hooks.mkdir(parents=True, exist_ok=True)
    hook.write_text(wiki_hook_text(root) if wiki else WALL_HOOK_NESTED if nested else WALL_HOOK, encoding="utf-8")
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


# Recall's indexes are a cache and its extracted sessions are private to the machine
# (#341): neither is ever committed. `.recall.sqlite*` covers the file, its journal and
# its write-ahead files.
RECALL_IGNORES = ("# Recall's search index is a cache rebuilt from the notes, and the sessions it extracts stay on this Mac.\n"
                  ".recall.sqlite*\n.sessions/\n")


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
                         + example + common + RECALL_IGNORES.replace(".sessions/", "System/.sessions/").replace(
                             ".recall.sqlite*", "System/.recall.sqlite*"),
           "Wikis/.gitignore": common + transcripts + RECALL_IGNORES}
    for zone in zones:
        out["Zones/%s/.gitignore" % zone] = common + inbox + RECALL_IGNORES
    out["/".join(ZONE_TEMPLATE + (".gitignore",))] = common + inbox + RECALL_IGNORES
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
# {"release-notice": true} lets the status page and the nightly job ask GitHub,
# at most once a day (every seven with "release-notice-every": 7), whether a newer Garrick is out. Off unless the file says true: it is the only
# call Garrick makes on its own. "release-repository" names another repository
# to ask, for a fork, as owner/name. "allowed-commands" lists the allow rules
# the installer wrote into the assistant's own settings, so an update can
# replace its own and leave the ones the user added.
RELEASE_NOTICE = "release-notice"
# How often the notice asks, in days: 1 or 7 (Settings offers Daily and Weekly).
# A missing or unreadable key means one day, so a workspace without it asks as
# it always did.
RELEASE_NOTICE_EVERY = "release-notice-every"
RELEASE_CADENCES = (1, 7)
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
# What a tool's rebuild passes as --reuse-check: it shows the check's last
# result, whatever its age, and never runs the check, which on a large
# workspace is half the build or more (#260, #382). The page says how old the
# result is. A build by hand, on schedule or by the app always runs it. The
# value is the age limit an older status.py reads; the current one ignores it.
CHECK_REUSE = float("inf")


def status_command(root: PathLike, settle: Optional[float] = None) -> Optional[List[str]]:
    """The command that builds `root`'s status page, or None where the status
    extra is not installed. It builds with the flags the last build stored
    (--same-flags), so the page keeps the app's or the plugin's flags (#246),
    and shows the check's last result, whatever its age, without running it
    (--reuse-check), where the builder knows the flag (#260). With `settle`,
    the build waits that many seconds and goes ahead only if no later one was
    asked for: a burst makes one page."""
    builder = Path(root).joinpath(*STATUS_BUILDER)
    if not builder.is_file():
        return None
    try:
        reuse = "--reuse-check" in builder.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        reuse = False
    return ([sys.executable or "python3", str(builder), "--workspace", str(root), "--same-flags"]
            + (["--reuse-check", "%g" % CHECK_REUSE] if reuse else [])
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


def release_every(root: PathLike) -> datetime.timedelta:
    """How long the release notice waits between questions: the days
    `release-notice-every` holds when they are 1 or 7, else one day."""
    days = read_settings(root).get(RELEASE_NOTICE_EVERY)
    if isinstance(days, int) and not isinstance(days, bool) and days in RELEASE_CADENCES:
        return datetime.timedelta(days=days)
    return RELEASE_EVERY


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
# (#226), so it is set by hand, and a workspace that set it keeps it;
# "graph" is Settings › Graph colours, the colour of each kind of note the
# status page's Explore draws (#291); "release-notice" and
# "release-notice-every" are Settings › About Garrick's switch and its cadence
# (#410), which release.py reads.
PREFERENCES = ("zones", "launchers", "default", "notifications", "while-you-wait", "home", "memory", "catch-up", "graph",
               "release-notice", "release-notice-every")
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


def release_asked_lately(root: PathLike, now: Optional[datetime.datetime] = None,
                         every: Optional[datetime.timedelta] = None) -> bool:
    """Whether GitHub was asked about this repository's releases within
    `every`, the last day unless said."""
    cache = read_release_cache(root)
    if cache.get("repository") != release_repository(root):
        return False
    try:
        asked = datetime.datetime.fromisoformat(str(cache.get("asked")))
    except ValueError:
        return False
    return datetime.timedelta(0) <= (now or datetime.datetime.now()) - asked < (every or RELEASE_EVERY)


def release_due(root: PathLike, now: Optional[datetime.datetime] = None) -> bool:
    """Whether the release notice should ask GitHub again: switched on, and
    not asked within its cadence (a day, or the seven `release-notice-every`
    holds)."""
    return release_notice_on(root) and not release_asked_lately(root, now, release_every(root))


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


def staged_walls_refusal(root: PathLike, repo: PathLike, paths: Optional[Iterable[str]] = None) -> str:
    """The walls check on what `repo` has staged, as its commit hook runs it
    (check.py --staged): "" when it passes, else why, as each refusing check
    and the paths it refused, and nothing of what they hold, since the reason
    is said where the far side of a wall may read it. A check that does not
    finish, or whose report cannot be read, is a refusal (#330).

    `paths`, from the top of `repo`, are what the command changed. The words,
    and only the words, then tell a wall apart from a page whose form the
    walls cannot read (FORM_PROBLEMS) and from a file staged there that the
    command did not change, another session's: each still refuses."""
    check = Path(__file__).resolve().parent / "check.py"
    try:
        r = subprocess.run([sys.executable, str(check), "--root", str(root), "--staged", "--walls-only", "--json"],
                           cwd=str(repo), capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL,
                           env=foreign_git_env())
    except subprocess.TimeoutExpired:
        return "the walls check did not finish in time, so nothing was committed; try again when the machine is less busy"
    except OSError as why:
        return "the walls check could not run (%s), so nothing was committed" % type(why).__name__
    if r.returncode == 0:
        return ""
    try:
        errors = [(str(f["check"]), str(f["path"]), str(f.get("message") or ""))
                  for f in json.loads(r.stdout)["findings"] if f.get("severity") == "error"]
    except (ValueError, KeyError, TypeError):
        return "the walls check refused it, and what it said could not be read"
    if not errors:
        return "the walls check refused it, and named no file"
    top, base = Path(repo).resolve(), Path(root).resolve()

    def from_root(name: str) -> str:
        try:
            return (top / name).relative_to(base).as_posix()
        except ValueError:
            return (top / name).as_posix()
    foreign: set = set()
    if paths is not None:
        listed = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"], cwd=str(top), capture_output=True,
                                text=True, env=foreign_git_env())
        mine = {from_root(p) for p in paths}
        foreign = {from_root(n) for n in listed.stdout.split("\0") if n} - mine if listed.returncode == 0 else set()
    kinds: Dict[str, Dict[str, List[str]]] = {}
    for check_name, path, message in errors:
        kind = "foreign" if path in foreign else "form" if message.startswith(FORM_PROBLEMS) else "wall"
        here = kinds.setdefault(kind, {}).setdefault(check_name, [])
        if path not in here:
            here.append(path)

    def where(found: Dict[str, List[str]]) -> str:
        return "; ".join("%s: %s" % (c, ", ".join(sorted(ps))) for c, ps in sorted(found.items()))
    said = {
        "wall": "the walls check refused it (%s)",
        "form": "the walls check refused it for a page's form, not for a wall: its frontmatter is not plain "
                "key: value lines, or it is a symbolic link (%s)",
        "foreign": "the walls check refused a file another session has staged, which this change did not touch (%s)",
    }
    return "; and ".join(said[k] % where(kinds[k]) for k in ("wall", "form", "foreign") if k in kinds)


class GitError(RuntimeError):
    """A git command that failed, with git's own reason."""


def own_repo_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The environment for a git process that must act on the repository in its
    own folder, never on one the caller's environment names: `env` (this
    process's own by default) without git's repository-local variables
    (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE and the rest) and without git
    settings passed through the environment (GIT_CONFIG_COUNT, every
    GIT_CONFIG_KEY_n and GIT_CONFIG_VALUE_n, GIT_CONFIG_PARAMETERS, GIT_CONFIG),
    so the repository's own hooks always run. The user's global config
    (GIT_CONFIG_GLOBAL) stays."""
    source = dict(os.environ) if env is None else dict(env)
    drop = set(git_local_env_vars()) | {"GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"}
    for name in list(source):
        if name in drop or re.match(r"GIT_CONFIG_(KEY|VALUE)_\d+$", name):
            del source[name]
    return source


def has_own_git_dir(folder: PathLike) -> bool:
    """True when git, with own_repo_env, resolves `folder`'s repository to
    `folder/.git` itself: not a parent's, not one a link or a file points away."""
    try:
        r = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=str(folder), env=own_repo_env(),
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode != 0 or not (Path(folder) / ".git").is_dir():
        return False
    # The same directory, not the same spelling: a case-insensitive disk opens
    # `work` as `Work`. Any error reading either is a refusal.
    try:
        return os.path.samefile(r.stdout.strip(), str(Path(folder) / ".git"))
    except OSError:
        return False


def wall_hook_problem(folder: PathLike) -> Optional[str]:
    """Why a commit in the zone `folder` would not run Garrick's wall check, or
    None when it would. Asks git, in the environment own_repo_env gives, which
    hooks folder it will use (`git rev-parse --git-path hooks`, which honours
    core.hooksPath from every layer of config), and wants a pre-commit there
    that is executable and holds WALL_HOOK_MARK. Fail-closed: a git that cannot
    be asked is a problem."""
    folder = Path(folder)
    if not has_own_git_dir(folder):
        return "%s has no git repository of its own here" % folder.name
    try:
        r = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=str(folder), env=own_repo_env(),
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        r = None
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return "git did not say which hooks %s would run" % folder.name
    hooks = Path(r.stdout.strip())
    hooks = hooks if hooks.is_absolute() else folder / hooks
    try:
        if WALL_HOOK_MARK in (hooks / "pre-commit").read_text(encoding="utf-8", errors="replace") \
                and os.access(hooks / "pre-commit", os.X_OK):
            return None
    except OSError:
        pass
    return "commits in %s would not run the wall check: git would take its hooks from %s" % (folder.name, hooks)


def git(args: List[str], cwd: PathLike) -> str:
    r = subprocess.run(["git"] + list(args), cwd=str(cwd), env=own_repo_env(), capture_output=True, text=True)
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
    # A new zone's repository is not a zone until its hook is in: its first commit is the one place
    # that needs only the repository to be its own.
    if not has_own_git_dir(path):
        raise GitError("%s has no repository of its own, so nothing was committed" % path)
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
        if in_fm and i > 0 and line.rstrip("\r\n") in ("---", "..."):
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
        end = next(i for i, l in enumerate(lines[1:], 1) if l in ("---", "..."))
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
