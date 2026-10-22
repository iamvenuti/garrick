#!/usr/bin/env python3
"""Context Nurture: every finding the workspace's own checks hold, sorted by
what a fix needs, and the mechanical ones applied on one yes.

    python3 System/tools/nurture.py [list] [--scope PATH]... [--json | --ear]
    python3 System/tools/nurture.py fix [--scope PATH]... [--yes] [--json]
    python3 System/tools/nurture.py nightly [--scope PATH]... [--json]
    python3 System/tools/nurture.py answered --path PATH --asked "<question>" --answer "<answer>"
    python3 System/tools/nurture.py correct --old OLD --new NEW [--scope PATH]... [--yes] [--why "..."] [--leave PATH]...

It adds no checks of its own. Its sources are the existing tools, each run
as it runs for anyone: `check.py --json`, `wiki_lint.py --json` for each
wiki, and `drift.py --json`. A new kind of problem gets a check in
`check.py` first, and this sorts it. The wikis' *Lint* stays a report that
changes nothing: this runs its script part, and the `nurture` skill runs its
reading part.

A scope is a path from the workspace's top: a zone (`Zones/Work`), a project
(`Zones/Work/Acme Review`), a thread (`.../Threads/Pricing`) or a wiki
(`Wikis/Meetings`). None means the whole workspace. Several may be given, as
for a party with several projects. Code never chooses which: the skill
resolves a spoken name to a path, and asks when it could be two.

**The four kinds**, by what a fix needs, not by which tool found it:

- *wall*: a file that names, links or quotes a party across a wall. Each is
  said as its file and its wall, never with the material that matched.
- *mechanical*: a fix with exactly one right answer: a link broken by a
  rename with exactly one candidate in its repository's history; a
  deliverable without its date prefix, dated from the commit that added it;
  a thread missing from its hub's list; a status synonym (`paused` for
  `parked`); a note path written as code that, as a wikilink, leads to
  exactly one live note in the same zone; a note inside a thread's folder
  with no `parent:`, given its thread's, when that thread note is there and
  its name leads nowhere else. `fix --yes` applies them all, one commit per
  repository, of the files it changed and nothing else. A fix whose files
  have changes not committed, or that no repository holds, is held and left
  in the report.
- *attribution*: which zone, party, wiki or type a thing belongs to. Each
  carries one line to ask, and a proposal where the context file settles one
  without crossing a wall. The skill asks; this changes none of them.
- *judgment*: everything else. Reported, with the page to open.

**Behind the share** is listed apart, after them all: a published file whose
ledger row ends in `share`, and whose copy here differs from the shared one,
which is what the ledger expects once a colleague saves there. Nothing is
fixed; it is low urgency, and the morning digest leaves it out. `drift.py`
names it `behind`, and the drift source hands it straight to its kind.

**A fifth kind, the correction**, is never found: a person gives it. When the
user answers a finding, or says outright, "that's wrong, it's Y", `correct`
takes the two values and makes one finding of every live copy that
`correct.py`'s `find_hits` finds, and on `--yes` applies them with its
`apply`, which commits once per repository: one implementation, shared with
the `threads` skill. With a scope, a copy in a file across a wall from it, or
whose parties cannot be told, is left out and left alone: the run says the
rule's sentence once and nothing else of it, no file, party or count. A copy
in a file another session has changes in is held, as for any fix. Raw records stay
as they are, as `correct.py` keeps them. It is not unattended, and has no
`apply` for the machine below, which holds a fix that spans two repositories,
as a correction usually does: so `fix` and `nightly` never apply one, and
under GARRICK_HEADLESS=1 `correct --yes` is refused.

**The nightly run**, `nightly`, applies the kinds registered as unattended,
which in this release is the mechanical kind alone, and nothing else ever
changes with nobody watching. It reads drift from `System/generated/
drift.json`, since macOS keeps a scheduled job out of cloud folders. Under
GARRICK_HEADLESS=1, as the jobs extra sets it, `fix --yes` behaves the same.

**The report**: every run writes `System/generated/nurture/<YYYY-MM-DD>.md`,
what was fixed, what was asked and answered, and what is left, rebuilt from
the day's record beside it, `<YYYY-MM-DD>.json`. `answered` adds a line the
skill asked and the user answered; `correct --yes` adds the copies it fixed,
each commit, and the yes. Neither file is committed.

**Kinds are a registry.** A kind is a `Kind`, put in KINDS by `register()`:
its name, its heading, the rank it claims findings at (lower first, the
judgment kind last as the catch-all), `claim(ctx, item)` that says whether a
finding is its own and fills in what the kind needs, and optionally
`gather(ctx)` for findings from a tool of its own, `apply(ctx, item,
journal)` for a fix, `unattended` when the nightly run may apply it, and
`quiet` when the morning digest leaves it out. A kind ranked after the
judgment kind claims nothing, since the catch-all claims first: a source or
a `gather` names it on the finding, as the drift source does for `behind`. To
add one, write its Kind and register it in the *Kinds* section below, or in
a module of its own imported where that section ends: sorting, holding,
applying, committing, rolling back, the report and the digest all read the
registry, and none of them changes. An `apply` edits through the journal,
`journal.write(path, text)` and `journal.move(old, new)`, and declares every
path it touches in `item.touches` at claim time, so the machine can refuse
a file with someone else's changes in it and undo a fix whose commit the
wall check refused.

Exit codes: 0; 1 when a source tool did not run or a commit was refused (its
fixes are put back); 2 when no workspace or scope is found.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import correct  # noqa: E402
from operations import WALL_REFUSAL  # noqa: E402
from garrick_lib import (  # noqa: E402
    foreign_git_env,
    live_files,
    load_context,
    parse_frontmatter_text,
    strip_tag,
    walled,
    workspace_root,
)

REPORTS = ("System", "generated", "nurture")
WIKIS = ("Meetings", "Knowledge")
EXIT_FAILED = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# A finding, as this tool carries it
# ---------------------------------------------------------------------------

@dataclass
class Item:
    source: str                     # check, wiki-lint, drift, or a kind's own
    check: str                      # the check's name, or orphan, missing, or a drift state
    path: str                       # from the workspace's top, no line number
    message: str
    ear: str = ""
    severity: str = "warning"
    kind: str = ""                  # set when a kind claims it
    where: List[str] = field(default_factory=list)   # other paths that put it in a scope
    fix: Optional[dict] = None      # what a fix changes: its `op`, and what the op needs
    touches: List[str] = field(default_factory=list)  # every path a fix writes, moves or makes
    question: str = ""              # attribution: the one line to ask
    proposal: str = ""              # attribution: the answer the context file settles, if any
    wall: str = ""                  # wall: "acme and birch"
    held: str = ""                  # why a fix was not applied
    said: str = ""                  # what a fix did, once applied

    def line(self) -> str:
        return KINDS[self.kind].say(self) if self.kind in KINDS else "%s: %s" % (self.path, self.message)


# ---------------------------------------------------------------------------
# The run's context
# ---------------------------------------------------------------------------

class Ctx:
    def __init__(self, root: Path, headless: bool = False, today: Optional[datetime.date] = None):
        self.root = root
        self.headless = headless
        self.today = today or datetime.date.today()
        self.context = load_context(root)
        self.failed: List[str] = []           # sources that did not run
        self._renames: Dict[Path, List[Tuple[str, str]]] = {}
        self._tracked: Dict[Path, set] = {}
        self._notes: Optional[List[str]] = None

    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def repo_of(self, path: Path) -> Optional[Path]:
        """The repository that holds `path`: the nearest folder above it, in
        the workspace, with a `.git` of its own."""
        d = path if path.is_dir() else path.parent
        while True:
            if os.path.lexists(str(d / ".git")):
                return d
            if d == self.root or self.root not in d.parents:
                return None
            d = d.parent

    def git(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=str(repo), capture_output=True,
                              text=True, timeout=300, stdin=subprocess.DEVNULL, env=foreign_git_env())

    def tracked(self, repo: Path) -> set:
        if repo not in self._tracked:
            r = self.git(repo, "ls-files", "-z")
            self._tracked[repo] = set(r.stdout.split("\0")) - {""} if r.returncode == 0 else set()
        return self._tracked[repo]

    def notes(self) -> List[str]:
        """Every live note a wikilink may land on, from the workspace's top:
        the root's own, System's, each zone's and the wikis', outside
        archives and build output, as Obsidian sees the workspace."""
        if self._notes is None:
            tops = [self.root / "System", self.root / "Wikis"]
            zones = self.root / "Zones"
            tops += sorted(z for z in zones.iterdir() if z.is_dir() and not z.name.startswith((".", "_"))) \
                if zones.is_dir() else []
            found = [p for p in self.root.glob("*.md") if p.is_file()]
            for top in tops:
                if top.is_dir():
                    found += [p for p in live_files(top) if p.suffix.lower() == ".md"]
            self._notes = sorted(self.rel(p) for p in found)
        return self._notes

    def renames(self, repo: Path) -> List[Tuple[str, str]]:
        """(old, new) for every rename the repository's history holds, oldest
        first, both from the repository's top."""
        if repo not in self._renames:
            r = self.git(repo, "log", "--reverse", "-M", "--diff-filter=R", "--name-status", "--format=")
            pairs = []
            for line in r.stdout.splitlines() if r.returncode == 0 else []:
                parts = line.split("\t")
                if len(parts) == 3 and parts[0].startswith("R"):
                    pairs.append((parts[1], parts[2]))
            self._renames[repo] = pairs
        return self._renames[repo]


# ---------------------------------------------------------------------------
# Kinds: the registry
# ---------------------------------------------------------------------------

@dataclass
class Kind:
    name: str
    title: str                                        # the report's heading for it
    rank: int                                         # claims in this order, lowest first
    claim: Callable[[Ctx, Item], bool]
    what: str = ""                                    # what the skill does with one, in a few words
    gather: Optional[Callable[[Ctx], List[Item]]] = None
    apply: Optional[Callable[[Ctx, Item, "Journal"], str]] = None
    unattended: bool = False                          # the nightly run may apply it
    quiet: bool = False                               # low urgency: listed last, never in the morning digest
    say: Callable[[Item], str] = lambda item: "%s: %s" % (item.path, item.message)


KINDS: Dict[str, Kind] = {}


def register(kind: Kind) -> Kind:
    """Put a kind in the registry. A later one with the same name replaces it."""
    KINDS[kind.name] = kind
    return kind


def ranked() -> List[Kind]:
    return sorted(KINDS.values(), key=lambda k: (k.rank, k.name))


class Held(Exception):
    """A fix that cannot be applied as things stand, and why, in words."""


# ---------------------------------------------------------------------------
# Gathering: the existing tools, run as they run for anyone
# ---------------------------------------------------------------------------

def run_tool(ctx: Ctx, name: str, *args: str) -> Optional[object]:
    script = HERE / name
    try:
        r = subprocess.run([sys.executable, str(script), "--root", str(ctx.root), *args], capture_output=True,
                           text=True, timeout=1800, stdin=subprocess.DEVNULL)
        return json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        ctx.failed.append("%s %s: %s" % (name, " ".join(args), type(exc).__name__))
        return None


def strip_line(path: str) -> str:
    return re.sub(r":\d+$", "", path or "")


TODO_BROKEN = re.compile(r"^open actions name (.+), which lead to no live note")


def from_check(ctx: Ctx) -> List[Item]:
    found = run_tool(ctx, "check.py", "--json")
    out = []
    for f in (found or {}).get("findings", []) if isinstance(found, dict) else []:
        item = Item("check", f.get("check", ""), strip_line(f.get("path", "")), f.get("message", ""),
                    f.get("ear", ""), f.get("severity", "warning"))
        m = TODO_BROKEN.match(item.message)
        if item.check == "todo" and m:
            # One finding names every broken thread link; each is its own fix.
            for target in re.findall(r"\[\[([^\]]+)\]\]", m.group(1)):
                out.append(Item("check", "todo", item.path, "an open action names [[%s]], which leads to no live note"
                                % target, item.ear, item.severity, fix={"target": target}))
            continue
        out.append(item)
    return out


def from_wiki_lint(ctx: Ctx) -> List[Item]:
    out = []
    for wiki in WIKIS:
        if not (ctx.root / "Wikis" / wiki / "wiki").is_dir():
            continue
        found = run_tool(ctx, "wiki_lint.py", "--wiki", wiki, "--json")
        if not isinstance(found, dict):
            continue
        for page in found.get("orphans", []):
            out.append(Item("wiki-lint", "orphan", "Wikis/%s/%s.md" % (wiki, page),
                            "links to no other page, and no page links to it", "A %s page is cut off" % wiki))
        for miss in found.get("missing", []):
            for page in miss.get("linked_from", []):
                out.append(Item("wiki-lint", "missing", "Wikis/%s/%s.md" % (wiki, page),
                                "links [[%s]], a page that is not there" % miss["target"],
                                "A %s page links to a page that is not there" % wiki, fix={"target": miss["target"]}))
    return out


DRIFT_STATES = ("drifted", "missing", "conflict")
BEHIND = "behind"           # a share row whose copy here is behind the share: its own kind, not drift


def from_drift(ctx: Ctx) -> List[Item]:
    """What drift.py says now, in a session; with nobody watching, what it
    last saved, since a scheduled job cannot read a cloud folder."""
    if ctx.headless:
        try:
            files = json.loads(ctx.root.joinpath("System", "generated", "drift.json").read_text(encoding="utf-8"))["files"]
        except (OSError, ValueError, KeyError, TypeError):
            files = []
    else:
        files = run_tool(ctx, "drift.py", "--json") or []
    out = []
    for f in files if isinstance(files, list) else []:
        if not isinstance(f, dict) or f.get("state") not in DRIFT_STATES + (BEHIND,):
            continue
        base = "Zones/%s/%s" % (f.get("zone", ""), f.get("project", ""))
        if f.get("thread"):
            base += "/Threads/%s" % f["thread"]
        behind = f["state"] == BEHIND
        out.append(Item("drift", f["state"], base + "/Deliverables/published.md",
                        "%s: %s%s" % (f.get("file") or "published.md", f["state"], " (%s)" % f["say"] if f.get("say") else ""),
                        "A published file's copy here is behind the share" if behind
                        else "A published file has drifted from its shared copy", kind=BEHIND if behind else ""))
    return out


SOURCES: List[Callable[[Ctx], List[Item]]] = [from_check, from_wiki_lint, from_drift]


def gather(ctx: Ctx, scopes: List[str]) -> List[Item]:
    items: List[Item] = []
    for source in SOURCES:
        items += source(ctx)
    for kind in ranked():
        if kind.gather:
            for i in kind.gather(ctx):
                i.kind = i.kind or kind.name
                items.append(i)
    for item in items:
        if not item.kind:
            for kind in ranked():
                if kind.claim(ctx, item):
                    item.kind = kind.name
                    break
    return [i for i in items if in_scope(i, scopes)]


def in_scope(item: Item, scopes: List[str]) -> bool:
    if not scopes:
        return True
    paths = [item.path] + item.where
    return any(p == s or p.startswith(s.rstrip("/") + "/") for p in paths for s in scopes)


# ---------------------------------------------------------------------------
# The wall kind
# ---------------------------------------------------------------------------

WALL_RE = re.compile(r"a wall stands between (\S+) and (\S+?)[.;,]?$")
CROSS_ZONE_RE = re.compile(r"from zone (\S+?)[;,]|filed in zone (\S+?)[;,]")
WALL_WORDS = ("repeats eight or more words", "shares eight or more words", "a Meetings page", "across a wall",
              "which a wall keeps apart")


def claim_wall(ctx: Ctx, item: Item) -> bool:
    if item.source != "check":
        return False
    m = WALL_RE.search(item.message)
    if item.check == "walls" or m or any(w in item.message for w in WALL_WORDS):
        if m:
            item.wall = "%s and %s" % (m.group(1), m.group(2))
        else:
            pair = re.search(r"names both (\S+) and (\S+),", item.message) or \
                re.search(r"a meeting with (\S+), but is written for ([^,]+), across a wall", item.message)
            zone = CROSS_ZONE_RE.search(item.message)
            if pair:
                item.wall = "%s and %s" % pair.groups()
            elif zone:
                item.wall = "the %s zone" % (zone.group(1) or zone.group(2))
        item.message = ""          # never repeat the material, nor what matched it
        return True
    if item.check == "threads" and "differs from the project's" in item.message:
        m = re.search(r"`party` (.+) differs from the project's (.+)$", item.message)
        if m:
            a = [t.strip() for t in m.group(1).split(",")]
            b = [t.strip() for t in m.group(2).split(",")]
            hit = next(((x, y) for x in a for y in b if walled(ctx.context, x, y)), None)
            if hit:
                item.wall = "%s and %s" % hit
                item.message = ""
                return True
    return False


def say_wall(item: Item) -> str:
    if item.wall.startswith("the "):
        return "%s: material from %s, which a project uses only when asked" % (item.path, item.wall)
    if item.wall:
        return "%s: the wall between %s" % (item.path, item.wall)
    return "%s: %s" % (item.path, item.ear or "a wall finding")


register(Kind("wall", "Walls", 10, claim_wall, what="named with its file and its wall; taken out only on a yes",
              say=say_wall))


# ---------------------------------------------------------------------------
# The mechanical kind
# ---------------------------------------------------------------------------

# Words for a status that every tool reads as one of the three, and only these.
STATUS_WORDS = {
    "parked": ("paused", "pause", "on-hold", "on hold", "onhold", "hold", "dormant", "suspended", "deferred"),
    "done": ("closed", "complete", "completed", "finished"),
    "active": ("open", "live", "ongoing", "in-progress", "in progress", "wip"),
}
SYNONYM = {w: s for s, words in STATUS_WORDS.items() for w in words}
STATUS_RE = re.compile(r"^`status` is (['\"])(.*)\1, should be ")
UNLISTED_RE = re.compile(r"^does not link the thread (.+); the hub lists every thread$")
UNDATED = "name does not start with its creation date"
PARENT_RE = re.compile(r"^`parent: \[\[(.+)\]\]` leads to no live note$")
CODE_NOTE_RE = re.compile(r"^names `(.+)` as code; write it as a wikilink")
NO_PARENT = "no `parent:`, a link to its thread note or hub"
DATE_INSIDE = re.compile(r"(?<!\d)(?:\d{6}|\d{4}-\d{2}-\d{2}|\d{8})(?!\d)")
NOT_LIVE = re.compile(r"^(?:archive|build|render.*|specs|\..*|_.*)$", re.I)
LINK = re.compile(r"(!?\[\[)([^\[\]|#\n]+)((?:#[^\[\]|\n]*)?(?:\|[^\[\]\n]*)?\]\])")


def note_status(path: Path) -> str:
    try:
        return str(parse_frontmatter_text(path.read_text(encoding="utf-8")).get("status") or "").strip().lower()
    except OSError:
        return ""


def claim_mechanical(ctx: Ctx, item: Item) -> bool:
    try:
        fix = mechanical_fix(ctx, item)
    except Held as why:
        item.held = str(why)
        return False
    if fix is None:
        return False
    item.fix = fix
    return True


def mechanical_fix(ctx: Ctx, item: Item) -> Optional[dict]:
    """The one right fix for a finding, or None when it is not this kind's;
    Held when it would be, but the answer is not one."""
    path = ctx.root / item.path
    if item.source == "check" and item.check in ("projects", "threads"):
        m = STATUS_RE.match(item.message)
        if m:
            word = m.group(2).strip().lower()
            to = SYNONYM.get(word)
            if to is None:
                return None
            if to == "done" and item.check == "threads" and not re.search(r"(?mi)^### Outcome\s*$",
                                                                         path.read_text(encoding="utf-8")):
                return None        # a finish needs its outcome written: the user's, not this tool's
            item.touches = [item.path]
            return {"op": "status", "from": m.group(2), "to": to}
        m = UNLISTED_RE.match(item.message) if item.check == "projects" else None
        if m:
            thread = m.group(1)
            note = path.parent / "Threads" / thread / (thread + ".md")
            item.touches = [item.path]
            item.where = [ctx.rel(note.parent)]
            return {"op": "list-thread", "thread": thread,
                    "section": "Finished" if note_status(note) == "done" else "Threads"}
        return None
    if item.source == "check" and item.check == "deliverables" and item.message.startswith(UNDATED):
        return date_fix(ctx, item, path)
    if (item.source == "wiki-lint" and item.check == "missing") or (item.source == "check" and item.check == "todo"
                                                                    and item.fix and item.fix.get("target")):
        return relink_fix(ctx, item, path, item.fix["target"])
    if item.source == "check" and item.check == "links":
        m = PARENT_RE.match(item.message)
        if m:
            return relink_fix(ctx, item, path, m.group(1).strip())
        m = CODE_NOTE_RE.match(item.message)
        if m:
            return codelink_fix(ctx, item, m.group(1))
        if item.message.startswith(NO_PARENT):
            return parent_fix(ctx, item)
    return None


def date_fix(ctx: Ctx, item: Item, path: Path) -> dict:
    name = path.name
    if DATE_INSIDE.search(name):
        raise Held("a date already sits in the name; which date it is, and where it goes, is yours to say")
    repo = ctx.repo_of(path)
    if repo is None:
        raise Held("no repository holds it, so a rename could not be undone")
    rel = path.relative_to(repo).as_posix()
    args = ["log", "--format=%ad", "--date=format:%y%m%d"] + (["--follow"] if path.is_file() else []) + ["--", rel]
    dates = ctx.git(repo, *args).stdout.split()
    if not dates:
        raise Held("it has never been committed, so the day it was made is not on record")
    new = path.with_name("%s - %s" % (dates[-1], name))
    if new.exists():
        raise Held("%s is there already" % new.name)
    refs = referring(ctx, repo, name)
    if any(p.name == "published.md" for p in refs):
        raise Held("it is in a published.md, and the copy on the share keeps its name")
    item.touches = [item.path, ctx.rel(new)] + [ctx.rel(p) for p in refs]
    return {"op": "date", "to": new.name, "refs": [ctx.rel(p) for p in refs]}


def referring(ctx: Ctx, repo: Path, name: str) -> List[Path]:
    """The notes in a repository that link a file by its name, or name it in
    backticks."""
    out = []
    for f in sorted(ctx.tracked(repo)):
        if not f.endswith(".md") or "/raw/" in "/" + f:
            continue
        p = repo / f
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if name in text and rename_refs(text, name, "\0") != text:
            out.append(p)
    return out


def rename_refs(text: str, old: str, new: str) -> str:
    """`text` with each link to a file named `old`, and each name of it in
    backticks, pointed at `new`; the rest of the path stays as written."""
    stem_old = old[:-3] if old.endswith(".md") else None
    stem_new = new[:-3] if new.endswith(".md") else new

    def link(m):
        target = m.group(2)
        head, _, last = target.rpartition("/")
        if last.strip() == old:
            last = new
        elif stem_old is not None and last.strip() == stem_old:
            last = stem_new
        else:
            return m.group(0)
        return m.group(1) + (head + "/" if head else "") + last + m.group(3)

    text = LINK.sub(link, text)
    return re.sub(r"`([^`\n]*?)%s`" % re.escape(old), lambda m: "`%s%s`" % (m.group(1), new)
                  if not m.group(1) or m.group(1).endswith("/") else m.group(0), text)


def relink_fix(ctx: Ctx, item: Item, path: Path, target: str) -> Optional[dict]:
    """A link broken by a rename: the note it led to moved, and the
    repository's history names exactly one live note it moved to."""
    repo = ctx.repo_of(path)
    if repo is None:
        return None
    t = target.strip().rstrip("\\").strip()
    t = t[:-3] if t.endswith(".md") else t
    for head in ("Wikis/", "Zones/"):
        if t.startswith(head):
            t = t[len(head):]
            break
    found = set()
    for old, new in ctx.renames(repo):
        o = old[:-3] if old.endswith(".md") else old
        if not old.endswith(".md"):
            continue
        hit = o == t or o.endswith("/" + t) or ("/" not in t and o.rsplit("/", 1)[-1].lower() == t.lower())
        if hit:
            found.add(follow(ctx, repo, old))
    found.discard(None)
    if len(found) != 1:
        return None
    final = found.pop()
    if any(NOT_LIVE.match(part) for part in final.split("/")[:-1]):
        return None                # it moved into an archive: where the link should go now is a question
    f = final[:-3]
    if "/" not in t:
        stem = f.rsplit("/", 1)[-1]
        if sum(1 for x in ctx.tracked(repo) if x.endswith(".md") and x.rsplit("/", 1)[-1][:-3].lower() == stem.lower()) > 1:
            return None            # the bare name would land on more than one note
        to = stem
    else:
        depth = len(t.split("/"))
        to = "/".join(f.split("/")[-depth:]) if f.count("/") + 1 >= depth else f
    if to == t:
        return None
    item.touches = [item.path]
    return {"op": "relink", "target": target, "to": to}


def landing(ctx: Ctx, target: str) -> List[str]:
    """The live notes a wikilink to `target` lands on, matched as Obsidian
    matches it: every note whose path ends with the link's, with or without
    `.md`, in any case."""
    want = [x.lower() for x in target.split("/")]
    want[-1] = want[-1][:-3] if want[-1].endswith(".md") else want[-1]
    out = []
    for note in ctx.notes():
        have = note.lower()[:-3].split("/")
        if len(have) >= len(want) and have[-len(want):] == want:
            out.append(note)
    return out


def codelink_fix(ctx: Ctx, item: Item, ref: str) -> Optional[dict]:
    """A note path written as code, which the graph does not see: it becomes
    `[[ref]]` when that link would land on exactly one live note, in the
    note's own zone. None, several, a relative path or one into another zone
    is a question, so judgment."""
    parts = ref.split("/")
    if ref.startswith("/") or any(p in ("", ".", "..") for p in parts) or re.search(r"[\[\]|#^]", ref):
        return None                # no wikilink reads it as written
    hits = landing(ctx, ref)
    if len(hits) != 1 or hits[0].split("/")[:2] != item.path.split("/")[:2]:
        return None
    item.touches = [item.path]
    return {"op": "codelink", "ref": ref, "note": hits[0]}


def parent_fix(ctx: Ctx, item: Item) -> Optional[dict]:
    """A note inside `Threads/<Thread>/` with no `parent:` belongs to that
    thread: it gets `parent: "[[<Thread>]]"` when the thread note is live and
    no other live note shares its name. A note at the project's own level
    could belong to the hub or to any thread, so it is judgment; so is the
    thread note itself, whose parent is the hub. A file under a Deliverables/
    or Sources/ folder is never given one, a ledger's published.md among
    them (#169): its wording is final, or as received."""
    parts = item.path.split("/")
    if len(parts) < 6 or parts[0] != "Zones" or parts[3] != "Threads":
        return None
    thread, inner = parts[4], parts[5:]
    if inner == [thread + ".md"] or {"Deliverables", "Sources"} & set(inner[:-1]):
        return None
    if any(NOT_LIVE.match(p) for p in parts[1:5]):
        return None
    note = "/".join(parts[:5] + [thread + ".md"])
    if note not in ctx.notes() or len([n for n in ctx.notes() if n.rsplit("/", 1)[-1][:-3].lower() == thread.lower()]) != 1:
        return None                # no thread note, or [[<Thread>]] would land on another note too
    item.touches = [item.path]
    return {"op": "parent", "thread": thread}


def follow(ctx: Ctx, repo: Path, path: str) -> Optional[str]:
    """Where a renamed file ended up, through every later rename; None when
    nothing is there now."""
    seen = set()
    while path not in seen:
        seen.add(path)
        nxt = [new for old, new in ctx.renames(repo) if old == path]
        if not nxt:
            break
        path = nxt[-1]
    return path if (repo / path).is_file() else None


# Each op: (what it does, in words for the report and the commit, how it is done).
def apply_status(ctx: Ctx, item: Item, journal: "Journal") -> str:
    path = ctx.root / item.path
    text = path.read_text(encoding="utf-8")
    m = re.match(r"(---[^\n]*\n)(.*?)(\n(?:---|\.\.\.))", text, re.S)
    if not m:
        raise Held("its frontmatter does not read")
    head, n = re.subn(r"(?m)^status:[ \t]*.*$", "status: %s" % item.fix["to"], m.group(2), count=1)
    if not n:
        raise Held("it has no status line")
    journal.write(path, text[:m.start(2)] + head + text[m.end(2):])
    return "status %s is now %s" % (item.fix["from"], item.fix["to"])


def apply_list_thread(ctx: Ctx, item: Item, journal: "Journal") -> str:
    hub = ctx.root / item.path
    thread, section = item.fix["thread"], item.fix["section"]
    entry = "- [[%s/Threads/%s/%s|%s]]" % (hub.stem, thread, thread, thread)
    lines = hub.read_text(encoding="utf-8").split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## " + section.lower()), None)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "## " + section, "", entry, ""]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
        items = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("- ")]
        if items:
            lines.insert(items[-1] + 1, entry)
        else:
            lines[start + 1:start + 1] = ["", entry]
    journal.write(hub, "\n".join(lines))
    return "the hub lists the thread %s under %s" % (thread, section)


def apply_date(ctx: Ctx, item: Item, journal: "Journal") -> str:
    path = ctx.root / item.path
    new = path.with_name(item.fix["to"])
    journal.move(path, new)
    for ref in item.fix["refs"]:
        p = ctx.root / ref
        text = p.read_text(encoding="utf-8")
        journal.write(p, rename_refs(text, path.name, new.name))
    return "%s is now %s" % (path.name, new.name)


def apply_relink(ctx: Ctx, item: Item, journal: "Journal") -> str:
    path = ctx.root / item.path
    target, to = item.fix["target"], item.fix["to"]

    def one(m):
        written = m.group(2)
        bare = written.strip().rstrip("\\").strip()
        if re.sub(r"\.md$", "", bare) != re.sub(r"\.md$", "", target.strip()):
            return m.group(0)
        return m.group(1) + written.replace(bare, to + (".md" if bare.endswith(".md") else ""), 1) + m.group(3)

    text = path.read_text(encoding="utf-8")
    changed = LINK.sub(one, text)
    if changed == text:
        raise Held("the link is not there any more")
    journal.write(path, changed)
    return "[[%s]] now leads to [[%s]]" % (target, to)


def apply_codelink(ctx: Ctx, item: Item, journal: "Journal") -> str:
    path = ctx.root / item.path
    ref = item.fix["ref"]
    text = path.read_text(encoding="utf-8")
    body = len(text) - len(body_text(text))
    ticked = re.compile(r"(?<!`)`%s`(?!`)" % re.escape(ref))
    lines, fence = text[body:].split("\n"), False
    for n, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence:
            lines[n] = ticked.sub(lambda m: "[[%s]]" % ref, line)
    changed = text[:body] + "\n".join(lines)
    if changed == text:
        raise Held("the path is not written as code there any more")
    journal.write(path, changed)
    return "`%s` is now [[%s]]" % (ref, ref)


def body_text(text: str) -> str:
    """`text` without its frontmatter, as check.py reads a note's body."""
    m = re.match(r"---[^\n]*\n.*?\n(?:---|\.\.\.)[^\n]*(?:\n|$)", text, re.S) if text.startswith("---") else None
    return text[m.end():] if m else text


def apply_parent(ctx: Ctx, item: Item, journal: "Journal") -> str:
    path = ctx.root / item.path
    line = 'parent: "[[%s]]"' % item.fix["thread"]
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        journal.write(path, "---\n%s\n---\n%s" % (line, text))
    else:
        m = re.match(r"(---[^\n]*\n)(.*?)(\n(?:---|\.\.\.))", text, re.S)
        if not m:
            raise Held("its frontmatter does not read")
        if re.search(r"(?m)^parent:", m.group(2)):
            raise Held("it has a parent line already")
        journal.write(path, text[:m.end(2)] + "\n" + line + text[m.end(2):])
    return "parent is now [[%s]]" % item.fix["thread"]


OPS: Dict[str, Callable[[Ctx, Item, "Journal"], str]] = {
    "status": apply_status, "list-thread": apply_list_thread, "date": apply_date, "relink": apply_relink,
    "codelink": apply_codelink, "parent": apply_parent}
OP_WORDS = {"status": ("status word", "status words"), "list-thread": ("hub list", "hub lists"),
            "date": ("date prefix", "date prefixes"), "relink": ("link", "links"),
            "codelink": ("path made a link", "paths made links"), "parent": ("parent link", "parent links")}


def apply_mechanical(ctx: Ctx, item: Item, journal: "Journal") -> str:
    return OPS[item.fix["op"]](ctx, item, journal)


def say_mechanical(item: Item) -> str:
    f = item.fix or {}
    what = {"status": lambda: "status %s becomes %s" % (f.get("from"), f.get("to")),
            "list-thread": lambda: "add the thread %s under ## %s" % (f.get("thread"), f.get("section")),
            "date": lambda: "rename it %s" % f.get("to"),
            "relink": lambda: "[[%s]] becomes [[%s]]" % (f.get("target"), f.get("to")),
            "codelink": lambda: "`%s` becomes [[%s]]" % (f.get("ref"), f.get("ref")),
            "parent": lambda: 'add parent: "[[%s]]"' % f.get("thread")}.get(f.get("op"))
    line = "%s: %s" % (item.path, item.said or (what() if what else item.message))
    return line + (" (held: %s)" % item.held if item.held and not item.said else "")


register(Kind("mechanical", "Mechanical", 20, claim_mechanical, what="listed, then applied on one yes",
              apply=apply_mechanical, unattended=True, say=say_mechanical))


# ---------------------------------------------------------------------------
# The attribution kind
# ---------------------------------------------------------------------------

def claim_attribution(ctx: Ctx, item: Item) -> bool:
    if item.source != "check":
        return False
    msg, c = item.message, item.check
    name = Path(item.path).stem
    q = None
    if c == "meetings":
        if msg.startswith("unfinished: no "):
            q = "Which %s does %s belong to?" % ("zone and parties" if "zone or parties" in msg else msg[15:].split(";")[0], name)
            item.proposal = meeting_zone(ctx, item)
        elif "is not a zone" in msg:
            q = "Which zone is %s?" % name
        elif "is not a tag in the Parties table" in msg:
            q = "Which party is %s on %s?" % (msg.split("`")[1], name)
        elif msg.startswith("`type` is"):
            q = "Is %s a meeting or an email?" % name
        elif "split-with" in msg:
            q = "Are %s and the pages that share its record one conversation filed twice, or a split?" % name
    elif c == "people":
        if msg.startswith("no `party`") or "is not a tag in the Parties table" in msg:
            q = "Which party does %s belong to?" % name
            item.proposal = person_party(ctx, item)
        elif msg.startswith("`type` is"):
            q = "Is %s a person page?" % name
    elif c in ("projects", "threads") and STATUS_RE.match(msg):
        what = Path(item.path).parent.name if c == "projects" else name
        q = "%s has the status %s; is it active, parked or done?" % (what, STATUS_RE.match(msg).group(2))
    elif c == "projects":
        if msg.startswith("no `party`") or "is not a tag in the Parties table" in msg:
            q = "Which party is the project %s for?" % Path(item.path).parent.name
        elif "frontmatter `zone` is" in msg:
            q = "The hub of %s names another zone than the one it sits in; which is it?" % Path(item.path).parent.name
        elif "is not listed under `## Finished`" in msg:
            thread = re.search(r"finished thread (.+) is not listed", msg).group(1)
            q = "%s is done; move it under Finished in its hub?" % thread
            item.proposal = "move it under ## Finished"
    elif c == "threads":
        if "differs from the project's" in msg:
            q = "%s names another party than its project; which is it?" % name
            m = re.search(r"differs from the project's (.+)$", msg)
            item.proposal = m.group(1) if m else ""
        elif "status is done but there is no `### Outcome`" in msg:
            q = "%s is marked done with no outcome; what did it deliver, or is it still active?" % name
        elif msg.startswith("`project` is"):
            q = "%s points at another project than the one it sits in; which is it?" % name
    elif c == "todo" and item.fix and item.fix.get("target"):
        q = "Which thread do the actions naming [[%s]] belong to now?" % item.fix["target"]
        item.fix = None
    elif c == "knowledge":
        if msg.startswith("carries "):
            q = "%s carries a party or a zone; is it published reading, or a conversation for Meetings?" % name
        elif "schema" in msg or msg.startswith("`type: "):
            q = "What kind of page is %s?" % name
    elif c == "sources" and "no finished page in Meetings" in msg:
        q = "%s came by mail that is not filed yet; file the mail as a conversation first?" % Path(item.path).name
    if q is None:
        return False
    item.question = q
    return True


def meeting_zone(ctx: Ctx, item: Item) -> str:
    """The zone every party on a page belongs to, when they all agree."""
    try:
        fm = parse_frontmatter_text((ctx.root / item.path).read_text(encoding="utf-8"))
    except OSError:
        return ""
    if fm.get("zone"):
        return ""
    tags = fm.get("parties") or []
    tags = [strip_tag(str(t)) for t in (tags if isinstance(tags, list) else [tags])]
    zones = {ctx.context["parties"].get(t, {}).get("zone") for t in tags}
    return "zone %s, from its parties" % zones.pop() if tags and len(zones) == 1 and None not in zones and "" not in zones else ""


def person_party(ctx: Ctx, item: Item) -> str:
    """The party the People table gives a person, when it gives one: someone
    with a row on each side of a wall gets no proposal."""
    try:
        fm = parse_frontmatter_text((ctx.root / item.path).read_text(encoding="utf-8"))
    except OSError:
        return ""
    name = str(fm.get("title") or Path(item.path).stem.replace("-", " ")).strip().lower()
    parties = {p["party"] for p in ctx.context["people"] if p["name"].strip().lower() == name and p["party"]}
    return parties.pop() if len(parties) == 1 else ""


def say_attribution(item: Item) -> str:
    return "%s: %s%s" % (item.path, item.question, " Proposed: %s." % item.proposal if item.proposal else "")


register(Kind("attribution", "Attribution and category", 30, claim_attribution,
              what="proposed and asked, one line each", say=say_attribution))


# ---------------------------------------------------------------------------
# The correction kind: correct.py's, called from here
# ---------------------------------------------------------------------------
#
# No check finds a wrong value: a person says the right one. So a correction
# is never gathered and never claimed. It enters on the `correct` verb, with
# the two values the user gave, and becomes one finding: every live copy
# `correct.find_hits` finds. On the yes, `correct.apply` writes them and
# commits once per repository. Nurture adds only what it adds to every kind:
# a scope's walls, the files another session has changes in, and the report.
# A copy across a wall from the scope, or whose parties cannot be told, is
# left out without a trace: the run says the rule's sentence, WALL_REFUSAL,
# once, and nothing of its file, its party or how many there were.
# The kind has no `apply` for the registry's machine, which holds a fix whose
# files span two repositories or none; a correction usually does, since the
# copies of one value sit in a zone, a wiki and a memory kept outside both. So
# `fix --yes` and `nightly` never apply one.

LINK_HEAD = re.compile(r"\[\[([^\]|#/\n]+)")


def tags_of(value) -> set:
    values = value if isinstance(value, list) else [value] if value else []
    return {strip_tag(str(v)) for v in values if str(v).strip()}


def note_tags(path: Path, *keys: str) -> set:
    try:
        fm = parse_frontmatter_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return set()
    out = set()
    for key in keys:
        out |= tags_of(fm.get(key))
    return out


def parties_at(ctx: Ctx, rel: str) -> set:
    """The party tags a path is written for: a project's or thread's, a wiki
    page's, or, for a zone, every project's in it. Empty when none is said."""
    parts = rel.split("/")
    if parts[0] == "Zones" and len(parts) == 2:
        zone = ctx.root / rel
        return set().union(*(note_tags(p / (p.name + ".md"), "party") for p in zone.iterdir() if p.is_dir())) \
            if zone.is_dir() else set()
    if parts[0] in ("Zones", "System") and len(parts) >= (3 if parts[0] == "Zones" else 2):
        project = ctx.root.joinpath(*parts[:3 if parts[0] == "Zones" else 2])
        tags = note_tags(project / (project.name + ".md"), "party")
        if len(parts) > (4 if parts[0] == "Zones" else 3) and parts[(3 if parts[0] == "Zones" else 2)] == "Threads":
            thread = project / "Threads" / parts[(4 if parts[0] == "Zones" else 3)]
            tags |= note_tags(thread / (thread.name + ".md"), "party")
        return tags
    if parts[0] == "Wikis" and rel.endswith(".md"):
        return note_tags(ctx.root / rel, "parties", "party")
    return set()


def hit_parties(ctx: Ctx, hit) -> Optional[set]:
    """The parties one of correct's hits is written for; None when it cannot
    be told, as for a raw record no page rests on."""
    rel = ctx.rel(hit.path)
    if hit.kind in ("memory", "context"):
        return set()                      # the user's own, across the workspace
    if hit.kind == "todo":
        zone = hit.path.parent
        return set().union(set(), *(note_tags(zone / name / (name + ".md"), "party")
                                    for _, text in hit.lines for name in LINK_HEAD.findall(text)))
    if hit.kind == "raw":
        return set().union(*(parties_at(ctx, ctx.rel(p)) for p in hit.pages)) if hit.pages else None
    return parties_at(ctx, rel)


def inside(rel: str, scopes: List[str]) -> bool:
    return any(rel == s or rel.startswith(s.rstrip("/") + "/") for s in scopes)


def sort_hits(ctx: Ctx, hits: list, scopes: List[str]) -> Tuple[list, List[Item], bool]:
    """correct's hits, sorted for this run: those to apply; a held finding for
    each one in a file another session has changes in; and whether any was
    left out, across a wall from the scope or with parties nobody can tell.
    What was left out is not kept, so nothing can say it."""
    ours = set().union(set(), *(parties_at(ctx, s) for s in scopes))
    go, held, withheld = [], [], False
    state: Dict[Path, Optional[set]] = {}
    for hit in hits:
        rel = ctx.rel(hit.path)
        if ours and not inside(rel, scopes):
            theirs = hit_parties(ctx, hit)
            if theirs is None or any(walled(ctx.context, a, b) for a in ours for b in theirs):
                withheld = True
                continue
        files = [hit.path] if hit.kind != "raw" else list(hit.pages)
        why = ""
        for f in files:
            repo = hit.repo if f == hit.path else correct.repo_of(f)
            if repo is None:
                continue                  # a memory outside any repository: changed, reported not committed
            if repo not in state:
                state[repo] = dirty(ctx, repo)
            try:
                r = f.resolve().relative_to(repo).as_posix()
            except ValueError:
                continue
            if state[repo] is None:
                why = "its repository is mid-merge or could not be read"
            elif r in state[repo] or r not in ctx.tracked(repo):
                why = "%s has changes not committed, or is not committed at all" % f.name
            elif busy(ctx, f.parent):
                why = "a session is mid-turn there"
            if why:
                break
        if why:
            held.append(Item("correct", "correction", rel, "holds the value being corrected", kind="correction",
                             held=why))
            continue
        go.append(hit)
    return go, held, withheld


def correction_item(ctx: Ctx, old: str, new: str, go: list, path: str = "") -> Item:
    live = [h for h in go if h.kind != "raw"]
    pages = sorted({ctx.rel(p) for h in go if h.kind == "raw" for p in h.pages})
    item = Item("correct", "correction", path or (ctx.rel(live[0].path) if live else ""),
                "%s to %s" % (old, new), kind="correction")
    item.where = [ctx.rel(h.path) for h in go]
    item.touches = [ctx.rel(h.path) for h in live] + pages
    item.fix = {"op": "correct", "old": old, "new": new, "files": [ctx.rel(h.path) for h in live],
                "raw": [ctx.rel(h.path) for h in go if h.kind == "raw"], "superseded": pages}
    return item


def say_correction(item: Item) -> str:
    f = item.fix or {}
    if f.get("op") != "correct":
        return "%s: %s%s" % (item.path, item.message, " (held: %s)" % item.held if item.held else "")
    files = f.get("files", [])
    line = 'Correct "%s" to "%s": %s' % (f["old"], f["new"], plural(len(files), "file") if files else "no live file")
    if files:
        line += " (%s)" % ", ".join(files)
    if f.get("raw"):
        them = "them" if len(f["raw"]) > 1 else "it"
        line += "; %s kept as %s, %s" % (plural(len(f["raw"]), "raw record"), "they are" if them == "them" else "it is",
                                         "the pages resting on %s marked superseded" % them if f.get("superseded")
                                         else "no page rests on %s" % them)
    if item.said:
        line += "; %s" % item.said
    return line


register(Kind("correction", "Corrections", 25, lambda ctx, item: False,
              what="every live copy of a wrong value, as one finding, corrected on one yes", say=say_correction))


def run_correction(ctx: Ctx, scopes: List[str], old: str, new: str, yes: bool, why: str = "",
                   leave: Optional[List[str]] = None, path: str = "") -> dict:
    """A correction the user gave, as one finding: listed, and on `yes`
    applied by correct.py, which commits once per repository. Recorded in the
    day's report: what it fixed, the yes, and what a wall or another
    session's changes held back."""
    if not new or not new.strip():
        raise ValueError("Say what it should be: --new cannot be empty.")
    if old == new:
        raise ValueError("The old value and the new one are the same; nothing to correct.")
    hits = correct.find_hits(ctx.root, old, new)
    left_out = {(ctx.root / Path(p).expanduser()).resolve() for p in leave or []}
    hits = [h for h in hits if h.path.resolve() not in left_out]
    go, held, withheld = sort_hits(ctx, hits, scopes)
    item = correction_item(ctx, old, new, go, path)
    out = {"old": old, "new": new, "item": item, "hits": correct.listing(go, ctx.root), "held": held, "done": None,
           "wall": WALL_REFUSAL if withheld else ""}
    rec = read_record(ctx)
    rec["runs"].append({"at": datetime.datetime.now().strftime("%H:%M"), "scope": scope_key(scopes),
                        "headless": ctx.headless})
    key = scope_key(scopes)
    leftover = list(held)
    if yes and go:
        done = correct.apply(ctx.root, old, new, go, why=why, today=ctx.today.isoformat())
        out["done"] = done
        item.said = "%s in %s" % (plural(len(done.commits), "commit"), ", ".join(r for r, _ in done.commits)) \
            if done.commits else "nothing committed"
        for repo, sha in done.commits:
            here = [c for c in done.changed if repo == "." or c.startswith(repo + "/")]
            if repo == ".":
                here = [c for c in here if not any(c.startswith(r + "/") for r, _ in done.commits if r != ".")]
            rec["fixed"].append({"line": '"%s" is now "%s" in %s' % (old, new, ", ".join(here)), "path": item.path,
                                 "commit": sha, "repo": repo_label(ctx, ctx.root / repo)})
        for p, reason in done.uncommitted:
            rec["fixed"].append({"line": '"%s" is now "%s" in %s, %s' % (old, new, p, reason), "path": p,
                                 "commit": "not committed", "repo": "none"})
        for repo, reason in done.refused:
            leftover.append(Item("correct", "correction", repo, "the commit was refused: %s; the files stay changed, "
                                 "not committed" % reason, kind="correction"))
        rec["answered"].append({"path": item.path, "asked": "Correct \"%s\" to \"%s\" in %s?"
                                % (old, new, plural(len(item.fix["files"]), "file")),
                                "answer": "yes" + (", %s" % why.strip() if why.strip() else "")})
    elif go:
        leftover.insert(0, item)
    mine = 'Correct "%s" to "%s"' % (old, new)
    now = [stored(i) for i in leftover]
    rec["left"][key] = [i for i in rec["left"].get(key, []) if not i.get("line", "").startswith(mine) and i not in now] + now
    out["report"] = write_report(ctx, rec)
    return out


# ---------------------------------------------------------------------------
# The judgment kind: everything no other kind claims
# ---------------------------------------------------------------------------

def say_judgment(item: Item) -> str:
    return "%s: %s%s" % (item.path, item.message, " (held: %s)" % item.held if item.held else "")


register(Kind("judgment", "Judgment", 1000, lambda ctx, item: True, what="reported, with the page to open",
              say=say_judgment))


# ---------------------------------------------------------------------------
# Behind the share: low urgency, after everything else
# ---------------------------------------------------------------------------
#
# A `share` row says colleagues edit the file on the share, so the copy here
# is a snapshot, and it falls behind on every save there. That is what the
# ledger predicts, not drift. Ranked after judgment, it claims nothing: the
# drift source names it on the finding.

register(Kind(BEHIND, "Behind the share", 1100, lambda ctx, item: False,
              what="the shared copy is the one that counts, so nothing to fix", quiet=True, say=say_judgment))

# A kind in a module of its own is imported here, after the four, so it can
# call register() and take its rank among them.


# ---------------------------------------------------------------------------
# Applying: the journal, the safety checks, one commit per repository
# ---------------------------------------------------------------------------

class Journal:
    """Every change a run makes, so a fix whose commit was refused can be put
    back exactly as it was."""

    def __init__(self):
        self.steps: List[Tuple[str, Path, object]] = []

    def write(self, path: Path, text: str) -> None:
        self.steps.append(("write", path, path.read_bytes() if path.exists() else None))
        path.write_text(text, encoding="utf-8")

    def move(self, old: Path, new: Path) -> None:
        if new.exists():
            raise Held("%s is there already" % new.name)
        os.rename(str(old), str(new))
        self.steps.append(("move", new, old))

    def mark(self) -> int:
        return len(self.steps)

    def rollback(self, to: int = 0) -> None:
        while len(self.steps) > to:
            what, path, before = self.steps.pop()
            if what == "write":
                if before is None:
                    path.unlink()
                else:
                    path.write_bytes(before)
            else:
                os.rename(str(path), str(before))


def busy(ctx: Ctx, folder: Path) -> bool:
    """Whether a cmux tab is mid-turn in the folder, as scaffold.py asks."""
    try:
        from scaffold import mid_turn
        return mid_turn(ctx.root, folder)
    except Exception:
        return False


def dirty(ctx: Ctx, repo: Path) -> Optional[set]:
    """The paths, from the repository's top, that git reports as changed or
    untracked; None when the repository is mid-merge or cannot be read."""
    gitdir = repo / ".git"
    if any((gitdir / m).exists() for m in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD")):
        return None
    r = ctx.git(repo, "status", "--porcelain", "-z", "--untracked-files=all")
    if r.returncode != 0:
        return None
    out, parts = set(), r.stdout.split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        if len(entry) > 3:
            out.add(entry[3:])
            if entry[0] in "RC":
                i += 1
                out.add(parts[i])
        i += 1
    return out


def hold_unsafe(ctx: Ctx, items: List[Item]) -> Dict[Path, List[Item]]:
    """Each fix that may go ahead, by its repository. A fix is held when no
    repository holds its files, or they span two, or any of them has changes
    not committed or is not tracked, since a commit of it would carry someone
    else's work; or a session is mid-turn in its folder."""
    by_repo: Dict[Path, List[Item]] = {}
    state: Dict[Path, Optional[set]] = {}
    for item in items:
        paths = [ctx.root / p for p in (item.touches or [item.path])]
        repos = {ctx.repo_of(p) for p in paths}
        if None in repos or len(repos) != 1:
            item.held = "no one repository holds its files, so it could not be undone" if None in repos \
                else "its files are in two repositories"
            continue
        repo = repos.pop()
        if repo not in state:
            state[repo] = dirty(ctx, repo)
        if state[repo] is None:
            item.held = "its repository is mid-merge or could not be read"
            continue
        tracked = ctx.tracked(repo)
        bad = []
        for p in paths:
            r = p.relative_to(repo).as_posix()
            if p.is_dir():
                inside = [t for t in tracked if t.startswith(r + "/")]
                if not inside or any(d == r or d.startswith(r + "/") for d in state[repo]):
                    bad.append(p.name)
            elif p.exists() and (r not in tracked or r in state[repo]):
                bad.append(p.name)
        if bad:
            item.held = "%s has changes not committed, or is not committed at all" % ", ".join(bad)
            continue
        if busy(ctx, (ctx.root / item.path).parent):
            item.held = "a session is mid-turn there"
            continue
        by_repo.setdefault(repo, []).append(item)
    return by_repo


def apply(ctx: Ctx, items: List[Item]) -> dict:
    """Apply every fix of an applying kind among `items`, one commit per
    repository, of the files the fixes changed and nothing else. In a run
    with nobody watching, only the kinds registered as unattended."""
    wanted = [i for i in items if i.kind in KINDS and KINDS[i.kind].apply and i.fix
              and (KINDS[i.kind].unattended or not ctx.headless)]
    seen, unique = set(), []
    for i in wanted:
        key = (i.kind, i.path, json.dumps(i.fix, sort_keys=True))
        if key not in seen:
            seen.add(key)
            unique.append(i)
    done = {"fixed": [], "held": [], "commits": [], "refused": []}
    by_repo = hold_unsafe(ctx, unique)
    done["held"] = [i for i in unique if i.held]
    journal = Journal()
    for repo, group in sorted(by_repo.items()):
        start = journal.mark()
        applied = []
        for item in group:
            mark = journal.mark()
            try:
                item.said = KINDS[item.kind].apply(ctx, item, journal)
                applied.append(item)
            except (Held, OSError, KeyError) as why:
                journal.rollback(mark)
                item.held = str(why) if isinstance(why, Held) else "%s: %s" % (type(why).__name__, why)
                done["held"].append(item)
        if not applied:
            continue
        paths = sorted({(ctx.root / t).relative_to(repo).as_posix() for i in applied for t in (i.touches or [i.path])})
        paths = [p for p in paths if (repo / p).exists() or known(ctx, repo, p)]   # a path moved away: git has it
        message = commit_message(ctx, repo, applied)
        add = ctx.git(repo, "add", "-A", "--", *paths)
        c = ctx.git(repo, "commit", "-q", "-m", message, "--", *paths) if add.returncode == 0 else add
        if c.returncode != 0:
            ctx.git(repo, "reset", "-q", "--", *paths)
            journal.rollback(start)
            why = (c.stderr or c.stdout).strip().splitlines()
            reason = "the commit was refused: %s" % (why[-1] if why else "git said no more")
            for item in applied:
                item.held, item.said = reason, ""
            done["held"] += applied
            done["refused"].append({"repo": ctx.rel(repo) or ".", "why": reason})
            continue
        sha = ctx.git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
        done["commits"].append({"repo": ctx.rel(repo) or ".", "commit": sha, "paths": paths, "message": message})
        for item in applied:
            item.fix = dict(item.fix, commit=sha)
            done["fixed"].append(item)
    return done


def known(ctx: Ctx, repo: Path, rel: str) -> bool:
    """Whether git tracks the path, or a file under it."""
    return any(t == rel or t.startswith(rel + "/") for t in ctx.tracked(repo))


def repo_label(ctx: Ctx, repo: Path) -> str:
    r = ctx.rel(repo)
    return r.split("/", 1)[1] if r.startswith("Zones/") else (r or "Workspace")


def counted(items: List[Item]) -> str:
    counts: Dict[str, int] = {}
    for i in items:
        op = (i.fix or {}).get("op", i.kind)
        counts[op] = counts.get(op, 0) + 1
    return ", ".join("%d %s" % (n, OP_WORDS.get(op, (op, op))[0 if n == 1 else 1]) for op, n in sorted(counts.items()))


def commit_message(ctx: Ctx, repo: Path, applied: List[Item]) -> str:
    head = "%s: context nurtured; %s" % (repo_label(ctx, repo), counted(applied))
    return head + "\n\n" + "\n".join("- %s" % i.line() for i in applied)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def record_path(ctx: Ctx) -> Path:
    return ctx.root.joinpath(*REPORTS) / ("%s.json" % ctx.today.isoformat())


def read_record(ctx: Ctx) -> dict:
    try:
        rec = json.loads(record_path(ctx).read_text(encoding="utf-8"))
        if isinstance(rec, dict):
            return rec
    except (OSError, ValueError):
        pass
    return {"date": ctx.today.isoformat(), "runs": [], "fixed": [], "answered": [], "left": {}}


def scope_key(scopes: List[str]) -> str:
    return ", ".join(scopes) if scopes else "the workspace"


def write_report(ctx: Ctx, rec: dict) -> Path:
    folder = ctx.root.joinpath(*REPORTS)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = record_path(ctx).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, record_path(ctx))
    md = folder / ("%s.md" % ctx.today.isoformat())
    md.write_text(render(rec), encoding="utf-8")
    return md


def render(rec: dict) -> str:
    out = ["# Context nurture, %s" % rec["date"], ""]
    runs = rec.get("runs", [])
    if runs:
        out += ["Runs: %s." % "; ".join("%s, %s%s" % (r["at"], r["scope"], ", nobody watching" if r.get("headless") else "")
                                         for r in runs), ""]
    out += ["## Fixed", ""]
    out += ["- %s (%s, %s)" % (f["line"], f["repo"], f["commit"]) for f in rec.get("fixed", [])] or ["Nothing."]
    out += ["", "## Asked and answered", ""]
    out += ["- %s: %s Answer: %s." % (a["path"], a["asked"], a["answer"]) for a in rec.get("answered", [])] or ["Nothing."]
    out += ["", "## Left", ""]
    left = rec.get("left", {})
    if not any(left.values()):
        out.append("Nothing.")
    for scope, items in left.items():
        out += ["### %s" % (scope[:1].upper() + scope[1:]), ""]
        if not items:
            out += ["Nothing.", ""]
            continue
        for kind in ranked():
            mine = [i for i in items if i["kind"] == kind.name]
            if mine:
                out += ["%s, %d: %s." % (kind.title, len(mine), kind.what), ""]
                out += ["- %s" % i["line"] for i in mine] + [""]
        other = [i for i in items if i["kind"] not in KINDS]
        out += ["- %s" % i["line"] for i in other] + ([""] if other else [])
    if rec.get("failed"):
        out += ["", "## Not run", ""] + ["- %s" % f for f in rec["failed"]]
    return "\n".join(out).rstrip() + "\n"


def stored(item: Item) -> dict:
    d = {"kind": item.kind, "path": item.path, "line": item.line()}
    if item.kind != "wall":
        d["check"] = item.check
    return d


def record_run(ctx: Ctx, scopes: List[str], items: List[Item], done: Optional[dict] = None) -> Path:
    rec = read_record(ctx)
    rec["runs"].append({"at": datetime.datetime.now().strftime("%H:%M"), "scope": scope_key(scopes),
                        "headless": ctx.headless})
    fixed = done["fixed"] if done else []
    for item in fixed:
        rec["fixed"].append({"line": item.line(), "path": item.path, "commit": item.fix.get("commit", ""),
                             "repo": repo_label(ctx, ctx.repo_of(ctx.root / item.path) or ctx.root)})
    fixed_ids = {id(i) for i in fixed}
    rec["left"][scope_key(scopes)] = [stored(i) for i in items if id(i) not in fixed_ids]
    rec["failed"] = sorted(set(ctx.failed))        # the last run's: a source that runs again is not left named
    return write_report(ctx, rec)


# ---------------------------------------------------------------------------
# Saying it
# ---------------------------------------------------------------------------

def by_kind(items: List[Item]) -> List[Tuple[Kind, List[Item]]]:
    return [(k, [i for i in items if i.kind == k.name]) for k in ranked() if any(i.kind == k.name for i in items)]


def say_text(items: List[Item], scopes: List[str]) -> str:
    if not items:
        return "Nothing to nurture in %s." % scope_key(scopes)
    out = ["%s to nurture in %s." % (plural(len(items), "finding"), scope_key(scopes))]
    for kind, mine in by_kind(items):
        out += ["", "%s, %d: %s" % (kind.title, len(mine), kind.what)]
        out += ["  %s" % i.line() for i in mine]
    return "\n".join(out)


SPOKEN = {"wall": ("one wall", "%d walls"), "mechanical": ("one fix ready", "%d fixes ready"),
          "correction": ("one correction", "%d corrections"),
          "attribution": ("one question", "%d questions"), "judgment": ("one thing to read", "%d things to read"),
          BEHIND: ("one copy behind the share", "%d copies behind the share")}


def say_ear(items: List[Item], scopes: List[str]) -> str:
    where = "the workspace" if not scopes else "that"
    if not items:
        return "Nothing to nurture in %s." % where
    parts = []
    for kind, mine in by_kind(items):
        one, many = SPOKEN.get(kind.name, ("one %s" % kind.title.lower(), "%d " + kind.title.lower()))
        parts.append(one if len(mine) == 1 else many % len(mine))
    said = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
    out = "In %s: %s." % (where, said)
    if any(i.kind == "mechanical" for i in items):
        out += " The fixes go in on one yes."
    return out


def plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "es" if word.endswith(("x", "s")) else "s")


def waiting(done: dict, items: List[Item]) -> Dict[str, int]:
    """{kind: how many} of what a run left for a person, but the quiet kinds:
    a pass lists them, the morning line does not."""
    fixed_ids = {id(i) for i in done["fixed"]}
    waits: Dict[str, int] = {}
    for i in items:
        if id(i) not in fixed_ids and not (i.kind in KINDS and KINDS[i.kind].quiet):
            waits[i.kind] = waits.get(i.kind, 0) + 1
    return waits


def digest(ctx: Ctx, done: dict, items: List[Item]) -> str:
    """One line for the morning: what was fixed first, then what waits."""
    fixed = done["fixed"]
    when = " overnight" if ctx.headless else ""
    waits = waiting(done, items)
    if fixed:
        repos = {}
        for i in fixed:
            label = repo_label(ctx, ctx.repo_of(ctx.root / i.path) or ctx.root)
            repos[label] = repos.get(label, 0) + 1
        head = "Fixed %d%s (%s): %s." % (len(fixed), when, ", ".join("%s %d" % kv for kv in sorted(repos.items())),
                                       counted(fixed))
    else:
        head = "Nothing needed fixing%s." % when
    if done["refused"]:
        head += " A commit was refused in %s; those fixes were put back." % ", ".join(r["repo"] for r in done["refused"])
    if not waits:
        return head
    parts = [SPOKEN.get(k, ("one %s" % k, "%d " + k))[0 if n == 1 else 1].replace("%d", str(n)).replace(" ready", " held")
             for k, n in sorted(waits.items(), key=lambda kv: KINDS[kv[0]].rank if kv[0] in KINDS else 999)]
    return head + " Waiting for you: %s. Say \"nurture the context\"." % ", ".join(parts)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def resolve_scopes(root: Path, given: List[str]) -> List[str]:
    out = []
    for s in given or []:
        p = Path(s).expanduser()
        p = p if p.is_absolute() else root / p
        if not p.exists():
            raise FileNotFoundError("there is no %s in the workspace" % s)
        out.append(p.resolve().relative_to(root).as_posix())
    return out


def item_json(item: Item) -> dict:
    d = asdict(item)
    if item.kind == "wall":
        d["message"] = ""
    d["line"] = item.line()
    return d


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Sort the workspace's findings by what a fix needs; apply the mechanical ones on a yes.")
    ap.add_argument("action", nargs="?", default="list", choices=("list", "fix", "nightly", "answered", "correct"))
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    ap.add_argument("--scope", action="append", default=[], help="a zone, project, thread or wiki, from the workspace's top")
    ap.add_argument("--yes", action="store_true", help="fix, correct: apply them; without it, only say what would change")
    fmt = ap.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true")
    fmt.add_argument("--ear", action="store_true", help="at most three short sentences, for reading aloud")
    ap.add_argument("--path", help="answered, correct: the file the question or the finding was about")
    ap.add_argument("--asked", help="answered: the question, as asked")
    ap.add_argument("--answer", help="answered: the user's answer")
    ap.add_argument("--old", help="correct: the wrong value, as written")
    ap.add_argument("--new", help="correct: what the user says it is")
    ap.add_argument("--why", default="", help="correct: why, in a few words, for the commit")
    ap.add_argument("--leave", action="append", default=[], metavar="PATH", help="correct: a file to leave as it is")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    try:
        root = Path(a.root).expanduser().resolve() if a.root else workspace_root(HERE)
        if not (root / "System" / "rules.md").is_file():
            root = workspace_root(root)
        scopes = resolve_scopes(root, a.scope)
    except FileNotFoundError as exc:
        print("nurture: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    headless = a.action == "nightly" or os.environ.get("GARRICK_HEADLESS") == "1"
    ctx = Ctx(root, headless=headless, today=datetime.date.fromisoformat(a.today) if a.today else None)

    if a.action == "answered":
        if not (a.path and a.asked and a.answer):
            print("nurture: answered needs --path, --asked and --answer", file=sys.stderr)
            return EXIT_USAGE
        rec = read_record(ctx)
        rec["answered"].append({"path": a.path, "asked": a.asked, "answer": a.answer})
        for items in rec["left"].values():
            items[:] = [i for i in items if not (i["path"] == a.path and i["kind"] == "attribution")]
        print(write_report(ctx, rec).relative_to(root).as_posix())
        return 0

    if a.action == "correct":
        return main_correct(ctx, scopes, a)

    items = gather(ctx, scopes)
    done = None
    if a.action == "nightly" or (a.action == "fix" and a.yes):
        done = apply(ctx, items)
    report = record_run(ctx, scopes, items, done)
    code = EXIT_FAILED if ctx.failed or (done and done["refused"]) else 0

    if a.json:
        out = {"scope": scope_key(scopes), "headless": ctx.headless, "report": report.relative_to(root).as_posix(),
               "kinds": {k.name: sum(1 for i in items if i.kind == k.name) for k in ranked()},
               "items": [item_json(i) for i in items], "failed": ctx.failed}
        if done is not None:
            out.update({"fixed": [item_json(i) for i in done["fixed"]], "held": [item_json(i) for i in done["held"]],
                        "commits": done["commits"], "refused": done["refused"], "digest": digest(ctx, done, items),
                        "waiting": sum(waiting(done, items).values())})
        print(json.dumps(out, indent=1, ensure_ascii=False))
    elif a.ear:
        print(say_ear(items, scopes) if done is None else digest(ctx, done, items))
    elif done is not None:
        lines = ["Fixed %s:" % plural(len(done["fixed"]), "thing")] + ["  %s" % i.line() for i in done["fixed"]]
        lines += ["Committed %s in %s: %s" % (c["commit"], c["repo"], ", ".join(c["paths"])) for c in done["commits"]]
        if done["held"]:
            lines += ["Held:"] + ["  %s: %s" % (i.path, i.held) for i in done["held"]]
        lines += ["Report: %s" % report.relative_to(root).as_posix()]
        print("\n".join(lines))
    else:
        text = say_text(items, scopes)
        if a.action == "fix":
            fixes = [i for i in items if i.kind in KINDS and KINDS[i.kind].apply and i.fix]
            text = "%s would change, on --yes:\n%s" % (plural(len(fixes), "fix"), "\n".join("  %s" % i.line() for i in fixes)) \
                if fixes else "No fix to apply."
        print(text + "\nReport: %s" % report.relative_to(root).as_posix())
    for f in ctx.failed:
        print("nurture: did not run: %s" % f, file=sys.stderr)
    return code


def main_correct(ctx: Ctx, scopes: List[str], a) -> int:
    if not (a.old and a.new):
        print("nurture: correct needs --old and --new, the value as written and the one the user gave", file=sys.stderr)
        return EXIT_USAGE
    if a.yes and ctx.headless:
        print("nurture: a correction waits for a person to say the right value; it never runs with nobody watching",
              file=sys.stderr)
        return EXIT_USAGE
    try:
        out = run_correction(ctx, scopes, a.old, a.new, a.yes, a.why, a.leave, a.path or "")
    except ValueError as exc:
        print("nurture: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    item, done, root = out["item"], out["done"], ctx.root
    report = out["report"].relative_to(root).as_posix()
    code = EXIT_FAILED if done is not None and done.refused else 0
    if a.json:
        j = {"scope": scope_key(scopes), "old": a.old, "new": a.new, "report": report, "item": item_json(item),
             "hits": out["hits"], "held": [item_json(i) for i in out["held"]]}
        if out["wall"]:
            j["refusal"] = out["wall"]
        if done is not None:
            j.update({"changed": done.changed, "superseded": done.superseded, "commits": done.commits,
                      "uncommitted": done.uncommitted, "refused": done.refused, "rebuilt": done.rebuilt})
        print(json.dumps(j, indent=1, ensure_ascii=False))
        return code
    files = item.fix["files"]
    back = len(out["held"])
    if a.ear:
        if done is not None:
            said = "Corrected in %s, %s." % (plural(len(done.changed), "place"), plural(len(done.commits), "commit"))                 if done.changed else "Nothing changed."
        elif files:
            said = "%s the old value. Correct them all?" % ("One place has" if len(files) == 1
                                                             else "%d places have" % len(files))
        else:
            said = "Nothing live holds the old value."
        if back:
            said += " %s held back, named in the report." % ("One more is" if back == 1 else "%d more are" % back)
        if out["wall"]:
            said += " " + out["wall"]
        print(said)
        return code
    lines = []
    if done is None:
        for h in out["hits"]:
            lines.append("%s\t%s" % (h["kind"], h["path"]))
            lines += ["\t%d: %s" % (l["line"], l["text"][:160]) for l in h["lines"]]
        lines.append(item.line() if files or item.fix["raw"] else 'Nothing live holds "%s".' % a.old)
        if files:
            lines.append("On a yes, run again with --yes: one commit per repository.")
    else:
        lines.append(item.line())
        lines += ["Committed %s in %s" % (sha, repo) for repo, sha in done.commits]
        lines += ["Not committed: %s (%s)" % u for u in done.uncommitted]
        lines += ["Refused in %s: %s" % r for r in done.refused]
        lines += ["Marked superseded: %s" % p for p in done.superseded]
    if out["held"]:
        lines += ["Held:"] + ["  %s: %s" % (i.path, i.held) for i in out["held"]]
    if out["wall"]:
        lines.append(out["wall"])
    lines.append("Report: %s" % report)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
