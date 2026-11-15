#!/usr/bin/env python3
"""dispatcher.py: which thread a Telegram message is about, and what to do with it, decided by code (#570).

No model call sorts a message. `route()` reads one message of the paired private chat and the exchange record
(exchanges.py), and returns one decision:

    {"do": "note", "destination": ..., "text": ...}       the message starts with `note` or `note:`: saved as a note under
                                                           #569's contract, never reaching an assistant
    {"do": "yes", "held": <entry>}                         a reply of `yes` to the message that asked for a held action
    {"do": "no", "held": <entry>}                          a reply of `no`, `cancel` or `stop` to it: the action is cancelled
    {"do": "gone", "held": <entry>}                        a reply of yes or no to the message of an action already cancelled:
                                                           nothing runs, and the answer says it was cancelled
    {"do": "done", "exchange": ex}                         the owner says they are done: save and close the exchange
    {"do": "continue", "exchange": ex, "text": ...}        a turn in an exchange that already exists
    {"do": "bind", "place": {...}, "text": ...}            a clear destination: a new exchange (the old one, if the subject
                                                           changed, is saved and closed first)
    {"do": "ask", "question": ..., "kind": ..., "text": ...}   one short question before any project content is read or changed:
                                                           the name is ambiguous, or no thread is named and no session is open

The order is fixed. (1) A reply to one of the bot's messages always continues that message's exchange, whatever its
first word, except that `yes` to a held-action message runs that action and `no`, `cancel` or `stop` (alone, in any case)
cancels it. (2) A message that starts with `note` or `note:`
is a note. (3) "done" closes the open exchange. (4) A message that names a thread binds to it, or gets one question when
the name is ambiguous; naming the thread the open exchange is bound to continues it, and naming another switches. (5) A
message that names no thread continues the open exchange while its session is still open (inside the two-hour limit, not
closed by "done" or a switch); with none open, the bot asks "Which thread?". A leading `deep:` is left on the text: the
engine reads it (channels.plan).

A reply to a question the bot asked (a pending subject) is read together with the message it answers, as Ask reads an
answer to its own question. A message that could answer two pending questions at once is asked about, not guessed.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Optional

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import exchanges  # noqa: E402

NOTE = re.compile(r"^\s*note\b\s*:?\s*(.*)\Z", re.I | re.S)
NOTE_FOR = re.compile(r"^for\s+(.+?)\s*:\s*(.+)\Z", re.I | re.S)
DONE = re.compile(r"^\s*(?:i['’]?m\s+)?(?:done|that['’]?s\s+all|all\s+done)\s*[.!]?\s*\Z", re.I)
YES = re.compile(r"^\s*yes\s*[.!]?\s*\Z", re.I)
NO = re.compile(r"^\s*(?:no|cancel|stop)\s*[.!]?\s*\Z", re.I)         # a no to a held action: these words alone, nothing after
WHICH = "Which thread?"


def parse_note(text: str) -> Optional[dict]:
    """`note: text`, `note for Acme pricing: text`, or `note text`: the destination, when one is given, and the note."""
    m = NOTE.match(text or "")
    if not m or not m.group(1).strip():
        return None
    rest = m.group(1).strip()
    f = NOTE_FOR.match(rest)
    return {"destination": f.group(1).strip(), "text": f.group(2).strip()} if f else {"destination": "", "text": rest}


def settle(intake, root: Path, text: str):
    """(kind, payload) for the place a message names: `place`, `ask` (the name is ambiguous), `none` or `refused`."""
    try:
        return "place", intake.resolve_destination(root, text, text)
    except intake.Confirm as e:
        q = str(e)
        return ("none" if q.startswith("Where does the note about") else "ask"), q
    except intake.Refusal as e:
        return "refused", str(e)


def route(intake, root: Path, message: dict, held_by_message, now: Optional[float] = None, cancelled_by_message=None) -> dict:
    """The decision for one message: {"text", "reply_to" (the message id replied to or None)}. `held_by_message(id)` is
    hold.by_message. Reads the exchange record; changes nothing."""
    now = now or time.time()
    text = (message.get("text") or "").strip()
    reply_to = message.get("reply_to")
    if reply_to is not None:
        held = held_by_message(reply_to)
        if held is not None and YES.match(text):
            return {"do": "yes", "held": held}
        if held is not None and NO.match(text):
            return {"do": "no", "held": held}
        gone = cancelled_by_message(reply_to, now) if cancelled_by_message is not None else None
        if gone is not None and (YES.match(text) or NO.match(text)):
            return {"do": "gone", "held": gone}
        ex = exchanges.for_message(reply_to)
        if ex is not None:
            if ex.get("pending_subject"):            # an answer to "Which thread?" or a question about a name
                return subject_answer(intake, root, ex, text)
            if DONE.match(text):
                return {"do": "done", "exchange": ex}
            return {"do": "continue", "exchange": ex, "text": text}
        # a reply to a message that belongs to no exchange (an old receipt, a note's): handled as any message
    if DONE.match(text):
        ex = exchanges.open_session(now)
        return {"do": "done", "exchange": ex} if ex else {"do": "ask", "kind": "nothing", "question": "Nothing is open.", "text": text}
    note = parse_note(text) if reply_to is None else None
    if note is not None:
        return {"do": "note", "destination": note["destination"], "text": note["text"]}
    kind, payload = settle(intake, root, strip_deep(text))
    if kind == "place":
        ex = exchanges.open_session(now)
        if ex is not None and (ex["zone"], ex["project"], ex["thread"]) == (payload["zone"], payload["project"], payload["thread"]):
            return {"do": "continue", "exchange": ex, "text": text}
        return {"do": "bind", "place": payload, "text": text}
    if kind in ("ask", "refused"):
        return {"do": "ask", "kind": "subject", "question": payload, "text": text}
    waiting = [e for e in exchanges.pending_for() if not e.get("pending_subject")]
    if len(waiting) > 1:                    # one message that could answer two questions: asked, never guessed
        names = [e["said"] for e in waiting[:3]]
        return {"do": "ask", "kind": "which-question", "text": text,
                "question": "Two questions are waiting: which are you answering, %s? Reply to the one you mean." % " or ".join(names)}
    ex = exchanges.open_session(now)
    if ex is not None:
        return {"do": "continue", "exchange": ex, "text": text}
    return {"do": "ask", "kind": "subject", "question": WHICH, "text": text}


def subject_answer(intake, root: Path, ex: dict, answer: str) -> dict:
    """The owner answered the bot's question about the subject: read together with the message it answers. When it
    settles to one place it binds; when it does not, the question is asked again, never guessed."""
    first = ex["pending_subject"]["text"]
    kind, payload = settle(intake, root, strip_deep(first) + "\n" + answer)
    if kind == "place":
        return {"do": "bind", "place": payload, "text": first, "answer_to": ex["id"]}
    return {"do": "ask", "kind": "subject", "question": payload if kind in ("ask", "refused") else WHICH, "text": first,
            "answer_to": ex["id"]}


def strip_deep(text: str) -> str:
    return re.sub(r"^\s*deep\s*:\s*", "", text or "", flags=re.I)
