#!/usr/bin/env python3
"""Allow once: the ledger of wall findings the user let through, and nothing else.

`System/walls-allowed.json` holds one entry per allowance:

    {"version": 1,
     "allowed": [{"path": "Zones/Work/Acme/Acme.md", "id": "3f9a1c2b7d",
                  "blob": "<git's blob id of the file as allowed>", "rule": "name",
                  "date": "2026-11-10", "by": "terminal"}]}

An entry covers one finding of one file, and only while the file is as it was
allowed: it matches on the path, the finding's id and git's blob id of the
file together. Edit the file and the blob changes, so the finding comes back.
The id is the first ten hex characters of SHA-1 over `path NUL rule NUL token`;
the token itself is never stored, so the ledger names no party.

A ledger that is missing, unreadable or of another version holds no allowance:
everything refuses as it did before. Only a terminal or the status page writes
an allowance (`may_write`); an assistant has neither, and so cannot.

This module reads and writes the ledger and decides who may. What a finding is,
and where a blob id comes from, belongs to check.py.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LEDGER = ("System", "walls-allowed.json")
VERSION = 1
BY = ("terminal", "page")
RULES = ("link", "name", "wording", "path", "unlabelled")   # the kinds an allowance may cover
ID_LENGTH = 10
KEYS = ("path", "id", "blob", "rule", "date", "by")


def ledger_path(root) -> Path:
    return Path(root).joinpath(*LEDGER)


def finding_id(path: str, rule: str, token: str) -> str:
    """The short id of a finding: SHA-1 over its path, rule and token, ten hex characters."""
    raw = "\0".join((path, rule, token)).encode("utf-8", "surrogatepass")
    return hashlib.sha1(raw).hexdigest()[:ID_LENGTH]


def _entry_ok(e) -> bool:
    return (isinstance(e, dict) and all(isinstance(e.get(k), str) and e.get(k) for k in KEYS)
            and e["rule"] in RULES and e["by"] in BY)


def read_ledger(root) -> List[dict]:
    """The allowances, as written. Fails closed: a ledger that is missing, unreadable, of another version, or not
    shaped as above holds none, and one entry that is not shaped as above is left out."""
    try:
        data = json.loads(ledger_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("allowed"), list):
        return []
    return [dict(e) for e in data["allowed"] if _entry_ok(e)]


def allowed_set(root) -> frozenset:
    """The ledger read once, for lookups: {(path, id, blob)}."""
    return frozenset((e["path"], e["id"], e["blob"]) for e in read_ledger(root))


def write_ledger(root, entries: List[dict]) -> None:
    """Write the ledger whole, atomically, sorted so that git sees a stable file."""
    entries = sorted((dict((k, e[k]) for k in KEYS) for e in entries), key=lambda e: (e["path"], e["id"], e["blob"]))
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"version": VERSION, "allowed": entries}, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".walls-allowed.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def allow(root, path: str, fid: str, blob: str, rule: str, by: str, today: Optional[str] = None) -> dict:
    """Add one allowance, or replace the entry for the same path and id (a new blob renews it). Returns the entry."""
    if rule not in RULES:
        raise ValueError("a finding of kind %r cannot be allowed" % rule)
    if by not in BY:
        raise ValueError("an allowance is written by the terminal or the page, not %r" % by)
    entry = {"path": path, "id": fid, "blob": blob, "rule": rule,
             "date": today or datetime.date.today().isoformat(), "by": by}
    entries = [e for e in read_ledger(root) if (e["path"], e["id"]) != (path, fid)]
    entries.append(entry)
    write_ledger(root, entries)
    return entry


def remove(root, path: str, fid: str) -> int:
    """Take away the allowance(s) for a path and a finding id, whatever their blob. Returns how many went."""
    entries = read_ledger(root)
    kept = [e for e in entries if (e["path"], e["id"]) != (path, fid)]
    if len(kept) != len(entries):
        write_ledger(root, kept)
    return len(entries) - len(kept)


def may_write(by: str, stdin=None) -> bool:
    """Whether an allowance may be written from here. The page writes through page_action.py (`by="page"`, a click
    in the app); the terminal only when stdin is a terminal. A run with neither, as an assistant's shell is, refuses."""
    if by == "page":
        return True
    if by == "terminal":
        stream = sys.stdin if stdin is None else stdin
        try:
            return bool(stream.isatty())
        except (AttributeError, ValueError):
            return False
    return False


def commit_ledger(root, message: str) -> str:
    """Commit the ledger, and only it, in the workspace's own repository, through its hook. "" when done or when
    there is no repository to commit in; otherwise what git said."""
    root = Path(root)
    if not (root / ".git").exists():
        return ""
    rel = "/".join(LEDGER)
    try:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=str(root), capture_output=True,
                                 timeout=30).returncode == 0
        if not tracked and not ledger_path(root).exists():
            return ""                    # nothing was ever written
        subprocess.run(["git", "add", "--", rel], cwd=str(root), capture_output=True, timeout=30, check=True)
        done = subprocess.run(["git", "commit", "-q", "-m", message, "--", rel], cwd=str(root), capture_output=True,
                              text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    if done.returncode == 0 or "nothing to commit" in (done.stdout + done.stderr):
        return ""
    return (done.stderr or done.stdout).strip()
