#!/usr/bin/env python3
"""ask.py: the ask box. A preview feature, `ask`, off until the workspace
switches it on in System/garrick-flags.json.

    python3 ask.py --workspace ~/Garrick ask "open Pricing in Claude"
    python3 ask.py --workspace ~/Garrick ask --json "park Pricing"   each line as it comes, for the app
    python3 ask.py --workspace ~/Garrick warm      start the session, answer nothing
    python3 ask.py --workspace ~/Garrick keep      the app's: start the session if it is not running, hold the lease
    python3 ask.py --workspace ~/Garrick reset     a fresh conversation now
    python3 ask.py --workspace ~/Garrick stop      stop the server and its session
    python3 ask.py --workspace ~/Garrick status    the server, the session's age and its turns
    python3 ask.py --workspace ~/Garrick --list    the workspace list the session is given

Garrick.app sends what is typed in its panel's field, or in the box ⌘G opens,
here. A short request in plain words ("open Pricing", "park the launch
video", "what's open") comes back as one sentence and the actions it took.

**One warm session, cleared every three hours.** A small server keeps one
assistant session open, reached through a socket in the jobs folder that
only you can read. With Claude (GARRICK_HARNESS unset or `claude`) it is one
`claude -p` process in stream-json mode, with no tools, no MCP servers and no
transcript on disk, so a request answers in a second or two and a follow-up
("no, the other one") works. It is sealed, as the answer session below is:
it holds its brief and what each request sends it, and nothing else. A
session older than three hours is replaced before the next request, and the
server exits after three hours with nothing asked of it. Codex has no such
mode: each request is one `codex exec` through agent.py, read-only, given
the last few exchanges again, run in an empty folder outside the workspace
that is removed when it returns, so no AGENTS.md of the workspace's is found.

**The session starts with the app, belongs to it, and is marked.** With Ask
on, Garrick.app sends `keep` a second after its window shows and every two
minutes after: the server starts the session when it is not running, and
never replaces one that is (the age rule above stays with `warm` and the
requests). Each `keep` holds a lease of LEASE seconds. While it is held, a
session that has died is started again within TICK seconds, once between
two keeps so a CLI that dies as it starts is not started every tick, and by
the next keep after that, each time with one line in ask.log that says so
and nothing else. When the lease lapses (the app crashed, or was
force-quit) the server stops, session and all. The app sends `stop` when it
quits, and `keep` with the flag off stops the server. Every process the
server starts carries MARKER (notifications.BACKGROUND), so the user's
assistant hooks send no notice for it; and none carries `CLAUDECODE` or a
`CMUX_*` variable, and the CLI is the real binary (handoff.find_claude()),
never a terminal's wrapper, so cmux has no record of it. With
`--no-session-persistence` it writes no transcript, so no list Garrick reads
of work sessions shows it. A new process, however it started, is given the
whole workspace list with its first request.

**One connection, read line by line.** A request's reply is JSON lines on
its connection: none or more `{"progress": "<text>"}` while it works, then
exactly one final line, the reply, which always carries `kind`: `command`,
`clarify` or `answer` (`command` where the reply names none). `call()`
hands each progress line to whoever asked, and `--json` prints them as they
come, so the app's window shows what is happening and never waits for the
end to show anything. Asker.progress is what a turn says progress through;
the server points it at the connection for that request only.

**Stop is said on the same connection**, as the line `{"stop": true}`. While a Claude
turn waits on the session, the server listens to the connection too, and on
STOP ends the session process: `claude -p` documents no way to interrupt a
turn in stream-json mode, so the conversation goes with it, and the next
request starts a fresh session, told the whole list. The final line then
says `"stopped": true`, and nothing the session proposed has run, because
it had proposed nothing yet. A client that leaves is not a Stop: the turn
runs on, as before. `call()` sends STOP when it is interrupted (Ctrl-C, or
the app's Stop, which sends SIGINT). With Codex the one call runs to its
end, and Stop is heard too late to matter.

A Claude session that reports an error, its budget spent say, is stopped,
so the next request starts a fresh one. One server per workspace: a lock
beside the socket keeps a second from starting, and a client that hears
nothing for ASK_WAIT seconds stops waiting and says so. That wait covers
the slowest request the server can be given, an action that commits and so
waits for the zone's wall check among them; and a client that gives up all
the same says the change may still be on its way and what to look at, never
just to ask again. ASK_WAIT is operations.py's, from its clock.

**The tier and the caps are the scheduled jobs'.** The session runs on
GARRICK_ASK_TIER (`haiku`, or `sonnet`, `opus`), named as a tier, never a
model, as agent.py names them. It loads agent.py's deny profile,
headless-settings.json. Every request is one call against agent.py's caps
(GARRICK_CAP_CALLS_HOUR and the rest) and one line in its ledger, as job
`ask`; a request past a cap is refused and calls nothing. A Claude session
as a whole stops at GARRICK_MAX_CALL_USD, and the next request starts
another. ask.py needs agent.py, from the scheduled jobs extra, in
System/jobs/ beside System/status/.

**The model proposes, this file disposes.** The session sees only names and
states: each request carries the live projects and threads of every zone,
from their frontmatter, sent again only when it has changed, and `<names>`,
each name the request holds as it was heard and what ask_scope.mentions()
settled it to: a party, a person and their party, a project or a thread.
The session loads no System/context.md, so an alias or a person reaches it
that way, and only the ones the request names. It answers with JSON
(ask-brief.md). Each action is checked against that list, then:

    open       comes back to the app as a folder to open, in an app the
               request named or the user's default; an app switched off in
               Settings is refused, and the app checks it again. With the
               cmux extra's desk ready (`dk`), cmux opens it as a tab that
               starts the session, as the page's buttons do
    park, wake run through page_action.perform(), as the page's buttons do:
    todo-add   the status field or the line, committed in the zone's
               repository, with the durable record the page's clicks keep

Nothing else: no ticking, no jobs, no settings, nothing sent. What happened
is carried into the next request as `<last-results>`.

**A question is answered from the records, which this file reads (#261,
slice C).** Before a request reaches any session, ask_scope.mentions()
settles the names in it to parties and places, from the list and from
System/context.md; a name that fits two entries is asked about (`kind:
"clarify"`) and nothing is read. For a question about what is *in* the
records the session proposes a `find` instead of actions: a route
(meetings, knowledge, a thread, Garrick's docs) and the words to look for.
ask_scope.scope() checks it against the list, ask_scope.search() reads files
inside that scope only, Sources/ documents through extract.py among them,
and a second session answers from the passages, on GARRICK_ASK_ANSWER_TIER
(`sonnet` unless set). It has no tools and proposes nothing: its reply is
said, never carried out, so text inside a record can never become an
action. It holds nothing but its brief, the list and the records admitted.
Both sessions are sealed alike: no settings but the deny profile
(`--setting-sources ""`), so no CLAUDE.md, rules or context of the user's;
no memory (CLAUDE_CODE_DISABLE_AUTO_MEMORY); and an empty folder outside
the workspace as the working folder, made when the session starts, removed
when it stops (sealed_folder()). The find and its answer are one call
against the caps and one line in the ledger. With Codex a question gets a
plain reply that answers need Claude.

**The wall reset.** Asker.admit() is the only way a record reaches a
prompt, and it adds the parties of what it admits to Asker.seen: a meeting
its `parties:`, a project or a thread its hub's `party:`, Knowledge and the
docs none. Before a request is sent, and again before anything is read, a
party walled from one in `seen` (any party at all, for a question across
every zone) stops both sessions and clears everything they were told: the
results, the questions waiting for a yes, `seen`, the records admitted, and
which process was given the list. The new processes get the new request
only, and the reply carries `"reset": "wall"`. A question across every zone
reads within one group of parties no wall divides; when a wall held records
back, the answer ends with the rules' sentence for it, word for word, and
says nothing of what it held.

**A request sent again is asked about, not done twice.** The record
recognises one that repeats an action it holds (operations.py): past a double
click's window, the action comes back as a question, which goes into
`<last-results>` like any result. When the user says yes, the session sends
the same action again with `"again": true`, and this file adds the `confirm`
that names the action asked about. Only a question from the turn before can
be answered that way; anything else asks again. One line per request
goes in ask.log in the jobs folder, and each action page_action.py runs in
page-actions.log, as from the page. The line holds the time, the op, the
kind of reply, the milliseconds and the tokens, and no request or answer
text: an answer carries what the records say. GARRICK_ASK_LOG_TEXT=1 adds
the first 200 characters of the request, the reply and what was done.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
BRIEF = HERE / "ask-brief.md"
ANSWER_BRIEF = HERE / "ask-answer-brief.md"
JOB = "ask"
FLAG = "ask"
DEFAULT_TIER = "haiku"
DEFAULT_ANSWER_TIER = "sonnet"
LOG_TEXT = "GARRICK_ASK_LOG_TEXT"   # =1: ask.log keeps the request's and the reply's text too
CLEAR_AFTER = 3 * 3600      # seconds: a session older than this is replaced, a server idle this long exits
SEND_TIMEOUT = 10           # seconds: the server waits this long for a client to take its answer
SERVE_WAIT = 5              # seconds: a second server waits this long for the first to go, then leaves it be
HISTORY = 6                 # exchanges a harness with no warm session is given again
MOST_HEARD = 12             # names a request's <names> block holds
MARKER = "GARRICK_BACKGROUND"   # notifications.BACKGROUND: every process this server starts carries it
LEASE = 10 * 60             # seconds: the server stays up this long after the app's last `keep`
TICK = 15                   # seconds: how often a held lease looks for a dead session, the accept timeout then
IDLE_TICK = 60              # seconds: the accept timeout with no lease
MAX_REQUEST = 2000
GONE = ("done",)
STOP = b'{"stop": true}\n'    # said on a request's own connection: stop that request
KINDS = ("command", "clarify", "answer")    # what a final line's `kind` says it is
STOPPED = "Stopped. Nothing was done, and the next request starts a new conversation."
APPS = ("claude", "codex", "cmux", "finder")
VERBS = ("open", "park", "wake", "todo-add")
# The app starts with a bare PATH; an assistant's command line usually lives in one of these.
EXTRA_PATH = ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin")

# What a client says when it gives up all the same: the action may yet
# finish, so nothing here invites another one.
GAVE_UP = ("The ask server did not answer in %s. The change may still be on its way: an action that commits waits "
           "for the zone's wall check. Look at the Todo list, or the thread, before you ask again. If it went "
           "through, asking again says so, and asks before doing it a second time.")
NEED_CLAUDE = ("Answers from your records need Claude. With Codex the box does commands: open, park, wake, "
               "and add a line to a Todo list.")
NOTHING_FOUND = "Nothing in the records answers that."


class Bad(Exception):
    pass


class Stopped(Bad):
    """The request was stopped on its connection, and the session with it."""


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_AGENT = None
_PA = None


def agent():
    """agent.py, from the scheduled jobs extra: System/jobs/ in a workspace,
    extras/jobs/ in Garrick's source, beside this file's folder either way."""
    global _AGENT
    if _AGENT is None:
        path = HERE.parent / "jobs" / "agent.py"
        if not path.is_file():
            raise Bad("ask needs agent.py from the scheduled jobs extra in %s" % path.parent)
        _AGENT = _load("garrick_agent", path)
    return _AGENT


_HANDOFF = None


def handoff():
    """handoff.py, beside this file: find_claude(), the real CLI and never a wrapper."""
    global _HANDOFF
    if _HANDOFF is None:
        _HANDOFF = _load("garrick_ask_handoff", HERE / "handoff.py")
    return _HANDOFF


def claude_binary() -> str:
    """The `claude` the session runs: handoff.find_claude()'s, which takes
    GARRICK_CLAUDE first and passes over a shell wrapper; GARRICK_CLAUDE as
    given when it names nothing there, so it still wins; else `claude`."""
    found = handoff().find_claude()
    if found is not None:
        return str(found)
    return os.environ.get("GARRICK_CLAUDE") or "claude"


def page_action():
    global _PA
    if _PA is None:
        _PA = _load("garrick_page_action", HERE / "page_action.py")
    return _PA


_SCOPE = None


def scope_lib():
    """ask_scope.py, beside this file: the names in a request, the scope of an answer and the records inside it."""
    global _SCOPE
    if _SCOPE is None:
        _SCOPE = _load("garrick_ask_scope", HERE / "ask_scope.py")
    return _SCOPE


# Seconds a turn may take, and a client waits for the server's answer: both
# from operations.py's clock, through page_action.py, which derives the wait
# from the slowest request the server can be given, two turns and an action
# that commits, and the record's lookback from that wait (#137). A shorter
# wait said the server had not answered while the commit was still running,
# and the retry it prompted did the action a second time (#92).
TURN_TIMEOUT = page_action().clock("TURN_TIMEOUT")
ASK_WAIT = page_action().clock("ASK_WAIT")


_PREFS = None


def prefs():
    """prefs.py, beside this file: the one way to the choices the page keeps."""
    global _PREFS
    if _PREFS is None:
        _PREFS = _load("garrick_prefs", HERE / "prefs.py")
    return _PREFS


def flag_on(ws: Path) -> bool:
    return page_action().flag_on(ws, FLAG)


def desk_ready(ws: Path) -> bool:
    """Whether cmux opens through the cmux extra's desk, as status.py's page
    decides it: the extra beside the page, cmux installed."""
    pa = page_action()
    try:
        pa.cmux_desk()
    except pa.Refused:
        return False
    return True


def launcher_on(ws: Path, app: str) -> bool:
    """Whether Settings › Opening a thread has this app switched on, read as
    status.py's shared_launchers() reads the choices the workspace keeps
    (prefs.FILE): {name: true or false}, a name left out being on, or a list
    of the names on. Nothing saved, or nothing that reads: every app is on."""
    on = prefs().read(ws).get("launchers")
    if isinstance(on, dict):
        return on.get(app, True) is True
    if isinstance(on, list):
        return app in on
    return True


def tier(name: str = "GARRICK_ASK_TIER", default: str = DEFAULT_TIER) -> str:
    chosen = os.environ.get(name, default).strip().lower() or default
    if chosen not in agent().TIERS:
        raise Bad("%s is %r; use %s" % (name, chosen, ", ".join(agent().TIERS)))
    return chosen


def answer_tier() -> str:
    """The answers' tier: a second session, since one `claude -p` runs one model."""
    return tier("GARRICK_ASK_ANSWER_TIER", DEFAULT_ANSWER_TIER)


# ---------------------------------------------------------------- the workspace list


def status_of(note: Path) -> str:
    head = note.read_text(encoding="utf-8", errors="replace")[:3000]
    m = re.match(r"---\n(.*?)\n---", head, re.S)
    s = re.search(r"(?m)^status:\s*(\S+)", m.group(1)) if m else None
    return s.group(1).strip("\"'").lower() if s else "active"


def scan(ws: Path) -> Dict[str, Dict[str, dict]]:
    """{zone: {project: {"status": s, "threads": {thread: status}}}} for every
    live project in every zone: a folder with a hub note of its own name, and
    its thread notes. Frontmatter only; nothing from a note's body."""
    out = {}
    zones = ws / "Zones"
    for zone in sorted((z for z in zones.iterdir() if z.is_dir()), key=lambda p: p.name.casefold()) if zones.is_dir() else []:
        if zone.name.startswith((".", "_")):
            continue
        projects = {}
        for folder in sorted((p for p in zone.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
            hub = folder / (folder.name + ".md")
            if folder.name.startswith((".", "_")) or folder.name == "archive" or not hub.is_file():
                continue
            s = status_of(hub)
            if s in GONE:
                continue
            threads = {}
            for t in sorted((folder / "Threads").glob("*/"), key=lambda p: p.name.casefold()):
                note = t / (t.name + ".md")
                if note.is_file() and status_of(note) not in GONE:
                    threads[t.name] = status_of(note)
            projects[folder.name] = {"status": s, "threads": threads}
        out[zone.name] = projects
    return out


def render(names: Dict[str, Dict[str, dict]]) -> str:
    lines = []
    for zone, projects in names.items():
        lines.append("%s:" % zone)
        for p, r in projects.items():
            ts = "; ".join(t + ("" if s == "active" else " (%s)" % s) for t, s in r["threads"].items())
            lines.append("- %s [%s]%s" % (p, r["status"], " threads: " + ts if ts else ""))
    return "\n".join(lines)


def spoken(names: Dict[str, Dict[str, dict]], zone: str, project: str, thread: Optional[str]) -> str:
    """The shortest name that is unique, as the threads skill says it: the
    thread alone, then project and thread, then the zone as well."""
    if thread is None:
        same = sum(project in ps for ps in names.values())
        return project if same == 1 else "%s, %s" % (zone, project)
    taken = [(z, p) for z, ps in names.items() for p, r in ps.items() if thread in r["threads"] or p == thread]
    if len(taken) == 1:
        return thread
    if sum(p == project for _, p in taken) == 1:
        return "%s, %s" % (project, thread)
    return "%s, %s, %s" % (zone, project, thread)


# ---------------------------------------------------------------- the answer, checked


def parse(text: str) -> Tuple[str, list]:
    """The JSON object in the answer, fence or no fence: (say, actions)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise Bad("the answer held no JSON")
    try:
        obj = json.loads(m.group(0))
    except ValueError as e:
        raise Bad("the answer's JSON did not parse: %s" % e)
    if not isinstance(obj, dict):
        raise Bad("the answer was not one JSON object")
    say = obj.get("say") if isinstance(obj.get("say"), str) else ""
    do = obj.get("do") if isinstance(obj.get("do"), list) else []
    return say.strip(), do


def wanted(text: str) -> Optional[dict]:
    """The `find` the answer proposes, when it is a question for the records,
    or None. Whatever it holds is checked by ask_scope.scope() before anything is read."""
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        obj = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    return obj["find"] if isinstance(obj, dict) and "find" in obj else None


def said(text: str) -> str:
    """An answer's sentence: its JSON's `say`, or the text itself when the
    session answered in plain words. Anything else it holds is dropped."""
    try:
        return parse(text)[0]
    except Bad:
        return (text or "").strip()


def proposal(a, names: Dict[str, Dict[str, dict]], ws: Path) -> Tuple[str, dict]:
    """One proposed action, checked against the workspace list: ("act", a
    page_action request) or ("launch", what the app opens). Raises Bad."""
    if not isinstance(a, dict):
        raise Bad("an action that is not an object")
    verb = a.get("verb")
    if verb not in VERBS:
        raise Bad("not something the box does: %r" % (verb,))
    zone, project, thread = a.get("zone"), a.get("project"), a.get("thread")
    if not isinstance(zone, str) or zone not in names:
        raise Bad("no zone %r" % (zone,))
    if project is not None and (not isinstance(project, str) or project not in names[zone]):
        raise Bad("no project %r in %s" % (project, zone))
    if thread is not None and (project is None or not isinstance(thread, str) or thread not in names[zone][project]["threads"]):
        raise Bad("no thread %r in %s" % (thread, project or zone))
    if verb == "todo-add":
        text = a.get("text")
        if not isinstance(text, str) or not text.strip():
            raise Bad("a Todo line with no text")
        date = a.get("date") or "-"
        if date != "-" and (not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)):
            raise Bad("not a date: %r" % (date,))
        target = "-" if project is None else project if thread is None else "%s/%s" % (project, thread)
        return "act", {"verb": "todo-add", "zone": zone, "text": text.strip(), "target": target, "date": date}
    if project is None:
        raise Bad("%s names a project" % verb)
    if verb in ("park", "wake"):
        if thread is None:          # the whole project: its hub, which holds every thread in it
            return "act", {"verb": verb, "zone": zone, "project": project}
        return "act", {"verb": verb, "zone": zone, "file": "%s/Threads/%s/%s.md" % (project, thread, thread)}
    app = a.get("app") or ""
    if app and app not in APPS:
        raise Bad("no app %r" % (app,))
    if app and not launcher_on(ws, app):
        raise Bad("%s is switched off in Settings" % ("cmux" if app == "cmux" else app.capitalize()))
    folder = ws / "Zones" / zone / project
    if thread is not None:
        folder = folder / "Threads" / thread
    name = spoken(names, zone, project, thread)
    return "launch", {"app": app, "folder": str(folder), "phrase": "open " + name, "name": name}


# ---------------------------------------------------------------- the session


def cost_of(event: dict) -> Optional[float]:
    v = event.get("total_cost_usd")
    return float(v) if isinstance(v, (int, float)) else None


def bill(entries) -> None:
    """One ledger line for one request, however many turns it took: a find
    and its answer are one call against the caps (#261). Each entry is a
    turn's (start, tier, outcome, seconds, exit code), as ClaudeSession.last
    holds it; the line takes the last turn's tier."""
    entries = [e for e in entries if e]
    if not entries:
        return
    a = agent()
    costs = [e[2]["cost_usd"] for e in entries if isinstance(e[2].get("cost_usd"), (int, float))]
    turns = [e[2]["turns"] for e in entries if isinstance(e[2].get("turns"), int)]
    outcome = {"turns": sum(turns) if turns else None, "cost_usd": sum(costs) if costs else None,
               "denied": sorted({d for e in entries for d in e[2].get("denied") or []}),
               "subtype": entries[-1][2].get("subtype")}
    a.append_ledger(a.ledger_path(), a.ledger_entry(entries[0][0], JOB, entries[-1][1], outcome,
                                                    sum(e[3] for e in entries), max(e[4] for e in entries)))


def sealed_folder(ws: Path) -> Path:
    """An empty folder of a session's own, outside the workspace, for it to
    run in: from there no instruction file, project setting or memory keyed
    to a folder of the workspace is found. The caller removes it."""
    home = Path(tempfile.mkdtemp(prefix="garrick-ask-")).resolve()
    root = Path(ws).resolve()
    if home == root or root in home.parents:
        shutil.rmtree(str(home), ignore_errors=True)
        raise Bad("the temporary folder is inside the workspace, so no session was started")
    return home


class ClaudeSession:
    """One `claude -p` kept open in stream-json mode, every turn counted against agent.py's caps."""

    remembers = True

    def __init__(self, ws: Path, tier_: str, brief: Path = BRIEF):
        self.ws, self.tier, self.brief = ws, tier_, brief
        # Sealed, the command session and the answer session alike: each
        # holds its brief and what it is sent, and nothing else. No settings
        # but the deny profile, so no CLAUDE.md, rules or context of the
        # user's; no memory; and a folder of its own, empty and outside the
        # workspace, made when it starts and removed when it stops, so nothing
        # is keyed to the workspace either.
        self.home = None
        self.last = None            # the last turn's ledger entry, when its caller writes the line
        self.proc = None
        self.pending = b""          # what was read past the last whole line
        self.started = 0.0
        self.turns = 0
        self.spent = 0.0            # what the session has cost so far, as Claude reports it
        self.watch = None           # the connection a turn listens to for STOP, while one is asked on it

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, at_once: bool = False) -> None:
        """Ends the process: its input closed, so it finishes and goes; or, at
        once, mid-turn, which is a Stop, ended and not waited on."""
        if self.proc is not None:
            try:
                if at_once:
                    self.proc.terminate()
                else:
                    self.proc.stdin.close()
                self.proc.wait(timeout=2 if at_once else 5)
            except Exception:
                self.proc.kill()
                self.proc.wait()
            for pipe in (self.proc.stdin, self.proc.stdout):
                try:
                    pipe.close()
                except OSError:
                    pass
        if self.home is not None:
            shutil.rmtree(self.home, ignore_errors=True)
            self.home = None
        self.proc, self.turns, self.spent, self.pending = None, 0, 0.0, b""

    def command(self) -> List[str]:
        a = agent()
        problem = a.profile_problem(a.PROFILE)
        if problem:
            raise Bad("the deny profile %s %s, so nothing was asked" % (a.PROFILE.name, problem))
        cmd = [claude_binary(), "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--model", self.tier, "--tools", "", "--strict-mcp-config", "--no-session-persistence",
               "--permission-mode", "default", "--settings", str(a.PROFILE),
               "--setting-sources", "",
               "--system-prompt", self.brief.read_text(encoding="utf-8")]
        budget = a._number("GARRICK_MAX_CALL_USD", a.DEFAULT_MAX_CALL_USD)
        if budget > 0:
            cmd += ["--max-budget-usd", "%g" % budget]
        return cmd

    def start(self) -> None:
        self.stop()
        cmd = self.command()
        self.home = sealed_folder(self.ws)
        env = dict(os.environ, CLAUDE_CODE_DISABLE_AUTO_MEMORY="1")
        try:
            self.proc = subprocess.Popen(cmd, cwd=str(self.home), env=env, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            self.stop()
            raise Bad("claude is not installed, or not on PATH")
        self.started = time.time()

    def fresh(self) -> bool:
        """Whether the next turn starts a new process, which knows nothing yet."""
        return not self.alive() or time.time() - self.started > CLEAR_AFTER

    def ready(self) -> None:
        if self.fresh():
            self.start()

    def line(self, deadline: float) -> str:
        """The session's next line of output. Read from the pipe itself, so a
        line already read along with the one before is never waited for.
        Listens to the request's connection too: STOP there ends the session."""
        fd = self.proc.stdout.fileno()
        while b"\n" not in self.pending:
            watch = [self.watch] if self.watch is not None else []
            ready, _, _ = select.select([fd] + watch, [], [], max(0.0, deadline - time.time()))
            if not ready:
                self.stop()
                raise Bad("the session took too long and was stopped; ask again")
            if watch and watch[0] in ready:
                said = stop_said(watch[0])
                if said is None:
                    self.watch = None           # the client left: the turn runs on, as before
                elif said:
                    self.stop(at_once=True)
                    raise Stopped("stopped")
            if fd not in ready:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                self.stop()
                raise Bad("the session ended; the next request starts a new one")
            self.pending += chunk
        line, self.pending = self.pending.split(b"\n", 1)
        return line.decode("utf-8", "replace")

    def turn(self, text: str, cap: bool = True, record: bool = True) -> Tuple[str, dict]:
        """One message and its result: (text, usage). Refused, calling nothing,
        past a cap, unless `cap` is off for the second turn of one request.
        With `record` off the turn's ledger entry is left in `last`, for the
        caller to write as part of the request's one line, error or not."""
        a = agent()
        self.last = None
        ledger, now = a.ledger_path(), time.time()
        reason = a.cap_reason(a.read_ledger(ledger, now), now, a.caps()) if cap else None
        if reason:
            a.append_ledger(ledger, a.ledger_entry(now, JOB, self.tier, {}, 0, a.EXIT_CAP, refused=reason))
            raise Bad("not asked: %s. Raise GARRICK_CAP_* or wait" % reason)
        self.ready()
        start = time.time()
        self.proc.stdin.write((json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        try:
            while True:
                line = self.line(start + TURN_TIMEOUT)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("type") == "result":
                    break
        except Stopped:
            # A call all the same, against the caps: what it cost so far is not reported.
            self.last = (start, self.tier, {"subtype": "stopped"}, time.time() - start, 1)
            if record:
                bill([self.last])
            raise
        self.turns += 1
        # The cost Claude reports runs for the whole session; the ledger wants this request's.
        total = cost_of(event)
        cost = None if total is None else (total - self.spent if total >= self.spent else total)
        if total is not None:
            self.spent = total
        denied = sorted({d.get("tool_name") for d in event.get("permission_denials") or [] if isinstance(d, dict)} - {None})
        code = 1 if event.get("is_error") else 0
        self.last = (start, self.tier, {"turns": event.get("num_turns"), "cost_usd": cost, "denied": denied,
                                        "subtype": event.get("subtype")}, time.time() - start, code)
        if record:
            bill([self.last])
        if code:
            self.stop()             # a spent budget would refuse every turn after it; the next request starts afresh
            raise Bad("the assistant reported an error: %s; the next request starts a new session"
                      % (event.get("subtype") or "unknown"))
        return event.get("result") or "", event.get("usage") or {}


class OnceSession:
    """A harness with no warm session: one agent.py call per request,
    read-only, with the last few exchanges given again. Each call runs in an
    empty folder of its own outside the workspace, removed when it returns,
    so Codex finds no AGENTS.md or project setting of the workspace's."""

    remembers = False
    last = None                     # agent.run() writes its own ledger line

    def __init__(self, ws: Path, tier_: str):
        self.ws, self.tier = ws, tier_
        self.history: List[Tuple[str, str]] = []
        self.started = 0.0
        self.turns = 0

    def alive(self) -> bool:
        return bool(self.history)

    def fresh(self) -> bool:
        return True                 # every call is given the whole list

    def stop(self) -> None:
        self.history, self.turns = [], 0

    def start(self) -> None:
        self.stop()
        self.started = time.time()

    def ready(self) -> None:
        if time.time() - self.started > CLEAR_AFTER:
            self.start()

    def turn(self, text: str, cap: bool = True, record: bool = True) -> Tuple[str, dict]:
        self.ready()
        before = "".join("<earlier-request>\n%s\n</earlier-request>\n<earlier-answer>\n%s\n</earlier-answer>\n" % h
                         for h in self.history[-HISTORY:])
        prompt = BRIEF.read_text(encoding="utf-8") + "\n\n" + before + text
        home = sealed_folder(self.ws)
        try:
            code, out = agent().run(self.tier, prompt, allow=(), cwd=home, job=JOB)
        finally:
            shutil.rmtree(str(home), ignore_errors=True)
        if code == agent().EXIT_CAP:
            raise Bad("not asked: a cap on assistant calls was reached. Raise GARRICK_CAP_* or wait")
        if code:
            raise Bad("%s exited %d" % (agent().harness(), code))
        request = re.search(r"<request>\n(.*?)\n</request>", text, re.S)
        self.history.append((request.group(1) if request else text, out.strip()))
        self.turns += 1
        return out, {}


def session_for(ws: Path):
    h = agent().harness()
    if h not in agent().HARNESSES:
        raise Bad("GARRICK_HARNESS is %r; use claude or codex" % h)
    return (ClaudeSession if h == "claude" else OnceSession)(ws, tier())


def heard_names(named, ctx: dict, since: int = 0) -> str:
    """The command session's `<names>` block: each name the request holds,
    as it was heard, and what ask_scope.mentions() settled it to, from the
    list and System/context.md's Parties, People and Aliases. The session
    is sealed and loads no context, so this is how a mangled name, an alias
    or a person reaches it. Names, kinds and zones only: never a role, a
    domain or anything from a note. A name heard before `since` is left out:
    the request a wall reset dropped."""
    parties = ctx.get("parties", {})
    lines = []
    for start, _, words, means in getattr(named, "heard", None) or []:
        if start < since:
            continue
        said = []
        for e in means:
            if e.kind == "party":
                d = "the party %s" % e.label + (" in %s" % e.zone if e.zone else "")
            elif e.kind == "person":
                of = ", ".join(sorted(parties.get(p, {}).get("party") or p for p in e.parties))
                d = "the person %s" % e.label + (", of %s" % of if of else "")
            elif e.kind == "project":
                d = "the project %s in %s" % (e.project, e.zone)
            else:
                d = "the thread %s of %s in %s" % (e.thread, e.project, e.zone)
            if d not in said:
                said.append(d)
        line = "- %s: %s" % (json.dumps(" ".join(words.split()), ensure_ascii=False), "; ".join(said))
        if said and line not in lines:
            lines.append(line)
    return "<names>\n%s\n</names>" % "\n".join(lines[:MOST_HEARD]) if lines else ""


class Asker:
    def __init__(self, ws: Path, session=None):
        self.ws = ws
        self.session = session
        self.sent = None            # the hash of the list the session was last given
        self.told = None            # the `started` of the process last given the whole list
        self.results = ""           # what the last actions did, for the next turn
        self.asked = {}             # each request the last turn was asked about: the action to confirm
        self.answers = None         # the second session, which answers from records: started on the first question
        self.answer_sent = None     # its `sent` and `told`, as above
        self.answer_told = None
        self.seen = set()           # the parties whose records the answer process holds (admit())
        self.seen_for = None        # the `started` of the process `seen` describes
        self.passages = []          # each record admitted to that process, its id and path
        self.unclear = None         # a request the box asked about, waiting for the answer that settles it
        self.ctx = {}               # System/context.md, as garrick_lib reads it, for this request
        self.progress = lambda text: None

    def ask(self, request: str, today: Optional[dt.date] = None) -> dict:
        if not flag_on(self.ws):
            return off()
        if self.session is None:
            self.session = session_for(self.ws)
        sc = scope_lib()
        lib = sc.lib(self.ws)
        if lib is None:
            raise Bad("ask needs garrick_lib.py in System/tools/")
        self.ctx = lib.load_context(self.ws)
        names = scan(self.ws)
        # The names first, before any session hears the request: one that
        # fits two entries is asked about, and nothing is read or sent.
        earlier = self.unclear
        heard = request if earlier is None else earlier + "\n" + request
        named = sc.mentions(self.ws, heard, names, self.ctx, lib)
        if named.question:
            self.unclear = heard[-MAX_REQUEST:]
            return clarify(named.question)
        self.unclear = None
        reset = self.crosses(named.parties)
        since = 0                                   # where in `heard` the names sent begin
        if reset:
            self.progress("Starting a fresh session")
            self.reset()
            since = 0 if earlier is None else len(earlier) + 1
            earlier, heard = None, request      # the new processes get the new request alone
        listing = render(names)
        sent = hashlib.sha1(listing.encode("utf-8")).hexdigest()
        # A process other than the one last told knows nothing: after a reset,
        # a warm that replaced an aged session, or a restart, the hash alone
        # would leave it with no names at all.
        whole = sent != self.sent or self.session.fresh() or self.session.started != self.told
        parts = ["<today>%s</today>" % (today or dt.date.today()).isoformat(),
                 "<workspace>\n%s\n</workspace>" % listing if whole else "<workspace unchanged/>"]
        if self.results:
            parts.append("<last-results>\n%s\n</last-results>" % self.results)
        if earlier is not None:                     # the request the box asked about, which this one answers
            parts.append("<earlier-request>\n%s\n</earlier-request>" % earlier[:MAX_REQUEST])
        known = heard_names(named, self.ctx, since)
        if known:                                   # the names it heard, settled: the session loads no context
            parts.append(known)
        parts.append("<request>\n%s\n</request>" % request[:MAX_REQUEST])
        turns = []
        try:
            try:
                text, usage = self.session.turn("\n".join(parts), record=False)
            finally:
                turns.append(getattr(self.session, "last", None))
            self.sent, self.told = sent, self.session.started
            find = wanted(text)
            if find is not None:
                out, again = self.answer(heard, find, named, names, today, turns, usage)
                reset = reset or again
            else:
                bill(turns)
                turns = []
                say, do = parse(text)
                if not do and re.search(r"\balready open", say, re.I) and self.session.remembers:
                    # It cannot know what is open; the brief says so, and this holds it to that once more.
                    text, usage = self.session.turn("<correction>You cannot know what is open. Send the open action "
                                                    "for the request above; never answer \"already open\".</correction>")
                    say, do = parse(text)
                out = self.carry_out(say, do, names, usage)
        finally:
            bill(turns)
        if reset:
            out["reset"] = "wall"
        return out

    def answer(self, request: str, find: dict, named, names, today: Optional[dt.date], turns: list,
               usage: dict) -> Tuple[dict, bool]:
        """A question, answered from the records inside its scope by the second
        session: (the reply, whether a wall reset ran). Its turn goes in
        `turns`, so the request is one line in the ledger. What it says is
        said; it never carries out an action, whatever a record holds."""
        sc = scope_lib()
        lib = sc.lib(self.ws)
        self.results, self.asked = "", {}
        if not self.session.remembers:
            return reply(NEED_CLAUDE), False
        self.progress("Finding the records")
        try:
            where = sc.scope(self.ws, find, named, names, self.ctx, lib)
        except sc.Unclear as e:
            self.unclear = request[-MAX_REQUEST:]
            return clarify(str(e)), False
        except sc.Refused as e:
            raise Bad(str(e))
        reset = self.crosses(where.parties, where.every)
        if reset:                                   # before anything is read
            self.progress("Starting a fresh session")
            self.reset()
        records, back = sc.pick(sc.search(self.ws, where, self.ctx, lib), self.holding(), self.ctx, lib)
        if not records and not self.passages:       # nothing to read, and nothing read before it
            return reply(self.wall() if back else NOTHING_FOUND, "answer"), reset
        if self.answers is None:
            self.answers = ClaudeSession(self.ws, answer_tier(), ANSWER_BRIEF)
        self.progress("Reading %d record%s" % (len(records), "" if len(records) == 1 else "s"))
        self.answers.ready()
        if self.answers.started != self.seen_for:   # a new process: what the last one held went with it
            self.seen, self.passages, self.seen_for = set(), [], self.answers.started
        listing = render(names)
        sent = hashlib.sha1(listing.encode("utf-8")).hexdigest()
        whole = sent != self.answer_sent or self.answers.started != self.answer_told
        parts = ["<today>%s</today>" % (today or dt.date.today()).isoformat(),
                 "<workspace>\n%s\n</workspace>" % listing if whole else "<workspace unchanged/>",
                 "<request>\n%s\n</request>" % request[-MAX_REQUEST:],
                 self.admit(records, {p for r in records for p in r["parties"]})]
        self.answers.watch = getattr(self.session, "watch", None)     # Stop is heard in either session
        try:
            text, more = self.answers.turn("\n".join(parts), cap=False, record=False)
        finally:
            self.answers.watch = None
            turns.append(self.answers.last)
        self.answer_sent, self.answer_told = sent, self.answers.started
        say = said(text)
        if back:
            say = (say + " " + self.wall()).strip()
        out = reply(say, "answer")
        out["usage"] = {k: sum(u.get(k) or 0 for u in (usage or {}, more or {}))
                        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens")}
        return out, reset

    def admit(self, passages: List[dict], parties) -> str:
        """The only way a record reaches a prompt (#261, section 3): the
        passages as `<records>`, each with an id, and their parties added to
        `seen`, the parties whose material the answer process holds. A
        passage of no party, Knowledge or the docs, adds none. Refuses what a
        wall divides from what the process holds: the reset runs before
        anything is read, so this never happens unless that order breaks."""
        lib = scope_lib().lib(self.ws)
        held = self.holding()
        adding = set(parties) | {p for r in passages for p in r["parties"]}
        if scope_lib().any_wall(self.ctx, adding, adding | held, lib):
            raise Bad("a wall stands between these records and what the session holds, so none was read")
        self.seen |= adding
        rows = ["<records>"]
        for r in passages:
            rid = "r%d" % (len(self.passages) + 1)
            self.passages.append({"id": rid, "path": r["path"]})
            rows.append('<record id="%s" path="%s"%s>' % (rid, attr(r["path"]),
                                                          ' date="%s"' % attr(r["date"]) if r.get("date") else ""))
            rows += [inert(r["text"]), "</record>"]
        rows.append("</records>")
        return "\n".join(rows)

    def holding(self) -> set:
        """The parties whose records the answer process holds: none once that
        process has ended or another has taken its place."""
        s = self.answers
        if s is None or not s.alive() or s.started != self.seen_for:
            self.seen, self.passages = set(), []
        return self.seen

    def crosses(self, parties, every: bool = False) -> bool:
        """Whether reading for these parties needs a fresh process first: a
        wall between one of them and a party the answer process holds, or,
        for a question across every zone, any party held at all."""
        held = self.holding()
        if every:
            return bool(held)
        return scope_lib().any_wall(self.ctx, parties, held, scope_lib().lib(self.ws))

    def reset(self) -> None:
        """Both sessions stopped, and everything they were told cleared: what
        the last actions did, the questions waiting for a yes, the parties and
        records held, a request asked about, and which process was given the
        list, so the next is given all of it. New conversation, and the wall
        reset. The command session starts again at once, as `reset` always
        did; the answer session on the next question."""
        for s in (self.answers, self.session):
            if s is not None:
                s.stop()
        self.results, self.asked, self.unclear = "", {}, None
        self.seen, self.seen_for, self.passages = set(), None, []
        self.sent = self.told = self.answer_sent = self.answer_told = None
        if self.session is not None:
            self.session.start()

    def stop(self) -> None:
        for s in (self.answers, self.session):
            if s is not None:
                s.stop()

    def wall(self) -> str:
        """System/rules.md's sentence for a wall that held something back, as
        operations.py holds it (#172): this file keeps no copy of its own."""
        said = page_action().wall_refusal(self.ws)
        if not said:
            raise Bad("a wall held records back, and this workspace's operations.py has no sentence to say so")
        return said

    def revive(self) -> bool:
        """Start a warm session that is not running: never replace a live one.
        True when it started one."""
        s = self.session
        if s is None or not s.remembers or s.alive():
            return False
        s.start()
        return True

    def carry_out(self, say: str, do: list, names, usage=None) -> dict:
        if do and not flag_on(self.ws):             # switched off while the session was answering
            return off()
        pa = page_action()
        done, launch, ok = [], [], True
        desk = None
        asked, questions = {}, []
        for a in do:
            try:
                kind, item = proposal(a, names, self.ws)
            except Bad as e:
                done.append("Refused: %s" % e)
                ok = False
                continue
            if kind == "launch":
                desk = desk_ready(self.ws) if desk is None else desk
                if desk:
                    item["dk"] = 1           # the app opens cmux through the desk, the session started
                launch.append(item)
                done.append("Opening %s%s" % (item["name"], " in " + item["app"].capitalize() if item["app"] else ""))
                continue
            same = canon(item)
            if a.get("again") is True and same in self.asked:
                item["confirm"] = self.asked[same]  # the user said yes to the question about it
            out, logged, why = pa.perform(self.ws, item, pa.ops_lib(self.ws))
            good = bool(out.get("ok"))
            said = why or out.get("say") or ""       # a refusal in its own words, as before the record
            pa.audit(item, good, logged or said, via="ask")
            if out.get("again"):                    # done already: asked, not done again
                asked[same] = out["again"]
                questions.append(out["say"])
                done.append(out["say"])
            elif good or said == pa.wall_refusal(self.ws):
                done.append(said)                   # a wall's refusal is the rule's sentence, with nothing added (#172)
            else:
                done.append("Refused: " + said)
            ok = ok and good
        self.asked = asked
        self.results = "\n".join(done)
        if questions and len(questions) == len(do):
            say = questions[0]                      # what the session said it did did not happen: the question did
        return {"kind": "command", "say": say, "done": done, "launch": launch, "ok": ok,
                "usage": {k: (usage or {}).get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens")}}


def canon(item: dict) -> str:
    """A request as the record would recognise it again, for matching a yes to
    the question it answers: everything it carries but its own ids."""
    return json.dumps({k: v for k, v in item.items() if k not in ("op", "confirm")}, sort_keys=True, ensure_ascii=False)


def off() -> dict:
    return {"kind": "command", "say": "Ask is a preview feature, and it is off. Switch it on in System/garrick-flags.json.",
            "done": [], "launch": [], "ok": False}


def reply(say: str, kind: str = "command") -> dict:
    """A reply that did nothing: the line protocol's final line (#261), `kind` always set."""
    return {"kind": kind, "say": say, "done": [], "launch": [], "ok": True}


def clarify(question: str) -> dict:
    """One question about a name or a scope, asked before anything is read or done."""
    return reply(question, "clarify")


# The tags a message is built from: a record's own text never opens or closes one.
_TAGS = re.compile(r"<(?=/?(?:records?|request|earlier-request|workspace|names|today|last-results|correction)\b)", re.I)


def inert(text: str) -> str:
    return _TAGS.sub("&lt;", text)


def attr(value: str) -> str:
    return str(value).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


# ---------------------------------------------------------------- the server


def sock_path(ws: Path) -> Path:
    """One server per workspace, its socket in the jobs folder."""
    return agent().jobs_dir() / ("ask-%s.sock" % hashlib.sha1(str(ws).encode("utf-8")).hexdigest()[:8])


def log(line: str) -> None:
    try:
        folder = agent().jobs_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "ask.log"
        agent().rotate(path)
        with path.open("a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except (OSError, Bad):
        pass


def stop_said(conn) -> Optional[bool]:
    """What came in on a request's connection while it ran: None when the
    client has gone, else whether it said STOP."""
    try:
        data = conn.recv(4096)
    except OSError:
        data = b""
    if not data:
        return None
    said = False
    for line in data.splitlines():
        try:
            msg = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            continue
        said = said or (isinstance(msg, dict) and msg.get("stop") is True)
    return said


def request_line(conn) -> bytes:
    """The request, its first line. Read a byte at a time, so a STOP sent
    straight after it stays on the connection for the turn to hear."""
    got = bytearray()
    while len(got) < 64 * 1024:
        b = conn.recv(1)
        if not b or b == b"\n":
            break
        got += b
    return bytes(got)


def log_line(request: str, out: dict) -> str:
    """ask.log's line for one request: the op, the kind of reply, whether a
    wall reset ran, the milliseconds and the tokens. No request or answer
    text, since an answer carries what the records say, unless LOG_TEXT is 1."""
    line = "ask %s%s%s %d ms %s" % (out.get("kind", "-"), " reset" if out.get("reset") else "",
                                    "" if out.get("ok", True) else " not ok", out.get("ms", 0),
                                    json.dumps(out.get("usage", {})))
    if os.environ.get(LOG_TEXT) == "1":
        line += "  %s  ->  %s %s" % (json.dumps(request[:200], ensure_ascii=False),
                                     json.dumps(out.get("say", ""), ensure_ascii=False),
                                     json.dumps(out.get("done", []), ensure_ascii=False))
    return line


def send(conn, out: dict) -> None:
    """The answer, to a client that may have gone: a closed or stuck
    connection costs that answer, never the server."""
    try:
        conn.settimeout(SEND_TIMEOUT)
        conn.sendall((json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8"))
    except OSError:
        pass


def serve(ws: Path) -> None:
    """The server, unless another holds the workspace's lock: then it has
    started, or is on its way out, and this one leaves its socket alone."""
    path = sock_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    pa = page_action()
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(pa.held(path.with_suffix(".lock").name, wait=SERVE_WAIT))
        except pa.Refused:
            return
        serve_locked(ws, path)


def serve_locked(ws: Path, path: Path) -> None:
    have = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    os.environ["PATH"] = os.pathsep.join(have + [os.path.expanduser(p) for p in EXTRA_PATH if os.path.expanduser(p) not in have])
    # Every process started from here is the app's background session: marked,
    # so the hooks stay quiet, and out of reach of the cmux tab or the session
    # this server may have been started from.
    os.environ[MARKER] = "ask"
    for k in [k for k in os.environ if k == "CLAUDECODE" or k.startswith("CMUX_")]:
        del os.environ[k]
    if path.exists():                           # a server that died without taking it away
        path.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o077)
    try:
        srv.bind(str(path))
    finally:
        os.umask(old)
    mine = path.stat().st_ino
    srv.listen(8)
    asker = Asker(ws)
    last = time.time()
    leased = None                               # when the app last sent `keep`
    kept = False                                # whether a dead session is started again
    try:
        while True:
            if leased is not None:
                if time.time() - leased > LEASE:   # the app has gone without a word
                    log("lease lapsed; stopped")
                    break
            elif time.time() - last >= CLEAR_AFTER:
                break
            if kept and asker.session is not None and asker.session.started and not asker.session.alive():
                # Once between keeps: a CLI that dies as it starts is not started
                # again every tick, and the app's next keep tries again.
                kept = False
                try:
                    if asker.revive():
                        log("session restarted")
                except Bad as e:
                    log("session not restarted: %s" % e)
            srv.settimeout(TICK if leased is not None else IDLE_TICK)
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            last = time.time()
            with conn:
                conn.settimeout(5)
                try:
                    msg = json.loads(request_line(conn).decode("utf-8", "replace") or "{}")
                except (ValueError, OSError):
                    continue
                if not isinstance(msg, dict):
                    continue
                conn.settimeout(None)
                op, t0 = msg.get("op"), time.time()
                try:
                    if op == "ask":
                        # This connection only: its progress lines, and its STOP heard mid-turn.
                        if asker.session is None and flag_on(ws):
                            asker.session = session_for(ws)
                        if asker.session is not None:
                            asker.session.watch = conn
                        asker.progress = lambda text, c=conn: send(c, {"progress": str(text)})
                        try:
                            out = asker.ask(str(msg.get("text", "")))
                        finally:
                            asker.progress = lambda text: None
                            if asker.session is not None:
                                asker.session.watch = None
                    elif op == "warm":
                        if asker.session is None:
                            asker.session = session_for(ws)
                        asker.session.ready()
                        out = {"say": "Ready."}
                    elif op == "keep":
                        if asker.session is None:
                            asker.session = session_for(ws)
                        leased, kept = time.time(), True
                        before = asker.session.started
                        if asker.revive() and before:
                            log("session restarted")
                        out = {"say": "Kept.", "leased": True}
                    elif op == "reset":
                        asker.reset()
                        out = {"say": "A fresh conversation."}
                    elif op == "status":
                        s = asker.session
                        out = {"pid": os.getpid(), "session": bool(s and s.alive()), "turns": s.turns if s else 0,
                               "age_min": round((time.time() - s.started) / 60) if s and s.alive() else None,
                               "leased": leased is not None}
                    elif op == "stop":
                        path.unlink()
                        send(conn, {"say": "Stopped."})
                        break
                    else:
                        out = {"say": "Unknown op %r." % (op,), "ok": False}
                except Stopped:
                    asker.results, asker.asked = "", {}     # said to a process that is gone
                    out = {"kind": "command", "say": STOPPED, "done": [], "launch": [], "ok": False, "stopped": True}
                except Bad as e:
                    out = {"say": "That did not work: %s." % e, "done": [], "launch": [], "ok": False, "failed": True}
                except Exception as e:  # a bug must still say so, and the server carry on
                    out = {"say": "Something went wrong: %s: %s." % (type(e).__name__, e), "done": [], "launch": [], "ok": False,
                           "failed": True}
                if out.get("kind") not in KINDS:
                    out["kind"] = "command"
                out["ms"] = round((time.time() - t0) * 1000)
                if op == "ask":
                    log(log_line(str(msg.get("text", "")), out))
                send(conn, out)
    finally:
        asker.stop()
        srv.close()
        try:
            if path.stat().st_ino == mine:      # never the socket of a server started since
                path.unlink()
        except FileNotFoundError:
            pass


def how_long(seconds: float) -> str:
    """A length of time as page_action.how_long() says it, so the box and the
    page read the same. Said, never printed as a number of seconds."""
    return "%d minutes" % round(seconds / 60) if seconds >= 120 else "%d s" % round(seconds)


@contextlib.contextmanager
def stop_on_interrupt(conn):
    """While a request waits, an interrupt (Ctrl-C, or the app's Stop, which
    sends SIGINT) says STOP on its connection, once, and the wait goes on for
    the final line, which says what stopped. Only the main thread can hear one."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    said = []

    def heard(signum, frame):
        if not said:
            said.append(True)
            try:
                conn.sendall(STOP)
            except OSError:
                pass
    old = signal.signal(signal.SIGINT, heard)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old)


def call(ws: Path, op: str, text: str = "", start: bool = True, progress=None) -> Optional[dict]:
    """One op to the workspace's server, starting it first if asked and needed:
    its final line, each progress line before it handed to `progress`."""
    path = sock_path(ws)
    for attempt in range(100):
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            c.connect(str(path))
            break
        except (FileNotFoundError, ConnectionRefusedError):
            c.close()
            if not start:
                return None
            if attempt == 0:
                subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--workspace", str(ws), "serve"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            time.sleep(0.1)
    else:
        return {"say": "The ask server did not start.", "ok": False}
    reply, heard = None, False
    with c, (stop_on_interrupt(c) if op == "ask" else contextlib.ExitStack()):
        until = time.time() + ASK_WAIT         # the whole wait, however many lines come in it
        try:
            c.settimeout(ASK_WAIT)
            c.sendall((json.dumps({"op": op, "text": text}) + "\n").encode("utf-8"))
            lines = c.makefile("rb")
            while reply is None:
                c.settimeout(max(0.05, until - time.time()))
                raw = lines.readline()
                if not raw:
                    break
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if isinstance(msg, dict) and "kind" not in msg and isinstance(msg.get("progress"), str):
                    heard = True
                    if progress is not None:
                        progress(msg["progress"])
                    continue
                reply = msg if isinstance(msg, dict) else {}
        except socket.timeout:
            return {"say": GAVE_UP % how_long(ASK_WAIT), "ok": False}
        except OSError:
            pass
    if reply is None and heard:                 # it was working on it: never asked a second time
        return {"say": "The ask server stopped before it answered.", "ok": False, "failed": True}
    if reply is None and start and op != "stop":     # reached a server on its way out
        time.sleep(0.3)
        return call(ws, op, text, start, progress)
    return reply or {}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="The status app's ask box: a request in plain words, answered and acted on.")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--json", action="store_true", help="print the answer as JSON lines, each as it comes, for the app")
    ap.add_argument("--list", action="store_true", help="print the workspace list the session is given")
    ap.add_argument("op", nargs="?", choices=("ask", "warm", "keep", "reset", "stop", "status", "serve"))
    ap.add_argument("words", nargs="*")
    args = ap.parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve()
    if not (ws / "System" / "rules.md").is_file() or not (ws / "Zones").is_dir():
        out = {"say": "Not a Garrick workspace.", "ok": False}
    elif args.list:
        print(render(scan(ws)))
        return 0
    elif args.op == "serve":
        serve(ws)
        return 0
    elif args.op == "keep" and not flag_on(ws):
        try:
            call(ws, "stop", start=False)       # switched off: the app's next keep frees the process
        except Bad:
            pass
        out = off()
    elif args.op in ("ask", "warm") and not flag_on(ws):
        out = off()
    else:
        try:
            if args.op == "ask":
                text = " ".join(args.words).strip()
                said = (lambda line: print(json.dumps({"progress": line}, ensure_ascii=False), flush=True)) if args.json else None
                out = call(ws, "ask", text, progress=said) if text else {"say": "Ask what?", "ok": False}
            elif args.op in ("warm", "keep", "reset", "status"):
                out = call(ws, args.op, start=args.op in ("warm", "keep")) or {"say": "Not running."}
            elif args.op == "stop":
                out = call(ws, "stop", start=False) or {"say": "Not running."}
            else:
                ap.print_usage()
                return 2
        except Bad as e:
            out = {"say": "That did not work: %s." % e, "ok": False}
    if args.json or args.op == "status":
        if out.get("kind") not in KINDS:
            out["kind"] = "command"                 # the final line always says what it is
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(out.get("say", ""))
        for m in out.get("done", []):
            print("  " + m)
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
