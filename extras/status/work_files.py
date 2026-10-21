#!/usr/bin/env python3
"""work_files.py: where a piece of work's files live (#189).

A piece of work started from a folder of the user's (#182, your_work.py)
leaves its files where they are, and Garrick only reads them. Its page offers
two more choices, each behind a plain preview, and never during setup:

- **Keep a copy.** Garrick keeps a copy of the work's files and refreshes it
  one way from the user's folder, which stays the original. Nobody edits the
  copy; it is there for its history.
- **Move into Garrick.** The files are copied in, every one checked against
  its original, and only then removed from the folder. Undo the move puts
  every file back, beside any file of the same name rather than over it.

Both keep the files in one place, the project's own `Files/` folder, with a
small git history of its own (history_*). The zone ignores that folder (the
project's `.gitignore`), so a large Office file never grows the zone's
repository, an unchanged file takes no extra space, and deleting the copy
deletes all of it. Its `.git` carries HISTORY_MARK, so the workspace's checks
treat it as Garrick's and never as a repository of someone else's to guard.

What a piece of work's hub says, in its frontmatter, and committed with it:

    storage: copy | moved      absent while the files are left in place
    media: in                  recordings and video come into the copy too
    moved: <date>              the day the files moved into Garrick

and what this Mac keeps of it, never committed: System/generated/work-files.json,
{"<Zone>/<note>": {"refreshed", "changed", "renamed"}}, and, while a copy or
a move runs, its progress and Stop (Job).

Nothing here writes into the user's folder, except Undo, which puts the files
back there. A copy and a refresh only read it; a move removes from it only
what it copied and checked, after every file was checked.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

FILES = "Files"                    # the project's folder for its copy or its moved files
STORAGE = "storage"                # the hub's key: COPY or MOVED; absent, left in place
COPY, MOVED, LEFT = "copy", "moved", "left"
MEDIA_KEY = "media"                # the hub's key: "in" when recordings and video come into the copy
MEDIA_IN = "in"
MOVED_ON = "moved"                 # the hub's key: the day the files moved in
HISTORY_MARK = "garrick-history"   # in the history's .git: Garrick's own, not a repository to guard
IGNORE_LINE = "/%s/" % FILES       # the project's .gitignore: the zone never takes the folder in
STATE = ("System", "generated", "work-files.json")
JOBS = ("System", "generated", "work-files")
VERSIONS = ("System", "generated", "versions")
FROM_GARRICK = "from Garrick"      # what Undo calls a file it puts back beside one of the same name
# Recordings and video: what stays out of a copy until the media switch brings it in.
MEDIA = frozenset(("mp3", "m4a", "wav", "aac", "aif", "aiff", "flac", "ogg", "oga", "opus", "wma", "caf", "amr",
                   "mp4", "mov", "m4v", "avi", "mkv", "wmv", "webm", "mpg", "mpeg", "3gp", "mts", "m2ts"))
# Files a Mac, an Office app or a sync makes on its own: never part of the work.
JUNK = frozenset((".ds_store", "thumbs.db", "desktop.ini", "icon\r"))
WHO = {"GIT_AUTHOR_NAME": "Garrick", "GIT_AUTHOR_EMAIL": "garrick@localhost",
       "GIT_COMMITTER_NAME": "Garrick", "GIT_COMMITTER_EMAIL": "garrick@localhost"}
GIT_TIMEOUT = 600
CHUNK = 1 << 20
FILES_MAX = 20000                  # files of one piece of work, at most


class Refused(Exception):
    """Why a copy, a move or an undo did not happen, in words for the page."""


class Stopped(Exception):
    """Stop was pressed while files were still being copied and checked."""


# --------------------------------------------------------------------------- the work's files

def junk(name: str) -> bool:
    low = name.casefold()
    return name.startswith((".", "~$")) or name.endswith("~") or low in JUNK


def is_media(rel: str) -> bool:
    return rel.rsplit(".", 1)[-1].casefold() in MEDIA if "." in os.path.basename(rel) else False


def listing(folder: Path, members: Optional[Iterable[str]] = None, limit: int = FILES_MAX) -> Dict[str, os.stat_result]:
    """The work's files under `folder`, by path from it: each regular file,
    never a link, a hidden one or one a Mac or an Office app makes on its own.
    With `members`, only those of them (a piece of work discover.py found by
    a word its files' names share). It only reads names and dates."""
    folder = Path(folder)
    out: Dict[str, os.stat_result] = {}
    if members is not None:
        for rel in sorted(set(members)):
            if not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in rel.split("/"):
                continue
            try:
                st = os.lstat(str(folder / rel))
            except OSError:
                continue
            if _regular(st) and not junk(os.path.basename(rel)):
                out[rel] = st
        return out
    for dirpath, dirnames, filenames in os.walk(str(folder)):
        dirnames[:] = sorted(d for d in dirnames if not junk(d) and d != ".git")
        for name in sorted(filenames):
            if junk(name):
                continue
            p = os.path.join(dirpath, name)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if _regular(st):
                out[os.path.relpath(p, str(folder)).replace(os.sep, "/")] = st
                if len(out) >= limit:
                    return out
    return out


def _regular(st: os.stat_result) -> bool:
    import stat as S
    return S.S_ISREG(st.st_mode)


def sizes(files: Dict[str, os.stat_result]) -> dict:
    """What a preview says of them: how many, how big, and how many and how big are recordings and video."""
    media = {r: s for r, s in files.items() if is_media(r)}
    return {"files": len(files), "bytes": sum(s.st_size for s in files.values()),
            "media": len(media), "media_bytes": sum(s.st_size for s in media.values())}


def said_size(n: int) -> str:
    """A size as the page says it: 430 KB, 2.1 MB, 38 MB, 1.2 GB."""
    n = max(0, int(n))
    if n < 1000 * 1000:
        return "%d KB" % max(1, round(n / 1000)) if n else "0 KB"
    if n < 10 * 1000 * 1000:
        return "%.1f MB" % (n / 1e6)
    if n < 1000 * 1000 * 1000:
        return "%d MB" % round(n / 1e6)
    return "%.1f GB" % (n / 1e9)


def said_files(n: int) -> str:
    return "%d file%s" % (n, "" if n == 1 else "s")


def disk_size(folder: Path) -> int:
    """Every byte under `folder`, its history included."""
    total = 0
    for dirpath, _, filenames in os.walk(str(folder)):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


# --------------------------------------------------------------------------- the hub's record

def mode(fm: dict) -> str:
    """LEFT, COPY or MOVED, from the hub's frontmatter."""
    v = str(fm.get(STORAGE) or "").strip().strip("\"'").casefold()
    return v if v in (COPY, MOVED) else LEFT


def media_in(fm: dict) -> bool:
    return str(fm.get(MEDIA_KEY) or "").strip().strip("\"'").casefold() == MEDIA_IN


def files_dir(project: Path) -> Path:
    return Path(project) / FILES


def has_copy(project: Path) -> bool:
    return (files_dir(project) / ".git" / HISTORY_MARK).is_file()


def ignore_text(current: Optional[str]) -> Optional[str]:
    """The project's .gitignore with IGNORE_LINE in it, or None when it has it already."""
    lines = (current or "").splitlines()
    if IGNORE_LINE in (l.strip() for l in lines):
        return None
    return "\n".join(lines + ["# Garrick's copy of this work's files, with its own history (#189)", IGNORE_LINE]).lstrip("\n") + "\n"


# --------------------------------------------------------------------------- the copy's own history

def git(folder: Path, *args, binary: bool = False, timeout: float = GIT_TIMEOUT) -> Tuple[int, object]:
    """git in the history's folder, with Garrick as the author, and the
    workspace's own hooks and settings out of it: it is not a zone."""
    env = dict(os.environ, **WHO)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    env.pop("GIT_INDEX_FILE", None)
    try:
        r = subprocess.run(["git", "-c", "core.quotepath=off", "-c", "commit.gpgsign=false", "-C", str(folder)] + list(args),
                           capture_output=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL, text=not binary)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, (b"" if binary else str(e))
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr if not binary else r.stderr))


def history_start(folder: Path) -> None:
    """The copy's folder and its history, made once. Marked as Garrick's
    (HISTORY_MARK), and kept clear of what a Mac writes on its own."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    gitdir = folder / ".git"
    if not gitdir.is_dir():
        code, said = git(folder, "-c", "init.defaultBranch=main", "init", "-q")
        if code != 0:
            raise Refused("Garrick could not start the history of its copy: %s" % str(said).strip())
        for k, v in (("gc.auto", "256"), ("core.autocrlf", "false"), ("core.fileMode", "false")):
            git(folder, "config", k, v)
        (gitdir / "info").mkdir(exist_ok=True)
        (gitdir / "info" / "exclude").write_text(".DS_Store\n._*\n~$*\n*~\n", encoding="utf-8")
    mark = gitdir / HISTORY_MARK
    if not mark.is_file():
        mark.write_text("This history is Garrick's copy of a piece of work's files (#189). Garrick commits to it; "
                        "nobody else does.\n", encoding="utf-8")


def history_keep(folder: Path, message: str) -> bool:
    """A version of everything in the folder now, when anything changed
    since the last one: True when one was kept."""
    code, said = git(folder, "add", "-A")
    if code != 0:
        raise Refused("Garrick could not keep a version of its copy: %s" % str(said).strip().splitlines()[-1:])
    code, _ = git(folder, "diff", "--cached", "--quiet")
    if code == 0:
        return False
    code, said = git(folder, "commit", "-q", "-m", message[:200])
    if code != 0:
        lines = str(said).strip().splitlines()
        raise Refused("Garrick could not keep a version of its copy: %s" % (lines[-1] if lines else "git refused"))
    return True


def history_back(folder: Path) -> None:
    """The copy's folder as its last version had it, everything since gone:
    what Stop leaves of a copy that was there before."""
    if (Path(folder) / ".git").is_dir() and git(folder, "rev-parse", "-q", "--verify", "HEAD")[0] == 0:
        git(folder, "reset", "-q", "--hard", "HEAD")
        git(folder, "clean", "-q", "-f", "-d")
    else:
        for p in Path(folder).iterdir() if Path(folder).is_dir() else []:
            if p.name != ".git":
                shutil.rmtree(str(p)) if p.is_dir() and not p.is_symlink() else p.unlink()


def history_drop_last(folder: Path) -> None:
    """The last version taken back, the files as the one before had them:
    a move whose record was refused leaves the copy as it was."""
    if git(folder, "rev-parse", "-q", "--verify", "HEAD~1")[0] == 0:
        git(folder, "reset", "-q", "--hard", "HEAD~1")
        git(folder, "clean", "-q", "-f", "-d")


def history_count(folder: Path) -> int:
    code, said = git(folder, "rev-list", "--count", "HEAD")
    try:
        return int(str(said).strip()) if code == 0 else 0
    except ValueError:
        return 0


def history_first(folder: Path) -> Optional[dt.datetime]:
    code, said = git(folder, "log", "--reverse", "--format=%ct", "-n", "1000000")
    lines = str(said).split() if code == 0 else []
    return dt.datetime.fromtimestamp(int(lines[0])) if lines else None


def history_of(folder: Path) -> Dict[str, List[Tuple[str, int]]]:
    """Every file's versions in the copy, newest first: {path: [(commit, time)]}.
    A version is a commit that added or changed the file; its removal is none."""
    code, said = git(folder, "log", "-z", "--no-renames", "--name-status", "--format=%x01%H %ct")
    out: Dict[str, List[Tuple[str, int]]] = {}
    if code != 0:
        return out
    head, status = None, None
    for tok in str(said).split("\0"):
        tok = tok.lstrip("\n")
        if tok.startswith("\x01"):
            h, _, t = tok[1:].partition(" ")
            head, status = (h, int(t or 0)), None
        elif head is None or not tok:
            continue
        elif status is None:
            status = tok
        else:
            if status[:1] in ("A", "M", "T"):
                out.setdefault(tok, []).append(head)
            status = None
    return out


def history_blob(folder: Path, commit: str, rel: str) -> bytes:
    """One file as one version of the copy had it."""
    if not (len(commit) in (40, 64) and all(c in "0123456789abcdef" for c in commit)):
        raise Refused("not a version Garrick kept")
    code, data = git(folder, "cat-file", "blob", "%s:%s" % (commit, rel), binary=True)
    if code != 0:
        raise Refused("Garrick's copy has no such version of %s" % os.path.basename(rel))
    return data


# --------------------------------------------------------------------------- copying, checked

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_checked(src: Path, dst: Path, tick: Optional[Callable[[int], None]] = None) -> str:
    """`src` copied to `dst`, by way of a file beside it renamed into place,
    with its dates; the copy read back and checked against what was read.
    `src` is only ever opened to read. Returns the checksum."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".garrick-", dir=str(dst.parent))
    h = hashlib.sha256()
    try:
        with open(str(src), "rb") as f, os.fdopen(fd, "wb") as out:
            for chunk in iter(lambda: f.read(CHUNK), b""):
                h.update(chunk)
                out.write(chunk)
                if tick:
                    tick(len(chunk))
        st = os.stat(str(src))
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        if digest(Path(tmp)) != h.hexdigest() or os.path.getsize(tmp) != st.st_size:
            raise Refused("the copy of %s did not match it" % src.name)
        os.replace(tmp, str(dst))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return h.hexdigest()


def same(a: os.stat_result, b: os.stat_result) -> bool:
    return a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns


def tidy(folder: Path, keep: Iterable[str]) -> List[str]:
    """Everything in the copy's folder that is no longer in `keep` removed,
    and the folders it leaves empty; its history keeps them. Returns what went."""
    keep = set(keep)
    gone = []
    for rel in sorted(listing(folder)):
        if rel not in keep:
            (Path(folder) / rel).unlink()
            gone.append(rel)
    for dirpath, dirnames, filenames in sorted(os.walk(str(folder)), key=lambda t: -len(t[0])):
        if ".git" in Path(dirpath).relative_to(folder).parts or Path(dirpath) == Path(folder):
            continue
        if not os.listdir(dirpath):
            os.rmdir(dirpath)
    return gone


# --------------------------------------------------------------------------- progress, and Stop

def key_hash(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


class Job:
    """A copy, a move or an undo as it runs, for the page to show and for Stop:
    System/generated/work-files/<work>.json says which phase it is in and how
    far along, and <work>.stop, made by Stop, asks it to stop while it still
    may. Phases: "copying" and "checking", which Stop may end, then "removing"
    or "putting back", which it may not, then "done"."""

    STOPPABLE = ("copying", "checking")

    def __init__(self, ws: Path, key: str, kind: str):
        self.base = Path(ws).joinpath(*JOBS)
        self.base.mkdir(parents=True, exist_ok=True)
        h = key_hash(key)
        self.path, self.flag = self.base / (h + ".json"), self.base / (h + ".stop")
        self.data = {"key": key, "kind": kind, "phase": "", "done": 0, "of": 0, "bytes": 0, "bytes_of": 0,
                     "pid": os.getpid(), "at": time.time()}
        self._last = 0.0
        if self.flag.exists():
            self.flag.unlink()

    def write(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last < 0.25:
            return
        self._last = now
        self.data["at"] = now
        fd, tmp = tempfile.mkstemp(prefix=".job-", dir=str(self.base))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.data))
        os.replace(tmp, str(self.path))

    def phase(self, name: str, of: int = 0, bytes_of: int = 0) -> None:
        self.data.update(phase=name, done=0, of=of, bytes=0, bytes_of=bytes_of)
        self.write(force=True)

    def step(self, n: int = 1) -> None:
        self.data["done"] += n
        self.write()

    def took(self, n: int) -> None:
        self.data["bytes"] += n
        self.write()

    def check(self) -> None:
        """Stopped, while Stop may still stop it."""
        if self.data["phase"] in self.STOPPABLE and self.flag.exists():
            raise Stopped()

    def past_stop(self, name: str, of: int = 0) -> None:
        """The phase from which Stop no longer stops it, said before the flag
        is looked at a last time: Stop makes the flag before it reads the phase,
        so one of the two always sees the other."""
        self.phase(name, of)
        if self.flag.exists():
            self.data["phase"] = "stopped"
            self.write(force=True)
            raise Stopped()

    def end(self) -> None:
        for p in (self.path, self.flag):
            try:
                p.unlink()
            except FileNotFoundError:
                pass


def progress(ws: Path, key: str) -> Optional[dict]:
    """The job running on a piece of work, or None. One whose process is gone is none."""
    path = Path(ws).joinpath(*JOBS) / (key_hash(key) + ".json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        os.kill(int(data.get("pid") or 0), 0)
    except (OSError, ValueError, OverflowError):
        return None
    return data


def ask_stop(ws: Path, key: str, wait: float = 3.0) -> str:
    """Stop, for the page: "stopping", "late" when files already leave, or "none"."""
    base = Path(ws).joinpath(*JOBS)
    flag = base / (key_hash(key) + ".stop")
    if progress(ws, key) is None:
        return "none"
    base.mkdir(parents=True, exist_ok=True)
    flag.write_text("stop\n", encoding="utf-8")
    deadline = time.time() + wait
    while True:
        p = progress(ws, key)
        phase = (p or {}).get("phase")
        if p is None or phase in Job.STOPPABLE or phase == "stopped":
            return "stopping"
        if phase not in ("", None) or time.time() >= deadline:
            try:
                flag.unlink()
            except FileNotFoundError:
                pass
            return "late"
        time.sleep(0.05)


# --------------------------------------------------------------------------- keep a copy

def refresh(source: Path, members: Optional[List[str]], folder: Path, media: bool, job: Optional[Job] = None,
            message: str = "Refreshed from the folder") -> dict:
    """Garrick's copy brought up to the user's folder, one way: a file new or
    changed there copied in and checked, one gone from there gone from the
    copy (its history keeps it), and recordings and video left out unless
    `media`. Then a version, when anything changed. The folder is only read.
    {"changed": [...], "added": [...], "removed": [...], "kept": bool}"""
    source, folder = Path(source), Path(folder)
    if not source.is_dir():
        raise Refused("the folder %s is not there" % source.name)
    history_start(folder)
    want = {r: s for r, s in listing(source, members).items() if media or not is_media(r)}
    have = listing(folder)
    todo = [r for r in sorted(want) if not (r in have and same(have[r], want[r]))]
    if job:
        job.phase("copying", len(todo), sum(want[r].st_size for r in todo))
    added, changed = [], []
    for rel in todo:
        if job:
            job.check()
        copy_checked(source / rel, folder / rel, job.took if job else None)
        (changed if rel in have else added).append(rel)
        if job:
            job.step()
    if job:
        job.phase("checking", len(want))
        job.check()
        job.past_stop("keeping")
    removed = tidy(folder, want)
    kept = history_keep(folder, message)
    return {"changed": changed, "added": added, "removed": removed, "kept": kept}


# --------------------------------------------------------------------------- move into Garrick

def move_in(source: Path, members: Optional[List[str]], folder: Path, job: Optional[Job] = None) -> Dict[str, os.stat_result]:
    """Every file of the work copied into Garrick, recordings and video
    included, then every one checked against its original, and a version
    kept. Nothing leaves the folder here: remove_moved() does that, once the
    record says moved. Stop may end it until every file is checked (Job).
    Returns the files as they stood when checked."""
    source, folder = Path(source), Path(folder)
    if not source.is_dir():
        raise Refused("the folder %s is not there" % source.name)
    history_start(folder)
    files = listing(source, members)
    if not files:
        raise Refused("there are no files in %s to move" % source.name)
    have = listing(folder)
    if job:
        job.phase("copying", len(files), sum(s.st_size for s in files.values()))
    sums = {}
    for rel in sorted(files):
        if job:
            job.check()
        if rel in have and same(have[rel], files[rel]):
            sums[rel] = None
        else:
            sums[rel] = copy_checked(source / rel, folder / rel, job.took if job else None)
        if job:
            job.step()
    if job:
        job.phase("checking", len(files))
    for rel in sorted(files):
        if job:
            job.check()
        theirs, ours = digest(source / rel), digest(folder / rel)
        if theirs != ours or (sums[rel] is not None and sums[rel] != ours):
            raise Refused("the copy of %s did not match its original, so nothing left the folder" % os.path.basename(rel))
        now = os.lstat(str(source / rel))
        if not same(now, files[rel]):
            raise Refused("%s changed in the folder while it was being moved, so nothing left the folder. "
                          "Try again when nobody is working on it" % os.path.basename(rel))
        if job:
            job.step()
    if job:
        job.past_stop("removing", len(files))
    tidy(folder, files)
    history_keep(folder, "Moved into Garrick from the folder")
    return files


def remove_moved(source: Path, files: Dict[str, os.stat_result], job: Optional[Job] = None) -> List[str]:
    """The files a move copied and checked, removed from the user's folder,
    each only if it is still as it was checked; the folders stay, the emptied
    one included, so Undo has somewhere to put them back. Returns the files
    that stayed, because they changed meanwhile or could not be removed."""
    stayed = []
    for rel in sorted(files):
        p = Path(source) / rel
        try:
            if same(os.lstat(str(p)), files[rel]):
                p.unlink()
            else:
                stayed.append(rel)
        except FileNotFoundError:
            pass
        except OSError:
            stayed.append(rel)
        if job:
            job.step()
    return stayed


def beside(path: Path) -> Path:
    """Where Undo puts a file back when the folder has one of that name: "<name> (from Garrick)"."""
    stem, ext = os.path.splitext(path.name)
    for n in range(1, 1000):
        cand = path.with_name("%s (%s%s)%s" % (stem, FROM_GARRICK, "" if n == 1 else " %d" % n, ext))
        if not os.path.lexists(str(cand)):
            return cand
    raise Refused("too many copies of %s are in the folder already" % path.name)


def put_back(folder: Path, dest: Path, job: Optional[Job] = None) -> List[Tuple[str, str]]:
    """Undo the move: every file in Garrick copied back into the user's folder
    and checked there, never over a file: one whose name is taken goes back
    beside it as "<name> (from Garrick)". Garrick's own stay, as an old copy.
    Returns the files it renamed, (as it was, as it went back)."""
    folder, dest = Path(folder), Path(dest)
    if not dest.is_dir():
        if not dest.parent.is_dir():
            raise Refused("the folder %s is not there any more, nor the one it was in, so Garrick kept the files"
                          % dest.name)
        dest.mkdir()
    files = listing(folder)
    if job:
        job.phase("putting back", len(files), sum(s.st_size for s in files.values()))
    renamed = []
    for rel in sorted(files):
        target = dest / rel
        if os.path.lexists(str(target)):
            try:
                back = os.path.isfile(str(target)) and not os.path.islink(str(target)) and digest(target) == digest(folder / rel)
            except OSError:
                back = False
            if back:                            # put back already, by an Undo that stopped part way
                if job:
                    job.step()
                continue
            target = beside(target)
            renamed.append((rel, target.relative_to(dest).as_posix()))
        copy_checked(folder / rel, target, job.took if job else None)
        if job:
            job.step()
    return renamed


# --------------------------------------------------------------------------- versions, for the page

def version_name(rel: str, when: dt.datetime, today: dt.date) -> str:
    """A version saved as a file of its own: "Lounge launch brief, 3 days ago.docx"."""
    stem, ext = os.path.splitext(os.path.basename(rel))
    return "%s, %s%s" % (stem, ago(when.date(), today), ext)


def ago(day: dt.date, today: dt.date) -> str:
    n = (today - day).days
    if n <= 0:
        return "today"
    if n == 1:
        return "yesterday"
    if n < 14:
        return "%d days ago" % n
    if n < 60:
        return "%d weeks ago" % (n // 7)
    return "%d months ago" % (n // 30)


def when_said(t: dt.datetime, today: dt.date) -> str:
    """A version's time as its list says it: Today, 09:14; 3 days ago, 17:40."""
    word = ago(t.date(), today)
    return "%s, %s" % (word[:1].upper() + word[1:], t.strftime("%H:%M"))


# --------------------------------------------------------------------------- what this Mac keeps

def state(ws: Path) -> dict:
    try:
        data = json.loads(Path(ws).joinpath(*STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def keep_state(ws: Path, key: str, **values) -> None:
    path = Path(ws).joinpath(*STATE)
    data = state(ws)
    entry = data.get(key) if isinstance(data.get(key), dict) else {}
    entry.update(values)
    data[key] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".work-files-", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, str(path))


def changed_said(done: dict) -> str:
    """What a refresh found, in one sentence."""
    n = len(done["changed"]) + len(done["added"]) + len(done["removed"])
    if not n:
        return "Nothing had changed since the last refresh."
    names = [os.path.splitext(os.path.basename(r))[0] for r in done["changed"] + done["added"] + done["removed"]]
    shown = ", ".join(names[:3]) + (" and %d more" % (len(names) - 3) if len(names) > 3 else "")
    return "%s had changed in your folder: %s. Garrick kept the version from before." % (said_files(n).capitalize(), shown) \
        if done["changed"] else "%s had changed in your folder: %s." % (said_files(n).capitalize(), shown)
