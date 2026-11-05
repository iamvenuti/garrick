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

`start` prints `locked` and exits 0, or says that a wrap of this note is
already running and exits 1. `end` removes the lock, and exits 0 when there is
none. `status` prints `running` or `idle`. Standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

sys.dont_write_bytecode = True

MAX_AGE = 600        # seconds: a lock older than this counts as gone
FOLDER = ("System", "generated")


def root_of(given: Optional[str]) -> Path:
    """The workspace: the one given, else the one this script sits in."""
    return Path(given).resolve() if given else Path(__file__).resolve().parents[2]


def lock_name(note: str) -> str:
    """The lock's file name for a note given by its path from the workspace root."""
    return "wrap-%s.lock" % note.strip("/").replace("/", "__")


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
    return (time.time() if now is None else now) - taken < MAX_AGE


def start(root: Path, note: str, now: Optional[float] = None) -> bool:
    """Take the lock. False when a wrap of this note is already running."""
    path = lock_path(root, note)
    path.parent.mkdir(parents=True, exist_ok=True)
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


def end(root: Path, note: str) -> None:
    try:
        lock_path(root, note).unlink()
    except FileNotFoundError:
        pass


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="The lock a running wrap holds.")
    ap.add_argument("verb", choices=("start", "end", "status"))
    ap.add_argument("note", help="the thread note, by its path from the workspace root")
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
            end(root, a.note)
            print("unlocked")
        else:
            print("running" if running(lock_path(root, a.note)) else "idle")
    except (ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
