"""Shared helpers for Garrick's tools.

Standard library only, Python 3.9 or later. The checker (`check.py`),
`scaffold.py` and the installer all import this module, so the public
functions below keep their signatures:

    parse_frontmatter(path) -> dict
    is_speakable(name) -> (bool, str)
    sounds_alike(a, b) -> bool
    load_context(root) -> dict
    walled(context, tag_a, tag_b) -> bool
    workspace_root(start=None) -> Path
    install_wall_hook(zone) -> Path
    has_wall_hook(zone) -> bool
    hooks_path(repo) -> str
    skill_links(root, repo) -> [(link, target)]
    init_repo(path, message, identity=None, paths=None)
    table_row(cells) -> str
    parse_mail(path) -> dict
    mail_attachments(data) -> [(name, type, bytes)]
    parties_for_domain(context, domain) -> [tag]
    is_webmail(domain) -> bool
"""

from __future__ import annotations

import datetime
import email
import email.policy
import os
import re
import subprocess
import unicodedata
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

PathLike = Union[str, "os.PathLike[str]"]

__all__ = [
    "parse_frontmatter",
    "parse_frontmatter_text",
    "is_speakable",
    "sounds_alike",
    "normalise_name",
    "phonetic_key",
    "edit_distance",
    "load_context",
    "walled",
    "workspace_root",
    "strip_tag",
    "install_wall_hook",
    "has_wall_hook",
    "hooks_path",
    "WALL_HOOK",
    "WALL_HOOK_MARK",
    "ZONE_TEMPLATE",
    "SKILL_FOLDERS",
    "LOCAL_EMAIL",
    "GitError",
    "git",
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
# Voice: speakable names and names that sound alike
# ---------------------------------------------------------------------------

_APOSTROPHES = "'’"
_HYPHENS = "-‐‑"


def is_speakable(name: str) -> Tuple[bool, str]:
    """Is `name` fit to be a zone, project or thread name said aloud?

    Letters, spaces, hyphens, apostrophes and `&` only. No digits (dates and
    codes), no underscores, no other punctuation. Not empty, and not starting
    with `_`, which is reserved for templates.
    """
    if name is None or not name.strip():
        return False, "the name is empty"
    if name.startswith("_"):
        return False, "it starts with an underscore, which marks a template"
    if name != name.strip():
        return False, "it starts or ends with a space"
    if "  " in name:
        return False, "it has a double space"
    for ch in name:
        if ch.isalpha() or ch == " " or ch == "&" or ch in _APOSTROPHES or ch in _HYPHENS:
            continue
        if ch.isdigit():
            return False, "it contains a digit; dates and codes cannot be said cleanly"
        if ch == "_":
            return False, "it contains an underscore"
        return False, "it contains '%s', which cannot be said" % ch
    if not any(ch.isalpha() for ch in name):
        return False, "it has no letters"
    return True, ""


def normalise_name(name: str) -> str:
    """Lower-case letters only, with `&` read as "and" and accents dropped."""
    name = unicodedata.normalize("NFKD", name.replace("&", " and "))
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
        }

    Tags are lower-cased and stripped of backticks. A missing file gives
    empty collections.
    """
    ctx = {"parties": {}, "walls": set(), "people": [], "aliases": {}, "zones": {}}
    path = Path(root) / "System" / "context.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ctx
    sections = _sections(text)

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


def install_wall_hook(zone: PathLike) -> Path:
    """Write the pre-commit wall check into a zone's repository and return its path.

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
                                  "python3 ../../System/tools/check.py --staged --walls-only" % zone)
    hooks.mkdir(parents=True, exist_ok=True)
    hook.write_text(WALL_HOOK, encoding="utf-8")
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
    source = {"download": "a download", "clone": "a clone"}.get(stamp.get("from"))
    if source:
        out += ", installed from %s" % source
    if stamp.get("modified"):
        out += " with changes not committed"
    return out + "."


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
    """(name, address) pairs, address lower-cased; entries without an @ dropped."""
    out = []
    for name, addr in getaddresses([v for v in values if v]):
        addr = addr.strip().lower()
        if "@" in addr and (name, addr) not in out:
            out.append((name.strip().replace('"', ""), addr))
    return out


_HEADER_LINE_RE = re.compile(r"^\s*>?\s*(from|to|cc|bcc|date|sent|subject|reply-to|delivered-to)\s*:\s*(.*)$", re.I)
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
    """Addresses in the header block of a message forwarded inline."""
    out: List[Tuple[str, str]] = []
    for m in _FORWARD_RE.finditer(body):
        headers, _ = _header_block(body[m.end():].lstrip("\n").splitlines()[:30])
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


def strip_recipients(data: bytes) -> bytes:
    """A mail with the reader's own addresses taken out: the recipient headers
    and `Received` lines go, and every recipient address in a text part (an
    unsubscribe link, a "sent to" footer) becomes you@removed.invalid.
    Knowledge is read in every zone, so what is filed there says nothing
    about who received it. Attachments are left byte for byte."""
    m = email.message_from_bytes(data, policy=email.policy.default)
    fields = [str(v) for h in RECIPIENT_HEADERS[:-1] for v in (m.get_all(h) or [])]
    addresses = sorted({a.lower() for _, a in getaddresses(fields) if "@" in a}, key=len, reverse=True)
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
        new = text
        for a in addresses:
            for form, repl in ((a, REMOVED), (a.replace("@", "%40"), REMOVED.replace("@", "%40"))):
                new = re.sub(re.escape(form), repl, new, flags=re.IGNORECASE)
        if new != text:
            part.set_content(new, subtype=part.get_content_subtype())
    return m.as_bytes()


def mail_attachments(data: bytes) -> List[Tuple[str, str, bytes]]:
    """(name, type, contents) of every attachment in a saved `.eml` message, in
    the order the message lists them. Nothing is written anywhere."""
    msg = email.message_from_bytes(data, policy=email.policy.default)
    return [(name, ctype, payload) for _, name, ctype, payload in _attachment_parts(msg)]


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
