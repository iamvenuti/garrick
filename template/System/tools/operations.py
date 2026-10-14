#!/usr/bin/env python3
"""operations.py: the durable record of what state a page action is in.

The status page's buttons (page_action.py, in the status extra) run each
click as its own process. This module gives each of those a record that
outlives the process and the page: one JSON object per line, appended to
`operations.jsonl` in the jobs folder (GARRICK_JOBS_DIR, or
~/Library/Logs/garrick-jobs on a Mac), beside the locks and the audit log.
That folder is outside the workspace, so the record is never committed and
never appears in Obsidian. The notes and git stay the only record of *what
changed*; this is the record of *what state an action is in*.

Two ids, each with one job:

    op   a correlation id, 8 to 32 lowercase hex characters, minted by the
         caller so the page can show the action within a second of the click.
         Checked for shape only; never trusted for meaning.
    key  an identity key, computed here from the verb, the zone and the
         verb's declared identity fields. A client cannot choose or defeat
         it. It recognises a repeated click.

Four states: `queued`, `running` (with a free-text `phase` the worker
writes), then `completed` or `failed`. Every terminal record carries an
`outcome`, and only one of them may read as saved:

    saved      completed   the edit was made and committed
    refused    failed      a check said no: a wall, a stale line, a collision
    crashed    failed      the worker raised, or git failed for another reason
    unknown    failed      the worker is gone and left no terminal record
    lost       failed      the record could not be read (the page's own entry)

The sentences for the four that failed come from one mapping, `say()`, keyed
by outcome; nothing else composes a terminal sentence, and a reason that
would read as a success is replaced before it reaches one (`affirms()`).

Whether a worker is alive is a lock file, `op-<op>.run`, held with a
non-blocking exclusive flock for the whole run: it survives pid reuse and
goes with the process on SIGKILL. A record that is not terminal whose lock
can be taken has no worker, and the next reader writes `unknown` for it.

`DECLARED` is the table every operation is declared in, one row per verb,
whichever way the request arrives: the page's buttons, the ask box, a skill
piping JSON into page_action.py, or scaffold.py on the command line. A row
names the `fields` a request may carry, the `identity` among them, the
`scope` it touches, whether it `commits`, whether a `retry` of it is safe,
and the `precheck` that says what must still be true for it to run.

Validation is closed: `validate()` refuses a field the verb does not declare,
by name, rather than ignoring it, so an unknown field can never widen what an
action touches. The reason comes from this file, so the sentence read for a
refusal is the same whichever way the request arrived.

`stale()` is the other half: given the fingerprint read from the world now,
it says whether the request still means what it did. Nothing here computes a
fingerprint. The Todo verbs' is the hash of the line's exact text, which
todo_lines keeps; park's and wake's is the note's own `status:`.

`OPS` stays what it has been since 0.26.0: the six verbs that keep a durable
record, derived from the table. A newer copy of this file found by an older
status extra must not start recording verbs that extra knows nothing about.

The table declares; the handlers do the work, and do not move here.
Standard library only; Python 3.9.
"""

from __future__ import annotations

import collections
import contextlib
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import fcntl
except ImportError:             # not on Windows, where the status app does not run
    fcntl = None

API = 1
FILE = "operations.jsonl"
JOURNAL_LOCK = "operations.lock"
IDEM_WINDOW = 120               # seconds: a repeated request joins, or replays a save, inside it
RECENT = 600                    # seconds: a terminal record is still offered to a page for this long
KEEP = 86400                    # seconds: and kept in the file for this long
COMPACT_BYTES = 512 * 1024
LOGGED_TEXT = 60                # a new line's text, cut as the audit log cuts it
OP_RE = re.compile(r"[0-9a-f]{8,32}")

STATES = ("queued", "running", "completed", "failed")
OUTCOMES = ("saved", "refused", "crashed", "unknown", "lost")
SUCCESS_VERBS = ("saved", "parked", "ticked", "added", "renamed", "made", "committed")

# ---- the declared operations ---------------------------------------------

Op = collections.namedtuple("Op", "fields identity scope commits retry precheck")
# Per verb:
#   fields    every field a request may carry besides those in ALWAYS. A field
#             not here is refused by name (validate), never ignored.
#   identity  which of them say what the request is, so that the same request
#             twice has the same key. The zone is always part of it besides.
#   scope     what a request of this verb may touch: one zone's notes, the
#             workspace outside a zone, the machine, or nothing (it reads).
#   commits   whether it makes a commit in a zone's repository.
#   retry     whether sending it again after it failed can do a second thing.
#             "safe": the handler checks the world before it changes it.
#   precheck  the fingerprint the request must still match (stale), or None
#             where the handler checks for itself.
SCOPES = ("zone", "workspace", "machine", "none")
RETRIES = ("safe", "unsafe")
PRECHECKS = (None, "line", "status")
# The fields every request may carry, whatever its verb: what it is, and the
# correlation id the caller mints for it.
ALWAYS = ("verb", "op")


def _op(fields, identity=(), scope="none", commits=False, retry="unsafe", precheck=None) -> Op:
    return Op(fields=tuple(fields), identity=tuple(identity), scope=scope, commits=commits,
              retry=retry, precheck=precheck)


DECLARED: Dict[str, Op] = {
    # The six the page sends under the zone lock, and the only ones that keep
    # a record. Their prechecks are this file's; the rest check for themselves.
    "park": _op(("zone", "project", "thread", "file"), ("project", "thread", "file"),
                "zone", True, "safe", "status"),
    "wake": _op(("zone", "project", "thread", "file"), ("project", "thread", "file"),
                "zone", True, "safe", "status"),
    "todo-done": _op(("zone", "file", "key"), ("file", "key"), "zone", True, "safe", "line"),
    "todo-undo": _op(("zone", "file", "key"), ("file", "key"), "zone", True, "safe", "line"),
    "todo-date": _op(("zone", "file", "key", "date"), ("file", "key", "date"), "zone", True, "safe", "line"),
    # The line it adds has no key yet: a line already in the note is refused
    # by the handler, which is that verb's own check.
    "todo-add": _op(("zone", "text", "target", "date"), ("text", "target", "date"), "zone", True, "safe"),
    # Declared, and nothing else: each of these keeps the validation it has.
    # They are here so that one table answers what a verb accepts, and so the
    # test that enumerates what the page sends has something to check against.
    "new-project": _op(("zone", "name", "party", "thread"), ("name",), "zone", True, "safe"),
    "new-thread": _op(("zone", "project", "name"), ("project", "name"), "zone", True, "safe"),
    "check-name": _op(("zone", "kind", "project", "thread", "name", "party", "to"), ("kind", "name", "to"), "none"),
    "rename": _op(("zone", "project", "thread", "to"), ("project", "thread", "to"), "zone", True),
    "delete": _op(("zone", "project", "thread", "confirm"), ("project", "thread"), "zone", True),
    "undo": _op(("zone", "commit"), ("commit",), "zone", True),
    "interrupt": _op(("zone", "project", "thread", "file", "where", "next", "keep", "by"),
                     ("project", "thread", "file"), "zone", True),
    # The interruption stack is in System/generated/, which is never committed.
    "back": _op(("zone", "project", "thread", "file"), ("project", "thread", "file"), "workspace"),
    "stack": _op((), (), "none", retry="safe"),
    "unstack": _op(("zone", "project", "thread"), ("project", "thread"), "workspace"),
    # The settings file is in the workspace's own repository, committed with it.
    "settings": _op(("launchers", "default", "zones"), (), "workspace"),
    # launchd starts the job; nothing in the workspace is touched here.
    "run": _op(("job",), ("job",), "machine"),
    # The cmux verbs: a tab in a folder, by name or by the folder itself.
    "open": _op(("zone", "project", "thread", "folder", "prompt"), ("project", "thread", "folder"), "machine"),
    "close": _op(("zone", "project", "thread"), ("project", "thread"), "machine"),
    "startup": _op((), (), "machine"),
    "shutdown": _op((), (), "machine"),
    # The one verb that only reads: the open set of records, for a page that
    # was reloaded. It carries nothing but its own name.
    "operations": _op((), (), "none", retry="safe"),
}
# The verbs that keep a durable record: what the page sends under the zone
# lock and commits a note. `OPS` is the name page_action.py has used since
# 0.26.0, and the name read() reports, so it keeps meaning exactly that.
RECORDED = ("park", "wake", "todo-done", "todo-undo", "todo-date", "todo-add")
OPS: Dict[str, Op] = {verb: DECLARED[verb] for verb in RECORDED}
# What an absent field means, so that leaving it out and sending it say the same.
DEFAULTS = {"target": "-", "date": "-"}
# For park and wake, the status the verb would set, and so the one a note
# already has nothing to do about. This is their precheck's whole content.
SETS = {"park": "parked", "wake": "active"}
FIELD_MAX = 40                  # of a field's name, in the sentence that refuses it


class BadOp(Exception):
    """The correlation id is not of the right shape."""


def mint_op() -> str:
    return secrets.token_hex(8)


def valid_op(op) -> bool:
    return isinstance(op, str) and OP_RE.fullmatch(op) is not None


def _norm(name: str, value):
    if isinstance(value, str):
        value = value.strip()
    if value is None or value == "":
        return DEFAULTS.get(name)
    return value


def identity_key(verb: str, req: dict) -> str:
    """sha256 of the canonical JSON of the verb, the zone and the verb's
    identity fields. Field order, a missing field against a null or empty
    one, and a client's own `op` or `key`-like extras do not change it."""
    spec = OPS[verb]
    body = {"verb": verb, "zone": _norm("zone", req.get("zone")),
            "fields": {k: _norm(k, req.get(k)) for k in sorted(spec.identity)}}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# Closed validation, and the precheck --------------------------------------


def _field_name(key) -> str:
    """A field's name as a sentence may carry it: one line, cut short."""
    name = " ".join(str(key).split())
    if len(name) > FIELD_MAX:
        name = name[:FIELD_MAX] + "…"
    return name or "(nothing)"


def undeclared(verb: str, req: dict) -> List[str]:
    """The fields of the request the verb does not declare, sorted. Empty for
    a verb the table does not know: that is the caller's refusal to make."""
    spec = DECLARED.get(verb)
    if spec is None or not isinstance(req, dict):
        return []
    return sorted(k for k in req if k not in spec.fields and k not in ALWAYS)


def validate(verb: str, req: dict) -> Optional[str]:
    """Why a request is refused before anything runs, or None to carry on.

    Closed: a field the verb does not declare is refused by name, rather than
    ignored, which is what stops an unknown field widening what an action
    touches. A verb the table does not declare is not judged here; the
    caller's own list of what it does says no first."""
    extra = undeclared(verb, req)
    if not extra:
        return None
    # The negation is repeated before every name on purpose: affirms() reads
    # the words before a success verb, so a field spelled `saved` still has
    # a `no` in front of it and the refusal cannot be read as a success.
    return NO_FIELD.format(verb=verb, names=" and ".join(ONE_FIELD.format(name=_field_name(k)) for k in extra))


def stale(verb: str, req: dict, found) -> Optional[str]:
    """Why the request no longer means what it did, or None to carry on.

    `found` is the fingerprint the verb's `precheck` names, read from the
    world now: for the Todo verbs the key of the line the request still
    points at, falsy when no live line has it; for park and wake the note's
    `status:` as its frontmatter has it, "" for a note with none. Nothing
    here computes a fingerprint, so there is one hash of a Todo line in the
    workspace and one reading of a note's status, not a second of each."""
    kind = DECLARED[verb].precheck if verb in DECLARED else None
    if kind is None:
        return None
    if kind == "line":
        return None if found else STALE_WHY[("line", None)]
    if str(found or "").strip().lower() != SETS[verb]:
        return None
    return STALE_WHY[("status", verb)].format(name=name_of(verb, req))


# The words ----------------------------------------------------------------

_SUCCESS = re.compile(r"\b(%s)\b" % "|".join(SUCCESS_VERBS), re.I)
_NEGATED = re.compile(r"(?:\bnot|\bno|\bnever|\bnothing|\bwithout|\bcannot|\bnor|n't)\s+(?:[\w'-]+\s+){0,2}$", re.I)


def affirms(sentence: str) -> bool:
    """Does the sentence say a success verb in the affirmative? "Not
    committed" does not; "made, but not committed" does, by "made"."""
    text = sentence or ""
    for m in _SUCCESS.finditer(text):
        if not _NEGATED.search(text[max(0, m.start() - 28):m.start()]):
            return True
    return False


def name_of(verb: str, req: dict) -> str:
    """What the request is about, for a sentence."""
    if verb in ("park", "wake"):
        for k in ("thread", "project"):
            if isinstance(req.get(k), str) and req[k].strip():
                return req[k].strip()
        if isinstance(req.get("file"), str) and req["file"].endswith(".md"):
            return Path(req["file"]).stem
        return "that note"
    return "that Todo line" if verb != "todo-add" else "the new Todo line"


WORKING = {"park": "Parking {name}…", "wake": "Waking {name}…", "todo-done": "Ticking that line…",
           "todo-undo": "Reopening that line…", "todo-date": "Changing that line's date…",
           "todo-add": "Adding to {zone}…"}
ALREADY = {"park": "Already parking {name}…", "wake": "Already waking {name}…",
           "todo-done": "Already ticking that line…", "todo-undo": "Already reopening that line…",
           "todo-date": "Already changing that line's date…", "todo-add": "Already adding to {zone}…"}
# The sentence for each way an action ends other than saved. {what} is the
# thing the action would have changed; {zone} where to look.
SAYINGS = {
    "refused": "Not done. {why}",
    "crashed": "That did not work: {why} Check git status in {zone} before trying again.",
    "unknown": "We do not know whether {what} went through: the action stopped before it reported. "
               "Run git log -1 in {zone} to see whether the change landed. Trying again is safe: it checks first.",
    "lost": "No record of this action was found, so we do not know whether it went through. "
            "Run git log -1 in {zone}, then try again: it checks first.",
}
FALLBACK_WHY = {"refused": "A check refused it.", "crashed": "The action stopped with an error."}
# The two refusals this file makes itself, which say() then puts in its
# sentence. Validation: the field, named. The precheck: what the world says
# now, keyed by the fingerprint and the verb. Both are read by whoever sent
# the request, so the words are here rather than in each caller.
# The name comes straight after the `no` on purpose: a field spelled `saved`
# must still read as a refusal, and both guards on that read two words back.
NO_FIELD = "{verb} takes {names}"
ONE_FIELD = "no {name} field"
STALE_WHY = {
    ("line", None): "that line has changed since the page was built; it rebuilds now, try again",
    ("status", "park"): "{name} was set aside already, so nothing was changed",
    ("status", "wake"): "{name} is active already, so nothing was changed",
}


def label(verb: str, req: dict, already: bool = False) -> str:
    table = ALREADY if already else WORKING
    return table[verb].format(name=name_of(verb, req), zone=req.get("zone") if isinstance(req.get("zone"), str) else "the zone")


def _sentence(why: str, outcome: str) -> str:
    why = " ".join(str(why or "").split())
    if not why or affirms(why):
        return FALLBACK_WHY.get(outcome, "")
    why = why[0].upper() + why[1:]
    return why if why[-1] in ".!?" else why + "."


def say(outcome: str, verb: str, req: dict, why: str = "", said: str = "") -> str:
    """The sentence an action ends on. Only `saved` says what the handler
    said; every other outcome is built here, from its own template."""
    if outcome not in OUTCOMES:
        raise ValueError("not an outcome: %r" % (outcome,))
    if outcome == "saved":
        return said or "Done."
    zone = req.get("zone") if isinstance(req.get("zone"), str) else "the zone"
    return SAYINGS[outcome].format(why=_sentence(why, outcome), what=_what(verb, req), zone=zone)


def _what(verb: str, req: dict) -> str:
    if verb == "todo-add":
        return "the new Todo line"
    if verb.startswith("todo-"):
        return "the change to that Todo line"
    return "the change to " + name_of(verb, req)


def state_for(outcome: str) -> str:
    return "completed" if outcome == "saved" else "failed"


def lost_sentence() -> str:
    """The page's own sentence for an entry the journal does not know, with
    {zone} for the page to fill in."""
    return SAYINGS["lost"]


# The journal -------------------------------------------------------------


def _request(verb: str, req: dict) -> dict:
    """Only the fields the verb declares, a new line's text cut short."""
    out = {}
    for k in OPS[verb].fields:
        if k in req:
            v = req[k]
            if isinstance(v, str) and len(v) > LOGGED_TEXT:
                v = v[:LOGGED_TEXT] + "…"
            out[k] = v
    return out


class Journal:
    """operations.jsonl and its lock in one jobs folder."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.path = self.folder / FILE

    def usable(self) -> bool:
        """Can records be written here at all? False on a platform without
        flock, or when the folder cannot be made or written."""
        if fcntl is None:
            return False
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            os.close(os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600))
            return True
        except OSError:
            return False

    @contextlib.contextmanager
    def lock(self, wait: float = 5.0):
        """The journal's own lock, for a read that must agree with the write
        that follows it. Best effort: past `wait`, the block runs without."""
        fd = None
        try:
            fd = os.open(str(self.folder / JOURNAL_LOCK), os.O_RDWR | os.O_CREAT, 0o600)
            deadline = time.time() + wait
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.time() >= deadline:
                        break
                    time.sleep(0.02)
        except (OSError, AttributeError):
            pass
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)

    def append(self, rec: dict) -> None:
        """One line, in one write. A terminal record without a valid outcome
        is a programming error and is refused loudly; a file that cannot be
        written is not, and stops nothing."""
        if rec.get("state") in ("completed", "failed"):
            if rec.get("outcome") not in OUTCOMES:
                raise ValueError("a terminal record needs an outcome, got %r" % (rec.get("outcome"),))
            if (rec["state"] == "completed") != (rec["outcome"] == "saved"):
                raise ValueError("only `saved` completes: %r is %s" % (rec["outcome"], rec["state"]))
        elif rec.get("state") not in STATES:
            raise ValueError("not a state: %r" % (rec.get("state"),))
        line = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
        except OSError:
            pass

    def records(self) -> List[dict]:
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        out = []
        for raw in text.splitlines():
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if isinstance(rec, dict) and isinstance(rec.get("op"), str):
                out.append(rec)
        return out

    def latest(self) -> "collections.OrderedDict[str, dict]":
        """The last record of each op, in the order the ops began."""
        seen: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
        for rec in self.records():
            seen[rec["op"]] = rec
        return seen

    def run_path(self, op: str) -> Path:
        return self.folder / ("op-%s.run" % op)

    def alive(self, op: str) -> bool:
        """Is a worker holding this op's lock? A missing file is no worker."""
        try:
            fd = os.open(str(self.run_path(op)), os.O_RDWR)
        except OSError:
            return False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            return False
        finally:
            os.close(fd)

    def settle_dead(self, now: float) -> None:
        """Write `unknown` for each op that is not terminal and has no worker.
        Under the journal's lock, re-reading first: a worker that finished
        between the caller's read and now has already written its own."""
        for op, rec in list(self.latest().items()):
            if rec.get("state") in ("completed", "failed") or self.alive(op):
                continue
            verb, req = rec.get("verb"), rec.get("request") or {}
            req = dict(req, zone=rec.get("zone"))
            sentence = say("unknown", verb, req) if verb in OPS else SAYINGS["unknown"].format(
                what="the change", zone=rec.get("zone") or "the zone")
            self.append(dict(rec, state="failed", phase="", done=now, outcome="unknown", say=sentence))
            try:
                self.run_path(op).unlink()
            except OSError:
                pass

    def open_set(self, now: Optional[float] = None) -> List[dict]:
        """What a page is shown: every record that is not terminal, and each
        terminal one from the last RECENT seconds. A worker found dead is
        settled first."""
        now = time.time() if now is None else now
        with self.lock():
            self.settle_dead(now)
            latest = list(self.latest().values())
        out = []
        for rec in latest:
            if rec.get("state") not in ("completed", "failed") or now - (rec.get("done") or rec.get("at") or 0) <= RECENT:
                out.append({k: rec.get(k) for k in ("op", "verb", "zone", "state", "phase", "at", "done", "outcome", "say", "label")})
        return out

    def compact(self, now: float) -> None:
        """Past COMPACT_BYTES, keep each op's last record, and only the ones
        that are not terminal or ended in the last day. Under the lock."""
        try:
            if self.path.stat().st_size < COMPACT_BYTES:
                return
        except OSError:
            return
        keep = [r for r in self.latest().values()
                if r.get("state") not in ("completed", "failed") or now - (r.get("done") or r.get("at") or 0) <= KEEP]
        tmp = self.folder / (FILE + ".tmp")
        try:
            tmp.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in keep), encoding="utf-8")
            os.replace(str(tmp), str(self.path))
        except OSError:
            pass


class Run:
    """One action's journal entry, from `queued` to its terminal record."""

    def __init__(self, journal: Journal, rec: dict, fd: int):
        self.journal, self.rec, self.fd = journal, rec, fd
        self.finished = False

    @property
    def op(self) -> str:
        return self.rec["op"]

    def _write(self, **change) -> None:
        self.rec = dict(self.rec, **change)
        with self.journal.lock():
            self.journal.append(self.rec)

    def running(self) -> None:
        if not self.finished and self.rec["state"] != "running":
            self._write(state="running", phase="")

    def phase(self, text: str) -> None:
        if not self.finished:
            self._write(state="running", phase=text)

    def finish(self, outcome: str, req: dict, why: str = "", said: str = "") -> dict:
        """Write the terminal record and return the reply to hand back:
        {"ok", "say", "op", "state", "outcome"}. `ok` is true only for saved."""
        verb = self.rec["verb"]
        sentence = say(outcome, verb, req, why=why, said=said)
        state = state_for(outcome)
        self._write(state=state, phase="", done=time.time(), outcome=outcome, say=sentence)
        self.finished = True
        return {"ok": outcome == "saved", "say": sentence, "op": self.op, "state": state, "outcome": outcome}

    def close(self, req: dict) -> None:
        """Whatever happened, leave a terminal record, then let go of the lock."""
        try:
            if not self.finished:
                self.finish("crashed", req, why="the action was stopped before it finished.")
        finally:
            try:
                self.journal.run_path(self.op).unlink()
            except OSError:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass


def start(folder, req: dict, now: Optional[float] = None) -> Tuple[Optional[Run], Optional[dict]]:
    """Begin the journal entry for a request of a declared verb.

    Returns (run, None) to carry on, (None, reply) when the request joins an
    identical one that is under way or replays one that saved, and (None,
    None) when nothing can be recorded here: the caller then does exactly
    what it would without this module. Raises BadOp for an op of the wrong
    shape."""
    now = time.time() if now is None else now
    verb = req["verb"]
    op = req.get("op")
    if op is None or op == "":
        op = mint_op()
    elif not valid_op(op):
        raise BadOp("not an operation id")
    journal = Journal(folder)
    if not journal.usable():
        return None, None
    key = identity_key(verb, req)
    zone = req.get("zone") if isinstance(req.get("zone"), str) else ""
    try:
        fd = os.open(str(journal.run_path(op)), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None, None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:                         # this very op is running already
        os.close(fd)
        return None, {"ok": True, "say": label(verb, req, already=True), "op": op, "state": "running"}
    try:
        with journal.lock():
            journal.settle_dead(now)
            latest = list(journal.latest().values())
            for rec in reversed(latest):
                if rec.get("key") != key or rec["op"] == op:
                    continue
                if rec.get("state") in ("queued", "running") and now - (rec.get("at") or 0) <= IDEM_WINDOW:
                    return _release(journal, fd, op), {"ok": True, "say": label(verb, req, already=True),
                                                       "op": rec["op"], "state": "running"}
            replay = _saved_replay(latest, key, zone, now)
            if replay is not None:
                return _release(journal, fd, op), {"ok": True, "say": replay["say"], "op": replay["op"],
                                                   "state": "completed", "outcome": "saved"}
            rec = {"op": op, "key": key, "verb": verb, "zone": zone, "state": "queued", "phase": "", "at": now,
                   "request": _request(verb, req), "done": None, "outcome": None, "say": None,
                   "label": label(verb, req)}
            journal.append(rec)
            journal.compact(now)
    except BaseException:
        _release(journal, fd, op)
        raise
    return Run(journal, rec, fd), None


def _saved_replay(latest: List[dict], key: str, zone: str, now: float) -> Optional[dict]:
    """The `saved` record to return instead of doing the same thing again:
    the latest one saved in this zone, if it has this key and is inside the
    window. A different save in the zone since then (a wake after a park)
    means the same request is a new one."""
    saved = [r for r in latest if r.get("outcome") == "saved" and r.get("zone") == zone]
    if not saved:
        return None
    last = max(saved, key=lambda r: r.get("done") or 0)
    if last.get("key") == key and now - (last.get("done") or 0) <= IDEM_WINDOW:
        return last
    return None


def _release(journal: Journal, fd: int, op: str) -> None:
    try:
        journal.run_path(op).unlink()
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass
    return None


def read(folder, now: Optional[float] = None) -> dict:
    """The reply to the page's `operations` request: the open set, and what the
    page needs to render it. `durable` is false when nothing can be recorded
    in this folder, which is what the page tells the user once."""
    journal = Journal(folder)
    if not journal.usable():
        return {"ok": True, "say": "Actions are not recoverable here.", "durable": False, "verbs": [], "ops": []}
    return {"ok": True, "say": "Checked what is running.", "durable": True, "verbs": sorted(OPS),
            "ops": journal.open_set(now), "lost": lost_sentence()}
