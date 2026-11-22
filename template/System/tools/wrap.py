#!/usr/bin/env python3
"""The wrap, as one command: the assistant writes the judgment, this does the transaction.

    python3 System/tools/wrap.py < wrap.json
    python3 System/tools/wrap.py --json --input wrap.json

The threads skill's *Wrap* gathers what the session did and decided, runs the
wall check's questions with the user, and writes the words. This tool takes
those words as one JSON object and does every step that needs no judgment, in
this order: the lock (`wrap_lock.py`), the Resume here block, the dated entry,
`updated:`, the checkpoint folded in, the Todo ticks and new lines, the history
mover, the Todo archive, staging by literal path, one commit through the zone's
own hooks, the finish record, and the lock's end.

The input, one JSON object. A key not listed here, or a required key missing,
fails the wrap with nothing written.

    zone      the zone's folder name                                     required
    project   the project's folder name                                  required
    thread    the thread's folder name; leave it out for a project that
              keeps its resume point in its hub                          optional
    resume    {"stands": "<two or three sentences>",                      required
               "rows": {"Live artifact": "", "Rebuild with": "",
                        "Next action": "", "Keep in mind": "",
                        "Waiting on": "", "Deadline": ""}}
              all six rows, each one line, none empty
    entry     the dated entry's text, without its date; the tool puts     required
              today's date in front
    message   the commit message: what changed, one line                 required
    todo      {"add": ["<action line>", ...], "tick": ["<words of an open line>", ...]}
              a line to tick must be the only open line that says it
    checkpoint  "folded", once the note's `### Checkpoint` block has been read and folded into
              the words above; a note that holds one and a wrap that does not say so fail
    memory    {"path": "<an entry file of the assistant's memory folder>"}
              the tool writes the pointer's words itself, from the zone, project, thread
              and the note's path, with no status. The path, once resolved, must be a
              .md file directly in `~/.claude/projects/<folder>/memory/`, never
              MEMORY.md and never a link; a file already there that is not this
              tool's pointer for this note is never rewritten (the wrap fails)
    lock      "take" (the default), or "held" when the band or the request has taken the lock

What it writes, and nothing else: the thread note (or the hub, for a project
that keeps its resume point there), its zone's `Todo.md` and `archive/` lines,
the `history/` files beside the note, the records in `System/generated/`, and
the named memory pointer. It stages those files by literal path, never `-A`,
and commits in the zone's repository only, so a repository it did not change
gets no commit. The wall check runs as the hook of that repository, as it
runs for any commit.

The receipt is one of four, in this tool's words, as one plain sentence or, with
`--json`, as an object with `outcome`, `say`, `commit`, `files` and `notes`:

    saved     the commit was made, or there was nothing to commit
    refused   the zone's hook refused the commit; its sentence is the reason
    conflict  another session moved the repository, or the note, while this ran
    failed    anything else, with the reason in plain words

Exit 0 only for *saved*. Only *saved* writes the finish record
(`wrap_lock.py end`); every other outcome releases the lock with
`end --abandon`, and puts back every file this run wrote, so a second run
starts from the note as it was. A wrap killed between its writes and its
commit leaves the lock, which counts as gone after ten minutes, and the files
it wrote, which `git status` shows. Standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import garrick_lib as gl  # noqa: E402
import history as hist  # noqa: E402
import wrap_lock as wl  # noqa: E402
try:
    import work  # noqa: E402
except ImportError:  # a tools folder an update left half copied: every wrap fails, nothing written
    work = None

OUTCOMES = ("saved", "refused", "conflict", "failed")
ROWS = ("Live artifact", "Rebuild with", "Next action", "Keep in mind", "Waiting on", "Deadline")
REQUIRED = ("zone", "project", "resume", "entry", "message")
ALLOWED = REQUIRED + ("thread", "todo", "checkpoint", "memory", "lock")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
MAX_LINE = 200                  # the length check.py warns about for a Todo line
EXAMPLE_LINE = "- [ ] [[<Thread>]]:"
# Words git itself uses when a commit fails for a reason that is not a hook's refusal.
GIT_OWN = ("author identity unknown", "please tell me who you are", "unable to auto-detect", "index.lock",
           "nothing to commit", "unable to create", "cannot lock", "not a git repository", "bad object",
           "could not read", "unable to write")


class Stop(Exception):
    """A wrap that ends here, with the outcome it ends in and its reason in plain words."""

    def __init__(self, outcome: str, why: str):
        super().__init__(why)
        self.outcome, self.why = outcome, why


def failed(why: str) -> Stop:
    return Stop("failed", why)


# ---------------------------------------------------------------------------
# The input


def one_line(value, field: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise failed("%s is empty or is not text" % field)
    if "\n" in value or "\r" in value:
        raise failed("%s must be one line" % field)
    if len(value) > limit:
        raise failed("%s is too long" % field)
    return value.strip()


def prose(value, field: str, limit: int = 6000) -> str:
    """Text for the note's body: no line may be a heading, a rule, a table row or a marker, which would
    change the note's structure."""
    if not isinstance(value, str) or not value.strip():
        raise failed("%s is empty or is not text" % field)
    if len(value) > limit or "\r" in value:
        raise failed("%s is too long, or has carriage returns" % field)
    for line in value.splitlines():
        flat = line.strip()
        if re.match(r"^(#{1,6}\s|---+\s*$|\||<!--)", flat):
            raise failed("%s has a line that would change the note's layout" % field)
    return value.strip()


def cell(value: str) -> str:
    return value.replace("|", "\\|")


def check_input(data) -> dict:
    if not isinstance(data, dict):
        raise failed("the input is not one JSON object")
    unknown = sorted(set(data) - set(ALLOWED))
    if unknown:
        raise failed("the input has a key the wrap does not take: %s" % ", ".join(unknown))
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        raise failed("the input is missing: %s" % ", ".join(missing))
    out = {}
    for name in ("zone", "project", "thread"):
        if name == "thread" and data.get("thread") in (None, ""):
            continue
        value = data[name]
        if (not isinstance(value, str) or not value or value in (".", "..") or "/" in value or "\\" in value
                or "\x00" in value or value.startswith(("_", "."))):
            raise failed("%s is not the name of a folder in the workspace" % name)
        out[name] = value
    resume = data["resume"]
    if not isinstance(resume, dict) or set(resume) != {"stands", "rows"} or not isinstance(resume["rows"], dict):
        raise failed("resume must hold stands and rows, and nothing else")
    if set(resume["rows"]) != set(ROWS):
        raise failed("resume rows must be exactly: %s" % ", ".join(ROWS))
    out["stands"] = prose(resume["stands"], "resume stands")
    out["rows"] = {k: one_line(resume["rows"][k], "the %s row" % k) for k in ROWS}
    out["entry"] = prose(data["entry"], "entry")
    out["message"] = one_line(data["message"], "message", 300)
    todo = data.get("todo") or {}
    if not isinstance(todo, dict) or set(todo) - {"add", "tick"}:
        raise failed("todo takes add and tick, and nothing else")
    out["add"], out["tick"] = [], []
    for kind in ("add", "tick"):
        lines = todo.get(kind) or []
        if not isinstance(lines, list):
            raise failed("todo %s must be a list" % kind)
        for line in lines:
            line = one_line(line, "a todo %s line" % kind, MAX_LINE)
            out[kind].append(line)
    if data.get("checkpoint") not in (None, "folded"):
        raise failed("checkpoint is either left out or \"folded\"")
    out["folded"] = data.get("checkpoint") == "folded"
    if data.get("lock", "take") not in ("take", "held"):
        raise failed("lock is either \"take\" or \"held\"")
    out["lock"] = data.get("lock", "take")
    memory = data.get("memory")
    if memory is not None:
        if not isinstance(memory, dict) or set(memory) != {"path"}:
            raise failed("memory takes a path, and nothing else: the tool writes the pointer's words itself")
        out["memory"] = one_line(memory["path"], "the memory path", 1000)
    return out


# ---------------------------------------------------------------------------
# Where the resume point is


def has_resume(text: str) -> bool:
    return any(l.strip().lower() == gl.RESUME_HEADING.lower() for l in text.splitlines())


def resume_note(root: Path, zone: str, project: str, thread: Optional[str]) -> Optional[Path]:
    """The note that holds the Resume here block of what is being wrapped: the thread's own note, or the hub of
    a project that keeps its resume point there. The one place this tool decides it, and it asks the one reader of the
    piece of work (`work.py`), so a change to the unit of work is made there."""
    if work is None:
        raise Stop("failed", "the reader of the pieces of work (System/tools/work.py) is missing; update Garrick, then wrap again")
    found = [w for w in work.pieces(root, zone=zone) if w.project == project and w.kind == "piece"]
    if thread:
        for w in found:
            if w.thread == thread and has_resume(w.note.read_text(encoding="utf-8", errors="replace")):
                return w.note
    for w in found:
        if w.thread is None and w.keeps_resume:
            return w.note
    return None


# ---------------------------------------------------------------------------
# The note's new text


def human(day: datetime.date) -> str:
    return "%d %s %d" % (day.day, MONTHS[day.month - 1], day.year)


def block_lines(job: dict, today: datetime.date) -> List[str]:
    out = [gl.RESUME_HEADING, "", "**Where it stands, %s.** %s" % (human(today), job["stands"]), "", "| | |", "|---|---|"]
    out += ["| %s | %s |" % (k, cell(job["rows"][k])) for k in ROWS]
    return out


def without_checkpoint(text: str, folded: bool) -> str:
    found = gl.checkpoint_span(text)
    if found is None:
        return text
    start, end = found
    if end is None:
        raise failed("the note has a checkpoint block that is not closed, which is never rewritten")
    if not folded:
        raise failed("the note holds a checkpoint that has not been folded in: read it, fold it into the words, and send checkpoint folded")
    head = text[:start].rstrip()
    if head.endswith(gl.CHECKPOINT_HEADING):
        head = head[: -len(gl.CHECKPOINT_HEADING)].rstrip("\n") + "\n"
    else:
        head = text[:start]
    return head + "\n" + text[end:].lstrip("\n") if text[end:].strip() else head


def set_updated(text: str, today: datetime.date) -> str:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise failed("the note has no frontmatter, so its updated date cannot be set")
    close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), -1)
    if close < 0:
        raise failed("the note's frontmatter is not closed")
    for i in range(1, close):
        if re.match(r"^updated:", lines[i]):
            lines[i] = "updated: %s" % today.isoformat()
            return "\n".join(lines)
    lines.insert(close, "updated: %s" % today.isoformat())
    return "\n".join(lines)


def new_note_text(text: str, job: dict, today: datetime.date) -> str:
    if "\r" in text:
        raise failed("the note has carriage returns, which a wrap does not rewrite")
    text = without_checkpoint(text, job["folded"])
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == gl.RESUME_HEADING.lower()), -1)
    if start < 0:
        raise failed("the note has no Resume here block")
    end = next((i for i in range(start + 1, len(lines)) if gl.RESUME_STOP_RE.match(lines[i].strip())), len(lines))
    new_block = block_lines(job, today) + [""]
    has_rule = end < len(lines) and lines[end].strip() == "---"
    lines[start:end] = new_block + ([] if has_rule else ["---", ""])
    rule = start + len(new_block)
    entry = "**%s.** %s" % (human(today), job["entry"])
    tail = lines[rule + 1:]
    if not tail or tail[0].strip():
        tail = [""] + tail
    lines = lines[: rule + 1] + ["", entry] + tail
    return set_updated("\n".join(lines), today)


# ---------------------------------------------------------------------------
# The Todo list


def todo_lines_after(text: str, job: dict, today: datetime.date) -> Tuple[str, List[str]]:
    """Todo.md with this wrap's ticks and new lines, and what was already there."""
    lines = text.split("\n")
    notes: List[str] = []
    for want in job["tick"]:
        norm = gl.same_action(want)
        open_ = [i for i, l in enumerate(lines) if l.startswith("- [ ] ")]
        hit = [i for i in open_ if gl.same_action(lines[i]) == norm] or [i for i in open_ if norm and norm in gl.same_action(lines[i])]
        if not hit:
            raise failed("no open line in Todo.md says: %s" % want[:80])
        if len(hit) > 1:
            raise failed("%d open lines in Todo.md say that: %s" % (len(hit), want[:80]))
        lines[hit[0]] = "- [x] " + lines[hit[0]][6:].rstrip() + " ✅ " + today.isoformat()
    fresh = []
    for want in job["add"]:
        line = want if want.startswith("- [ ] ") else "- [ ] " + want
        if any(gl.same_action(l) == gl.same_action(line) for l in lines + fresh if l.startswith("- [ ] ")):
            notes.append("A line was already on the list: %s" % want[:80])
            continue
        fresh.append(line)
    if fresh:
        lines = [l for l in lines if not l.startswith(EXAMPLE_LINE)]       # the example goes with the first real action
        inbox = next((i for i, l in enumerate(lines) if l.strip() == "## Inbox"), -1)
        if inbox < 0:
            raise failed("Todo.md has no Inbox section to add a line to")
        stop = next((i for i in range(inbox + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        last = max((i for i in range(inbox + 1, stop) if lines[i].strip()), default=None)
        if last is None:
            lines[inbox + 1:stop] = [""] + fresh + [""]
        else:
            lines[last + 1:last + 1] = fresh
    return "\n".join(lines), notes


def todo_module(root: Path):
    for tool in (root / "System" / "skills" / "todo" / "todo.py", HERE.parent / "skills" / "todo" / "todo.py"):
        if tool.is_file():
            spec = importlib.util.spec_from_file_location("garrick_wrap_todo", str(tool))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


# ---------------------------------------------------------------------------
# The memory pointer


def pointer_text(job: dict, rel: str) -> str:
    """The words of the memory pointer: where the resume point is, and nothing else. Built here from the names and the
    note's path, so no word of the assistant's reaches a folder every zone's sessions load."""
    return "%s (%s zone). Resume from %s, the Resume here block. Read it before anything else in the thread." % (
        name_of(job), job["zone"], rel)


def pointer_file(text: str, rel: str, today: datetime.date) -> str:
    return "---\nsource: file:%s\ncreated: %s\n---\n%s\n" % (rel, today.isoformat(), text)


def memory_target(root: Path, path: str, job: dict, rel: str) -> Path:
    """The memory file this wrap may write, or a failure. It is a file of the assistant's own memory folder,
    `~/.claude/projects/<folder>/memory/<name>.md`, by its resolved path: the folder may be a link, the file may not.
    Codex documents no memory folder here, so none is allowed. An existing file is accepted only if it is the pointer this
    tool writes for this note; any other is never rewritten."""
    given = Path(path)
    if not given.is_absolute() or given.is_symlink():
        raise failed("the memory path is not an entry file of the assistant's memory folder")
    where = given.resolve()
    if where.suffix != ".md" or where.name.lower() == "memory.md":
        raise failed("the memory path is not an entry file of the assistant's memory folder")
    base = (Path.home() / ".claude" / "projects").resolve()
    try:
        parts = where.relative_to(base).parts
    except ValueError:
        parts = ()
    if len(parts) != 3 or parts[1] != "memory" or root in where.parents:
        raise failed("the memory path is not in the assistant's own memory folder")
    if not where.parent.is_dir():
        raise failed("the memory folder is not there")
    if where.exists():
        old = where.read_text(encoding="utf-8", errors="replace")
        match = re.match(r"---\nsource: file:(.*)\ncreated: \d{4}-\d{2}-\d{2}\n---\n(.*)\n\Z", old, re.S)
        if not (match and match.group(1) == rel and match.group(2) == pointer_text(job, rel)):
            raise failed("a file is already there that is not this wrap's pointer, and it is never rewritten")
    return where


def write_memory(where: Path, job: dict, rel: str, today: datetime.date) -> str:
    """Create the pointer; leave the one that is there. A note for the reply."""
    if not where.exists():
        where.write_text(pointer_file(pointer_text(job, rel), rel, today), encoding="utf-8")
    return ""


# ---------------------------------------------------------------------------
# Git


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + list(args), cwd=str(repo), env=gl.own_repo_env(), capture_output=True, text=True)


def literal(path: str) -> str:
    return ":(literal)" + path


def head_of(repo: Path) -> str:
    r = git(repo, "rev-parse", "--verify", "-q", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else ""


def changed_among(repo: Path, places: List[str]) -> List[str]:
    """The files git reports as changed or new under `places` (zone-relative paths, files or folders), by name."""
    r = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *[literal(p) for p in places])
    if r.returncode != 0:
        raise failed("git could not list what changed: %s" % " ".join(r.stderr.split())[:200])
    out, parts = [], [p for p in r.stdout.split("\0") if p]
    skip = False
    for entry in parts:
        if skip:
            skip = False
            continue
        code, name = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            skip = True
        out.append(name)
    return out


def hook_sentence(text: str) -> str:
    lines = [" ".join(l.split()) for l in text.splitlines() if l.strip()]
    return " ".join(lines)[:600]


class Snapshot:
    """What the files this wrap may write held before it wrote them, so that every outcome but *saved* can put
    them back. A folder is kept by its files: a file made since is removed."""

    def __init__(self):
        self.files: Dict[Path, Optional[bytes]] = {}
        self.folders: List[Path] = []
        self.existed: Dict[Path, bool] = {}

    def take(self, path: Path) -> None:
        if path not in self.files:
            self.files[path] = path.read_bytes() if path.is_file() else None

    def take_folder(self, folder: Path) -> None:
        self.folders.append(folder)
        self.existed[folder] = folder.is_dir()
        if folder.is_dir():
            for p in folder.rglob("*"):
                if p.is_file():
                    self.take(p)

    def changed(self) -> List[Path]:
        """The files of the kept folders that this run made or changed, and no other: another session's file there is
        none of them."""
        out = []
        for folder in self.folders:
            if folder.is_dir():
                for p in sorted(folder.rglob("*")):
                    if p.is_file() and (p not in self.files or self.files[p] != p.read_bytes()):
                        out.append(p)
        return out

    def restore(self) -> None:
        for folder in self.folders:
            if folder.is_dir():
                for p in sorted(folder.rglob("*")):
                    if p.is_file() and p not in self.files:
                        self.files[p] = None
        for path, data in self.files.items():
            try:
                if data is None:
                    if path.is_file():
                        path.unlink()
                elif not path.is_file() or path.read_bytes() != data:
                    path.write_bytes(data)
            except OSError:
                pass
        for folder, there in self.existed.items():          # a folder this run made, and nothing now in it
            try:
                if not there and folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# The wrap


def receipt(outcome: str, say: str, commit: str = "", files=(), notes=()) -> dict:
    return {"outcome": outcome, "say": say, "commit": commit, "files": list(files), "notes": [n for n in notes if n]}


def name_of(job: dict) -> str:
    return "%s, %s" % (job["project"], job["thread"]) if job.get("thread") else job["project"]


def run(root, data, today: Optional[datetime.date] = None, before_commit: Optional[Callable[[], None]] = None) -> dict:
    """Wrap one thread from `data`; returns the receipt. `before_commit` is a seam for tests: it runs after the
    files are written and before the commit, where another session could move the repository."""
    root = Path(root).resolve()
    today = today or datetime.date.today()
    try:
        job = check_input(data)
        zone = root / "Zones" / job["zone"]
        base = zone / job["project"]
        if not zone.is_dir() or not base.is_dir() or zone.resolve().parent != (root / "Zones").resolve() \
                or base.resolve().parent != zone.resolve():
            raise failed("that zone or project is not in this workspace")
        if job.get("thread") and not (base / "Threads" / job["thread"]).is_dir():
            raise failed("that thread is not in this project")
        note = resume_note(root, job["zone"], job["project"], job.get("thread"))
        if note is None:
            raise failed("no Resume here block was found for it: not in the thread's note, and the project's hub keeps none")
        if zone.resolve() not in note.resolve().parents:
            raise failed("the note is not inside its zone")
        text = note.read_text(encoding="utf-8")
        status = str(gl.parse_frontmatter_text(text).get("status") or "active").lower()
        if status in ("done", "parked"):
            raise failed("%s is %s, so it is not wrapped; open or wake it first" % (name_of(job), status))
        rel = note.relative_to(root).as_posix()
        in_zone = note.relative_to(zone).as_posix()
        problem = gl.wall_hook_problem(zone)
        if problem:
            raise failed(problem)
        new_text = new_note_text(text, job, today)
        memory = memory_target(root, job["memory"], job, rel) if job.get("memory") else None
        todo_path = zone / "Todo.md"
        for place in (todo_path, zone / "archive", note.parent / hist.FOLDER):     # a link that leaves the zone is never written through
            if (place.exists() or place.is_symlink()) and zone.resolve() not in (place.resolve(), *place.resolve().parents):
                raise failed("%s leads out of the %s zone, so nothing was written" % (place.name, job["zone"]))
        if (job["add"] or job["tick"]) and not todo_path.is_file():
            raise failed("the %s zone has no Todo.md" % job["zone"])
        todo = todo_module(root) if todo_path.is_file() else None
        if todo_path.is_file() and todo is None:
            raise failed("the todo skill is not here, so the list cannot be archived")
    except Stop as stop:
        release_held(root, data)
        return receipt(stop.outcome, say_for(stop.outcome, stop.why, data))
    except (OSError, ValueError) as exc:
        release_held(root, data)
        return receipt("failed", say_for("failed", "a file could not be read: %s" % exc, data))

    locked = False
    if job["lock"] == "take":
        try:
            if not wl.start(root, rel):
                return receipt("failed", "Failed: a wrap of %s is already running." % name_of(job))
        except (ValueError, OSError) as exc:
            return receipt("failed", "Failed: the wrap could not take its lock: %s." % exc)
        locked = True
    saved = False
    snap = Snapshot()
    try:
        out = transact(root, zone, job, note, in_zone, rel, text, new_text, todo, today, snap, before_commit, memory)
        saved = out["outcome"] == "saved"
        return out
    except Stop as stop:
        snap.restore()
        return receipt(stop.outcome, say_for(stop.outcome, stop.why, job))
    except BaseException as exc:                       # an interrupt, or a fault: put the files back, release the lock
        snap.restore()
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return receipt("failed", "Failed: %s: %s." % (type(exc).__name__, exc))
    finally:
        if saved:
            wl.end(root, rel)
        else:
            wl.end(root, rel, abandon=True)


def release_held(root: Path, data) -> None:
    """A lock the band took stays the wrap's to release even when the wrap fails before it starts. The input may be what
    failed, so only a request that says `held` and names its folders plainly is read; the lock is the one of the thread's
    note or of the hub, whichever the band took."""
    if not isinstance(data, dict) or data.get("lock") != "held":
        return
    names = [data.get(k) for k in ("zone", "project")] + ([data["thread"]] if data.get("thread") else [])
    if not all(isinstance(n, str) and n and "/" not in n and "\\" not in n and n not in (".", "..") for n in names):
        return
    zone, project = names[0], names[1]
    notes = ["Zones/%s/%s/%s.md" % (zone, project, project)]
    if len(names) == 3:
        notes.insert(0, "Zones/%s/%s/Threads/%s/%s.md" % (zone, project, names[2], names[2]))
    for rel in notes:
        try:
            wl.end(root, rel, abandon=True)
        except (ValueError, OSError):
            pass


def say_for(outcome: str, why: str, job) -> str:
    if outcome == "refused":
        return "Refused: %s" % why          # the hook's own sentence, as it said it
    why = why.rstrip(".")
    if outcome == "conflict":
        return "Conflict: %s. Nothing was saved; run the wrap again." % why
    return "Failed: %s." % why


def transact(root, zone, job, note, in_zone, rel, text, new_text, todo, today, snap, before_commit, memory) -> dict:
    head0 = head_of(zone)
    notes: List[str] = []
    snap.take(note)
    original = note.read_bytes()
    if original != text.encode("utf-8"):
        raise Stop("conflict", "%s changed while the wrap was being written" % name_of(job))
    todo_path = zone / "Todo.md"
    archive_dir = zone / "archive"
    history_dir = note.parent / hist.FOLDER
    snap.take_folder(archive_dir)
    snap.take_folder(history_dir)
    if todo_path.is_file():
        snap.take(todo_path)
    # 1. the note: written only if it is still what was read
    mine = new_text.encode("utf-8")
    if not gl.write_if_unchanged(note, new_text, original):
        raise Stop("conflict", "%s changed while the wrap was being written" % name_of(job))
    # 2. the history mover, on the note just written
    moved = hist.apply(root, note, today)
    if moved.error:
        raise failed("the older entries could not be moved to history: %s" % moved.error)
    if moved.skipped:
        notes.append("History: %s" % moved.skipped)
    after_history = note.read_bytes()
    # 3. the Todo ticks and new lines, then the archive of what was ticked before today
    if todo is not None:
        before = todo_path.read_text(encoding="utf-8")
        changed, todo_notes = todo_lines_after(before, job, today)
        notes += todo_notes
        if changed != before:
            todo_path.write_text(changed, encoding="utf-8")
        archived = todo.archive(zone, today)
        if archived:
            notes.append("%d done line%s moved to the archive." % (archived, "" if archived == 1 else "s"))
    words = hist.resume_words(note.read_text(encoding="utf-8"))
    cap = hist.limits(root)["resume-max-words"]
    if words > cap:
        notes.append("The Resume block is %d words, over its %d. Want a shorter one?" % (words, cap))
    # 4. what changed, by name
    places = [in_zone, "Todo.md"] + [p.relative_to(zone).as_posix() for p in snap.changed()]       # the files it wrote, by name
    files = changed_among(zone, places)
    if before_commit is not None:
        before_commit()
    if head_of(zone) != head0:
        raise Stop("conflict", "another session committed in the %s zone while the wrap ran" % job["zone"])
    if note.read_bytes() != after_history:
        raise Stop("conflict", "%s changed while the wrap ran" % name_of(job))
    if not files:
        notes.append("There was nothing to commit: the note was already current.")
        commit = ""
    else:
        added = git(zone, "add", "--", *[literal(f) for f in files])
        if added.returncode != 0:
            git(zone, "reset", "-q", "--", *[literal(f) for f in files])
            raise failed("git could not stage the files: %s" % " ".join(added.stderr.split())[:200])
        staged = [p for p in git(zone, "diff", "--cached", "--name-only", "-z").stdout.split("\0") if p]
        stray = sorted(set(staged) - set(files))
        if stray:
            git(zone, "reset", "-q", "--", *[literal(f) for f in files])
            raise failed("other files were already staged in the %s zone, so nothing was committed" % job["zone"])
        done = git(zone, "commit", "-q", "-m", job["message"])
        if done.returncode != 0:
            git(zone, "reset", "-q", "--", *[literal(f) for f in files])
            said = (done.stderr + "\n" + done.stdout)
            if any(w in said.lower() for w in GIT_OWN):
                raise failed("git did not commit: %s" % hook_sentence(said)[:300])
            raise Stop("refused", hook_sentence(said) or "the zone's hook refused the commit")
        commit = git(zone, "rev-parse", "--short", "HEAD").stdout.strip()
    if memory is not None:
        try:
            extra = write_memory(memory, job, rel, today)
            notes.append(extra)
        except OSError as exc:
            notes.append("The memory pointer was not written: %s." % exc)
    say = "Saved: %s is wrapped." % name_of(job)
    return receipt("saved", say, commit, files, notes)


# ---------------------------------------------------------------------------
# The command line


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Wrap one thread from the assistant's words: the transaction, with a receipt.")
    ap.add_argument("--input", default="-", help="the JSON file, or - for standard input")
    ap.add_argument("--json", action="store_true", help="print the receipt as JSON")
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else HERE.parents[1]
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(SystemExit(143)))
    try:
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        out = receipt("failed", "Failed: the input is not readable JSON.")
    else:
        today = datetime.date.fromisoformat(args.today) if args.today else None
        out = run(root, data, today)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print("\n".join([out["say"]] + out["notes"]))
    return 0 if out["outcome"] == "saved" else 1


if __name__ == "__main__":
    sys.exit(main())
