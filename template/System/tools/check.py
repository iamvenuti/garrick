#!/usr/bin/env python3
"""Check a Garrick workspace against every rule a machine can check.

    python3 System/tools/check.py [--root PATH] [--ear] [--json] [--quick]
    python3 System/tools/check.py --staged --walls-only      (the pre-commit hook)
    python3 System/tools/check.py --install-hooks
    python3 System/tools/check.py --version                  (which Garrick, for a bug report)

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
`--install-hooks` writes that hook into every zone's repository.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

sys.dont_write_bytecode = True  # keep System/tools free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))

from garrick_lib import (  # noqa: E402
    INBOX,
    SKILL_FOLDERS,
    VERSION_STAMP,
    MEDIA_EXTS,
    WALL_HOOK_MARK,
    has_wall_hook,
    install_wall_hook,
    is_domain,
    is_speakable,
    is_webmail,
    fingerprint,
    load_context,
    mail_attachments,
    parse_frontmatter,
    parse_frontmatter_text,
    parse_mail_bytes,
    read_version,
    say_changes,
    say_version,
    sounds_alike,
    strip_recipients,
    strip_tag,
    walled,
    workspace_root,
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
    ("links", "Links"),
    ("meetings", "Meeting pages"),
    ("people", "Person pages"),
    ("walls", "Walls"),
    ("sources", "Project sources"),
    ("inbox", "Inboxes"),
    ("knowledge", "Knowledge wiki"),
    ("raw", "Raw records"),
    ("generated", "Generated files"),
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
    "links": "{n} links cross a boundary or lead somewhere fragile",
    "meetings": "{n} things need fixing on meeting pages",
    "people": "{n} things need fixing on person pages",
    "walls": "the walls were crossed in {n} places",
    "sources": "{n} project sources came from mail that is not filed in Meetings",
    "inbox": "{n} files in the inboxes need attention",
    "knowledge": "{n} Knowledge pages carry parties or meeting material",
    "raw": "{n} raw records were changed",
    "generated": "{n} generated files could end up in the workspace history",
}

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".csv", ".tsv", ".html", ".htm", ".json", ".yaml", ".yml", ".vtt"}
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")
CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
WIKILINK_RE = re.compile(r"!?\[\[([^\[\]\n]+?)\]\]")
URI_RE = re.compile(r"obsidian://[^\s)\]>\"'`]+")
MDLINK_RE = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
DELIVERABLE_RE = re.compile(r"^(\d{2})(\d{2})(\d{2}) - \S")
MEETING_NAME_RE = re.compile(r"^\d{6}-[a-z0-9][a-z0-9-]*$")
MAX_SCAN_BYTES = 2_000_000


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
    meetings: Dict[Path, dict] = field(default_factory=dict)  # meeting page -> frontmatter
    wiki_files: List[Path] = field(default_factory=list)  # every .md under Wikis/
    quote_index: Optional["QuoteIndex"] = None  # built on first use by the walls check
    meeting_links: Optional["PathIndex"] = None  # the meeting pages, indexed for links on first use
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rel(ws: Workspace, path: Path) -> str:
    try:
        return path.relative_to(ws.root).as_posix()
    except ValueError:
        return str(path)


def nested_repo(folder: Path) -> bool:
    """A git repository of its own inside a project, such as code checked out
    beside the notes about it. The workspace's own repositories are its root,
    its zones and its wikis; anything below them with a `.git` is somebody
    else's files, not the zone's."""
    if not (folder / ".git").exists():
        return False
    return not (folder.parent.name in ("Zones", "Wikis") or folder.name == "Wikis")


# Folders no one writes in: git's own, installed packages, caches and build
# output. Skipped by name wherever the check walks, before git is asked.
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "__pycache__", "dist"})


def walk_files(top: Path, skip: Optional[set] = None) -> Iterable[Path]:
    """Every file under `top`, skipping SKIP_DIRS, nested repositories, and
    the files and folders in `skip` (see ignored)."""
    for dirpath, dirnames, filenames in os.walk(top):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not nested_repo(here / d)
                             and not (skip and here / d in skip))
        for name in sorted(filenames):
            if not (skip and here / name in skip):
                yield here / name


def read_text(path: Path) -> Optional[str]:
    """The file's text, or None when it is binary, huge or unreadable."""
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


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


GENERATED = ("System", "generated")


def is_generated(ws: Workspace, path: Path) -> bool:
    """Output a tool wrote for you, such as the status page: never committed,
    never read as material the workspace shares. Skipping it can only make a
    check stricter, so a file put there by mistake loses nothing but its
    place in git."""
    return Path(rel(ws, path)).parts[:2] == GENERATED


def is_template_path(ws: Workspace, path: Path) -> bool:
    parts = Path(rel(ws, path)).parts
    if parts[:2] == ("System", "templates"):
        return True
    # Under Zones/, a leading underscore marks a template folder (`_project`).
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

def extract_links(text: str) -> List[Tuple[str, str]]:
    """(as written, target) for every wikilink, obsidian:// URI and relative
    Markdown link in `text`. Targets are vault-relative or file-relative
    paths without the alias or heading."""
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
    for m in MDLINK_RE.finditer(text):
        target = unquote(m.group(1)).split("#", 1)[0]
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target):
            continue  # web or obsidian URI, handled above or not ours
        links.append((m.group(0), target))
    return links


def _strip_md(parts: Tuple[str, ...]) -> Tuple[str, ...]:
    if parts and parts[-1].lower().endswith(".md"):
        parts = parts[:-1] + (parts[-1][:-3],)
    return parts


class PathIndex:
    """Files a link may point at, indexed once: by the last part of each path,
    for links matched the way Obsidian matches them, and by resolved path, for
    exact ones. A link then costs the few files that share its last part, not
    a pass over every file: thousands of notes stay seconds, not minutes."""

    def __init__(self, ws: Workspace, candidates: Iterable[Path]):
        self.items = list(candidates)
        self.by_last: Dict[str, List[Tuple[Tuple[str, ...], Path]]] = {}
        for c in self.items:
            have = tuple(x.lower() for x in _strip_md(Path(rel(ws, c)).parts))
            if have:
                self.by_last.setdefault(have[-1], []).append((have, c))
        self._exact: Optional[Dict[Path, List[Tuple[int, Path]]]] = None

    def exact(self) -> Dict[Path, List[Tuple[int, Path]]]:
        """Resolved path -> (position, file); built on the first exact link."""
        if self._exact is None:
            self._exact = {}
            for i, c in enumerate(self.items):
                try:
                    self._exact.setdefault(c.resolve(), []).append((i, c))
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
    if target.startswith("/") or target.startswith("./") or target.startswith("../"):
        base = Path(target) if target.startswith("/") else source.parent / target
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
    parts = _strip_md(tuple(p for p in target.replace("\\", "/").split("/") if p and p != "."))
    if not parts:
        return []
    tries = [((vault,) + parts)] if vault else []
    tries.append(parts)
    for want in tries:
        want = tuple(x.lower() for x in want)
        hits = [c for have, c in index.by_last.get(want[-1], [])
                if len(have) >= len(want) and have[-len(want):] == want]
        if hits:
            return hits
    return []


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
        elif not isinstance(value, kind) or (kind is list and not all(isinstance(v, str) for v in value)):
            problems.append("`%s` should be %s" % (key, "a list of names" if kind is list else "an object"))
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
    for key in ("retired-skills", "raw-accepted"):
        for name, value in ws.settings.get(key, {}).items():
            if not isinstance(value, str) or not value.strip():
                out.append(Finding(WARNING, "settings", r, "`%s` gives %s no value" % (key, name),
                                   "A line in the check settings has no value"))
    return out


def setting_zones(ws: Workspace, key: str) -> List[Path]:
    names = set(ws.settings.get(key, []))
    return [z for z in ws.zones if z.name in names]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover(root: Path) -> Workspace:
    ws = Workspace(root=root, context=load_context(root))
    ws.settings, ws.settings_problems = load_settings(root)
    ws.zones = visible_dirs(root / "Zones")
    for zone in ws.zones:
        for project in project_dirs(zone):
            ws.projects.append((project, parse_frontmatter(project / (project.name + ".md"))))
    # A project about the workspace itself may live in System/, in no zone.
    for folder in visible_dirs(root / "System"):
        fm = parse_frontmatter(folder / (folder.name + ".md"))
        if fm.get("type") == "project":
            ws.projects.append((folder, fm))
    wikis = root / "Wikis"
    if wikis.is_dir():
        for path in walk_files(wikis):
            if path.suffix.lower() == ".md":
                ws.wiki_files.append(path)
    sources = wikis / "Meetings" / "wiki" / "sources"
    if sources.is_dir():
        for page in sorted(sources.rglob("*.md")):
            ws.meetings[page] = parse_frontmatter(page)
    return ws


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
WORD_BUDGET_ROOT = 800
WORD_BUDGET_OTHER = 1000
COPY_MIN_CHARS = 80


def instruction_files(ws: Workspace) -> List[Path]:
    files = [ws.root / p for p in ROOT_INSTRUCTIONS]
    files += [z / "AGENTS.md" for z in ws.zones]
    files += [ws.root / "Wikis" / "AGENTS.md"]
    wikis = ws.root / "Wikis"
    if wikis.is_dir():
        files += sorted(w / "AGENTS.md" for w in wikis.iterdir() if w.is_dir() and not w.name.startswith("."))
    return [f for f in files if f.is_file()]


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
        if f.name != "AGENTS.md":
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
    # The same sentence in two files, one of them at the root: one is a copy.
    # Zone and wiki files may share boilerplate, since each stands alone in its own repository.
    root_files = {ws.root / p for p in ROOT_INSTRUCTIONS} | {ws.root / "Wikis" / "AGENTS.md"}
    seen: Dict[str, set] = {}
    for f, text in texts.items():
        for line in text.splitlines():
            norm = re.sub(r"\s+", " ", re.sub(r"^\s*(?:[-*>]|\d+\.)\s*", "", line)).strip().lower()
            if len(norm) >= COPY_MIN_CHARS and not norm.startswith(("|", "```")):
                seen.setdefault(norm, set()).add(f)
    for norm, where in sorted(seen.items()):
        if len(where) > 1 and where & root_files:
            names = " and ".join(sorted(rel(ws, w) for w in where))
            out.append(Finding(WARNING, "instructions", names,
                               "the same text in both: \"%s…\"; keep it in one and point from the other" % norm[:60],
                               "Two instruction files say the same thing"))
    # A file that names several skills names every one of them.
    skills = {p.parent.name for p in (ws.root / "System" / "skills").glob("*/SKILL.md")}
    for f, text in texts.items():
        named = {s for s in skills if "`%s`" % s in text}
        if len(named) >= 3 and named != skills:
            out.append(Finding(WARNING, "instructions", rel(ws, f),
                               "lists skills but not %s; list the folder instead of naming them" % ", ".join(sorted(skills - named)),
                               "An instruction file lists skills that no longer match the folder"))
    # A zone's AGENTS.md that names its projects' hub notes names every one
    # of them, and only notes that exist.
    for zone in ws.zones:
        f = zone / "AGENTS.md"
        text = texts.get(f)
        if not text:
            continue
        projects = [p.name for p in project_dirs(zone) if (p / (p.name + ".md")).is_file()]
        listed = re.findall(r"`([^`/]+)/[^`]*\.md`", text)
        if not any(name in projects for name in listed):
            continue  # this zone keeps no list of its projects
        for name in projects:
            if name not in listed:
                out.append(Finding(WARNING, "instructions", rel(ws, f),
                                   "lists project hub notes but not %s/%s.md; list the folder instead of naming them" % (name, name),
                                   "The %s instructions list projects that no longer match the folder" % zone.name))
        for m in re.finditer(r"`([^`/]+/[^`]*\.md)`", text):
            path = m.group(1)
            if path.split("/")[0] in {"..", "System", "Zones", "Wikis"} | {z.name for z in ws.zones}:
                continue  # a path from another folder, not one of this zone's notes
            if not (zone / path).exists():
                out.append(Finding(WARNING, "instructions", rel(ws, f), "lists %s, which does not exist" % path,
                                   "The %s instructions name a note that is not there" % zone.name))
    return out


def check_placeholders(ws: Workspace) -> List[Finding]:
    """Installer placeholders left unfilled, in a file's name or its text.
    Files git ignores are not the install's: a package's own templates may
    hold the same marks."""
    out = []
    for path in walk_files(ws.root, ignored(ws)):
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


def check_context(ws: Workspace) -> List[Finding]:
    out = []
    ctx_path = "System/context.md"
    if not (ws.root / ctx_path).is_file():
        return [Finding(ERROR, "context", ctx_path, "missing; walls and aliases cannot be read", "The context file is missing")]
    parties = ws.context["parties"]
    if not parties:
        out.append(Finding(WARNING, "context", ctx_path, "the Parties table is empty; no wall can be checked",
                           "The Parties table is empty"))
    for wall in sorted(ws.context["walls"], key=sorted):
        for tag in sorted(wall):
            if tag not in parties:
                out.append(Finding(ERROR, "context", ctx_path,
                                   "the Walls table names `%s`, which is not a tag in Parties" % tag,
                                   "The walls table names an unknown party"))
    if any(len(w) == 1 for w in ws.context["walls"]):
        out.append(Finding(WARNING, "context", ctx_path, "a wall names the same tag on both sides",
                           "A wall in the context file names one party twice"))
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
    listed = set(ws.context["zones"])
    for zone in ws.zones:
        if listed and zone.name not in listed:
            out.append(Finding(WARNING, "context", ctx_path, "zone %s is not in the Zones table" % zone.name,
                               "The %s zone is missing from the context file" % zone.name))
    # One name, two tags: the same organisation in two roles. Saying its name
    # never says which, so only a wall keeps the two apart in writing.
    by_name: Dict[str, List[str]] = {}
    for tag, entry in sorted(parties.items()):
        key = " ".join(words(entry.get("party") or ""))
        if key:
            by_name.setdefault(key, []).append(tag)
    for tags in by_name.values():
        for i, a in enumerate(tags):
            for b in tags[i + 1:]:
                if not walled(ws.context, a, b):
                    name = parties[a].get("party") or a
                    out.append(Finding(WARNING, "context", ctx_path,
                                       "`%s` and `%s` are both %s, with no wall between them; add one, or the name "
                                       "alone can carry one role's material into the other's" % (a, b, name.strip("* ")),
                                       "Two parties share a name and no wall"))
    text = read_text(ws.root / ctx_path) or ""
    if not re.search(r"(?m)^## Aliases\s*$", text):
        out.append(Finding(WARNING, "context", ctx_path,
                           "no `## Aliases` table (| Heard | Means |); names that arrive mangled by dictation have nothing to match",
                           "The context file has no aliases table"))
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
    return out


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
            if is_zone and WALL_HOOK_MARK in hook.read_text(encoding="utf-8", errors="replace") and os.access(hook, os.X_OK):
                continue  # the folder it names runs the wall check too
        except OSError:
            pass
        what = "the wall check in its .git/hooks" if is_zone else "any hook in its own .git/hooks"
        out.append(Finding(WARNING, "hooks", rel(ws, repo),
                           "git takes its hooks from %s (core.hooksPath), so %s never runs before a commit; "
                           "run `git config core.hooksPath .git/hooks` in %s" % (value, what, rel(ws, repo)),
                           ("Git skips the wall check in the %s zone" % repo.name) if is_zone
                           else "Git skips the hooks of the %s repository" % repo.name))
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
        live = [ws.root / p for p in ROOT_INSTRUCTIONS] + [z / "AGENTS.md" for z in ws.zones]
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
    for folder in folders:
        ok, why = is_speakable(folder.name)
        if not ok:
            out.append(Finding(ERROR, "names", rel(ws, folder), "%s name is not speakable: %s" % (level, why),
                               "The %s name %s cannot be said cleanly" % (level, folder.name)))
    for i, a in enumerate(folders):
        for b in folders[i + 1:]:
            if sounds_alike(a.name, b.name):
                out.append(Finding(WARNING, "names", rel(ws, a.parent),
                                   "%ss \"%s\" and \"%s\" sound alike" % (level, a.name, b.name),
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
            out.append(Finding(WARNING, "projects", r, "no `party`; it cannot draw on the Meetings wiki until it has one",
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
            if ttags and ptags and ttags != ptags:
                out.append(Finding(WARNING, "threads", r,
                                   "`party` %s differs from the project's %s" % (", ".join(sorted(ttags)), ", ".join(sorted(ptags))),
                                   "Thread %s names a different party from its project" % spoken))
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
RESUME_PROMPT_RE = re.compile(r"^\s*\|\s*(Live artifact|Rebuild with|Next action|Waiting on|Deadline)\s*\|\s*<")
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
    # Where a relative path may start: the note's folder and those above it
    # in the project, the project's own folders, the zone, the workspace, the
    # wikis and the skills.
    bases, d = [], note.parent
    while d == project or project in d.parents:
        bases.append(d)
        d = d.parent
    bases += [x for x in visible_dirs(project) if x not in bases]
    bases += [project.parent, ws.root / "Zones", ws.root, ws.root / "Wikis"] + visible_dirs(ws.root / "Wikis")
    bases += [ws.root / "System" / "skills"]
    inside: Optional[List[str]] = None  # the project's files, listed on the first path not found
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
        for m in TICK_RE.finditer(line):
            path = m.group(1).strip()
            if (path.startswith(("<", "/tmp/", "/private/", "/var/")) or "://" in path or "*" in path
                    or COMMAND_RE.match(path) or OFFICE_PART_RE.match(path) or not PATHLIKE_RE.match(path)
                    or "/" not in path.rstrip("/")):
                continue
            if path.startswith(("~", "/")):
                found = Path(path).expanduser().exists()
            else:
                found = any((b / path).exists() for b in bases)
                if not found:
                    # Relative to a folder the block names elsewhere: any file
                    # in the project whose path ends the same way.
                    if inside is None:
                        inside = ["/" + f.relative_to(project).as_posix() for f in walk_files(project)]
                    tail = "/" + path.strip("./").rstrip("/")
                    found = any(f.endswith(tail) or (path.endswith("/") and tail + "/" in f) for f in inside)
            if not found and (shared or SHARE_RE.search(line)):
                continue  # on a shared drive, which the check does not read
            if not found:
                out.append(Finding(WARNING, "resume", rel(ws, note),
                                   "Resume here names `%s`, which is not there" % path,
                                   "Thread %s names a file that is not there" % spoken))
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
    way, and a resume point that work has left behind is reported."""
    out = []
    files: List[Optional[PathIndex]] = [None]  # every file in the workspace, indexed on the first link
    for project, pfm in ws.projects:
        hub = project / (project.name + ".md")
        if not hub.is_file() or not live_status(pfm):
            continue  # finished, or set aside: nobody resumes it until it is woken
        shared = bool(str(pfm.get("share") or "").strip())
        holding = [hub]
        block = resume_block(read_text(hub) or "")
        if block:
            out += resume_findings(ws, project, hub, block, project.name, files, shared)
        for thread in visible_dirs(project / "Threads"):
            note = thread / (thread.name + ".md")
            text = read_text(note) if note.is_file() else None
            if not text:
                continue
            block = resume_block(text)
            if block:
                holding.append(note)
            if not live_status(parse_frontmatter(note)):
                continue
            out += resume_findings(ws, project, note, block, "%s, %s" % (project.name, thread.name), files, shared)
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
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError):
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
TASKS_FIELD_RE = re.compile(r"(?:\s*(?:[🔺⏫🔼🔽⏬]\uFE0F?|(?:📅|📆|🗓|⏳|⌛|🛫|➕|✅|❌)\uFE0F? *\d{4}-\d{2}-\d{2}|#[^\s#]+))$")
TASKS_DATE_RE = re.compile(r"(?:📅|📆|🗓|⏳|⌛|🛫|➕)\uFE0F? *\d{4}-\d{2}-\d{2}")
INBOX_GROWTH = 20  # open actions added to a list's Inbox in a week, past which triage is not keeping up


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


def check_todo(ws: Workspace) -> List[Finding]:
    """Each zone's Todo.md: an open action that opens with a thread's link
    leads to a live note; its dates come last, where Obsidian Tasks reads them;
    the Inbox does not grow by more than INBOX_GROWTH in a week. In a zone the
    check settings name under `todo-labels`, every open action opens with
    its thread's link."""
    out = []
    strict = set(setting_zones(ws, "todo-labels"))
    for zone in ws.zones:
        todo = zone / "Todo.md"
        text = read_text(todo) if todo.is_file() else None
        if text is None:
            continue
        r = rel(ws, todo)
        open_lines = [l for l in text.splitlines() if l.startswith("- [ ] ")]
        stems = {p.stem.lower() for p, _ in zone_notes(ws, zone)}
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
        unread = sum(1 for l in open_lines if TASKS_DATE_RE.search(tasks_description(l)))
        if unread:
            out.append(Finding(WARNING, "todo", r,
                               "%d open action%s a date with text after it, which Obsidian Tasks does not read; "
                               "put the dates last" % (unread, " has" if unread == 1 else "s have"),
                               "Some actions in %s have a date that is not read" % zone.name))
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

# Folders whose notes no longer count as live: archives, build output, specs,
# hidden and template folders.
NOT_LIVE_DIR_RE = re.compile(r"^(?:archive|build|render.*|specs|\..*|_.*)$", re.I)
CLOUD_PATH_RE = re.compile(r"Library/CloudStorage/")
TICKED_NOTE_RE = re.compile(r"(?<!`)`([^`\n*~/][^`\n*]*?\.md)`(?!`)")


def live_files(folder: Path) -> Iterable[Path]:
    """Every file under `folder` outside archives, build output, hidden and
    template folders, and any repository of its own kept inside a project,
    such as a program's code: its files are not notes."""
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames
                             if not NOT_LIVE_DIR_RE.match(d) and not os.path.lexists(os.path.join(dirpath, d, ".git")))
        for name in sorted(filenames):
            yield Path(dirpath) / name


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
    others = [p for p in ws.wiki_files if "raw" not in Path(rel(ws, p)).parts[:3] and p != registry / "index.md"]
    others += [ws.root / p for p in ROOT_INSTRUCTIONS if (ws.root / p).is_file()]
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


def parent_links(ws: Workspace, zone: Path) -> List[Finding]:
    """Every live note in a project, other than its hub, carries `parent:`, a
    link to its thread note or hub that leads to a live note, so the graph
    attaches it to its project whatever its prose says."""
    out = []
    notes = zone_notes(ws, zone)
    stems = {p.stem for p, _ in notes}
    for path, text in notes:
        parts = path.relative_to(zone).parts
        if len(parts) < 2 or not (zone / parts[0] / (parts[0] + ".md")).is_file() or path == zone / parts[0] / (parts[0] + ".md"):
            continue  # loose in the zone, outside any project, or the hub itself
        m = PARENT_RE.search(parse_frontmatter_block(text))
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


def check_meetings(ws: Workspace) -> List[Finding]:
    out = []
    zone_names = {z.name for z in ws.zones} | set(ws.context["zones"])
    for page, fm in ws.meetings.items():
        r = rel(ws, page)
        zone = fm.get("zone")
        tags = [strip_tag(t) for t in as_list(fm.get("parties"))]
        missing = [k for k, v in (("zone", zone), ("parties", tags)) if not v]
        if missing:
            out.append(Finding(WARNING, "meetings", r,
                               "unfinished: no %s; nothing on it may be used in a project" % " or ".join(missing),
                               "One meeting page has no %s" % " or ".join(missing)))
        if zone and zone_names and zone not in zone_names:
            out.append(Finding(WARNING, "meetings", r, "`zone` %s is not a zone" % zone,
                               "A meeting page names an unknown zone"))
        for tag in tags:
            if tag not in ws.context["parties"]:
                out.append(Finding(ERROR, "meetings", r,
                                   "party `%s` is not a tag in the Parties table, so no wall can see it" % tag,
                                   "A meeting page names an unknown party"))
        both = sorted(sorted(w) for w in ws.context["walls"] if len(w) == 2 and w <= set(tags))
        if both:
            out.append(Finding(WARNING, "meetings", r,
                               "names both %s and %s, which a wall keeps apart, so no project of either may use it; "
                               "if it was two conversations, file them as two pages" % tuple(both[0]),
                               "A meeting page sits on both sides of a wall"))
        if fm and fm.get("type") not in (None, "meeting", "email"):
            out.append(Finding(WARNING, "meetings", r, "`type` is %r, should be meeting or email" % fm.get("type"),
                                   "A meeting page is not marked as a meeting"))
        if not MEETING_NAME_RE.match(page.stem):
            out.append(Finding(WARNING, "meetings", r, "file name should be `YYMMDD-slug.md`",
                                   "A meeting page is misnamed"))
        for problem in bad_dates(fm):
            out.append(Finding(ERROR, "meetings", r, problem, "A meeting page has a date in the wrong form"))
    out += cited_across_walls(ws)
    return out


def cited_across_walls(ws: Workspace) -> List[Finding]:
    """A page of the Meetings wiki written for one party, such as a person or
    an organisation it keeps a page on, with `party` in its frontmatter,
    cites no meeting walled from that party. One organisation in two roles
    gets one page per role, and a meeting cited by both would make the two
    one history."""
    out = []
    wiki = ws.root / "Wikis" / "Meetings" / "wiki"
    sources = wiki / "sources"
    if ws.meeting_links is None:
        ws.meeting_links = PathIndex(ws, ws.meetings)
    for page in ws.wiki_files:
        if wiki not in page.parents or sources in page.parents or page.parent == wiki:
            continue
        text = read_text(page) or ""
        tags = {strip_tag(t) for t in as_list(parse_frontmatter_text(text).get("party"))} - {"none"}
        if not tags:
            continue
        for written, target in extract_links(text):
            hits = [m for m in resolve(ws, page, target, ws.meeting_links)
                    for a in tags for b in as_list(ws.meetings[m].get("parties")) if walled(ws.context, a, strip_tag(b))]
            if hits:
                b = next(strip_tag(t) for t in as_list(ws.meetings[hits[0]].get("parties"))
                         if any(walled(ws.context, a, strip_tag(t)) for a in tags))
                out.append(Finding(WARNING, "meetings", rel(ws, page),
                                   "cites %s, a meeting with %s, but is written for %s, across a wall"
                                   % (hits[0].stem, b, ", ".join(sorted(tags))),
                                   "A page for one party cites a meeting across a wall"))
                break
    return out


PEOPLE = ("Wikis", "Meetings", "wiki", "people")


def check_people(ws: Workspace) -> List[Finding]:
    """A person page is read on both sides of every wall. It says who someone
    is and which party they belong to, and holds nothing learned in a meeting."""
    out = []
    folder = ws.root.joinpath(*PEOPLE)
    if not folder.is_dir():
        return out
    common = None
    for page in sorted(folder.rglob("*.md")):
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
        if ws.quick:
            continue
        if common is None:
            common = quote_index(ws).common
        heard = meeting_wording(ws, body_of(text), common, page)
        if heard:
            more = " and %d more" % (len(heard) - 1) if len(heard) > 1 else ""
            out.append(Finding(WARNING, "people", r,
                               "repeats eight or more words from meeting %s%s; a person page is read on both sides of "
                               "every wall, so it says who they are and nothing learned in a meeting" % (heard[0].stem, more),
                               "The page for %s repeats what was said in a meeting" % name))
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
        m = re.match(r"---[^\n]*\n.*?\n(?:---|\.\.\.)[^\n]*(?:\n|$)", text, re.S)
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
        if line.strip() in ("---", "..."):
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


def shingles(tokens: List[str]) -> Iterable[int]:
    """A hash for each run of SHINGLE words that carries enough content words."""
    content = [is_content(t) for t in tokens]
    for i in range(len(tokens) - SHINGLE + 1):
        if sum(content[i:i + SHINGLE]) >= MIN_CONTENT_WORDS:
            yield hash(tuple(tokens[i:i + SHINGLE]))


HEADING_RE = re.compile(r"(?m)^ {0,3}#{1,6}[ \t].*$")
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
    here"), and the words either side of one were not written as one sentence."""
    text = without_link_targets(text, shared)
    out: set = set()
    last = 0
    for m in HEADING_RE.finditer(text):
        out.update(shingles(words(text[last:m.start()])))
        out.update(shingles(words(m.group(0))))
        last = m.end()
    out.update(shingles(words(text[last:])))
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
SHARED_FILES = ("AGENTS.md", "Wikis/AGENTS.md", "Wikis/Meetings/AGENTS.md", "System/rules.md", "System/context.md")
SHARED_FOLDERS = ("System/skills", "System/templates", "System/tools", "Wikis/Knowledge")


def shared_files(ws: Workspace) -> List[Path]:
    """Every shared file that exists: SHARED_FILES, and all under SHARED_FOLDERS."""
    out = [ws.root / name for name in SHARED_FILES]
    for name in SHARED_FOLDERS:
        folder = ws.root / name
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


def meeting_raws(ws: Workspace, page: Path, fm: dict) -> List[Path]:
    """The raw transcripts behind a meeting page: the one its `raw` field names,
    else any file in raw/ with the page's slug. The inbox is not yet filed. In
    staged mode, a record deleted from disk but still in git counts too."""
    raw = ws.root / "Wikis" / "Meetings" / "raw"
    stems = {page.stem}
    for value in as_list(fm.get("raw")):
        stems.add(Path(value.strip("[]").split("|", 1)[0]).stem)
    found = {p for p in raw.iterdir() if p.is_file() and p.stem in stems} if raw.is_dir() else set()
    found |= {p for p in ws.git_view if p.parent == raw and p.stem in stems}
    return sorted(found)


def finished(fm: dict) -> bool:
    """A meeting page with both of the fields the walls read."""
    return bool(fm.get("zone")) and bool(as_list(fm.get("parties")))


def quote_index(ws: Workspace) -> QuoteIndex:
    if ws.quote_index is not None:
        return ws.quote_index
    owners: Dict[int, set] = {}

    def add(text: str, owner: Path, source: Path) -> None:
        for h in runs(text, shared_link(ws, source)):
            owners.setdefault(h, set()).add(owner)

    # In staged mode a file can hold one text on disk and another in git (see
    # git_view): both count as where its wording was said or written.
    view = ws.git_view

    def texts(path: Path) -> List[str]:
        out = [read_text(path) or ""] if path.exists() else []
        if path in view:
            out.append(view[path])
        return out

    # Every meeting page and its raw record, finished or not: nothing on an
    # unfinished page may be used anywhere until it has its zone and parties.
    for page, fm in ws.meetings.items():
        for text in texts(page):
            add(body_of(text), page, page)
        for r in meeting_raws(ws, page, fm):
            for text in texts(r):
                add(transcript_text(r, text), page, r)
    # Every project's own text files, under the party each is written for: a
    # client's brief or data file, and the notes made from them, are that
    # party's material as much as its meetings are. Template folders are not.
    tags: Dict[Path, frozenset] = {}
    projects: Dict[Path, Path] = {}
    for project, pfm in ws.projects:
        ptags = party_tags(ws, project / (project.name + ".md"), pfm)
        thread_tags: Dict[str, set] = {}
        files = list(walk_files(project, ignored(ws)))
        files += sorted(p for p in view if project in p.parents and not p.exists())  # deleted, but still in git
        for path in files:
            if path.suffix.lower() not in TEXT_SUFFIXES or is_template_path(ws, path):
                continue
            found = [t for t in texts(path) if t]
            if not found:
                continue
            parts = path.relative_to(project).parts
            ftags = set(ptags)
            if len(parts) > 2 and parts[0] == "Threads":
                if parts[1] not in thread_tags:
                    note = project / "Threads" / parts[1] / (parts[1] + ".md")
                    thread_tags[parts[1]] = party_tags(ws, note)
                ftags |= thread_tags[parts[1]]
            tags[path] = frozenset(ftags)
            projects[path] = project
            for text in found:
                add(body_of(transcript_text(path, text)), path, path)
    common: set = set()
    beyond: set = set()
    # Wording also found in a shared file is common wording, not a leak. No
    # other file counts, however widely it is read: see SHARED_FILES. A shared
    # file whose working copy differs from git counts only for the wording both
    # versions hold, so an edit left unstaged cannot make a quotation common.
    knowledge = ws.root / "Wikis" / "Knowledge"
    for path in shared_files(ws):
        if path.suffix.lower() in TEXT_SUFFIXES or path.suffix.lower() == ".eml":
            link = shared_link(ws, path)
            found = {h for h in runs(transcript_text(path, read_text(path) or ""), link) if h in owners}
            if path in view:
                found &= runs(transcript_text(path, view[path]), link)
            common |= found
            if knowledge not in path.parents:
                beyond |= found
    ws.quote_index = QuoteIndex(owners, common, beyond, tags, projects)
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
    the wall is dropped: it cannot tell the two apart.
    """
    key = frozenset(walled_tags)
    if key not in ws.forms:
        ws.forms[key] = _name_forms(ws, walled_tags)
    return ws.forms[key]


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
    near_side = set()
    for tag in forms:
        if tag not in walled_tags:
            near_side |= forms[tag] | {f.lower() for f in firsts[tag]}
    out: Dict[str, List[Tuple[bool, str]]] = {}
    for tag in sorted(walled_tags):
        if tag not in forms:
            continue
        found = [(False, f) for f in sorted(forms[tag]) if f not in near_side]
        found += [(True, f) for f in sorted(firsts[tag]) if f.lower() not in near_side and f.lower() not in forms[tag]]
        out[tag] = found
    return out


def padded_words(text: str) -> str:
    """`text` as its words, with a space either side, for names_hit."""
    return " %s " % " ".join(words(text))


def names_hit(text: str, forms: List[Tuple[bool, str]], padded: Optional[str] = None) -> bool:
    """Does `text` hold one of `forms`? `padded` is padded_words(text), when
    the caller has it already."""
    if padded is None:
        padded = padded_words(text)
    for case_sensitive, form in forms:
        if case_sensitive:
            if re.search(r"(?<![\w])%s(?![\w])" % re.escape(form), text):
                return True
        elif " %s " % form in padded:
            return True
    return False


def party_tags(ws: Workspace, note: Path, fm: Optional[dict] = None) -> set:
    """The party tags a hub or thread note declares. In staged mode, where git
    holds another version of the note, the tags of both: the more parties a
    file belongs to, the more walls stand around its wording."""
    tags = {strip_tag(t) for t in as_list((parse_frontmatter(note) if fm is None else fm).get("party"))}
    if note in ws.git_view:
        tags |= {strip_tag(t) for t in as_list(parse_frontmatter_text(ws.git_view[note]).get("party"))}
    return tags


def file_tags(ws: Workspace, project: Path, ptags: set, path: Path) -> Tuple[set, str]:
    """The party tags a project file is written for, and how to say where it is."""
    tags = set(ptags)
    parts = Path(rel(ws, path)).parts
    where = project.name
    if len(parts) > 5 and parts[3] == "Threads":
        thread = parts[4]
        note = project / "Threads" / thread / (thread + ".md")
        tags |= {strip_tag(t) for t in as_list(parse_frontmatter(note).get("party"))}
        where = "%s's %s thread" % (project.name, thread)
    return tags, where


def walls_for_file(ws: Workspace, project: Path, ptags: set, path: Path, text: str) -> List[Finding]:
    """Every walls finding for one project file, whose text is `text`."""
    out: List[Finding] = []
    if ws.meeting_links is None:
        ws.meeting_links = PathIndex(ws, ws.meetings)
    meetings = ws.meeting_links
    tags, where = file_tags(ws, project, ptags, path)
    r = rel(ws, path)
    zone = project.parent.name
    reported: set = set()  # walled parties and meetings already named for this file

    # Links.
    seen = set()
    for written, target in extract_links(text) if meetings.items else []:
        for page in resolve(ws, path, target, meetings):
            key = (written, page)
            if key in seen:
                continue
            seen.add(key)
            mfm = ws.meetings[page]
            mtags = [strip_tag(t) for t in as_list(mfm.get("parties"))]
            if not mtags or not mfm.get("zone"):
                reported.add(page)
                out.append(Finding(ERROR, "walls", r,
                                   "uses %s, an unfinished meeting page (no zone or parties)" % page.stem,
                                   "A note in %s uses an unfinished meeting page" % where))
                continue
            if not tags:
                out.append(Finding(ERROR, "walls", r,
                                   "uses meeting %s, but the project has no party to check the walls against" % page.stem,
                                   "A note in %s uses a meeting before the project has a party" % where))
                continue
            hits = sorted((a, b) for a in tags for b in mtags if walled(ws.context, a, b))
            if hits:
                a, b = hits[0]
                reported |= {b, page}
                out.append(Finding(ERROR, "walls", r,
                                   "links %s, a meeting with %s; a wall stands between %s and %s" % (written, b, a, b),
                                   "A note in %s uses a meeting with %s" % (where, party_name(ws, b))))
            elif mfm.get("zone") != zone:
                out.append(Finding(WARNING, "walls", r,
                                   "uses meeting %s from zone %s; cross-zone work happens only when asked" % (page.stem, mfm.get("zone")),
                                   "A note in %s uses a meeting from the %s zone" % (where, mfm.get("zone"))))
    far = {t for t in ws.context["parties"] if any(walled(ws.context, a, t) for a in tags)}

    # Names. Sources/ holds what a party sent, which may name anyone; it is exempt.
    in_sources = "Sources" in Path(rel(ws, path)).parts[3:-1]
    if far and not in_sources:
        scanned = without_party_field(text) + "\n" + path.name
        padded = padded_words(scanned)
        for b, forms in name_forms(ws, far).items():
            if b in reported or not forms or not names_hit(scanned, forms, padded):
                continue
            a = sorted(t for t in tags if walled(ws.context, t, b))[0]
            reported.add(b)
            out.append(Finding(ERROR, "walls", r,
                               "names %s, or one of its people; a wall stands between %s and %s" % (party_name(ws, b), a, b),
                               "A note in %s names %s" % (where, party_name(ws, b))))

    # Quotes: a run of words held only across a wall, by a meeting page or its
    # raw record or by another project's file, or held by an unfinished page.
    # Wording also held on the near side of the wall, by a meeting or a file
    # of another project, or by this project's own Sources/, is not evidence of
    # a leak, and nor is wording found in one of the shared files every side
    # reads. This project's own notes are neither: a leak copied twice must
    # not vouch for itself. A file in Sources/ is what a party sent, which may
    # repeat what another party sent too: like the name check, the file check
    # leaves it out, and only meetings count against it.
    if ws.quick:
        return out  # --quick leaves the wording to the full check and the commit hook
    index = quote_index(ws)
    sent = _in_sources(project, path)
    lifted: Dict[Path, int] = {}
    unfinished: Dict[Path, int] = {}
    copied: Dict[Path, set] = {}  # another project -> its files the wording came from
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
                elif any(walled(ws.context, a, strip_tag(m)) for a in tags for m in as_list(mfm.get("parties"))):
                    pages.append(o)
                else:
                    clear = True
                    break
            elif sent or (index.project.get(o) == project and not _in_sources(project, o)):
                continue
            elif any(walled(ws.context, a, b) for a in tags for b in index.tags.get(o, ())):
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
        a, b = sorted((a, m) for a in tags for m in mtags if walled(ws.context, a, m))[0]
        out.append(Finding(ERROR, "walls", r,
                           "repeats wording from meeting %s, a meeting with %s; a wall stands between %s and %s"
                           % (page.stem, b, a, b),
                           "A note in %s quotes a meeting with %s" % (where, party_name(ws, b))))
    for page in sorted(unfinished):
        if page in reported:
            continue
        out.append(Finding(ERROR, "walls", r,
                           "repeats wording from %s, an unfinished meeting page (no zone or parties)" % page.stem,
                           "A note in %s quotes an unfinished meeting page" % where))
    for other in sorted(copied):
        sources = sorted(copied[other])
        a, b = sorted((a, t) for a in tags for t in index.tags[sources[0]] if walled(ws.context, a, t))[0]
        more = " and %d more of its files" % (len(sources) - 1) if len(sources) > 1 else ""
        out.append(Finding(ERROR, "walls", r,
                           "repeats wording from %s%s, in project %s for %s; a wall stands between %s and %s"
                           % (rel(ws, sources[0]), more, other.name, b, a, b),
                           "A note in %s quotes a file of %s" % (where, party_name(ws, b))))
    return out


def project_of(ws: Workspace, path: Path) -> Optional[Tuple[Path, dict]]:
    for project, pfm in ws.projects:
        if project in path.parents:
            return project, pfm
    return None


# ---------------------------------------------------------------------------
# Mail behind a project's sources
#
# Mail is recorded in Meetings, where the walls can read its parties; what goes
# into a project's Sources/ is an attachment. A file in Sources/ with the same
# bytes as an attachment came from that mail, so the mail must be filed with a
# finished page, and its parties must not be walled from the project's. The
# same holds for a whole mail saved into Sources/.
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
    owner: Dict[Path, Path] = {}
    for page, fm in ws.meetings.items():
        for raw in meeting_raws(ws, page, fm):
            owner.setdefault(raw, page)
    records: List[MailRecord] = []
    raw_dir = ws.root / "Wikis" / "Meetings" / "raw"
    if raw_dir.is_dir():
        records += [MailRecord(p, owner.get(p)) for p in sorted(raw_dir.iterdir())
                    if p.is_file() and p.suffix.lower() == ".eml"]
    for zone in ws.zones:
        inbox = zone / INBOX
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
    if not is_mail and len(data) < MIN_ATTACHMENT_BYTES:
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
        hits.append(sorted((a, b) for a in ptags for b in mtags if walled(ws.context, a, b)))
    if all(hits):  # every mail it could have come from is on the far side of a wall
        a, b = hits[0][0]
        return [Finding(ERROR, "walls", r,
                        "came from mail %s, a mail with %s; a wall stands between %s and %s" % (filed[0].page.stem, b, a, b),
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
            for path in walk_files(project / "Sources", ignored(ws)):
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
    hook guards, and an installed package's files are not the project's."""
    out = []
    for project, pfm in ws.projects:
        ptags = {strip_tag(t) for t in as_list(pfm.get("party"))}
        for path in walk_files(project, ignored(ws)):
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = read_text(path)
            if text:
                out.extend(walls_for_file(ws, project, ptags, path, text))
    out.extend(f for f in all_sources_findings(ws) if f.check == "walls")
    return out


def staged_names(repo: Path) -> Optional[Tuple[Path, List[str]]]:
    """(top of the repository holding `repo`, every path added, copied, modified
    or renamed in its index). None when it is not a repository."""
    top = _git(["rev-parse", "--show-toplevel"], repo)
    if top is None:
        return None
    top_path = Path(top.strip()).resolve()
    names = _git(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"], top_path)
    if names is None:
        return None
    return top_path, [n for n in names.split("\0") if n]


def staged_files(repo: Path) -> Optional[List[Tuple[Path, str]]]:
    """(path, staged text) for every text file added, copied, modified or renamed
    in the index of the repository holding `repo`. None when it is not one."""
    staged = staged_names(repo)
    if staged is None:
        return None
    top_path, names = staged
    out = []
    for name in names:
        path = top_path / name
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            res = subprocess.run(["git", "show", ":" + name], cwd=str(top_path), capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        data = res.stdout
        if res.returncode != 0 or len(data) > MAX_SCAN_BYTES or b"\0" in data[:8192]:
            continue
        out.append((path, data.decode("utf-8", errors="replace")))
    return out


def _git_bytes(args: List[str], cwd: Path) -> Optional[bytes]:
    try:
        res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


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
    for top in workspace_repos(ws):
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
            if data is None or len(data) > MAX_SCAN_BYTES or b"\0" in data[:8192]:
                continue  # deleted in git too, or not text
            out[top / name] = data.decode("utf-8", errors="replace")
    return out


def apply_git_view(ws: Workspace, committing: Path) -> List[Finding]:
    """Read git's version of every file whose working copy differs (git_view)
    alongside the disk's. A meeting page counts with the parties of both
    versions, and one deleted from disk still counts. A project or thread note
    in the repository being committed whose party differs from the one staged
    is refused: which party the commit is written for must not depend on an
    edit it leaves out."""
    ws.git_view = git_view(ws, committing)
    sources = ws.root / "Wikis" / "Meetings" / "wiki" / "sources"
    for path, text in sorted(ws.git_view.items()):
        if sources in path.parents and path.suffix.lower() == ".md":
            then = parse_frontmatter_text(text)
            if path not in ws.meetings:
                if not path.exists():
                    ws.meetings[path] = then
                continue
            now = ws.meetings[path]
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
            disk = {strip_tag(t) for t in as_list(parse_frontmatter(note).get("party"))}
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


def check_walls_staged(ws: Workspace, repo: Path) -> List[Finding]:
    """The walls check on what is about to be committed, and nothing else.
    Anything waiting in a zone's Inbox, or in the Meetings inbox, at any depth,
    is refused too: it has not been filed, so no wall has seen its parties yet."""
    out = []
    staged = staged_names(repo)
    zones = {z.resolve() for z in ws.zones}
    minbox = ws.root.joinpath(*MEETINGS_INBOX).resolve()
    if staged is not None:
        top_path, names = staged
        out.extend(apply_git_view(ws, top_path))
        try:
            minbox_rel = minbox.relative_to(top_path).parts
        except ValueError:
            minbox_rel = None  # the Meetings inbox is in another repository
        for name in names:
            if top_path in zones and in_inbox(name, (INBOX,)):
                out.append(Finding(ERROR, "inbox", rel(ws, top_path / name),
                                   "is waiting in the inbox to be filed, and never goes into the zone's history; "
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
            if owner is None or not _in_sources(owner[0], top_path / name):
                continue
            try:
                res = subprocess.run(["git", "show", ":" + name], cwd=str(top_path), capture_output=True, timeout=60)
            except (OSError, subprocess.SubprocessError):
                continue
            if res.returncode == 0 and len(res.stdout) <= MAX_SOURCE_BYTES:
                project, pfm = owner
                ptags = {strip_tag(t) for t in as_list(pfm.get("party"))}
                out.extend(sources_for_file(ws, project, ptags, top_path / name, res.stdout))
    for path, text in staged_files(repo) or []:
        owner = project_of(ws, path)
        if owner is None:
            continue  # not inside a project: no party, so no wall to hold
        project, pfm = owner
        ptags = {strip_tag(t) for t in as_list(pfm.get("party"))}
        out.extend(walls_for_file(ws, project, ptags, path, text))
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
            forms = [data] + ([strip_recipients(data)] if path.suffix.lower() == ".eml" else [])
            twin = next((r for f in forms for r in by_size.get(len(f), []) if r.read_bytes() == f), None)
            if twin is not None:
                out.append(Finding(WARNING, "inbox", rel(ws, path),
                                   "already filed as %s; this copy was left behind, so delete it" % rel(ws, twin),
                                   "Something in %s was filed but not moved" % spoken))
    return out


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
    mfiles = PathIndex(ws, (p for p in ws.wiki_files if mroot in p.parents))
    raw = kroot / "raw"
    beyond = None
    for path in walk_files(kroot):
        suffix = path.suffix.lower()
        if suffix not in TEXT_SUFFIXES and suffix != ".eml":
            continue
        text = read_text(path) or ""
        if raw not in path.parents and suffix != ".eml":
            fm = {}
            if suffix == ".md":  # read once; a page too big to scan still has its fields read
                fm = parse_frontmatter_text(text) if text else parse_frontmatter(path)
            carried = [k for k in ("party", "parties", "zone") if as_list(fm.get(k))]
            if carried:
                out.append(Finding(ERROR, "knowledge", rel(ws, path),
                                   "carries %s; Knowledge holds published material, which carries nobody's confidence. "
                                   "Take the field out, or file the item in Meetings if it is a conversation"
                                   % " and ".join("`%s`" % k for k in carried),
                                   "A Knowledge page carries parties"))
            for problem in bad_dates(fm):
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
            out.append(Finding(WARNING, "knowledge", rel(ws, path),
                               "shares eight or more words in a row with meeting %s%s; wording in Knowledge is common to "
                               "every side, so a conversation copied here crosses every wall. If the meeting quoted "
                               "this published text, nothing needs changing" % (heard[0].stem, more),
                               "A Knowledge page repeats a meeting"))
    return out


def _git(args: List[str], cwd: Path) -> Optional[str]:
    try:
        res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def check_raw(ws: Workspace) -> List[Finding]:
    """A raw record is never changed after its first commit, unless the check
    settings accept that change (`raw-accepted`): then only a later one counts."""
    out = []
    accepted = {k: v.strip() for k, v in ws.settings.get("raw-accepted", {}).items() if isinstance(v, str) and v.strip()}
    wikis = ws.root / "Wikis"
    if not wikis.is_dir():
        return out
    root = ws.root.resolve()
    for wiki in visible_dirs(wikis):
        raw = wiki / "raw"
        if not raw.is_dir():
            continue
        top = _git(["rev-parse", "--show-toplevel"], raw)
        if top is None:
            continue  # not a git repository, or git is not installed: nothing to compare against
        top_path = Path(top.strip()).resolve()
        if top_path != root and root not in top_path.parents:
            continue  # the repository belongs to something outside the workspace
        rawrel = raw.resolve().relative_to(top_path).as_posix()
        changed: Dict[str, str] = {}
        log = _git(["log", "--no-renames", "--diff-filter=MD", "--name-status", "--format=", "--", rawrel], top_path) or ""
        for line in log.splitlines():
            status, _, name = line.partition("\t")
            if name:
                changed.setdefault(name, "deleted" if status.startswith("D") else "edited")
        # A change the user accepted (raw-accepted in the check settings)
        # counts no more; one in a later commit does.
        for name in list(changed):
            commit = accepted.get(rel(ws, top_path / name))
            if commit:
                later = _git(["log", "--no-renames", "--diff-filter=MD", "--format=%H", commit + "..HEAD", "--", name], top_path)
                if later is None:
                    out.append(Finding(WARNING, "raw", rel(ws, top_path / name),
                                       "the check settings accept a change to it in commit %s, which git does not know" % commit,
                                       "An accepted change names a commit git does not know"))
                elif not later.strip():
                    del changed[name]
        status = _git(["status", "--porcelain", "--no-renames", "--untracked-files=no", "--", rawrel], top_path) or ""
        for line in status.splitlines():
            if len(line) > 3 and ("M" in line[:2] or "D" in line[:2]):
                name = line[3:].strip().strip('"')
                changed.setdefault(name, "deleted" if "D" in line[:2] else "edited")
        inbox = rawrel + "/inbox/"
        for name, how in sorted(changed.items()):
            if name.startswith(inbox):
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
            return subprocess.run(["git", "-C", str(ws.root), *args], capture_output=True, text=True, timeout=30)
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
    return out


ALL_CHECKS = [
    check_claude_md, check_instructions, check_settings, check_placeholders, check_context, check_zones, check_hooks,
    check_skills, check_names, check_projects, check_threads, check_resume, check_deliverables, check_anonymous,
    check_todo, check_links, check_meetings, check_people, check_walls, check_sources, check_inbox, check_knowledge,
    check_raw, check_generated, check_updates,
]


def run_checks(root: Path, walls_only: bool = False, staged: Optional[Path] = None, quick: bool = False) -> List[Finding]:
    """Every check, or with `walls_only` the walls check alone. With `staged`, a
    folder inside a git repository, the walls check alone on what it has staged.
    With `quick`, every check but the comparison of wording: whether a project
    file, a person page or a Knowledge page repeats a meeting. That comparison
    reads every meeting and project file, and is most of the time a full check
    takes on a large workspace; the commit hook still runs it on what is staged."""
    ws = discover(Path(root).resolve())
    ws.quick = quick and staged is None
    findings: List[Finding] = []
    if staged is not None:
        findings = check_walls_staged(ws, Path(staged))
    else:
        for check in ([check_walls] if walls_only else ALL_CHECKS):
            findings.extend(check(ws))
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


def report_staged(findings: List[Finding]) -> str:
    """For the pre-commit hook: one plain line per wall broken, nothing when clear."""
    return "\n".join(
        "Commit refused: %s %s. Take it out and commit again; only if you mean it, git commit --no-verify."
        % (f.path, f.message) for f in findings if f.severity == ERROR)


def install_hooks(root: Path) -> int:
    ws = discover(root)
    code = 0
    for zone in ws.zones:
        try:
            hook = install_wall_hook(zone)
            print("%s: wall check installed at %s" % (zone.name, rel(ws, hook)))
        except (FileExistsError, FileNotFoundError) as exc:
            print("%s: %s" % (zone.name, exc), file=sys.stderr)
            code = 1
    return code


def report_json(findings: List[Finding], root: Path) -> str:
    errors, warnings = _counts(findings)
    return json.dumps({"root": str(root), "errors": errors, "warnings": warnings,
                       "findings": [asdict(f) for f in findings]}, indent=2)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check a Garrick workspace against its rules.")
    parser.add_argument("--root", help="workspace root (default: the workspace this script sits in, else the current folder's)")
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument("--ear", action="store_true", help="at most three short sentences, for reading aloud")
    fmt.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--walls-only", action="store_true", help="run the walls check alone")
    parser.add_argument("--quick", action="store_true",
                        help="leave out the comparison of wording with the meetings, the slow part on a large workspace")
    parser.add_argument("--staged", action="store_true",
                        help="check only the files staged in the current folder's git repository (implies --walls-only)")
    parser.add_argument("--install-hooks", action="store_true",
                        help="install the pre-commit wall check in every zone's repository")
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
    if args.version:
        stamp = read_version(root)
        print(" ".join(s for s in (say_version(stamp), say_changes(root, stamp)) if s))
        return 0
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
