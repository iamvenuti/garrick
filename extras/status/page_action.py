#!/usr/bin/env python3
"""page_action.py: what the status page's action buttons do. A preview feature,
`page-actions`, off until the workspace switches it on.

    echo '{"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "…"}' | \\
        python3 page_action.py --workspace ~/Garrick

Garrick.app, or the Obsidian plugin beside this file, runs it when a button
on the page asks; nothing else can, because a browser has no way to reach it.
The ask preview (ask.py) runs what it proposes through act(), the same check.
Each verb changes one thing, and the ones that change a note commit it in the
zone's repository, as the skills would:

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
                own wrapper, lock and log; it changes no note itself. A job
                whose lock (job.py's) is held is already running, and refused
    settings    which ways to open a thread the page offers, and which one
                clicking a thread's name runs: {"launchers": ["note", "cmux"],
                "default": "cmux"}, written to System/generated/status-settings.json,
                so the app and Obsidian agree. It commits nothing

A line is named by its zone, its file and the hash of its exact text, so a page
built before the line last changed finds nothing and is refused, rather than
ticking another line. A date changes a line's text, and so its key, and the
page learns the new key only when it rebuilds; until then a second click on the
same row still carries the old key, so the handler keeps, for an hour, which
old key became which new one (todo-rekeys.json in the jobs folder) and follows
it. Every path must be a live note inside a zone. When the zone's wall check
refuses the commit, the file is put back as it was.

Every request, done or refused, is one line in page-actions.log in the jobs
folder (agent.py's jobs_dir(): GARRICK_JOBS_DIR, or ~/Library/Logs/garrick-jobs
on a Mac): the time, the verb, the fields it names and what came of it. Only
the fields a verb reads are written, the text of a new line cut short, so
nothing else a request carries reaches the log. The host rebuilds the page
after every request. The reply is one line of JSON: {"ok": true|false,
"say": "…"}. Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
VERBS = ("todo-done", "todo-undo", "todo-date", "todo-add", "park", "wake", "run", "settings")
SKIP = {"archive", "_template", ".git", ".obsidian", ".trash"}
# The ways to open a thread Settings lists: the note's own link, then status.py's LAUNCHERS.
LAUNCHERS = ("note", "finder", "cmux", "codex", "claude")
# What the audit log may name of a request, and how much of a new line's text.
LOGGED = ("zone", "file", "key", "date", "target", "job", "launchers", "default")
LOGGED_TEXT = 60
LOGGED_SAY = 160
REKEY_HOURS = 1
# A lock with no record of its own, left by an older job.py, holds for the
# default limit job.py gives it: twice the watchdog's 1500 s, the sign-in
# retry's 300 s and its 600 s of slack.
LOCK_HOLD = 2 * 1500 + 300 + 600
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


class Refused(Exception):
    pass


def jobs_dir() -> Path:
    """The jobs folder, as agent.py's jobs_dir() finds it: logs, locks and
    heartbeats, outside the workspace, so nothing here is committed."""
    set_to = os.environ.get("GARRICK_JOBS_DIR")
    if set_to:
        return Path(set_to).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "garrick-jobs"
    return Path.home() / ".local" / "state" / "garrick-jobs"


def audit(req, ok: bool, say: str, via: str = "") -> None:
    """One line in page-actions.log for every request: what it asked and what
    came of it. A log that cannot be written never stops the action."""
    req = req if isinstance(req, dict) else {}
    parts = [str(req.get("verb", "?"))[:20]]
    for k in LOGGED:
        if k in req:
            parts.append("%s=%s" % (k, json.dumps(req[k], ensure_ascii=False)[:120]))
    text = req.get("text")
    if isinstance(text, str):
        parts.append("text=%s" % json.dumps(text[:LOGGED_TEXT] + ("…" if len(text) > LOGGED_TEXT else ""), ensure_ascii=False))
    said = say.replace("\n", " ")
    said = said[:LOGGED_SAY] + ("…" if len(said) > LOGGED_SAY else "")
    line = "%s  %s  ->  %s: %s%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(parts), "ok" if ok else "refused",
                                      said, "  (%s)" % via if via else "")
    try:
        folder = jobs_dir()
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "page-actions.log").open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def rekeys(zone: str, rel: str, update=None) -> dict:
    """Old key -> new key for the lines of one note re-dated in the last hour.
    `update` is (old, new): a line re-dated again moves every key that led to
    it on to the newest, and one dated back to where it started drops out."""
    path = jobs_dir() / "todo-rekeys.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    cut = time.time() - REKEY_HOURS * 3600
    data = {k: v for k, v in data.items() if isinstance(v, list) and len(v) == 2 and isinstance(v[1], (int, float)) and v[1] >= cut}
    scope = "%s/%s|" % (zone, rel)
    if update:
        old, new = scope + update[0], update[1]
        now = time.time()
        data = {k: ([new, now] if k.startswith(scope) and v[0] == update[0] else v) for k, v in data.items()}
        data[old] = [new, now]
        data = {k: v for k, v in data.items() if k != scope + v[0]}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".todo-rekeys-", dir=str(path.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, str(path))
        except OSError:
            pass
    return {k[len(scope):]: v[0] for k, v in data.items() if k.startswith(scope)}


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
    rel = note.relative_to(zone).as_posix()
    when = None
    if req["verb"] == "todo-date":
        raw = req.get("date")
        try:
            when = None if raw == "-" else dt.date.fromisoformat(raw or "")
        except (TypeError, ValueError):
            raise Refused("not a date: %r" % raw)
    before = note.read_bytes()
    try:
        try:
            said, message = todo_edit(tl, zone, rel, key, req["verb"], when)
        except tl.NotFound:
            newer = rekeys(zone.name, rel).get(key)      # a second click before the page rebuilt
            if not newer:
                raise
            said, message = todo_edit(tl, zone, rel, newer, req["verb"], when)
    except tl.NotFound:
        raise Refused("that line has changed since the page was built; it rebuilds now, try again")
    commit(zone, note, before, message[:200])
    return said


def todo_edit(tl, zone: Path, rel: str, key: str, verb: str, when):
    """One edit to the line with this key: what to say, and the commit message."""
    if verb == "todo-done":
        text = tl.done(str(zone), rel, key)
        return "Done: " + text, "%s: done, %s" % (zone.name, text)
    if verb == "todo-undo":
        text = tl.undo(str(zone), rel, key)
        return "Reopened: " + text, "%s: reopened, %s" % (zone.name, text)
    text, moved, new = tl.set_date(str(zone), rel, key, when)
    rekeys(zone.name, rel, (key, new))
    what = "%s %d %s" % (when.strftime("%a"), when.day, when.strftime("%b")) if when else "no date"
    return "%s: %s%s" % (text, what, ", moved to " + moved if moved else ""), "%s: %s, %s" % (zone.name, what, text)


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


def lock_held(name: str, now: float = None) -> bool:
    """Whether job.py's lock for this job stands: `<name>.lock`, a folder in
    the jobs folder, whose `until` file says when it goes stale. A lock past
    that belongs to a run that died, and job.py's next run takes it over."""
    lock = jobs_dir() / ("%s.lock" % name)
    if not lock.is_dir():
        return False
    now = time.time() if now is None else now
    try:
        until = float((lock / "until").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        try:
            until = lock.stat().st_mtime + LOCK_HOLD
        except OSError:
            return False
    return now <= until


def run_job(req: dict, folder: Path = None) -> str:
    name = req.get("job")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise Refused("not a job name")
    label = job_label(name, folder)
    if label is None:
        raise Refused("no scheduled job called %s" % name)
    if lock_held(name):
        raise Refused("%s is already running" % name)
    if not kickstart(label):
        raise Refused("launchd would not start %s; is it loaded?" % name)
    return "%s is running now" % name


def save_settings(ws: Path, req: dict) -> str:
    """Settings › Opening a thread, kept in one file so every viewer of the page
    agrees: {"launchers": {"note": true, "cmux": false, …}, "default": "note"}.
    Every known way is written, on or off; status.py reads the file when it
    builds the page. A way it does not list is on, as on the page."""
    on, default = req.get("launchers"), req.get("default", "note")
    if not isinstance(on, list) or not all(isinstance(k, str) for k in on) or len(set(on)) != len(on):
        raise Refused("not a list of ways to open a thread")
    unknown = [k for k in on if k not in LAUNCHERS]
    if unknown:
        raise Refused("no way to open a thread called %s" % ", ".join(repr(k) for k in unknown))
    if default not in LAUNCHERS:
        raise Refused("no way to open a thread called %r" % (default,))
    if default != "note" and default not in on:
        raise Refused("the default must be one of the ways switched on")
    path = ws / "System" / "generated" / "status-settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"launchers": {k: k in on for k in LAUNCHERS}, "default": default}
    fd, tmp = tempfile.mkstemp(prefix=".status-settings-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=1) + "\n")
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return "Settings saved"


def act(ws: Path, req, today=None) -> str:
    if not isinstance(req, dict) or req.get("verb") not in VERBS:
        raise Refused("unknown action")
    if req["verb"] == "run":
        return run_job(req)
    if req["verb"] == "settings":
        return save_settings(ws, req)
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
    req = None
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
    audit(req, out["ok"], out["say"])
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
