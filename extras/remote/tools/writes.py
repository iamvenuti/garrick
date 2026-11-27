"""writes.py: the ten write verbs, as prepare, execute and status.

One prepare, one execute and one status serve all ten verbs, with the verb as an argument limited to the manifest's
served rows. Three tools are fewer for a voice client to choose between than thirty, and the verb is checked against
the manifest on every call.

    prepare   checks the request against the grant, and returns an operation id and what would change
    execute   runs that operation once, as a process of its own, and returns at once
    status    returns the receipt from the durable record

The durable record is this module's own store, `<state folder>/operations/<id>.json`, mode 0600. It is the receipt
for every verb, including those that `operations.RECORDED` does not hold, so that a restart of the service, or a
page action killed at its time limit, still ends in a receipt that says so. The same id returns the first result, and
a changed payload under the same id is refused. No `confirm` field comes from the model: the request is built here
from the fields each verb takes, and `file`, `key`, `confirm` and `destination` are never among them.

A write needs the grant's `write` class and `zone_allowed(zone, write=True)`, checked at prepare and again at
execute, because the owner may change the reach between them. Execute refuses a target that holds changes git has
not committed, and a thread that a wrap is running on. The zone lock is taken by the page action itself, as a
click takes it, so that a click at the desk and a call from here never run side by side in one zone.

Standard library only.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import common, manifest, run_op
from . import lifecycle

sys.dont_write_bytecode = True

MOST_TODO, MOST_NOTE, MOST_TITLE, MOST_NAME = 1000, 4000, 200, 120
MOST_ITEMS, MOST_DROP = 20, 20
PREPARED_KEEP = 3600            # seconds an operation waits to be executed
DONE_KEEP = 7 * 86400           # and how long a receipt is kept: longer than any client's wait or retry
UNKNOWN_AFTER = 30              # seconds before a running operation with no worker is called unknown
NOT_FOUND = "There is no such operation."

# What each verb takes, besides `zone`, and what it must have.
TAKES = {
    "note-add": ("project", "thread", "text", "title"),
    "todo-add": ("text", "target", "date"),
    "todo-done": ("line",),
    "todo-undo": ("line",),
    "todo-date": ("line", "date"),
    "todo-edit": ("line", "text"),
    "todo-retire": ("line", "reason"),
    "park": ("project", "thread"),
    "wake": ("project", "thread"),
    "checkpoint": ("project", "thread", "items", "drop"),
}
MUST = {
    "note-add": ("project", "text"), "todo-add": ("text",), "todo-done": ("line",), "todo-undo": ("line",),
    "todo-date": ("line", "date"), "todo-edit": ("line", "text"), "todo-retire": ("line", "reason"),
    "park": ("project",), "wake": ("project",), "checkpoint": ("project", "thread"),
}
LONG = {"text": MOST_TODO, "line": MOST_TODO, "reason": 300, "title": MOST_TITLE, "target": 2 * MOST_NAME}
NAMES = ("project", "thread")
ISO = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
FIELDS = ("project", "thread", "text", "title", "line", "date", "target", "reason", "items", "drop")
TAKES.update(lifecycle.TAKES)                   # #724: check-name, new-project, new-thread, rename, move and undo
MUST.update(lifecycle.MUST)
FIELDS = FIELDS + lifecycle.MORE_FIELDS


REACH_CHANGED_SAY = "That was prepared before the owner changed what this connection may reach. Prepare it again in a new chat."


def say(code, words):
    return common.refusal(code, words)


class Store:
    """The operations folder: one JSON record for each operation, a lock to change it under, and a lock a worker holds."""

    def __init__(self, root=None):
        self.root = common.private_dir(Path(root or common.state_root()) / "operations")

    def path(self, op):
        return self.root / (op + ".json")

    def exists(self, op):
        return self.path(op).is_file()

    def read(self, op):
        try:
            data = json.loads(self.path(op).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def write(self, op, rec):
        run_op.write(self.path(op), rec)

    @contextmanager
    def locked(self, op):
        fd = os.open(str(self.root / (op + ".lock")), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def worker_alive(self, op):
        """Whether a worker holds `<id>.run`. The lock goes with the process, so a worker that was killed holds nothing."""
        fd = os.open(str(self.root / (op + ".run")), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            return False
        finally:
            os.close(fd)

    def all(self):
        for p in self.root.glob("*.json"):
            if re.fullmatch(r"[0-9a-f]{16}\.json", p.name):
                rec = self.read(p.stem)
                if rec:
                    yield rec

    def tidy(self, now=None):
        now = now or time.time()
        for rec in list(self.all()):
            age = now - float(rec.get("created") or 0)
            fin = rec.get("finished")
            if (rec.get("state") == "prepared" and age > PREPARED_KEEP) or (fin and now - float(fin) > DONE_KEEP):
                for suffix in (".json", ".lock", ".run"):
                    try:
                        (self.root / (rec["id"] + suffix)).unlink()
                    except OSError:
                        pass


def payload_hash(verb, zone, fields):
    body = json.dumps({"verb": verb, "zone": zone, "fields": fields}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class Writes:
    """The write tools for one call: a Session and the operations store."""

    def __init__(self, session, store=None):
        self.session = session
        self.ws = Path(session.workspace)
        self.store = store or Store()
        self.grant = common.short(session.grant_id)
        self.verbs = manifest.served_verbs(manifest.load())

    # ------------------------------------------------------------ checks

    def zone_named(self, text):
        want = common.clean_zone_name(text).casefold()
        zones = [p.name for p in sorted((self.ws / "Zones").iterdir()) if p.is_dir() and not p.name.startswith(".")] \
            if (self.ws / "Zones").is_dir() else []
        return next((z for z in zones if z.casefold() == want), None)

    def may_write(self, zone):
        return "write" in self.session.classes and bool(self.session.zone_allowed(zone, True))

    def clean(self, verb, given):
        """The fields of a request, checked: (fields, "") or (None, the words of the refusal). A field the verb does
        not take is refused by name, as operations.validate() does, never ignored."""
        if verb in lifecycle.VERBS:
            return lifecycle.clean(verb, given, FIELDS)
        fields = {}
        for name in given:
            if name not in FIELDS:
                return None, "%s is not a field of any change." % str(name)[:40]
        for name in FIELDS:
            value = given.get(name)
            if value in (None, "", []):
                continue
            if name not in TAKES[verb]:
                return None, "%s does not take %s." % (verb, name)
            fields[name] = value
        for name in MUST[verb]:
            if name not in fields:
                return None, "%s needs %s." % (verb, name)
        for name, most in LONG.items():
            if name in fields:
                v = fields[name]
                if not isinstance(v, str) or not v.strip() or len(v) > (MOST_NOTE if (verb == "note-add" and name == "text") else most):
                    return None, "%s is not a %s that can be saved." % (name, name)
        for name in NAMES:
            if name in fields:
                v = fields[name]
                if (not isinstance(v, str) or not v.strip() or len(v) > MOST_NAME or any(c in v for c in "/\\\0\n")
                        or v.startswith((".", "_")) or v in ("..", "Threads")):
                    return None, "%s is not the name of a %s." % (name, name)
        if "date" in fields and not (isinstance(fields["date"], str) and ISO.match(fields["date"])):
            return None, "date is a day as YYYY-MM-DD."
        if "target" in fields:
            parts = fields["target"].split("/")
            if len(parts) not in (1, 2) or any(not p or p.startswith((".", "_")) or p in ("..", "Threads") for p in parts):
                return None, "target is a project, or Project/Thread."
        if "line" in fields and "\n" in fields["line"]:
            return None, "line is the words of one line."
        if verb in ("todo-edit", "todo-add") and "\n" in fields.get("text", ""):
            return None, "text is one line."
        if "items" in fields:
            items = fields["items"]
            if not (isinstance(items, list) and 0 < len(items) <= MOST_ITEMS and all(isinstance(i, dict) for i in items)):
                return None, "items is a short list of items."
        if "drop" in fields:
            drop = fields["drop"]
            if not (isinstance(drop, list) and len(drop) <= MOST_DROP and all(isinstance(i, str) and len(i) <= 40 for i in drop)):
                return None, "drop is a short list of item ids."
        if verb == "checkpoint" and not ("items" in fields or "drop" in fields):
            return None, "checkpoint needs items or drop."
        return fields, ""

    def targets(self, verb, zone, fields):
        """The files an operation changes, from the zone, as the page action would change them."""
        if verb in lifecycle.VERBS:
            return lifecycle.targets(self, zone, verb, fields)
        if verb in ("note-add", "todo-add") or verb in run_op.LINE_VERBS:
            return ["Todo.md"]
        project, thread = fields["project"], fields.get("thread")
        return ["%s/Threads/%s/%s.md" % (project, thread, thread)] if thread else ["%s/%s.md" % (project, project)]

    def would(self, verb, zone, f):
        where = "%s, %s" % (zone, " / ".join(x for x in (f.get("project"), f.get("thread")) if x)) if f.get("project") else zone
        return {
            "note-add": "Save a note of %d characters in %s." % (len(f.get("text", "")), where),
            "todo-add": "Add this line to %s's Todo list: %s" % (zone, f.get("text", "")[:120]),
            "todo-done": "Tick the one open line in %s's Todo list that says: %s" % (zone, f.get("line", "")[:120]),
            "todo-undo": "Reopen the one line ticked today in %s's Todo list that says: %s" % (zone, f.get("line", "")[:120]),
            "todo-date": "Move the due day of the line that says \"%s\" to %s." % (f.get("line", "")[:120], f.get("date")),
            "todo-edit": "Reword the line that says \"%s\" to: %s" % (f.get("line", "")[:120], f.get("text", "")[:120]),
            "todo-retire": "Retire the line that says \"%s\" to the expired list. Nothing is deleted." % f.get("line", "")[:120],
            "park": "Park %s." % where,
            "wake": "Wake %s." % where,
            "checkpoint": "Record %d checkpoint item%s in the thread note of %s. The next wrap at the desk folds them into the Resume here block."
                          % (len(f.get("items") or []), "" if len(f.get("items") or []) == 1 else "s", where),
        }[verb]

    # ------------------------------------------------------------ prepare

    def prepare(self, verb, zone, operation_id=None, **given):
        if verb not in self.verbs:
            return say("not_available", manifest.answer(manifest.load(), verb))
        canonical = self.zone_named(zone)
        if canonical is None:
            return {"text": common.NO_ZONE}
        if not self.may_write(canonical):
            return common.write_reach_refusal()
        fields, why = self.clean(verb, given)
        if fields is None:
            return say("not_prepared", why)
        if verb in lifecycle.VERBS:
            return lifecycle.prepare(self, verb, canonical, fields, operation_id)
        digest = payload_hash(verb, canonical, fields)
        with self.store.locked("prepare"):               # two prepares of one request at once are still one operation
            return self.prepared(verb, canonical, fields, digest, operation_id)

    def prepared(self, verb, canonical, fields, digest, operation_id, extra=None):
        self.store.tidy()
        if operation_id not in (None, ""):
            if not common.op_id_ok(operation_id) or len(operation_id) != 16:
                return say("not_found", NOT_FOUND)
            if not self.store.exists(operation_id):
                return say("not_found", NOT_FOUND)
            with self.store.locked(operation_id):
                rec = self.store.read(operation_id)
                if rec is None or rec.get("grant") != self.grant:
                    return say("not_found", NOT_FOUND)
                if rec.get("hash") != digest:
                    return say("changed", "That operation id belongs to a different request. Prepare a new one.")
                if rec.get("state") == "prepared" and self.reach_changed(rec):
                    return say("changed", REACH_CHANGED_SAY)
                return self.view(rec)
        for rec in self.store.all():                     # the same request prepared twice, and not yet run, is one operation
            if rec.get("grant") == self.grant and rec.get("hash") == digest and rec.get("state") == "prepared" \
                    and not self.reach_changed(rec):     # one made under an earlier reach is not that operation: a new one is made
                return self.view(rec)
        op = secrets.token_hex(8)
        rec = {"id": op, "grant": self.grant, "workspace": str(self.ws), "verb": verb, "zone": canonical, "fields": fields,
               "hash": digest, "state": "prepared", "created": time.time(),
               "would": (extra or {}).get("would") or self.would(verb, canonical, fields),
               "receipt": None, "finished": None, "reach": self.reach_now()}
        rec["fields"] = dict(fields, **{k: v for k, v in (extra or {}).items() if k.startswith("_")})   # a preview lives with the fields
        with self.store.locked(op):
            self.store.write(op, rec)
        return self.view(rec)

    # ------------------------------------------------------------ execute

    def reach_now(self) -> str:
        """The fingerprint of the Session's reach, which holds the marker of a walled zone: "" for a Session that has none."""
        fn = getattr(self.session, "reach_id", None)
        return str(fn()) if callable(fn) else ""

    def reach_changed(self, rec) -> bool:
        """Whether a record was prepared under another reach than the Session's now. A Session with no reach id never differs."""
        now = self.reach_now()
        return bool(now) and rec.get("reach") != now

    def refusal_before(self, rec):
        """Why an operation may not run now, or "". The reach as it is now, then the desk: a wrap that is running, and
        changes that git does not hold yet."""
        zone, verb, fields = rec["zone"], rec["verb"], rec["fields"]
        if not self.may_write(zone):
            return "reach"
        if self.reach_changed(rec):
            return "reach_changed"                            # prepared under another reach, or another folder of that zone
        if verb in lifecycle.VERBS and lifecycle.guard(self, zone, verb, fields):
            return lifecycle.NOT_A_PLACE                      # a link, or a place outside the zone, now
        zdir = self.ws / "Zones" / zone
        for rel in self.targets(verb, zone, fields):
            if self.wrapping(zone, rel, verb, fields):
                return "A wrap is running on that thread at the desk. Try again when it has finished."
            if self.dirty(zdir, rel, rec):
                return ("%s has changes that are not saved to its history yet. They may be open at the desk. "
                        "Nothing was changed. Try again after the next wrap, or save them first." % rel.rsplit("/", 1)[-1])
        return ""

    def wrapping(self, zone, rel, verb, fields):
        """Whether a wrap holds the lock of the note this operation changes or sits under. Fails closed: a lock tool that
        cannot answer is a wrap that may be running."""
        notes = ["Zones/%s/%s" % (zone, rel)] if rel != "Todo.md" else []
        if verb == "note-add" and fields.get("thread"):
            notes.append("Zones/%s/%s/Threads/%s/%s.md" % (zone, fields["project"], fields["thread"], fields["thread"]))
        tool = self.ws / "System" / "tools" / "wrap_lock.py"
        for note in notes:
            if not tool.is_file():
                return True
            try:
                done = subprocess.run([run_op.python(), str(tool), "status", note], capture_output=True, text=True, timeout=30,
                                      cwd=str(self.ws))
            except (OSError, subprocess.SubprocessError):
                return True
            if done.returncode != 0 or done.stdout.strip() != "idle":
                return True
        return False

    def dirty(self, zdir, rel, rec):
        """Whether the file holds changes git has not committed. A git that cannot answer counts as a yes. A checkpoint
        leaves its own note uncommitted until the next wrap: a note is the service's own, and not someone's edit, only
        while it is exactly as the last checkpoint left it."""
        try:
            done = subprocess.run(["git", "-C", str(zdir), "status", "--porcelain", "--", rel], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return True
        if done.returncode != 0:
            return True
        if not done.stdout.strip():
            return False
        if rec["verb"] != "checkpoint":
            return True
        return self.sha(zdir / rel) != self.kept(rec["zone"], rel)

    @staticmethod
    def sha(path):
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    def kept_path(self):
        return Path(self.store.root) / "checkpoints.json"

    def kept(self, zone, rel):
        try:
            return json.loads(self.kept_path().read_text(encoding="utf-8")).get("%s/%s/%s" % (self.grant, zone, rel))
        except (OSError, ValueError):
            return None

    def execute(self, operation_id, confirmation=None):
        if not (common.op_id_ok(operation_id) and len(str(operation_id)) == 16):
            return say("not_found", NOT_FOUND)
        op = str(operation_id)
        if not self.store.exists(op):
            return say("not_found", NOT_FOUND)
        with self.store.locked(op):
            rec = self.store.read(op)
            if rec is None or rec.get("grant") != self.grant:
                return say("not_found", NOT_FOUND)
            if rec["state"] != "prepared":
                return self.view(self.settle(rec))        # the same id returns the first result: running, saved, refused
            if rec["verb"] in lifecycle.CONFIRMED:
                stopped = lifecycle.confirmed(self, rec, confirmation, PREPARED_KEEP)       # the owner's yes, for this one preview
                if stopped is not None:
                    return stopped
            why = self.refusal_before(rec)
            if why == "reach":
                return common.write_reach_refusal()
            if why == "reach_changed":
                return common.refusal(common.NEW_REACH, REACH_CHANGED_SAY)
            if why:
                rec.update({"state": "refused", "receipt": {"ok": False, "say": why}, "finished": time.time()})
                rec.pop("fields", None)
                rec.pop("would", None)
                self.store.write(op, rec)
                return self.view(rec)
            if rec["verb"] in lifecycle.CONFIRMED:
                stopped = lifecycle.unchanged(self, rec)                               # and the plan is still the one it was shown
                if stopped is not None:
                    return stopped
            rec.update({"state": "running", "started": time.time()})
            self.store.write(op, rec)
            worker = subprocess.Popen([sys.executable, str(Path(run_op.__file__).resolve()), str(self.store.root.parent), op],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                                      close_fds=True)
            threading.Thread(target=worker.wait, daemon=True).start()       # reaped when it ends: no zombie in a long-lived service
            return self.view(rec)

    # ------------------------------------------------------------ status

    def core_receipt(self, rec):
        """What the commit record of the core says became of this operation: (state, receipt) or None. page_action.py keeps that
        record in the zone's own git folder for each verb that commits and carries this operation's id (#716), so a worker that stopped
        in the middle is settled here from the zone's history, once. None when the core has no record calls, the verb sends no id, or
        there is no record of this operation (a write begun by an older Garrick, or stopped before page_action began): the caller then
        says unknown, as it always did."""
        if rec.get("verb") not in run_op.JSON_VERBS + run_op.LINE_VERBS or not common.op_id_ok(rec.get("id")):
            return None
        if not self.may_write(rec["zone"]) or self.reach_changed(rec):
            return None                                   # the grant no longer reaches that zone, or that folder: the core is not asked
        got = run_op.core_outcome(self.ws, self.ws / "Zones" / rec["zone"], rec["id"])
        if got is None:                                   # no record, an unreadable repository, an older operations.py: say unknown
            return None
        result = got.get("result")
        say = str(got.get("say") or "")[:600]
        if result == "done":
            made = {"ok": True, "say": say or "Done."}
            if got.get("commit"):
                made["commit"] = str(got["commit"])[:64]
            return "saved", made
        if result == "not-done":
            return "refused", {"ok": False, "say": say or "It was not saved. Nothing was changed."}
        if result == "unsure":
            return "unknown", {"ok": False, "say": say or run_op.CRASHED}
        return None

    def settle(self, rec):
        """A running operation whose worker is gone is settled from the zone's own record of the commit when it has one (saved, not
        saved, or cannot be told), and unknown otherwise. It is never run again."""
        if rec.get("state") == "running" and time.time() - float(rec.get("started") or 0) > UNKNOWN_AFTER \
                and not self.store.worker_alive(rec["id"]):
            fresh = self.store.read(rec["id"]) or rec
            if fresh.get("state") == "running":
                said = self.core_receipt(fresh) or ("unknown", {"ok": False, "say": run_op.CRASHED})
                fresh.update({"state": said[0], "receipt": said[1], "finished": time.time()})
                fresh.pop("fields", None)
                fresh.pop("would", None)
                self.store.write(rec["id"], fresh)
            return fresh
        return rec

    def status(self, operation_id):
        if not (common.op_id_ok(operation_id) and len(str(operation_id)) == 16):
            return say("not_found", NOT_FOUND)
        op = str(operation_id)
        if not self.store.exists(op):
            return say("not_found", NOT_FOUND)
        with self.store.locked(op):
            rec = self.store.read(op)
            if rec is None or rec.get("grant") != self.grant:
                return say("not_found", NOT_FOUND)
            return self.view(self.settle(rec))

    def view(self, rec):
        state, receipt = rec["state"], rec.get("receipt") or {}
        words = {
            "prepared": ("Prepared. Nothing has changed yet. Show the owner the preview: it runs only on the owner's yes. "
                         if rec["verb"] in lifecycle.CONFIRMED else "Prepared. Nothing has changed yet. Execute it to go ahead. ") + rec.get("would", ""),
            "running": "It is running. Ask for its status in a moment.",
        }.get(state) or receipt.get("say") or ""
        out = {"operation_id": rec["id"], "verb": rec["verb"], "zone": rec["zone"], "state": state, "saved": state == "saved",
               "say": words}
        if state == "prepared":
            out["would"] = rec.get("would", "")
            if rec["verb"] in lifecycle.CONFIRMED:       # what the owner is asked about, and the token that says yes to this one
                out["preview"] = (rec.get("fields") or {}).get("_preview", {})
                out["confirmation"] = lifecycle.token(self, rec)
                out["needs_confirmation"] = True
        if receipt.get("commit"):
            out["commit"] = receipt["commit"]
        if state == "saved":
            out["source"] = "the receipt of the operation as the service recorded it"
        return out
