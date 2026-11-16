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
OK = re.compile(r"^\s*(?:yes|yep|yeah|ok|okay|sure)\s*[.!]?\s*\Z", re.I)    # an answer to a question that offers one place
ANSWER_WORDS = 6                # a message of more words, or one that asks something, is a new request, not an answer
SUBJECT_WINDOW = 2 * 3600       # a question about the subject stays open this long, the exchanges' own session limit
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


def settle(intake, root: Path, text: str, offer: Optional[list] = None):
    """(kind, payload) for the place a message names: `place`, `ask` (the name is ambiguous), `none` or `refused`. The
    words are settled as a question about a place, never a note's (`purpose="ask"`): a project alone is a place. When
    `offer` is a list, the places an `ask` or `none` question lists are put in it."""
    try:
        return "place", intake.resolve_destination(root, text, text, purpose="ask")
    except intake.Confirm as e:
        q = str(e)
        if offer is not None:
            offer.extend(getattr(e, "offer", None) or [])
        return ("none" if isinstance(e, getattr(intake, "NoPlace", ())) and not getattr(e, "offer", None) else "ask"), q
    except intake.Refusal as e:
        return "refused", str(e)


def pending_subjects(now: float) -> list:
    """The questions about a subject that the bot asked and nobody has answered, inside the open window."""
    return [e for e in exchanges.load()["exchanges"].values()
            if e.get("pending_subject") and not e.get("closed") and now - e.get("touched", 0) <= SUBJECT_WINDOW]


def is_answer(text: str) -> bool:
    """Whether a message typed as a new message may be the answer to a question: short, and itself no question."""
    return len(text.split()) <= ANSWER_WORDS and "?" not in text


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
    if reply_to is None and is_answer(text):
        waiting_subject = pending_subjects(now)
        if len(waiting_subject) == 1:        # the bot has just asked about a subject: the next short message is the answer
            return subject_answer(intake, root, waiting_subject[0], text)
        if len(waiting_subject) > 1:
            names = [(e["pending_subject"]["text"] or "")[:40] for e in waiting_subject[:3]]
            return {"do": "ask", "kind": "which-subject", "text": text,
                    "question": "Two questions are waiting: which are you answering, %s? Reply to the one you mean." % " or ".join(
                        '"%s"' % n for n in names)}
    offer: list = []
    kind, payload = settle(intake, root, strip_deep(text), offer)
    if kind in ("ask", "none", "refused"):
        inside = open_project(intake, root, text, now)          # "Pricing: ..." inside a project-bound exchange
        if inside is not None:
            kind, payload = "place", inside
    if kind == "place":
        ex = exchanges.open_session(now)
        if ex is not None and (ex["zone"], ex["project"], ex["thread"]) == (payload["zone"], payload["project"], payload["thread"]):
            return {"do": "continue", "exchange": ex, "text": text}
        return {"do": "bind", "place": payload, "text": text}
    if kind in ("ask", "refused"):
        return {"do": "ask", "kind": "subject", "question": payload, "text": text, "offer": offer}
    waiting = [e for e in exchanges.pending_for() if not e.get("pending_subject")]
    if len(waiting) > 1:                    # one message that could answer two questions: asked, never guessed
        names = [e["said"] for e in waiting[:3]]
        return {"do": "ask", "kind": "which-question", "text": text,
                "question": "Two questions are waiting: which are you answering, %s? Reply to the one you mean." % " or ".join(names)}
    ex = exchanges.open_session(now)
    if ex is not None:
        return {"do": "continue", "exchange": ex, "text": text}
    return {"do": "ask", "kind": "subject", "question": WHICH, "text": text, "offer": []}


def open_project(intake, root: Path, text: str, now: float) -> Optional[dict]:
    """The place a message names inside the project the open exchange is bound to, when that exchange is bound to a
    project alone and the message names one of its threads: the conversation narrows, no question is asked."""
    ex = exchanges.open_session(now)
    if ex is None or not ex.get("project") or ex.get("thread"):
        return None
    kind, payload = settle(intake, root, "%s, %s" % (ex["project"], strip_deep(text)))
    if kind == "place" and (payload["zone"], payload["project"]) == (ex["zone"], ex["project"]) and payload["thread"]:
        return payload
    return None


def subject_answer(intake, root: Path, ex: dict, answer: str) -> dict:
    """The owner answered the bot's question about the subject: read together with the message it answers. When it
    settles to one place it binds; when it does not, the question is asked again, never guessed. A yes or an ok to a
    question that offered one place binds to that place."""
    first = ex["pending_subject"]["text"]
    offered = ex["pending_subject"].get("offer") or []
    if OK.match(answer or "") and len(offered) == 1:
        return {"do": "bind", "place": dict(offered[0]), "text": first, "answer_to": ex["id"]}
    offer: list = []
    kind, payload = settle(intake, root, strip_deep(first) + "\n" + answer, offer)
    if kind == "place":
        return {"do": "bind", "place": payload, "text": first, "answer_to": ex["id"]}
    return {"do": "ask", "kind": "subject", "question": payload if kind in ("ask", "refused") else WHICH, "text": first,
            "answer_to": ex["id"], "offer": offer}


def strip_deep(text: str) -> str:
    return re.sub(r"^\s*deep\s*:\s*", "", text or "", flags=re.I)
