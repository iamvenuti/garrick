"""The page's reads that 0.78.0 moved onto the view model, frozen as v0.77.0 had them (#650): the oracle the shadow tests
compare against, as `old_status_reads.py` is for 0.77.0's three sections.

Each area below is `status.py`'s own code for one section of the page, copied word for word before the section moved.
They read the workspace by themselves, which the page no longer does; they stay here only so that a test can say the
view model and the old code agree. They borrow the page's small helpers, which the page still holds (`HELPERS`). Never
edited: a difference the view model should keep is written into the shadow test as a named display rule, not changed here.

    old = old_reads(status, "SYSTEM")        # a namespace holding the area's old functions
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HELPERS = ("frontmatter", "as_text", "tags", "as_date", "visible_dirs", "work_reader", "workspace_lib", "PARKED", "DONE",
           "todo_lines", "outbox_mod", "machine_role", "line_place", "plain_text", "md_inline", "E", "question_need")


def old_reads(status, *areas):
    """The old functions of the areas named, bound to the page module `status`, as a namespace."""
    g = {"dt": dt, "re": re, "os": os, "json": json, "hashlib": hashlib, "subprocess": subprocess, "Path": Path, "Dict": Dict,
         "List": List, "Optional": Optional, "Tuple": Tuple}
    for name in HELPERS:
        if hasattr(status, name):
            g[name] = getattr(status, name)
    if "GRAPH" in areas:        # the graph borrows most of the page's drawing rules (kinds, labels, names): all of them
        g.update({k: v for k, v in vars(status).items() if not k.startswith("__")})
    for area in areas:
        exec(compile(AREAS[area], "old_status_reads_0770:" + area, "exec"), g)
    return g


SYSTEM = r'''
def system_notes(ws: Path) -> Dict[str, Path]:
    """The hub and thread notes of every project kept in System/, by name and
    by path from the workspace, lower-cased. Such a project has no Todo.md of
    its own: its actions live in a zone's, opening with its thread's link."""
    out: Dict[str, Path] = {}
    for project in visible_dirs(ws / "System"):
        hub = project / (project.name + ".md")
        if not hub.is_file() or as_text(frontmatter(hub, ws).get("type")).strip().lower() != "project":
            continue
        for note in [hub] + [t / (t.name + ".md") for t in visible_dirs(project / "Threads")]:
            if note.is_file():
                out.setdefault(note.relative_to(ws).with_suffix("").as_posix().lower(), note)
                out.setdefault(note.stem.lower(), note)
    return out
'''

TODO = r'''
def line_place(note: Path, zone: Path) -> Tuple[str, str]:
    """The project and the thread a line belongs to, from the note it points at or sits in (#596): a thread's note,
    or any file in its folder, gives both; a project's hub, or a file in the project and not in a thread, gives the
    project alone. A note outside the zone's projects, or not placed, gives neither."""
    try:
        parts = Path(os.path.abspath(str(note))).relative_to(Path(os.path.abspath(str(zone)))).parts
    except ValueError:
        return "", ""
    if len(parts) >= 4 and parts[1] == "Threads":
        return parts[0], parts[2]
    if len(parts) >= 2 and parts[0] not in ("Inbox", "archive") and not parts[0].startswith("."):
        return parts[0], ""
    return "", ""

def todo_list(ws: Path, link: "Links", today: dt.date) -> List[dict]:
    """Preview: each zone's open actions, read from the notes, never written.
    Per zone: the lines of Todo.md grouped under its `## ` headings in their
    order, then the lines that sit in thread notes ("In thread notes"), then
    what was ticked today, with counts of the open, the late and the
    undated. An empty section is left out, but an empty Inbox is said. A
    label names a note in the zone or, failing that, a project in System/."""
    tl = todo_lines()
    out = []
    system = system_notes(ws)
    role = machine_role(ws)
    for zone in visible_dirs(ws / "Zones"):
        todo_md = zone / "Todo.md"
        waits = outbox_mod().pending_marks(ws, zone.name) if role == "roaming" else {}
        held = [dict(h, role=role) for h in outbox_mod().held_requests(ws, zone.name)] if role in ("server", "roaming") else []
        notes = {}
        for n in tl.notes(str(zone)):
            rel = Path(n).relative_to(zone).with_suffix("").as_posix()
            notes.setdefault(rel.lower(), Path(n))
            notes.setdefault(Path(n).stem.lower(), Path(n))
        for name, n in system.items():
            notes.setdefault(name, n)

        def row(t, done=False):
            field = t["scheduled"] if t["waiting"] else t["due"]
            try:
                when = dt.date.fromisoformat(field) if field else None
            except ValueError:
                when = None
            late = bool(when and (when <= today if t["waiting"] else when < today)) and not done
            if t["file"] != "Todo.md":
                thread, note = Path(t["file"]).stem, zone / t["file"]
            elif t["target"]:
                thread, note = t["thread"], notes.get(t["target"].lower()) or notes.get(t["target"].rsplit("/", 1)[-1].lower())
            else:
                thread, note = None, None
            project, tname = line_place(note, zone) if note and not t["unsure"] else ("", "")
            return dict(t, when=when, late=late, done=done, field=field if when else "", label=thread, waits=waits.get(t["key"], ""),
                        project=project, tname=tname,
                        link=link.attrs(note) if note else "", zone=zone.name,
                        alpha=("%s\u0001%s" % (thread or ("\uffff" if t["unsure"] else ""), plain_text(t["text"]))).casefold())

        rows = [row(t) for t in tl.tasks(str(zone)) if t["text"] and "<action>" not in t["text"]]
        if not rows and not todo_md.is_file():
            continue
        order: List[str] = []
        if todo_md.is_file():
            order = [l[3:].strip() for l in todo_md.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("## ")]
        groups = []
        for name in order:
            if name in (g for g, _ in groups):
                continue
            items = [r for r in rows if r["file"] == "Todo.md" and r["section"] == name]
            if items or name == "Inbox":
                groups.append((name, sorted(items, key=lambda r: r["alpha"])))
        loose = [r for r in rows if r["file"] == "Todo.md" and r["section"] not in order]
        if loose:
            groups.append(("Not under a heading", sorted(loose, key=lambda r: r["alpha"])))
        elsewhere = [r for r in rows if r["file"] != "Todo.md"]
        if elsewhere:
            groups.append(("In thread notes", sorted(elsewhere, key=lambda r: (r["file"].lower(), r["alpha"]))))
        done = [row(t, done=True) for t in tl.done_on(str(zone), today) if t["text"] and "<action>" not in t["text"]]
        out.append(dict({"zone": zone.name, "file": todo_md if todo_md.is_file() else None, "groups": groups,
                         "done": sorted(done, key=lambda r: r["alpha"]), "open": len(rows),
                         "late": sum(1 for r in rows if r["late"]), "undated": sum(1 for r in rows if r["when"] is None)},
                        **({"held": held} if held else {})))
    return out
'''

QUESTIONS = r'''
QUESTION_BOX = "Needs you"

QUESTION_OPTION = re.compile(r"^\s*-\s+\[(?![ xX]\])([^\]]+)\]\s+(\S.*?)\s*$")

def questions_in(folder: Path, zone: Path, today: dt.date) -> List[dict]:
    """The open questions in one piece of work's `Needs you` folder, oldest first, and the ones put off whose day has
    come. One put off to a later day, an answered one and a file with no bold line to ask are left out."""
    out: List[dict] = []
    box = folder / QUESTION_BOX
    if not box.is_dir():
        return out
    for f in sorted(box.glob("*.md")):
        if f.name.startswith((".", "_")):
            continue
        fm = frontmatter(f)
        if folder == zone and not as_text(fm.get("intake")).strip():
            continue                    # the zone's own box holds only what an inbox run asked (#634)
        state = as_text(fm.get("status")).strip().lower() or "open"
        later = as_date(fm.get("later"))
        if state not in ("open", "later") or (state == "later" and not (later is not None and later <= today)):
            continue
        try:
            body = re.sub(r"\A---\n.*?\n---\n", "", f.read_text(encoding="utf-8", errors="replace"), count=1, flags=re.S)
        except OSError:
            continue
        ask, opts = "", []
        for line in body.splitlines():
            m = QUESTION_OPTION.match(line)
            if m:
                opts.append(m.group(1).strip())
            elif not ask and re.match(r"^\s*\*\*.+\*\*\s*$", line):
                ask = line.strip().strip("*").strip()
        if ask:
            out.append({"file": f.relative_to(zone).as_posix(), "zone": zone.name, "ask": ask, "options": opts,
                        "asked": as_date(fm.get("asked")), "own": as_text(fm.get("own")).strip(), "work": folder.name,
                        "intake": bool(as_text(fm.get("intake")).strip()) and folder == zone})
    return out

def question_needs(ws: Path, today: dt.date) -> List[dict]:
    """Every zone's open questions as rows, oldest first within the zone, zones in their order."""
    out: List[dict] = []
    for zone in visible_dirs(ws / "Zones"):
        found: List[dict] = questions_in(zone, zone, today)      # the zone's own: what an inbox run asked (#634)
        for project in visible_dirs(zone):
            hub = project / (project.name + ".md")
            if hub.is_file():
                found += questions_in(project, zone, today)
            for thread in visible_dirs(project / "Threads"):
                if (thread / (thread.name + ".md")).is_file():
                    found += questions_in(thread, zone, today)
        found.sort(key=lambda q: (q["asked"] or dt.date.max, q["file"]))
        out += [question_need(q, today) for q in found]
    return out
'''

WIKIS = r'''
LOG_ENTRY = re.compile(r"^\s*-\s+(\d{4}-\d\d-\d\d):\s+\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")

LOG_DATED = re.compile(r"^\s*-\s+(\d{4}-\d\d-\d\d):\s+(.*)$")

LOG_SECTION = re.compile(r"^##\s+(\d{4}-\d\d-\d\d)\b[\s:·,—–-]*(.*)$")

LOG_NOT_READ = "log not read"

def log_entries(text: str) -> Tuple[List[Tuple[dt.date, int, str, str]], bool]:
    """(date, -line, title, page target or "") for every entry a wiki's log
    holds, in the three forms (#322); and whether it holds lines that look
    like entries, a list item or a `## ` section, so a log that reads as none
    of them says so rather than "nothing logged yet"."""
    lines = text.splitlines()
    entries, tried = [], False
    for n, line in enumerate(lines):
        m = LOG_ENTRY.match(line)
        if m:
            when = as_date(m.group(1))
            if when:
                target = m.group(2).strip()
                entries.append((when, -n, (m.group(3) or target.rsplit("/", 1)[-1]).strip(), target))
                continue
        m = LOG_DATED.match(line) or LOG_SECTION.match(line)
        if m and as_date(m.group(1)):
            rest = m.group(2).strip()
            if not rest and line.startswith("##"):          # the section's first line says what it holds
                rest = next((l.strip().lstrip("-* ").strip() for l in lines[n + 1:n + 6] if l.strip() and not l.startswith("#")), "")
                k = LOG_ENTRY.match("- %s: %s" % (m.group(1), rest))
                if k:
                    target = k.group(2).strip()
                    entries.append((as_date(m.group(1)), -n, (k.group(3) or target.rsplit("/", 1)[-1]).strip(), target))
                    continue
            title = plain_text(re.split(r"[(;]", rest, 1)[0]).strip(" .,:") or "an entry"
            entries.append((as_date(m.group(1)), -n, title, ""))
            continue
        tried = tried or line.lstrip().startswith(("- ", "* ")) or line.startswith("## ")
    return entries, tried

def wikis(ws: Path) -> List[dict]:
    """Per wiki: its log, how many entries it holds, and the newest entry's
    date and title. Nothing else from the line: not its zone, not its parties.
    An entry with a link opens its page; a log whose entries it cannot read
    at all says so (`unread`)."""
    out = []
    for w in visible_dirs(ws / "Wikis"):
        log = w / "wiki" / "log.md"
        if not log.is_file():
            continue
        entries, tried = log_entries(log.read_text(encoding="utf-8", errors="replace"))
        row = {"name": w.name, "log": log, "count": len(entries), "when": None, "title": "", "page": None,
               "unread": tried and not entries}
        if entries:
            when, _, title, target = max(entries)   # the newest; on a tie, the line nearer the top
            page = None
            if target:
                page = (w / (target if target.endswith(".md") else target + ".md")).resolve()
                if not (str(page).startswith(str(w.resolve()) + os.sep) and page.is_file()):
                    page = None
            row.update(when=when, title=title[:100] + ("…" if len(title) > 100 else ""), page=page)
        out.append(row)
    return out
'''

REPOS = r'''
UNMERGED = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}

def oldest_change(folder: Path, changes) -> Optional[dt.datetime]:
    """When the longest-waiting uncommitted change was made: the oldest
    modification time among the changed files still on disk. A deleted file
    has none and is passed over."""
    times = []
    for path, _ in changes:
        try:
            times.append((folder / path).stat().st_mtime)
        except OSError:
            continue
    return dt.datetime.fromtimestamp(min(times)) if times else None

def changed_files(porcelain: str) -> List[Tuple[str, Tuple[str, ...]]]:
    """(path, kinds) for every file `git status --porcelain -z` lists: one entry
    per file, a rename under its new name. A count of these is a count of
    files, never of commits."""
    out, items = [], porcelain.split("\0")
    i = 0
    while i < len(items):
        item = items[i]
        i += 1
        if len(item) < 4:
            continue
        xy, path = item[:2], item[3:]
        if "R" in xy or "C" in xy:
            i += 1                              # the name it had before
        if xy == "??":
            kinds = ("untracked",)
        elif xy in UNMERGED:
            kinds = ("conflicted",)
        else:
            kinds = tuple(k for k, mark in (("staged", xy[0]), ("unstaged", xy[1])) if mark not in " ?!")
        if kinds:
            out.append((path, kinds))
    return out

def repos(ws: Path) -> List[dict]:
    """The root, each zone, and the wikis: the installer makes one repository
    at Wikis/ for both. A wiki with a repository of its own is listed too.
    When git fails or runs out of time, the repository is `unread`, never
    clean: an empty answer is not a count of nothing."""
    places = [("Workspace", ws)] + [(z.name, z) for z in visible_dirs(ws / "Zones")] + \
             [("Wikis", ws / "Wikis")] + [(w.name, w) for w in visible_dirs(ws / "Wikis")]
    out = []
    for name, folder in places:
        if not (folder / ".git").exists():
            continue
        # --no-optional-locks: the page only reads, so git status never takes
        # index.lock to refresh the index, and a commit a session makes in the
        # same moment never finds it held.
        def git(*args):
            try:
                proc = subprocess.run(["git", "--no-optional-locks", "-C", str(folder), *args], capture_output=True,
                                      text=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                return None
            return proc.stdout if proc.returncode == 0 else None
        porcelain = git("status", "--porcelain", "-z", "--untracked-files=all")
        changes = changed_files(porcelain or "")
        ct = (git("log", "-1", "--format=%ct") or "").strip()
        out.append({"name": name, "folder": folder, "dirty": len(changes), "changes": changes,
                    "unread": porcelain is None, "since": oldest_change(folder, changes),
                    "last": dt.datetime.fromtimestamp(int(ct)) if ct.isdigit() else None})
    return out
'''

EXAMPLE = r'''
EXAMPLE_MANIFEST = ".example.json"

def example_zone(ws: Path) -> Optional[str]:
    """The zone the worked example is in, or None: the first zone whose
    .example.json names it, read as System/tools/example.py's present() does."""
    zones = ws / "Zones"
    for zone in sorted(zones.iterdir()) if zones.is_dir() else []:
        manifest = zone / EXAMPLE_MANIFEST
        if not (zone.is_dir() and manifest.is_file()):
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("zone") == zone.name:
            return zone.name
    return None
'''

GRAPH = r'''
WIKILINK = re.compile(r"\[\[([^\]|#^]+)")

SKIP_DIRS = {"inbox", "raw", "archive", "generated"}

def walked(root: Path, folder: str, name: str, in_zone: bool) -> bool:
    """Whether the graph reads the folder `name` inside `folder`. A zone's own
    Inbox is left out. A project or a thread is read whatever it is called, so
    one named Archive or raw stays on the graph; anywhere else a folder named
    for an inbox, raw records, old versions or generated pages is left out."""
    if name.startswith((".", "_")):
        return False
    depth = Path(folder).relative_to(root).parts
    if in_zone and not depth:
        return name != "Inbox"                                # every other folder here is a project
    if in_zone and len(depth) == 2 and depth[1] == "Threads":
        return True                                           # a thread
    return name.casefold() not in SKIP_DIRS

def git_ignored(root: Path) -> set:
    """The folders (paths relative to the zone `root`) that the zone's own git
    ignores, from one `git ls-files` over the zone (#399), asked for before the
    walk so that an ignored folder is never entered. A path git cannot encode
    as text (a name that is not valid UTF-8) is read back as the walk reads it,
    with surrogateescape. A zone that is not a repository of its own, or a Mac
    with no git, ignores nothing."""
    if not (root / ".git").exists():
        return set()
    try:
        done = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return set()
    if done.returncode != 0:
        return set()
    return {os.fsdecode(x).rstrip("/") for x in done.stdout.split(b"\0") if x.endswith(b"/")}

def vault_of(ws: Path, folder: Path) -> Optional[Path]:
    """The Obsidian vault a folder's notes belong to: the nearest folder at or
    above it, up to the workspace root, that holds a .obsidian folder."""
    return todo_lines().vault_of(ws, folder)

def vault_filters(vault: Optional[Path]) -> List[object]:
    """A vault's ignore filters (.obsidian/app.json, userIgnoreFilters), a path
    prefix or a /regex/ each, read as the Todo card reads them: what Obsidian
    leaves off its graph, Explore leaves off too. Nothing else of the vault's
    is read, so the graph looks the same with Obsidian or without it (#292).
    Empty outside a vault, or when the file is missing or does not read."""
    return todo_lines().ignore_filters(vault) if vault is not None else []

def ignored(rel: str, filters: List[object]) -> bool:
    return todo_lines().ignored(rel, filters)

def graph(ws: Path, T: Dict[str, dict], link: "Links", now: dt.datetime, cmux: bool = False, actions: bool = False,
          desk: Optional[Dict[str, str]] = None, drive: bool = False, urgent: Optional[set] = None) -> dict:
    """Every note in the zones and the wikis, and the [[links]] between them.
    From a note it keeps its title, kind, place, party tags and, for a thread,
    how long since it moved; from its body only the targets of its links.
    Instructions (AGENTS.md) are not notes, and each zone's Todo.md has the
    Todo card, so neither is drawn. A parked thread, with the notes in
    its folder, and a project with no live thread left, with everything in it,
    are marked `s` and drawn only when the page is asked to show them.

    Every note is coloured by its kind, in every place, whether or not it
    sits inside an Obsidian vault (#292). A vault's ignore filters
    (.obsidian/app.json) leave notes out, as Obsidian's graph does: a filter
    for what to draw, not a colour. Every note in a project carries the
    folder an app opens it in (`f`), its thread's or else its project's,
    where an app can open one. A thread whose own next action is late, named by zone,
    project and thread in `urgent`, is marked `lt` and draws the one ring the
    graph has: age alone never marks a note. Every note carries its path from
    its place's folder, without `.md` (`m`), and `pr` maps each place to that
    folder from the workspace's, so Preview can name the note it reads (#206)."""
    places = [(z.name, z) for z in visible_dirs(ws / "Zones")]
    places += [(w.name, w / "wiki") for w in visible_dirs(ws / "Wikis") if (w / "wiki").is_dir()]
    names = short_names(T)
    held = {(r["zone"], r["project"], r["thread"]) for z in T.values() for r in z["parked"]}
    hubs_parked = {zone: set(data.get("held", ())) for zone, data in T.items()}
    awake = {(r["zone"], r["project"]) for z in T.values() for r in z["rows"]}
    asleep = {(zone, project) for zone, project, _ in held} - awake
    vaults: Dict[Path, List[object]] = {}             # vault -> its ignore filters
    notes = []
    for place, root in places:
        in_zone = root.parent.name == "Zones"
        vault = vault_of(ws, root)
        if vault is not None and vault not in vaults:
            vaults[vault] = vault_filters(vault)
        filters = vaults[vault] if vault is not None else []
        found_in = []                                 # (folder, files), in walk order
        # What the zone's git ignores is known before the walk, so an ignored folder is never entered.
        left_out = git_ignored(root) if in_zone else set()
        for folder, dirs, files in os.walk(root):
            # A folder that tops a repository of its own (a `.git` folder, or the file a worktree has) is not walked.
            dirs[:] = sorted(d for d in dirs if walked(root, folder, d, in_zone) and not (Path(folder) / d / ".git").exists()
                             and Path(folder, d).relative_to(root).as_posix() not in left_out)
            found_in.append((folder, files))
        for folder, files in found_in:
            for f in sorted(files):
                if not f.endswith(".md") or f == "AGENTS.md" or f.startswith((".", "_")):
                    continue
                if folder == str(root) and (f in ("index.md", "log.md") and root.name == "wiki"
                                            or f == "Todo.md" and root.parent.name == "Zones"):
                    continue
                if filters and ignored((Path(folder) / f).relative_to(vault).as_posix(), filters):
                    continue
                notes.append((place, root, Path(folder) / f))
    rel = {path: path.relative_to(ws).with_suffix("").as_posix() for _, _, path in notes}
    by_rel = {r: p for p, r in rel.items()}
    nodes, index = [], {}
    kinds = [k for k, _, _ in KINDS]
    found: Dict[str, Dict[str, int]] = {}             # wiki -> type no model kind takes -> its pages (#250)
    typed_at: List[Tuple[int, str, str]] = []
    lib, source_type = workspace_lib(ws), "source"
    try:
        if lib is not None and callable(getattr(lib, "knowledge_schema", None)):
            source_type = lib.knowledge_schema(ws)[0]["source"]["type"]     # a wiki that names its sources otherwise
    except Exception:
        pass
    projects = [(place, path.parent.name) for place, root, path in notes
                if root.parent.name == "Zones" and path.parent.parent == root and path.stem == path.parent.name]
    threads_said = {t.casefold() for z in T.values() for r in z["rows"] + z["parked"] for t in [r["thread"]]}
    for place, root, path in notes:
        fm = frontmatter(path, ws)
        parts = path.relative_to(root).parts
        kind = as_text(fm.get("type")).strip().lower()
        kind = "mail" if kind in ("email", "mail") else kind
        in_zone = root.parent.name == "Zones"
        project = parts[0] if len(parts) > 1 and in_zone else ""
        wiki = root.parent.name if not in_zone else ""
        typed = kind
        if wiki:
            kind = wiki_kind(wiki, kind, parts, source_type)
        elif kind == "project" or (len(parts) == 2 and parts[1] == parts[0] + ".md"):
            kind = "project"
        elif kind not in ("project", "thread"):
            kind = "note"
        thread = parts[2] if kind == "thread" and len(parts) > 3 else ""
        state = as_text(fm.get("status")).strip().lower()
        moving = kind == "thread" and state != "done"
        updated = as_date(fm.get("updated"))
        days = (now.date() - updated).days if moving and updated else None
        party = tags(fm.get("party") or fm.get("parties"))
        folder_thread = parts[2] if in_zone and len(parts) > 3 and parts[1] == "Threads" else ""
        parked = (place, project) in asleep or (place, project, folder_thread) in held
        say = names.get((place, project, thread), "") if thread else ""
        project_said = project if project and project.casefold() not in threads_said \
            and sum(1 for _, p in projects if p.casefold() == project.casefold()) == 1 else ""
        if kind == "project" and project_said:
            say = project        # "open Acme Review": the threads skill resolves a project name too
        # Short keys keep the page small. The layout adds x, y, vx, vy, ax, ay, r,
        # i, adj, deg, lp and tw to each node in the browser, so none of those is used here.
        # tw holds a name's widths; it was lw, which a note in a project carries for what an app
        # resumes, so such a note was never named once zoomed in (#252).
        index[path] = len(nodes)
        title = as_text(fm.get("title")).strip() or path.stem
        hub = kind in HUBS.get(wiki, HUBS["*"]) if wiki else kind in HUBS[""]
        typed = found_kind(typed) if wiki and kind == "note" else ""
        if typed and typed not in kinds:
            seen = found.setdefault(wiki, {})
            seen[typed] = seen.get(typed, 0) + 1
            typed_at.append((len(nodes), wiki, typed))      # a kind of its own once enough pages share it (#250)
        nodes.append({"n": short_label(title) if wiki else title, "k": kinds.index(kind), "z": place, "p": project,
                      "t": party, "d": days, "s": 1 if parked else 0,
                      "c": 1 if hub else 0, "h": 1 if kind == "project" else 0,
                      "w": say, "u": link(path), "m": path.relative_to(root).as_posix()[:-3]})
        if link.place(path):
            nodes[-1]["pl"] = link.place(path)       # a hub or a thread's note: a double-click opens it as its row (#318)
        if moving and urgent and (place, project, folder_thread) in urgent:
            nodes[-1]["lt"] = 1                  # its next action is late
        if wiki and nodes[-1]["n"] != title:
            nodes[-1]["N"] = title                   # the whole title, for the card and the tooltip
        if in_zone and project:
            home = root / project / "Threads" / folder_thread if folder_thread else root / project
            if cmux:
                nodes[-1]["f"] = str(home)          # where the apps a card offers open it
                if not say:                          # what they resume there
                    lw = names.get((place, project, folder_thread), "") if folder_thread else project_said
                    if lw:
                        nodes[-1]["lw"] = lw
            if drive:
                nodes[-1]["dk"] = [place, project, folder_thread]     # what the desk opens and closes
            live = session_in(desk, home) if kind in ("project", "thread") else None
            if live:
                nodes[-1]["live"] = live
        if kind == "project" and in_zone and project:
            nodes[-1]["hp"] = 1 if project in hubs_parked.get(place, ()) else 0
            if actions:
                nodes[-1]["pp"] = [place, project]                          # Park and Wake for all of it
        if kind == "thread" and in_zone and project in hubs_parked.get(place, ()):
            nodes[-1]["held"] = 1                                           # woken with its project
        elif actions and kind == "thread" and in_zone and folder_thread:
            nodes[-1]["pa"] = [place, path.relative_to(root).as_posix()]   # what Park and Wake act on
        if actions and kind == "thread" and in_zone and folder_thread and path.name == folder_thread + ".md":
            nodes[-1]["oc"] = [place, path.relative_to(root).as_posix()]   # what Open in Claude continues (#180)
    every = KINDS + page_kinds(found)
    keys = [k for k, _, _ in every]
    for i, wiki, typed in typed_at:
        if found[wiki][typed] >= KIND_FROM_PAGES:
            nodes[i]["k"] = keys.index(typed)
    # A link that is not a whole path resolves to the shortest path that ends
    # in it after a slash, and else to the shortest note of its name; among
    # paths as long, the first walked. Each note goes in once under every such
    # ending, so a link is a lookup, not a pass over every note (#260).
    by_base: Dict[str, Path] = {}
    by_tail: Dict[str, Path] = {}
    for p in sorted(rel, key=lambda q: len(rel[q])):
        by_base.setdefault(p.stem.lower(), p)
        parts = rel[p].split("/")
        for i in range(1, len(parts)):
            by_tail.setdefault("/".join(parts[i:]), p)
    edges = set()
    for _, _, path in notes:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for target in WIKILINK.findall(text):
            # In a Markdown table the alias's pipe is escaped, [[x\|alias]]: drop the backslash.
            target = target.strip().rstrip("\\").strip().rstrip("/")
            target = target[:-3] if target.endswith(".md") else target
            hit = by_rel.get(target)
            if hit is None:
                hit = by_tail.get(target)
            if hit is None:
                hit = by_base.get(target.split("/")[-1].lower())
            if hit is not None and hit != path:
                a, b = index[path], index[hit]
                edges.add((min(a, b), max(a, b)))
    used = sorted({n["k"] for n in nodes})        # each kind the legend offers as a filter (#250)
    # In a wiki's core view the hubs are joined when one page links both: two
    # people in the same meeting, a person and the entity met in it (#320),
    # two concepts cited by the same source. The third number is how many
    # pages do. A page that joins is any not of the kinds the place opens on
    # (OPENS), or not a hub where it names none: so in Meetings an entity's
    # page still joins two people, as before entities were hubs.
    wikis = {place for place, root, _ in notes if root.parent.name != "Zones"}
    opens = {place: {keys.index(k) for k in OPENS[place] if k in keys} for place in wikis if place in OPENS}
    neighbours: Dict[int, set] = {}
    for a, b in edges:
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    co: Dict[Tuple[int, int], int] = {}
    for i, n in enumerate(nodes):
        if n["z"] not in wikis or (n["k"] in opens[n["z"]] if n["z"] in opens else n["c"]):
            continue
        hubs = sorted(j for j in neighbours.get(i, ()) if j != i and nodes[j]["c"] and nodes[j]["z"] == n["z"])
        for x in range(len(hubs)):
            for y in range(x + 1, len(hubs)):
                co[(hubs[x], hubs[y])] = co.get((hubs[x], hubs[y]), 0) + 1
    counts: Dict[str, int] = {}
    for n in nodes:
        counts[n["z"]] = counts.get(n["z"], 0) + 1
    return {"nodes": nodes, "edges": sorted(edges), "colors": [c for _, _, c in every],
            "kinds": [[i, every[i][1]] for i in used], "keys": keys, "known": len(KINDS),
            "mode": "all" if len(nodes) <= 150 else "core",
            "modes": {z: "all" if c <= 150 else "core" for z, c in counts.items()},
            "pr": {place: root.relative_to(ws).as_posix() for place, root in places},
            "ce": [[a, b, w] for (a, b), w in sorted(co.items())],
            "op": {place: sorted(ks) for place, ks in opens.items()}}
'''

AREAS = {"GRAPH": GRAPH, "EXAMPLE": EXAMPLE, "SYSTEM": SYSTEM, "TODO": TODO, "QUESTIONS": QUESTIONS, "WIKIS": WIKIS, "REPOS": REPOS}
