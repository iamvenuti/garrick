#!/usr/bin/env python3
"""The lock a running wrap holds, so the band can show it and a second wrap cannot start.

    python3 System/tools/wrap_lock.py start Zones/Work/Acme/Threads/Pricing/Pricing.md
    python3 System/tools/wrap_lock.py end   Zones/Work/Acme/Threads/Pricing/Pricing.md
    python3 System/tools/wrap_lock.py status Zones/Work/Acme/Threads/Pricing/Pricing.md

The wrap in the threads skill runs `start` before its steps and `end` after
them, whatever happened in between. The lock is one small file in
System/generated/, `wrap-<the note's path, with / as __>.lock`, holding the
note's path and the time it was taken. A lock older than ten minutes counts as
gone: a wrap that died leaves one behind, and it must not block the thread for
good. The Garrick band reads the same file by the same name and the same
ten minutes; it asks no model.

`end` also writes the time the wrap finished, beside the lock:
`wrap-<the note's path, with / as __>.done`, holding the note's path and that
time. The band compares it with the start of the session's last turn, and
Close reads the same record, so a note written by any other route is never
taken for a wrap that ran. `end --abandon` removes the lock and writes none:
for a wrap that never began.

`start` prints `locked` and exits 0, or says that a wrap of this note is
already running and exits 1. `end` removes the lock, writes the record, and
exits 0 when there is no lock. `status` prints `running` or `idle`. Standard
library only.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import fcntl
except ImportError:             # not on Windows
    fcntl = None

sys.dont_write_bytecode = True

MAX_AGE = 600        # seconds: a lock older than this counts as gone
FOLDER = ("System", "generated")


def root_of(given: Optional[str]) -> Path:
    """The workspace: the one given, else the one this script sits in."""
    return Path(given).resolve() if given else Path(__file__).resolve().parents[2]


def lock_name(note: str) -> str:
    """The lock's file name for a note given by its path from the workspace root."""
    return "wrap-%s.lock" % note.strip("/").replace("/", "__")


def done_name(note: str) -> str:
    """The name of the record a finished wrap leaves, beside the lock."""
    return "wrap-%s.done" % note.strip("/").replace("/", "__")


def done_path(root: Path, note: str) -> Path:
    return lock_path(root, note).with_name(done_name(note))


def lock_path(root: Path, note: str) -> Path:
    clean = note.strip("/")
    parts = Path(clean).parts
    if not clean.endswith(".md") or ".." in parts or not parts or parts[0] != "Zones":
        raise ValueError("%s is not a thread note under Zones/" % note)
    return root.joinpath(*FOLDER) / lock_name(clean)


def started(path: Path) -> Optional[float]:
    """When the lock was taken, as seconds since the epoch; None when it does
    not read. The file's own modification time stands in for a file that holds
    no time, so a hand-made lock still expires."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stamp = datetime.datetime.strptime(data["started"], "%Y-%m-%dT%H:%M:%SZ")
        return stamp.replace(tzinfo=datetime.timezone.utc).timestamp()
    except (OSError, ValueError, KeyError, TypeError):
        try:
            return path.stat().st_mtime
        except OSError:
            return None


def running(path: Path, now: Optional[float] = None) -> bool:
    """A lock that is there and younger than ten minutes."""
    taken = started(path)
    if taken is None:
        return False
    return abs((time.time() if now is None else now) - taken) < MAX_AGE     # one dated far ahead counts as gone, as in the band


def start(root: Path, note: str, now: Optional[float] = None) -> bool:
    """Take the lock. False when a wrap of this note is already running."""
    path = lock_path(root, note)
    path.parent.mkdir(parents=True, exist_ok=True)
    with serial(path.parent):
        return take(path, note, now)


@contextlib.contextmanager
def serial(folder: Path):
    """One start at a time on this machine, so that two starters which both see
    a dead lock cannot each clear it and each take it."""
    if fcntl is None:
        yield
        return
    fd = os.open(str(folder / ".wrap-start.lock"), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def take(path: Path, note: str, now: Optional[float]) -> bool:
    if path.exists():
        if running(path, now):
            return False
        path.unlink()                       # a wrap that died
    when = datetime.datetime.fromtimestamp(time.time() if now is None else now, datetime.timezone.utc)
    body = json.dumps({"note": note.strip("/"), "started": when.strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n"
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False                        # another wrap took it a moment ago
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    return True


def finished(path: Path) -> Optional[float]:
    """When the wrap finished, as seconds since the epoch; None when there is
    no record or it does not read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stamp = datetime.datetime.strptime(data["finished"], "%Y-%m-%dT%H:%M:%S.%fZ")
        return stamp.replace(tzinfo=datetime.timezone.utc).timestamp()
    except (OSError, ValueError, KeyError, TypeError):
        return None


def end(root: Path, note: str, now: Optional[float] = None, abandon: bool = False) -> None:
    """Remove the lock and record when the wrap finished. `abandon` records nothing."""
    lock = lock_path(root, note)
    if not abandon:
        when = datetime.datetime.fromtimestamp(time.time() if now is None else now, datetime.timezone.utc)
        body = json.dumps({"note": note.strip("/"), "finished": when.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (when.microsecond // 1000)}) + "\n"
        lock.parent.mkdir(parents=True, exist_ok=True)
        done = done_path(root, note)
        tmp = done.with_name(done.name + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(str(tmp), str(done))
    try:
        lock.unlink()
    except FileNotFoundError:
        pass


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="The lock a running wrap holds.")
    ap.add_argument("verb", choices=("start", "end", "status"))
    ap.add_argument("note", help="the thread note, by its path from the workspace root")
    ap.add_argument("--abandon", action="store_true", help="with end: remove the lock and record no finish time")
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    a = ap.parse_args(argv)
    root = root_of(a.root)
    try:
        if a.verb == "start":
            if not start(root, a.note):
                print("A wrap of %s is already running." % a.note, file=sys.stderr)
                return 1
            print("locked")
        elif a.verb == "end":
            end(root, a.note, abandon=a.abandon)
            print("unlocked")
        else:
            print("running" if running(lock_path(root, a.note)) else "idle")
    except (ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
