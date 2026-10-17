#!/usr/bin/env python3
"""Stop a wrong value everywhere: "that's wrong, it's Y".

    python3 System/tools/correct.py --old OLD --new NEW               every live copy of OLD, listed; changes nothing
    python3 System/tools/correct.py --old OLD --new NEW --json        the same, for a program
    python3 System/tools/correct.py --old OLD --new NEW --apply [--why "..."] [--leave PATH ...] [--today YYYY-MM-DD]

A value one session wrote, a later one reads as fact: an address, an account,
a name, a share path. When it turns out wrong, correcting the one file in
front of you leaves the other copies to be read again tomorrow. This finds
them all, in the places a session reads as fact:

- the assistant's memory entries, in the folders `memory` names in
  System/garrick-checks.json (none when it is not set), their index included;
- System/context.md;
- every hub and thread note, in the zones and in System/;
- each zone's Todo.md;
- the pages of both wikis, under `wiki/`.

It lists every hit by file and line, and changes nothing. With `--apply`,
the user's one yes, it puts NEW in place of OLD in each of them, then commits
once per repository the files it changed, staged by name and nothing else.
A file in no repository, such as a memory kept outside the workspace, is
changed and reported as not committed. A zone's wall check still runs on its
commit, and a refusal is reported: the files stay changed, uncommitted.
Live files show only the current value: no "was OLD" is written anywhere.
Git holds the old one.

Raw records are never edited. A raw record under a wiki's `raw/` that holds
OLD is listed, and the wiki pages that rest on it (those that link to it or
name its path) get `superseded:` in their frontmatter and one line at the
end, saying that their record holds a value corrected since, and the right
one, without repeating the wrong one. `superseded:` is the key the waking
guard reads, so a page that rests on a corrected record does not come back
into use as though nothing happened.

Then it rebuilds what is built from those files: the Meetings wiki's index,
where a page of it changed, committed with the pages, and the status page,
where the status extra is installed, which is never committed.

OLD is matched as written, case and all, and never inside a longer word:
`acme` is not found in `acmecorp`. Where NEW contains OLD (`Acme` to `Acme
Corp`), an OLD that is already part of NEW is left alone, so a second run
changes nothing. `--leave PATH` keeps one file out, for a hit that is right
where it is (a heard form in Aliases is meant to be misspelt).

Two callers share it: the `threads` skill, when the user says "that's wrong,
it's Y" in a session, and `nurture.py correct`, the nurture pass's correction
kind. Nurture imports it rather than run it:

    import correct
    hits = correct.find_hits(root, old, new)                       # [Hit], every live copy
    done = correct.apply(root, old, new, hits, why="", today=None)  # Applied: what changed and each commit
    correct.listing(hits)                                           # the JSON `--json` prints

`find_hits(root, old, new="", memory=None)` takes the memory folders as a
list to search instead of the setting's. `apply(root, old, new, hits=None,
why="", today=None, commit=True, rebuild=True)` re-reads each file before it
writes it, since another session may have changed it, finds the hits again
when `hits` is None, and never edits a raw record. Each Hit has `path`,
`kind` (memory, context, hub, thread, todo, wiki or raw), `repo`, `lines` as
(line number, text), and for a raw record the `pages` that rest on it.
Applied has `changed`, `superseded`, `commits` as (repository, commit),
`uncommitted` and `refused` as (path, reason), and `rebuilt`. A refusal is a
ValueError with one line to say.

Exit codes: 0, also when nothing holds OLD; 1 for a refusal, or a commit a
wall check refused; 2 when no workspace is found. Standard library only,
Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

sys.dont_write_bytecode = True  # keep System/tools free of __pycache__
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from garrick_lib import (  # noqa: E402
    INBOX,
    memory_folders,
    parse_frontmatter_text,
    workspace_root,
)

KINDS = ("memory", "context", "hub", "thread", "todo", "wiki", "raw")
RAW_TEXT = {".md", ".markdown", ".txt", ".eml", ".vtt", ".html", ".htm", ".json", ".csv", ".tsv", ".yaml", ".yml", ".xml"}
MAX_BYTES = 5_000_000
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
INGEST = ("System", "skills", "meetings", "ingest.py")
STATUS = ("System", "status", "status.py")


@dataclass
class Hit:
    path: Path
    kind: str
    repo: Optional[Path]
    lines: List[Tuple[int, str]]
    pages: List[Path] = field(default_factory=list)  # a raw record's: the wiki pages that rest on it


@dataclass
class Applied:
    changed: List[str] = field(default_factory=list)
    superseded: List[str] = field(default_factory=list)
    commits: List[Tuple[str, str]] = field(default_factory=list)
    uncommitted: List[Tuple[str, str]] = field(default_factory=list)
    refused: List[Tuple[str, str]] = field(default_factory=list)
    rebuilt: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- matching


def pattern(old: str) -> "re.Pattern[str]":
    """OLD as written, never inside a longer word."""
    head = r"(?<!\w)" if re.match(r"\w", old[:1]) else ""
    tail = r"(?!\w)" if re.match(r"\w", old[-1:]) else ""
    return re.compile(head + re.escape(old) + tail)


def spans(text: str, old: str, new: str) -> List[Tuple[int, int]]:
    """Where OLD stands in `text`, leaving out an OLD that is part of a NEW
    already there."""
    inside = [(m.start(), m.end()) for m in re.finditer(re.escape(new), text)] if new and old in new else []
    return [(m.start(), m.end()) for m in pattern(old).finditer(text)
            if not any(a <= m.start() and m.end() <= b for a, b in inside)]


def replaced(text: str, old: str, new: str) -> str:
    out, at = [], 0
    for a, b in spans(text, old, new):
        out.append(text[at:a])
        out.append(new)
        at = b
    out.append(text[at:])
    return "".join(out)


def _read(path: Path) -> Optional[str]:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def _lines(text: str, old: str, new: str) -> List[Tuple[int, str]]:
    numbers = sorted({text.count("\n", 0, a) + 1 for a, _ in spans(text, old, new)})
    lines = text.split("\n")
    return [(n, lines[n - 1].strip()) for n in numbers]


# --------------------------------------------------------------------------- where to look


def _visible(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def _notes(project: Path) -> Iterable[Tuple[str, Path]]:
    hub = project / (project.name + ".md")
    if hub.is_file():
        yield "hub", hub
    for thread in _visible(project / "Threads"):
        note = thread / (thread.name + ".md")
        if note.is_file():
            yield "thread", note


def places(root: Path, memory: Optional[List[Path]] = None) -> List[Tuple[str, Path]]:
    """(kind, file) for every live file a correction reaches, and every raw record."""
    out: List[Tuple[str, Path]] = []
    folders = memory if memory is not None else memory_folders(root)
    for folder in folders:
        if Path(folder).is_dir():
            for path in sorted(Path(folder).rglob("*.md")):
                if path.is_file() and not any(p.startswith(".") for p in path.relative_to(folder).parts):
                    out.append(("memory", path))
    context = root / "System" / "context.md"
    if context.is_file():
        out.append(("context", context))
    for zone in _visible(root / "Zones"):
        for project in _visible(zone):
            if project.name.lower() != INBOX.lower():
                out.extend(_notes(project))
        todo = zone / "Todo.md"
        if todo.is_file():
            out.append(("todo", todo))
    for folder in _visible(root / "System"):
        hub = folder / (folder.name + ".md")
        if hub.is_file() and parse_frontmatter_text(_read(hub) or "").get("type") == "project":
            out.extend(_notes(folder))
    for wiki in _visible(root / "Wikis"):
        pages = wiki / "wiki"
        if pages.is_dir():
            out.extend(("wiki", p) for p in sorted(pages.rglob("*.md"))
                       if p.is_file() and not any(x.startswith(".") for x in p.relative_to(pages).parts))
        raw = wiki / "raw"
        if raw.is_dir():
            for p in sorted(raw.rglob("*")):
                parts = p.relative_to(raw).parts
                if (p.is_file() and p.suffix.lower() in RAW_TEXT and parts[0] != "inbox"
                        and not any(x.startswith(".") for x in parts)):
                    out.append(("raw", p))
    seen, unique = set(), []
    for kind, path in out:
        key = path.resolve()
        if key not in seen:
            seen.add(key)
            unique.append((kind, path))
    return unique


def resting_on(root: Path, raw: Path) -> List[Path]:
    """The wiki pages that rest on a raw record: the pages of its wiki that link
    to it, or name its path, with or without the extension."""
    wiki = next((p for p in raw.parents if p.parent == root / "Wikis"), None)
    if wiki is None or not (wiki / "wiki").is_dir():
        return []
    name = raw.relative_to(wiki).with_suffix("").as_posix()
    mark = re.compile(r"(?<![\w-])%s(?:%s)?(?![\w-])" % (re.escape(name), re.escape(raw.suffix)))
    return [p for p in sorted((wiki / "wiki").rglob("*.md")) if mark.search(_read(p) or "")]


def repo_of(path: Path) -> Optional[Path]:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(path.parent), capture_output=True, text=True)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else None


def find_hits(root, old: str, new: str = "", memory: Optional[List[Path]] = None) -> List[Hit]:
    """Every live copy of OLD, and every raw record that holds it. Changes nothing."""
    root = Path(root).resolve()
    if not old or not old.strip():
        raise ValueError("Say which value is wrong: --old cannot be empty.")
    hits, repos = [], {}
    for kind, path in places(root, memory):
        text = _read(path)
        lines = _lines(text, old, new) if text is not None else []
        if not lines:
            continue
        folder = path.parent
        if folder not in repos:
            repos[folder] = repo_of(path)
        hits.append(Hit(path, kind, repos[folder], lines, resting_on(root, path) if kind == "raw" else []))
    return hits


# --------------------------------------------------------------------------- applying


def _day(today: str) -> str:
    d = datetime.date.fromisoformat(today)
    return "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)


def _quoted(value: str) -> str:
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def superseded(text: str, new: str, why: str, today: str) -> str:
    """The page with `superseded:` in its frontmatter, unless it has one, and a
    line at its end saying its record holds a value corrected since. The wrong
    value is not repeated: the raw record keeps it, and git."""
    reason = "Corrected %s: the raw record holds a value corrected since; the right one is %s.%s" % (
        today, new, " " + why.strip() if why.strip() else "")
    line = "**Superseded, %s.** The raw record behind this page holds a value corrected since: the right one is %s.%s" % (
        _day(today), new, " " + why.strip() if why.strip() else "")
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
        if end is not None and not any(re.match(r"superseded\s*:", l) for l in lines[1:end]):
            lines.insert(end, "superseded: %s" % _quoted(reason))
    else:
        lines = ["---", "superseded: %s" % _quoted(reason), "---", ""] + lines
    text = "\n".join(lines)
    if line not in text:
        text = text.rstrip("\n") + "\n\n" + line + "\n"
    return text


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True)


def _commit(repo: Path, files: List[Path], message: str) -> Tuple[bool, str]:
    """One commit in `repo` of `files` and nothing else: (done, commit or reason)."""
    names = [f.resolve().relative_to(repo).as_posix() for f in files]
    added = _git(["add", "--"] + names, repo)
    if added.returncode != 0:
        return False, " ".join((added.stderr or added.stdout).split()) or "git add failed"
    if not _git(["diff", "--cached", "--quiet", "--"] + names, repo).returncode:
        return False, "nothing to commit"
    done = _git(["commit", "-q", "-m", message, "--"] + names, repo)
    if done.returncode != 0:
        _git(["reset", "-q", "--"] + names, repo)    # left changed, and not staged for somebody else's commit
        return False, " ".join((done.stderr or done.stdout).split()) or "git commit failed"
    return True, _git(["rev-parse", "--short", "HEAD"], repo).stdout.strip()


def apply(root, old: str, new: str, hits: Optional[List[Hit]] = None, why: str = "", today: Optional[str] = None,
          commit: bool = True, rebuild: bool = True) -> Applied:
    """Put NEW in place of OLD in every live file `hits` names, mark the pages
    that rest on a raw record holding OLD as superseded, rebuild what is built
    from them, and commit once per repository. Raw records are never touched."""
    root = Path(root).resolve()
    if not old or not old.strip():
        raise ValueError("Say which value is wrong: --old cannot be empty.")
    if not new or not new.strip():
        raise ValueError("Say what it should be: --new cannot be empty.")
    if old == new:
        raise ValueError("The old value and the new one are the same; nothing to correct.")
    today = today or datetime.date.today().isoformat()
    try:
        _day(today)
    except ValueError:
        raise ValueError('"%s" is not a date (YYYY-MM-DD).' % today)
    hits = find_hits(root, old, new) if hits is None else hits
    done = Applied()
    touched: Dict[Path, Optional[Path]] = {}
    pages: List[Path] = []
    for hit in hits:
        if hit.kind == "raw":
            pages += [p for p in hit.pages if p not in pages]
            continue
        text = _read(hit.path)                           # re-read now: another session may have changed it
        if text is None:
            continue
        fixed = replaced(text, old, new)
        if fixed != text:
            hit.path.write_text(fixed, encoding="utf-8")
            touched[hit.path] = hit.repo
            done.changed.append(_rel(root, hit.path))
    for page in pages:
        text = _read(page)
        if text is None:
            continue
        marked = superseded(replaced(text, old, new), new, why, today)
        if marked != text:
            page.write_text(marked, encoding="utf-8")
            touched.setdefault(page, repo_of(page))
            done.superseded.append(_rel(root, page))
            if _rel(root, page) not in done.changed:
                done.changed.append(_rel(root, page))
    if not touched:
        return done
    meetings = root / "Wikis" / "Meetings" / "wiki"
    ingest = root.joinpath(*INGEST)
    if rebuild and ingest.is_file() and any(meetings in p.parents for p in touched):
        index = meetings / "index.md"
        before = _read(index)
        r = subprocess.run([sys.executable, str(ingest), "--root", str(root), "index"], capture_output=True, text=True)
        if r.returncode == 0:
            done.rebuilt.append(_rel(root, index))
            if _read(index) != before:
                touched.setdefault(index, repo_of(index))
        else:
            done.uncommitted.append((_rel(root, index), "the index was not rebuilt: %s" % " ".join(r.stderr.split())))
    if commit:
        groups: Dict[Path, List[Path]] = {}
        for path, repo in touched.items():
            if repo is None:
                done.uncommitted.append((_rel(root, path), "in no repository, so changed and not committed"))
            else:
                groups.setdefault(repo, []).append(path)
        message = 'Correct "%s" to "%s"' % (old, new) + ("\n\n" + why.strip() if why.strip() else "")
        for repo, files in sorted(groups.items()):
            ok, said = _commit(repo, sorted(files), message)
            if ok:
                done.commits.append((_rel(root, repo) if repo != root else ".", said))
            else:
                done.refused.append((_rel(root, repo) if repo != root else ".", said))
    status = root.joinpath(*STATUS)
    if rebuild and status.is_file():
        r = subprocess.run([sys.executable, str(status), "--workspace", str(root)], capture_output=True, text=True,
                           timeout=300)
        if r.returncode == 0:
            done.rebuilt.append("System/generated/status.html")
    return done


# --------------------------------------------------------------------------- saying it


def listing(hits: List[Hit], root=None) -> List[dict]:
    """The hits as `--json` prints them."""
    base = Path(root).resolve() if root else None
    say = (lambda p: _rel(base, p)) if base else str
    return [{"path": say(h.path), "kind": h.kind, "repo": say(h.repo) if h.repo else None,
             "lines": [{"line": n, "text": t} for n, t in h.lines],
             "pages": [say(p) for p in h.pages], "edited": h.kind != "raw"} for h in hits]


def report(root: Path, old: str, hits: List[Hit]) -> str:
    if not hits:
        return 'Nothing live holds "%s".' % old
    out = []
    for h in hits:
        out.append("%s\t%s" % (h.kind, _rel(root, h.path)))
        out += ["\t%d: %s" % (n, t[:160]) for n, t in h.lines]
    live = [h for h in hits if h.kind != "raw"]
    raw = [h for h in hits if h.kind == "raw"]
    out.append("")
    out.append('%d live file%s hold "%s".' % (len(live), "" if len(live) == 1 else "s", old))
    if raw:
        pages = sorted({_rel(root, p) for h in raw for p in h.pages})
        out.append("%d raw record%s hold it, and stay as they are; %s" % (
            len(raw), "" if len(raw) == 1 else "s",
            "the page%s resting on them get a superseded line: %s." % ("" if len(pages) == 1 else "s", ", ".join(pages))
            if pages else "no page rests on them."))
    out.append("On a yes, run again with --apply: one commit per repository.")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Find every live copy of a wrong value, and on a yes correct them all.")
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    ap.add_argument("--old", required=True, help="the wrong value, as written")
    ap.add_argument("--new", required=True, help="what it should be")
    ap.add_argument("--apply", action="store_true", help="correct every hit, and commit once per repository")
    ap.add_argument("--why", default="", help="why, in a few words, for the commit and a superseded line")
    ap.add_argument("--leave", action="append", default=[], metavar="PATH", help="a file to leave as it is")
    ap.add_argument("--today", help="YYYY-MM-DD to stamp instead of today")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        root = Path(a.root).expanduser().resolve() if a.root else workspace_root(HERE)
    except FileNotFoundError:
        print("correct: not inside a Garrick workspace", file=sys.stderr)
        return 2
    try:
        hits = find_hits(root, a.old, a.new)
        left = {(root / Path(p).expanduser()).resolve() for p in a.leave}
        hits = [h for h in hits if h.path.resolve() not in left]
        if not a.apply:
            print(json.dumps({"old": a.old, "new": a.new, "hits": listing(hits, root)}, indent=1) if a.json
                  else report(root, a.old, hits))
            return 0
        done = apply(root, a.old, a.new, hits, a.why, a.today)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps({"old": a.old, "new": a.new, "changed": done.changed, "superseded": done.superseded,
                          "commits": done.commits, "uncommitted": done.uncommitted, "refused": done.refused,
                          "rebuilt": done.rebuilt}, indent=1))
    else:
        if not done.changed:
            print('Nothing live holds "%s"; nothing changed.' % a.old)
        else:
            print("Corrected %d file%s." % (len(done.changed), "" if len(done.changed) == 1 else "s"))
        for repo, commit in done.commits:
            print("Committed in %s: %s" % (repo, commit))
        for path, why in done.uncommitted:
            print("Not committed: %s (%s)" % (path, why))
        for repo, why in done.refused:
            print("Refused in %s: %s" % (repo, why))
        for page in done.superseded:
            print("Marked superseded: %s" % page)
    return 1 if done.refused else 0


if __name__ == "__main__":
    sys.exit(main())
