#!/usr/bin/env python3
"""exchanges.py: the record of the Telegram channel's conversations (#570).

One private chat serves many work threads. Each conversation about one thread is an *exchange*, and this file is the
only place that says which. It keeps what must survive a closed assistant session, a restart and several days, and
nothing that would become a second authority for the project's state: the project's state is in the workspace's notes.

An exchange holds:

    id          a stable id
    zone, project, thread   the place it is bound to (thread None for a one-thread project), set when the subject is clear
    session     the assistant's session id, while one is open; `started` and `ended` times for it; `tokens`, the input its
                last turn measured
    closed      why the exchange was closed ("done", "switched"), or None: an open exchange can be continued
    pending     the question the assistant asked and is waiting on, with the message id the bot sent it as
    recent      the last few turns, each cut short: what was asked and what was answered, so a new session can pick up
    messages    the message ids of this chat that belong to it: the owner's, and the bot's

Plus, apart from the exchanges, `by_message`: each Telegram message id and the exchange it belongs to. A reply to a bot
message is resolved by this map, never by asking a model to remember the chat. Two pending questions that a message
could answer need a clarification; code finds that, too.

Session age is a maximum, not an idle timer: `expired()` says whether a session began more than SESSION_MAX seconds ago, or
its measured input passed CONTEXT_TOKEN_LIMIT, and is checked between turns, with no model call. Replacing a session starts
the next one from the saved state (`resume_context()`), never from the whole chat.

The file is `telegram-exchanges.json` in the jobs folder, written whole beside itself and renamed over, so a reader sees
one whole file or the other. It holds words of the owner's requests, so it lives outside the workspace and is never
committed.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

sys.dont_write_bytecode = True

FILE = "telegram-exchanges.json"
SESSION_MAX = 2 * 3600          # seconds: a session older than this, counted from when it began, is replaced between turns
# The input tokens one session may reach before the next turn starts a new one from the saved state. A session's whole
# context is what the model re-reads each turn, so a limit well under the model's window keeps a long exchange cheap and
# leaves room for the thread's resume point and the saved state to be read again.
CONTEXT_TOKEN_LIMIT = 120_000
RECENT_TURNS = 6                # turns kept for a new session to read
RECENT_CHARS = 600              # characters kept of each side of a turn
KEEP_DAYS = 30                  # an exchange untouched this long is dropped, with its message ids


def jobs_dir() -> Path:
    given = os.environ.get("GARRICK_JOBS_DIR")
    if given:
        return Path(given).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "garrick-jobs"
    return Path.home() / ".local" / "state" / "garrick-jobs"


def path() -> Path:
    return jobs_dir() / FILE


def load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {"exchanges": data.get("exchanges") if isinstance(data.get("exchanges"), dict) else {},
            "by_message": data.get("by_message") if isinstance(data.get("by_message"), dict) else {}}


def save(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".new")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(str(tmp), str(p))


def new(zone: Optional[str], project: Optional[str], thread: Optional[str], said: str, now: Optional[float] = None,
        **more) -> dict:
    """Open an exchange bound to a place, or, with no place yet, one that holds the question the bot asked about the
    subject (`pending_subject`). Returns it, saved."""
    now = now or time.time()
    data = load()
    ex = {"id": "tg-" + secrets.token_hex(4), "zone": zone, "project": project, "thread": thread, "said": said,
          "created": now, "touched": now, "session": None, "started": None, "ended": None, "tokens": 0, "closed": None,
          "pending": None, "recent": [], "messages": []}
    ex.update(more)
    data["exchanges"][ex["id"]] = ex
    save(data)
    return ex


def get(eid: str) -> Optional[dict]:
    return load()["exchanges"].get(eid)


def update(eid: str, **fields) -> Optional[dict]:
    data = load()
    ex = data["exchanges"].get(eid)
    if ex is None:
        return None
    ex.update(fields)
    save(data)
    return ex


def link(eid: str, message_id: int, now: Optional[float] = None) -> None:
    """Message `message_id` of the chat belongs to this exchange."""
    data = load()
    ex = data["exchanges"].get(eid)
    if ex is None:
        return
    data["by_message"][str(int(message_id))] = eid
    if int(message_id) not in ex["messages"]:
        ex["messages"].append(int(message_id))
    ex["touched"] = now or time.time()
    save(data)


def for_message(message_id) -> Optional[dict]:
    """The exchange a Telegram message belongs to: a reply is resolved by this and nothing else."""
    data = load()
    eid = data["by_message"].get(str(message_id))
    return data["exchanges"].get(eid) if eid else None


def open_session(now: Optional[float] = None) -> Optional[dict]:
    """The most recent exchange that is still open: not closed by "done" or a switch, and whose session, if it has one, has
    not passed its age or its token limit. None when there is none: a message that names no thread then gets "Which
    thread?"."""
    now = now or time.time()
    best = None
    for ex in load()["exchanges"].values():
        if ex.get("closed") or ex.get("pending_subject") or aged(ex, now):
            continue
        if best is None or ex.get("touched", 0) > best.get("touched", 0):
            best = ex
    return best


def aged(ex: dict, now: Optional[float] = None) -> bool:
    """Whether the exchange's session began more than SESSION_MAX ago. Only this closes the door on a message that names no
    thread: a session replaced for its size is the same conversation, and carries on from what was saved."""
    if not ex.get("session") or not ex.get("started"):
        return False
    return (now or time.time()) - ex["started"] > SESSION_MAX


def expired(ex: dict, now: Optional[float] = None) -> bool:
    """Whether the exchange's session is past its maximum age, counted from when it began, or past the token limit.
    An exchange with no session yet is not expired. Checked between turns; it calls nothing."""
    if not ex.get("session") or not ex.get("started"):
        return False
    now = now or time.time()
    return now - ex["started"] > SESSION_MAX or (ex.get("tokens") or 0) >= CONTEXT_TOKEN_LIMIT


def close(eid: str, why: str, now: Optional[float] = None) -> None:
    """End the exchange: its session is over (the saved state stays), and it is no longer the one a message with no
    thread continues. A reply to one of its messages still resolves to it, and starts a new session from the saved state."""
    ex = get(eid)
    if ex is None:
        return
    update(eid, closed=why, ended=now or time.time(), session=None)


def reopen(eid: str) -> Optional[dict]:
    return update(eid, closed=None)


def end_session(eid: str, now: Optional[float] = None) -> None:
    """The session is over (age, size) and the exchange is not: the next turn builds a session from the saved state."""
    update(eid, session=None, ended=now or time.time(), tokens=0)


def record_turn(eid: str, asked: str, answered: str, session: Optional[str], tokens: int, pending: Optional[dict],
                now: Optional[float] = None) -> Optional[dict]:
    """Save one completed turn durably: the session to resume, the measured input, the question waiting if the answer
    asks one, and the turn itself, cut short, among the last few."""
    ex = get(eid)
    if ex is None:
        return None
    now = now or time.time()
    sess = session or ex.get("session")
    started = now if (sess and sess != ex.get("session")) else ex.get("started")
    recent = (ex.get("recent") or []) + [{"asked": asked[:RECENT_CHARS], "answered": answered[:RECENT_CHARS], "at": now}]
    return update(eid, session=sess, started=started,
                  tokens=int(tokens or 0), pending=pending, recent=recent[-RECENT_TURNS:], touched=now, ended=None)


def resume_context(ex: dict) -> str:
    """What a new session is told of an exchange that had one before: the pending question and the last few turns,
    each cut short. Never the chat. The thread's own resume point is read by the session from the workspace."""
    lines = []
    if ex.get("pending"):
        lines.append("Waiting on the owner: %s" % ex["pending"].get("question", ""))
    for turn in ex.get("recent") or []:
        lines.append("Owner: %s\nYou: %s" % (turn["asked"], turn["answered"]))
    return "\n".join(lines)


def pending_for(text_is_reply_to: Optional[int] = None) -> List[dict]:
    """Every exchange waiting on an answer, newest first, for code to say when two could be answered by one message."""
    waiting = [e for e in load()["exchanges"].values() if e.get("pending")]
    return sorted(waiting, key=lambda e: e.get("touched", 0), reverse=True)


def sweep(now: Optional[float] = None) -> int:
    """Drop exchanges untouched for KEEP_DAYS, with their message ids. Returns how many."""
    now = now or time.time()
    data = load()
    old = [k for k, e in data["exchanges"].items() if now - e.get("touched", 0) > KEEP_DAYS * 86400]
    for k in old:
        del data["exchanges"][k]
    if old:
        data["by_message"] = {m: e for m, e in data["by_message"].items() if e in data["exchanges"]}
        save(data)
    return len(old)
