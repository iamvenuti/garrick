#!/usr/bin/env python3
"""outbox.py: Todo actions from a machine that only receives the workspace (#612).

A `roaming` machine (System/tools/machine.py) holds a copy of the server's workspace that the sync only
refreshes, so it never edits `Todo.md`. A tick on its status page, or a line reworded or added there, is
written instead as a request in the zone's drop folder, `Zones/<Zone>/Inbox/.outbox/<id>.json`, which the
sync carries to the server (a drop folder syncs both ways). The server applies each one through
page_action.py, `via: outbox`, with the lock, the commit (and the wall check) and the record a click on
the server would have, and takes the file out.

The outbox carries four verbs, and nothing else: a tick (`todo-done`), an untick (`todo-undo`), a reworded
line (`todo-edit`) and a new line (`todo-add`). A request is closed: a field its verb does not declare is
refused, a fifth verb is refused, and a request is read only from its own zone's outbox, about that zone's
`Todo.md`. Each request has an id, and an id the server has applied is never applied again.

A request whose line no longer reads as it did (its key, the hash of the line's exact text, matches no line)
is held, never applied: the server renames the file `<id>.held.json`, with the reason, and the page asks:
*Show me the line*, or *Drop it*. Applying it anyway is not an answer.

A tick typed into `Todo.md` by hand, in Obsidian for example, counts too. The status page's refresh keeps
the last `Todo.md` the sync delivered, outside the workspace (the jobs folder, `outbox-base/`), compares it
with the file, and turns each line newly ticked into a tick request, its key taken from the line as it was
before the tick. No launchd agent does it: a roaming machine loads none.

    python3 System/status/outbox.py replay [--workspace PATH]     apply what has reached this server
    python3 System/status/outbox.py list   [--workspace PATH]     what waits, and what is held

Standard library only; Python 3.9.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent

FOLDER = (("Inbox", ".outbox"))
DROP_VERB = "outbox-drop"          # the page's *Drop it*: allowed on every role, since it only removes a file from the drop folder
VERBS = ("todo-done", "todo-undo", "todo-edit", "todo-add")       # operations.OUTBOX_VERBS, which page_action.py checks it against
ENVELOPE = ("id", "made", "machine", "line", "request", "op")   # `op`: the operation a replay joined, written by the server (#641)
HELD_ENVELOPE = ENVELOPE + ("held", "held_at")
ID_RE = re.compile(r"[0-9a-f]{8,32}")
PENDING_FILE = re.compile(r"([0-9a-f]{8,32})\.json")
HELD_FILE = re.compile(r"([0-9a-f]{8,32})\.held\.json")
LEDGER = "outbox-applied.json"
KEEP_APPLIED = 5000
LINE_MAX = 300
WAITS = "waits for the server"
READ_GUARD_HOME = "the read guard is set on the home server, since this machine only receives the workspace"
ONLY_RECEIVES = ("this machine only receives the workspace, so %s waits until you are on the server")
TRANSIENT = ("try again in a moment", "cannot take the lock in", "git took longer than", "git did not run",
             "wall check was still running")      # page_action.py's words for a busy lock, a timeout and a missing git
HOLD_REASONS = {
    "stale": "the line has changed on the server since it was ticked here, so nothing was applied",
}


class Refused(Exception):
    """A request the outbox will not carry or apply, in the words the user reads."""


_PA = None


def page_action():
    """page_action.py beside this file, loaded once."""
    global _PA
    for name in ("page_action", "__main__"):          # the one already running, so that its Refused is the one caught
        loaded = sys.modules.get(name)
        if loaded is not None and callable(getattr(loaded, "perform", None)) \
                and Path(str(getattr(loaded, "__file__", "") or "")).resolve() == HERE / "page_action.py":
            return loaded
    if _PA is None:
        spec = importlib.util.spec_from_file_location("garrick_outbox_page_action", str(HERE / "page_action.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("garrick_outbox_page_action", mod)
        spec.loader.exec_module(mod)
        _PA = mod
    return _PA


def _machine(ws: Optional[Path] = None):
    """System/tools/machine.py: the workspace's, else the one beside this folder, else a Garrick clone's template."""
    places = ([Path(ws) / "System" / "tools"] if ws is not None else []) + [HERE.parent / "tools",
                                                                          HERE.parent.parent / "template" / "System" / "tools"]
    for folder in places:
        src = folder / "machine.py"
        if src.is_file():
            try:
                spec = importlib.util.spec_from_file_location("garrick_outbox_machine", str(src))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
            except Exception:
                continue
    return None


def role(ws: Optional[Path] = None) -> str:
    """This machine's role, `solo` when machine.py is not there or cannot be read."""
    mod = _machine(ws)
    try:
        return mod.role() if mod else "solo"
    except Exception:
        return "solo"


def machine_name(ws: Optional[Path] = None) -> str:
    mod = _machine(ws)
    try:
        return str(mod.name()) if mod else ""
    except Exception:
        return ""


def state_dir() -> Path:
    """Where this machine keeps what is its own: outside the workspace, in the jobs folder."""
    return page_action().jobs_dir()


def zones(ws: Path) -> List[Path]:
    root = Path(ws) / "Zones"
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))) if root.is_dir() else []


def folder_of(zone: Path) -> Path:
    return zone.joinpath(*FOLDER)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- the laptop: queue a request


def line_text(ws: Path, zone: Path, key: str, verb: str) -> str:
    """The text of the line a key names, as the zone's notes have it now: for the page's row, and the question that asks
    about it later. "" when no line has it."""
    tl = page_action().todo_lines()
    reopen = verb == "todo-undo"
    try:
        for rel, _, line in tl._scan(str(zone)):
            if rel != "Todo.md":
                continue
            if line.startswith("- [ ] ") and not reopen and tl.key(line) == key:
                return line[6:].strip()[:LINE_MAX]
            if line.startswith("- [x] ") and reopen and tl.key(tl._reopened(line)) == key:
                return tl._reopened(line)[6:].strip()[:LINE_MAX]
    except Exception:
        pass
    return ""


def make(zone: Path, request: dict, line: str = "", machine: str = "", now: Optional[dt.datetime] = None) -> str:
    """Write one request in the zone's outbox, and return its id."""
    ops = page_action().ops_lib(zone.parent.parent)
    rid = ops.mint_op()
    envelope = {"id": rid, "made": (now or dt.datetime.now()).isoformat(timespec="seconds"), "machine": machine,
                "line": line[:LINE_MAX], "request": request}
    _write_json(folder_of(zone) / (rid + ".json"), envelope)
    return rid


def queue(ws: Path, req: dict) -> dict:
    """What a roaming machine does with a page action in place of doing it: queue it, for the four Todo verbs, or say
    it waits. Raises Refused for any other verb that would write in the workspace, and returns None for one that does
    not (a read, a look at a file), which carries on as it did."""
    pa = page_action()
    ops = pa.ops_lib(ws)
    verb = req.get("verb")
    spec = ops.DECLARED.get(verb) if ops is not None else None
    if verb == DROP_VERB:
        return None         # Drop it takes a held file out of the drop folder, the one place a laptop copy may write (#621)
    if verb not in VERBS:
        if verb == "read-guard":
            raise Refused(READ_GUARD_HOME)
        if spec is not None and spec.scope in ("zone", "workspace"):
            raise Refused(ONLY_RECEIVES % "this")
        return None
    why = ops.validate(verb, req)
    if why:
        raise Refused(why)
    zone = pa.zone_dir(ws, req.get("zone"))
    name = machine_name(ws)
    if verb == "todo-add":
        request = {k: req[k] for k in ("verb", "zone", "text", "target", "date") if k in req}
        rid = make(zone, request, str(req.get("text") or ""), name)
        return {"ok": True, "say": "Added here; it %s." % WAITS, "queued": [rid]}
    if req.get("file") != "Todo.md":
        raise Refused("a line in a thread note waits until you are on the server")
    keys = pa.task_keys(req)
    made = []
    for key in keys:
        request = {"verb": verb, "zone": req["zone"], "file": "Todo.md", "key": key}
        if verb == "todo-edit":
            request["text"] = req.get("text")
        made.append(make(zone, request, line_text(ws, zone, key, verb), name))
    word = {"todo-done": "Ticked", "todo-undo": "Reopened", "todo-edit": "Reworded"}[verb]
    return {"ok": True, "say": "%s here; it %s." % (word, WAITS), "queued": made}


def gate(ws: Path, req, via: str) -> Optional[dict]:
    """page_action.perform's question before it acts. `via: outbox` is limited to the four verbs (operations.py). On a
    roaming machine a page action is queued, or refused, in place of being done. None means carry on as before: any
    other machine, and any request that only reads."""
    verb = req.get("verb") if isinstance(req, dict) else None
    ops = page_action().ops_lib(ws)
    if ops is not None and callable(getattr(ops, "via_refusal", None)):
        why = ops.via_refusal(via, verb)
        if why:
            raise page_action().Refused(why)
    if via == "outbox" or not isinstance(req, dict) or role(ws) != "roaming":
        return None
    try:
        return queue(ws, req)
    except Refused as e:
        raise page_action().Refused(str(e))


# --------------------------------------------------------------------------- what waits


def _envelopes(zone: Path):
    """(path, envelope or None, held) for each request file in a zone's outbox, in the order the requests were made:
    by `made`, then by id. A file name is a random id, so the name says nothing about which request came first."""
    folder = folder_of(zone)
    found = []
    for path in folder.iterdir() if folder.is_dir() else []:
        held = HELD_FILE.fullmatch(path.name)
        if path.is_file() and (held or PENDING_FILE.fullmatch(path.name)):
            env = _read_json(path)
            made = env.get("made") if env else None
            found.append((made if isinstance(made, str) else "", (held or PENDING_FILE.fullmatch(path.name)).group(1),
                          path, env, bool(held)))
    for _, _, path, env, held in sorted(found, key=lambda f: (f[0], f[1])):
        yield path, env, held


def pending_marks(ws: Path, zone_name: str) -> Dict[str, str]:
    """{line key: verb} of the ticks and unticks waiting in a zone's outbox, for the page's rows."""
    out: Dict[str, str] = {}
    for path, env, held in _envelopes(Path(ws) / "Zones" / zone_name):
        req = env.get("request") if env else None
        if not held and isinstance(req, dict) and req.get("verb") in ("todo-done", "todo-undo") and isinstance(req.get("key"), str):
            out[req["key"]] = req["verb"]
    return out


def held_requests(ws: Path, zone_name: str) -> List[dict]:
    """The requests the server held in a zone, each with what the question needs: its id, what was asked, the line as
    it was, why it was held, and the lines of Todo.md now that read nearest to it."""
    zone = Path(ws) / "Zones" / zone_name
    out = []
    for path, env, held in _envelopes(zone):
        if not held or not env:
            continue
        req = env.get("request") if isinstance(env.get("request"), dict) else {}
        out.append({"id": str(env.get("id") or HELD_FILE.fullmatch(path.name).group(1)), "zone": zone_name,
                    "verb": str(req.get("verb") or ""), "line": str(env.get("line") or ""),
                    "text": str(req.get("text") or ""), "why": str(env.get("held") or ""),
                    "machine": str(env.get("machine") or ""), "now": nearest(zone, str(env.get("line") or ""))})
    return out


def nearest(zone: Path, line: str, n: int = 3) -> List[str]:
    """The open lines of the zone's Todo.md that read nearest to `line`, to show next to it."""
    import difflib
    if not line.strip():
        return []
    try:
        tl = page_action().todo_lines()
        text = [t["text"] for t in tl.tasks(str(zone)) if t["file"] == "Todo.md"]
    except Exception:
        return []
    return [t[:LINE_MAX] for t in difflib.get_close_matches(line, text, n=n, cutoff=0.5)]


def drop(ws: Path, zone_name: str, rid: str) -> str:
    """Take a held request out of its outbox unapplied. Only a held one: a request that waits to be applied is not
    dropped from here."""
    pa = page_action()
    if not isinstance(rid, str) or not ID_RE.fullmatch(rid):
        raise pa.Refused("not a request")
    zone = pa.zone_dir(ws, zone_name)
    target = folder_of(zone) / (rid + ".held.json")
    if not target.is_file():
        raise pa.Refused("no held request has that id in %s" % zone.name)
    target.unlink()
    return "Dropped. Nothing was changed in %s." % zone.name


# --------------------------------------------------------------------------- the server: apply


def ledger_path() -> Path:
    return state_dir() / LEDGER


def applied_ids() -> Dict[str, str]:
    data = _read_json(ledger_path()) or {}
    ids = data.get("ids")
    return ids if isinstance(ids, dict) else {}


def remember(rid: str, now: dt.datetime) -> None:
    ids = applied_ids()
    ids[rid] = now.isoformat(timespec="seconds")
    if len(ids) > KEEP_APPLIED:
        ids = dict(sorted(ids.items(), key=lambda kv: kv[1])[-KEEP_APPLIED:])
    _write_json(ledger_path(), {"ids": ids})


def read_request(zone: Path, path: Path, env: Optional[dict]) -> dict:
    """The request an envelope carries, after the closed checks; Refused with the reason when it fails one."""
    pa = page_action()
    ops = pa.ops_lib(zone.parent.parent)
    if env is None:
        raise Refused("the request file does not read")
    if set(env) - set(ENVELOPE):
        raise Refused("the request has a field the outbox does not declare")
    m = PENDING_FILE.fullmatch(path.name)
    if not m or env.get("id") != m.group(1) or not ops.valid_op(env.get("id")):
        raise Refused("the request's id is not its file's")
    req = env.get("request")
    if not isinstance(req, dict) or req.get("verb") not in VERBS:
        raise Refused(ops.OUTBOX_ONLY)
    why = ops.validate(req["verb"], req)
    if why:
        raise Refused(why)
    if req.get("zone") != zone.name:
        raise Refused("the request is for another zone than the outbox it is in")
    if req["verb"] != "todo-add" and (req.get("file") != "Todo.md" or "keys" in req):
        raise Refused("the request is not about the zone's own Todo.md")
    return req


def transient(say: str) -> bool:
    """A refusal that says nothing about the line: a busy lock, a timeout, a git that did not run. The request is not
    held for it; it stays in the outbox for the next run."""
    low = str(say or "").casefold()
    return any(t in low for t in TRANSIENT)


def hold(zone: Path, path: Path, env: Optional[dict], reason: str, now: dt.datetime) -> None:
    """Keep a request that was not applied, as `<id>.held.json` with its reason, for the page to ask about."""
    m = PENDING_FILE.fullmatch(path.name)
    if m is None:
        return
    body = {k: v for k, v in (env or {}).items() if k in ENVELOPE}
    body.update(id=m.group(1), held=reason[:400], held_at=now.isoformat(timespec="seconds"))
    body.setdefault("request", {})
    _write_json(path.with_name(m.group(1) + ".held.json"), body)
    path.unlink()


def joined_op(env: Optional[dict]) -> str:
    """The operation an envelope joined on an earlier run, or ''."""
    op = env.get("op") if isinstance(env, dict) else ""
    return op if isinstance(op, str) else ""


def ended_for_good(ops, req: dict, out: dict) -> bool:
    """Whether the reply to a replayed request says the work is over and saved. A journalled verb says so with a
    completed state. A reply with no state came from an action done inline (a reworded line, which the journal does not
    hold, or a journal that failed mid-way): it is done, and is remembered so that it is never applied twice. A joined
    request that is still running is not over, and the request stays in the outbox."""
    state = out.get("state")
    if state is not None:
        return state == "completed"
    return True         # no state: the action ran inline, with no record to wait on (a verb the journal does not hold, or a journal that failed mid-way)


def how_it_ended(pa, ops, op: str, ws: Optional[Path] = None) -> str:
    """`saved`, `running`, `failed` or `gone` for an operation the journal holds. `gone`: no record of it is there (the
    journal was compacted), so whether it saved cannot be told, and it is never applied again. A record of another
    workspace is not believed: it counts as `failed`, and the request goes through the usual check. A record that cannot
    be read at all counts as running: the envelope is kept."""
    try:
        journal = ops.Journal(pa.jobs_dir())
        with journal.lock():
            journal.settle_dead(time.time())     # a worker that died is failed, not running for ever
            rec = journal.latest().get(op)
    except Exception:
        return "running"
    if rec is None:
        return "gone"
    if ws is not None and rec.get("workspace") != ops.workspace_id(ws):
        return "failed"
    if rec.get("state") not in ("completed", "failed"):
        return "running"
    return "saved" if rec.get("outcome") == "saved" else "failed"


def replay(ws: Path, now: Optional[dt.datetime] = None, perform=None) -> Dict[str, int]:
    """Apply, in each zone, what its outbox holds: each request once, through page_action's perform with the lock,
    the commit and the record of a click here. Returns {applied, held, skipped}. Never raises for one request."""
    pa = page_action()
    now = now or dt.datetime.now()
    perform = perform or pa.perform
    ops = pa.ops_lib(ws)
    count = {"applied": 0, "held": 0, "skipped": 0}
    journal = getattr(ops, "Journal", None)
    if journal is not None and not journal(pa.jobs_dir()).usable():
        # Nothing records an action here, so an envelope could be applied again and again: every envelope stays, and
        # nothing is applied until the journal can be written.
        count["journal"] = 1
        return count
    for zone in zones(ws):
        for path, env, held in list(_envelopes(zone)):
            if held:
                continue
            rid = PENDING_FILE.fullmatch(path.name).group(1)
            if rid in applied_ids():                  # applied before: a copy the sync brought back
                path.unlink(missing_ok=True)
                count["skipped"] += 1
                continue
            try:
                req = read_request(zone, path, env)
            except Refused as e:
                hold(zone, path, env, str(e), now)
                count["held"] += 1
                continue
            waited = joined_op(env)
            if waited:
                ended = how_it_ended(pa, ops, waited, ws)   # an operation this envelope joined on an earlier run
                if ended == "running":
                    count["waiting"] = count.get("waiting", 0) + 1
                    continue
                if ended == "saved":
                    remember(rid, now)
                    path.unlink(missing_ok=True)
                    count["applied"] += 1
                    continue
                if ended == "gone":                       # its record was compacted away: it may have saved, so it is not applied again
                    remember(rid, now)
                    path.unlink(missing_ok=True)
                    count.setdefault("gone", []).append(rid)
                    continue
                env = {k: v for k, v in env.items() if k != "op"}      # it ended without saving: this replay does it again
                _write_json(path, env)
            out, logged, _ = perform(ws, dict(req), ops, via="outbox")
            try:
                pa.audit(req, bool(out.get("ok")), logged or out.get("say") or "", via="outbox")
            except Exception:
                pass
            if out.get("ok") and not ended_for_good(ops, req, out):
                # The request joined one that is still running (or the record says nothing of how it ended): keep the
                # envelope, with the operation's id, until that operation really ends (#641).
                if isinstance(out.get("op"), str) and ops.valid_op(out.get("op")) and path.exists():
                    _write_json(path, dict(env, op=out["op"]))
                count["waiting"] = count.get("waiting", 0) + 1
            elif out.get("ok"):
                remember(rid, now)                    # first: a crash after the commit never applies it twice
                path.unlink(missing_ok=True)
                count["applied"] += 1
            elif transient(out.get("say")):
                count["retry"] = count.get("retry", 0) + 1       # left in place, and the zone's later requests wait behind it
                break
            else:
                hold(zone, path, env, str(out.get("say") or "refused"), now)
                count["held"] += 1
    return count


# --------------------------------------------------------------------------- the laptop: a tick made by hand


def _base_dir() -> Path:
    return state_dir() / "outbox-base"


def last_request(zone: Path, key: str):
    """(made, verb, line) of the latest tick or untick waiting in the zone's outbox for a line, or None."""
    last = None
    for path, env, held in _envelopes(zone):
        req = env.get("request") if env else None
        if held or not isinstance(req, dict) or req.get("key") != key or req.get("verb") not in ("todo-done", "todo-undo"):
            continue
        last = (str(env.get("made") or ""), req["verb"], str(env.get("line") or ""))
    return last


def after_last(zone: Path, key: str, now: Optional[dt.datetime] = None) -> dt.datetime:
    """The time a new request for a line is made at: now, or a second after the line's latest request waiting, so that
    `made` orders them as the user chose, whatever the clock says."""
    stamp = now or dt.datetime.now()
    last = last_request(zone, key)
    if last:
        try:
            stamp = max(stamp, dt.datetime.fromisoformat(last[0]) + dt.timedelta(seconds=1))
        except ValueError:
            pass
    return stamp


def untick_for(ws: Path, zone: Path, key: str, now: Optional[dt.datetime] = None) -> int:
    """A line ticked by hand and reopened by hand: if its tick request is still in the outbox, write an untick request
    after it, and return 1. The tick may already be on its way to the server, or applied there, and a file taken out here
    would not stop it; an untick, ordered after the tick by `made`, ends with the line open whichever happened. The tick
    stays: nothing is removed. No tick waiting, or an untick already last for the line, makes none."""
    last = last_request(zone, key)
    if last is None or last[1] != "todo-done":
        return 0
    stamp = after_last(zone, key, now)
    make(zone, {"verb": "todo-undo", "zone": zone.name, "file": "Todo.md", "key": key}, last[2], machine_name(ws), stamp)
    return 1


def hand_ticks(ws: Path, now: Optional[dt.datetime] = None) -> int:
    """On a roaming machine: turn each line newly ticked by hand in a zone's Todo.md into one tick request, and return
    how many were made. The last Todo.md the sync delivered is kept outside the workspace; a line open there and
    ticked now is a new tick, its key the line's as it was. Nothing is made twice."""
    if role(ws) != "roaming":
        return 0
    pa = page_action()
    tl = pa.todo_lines()
    made = 0
    for zone in zones(ws):
        todo = zone / "Todo.md"
        try:
            current = todo.read_text(encoding="utf-8").split("\n")
        except OSError:
            continue
        base_file = _base_dir() / (zone.name + ".md")
        seen_file = _base_dir() / (zone.name + ".json")
        try:
            base = base_file.read_text(encoding="utf-8").split("\n")
        except OSError:
            base_file.parent.mkdir(parents=True, exist_ok=True)
            base_file.write_text("\n".join(current), encoding="utf-8")       # the first sight is what was delivered
            continue
        open_before = {l.rstrip() for l in base if l.startswith("- [ ] ")}
        ticked_before = {tl._reopened(l.rstrip()).rstrip() for l in base if l.startswith("- [x] ")}
        open_now = {l.rstrip() for l in current if l.startswith("- [ ] ")}
        ticks = {}
        for line in current:
            if line.startswith("- [x] "):
                before = tl._reopened(line.rstrip()).rstrip()
                if before in open_now:
                    continue
                # open in the delivered copy and ticked now; or a line the server added after it, ticked here
                if before in open_before or before not in ticked_before:
                    ticks[tl.key(before)] = before
        handled = set((_read_json(seen_file) or {}).get("keys") or [])
        for key in sorted(handled - set(ticks)):
            handled.discard(key)
            taken = untick_for(ws, zone, key, now)           # ticked here, then reopened by hand before the server applied it
            made += taken
        for key, before in sorted(ticks.items()):
            if key in handled:
                continue
            make(zone, {"verb": "todo-done", "zone": zone.name, "file": "Todo.md", "key": key}, before[6:].strip(), machine_name(ws),
                 after_last(zone, key, now))
            handled.add(key)
            made += 1
        waiting = {k for k in ticks if k in pending_marks(ws, zone.name)}
        if not ticks or not waiting:                  # nothing ticked, or the server has caught up: this is the new delivery
            base_file.write_text("\n".join(current), encoding="utf-8")
            handled = set()
        _write_json(seen_file, {"keys": sorted(handled)})
    return made


# --------------------------------------------------------------------------- command line


def summary(done: dict) -> str:
    """The one line `replay` prints: what it applied, and what it kept back and why."""
    line = "Applied %(applied)d, held %(held)d, skipped %(skipped)d." % done
    if done.get("retry"):
        line += " %d wait for the next run." % done["retry"]
    if done.get("journal"):
        line += " The journal could not be read, so nothing was applied; the queued requests are kept."
    if done.get("gone"):
        line += " %d not applied again, because their record is gone: %s." % (len(done["gone"]), ", ".join(done["gone"]))
    return line


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="The outbox of a roaming machine's Todo actions.")
    ap.add_argument("command", choices=("replay", "list"))
    ap.add_argument("--workspace")
    args = ap.parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve() if args.workspace else HERE.parent.parent
    if args.command == "list":
        for zone in zones(ws):
            for path, env, held in _envelopes(zone):
                req = (env or {}).get("request") or {}
                print("%s: %s %s%s" % (zone.name, "held" if held else "waits", req.get("verb", "?"),
                                       ": " + (env or {}).get("held", "") if held else ""))
        return 0
    if role(ws) == "roaming":
        print("This machine only receives the workspace; the server applies the outbox.", file=sys.stderr)
        return 1
    done = replay(ws)
    print(summary(done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
