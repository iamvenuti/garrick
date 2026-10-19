#!/usr/bin/env python3
"""page_action.py: what the status page's action buttons do.

    echo '{"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "…"}' | \\
        python3 page_action.py --workspace ~/Garrick

Garrick.app, or the Obsidian plugin beside this file, runs it when a button
on the page asks; nothing else can, because a browser has no way to reach it.
The ask preview (ask.py) runs what it proposes through act(), the same check.
Each verb changes one thing, and the ones that change a note commit it in the
zone's repository, as the skills would:

    todo-done   tick a Todo line, with Obsidian Tasks' ✅ date; "keys" in place
                of "key" ticks several lines of one note at once, the batch the
                page sends for the ticks made within a few seconds of each
                other: one lock, one edit, one commit ("Work: done, 3
                actions"), and refused as a whole when one line has moved
    todo-undo   reopen a line ticked from the page, or several by "keys"
    todo-date   set or clear its date: 📅, or ⏳ on a #waiting line; "-" clears
    todo-add    a new line in the zone's Todo.md, from the Todo list's + button:
                {"zone", "text", "target": "-", "Project" or "Project/Thread",
                "date": an ISO date or "-"}; the Inbox, or with a date where a
                dated line goes; a line already there is refused
    park        a thread note's status to parked, with a dated entry:
                {"zone", "file"}, or by name {"zone", "project", "thread"?};
                with no thread, the project's hub, and all of it is parked.
                The edit is System/tools/scaffold.py's, as a new project's
                is; the commit is this file's, so a wall refusal puts the
                note back. A thread already parked is refused
    wake        and back to active
    run         start a scheduled job now, through launchd, so it keeps its
                own wrapper, lock and log; it changes no note itself. A job
                whose lock (job.py's) is held is already running, and refused
    new-project a project and its first thread, as "new project" by voice:
                {"zone", "name", "party", "thread"}; committed in the zone
    new-thread  a thread in a project: {"zone", "project", "name"}
    check-name  whether a new name would do, making nothing, for the form as
                it is typed: {"kind": "project", "thread" or "rename", and the
                fields of that verb}
    rename      a project or thread and every link to it in the zone:
                {"zone", "project", "thread"?, "to"}
    delete      without "confirm", what would go; with "confirm" naming it,
                gone in one commit: {"zone", "project", "thread"?, "confirm"?}
    undo        a rename or deletion, while it is the zone's last commit:
                {"zone", "commit"}
                These six run System/tools/scaffold.py and nothing else, so
                the page, the voice command and the script make the same
                folders, notes and commits.
    interrupt   a thread's place saved when something cuts in: {"zone", "project",
                "thread"} or {"zone", "file"}, with "where", "next", and "keep"
                and "by" if given; written into its Resume here block as a
                wrap would, committed, then pushed on the interruption stack.
                An unwrapped checkpoint under that block is rebased onto the
                block just written, so a hold does not leave it stale
    back        the top of the stack taken off, or the thread named taken out;
                the note is only read: the reply adds its "path" and its three
                lines, "where", "next" and "keep", and "checkpoint" where one
                is waiting. An empty stack says so and
                offers the most recent live thread, as "offer"
    stack       what is on it, top first, as "stack"; it changes nothing
    unstack     a thread, or all of a project, taken off it without reading
                it back: {"zone", "project", "thread"?}, for a wrap, park,
                finish or deletion done by the assistant. Park, rename and
                delete here keep the stack in step themselves
    settings    which ways to open a thread the page offers, and which one
                clicking a thread's name runs: {"launchers": ["note", "cmux"],
                "default": "cmux"}; each zone's colour and icon: {"zones":
                {"Work": {"color": "Teal", "icon": "briefcase"}}}; or both.
                Kept in System/garrick-settings.json, committed with the
                workspace, so the app, Obsidian and the cmux desk agree. A zone
                whose colour changed has its open cmux workspace recoloured,
                when the cmux extra and cmux are there. Settings ›
                Notifications: {"notifications": {...}}, checked and kept by
                System/tools/notifications.py, and with "test": "telegram"
                (or "mac", "command") a test sent on that channel once the
                rest is saved; the reply says whether it went. Telegram's
                Set up…: "token", the bot's token, kept in the keychain
                through notifications.py's store_token(), which hands it to
                `security` on its standard input; and "find-chat": true,
                the chat that last wrote to the bot found, kept, Telegram
                switched on and a test sent (set_up_chat()). The token is
                the one field no reply, log line or record holds: the audit
                log names only LOGGED, settings keeps no durable record, and
                a failure is said in words of this file's own.
                Settings › While you wait: {"while-you-wait": {...}},
                checked by System/tools/next_up.py. Settings › Home:
                {"home": "simple"} or "full", the page Garrick opens on
    answer      a Needs you question answered by one of its options (#175):
                {"zone", "file", "label"}; the work's Next action becomes
                what the option leads to, with a dated entry, the question
                says answered, and both are committed in one commit
    later       "Not now": {"zone", "file", "until"?}; the question put off
                to tomorrow, or to the day `until` names, and committed
    continue    a piece of work opened in Claude's desktop app, already
                oriented: {"zone", "file"}, its note. Its own record is
                committed, a headless `claude -p` asks where it stands, and
                that session opens with `claude --desktop --resume`, under
                a pseudo-terminal (handoff.py, beside this file)
    ask-desktop Ask something: {"prompt"}, asked the same way in the
                workspace's own folder; where the desktop app cannot open
                it, the answer comes back in the reply, as "answer"
    example     the example put away or brought back: {"do": "archive"}
                or "restore", through System/tools/example.py (#174)
    fix         a check finding Nurture has a mechanical fix for, fixed from
                the Threads card's `check` chip (#179): {"zone", "file"}, the
                note the finding names. System/tools/nurture.py's own `fix
                --yes`, scoped to that note and run as its nightly run is
                (GARRICK_HEADLESS=1), so it applies only the mechanical kind,
                commits in the zone and puts the note back when the wall
                check refuses; under the zone's lock

What a Todo verb says it did is the line's text without its Markdown links,
cut to SAID_TEXT characters: the link back to a meeting belongs in Todo.md,
not in a toast. A batch that saved says "Saved 3". A tick or untick the zone's
wall check refused ends on the rule's own sentence, operations.py's
WALL_REFUSAL, word for word, and says nothing of what the check found.

A line is named by its zone, its file and the hash of its exact text, so a page
built before the line last changed finds nothing and is refused, rather than
ticking another line. A date changes a line's text, and so its key, and the
page learns the new key only when it rebuilds; until then a second click on the
same row still carries the old key, so the handler keeps, for an hour, which
old key became which new one (todo-rekeys.json in the jobs folder) and follows
it. Every path must be a live note inside a zone. When the zone's wall check
refuses the commit, or is still running after COMMIT_TIMEOUT, the file is put
back as it was, unless it was edited meanwhile, in Obsidian say: then it is
left as it is, and the reply says so. A check stopped that way had found
nothing wrong yet, so the reply also says that a commit by hand, which waits
for it, goes through. A new project or thread stays made, unstaged.

Every click is its own process, so two quick clicks, or a click and an ask,
can run at once. Each takes a lock on the zone first (page-action-<zone>.lock
in the jobs folder) and holds it from reading the note to committing it; a
second request waits for the first. The rekey map has a lock of its own.

The cmux verbs need the cmux extra and cmux itself.

Every verb is declared in one table, System/tools/operations.py's DECLARED,
found as ops_lib() finds it: the fields a request may carry, which of them
say what it is, what it touches, whether it commits, whether retrying it is
safe, and what must still be true for it to run. Two things come of that
here. A field the verb does not declare is refused by name, rather than
ignored as it was before, so a request cannot carry something that widens
what the action touches; and park, wake and the three Todo verbs with a key
check their fingerprint first: the note's `status:` for park and wake, so a
second park of an already parked thread says so instead of writing another
dated entry, and the hash of the line's exact text for the Todo verbs, which
todo_lines keeps. Both refusals take their words from that module, so the
sentence read is the same whichever way the request arrived. Without it,
nothing is validated and park and wake say what they said before.

Park, wake and the four Todo verbs also leave a durable record, so a page
that was reloaded, or an app that was quit, can find the action again and
learn how it ended. System/tools/operations.py, found as ops_lib() finds it,
keeps it as one JSON line per state in operations.jsonl in the jobs folder:
queued, running (with the phase "checking" while the wall check runs), then
completed, or failed with an outcome of refused, crashed or unknown. The reply
to such a request then also carries "op", "state" and "outcome", and a
failure's "say" is the module's sentence for that outcome, so a refusal
never reads as saved. {"verb": "operations"} reads the open set back. A
request identical to one under way, or just saved, is answered from the
record instead of being done twice; one that repeats an action the record
holds, past that short window, is told what was done and when and asked
whether it is meant a second time ("again" in the reply names that action),
and only the same request sent with "confirm" naming it is done again.
perform() is that whole path, which the ask box takes too, so a request
typed into it is recognised as one clicked on the page is. Without the
module, or with a jobs folder that cannot be written, every reply is what it
was before: the record is best effort, as the audit log is, and stops
nothing. How long each of those waits is operations.py's clock.

Every request, done or refused, is one line in page-actions.log in the jobs
folder (agent.py's jobs_dir(): GARRICK_JOBS_DIR, or ~/Library/Logs/garrick-jobs
on a Mac): the time, the verb, the fields it names and what came of it. Only
the fields a verb reads are written, the text of a new line cut short, so
nothing else a request carries reaches the log. The host hands the request
and the reply to the page (window.GarrickActed), which moves a parked or woken
row at once, and rebuilds the page after every request. The reply is one line
of JSON: {"ok": true|false, "say": "…"}, and for back and stack what they
read. Standard library only.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

try:
    import fcntl
except ImportError:             # not on Windows, where the status app does not run
    fcntl = None

sys.dont_write_bytecode = True
VERBS = ("todo-done", "todo-undo", "todo-date", "todo-add", "park", "wake", "run", "settings",
         "new-project", "new-thread", "check-name", "rename", "delete", "undo",
         "interrupt", "back", "stack", "unstack", "answer", "later", "continue", "ask-desktop", "example", "fix")
SKIP = {"archive", "_template", ".git", ".obsidian", ".trash"}
# The ways to open a thread Settings lists: the note's own link, then status.py's LAUNCHERS.
LAUNCHERS = ("note", "finder", "cmux", "codex", "claude")
# What Settings › Zones offers: cmux's named colours and status.py's ZONE_ICONS.
ZONE_COLOURS = ("Red", "Crimson", "Orange", "Amber", "Olive", "Green", "Teal", "Aqua", "Blue", "Navy", "Indigo",
                "Purple", "Magenta", "Rose", "Brown", "Charcoal")
# Settings › Home: which the page opens on. Its words are status.py's HOMES too.
HOMES = ("simple", "full")
ZONE_ICONS = ("briefcase", "house", "flask", "rocket", "book", "globe", "heart", "star", "leaf", "wrench", "chart", "shield")
# What the audit log may name of a request, and how much of a new line's text.
LOGGED = ("zone", "file", "project", "thread", "folder", "key", "keys", "date", "target", "job", "launchers", "default", "zones",
          "name", "party", "kind", "to", "confirm", "commit", "test", "find-chat", "home", "label", "until",
          "do")       # never "token"
LOGGED_TEXT = 60
LOGGED_SAY = 160
# What a Todo verb says it did: the line's text, no longer than this, and
# without its Markdown links (#107). The most lines one batch may name.
SAID_TEXT = 60
KEYS_MAX = 50
MDLINK = re.compile(r"!?\[([^\]]*)\]\([^)\s]*\)")
WIKILINK = re.compile(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]")
# One line of what the zone's wall check prints when it refuses a commit:
# check.py's report_staged(), as the pre-commit hook runs it.
WALL_LINE = re.compile(r"^Commit refused: .+\. Take it out and commit again\b")
REKEY_HOURS = 1
# Seconds: how long one git command may take, then a commit's whole share
# (add, commit and its hooks), then how long a request waits for another on
# the same zone. A commit runs the zone's wall check, which on a large
# workspace reads every meeting and project file the first time (see
# check.py's NoteCache): a minute or more while another job has the disk.
# The Obsidian plugin gives a request longer than all of them together. The
# first two are operations.py's clock, read below once ops_lib() is defined.
LOCK_WAIT = 45
# A lock with no record of its own, left by an older job.py, holds for the
# default limit job.py gives it: twice the watchdog's 1500 s, the sign-in
# retry's 300 s and its 600 s of slack.
LOCK_HOLD = 2 * 1500 + 300 + 600
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


# The one verb that only reads: the journal's open set (operations.py). It is
# not in VERBS: without the module it is an unknown action, as it always was.
JOURNAL_VERB = "operations"
HERE = Path(__file__).resolve().parent
_OPS_LIBS: dict = {}
# The action in hand, for the two places that know a phase: when the zone's lock
# is had, and when the wall check starts. None for anything without a record.
CURRENT = None


class Refused(Exception):
    pass


def ops_lib(ws: Optional[Path] = None):
    """The first System/tools/operations.py that loads and speaks the API this
    file expects, or None: the workspace's own copy first, then the one beside
    this folder (an extra sits in System/, a step from System/tools/), then a
    Garrick clone's template/, which is what the tests run against."""
    key = None if ws is None else Path(ws)
    if key not in _OPS_LIBS:
        found = None
        places = ([Path(ws) / "System" / "tools" / "operations.py"] if ws is not None else []) + [
            HERE.parent / "tools" / "operations.py", HERE.parent.parent / "template" / "System" / "tools" / "operations.py"]
        for src in places:
            if not src.is_file():
                continue
            try:
                spec = importlib.util.spec_from_file_location("garrick_operations", str(src))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                continue
            if getattr(mod, "API", None) == 1 and callable(getattr(mod, "start", None)):
                found = mod
                break
        _OPS_LIBS[key] = found
    return _OPS_LIBS[key]


# operations.py's clock (#137): how long a commit and a git command may take,
# every client's wait derived from them, and how long the record recognises a
# request sent again, in one place. Without operations.py, or with one older
# than its clock, the numbers 0.31.0 used, frozen here: change the clock, not
# these.
BEFORE_CLOCK = {"GIT_TIMEOUT": 60, "COMMIT_TIMEOUT": 300, "TURN_TIMEOUT": 60, "ASK_WAIT": 480}


def clock(name: str):
    """One of operations.py's clock, by name, as ask.py takes its waits too."""
    value = getattr(ops_lib(), name, None)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else BEFORE_CLOCK[name]


GIT_TIMEOUT = clock("GIT_TIMEOUT")
COMMIT_TIMEOUT = clock("COMMIT_TIMEOUT")


def refuse_undeclared(ws: Path, req: dict) -> None:
    """Closed validation, from the one table (operations.py): a field the verb
    does not declare is refused by name rather than ignored, so a request
    cannot carry something that widens what the action touches. Without that
    module nothing is checked here, which is what every release before it did."""
    ops = ops_lib(ws)
    why = ops.validate(req["verb"], req) if ops is not None and callable(getattr(ops, "validate", None)) else None
    if why:
        raise Refused(why)


def stale_why(ws: Path, verb: str, req: dict, found) -> Optional[str]:
    """What operations.py's precheck makes of the fingerprint read from the
    world now: why the request no longer means what it did, or None to carry
    on. Without the module, the words this file used before it for a line
    that has moved, and nothing for park and wake, whose own handler says
    when there is nothing left to do."""
    ops = ops_lib(ws)
    if ops is not None and callable(getattr(ops, "stale", None)):
        try:
            return ops.stale(verb, req, found)
        except Exception:               # the table is best effort, as the record is
            pass
    if verb.startswith("todo-") and verb != "todo-add" and not found:
        return "that line has changed since the page was built; it rebuilds now, try again"
    return None


def note_event(event: str, *args) -> None:
    """Tell the action in hand where it has got to. A record that cannot be
    written never stops the action."""
    run = CURRENT
    if run is None:
        return
    try:
        getattr(run, event)(*args)
    except Exception:
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


def flag_on(ws: Path, name: str) -> bool:
    """A preview feature switched on in System/garrick-flags.json, read as
    status.py's preview_flags() reads it: only a JSON true counts."""
    try:
        data = json.loads((ws / "System" / "garrick-flags.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get(name) is True


@contextlib.contextmanager
def held(name: str, wait: float = None, strict: bool = True, busy: str = "another action is still running"):
    """An exclusive lock on `name` in the jobs folder for the length of the
    block, waiting up to `wait` seconds for another process to let it go.
    Strict, a lock that cannot be had is refused, saying `busy`; otherwise
    the block runs without it."""
    wait = LOCK_WAIT if wait is None else wait
    if fcntl is None:
        yield
        return
    try:
        folder = jobs_dir()
        folder.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(folder / name), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as e:
        if strict:
            raise Refused("cannot take the lock in %s: %s" % (jobs_dir(), e.strerror or e))
        yield
        return
    try:
        deadline = time.time() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= deadline:
                    if strict:
                        raise Refused("%s; try again in a moment" % busy)
                    break
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)                # and with it the lock


@contextlib.contextmanager
def zone_lock(zone: Path):
    """One request at a time per zone, from reading a note to committing it."""
    with held("page-action-%s.lock" % zone.name, busy="another action in %s is still running" % zone.name):
        note_event("running")           # queued until the lock is had
        yield


def audit(req, ok: bool, say: str, via: str = "") -> None:
    """One line in page-actions.log for every request: what it asked and what
    came of it. A log that cannot be written never stops the action."""
    req = req if isinstance(req, dict) else {}
    parts = [str(req.get("verb", "?"))[:20]]
    for k in LOGGED:
        if k in req:
            parts.append("%s=%s" % (k, json.dumps(req[k], ensure_ascii=False)[:120]))
    for k in ("text", "prompt"):
        text = req.get(k)
        if isinstance(text, str):
            parts.append("%s=%s" % (k, json.dumps(text[:LOGGED_TEXT] + ("…" if len(text) > LOGGED_TEXT else ""), ensure_ascii=False)))
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
    scope = "%s/%s|" % (zone, rel)
    if update:
        with held("todo-rekeys.lock", wait=10, strict=False):    # one zone's update never loses another's
            data = recent_rekeys(path)
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
    else:
        data = recent_rekeys(path)
    return {k[len(scope):]: v[0] for k, v in data.items() if k.startswith(scope)}


def recent_rekeys(path: Path) -> dict:
    """The rekey map as saved, less what is older than the hour."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    cut = time.time() - REKEY_HOURS * 3600
    return {k: v for k, v in data.items() if isinstance(v, list) and len(v) == 2 and isinstance(v[1], (int, float)) and v[1] >= cut}


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


def git(zone: Path, *args, timeout: float = None):
    """One git command in the zone: (exit code, what it said). It runs in a
    process group of its own, so a hook that hangs, or a signing key waiting
    for its passphrase, is stopped with it when the time is up: politely
    first, so git takes away its own index.lock. Past the time, the code is None."""
    timeout = GIT_TIMEOUT if timeout is None else timeout
    try:
        p = subprocess.Popen(["git", "-C", str(zone)] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as e:
        return 127, "git did not run: %s" % (e.strerror or e)
    try:
        out, err = p.communicate(timeout=max(1.0, timeout))
    except subprocess.TimeoutExpired:
        for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, None)):
            try:
                os.killpg(p.pid, sig)
            except OSError:
                pass
            try:
                p.communicate(timeout=grace)
                break
            except subprocess.TimeoutExpired:
                continue
        return None, "git took longer than %d s and was stopped" % round(timeout)
    return p.returncode, (err or out or "")


def how_long(seconds: float) -> str:
    return "%d minutes" % round(seconds / 60) if seconds >= 120 else "%d s" % round(seconds)


def committing(zone: Path, rel: str, message: str) -> tuple:
    """Add and commit `rel` within COMMIT_TIMEOUT: (exit code, why not). The
    code is None when the commit was stopped while its hooks ran: the wall
    check had found nothing wrong yet."""
    deadline = time.time() + COMMIT_TIMEOUT
    code, said = git(zone, "add", "--", rel)
    if code == 0:
        note_event("phase", "checking")         # the wall check runs inside git commit
        code, said = git(zone, "commit", "-q", "-m", message, "--", rel, timeout=deadline - time.time())
        if code is None:
            return None, "the wall check was still running after %s and was stopped" % how_long(COMMIT_TIMEOUT)
    if code != 0:
        why = said.strip().splitlines() if code is not None else [said]
        return code or 1, why[-1] if why else "git refused"
    return 0, ""


def commit(zone: Path, note: Path, before: bytes, message: str, wall: Optional[str] = None) -> None:
    """Commit the one file, or put it back as it was and say why. Put back
    only if it still holds what this request wrote: an edit made meanwhile,
    in Obsidian say, is left alone. With `wall`, the sentence a refusal by
    the zone's wall check ends on, in place of what the check printed."""
    rel = str(note.relative_to(zone))
    mine = note.read_bytes()
    code, why = committing(zone, rel, message)
    if code != 0:
        try:
            ours = note.read_bytes() == mine
        except OSError:
            ours = False
        if ours:
            note.write_bytes(before)
        git(zone, "reset", "-q", "--", rel, timeout=10)
        if code is None and ours:
            raise Refused("not committed: %s, so the note was put back as it was. Make the change again and commit "
                          "it by hand: that commit waits for the check and goes through" % why)
        if code is None:
            raise Refused("not committed: %s. The note was edited meanwhile, so it was left as it is, uncommitted; "
                          "commit it by hand: that commit waits for the check and goes through" % why)
        if not ours:
            raise Refused("not committed: %s. The note was edited meanwhile, so it was left as it is" % why)
        if wall and WALL_LINE.match(why):
            raise Refused(wall)
        raise Refused("not committed, so nothing changed: %s" % why)


def said_text(text: str) -> str:
    """A line's text as a reply says it: Markdown links down to their words,
    a trailing `· ` left by a link that was the source, and no longer than
    SAID_TEXT characters."""
    text = WIKILINK.sub(lambda m: m.group(2) or m.group(1).split("#", 1)[0].rsplit("/", 1)[-1], text or "")
    text = re.sub(r"\s*·\s*" + MDLINK.pattern + r"\s*$", "", text)       # the source link at the end: dropped whole
    text = MDLINK.sub(lambda m: m.group(1), text)
    text = re.sub(r"\s+", " ", text).strip().rstrip("·").strip()
    return text if len(text) <= SAID_TEXT else text[:SAID_TEXT - 1].rstrip() + "…"


def task_keys(req: dict) -> list:
    """The lines a Todo request names: its one `key`, or a tick's or an
    untick's `keys`, each once, in the order given."""
    if "keys" in req:
        keys = req.get("keys")
        if req["verb"] not in ("todo-done", "todo-undo") or "key" in req or not isinstance(keys, list) \
                or not 1 <= len(keys) <= KEYS_MAX:
            raise Refused("not a list of task keys")
    else:
        keys = [req.get("key")]
    if not all(isinstance(k, str) and re.fullmatch(r"[0-9a-f]{16}", k) for k in keys):
        raise Refused("not a task key")
    return list(dict.fromkeys(keys))


def todo(ws: Path, req: dict) -> str:
    """A Todo verb with a key, or a batch of ticks or unticks with `keys`: one
    lock, one edit, one commit. A batch is refused as a whole, since it is one
    commit: a line that has moved refuses it before anything is written."""
    tl = todo_lines()
    zone = zone_dir(ws, req.get("zone"))
    note = live_note(zone, req.get("file"))
    keys = task_keys(req)
    rel = note.relative_to(zone).as_posix()
    when = None
    if req["verb"] == "todo-date":
        raw = req.get("date")
        try:
            when = None if raw == "-" else dt.date.fromisoformat(raw or "")
        except (TypeError, ValueError):
            raise Refused("not a date: %r" % raw)
    with zone_lock(zone):
        before = note.read_bytes()
        found = [live_key(tl, zone, rel, key, req["verb"]) for key in keys]
        why = stale_why(ws, req["verb"], req, all(found))
        if why:
            raise Refused(why)
        said, messages = [], []
        try:
            for key in found:
                one, message = todo_edit(tl, zone, rel, key, req["verb"], when)
                said.append(one)
                messages.append(message)
        except tl.NotFound:             # a line went between the precheck and the edit
            note.write_bytes(before)
            raise Refused(stale_why(ws, req["verb"], req, None) or "that line has changed since the page was built")
        if len(messages) == 1:
            message = messages[0]
        else:
            message = "%s: %s, %d actions" % (zone.name, "done" if req["verb"] == "todo-done" else "reopened", len(messages))
        wall = wall_refusal(ws) if req["verb"] in ("todo-done", "todo-undo") else None
        commit(zone, note, before, message[:200], wall=wall)
    return said[0] if len(said) == 1 else "Saved %d" % len(said)


def wall_refusal(ws: Path) -> Optional[str]:
    """The rule's sentence for a wall that held something back, as
    operations.py quotes it; None without that module, or with one older
    than #107, and the refusal is then worded as it was before."""
    said = getattr(ops_lib(ws), "WALL_REFUSAL", None)
    return said if isinstance(said, str) and said else None


def live_key(tl, zone: Path, rel: str, key: str, verb: str) -> Optional[str]:
    """operations.py's `line` precheck, answered by the file itself: the key
    of the line this request still points at, or None when no live line has
    it. Where a date has changed a line since the page was built, the rekey
    map says which key that one became and the request follows it. The hash
    is todo_lines', here as everywhere: nothing computes a second one."""
    reopen = verb == "todo-undo"
    found = tl.live_key(str(zone), rel, key, reopen)
    if found is None:
        newer = rekeys(zone.name, rel).get(key)         # a second click before the page rebuilt
        found = tl.live_key(str(zone), rel, newer, reopen) if newer else None
    return found


def todo_edit(tl, zone: Path, rel: str, key: str, verb: str, when):
    """One edit to the line with this key: what to say, and the commit message.
    What it says is the line's text as said_text() cuts it; the commit keeps it whole."""
    if verb == "todo-done":
        text = tl.done(str(zone), rel, key)
        return "Done: " + said_text(text), "%s: done, %s" % (zone.name, text)
    if verb == "todo-undo":
        text = tl.undo(str(zone), rel, key)
        return "Reopened: " + said_text(text), "%s: reopened, %s" % (zone.name, text)
    text, moved, new = tl.set_date(str(zone), rel, key, when)
    rekeys(zone.name, rel, (key, new))
    what = "%s %d %s" % (when.strftime("%a"), when.day, when.strftime("%b")) if when else "no date"
    return "%s: %s%s" % (said_text(text), what, ", moved to " + moved if moved else ""), "%s: %s, %s" % (zone.name, what, text)


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
    with zone_lock(zone):
        before = note.read_bytes()
        try:
            line, section, _ = tl.add(str(zone), text, label, when)
        except ValueError as e:
            raise Refused(str(e))
        except tl.NotFound:
            raise Refused("%s's Todo.md has no Inbox section" % zone.name)
        said = tl.parse(line)["text"]
        commit(zone, note, before, ("%s: added to %s, %s" % (zone.name, section, said))[:200])
    return "Added to %s: %s" % (section, said_text(said))


def park(ws: Path, req: dict, today: dt.date) -> str:
    """The threads skill's Park and Wake: the status, `updated:`, a dated entry, a commit.
    A note by its path, {"zone", "file"}: a thread note, or the hub of a
    project that is one thread. Or by name, {"zone", "project", "thread"?}:
    a thread, or a whole project, whose hub then says parked and every
    thread in it counts as parked with it. Waking the project leaves a thread
    parked on its own as it was.

    The edit is System/tools/scaffold.py's, run as a new project's is, so the
    page, the voice command and the script set a status the same way; the
    commit stays here, because this is the path that puts the note back when
    the zone's wall check refuses it."""
    zone = zone_dir(ws, req.get("zone"))
    if req.get("file") is None and req.get("project") is not None:
        folder, _ = cmux_folder(ws, req)
        note = live_note(zone, (folder / (folder.name + ".md")).relative_to(zone).as_posix())
        parts = note.relative_to(zone).parts
        is_thread = len(parts) == 4
    else:
        note = live_note(zone, req.get("file"))
        parts = note.relative_to(zone).parts
        is_thread = len(parts) == 4 and parts[1] == "Threads" and parts[2] + ".md" == parts[3]
        is_hub = len(parts) == 2 and parts[0] + ".md" == parts[1] and not any((zone / parts[0] / "Threads").glob("*/*.md"))
        if not (is_thread or is_hub):
            raise Refused("only a thread note, or a single-thread project's hub, can be parked by its path; "
                          "name the project to park all of it")
    status = "parked" if req["verb"] == "park" else "active"
    name = "%s, %s" % (parts[0], parts[2]) if is_thread else parts[0]
    with zone_lock(zone):
        why = stale_why(ws, req["verb"], req, note_status(note))     # the note's status, read under the lock
        if why:
            raise Refused(why)
        before = note.read_bytes()
        said = scaffold(ws, "--today", today.isoformat(), req["verb"], "--zone", zone.name, "--project", parts[0],
                        *(["--thread", parts[2]] if is_thread else []))
        commit(zone, note, before, "%s: %s" % (name, status if status == "parked" else "woken"))
        if status == "parked":      # a parked thread, or every thread of a parked project, leaves the stack
            drop_from_stack(ws, zone.name, "/".join(parts) if is_thread else parts[0])
        return said


def note_status(note: Path) -> str:
    """A note's `status:`, lower-cased, as front() reads it; "" where it has
    none. This is the fingerprint operations.py declares for park and wake."""
    return front(note).get("status", "")


def dated_entry(body: str, today: dt.date, said: str) -> str:
    """The body with a dated entry added, newest first: below the Resume here
    block's rule, or, with no block, under ## State of play. Neither: as it
    was. Park's copy of this moved into System/tools/scaffold.py, whose own
    one it joined; this stays for `interrupt`, which no tool writes.
    tests/test_scaffold_manage.py holds the two to the same text wherever a
    note has a block to write under, and names where they differ."""
    entry = "**%d %s %d.** %s" % (today.day, MONTHS[today.month - 1], today.year, said)
    resume = body.find("### Resume here")
    rule = body.find("\n---\n", resume) if resume >= 0 else -1
    play = re.search(r"(?m)^## State of play[ \t]*\n", body) if resume < 0 else None
    at = rule + 5 if rule >= 0 else play.end() if play else -1
    if at >= 0:
        rest = body[at:]
        lead = re.match(r"\n*(?:<Dated entries[^\n]*>\n)?\n*", rest)
        at += lead.end()
        body = body[:at] + entry + "\n\n" + body[at:]
    return body


# ---- interrupted and back: the stack of threads left mid-thought ----------------
# "I'm being interrupted" writes the thread's place into its Resume here block
# and commits it, as a wrap would, then puts the thread on top of a stack;
# "back" takes it off again. The stack is System/generated/interrupted.json,
# never committed: it spans zones, and the thread notes hold everything in it
# but the order, {"stack": [{"zone", "project", "thread", "file", "at"}, …]},
# top first, `file` from the zone's folder, `thread` null for a project that
# is its own single thread. Wrapping, parking, finishing or deleting a thread
# takes it off; renaming one moves its entry with it.
STACK_FILE = ("System", "generated", "interrupted.json")
ANSWER_MAX = 400
BY_MAX = 120
ROW_RE = r"(?m)^\|\s*%s\s*\|.*$"


def stack_path(ws: Path) -> Path:
    return ws.joinpath(*STACK_FILE)


def stack_lock():
    """One change to the stack at a time. Taken after a zone's lock, never before."""
    return held("interrupted.lock", busy="the interruption stack is busy")


def load_stack(ws: Path, prune: bool = True) -> list:
    """The entries whose note is still there, top first; every entry, with
    `prune` off, for a rename to move. A missing or unreadable file is an
    empty stack: losing it loses the order, not the notes."""
    try:
        data = json.loads(stack_path(ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("stack") if isinstance(data, dict) else None
    out = []
    for e in entries if isinstance(entries, list) else []:
        if not (isinstance(e, dict) and all(isinstance(e.get(k), str) for k in ("zone", "project", "file"))):
            continue
        if prune:
            try:
                live_note(zone_dir(ws, e["zone"]), e["file"])
            except Refused:
                continue
        if not any((e["zone"], e["file"]) == (o["zone"], o["file"]) for o in out):
            out.append(e)
    return out


def stacked_note(ws: Path, e: dict) -> Path:
    return (ws / "Zones" / e["zone"] / e["file"]).resolve()


def save_stack(ws: Path, entries: list) -> None:
    path = stack_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".interrupted-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"stack": entries}, indent=1, ensure_ascii=False) + "\n")
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def restack(ws: Path, change, prune: bool = True) -> list:
    """Apply `change`, a function from the entries to the new entries, under
    the stack's lock; the entries it left out. Saved only when the file
    changes, which also clears out an entry whose note has gone."""
    with stack_lock():
        saved = load_stack(ws, prune=False)
        before = load_stack(ws) if prune else saved
        after = change(list(before))
        if after != saved:
            save_stack(ws, after)
    return [e for e in before if e not in after]


def drop_from_stack(ws: Path, zone: str, prefix: str) -> list:
    """Every entry for a note at or under `prefix`, a note or a project's
    folder from the zone: a thread parked or deleted, or all of a project."""
    under = lambda e: e["zone"] == zone and (e["file"] == prefix or e["file"].startswith(prefix.rstrip("/") + "/"))
    return restack(ws, lambda entries: [e for e in entries if not under(e)])


def rename_in_stack(ws: Path, zone: str, project: str, thread: Optional[str], to: str) -> None:
    """A renamed project or thread keeps its place on the stack, under its new name."""
    def moved(e):
        if e["zone"] != zone or e.get("project") != project:
            return e
        if thread is None:
            rest = e["file"].split("/", 1)[1]
            return dict(e, project=to, file="%s/%s" % (to, to + ".md" if rest == project + ".md" else rest))
        if e.get("thread") != thread:
            return e
        return dict(e, thread=to, file="%s/Threads/%s/%s.md" % (project, to, to))
    restack(ws, lambda entries: [moved(e) for e in entries], prune=False)     # the old paths are gone by now


def resume_note(ws: Path, req: dict) -> tuple:
    """The note that holds a thread's resume point: (zone, note, its parts
    from the zone, the name to say). A thread note, by its path {"zone",
    "file"} or by name {"zone", "project", "thread"}; or the hub of a project
    that is one thread, with no thread named."""
    zone = zone_dir(ws, req.get("zone"))
    if req.get("file") is None and req.get("project") is not None:
        folder, _ = cmux_folder(ws, req)
        note = live_note(zone, (folder / (folder.name + ".md")).relative_to(zone).as_posix())
    else:
        note = live_note(zone, req.get("file"))
    parts = note.relative_to(zone).parts
    is_thread = len(parts) == 4 and parts[1] == "Threads" and parts[2] + ".md" == parts[3]
    is_hub = len(parts) == 2 and parts[0] + ".md" == parts[1]
    if not (is_thread or is_hub):
        raise Refused("only a thread note, or a single-thread project's hub, holds a resume point")
    if is_hub and any((zone / parts[0] / "Threads").glob("*/*.md")):
        raise Refused("%s has threads; name the one" % parts[0])
    return zone, note, parts, ("%s, %s" % (parts[0], parts[2]) if is_thread else parts[0])


def entry_for(zone: Path, parts: tuple, when: dt.datetime) -> dict:
    return {"zone": zone.name, "project": parts[0], "thread": parts[2] if len(parts) == 4 else None,
            "file": "/".join(parts), "at": when.strftime("%Y-%m-%dT%H:%M")}


def answer(req: dict, key: str, required: bool = True, most: int = ANSWER_MAX) -> Optional[str]:
    """One answer, on one line: white space run together, at most `most` characters."""
    value = req.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise Refused("no %s given" % key if value is None else "not an answer: %s" % key)
    value = " ".join(value.split())
    if not value and not required:
        return None
    if not value:
        raise Refused("no %s given" % key)
    if len(value) > most:
        raise Refused("%s is longer than %d characters; one line will do" % (key, most))
    return value


def cell(text: str) -> str:
    return text.replace("|", "\\|")


def resume_block(body: str):
    """Where the Resume here block's lines are in the body: (start, end), the
    lines between its heading and the next rule or heading. None without one."""
    head = re.search(r"(?m)^###[ \t]+Resume here[ \t]*\n", body)
    if not head:
        return None
    end = re.compile(r"(?m)^(?:---[ \t]*$|#{1,6}[ \t])").search(body, head.end())
    return head.end(), end.start() if end else len(body)


def saved_lines(note: Path) -> dict:
    """The three lines an interruption saves, read back from the note: where it
    stands, the next action and what to keep in mind, each None when missing."""
    try:
        body = note.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"where": None, "next": None, "keep": None}
    span = resume_block(body)
    block = body[span[0]:span[1]] if span else ""
    lead = []
    for line in block.splitlines():
        if line.strip().startswith("|") or (lead and not line.strip()):
            break
        if line.strip():
            lead.append(line.strip())

    def row(name):
        m = re.search(r"(?m)^\|\s*%s\s*\|(.*)\|\s*$" % name, block)
        return m.group(1).strip().replace("\\|", "|") if m else None
    return {"where": " ".join(lead).replace("**", "") or None, "next": row("Next action"), "keep": row("Keep in mind")}


def checkpoint_lib(ws: Path):
    """garrick_lib.py, found as prefs.py finds it: the checkpoint primitives,
    so this file reads and writes the block exactly as scaffold.py does and
    keeps no second reading of its own. None where the workspace has no copy
    with them in it, which is every release before them."""
    found = prefs()
    lib = found.lib(ws) if found is not None and callable(getattr(found, "lib", None)) else None
    return lib if lib is not None and callable(getattr(lib, "rebase_checkpoint", None)) else None


def rebased(ws: Path, text: str) -> Optional[str]:
    """`text` with its unwrapped checkpoint written against the Resume here
    block that is in it now: the same items at the same time, a new base and
    the key that follows. The interrupt is the one Garrick writer that
    rewrites Resume here without folding the checkpoint, because it has to
    take thirty seconds, so without this every hold would make the checkpoint
    stale. None where there is nothing valid to rebase; best effort, as the
    record is, and a failure never stops the hold."""
    lib = checkpoint_lib(ws)
    if lib is None:
        return None
    try:
        base = lib.resume_hash(text)
        return lib.rebase_checkpoint(text, base) if base else None
    except Exception:
        return None


def waiting_checkpoint(ws: Path, note: Path) -> Optional[str]:
    """The time an unwrapped checkpoint in `note` was written, as it is said:
    what Back adds a clause for. None where there is none, or where the block
    cannot be read: an invalid one is never resumed from, the check reports it,
    and Back does not mention it. No content of the block is read here."""
    lib = checkpoint_lib(ws)
    if lib is None:
        return None
    try:
        block = lib.read_checkpoint(note.read_text(encoding="utf-8"))
        if block is None or not block["valid"]:
            return None
        return lib.said_time(block["at"]).split(" on ")[0]
    except Exception:
        return None


def interrupt(ws: Path, req: dict, now: dt.datetime) -> str:
    """"I'm being interrupted": the three answers written into the Resume here
    block as a wrap would, committed in the zone, then the thread on top of the
    stack, moved there if it was already on it. {"zone", "project", "thread"}
    or {"zone", "file"}, with "where" and "next", and "keep" and "by" if given."""
    zone, note, parts, name = resume_note(ws, req)
    where, step = answer(req, "where"), answer(req, "next")
    keep, by = answer(req, "keep", required=False), answer(req, "by", required=False, most=BY_MAX)
    with zone_lock(zone):
        interrupt_note(ws, zone, note, parts, name, where, step, keep, by, now)
        entry = entry_for(zone, parts, now)
        restack(ws, lambda entries: [entry] + [e for e in entries if stacked_note(ws, e) != note.resolve()])
        held_now = len(load_stack(ws))
    return "Held %s at %s%s" % (name, now.strftime("%H:%M"), "" if held_now == 1 else "; %d on the stack" % held_now)


def interrupt_note(ws: Path, zone: Path, note: Path, parts: tuple, name: str, where: str, step: str,
                   keep: Optional[str], by: Optional[str], now: dt.datetime) -> None:
    """The edit and its commit, under the zone's lock. Where it stands becomes
    the stamped answer; Next action and Keep in mind take theirs, a Keep in
    mind skipped is left as it was, or says nothing where there was none.
    The other rows stay. `status:` stays active: an interruption is no park.
    An unwrapped checkpoint under the block is rebased onto what this wrote,
    its items untouched, so a hold never makes one stale."""
    before = note.read_bytes()
    try:
        text = before.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("the note is not UTF-8 text")
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise Refused("the note has no frontmatter")
    fm = m.group(1)
    status = re.search(r"(?m)^status:\s*(\S+)", fm)
    status = status.group(1).lower() if status else "active"
    hub = zone / parts[0] / (parts[0] + ".md")
    parked_project = len(parts) == 4 and hub.is_file() and re.search(
        r"(?m)^status:\s*parked\s*$", hub.read_text(encoding="utf-8", errors="replace").split("\n---", 2)[0])
    if status == "done":
        raise Refused("%s is finished" % name)
    if status == "parked" or parked_project:
        raise Refused("%s is parked; wake it first" % name)
    fm = re.sub(r"(?m)^updated:.*$", "updated: " + now.date().isoformat(), fm) if re.search(r"(?m)^updated:", fm) \
        else fm + "\nupdated: " + now.date().isoformat()
    body = text[m.end():]
    span = resume_block(body)
    if not span:
        raise Refused("%s has no Resume here block to write in; wrap it instead" % name)
    lines = body[span[0]:span[1]].split("\n")
    stamp = "**Interrupted %s, %d %s %d.** %s" % (now.strftime("%H:%M"), now.day, MONTHS[now.month - 1], now.year, where)
    first = next((i for i, x in enumerate(lines) if x.strip()), None)
    if first is None or lines[first].lstrip().startswith("|"):
        at = 0 if first is None else first
        lines[at:at] = ["", stamp, ""] if at == 0 else [stamp, ""]
    else:
        last = first
        while last + 1 < len(lines) and lines[last + 1].strip() and not lines[last + 1].lstrip().startswith("|"):
            last += 1
        lines[first:last + 1] = [stamp]
    rows = [i for i, x in enumerate(lines) if x.lstrip().startswith("|")]
    if not rows:            # a block with no table yet: the two rows, under an empty header
        at = lines.index(stamp) + 1
        lines[at:at] = ["", "| | |", "|---|---|"]
        rows = [at + 1, at + 2]
    set_row(lines, rows, "Next action", step, after=None)
    rows = [i for i, x in enumerate(lines) if x.lstrip().startswith("|")]
    if keep is not None or not any(re.match(ROW_RE % "Keep in mind", lines[i]) for i in rows):
        set_row(lines, rows, "Keep in mind", keep or "nothing", after="Next action")
    body = body[:span[0]] + "\n".join(lines) + body[span[1]:]
    body = dated_entry(body, now.date(), "Interrupted at %s%s." % (now.strftime("%H:%M"), ", by " + by if by else ""))
    written = "---\n%s\n---\n%s" % (fm, body)
    note.write_text(rebased(ws, written) or written, encoding="utf-8")
    commit(zone, note, before, ("%s: interrupted%s" % (name, ", by " + by if by else ""))[:200])


def set_row(lines: list, rows: list, name: str, value: str, after: Optional[str]) -> None:
    """A row of the block's table set to `value`; a missing one goes in after
    the row named `after`, or at the table's end."""
    row = "| %s | %s |" % (name, cell(value))
    for i in rows:
        if re.match(ROW_RE % re.escape(name), lines[i]):
            lines[i] = row
            return
    prior = next((i for i in rows if after and re.match(ROW_RE % re.escape(after), lines[i])), rows[-1])
    lines.insert(prior + 1, row)


def back(ws: Path, req: dict) -> dict:
    """"Back": the top of the stack taken off, or, with a thread named, that
    one taken out from wherever it is, the others left in order. The note is
    read, never written: the reply carries its three lines and its path, for
    the caller to open it and read them back, with one clause more where an
    unwrapped checkpoint is waiting (`checkpoint`, the time it was written).
    An empty stack says so, and offers the live thread updated most
    recently."""
    named = req.get("file") is not None or req.get("project") is not None
    if named:
        zone, note, parts, name = resume_note(ws, req)
    taken = []

    def take(entries):
        if not entries:
            return entries
        at = 0 if not named else next((i for i, e in enumerate(entries) if stacked_note(ws, e) == note.resolve()), None)
        if at is None:
            return entries
        taken.append(entries[at])
        return entries[:at] + entries[at + 1:]
    restack(ws, take)
    if not taken:
        if named:
            raise Refused("%s is not on the stack; open it instead" % name)
        latest = latest_thread(ws)
        if latest is None:
            return {"say": "Nothing is on the stack, and no thread is live.", "empty": True}
        return {"say": "Nothing is on the stack. The most recent live thread is %s." % latest["name"], "empty": True,
                "offer": latest}
    e = taken[0]
    name = e["project"] if not e.get("thread") else "%s, %s" % (e["project"], e["thread"])
    note = stacked_note(ws, e)
    lines = saved_lines(note)
    said = ["Back to %s." % name]
    if lines["where"]:
        said.append(sentence(lines["where"]))
    if lines["next"]:
        said.append(sentence("Next: " + lines["next"]))
    if lines["keep"] and lines["keep"].lower().rstrip(". ") not in ("nothing", "none"):
        said.append(sentence("Keep in mind: " + lines["keep"]))
    at = waiting_checkpoint(ws, note)
    if at:
        said.append("There's also an unwrapped checkpoint from %s." % at)
    out = dict(e, path=("Zones/%s/%s" % (e["zone"], e["file"])), name=name, left=len(load_stack(ws)),
               checkpoint=at, **lines)
    out["say"] = " ".join(said)
    out["logged"] = said[0]         # the log names the thread; what was saved stays in the note
    return out


def sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else text + "."


def show_stack(ws: Path) -> dict:
    """What is on the stack, top first, each entry with its path and the next
    action its note saved. Read only: close for the day lists it and leaves it."""
    entries = load_stack(ws)
    out = []
    for e in entries:
        name = e["project"] if not e.get("thread") else "%s, %s" % (e["project"], e["thread"])
        out.append(dict(e, name=name, path="Zones/%s/%s" % (e["zone"], e["file"]),
                        next=saved_lines(stacked_note(ws, e))["next"]))
    if not out:
        return {"say": "Nothing is on the stack.", "stack": []}
    return {"say": "%d on the stack: %s." % (len(out), "; ".join(e["name"] for e in out)), "stack": out}


def unstack(ws: Path, req: dict) -> str:
    """A thread off the stack without reading it back: what a wrap, a park,
    a finish or a deletion done by the assistant runs. {"zone", "project",
    "thread"?}: with no thread, every thread of the project. The names need
    not lead anywhere any more, so a thread already deleted can still go.
    Not there is no fault."""
    zone = zone_dir(ws, req.get("zone"))
    names = [req.get("project")] + ([req["thread"]] if req.get("thread") not in (None, "", "-") else [])
    if any(not isinstance(n, str) or not n or n.startswith((".", "_")) or "/" in n or n in ("..", "Threads")
           for n in names):
        raise Refused("not a project or thread")
    gone = drop_from_stack(ws, zone.name, "%s/Threads/%s" % tuple(names) if len(names) == 2 else names[0])
    name = ", ".join(names)
    return ("%s is off the stack" if gone else "%s was not on the stack") % name


def latest_thread(ws: Path) -> Optional[dict]:
    """The live thread updated most recently, as "what's open" orders them:
    `updated:`, then the note's last change. A project with no threads is its
    own; a parked project holds every thread in it parked."""
    best = None
    for zone in sorted((ws / "Zones").iterdir()) if (ws / "Zones").is_dir() else []:
        if not zone.is_dir() or zone.name.startswith((".", "_")):
            continue
        for project in sorted(zone.iterdir()):
            hub = project / (project.name + ".md")
            if project.name.startswith((".", "_")) or project.name in SKIP or project.name == "Inbox" or not hub.is_file():
                continue
            hub_fm = front(hub)
            if hub_fm.get("status") in ("done", "parked"):
                continue
            notes = [t / (t.name + ".md") for t in sorted((project / "Threads").glob("*"))
                     if not t.name.startswith((".", "_")) and (t / (t.name + ".md")).is_file()]
            for note in notes or [hub]:
                fm = hub_fm if note == hub else front(note)
                if fm.get("status") in ("done", "parked"):
                    continue
                key = (fm.get("updated", ""), note.stat().st_mtime)
                if best is None or key > best[0]:
                    thread = note.stem if note != hub else None
                    best = (key, {"zone": zone.name, "project": project.name, "thread": thread,
                                  "file": note.relative_to(zone).as_posix(),
                                  "path": note.relative_to(ws).as_posix(),
                                  "name": project.name if thread is None else "%s, %s" % (project.name, thread)})
    return best[1] if best else None


def front(note: Path) -> dict:
    """A note's `status:` and `updated:`, lower-cased status, as listing reads them."""
    try:
        text = note.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    m = re.match(r"\A---\n(.*?)\n---", text, re.S)
    out = {}
    for key in ("status", "updated"):
        found = re.search(r"(?m)^%s:[ \t]*(\S*)" % key, m.group(1)) if m else None
        if found:
            out[key] = found.group(1).lower() if key == "status" else found.group(1)
    return out
# ---- end of interrupted and back ------------------------------------------------


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


JOB_PY = Path(__file__).resolve().parent.parent / "jobs" / "job.py"
_JOB = None


def job_py():
    """job.py from the scheduled jobs extra, beside this folder (System/jobs/
    in a workspace, extras/jobs/ in Garrick's source), loaded once; None when
    it is not there or does not load."""
    global _JOB
    if _JOB is None:
        _JOB = False
        if JOB_PY.is_file():
            try:
                spec = importlib.util.spec_from_file_location("garrick_job", str(JOB_PY))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _JOB = mod
            except Exception:
                pass
    return _JOB or None


def lock_held(name: str, now: float = None) -> bool:
    """Whether job.py's lock for this job stands: `<name>.lock`, a folder in
    the jobs folder. job.py's own lock_state() decides, where it is beside
    this folder: a job.py still alive holds its lock whatever the clock says,
    as after a Mac's sleep. Without it, or given `now`, the lock's `until`
    file decides: a lock past it belongs to a run that died, and job.py's
    next run takes it over."""
    lock = jobs_dir() / ("%s.lock" % name)
    if not lock.is_dir():
        return False
    job = job_py() if now is None else None
    if job is not None and callable(getattr(job, "lock_state", None)):
        try:
            return job.lock_state(lock) is not None
        except Exception:
            pass                    # its rule failed; the clock's still holds
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


_PREFS = None


def prefs():
    """prefs.py, beside this file: the one way to the choices the page keeps."""
    global _PREFS
    if _PREFS is None:
        spec = importlib.util.spec_from_file_location("garrick_prefs", str(Path(__file__).with_name("prefs.py")))
        _PREFS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_PREFS)
    return _PREFS


_NOTIFY = {}


def notifications_lib(ws: Path):
    """System/tools/notifications.py: the workspace's own, else the one a
    step from this extra, else a Garrick clone's template, as prefs.py finds
    garrick_lib. None when there is none."""
    key = Path(ws)
    if key not in _NOTIFY:
        found = None
        for src in (key / "System" / "tools" / "notifications.py", Path(__file__).resolve().parent.parent / "tools" / "notifications.py",
                    Path(__file__).resolve().parent.parent.parent / "template" / "System" / "tools" / "notifications.py"):
            if not src.is_file():
                continue
            try:
                spec = importlib.util.spec_from_file_location("garrick_notifications", str(src))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                continue
            if callable(getattr(mod, "clean", None)) and callable(getattr(mod, "test", None)):
                found = mod
                break
        _NOTIFY[key] = found
    return _NOTIFY[key]


_NEXT_UP = {}


def next_up_lib(ws: Path):
    """System/tools/next_up.py, which checks Settings › While you wait: found
    as notifications_lib() finds its module. None when there is none."""
    key = Path(ws)
    if key not in _NEXT_UP:
        found = None
        for src in (key / "System" / "tools" / "next_up.py", Path(__file__).resolve().parent.parent / "tools" / "next_up.py",
                    Path(__file__).resolve().parent.parent.parent / "template" / "System" / "tools" / "next_up.py"):
            if not src.is_file():
                continue
            try:
                spec = importlib.util.spec_from_file_location("garrick_next_up", str(src))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                continue
            if callable(getattr(mod, "clean", None)):
                found = mod
                break
        _NEXT_UP[key] = found
    return _NEXT_UP[key]


def save_settings(ws: Path, req: dict) -> str:
    """Settings, kept in one file so every viewer of the page agrees, and the
    cmux desk with them: {"launchers": {"note": true, "cmux": false, …},
    "default": "note", "zones": {"Work": {"color": "Teal", "icon": "briefcase"}}}.
    They go in the workspace's own settings file, through garrick_lib's
    accessor (prefs.py), so they are committed with the workspace and nothing
    here knows where the file is. A request carries the launchers, the zones
    or both, and what it leaves out stays as saved. Every known way is
    written, on or off; status.py reads the same choices when it builds the
    page. A way it does not list is on, as on the page. Settings › Home:
    {"home": "simple"} or "full", which the page opens on (#175)."""
    notifying = {"notifications", "test", "token", "find-chat"} & set(req)
    if not ({"launchers", "zones", "while-you-wait", "home"} | notifying) & set(req):
        raise Refused("nothing to save")
    new = {}
    if "home" in req:
        if req["home"] not in HOMES:
            raise Refused("no home called %r; it is %s" % (req["home"], " or ".join(HOMES)))
        new["home"] = req["home"]
    notify = notifications_lib(ws) if notifying else None
    if notifying and notify is None:
        raise Refused("cannot find System/tools/notifications.py; update Garrick")
    test = req.get("test")
    if test is not None and test not in ("mac", "telegram", "command"):
        raise Refused("no channel to test called %r" % (test,))
    tok, find = req.get("token"), req.get("find-chat")
    if tok is not None and not isinstance(tok, str):
        raise Refused("not a bot token")
    if find is not None and find is not True:
        raise Refused("find-chat is true or left out")
    if find and not callable(getattr(notify, "set_up_chat", None)):
        raise Refused("this workspace's System/tools/notifications.py cannot find a chat yet; update Garrick")
    if "launchers" in req:
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
        new = {"launchers": {k: k in on for k in LAUNCHERS}, "default": default}
    if "zones" in req:
        new["zones"] = zone_styles(ws, req["zones"])
    if "notifications" in req:
        zones = [z.name for z in (ws / "Zones").iterdir() if z.is_dir()] if (ws / "Zones").is_dir() else []
        try:
            new["notifications"] = notify.clean(req["notifications"], zones)
        except ValueError as e:
            raise Refused(str(e))
    if "while-you-wait" in req:
        wait = next_up_lib(ws)
        if wait is None:
            raise Refused("cannot find System/tools/next_up.py; update Garrick")
        try:
            new[wait.KEY] = wait.clean(req["while-you-wait"])
        except ValueError as e:
            raise Refused(str(e))
    keep = prefs()
    keep.migrate(ws)             # a choice an older Garrick left in System/generated/ comes first
    was = keep.read(ws).get("zones")
    before = was if isinstance(was, dict) else {}
    if new:
        try:
            keep.save(ws, new)
        except ValueError as e:         # a garrick_lib older than the choice: "not a kept choice: home"
            raise Refused("%s; update Garrick to keep it" % e)
    if "home" in new and set(new) == {"home"} and not notifying:
        return "Garrick now opens on %s" % ("the simple home" if new["home"] == "simple" else "the full page")
    if "zones" in new:
        colour = lambda zones, z: zones.get(z, {}).get("color") if isinstance(zones.get(z), dict) else None
        changed = sorted(z for z in set(before) | set(new["zones"]) if colour(before, z) != colour(new["zones"], z))
        if changed:
            recolour(ws, changed)
    if tok is not None:
        keep_token(notify, ws, tok, bool(new))
        if not find and test is None:
            return "%sToken kept in this Mac's keychain. Now send your bot any message, then press Find my chat" % (
                "Settings saved. " if new else "")
    if find:
        ok, said = notify.set_up_chat(ws, desk=(CMUX_EXTRA / "cmuxlib.py").is_file())
        if not ok:
            raise Refused(said.rstrip("."))
        return said.rstrip(".")
    if test is not None:
        name = {"mac": "this Mac", "telegram": "Telegram", "command": "your command"}[test]
        problem = notify.test(ws, test)
        if problem:
            raise Refused("%sthe test did not go: %s %s" % ("Settings saved, but " if new else "", name[:1].upper() + name[1:], problem))
        return "%sA test went to %s" % ("Settings saved. " if new else "", name)
    return "Settings saved"


def keep_token(notify, ws: Path, tok: str, saved: bool) -> None:
    """The bot's token into the keychain, or Refused in words that cannot
    carry it: notifications.py's own for a value that is not a token or a
    keychain that said no, and only the kind of anything else, whose own
    message is never read out, since nobody here wrote it."""
    first = "Settings saved, but " if saved else ""
    try:
        notify.store_token(tok, ws)
    except ValueError as e:                 # notifications.Invalid: its words never quote the value
        raise Refused(first + str(e).strip())
    except OSError as e:
        raise Refused("%sthe token was not kept: %s" % (first, notify.scrub(str(e), tok.strip())))
    except Exception as e:
        raise Refused("%sthe token was not kept: %s" % (first, type(e).__name__))


def zone_styles(ws: Path, given) -> dict:
    """Settings › Zones as the page sends it, every zone it lists with what
    was chosen: {"Work": {"color": "Teal", "icon": "briefcase"}, "Personal": {}}.
    A zone no longer in the workspace, from a page built before it was
    renamed, is left out; so is a zone with neither, which looks as it did."""
    if not isinstance(given, dict):
        raise Refused("not a colour and an icon for each zone")
    out = {}
    for zone, style in given.items():
        if not isinstance(style, dict) or set(style) - {"color", "icon"}:
            raise Refused("not a colour and an icon for %s" % zone)
        colour, icon = style.get("color") or "", style.get("icon") or ""
        if colour not in ZONE_COLOURS + ("",):
            raise Refused("no colour called %r" % (colour,))
        if icon not in ZONE_ICONS + ("",):
            raise Refused("no icon called %r" % (icon,))
        try:
            zone_dir(ws, zone)
        except Refused:
            continue
        chosen = {k: v for k, v in (("color", colour), ("icon", icon)) if v}
        if chosen:
            out[zone] = chosen
    return out


def recolour(ws: Path, zones) -> None:
    """Best effort: the cmux workspace of each zone whose colour changed takes
    the new one, or loses it. Without the cmux extra, without cmux or with it
    not running, nothing happens, and a tab takes its colour when the desk
    next opens one."""
    try:
        run_desk(ws, "colour", "--", *zones, timeout=20)
    except (Refused, OSError):
        pass


# ---- cmux tabs: open, close, startup, shutdown -------------------------------
# Only with the cmux extra (extras/cmux, beside this folder) and cmux installed.
# Each runs that extra's desk.py, which reads cmux's socket password itself.
#   {"verb": "open", "zone", "project", "thread"?}  a tab in that folder, started on "open …"
#   {"verb": "open", "folder", "prompt"}  the same by the folder's full path, for the app's
#                          own rows and Ask; or the workspace root, started on the prompt,
#                          for Process the Inbox and the words typed in the panel's field
#   {"verb": "close", "zone", "project", "thread"?} its tabs; refused while one is mid-turn
#   {"verb": "startup"}    start or restore cmux and resume its tabs, detached
#   {"verb": "shutdown"}   the dry run here, so a busy tab is refused while the page
#                          watches; the wraps and the quit go on detached
CMUX_VERBS = ("open", "close", "startup", "shutdown")
CMUX_EXTRA = Path(__file__).resolve().parent.parent / "cmux"
PROMPT_MAX = 2000


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


def by_folder(ws: Path, req: dict) -> Optional[str]:
    """An open by folder: None for the workspace root, whose tab starts on the
    request's prompt; for a project's or a thread's folder, the request is
    rewritten in place to name it, as the page's buttons do. Anything else,
    such as a zone, a wiki or a folder outside the workspace, is refused: a
    tab there would reach more than one project, or nothing of this one."""
    given = req.get("folder")
    if not isinstance(given, str) or not given or not Path(given).is_absolute():
        raise Refused("not a folder in the workspace")
    folder = Path(given).resolve()
    if folder == ws.resolve():
        prompt = req.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise Refused("the workspace root opens only to do something; say what")
        prompt = prompt.strip()
        if len(prompt) > PROMPT_MAX or prompt.startswith("-"):
            raise Refused("that is not something to start a session on")
        return prompt
    try:
        parts = folder.relative_to((ws / "Zones").resolve()).parts
    except ValueError:
        raise Refused("a tab opens only at the workspace root or in a project or thread")
    if len(parts) == 2:
        req.update(zone=parts[0], project=parts[1])
    elif len(parts) == 4 and parts[2] == "Threads":
        req.update(zone=parts[0], project=parts[1], thread=parts[3])
    else:
        raise Refused("a tab opens only at the workspace root or in a project or thread")
    return None


# What a tab opened at the workspace root is called, by what it starts on.
# Anything else at the root is a question asked of Garrick, named by its
# first words, so two of them are told apart and "close the X tab" has an X.
ROOT_TITLES = {"process the inbox": "Inbox"}
ROOT_TITLE_WORDS = 4


def root_title(prompt: str) -> str:
    known = ROOT_TITLES.get(re.sub(r"\s+", " ", prompt).strip().lower().rstrip(".!?"))
    if known:
        return known
    words = re.findall(r"[\w'’-]+", prompt)[:ROOT_TITLE_WORDS]
    title = " ".join(words).strip("-'’ ")
    return (title[:1].upper() + title[1:]) if title else "Ask"


def cmux_act(ws: Path, req: dict) -> str:
    verb = req["verb"]
    if verb == "open" and "folder" in req:
        req = dict(req)
        prompt = by_folder(ws, req)
        if prompt is not None:
            said = run_desk(ws, "open", str(ws.resolve()), "--prompt", prompt, "--title", root_title(prompt),
                            "--front").splitlines()
            return said[0][:1].upper() + said[0][1:] if said else "Opened the workspace root in cmux"
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


# ---- projects and threads: made, renamed and deleted through scaffold.py -------

NAME_MAX = 80


def field(req: dict, key: str, required: bool = True) -> Optional[str]:
    value = req.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > NAME_MAX or value.strip().startswith("-") \
            or "\n" in value:
        raise Refused("no %s given" % key if value is None else "not a %s: %r" % (key, value))
    return value.strip()


def scaffold(ws: Path, *args) -> str:
    """Run the workspace's scaffold.py: what it said, or Refused with its reason.
    A rename or a deletion commits through the wall check, so it has a
    commit's time and a git command's besides."""
    tool = ws / "System" / "tools" / "scaffold.py"
    if not tool.is_file():
        raise Refused("System/tools/scaffold.py is missing")
    try:
        r = subprocess.run([sys.executable, str(tool), "--root", str(ws)] + list(args), capture_output=True, text=True,
                           timeout=COMMIT_TIMEOUT + GIT_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise Refused("scaffold.py was still running after %s, most likely in the wall check of its commit, and was "
                      "stopped; its change may be left staged, so look at git status in the zone before trying again"
                      % how_long(COMMIT_TIMEOUT + GIT_TIMEOUT))
    if r.returncode != 0:
        raise Refused((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else "scaffold.py refused")
    return r.stdout.strip()


def manage(ws: Path, req: dict) -> str:
    verb = req["verb"]
    zone = zone_dir(ws, req.get("zone"))
    if verb == "check-name":
        kind = req.get("kind")
        if kind not in ("project", "thread", "rename"):
            raise Refused("not a kind of name: %r" % kind)
        req = dict(req, verb={"project": "new-project", "thread": "new-thread"}.get(kind, kind))
        return manage_args(ws, zone, req, check=True)
    with zone_lock(zone):
        return manage_args(ws, zone, req, check=False)


def manage_args(ws: Path, zone: Path, req: dict, check: bool) -> str:
    verb, z = req["verb"], zone.name
    flag = ["--check"] if check else []
    if verb == "new-project":
        name, thread = field(req, "name"), field(req, "thread")
        said = scaffold(ws, "project", "--zone", z, "--name", name, "--party", field(req, "party"), "--thread", thread,
                        *flag)
        if not check:
            commit_new(zone, zone / name, "New project %s (%s), first thread %s" % (name, req["party"].strip(), thread))
        return said
    if verb == "new-thread":
        project, name = field(req, "project"), field(req, "name")
        said = scaffold(ws, "thread", "--zone", z, "--project", project, "--name", name, *flag)
        if not check:
            commit_new(zone, zone / project, "%s: new thread %s" % (project, name))
        return said
    if verb == "undo":
        commit = req.get("commit")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{7,40}", commit):
            raise Refused("not a commit: %r" % commit)
        return scaffold(ws, "undo", "--zone", z, "--commit", commit)
    thread = field(req, "thread", required=False)
    which = ["--zone", z, "--project", field(req, "project")] + (["--thread", thread] if thread else [])
    if verb == "rename":
        said = scaffold(ws, "rename", *which, "--to", field(req, "to"), *flag)
        if not check:               # its place on the interruption stack follows it
            rename_in_stack(ws, z, field(req, "project"), thread, field(req, "to"))
        return said
    confirm = field(req, "confirm", required=False)
    said = scaffold(ws, "delete", *which, *(["--confirm", confirm] if confirm else []))
    if confirm:
        project = field(req, "project")
        drop_from_stack(ws, z, "%s/Threads/%s" % (project, thread) if thread else project)
    return said


def commit_new(zone: Path, folder: Path, message: str) -> None:
    """Commit what scaffold.py made, as the threads skill's New does: the new
    folder by name, and its hub. Refused, the folder stays for the user."""
    rel = folder.relative_to(zone).as_posix()
    code, why = committing(zone, rel, message)
    if code != 0:
        git(zone, "reset", "-q", "--", rel, timeout=10)
        if code is None:
            raise Refused("made, but not committed: %s. The files are there, unstaged; commit them by hand: that "
                          "commit waits for the check and goes through" % why)
        raise Refused("made, but not committed: %s. The files are there; commit them when it is fixed" % why)


# ---- the simple home (#175): Needs you, Continue, Ask something, the example ----
# Needs you is a record, not a view: one file per question Garrick asked, in
# the folder of the work it blocks, `Needs you/<YYMMDD> - <slug>.md`,
# committed with the zone. `status: open`, `answered` or `later`; each option
# is a line `- [<label>] <the next action it leads to>`. Answering sets the
# work's Next action to that option's action, ends its Where it stands with
# "Answered on <date>: <label>.", adds a dated entry ("Answered: <label>."), writes the file's new status, and commits the two in one commit.
# "Not now" puts it off to a later day, `later: <date>`, and the home shows it
# again that day.
NEEDS = "Needs you"
OPTION = re.compile(r"^\s*-\s+\[(?![ xX]\])([^\]]+)\]\s+(\S.*?)\s*$")
LABEL_MAX = 120
_HANDOFF = None


def handoff():
    """handoff.py, beside this file: Continue's and Ask something's way into Claude's desktop app."""
    global _HANDOFF
    if _HANDOFF is None:
        spec = importlib.util.spec_from_file_location("garrick_handoff", str(HERE / "handoff.py"))
        _HANDOFF = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_HANDOFF)
    return _HANDOFF


def options(text: str) -> list:
    """A question's options, in its order: [(label, the action it leads to)]."""
    body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)
    return [(m.group(1).strip(), m.group(2).strip()) for m in (OPTION.match(l) for l in body.splitlines()) if m]


def set_front(text: str, values: dict, drop=()) -> str:
    """The note with these frontmatter keys set, in place where each is, at
    the end where it is not, and the keys in `drop` taken out."""
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise Refused("the note has no frontmatter")
    fm = m.group(1)
    for key in drop:
        fm = re.sub(r"(?m)^%s:.*(?:\n|\Z)" % re.escape(key), "", fm)
    for key, value in values.items():
        line = "%s: %s" % (key, value)
        if re.search(r"(?m)^%s:" % re.escape(key), fm):
            fm = re.sub(r"(?m)^%s:.*$" % re.escape(key), lambda _: line, fm, count=1)
        else:
            fm = fm.rstrip("\n") + "\n" + line
    return "---\n%s\n---\n%s" % (fm.strip("\n"), text[m.end():])


def quoted(value: str) -> str:
    """A frontmatter value that reads back as written, whatever its words."""
    return json.dumps(value, ensure_ascii=False)


def question(ws: Path, req: dict) -> tuple:
    """(zone, the question's file, the note of the work it blocks, its parts
    from the zone, the work's name). The file must sit in a `Needs you` folder
    beside a thread note, or beside the hub of a project that is one thread."""
    zone = zone_dir(ws, req.get("zone"))
    q = live_note(zone, req.get("file"))
    if q.parent.name != NEEDS:
        raise Refused("that is not a question Garrick asked")
    work = q.parent.parent
    note = work / (work.name + ".md")
    if not note.is_file():
        raise Refused("the work this question is for is not there any more")
    parts = note.relative_to(zone).parts
    if not ((len(parts) == 4 and parts[1] == "Threads") or len(parts) == 2):
        raise Refused("that question is not in a piece of work's folder")
    return zone, q, note, parts, work_name(zone, parts)


def work_name(zone: Path, parts: tuple) -> str:
    """A piece of work as the home names it: the project's name for a project
    that is one thread, "Project, Thread" where it has more than one."""
    if len(parts) == 2:
        return parts[0]
    threads = [t for t in (zone / parts[0] / "Threads").glob("*/*.md") if t.parent.name + ".md" == t.name]
    return parts[0] if len(threads) <= 1 else "%s, %s" % (parts[0], parts[2])


def open_question(q: Path) -> str:
    text = q.read_text(encoding="utf-8")
    state = front(q).get("status", "open")
    if state == "answered":
        raise Refused("that question is already answered")
    if state not in ("open", "later"):
        raise Refused("that question is %s, not open" % state)
    return text


def answer_question(ws: Path, req: dict, today: dt.date) -> str:
    """Answer a Needs you question by one of its options: the work's Next
    action becomes what the option leads to, a dated entry says so, the
    question says it was answered, and the two are committed in one commit."""
    zone, q, note, parts, name = question(ws, req)
    label = answer(req, "label", most=LABEL_MAX)
    with zone_lock(zone):
        text = open_question(q)
        chosen = next(((l, a) for l, a in options(text) if l.casefold() == label.casefold()), None)
        if chosen is None:
            raise Refused("that question has no answer called %r" % label)
        q_before, n_before = q.read_bytes(), note.read_bytes()
        written = answered_note(n_before.decode("utf-8"), chosen[1], chosen[0], today, name)
        note.write_text(written, encoding="utf-8")
        q.write_text(set_front(text, {"status": "answered", "answer": quoted(chosen[0]), "answered": today.isoformat()},
                               drop=("later",)), encoding="utf-8")
        commit_all(zone, [(note, n_before), (q, q_before)], ("%s: answered %s" % (name, chosen[0]))[:200],
                   wall=wall_refusal(ws))
    return "Noted: %s. Next for %s: %s" % (chosen[0], name, said_text(chosen[1]))


def answered_note(text: str, step: str, label: str, today: dt.date, name: str) -> str:
    """The work's note with its Next action set to `step`, `updated:` moved
    and a dated entry, newest first, as a wrap writes one."""
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise Refused("%s has no frontmatter" % name)
    status = re.search(r"(?m)^status:\s*(\S+)", m.group(1))
    if status and status.group(1).lower() == "done":
        raise Refused("%s is finished" % name)
    text = set_front(text, {"updated": today.isoformat()})
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    body = text[m.end():]
    span = resume_block(body)
    if not span:
        raise Refused("%s has no Resume here block to write the answer in" % name)
    lines = body[span[0]:span[1]].split("\n")
    rows = [i for i, x in enumerate(lines) if x.lstrip().startswith("|")]
    if not rows:
        lines += ["| | |", "|---|---|"]
        rows = [len(lines) - 2, len(lines) - 1]
    set_row(lines, rows, "Next action", step, after=None)
    said_answered(lines, today, label)
    body = body[:span[0]] + "\n".join(lines) + body[span[1]:]
    body = dated_entry(body, today, "Answered: %s." % label.rstrip("."))
    return text[:m.end()] + body


ANSWERED_SENTENCE = re.compile(r" ?Answered on \d{1,2} [A-Z][a-z]+ \d{4}: (?:(?!\. ).)+\.$")


def said_answered(lines: list, today: dt.date, label: str) -> None:
    """The block's Where it stands, which said the work waits in Needs you,
    now saying it was answered: one sentence at the end of its paragraph, in
    place of the one an earlier answer added there. Nothing else the user
    wrote is touched. With no such paragraph, the sentence is one."""
    said = "Answered on %d %s %d: %s." % (today.day, MONTHS[today.month - 1], today.year, label.rstrip("."))
    first = next((i for i, x in enumerate(lines) if x.strip()), None)
    if first is None or lines[first].lstrip().startswith("|"):
        at = 0 if first is None else first
        lines[at:at] = ["", said, ""] if at == 0 else [said, ""]
        return
    last = first
    while last + 1 < len(lines) and lines[last + 1].strip() and not lines[last + 1].lstrip().startswith("|"):
        last += 1
    kept = ANSWERED_SENTENCE.sub("", lines[last].rstrip())
    lines[last] = (kept + " " + said) if kept.strip() else said


def put_off(ws: Path, req: dict, today: dt.date) -> str:
    """"Not now": the question set aside to a later day, tomorrow unless
    `until` names one, and back on the home that day."""
    zone, q, _, _, name = question(ws, req)
    until = req.get("until")
    if until in (None, ""):
        day = today + dt.timedelta(days=1)
    else:
        try:
            day = dt.date.fromisoformat(until) if isinstance(until, str) else None
        except ValueError:
            day = None
        if day is None or day <= today:
            raise Refused("not a later day: %r" % (until,))
    with zone_lock(zone):
        text = open_question(q)
        before = q.read_bytes()
        q.write_text(set_front(text, {"status": "later", "later": day.isoformat()}), encoding="utf-8")
        commit(zone, q, before, ("%s: question put off to %s" % (name, day.isoformat()))[:200], wall=wall_refusal(ws))
    when = "tomorrow" if day == today + dt.timedelta(days=1) else "%s %d %s" % (day.strftime("%A"), day.day, MONTHS[day.month - 1])
    return "Put off until %s. It will be back then" % when


def commit_all(zone: Path, notes: list, message: str, wall: Optional[str] = None) -> None:
    """commit() for several files in one commit. When the commit is refused,
    all are put back if every one still holds what this request wrote, and
    none if any was edited meanwhile, so they never disagree."""
    rels = [str(n.relative_to(zone)) for n, _ in notes]
    mine = [n.read_bytes() for n, _ in notes]
    deadline = time.time() + COMMIT_TIMEOUT
    code, why = git(zone, "add", "--", *rels)
    if code == 0:
        note_event("phase", "checking")
        code, why = git(zone, "commit", "-q", "-m", message, "--", *rels, timeout=deadline - time.time())
        if code is None:
            why = "the wall check was still running after %s and was stopped" % how_long(COMMIT_TIMEOUT)
    if code == 0:
        return
    why = why if code is None else ((why.strip().splitlines() or ["git refused"])[-1])
    try:
        ours = all(n.read_bytes() == wrote for (n, _), wrote in zip(notes, mine))
    except OSError:
        ours = False
    if ours:                                    # all put back, or none: never one answered and the other open
        for n, before in notes:
            n.write_bytes(before)
    git(zone, "reset", "-q", "--", *rels, timeout=10)
    if not ours:
        raise Refused("not committed: %s. A note was edited meanwhile, so it was left as it is" % why)
    if wall and WALL_LINE.match(why):
        raise Refused(wall)
    raise Refused("not committed, so nothing changed: %s" % why)


def managed_places() -> Optional[list]:
    """Where the managed setting that switches local sessions off is looked
    for: GARRICK_MANAGED_PLACES, separated as PATH is, for a test or a Mac
    that keeps it elsewhere; otherwise handoff.py's places on this Mac."""
    given = os.environ.get("GARRICK_MANAGED_PLACES")
    return [Path(p) for p in given.split(os.pathsep) if p] if given is not None else None


def work_folder(zone: Path, parts: tuple) -> Path:
    """Where Claude opens a piece of work: Garrick's own record of it, the
    folder named after it, since that name is what Claude's sidebar shows.
    A project that is one thread opens in the project's folder."""
    project = zone / parts[0]
    if len(parts) == 2:
        return project
    return project if work_name(zone, parts) == parts[0] else project / "Threads" / parts[2]


def files_folder(ws: Path, zone: Path, parts: tuple) -> tuple:
    """(the folder a work's files are in, whether it is the project's own):
    the hub's `folder:`, from the workspace, absolute or from `~/`; or the
    project's folder."""
    hub = zone / parts[0] / (parts[0] + ".md")
    given = hub_value(hub, "folder") if hub.is_file() else ""
    found = handoff().resolve_folder(ws, given) if given else None
    return (found, False) if found is not None else (zone / parts[0], True)


def hub_value(note: Path, key: str) -> str:
    try:
        text = note.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.match(r"\A---\n(.*?)\n---", text, re.S)
    found = re.search(r"(?m)^%s:[ \t]*(.*?)[ \t]*$" % re.escape(key), m.group(1)) if m else None
    return found.group(1).strip().strip("\"'") if found else ""


def record_files(zone: Path, note: Path, parts: tuple, folder: Path) -> list:
    """Garrick's own record of a piece of work, as pathspecs from the zone:
    its note, its project's hub, and the questions in each Needs you folder
    the work keeps. Nothing else of the folder, which holds the user's files."""
    project = zone / parts[0]
    hub = project / (parts[0] + ".md")
    boxes = dict.fromkeys([note.parent / NEEDS] + ([project / NEEDS] if folder == project else []))
    return ([n.relative_to(zone).as_posix() for n in dict.fromkeys([note, hub])]
            + [":(glob)%s/*.md" % b.relative_to(zone).as_posix() for b in boxes])


def commit_record(zone: Path, note: Path, parts: tuple, folder: Path, name: str) -> str:
    """Garrick's own record of the work committed before Claude opens on it,
    so the desktop app's Changes panel has nothing of Garrick's to offer:
    record_files() by name, and only those that changed; anything else in the
    folder is the user's and is left as it is. "" when that went through or
    there was nothing to commit; otherwise why not, for the reply. Nothing is
    put back: the files are the user's."""
    code, said = git(zone, "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all", "--",
                     *record_files(zone, note, parts, folder))
    if code != 0:
        return ""
    changed = [":(literal)" + e[3:] for e in said.split("\0") if len(e) > 3]
    if not changed:
        return ""
    deadline = time.time() + COMMIT_TIMEOUT
    code, why = git(zone, "add", "-A", "--", *changed)
    if code == 0:
        code, why = git(zone, "commit", "-q", "-m", ("%s: saved before opening in Claude" % name)[:200], "--", *changed,
                        timeout=deadline - time.time())
    if code == 0:
        return ""
    git(zone, "reset", "-q", "--", *changed, timeout=10)
    return why if code is None else (why.strip().splitlines() or ["git refused"])[-1]


def continue_work(ws: Path, req: dict, now: Optional[dt.datetime] = None) -> str:
    """Continue: Claude's desktop app opened on a piece of work, already
    oriented. The record committed, a headless call asked where the work
    stands, its session handed to the desktop app; a session continued
    within FRESH_HOURS is resumed as it was, without asking again."""
    H = handoff()
    zone, note, parts, _ = resume_note(ws, req)
    name = work_name(zone, parts)
    if H.managed_off(managed_places()):          # not kept: the page reads the setting at every build
        raise Refused("%s %s" % (H.LOCAL_OFF_TITLE, H.LOCAL_OFF))
    claude = H.find_claude()
    if claude is None:
        raise Refused(H.NO_CLI)
    folder = work_folder(zone, parts)
    with zone_lock(zone):
        unsaved = commit_record(zone, note, parts, folder, name)
    key = "%s/%s" % (zone.name, note.relative_to(zone).as_posix())
    kept = H.session_for(ws, key)
    resume = H.fresh(kept, now) and kept.get("folder") == str(folder)
    try:
        sid = kept["id"] if resume else H.prime(claude, folder, "Where am I on %s?" % name, brief=H.CONTINUE_BRIEF, name=name)[0]
        try:
            H.open_desktop(claude, folder, sid)
        except (H.LocalOff, H.TimedOut):
            raise                               # a timeout may well have opened it: never a second window
        except H.HandOffError:
            if not resume:
                raise
            resume = False                      # the kept session would not open: ask afresh, once
            sid = H.prime(claude, folder, "Where am I on %s?" % name, brief=H.CONTINUE_BRIEF, name=name)[0]
            H.open_desktop(claude, folder, sid)
    except H.LocalOff as e:
        H.mark_local_off(ws, "refused")
        raise Refused(str(e))
    except H.HandOffError as e:
        raise Refused(str(e))
    files, own = files_folder(ws, zone, parts)
    H.keep_session(ws, key, sid, folder, H.walk(files, project=own), primed=not resume, now=now)
    said = "Opened %s in Claude%s" % (name, "" if resume else ". It already knows where it stands")
    return said + ("; Garrick's record of it is not committed: %s" % unsaved if unsaved else "")


def ask_desktop(ws: Path, req: dict) -> dict:
    """Ask something: the user's words asked in the workspace's own folder,
    so Claude reads every piece of work, then that session opened in the
    desktop app. Where the desktop app cannot open it, Claude's answer comes
    back to the page instead, in "answer"."""
    H = handoff()
    prompt = answer(req, "prompt", most=PROMPT_MAX).lstrip("- ")
    if not prompt:
        raise Refused("no prompt given")
    claude = H.find_claude()
    if claude is None:
        raise Refused(H.NO_CLI)
    try:
        sid, said = H.prime(claude, ws, prompt, brief=H.ASK_BRIEF, name=H.session_name(prompt))
    except H.HandOffError as e:
        raise Refused(str(e))
    if not H.managed_off(managed_places()):      # a managed setting is read at every build, never kept
        try:
            H.open_desktop(claude, ws, sid)
            H.clear_local_off(ws)
            return {"say": "Opened Claude on your question. Its answer is waiting there"}
        except H.LocalOff:
            H.mark_local_off(ws, "refused")
        except H.HandOffError as e:
            return {"say": "%s Claude's answer is below." % str(e).rstrip("."), "answer": said[:4000]}
    return {"say": "Claude answered here, since it can't open work on this Mac", "answer": said[:4000]}


def example(ws: Path, req: dict) -> str:
    """The example's Remove and Bring back: System/tools/example.py's
    `archive` and `restore` (#174), which move the Example zone, its shared
    drive and its rows of System/context.md into one recoverable place and
    back. What it says is the reply."""
    do = req.get("do")
    if do not in ("archive", "restore"):
        raise Refused("not something to do with the example: %r" % (do,))
    tool = ws / "System" / "tools" / "example.py"
    if not tool.is_file():
        raise Refused("System/tools/example.py is missing; update Garrick")
    try:
        r = subprocess.run([sys.executable, str(tool), "--root", str(ws), do], capture_output=True, text=True,
                           timeout=COMMIT_TIMEOUT + GIT_TIMEOUT, stdin=subprocess.DEVNULL, cwd=str(ws))
    except subprocess.TimeoutExpired:
        raise Refused("example.py was still running after %s and was stopped" % how_long(COMMIT_TIMEOUT + GIT_TIMEOUT))
    said = (r.stdout if r.returncode == 0 else (r.stderr or r.stdout)).strip().splitlines()
    if r.returncode != 0:
        raise Refused(said[-1] if said else "example.py refused")
    return said[-1].rstrip(".") if said else ("The example is archived. Nothing of yours was touched" if do == "archive"
                                              else "The example is back")
# ---- end of the simple home ------------------------------------------------------


def fix_finding(ws: Path, req: dict) -> str:
    """The Fix button on a `check` chip's finding (#179): Nurture's own
    mechanical fix for the note it names, and nothing else. `nurture.py fix
    --yes --scope <note>` gathers the findings again, so a finding fixed
    meanwhile, or one whose fix it would now hold, is refused in its words
    rather than guessed at; it commits in the zone, one commit, and puts the
    note back when the wall check refuses. GARRICK_HEADLESS=1, as the nightly
    run sets it, keeps it to the kinds registered as unattended and reads
    drift from what drift.py last saved, since the app may not read a cloud
    folder. Run under the zone's lock, as every edit of a zone from the page."""
    zone = zone_dir(ws, req.get("zone"))
    note = live_note(zone, req.get("file"))
    tool = ws / "System" / "tools" / "nurture.py"
    if not tool.is_file():
        raise Refused("System/tools/nurture.py is missing; update Garrick")
    scope = note.relative_to(ws.resolve()).as_posix()
    with zone_lock(zone):
        try:
            r = subprocess.run([sys.executable, str(tool), "--root", str(ws), "fix", "--scope", scope, "--yes", "--json"],
                               capture_output=True, text=True, timeout=COMMIT_TIMEOUT + GIT_TIMEOUT, stdin=subprocess.DEVNULL,
                               cwd=str(ws), env=dict(os.environ, GARRICK_HEADLESS="1"))
        except subprocess.TimeoutExpired:
            raise Refused("nurture.py was still running after %s and was stopped; look at git status in %s"
                          % (how_long(COMMIT_TIMEOUT + GIT_TIMEOUT), zone.name))
    try:
        out = json.loads(r.stdout)
    except ValueError:
        said = (r.stderr or r.stdout).strip().splitlines()
        raise Refused(said[-1] if said else "nurture.py did not answer")
    fixed = [i for i in out.get("fixed") or [] if isinstance(i, dict)]
    if out.get("refused"):
        raise Refused(wall_refusal(ws) or "the zone's wall check refused the commit, so the note is as it was")
    if not fixed:
        held = [str(i.get("held") or "") for i in out.get("held") or [] if isinstance(i, dict) and i.get("held")]
        raise Refused("not fixed: %s" % held[0] if held else "nothing here has a mechanical fix any more; the page rebuilds now")
    return "Fixed: %s" % "; ".join(str(i.get("said") or i.get("line") or "") for i in fixed)


def act(ws: Path, req, today=None, now=None):
    """Carry out one request, or raise Refused. What to say, or, for back
    and stack, a reply whose "say" comes with what the caller reads back."""
    if not isinstance(req, dict) or req.get("verb") not in VERBS + CMUX_VERBS:
        raise Refused("unknown action")
    refuse_undeclared(ws, req)      # before anything reads the request's own fields
    if req["verb"] in CMUX_VERBS:
        cmux_desk()                 # the cmux extra and cmux itself, before anything else
        return cmux_act(ws, req)
    if req["verb"] == "run":
        return run_job(req)
    if req["verb"] == "settings":
        return save_settings(ws, req)
    if req["verb"] in ("park", "wake"):
        return park(ws, req, today or dt.date.today())
    if req["verb"] == "interrupt":
        now = now or dt.datetime.now().replace(second=0, microsecond=0)
        return interrupt(ws, req, dt.datetime.combine(today, now.time()) if today else now)
    if req["verb"] == "back":
        return back(ws, req)
    if req["verb"] == "stack":
        return show_stack(ws)
    if req["verb"] == "unstack":
        return unstack(ws, req)
    if req["verb"] == "todo-add":
        return todo_add(ws, req)
    if req["verb"] == "answer":
        return answer_question(ws, req, today or dt.date.today())
    if req["verb"] == "later":
        return put_off(ws, req, today or dt.date.today())
    if req["verb"] == "continue":
        return continue_work(ws, req, now)
    if req["verb"] == "ask-desktop":
        return ask_desktop(ws, req)
    if req["verb"] == "example":
        return example(ws, req)
    if req["verb"] == "fix":
        return fix_finding(ws, req)
    if req["verb"] in ("new-project", "new-thread", "check-name", "rename", "delete", "undo"):
        return manage(ws, req)
    return todo(ws, req)


def perform(ws: Path, req, ops=None):
    """One request, as a click sends it and as the ask box does: through the
    durable record where operations.py keeps one for its verb, so that a
    request repeating one the record holds is joined, answered or asked
    about (operations.start()) rather than done again. Never raises.

    Returns (the reply, what the audit log says in place of its sentence or
    None, and the refusal or the fault in its own words, "" when there was
    none, for a caller that words a failure itself, as the ask box does)."""
    global CURRENT
    out, logged, run, outcome, why = None, None, None, None, ""
    try:
        try:
            joined = None
            if ops is not None and isinstance(req, dict) and req.get("verb") in ops.OPS:
                try:
                    run, joined = ops.start(jobs_dir(), req)
                except ops.BadOp as e:
                    raise Refused(str(e))
                except Exception:           # the record is best effort, as the audit log is
                    run = joined = None
            if joined is not None:
                out = joined                # under way, just saved, or asked whether it is meant again
                logged = "%s (%s)" % (joined["say"], joined["state"])
            else:
                CURRENT = run
                done = act(ws, req)
                outcome = "saved"
                if isinstance(done, dict):
                    logged = done.pop("logged", None)
                    out = dict({"ok": True}, **done)
                else:
                    out = {"ok": True, "say": done}
        except Refused as e:
            out = {"ok": False, "say": str(e)}
            outcome, why = "refused", str(e)
        except Exception as e:          # a fault still answers in JSON, and is logged
            out = {"ok": False, "say": "that did not work: %s: %s" % (type(e).__name__, e)}
            outcome, why = "crashed", "%s: %s" % (type(e).__name__, e)
        if run is not None and outcome is not None:
            out = run.finish(outcome, req, why=why, said=out["say"] if outcome == "saved" else "")
    finally:
        CURRENT = None
        if run is not None:
            run.close(req)              # a terminal record, whatever stopped us, then the lock
    return out, logged, why


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Do what a status page button asks, reading one JSON request on stdin.")
    ap.add_argument("--workspace", required=True)
    args = ap.parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve()
    req, logged = None, None
    try:
        if not (ws / "System" / "rules.md").is_file() or not (ws / "Zones").is_dir():
            raise Refused("not a Garrick workspace")
        try:
            req = json.loads(sys.stdin.read())
        except ValueError:
            raise Refused("not a request")
        ops = ops_lib(ws)
        if ops is not None and isinstance(req, dict) and req.get("verb") == JOURNAL_VERB:
            print(json.dumps(ops.read(jobs_dir()), ensure_ascii=False))     # a read: nothing to log
            return 0
        out, logged, _ = perform(ws, req, ops)
    except Refused as e:
        out = {"ok": False, "say": str(e)}
    except Exception as e:              # a fault still answers in JSON, and is logged
        out = {"ok": False, "say": "that did not work: %s: %s" % (type(e).__name__, e)}
    audit(req, out["ok"], logged or out["say"])
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
