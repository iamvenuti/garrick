#!/usr/bin/env python3
"""hold.py: the queue of actions an engine session asked for and may not do by itself (#571).

At Act an engine session has no tool that sends, shares or deletes: those tools are not in it. It has one, `hold`
(hold_tools.py), which queues the action with what it would do and where. Nothing runs from the queue until the
owner says yes: a dialog in Ask (*Run it*, *Cancel*), or, in Telegram, a reply of `yes` to the message that asked,
and nothing else. A `yes` that is not a reply to that message runs nothing. A held action expires after 24 hours;
the status page lists it until then.

The confirmation is asked by code, not by the model's judgment: text the engine reads can at most produce a queued
action the owner sees and can refuse.

The queue is `held-actions.json` in the jobs folder, outside the workspace: it holds the words of a request, and is
never committed. Each entry carries what it would do (`what`), where (`where`), who asked (`channel`, `zone`,
`exchange`), and the action itself (`request`): either `{"tool": <the tool's name>, "args": {...}}`, which runs
through the assistant with that one tool allowed once the owner has said yes, or `{"write": <path under a shared
folder>, "text": ...}`, which code writes itself, and refuses to write over a file that is there.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

try:
    import fcntl
except ImportError:                 # no flock on this platform: the in-process lock stays
    fcntl = None

sys.dont_write_bytecode = True

FILE = "held-actions.json"
TTL = 24 * 3600                 # seconds a held action waits for its yes
KINDS = ("send", "share", "delete", "write-shared", "other")
# Tool names that send, share or delete. A name this list does not know is held all the same: unknown fails closed.
KIND_WORDS = (("delete", re.compile(r"delete|trash|remove|destroy|purge", re.I)),
              ("share", re.compile(r"share|publish|upload|invite|permission", re.I)),
              ("send", re.compile(r"send|forward|reply|draft_send|post|respond|create_event|update_event|message", re.I)))
MOST_TEXT = 20_000
# A connector tool as the assistant names it: mcp__<server>__<tool>, nothing else. A name with any other shape is
# not a tool Garrick knows, whatever the model wrote.
TOOL_RE = re.compile(r"mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+\Z")
HELD_KINDS = ("send", "share", "delete")        # a held tool is one of these kinds; any other is refused
# The arguments a confirmation shows, whatever `what` and `where` say: who it goes to, and what it touches.
SHOWN_ARGS = ("to", "cc", "bcc", "recipients", "recipient", "attendees", "email", "emails", "target", "share_with",
              "shared_with", "user", "users", "path", "file_path")
_mutex = threading.RLock()
_depth = [0]
_lock_fh: list = []
ID_RE = re.compile(r"[0-9a-f]{8}")


def jobs_dir() -> Path:
    given = os.environ.get("GARRICK_JOBS_DIR")
    if given:
        return Path(given).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "garrick-jobs"
    return Path.home() / ".local" / "state" / "garrick-jobs"


def path() -> Path:
    return jobs_dir() / FILE


@contextlib.contextmanager
def locked():
    """One writer at a time, across threads and processes: load, change and save happen inside it. Reentrant."""
    with _mutex:
        if _depth[0] == 0 and fcntl is not None:
            lock = path().with_name(FILE + ".lock")
            try:
                lock.parent.mkdir(parents=True, exist_ok=True)
                fh = open(str(lock), "a+")
                fcntl.flock(fh, fcntl.LOCK_EX)
                _lock_fh.append(fh)
            except OSError:
                pass
        _depth[0] += 1
        try:
            yield
        finally:
            _depth[0] -= 1
            if _depth[0] == 0 and _lock_fh:
                fh = _lock_fh.pop()
                try:
                    fcntl.flock(fh, fcntl.LOCK_UN)
                finally:
                    fh.close()


def load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    rows = data.get("held") if isinstance(data, dict) else None
    return {"held": rows if isinstance(rows, list) else []}


def save(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".new")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(p))


def kind_of(request: dict) -> str:
    if "write" in request:
        return "write-shared"
    tool = str(request.get("tool") or "")
    if TOOL_RE.match(tool):
        tool = tool.split("__", 2)[2]               # the tool's own name: a server called Share is not a share tool
    for kind, words in KIND_WORDS:
        if words.search(tool):
            return kind
    return "other"


def add(channel: str, zone: str, exchange: str, what: str, where: str, request: dict, now: Optional[float] = None) -> dict:
    """Queue one action. Nothing is done: the owner decides. Returns the entry."""
    if not isinstance(request, dict) or not ({"tool"} <= set(request) or {"write", "text"} <= set(request)):
        raise ValueError("a held action names a tool, or a file under a shared folder and its text")
    if "tool" in request and "write" not in request:
        tool = str(request.get("tool") or "")
        if not TOOL_RE.match(tool):
            raise ValueError("%r is not the name of a connector tool (mcp__<server>__<tool>)" % tool[:60])
        if kind_of({"tool": tool}) not in HELD_KINDS:
            raise ValueError("%s is not a tool that sends, shares or deletes, so it is not held" % tool[:60])
        if not isinstance(request.get("args", {}), dict):
            raise ValueError("the tool's arguments are an object")
    now = now or time.time()
    entry = {"id": secrets.token_hex(4), "channel": channel, "zone": zone, "exchange": exchange,
             "what": " ".join(str(what).split())[:300], "where": " ".join(str(where).split())[:300],
             "kind": kind_of(request), "state": "held", "at": now, "expires": now + TTL,
             "request": {k: v for k, v in request.items() if k in ("tool", "args", "write", "text")}}
    if len(json.dumps(entry["request"])) > MOST_TEXT:
        raise ValueError("that action is too long to hold")
    with locked():
        data = load()
        data["held"].append(entry)
        save(data)
    return entry


def sweep(data: dict, now: float) -> bool:
    """Mark what has waited past its day as expired. True when anything changed."""
    changed = False
    for e in data["held"]:
        if e.get("state") == "held" and e.get("expires", 0) <= now:
            e["state"] = "expired"
            changed = True
    return changed


def pending(now: Optional[float] = None, channel: Optional[str] = None) -> List[dict]:
    """The actions waiting for a yes, oldest first, expired ones taken out."""
    now = now or time.time()
    if not path().is_file():            # nothing was ever held: a reader (the status page) writes nothing, not even a lock
        return []
    with locked():
        data = load()
        if sweep(data, now):
            save(data)
    return [e for e in data["held"] if e.get("state") == "held" and (channel is None or e.get("channel") == channel)]


def get(hid: str) -> Optional[dict]:
    return next((e for e in load()["held"] if e.get("id") == hid), None)


def _set(hid: str, **fields) -> Optional[dict]:
    with locked():
        data = load()
        for e in data["held"]:
            if e.get("id") == hid:
                e.update(fields)
                save(data)
                return e
    return None


def note_message(hid: str, message_id: int) -> None:
    """The Telegram message that asked, so a reply of `yes` to it, and only to it, runs this action."""
    _set(hid, message_id=int(message_id))


def by_message(message_id: int) -> Optional[dict]:
    for e in pending():
        if e.get("message_id") == int(message_id):
            return e
    return None


def cancel(hid: str) -> str:
    with locked():
        e = get(hid)
        if e is None or e.get("state") != "held":
            return "That action is not waiting any more."
        _set(hid, state="cancelled")
    return "Cancelled. Nothing was done."


def _flat(value, depth: int = 0) -> List[str]:
    if isinstance(value, (list, tuple)) and depth < 2:
        return [x for v in list(value)[:20] for x in _flat(v, depth + 1)]
    if isinstance(value, dict) and depth < 2:
        pick = [value[k] for k in ("email", "address", "name", "id") if k in value]
        return [x for v in pick[:2] for x in _flat(v, depth + 1)] or [json.dumps(value, ensure_ascii=False)[:80]]
    return [" ".join(str(value).split())[:120]] if value not in (None, "") else []


def shown(e: dict) -> str:
    """What code shows of a held tool action, apart from the model's own `what` and `where`: the tool's short name and
    the arguments that say who or what it reaches. Rendered here, from `request`, so the owner reads what will run."""
    req = e.get("request") or {}
    if "write" in req:
        return "writes the file %s" % " ".join(str(req.get("write")).split())[:200]
    tool = str(req.get("tool") or "")
    parts = ["tool %s" % (tool.split("__", 2)[2] if TOOL_RE.match(tool) else "(unknown)")]
    args = req.get("args") if isinstance(req.get("args"), dict) else {}
    for key in SHOWN_ARGS:
        if key in args:
            got = _flat(args[key])
            if got:
                parts.append("%s: %s" % (key, ", ".join(got)))
    return "; ".join(parts)


def say(e: dict) -> str:
    base = "%s (%s)?" % (e["what"].rstrip("?.!"), e["where"]) if e.get("where") else "%s?" % e["what"].rstrip("?.!")
    return "%s [%s]" % (base, shown(e))


def run(hid: str, ws: Path, runner: Callable[[Path, dict], Tuple[bool, str]], now: Optional[float] = None) -> str:
    """Run a held action, once, after the owner's yes. Refused when it is not waiting, or has expired. The queue
    keeps it as done, or as failed with the reason: a second yes never repeats it."""
    now = now or time.time()
    with locked():                      # held -> running is one step under the lock: two yes replies run it once
        data = load()
        e = next((x for x in data["held"] if x.get("id") == hid), None)
        if e is not None and e.get("state") == "expired":
            return "That action waited more than a day and was dropped. Nothing was done."
        if e is None or e.get("state") != "held":
            return "That action is not waiting any more."
        if e.get("expires", 0) <= now:
            e["state"] = "expired"
            save(data)
            return "That action waited more than a day and was dropped. Nothing was done."
        e["state"] = "running"
        save(data)
    try:
        ok, said = runner(Path(ws), e)
    except Exception as exc:
        ok, said = False, "It did not run: %s." % type(exc).__name__
    _set(hid, state="done" if ok else "failed", result=" ".join(str(said).split())[:300], ran=now)
    return said if ok else "Not done. " + said


def write_shared(ws: Path, e: dict) -> Tuple[bool, str]:
    """Code's own run of a held write under a synced shared folder: only a file that is not there yet, inside a
    `.shared/` link of the entry's zone, written whole."""
    rel = str(e["request"].get("write"))
    zone = Path(os.path.normpath(str(Path(ws).resolve() / "Zones" / str(e.get("zone")))))
    target = Path(os.path.normpath(str(zone / rel)))
    if ".shared" not in Path(rel).parts or not str(target).startswith(str(zone) + os.sep):
        return False, "that path is not under a shared folder of the zone"
    try:
        if target.exists():
            return False, "a file is already there, and a file somebody else may be working on is never overwritten"
        if not target.parent.is_dir():
            return False, "the shared folder is not there"
        target.write_text(str(e["request"].get("text") or ""), encoding="utf-8")
    except OSError as exc:
        return False, "the write failed (%s)" % type(exc).__name__
    return True, "Written to the shared folder."


def listing(now: Optional[float] = None) -> List[dict]:
    """The rows the status page lists: what, where, which channel, and how long it has left."""
    now = now or time.time()
    out = []
    for e in pending(now):
        left = max(0, int(e["expires"] - now))
        out.append({"id": e["id"], "what": e["what"], "where": e["where"], "channel": e["channel"], "zone": e["zone"],
                    "kind": e["kind"], "detail": shown(e), "hours_left": left // 3600 + (1 if left % 3600 else 0)})
    return out
