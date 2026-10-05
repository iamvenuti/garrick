#!/usr/bin/env python3
"""page_action.py: what the status page's action buttons do. A preview feature,
`page-actions`, off until the workspace switches it on.

    echo '{"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "…"}' | \\
        python3 page_action.py --workspace ~/Garrick

Garrick's Status.app runs it when a button on the page asks; nothing else can,
because a browser has no way to reach it. Five verbs, each changing one thing
and committing it in the zone's repository, as the skills would:

    todo-done   tick a Todo line, with Obsidian Tasks' ✅ date
    todo-undo   reopen a line ticked from the page
    todo-date   set or clear its date: 📅, or ⏳ on a #waiting line; "-" clears
    park        a thread note's status to parked, with a dated entry
    wake        and back to active

A line is named by its zone, its file and the hash of its exact text, so a page
built before the line last changed finds nothing and is refused, rather than
ticking another line. Every path must be a live note inside a zone. When the
zone's wall check refuses the commit, the file is put back as it was. The reply
is one line of JSON: {"ok": true|false, "say": "…"}. Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
VERBS = ("todo-done", "todo-undo", "todo-date", "park", "wake")
SKIP = {"archive", "_template", ".git", ".obsidian", ".trash"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


class Refused(Exception):
    pass


def todo_lines():
    spec = importlib.util.spec_from_file_location("garrick_todo_lines", str(Path(__file__).with_name("todo_lines.py")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def zone_dir(ws: Path, zone) -> Path:
    if not isinstance(zone, str) or not re.fullmatch(r"[^/\\.][^/\\]*", zone) or zone.startswith("_"):
        raise Refused("not a zone")
    z = (ws / "Zones" / zone).resolve()
    if z.parent != (ws / "Zones").resolve() or not z.is_dir():
        raise Refused("no zone called %s" % zone)
    return z


def live_note(base: Path, rel) -> Path:
    """A Markdown note inside `base`, not in an archive, a template or git."""
    if not isinstance(rel, str) or not rel.endswith(".md"):
        raise Refused("not a note")
    p = (base / rel).resolve()
    if not p.is_file() or base.resolve() not in p.parents or SKIP & set(p.relative_to(base.resolve()).parts):
        raise Refused("that note is not a live note in the zone any more")
    return p


def commit(zone: Path, note: Path, before: bytes, message: str) -> None:
    """Commit the one file, or put it back as it was and say why."""
    rel = str(note.relative_to(zone))
    add = subprocess.run(["git", "-C", str(zone), "add", "--", rel], capture_output=True, text=True)
    done = add if add.returncode else subprocess.run(
        ["git", "-C", str(zone), "commit", "-q", "-m", message, "--", rel], capture_output=True, text=True)
    if done.returncode:
        note.write_bytes(before)
        subprocess.run(["git", "-C", str(zone), "reset", "-q", "--", rel], capture_output=True)
        why = (done.stderr or done.stdout).strip().splitlines()
        raise Refused("not committed, so nothing changed: %s" % (why[-1] if why else "git refused"))


def todo(ws: Path, req: dict) -> str:
    tl = todo_lines()
    zone = zone_dir(ws, req.get("zone"))
    note = live_note(zone, req.get("file"))
    key = req.get("key")
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{16}", key):
        raise Refused("not a task key")
    rel = str(note.relative_to(zone))
    before = note.read_bytes()
    try:
        if req["verb"] == "todo-done":
            text = tl.done(str(zone), rel, key)
            say, message = "Done: " + text, "%s: done, %s" % (zone.name, text)
        elif req["verb"] == "todo-undo":
            text = tl.undo(str(zone), rel, key)
            say, message = "Reopened: " + text, "%s: reopened, %s" % (zone.name, text)
        else:
            raw = req.get("date")
            try:
                when = None if raw == "-" else dt.date.fromisoformat(raw or "")
            except (TypeError, ValueError):
                raise Refused("not a date: %r" % raw)
            text, moved, _ = tl.set_date(str(zone), rel, key, when)
            what = "%s %d %s" % (when.strftime("%a"), when.day, when.strftime("%b")) if when else "no date"
            say = "%s: %s%s" % (text, what, ", moved to " + moved if moved else "")
            message = "%s: %s, %s" % (zone.name, what, text)
    except tl.NotFound:
        raise Refused("that line has changed since the page was built; it rebuilds now, try again")
    commit(zone, note, before, message[:200])
    return say


def park(ws: Path, req: dict, today: dt.date) -> str:
    """The threads skill's Park and Wake: the status, `updated:`, a dated entry, a commit."""
    zone = zone_dir(ws, req.get("zone"))
    note = live_note(zone, req.get("file"))
    parts = note.relative_to(zone).parts
    is_thread = len(parts) == 4 and parts[1] == "Threads" and parts[2] + ".md" == parts[3]
    is_hub = len(parts) == 2 and parts[0] + ".md" == parts[1] and not any((zone / parts[0] / "Threads").glob("*/*.md"))
    if not (is_thread or is_hub):
        raise Refused("only a thread note, or a single-thread project's hub, can be parked")
    status = "parked" if req["verb"] == "park" else "active"
    before = note.read_bytes()
    text = before.decode("utf-8")
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise Refused("the note has no frontmatter to set its status in")
    fm = m.group(1)
    if re.search(r"(?m)^status:\s*%s\s*$" % status, fm):
        return "%s is already %s" % (note.stem, status)
    fm = re.sub(r"(?m)^status:.*$", "status: " + status, fm) if re.search(r"(?m)^status:", fm) else fm + "\nstatus: " + status
    fm = re.sub(r"(?m)^updated:.*$", "updated: " + today.isoformat(), fm) if re.search(r"(?m)^updated:", fm) \
        else fm + "\nupdated: " + today.isoformat()
    body = text[m.end():]
    entry = "**%d %s %d.** %s" % (today.day, MONTHS[today.month - 1], today.year, "Parked." if status == "parked" else "Woken.")
    resume = body.find("### Resume here")
    rule = body.find("\n---\n", resume) if resume >= 0 else -1
    if rule >= 0:                                     # newest first, below the rule and its placeholder line
        at = rule + 5
        rest = body[at:]
        lead = re.match(r"\n*(?:<Dated entries[^\n]*>\n)?\n*", rest)
        at += lead.end()
        body = body[:at] + entry + "\n\n" + body[at:]
    note.write_text("---\n%s\n---\n%s" % (fm, body), encoding="utf-8")
    name = "%s, %s" % (parts[0], parts[2]) if is_thread else parts[0]
    commit(zone, note, before, "%s: %s" % (name, status if status == "parked" else "woken"))
    return "%s is %s" % (name, "parked" if status == "parked" else "awake again")


def act(ws: Path, req, today=None) -> str:
    if not isinstance(req, dict) or req.get("verb") not in VERBS:
        raise Refused("unknown action")
    if req["verb"] in ("park", "wake"):
        return park(ws, req, today or dt.date.today())
    return todo(ws, req)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Do what a status page button asks, reading one JSON request on stdin.")
    ap.add_argument("--workspace", required=True)
    args = ap.parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve()
    try:
        if not (ws / "System" / "rules.md").is_file() or not (ws / "Zones").is_dir():
            raise Refused("not a Garrick workspace")
        try:
            req = json.loads(sys.stdin.read())
        except ValueError:
            raise Refused("not a request")
        out = {"ok": True, "say": act(ws, req)}
    except Refused as e:
        out = {"ok": False, "say": str(e)}
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
