#!/usr/bin/env python3
"""page_action.py: what the status page's action buttons do. A preview feature,
`page-actions`, off until the workspace switches it on.

    echo '{"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "…"}' | \\
        python3 page_action.py --workspace ~/Garrick

Garrick.app runs it when a button on the page asks; nothing else can,
because a browser has no way to reach it. Seven verbs, each changing one thing
and committing it in the zone's repository, as the skills would:

    todo-done   tick a Todo line, with Obsidian Tasks' ✅ date
    todo-undo   reopen a line ticked from the page
    todo-date   set or clear its date: 📅, or ⏳ on a #waiting line; "-" clears
    todo-add    a new line in the zone's Todo.md, from the Todo list's + button:
                {"zone", "text", "target": "-", "Project" or "Project/Thread",
                "date": an ISO date or "-"}; the Inbox, or with a date where a
                dated line goes; a line already there is refused
    park        a thread note's status to parked, with a dated entry
    wake        and back to active
    run         start a scheduled job now, through launchd, so it keeps its
                own wrapper, lock and log; it changes no note itself

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
VERBS = ("todo-done", "todo-undo", "todo-date", "todo-add", "park", "wake", "run")
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


def todo_add(ws: Path, req: dict) -> str:
    """A new line in the zone's Todo.md. The target is checked against the
    folders: a project with its hub, or a thread with its note. The link names
    the thread, or the note's path when another note in the zone has its name."""
    tl = todo_lines()
    zone = zone_dir(ws, req.get("zone"))
    note = zone / "Todo.md"
    if not note.is_file():
        raise Refused("%s has no Todo.md" % zone.name)
    text, target, raw = req.get("text"), req.get("target") or "-", req.get("date") or "-"
    if not isinstance(text, str) or len(text) > 1000 or not isinstance(target, str) or not isinstance(raw, str):
        raise Refused("not a line to add")
    label = None
    if target != "-":
        parts = target.split("/")
        if len(parts) not in (1, 2) or any(not p or p.startswith((".", "_")) or p in ("..", "Threads") for p in parts):
            raise Refused("not a project or thread: %r" % target)
        found = zone / parts[0] / (parts[0] + ".md") if len(parts) == 1 else zone / parts[0] / "Threads" / parts[1] / (parts[1] + ".md")
        if not found.is_file():
            raise Refused("no %s called %r in %s" % ("project" if len(parts) == 1 else "thread", target, zone.name))
        name = parts[-1]
        same = sum(1 for n in tl.notes(str(zone)) if Path(n).stem.lower() == name.lower())
        label = name if same <= 1 else "%s|%s" % (found.relative_to(zone).with_suffix("").as_posix(), name)
    try:
        when = None if raw == "-" else dt.date.fromisoformat(raw)
    except ValueError:
        raise Refused("not a date: %r" % raw)
    before = note.read_bytes()
    try:
        line, section, _ = tl.add(str(zone), text, label, when)
    except ValueError as e:
        raise Refused(str(e))
    except tl.NotFound:
        raise Refused("%s's Todo.md has no Inbox section" % zone.name)
    said = tl.parse(line)["text"]
    commit(zone, note, before, ("%s: added to %s, %s" % (zone.name, section, said))[:200])
    return "Added to %s: %s" % (section, said)


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


def job_label(name, folder: Path = None):
    """The launchd label of the job the jobs extra runs as `job.py <name>`, or None."""
    import plistlib
    folder = folder or Path.home() / "Library" / "LaunchAgents"
    for plist in sorted(folder.glob("*.plist")) if folder.is_dir() else []:
        try:
            p = plistlib.loads(plist.read_bytes())
            args = [str(a) for a in p.get("ProgramArguments", [])]
        except Exception:
            continue
        at = next((i for i, a in enumerate(args) if a.endswith("job.py")), None)
        if at is not None and at + 1 < len(args) and args[at + 1] == name and isinstance(p.get("Label"), str):
            return p["Label"]
    return None


def kickstart(label: str) -> bool:
    import os
    done = subprocess.run(["launchctl", "kickstart", "gui/%d/%s" % (os.getuid(), label)], capture_output=True, text=True)
    return done.returncode == 0


def run_job(req: dict, folder: Path = None) -> str:
    name = req.get("job")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise Refused("not a job name")
    label = job_label(name, folder)
    if label is None:
        raise Refused("no scheduled job called %s" % name)
    if not kickstart(label):
        raise Refused("launchd would not start %s; is it loaded?" % name)
    return "%s is running now" % name


# ---- cmux tabs: open, close, startup, shutdown -------------------------------
# Only with the cmux extra (extras/cmux, beside this folder) and cmux installed.
# Each runs that extra's desk.py, which reads cmux's socket password itself.
#   {"verb": "open", "zone", "project", "thread"?}  a tab in that folder, started on "open …"
#   {"verb": "close", "zone", "project", "thread"?} its tabs; refused while one is mid-turn
#   {"verb": "startup"}    start or restore cmux and resume its tabs, detached
#   {"verb": "shutdown"}   the dry run here, so a busy tab is refused while the page
#                          watches; the wraps and the quit go on detached
CMUX_VERBS = ("open", "close", "startup", "shutdown")
CMUX_EXTRA = Path(__file__).resolve().parent.parent / "cmux"


def cmux_desk() -> Path:
    desk = CMUX_EXTRA / "desk.py"
    if not (desk.is_file() and (CMUX_EXTRA / "cmuxlib.py").is_file()):
        raise Refused("tabs need the cmux extra, extras/cmux, beside the status page")
    spec = importlib.util.spec_from_file_location("garrick_cmuxlib", str(CMUX_EXTRA / "cmuxlib.py"))
    cx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cx)
    if not cx.installed():
        raise Refused("cmux is not installed here")
    return desk


def run_desk(ws: Path, *args, timeout: int = 60) -> str:
    try:
        done = subprocess.run([sys.executable, str(cmux_desk()), "--workspace", str(ws)] + list(args),
                              capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise Refused("cmux did not answer in time")
    out = (done.stdout if done.returncode == 0 else done.stderr or done.stdout).strip().splitlines()
    if done.returncode:
        raise Refused(out[-1].replace("desk: ", "", 1) if out else "desk failed")
    return "\n".join(out)


def desk_detached(ws: Path, *args) -> None:
    """desk in a session of its own, so it outlives this request; its notifications report the outcome."""
    subprocess.Popen([sys.executable, str(cmux_desk()), "--workspace", str(ws)] + list(args),
                     start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def cmux_folder(ws: Path, req: dict) -> tuple:
    """The project's or thread's folder, and the name to say for it."""
    zone = zone_dir(ws, req.get("zone"))
    names = [req.get("project")] + ([req["thread"]] if req.get("thread") not in (None, "", "-") else [])
    if any(not isinstance(n, str) or not n or n.startswith((".", "_")) or "/" in n or n in ("..", "Threads")
           for n in names):
        raise Refused("not a project or thread")
    folder = zone / names[0] if len(names) == 1 else zone / names[0] / "Threads" / names[1]
    if not (folder / (folder.name + ".md")).is_file():
        raise Refused("no %s called %s in %s" % ("project" if len(names) == 1 else "thread", names[-1], zone.name))
    return folder, ", ".join(names)


def cmux_act(ws: Path, req: dict) -> str:
    verb = req["verb"]
    if verb == "open":
        folder, name = cmux_folder(ws, req)
        said = run_desk(ws, "open", str(folder), "--prompt", "open " + name, "--front").splitlines()
        return said[0][:1].upper() + said[0][1:] if said else "Opened %s in cmux" % name
    if verb == "close":
        folder, name = cmux_folder(ws, req)
        run_desk(ws, "close", "--folder", str(folder), "--yes")
        return "Closed the tabs in %s" % name
    if verb == "startup":
        cmux_desk()
        desk_detached(ws, "start", "--notify")
        return "Starting cmux; a notification follows when every tab is back"
    m = re.search(r"(\d+) used today", run_desk(ws, "shutdown"))
    desk_detached(ws, "shutdown", "--yes")
    n = int(m.group(1)) if m else None
    return "Shutting down: %s, then cmux quits" % (
        "wrapping %d tab%s" % (n, "" if n == 1 else "s") if n is not None else "wrapping each tab used today")
# ---- end of cmux tabs ----------------------------------------------------------


def act(ws: Path, req, today=None) -> str:
    if isinstance(req, dict) and req.get("verb") in CMUX_VERBS:
        return cmux_act(ws, req)
    if not isinstance(req, dict) or req.get("verb") not in VERBS:
        raise Refused("unknown action")
    if req["verb"] == "run":
        return run_job(req)
    if req["verb"] in ("park", "wake"):
        return park(ws, req, today or dt.date.today())
    if req["verb"] == "todo-add":
        return todo_add(ws, req)
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
