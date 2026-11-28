"""lifecycle.py: check a name, make a project or a thread, rename, move and undo (#724), through the same prepare, execute and status.

Six verbs, one executor. Each runs the workspace's own page_action.py, as a process, with `--via remote` and the operation's id, so that the
core's commit record (0.84.0) keeps one operation, one commit, and a retry returns the first receipt. Nothing here copies a handler: what a
name must look like, what a rename rewrites and what a move refuses are scaffold.py's, and the words are the App's.

    check-name   answers at once, in the App's words, whether a name is free and valid in the zone. It writes and prepares nothing.
    new-project  a project, and its first thread if one is named. A party must already be in the Parties table: adding one stays at the Mac.
    new-thread   a thread in a project.
    rename       a project or a thread, and every link to it in the zone.
    move         a thread to another project of its zone.
    undo         a rename, a move, a new project or a new thread made through these verbs, while it is the zone's last commit.

A rename and a move show what would change before they run: the paths, and the notes and lines that would be rewritten, from the plan
scaffold.py makes with the function the change writes with. The preview carries `confirmation`, a token for that one prepared operation and the plan
it showed. Nothing runs until `execute` is sent with that operation id and that token. The token works once, expires with the prepared record,
and is refused when the plan has changed since: it is made again, and the change is checked again, at the moment of the confirmation.

Every zone a request names is checked against the grant's write reach before anything is prepared (writes.py does that), and again at execute.
A name is one folder name, never a path. A project, a thread or a note that is a link is refused, because a link may lead out of the zone.
The one refusal of the App that lists every party of the workspace is replaced by a sentence that names none.

Standard library only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import common, run_op

sys.dont_write_bytecode = True

VERBS = ("check-name", "new-project", "new-thread", "rename", "move", "undo")
CONFIRMED = ("rename", "move")                          # the two whose preview the owner confirms
UNDOABLE = ("rename", "move", "new-project", "new-thread")
KINDS = ("project", "thread", "rename", "move")
MORE_FIELDS = ("name", "to", "party", "kind", "commit")
TAKES = {
    "check-name": ("kind", "project", "thread", "name", "to", "party"),
    "new-project": ("name", "party", "thread"),
    "new-thread": ("project", "name"),
    "rename": ("project", "thread", "to"),
    "move": ("project", "thread", "to"),
    "undo": ("commit",),
}
MUST = {
    "check-name": ("kind",), "new-project": ("name",), "new-thread": ("project", "name"), "rename": ("project", "to"),
    "move": ("project", "thread", "to"), "undo": ("commit",),
}
# What each kind of check needs, and what it may carry.
KIND_NEEDS = {"project": ("name",), "thread": ("project", "name"), "rename": ("project", "to"), "move": ("project", "thread", "to")}
KIND_TAKES = {"project": ("name", "party", "thread"), "thread": ("project", "name"), "rename": ("project", "thread", "to"),
              "move": ("project", "thread", "to")}
MOST_NAME = 120
COMMIT = re.compile(r"[0-9a-f]{7,40}\Z")
TAG = re.compile(r"[a-z0-9][a-z0-9-]{0,60}\Z")
ASK_TIMEOUT = 120               # seconds: one check or one plan, which reads every note of the zone
KEEP_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "GARRICK_JOBS_DIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
            "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")

NOT_A_PLACE = "That is not a project or a thread of this zone that can be changed from here."
NEEDS_READ = ("A rename or a move needs this connection to read and write the zone, because it shows what would change. "
              "The owner sets that at the Mac. Nothing was changed.")
NOT_YOURS = "That is not a change this connection made, so it is not undone from here. Undo it at the Mac."
EXPIRED = "That preview has expired. Its confirmation value lasted an hour. Nothing was changed. Prepare it again."
CHANGED = run_op.PLAN_CHANGED_SAYS
NEEDS_YES = ("Nothing was changed. This change needs the confirmation value that came with its preview. "
             "Show the owner the preview, and run execute only after the owner says yes. Garrick cannot check that. "
             "The value proves only that it was issued with this preview, for this one change, once, for an hour.")
NOT_THIS = ("That is not the confirmation value issued with this preview. It is good for that one change only, once, for an hour. "
            "Nothing was changed.")
TOO_LONG = "That took too long to check. Nothing was changed."


# ------------------------------------------------------------------ the request

def valid_name(value) -> bool:
    """One folder name: not a path, not hidden, not a name the workspace keeps, and no control character."""
    if not isinstance(value, str) or not value.strip() or len(value) > MOST_NAME or value != value.strip():
        return False
    if any(c in value for c in "/\\") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    return not (value.startswith((".", "_", "~")) or value in ("..", "Threads"))


def clean(verb, given, known):
    """The fields of a request, checked: (fields, "") or (None, the words of the refusal). A field the verb does not take is refused
    by name, as every verb of writes.py does, never ignored. `known` is every field name of any change."""
    fields = {}
    for name in given:
        if name not in known:
            return None, "%s is not a field of any change." % str(name)[:40]
    for name in known:
        value = given.get(name)
        if value in (None, "", []):
            continue
        if name not in TAKES[verb]:
            return None, "%s does not take %s." % (verb, name)
        fields[name] = value
    for name in MUST[verb]:
        if name not in fields:
            return None, "%s needs %s." % (verb, name)
    if verb == "check-name":
        kind = fields["kind"]
        if kind not in KINDS:
            return None, "kind is one of %s." % ", ".join(KINDS)
        for name in KIND_NEEDS[kind]:
            if name not in fields:
                return None, "a check of a %s name needs %s." % (kind, name)
        for name in fields:
            if name != "kind" and name not in KIND_TAKES[kind]:
                return None, "a check of a %s name does not take %s." % (kind, name)
    for name in ("project", "thread", "name", "to"):
        if name in fields and not valid_name(fields[name]):
            return None, "%s is not a name that can be used for %s." % (name, "a thread" if name == "thread" else "this")
    if "party" in fields and not (isinstance(fields["party"], str) and TAG.match(fields["party"])):
        return None, "party is the tag of one party in the Parties table."
    if "commit" in fields and not (isinstance(fields["commit"], str) and COMMIT.match(fields["commit"])):
        return None, "commit is a commit id, as the receipt of the change gave it."
    return fields, ""


# ------------------------------------------------------------------ places

def children_named(folder: Path, name: str):
    """What `name` names in `folder`, as scaffold.py finds it (case ignored): the one entry, None for none, and False when two
    entries answer to it, which is never a place to write in."""
    try:
        hit = [e for e in os.scandir(str(folder)) if e.name.lower() == name.strip().lower()]
    except OSError:
        return None
    if len(hit) > 1:
        return False
    return Path(hit[0].path) if hit else None


def inside(path: Path, zone: Path) -> bool:
    """Whether `path` is in the zone as written: no part of it, below the zone, is a link, and it resolves under the zone."""
    try:
        base = zone.resolve()
        if path.resolve() != base and base not in path.resolve().parents:
            return False
        up = path
        while up != zone and zone in up.parents:
            if up.is_symlink():
                return False
            up = up.parent
        return True
    except (OSError, RuntimeError):
        return False


def places(w, zone, verb, fields):
    """The folders and notes a request touches in its zone, as paths that exist, or "" for a place that cannot be written in: a link, a
    path that leaves the zone, or a name two entries answer to. A place that is not there is left to the page action, which says so in its
    own words."""
    zroot = Path(w.ws) / "Zones"
    zdir = zroot / zone
    if zdir.is_symlink() or not zdir.is_dir() or zdir.resolve().parent != zroot.resolve():
        return None
    out = []
    for key in ("project", "to"):
        if (key == "to" and verb != "move") or key not in fields:
            continue
        got = children_named(zdir, fields[key])
        if got is False or (got is not None and not inside(got, zdir)):
            return None
        if got is None:
            continue
        hub = got / (got.name + ".md")
        threads = got / "Threads"
        for each in (hub, threads):
            if each.exists() or each.is_symlink():
                if not inside(each, zdir):
                    return None
        out.append(got)
        if key == "project" and fields.get("thread"):
            t = children_named(threads, fields["thread"]) if threads.is_dir() else None
            if t is False or (t is not None and not inside(t, zdir)):
                return None
            if t is not None:
                note = t / (t.name + ".md")
                if (note.exists() or note.is_symlink()) and not inside(note, zdir):
                    return None
                out.append(t)
    return out


def guard(w, zone, verb, fields) -> str:
    """The words of a refusal for a request that points anywhere but at an ordinary project or thread of its zone, or ""."""
    if verb == "undo":
        return "" if undoable(w, zone, fields["commit"]) else NOT_YOURS
    shows = verb in CONFIRMED or (verb == "check-name" and fields.get("kind") in CONFIRMED)    # the App's words name a file of the zone
    if shows and not w.session.zone_allowed(zone):          # the preview holds lines of the zone's notes
        return NEEDS_READ
    named = {"project": "new-project", "thread": "new-thread"}.get(fields.get("kind"), fields.get("kind")) if verb == "check-name" else verb
    return "" if places(w, zone, named, fields) is not None else NOT_A_PLACE


def targets(w, zone, verb, fields):
    """The notes a rename or a move changes the place of, from the zone, for the checks that a wrap is not running on them and that
    git holds no changes of theirs. A new project or thread and an undo have none: the page action checks what they need."""
    if verb not in CONFIRMED:
        return []
    found = places(w, zone, verb, fields) or []
    zdir = Path(w.ws) / "Zones" / zone
    notes = []
    for folder in found[:3]:
        note = folder / (folder.name + ".md")
        if note.is_file():
            notes.append(note)
        if folder.parent.name != "Threads" and not fields.get("thread") and (folder / "Threads").is_dir():
            notes += [t / (t.name + ".md") for t in sorted((folder / "Threads").iterdir())[:200] if (t / (t.name + ".md")).is_file()]
    return sorted({n.relative_to(zdir).as_posix() for n in notes})


# ------------------------------------------------------------------ undo

def undoable(w, zone, commit) -> bool:
    """Whether this connection's own receipt holds that commit: a rename, a move, a new project or a new thread it made, in this
    zone, and saved. The page action's undo takes any commit that is the zone's last; this takes only these."""
    for rec in w.store.all():
        got = (rec.get("receipt") or {}).get("commit")
        if rec.get("grant") == w.grant and rec.get("zone") == zone and rec.get("verb") in UNDOABLE and rec.get("state") == "saved" \
                and isinstance(got, str) and len(got) == 40 and got.startswith(commit):      # the receipt holds the whole id
            return True
    return False


# ------------------------------------------------------------------ the page action, asked

def environment():
    return {k: os.environ[k] for k in KEEP_ENV if k in os.environ}


def ask(w, request: dict):
    """One request to the workspace's page_action.py, as a process, for what it says and writes nothing: (ok, reply). A page action
    that cannot be run, or does not answer in JSON, is a no."""
    page = str(Path(w.ws) / "System" / "status" / "page_action.py")
    argv = [run_op.python(), page, "--workspace", str(w.ws), "--via", run_op.VIA]
    try:
        done = subprocess.run(argv, input=json.dumps(request), capture_output=True, text=True, timeout=ASK_TIMEOUT, env=environment(),
                              cwd=str(w.ws))
        reply = json.loads((done.stdout or "").strip())
    except subprocess.TimeoutExpired:
        return False, {"say": TOO_LONG}
    except (OSError, ValueError):
        return False, {"say": "That could not be checked."}
    if not isinstance(reply, dict):
        return False, {"say": "That could not be checked."}
    return bool(reply.get("ok")), reply


def kind_of(verb, fields):
    return {"new-project": "project", "new-thread": "thread"}.get(verb, verb)


def check_request(zone, kind, fields, plan=False):
    req = {"verb": "check-name", "zone": zone, "kind": kind}
    for name in KIND_TAKES[kind]:
        if fields.get(name) is not None:
            req[name] = fields[name]
    if plan:
        req["plan"] = True
    return req


def words(reply) -> str:
    return run_op.clean_say(str(reply.get("say") or "That was refused.").strip())[:600]


def check_answer(w, zone, fields):
    """check-name: the App's answer, at once, and nothing written. A name that does not do is an answer, not an error."""
    ok, reply = ask(w, check_request(zone, fields["kind"], fields))
    return {"verb": "check-name", "zone": zone, "state": "checked", "free": ok, "saved": False, "say": words(reply)}


# ------------------------------------------------------------------ prepare

def may_show(w, rec) -> bool:
    """Whether a prepared preview may still be shown: the grant reaches the zone to write and to read, as it did when it was made."""
    return bool(w.may_write(rec["zone"]) and w.session.zone_allowed(rec["zone"]) and not w.reach_changed(rec))


def token(w, rec) -> str:
    """What the value is for: it was issued with the preview, for this operation, this request, and the plan the preview showed. A token for another operation, or for
    the same request as it stood under another plan, does not match."""
    plan = (rec.get("fields") or {}).get("_plan", "")
    return hashlib.sha256(("%s:%s:%s:%s" % (rec["id"], rec["hash"], plan, w.grant)).encode("utf-8")).hexdigest()[:20]


def would(verb, zone, fields, said, plan):
    where = "%s, %s" % (zone, fields["project"]) if fields.get("project") else zone
    if verb == "new-project":
        return "Make a project. %s" % said
    if verb == "new-thread":
        return "Make a thread. %s" % said
    if verb == "undo":
        return "Undo the change that commit %s made in %s, as one commit. It is undone only while it is still the last commit there." % (
            fields["commit"], zone)
    name = fields.get("thread") or fields["project"]
    if verb == "rename":
        head = "Rename the %s %s to %s in %s." % ("thread" if fields.get("thread") else "project", name, fields["to"], where)
    else:
        head = "Move the thread %s from %s to %s in %s." % (name, fields["project"], fields["to"], zone)
    notes = plan.get("count", 0)
    return ("%s Every link to it in the zone follows, in one commit. %d note%s would change. "
            "Nothing changes until execute is called with the confirmation value of this preview." % (head, notes, "" if notes == 1 else "s"))


def prepare(w, verb, zone, fields, operation_id):
    """Prepare one of the six. The reach has been checked by the caller; this checks the places, asks the App whether it would do the
    change (its words are the refusal), and stores the operation with what would change. A retry with an operation id returns the
    record it names, and asks the App nothing: a change that has been made would be refused as done."""
    from . import writes
    bad = guard(w, zone, verb, fields)
    if bad:
        return writes.say("not_prepared", bad)
    digest = writes.payload_hash(verb, zone, fields)
    if operation_id not in (None, ""):
        with w.store.locked("prepare"):
            return w.prepared(verb, zone, fields, digest, operation_id)
    if verb == "check-name":
        return check_answer(w, zone, fields)
    extra = {}
    if verb == "undo":
        extra["would"] = would(verb, zone, fields, "", {})
    else:
        plan = verb in CONFIRMED
        ok, reply = ask(w, check_request(zone, kind_of(verb, fields), fields, plan=plan))
        if not ok:
            return writes.say("not_prepared", words(reply))
        lines = words(reply).splitlines()
        if verb in ("new-project", "new-thread") and len(lines) > 1:       # the name asks how it is said: the App makes nothing then
            return writes.say("not_prepared", " ".join(l.strip() for l in lines[1:]) + " Make it in a session, with its spoken form (--spoken).")
        said = lines[0]
        shown = reply.get("plan") if isinstance(reply.get("plan"), dict) else {}
        if plan and not (shown and isinstance(shown.get("digest"), str) and run_op.PLAN_DIGEST.fullmatch(shown["digest"])):
            return writes.say("not_prepared", "That could not be previewed, so nothing was prepared.")      # no digest: neither recheck could hold
        extra["would"] = would(verb, zone, fields, said, shown)
        if plan:
            extra["_plan"] = str(shown.get("digest") or "")
            extra["_preview"] = {k: shown[k] for k in ("paths", "count", "files", "hubs", "ledger_rows") if k in shown}
    with w.store.locked("prepare"):
        stale(w, verb, zone, digest, extra.get("_plan"))
        return w.prepared(verb, zone, fields, digest, None, extra)


def stale(w, verb, zone, digest, plan):
    """A request prepared before, and not run, whose plan is not the one just made: it is ended, so that the owner is shown the new one
    and the old token is never good for it."""
    if verb not in CONFIRMED:
        return
    for rec in list(w.store.all()):
        if rec.get("grant") == w.grant and rec.get("hash") == digest and rec.get("state") == "prepared" \
                and (rec.get("fields") or {}).get("_plan") != plan:
            with w.store.locked(rec["id"]):
                fresh = w.store.read(rec["id"])
                if fresh and fresh.get("state") == "prepared":
                    end(w, fresh, CHANGED)


def end(w, rec, say):
    """A prepared operation that will not run: refused, and what was asked is not kept."""
    rec.update({"state": "refused", "receipt": {"ok": False, "say": say}, "finished": time.time()})
    rec.pop("fields", None)
    rec.pop("would", None)
    w.store.write(rec["id"], rec)
    return rec


# ------------------------------------------------------------------ execute

def confirmed(w, rec, confirmation, keep):
    """For a rename or a move that is prepared: None when the owner's confirmation is for this operation, as it was previewed, and the
    preview has not expired; else the reply that stops it, with nothing written. `keep` is how long a prepared operation lives."""
    if time.time() - float(rec.get("created") or 0) > keep:
        return w.view(end(w, rec, EXPIRED))
    if confirmation in (None, ""):
        return common.refusal("needs_confirmation", NEEDS_YES)
    if not isinstance(confirmation, str) or not hmac.compare_digest(confirmation.encode("utf-8"), token(w, rec).encode("utf-8")):
        return common.refusal("not_confirmed", NOT_THIS)
    return None


def unchanged(w, rec):
    """None when the plan, made again now, is the one the preview showed; else the reply that stops it. Asked just before the page
    action runs, so that a thread renamed, a link added or a note saved since the preview is not carried along."""
    fields = rec.get("fields") or {}
    ok, reply = ask(w, check_request(rec["zone"], kind_of(rec["verb"], fields), fields, plan=True))
    shown = reply.get("plan") if isinstance(reply.get("plan"), dict) else {}
    if not ok or str(shown.get("digest") or "") != fields.get("_plan"):
        return w.view(end(w, rec, words(reply) if not ok else CHANGED))
    return None
