#!/usr/bin/env python3
"""inbox_run.py: Process the Inbox in the background (#634).

    python3 inbox_run.py run --workspace WS [--answer ZONE FILE LABEL] [--lock-fd N]

The button runs the `intake` skill headless, once, at the workspace root: one call through agent.run_prepared() under the jobs
extra's deny profile (no send, share or delete), with the assistant found as the Ask box finds it. The call may write only
where intake files things. That is checked, not only asked for: before the call every repository (each zone, the Meetings
wiki and the Knowledge wiki) is recorded; after it every changed path is compared with the allowed set, and a change outside it
puts every repository back as it was and every inbox item back where it was, so nothing is kept. Each repository the call
changed is then committed once, through its own hooks, by path; a commit a hook refuses is put back, and the items in that
repository's inbox stay in it.

One run at a time: the page's verb takes an exclusive lock in the jobs folder and hands it to this process, which holds it until
it ends. The result is kept for the page in `System/generated/status-inbox.json`: one place at a time (a zone, Meetings, the
workspace's own Inbox) and never a sum of two.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import channels  # noqa: E402
import engine  # noqa: E402

STATE = ("System", "generated", "status-inbox.json")
JOB = "inbox"                       # the ledger's name for this call
TIER = "sonnet"
TIMEOUT = 1200                      # seconds the one call may take
LOCK = "inbox-run.lock"
MOST_BACKUP_BYTES = 200 * 1024 * 1024       # more waiting than this is left to a visible session
MOST_BACKUP_FILES = 3000
MOST_KEPT = 2 * 1024 * 1024         # a file already changed before the run is kept in memory to put back, up to this size
NEEDS = "Needs you"
# What the call may run: the file tools, and one rule for each subcommand of the two scripts that the intake skill's
# unattended section uses. A subcommand that writes `System/` (`learn`, `person`) or leaves the inbox's own rules
# (`move-to-zone`, `file-note`, `process-notes`, `split`) is not here (S1). Nothing else.
INTAKE_SUBS = ("list", "parse", "file-conversation", "file-reading", "file-to-project", "extract-attachment", "skip", "ask")
INGEST_SUBS = ("land", "index", "log", "link")
ALLOW = ["Read", "Grep", "Glob", "Edit", "Write"] \
    + ["Bash(python3 System/skills/intake/intake.py %s:*)" % sub for sub in INTAKE_SUBS] \
    + ["Bash(python3 System/skills/meetings/ingest.py %s:*)" % sub for sub in INGEST_SUBS]
# What the run must leave as it found it: the files that decide a wall and the code a run could change under itself.
WATCHED_FILES = ("context.md", "rules.md", "rules.local.md")           # in System/
ROOT_FILES = ("AGENTS.md", "AGENTS.local.md")                           # in the workspace root
WATCHED_TREES = ("skills", "tools")                                     # under System/
SAY_BUSY = "The inbox is being processed already. Nothing new was started."
SAY_UNAVAILABLE = "The background assistant is not available, so this goes to a visible one."
SAY_FAILED = "The inbox could not be processed in the background."
SAY_REFUSED = "The assistant changed something it may not, so nothing was kept. The items are still in the inbox."
SAY_KEPT = "Something changed that the run may not change, so nothing was committed or put back in %s. Those files are left as they are."
SAY_SYSTEM = "The assistant changed a file of the workspace's rules or tools, so nothing was kept. That file was left as it is."
MEETINGS_INBOX = ("Wikis", "Meetings", "raw", "inbox")


# ---- what is allowed ------------------------------------------------------------------------------------------------

def allowed(rel: str) -> bool:
    """Whether a path from the workspace is one the inbox run may change: an inbox, the Meetings and Knowledge wikis, a
    project's or a thread's own `Sources/`, a zone's `Todo.md` and its `Needs you` question files, the workspace's own Inbox."""
    parts = rel.split("/")
    if not parts or any(p in ("", ".", "..", ".git") for p in parts):
        return False
    if parts[0] == "Inbox":
        return len(parts) >= 2
    if parts[0] == "Wikis":
        return len(parts) >= 3 and parts[1] in ("Meetings", "Knowledge")
    if parts[0] != "Zones" or len(parts) < 3 or parts[1].startswith((".", "_")):
        return False
    rest = parts[2:]
    if rest[0] in ("Inbox", NEEDS):
        return len(rest) >= 2
    if rest == ["Todo.md"]:
        return True
    if rest[0].startswith((".", "_")) or rest[0] == "archive":
        return False
    if len(rest) >= 3 and rest[1] == "Sources":
        return True
    return len(rest) >= 5 and rest[1] == "Threads" and rest[3] == "Sources"


def system_hash(ws: Path) -> str:
    """One hash over the files that decide a wall and the code a run could change under itself: `System/context.md`, the rules
    files, and every file under `System/skills` and `System/tools`. A run that leaves a different hash was not a run that only
    files (S1)."""
    h = hashlib.sha1()
    files = [ws / "System" / f for f in WATCHED_FILES]
    for tree in WATCHED_TREES:
        base = ws / "System" / tree
        if base.is_dir():
            files += sorted(p for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    files += [ws / n for n in ROOT_FILES]
    shared = ws / "Zones" / ".shared"                    # a link there is a share; one added or pointed elsewhere is a change (C3)
    if shared.is_dir():
        for e in sorted(shared.iterdir()):
            h.update(e.name.encode("utf-8", "replace") + b"\0" + (os.readlink(str(e)).encode("utf-8", "replace") if e.is_symlink() else b"-") + b"\0")
    for f in files:
        h.update(str(f.relative_to(ws)).encode("utf-8", "replace") + b"\0")
        try:
            h.update(signature(f).encode("ascii") + b"\0")
        except OSError:
            h.update(b"unreadable\0")
    return h.hexdigest()


def inboxes(ws: Path) -> Dict[str, Path]:
    """The place's name (a zone, Meetings, or Inbox for the workspace's own) and the folder that holds its items."""
    out = {}
    zones = ws / "Zones"
    for z in sorted(zones.iterdir()) if zones.is_dir() else []:
        if z.is_dir() and not z.is_symlink() and not z.name.startswith((".", "_")) and (z / "Inbox").is_dir():
            out[z.name] = z / "Inbox"
    meetings = ws.joinpath(*MEETINGS_INBOX)
    if meetings.is_dir():
        out["Meetings"] = meetings
    if (ws / "Inbox").is_dir():
        out["Inbox"] = ws / "Inbox"
    return out


def waiting(folder: Path) -> List[str]:
    return sorted(p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")) if folder.is_dir() else []


def question_files(ws: Path) -> Dict[str, List[str]]:
    out = {}
    zones = ws / "Zones"
    for z in sorted(zones.iterdir()) if zones.is_dir() else []:
        box = z / NEEDS
        if z.is_dir() and not z.is_symlink() and box.is_dir() and not box.is_symlink():
            out[z.name] = sorted(f.name for f in box.glob("*.md") if f.is_file() and not f.name.startswith((".", "_")))
    return out


# ---- repositories ---------------------------------------------------------------------------------------------------

def git(repo: Path, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "--literal-pathspecs", *args], cwd=str(repo), capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, env=engine.agent_lib().own_repo_env())


def repositories(ws: Path) -> List[Path]:
    """The repositories the run may touch: each zone's own, the Meetings wiki's and the Knowledge wiki's, each once."""
    found, seen = [], set()
    folders = [z for z in sorted((ws / "Zones").iterdir()) if z.is_dir() and not z.is_symlink() and not z.name.startswith((".", "_"))] \
        if (ws / "Zones").is_dir() else []
    folders += [ws / "Wikis" / "Meetings", ws / "Wikis" / "Knowledge"]
    for f in folders:
        if not f.is_dir():
            continue
        top = git(f, "rev-parse", "--show-toplevel").stdout.strip()
        if top and Path(top).resolve() not in seen:
            seen.add(Path(top).resolve())
            found.append(Path(top).resolve())
    return found


def dirty(repo: Path) -> Optional[List[str]]:
    """The paths `git status` shows as changed in a repository, from it; None when git does not answer."""
    r = git(repo, "status", "--porcelain", "-z", "--untracked-files=all", "--no-renames")
    if r.returncode != 0:
        return None
    return sorted({e[3:] for e in r.stdout.split("\0") if len(e) > 3})


def signature(path: Path) -> str:
    if path.is_symlink():
        return "link:" + os.readlink(str(path))
    if not path.exists():
        return "gone"
    if path.is_dir():
        return "dir"
    h = hashlib.sha1()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Snapshot:
    """What every repository held before the call: its HEAD, the paths already changed, each one's signature, and the bytes of
    the small ones, so that a path the call changes again is put back as the user left it."""

    def __init__(self, ws: Path):
        self.ws = ws
        self.repos = repositories(ws)
        self.head, self.sig, self.kept, self.ok = {}, {}, {}, True
        for r in self.repos:
            self.head[r] = git(r, "rev-parse", "HEAD").stdout.strip()
            paths = dirty(r)
            if paths is None:
                self.ok = False
                paths = []
            for p in paths:
                full = r / p
                self.sig[(r, p)] = signature(full)
                try:
                    if full.is_file() and not full.is_symlink() and full.stat().st_size <= MOST_KEPT:
                        self.kept[(r, p)] = full.read_bytes()
                except OSError:
                    pass

    def moved(self) -> Dict[Path, List[str]]:
        """Each repository's paths the call changed, from the repository: a path that is changed now and was not before, and a
        path that was changed before and holds something else now (or is clean now)."""
        out = {}
        for r in self.repos:
            now = set(dirty(r) or [])
            before = {p for (rr, p) in self.sig if rr == r}
            out[r] = sorted(p for p in now | before
                            if (p in before and signature(r / p) != self.sig[(r, p)]) or (p not in before and p in now))
        return out

    def untouched_head(self) -> bool:
        return all(git(r, "rev-parse", "HEAD").stdout.strip() == self.head[r] for r in self.repos)


def put_back(snap: Snapshot, repo: Path, paths: List[str]) -> List[str]:
    """Put each path back as it was before the call: a file that was changed already, with the bytes then kept; a tracked file
    as the last commit has it; a file the call made, removed. Only a path that `allowed()` names, with no link on the way, is
    ever touched (S2): any other is left exactly as it is and returned. A file about to be reverted or removed is first copied
    into the repository's own `.git/garrick-put-back/`, so a writer that was not the call loses nothing. Returns the paths that
    were not put back."""
    left = []
    keep = repo / ".git" / "garrick-put-back" / time.strftime("%Y%m%d-%H%M%S")
    for p in paths:
        full = repo / p
        try:
            rel = str(full.relative_to(snap.ws)).replace(os.sep, "/")
            if not allowed(rel) or linked(snap.ws, repo, p):
                left.append(p)
                continue
            if (repo, p) in snap.sig:
                if (repo, p) in snap.kept:
                    full.parent.mkdir(parents=True, exist_ok=True)
                    full.write_bytes(snap.kept[(repo, p)])
                elif snap.sig[(repo, p)] != signature(full):
                    left.append(p)
                continue
            if full.is_file() and not full.is_symlink():
                (keep / p).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(full), str(keep / p))
            git(repo, "reset", "-q", "--", p)
            if git(repo, "ls-files", "--error-unmatch", "--", p).returncode == 0:
                git(repo, "checkout", "-q", "HEAD", "--", p)
            elif full.is_symlink() or full.is_file():
                full.unlink()
        except (OSError, subprocess.SubprocessError, ValueError):
            left.append(p)
    return left


def commit(snap: Snapshot, repo: Path, paths: List[str], filed: int, asked: int) -> bool:
    """One commit of the paths the call changed in a repository, through its hooks. False, with the paths put back, when the
    commit is refused. A path that was already changed before the call is never committed: it is the user's own."""
    mine = [p for p in paths if (repo, p) not in snap.sig]
    if not mine:
        return True
    git(repo, "add", "-A", "--", *mine)
    said = "Process the inbox: %d filed, %d question%s" % (filed, asked, "" if asked == 1 else "s")
    r = git(repo, "commit", "-q", "-m", said, "--", *mine)
    if r.returncode != 0:
        git(repo, "reset", "-q", "--", *mine)
        put_back(snap, repo, mine)
        return False
    return True


# ---- the inboxes' own copies ----------------------------------------------------------------------------------------

class Backup:
    """A copy of every waiting item, in the jobs folder, so that a run put back leaves each item in its inbox as it was."""

    def __init__(self, ws: Path, folders: Dict[str, Path], where: Path):
        self.root, self.copies, self.ok = where, {}, True
        total = n = 0
        for d in (where.parent, where):
            d.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(str(d), 0o700)
        for place, folder in folders.items():
            for f in sorted(p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()):
                total += f.stat().st_size
                n += 1
                if total > MOST_BACKUP_BYTES or n > MOST_BACKUP_FILES:
                    self.ok = False
                    return
        for place, folder in folders.items():
            for f in sorted(p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()):
                dst = where / place / f.relative_to(folder)
                dst.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copy2(str(f), str(dst))
                self.copies[f] = dst

    def restore(self, folders: Optional[List[Path]] = None) -> None:
        for orig, copy in self.copies.items():
            if folders is not None and not any(f in orig.parents for f in folders):
                continue
            try:
                if not orig.exists() and not orig.is_symlink():          # only what is gone: a file there now is not the call's to replace
                    orig.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(copy), str(orig))
            except OSError:
                pass

    def drop(self) -> None:
        shutil.rmtree(str(self.root), ignore_errors=True)


# ---- state ----------------------------------------------------------------------------------------------------------

def state_path(ws: Path) -> Path:
    return ws.joinpath(*STATE)


def read_state(ws: Path) -> dict:
    try:
        data = json.loads(state_path(ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(ws: Path, data: dict) -> None:
    path = state_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".status-inbox-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, str(path))


def place_bits(v: dict) -> str:
    bits = []
    if v.get("filed"):
        bits.append("filed %d" % v["filed"])
    if v.get("questions"):
        bits.append("%d question%s" % (v["questions"], "" if v["questions"] == 1 else "s"))
    if v.get("needs"):
        bits.append("%d item%s need%s you" % (v["needs"], "" if v["needs"] == 1 else "s", "s" if v["needs"] == 1 else ""))
    return " \u00b7 ".join(bits)


def result_line(places: dict) -> str:
    """The result as one sentence for each place that had something, never a figure over two: `Work: filed 4, 1 question`."""
    parts = ["%s: %s" % (place, place_bits(places[place])) for place in sorted(places) if place_bits(places[place])]
    return "; ".join(parts) if parts else "Nothing was filed."


def sentence(state: dict, only=None) -> str:
    """The result's sentence from a state, for the places in `only` alone when it is given (W4): the row shows the places it
    lists and nothing of another zone. A state with no per-place lines gives its own sentence, which names no place."""
    lines = state.get("lines")
    if not isinstance(lines, dict):
        return str(state.get("say") or "")
    keys = sorted(k for k in lines if only is None or k in only)
    out = "; ".join("%s: %s" % (k, lines[k]) for k in keys)
    tail = str(state.get("tail") or "")
    if tail:
        out = (out + ". " if out else "") + tail
    kept = [k for k in state.get("kept") or [] if only is None or k in only]
    if kept:
        out = (out + " " if out else "") + SAY_KEPT % ", ".join(kept)
    if not out and state.get("state") == "done" and only is None:
        out = "Nothing was filed."
    return out


# ---- availability, the lock, the call -------------------------------------------------------------------------------

def available(ws: Path, cap: Optional[dict] = None) -> bool:
    """Whether a background run may start: Claude is the assistant, it passes the capability check, and Ask is not at Read."""
    try:
        if channels.assistant() != "claude":
            return False
        cap = cap if cap is not None else channels.capability(ws)
        if not cap.get("ok") or channels.effective(ws, "ask", cap)["autonomy"] == "read":
            return False
        engine.agent_lib()
    except Exception:
        return False
    return True


def prompt_for(answer: Optional[dict] = None, item: str = "", zone: str = "") -> str:
    base = ("Process the inbox, unattended. Follow the intake skill's \"Running unattended\" section. Nobody can answer: write "
            "every question as a Needs you file with `intake.py ask`, and leave that item in its inbox. Send, share and delete "
            "nothing. ")
    if answer:
        return (base + "Only one item is for you: `%s` in the %s zone's Inbox. The user answered the question about it: %s. "
                "File that one item as the answer says, and nothing else. Then say exactly: Done." % (item, zone, answer["label"]))
    return base + "Then say exactly: Done."


def default_runner(cmd, tier, cwd, env):
    return engine.agent_lib().run_prepared(cmd, tier, cwd=cwd, job=JOB, timeout=TIMEOUT, env=env)


def settings_file(ws: Path, folder: Optional[Path] = None) -> Path:
    """The settings the call loads: Garrick's deny profile, and before every file write the inbox run's own guard (S3)."""
    import inbox_guard
    a = engine.agent_lib()
    try:
        base = json.loads(Path(a.PROFILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        base = {}
    out = dict(base)
    out["hooks"] = {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [
        {"type": "command", "command": inbox_guard.hook_command()}]}]}
    folder = folder or (a.jobs_dir() / "inbox-run")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / "settings.json"
    path.write_text(json.dumps(out), encoding="utf-8")
    return path


def build(ws: Path, prompt: str, zone: str = "") -> Tuple[List[str], dict]:
    a = engine.agent_lib()
    cmd = a.claude_command(TIER, prompt, list(ALLOW), a._number("GARRICK_MAX_CALL_USD", a.DEFAULT_MAX_CALL_USD), settings_file(ws))
    cmd[0] = channels.claude_path() or "claude"
    env = {"GARRICK_BACKGROUND": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "GARRICK_INBOX_WS": str(ws)}
    if zone:
        env["GARRICK_INBOX_ZONE"] = zone
    return cmd, env


def item_of(text: str) -> str:
    """The inbox item a question file is about: its `intake:` line."""
    m = re.search(r"(?m)^intake:\s*(.+?)\s*$", text)
    if not m:
        return ""
    v = m.group(1)
    try:
        return str(json.loads(v)) if v.startswith('"') else v
    except ValueError:
        return ""


def linked(ws: Path, repo: Path, rel: str) -> bool:
    """Whether the path, or a folder on the way to it from the repository, is a symbolic link."""
    cur = repo
    for part in Path(rel).parts:
        cur = cur / part
        if cur.is_symlink():
            return True
    return False


_INTAKE: Dict[str, object] = {}


def question_names_another_zone(ws: Path, zone: str, text: str) -> bool:
    """Whether a question file's words name a party, a person or a domain of a walled zone other than its own, by the Parties and
    People tables, as `intake.py ask` refuses them. True too when that cannot be told: a question that cannot be read is not kept."""
    path = ws / "System" / "skills" / "intake" / "intake.py"
    try:
        mod = _INTAKE.get(str(path))
        if mod is None:
            sys.path.insert(0, str(path.parent))
            spec = importlib.util.spec_from_file_location("garrick_inbox_run_intake_%d" % len(_INTAKE), str(path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _INTAKE[str(path)] = mod
        names = mod._foreign_names(mod.load_context(ws), zone)
    except Exception:
        return True
    low = " ".join(text.split()).casefold()
    return any(re.search(r"(?<![\w])%s(?![\w])" % re.escape(n.casefold()), low) for n in names)


def _without_item_line(ws: Path, zone: str, text: str) -> str:
    """The question's text without its `intake:` line, when that line's value is a file name in the zone's own Inbox (the item's
    name is not the question's words). Any other value is screened like the rest."""
    value = item_of(text)
    if value and "/" not in value and (ws / "Zones" / zone / "Inbox" / value).is_file():
        return re.sub(r"(?m)^intake:.*$", "", text)
    return text


def question_problems(ws: Path, moved: Dict[Path, List[str]]) -> List[str]:
    """The question files the call wrote or changed whose words reach into another walled zone."""
    bad = []
    for repo, paths in moved.items():
        for p in paths:
            parts = str((repo / p).relative_to(ws)).replace(os.sep, "/").split("/")
            if len(parts) >= 4 and parts[0] == "Zones" and parts[2] == NEEDS and (repo / p).is_file():
                try:
                    text = (repo / p).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                if question_names_another_zone(ws, parts[1], _without_item_line(ws, parts[1], text)):
                    bad.append("/".join(parts))
    return bad


def set_question(ws: Path, zone: str, name: str, reopen: bool = False, label: str = "") -> None:
    """Mark an intake question answered, or open again one whose run did not file its item."""
    f = ws / "Zones" / zone / NEEDS / name
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        return
    lines = [l for l in m.group(1).split("\n") if not re.match(r"(?:status|answer|answered):", l)]
    lines += ["status: open"] if reopen else ["status: answered", "answer: %s" % json.dumps(label, ensure_ascii=False),
                                              "answered: %s" % dt.date.today().isoformat()]
    f.write_text("---\n" + "\n".join(lines) + "\n---\n" + text[m.end():], encoding="utf-8")


def repo_of(snap: Snapshot, path: Path) -> Optional[Path]:
    """The recorded repository that holds a path, or None (the workspace's own Inbox is in none)."""
    try:
        real = path.resolve()
    except OSError:
        return None
    return next((r for r in snap.repos if r == real or r in real.parents), None)


def place_of(ws: Path, repo: Path) -> str:
    """A repository by its place, never by a file: a zone's name, Meetings, Knowledge, or Wikis when one repository holds both."""
    try:
        parts = repo.relative_to(ws).parts
    except ValueError:
        return "the workspace"
    if len(parts) == 2 and parts[0] == "Zones":
        return parts[1]
    if parts[:2] == ("Wikis", "Meetings"):
        return "Meetings"
    if parts[:2] == ("Wikis", "Knowledge"):
        return "Knowledge"
    return "Wikis" if parts == ("Wikis",) else "the workspace"


def active_zones(ws: Path, folders: Dict[str, Path], before_items: Dict[str, List[str]],
                 before_questions: Dict[str, List[str]], answered: str = "") -> set:
    """The zones this run may have changed something in (W1): a zone whose inbox lost an item, a zone that gained a question file,
    and the zone of the answered question. A change in any other zone is not the run's."""
    out = {answered} if answered else set()
    now_q = question_files(ws)
    for place, folder in folders.items():
        if place in ("Meetings", "Inbox"):
            continue
        if set(before_items.get(place, [])) - set(waiting(folder)) or set(now_q.get(place, [])) - set(before_questions.get(place, [])):
            out.add(place)
    return out


def kept_repos(ws: Path, snap: Snapshot, moved: Dict[Path, List[str]], active: set) -> Dict[Path, str]:
    """The repositories to leave exactly as they are (S2, W1): one whose HEAD moved, one with a changed path that `allowed()` does
    not name or a link on the way to, and one with a changed path in a zone the run had no item in. In such a repository the call's
    own changes cannot be told from another writer's, so nothing is committed there and nothing is put back."""
    keep = {}
    for repo, paths in moved.items():
        if not paths:
            continue
        reason = ""
        if git(repo, "rev-parse", "HEAD").stdout.strip() != snap.head[repo]:
            reason = "head"
        for p in paths:
            rel = str((repo / p).relative_to(ws)).replace(os.sep, "/")
            if not allowed(rel) or linked(ws, repo, p):
                reason = reason or "outside"
            elif rel.startswith("Zones/") and rel.split("/")[1] not in active:
                reason = reason or "zone"
        if reason:
            keep[repo] = reason
    return keep


def clear_stale(folder: Path, mine: str) -> None:
    """Take away the backup folders an earlier run left (a crash, a kill): the run holds the lock, so no other is going (S5)."""
    try:
        for e in folder.iterdir():
            if e.name.isdigit() and e.name != mine and e.is_dir() and not e.is_symlink():
                shutil.rmtree(str(e), ignore_errors=True)
    except OSError:
        pass


def run(ws: Path, answer: Optional[dict] = None, runner: Optional[Callable] = None, cap: Optional[dict] = None,
        jobs: Optional[Path] = None) -> dict:
    """One inbox run, whole: record, call, check, commit. Returns the state it wrote. `answer` is {"zone", "file", "label"} for
    the one item an answered question names. The call may be stubbed with `runner(cmd, tier, cwd, env) -> (code, got)`."""
    ws = Path(ws).resolve()
    started = dt.datetime.now().isoformat(timespec="seconds")
    folders = inboxes(ws)
    keep = (jobs or engine.agent_lib().jobs_dir()) / "inbox-run" / str(os.getpid())
    clear_stale(keep.parent, keep.name)
    state = {"state": "running", "at": started, "places": {}, "say": "Processing the inbox.", "answer": bool(answer)}
    write_state(ws, state)

    def finish(**more) -> dict:
        out = dict(state, **more)
        write_state(ws, out)
        return out

    if not available(ws, cap):
        return finish(state="failed", say=SAY_UNAVAILABLE, unavailable=True)
    before_items = {p: waiting(f) for p, f in folders.items()}
    before_questions = question_files(ws)
    item = zone = ""
    if answer:
        zone = answer["zone"]
        try:
            item = item_of((ws / "Zones" / zone / NEEDS / answer["file"]).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            item = ""
        if not item or "/" in item or item not in before_items.get(zone, []):
            return finish(state="failed", say="The item that question was about is not in the inbox any more.")
    snap = Snapshot(ws)
    system_before = system_hash(ws)
    backup = Backup(ws, folders, keep)
    if not snap.ok or not backup.ok:
        backup.drop()
        return finish(state="failed", say="There is too much waiting to process in the background, so this goes to a visible assistant.",
                      unavailable=True)
    if answer:
        set_question(ws, zone, answer["file"], label=answer["label"])
    cmd, env = build(ws, prompt_for(answer, item, zone), zone)
    try:
        code, got = (runner or default_runner)(cmd, TIER, ws, env)
    except Exception:
        code, got = 1, {}
    moved = snap.moved()
    changed_system = system_hash(ws) != system_before
    active = active_zones(ws, folders, before_items, before_questions, zone if answer else "")
    keep = kept_repos(ws, snap, moved, active)
    bad = {r for r in moved if r not in keep and any(
        True for _ in question_problems(ws, {r: moved[r]}))}
    failed = bool(got.get("refused") or code != 0)

    def undo(repos, root_inbox: bool = False) -> None:
        for repo, paths in moved.items():
            if repo in repos:
                put_back(snap, repo, paths)
        backup.restore([f for f in folders.values() if repo_of(snap, f) in repos or (root_inbox and repo_of(snap, f) is None)])

    if failed or changed_system:
        undo({r for r in snap.repos if r not in keep}, root_inbox=True)
        backup.drop()
        if answer:
            set_question(ws, zone, answer["file"], reopen=True)
        base = SAY_SYSTEM if changed_system else SAY_FAILED
        kept_places = sorted({place_of(ws, r) for r in keep})
        out = {"state": "failed", "lines": {}, "tail": base, "kept": kept_places}
        return finish(state="failed", say=sentence(out), refused=bool(changed_system or keep), system=changed_system,
                      lines={}, tail=base, kept=kept_places)
    undo(bad)
    refused = []
    for repo, paths in moved.items():
        if not paths or repo in keep or repo in bad:
            continue
        rel = lambda p: str((repo / p).relative_to(ws)).replace(os.sep, "/")  # noqa: E731
        zones = {rel(p).split("/")[1] for p in paths if rel(p).startswith("Zones/")}
        wiki = any(rel(p).startswith("Wikis/") for p in paths)
        gone = [place for place, f in folders.items() if place in zones or (wiki and place == "Meetings")]
        filed = sum(len(set(before_items[g]) - set(waiting(folders[g]))) for g in gone)
        asked = sum(len(set(question_files(ws).get(z, [])) - set(before_questions.get(z, []))) for z in zones)
        if not commit(snap, repo, paths, filed, asked):
            refused.append(repo)
            backup.restore([folders[g] for g in gone])
    after_items = {p: waiting(f) for p, f in folders.items()}
    now_q = question_files(ws)
    places = {}
    for place in folders:
        places[place] = {"filed": len(set(before_items[place]) - set(after_items[place])),
                         "questions": len(set(now_q.get(place, [])) - set(before_questions.get(place, []))),
                         "needs": len(after_items[place]) if place in ("Meetings", "Inbox") else 0}
    if answer and item in after_items.get(zone, []):
        set_question(ws, zone, answer["file"], reopen=True)
    backup.drop()
    places = {p: v for p, v in places.items() if v["filed"] or v["questions"] or v["needs"]}
    lines = {p: place_bits(v) for p, v in places.items() if place_bits(v)}
    tails = []
    if refused:
        tails.append("A commit was refused, so those items stay in the inbox")
    if bad:
        tails.append(SAY_REFUSED if not (lines or refused or keep) else "A question named another zone, so that part was not kept")
    kept_places = sorted({place_of(ws, r) for r in keep})
    out = {"state": "done", "lines": lines, "tail": ". ".join(tails), "kept": kept_places}
    return finish(state="done" if not (refused or keep or bad) else "failed", say=sentence(out), places=places, lines=lines,
                  tail=out["tail"], kept=kept_places, refused=bool(keep or bad) or None)


# ---- starting a run from the page -----------------------------------------------------------------------------------

def lock_path() -> Path:
    return engine.agent_lib().jobs_dir() / LOCK


def start(ws: Path, answer: Optional[dict] = None, spawn: Optional[Callable] = None) -> dict:
    """The page's verb: take the lock, or say a run is going; check that a background run is possible; start the run, detached,
    holding the lock. The reply is one sentence. `spawn(args, fd)` is a test's stand-in for the child process."""
    import fcntl
    ws = Path(ws).resolve()
    if not available(ws):
        return {"say": SAY_UNAVAILABLE, "unavailable": True}
    folder = lock_path().parent
    folder.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path()), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return {"say": SAY_BUSY, "state": "running", "busy": True}
    args = [sys.executable, str(HERE / "inbox_run.py"), "run", "--workspace", str(ws), "--lock-fd", str(fd)]
    if answer:
        # one value in the `=` form, so a label that starts with `-` is read as the label (C6)
        args += ["--answer-json=" + json.dumps([answer["zone"], answer["file"], answer["label"]])]
    try:
        write_state(ws, {"state": "running", "at": dt.datetime.now().isoformat(timespec="seconds"), "places": {},
                         "say": "Processing the inbox.", "answer": bool(answer)})
        if spawn is not None:
            spawn(args, fd)
        else:
            subprocess.Popen(args, cwd=str(ws), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, pass_fds=(fd,))
    finally:
        os.close(fd)            # the child holds its own copy of the open lock
    return {"say": "Processing the inbox in the background.", "state": "running"}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Process the inbox in the background.")
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--workspace", required=True)
    r.add_argument("--answer", nargs=3, metavar=("ZONE", "FILE", "LABEL"))
    r.add_argument("--answer-json", default=None)
    r.add_argument("--lock-fd", type=int, default=-1)
    args = ap.parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve()
    given = args.answer
    if args.answer_json:
        try:
            given = json.loads(args.answer_json)
        except ValueError:
            given = None
    if args.answer_json and not (isinstance(given, list) and len(given) == 3):
        write_state(ws, {"state": "failed", "at": dt.datetime.now().isoformat(timespec="seconds"), "places": {}, "say": SAY_FAILED})
        return 1
    answer = dict(zip(("zone", "file", "label"), map(str, given))) if given and len(given) == 3 else None
    try:
        out = run(ws, answer)
    except Exception:
        write_state(ws, {"state": "failed", "at": dt.datetime.now().isoformat(timespec="seconds"), "places": {}, "say": SAY_FAILED})
        return 1
    finally:
        if args.lock_fd >= 0:
            try:
                os.close(args.lock_fd)
            except OSError:
                pass
    return 0 if out.get("state") == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
