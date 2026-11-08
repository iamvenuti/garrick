#!/usr/bin/env python3
"""page_action.py: what the status page's action buttons do.

    echo '{"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "…"}' | \\
        python3 page_action.py --workspace ~/Garrick

Garrick.app, or the Obsidian plugin beside this file, runs it when a button
on the page asks; nothing else can, because a browser has no way to reach it.
The ask preview (ask.py) runs what it proposes through perform(), the same
check and the same record. A session runs it too (#344), with the verb and its
options in place of JSON, and reads the sentence it prints:

    python3 System/status/page_action.py park --zone Work --project Acme --thread Pricing

So one action has one executor, whoever asks: the stale check, the zone lock,
the commit with the wall check, the record, and, as
the last step of an action that changed what the page shows, one request for
the page (ask_for_page).
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
    move        a thread to another project of its zone, every link to it
                following, in one commit: {"zone", "project", "thread", "to"}
    delete      without "confirm", what would go; with "confirm" naming it,
                gone in one commit: {"zone", "project", "thread"?, "confirm"?}
    undo        a rename or deletion, while it is the zone's last commit:
                {"zone", "commit"}
                These six run System/tools/scaffold.py and nothing else, so
                the page, the voice command and the script make the same
                folders, notes and commits.
    settings    which ways to open a thread the page offers, and which one
                clicking a thread's name runs: {"launchers": ["note", "cmux"],
                "default": "cmux"}, with "preview" for whether Explore's cards
                offer Preview, which is never the default; each zone's colour
                and icon: {"zones": {"Work": {"color": "Teal", "icon":
                "briefcase"}}}; or both. Settings › Graph colours: {"graph":
                {"project": "Teal"}}, a colour for each kind of note Explore
                draws, the whole section; a kind left out keeps its default.
                Kept in System/garrick-settings.json, committed with the
                workspace, so the app, Obsidian and the cmux desk agree. A zone
                whose colour changed has its open cmux workspace recoloured,
                when the cmux extra and cmux are there. Settings ›
                Notifications: {"notifications": {"tell": {...}, "after": 2,
                "quiet": {...}}}, which notices this Mac shows, checked and
                kept by System/tools/notifications.py.
                Settings › While you wait: {"while-you-wait": {...}},
                checked by System/tools/next_up.py. Settings › Home:
                {"home": "simple"} or "full", the page Garrick opens on.
                Settings › Memory: {"memory": {...}}, how pages fade out
                of the wikis (#108), checked here against the shape
                System/tools/fade.py keeps; saving moves no page.
                {"desk-agent": "codex"}, which assistant a cmux tab starts,
                written by the cmux extra's desk.py into System/desk.json
    release-check  Settings › About Garrick's Check for updates (#410):
                release.py latest --now, the click being the consent for that
                one request; says what it found and whether this workspace
                may be updated. It changes no workspace file but the kept answer
    release-update  the update to the release the check found, after it:
                release.py update --tag <that release> --apply, and only when
                the running version is older than it by semantic comparison;
                a build that is not older, or that cannot be read, is refused
                with the reason. The report comes back as counts and lists
    memory-preview  what Settings › Memory's unsaved values would do now:
                {"memory": {...}}; System/tools/fade.py's counts() for
                them, per wiki, as "counts", and, from a fade.py with
                preview(), the first pages that would move and those
                active work keeps, as "preview". It only reads
    answer      a Needs you question answered by one of its options (#175):
                {"zone", "file", "label"}; the work's Next action becomes
                what the option leads to, with a dated entry, the question
                says answered, and both are committed in one commit
    question-answer  a wiki question answered in the user's own words (#224):
                {"wiki", "file", "words"}. The words are filed first, word for
                word, as Wikis/<Wiki>/raw/answers/<YYMMDD> - <slug>.md, with
                the question and the date; only then does the question say
                answered and point at that record. Nothing else is written,
                no page is changed (the meetings and knowledge skills do that,
                see question-work), and nothing is committed
    question-later   a wiki question put off to a day: {"wiki", "file", "until"}
    question-close   a wiki question with nothing to work in: {"wiki", "file"}
    question-open-sections  the lines under a page's *Open* or *Open issues*
                heading as questions (#224, point 8): {"wiki", "confirm"?,
                "pages"?}. Without confirm: read only, the lines that would
                become a question file and the pages that cannot, with why.
                With "confirm": true: one question file per line, the page as
                origin and pages, its zone and parties copied exactly (a
                Knowledge question has neither). No page is changed
    question-decide  Record as a decision (#224, point 5): {"wiki", "file", "words"}.
                One transaction writes the words as the raw answer, word for
                word, then the decision page Wikis/Meetings/wiki/decisions/
                <YYMMDD> - <slug>.md with status: valid, the same zone and
                parties as the question, and the words under Decision; the
                question then says answered and points at both. Meetings
                only: a question with no zone or parties is refused. The
                status of a decision is never changed by any other verb
    question-work    read only: the pages an answered question may change, and
                the record to cite. A page walled from the question's parties
                is left out and the wall sentence said; a question whose
                pages sit on both sides of a wall is refused with it
    question-done    an answered question marked done once its pages are worked in
    later       "Not now": {"zone", "file", "until"?}; the question put off
                to tomorrow, or to the day `until` names, and committed
    continue    a piece of work opened in Claude's desktop app, already
                oriented: {"zone", "file"}, its note. The simple home's
                Continue and, since #180, every Open in Claude on a thread
                (the Threads card, the graph's panel, the app's menu and
                panel). Its own record is committed, a headless `claude -p`
                asks "Where am I on <it>?" (say_name()), and that session
                opens with `claude --desktop --resume`, under a
                pseudo-terminal (handoff.py, beside this file)
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
    files       where a piece of work's files live (#189), from its page:
                {"zone", "file", "do"}, do one of copy, refresh, media-in,
                media-out, move, undo, keep-copy, delete-copy. A copy and
                moved files are kept in the project's Files/ folder, with a
                history of their own (work_files.py, beside this file); the
                hub's `storage:`, the project's .gitignore and its Claude
                settings are committed by name, and put back if refused. A
                copy or a move that Stop ends, or that fails, leaves nothing
                behind, and nothing leaves the user's folder until every file
                is copied and checked
    files-stop  Stop, while a copy or a move is still copying and checking
    files-progress  how far one has got; it only reads
    work-file   a moved file opened, the work's Files/ folder in Finder, or
                an earlier version opened to read or saved as a separate file:
                {"zone", "file", "do", "path"?, "version"?, "to"?}
    note-read   a note drawn for Explore's Preview (#206): {"path"}, from the
                workspace's folder, a .md file inside Zones/ or Wikis/ once
                every link is followed; "title" and "html", guide.py's
                rendering, in the reply, or why not, with "missing" for a
                note that is not there. It only reads
    note-open   that note opened in the app the Mac uses for a .md file:
                {"path"}; the same checks, and nothing written

What a Todo verb says it did is the line's text without its Markdown links,
cut to SAID_TEXT characters: the link back to a meeting belongs in Todo.md,
not in a toast. A batch that saved says "Saved 3". Any action whose commit the
zone's wall check refused, from a click or the ask box, ends on the rule's own
sentence, operations.py's WALL_REFUSAL, word for word, and says nothing of
what the check found (#107, #172): a tick, a date, a new line, park and wake,
an answer, a new project or thread, a rename or a deletion.
Every helper that commits takes that sentence as `wall`, with no default, so a
verb added later cannot forget it. A refusal for any other reason still says
why.

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
row at once; the app does the same for each action the ask box ran. The line
ends with who asked, `page`, `ask` or `session`, and so does the record. The
reply is one line of JSON: {"ok": true|false, "say": "…"}; an action that asked for the page also says "built":
true, and then the host does not rebuild a second time. Standard library only.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import html
import importlib.util
import inspect
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Optional

try:
    import fcntl
except ImportError:             # not on Windows, where the status app does not run
    fcntl = None

sys.dont_write_bytecode = True
VERBS = ("todo-done", "todo-undo", "todo-date", "todo-add", "park", "wake", "run", "settings",
         "new-project", "new-thread", "check-name", "rename", "move", "delete", "undo",
         "answer", "later", "question-answer", "question-later",
         "question-close", "question-decide", "question-open-sections", "question-work", "question-done", "continue", "ask-desktop", "example", "fix",
         "discover", "suggestion", "start", "stop-using", "bring-back", "files", "files-stop", "files-progress",
         "work-file", "memory-preview", "note-read", "note-open", "release-check", "release-update",
         "nurture-answer", "nurture-organisation", "nurture-correct", "nurture-save", "nurture-save-all", "party-flag")
SKIP = {"archive", "_template", ".git", ".obsidian", ".trash"}
# The ways to open a thread Settings lists: the note's own link, Explore's Preview (#219),
# which is switched on and off with them but opens nothing, then status.py's LAUNCHERS.
LAUNCHERS = ("note", "preview", "finder", "cmux", "codex", "claude")
DESK_AGENTS = ("claude", "codex")      # which assistant a cmux tab starts: cmuxlib's AGENTS
# What Settings › Zones offers: cmux's named colours and status.py's ZONE_ICONS.
ZONE_COLOURS = ("Red", "Crimson", "Orange", "Amber", "Olive", "Green", "Teal", "Aqua", "Blue", "Navy", "Indigo",
                "Purple", "Magenta", "Rose", "Brown", "Charcoal")
# What Settings › Graph colours offers (#291): the same, less the three a ring on the graph uses; status.py's
# GRAPH_OFF. A kind is one of status.py's KINDS, or one found from a wiki's pages, which is named by its type
# as status.py's found_kind() names it: lower case, of letters, digits, spaces, hyphens and underscores, neither
# starting with an underscore nor longer than its FOUND_KIND_MAX. This request cannot see the pages, so it holds
# a found kind to that shape; a kind no page has is never drawn.
GRAPH_OFF = ("Red", "Crimson", "Amber")
GRAPH_KINDS = ("project", "thread", "note", "meeting", "mail", "person", "source", "concept", "entity", "decision")
GRAPH_FOUND = re.compile(r"[^\W_][\w -]{0,59}")
# Settings › Home: which the page opens on. Its words are status.py's HOMES too.
HOMES = ("simple", "full")
# Settings › About Garrick: how often, in days, the check for a newer Garrick runs (garrick_lib's RELEASE_CADENCES).
RELEASE_CADENCES = (1, 7)
ZONE_ICONS = ("briefcase", "house", "flask", "rocket", "book", "globe", "heart", "star", "leaf", "wrench", "chart", "shield")
# What the audit log may name of a request, and how much of a new line's text.
LOGGED = ("zone", "file", "project", "thread", "folder", "key", "keys", "date", "target", "job", "launchers", "default", "zones", "graph",
          "name", "party", "kind", "to", "confirm", "commit", "test", "find-chat", "home", "label", "until",
          "do", "id", "answer", "suggested", "path", "version", "agent", "wiki")       # never "token"
LOGGED_TEXT = 60
LOGGED_SAY = 160
# What a Todo verb says it did: the line's text, no longer than this, and
# without its Markdown links (#107). The most lines one batch may name.
SAID_TEXT = 60
KEYS_MAX = 50
MDLINK = re.compile(r"!?\[([^\]]*)\]\([^)\s]*\)")
WIKILINK = re.compile(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]")
# One line of what the zone's wall check prints when it refuses a commit:
# check.py's report_staged(), as the pre-commit hook runs it. WALL_IN finds
# it inside a longer line, as scaffold.py folds git's output into its refusal.
# Each ends with the fix for its kind of finding, and every fix says "commit again".
WALL_LINE = re.compile(r"^Commit refused: .+\. [^.\n]*\bcommit again\b")
WALL_IN = re.compile(r"(?:^|\s)Commit refused: .+?\. [^.\n]*\bcommit again\b")
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


class KeepRecord(Refused):
    """A refusal that leaves what was filed where it is: the user's own words
    are evidence, so a transaction does not take them away when the question
    that cites them could not be updated."""


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


def audit(req, ok: bool, say: str, via: str = "page") -> None:
    """One line in page-actions.log for every request: what it asked and what
    came of it, and who sent it, `page`, `ask` or `session` (#344), last. A log
    that cannot be written never stops the action."""
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


# Git's repository-local variables, for when garrick_lib cannot be loaded.
_REPO_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
              "GIT_COMMON_DIR", "GIT_PREFIX", "GIT_NAMESPACE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
              "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS")


def own_repo_env(zone: Path) -> dict:
    """The environment git runs in: this process's own without the variables
    that point git at another repository or hand it other settings (hooks
    included), so the zone's own repository and hooks are what act. From
    garrick_lib where the workspace has the helper, else by a fixed list."""
    lib = None
    try:
        found = prefs()
        lib = found.lib(zone.parent.parent) if callable(getattr(found, "lib", None)) else None
    except Exception:
        lib = None
    if lib is not None and callable(getattr(lib, "own_repo_env", None)):
        try:
            return lib.own_repo_env()
        except Exception:
            pass
    env = {k: v for k, v in os.environ.items() if k not in _REPO_VARS and not re.match(r"GIT_CONFIG_(KEY|VALUE)_\d+$", k)}
    return env


WALL_HOOK_MARK = "Garrick wall check"       # garrick_lib's, which this file may not be able to load


def commit_refusal(zone: Path) -> Optional[str]:
    """Why a commit in the zone would not run Garrick's wall check, or None.
    Fail-closed: git, in the cleaned environment, must find the repository at
    <zone>/.git, and the hooks folder it will use (core.hooksPath from any
    layer of config included) must hold an executable pre-commit with the
    wall check's mark."""
    env = own_repo_env(zone)

    def ask(*a):
        try:
            return subprocess.run(["git", "-C", str(zone)] + list(a), env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
    r = ask("rev-parse", "--absolute-git-dir")
    try:        # the same directory, not the same spelling: a case-insensitive disk opens `work` as `Work`
        same = r is not None and r.returncode == 0 and (zone / ".git").is_dir() \
            and os.path.samefile(r.stdout.strip(), str(zone / ".git"))
    except OSError:
        same = False
    if not same:
        return "%s has no git repository of its own here" % zone.name
    if zone.parent.name != "Zones":
        return None             # the workspace's own repository (a heard name in context.md) has no wall hook by design
    r = ask("rev-parse", "--git-path", "hooks")
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return "git did not say which hooks %s would run" % zone.name
    hooks = Path(r.stdout.strip())
    hooks = hooks if hooks.is_absolute() else zone / hooks
    try:
        if WALL_HOOK_MARK in (hooks / "pre-commit").read_text(encoding="utf-8", errors="replace") \
                and os.access(hooks / "pre-commit", os.X_OK):
            return None
    except OSError:
        pass
    return "commits in %s would not run the wall check: git would take its hooks from %s" % (zone.name, hooks)


def git(zone: Path, *args, timeout: float = None):
    """One git command in the zone: (exit code, what it said). It runs in a
    process group of its own, so a hook that hangs, or a signing key waiting
    for its passphrase, is stopped with it when the time is up: politely
    first, so git takes away its own index.lock. Past the time, the code is None."""
    timeout = GIT_TIMEOUT if timeout is None else timeout
    try:
        p = subprocess.Popen(["git", "-C", str(zone)] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True, env=own_repo_env(zone))
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


def committing(zone: Path, rel, message: str) -> tuple:
    """Add and commit `rel`, one path from the zone or a list of them, and
    nothing else, within COMMIT_TIMEOUT: (exit code, why not). The code is
    None when the commit was stopped while its hooks ran: the wall check had
    found nothing wrong yet. A path that is gone is committed as gone."""
    rels = [rel] if isinstance(rel, str) else list(rel)
    deadline = time.time() + COMMIT_TIMEOUT
    problem = commit_refusal(zone)
    if problem:
        return 1, "%s, so nothing was committed" % problem
    code, said = git(zone, "add", "-A", "--", *rels)
    if code == 0:
        note_event("phase", "checking")         # the wall check runs inside git commit
        code, said = git(zone, "commit", "-q", "-m", message, "--", *rels, timeout=deadline - time.time())
        if code is None:
            return None, "the wall check was still running after %s and was stopped" % how_long(COMMIT_TIMEOUT)
    if code != 0:
        why = said.strip().splitlines() if code is not None else [said]
        return code or 1, why[-1] if why else "git refused"
    return 0, ""


def commit(zone: Path, note: Path, before: bytes, message: str, *, wall: Optional[str]) -> None:
    """Commit the one file, or put it back as it was and say why. Put back
    only if it still holds what this request wrote: an edit made meanwhile,
    in Obsidian say, is left alone. `wall` is the sentence a refusal by the
    zone's wall check ends on, in place of what the check printed: always
    wall_refusal(ws), which is None only without operations.py."""
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
        commit(zone, note, before, message[:200], wall=wall_refusal(ws))
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
        commit(zone, note, before, ("%s: added to %s, %s" % (zone.name, section, said))[:200], wall=wall_refusal(ws))
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
        commit(zone, note, before, "%s: %s" % (name, status if status == "parked" else "woken"), wall=wall_refusal(ws))
        return said


def note_status(note: Path) -> str:
    """A note's `status:`, lower-cased, as front() reads it; "" where it has
    none. This is the fingerprint operations.py declares for park and wake."""
    return front(note).get("status", "")


def dated_entry(body: str, today: dt.date, said: str) -> str:
    """The body with a dated entry added, newest first: below the Resume here
    block's rule, or, with no block, under ## State of play. Neither: as it
    was. Park's copy of this moved into System/tools/scaffold.py, whose own
    one it joined; this stays for `answer`, which no tool writes.
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


ANSWER_MAX = 400
ROW_RE = r"(?m)^\|\s*%s\s*\|.*$"


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
            if callable(getattr(mod, "clean", None)):
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


# Settings › Memory (#108). System/tools/fade.py, the workspace's own, owns
# graded oblivion: its settings() keeps what is saved merged over its
# defaults, and counts() says what a set of them would do now. What the page
# sends is checked here against the shape fade.py keeps, so a malformed form
# is refused by name before anything is written or counted; the months and
# their order are judged here too, and fade.py may judge more.
_FADE = {}
MEMORY_WIKIS = ("Meetings", "Knowledge")
MEMORY_PINS = ("thread", "project", "todo", "pinned")
MEMORY_REACH = ("working", "dormant")
MEMORY_MONTHS = (1, 240)
MEMORY_MIN = (1, 1000)
MEMORY_WORDS = 60          # the longest type or domain a kind may list, and a kind's name


@contextlib.contextmanager
def tools_path(ws: Path):
    """The workspace's System/tools/ first on the path while fade.py is
    loaded or asked; the path and the modules it imported put back after."""
    path, before = list(sys.path), set(sys.modules)
    sys.path.insert(0, str(ws / "System" / "tools"))
    try:
        yield
    finally:
        sys.path[:] = path
        for k in set(sys.modules) - before:
            sys.modules.pop(k, None)


def fade_lib(ws: Path):
    """The workspace's own System/tools/fade.py, or None: never one beside
    this extra, since what it counts is that workspace's pages."""
    key = Path(ws)
    if key not in _FADE:
        found, src = None, key / "System" / "tools" / "fade.py"
        if src.is_file():
            name = "garrick_page_fade"
            try:
                with tools_path(key):
                    spec = importlib.util.spec_from_file_location(name, str(src))
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[name] = mod
                    spec.loader.exec_module(mod)
                if callable(getattr(mod, "settings", None)) and callable(getattr(mod, "counts", None)):
                    found = mod
            except Exception:
                found = None
        _FADE[key] = found
    return _FADE[key]


def clean_memory(value) -> dict:
    """Settings › Memory as the page sends it, checked: the keys fade.py
    keeps and nothing else, each of its shape. Refused with the reason."""
    if not isinstance(value, dict):
        raise Refused("Memory's settings are not an object")
    known = ("wikis", "kinds", "pins", "wake", "reach", "nightly")
    unknown = sorted(set(value) - set(known))
    if unknown:
        raise Refused("Memory has no setting called %s" % ", ".join(repr(k) for k in unknown))
    flag = lambda v: isinstance(v, bool)
    count = lambda v, low, high: isinstance(v, int) and not isinstance(v, bool) and low <= v <= high
    out = {}
    if "wikis" in value:
        w = value["wikis"]
        if not isinstance(w, dict) or set(w) - set(MEMORY_WIKIS) or not all(flag(v) for v in w.values()):
            raise Refused("which wikis fade is Meetings and Knowledge, each on or off")
        out["wikis"] = dict(w)
    if "kinds" in value:
        kinds = value["kinds"]
        if not isinstance(kinds, dict):
            raise Refused("Memory's kinds are not an object")
        out["kinds"] = {}
        for name, k in kinds.items():
            if not isinstance(name, str) or not name.strip() or len(name) > MEMORY_WORDS:
                raise Refused("a kind needs a name of at most %d characters" % MEMORY_WORDS)
            if not isinstance(k, dict) or set(k) - {"wiki", "types", "domains", "dormant", "archived"}:
                raise Refused("the kind %s takes wiki, types, domains, dormant and archived" % name)
            if k.get("wiki") not in MEMORY_WIKIS:
                raise Refused("the kind %s belongs to Meetings or Knowledge" % name)
            if not count(k.get("dormant"), *MEMORY_MONTHS):
                raise Refused("the kind %s goes dormant after %d to %d months" % ((name,) + MEMORY_MONTHS))
            if "archived" not in k or not (k["archived"] is None or count(k["archived"], *MEMORY_MONTHS)):
                raise Refused("the kind %s is archived after %d to %d months, or never" % ((name,) + MEMORY_MONTHS))
            if k["archived"] is not None and k["archived"] < k["dormant"]:
                raise Refused("the kind %s cannot be archived before it goes dormant" % name)
            lists = {}
            for key in ("types", "domains"):
                got = k.get(key, [])
                if not isinstance(got, list) or not all(isinstance(x, str) and len(x.strip()) <= MEMORY_WORDS for x in got):
                    raise Refused("the kind %s lists its %s as words" % (name, key))
                lists[key] = list(dict.fromkeys(x.strip() for x in got if x.strip()))
            out["kinds"][name] = {"wiki": k["wiki"], "types": lists["types"], "domains": lists["domains"],
                                  "dormant": k["dormant"], "archived": k["archived"]}
    if "pins" in value:
        pins = value["pins"]
        if not isinstance(pins, dict) or set(pins) - set(MEMORY_PINS) or not all(flag(v) for v in pins.values()):
            raise Refused("what pins a page is %s, each on or off" % ", ".join(MEMORY_PINS))
        out["pins"] = dict(pins)
    if "wake" in value:
        if not flag(value["wake"]):
            raise Refused("whether use wakes a page is on or off")
        out["wake"] = value["wake"]
    if "reach" in value:
        if value["reach"] not in MEMORY_REACH:
            raise Refused("search reaches working pages, or working and dormant ones")
        out["reach"] = value["reach"]
    if "nightly" in value:
        night = value["nightly"]
        if not isinstance(night, dict) or set(night) - {"on", "min"} or ("on" in night and not flag(night["on"])) \
                or ("min" in night and not count(night["min"], *MEMORY_MIN)):
            raise Refused("the nightly line is on or off, from %d to %d pages" % MEMORY_MIN)
        out["nightly"] = dict(night)
    return out


COUNT_KEYS = ("on", "working", "dormant", "archived", "to_dormant", "to_archive", "to_wake")


def memory_preview(ws: Path, req: dict) -> dict:
    """What Settings › Memory's unsaved values would do now: fade.py's counts
    for them, merged over what is saved, a key at a time, and, where its
    fade.py has preview(), the pages behind them (#205): per wiki, the first
    that would move, with where to and why, and the first active work keeps.
    One plan either way. Reads only."""
    lib = fade_lib(ws)
    if lib is None:
        raise Refused("cannot find System/tools/fade.py; update Garrick")
    chosen = clean_memory(req.get("memory") if "memory" in req else {})
    with tools_path(ws):
        memory = dict(lib.settings(ws), **chosen)
        if not callable(getattr(lib, "preview", None)):
            return {"say": "Counted", "counts": lib.counts(ws, memory=memory)}
        preview = lib.preview(ws, memory=memory)
    counts = {w: {k: v for k, v in c.items() if k in COUNT_KEYS} for w, c in preview.items()}
    return {"say": "Counted", "counts": counts, "preview": preview}


# ---- Settings › About Garrick: Check for updates (#410) -----------------------------
# The only network this file reaches is release.py's own: `latest --now` for the
# question and `update --apply` for the update, both started by a click. The
# update is applied only when the running release is older than the newest by
# semantic comparison (release.py's state()), and a failed or partial answer
# never starts it. Nothing scheduled calls `update`.
RELEASE_ASK_TIMEOUT = 60
RELEASE_UPDATE_TIMEOUT = 900          # a download, then the update's own check and a commit in each repository


def release_run(ws: Path, *args, timeout: float):
    tool = ws / "System" / "tools" / "release.py"
    if not tool.is_file():
        raise Refused("System/tools/release.py is missing; update Garrick")
    try:
        return subprocess.run([sys.executable, str(tool), "--root", str(ws), *args], capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL, cwd=str(ws))
    except subprocess.TimeoutExpired:
        raise Refused("release.py was still running after %s and was stopped" % how_long(timeout))


def release_state(ws: Path, *args) -> dict:
    r = release_run(ws, "latest", *args, "--json", timeout=RELEASE_ASK_TIMEOUT)
    try:
        found = json.loads(r.stdout)
    except ValueError:
        raise Refused("release.py did not answer; update Garrick" if r.stderr else "release.py did not answer")
    if not isinstance(found, dict):
        raise Refused("release.py did not answer")
    return found


def release_words(state: dict) -> dict:
    """The reply for a question: the line under the button, and the facts."""
    out = {"state": "failed", "running": state.get("running", ""), "latest": state.get("latest", ""),
           "asked": state.get("asked", "")}
    if state.get("failed"):
        out["line"] = "Could not ask GitHub (%s). Nothing was changed." % str(state["failed"]).rstrip(".")
    elif state.get("newer"):
        out.update(state="newer", line="Garrick %s is out; this workspace runs %s." % (state["latest"], state["running"]))
    elif state.get("why"):
        out.update(state="current" if state.get("running") else "unknown", line="%s." % state["why"])
    else:
        out["line"] = "Could not tell which release is newest. Nothing was changed."
    return out


def release_check(ws: Path) -> dict:
    """Check for updates: ask GitHub now, on this click, and say what it found."""
    state = release_state(ws, "--now")
    out = release_words(state)
    return {"say": out["line"], "release": out}


def release_notes_url(state: dict) -> str:
    url = str(state.get("url") or "")
    return url if url.startswith("https://github.com/") else ""


def release_update(ws: Path) -> dict:
    """The update itself, after a check found a newer release: read what it
    would change, then make the changes, and report in the update's own
    terms. Refuses, with the reason, unless the running release is older."""
    state = release_state(ws)
    if not state.get("update"):
        out = release_words(state)
        if state.get("tag") and not state.get("newer") and not state.get("failed") and not state.get("why"):
            out["line"] = "Garrick %s is the newest release, and this workspace runs %s. Nothing was changed." % (
                state.get("latest"), state.get("running") or "an unrecorded release")
        else:
            out["line"] += " Nothing was updated."
        return {"say": out["line"], "release": dict(out, state="refused" if out["state"] == "newer" else out["state"])}
    tag = str(state["tag"])
    plan = release_run(ws, "update", "--tag", tag, "--json", timeout=RELEASE_UPDATE_TIMEOUT)
    try:
        planned = json.loads(plan.stdout) if plan.returncode == 0 else None
    except ValueError:
        planned = None
    if not isinstance(planned, dict):
        why = (plan.stderr or plan.stdout).strip().splitlines()
        line = "The update did not start: %s" % (why[-1].rstrip(".") + "." if why else "release.py gave no report.")
        return {"say": line, "release": {"state": "failed", "line": line + " Nothing was changed.",
                                         "running": state["running"], "latest": state["latest"]}}
    split = [str(x) for x in (planned.get("actions") or {}).get("split") or []]
    r = release_run(ws, "update", "--tag", tag, "--apply", "--json", timeout=RELEASE_UPDATE_TIMEOUT)
    try:
        result = json.loads(r.stdout)
    except ValueError:
        result = None
    if not isinstance(result, dict):
        why = (r.stderr or r.stdout).strip().splitlines()
        line = "The update stopped: %s" % (why[-1].rstrip(".") + "." if why else "release.py gave no report.")
        return {"say": line, "release": {"state": "stopped", "line": line, "running": state["running"],
                                         "latest": state["latest"], "split": split}}
    done = result.get("done") if isinstance(result.get("done"), dict) else {}
    names = lambda kind: [str(x) for x in done.get(kind) or []]
    skipped = [[str(a), str(b)] for a, b in (x for x in result.get("skipped") or [] if isinstance(x, (list, tuple)) and len(x) == 2)]
    problems = [str(x) for x in result.get("problems") or []]
    out = {"running": state["running"], "latest": state["latest"], "url": release_notes_url(state),
           "replaced": len(names("replace")) + len(names("restore")), "added": len(names("add")), "new": names("merge"),
           "split": split, "skipped": skipped, "then": [str(x) for x in result.get("then") or []],
           "problems": problems, "commits": [str(x) for x in result.get("commits") or []]}
    if problems or result.get("unstamped"):
        out["state"] = "stopped"
        out["line"] = ("The update stopped: the check found errors in the files it wrote, so the version stamp is not moved. "
                       "git revert of the update commit in each repository undoes it." if problems else
                       "The update stopped: %s. Run it again to record the version." % str(result.get("unstamped")).rstrip("."))
    else:
        out["state"] = "updated"
        out["line"] = "Updated to %s from %s." % (state["latest"], state["running"])
    return {"say": out["line"], "release": out}


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
    {"home": "simple"} or "full", which the page opens on (#175).
    {"graph": {"project": "Teal"}}, Settings › Graph colours (#291).
    {"desk-agent": "claude"} or "codex", which assistant a cmux tab starts,
    is the cmux extra's own setting: the desk writes it in System/desk.json
    (#279), and it is refused without the extra and cmux."""
    if not {"launchers", "zones", "graph", "notifications", "while-you-wait", "home", "memory", "desk-agent",
            "release-notice", "release-notice-every"} & set(req):
        raise Refused("nothing to save")
    if "desk-agent" in req and req["desk-agent"] not in DESK_AGENTS:
        raise Refused("a cmux tab starts %s, not %r" % (" or ".join(DESK_AGENTS), req["desk-agent"]))
    new = {}
    if "release-notice" in req:
        if not isinstance(req["release-notice"], bool):
            raise Refused("the check for a newer Garrick is on or off")
        new["release-notice"] = req["release-notice"]
    if "release-notice-every" in req:
        days = req["release-notice-every"]
        if not (isinstance(days, int) and not isinstance(days, bool) and days in RELEASE_CADENCES):
            raise Refused("the check for a newer Garrick runs every %s days" % " or ".join(str(d) for d in RELEASE_CADENCES))
        new["release-notice-every"] = days
    if "home" in req:
        if req["home"] not in HOMES:
            raise Refused("no home called %r; it is %s" % (req["home"], " or ".join(HOMES)))
        new["home"] = req["home"]
    if "launchers" in req:
        on, default = req.get("launchers"), req.get("default", "note")
        if not isinstance(on, list) or not all(isinstance(k, str) for k in on) or len(set(on)) != len(on):
            raise Refused("not a list of ways to open a thread")
        unknown = [k for k in on if k not in LAUNCHERS]
        if unknown:
            raise Refused("no way to open a thread called %s" % ", ".join(repr(k) for k in unknown))
        if default not in LAUNCHERS:
            raise Refused("no way to open a thread called %r" % (default,))
        if default == "preview":
            raise Refused("Preview reads a note and opens nothing, so it cannot be what clicking a thread does")
        if default != "note" and default not in on:
            raise Refused("the default must be one of the ways switched on")
        new = {"launchers": {k: k in on for k in LAUNCHERS}, "default": default}
    if "zones" in req:
        new["zones"] = zone_styles(ws, req["zones"])
    if "graph" in req:
        new["graph"] = graph_styles(req["graph"])
    if "notifications" in req:
        notify = notifications_lib(ws)
        if notify is None or not hasattr(notify, "TELL"):
            raise Refused("cannot find System/tools/notifications.py, or it is older than this page; update Garrick")
        try:
            new["notifications"] = notify.clean(req["notifications"])
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
    if "memory" in req:
        if fade_lib(ws) is None:
            raise Refused("cannot find System/tools/fade.py; update Garrick")
        new["memory"] = clean_memory(req["memory"])
    keep = prefs()
    keep.migrate(ws)             # a choice an older Garrick left in System/generated/ comes first
    was = keep.read(ws).get("zones")
    before = was if isinstance(was, dict) else {}
    if "desk-agent" in req:             # first: a desk that refuses leaves every other choice unsaved
        run_desk(ws, "agent", req["desk-agent"], timeout=20)
    if new:
        try:
            keep.save(ws, new)
        except ValueError as e:         # a garrick_lib older than the choice: "not a kept choice: home"
            raise Refused("%s; update Garrick to keep it" % e)
    if "home" in new and set(new) == {"home"} and "desk-agent" not in req:
        return "Garrick now opens on %s" % ("the simple home" if new["home"] == "simple" else "the full page")
    if "zones" in new:
        colour = lambda zones, z: zones.get(z, {}).get("color") if isinstance(zones.get(z), dict) else None
        changed = sorted(z for z in set(before) | set(new["zones"]) if colour(before, z) != colour(new["zones"], z))
        if changed:
            recolour(ws, changed)
    return "Settings saved"


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


def graph_styles(given) -> dict:
    """Settings › Graph colours as the page sends it, every kind it lists
    with its colour: {"project": "Teal", "thread": ""}. A kind on its default,
    "" or left out, is not kept. An unknown kind or colour is refused, and so
    is a colour a ring on the graph uses."""
    if not isinstance(given, dict):
        raise Refused("not a colour for each kind of note")
    out = {}
    for kind, colour in given.items():
        if not isinstance(kind, str) or not (kind in GRAPH_KINDS or GRAPH_FOUND.fullmatch(kind) and kind == kind.lower()):
            raise Refused("no kind of note called %r" % (kind,))
        if colour in ("", None):
            continue
        if colour not in ZONE_COLOURS:
            raise Refused("no colour called %r" % (colour,))
        if colour in GRAPH_OFF:
            raise Refused("%s marks a late next action on the graph, so no kind of note takes it" % colour)
        out[kind] = colour
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
        zone, project, name, note = parts[0], parts[1], parts[1], folder / (parts[1] + ".md")
        thread = None
    elif len(parts) == 4 and parts[2] == "Threads":
        zone, project, name, thread = parts[0], parts[1], parts[3], parts[3]
        note = folder / (parts[3] + ".md")
    else:
        raise Refused("a tab opens only at the workspace root or in a project or thread")
    # A project is a folder with its own hub note, and a thread belongs to one: Sources/Threads/X is neither.
    # Names that are never a project, names with a control character (they become prompt text), and a
    # note that is not a regular file are refused, as the Finder menu's GarrickLink.openable refuses them.
    for part in parts:
        if part.startswith(".") or any(unicodedata.category(c) in ("Cc", "Zl", "Zp") for c in part):
            raise Refused("a tab opens only at the workspace root or in a project or thread")
    if project in ("Inbox", "Sources", "Deliverables") or name in ("Inbox", "Sources", "Deliverables"):
        raise Refused("a tab opens only at the workspace root or in a project or thread")
    hub = (ws / "Zones").resolve() / zone / project / (project + ".md")
    if not hub.is_file() or not note.is_file():
        raise Refused("a tab opens only at the workspace root or in a project or thread")
    req.update(zone=zone, project=project)
    if thread:
        req.update(thread=thread)
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


def tab_agent(req: dict) -> list:
    """The assistant an open asks its tab to start, for this open only (#307),
    as desk's --agent: none, and the tab starts what desk-agent says."""
    agent = req.get("agent")
    if agent is None:
        return []
    if agent not in DESK_AGENTS:
        raise Refused("a cmux tab starts %s, not %r" % (" or ".join(DESK_AGENTS), agent))
    return ["--agent", agent]


def cmux_act(ws: Path, req: dict) -> str:
    verb = req["verb"]
    agent = tab_agent(req) if verb == "open" else []
    if verb == "open" and "folder" in req:
        req = dict(req)
        prompt = by_folder(ws, req)
        if prompt is not None:
            said = run_desk(ws, "open", str(ws.resolve()), "--prompt", prompt, "--title", root_title(prompt),
                            "--front", *agent).splitlines()
            return said[0][:1].upper() + said[0][1:] if said else "Opened the workspace root in cmux"
    if verb == "open":
        folder, name = cmux_folder(ws, req)
        said = run_desk(ws, "open", str(folder), "--prompt", "open " + name, "--front", *agent).splitlines()
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
# Set for scaffold.py, which then asks for no build of the page itself: the
# app builds it after this reply. garrick_lib's CALLER_BUILDS_PAGE (#243).
CALLER_BUILDS_PAGE = "GARRICK_CALLER_BUILDS_PAGE"


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
    commit's time and a git command's besides. A refusal that carries the
    check's own line is the wall's, and says the rule's sentence alone: the
    script prints the line for whoever ran it in a terminal, who needs it to
    take the material out, but the page and the ask box never show it."""
    tool = ws / "System" / "tools" / "scaffold.py"
    if not tool.is_file():
        raise Refused("System/tools/scaffold.py is missing")
    try:
        r = subprocess.run([sys.executable, str(tool), "--root", str(ws)] + list(args), capture_output=True, text=True,
                           timeout=COMMIT_TIMEOUT + GIT_TIMEOUT, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, **{CALLER_BUILDS_PAGE: "1"}))
    except subprocess.TimeoutExpired:
        raise Refused("scaffold.py was still running after %s, most likely in the wall check of its commit, and was "
                      "stopped; its change may be left staged, so look at git status in the zone before trying again"
                      % how_long(COMMIT_TIMEOUT + GIT_TIMEOUT))
    if r.returncode != 0:
        why = (r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else "scaffold.py refused"
        wall = wall_refusal(ws)
        raise Refused(wall if wall and WALL_IN.search(why) else why)
    return r.stdout.strip()


def manage(ws: Path, req: dict) -> str:
    verb = req["verb"]
    zone = zone_dir(ws, req.get("zone"))
    if verb == "check-name":
        kind = req.get("kind")
        if kind not in ("project", "thread", "rename", "move"):
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
        made = [p for p in (zone / name,) if not p.exists()]
        spoken = [*(["--spoken", field(req, "spoken")] if req.get("spoken") is not None else []),
                  *(["--thread-spoken", field(req, "thread_spoken")] if req.get("thread_spoken") is not None else [])]
        args = ["project", "--zone", z, "--name", name, "--party", field(req, "party"), "--thread", thread, *spoken]
        if not check:
            asks_how(ws, args)
        said = scaffold(ws, *args, *flag)
        if not check:
            commit_new(zone, [name], "New project %s (%s), first thread %s" % (name, req["party"].strip(), thread),
                       made, {}, wall=wall_refusal(ws))
            return first_line(said)
        return said
    if verb == "new-thread":
        project, name = field(req, "project"), field(req, "name")
        threads, hub = zone / project / "Threads", zone / project / ("%s.md" % project)
        made = [p for p in (threads, threads / name) if not p.exists()]
        before = {hub: hub.read_bytes()} if hub.is_file() else {}
        # The hub is committed with the new thread only when it held nothing
        # else uncommitted: another session's edit is never filed under this
        # commit's message (#183). Otherwise its new line waits for a wrap.
        held = bool(before) and not check and uncommitted(zone, hub)
        args = ["thread", "--zone", z, "--project", project, "--name", name,
                *(["--spoken", field(req, "spoken")] if req.get("spoken") is not None else [])]
        if not check:
            asks_how(ws, args)
        said = scaffold(ws, *args, *flag, *([] if check else ["--touched"]))
        if check:
            return said
        said, touched = touched_paths(said)
        if touched is None:                     # a scaffold.py that does not say: what it always writes
            touched = [(threads / name).relative_to(zone).as_posix(), hub.relative_to(zone).as_posix()]
        hub_rel = hub.relative_to(zone).as_posix()
        paths = [t for t in touched if not (held and t == hub_rel)]
        commit_new(zone, paths, "%s: new thread %s" % (project, name), made, before, wall=wall_refusal(ws))
        said = first_line(said)
        if held and hub_rel in touched:
            said += (" The hub's line for it is not committed yet: %s had other changes not committed, so it is "
                     "left for the next wrap." % hub.name)
        return said
    if verb == "undo":
        commit = req.get("commit")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{7,40}", commit):
            raise Refused("not a commit: %r" % commit)
        return scaffold(ws, "undo", "--zone", z, "--commit", commit)
    thread = field(req, "thread", required=False)
    which = ["--zone", z, "--project", field(req, "project")] + (["--thread", thread] if thread else [])
    if verb == "move":
        project, to = field(req, "project"), field(req, "to")
        if not thread:
            raise Refused("no thread given: only a thread moves")
        if check:
            return scaffold(ws, "move", *which, "--to", to, *flag)
        return moved_here(ws, zone, project, thread, to, which)
    if verb == "rename":
        if check:
            return scaffold(ws, "rename", *which, "--to", field(req, "to"), *flag)
        return renamed_here(ws, zone, field(req, "project"), thread, field(req, "to"), which)
    confirm = field(req, "confirm", required=False)
    said = scaffold(ws, "delete", *which, *(["--confirm", confirm] if confirm else []))
    if confirm:
        # One line, with the commit the page's Undo reverts; scaffold.py's undo command and memory hint are
        # for a terminal, and Undo on the page is the way back here.
        found = re.search(r"\bin commit ([0-9a-f]{7,40})\b", said)
        return {"say": first_line(said).rstrip("."), "commit": found.group(1) if found else ""}
    return said


def said_all(said: str, most: int = 1200) -> str:
    """The whole of what scaffold.py said, for a reply that carries a count or a list (the files a flag releases or
    now holds in violation), cut at `most` characters."""
    text = said.strip()
    return text if len(text) <= most else text[:most].rsplit("\n", 1)[0] + "\n..."


def party_flag(ws: Path, req: dict):
    """Flip a party's flag from the Parties tab (#447): scaffold.py's own `party --walled | --open`, so the
    page, a session and a terminal meet the same refusals, then System/context.md committed in the workspace's
    own repository. Walled to open releases history: the command says how many files and writes only on
    `yes`, so a first request without it comes back as a question (`ask`) and nothing changed. Open to walled
    writes at once and the reply lists the files now in violation."""
    tag, flag = field(req, "tag"), req.get("flag")
    if flag not in ("walled", "open"):
        raise Refused("not a flag: %r" % (flag,))
    if req.get("yes") not in (None, True, False):
        raise Refused("not an answer: %r" % (req.get("yes"),))
    context = ws / "System" / "context.md"
    with held("page-action-context.lock", busy="another change to the parties is still running"):
        try:
            before = context.read_bytes()
        except OSError:
            raise Refused("System/context.md is missing")
        said = scaffold(ws, "party", "--tag", tag, "--" + flag, *(["--yes"] if req.get("yes") else []))
        try:
            after = context.read_bytes()
        except OSError:
            after = b""
        if after == before:
            return {"say": said_all(said), "ask": not req.get("yes") and "--yes" in said, "written": False}
        code, why = committing(ws, "System/context.md", "Party %s: %s" % (tag, flag))
        if code != 0:
            context.write_bytes(before)
            git(ws, "reset", "-q", "--", "System/context.md", timeout=10)
            raise Refused("not committed, so nothing changed: %s" % why)
    return {"say": said_all(said), "ask": False, "written": True}


def asks_how(ws: Path, args: list) -> None:
    """Before anything is written (#344): scaffold.py's own --check, and where it asks how a name is said, Refused
    with that question and nothing made. The answer is the request's `spoken` (a project's first thread's
    `thread_spoken`), so a name such as Q4 Planning is never made without the form it is heard as."""
    asked = scaffold(ws, *args, "--check").strip().splitlines()[1:]
    if asked:
        raise Refused(" ".join(l.strip() for l in asked) + " Make it in a session, with its spoken form (--spoken).")


def first_line(said: str) -> str:
    """What the page says of scaffold.py's report: its first line, which says what was done. The rest is for a
    terminal: what to commit by hand, a spoken form to ask for, a memory pointer, a flag to rebuild with."""
    return (said.strip().splitlines() or [""])[0].strip()


def renamed_here(ws: Path, zone: Path, project: str, thread: Optional[str], to: str, which: list) -> dict:
    """A rename from the page, finished here rather than left to the user
    (#184): scaffold.py renames and commits in the zone; then the old name,
    which it adds to System/context.md as a heard name, is committed there
    by name in the workspace's own repository, unless that file held other
    changes not committed, which are never filed under this commit (#183);
    the move is kept for the effort history (effort.py's moved.json), so the
    page's Time and Cost follow the new name. One line, and the zone's commit for Undo."""
    old = thread or project
    context = ws / "System" / "context.md"
    root_repo = (ws / ".git").exists()
    held = root_repo and context.is_file() and uncommitted(ws, context)
    before = context.read_bytes() if context.is_file() else None
    said = scaffold(ws, "rename", *which, "--to", to)
    code, head = git(zone, "rev-parse", "--short", "HEAD")
    made = head.strip() if code == 0 else ""
    rel_old = "Zones/%s/%s" % (zone.name, project + ("/Threads/" + thread if thread else ""))
    rel_new = "Zones/%s/%s" % (zone.name, project + "/Threads/" + to if thread else to)
    note = ""
    try:
        keep_move(ws, rel_old, rel_new)
    except OSError:
        note += " The page's time and cost for it start afresh under the new name."
    added = context.is_file() and context.read_bytes() != before
    if added and root_repo and not held:
        try:
            commit(ws, context, before or b"", ("Heard name %s for %s, renamed in %s" % (old, to, zone.name))[:200],
                   wall=wall_refusal(ws))
        except Refused as e:
            note += " Its old name is not kept as a heard one: %s." % str(e).rstrip(".")
    elif added and held:
        note += (" Its old name is added as a heard one in System/context.md, which had other changes not committed, "
                 "so it is left for you to commit.")
    if "Links written [[" in said:
        note += " Links that name only %s were left alone: another note in %s has that name too." % (old, zone.name)
    return {"say": "Renamed %s to %s.%s" % (old, to, note), "commit": made}


def moved_here(ws: Path, zone: Path, project: str, thread: str, to: str, which: list) -> dict:
    """A move from the page, a button or a session, finished here as a rename
    is: scaffold.py moves the thread and commits in the zone, and the effort
    history follows it there. One line, and
    the zone's commit for Undo. The assistant's memory pointer and a desk tab
    are not Garrick's to write, so the reply says that they still name the old
    path."""
    said = scaffold(ws, "move", *which, "--to", to)
    code, head = git(zone, "rev-parse", "--short", "HEAD")
    made = head.strip() if code == 0 else ""
    name = thread
    if (zone / to).is_dir():                                  # to, as the folder is spelled
        to = next((c.name for c in zone.iterdir() if c.name.lower() == to.lower()), to)
    # The effort history follows the thread inside scaffold.py, which also puts it
    # back when the move is undone; the memory pointer and a desk tab are not Garrick's to write.
    note = " A memory pointer or an open desk tab for it still names %s." % project
    left = next((l for l in said.splitlines() if l.startswith("Markdown links left as they are")), "")
    note += (" " + left) if left else ""
    return {"say": "Moved %s from %s to %s.%s" % (name, project, to, note), "commit": made}


def keep_move(ws: Path, old: str, new: str) -> None:
    """A folder renamed from the page, kept for the effort history in
    System/generated/moved.json, never committed: {"<old>": "<new>"}, each
    path from the workspace's root. effort.py reads it beside any `--moved`
    the page is built with; a move of a folder already moved follows on."""
    path = ws.joinpath(*EFFORT_MOVED)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    data = {o: (new if n == old else n) for o, n in data.items() if isinstance(o, str) and isinstance(n, str)}
    if old != new:
        data[old] = new
    data.pop(new, None)                     # renamed back: its own name again
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".moved-", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, str(path))


# effort.py's MOVED, beside this file: where the moves made from the page are kept for it.
EFFORT_MOVED = ("System", "generated", "moved.json")


def touched_paths(said: str) -> tuple:
    """scaffold.py's reply without its last line `Touched: [...]`, and the
    paths from the zone that line lists; None when there is no such line."""
    lines = said.splitlines()
    if lines and lines[-1].startswith("Touched: "):
        try:
            found = json.loads(lines[-1][len("Touched: "):])
        except ValueError:
            found = None
        if isinstance(found, list) and all(isinstance(p, str) for p in found):
            return "\n".join(lines[:-1]).strip(), found
    return said, None


def uncommitted(zone: Path, path: Path) -> bool:
    """Whether `path` holds changes git has not committed, staged or not."""
    code, said = git(zone, "status", "--porcelain", "--", path.relative_to(zone).as_posix())
    return code == 0 and bool(said.strip())


def commit_new(zone: Path, paths: list, message: str, made: list, before: dict, moved: tuple = (), *,
               wall: Optional[str]) -> None:
    """Commit what scaffold.py made, by name: `paths`, from the zone, the new
    folder and the files it changed, and nothing else in the zone (#183).
    Refused, the files stay for the user; refused by the wall check, the reply
    is `wall` alone, as commit()'s is, and its "Nothing was written" holds
    (#172): `made`, the folders that were not there before the request, go,
    and each file in `before` gets back the bytes it held then, an edit from
    another session included. Nothing else is touched. If a file scaffold.py
    changed was edited meanwhile, all of it stays, as commit_all() leaves its
    notes. `moved` is what the request moved, (where it is now, where it
    was): refused for any reason, each goes back, and `before` with it, so a
    move is committed whole or not at all."""
    mine = {n: n.read_bytes() for n in before if n.is_file()}
    code, why = committing(zone, paths, message)
    if code != 0:
        git(zone, "reset", "-q", "--", *paths, timeout=10)
        if moved:
            for now, was in moved:
                if now.exists() and not was.exists():
                    os.rename(str(now), str(was))
            for n, was in before.items():
                n.write_bytes(was)
            if wall and code is not None and WALL_LINE.match(why):
                raise Refused(wall)
            raise Refused("not committed, so nothing changed: %s" % why)
        if wall and code is not None and WALL_LINE.match(why):
            try:
                ours = all(n.read_bytes() == wrote for n, wrote in mine.items())
            except OSError:
                ours = False
            if not ours:
                raise Refused("made, but not committed. A note was edited meanwhile, so what was made was left as "
                              "it is; take it out, or commit it by hand")
            for n, was in before.items():
                n.write_bytes(was)
            for p in made:                      # the outermost first: a new Threads folder takes its thread with it
                shutil.rmtree(p, ignore_errors=True)
            raise Refused(wall)
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


def say_name(ws: Path, zone: Path, parts: tuple) -> str:
    """The name Continue asks about, "Where am I on <it>?": the name the home
    shows (work_name()), but for a thread of a project with several, the
    shortest that is unique, as the threads skill says it (#180): the thread
    alone when no other thread in any zone, live or parked, has its name;
    else project and thread; else the zone first as well. A project that is
    one thread keeps the project's name, which is what the home calls it."""
    name = work_name(zone, parts)
    if len(parts) != 4 or name == parts[0]:
        return name
    thread, project = parts[2].casefold(), parts[0].casefold()
    seen = []
    for z in sorted((ws / "Zones").iterdir()) if (ws / "Zones").is_dir() else []:
        if not z.is_dir() or z.name.startswith((".", "_")):
            continue
        for p in z.iterdir():
            if not p.is_dir() or p.name.startswith((".", "_")) or p.name in SKIP or p.name == "Inbox":
                continue
            notes = [t / (t.name + ".md") for t in (p / "Threads").glob("*/")
                     if not t.name.startswith((".", "_")) and t.name not in SKIP and (t / (t.name + ".md")).is_file()]
            if not notes and (p / (p.name + ".md")).is_file():
                notes = [p / (p.name + ".md")]          # a project that is its own thread, by its name
            seen += [(z.name, p.name.casefold(), n.stem.casefold()) for n in notes
                     if front(n).get("status") not in ("done", "closed", "archived", "complete", "completed")]
    same = [s for s in seen if s[2] == thread]
    if len(same) <= 1:
        return parts[2]
    return name if sum(s[1] == project for s in same) <= 1 else "%s, %s" % (zone.name, name)


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
    words = answer(req, "text", required=False)
    with zone_lock(zone):
        text = open_question(q)
        own = hub_value(q, "own")
        chosen = next(((l, a) for l, a in options(text) if l.casefold() == label.casefold()), None)
        if own and label.casefold() == own.casefold():
            # The answer in the user's own words (#182): what they write is the next step.
            if not words:
                raise Refused("say what the next step is, in your own words")
            chosen = (own, words)
        elif words:
            raise Refused("only %s takes words of your own" % (own or "an answer in Claude"))
        if chosen is None:
            raise Refused("that question has no answer called %r" % label)
        q_before, n_before = q.read_bytes(), note.read_bytes()
        written = answered_note(n_before.decode("utf-8"), chosen[1], chosen[0], today, name)
        note.write_text(written, encoding="utf-8")
        q.write_text(set_front(text, {"status": "answered", "answer": quoted(chosen[0]), "answered": today.isoformat()},
                               drop=("later",)), encoding="utf-8")
        commit_all(zone, [(note, n_before), (q, q_before)], ("%s: answered %s" % (name, chosen[0]))[:200],
                   wall=wall_refusal(ws))
    key = "%s/%s" % (zone.name, note.relative_to(zone).as_posix())
    kept = your_work().first_looks(ws).get(key)
    if isinstance(kept, dict) and kept.get("question") == q.relative_to(zone).as_posix():
        # A first look's next step confirmed or put in the user's words: the request Continue asks follows it.
        if own and chosen[0] == own:
            your_work().keep_first_look(ws, key, request="Help me with the next step on %s: %s" % (name, chosen[1]))
        return "Noted. Next for %s: %s. Continue in Claude starts on it" % (name, said_text(chosen[1]))
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


# ---------------------------------------------------------------------------
# Wiki questions (#224): answered, put off, closed, worked in
# ---------------------------------------------------------------------------
#
# A wiki question is a file, Wikis/<Wiki>/questions/<YYMMDD> - <slug>.md. The
# user's answer is a raw record first, Wikis/<Wiki>/raw/answers/<YYMMDD> -
# <slug>.md, never edited after; only then does the question change. These
# verbs write those two files and nothing else, and commit nothing: a wiki's
# commit is the skill's. They read the walls as check.py does and fail closed:
# a question or a page they cannot read plainly is not used.
WIKI_NAMES = ("Meetings", "Knowledge")
WIKI_QUESTION_DIR = "questions"
WIKI_ANSWER_DIR = ("raw", "answers")
WORDS_MAX = 4000
BOLD_LINE = re.compile(r"(?m)^\s*\*\*(.+)\*\*\s*$")
WIKI_DECISION_DIR = ("wiki", "decisions")
DECISION_SECTIONS = ("Decision", "Assumptions", "Options turned down", "Revisit when")
NO_DECISION = ("a Knowledge question has no zone and no parties for a decision to carry, so nothing was written. "
               "Answer it, put it off or close it instead")
NOT_SET = "Not set yet. The assistant may propose some, each marked *Proposed*; you settle what stays."


def wall_sentence(ws: Path) -> str:
    """The rule's sentence, from operations.py's one copy. Without it the wall
    cannot be said, so nothing is done (fail closed)."""
    said = wall_refusal(ws)
    if not said:
        raise Refused("this workspace's operations.py cannot say the wall sentence, so nothing was written")
    return said


def tags_of(value) -> list:
    """A frontmatter value as a list of party tags, as written."""
    items = value if isinstance(value, list) else [value]
    return [str(v).strip() for v in items if v is not None and str(v).strip()]


def two_walled(lib, ctx: dict, tags) -> bool:
    """Do `tags` hold more than one walled party? A page or a question of two is mixed and has no
    destination yet: nothing is named or written."""
    return not lib.meets_in(ctx, tags)


def bare_tag(lib, tag: str) -> str:
    return lib.strip_tag(tag) if callable(getattr(lib, "strip_tag", None)) else tag


class WikiQuestion:
    """One wiki question as the walls read it: where it is, its text and frontmatter."""

    def __init__(self, ws: Path, req: dict):
        self.ws = ws
        wiki = req.get("wiki")
        if wiki not in WIKI_NAMES:
            raise Refused("no wiki called %s; the wikis with questions are %s" % (wiki, " and ".join(WIKI_NAMES)))
        self.name = wiki
        self.dir = (ws / "Wikis" / wiki).resolve()
        if self.dir.parent != (ws / "Wikis").resolve() or not self.dir.is_dir():
            raise Refused("no wiki called %s" % wiki)
        rel = req.get("file")
        if not isinstance(rel, str) or not rel.endswith(".md") or rel.startswith(("/", "~")):
            raise Refused("not a question")
        asked = (self.dir / WIKI_QUESTION_DIR).resolve()
        path = (self.dir / rel).resolve()
        if asked not in path.parents or not path.is_file() or SKIP & set(path.relative_to(asked).parts):
            raise Refused("that question is not in %s any more" % (WIKI_QUESTION_DIR + "/"))
        self.path = path
        self.lib = prefs().lib(ws)
        if self.lib is None or not all(callable(getattr(self.lib, n, None)) for n in
                                       ("parse_frontmatter_text", "frontmatter_form_problem", "load_context", "blocked", "decide")):
            raise Refused("this workspace's garrick_lib.py cannot read the walls, so nothing was written")
        self.reload()

    def reload(self) -> None:
        try:
            self.text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise Refused("that question cannot be read")
        if self.lib.frontmatter_form_problem(self.text):
            raise Refused("that question's frontmatter cannot be read plainly, so nothing was written")
        self.fm = self.lib.parse_frontmatter_text(self.text)
        if self.fm.get("type") != "question":
            raise Refused("that file is not a question")
        self.status = str(self.fm.get("status") or "").strip().lower()
        found = BOLD_LINE.search(self.text)
        self.bold = found.group(0).strip() if found else ""

    @property
    def context(self) -> dict:
        return self.lib.load_context(self.ws)

    def parties(self) -> list:
        return [bare_tag(self.lib, t) for t in tags_of(self.fm.get("parties"))]

    def stem(self) -> str:
        return self.path.stem


def party_keys_two_ways(text: str) -> bool:
    """Whether a page spells its party keys so a reader could take them two
    ways: `party:` beside `parties:`, or either in capitals. The walls read
    `parties:` alone on a Meetings question or decision, so such a page is
    placed nowhere and nothing is saved from it (fail closed)."""
    m = re.match(r"---\n(.*?)\n---", text or "", re.S)
    if not m:
        return False
    keys = [k for k in re.findall(r"(?m)^([A-Za-z_][\w-]*)\s*:", m.group(1)) if k.lower() in ("party", "parties")]
    return bool(keys) and (len({k.lower() for k in keys}) > 1 or any(k != k.lower() for k in keys))


def question_parties(q: WikiQuestion, wall: str) -> list:
    """The question's own parties, checked: a Meetings question names its zone
    and parties, every one a tag the workspace knows, and no two walled from
    each other. A Knowledge question names neither. Anything else is refused."""
    ctx = q.context
    zone = q.fm.get("zone")
    # Both spellings of the party key, or one in another case, read two ways: the question says whose it is to no one.
    keys = [k for k in q.fm if str(k).strip().lower() in ("party", "parties")]
    if any(k != "parties" for k in keys):
        raise Refused("that question's frontmatter cannot be read plainly, so nothing was written")
    tags = q.parties()
    if q.name == "Knowledge":
        if zone not in (None, "") or tags:
            raise Refused("a Knowledge question carries no zone and no parties, so nothing was written")
        return []
    if not isinstance(zone, str) or zone.strip() not in {z.name for z in (q.ws / "Zones").iterdir() if z.is_dir()}:
        raise Refused("that question is unfinished, with no zone or parties it can be read by, so nothing was written")
    if not tags or any(t not in ctx.get("parties", {}) for t in tags):
        raise Refused("that question is unfinished, with no zone or parties it can be read by, so nothing was written")
    if two_walled(q.lib, ctx, tags):
        raise Refused(wall)
    return tags


def page_target(q: WikiQuestion, link: str) -> Optional[Path]:
    """The file a `pages:` link names, inside the question's own wiki, or None."""
    m = re.fullmatch(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]", link.strip())
    if not m:
        return None
    target = m.group(1).strip()
    if target.startswith(("/", "~")) or ".." in Path(target).parts:
        return None
    for name in (target, target + ".md"):
        p = (q.dir / name).resolve()
        # Only a page of the wiki's own wiki/ folder: never a raw record, a
        # question or the question's own answer.
        if p.is_file() and (q.dir / "wiki").resolve() in p.parents and p.suffix.lower() == ".md":
            return p
    return None


def page_tags(q: WikiQuestion, page: Path) -> Optional[list]:
    """The parties a Meetings page is written for, or None when it cannot be
    read plainly: no party, a form a reader could take two ways, or a tag the
    workspace does not know. `party: none` is plainly nobody's."""
    try:
        text = page.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if q.lib.frontmatter_form_problem(text):
        return None
    fm = q.lib.parse_frontmatter_text(text)
    found = tags_of(fm.get("parties")) + tags_of(fm.get("party"))
    if not found:
        return None
    known = q.context.get("parties", {})
    out = [bare_tag(q.lib, t) for t in found]
    if out == ["none"]:
        return []
    return out if all(t in known for t in out) else None


def question_pages(q: WikiQuestion, wall: str) -> tuple:
    """(the pages the answer may change, how many were held back, how many are
    not there). A question whose pages sit on both sides of a wall is refused
    with the rules' sentence and nothing named. A page walled from the
    question's parties, or not readable plainly, is held back. A Knowledge
    question has no parties: every page it names is one it may change."""
    mine = question_parties(q, wall)
    links = tags_of(q.fm.get("pages"))
    pages, missing = [], 0
    for link in links:
        p = page_target(q, link)
        if p is None:
            missing += 1
        elif p not in pages:
            pages.append(p)
    if q.name == "Knowledge":
        return pages, 0, missing
    ctx = q.context
    seen, readable, held = [], [], 0
    for p in pages:
        tags = page_tags(q, p)
        if tags is None:
            held += 1
            continue
        seen.append(tags)
        readable.append((p, tags))
    flat = [t for tags in seen for t in tags]
    if two_walled(q.lib, ctx, flat):
        raise Refused(wall)             # two walled parties: nothing named, nothing written
    allowed = []
    for p, tags in readable:
        # Only a page that carries the question's own parties, and no others:
        # a page written for nobody (`none`) is guarded by no wall, so the
        # answer is never written into it.
        if not tags or not set(tags) <= set(mine) or q.lib.decide(mine, tags, "write", ctx) == "deny":
            held += 1
        else:
            allowed.append(p)
    # A page that is not there looks like a page held back, so that a `pages:`
    # list cannot be used to ask whether a walled page exists.
    return allowed, held + missing, 0


def answer_slug(stem: str) -> str:
    """The question's name without its date: the raw answer is dated by the
    day it was given and named by what it answers."""
    slug = re.sub(r"^\d{6} - ", "", stem)
    slug = re.sub(r"[^\w\- ]", "", slug).strip()
    return slug or "answer"


def fence_for(words: str) -> str:
    longest = max([len(r) for r in re.findall(r"`+", words)] or [0])
    return "`" * max(3, longest + 1)


def raw_answer_text(q: WikiQuestion, words: str, today: dt.date, tags: list, outcome: str = "") -> str:
    where = ["type: answer", "answered: %s" % today.isoformat()]
    if outcome:
        where.append("outcome: %s" % outcome)       # `decision`: the record check.py asks for before a decision's status moves
    if q.name == "Meetings":
        where += ["zone: %s" % str(q.fm.get("zone")).strip(), "parties: [%s]" % ", ".join(tags)]
    where.append("question: %s" % quoted("[[%s]]" % q.path.relative_to(q.dir).with_suffix("").as_posix()))
    fence = fence_for(words)
    return ("---\n%s\n---\n\nQuestion: %s\n\nAnswered on %s, in the user's own words:\n\n%s\n%s\n%s\n"
            % ("\n".join(where), q.bold.strip("*").strip(), today.isoformat(), fence, words, fence))


def write_new(path: Path, text: str) -> None:
    """A file that did not exist, made whole or not at all: exclusive, so a
    raw record already there is never touched."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        try:
            path.unlink()               # half a record is no record
        except OSError:
            pass
        raise


def file_raw_answer(q: WikiQuestion, today: dt.date, words: str, tags: list, outcome: str = "") -> Path:
    folder = q.dir.joinpath(*WIKI_ANSWER_DIR)
    tx_dirs(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if folder.resolve() != folder or q.dir not in folder.parents:
        raise Refused("raw/answers is not a plain folder of this wiki, so nothing was written")
    body = raw_answer_text(q, words, today, tags, outcome)
    base = "%s - %s" % (today.strftime("%y%m%d"), answer_slug(q.stem()))
    for n in range(1, 10):
        path = folder / ("%s.md" % base if n == 1 else "%s-%d.md" % (base, n))
        try:
            write_new(path, body)
            tx_made(path)
            return path
        except FileExistsError:
            continue
    raise Refused("nine answers to this question are already filed today, so nothing was written")


def decision_text(q: WikiQuestion, words: str, today: dt.date, tags: list, record: str) -> str:
    """The decision page: its question's zone and parties copied exactly,
    status valid (the user's own save is the act that settles it), and the
    user's words under Decision, fenced so nothing in them can open a section."""
    title = q.bold.strip("*").strip()
    where = ["type: decision", "title: %s" % quoted(title), "status: valid", "decided: %s" % today.isoformat(),
             "zone: %s" % str(q.fm.get("zone")).strip(), "parties: [%s]" % ", ".join(tags),
             "source: %s" % quoted("[[%s]]" % record),
             "question: %s" % quoted(q.path.relative_to(q.dir).with_suffix("").as_posix()),
             "created: %s" % today.isoformat(), "updated: %s" % today.isoformat()]
    fence = fence_for(words)
    return ("---\n%s\n---\n\n# %s\n\n## Decision\n\n%s\n%s\n%s\n\n## Assumptions\n\n%s\n\n"
            "## Options turned down\n\n%s\n\n## Revisit when\n\n%s\n"
            % ("\n".join(where), title, fence, words, fence, NOT_SET, NOT_SET, NOT_SET))


def file_decision(q: WikiQuestion, today: dt.date, words: str, tags: list, record: str) -> Path:
    folder = q.dir.joinpath(*WIKI_DECISION_DIR)
    tx_dirs(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if folder.resolve() != folder or q.dir not in folder.parents:
        raise Refused("wiki/decisions is not a plain folder of this wiki, so nothing was written")
    body = decision_text(q, words, today, tags, record)
    base = "%s - %s" % (today.strftime("%y%m%d"), answer_slug(q.stem()))
    for n in range(1, 10):
        path = folder / ("%s.md" % base if n == 1 else "%s-%d.md" % (base, n))
        try:
            write_new(path, body)
            tx_made(path)
            return path
        except FileExistsError:
            continue
    raise Refused("nine decisions on this question are already filed today, so nothing was written")


def wiki_words(req: dict) -> str:
    words = req.get("words")
    if not isinstance(words, str) or not words.strip():
        raise Refused("say the answer, in your own words")
    words = words.strip()
    if len(words) > WORDS_MAX or "\0" in words:
        raise Refused("the answer is too long to file: at most %d characters, no control characters" % WORDS_MAX)
    return words


def write_question(path: Path, text: str) -> None:
    tx_watch(path)
    path.write_text(text, encoding="utf-8")


def open_section_slug(title: str, line: str) -> str:
    words = re.findall(r"[a-z0-9]+", ("%s %s" % (title, line)).lower())
    slug = "-".join(words)[:60].strip("-")
    return slug or "open-line"


def open_section_text(row: dict, today: dt.date, meetings: bool) -> str:
    where = ["type: question", "asked: %s" % today.isoformat(), "status: open"]
    if meetings:
        where += ["zone: %s" % row["zone"], "parties: [%s]" % ", ".join(row["parties"])]
    link = quoted("[[%s]]" % row["page"])
    where += ["origin: %s" % link, "pages: [%s]" % link]
    return ("---\n%s\n---\n\n**%s**\n\nThe page lists this under Open, and nothing on the page has changed. "
            "Answer it, put it off or close it; the page changes only once the answer is worked in.\n"
            % ("\n".join(where), row["bold"]))


def open_section_rows(ws: Path, wiki: str, wall: str, only: Optional[list]) -> list:
    """The open-section rows of a wiki, as wiki_lint.py reads them, each
    proposal checked the way a question's own fields are: a zone the workspace
    has, parties it knows, none two sides of a wall. A row that fails is
    skipped with the reason, and nothing about the other side is named."""
    tool = Path(ws) / "System" / "tools" / "wiki_lint.py"
    lib = prefs().lib(ws)
    if not tool.is_file() or lib is None or not all(callable(getattr(lib, n, None)) for n in
                                                     ("parse_frontmatter_text", "frontmatter_form_problem", "load_context", "blocked", "decide")):
        raise Refused("this workspace's wiki_lint.py or garrick_lib.py cannot read the pages, so nothing was written")
    import importlib.util
    spec = importlib.util.spec_from_file_location("wiki_lint_for_open_sections", str(tool))
    mod = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        sys.path.insert(0, str(tool.parent))
        spec.loader.exec_module(mod)
    except Exception:
        raise Refused("this workspace's wiki_lint.py cannot be read, so nothing was written")
    finally:
        sys.path[:] = saved
    if not callable(getattr(mod, "open_sections", None)):
        raise Refused("this workspace's wiki_lint.py does not list open sections, so nothing was written")
    rows = mod.open_sections(Path(ws) / "Wikis" / wiki)
    if only is not None:
        rows = [r for r in rows if r["page"] in only]
    ctx = lib.load_context(ws)
    zones = {z.name for z in (Path(ws) / "Zones").iterdir() if z.is_dir()}
    for r in rows:
        if r["state"] != "propose" or wiki != "Meetings":
            continue
        tags = [bare_tag(lib, t) for t in r["parties"]]
        if r["zone"] not in zones or any(t not in ctx.get("parties", {}) for t in tags):
            r.update(state="skipped", reason="its zone or parties are not ones this workspace knows")
        elif two_walled(lib, ctx, tags):
            r.update(state="skipped", reason=wall)
        else:
            r["parties"] = [t.strip() for t in r["parties"]]
    return rows


def open_sections_act(ws: Path, req: dict, today: dt.date) -> str:
    wiki = req.get("wiki")
    if wiki not in WIKI_NAMES:
        raise Refused("no wiki called %s; the wikis with questions are %s" % (wiki, " and ".join(WIKI_NAMES)))
    if not (Path(ws) / "Wikis" / wiki / "wiki").is_dir():
        raise Refused("no wiki called %s" % wiki)
    only = req.get("pages")
    if isinstance(only, str):                   # typed in a terminal: --pages "a,b"
        only = [x.strip() for x in only.split(",") if x.strip()]
    if only is not None and not (isinstance(only, list) and all(isinstance(x, str) for x in only)):
        raise Refused("pages is a list of page names")
    confirm = req.get("confirm")
    if confirm == "true":                       # typed in a terminal: --confirm true
        confirm = True
    if confirm not in (None, False, True):
        raise Refused("confirm is true or left out")
    wall = wall_sentence(ws)
    meetings = wiki == "Meetings"

    def group_of(r):
        return (r["zone"], tuple(sorted(r["parties"])))

    def say(rows):
        todo = [r for r in rows if r["state"] == "propose"]
        groups = sorted({group_of(r) for r in todo})
        lines = ["%d open line%s would become a question, in %d group%s. Ask once per group, never for two together."
                 % (len(todo), "" if len(todo) == 1 else "s", len(groups), "" if len(groups) == 1 else "s")]
        for g in groups:
            lines.append("Group%s:" % (" (%s, %s)" % (g[0], ", ".join(g[1])) if meetings else ""))
            lines += ["  %s: %s" % (r["page"], r["line"]) for r in todo if group_of(r) == g]
        done = sum(r["state"] == "converted" for r in rows)
        if done:
            lines.append("%d already asked." % done)
        for r in rows:
            if r["state"] == "skipped" and r["reason"] != wall:
                lines.append("No question for %s: %s." % (r["page"], r["reason"]))
        if any(r["state"] == "skipped" and r["reason"] == wall for r in rows):
            lines.append(wall)
        return lines
    if confirm is not True:
        return "\n".join(say(open_section_rows(ws, wiki, wall, only)))
    with held("question-%s.lock" % wiki, busy="another question in %s is still being written" % wiki):
        rows = [r for r in open_section_rows(ws, wiki, wall, only) if r["state"] == "propose"]
        if not rows:
            return "Nothing to write. No open line is waiting for a question"
        if len({group_of(r) for r in rows}) > 1:
            raise Refused("those lines belong to more than one zone and party group, so nothing was written. "
                          "Confirm one group at a time, naming its pages")
        folder = Path(ws) / "Wikis" / wiki / WIKI_QUESTION_DIR
        used = set()

        def write_all(w):
            tx_dirs(folder)
            folder.mkdir(parents=True, exist_ok=True)
            if folder.resolve() != folder or folder.parent.parent != Path(ws).resolve() / "Wikis":
                raise Refused("questions is not a plain folder of this wiki, so nothing was written")
            made = 0
            for r in rows:
                if r["bold"] in used:
                    continue
                used.add(r["bold"])
                base = "%s - %s" % (today.strftime("%y%m%d"), open_section_slug(r["title"], r["line"]))
                for n in range(1, 100):
                    path = folder / ("%s.md" % base if n == 1 else "%s-%d.md" % (base, n))
                    try:
                        write_new(path, open_section_text(r, today, meetings))
                    except FileExistsError:
                        continue
                    tx_made(path)
                    made += 1
                    break
                else:
                    raise Refused("too many questions with one name today, so nothing was written")
            return "%d question%s written in %s/questions. No page was changed" % (made, "" if made == 1 else "s", wiki)
        return transaction(ws, write_all)


def wiki_question_act(ws: Path, req: dict, today: dt.date) -> str:
    verb = req["verb"]
    if verb == "question-open-sections":
        return open_sections_act(ws, req, today)
    wall = wall_sentence(ws)
    q = WikiQuestion(ws, req)
    if verb in ("question-work", "question-done"):
        return wiki_work(ws, q, req, today, wall)
    with held("question-%s.lock" % q.name, busy="another question in %s is still being written" % q.name):
        q.reload()
        if q.status not in ("open", "later"):
            raise Refused("that question is %s, not open" % (q.status or "unreadable"))
        tags = question_parties(q, wall)
        question_pages(q, wall)         # a question across a wall is refused before anything is written
        if verb == "question-decide":
            if q.name != "Meetings" or not tags:
                raise Refused(NO_DECISION)
            if party_keys_two_ways(q.text):
                raise Refused("that question names its parties two ways, so nothing was written")
            # the zone must own the parties: the panel's own test, with its wording
            if not View(ws, q.lib, str(q.fm.get("zone")).strip(), tags[0]).ok(tags):
                raise Refused(wall)
            words = wiki_words(req)
            set_front(q.text, {"status": "answered"})

            def decide(w):
                # Both files or neither: a failure anywhere puts every file back, the raw answer too.
                record = file_raw_answer(q, today, words, tags, "decision")
                stem = record.relative_to(q.dir).with_suffix("").as_posix()
                page = file_decision(q, today, words, tags, stem)
                decided = page.relative_to(q.dir).with_suffix("").as_posix()
                write_question(q.path, set_front(q.text, {"status": "answered", "answer": quoted("[[%s]]" % stem),
                                                          "answered": today.isoformat(), "decision": quoted("[[%s]]" % decided)},
                                                 drop=("later",)))
                return ("Recorded as a decision. Your words are filed as %s and the decision as %s. "
                        "The pages change when you say work them in" % (stem, decided))
            return transaction(ws, decide)
        if verb == "question-close":
            def close(w):
                write_question(q.path, set_front(q.text, {"status": "closed", "closed": today.isoformat()}, drop=("later",)))
                return "Closed. Nothing was worked in"
            return transaction(ws, close)
        if verb == "question-later":
            until = req.get("until")
            try:
                day = dt.date.fromisoformat(until) if isinstance(until, str) else None
            except ValueError:
                day = None
            if day is None or day <= today:
                raise Refused("not a later day: %r" % (until,))

            def put_off_until(w):
                write_question(q.path, set_front(q.text, {"status": "later", "later": day.isoformat()}))
                return "Put off until %s %d %s. It is hidden until then" % (day.strftime("%A"), day.day, MONTHS[day.month - 1])
            return transaction(ws, put_off_until)
        words = wiki_words(req)
        # A question that cannot be rewritten stops here, with nothing written.
        set_front(q.text, {"status": "answered"})

        def file_answer(w):
            path = file_raw_answer(q, today, words, tags)
            stem = path.relative_to(q.dir).with_suffix("").as_posix()
            try:
                write_question(q.path, set_front(q.text, {"status": "answered", "answer": quoted("[[%s]]" % stem),
                                                          "answered": today.isoformat()}, drop=("later",)))
            except Exception as e:
                raise KeepRecord("the answer is filed as %s, but the question could not be updated (%s: %s); "
                                 "the record stays" % (stem, type(e).__name__, e))
            return "Noted. Your words are filed as %s. The pages change when you say work them in" % stem
        return transaction(ws, file_answer)


def own_record(q: WikiQuestion, wall: str) -> str:
    """The raw answer an answered question points at, as a link target, only
    when it is this question's own: a record of type answer, in raw/answers/,
    with the question's zone and parties and a `question:` link that lands on
    this very file. Anything else is refused before a name is printed: a
    Meetings question with the wall sentence, a Knowledge one plainly."""
    refuse = Refused(wall if q.name == "Meetings" else "that question's answer is not a record of this question")
    answered = tags_of(q.fm.get("answer"))
    m = re.fullmatch(r"\[\[(raw/answers/[^\]|#]+)\]\]", answered[0]) if len(answered) == 1 else None
    if not m:
        raise Refused("that question points at no raw answer, so there is nothing to cite")
    folder = q.dir.joinpath(*WIKI_ANSWER_DIR).resolve()
    candidate = (q.dir / (m.group(1) + ".md")).resolve()
    if not candidate.is_file() or folder not in candidate.parents:
        raise Refused("that question points at no raw answer, so there is nothing to cite")
    try:
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise refuse
    if q.lib.frontmatter_form_problem(text):
        raise refuse
    fm = q.lib.parse_frontmatter_text(text)
    if fm.get("type") != "answer":
        raise refuse
    mine = sorted(q.parties())
    theirs = sorted(bare_tag(q.lib, t) for t in tags_of(fm.get("parties")))
    if q.name == "Meetings":
        zone = fm.get("zone")
        if not isinstance(zone, str) or zone.strip() != str(q.fm.get("zone")).strip() or theirs != mine:
            raise refuse
    elif fm.get("zone") not in (None, "") or theirs:
        raise refuse
    link = tags_of(fm.get("question"))
    target = re.fullmatch(r"\[\[([^\]|#]+)\]\]", link[0]) if len(link) == 1 else None
    if not target:
        raise refuse
    for name in (target.group(1).strip(), target.group(1).strip() + ".md"):
        if (q.dir / name).resolve() == q.path:
            return m.group(1)
    raise refuse


def wiki_work(ws: Path, q: WikiQuestion, req: dict, today: dt.date, wall: str) -> str:
    """Read only (question-work): what an answered question may change, and the
    record to cite. question-done: it is marked done."""
    if q.status != "answered":
        raise Refused("that question is %s, not answered" % (q.status or "unreadable"))
    record = own_record(q, wall)
    pages, held_back, missing = question_pages(q, wall)
    if req["verb"] == "question-done":
        with held("question-%s.lock" % q.name, busy="another question in %s is still being written" % q.name):
            q.reload()
            if q.status != "answered":
                raise Refused("that question is %s, not answered" % (q.status or "unreadable"))
            return transaction(ws, lambda w: write_question(q.path, set_front(q.text, {"status": "done", "done": today.isoformat()}))
                               or "Done. The question is worked in")
    lines = ["Cite [[%s]]." % record]
    lines += ["Change %s" % p.relative_to(q.dir).as_posix() for p in pages] or ["No page may be changed."]
    if missing:
        lines.append("%d page%s not there." % (missing, " is" if missing == 1 else "s are"))
    if held_back:
        lines.append(wall)
    return "\n".join(lines)


def commit_all(zone: Path, notes: list, message: str, *, wall: Optional[str]) -> None:
    """commit() for several files in one commit, (file, the bytes it held
    before) each, None for a file the request made. When the commit is
    refused, all are put back, a new one removed, if every one still holds
    what this request wrote, and none if any was edited meanwhile, so they
    never disagree."""
    rels = [str(n.relative_to(zone)) for n, _ in notes]
    mine = [n.read_bytes() for n, _ in notes]
    deadline = time.time() + COMMIT_TIMEOUT
    problem = commit_refusal(zone)
    code, why = (1, "%s, so nothing was committed" % problem) if problem else git(zone, "add", "--", *rels)
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
            if before is None:                  # a file this request made: it goes
                n.unlink()
            else:
                n.write_bytes(before)
    git(zone, "reset", "-q", "--", *rels, timeout=10)
    if not ours:
        raise Refused("not committed: %s. A note was edited meanwhile, so it was left as it is" % why)
    if wall and WALL_LINE.match(why):
        raise Refused(wall)
    raise Refused("not committed, so nothing changed: %s" % why)


# ---- One transaction for every write that changes pages (#224, point 6) ------------------
# A write that changes wiki pages runs inside transaction(): the files are
# written, check.py and each wiki's lint are counted before and after, and if
# any count is worse every file goes back as it was, byte for byte, a file the
# write made removed. Otherwise, where the action commits, the files are
# committed once per repository. The wiki-question actions write and commit
# nothing themselves (the work-in step commits), so they pass no `commit`; the
# Nurture review page's save commits. The measuring is `check_counts`, a name
# the tests replace.
TX = None
CHECK_TIMEOUT = 270     # two runs and a commit fit inside the page's ACTION_LOST (a test pins the sum); a run that takes longer writes nothing


class Writes:
    """The files a transaction has written, and what each held before: the
    bytes, or None for a file that was not there."""

    def __init__(self):
        self.before = {}            # Path -> bytes or None
        self.made_dirs = []         # folders the transaction made, outermost first
        self.tag = None             # the row being written, so a file knows whose it is
        self.owners = {}            # Path -> the tags that wrote it

    def watch(self, path) -> None:
        path = Path(path)
        if self.tag is not None:
            self.owners.setdefault(path, set()).add(self.tag)
        if path in self.before:
            return
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise Refused("%s is not a plain file, so nothing was written" % path.name)
        self.before[path] = path.read_bytes() if path.exists() else None

    def made(self, path) -> None:
        if self.tag is not None:
            self.owners.setdefault(Path(path), set()).add(self.tag)
        self.before.setdefault(Path(path), None)

    def dirs(self, folder) -> None:
        missing = []
        d = Path(folder)
        while not d.exists() and d.parent != d:
            missing.append(d)
            d = d.parent
        for m in reversed(missing):
            if m not in self.made_dirs:
                self.made_dirs.append(m)

    def write(self, path, text: str) -> None:
        path = Path(path)
        self.watch(path)
        self.dirs(path.parent)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def changed(self) -> list:
        out = []
        for p, was in self.before.items():
            now = p.read_bytes() if p.is_file() else None
            if now != was:
                out.append(p)
        return out

    def undo(self, paths=None) -> None:
        """Put the given files (all, by default) back as they were."""
        for p in list(self.before) if paths is None else [Path(x) for x in paths]:
            if p not in self.before:
                continue
            was = self.before[p]
            try:
                if was is None:
                    if p.exists():
                        p.unlink()
                else:
                    p.write_bytes(was)
            except OSError:
                pass

    def restore(self) -> None:
        self.undo()
        for d in reversed(self.made_dirs):
            try:
                d.rmdir()               # only if empty: it was made here
            except OSError:
                pass


def tx_watch(path) -> None:
    if TX is not None:
        TX.watch(path)


def tx_made(path) -> None:
    if TX is not None:
        TX.made(path)


def tx_dirs(folder) -> None:
    if TX is not None:
        TX.dirs(folder)


# A finding of the walls family, by its check or its words: a page naming, linking or quoting across a wall,
# repeating a meeting's wording, or one company under two hats. Any severity. The words are nurture.py's
# (claim_wall), kept here because the transaction reads findings without loading it.
WALLISH = re.compile(r"across a wall|is walled and|one company in two hats|eight or more words|"
                     r"names both \S+ and \S+|a Meetings page|from zone \S+|filed in zone \S+", re.I)


def wallish(check, message) -> bool:
    return str(check) == "walls" or bool(WALLISH.search(str(message or "")))


def check_counts(ws: Path) -> Optional[dict]:
    """What the workspace's checks count now: check.py's errors and warnings,
    and each wiki's orphans and missing links. None when a check cannot run
    or its answer cannot be read: a write is then not made, since nothing can
    say it did no harm."""
    tools = Path(ws) / "System" / "tools"
    out = {}

    def run(*args):
        script = tools / args[0]
        if not script.is_file():
            return None
        try:
            r = subprocess.run([sys.executable, str(script), "--root", str(ws)] + list(args[1:]), capture_output=True, text=True,
                               timeout=CHECK_TIMEOUT, stdin=subprocess.DEVNULL, cwd=str(ws))
            data = json.loads(r.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        return data if isinstance(data, dict) else None
    # The whole check, wording included: a sentence copied from the far side is read only in a full run.
    found = run("check.py", "--json")
    if found is None or not isinstance(found.get("findings"), list):
        return None
    for f in found["findings"]:
        if isinstance(f, dict):
            key = "check:%s" % (f.get("severity") or "warning")
            out.setdefault(key, set()).add((str(f.get("check")), re.sub(r":\d+$", "", str(f.get("path"))), str(f.get("message"))))
    for wiki in WIKI_NAMES:
        if not (Path(ws) / "Wikis" / wiki / "wiki").is_dir():
            continue
        lint = run("wiki_lint.py", "--wiki", wiki, "--json")
        if lint is None:
            return None
        out["lint:%s:orphans" % wiki] = {("orphan", "Wikis/%s/%s.md" % (wiki, o), "") for o in lint.get("orphans") or []}
        out["lint:%s:missing" % wiki] = {("missing", "Wikis/%s/%s.md" % (wiki, p), str(m.get("target")))
                                         for m in lint.get("missing") or [] if isinstance(m, dict) for p in m.get("linked_from") or []}
    return out


def worse_counts(before: dict, after: dict) -> list:
    """What got worse between two readings. A reading holds, for each check, the
    findings it made (check, path, message), or a number where a caller only
    counts. A finding present after and not before is worse, even when another
    was fixed in the same write: one fix never pays for a new problem. Only
    names and numbers are said, never a path or a message."""
    names = {"check:error": "errors", "check:warning": "warnings"}
    out = []
    for key in sorted(set(before) | set(after)):
        was, now = before.get(key, set()), after.get(key, set())
        what = names.get(key) or key.replace("lint:", "").replace(":", " ")
        if isinstance(was, int) or isinstance(now, int):
            if (now if isinstance(now, int) else len(now)) > (was if isinstance(was, int) else len(was)):
                out.append("%s %d to %d" % (what, was if isinstance(was, int) else len(was), now if isinstance(now, int) else len(now)))
        elif now - was:
            out.append("%s: %d new" % (what, len(now - was)))
    return out


def repo_of_path(ws: Path, path: Path) -> Optional[Path]:
    """The nearest folder above `path`, inside the workspace, with a .git of its own."""
    d = path.parent
    top = Path(ws).resolve()
    while True:
        if os.path.lexists(str(d / ".git")):
            return d
        if d == top or top not in d.parents:
            return None
        d = d.parent


def stage(repo: Path, rels: list) -> tuple:
    return git(repo, "add", "-A", "--", *rels)


def unstage(repo: Path, rels: list) -> None:
    git(repo, "reset", "-q", "--", *rels, timeout=10)


def walls_on_staged(ws: Path, repo: Path, rels: list) -> str:
    """The walls check on what is staged in `repo`, as the commit hook runs it
    (garrick_lib.staged_walls_refusal), "" when it passes. A repository with no
    hook (Wikis/ has none) is checked all the same. Without that function in
    this workspace's garrick_lib, a refusal: nothing can say the change is fine."""
    lib = prefs().lib(ws)
    fn = getattr(lib, "staged_walls_refusal", None)
    if not callable(fn):
        return "this workspace's garrick_lib.py cannot run the walls check on a staged change"
    try:
        return fn(ws, repo, rels) or ""
    except Exception as e:
        return "the walls check could not run (%s)" % type(e).__name__


def refusal_kind(said: str) -> str:
    """wall, form or foreign, from the words of staged_walls_refusal."""
    if "another session has staged" in said:
        return "foreign"
    if "for a page's form" in said:
        return "form"
    return "wall"


def commit_groups(ws: Path, w: Writes, message_for, *, wall: Optional[str]) -> dict:
    """Commit what `w` changed, once per repository, each after the walls check
    on it staged. Returns {"commits": {repo: sha}, "refused": {repo: why},
    "uncommitted": [rel]}; the files of a repository whose commit is refused
    are put back. Before any commit, every repository is asked whether it can
    commit at all, and one that cannot refuses the lot: nothing is committed
    in one and not another for a reason that was known. `wall` is the rules'
    sentence, which a refusal by the wall check ends on."""
    done = {"commits": {}, "refused": {}, "uncommitted": []}
    groups = {}
    top = Path(ws).resolve()
    for p in w.changed():
        repo = repo_of_path(ws, p)
        if repo is None:
            done["uncommitted"].append(str(p.relative_to(top)) if top in p.parents else p.name)
        else:
            groups.setdefault(repo, []).append(p)
    for repo in sorted(groups):
        problem = commit_refusal(repo) if repo.parent.name == "Zones" else None
        if problem:
            raise Refused("%s, so nothing was committed and nothing was written" % problem)
    for repo, files in sorted(groups.items()):
        rels = sorted(str(f.relative_to(repo)) for f in files)
        label = str(repo.relative_to(top)) if repo != top else "."
        code, why = stage(repo, rels)
        if code == 0:
            said = walls_on_staged(ws, repo, rels)
            if said:
                code, why = 1, said
        if code == 0:
            code, why = committing(repo, rels, message_for(label, rels))
        if code == 0:
            done["commits"][label] = git(repo, "rev-parse", "--short", "HEAD")[1].strip()
            continue
        unstage(repo, rels)
        w.undo(files)
        if wall and (WALL_LINE.match(why or "") or "walls check refused" in (why or "")):
            why = wall
        done["refused"][label] = why
    return done


def new_findings(before: dict, now: dict) -> list:
    """(reading, finding) for each finding present now and not before."""
    out = []
    for key, found in now.items():
        if isinstance(found, set):
            was = before.get(key, set())
            out += [(key, f) for f in sorted(found - (was if isinstance(was, set) else set()))]
    return out


def walls_on_written(now: dict, written: set) -> list:
    """Every walls-family finding now on a file the transaction wrote, whatever
    the reading before held: a finding's identity stays equal while what it
    reports grows (more words repeated, one more cite), so none is let through."""
    return [(key, f) for key, found in now.items() if isinstance(found, set)
            for f in sorted(found) if wallish(f[0], f[2]) and f[1] in written]


def transaction(ws: Path, change, *, commit=None, after=None, triage=None):
    """Run change(w) and what it wrote either holds or is undone.

    `change(w)` writes through `w` (or the tx_* hooks) and returns the action's
    result; `w.before_counts` is the reading taken before. check_counts() runs
    before and after: a check that cannot run puts every file back and
    refuses. So does a finding that is new, and so does any walls-family
    finding on a file written, whatever the reading before held. With a
    `triage(w, new, walls)`, those are first attributed by path to the rows
    that wrote the files and the rows put back; the check then runs once more,
    and only what no row accounts for refuses the lot. With `commit`, a
    function (repository, paths) -> message, the changed files are then
    committed once per repository; `after(result, done)` then returns the
    action's final result. Without `commit` nothing is staged or committed."""
    global TX
    if TX is not None:
        raise Refused("a transaction is already open")
    before = check_counts(ws)
    if before is None:
        raise Refused("the workspace's checks (check.py and the wiki lint) cannot run, so nothing was written")
    w = Writes()
    w.before_counts = before
    TX = w
    top = Path(ws).resolve()
    try:
        try:
            result = change(w)
        except KeepRecord:
            raise
        except BaseException:
            w.restore()
            raise

        def reading():
            now = check_counts(ws)
            if now is None:
                w.restore()
                raise Refused("the workspace's checks (check.py and the wiki lint) could not run afterwards, so nothing was written")
            written = {str(p.relative_to(top)) for p in w.changed() if top in p.parents}
            return now, worse_counts(before, now), new_findings(before, now), walls_on_written(now, written)
        now, bad, new, walls = reading()
        if (bad or walls) and triage is not None:
            try:
                triage(w, new, walls)
            except BaseException:
                w.restore()
                raise
            now, bad, new, walls = reading()
        if walls:
            w.restore()
            raise Refused(wall_sentence(ws))
        if bad:
            w.restore()
            raise Refused("a check got worse (%s), so every file is back as it was and nothing was committed. "
                          "If something else changed in the workspace meanwhile, that can cause it: try again" % "; ".join(bad))
        if commit is None:
            return result
        try:
            done = commit_groups(ws, w, commit, wall=wall_refusal(ws))
        except BaseException as e:
            w.restore()
            if isinstance(e, Refused):
                raise
            raise Refused("the commit could not be made (%s), so every file is back as it was" % type(e).__name__)
        return after(result, done) if after else result
    finally:
        TX = None


# ---- Nurture's answers, from the Questions panel (#224, point 9) --------------------------
# nurture-answer (an entity page's party), nurture-organisation (where a person
# works) and nurture-correct (a value written wrong) call the same code as
# `nurture.py answered`, `organisation` and `correct`, so the chat and the panel
# write the same way and record in the day's Nurture report. nurture-save is the
# review page's Save: its rows go through one transaction, the walls check runs
# on what is staged and a row it refuses is put back and named while the rest
# go on, and the files are committed once per repository. Every row is read
# again from the page it names: nothing a row carries is trusted, and its text
# is data, never a command or a path to open.
NURTURE_VERBS = ("nurture-answer", "nurture-organisation", "nurture-correct", "nurture-save", "nurture-save-all")
NURTURE_LATER = ("System", "generated", "nurture", "later.json")
NURTURE_ROWS_MAX = 200
NURTURE_WORD_MAX = 200
NURTURE_ROW_KEYS = ("do", "key", "path", "choice", "pick", "until", "edit")
NURTURE_DO = ("answer", "organisation", "correct")
NURTURE_CHOICES = ("yes", "no", "another", "later")
UNATTRIBUTED = "unattributed"           # the view of entity pages that do not say whose they are
KEY_RE = re.compile(r"[0-9a-f]{12}")
_NURTURE_MOD = {}


@contextlib.contextmanager
def nurture_tools(ws: Path):
    """The workspace's own nurture.py, loaded with its System/tools/ on the
    path for as long as the block runs, and its context for today. Nothing
    beside this extra: what it counts is that workspace's pages."""
    key = Path(ws)
    src = key / "System" / "tools" / "nurture.py"
    if not src.is_file():
        raise Refused("System/tools/nurture.py is missing; update Garrick")
    with tools_path(key):
        if key not in _NURTURE_MOD:
            try:
                spec = importlib.util.spec_from_file_location("garrick_page_nurture", str(src))
                mod = importlib.util.module_from_spec(spec)
                sys.modules["garrick_page_nurture"] = mod
                spec.loader.exec_module(mod)
            except Exception as e:
                raise Refused("System/tools/nurture.py cannot be loaded (%s); update Garrick" % type(e).__name__)
            if not all(callable(getattr(mod, n, None)) for n in ("organisation_item", "party_item", "record_answer",
                                                                  "run_correction", "record_correction", "Ctx")):
                raise Refused("this workspace's nurture.py is too old for the Questions panel; update Garrick")
            _NURTURE_MOD[key] = mod
        yield _NURTURE_MOD[key]


class RowRefused(Exception):
    """One row put back, with the words the row says."""


def zone_names(ws: Path) -> set:
    folder = Path(ws) / "Zones"
    return {z.name for z in folder.iterdir() if z.is_dir()} if folder.is_dir() else set()


class View:
    """The near side of the walls for what the Questions panel shows: the zone
    shown, and the party chosen in it. `ok(tags)` is the one test, for what the
    panel lists, counts and offers and for what a save may write: every tag
    belongs to the zone, no two are walled from each other, and, with a party
    chosen, it is among them and none is walled from it. The view of entity
    pages that do not say whose they are (`zone` is UNATTRIBUTED) names, as
    `scope`, the zone whose parties may be given to them. Fail closed: an
    unknown zone or party, or a zone whose own parties a wall divides with no
    party chosen, is refused with the rules' sentence."""

    def __init__(self, ws: Path, lib, zone, scope):
        wall = wall_sentence(ws)
        self.lib, self.ctx, self.ws = lib, lib.load_context(ws), ws
        zones = zone_names(ws)
        self.unattributed = zone == UNATTRIBUTED and zone not in zones
        home = str(scope).strip() if self.unattributed and scope else zone
        scope = bare_tag(lib, str(scope)) if scope not in (None, "") and not self.unattributed else None
        if not isinstance(home, str) or home not in zones:
            raise Refused(wall)
        self.zone = home
        self.parties = {t for t, p in (self.ctx.get("parties") or {}).items() if str(p.get("zone") or "").strip() == home}
        self.chosen = None
        if self.unattributed:
            return
        if scope is not None:
            if scope not in self.parties:
                raise Refused(wall)
            self.chosen = scope
        elif not self.parties or two_walled(lib, self.ctx, self.parties):
            raise Refused(wall)

    def ok(self, tags) -> bool:
        tags = set(tags or ())
        if self.unattributed or not tags or not tags <= self.parties:
            return False
        if two_walled(self.lib, self.ctx, tags):
            return False
        return self.chosen is None or self.chosen in tags


def page_party_tags(lib, ws: Path, path: Path) -> Optional[set]:
    """The party tags a Meetings page names, `party:` and `parties:`; None when
    it cannot be read plainly or names none (treated as walled)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if lib.frontmatter_form_problem(text):
        return None
    fm = lib.parse_frontmatter_text(text)
    # Two spellings of the party key (`party:` and `PARTY:`) can be read two ways: the page says whose it is to no one.
    if any(str(k).strip().lower() in ("party", "parties") and str(k).strip() not in ("party", "parties") for k in fm):
        return None
    got = lib.labels(ws, path)          # one derivation: a page whose party: and parties: disagree reads as neither
    known = lib.load_context(ws).get("parties", {})
    tags = set(got or ())
    return tags if tags and all(t in known for t in tags) else None


def near_side(lib, ws: Path, view: "View", path: Path) -> bool:
    return view.ok(page_party_tags(lib, ws, path))


def meetings_page(ws: Path, rel, folder: str) -> Path:
    """A page of the Meetings wiki's wiki/<folder>/, by its path from the
    workspace's top; anything else, a link, or a path out of the folder, is
    refused."""
    if not isinstance(rel, str) or not rel.endswith(".md") or rel.startswith(("/", "~")) or "\0" in rel or len(rel) > 400:
        raise RowRefused("not a page of the Meetings wiki")
    base = (Path(ws) / "Wikis" / "Meetings" / "wiki" / folder).resolve()
    raw = Path(ws) / rel
    path = raw.resolve()
    if base not in path.parents or raw.is_symlink() or not path.is_file() or SKIP & set(path.relative_to(base).parts):
        raise RowRefused("that page is not in wiki/%s/ any more" % folder)
    # On a disk that ignores case a path can be spelled two ways and git knows one: only the spelling on disk is taken.
    here = Path(ws).resolve()
    for part in path.relative_to(here).parts:
        if part not in os.listdir(str(here)):
            raise RowRefused("that page is not in wiki/%s/ any more" % folder)
        here = here / part
    return path


def clean_in_repo(ws: Path, path: Path) -> None:
    """Refuse a page whose repository cannot be found, or that has changes not
    committed or is not committed at all: a commit of it would carry somebody
    else's work."""
    repo = repo_of_path(ws, path)
    if repo is None:
        raise RowRefused("no repository holds that page, so it could not be undone")
    code, said = git(repo, "status", "--porcelain", "--untracked-files=all", "--", str(path.relative_to(repo)))
    if code != 0 or said.strip():
        raise RowRefused("that page has changes not committed, or is not committed at all")


def clean_rows(req: dict) -> list:
    rows = req.get("rows")
    if not isinstance(rows, list) or not rows:
        raise Refused("there is nothing to save")
    if len(rows) > NURTURE_ROWS_MAX:
        raise Refused("at most %d answers are saved at once" % NURTURE_ROWS_MAX)
    out = []
    for r in rows:
        if not isinstance(r, dict) or set(r) - set(NURTURE_ROW_KEYS):
            raise Refused("an answer carries a field the review page does not send, so nothing was written")
        if r.get("do") not in NURTURE_DO or r.get("choice", "yes") not in NURTURE_CHOICES:
            raise Refused("an answer is not one the review page sends, so nothing was written")
        for k in ("key", "path", "pick", "until"):
            v = r.get(k)
            if v is not None and (not isinstance(v, str) or len(v) > 400 or "\0" in v or (k == "pick" and len(v) > NURTURE_WORD_MAX)):
                raise Refused("an answer carries a value the review page does not send, so nothing was written")
        if r.get("key") is not None and not KEY_RE.fullmatch(r["key"]):
            raise Refused("an answer names a finding by a key the review page does not make, so nothing was written")
        edit = r.get("edit")
        if edit is not None:
            if isinstance(edit, dict) and isinstance(edit.get("old"), str) and len(edit["old"].strip()) < 3:
                raise Refused("the value to correct needs at least three characters, so nothing was written")
            if not isinstance(edit, dict) or set(edit) - {"old", "new"} or not all(
                    isinstance(edit.get(k), str) and 0 < len(edit[k]) <= NURTURE_WORD_MAX
                    and not any(ord(c) < 32 or c == "\x7f" for c in edit[k]) for k in ("old", "new")):
                raise Refused("a correction carries more than the two values, so nothing was written")
        out.append(dict(r, choice=r.get("choice", "yes")))
    return out


def later_path(ws: Path) -> Path:
    return Path(ws).joinpath(*NURTURE_LATER)


def read_later(ws: Path) -> dict:
    """Rows put off: {key: {"until": day, "path": page}}. A key is bound to the
    page it was put off for, so a forged key cannot hide another finding."""
    try:
        data = json.loads(later_path(ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if KEY_RE.fullmatch(str(k)) and isinstance(v, dict)
            and isinstance(v.get("until"), str) and isinstance(v.get("path"), str)}


def save_later(ws: Path, put: dict, drop: set) -> None:
    """Rows put off until a date, and rows that were answered: a small file the
    tools own, beside the day's report, never committed."""
    data = read_later(ws)
    if not put and not (drop & set(data)):
        return
    for k in drop:
        data.pop(k, None)
    data.update(put)
    target = later_path(ws)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=target.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=1, sort_keys=True) + "\n")
        os.replace(tmp, str(target))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def put_back(w: Writes, rows: list, bad: dict, say_wall: str, refuse) -> None:
    """Put back the rows in `bad` ({tag: kind}) and any row that shares a real
    file with one, until no more do, and say each: the rules' sentence for a
    wall, else what the kind is. What is put back is worked out after the
    sharing is settled, so a row said not to be written has all its files back."""
    while True:
        back = set()
        for tag in bad:
            back |= {p for p, o in w.owners.items() if tag in o}
        more = {tag for tag, row in rows if tag not in bad and any(tag in o for p, o in w.owners.items() if p in back)}
        if not more:
            break
        for tag in more:
            bad[tag] = "wall"
    w.undo(back)
    for tag, kind in bad.items():
        refuse(tag, say_wall if kind == "wall" else
               "the walls check could not read this page's form, so nothing was written for it" if kind == "form" else
               "a check found something new on this page, so nothing was written for it" if kind == "new" else
               "another session has files staged in that repository, so nothing was written for it")


def walls_gate(ws: Path, w: Writes, rows: list, say_wall: str, refuse) -> None:
    """The walls check on what the rows wrote, staged, per repository. When it
    refuses, each row is checked on its own files, the rows it refuses are put
    back (and any row that shares a file with one), and the rest are checked
    again. `rows` are (tag, the row); `refuse(tag, why)` records a row put
    back. A refusal no row accounts for refuses the lot."""
    def check(files) -> str:
        groups = {}
        for p in files:
            repo = repo_of_path(ws, p)
            if repo is None:
                continue
            groups.setdefault(repo, []).append(str(p.relative_to(repo)))
        for repo, rels in groups.items():
            stage(repo, rels)
            try:
                said = walls_on_staged(ws, repo, rels)
            finally:
                unstage(repo, rels)
            if said:
                return said
        return ""
    changed = set(w.changed())
    said = check(changed)
    if not said:
        return
    bad = {}
    for tag, row in rows:
        mine = [p for p, o in w.owners.items() if tag in o and p in changed]
        one = check(mine) if mine else ""
        if one:
            bad[tag] = refusal_kind(one)
    if not bad:
        raise Refused(say_wall if refusal_kind(said) == "wall" else
                      "the walls check could not pass the change as a whole (%s), so nothing was written" % refusal_kind(said))
    put_back(w, rows, bad, say_wall, refuse)
    left = set(w.changed())
    again = check(left) if left else ""
    if again:
        raise Refused(say_wall if refusal_kind(again) == "wall" else
                      "the walls check could not pass what was left, so nothing was written")


def nurture_save(ws: Path, req: dict, rows: list, today: dt.date, single: bool = False):
    """Save rows (see clean_rows) as one transaction. Returns the reply, or,
    for a single verb, its sentence."""
    wall = wall_sentence(ws)
    lib = prefs().lib(ws)
    if lib is None or not all(callable(getattr(lib, n, None)) for n in
                              ("parse_frontmatter_text", "frontmatter_form_problem", "load_context", "blocked", "decide",
                               "entity_names", "staged_walls_refusal")):
        raise Refused("this workspace's garrick_lib.py cannot read the walls, so nothing was written")
    view = View(ws, lib, req.get("zone"), req.get("scope"))
    headless = os.environ.get("GARRICK_HEADLESS", "").strip() not in ("", "0")
    results = {}                    # index -> {"key", "ok", "say"}
    plan = []                       # (index, row, how, item, asked, extra)

    def refuse(i, why):
        r = rows[i]
        results[i] = {"key": r.get("key"), "ok": False, "say": why}
        plan[:] = [entry for entry in plan if entry[0] != i]

    with held("nurture-answers.lock", busy="another answer is still being saved"), nurture_tools(ws) as N:
        ctx = N.Ctx(Path(ws).resolve(), headless=headless, today=today)

        def open_walls(w):
            """The pages that carry a walls-family finding already: not writable from the panel."""
            before = getattr(w, "before_counts", None) or {}
            return {f[1] for found in before.values() if isinstance(found, set) for f in found if wallish(f[0], f[2])}

        def one(i, row, w):
            """Write one row's change; a RowRefused leaves nothing of it."""
            path_rel = row.get("path")
            if row["choice"] in ("no", "later"):
                if row["do"] == "answer":
                    page = meetings_page(ws, path_rel, "entities")
                    if not view.unattributed:
                        raise RowRefused(wall)
                else:
                    page = meetings_page(ws, path_rel, "people")
                    if view.unattributed or not near_side(lib, ws, view, page):
                        raise RowRefused(wall)
                if row.get("edit") and row["do"] != "answer":
                    run_edit(i, row, page, w)
                if row["choice"] == "later":
                    try:
                        day = dt.date.fromisoformat(row.get("until") or "")
                    except ValueError:
                        raise RowRefused("not a later day: %r" % (row.get("until"),))
                    if day <= today:
                        raise RowRefused("not a later day: %r" % (row.get("until"),))
                    if not isinstance(row.get("key"), str):
                        raise RowRefused("a row put off is named by its key")
                    plan.append((i, row, "later", None, "", {"until": day.isoformat(), "path": ctx.rel(page)}))
                    return
                plan.append((i, row, "no", None, ctx.rel(page), ""))
                return
            do = row["do"]
            folder = "entities" if do == "answer" else "people"
            if do == "correct":
                if not row.get("edit"):
                    raise RowRefused("say the old value and the new one")
                page = meetings_page(ws, path_rel, "people") if "/people/" in "/" + str(path_rel) else meetings_page(ws, path_rel, "entities")
            else:
                page = meetings_page(ws, path_rel, folder)
            if do == "answer":
                if not view.unattributed:
                    raise RowRefused(wall)          # an entity page is asked about in the unattributed view only
                tag = bare_tag(lib, str(row.get("pick") or "").strip())
                if tag != "none" and tag not in view.parties:
                    raise RowRefused(wall)          # only the parties of the zone chosen are offered
            else:
                if view.unattributed or not near_side(lib, ws, view, page):
                    raise RowRefused(wall)
            if do != "correct":
                if ctx.rel(page) in open_walls(w):
                    raise RowRefused(wall)          # a page with a wall finding open is read-only here
                clean_in_repo(ws, page)
            edit = row.get("edit")
            if edit and do != "correct":
                run_edit(i, row, page, w)
            if do == "correct":
                run_edit(i, row, page, w)
                return
            try:
                if do == "answer":
                    if row["choice"] != "another":
                        raise RowRefused("say whose it is: a party, or none")
                    item, asked = N.party_item(ctx, ctx.rel(page), row.get("pick") or "")
                    answer = item.fix["party"]
                else:
                    pick = row.get("pick") or "" if row["choice"] == "another" else ""
                    if row["choice"] == "another" and not pick.strip():
                        raise RowRefused("name the entity page")
                    item, asked = N.organisation_item(ctx, ctx.rel(page), pick)
                    answer = "yes" if not pick else "another page: %s" % pick
                    target = re.fullmatch(r"\[\[wiki/entities/([^\]|#]+)\]\]", item.fix["link"])
                    entity = ctx.root.joinpath("Wikis", "Meetings", "wiki", "entities", (target.group(1) if target else "") + ".md")
                    if not target or not near_side(lib, ws, view, entity):
                        raise RowRefused(wall)
            except N.Refusal as e:
                # A page picked by name that cannot be used is said as a wall, whatever stopped it: a typed or
                # forged name must not tell a page that is not there from one on the far side.
                raise RowRefused(wall if (do == "organisation" and row["choice"] == "another") else str(e))
            w.tag = i
            N.OPS[item.fix["op"]](ctx, item, ShimJournal(w))
            plan.append((i, row, do, item, asked, answer))

        def run_edit(i, row, page, w):
            if view.unattributed or not near_side(lib, ws, view, page) or ctx.rel(page) in open_walls(w):
                raise RowRefused(wall)
            edit = row["edit"]
            w.tag = i
            index = ctx.root / "Wikis" / "Meetings" / "wiki" / "index.md"

            def only(hit) -> bool:
                """A correction in the panel reaches Meetings wiki pages on the near side of the view, and nothing
                else: not a zone's notes, a memory, a page with no readable party or another party's page."""
                pages = [hit.path] if hit.kind == "wiki" else list(hit.pages) if hit.kind == "raw" else []
                base = (ctx.root / "Wikis" / "Meetings" / "wiki").resolve()
                # A decision page is settled by the user's own save (#224, point 5): no correction rewrites its
                # `question:`, `status:`, `zone:` or `parties:`, so it is left out whole.
                settled = base / "decisions"
                return bool(pages) and all(base in Path(x).resolve().parents and settled not in Path(x).resolve().parents
                                           and near_side(lib, ws, view, Path(x)) for x in pages)
            try:
                out = N.run_correction(ctx, [ctx.rel(page)], edit["old"], edit["new"], True, "", [], ctx.rel(page),
                                       commit=False, watch=w.watch, only=only, rebuild=False)
            except ValueError as e:
                raise RowRefused(str(e))
            plan.append((i, row, "correct", out, "", edit))

        def rebuild_index(w):
            """The Meetings index, once, from the pages that remain: it belongs to no row, so a row put back
            never leaves it describing pages it did not write."""
            index = ctx.root / "Wikis" / "Meetings" / "wiki" / "index.md"
            w.tag = None
            if not any(e[2] == "correct" and e[3].get("done") and e[3]["done"].changed for e in plan):
                if index in w.before:
                    w.undo([index])
                return
            ingest = ctx.root.joinpath(*N.correct.INGEST)
            if not ingest.is_file():
                raise Refused("the Meetings index cannot be rebuilt (the meetings skill's ingest.py is missing), so nothing was written")
            w.watch(index)
            try:
                r = subprocess.run([sys.executable, str(ingest), "--root", str(ctx.root), "index"], capture_output=True, text=True,
                                   stdin=subprocess.DEVNULL, timeout=CHECK_TIMEOUT)
            except subprocess.SubprocessError:
                raise Refused("the Meetings index took too long to rebuild, so nothing was written")
            if r.returncode != 0:
                w.undo([index])
                raise Refused("the Meetings index could not be rebuilt, so nothing was written")

        def triage(w, new, walls):
            """Findings the write made, or walls-family findings on a file it wrote, put on the rows that wrote
            those files by path: the rows are put back with their own reply, and the rest go on."""
            root = Path(ws).resolve()
            hit = {f[1] for _k, f in new} | {f[1] for _k, f in walls}
            wallish_paths = {f[1] for _k, f in walls} | {f[1] for _k, f in new if wallish(f[0], f[2])}
            bad = {}
            for e in plan:
                if e[2] not in NURTURE_DO:
                    continue
                mine = {str(p.relative_to(root)) for p, o in w.owners.items() if e[0] in o and root in p.parents}
                if mine & hit:
                    bad[e[0]] = "wall" if mine & wallish_paths else "new"
            if bad:
                put_back(w, [(e[0], e[1]) for e in plan if e[2] in NURTURE_DO], bad, wall, refuse)
                rebuild_index(w)

        def change(w):
            for i, row in enumerate(rows):
                w.tag = i
                try:
                    one(i, row, w)
                except RowRefused as e:
                    refuse(i, str(e))
                except N.Held as e:
                    refuse(i, "held: %s" % e)
            w.tag = None
            walls_gate(ws, w, [(e[0], e[1]) for e in plan if e[2] in NURTURE_DO], wall, refuse)
            rebuild_index(w)
            return None

        def message(label, rels):
            repo = Path(ws).resolve() / label if label != "." else Path(ws).resolve()
            counts = {}
            for e in plan:
                if e[2] in NURTURE_DO and any(e[0] in o and repo_of_path(ws, p) == repo for p, o in TX.owners.items()):
                    counts[e[2]] = counts.get(e[2], 0) + 1
            words = {"answer": ("entity party", "entity parties"), "organisation": ("organisation link", "organisation links"),
                     "correct": ("correction", "corrections")}
            return "%s: context nurtured by hand; %s" % (
                label.split("/", 1)[-1] if label != "." else "Workspace",
                ", ".join("%d %s" % (n, words[k][0 if n == 1 else 1]) for k, n in sorted(counts.items())))

        def finish(result, done):
            refused_repos = done["refused"]
            put, answered_keys = {}, set()
            for e in list(plan):
                i, row, how, item, asked, extra = e
                if how in ("no", "later"):
                    if how == "later":
                        put[row["key"]] = extra
                    said = "Left as it is" if how == "no" else "Put off until %s" % extra["until"]
                    before = results.get(i)
                    one_outcome = before["say"] if before and before["ok"] and how == "no" else \
                        "%s; %s" % (before["say"], said.lower()) if before and before["ok"] else said
                    results[i] = {"key": row.get("key"), "ok": True, "say": one_outcome}
                    continue
                files = [p for p, o in TX.owners.items() if i in o] if TX else []
                repos = {repo_of_path(ws, p) for p in files}
                failed = [r for r in repos if r is not None and (str(r.relative_to(Path(ws).resolve())) if r != Path(ws).resolve() else ".") in refused_repos]
                if failed:
                    names = {str(r.relative_to(Path(ws).resolve())) if r != Path(ws).resolve() else "." for r in repos if r is not None}
                    kept = sorted(n for n in names if n in done["commits"])
                    results[i] = {"key": row.get("key"), "ok": False,
                                  "say": ("committed in %s, not committed elsewhere and put back there" % ", ".join(kept)) if kept
                                  else "not committed, so nothing changed"}
                    continue
                if how == "correct":
                    out = item
                    said = "Corrected %s to %s" % (extra["old"], extra["new"]) if out.get("done") and out["done"].changed else \
                        "Nothing live held the old value"
                    results[i] = {"key": row.get("key"), "ok": True, "say": said}
                    continue
                results[i] = {"key": row.get("key"), "ok": True,
                              "say": ("Whose it is: %s" % extra) if how == "answer" else "Where they work: written"}
                answered_keys.add(row.get("key"))
            # the day's report: the same lines the chat path writes
            for e in plan:
                i, row, how, item, asked, extra = e
                if how == "no" and results.get(i, {}).get("ok"):
                    N.record_answer(ctx, asked, "Is the proposed answer right?", "no", settled=False)
                    continue
                if not results.get(i, {}).get("ok") or how in ("no", "later"):
                    continue
                if how == "correct":
                    class Done:
                        pass
                    d = Done()
                    app = item.get("done")
                    d.commits = [(r, s) for r, s in done["commits"].items()]
                    d.changed = list(app.changed) if app else []
                    d.superseded = list(app.superseded) if app else []
                    d.uncommitted = [(p, "in no repository, so changed and not committed") for p in done["uncommitted"]]
                    d.refused = list(done["refused"].items())
                    rec = N.read_record(ctx)
                    N.record_correction(ctx, rec, item["item"], extra["old"], extra["new"], "", d)
                    N.write_report(ctx, rec)
                elif how == "answer":
                    N.record_answer(ctx, item.path, asked, extra)
                else:
                    N.organisation_answered(ctx, item, asked, "" if extra == "yes" else extra.split(": ", 1)[-1])
            save_later(ws, put, {k for k in answered_keys if k})
            return results

        if not any(True for _ in rows):
            raise Refused("there is nothing to save")
        out = transaction(ws, change, commit=message, after=finish, triage=triage)
    saved = sum(1 for r in out.values() if r["ok"] and not r["say"].startswith(("Left as it is", "Put off")))
    later = sum(1 for r in out.values() if r["ok"] and r["say"].startswith("Put off"))
    held_back = [r for r in out.values() if not r["ok"]]
    if single:
        only = out[0]
        if not only["ok"]:
            raise Refused(only["say"])
        return only["say"]
    say = "Saved %d answer%s" % (saved, "" if saved == 1 else "s")
    if later:
        say += ", put off %d" % later
    if held_back:
        say += ". %d row%s put back, named below" % (len(held_back), " was" if len(held_back) == 1 else "s were")
    return {"say": say, "rows": [dict(out[i], index=i) for i in sorted(out)]}


NURTURE_GROUPS_MAX = 20


def nurture_save_all(ws: Path, req: dict, today: dt.date):
    """A save from the panel's *All* view (#384). `groups` is a list of
    {"zone", "scope", "rows"}, one for each view the rows were shown in. Each
    group is saved as it would be from its own view: its own View, its own
    transaction, its own check and its own commit, through nurture_save. Two
    groups are never one transaction, so a wall between them cannot be
    crossed by saving together. A group that is refused as a whole (its view
    refused, the checks cannot run) is named and the others go on; the walls
    still hold in each. The reply is nurture_save's, with the rows of every
    group and the say of each."""
    groups = req.get("groups")
    if not isinstance(groups, list) or not groups:
        raise Refused("there is nothing to save")
    if len(groups) > NURTURE_GROUPS_MAX:
        raise Refused("at most %d groups are saved at once" % NURTURE_GROUPS_MAX)
    clean = []
    for g in groups:
        if not isinstance(g, dict) or set(g) - {"zone", "scope", "rows"}:
            raise Refused("a group carries a field the review page does not send, so nothing was written")
        for k in ("zone", "scope"):
            if g.get(k) is not None and (not isinstance(g[k], str) or len(g[k]) > 200 or "\0" in g[k]):
                raise Refused("a group carries a value the review page does not send, so nothing was written")
        clean.append((g.get("zone"), g.get("scope"), clean_rows(g)))
    rows, said, results = [], [], []
    for gi, (zone, scope, mine) in enumerate(clean):
        try:
            reply = nurture_save(ws, {"zone": zone, "scope": scope}, mine, today)
            ok, whole = True, False
        except Refused as e:
            whole = True
            reply = {"say": str(e), "rows": [{"key": r.get("key"), "ok": False, "say": str(e), "index": i} for i, r in enumerate(mine)]}
            ok = False
        rows.extend(dict(r, group=gi) for r in reply["rows"])
        said.append(reply["say"])
        results.append({"zone": zone, "scope": scope, "ok": ok and all(r["ok"] for r in reply["rows"]), "say": reply["say"],
                        "refused": whole})
    return {"say": " | ".join(said), "rows": rows, "groups": results}


class ShimJournal:
    """What nurture's fixes write through, in place of its Journal: the
    transaction's Writes, which put every file back."""

    def __init__(self, w):
        self.w = w

    def write(self, path, text):
        self.w.write(path, text)


def nurture_act(ws: Path, req: dict, today: dt.date):
    verb = req["verb"]
    if verb == "nurture-save":
        return nurture_save(ws, req, clean_rows(req), today)
    if verb == "nurture-save-all":
        return nurture_save_all(ws, req, today)
    if verb == "nurture-answer":
        row = {"do": "answer", "path": req.get("path"), "choice": "another", "pick": req.get("party")}
    elif verb == "nurture-organisation":
        row = {"do": "organisation", "path": req.get("path"), "choice": "another" if req.get("entity") else "yes",
               "pick": req.get("entity") or None}
    else:
        row = {"do": "correct", "path": req.get("path"), "choice": "yes",
               "edit": {"old": req.get("old"), "new": req.get("new")}}
    return nurture_save(ws, req, clean_rows({"rows": [{k: v for k, v in row.items() if v is not None}]}), today, single=True)


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
    its note, its project's hub, the questions in each Needs you folder the
    work keeps, and the Claude settings of the folder its sessions start in.
    Nothing else of the folder, which holds the user's files."""
    project = zone / parts[0]
    hub = project / (parts[0] + ".md")
    boxes = dict.fromkeys([note.parent / NEEDS] + ([project / NEEDS] if folder == project else []))
    settings = folder.joinpath(*your_work().CLAUDE_SETTINGS)     # the read-only rule for a folder of the user's (#182)
    return ([n.relative_to(zone).as_posix() for n in dict.fromkeys([note, hub, settings])]
            + [":(glob)%s/*.md" % b.relative_to(zone).as_posix() for b in boxes])


def commit_record(zone: Path, note: Path, parts: tuple, folder: Path, name: str, *, wall: Optional[str]) -> str:
    """Garrick's own record of the work committed before Claude opens on it,
    so the desktop app's Changes panel has nothing of Garrick's to offer:
    record_files() by name, and only those that changed; anything else in the
    folder is the user's and is left as it is. "" when that went through or
    there was nothing to commit; otherwise why not, for the reply: `wall`
    alone where the wall check refused it. Nothing is put back: the files
    are the user's."""
    code, said = git(zone, "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all", "--",
                     *record_files(zone, note, parts, folder))
    if code != 0:
        return ""
    changed = [":(literal)" + e[3:] for e in said.split("\0") if len(e) > 3]
    if not changed:
        return ""
    deadline = time.time() + COMMIT_TIMEOUT
    problem = commit_refusal(zone)
    code, why = (1, "%s, so nothing was committed" % problem) if problem else git(zone, "add", "-A", "--", *changed)
    if code == 0:
        code, why = git(zone, "commit", "-q", "-m", ("%s: saved before opening in Claude" % name)[:200], "--", *changed,
                        timeout=deadline - time.time())
    if code == 0:
        return ""
    git(zone, "reset", "-q", "--", *changed, timeout=10)
    why = why if code is None else (why.strip().splitlines() or ["git refused"])[-1]
    return wall if wall and code is not None and WALL_LINE.match(why) else why


def continue_work(ws: Path, req: dict, now: Optional[dt.datetime] = None) -> str:
    """Continue: Claude's desktop app opened on a piece of work, already
    oriented. The record committed, a headless call asked where the work
    stands, its session handed to the desktop app; a session continued
    within FRESH_HOURS is resumed as it was, without asking again.

    A piece of work whose files are in a folder of the user's (#182) is read
    there: the call gets the folder, and the text of its Office files, with
    `--add-dir`, and Edit is denied in it, by a rule in the Claude settings
    of the folder the session starts in, committed with Garrick's record
    before anything opens, and by `--settings` on the call. The rule covers
    Claude's file-editing tools in every mode, not a shell command, approved
    or run by Auto mode. With
    `suggested`, the first
    look's suggested request is asked instead of where it stands, once."""
    H, Y = handoff(), your_work()
    zone, note, parts, _ = resume_note(ws, req)
    name = work_name(zone, parts)
    asked, brief = "Where am I on %s?" % say_name(ws, zone, parts), H.CONTINUE_BRIEF
    key = "%s/%s" % (zone.name, note.relative_to(zone).as_posix())
    suggested = req.get("suggested")
    if suggested not in (None, True, False):
        raise Refused("not a yes or no: suggested")
    look = Y.first_looks(ws).get(key) if suggested else None
    if suggested:
        if not isinstance(look, dict) or look.get("used") or not look.get("request"):
            raise Refused("there is no suggested request waiting for %s; press Continue" % name)
        asked, brief = " ".join(str(look["request"]).split())[:PROMPT_MAX].lstrip("- "), H.REQUEST_BRIEF
    if H.managed_off(managed_places()):          # not kept: the page reads the setting at every build
        raise Refused("%s %s" % (H.LOCAL_OFF_TITLE, H.LOCAL_OFF))
    claude = H.find_claude()
    if claude is None:
        raise Refused(H.NO_CLI)
    folder = work_folder(zone, parts)
    files, own = files_folder(ws, zone, parts)
    add_dirs, guard = [], None
    # Where its files live (#189): a copy kept is refreshed from the folder first, and Claude still reads the
    # folder; moved files are read, and may be edited, in Garrick, with a version kept first so an edit can be undone.
    F, hub = work_files_lib(), zone / parts[0] / (parts[0] + ".md")
    w = stored_work(ws, req) if (name == parts[0] and hub.is_file() and hub_value(hub, Y.DISCOVERED)
                                 and hub_value(hub, "folder")) else None
    moved, walked, refreshed = bool(w and w["mode"] == F.MOVED), files, ""
    if w and w["mode"] == F.COPY:
        try:
            with files_lock(w):
                refreshed = "Garrick refreshed its copy first. " + refresh_copy(ws, w, now or dt.datetime.now(), "continue")["said"]
        except Refused as e:
            refreshed = str(e).rstrip(".") + "."
    with zone_lock(zone):
        extracts = (Y.first_looks(ws).get(key) or {}).get("extracts")
        extracts = [ws / extracts] if extracts and (ws / extracts).is_dir() else []
        if moved:
            storage_rules(w, True)              # committed below, with Garrick's own record of the work
            try:
                F.history_keep(w["files"], "Kept before Claude opened it")
            except F.Refused:
                pass
            add_dirs, walked = [w["files"]] + extracts, w["files"]
        elif not own:
            read_only_rule(folder, files)       # committed below, with Garrick's own record of the work
            if w:
                storage_rules(w, False)         # and Garrick's copy kept out of reach too, while there is one
            add_dirs = [files] + extracts
            guard = deny_arg(w, False) if w else Y.settings_arg(str(files))
        if len(add_dirs) > 1:                   # where the text of its Office files is: in the hidden brief, never the
            brief = "%s %s" % (brief, Y.EXTRACTS_SAID % add_dirs[1])     # message the user sees as theirs
        unsaved = commit_record(zone, note, parts, folder, name, wall=wall_refusal(ws))
    kept = H.session_for(ws, key)
    resume = not suggested and H.fresh(kept, now) and kept.get("folder") == str(folder)
    try:
        sid = kept["id"] if resume else H.prime(claude, folder, asked, brief=brief, name=name, add_dirs=add_dirs,
                                                 settings=guard)[0]
        try:
            H.open_desktop(claude, folder, sid)
        except (H.LocalOff, H.TimedOut):
            raise                               # a timeout may well have opened it: never a second window
        except H.HandOffError:
            if not resume:
                raise
            resume = False                      # the kept session would not open: ask afresh, once
            sid = H.prime(claude, folder, asked, brief=brief, name=name, add_dirs=add_dirs, settings=guard)[0]
            H.open_desktop(claude, folder, sid)
    except H.LocalOff as e:
        H.mark_local_off(ws, "refused")
        raise Refused(str(e))
    except H.HandOffError as e:
        raise Refused(str(e))
    H.keep_session(ws, key, sid, folder, H.walk(walked, project=own and not moved), primed=not resume, now=now)
    if suggested:
        Y.keep_first_look(ws, key, used=True)
        said = "Opened %s in Claude, with your request already asked" % name
    else:
        said = "Opened %s in Claude%s" % (name, "" if resume else ". It already knows where it stands")
    if refreshed:
        said = "%s. %s" % (said, refreshed.rstrip("."))
    if unsaved and unsaved == wall_refusal(ws):     # the rule's sentence ends the reply, and nothing is added to it
        return "%s. Garrick's record of it is not committed. %s" % (said, unsaved)
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


# ---- your own work (#182): a folder you already keep, read and never written ----
# Add your own work picks a folder in the Mac app; discover.py proposes the
# pieces of work in it from names and dates alone, and keeps the proposals and
# the answers in System/generated/discovery.json. A yes makes Garrick's record
# of one, a project with one thread whose hub's `folder:` names the folder,
# committed by name. Start with this one reads its files for the first time:
# extract.py takes the text out of its Office files, a headless read-only call
# answers with a first look, and Garrick writes it into the thread note and the
# hub, with the next step as a Needs you question. Stop using this puts the
# record away under the zone's archive/, recoverably; Bring it back returns it.
# Nothing here writes under the folder: the two tools refuse to. Claude's
# file-editing tools are kept out by an Edit deny rule in the Claude settings
# of the folder its sessions start in, and by `--settings` on every headless
# call; a shell command, approved or run by Auto mode, is covered by neither.
_YW = None
FOLDER_MAX = 1024
FIRST_LOOK_TIMEOUT = 360          # seconds for the call that reads a piece of work's files for the first time
TOOL_TIMEOUT = 300                # for discover.py, which lists a folder that may be a large cloud drive
EXTRACT_TIMEOUT = 180             # for extract.py, on one piece of work's Office files


def your_work():
    """your_work.py, beside this file: what the page and these actions share about the user's own work."""
    global _YW
    if _YW is None:
        spec = importlib.util.spec_from_file_location("garrick_your_work", str(HERE / "your_work.py"))
        _YW = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_YW)
    return _YW


def tool_json(ws: Path, name: str, *args, timeout: float = TOOL_TIMEOUT) -> dict:
    """One of the workspace's own tools, with --json: what it answered, or Refused in its words."""
    tool = ws / "System" / "tools" / name
    if not tool.is_file():
        raise Refused("System/tools/%s is missing; update Garrick" % name)
    try:
        r = subprocess.run([sys.executable, str(tool), "--root", str(ws), "--json"] + list(args), capture_output=True,
                           text=True, timeout=timeout, stdin=subprocess.DEVNULL, cwd=str(ws))
    except subprocess.TimeoutExpired:
        raise Refused("%s was still running after %s and was stopped; nothing was changed" % (name, how_long(timeout)))
    try:
        out = json.loads(r.stdout)
    except ValueError:
        said = (r.stderr or r.stdout).strip().splitlines()
        raise Refused(said[-1] if said else "%s did not answer" % name)
    if not isinstance(out, dict):
        raise Refused("%s did not answer" % name)
    if r.returncode != 0 or out.get("error"):
        raise Refused(str(out.get("error") or "%s refused" % name).rstrip("."))
    return out


def context_of(ws: Path) -> dict:
    lib = prefs().lib(ws)
    try:
        return lib.load_context(ws) if lib is not None and callable(getattr(lib, "load_context", None)) else {}
    except Exception:
        return {}


def picked_folder(req: dict) -> str:
    """The folder the picker gave: an absolute path, on one line."""
    folder = req.get("folder")
    if not isinstance(folder, str) or not folder.strip() or "\n" in folder or len(folder) > FOLDER_MAX:
        raise Refused("no folder given")
    folder = os.path.expanduser(folder.strip())
    if not os.path.isabs(folder):
        raise Refused("not a folder Garrick can read: %s" % folder)
    return folder


def discover_folder(ws: Path, req: dict) -> dict:
    """Add your own work: the picked folder looked through by discover.py,
    names and dates only, and its proposals kept for the page to show."""
    out = tool_json(ws, "discover.py", "scan", picked_folder(req))
    top, more = out.get("top") or [], out.get("more") or []
    name = out.get("name") or os.path.basename(out.get("folder") or "")
    if top:
        said = "Found %d piece%s of work in %s. Nothing in it was changed" % (
            len(top) + len(more), "" if len(top) + len(more) == 1 else "s", name)
    else:
        said = "Nothing new in %s looks like a piece of work. Nothing in it was changed" % name
    return {"say": said, "view": your_work().view_id(out.get("folder") or "")}


def suggestion(ws: Path, pid) -> tuple:
    """(the looked-at folder, the proposal) for a proposal's id."""
    if not isinstance(pid, str) or not re.fullmatch(r"[0-9a-f]{8}", pid):
        raise Refused("not a suggestion: %r" % (pid,))
    for real, entry in your_work().discovery(ws)["folders"].items():
        for p in (entry.get("top") or []) + (entry.get("more") or []):
            if isinstance(p, dict) and p.get("id") == pid:
                return real, p
    raise Refused("that suggestion is not waiting any more; the page rebuilds now")


def answer_suggestion(ws: Path, req: dict) -> str:
    """Yes, Rename or Not a piece of work, on one proposal. Not is kept by
    discover.py, so it is never proposed again. A yes, or a rename, makes
    Garrick's record of the work: a project with one thread, named after it,
    in the workspace's only place for work, or the one the request names
    after the page asked; its hub's `folder:` names the folder, and only the
    new project is committed."""
    Y = your_work()
    real, p = suggestion(ws, req.get("id"))
    said_answer = req.get("answer")
    if said_answer not in ("yes", "rename", "not"):
        raise Refused("not an answer to a suggestion: %r" % (said_answer,))
    if said_answer == "not":
        tool_json(ws, "discover.py", "answer", p["id"], "not")
        return "Noted: %s is not a piece of work. It won't be suggested again" % p.get("name")
    name = field(req, "name") if said_answer == "rename" else str(p.get("name") or "").strip()
    options = Y.places(ws, context_of(ws))
    if not options:
        raise Refused(Y.NOWHERE)
    chosen = [o for o in options if req.get("zone") in (None, o["zone"]) and req.get("party") in (None, o["party"])]
    if len(options) == 1:
        chosen = options
    if len(chosen) != 1:
        raise Refused(Y.which_place(chosen or options))
    place = chosen[0]
    zone = zone_dir(ws, place["zone"])
    path = p.get("path") or real
    owner = answer(req, "owner", required=False, most=NAME_MAX)
    with zone_lock(zone):
        party = place["party"]
        if party is None:
            # The work's zone has no party yet, as before any interview: whose work it is, asked on the page,
            # becomes one, committed on its own in the workspace's repository, then the yes goes on.
            if not owner:
                raise Refused(Y.OWNER_ASK)
            party = owner_party(ws, zone, Y.owner_name(owner))
        scaffold(ws, "project", "--zone", zone.name, "--name", name, "--party", party, "--thread", name, "--check")
        made = [] if (zone / name).exists() else [zone / name]
        scaffold(ws, "project", "--zone", zone.name, "--name", name, "--party", party, "--thread", name)
        hub = zone / name / (name + ".md")
        hub.write_text(set_front(hub.read_text(encoding="utf-8"), {"folder": quoted(Y.folder_value(path)),
                                                                     Y.DISCOVERED: p["id"]}), encoding="utf-8")
        # Edit denied in the folder from the start, in the project's own Claude settings, where every session on
        # the work starts: committed with the project, it moves with it, put away and brought back.
        read_only_rule(zone / name, Path(path))
        commit_new(zone, [name], ("New work %s, from %s" % (name, os.path.basename(real)))[:200], made, {},
                   wall=wall_refusal(ws))
    tool_json(ws, "discover.py", "answer", p["id"], *(("rename", name) if said_answer == "rename" else ("yes",)))
    return "Garrick will keep track of %s. %s is as it was" % (name, os.path.basename(real))


def owner_party(ws: Path, zone: Path, name: str) -> str:
    """The tag of the party `name` in `zone`, made by `scaffold.py party` when
    there is none, and System/context.md committed on its own in the
    workspace's own repository, as scaffold.py says a new party is."""
    if not name or "\n" in name or len(name) > NAME_MAX or name.startswith("-"):
        raise Refused(your_work().OWNER_ASK)
    if name.strip().casefold() == "none":         # a reserved tag is no party's name
        raise Refused(your_work().OWNER_ASK)

    def found():
        for tag, p in (context_of(ws).get("parties") or {}).items():
            if str(p.get("party") or "").strip().casefold() == name.casefold():
                return tag, str(p.get("zone") or "").strip()
        return None, ""
    tag, where = found()
    if tag:
        if where.casefold() != zone.name.casefold():
            raise Refused("%s already has work kept elsewhere in your workspace. Ask Claude where this work belongs"
                          % name)
        return tag
    context = ws / "System" / "context.md"
    before = context.read_bytes() if context.is_file() else b""
    scaffold(ws, "party", "--name", name, "--zone", zone.name, "--what",
             "Whose work is kept in %s, as said on the simple home" % zone.name)
    tag, _ = found()
    if not tag:
        context.write_bytes(before)
        raise Refused("Garrick could not note whose work this is. Ask Claude to set up your workspace")
    if (ws / ".git").exists():
        commit(ws, context, before, "New party %s (%s), in %s, from the simple home" % (name, tag, zone.name),
               wall=wall_refusal(ws))
    return tag


def work_files_of(ws: Path, zone: Path, parts: tuple) -> tuple:
    """(the folder of a piece of work started from a folder of the user's,
    the files of it that belong to the work or None for all, the proposal's
    id or ""). Refused for a piece of work kept in Garrick itself."""
    hub = zone / parts[0] / (parts[0] + ".md")
    files, own = files_folder(ws, zone, parts)
    if own:
        raise Refused("%s keeps its files in Garrick, not in a folder of yours" % parts[0])
    pid = hub_value(hub, your_work().DISCOVERED)
    members = None
    if pid:
        for entry in your_work().discovery(ws)["folders"].values():
            a = (entry.get("answers") or {}).get(pid)
            if isinstance(a, dict) and a.get("kind") == "names":
                members = [m for m in a.get("members") or [] if isinstance(m, str)]
    return files, members, pid


def read_only_rule(session: Path, folder: Path):
    """Edit denied in a folder of the user's, in the Claude settings of the
    folder a session on the work starts in: Claude Code reads a project's
    settings from there and from nowhere above it. (the file, the bytes it
    held before or None for a new one) when it was written; None when it
    already said so. The caller commits it with the work's record."""
    try:
        before = your_work().read_only(session, str(folder))
    except ValueError as e:
        raise Refused("%s, so Claude could not be kept from changing %s. Nothing was opened" % (e, folder.name))
    if before is False:
        return None
    return session.joinpath(*your_work().CLAUDE_SETTINGS), before


def first_look_note(text: str, look: dict, today: dt.date, where: str, name: str) -> str:
    """The thread note with the first look written in: its opening sentence,
    a Resume here block that says it is a first look to check, and a dated
    entry. The template's placeholders it fills go; anything else stays."""
    Y = your_work()
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise Refused("%s has no frontmatter" % name)
    if re.search(r"(?m)^%s:" % Y.FIRST_LOOK, m.group(1)):
        raise Refused("%s already has its first look; Continue goes on from it" % name)
    text = set_front(text, {"updated": today.isoformat(), Y.FIRST_LOOK: today.isoformat()})
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    body = text[m.end():]
    body = re.sub(r"(?m)^<One or two sentences: what this thread is for[^\n]*>[ \t]*$", lambda _: look["what"], body, count=1)
    body = re.sub(r"(?m)^<Who asked, when, and in their words[^\n]*>[ \t]*$",
                  lambda _: "Started on %s from the files in %s, through Add your own work." % (Y.today_said(today), where),
                  body, count=1)
    body = re.sub(r"(?m)^<Dated entries[^\n]*>[ \t]*\n?", "", body)
    body = re.sub(r"(?m)^\*\*<D Month YYYY>\.\*\*[^\n]*\n?", "", body)
    span = resume_block(body)
    if not span:
        raise Refused("%s has no Resume here block to write its first look in" % name)
    stands = " ".join(x for x in ("First look, made by Garrick from the files in %s; check it before you rely on it." % where,
                                   look["last"], look["open"],
                                   "Involved: %s." % look["who"].rstrip(".") if look["who"] else "") if x)
    rows = [("Live artifact", "the files in %s, read and never changed" % where),
            ("Rebuild with", "nothing to rebuild: the files stay where they are"),
            ("Next action", look["next"]),
            ("Keep in mind", "a first look, made from the files; the question in Needs you confirms the next action"),
            ("Waiting on", look["waiting"]),
            ("Deadline", look["deadline"])]
    block = "\n**Where it stands, %s.** %s\n\n| | |\n|---|---|\n%s\n\n" % (
        Y.today_said(today), stands, "\n".join("| %s | %s |" % (k, cell(v)) for k, v in rows))
    body = body[:span[0]] + block + body[span[1]:]
    body = dated_entry(body, today, Y.FIRST_ENTRY % (where, look["last"]))
    return text[:m.end()] + body


def first_look_hub(text: str, what: str) -> str:
    """The hub with its opening sentence, where the template's placeholder still stands."""
    return re.sub(r"(?m)^<One or two sentences: what this project is[^\n]*>[ \t]*$", lambda _: what, text, count=1)


def first_look_question(name: str, look: dict, today: dt.date) -> str:
    """The Needs you question that asks the user to confirm the proposed next step, or to say it."""
    Y = your_work()
    return ("---\ntype: question\nasked: %s\nstatus: open\nown: %s\n---\n\n**%s: is this your next step?**\n\n%s\n\n%s"
            "- [%s] %s\n" % (today.isoformat(), quoted(Y.OWN), name, look["next"],
                             "From: %s\n\n" % look["source"] if look["source"] else "", Y.RIGHT, look["next"]))


def start_work(ws: Path, req: dict, today: dt.date) -> dict:
    """Start with this one: the first time a piece of work's files are read.
    Their Office files' text is taken out (extract.py), one headless,
    read-only call reads the folder and answers with a first look, and
    Garrick writes it into the thread note's Resume here block and the hub's
    opening sentence, with the next step as a Needs you question to confirm
    or change. The three are committed by name, in one commit."""
    H, Y = handoff(), your_work()
    zone, note, parts, _ = resume_note(ws, req)
    name = work_name(zone, parts)
    folder, members, pid = work_files_of(ws, zone, parts)
    text = note.read_text(encoding="utf-8")
    if re.search(r"(?m)^%s:" % Y.FIRST_LOOK, text.split("\n---\n", 1)[0]):
        raise Refused("%s already has its first look; Continue goes on from it" % name)
    claude = H.find_claude()
    if claude is None:
        raise Refused(H.NO_CLI)
    extracted = tool_json(ws, "extract.py", *(["--work", pid] if pid and members is not None else [str(folder)]),
                          timeout=EXTRACT_TIMEOUT)
    extracts = ws / extracted["extracts"] if extracted.get("made") or extracted.get("kept") else None
    where = folder.name
    session = work_folder(zone, parts)
    with zone_lock(zone):
        rule = read_only_rule(session, folder)  # in place before Claude reads the folder; committed with the first look
    prompt = Y.first_look_prompt(name, str(folder), str(extracts) if extracts else None, members)

    def unwritten():
        if rule is not None:
            if rule[1] is None:
                rule[0].unlink()
            else:
                rule[0].write_bytes(rule[1])
    try:
        _, said = H.prime(claude, session, prompt, timeout=FIRST_LOOK_TIMEOUT, brief=Y.FIRST_LOOK_BRIEF,
                          name=name, add_dirs=[folder] + ([extracts] if extracts else []),
                          settings=Y.settings_arg(str(folder)))
    except H.HandOffError as e:
        unwritten()
        raise Refused(str(e).replace("so nothing was opened", "so nothing was written"))
    look = Y.parse_first_look(said)
    if look is None:
        unwritten()
        raise Refused("Claude's first look at %s did not come back in a shape Garrick can use, so nothing was written. "
                      "Try Start again" % name)
    hub = zone / parts[0] / (parts[0] + ".md")
    box = note.parent / NEEDS
    q = box / ("%s - next-step.md" % today.strftime("%y%m%d"))
    with zone_lock(zone):
        n_before, h_before = note.read_bytes(), hub.read_bytes()
        written = first_look_note(n_before.decode("utf-8"), look, today, where, name)
        made_box = not box.exists()
        if q.exists():
            raise Refused("%s already has a question from today about its next step" % name)
        note.write_text(written, encoding="utf-8")
        files = [(note, n_before)]
        if hub != note:
            hub.write_text(first_look_hub(h_before.decode("utf-8"), look["what"]), encoding="utf-8")
            files.append((hub, h_before))
        box.mkdir(exist_ok=True)
        q.write_text(first_look_question(name, look, today), encoding="utf-8")
        files.append((q, None))
        if rule is not None:
            files.append(rule)
        try:
            commit_all(zone, files, ("%s: first look, from the files in %s" % (name, where))[:200], wall=wall_refusal(ws))
        except Refused:
            if made_box and box.is_dir() and not any(box.iterdir()):
                box.rmdir()
            raise
    key = "%s/%s" % (zone.name, note.relative_to(zone).as_posix())
    Y.keep_first_look(ws, key, request=look["request"] or "Help me with the next step on %s: %s" % (name, look["next"]),
                      question=q.relative_to(zone).as_posix(), made=today.isoformat(), used=False,
                      extracts=extracted.get("extracts") or "")
    reply = "Garrick has a first look at %s. Check it, and say whether the next step is right" % name
    return {"say": reply, "view": Y.work_id(name, key)}


def stop_using(ws: Path, req: dict, today: dt.date) -> str:
    """Stop using this: Garrick's record of a piece of work put away, under
    the zone's archive/, with the day in its hub, and committed as a move.
    Its folder of files is not touched. Bring it back returns the record."""
    Y = your_work()
    zone, note, parts, _ = resume_note(ws, req)
    name = work_name(zone, parts)
    project = zone / parts[0]
    if name != parts[0]:
        raise Refused("%s is one of several threads; Stop using this puts away a piece of work that is one" % name)
    dest = zone / Y.ARCHIVE / parts[0]
    if dest.exists():
        raise Refused("a piece of work called %s is already put away; bring it back or rename this one first" % parts[0])
    F, hub = work_files_lib(), project / (parts[0] + ".md")
    back, kept = "", F.has_copy(project)
    if hub_value(hub, F.STORAGE) == F.MOVED:
        # Moved files go back into the folder first, as Undo the move puts them (#189); Garrick's copy of them
        # is put away with the record, recoverably.
        w = stored_work(ws, req)
        with files_lock(w):
            n, renamed = put_moved_back(ws, w)
        back = "All %s are back in %s first" % (F.said_files(n), w["given"].name) + (
            ". " + renamed_said(renamed) if renamed else "")
    with zone_lock(zone):
        if uncommitted(zone, project):
            raise Refused("%s has changes not saved yet. Continue it once, or wrap it, then stop using it" % name)
        hub = project / (parts[0] + ".md")
        before = hub.read_bytes()
        hub.write_text(set_front(before.decode("utf-8"), {Y.PUT_AWAY: today.isoformat()}), encoding="utf-8")
        dest.parent.mkdir(exist_ok=True)
        os.rename(str(project), str(dest))
        commit_new(zone, [parts[0], "%s/%s" % (Y.ARCHIVE, parts[0])], ("%s: put away, its folder left as it was" % name)[:200],
                   [], {hub: before}, ((dest, project),), wall=wall_refusal(ws))
    if back:
        return "%s is put away. %s. Garrick's copy of them is put away with it" % (name, back)
    return "%s is put away. Its folder is as it was%s" % (name, ", and Garrick's copy is put away with it" if kept else "")


def bring_back(ws: Path, req: dict) -> str:
    """Bring it back: a piece of work put away returned to where it stood."""
    Y = your_work()
    zone = zone_dir(ws, req.get("zone"))
    name = field(req, "project")
    src, dest = zone / Y.ARCHIVE / name, zone / name
    hub = src / (name + ".md")
    if not hub.is_file() or not Y.front_value(hub, Y.PUT_AWAY):
        raise Refused("%s is not put away" % name)
    if dest.exists():
        raise Refused("there is already a piece of work called %s; rename it before bringing this one back" % name)
    with zone_lock(zone):
        if uncommitted(zone, src):
            raise Refused("%s has changes not saved yet in its put-away place" % name)
        before = hub.read_bytes()
        hub.write_text(set_front(before.decode("utf-8"), {}, drop=(Y.PUT_AWAY,)), encoding="utf-8")
        os.rename(str(src), str(dest))
        commit_new(zone, ["%s/%s" % (Y.ARCHIVE, name), name], ("%s: brought back" % name)[:200],
                   [], {hub: before}, ((dest, src),), wall=wall_refusal(ws))
    return "%s is back, where it stood" % name
# ---- end of your own work ----------------------------------------------------------


# ---- where a work's files live (#189): left in place, a copy kept, or moved in ----
# A piece of work from a folder of the user's has its files left in place
# (#182), and its page offers two more choices: Keep a copy, which Garrick
# refreshes one way from the folder, and Move into Garrick, which copies and
# checks every file before any is removed from the folder. Both keep the files
# in the project's own Files/ folder, with a small history of its own that the
# zone ignores (work_files.py, beside this file). The hub says which, in
# `storage:`, committed by name with the project's .gitignore and the Claude
# settings of the folder its sessions start in: Edit denied in the user's
# folder always, and in Garrick's copy too until the files are moved, when
# Claude may edit them like any file of the work. A copy or a move holds a
# lock of its own on the work, and the zone's only while its record commits;
# it says how far it has got in System/generated/work-files/, where Stop
# finds it, and Stop ends it, leaving nothing behind, until files start
# leaving the folder.
_WF = None
FILES_DO = ("copy", "refresh", "media-in", "media-out", "move", "undo", "keep-copy", "delete-copy")
WORK_FILE_DO = ("open", "finder", "version-open", "version-save")
OPEN_TOOL = "/usr/bin/open"
PATH_MAX = 1024


def work_files_lib():
    """work_files.py, beside this file: where a piece of work's files live."""
    global _WF
    if _WF is None:
        spec = importlib.util.spec_from_file_location("garrick_work_files", str(HERE / "work_files.py"))
        _WF = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_WF)
    return _WF


def stored_work(ws: Path, req: dict) -> dict:
    """A piece of work from a folder of the user's, as the storage verbs need
    it: its zone, note, name and key, its project and hub, the user's folder
    (`folder`, None when it is not there now, and `given`, where it was),
    the files of it that belong to the work (`members`, None for all), where
    its files live now (`mode`), and Garrick's own folder for them (`files`)."""
    Y, F = your_work(), work_files_lib()
    zone, note, parts, _ = resume_note(ws, req)
    name = work_name(zone, parts)
    project = zone / parts[0]
    hub = project / (parts[0] + ".md")
    given = hub_value(hub, "folder") if hub.is_file() else ""
    if not given or not hub_value(hub, Y.DISCOVERED):
        raise Refused("%s keeps its files in Garrick, not in a folder of yours" % name)
    if name != parts[0]:
        raise Refused("%s is one of several threads; where files live is chosen for a piece of work that is one" % name)
    raw = Path(given).expanduser()
    raw = raw if raw.is_absolute() else ws / raw
    members = None
    pid = hub_value(hub, Y.DISCOVERED)
    for entry in Y.discovery(ws)["folders"].values():
        a = (entry.get("answers") or {}).get(pid)
        if isinstance(a, dict) and a.get("kind") == "names":
            members = [m for m in a.get("members") or [] if isinstance(m, str)]
    fm = {k: hub_value(hub, k) for k in (F.STORAGE, F.MEDIA_KEY, F.MOVED_ON)}
    return {"zone": zone, "note": note, "parts": parts, "name": name, "project": project, "hub": hub,
            "key": "%s/%s" % (zone.name, note.relative_to(zone).as_posix()), "given": raw,
            "folder": raw if raw.is_dir() else None, "members": members, "mode": F.mode(fm), "media": F.media_in(fm),
            "files": F.files_dir(project), "session": work_folder(zone, parts)}


def files_lock(w: dict):
    """One copy, move, undo or refresh at a time on a piece of work."""
    return held("work-files-%s.lock" % work_files_lib().key_hash(w["key"]), wait=2,
                busy="Garrick is already busy with the files of %s" % w["name"])


def storage_rules(w: dict, moved: bool, copy: Optional[bool] = None):
    """The Claude settings of the folder the work's sessions start in, for
    where its files live: Edit denied in the user's folder, always, and in
    Garrick's copy of them (Files/) while there is one and the files are not
    moved in; once they are, the rule on the copy comes off, so Claude may
    edit them. `copy` says whether there is a copy, when it is about to be
    made or deleted. Everything else in the file stays. (the file, the bytes
    it held before or None) when it changed; None when it already said so."""
    Y = your_work()
    path = w["session"].joinpath(*Y.CLAUDE_SETTINGS)
    try:
        before = path.read_bytes()
    except FileNotFoundError:
        before = None
    try:
        data = json.loads(before.decode("utf-8")) if before and before.strip() else {}
        perms = data.setdefault("permissions", {}) if isinstance(data, dict) else None
        deny = perms.setdefault("deny", []) if isinstance(perms, dict) else None
    except ValueError:
        deny = None
    if not isinstance(deny, list):
        raise Refused("this work's Claude settings are not JSON Garrick can add to, so nothing was changed")
    copy_rule = copy_rule_of(w)
    want_copy = not moved and ((w["files"] / ".git").is_dir() if copy is None else copy)
    kept = [r for r in deny if r != copy_rule or want_copy]
    kept += [r for r in Y.read_only_rules(str(w["given"])) if r not in kept]
    if want_copy and copy_rule not in kept:
        kept.append(copy_rule)
    if kept == deny:
        return None
    perms["deny"] = kept
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path, before


def copy_rule_of(w: dict) -> str:
    return "Edit(/%s/**)" % os.path.realpath(str(w["files"])).rstrip("/")


def deny_arg(w: dict, moved: bool) -> str:
    """The same rules as the JSON `--settings` takes, for a headless call."""
    rules = your_work().read_only_rules(str(w["given"]))
    if not moved and (w["files"] / ".git").is_dir():
        rules.append(copy_rule_of(w))
    return json.dumps({"permissions": {"deny": rules}}, ensure_ascii=False)


def commit_storage(ws: Path, w: dict, values: dict, drop: tuple, moved: bool, message: str,
                   copy: Optional[bool] = None) -> None:
    """Garrick's record of where the work's files live, committed by name in
    one commit: the hub's keys, the project's .gitignore, and the Claude
    settings of the folder its sessions start in (storage_rules()). Only what
    changed; all of it put back if the commit is refused."""
    F = work_files_lib()
    with zone_lock(w["zone"]):
        hub_before = w["hub"].read_bytes()
        hub_text = set_front(hub_before.decode("utf-8"), values, drop=drop)
        files = []
        if hub_text.encode("utf-8") != hub_before:
            w["hub"].write_text(hub_text, encoding="utf-8")
            files.append((w["hub"], hub_before))
        ignore = w["project"] / ".gitignore"
        before = ignore.read_bytes() if ignore.is_file() else None
        text = F.ignore_text(before.decode("utf-8", "replace") if before is not None else None)
        if text is not None:
            ignore.write_text(text, encoding="utf-8")
            files.append((ignore, before))
        try:
            rule = storage_rules(w, moved, copy)
        except Refused:
            for f, b in files:
                f.unlink() if b is None else f.write_bytes(b)
            raise
        if rule is not None:
            files.append(rule)
        if files:
            commit_all(w["zone"], files, ("%s: %s" % (w["name"], message))[:200], wall=wall_refusal(ws))


def let_go(w: dict, new: bool) -> None:
    """What a copy or a move made, taken back: a new copy deleted, one that
    was there before put back to its last version."""
    F = work_files_lib()
    if new:
        shutil.rmtree(str(w["files"]), ignore_errors=True)
    else:
        F.history_back(w["files"])


def storage(ws: Path, req: dict, today: dt.date, now: Optional[dt.datetime] = None) -> dict:
    """Where these files live, from the work's page: {"zone", "file", "do"}.

        copy         Keep a copy: made, or an old one picked up, and refreshed
        refresh      Refresh now
        media-in     recordings and video brought into the copy, and out again
        media-out
        move         Move into Garrick
        undo         Undo the move: every file back, never over one
        keep-copy    back to left in place from a copy, keeping it
        delete-copy  back to left in place, the copy deleted; or an old copy deleted
    """
    F = work_files_lib()
    do = req.get("do")
    if do not in FILES_DO:
        raise Refused("not something Garrick does with a work's files: %r" % (do,))
    w = stored_work(ws, req)
    now = now or dt.datetime.now()
    with files_lock(w):
        if do == "copy":
            return keep_a_copy(ws, w, now)
        if do == "refresh":
            return refresh_now(ws, w, now)
        if do in ("media-in", "media-out"):
            return switch_media(ws, w, do == "media-in", now)
        if do == "move":
            return move_in(ws, w, today)
        if do == "undo":
            return undo_move(ws, w)
        if do == "keep-copy":
            if w["mode"] != F.COPY:
                raise Refused("%s has no copy being refreshed" % w["name"])
            commit_storage(ws, w, {}, (F.STORAGE, F.MEDIA_KEY), False, "files left in place, Garrick's copy kept")
            return {"say": "Garrick only reads your folder again. Its copy is kept, and no longer refreshed",
                    "view": your_work().work_id(w["name"], w["key"])}
        return delete_copy(ws, w)


def view_of(w: dict) -> str:
    return your_work().work_id(w["name"], w["key"])


def keep_a_copy(ws: Path, w: dict, now: dt.datetime) -> dict:
    F = work_files_lib()
    if w["mode"] == F.MOVED:
        raise Refused("The files are in Garrick now, so there is no folder to copy them from. Undo the move first")
    if w["mode"] == F.COPY:
        raise Refused("Garrick keeps a copy of %s already; Refresh now brings it up to your folder" % w["name"])
    if w["folder"] is None:
        raise Refused("the folder %s is not there now, so there is nothing to copy" % w["given"].name)
    new = not F.has_copy(w["project"])
    job = F.Job(ws, w["key"], "copy")
    try:
        done = F.refresh(w["folder"], w["members"], w["files"], w["media"], job,
                         "The first copy" if new else "Refreshed when the copy was picked up again")
        commit_storage(ws, w, {F.STORAGE: F.COPY}, (F.MOVED_ON,), False, "a copy of its files kept in Garrick")
    except F.Stopped:
        let_go(w, new)
        return {"say": "Stopped. Garrick kept nothing, and your folder is as it was", "view": view_of(w), "stopped": True}
    except Refused:
        let_go(w, new)
        raise
    except (F.Refused, OSError) as e:
        let_go(w, new)
        raise Refused("%s, so Garrick kept nothing. Your folder is as it was" % (
            e.strerror if isinstance(e, OSError) and e.strerror else e))
    finally:
        job.end()
    # The first copy changed nothing: it copied the files. A copy picked up again was refreshed, and says what changed.
    F.keep_state(ws, w["key"], refreshed=now.isoformat(timespec="seconds"), via="copy" if new else "pickup", first=new,
                 changed=F.copied_said(done) if new else F.changed_said(done))
    return {"say": ("Garrick keeps a copy now. Your folder is as it was" if new else
                    "Garrick's copy is refreshed and kept again. Your folder is as it was"), "view": view_of(w)}


def refresh_copy(ws: Path, w: dict, now: dt.datetime, via: str) -> dict:
    """The copy brought up to the folder, as Refresh now and Continue do it."""
    F = work_files_lib()
    if w["folder"] is None:
        raise Refused("the folder %s is not there now, so Garrick's copy was not refreshed" % w["given"].name)
    job = F.Job(ws, w["key"], "refresh")
    try:
        done = F.refresh(w["folder"], w["members"], w["files"], w["media"], job)
    except F.Stopped:
        F.history_back(w["files"])
        raise Refused("Stopped. Garrick's copy is as it was")
    except (F.Refused, OSError) as e:
        F.history_back(w["files"])
        raise Refused("Garrick's copy was not refreshed: %s" % (e.strerror if isinstance(e, OSError) and e.strerror else e))
    finally:
        job.end()
    said = F.changed_said(done)
    F.keep_state(ws, w["key"], refreshed=now.isoformat(timespec="seconds"), via=via, changed=said, first=False)
    return {"done": done, "said": said}


def refresh_now(ws: Path, w: dict, now: dt.datetime) -> dict:
    F = work_files_lib()
    if w["mode"] != F.COPY:
        raise Refused("Garrick keeps no copy of %s to refresh" % w["name"])
    said = refresh_copy(ws, w, now, "refresh")["said"]
    return {"say": "Refreshed Garrick's copy. %s Your folder is as it was" % said, "view": view_of(w)}


def switch_media(ws: Path, w: dict, on: bool, now: dt.datetime) -> dict:
    """Recordings and video brought into the copy, or left out from now on;
    the versions already kept stay. The switch is the hub's, committed first,
    then the copy follows it."""
    F = work_files_lib()
    if w["mode"] != F.COPY:
        raise Refused("Garrick keeps no copy of %s" % w["name"])
    if on == w["media"]:
        raise Refused("Recordings and video are %s already" % ("in the copy" if on else "left out"))
    commit_storage(ws, w, {F.MEDIA_KEY: F.MEDIA_IN} if on else {}, () if on else (F.MEDIA_KEY,), False,
                   "recordings and video %s its copy" % ("brought into" if on else "left out of"))
    w = dict(w, media=on)
    try:
        refresh_copy(ws, w, now, "media")
    except Refused as e:
        return {"say": "The switch is %s. %s; the next refresh tries again" % ("on" if on else "off", str(e).rstrip(".")),
                "view": view_of(w)}
    if not on:
        return {"say": "Recordings and video are left out from now on. The versions already kept stay", "view": view_of(w)}
    got = F.sizes({r: s for r, s in F.listing(w["files"]).items() if F.is_media(r)})
    return {"say": "Recordings and video are in Garrick's copy now: %s, %s" % (F.said_files(got["files"]),
                                                                          F.said_size(got["bytes"])), "view": view_of(w)}


def move_in(ws: Path, w: dict, today: dt.date) -> dict:
    """Move into Garrick: every file copied into the work's Files/ folder and
    checked against its original, a version kept, the record committed, and
    only then each file removed from the folder, if it is still as it was
    checked. The folder itself stays, empty, so Undo has somewhere to go, and
    nothing is written into it."""
    F = work_files_lib()
    if w["mode"] == F.MOVED:
        raise Refused("The files of %s are in Garrick already" % w["name"])
    if w["folder"] is None:
        raise Refused("the folder %s is not there now, so there is nothing to move" % w["given"].name)
    new = not F.has_copy(w["project"])
    job = F.Job(ws, w["key"], "move")
    try:
        try:
            files = F.move_in(w["folder"], w["members"], w["files"], job)
        except F.Stopped:
            let_go(w, new)
            return {"say": "Stopped. Every file is still in your folder, and Garrick kept nothing of the move",
                    "view": view_of(w), "stopped": True}
        except (F.Refused, OSError) as e:
            let_go(w, new)
            raise Refused("%s. Every file is still in your folder" % (
                e.strerror if isinstance(e, OSError) and e.strerror else str(e)).rstrip("."))
        try:
            commit_storage(ws, w, {F.STORAGE: F.MOVED, F.MOVED_ON: today.isoformat()}, (F.MEDIA_KEY,), True,
                           "its files moved into Garrick")
        except Refused:
            if new:
                shutil.rmtree(str(w["files"]), ignore_errors=True)
            else:
                F.history_drop_last(w["files"])
            raise
        stayed = F.remove_moved(w["folder"], files, job)
    finally:
        job.end()
    F.keep_state(ws, w["key"], moved=today.isoformat(), stayed=stayed, renamed=[])
    said = "Moved. All %s are in Garrick" % F.said_files(len(files)) if not stayed else \
        "Moved, but %s stayed in the folder, because %s changed or could not be removed there: %s. Garrick has %s as " \
        "%s were checked" % (F.said_files(len(stayed)), "it" if len(stayed) == 1 else "they",
                             ", ".join(os.path.basename(r) for r in stayed[:3]), "it" if len(stayed) == 1 else "them",
                             "it was" if len(stayed) == 1 else "they were")
    return {"say": said, "view": view_of(w)}


def put_moved_back(ws: Path, w: dict) -> tuple:
    """Every file of a moved work back in its folder, checked there, and the
    record back to left in place: (the files put back, the ones renamed)."""
    F = work_files_lib()
    job = F.Job(ws, w["key"], "undo")
    try:
        n = len(F.listing(w["files"]))
        try:
            renamed = F.put_back(w["files"], w["given"], job)
        except (F.Refused, OSError) as e:
            raise Refused("%s. The files are still in Garrick; Undo the move again to put the rest back" % (
                e.strerror if isinstance(e, OSError) and e.strerror else str(e)).rstrip("."))
        job.phase("saving")
        commit_storage(ws, w, {}, (F.STORAGE, F.MOVED_ON, F.MEDIA_KEY), False, "its files put back in the folder")
    finally:
        job.end()
    F.keep_state(ws, w["key"], renamed=[b for _, b in renamed], moved="", stayed=[])
    return n, renamed


def renamed_said(renamed: list) -> str:
    """Which files Undo put back beside one of the same name, in a sentence; "" for none."""
    if not renamed:
        return ""
    n = len(renamed)
    return ("%s of the same name %s in the folder already, so Garrick's went back beside %s: %s" % (
        "A file" if n == 1 else "%d files" % n, "was" if n == 1 else "were", "it" if n == 1 else "them",
        ", ".join(os.path.basename(b) for _, b in renamed[:3]) + (" and %d more" % (n - 3) if n > 3 else "")))


def undo_said(w: dict, n: int, renamed: list) -> str:
    said = "All %s are back in %s. Garrick only reads them again, and keeps its copy, with its versions, until you " \
           "delete it" % (work_files_lib().said_files(n), w["given"].name)
    return said + (". " + renamed_said(renamed) if renamed else "")


def undo_move(ws: Path, w: dict) -> dict:
    F = work_files_lib()
    if w["mode"] != F.MOVED:
        raise Refused("The files of %s are not in Garrick, so there is nothing to undo" % w["name"])
    n, renamed = put_moved_back(ws, w)
    return {"say": undo_said(w, n, renamed), "view": view_of(w)}


def delete_copy(ws: Path, w: dict) -> dict:
    """The copy deleted, with every version: from a copy kept, back to left in
    place; from left in place, the old copy. Never once the files are moved.
    The record is committed first, the rule on the copy with it; then the
    copy goes."""
    F = work_files_lib()
    if w["mode"] == F.MOVED:
        raise Refused("The files of %s are in Garrick; Undo the move puts them back first" % w["name"])
    if not F.has_copy(w["project"]):
        raise Refused("Garrick keeps no copy of %s" % w["name"])
    versions = F.history_count(w["files"])
    commit_storage(ws, w, {}, (F.STORAGE, F.MEDIA_KEY), False, "Garrick's copy of its files deleted", copy=False)
    shutil.rmtree(str(w["files"]))
    F.keep_state(ws, w["key"], refreshed="", changed="")
    return {"say": "Garrick's copy is deleted, with its %s. Your folder is as it was" % (
        "version" if versions == 1 else "%d versions" % versions), "view": view_of(w)}


def files_stop(ws: Path, req: dict) -> str:
    """Stop, on the page while files are copied and checked: the job ends and
    leaves nothing behind. Refused once files start leaving the folder."""
    F = work_files_lib()
    w = stored_work(ws, req)
    said = F.ask_stop(ws, w["key"])
    if said == "stopping":
        return "Stopping: Garrick takes back what it copied"
    if said == "late":
        raise Refused("Files are already leaving the folder, so the move goes on to the end. Undo the move puts them back")
    raise Refused("Nothing is being copied or moved for %s now" % w["name"])


def files_progress(ws: Path, req: dict) -> dict:
    """How far a copy, a move or an undo has got, for the page to show. Only reads."""
    w = stored_work(ws, req)
    p = work_files_lib().progress(ws, w["key"])
    return {"say": "", "progress": {k: p.get(k) for k in ("kind", "phase", "done", "of", "bytes", "bytes_of")} if p else None}


def opener() -> str:
    """macOS's `open`, which opens a file in the app the Mac uses for it, and a
    folder in Finder; GARRICK_OPEN for a test."""
    tool = os.environ.get("GARRICK_OPEN") or OPEN_TOOL
    if not os.path.isfile(tool):
        raise Refused("Garrick opens files only on a Mac")
    return tool


def open_path(path: Path) -> None:
    try:
        r = subprocess.run([opener(), str(path)], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Refused("%s did not open: %s" % (path.name, e))
    if r.returncode != 0:
        said = (r.stderr or r.stdout).strip().splitlines()
        raise Refused("%s did not open%s" % (path.name, ": " + said[-1] if said else ""))


def in_files(w: dict, rel) -> Path:
    """A file of Garrick's copy or of the moved files, by its path from Files/, never outside it."""
    if not isinstance(rel, str) or not rel or len(rel) > PATH_MAX or "\n" in rel:
        raise Refused("no file named")
    base = w["files"].resolve()
    p = (base / rel).resolve()
    if base not in p.parents or ".git" in p.relative_to(base).parts:
        raise Refused("that file is not one of this work's")
    return p


def work_file(ws: Path, req: dict, today: dt.date) -> str:
    """A work's own file from its page: {"zone", "file", "do", "path"?,
    "version"?, "to"?}. Moved files open in their own app, and Show in Finder
    opens the work's Files/ folder, never one above it. An earlier version, of
    a copy or of moved files, opens to read, from a file of its own, or is
    saved as a separate file where the user chooses (`to`, from the app's
    Save panel), or in Downloads. A version is never put back over a file."""
    F = work_files_lib()
    do = req.get("do")
    if do not in WORK_FILE_DO:
        raise Refused("not something Garrick does with a work's file: %r" % (do,))
    w = stored_work(ws, req)
    if do == "finder":
        if w["mode"] != F.MOVED or not w["files"].is_dir():
            raise Refused("The files of %s are not in Garrick" % w["name"])
        open_path(w["files"])
        return "Showed the files of %s in Finder" % w["name"]
    if do == "open":
        if w["mode"] != F.MOVED:
            raise Refused("The files of %s are in your folder; open them there" % w["name"])
        p = in_files(w, req.get("path"))
        if not p.is_file():
            raise Refused("%s is not in Garrick now; the page rebuilds" % os.path.basename(str(req.get("path"))))
        open_path(p)
        return "Opened %s" % p.name
    rel = req.get("path")
    in_files(w, rel)                                # a path inside the copy, never outside it
    version = req.get("version")
    if not isinstance(version, str):
        raise Refused("no version named")
    if not (w["files"] / ".git").is_dir():
        raise Refused("Garrick keeps no copy of %s" % w["name"])
    data = F.history_blob(w["files"], version, rel)
    stamp = next((t for c, t in F.history_of(w["files"]).get(rel, []) if c == version), None)
    name = F.version_name(rel, dt.datetime.fromtimestamp(stamp) if stamp else dt.datetime.now(), today)
    if do == "version-open":
        box = ws.joinpath(*F.VERSIONS)
        for old in box.glob("*/") if box.is_dir() else []:
            if time.time() - old.stat().st_mtime > 86400:
                shutil.rmtree(str(old), ignore_errors=True)
        dest = box / version[:12] / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.chmod(0o644)
        dest.write_bytes(data)
        dest.chmod(0o444)                           # to read: a change belongs in the file itself
        open_path(dest)
        return "Opened %s, to read. Nothing was changed" % name
    to = req.get("to")
    if to is None:
        downloads = Path(os.path.expanduser("~")) / "Downloads"
        if not downloads.is_dir():
            raise Refused("there is no Downloads folder to save it in")
        dest = downloads / name
        n = 2
        while dest.exists():
            stem, ext = os.path.splitext(name)
            dest = downloads / ("%s %d%s" % (stem, n, ext))
            n += 1
    else:
        if not isinstance(to, str) or not os.path.isabs(to) or "\n" in to or len(to) > PATH_MAX:
            raise Refused("not a place to save it")
        dest = Path(to)
        real = os.path.realpath(str(dest.parent))
        for keep in [w["given"]] + ([] if w["mode"] == F.MOVED else [w["files"]]):
            k = os.path.realpath(str(keep))
            if real == k or real.startswith(k + os.sep):
                raise Refused("Save it somewhere outside %s: Garrick never writes there" % (
                    "your folder %s" % w["given"].name if keep == w["given"] else "Garrick's copy"))
        if not dest.parent.is_dir():
            raise Refused("the folder to save it in is not there")
    dest.write_bytes(data)
    return "Saved %s in %s. Nothing else was changed" % (dest.name, dest.parent.name)
# ---- end of where a work's files live -----------------------------------------------


# ---- a note previewed from Explore (#206) ---------------------------------------
# A node's card on the graph offers Preview: the note read here, drawn by
# guide.py's renderer, the one the Guide and the release notes are drawn with,
# and shown over the graph; and, from the preview, Open in default app, the
# note opened by `open` in whatever app the Mac uses for a .md file, whatever
# Settings › Opening a thread says. Both only read. A note is named by its path
# from the workspace's folder, and only a Markdown file inside Zones/ or Wikis/,
# once every link on the way is followed, is either read or opened. A note
# larger than NOTE_MAX is not drawn, and opens in its own app instead.
_GUIDE = None
NOTE_PLACES = ("Zones", "Wikis")
NOTE_MAX = 400 * 1000
NOTE_PROPS = 16                 # properties drawn above a note, at most
NOTE_FM = re.compile(r"\A---[ \t]*\r?\n(.*?)^(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.S | re.M)
NOTE_KEY = re.compile(r"^([A-Za-z_][\w-]*)[ \t]*:[ \t]*(.*?)\s*$")
NOTE_ITEM = re.compile(r"^[ \t]+-[ \t]+(.*?)\s*$")


class Missing(Refused):
    """A note that is not there: the reply says so in `missing`, so the page
    offers no Open in default app for it."""
    reply = {"missing": True}


def guide_lib():
    """guide.py, beside this file: the one Markdown renderer."""
    global _GUIDE
    if _GUIDE is None:
        spec = importlib.util.spec_from_file_location("garrick_guide", str(HERE / "guide.py"))
        _GUIDE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_GUIDE)
    return _GUIDE


def gone(name: str) -> Missing:
    return Missing("%s is not there any more: it was moved, renamed or deleted after the page was built" % name)


def note_file(ws: Path, rel) -> Path:
    """A note by its path from the workspace, as the graph names it: a .md
    file inside Zones/ or Wikis/ once every link is followed, so a note that
    links to one elsewhere in them is read, and `..`, a hidden folder or a
    link that leads out of them is refused. One that is not there is Missing."""
    if not isinstance(rel, str) or not rel or len(rel) > PATH_MAX or any(c in rel for c in "\n\r\x00\\"):
        raise Refused("no note named")
    parts = rel.split("/")
    if parts[0] not in NOTE_PLACES or any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        raise Refused("Garrick previews only a note in a zone or a wiki")
    name = parts[-1][:-3] if parts[-1].endswith(".md") else parts[-1]
    if not rel.endswith(".md"):
        raise Refused("%s is not a Markdown note, so Garrick does not preview it" % name)
    p = (ws / rel).resolve()
    if p.suffix != ".md" or not any(root in p.parents for root in ((ws / place).resolve() for place in NOTE_PLACES)):
        raise Refused("%s leads outside the zones and wikis, so Garrick does not preview it" % name)
    if not p.is_file():
        raise gone(name)
    return p


def note_props(block: str) -> list:
    """A note's frontmatter as (key, value) to show: a key's value, or its
    list on the lines under it or in brackets, joined by commas. A nested map
    is left out; it is not what a reader looks for above a note."""
    props: list = []
    for line in block.splitlines():
        m, item = NOTE_KEY.match(line), NOTE_ITEM.match(line)
        if m:
            v = m.group(2)
            props.append([m.group(1), [x.strip() for x in v[1:-1].split(",")] if v[:1] == "[" and v[-1:] == "]" else [v], False])
        elif item and props:
            props[-1][1].append(item.group(1))
        elif props and line.strip() and line[:1] in " \t":
            props[-1][2] = True                     # a key under a key: a nested map
    out = []
    for key, values in [(k, v) for k, v, nested in props if not nested][:NOTE_PROPS]:
        values = [v[1:-1] if len(v) > 1 and v[0] == v[-1] and v[0] in "'\"" else v for v in values]
        if any(values):
            out.append((key, ", ".join(v for v in values if v)))
    return out


def note_read(ws: Path, req: dict) -> dict:
    """Preview (#206): {"path"}, the note drawn as HTML, its frontmatter as a
    short list of properties above it, with its title. Nothing is written."""
    p = note_file(ws, req.get("path"))
    try:
        size = p.stat().st_size
        with p.open("rb") as f:
            data = f.read(NOTE_MAX + 1) if size <= NOTE_MAX else b""
    except FileNotFoundError:
        raise gone(p.stem)
    except OSError as e:
        raise Refused("%s could not be read: %s" % (p.stem, (e.strerror or str(e)).lower()))
    if size > NOTE_MAX or len(data) > NOTE_MAX:
        raise Refused("%s is too large to preview here (%s); open it in its own app"
                      % (p.stem, work_files_lib().said_size(max(size, len(data)))))
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Refused("%s could not be read: it is not text Garrick can read (UTF-8)" % p.stem)
    G, m = guide_lib(), NOTE_FM.match(text)
    props = note_props(m.group(1)) if m else []
    title = next((v for k, v in props if k == "title"), "") or p.stem
    shown = "".join("<div><dt>%s</dt><dd>%s</dd></div>" % (html.escape(k), G.inline(v)) for k, v in props if k != "title")
    body = G.blocks(text[m.end():] if m else text)
    return {"say": "Read %s" % p.stem, "title": title,
            "html": ('<dl class="nv-props">%s</dl>' % shown if shown else "") + (body or '<p class="nv-none">This note is empty.</p>')}


ALIAS_MAGIC = b"book\x00\x00\x00\x00mark"      # how a Finder alias file begins, whatever it is named


def note_open(ws: Path, req: dict) -> str:
    """Open in default app (#206): {"path"}, the note opened by `open`, in the
    app the Mac uses for a .md file, never one of Garrick's launchers. Only a
    note reached with no symlink anywhere below the workspace's folder, and
    never a Finder alias named as a note, which `open` would follow, as
    Garrick.app's workspaceFile() and runsSomething() refuse them (#318)."""
    p = note_file(ws, req.get("path"))
    rel = str(req.get("path"))
    name = p.stem
    at = ws
    for part in rel.split("/"):
        at = at / part
        if at.is_symlink():
            raise Refused("%s is reached through a link, so Garrick does not open it" % name)
    try:
        with p.open("rb") as f:
            alias = f.read(len(ALIAS_MAGIC)) == ALIAS_MAGIC
    except OSError as e:
        raise Refused("%s could not be read: %s" % (name, (e.strerror or str(e)).lower()))
    if alias:
        raise Refused("%s is an alias, not a note, so Garrick does not open it" % name)
    open_path(p)
    return "Opened %s" % p.stem
# ---- end of a note previewed ----------------------------------------------------


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
    """Carry out one request, or raise Refused. What to say, or a reply whose
    "say" comes with what the caller reads back."""
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
    if req["verb"] == "memory-preview":
        return memory_preview(ws, req)
    if req["verb"] == "party-flag":
        return party_flag(ws, req)
    if req["verb"] == "release-check":
        return release_check(ws)
    if req["verb"] == "release-update":
        return release_update(ws)
    if req["verb"] == "note-read":
        return note_read(ws, req)
    if req["verb"] == "note-open":
        return note_open(ws, req)
    if req["verb"] in ("park", "wake"):
        return park(ws, req, today or dt.date.today())
    if req["verb"] == "todo-add":
        return todo_add(ws, req)
    if req["verb"] == "answer":
        return answer_question(ws, req, today or dt.date.today())
    if req["verb"] == "later":
        return put_off(ws, req, today or dt.date.today())
    if req["verb"].startswith("question-"):
        return wiki_question_act(ws, req, today or dt.date.today())
    if req["verb"].startswith("nurture-"):
        return nurture_act(ws, req, today or dt.date.today())
    if req["verb"] == "continue":
        return continue_work(ws, req, now)
    if req["verb"] == "ask-desktop":
        return ask_desktop(ws, req)
    if req["verb"] == "example":
        return example(ws, req)
    if req["verb"] == "fix":
        return fix_finding(ws, req)
    if req["verb"] == "discover":
        return discover_folder(ws, req)
    if req["verb"] == "suggestion":
        return answer_suggestion(ws, req)
    if req["verb"] == "start":
        return start_work(ws, req, today or dt.date.today())
    if req["verb"] == "stop-using":
        return stop_using(ws, req, today or dt.date.today())
    if req["verb"] == "bring-back":
        return bring_back(ws, req)
    if req["verb"] == "files":
        return storage(ws, req, today or dt.date.today(), now)
    if req["verb"] == "files-stop":
        return files_stop(ws, req)
    if req["verb"] == "files-progress":
        return files_progress(ws, req)
    if req["verb"] == "work-file":
        return work_file(ws, req, today or dt.date.today())
    if req["verb"] in ("new-project", "new-thread", "check-name", "rename", "move", "delete", "undo"):
        return manage(ws, req)
    return todo(ws, req)


# The verbs whose reply asks for the page to be built (#344): what a page, the
# ask box or a session changes that the page shows. Every other verb leaves the
# rebuild to the app, as it did. A delete asks for it only once confirmed.
PAGE_BUILDS = ("todo-done", "todo-undo", "todo-date", "todo-add", "park", "wake", "new-project", "new-thread",
               "rename", "move", "delete", "undo")
PAGE_SETTLE = 10        # seconds the build waits for another request first, so a burst makes one page
CALLERS = ("page", "ask", "session")


def builds_page(req) -> bool:
    if not isinstance(req, dict) or req.get("verb") not in PAGE_BUILDS:
        return False
    return not (req["verb"] == "delete" and not req.get("confirm"))       # the first form only says what would go


def ask_for_page(ws: Path) -> bool:
    """Ask for one build of the status page, in the background, and return at
    once: with `--settle`, so a burst of actions makes one page, and with
    `--same-flags`, so it keeps the flags the app or the plugin last built it
    with. The one place any caller's action asks for it (#344). False where
    the status extra is not installed, or garrick_lib is too old to say how."""
    try:
        found = prefs().lib(ws)
        command = getattr(found, "status_command", None)
        start = getattr(found, "detach", None)
        cmd = command(ws, settle=PAGE_SETTLE) if callable(command) and callable(start) else None
        return bool(cmd) and bool(start(cmd))
    except Exception:
        return False


def perform(ws: Path, req, ops=None, via: str = "page"):
    """One request, as a click sends it and as the ask box does: through the
    durable record where operations.py keeps one for its verb, so that a
    request repeating one the record holds is joined, answered or asked
    about (operations.start()) rather than done again. Never raises.
    `via` names the caller, one of CALLERS: it goes into the record.

    An action that changed something the page shows ends with the page
    request (ask_for_page), once, after the commit, and
    the reply says `"built": true`. Only that: a refusal, a repeat joined or
    answered, a read, a verb this does not build for, and a page that could
    not be asked for all leave the key out, and the caller rebuilds as it
    always did. A refusal such as "it rebuilds now, try again" depends on it.

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
                    run, joined = start_record(ops, req, via)
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
            out = dict({"ok": False, "say": str(e)}, **getattr(e, "reply", {}))     # a note not there says so (#206)
            outcome, why = "refused", str(e)
        except Exception as e:          # a fault still answers in JSON, and is logged
            out = {"ok": False, "say": "that did not work: %s: %s" % (type(e).__name__, e)}
            outcome, why = "crashed", "%s: %s" % (type(e).__name__, e)
        if run is not None and outcome is not None:
            out = run.finish(outcome, req, why=why, said=out["say"] if outcome == "saved" else "")
        if builds_page(req):
            if outcome == "saved" and ask_for_page(ws):
                out["built"] = True         # asked for, once: the app does not rebuild as well
    finally:
        CURRENT = None
        if run is not None:
            run.close(req)              # a terminal record, whatever stopped us, then the lock
    return out, logged, why


def start_record(ops, req: dict, via: str):
    """operations.start(), naming the caller where this operations.py takes
    one; an older copy is called as it always was."""
    try:
        takes = "via" in inspect.signature(ops.start).parameters
    except (TypeError, ValueError):
        takes = False
    return ops.start(jobs_dir(), req, via=via) if takes else ops.start(jobs_dir(), req)


# The command-line form for a session (#344): a verb and the fields it takes as
# options, no JSON. Each builds the request a button sends, so everything after
# it is the same code: the stale check, the commit and its wall check,
# the record, the page request. The line a Todo verb names is given in words
# (`--line`), and resolved here to the key the page would send.
CLI_FIELDS = {
    "park": ("zone", "project", "thread"), "wake": ("zone", "project", "thread"),
    "new-project": ("zone", "name", "party", "thread", "spoken", "thread_spoken"),
    "new-thread": ("zone", "project", "name", "spoken"),
    "rename": ("zone", "project", "thread", "to"), "move": ("zone", "project", "thread", "to"),
    "delete": ("zone", "project", "thread", "confirm"),
    "undo": ("zone", "commit"),
    "todo-add": ("zone", "text", "target", "date"),
    "question-answer": ("wiki", "file", "words"), "question-later": ("wiki", "file", "until"),
    "question-close": ("wiki", "file"), "question-decide": ("wiki", "file", "words"),
    "question-open-sections": ("wiki", "confirm", "pages"),
    "question-work": ("wiki", "file"), "question-done": ("wiki", "file"),
    "todo-done": ("zone", "line", "file"), "todo-undo": ("zone", "line", "file"),
    "todo-date": ("zone", "line", "file", "date"),
}


def session_line(ws: Path, req: dict) -> dict:
    """A Todo verb given its line in words: the request with the `key` of the one
    line it says, and the note's `file`. Refused when no line, or more than one,
    says it, so that nothing is ticked that was not meant."""
    tl = todo_lines()
    zone = zone_dir(ws, req.get("zone"))
    said = req.pop("line", None)
    if not isinstance(said, str) or not said.strip() or len(said) > 1000:
        raise Refused("no line given: say the line, or enough of it to be the only one")
    want = " ".join(said.split()).casefold().rstrip(".")
    reopen = req["verb"] == "todo-undo"
    pool = tl.done_on(str(zone), dt.date.today()) if reopen else tl.tasks(str(zone))
    only = req.get("file")
    pool = [t for t in pool if only in (None, t["file"])]

    def plain(t):
        return " ".join(t["text"].split()).casefold().rstrip(".")
    found = [t for t in pool if plain(t) == want] or [t for t in pool if want in plain(t)]
    if not found:
        raise Refused("no %s line says that in %s" % ("ticked" if reopen else "open", zone.name))
    if len(found) > 1:
        raise Refused("%d lines say that in %s: say more of the line" % (len(found), zone.name))
    return dict(req, key=found[0]["key"], file=found[0]["file"])


def session_request(ws: Path, args) -> dict:
    """The request a verb typed in a terminal means: only the options that verb
    takes, each given or left out. A zone is always named; nothing is guessed."""
    given = {k: getattr(args, k.replace("-", "_")) for k in CLI_FIELDS[args.verb]}
    if args.verb.startswith("question-"):
        if not given.get("wiki"):
            raise Refused("no wiki given: say which, with --wiki")
    elif not given.get("zone"):
        raise Refused("no zone given: say which, with --zone")
    req = dict({"verb": args.verb}, **{k: v for k, v in given.items() if v is not None})
    if args.verb in ("todo-done", "todo-undo", "todo-date"):
        req = session_line(ws, req)
    return req


def command_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Do what a status page button asks. With a verb, from the options below; without one, "
                    "reading one JSON request on stdin.")
    ap.add_argument("--workspace", help="the workspace (default: the one this script is in)")
    ap.add_argument("--via", choices=CALLERS, help="who is asking, for the log and the record (default: session "
                                                  "with a verb, page with JSON)")
    ap.add_argument("verb", nargs="?", choices=sorted(CLI_FIELDS), help="the action; leave out to read JSON on stdin")
    for name in ("zone", "project", "thread", "name", "party", "to", "text", "target", "date", "file", "line",
                 "confirm", "commit", "spoken", "thread-spoken", "wiki", "words", "until", "pages"):
        ap.add_argument("--" + name)
    return ap


def main(argv=None) -> int:
    args = command_parser().parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve() if args.workspace else HERE.parent.parent
    cli = args.verb is not None
    via = args.via or ("session" if cli else "page")
    req, logged = None, None
    try:
        if not (ws / "System" / "rules.md").is_file() or not (ws / "Zones").is_dir():
            raise Refused("not a Garrick workspace")
        if cli:
            req = session_request(ws, args)
        else:
            try:
                req = json.loads(sys.stdin.read())
            except ValueError:
                raise Refused("not a request")
        ops = ops_lib(ws)
        if ops is not None and isinstance(req, dict) and req.get("verb") == JOURNAL_VERB:
            print(json.dumps(ops.read(jobs_dir()), ensure_ascii=False))     # a read: nothing to log
            return 0
        out, logged, _ = perform(ws, req, ops, via)
    except Refused as e:
        out = {"ok": False, "say": str(e)}
    except Exception as e:              # a fault still answers in JSON, and is logged
        out = {"ok": False, "say": "that did not work: %s: %s" % (type(e).__name__, e)}
    audit(req if req is not None else {}, out["ok"], logged or out["say"], via=via)
    if cli:                             # a session reads the sentence, not JSON
        undo = ("\nTo undo: python3 System/status/page_action.py undo --zone %s --commit %s" % (args.zone, out["commit"])
                if out.get("ok") and out.get("commit") else "")
        print(out["say"] + undo, file=sys.stdout if out["ok"] else sys.stderr)
    else:
        print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
