#!/usr/bin/env python3
"""Check a Garrick workspace against every rule a machine can check.

    python3 System/tools/check.py [--root PATH] [--ear] [--json]
    python3 System/tools/check.py --staged --walls-only      (the pre-commit hook)
    python3 System/tools/check.py --install-hooks

Plain text by default: findings grouped by check, one line each, then a
count. `--ear` gives at most three short sentences for reading aloud.
`--json` is for other programs. Exit code 1 when there is any error.

`--walls-only` runs the walls check alone. `--staged` checks only the files
staged in the git repository of the current folder, as they are staged, and
prints one line per wall broken: it is what each zone's pre-commit hook runs.
`--install-hooks` writes that hook into every zone's repository.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

sys.dont_write_bytecode = True  # keep System/tools free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))

from garrick_lib import (  # noqa: E402
    INBOX,
    MEDIA_EXTS,
    has_wall_hook,
    install_wall_hook,
    is_domain,
    is_speakable,
    is_webmail,
    load_context,
    mail_attachments,
    parse_frontmatter,
    parse_mail_bytes,
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
    ("placeholders", "Unfinished install"),
    ("context", "Context"),
    ("zones", "Zones"),
    ("names", "Names"),
    ("projects", "Projects"),
    ("threads", "Threads"),
    ("deliverables", "Deliverables"),
    ("meetings", "Meeting pages"),
    ("walls", "Walls"),
    ("sources", "Project sources"),
    ("inbox", "Zone inboxes"),
    ("knowledge", "Knowledge wiki"),
    ("raw", "Raw records"),
]

# How a group of findings is said aloud when there is more than one.
EAR_GROUP = {
    "claude-md": "{n} CLAUDE files could switch off the instructions",
    "instructions": "the instruction files have drifted in {n} places",
    "placeholders": "{n} files still hold installer placeholders",
    "context": "the context file has {n} problems",
    "zones": "the zone folders have {n} gaps",
    "names": "{n} names are hard to say or sound alike",
    "projects": "{n} things need fixing in project hub notes",
    "threads": "{n} things need fixing in thread notes",
    "deliverables": "{n} deliverables lack their date",
    "meetings": "{n} things need fixing on meeting pages",
    "walls": "the walls were crossed in {n} places",
    "sources": "{n} project sources came from mail that is not filed in Meetings",
    "inbox": "{n} files in the zone inboxes need attention",
    "knowledge": "{n} Knowledge pages cross into Meetings or carry parties",
    "raw": "{n} raw records were changed",
}

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".csv", ".tsv", ".html", ".htm", ".json", ".yaml", ".yml", ".vtt"}
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")
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
    mail_index: Optional[Dict[Tuple[str, int, str], List["MailRecord"]]] = None  # built on first use
    source_findings: Optional[List["Finding"]] = None  # the Sources/ findings, computed once


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def rel(ws: Workspace, path: Path) -> str:
    try:
        return path.relative_to(ws.root).as_posix()
    except ValueError:
        return str(path)


def walk_files(top: Path) -> Iterable[Path]:
    """Every file under `top`, skipping `.git` folders."""
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(filenames):
            yield Path(dirpath) / name


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
    """A zone's projects: every visible folder but its Inbox."""
    return [p for p in visible_dirs(zone) if p.name != INBOX]


def as_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)] if str(value).strip() else []


def party_name(ws: Workspace, tag: str) -> str:
    entry = ws.context["parties"].get(tag)
    return entry["party"] if entry and entry.get("party") else tag


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


def resolve(ws: Workspace, source: Path, target: str, candidates: Iterable[Path]) -> List[Path]:
    """Which of `candidates` could `target`, written in `source`, point at?

    Absolute and ./ ../ paths resolve exactly. Everything else matches the way
    Obsidian does: a page whose path ends with the link's path.
    """
    candidates = list(candidates)
    vault = None
    if target.startswith("obsidian:"):
        _, vault, target = target.split(":", 2)
    if target.startswith("/") or target.startswith("./") or target.startswith("../"):
        base = Path(target) if target.startswith("/") else source.parent / target
        try:
            exact = base.resolve()
        except OSError:
            return []
        hits = [c for c in candidates if c.resolve() in (exact, exact.with_suffix(".md"), Path(str(exact) + ".md"))]
        return hits
    parts = _strip_md(tuple(p for p in target.replace("\\", "/").split("/") if p and p != "."))
    if not parts:
        return []
    tries = [((vault,) + parts)] if vault else []
    tries.append(parts)
    for want in tries:
        hits = []
        for c in candidates:
            have = _strip_md(Path(rel(ws, c)).parts)
            if len(have) >= len(want) and tuple(x.lower() for x in have[-len(want):]) == tuple(x.lower() for x in want):
                hits.append(c)
        if hits:
            return hits
    return []


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover(root: Path) -> Workspace:
    ws = Workspace(root=root, context=load_context(root))
    ws.zones = visible_dirs(root / "Zones")
    for zone in ws.zones:
        for project in project_dirs(zone):
            ws.projects.append((project, parse_frontmatter(project / (project.name + ".md"))))
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
    files = instruction_files(ws)
    texts = {f: f.read_text(encoding="utf-8", errors="replace") for f in files}
    for f, text in texts.items():
        if f.name != "AGENTS.md":
            continue
        budget = WORD_BUDGET_ROOT if f.parent == ws.root else WORD_BUDGET_OTHER
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
    return out


def check_placeholders(ws: Workspace) -> List[Finding]:
    out = []
    for path in walk_files(ws.root):
        if is_template_path(ws, path):
            continue
        found = PLACEHOLDER_RE.findall(rel(ws, path))
        if path.suffix.lower() in TEXT_SUFFIXES or path.suffix == "":
            text = read_text(path)
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


def check_projects(ws: Workspace) -> List[Finding]:
    out = []
    for project, fm in ws.projects:
        hub = project / (project.name + ".md")
        r = rel(ws, hub)
        spoken = "%s, %s" % (project.parent.name, project.name)
        if not hub.is_file():
            out.append(Finding(ERROR, "projects", rel(ws, project), "no hub note %s.md" % project.name,
                               "Project %s has no hub note" % spoken))
            continue
        if fm.get("type") != "project":
            out.append(Finding(ERROR, "projects", r, "frontmatter `type` is %r, should be project" % fm.get("type"),
                               "The %s hub note is not marked as a project" % project.name))
        if fm.get("zone") != project.parent.name:
            out.append(Finding(ERROR, "projects", r,
                               "frontmatter `zone` is %r but the project sits in %s" % (fm.get("zone"), project.parent.name),
                               "The %s hub note names the wrong zone" % project.name))
        tags = [strip_tag(t) for t in as_list(fm.get("party"))]
        if not tags:
            out.append(Finding(WARNING, "projects", r, "no `party`; it cannot draw on the Meetings wiki until it has one",
                               "Project %s has no party" % project.name))
        for tag in tags:
            if tag not in ws.context["parties"]:
                out.append(Finding(ERROR, "projects", r, "`party` %s is not a tag in the Parties table" % tag,
                                   "Project %s names an unknown party" % project.name))
        if not visible_dirs(project / "Threads"):
            out.append(Finding(WARNING, "projects", rel(ws, project), "no threads; every piece of work belongs to one",
                               "Project %s has no threads" % project.name))
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
                out.append(Finding(ERROR, "threads", rel(ws, thread), "no thread note %s.md" % thread.name,
                                   "Thread %s has no note" % spoken))
                continue
            fm = parse_frontmatter(note)
            if fm.get("type") != "thread":
                out.append(Finding(ERROR, "threads", r, "frontmatter `type` is %r, should be thread" % fm.get("type"),
                                   "Thread %s is not marked as a thread" % spoken))
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
            if ttags and ptags and ttags != ptags:
                out.append(Finding(WARNING, "threads", r,
                                   "`party` %s differs from the project's %s" % (", ".join(sorted(ttags)), ", ".join(sorted(ptags))),
                                   "Thread %s names a different party from its project" % spoken))
    return out


def check_deliverables(ws: Workspace) -> List[Finding]:
    out = []
    for project, _ in ws.projects:
        folder = project / "Deliverables"
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.name.startswith("."):
                continue
            if path.is_dir() and path.name.lower() == "archive":
                continue
            m = DELIVERABLE_RE.match(path.name)
            ok = bool(m) and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31
            if not ok:
                out.append(Finding(WARNING, "deliverables", rel(ws, path),
                                   "name does not start with its creation date, `YYMMDD - <name>`",
                                   "A deliverable in %s lacks its date" % project.name))
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
        if fm and fm.get("type") not in (None, "meeting", "email"):
            out.append(Finding(WARNING, "meetings", r, "`type` is %r, should be meeting or email" % fm.get("type"),
                                   "A meeting page is not marked as a meeting"))
        if not MEETING_NAME_RE.match(page.stem):
            out.append(Finding(WARNING, "meetings", r, "file name should be `YYMMDD-slug.md`",
                                   "A meeting page is misnamed"))
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


def words(text: str) -> List[str]:
    """Lower-case words: accents dropped, `&` read as "and", punctuation gone."""
    text = unicodedata.normalize("NFKD", text.replace("&", " and "))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.findall(r"[a-z0-9]+", text)


def transcript_text(path: Path, text: str) -> str:
    """A raw record as the words that were said or written: a transcript
    without its timings and voice tags, so a sentence split across two cues
    still reads as one run of words; a saved mail as its subject and text,
    decoded from however the message was encoded."""
    if path.suffix.lower() == ".vtt":
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


def shingles(tokens: List[str]) -> Iterable[int]:
    """A hash for each run of SHINGLE words that carries enough content words."""
    content = [t not in STOPWORDS for t in tokens]
    for i in range(len(tokens) - SHINGLE + 1):
        if sum(content[i:i + SHINGLE]) >= MIN_CONTENT_WORDS:
            yield hash(tuple(tokens[i:i + SHINGLE]))


@dataclass
class QuoteIndex:
    owners: Dict[int, set]  # shingle -> the finished meeting pages whose page or raw record holds it
    common: set  # shingles in material that crosses every wall: System/, Knowledge, instruction files


def meeting_raws(ws: Workspace, page: Path, fm: dict) -> List[Path]:
    """The raw transcripts behind a meeting page: the one its `raw` field names,
    else any file in raw/ with the page's slug. The inbox is not yet filed."""
    raw = ws.root / "Wikis" / "Meetings" / "raw"
    if not raw.is_dir():
        return []
    stems = {page.stem}
    for value in as_list(fm.get("raw")):
        stems.add(Path(value.strip("[]").split("|", 1)[0]).stem)
    return sorted(p for p in raw.iterdir() if p.is_file() and p.stem in stems)


def quote_index(ws: Workspace) -> QuoteIndex:
    if ws.quote_index is not None:
        return ws.quote_index
    owners: Dict[int, set] = {}
    for page, fm in ws.meetings.items():
        if not fm.get("zone") or not as_list(fm.get("parties")):
            continue  # unfinished: the meetings check reports it, and nothing on it may be used
        texts = [body_of(read_text(page) or "")]
        texts += [transcript_text(r, read_text(r) or "") for r in meeting_raws(ws, page, fm)]
        for text in texts:
            for h in shingles(words(text)):
                owners.setdefault(h, set()).add(page)
    common: set = set()
    shared = [ws.root / "AGENTS.md"] + list(walk_files(ws.root / "System"))
    shared += list(walk_files(ws.root / "Wikis" / "Knowledge")) if (ws.root / "Wikis" / "Knowledge").is_dir() else []
    shared += [ws.root / "Wikis" / "AGENTS.md", ws.root / "Wikis" / "Meetings" / "AGENTS.md"]
    for path in shared:
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            common.update(h for h in shingles(words(read_text(path) or "")) if h in owners)
    ws.quote_index = QuoteIndex(owners, common)
    return ws.quote_index


def name_forms(ws: Workspace, walled_tags: set) -> Dict[str, List[Tuple[bool, str]]]:
    """For each walled party, the forms that name it: (case-sensitive, form).

    Case-insensitive forms are word sequences, matched on `words()`: the party's
    name, tag and mail domains, its people's full names, and the aliases that
    mean either. A
    person's first name alone is matched only as written, capitalised, and not
    when it is an everyday word. A form that also names a party on this side of
    the wall is dropped: it cannot tell the two apart.
    """
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


def names_hit(text: str, forms: List[Tuple[bool, str]]) -> bool:
    padded = " %s " % " ".join(words(text))
    for case_sensitive, form in forms:
        if case_sensitive:
            if re.search(r"(?<![\w])%s(?![\w])" % re.escape(form), text):
                return True
        elif " %s " % form in padded:
            return True
    return False


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
    meetings = list(ws.meetings)
    tags, where = file_tags(ws, project, ptags, path)
    r = rel(ws, path)
    zone = project.parent.name
    reported: set = set()  # walled parties and meetings already named for this file

    # Links.
    seen = set()
    for written, target in extract_links(text) if meetings else []:
        for page in resolve(ws, path, target, meetings):
            key = (written, page)
            if key in seen:
                continue
            seen.add(key)
            mfm = ws.meetings[page]
            mtags = [strip_tag(t) for t in as_list(mfm.get("parties"))]
            if not mtags or not mfm.get("zone"):
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
    if not tags:
        return out
    far = {t for t in ws.context["parties"] if any(walled(ws.context, a, t) for a in tags)}
    if not far:
        return out

    # Names. Sources/ holds what a party sent, which may name anyone; it is exempt.
    in_sources = "Sources" in Path(rel(ws, path)).parts[3:-1]
    if not in_sources:
        scanned = without_party_field(text) + "\n" + path.name
        for b, forms in name_forms(ws, far).items():
            if b in reported or not forms or not names_hit(scanned, forms):
                continue
            a = sorted(t for t in tags if walled(ws.context, t, b))[0]
            reported.add(b)
            out.append(Finding(ERROR, "walls", r,
                               "names %s, or one of its people; a wall stands between %s and %s" % (party_name(ws, b), a, b),
                               "A note in %s names %s" % (where, party_name(ws, b))))

    # Quotes. Wording also found on the near side of the wall, or in material
    # that crosses every wall, is not evidence of a leak.
    index = quote_index(ws)
    lifted: Dict[Path, int] = {}
    for h in set(shingles(words(text))):
        pages = index.owners.get(h)
        if not pages or h in index.common:
            continue
        walled_pages = {p for p in pages
                        if any(walled(ws.context, a, strip_tag(m)) for a in tags for m in as_list(ws.meetings[p].get("parties")))}
        if walled_pages != pages:
            continue
        for p in walled_pages:
            lifted[p] = lifted.get(p, 0) + 1
    for page in sorted(lifted):
        if page in reported:
            continue
        mtags = [strip_tag(m) for m in as_list(ws.meetings[page].get("parties"))]
        a, b = sorted((a, m) for a in tags for m in mtags if walled(ws.context, a, m))[0]
        out.append(Finding(ERROR, "walls", r,
                           "repeats wording from meeting %s, a meeting with %s; a wall stands between %s and %s"
                           % (page.stem, b, a, b),
                           "A note in %s quotes a meeting with %s" % (where, party_name(ws, b))))
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
            for path in walk_files(project / "Sources"):
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
    side of a wall from the project's party, or came from a mail that is."""
    out = []
    for project, pfm in ws.projects:
        ptags = {strip_tag(t) for t in as_list(pfm.get("party"))}
        for path in walk_files(project):
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


def check_walls_staged(ws: Workspace, repo: Path) -> List[Finding]:
    """The walls check on what is about to be committed, and nothing else.
    Anything waiting in a zone's Inbox is refused too: it has not been filed,
    so no wall has seen its parties yet."""
    out = []
    staged = staged_names(repo)
    zones = {z.resolve() for z in ws.zones}
    if staged is not None:
        top_path, names = staged
        for name in names:
            parts = Path(name).parts
            if top_path in zones and len(parts) == 2 and parts[0] == INBOX and parts[1] != ".gitkeep":
                out.append(Finding(ERROR, "inbox", rel(ws, top_path / name),
                                   "is waiting in the inbox to be filed, and never goes into the zone's history; "
                                   "unstage it and file it where it belongs",
                                   "A file from the %s inbox was about to be committed" % top_path.name))
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


def _zone_repo(zone: Path) -> bool:
    """Is `zone` the top of its own git repository?"""
    top = _git(["rev-parse", "--show-toplevel"], zone) if (zone / ".git").exists() else None
    return top is not None and Path(top.strip()).resolve() == zone.resolve()


def check_inbox(ws: Workspace) -> List[Finding]:
    """Mail and files in a zone's Inbox are waiting to be filed. They never
    enter the zone's history, and once filed no copy stays behind."""
    out = []
    by_size: Optional[Dict[int, List[Path]]] = None
    for zone in ws.zones:
        inbox = zone / INBOX
        if not inbox.is_dir():
            continue
        if _zone_repo(zone):
            listing = _git(["ls-files", "-z", "--", INBOX], zone) or ""
            for name in sorted(n for n in listing.split("\0") if n and Path(n).name != ".gitkeep"):
                out.append(Finding(ERROR, "inbox", rel(ws, zone / name),
                                   "committed into the %s zone's history from its inbox, which is never committed: "
                                   "`git rm --cached` it, then file it where it belongs" % zone.name,
                                   "Something in the %s inbox was committed" % zone.name))
        for path in sorted(p for p in inbox.iterdir() if p.is_file() and not p.name.startswith(".")):
            if path.suffix.lower() in MEDIA_EXTS:
                out.append(Finding(WARNING, "inbox", rel(ws, path),
                                   "audio or video is never read; put its transcript in Wikis/Meetings/raw/inbox/ instead",
                                   "A recording in the %s inbox cannot be read" % zone.name))
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
                                   "Something in the %s inbox was filed but not moved" % zone.name))
    return out


def check_knowledge(ws: Workspace) -> List[Finding]:
    out = []
    kroot = ws.root / "Wikis" / "Knowledge"
    mroot = ws.root / "Wikis" / "Meetings"
    if not kroot.is_dir():
        return out
    kfiles = list(walk_files(kroot))
    mfiles = [p for p in ws.wiki_files if mroot in p.parents]
    raw = kroot / "raw"
    for path in walk_files(kroot):
        if path.suffix.lower() not in TEXT_SUFFIXES or raw in path.parents:
            continue
        fm = parse_frontmatter(path) if path.suffix.lower() == ".md" else {}
        carried = [k for k in ("parties", "zone") if as_list(fm.get(k))]
        if carried:
            out.append(Finding(ERROR, "knowledge", rel(ws, path),
                               "carries %s; Knowledge holds published material, which carries nobody's confidence. "
                               "Take the field out, or file the item in Meetings if it is a conversation"
                               % " and ".join("`%s`" % k for k in carried),
                               "A Knowledge page carries parties"))
        text = read_text(path) or ""
        for written, target in extract_links(text):
            explicit = "Meetings/" in target.replace("\\", "/") or target.startswith("obsidian:Meetings:")
            if not explicit and resolve(ws, path, target, kfiles):
                continue  # the link lands inside Knowledge, which is where Obsidian looks first
            if resolve(ws, path, target, mfiles):
                out.append(Finding(ERROR, "knowledge", rel(ws, path),
                                   "links %s, a Meetings page; Knowledge must not carry anyone's confidence" % written,
                                   "A Knowledge page links into Meetings"))
    return out


def _git(args: List[str], cwd: Path) -> Optional[str]:
    try:
        res = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def check_raw(ws: Workspace) -> List[Finding]:
    out = []
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


ALL_CHECKS = [
    check_claude_md, check_instructions, check_placeholders, check_context, check_zones, check_names,
    check_projects, check_threads, check_deliverables, check_meetings, check_walls,
    check_sources, check_inbox, check_knowledge, check_raw,
]


def run_checks(root: Path, walls_only: bool = False, staged: Optional[Path] = None) -> List[Finding]:
    """Every check, or with `walls_only` the walls check alone. With `staged`, a
    folder inside a git repository, the walls check alone on what it has staged."""
    ws = discover(Path(root).resolve())
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
    parser.add_argument("--staged", action="store_true",
                        help="check only the files staged in the current folder's git repository (implies --walls-only)")
    parser.add_argument("--install-hooks", action="store_true",
                        help="install the pre-commit wall check in every zone's repository")
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
    findings = run_checks(root, walls_only=args.walls_only, staged=Path.cwd() if args.staged else None)
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
