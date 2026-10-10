#!/usr/bin/env python3
"""ask.py: the ask box. A preview feature, `ask`, off until the workspace
switches it on in System/garrick-flags.json.

    python3 ask.py --workspace ~/Garrick ask "open Pricing in Claude"
    python3 ask.py --workspace ~/Garrick ask --json "park Pricing"   the whole answer, for the app
    python3 ask.py --workspace ~/Garrick warm      start the session, answer nothing
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
("no, the other one") works. A session older than three hours is replaced
before the next request, and the server exits after three hours with nothing
asked of it. Codex has no such mode: each request is one `codex exec`
through agent.py, read-only, given the last few exchanges again.

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
from their frontmatter, sent again only when it has changed. It answers with
JSON (ask-brief.md). Each action is checked against that list, then:

    open       comes back to the app as a folder to open, in an app the
               request named or the user's default; the app checks it again
    park, wake run through page_action.act(), as the page's buttons do: the
    todo-add   status field or the line, committed in the zone's repository

Nothing else: no ticking, no jobs, no settings, nothing sent. What happened
is carried into the next request as `<last-results>`. One line per request
goes in ask.log in the jobs folder, and each action page_action.py runs in
page-actions.log, as from the page.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import select
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
BRIEF = HERE / "ask-brief.md"
JOB = "ask"
FLAG = "ask"
DEFAULT_TIER = "haiku"
CLEAR_AFTER = 3 * 3600      # seconds: a session older than this is replaced, a server idle this long exits
TURN_TIMEOUT = 60           # seconds: a turn that takes longer ends the session
HISTORY = 6                 # exchanges a harness with no warm session is given again
MAX_REQUEST = 2000
GONE = ("done",)
APPS = ("claude", "codex", "cmux", "finder")
VERBS = ("open", "park", "wake", "todo-add")
# The app starts with a bare PATH; an assistant's command line usually lives in one of these.
EXTRA_PATH = ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin")


class Bad(Exception):
    pass


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


def page_action():
    global _PA
    if _PA is None:
        _PA = _load("garrick_page_action", HERE / "page_action.py")
    return _PA


def flag_on(ws: Path) -> bool:
    try:
        data = json.loads((ws / "System" / "garrick-flags.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get(FLAG) is True


def tier() -> str:
    chosen = os.environ.get("GARRICK_ASK_TIER", DEFAULT_TIER).strip().lower() or DEFAULT_TIER
    if chosen not in agent().TIERS:
        raise Bad("GARRICK_ASK_TIER is %r; use %s" % (chosen, ", ".join(agent().TIERS)))
    return chosen


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
        if thread is None:
            if names[zone][project]["threads"]:
                raise Bad("%s has threads: %s one of them" % (project, verb))
            rel = "%s/%s.md" % (project, project)
        else:
            rel = "%s/Threads/%s/%s.md" % (project, thread, thread)
        return "act", {"verb": verb, "zone": zone, "file": rel}
    app = a.get("app") or ""
    if app and app not in APPS:
        raise Bad("no app %r" % (app,))
    folder = ws / "Zones" / zone / project
    if thread is not None:
        folder = folder / "Threads" / thread
    name = spoken(names, zone, project, thread)
    return "launch", {"app": app, "folder": str(folder), "phrase": "open " + name, "name": name}


# ---------------------------------------------------------------- the session


def cost_of(event: dict) -> Optional[float]:
    v = event.get("total_cost_usd")
    return float(v) if isinstance(v, (int, float)) else None


class ClaudeSession:
    """One `claude -p` kept open in stream-json mode, every turn counted against agent.py's caps."""

    remembers = True

    def __init__(self, ws: Path, tier_: str):
        self.ws, self.tier = ws, tier_
        self.proc = None
        self.pending = b""          # what was read past the last whole line
        self.started = 0.0
        self.turns = 0
        self.spent = 0.0            # what the session has cost so far, as Claude reports it

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.alive():
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        self.proc, self.turns, self.spent, self.pending = None, 0, 0.0, b""

    def command(self) -> List[str]:
        a = agent()
        problem = a.profile_problem(a.PROFILE)
        if problem:
            raise Bad("the deny profile %s %s, so nothing was asked" % (a.PROFILE.name, problem))
        cmd = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--model", self.tier, "--tools", "", "--strict-mcp-config", "--no-session-persistence",
               "--permission-mode", "default", "--settings", str(a.PROFILE), "--setting-sources", "user,project",
               "--system-prompt", BRIEF.read_text(encoding="utf-8")]
        budget = a._number("GARRICK_MAX_CALL_USD", a.DEFAULT_MAX_CALL_USD)
        if budget > 0:
            cmd += ["--max-budget-usd", "%g" % budget]
        return cmd

    def start(self) -> None:
        self.stop()
        cmd = self.command()
        try:
            self.proc = subprocess.Popen(cmd, cwd=str(self.ws), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL)
        except FileNotFoundError:
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
        line already read along with the one before is never waited for."""
        fd = self.proc.stdout.fileno()
        while b"\n" not in self.pending:
            ready, _, _ = select.select([fd], [], [], max(0.0, deadline - time.time()))
            if not ready:
                self.stop()
                raise Bad("the session took too long and was stopped; ask again")
            chunk = os.read(fd, 65536)
            if not chunk:
                self.stop()
                raise Bad("the session ended; the next request starts a new one")
            self.pending += chunk
        line, self.pending = self.pending.split(b"\n", 1)
        return line.decode("utf-8", "replace")

    def turn(self, text: str) -> Tuple[str, dict]:
        """One message and its result: (text, usage). Refused, calling nothing, past a cap."""
        a = agent()
        ledger, now = a.ledger_path(), time.time()
        reason = a.cap_reason(a.read_ledger(ledger, now), now, a.caps())
        if reason:
            a.append_ledger(ledger, a.ledger_entry(now, JOB, self.tier, {}, 0, a.EXIT_CAP, refused=reason))
            raise Bad("not asked: %s. Raise GARRICK_CAP_* or wait" % reason)
        self.ready()
        start = time.time()
        self.proc.stdin.write((json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        while True:
            line = self.line(start + TURN_TIMEOUT)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                break
        self.turns += 1
        # The cost Claude reports runs for the whole session; the ledger wants this request's.
        total = cost_of(event)
        cost = None if total is None else (total - self.spent if total >= self.spent else total)
        if total is not None:
            self.spent = total
        denied = sorted({d.get("tool_name") for d in event.get("permission_denials") or [] if isinstance(d, dict)} - {None})
        code = 1 if event.get("is_error") else 0
        a.append_ledger(ledger, a.ledger_entry(start, JOB, self.tier, {"turns": event.get("num_turns"), "cost_usd": cost,
                                                                       "denied": denied, "subtype": event.get("subtype")},
                                               time.time() - start, code))
        if code:
            raise Bad("the assistant reported an error: %s" % (event.get("subtype") or "unknown"))
        return event.get("result") or "", event.get("usage") or {}


class OnceSession:
    """A harness with no warm session: one agent.py call per request,
    read-only, with the last few exchanges given again."""

    remembers = False

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

    def turn(self, text: str) -> Tuple[str, dict]:
        self.ready()
        before = "".join("<earlier-request>\n%s\n</earlier-request>\n<earlier-answer>\n%s\n</earlier-answer>\n" % h
                         for h in self.history[-HISTORY:])
        prompt = BRIEF.read_text(encoding="utf-8") + "\n\n" + before + text
        code, out = agent().run(self.tier, prompt, allow=(), cwd=self.ws, job=JOB)
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


class Asker:
    def __init__(self, ws: Path, session=None):
        self.ws = ws
        self.session = session
        self.sent = None            # the hash of the list the session was last given
        self.results = ""           # what the last actions did, for the next turn

    def ask(self, request: str, today: Optional[dt.date] = None) -> dict:
        if not flag_on(self.ws):
            return off()
        if self.session is None:
            self.session = session_for(self.ws)
        names = scan(self.ws)
        listing = render(names)
        sent = hashlib.sha1(listing.encode("utf-8")).hexdigest()
        parts = ["<today>%s</today>" % (today or dt.date.today()).isoformat(),
                 "<workspace>\n%s\n</workspace>" % listing if sent != self.sent or self.session.fresh()
                 else "<workspace unchanged/>"]
        if self.results:
            parts.append("<last-results>\n%s\n</last-results>" % self.results)
        parts.append("<request>\n%s\n</request>" % request[:MAX_REQUEST])
        text, usage = self.session.turn("\n".join(parts))
        self.sent = sent
        say, do = parse(text)
        if not do and re.search(r"\balready open", say, re.I) and self.session.remembers:
            # It cannot know what is open; the brief says so, and this holds it to that once more.
            text, usage = self.session.turn("<correction>You cannot know what is open. Send the open action for "
                                            "the request above; never answer \"already open\".</correction>")
            say, do = parse(text)
        return self.carry_out(say, do, names, usage)

    def carry_out(self, say: str, do: list, names, usage=None) -> dict:
        pa = page_action()
        done, launch, ok = [], [], True
        for a in do:
            try:
                kind, item = proposal(a, names, self.ws)
            except Bad as e:
                done.append("Refused: %s" % e)
                ok = False
                continue
            if kind == "launch":
                launch.append(item)
                done.append("Opening %s%s" % (item["name"], " in " + item["app"].capitalize() if item["app"] else ""))
                continue
            try:
                said, good = pa.act(self.ws, item), True
            except pa.Refused as e:
                said, good = str(e), False
            pa.audit(item, good, said, via="ask")
            done.append(said if good else "Refused: " + said)
            ok = ok and good
        self.results = "\n".join(done)
        return {"say": say, "done": done, "launch": launch, "ok": ok,
                "usage": {k: (usage or {}).get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens")}}


def off() -> dict:
    return {"say": "Ask is a preview feature, and it is off. Switch it on in System/garrick-flags.json.",
            "done": [], "launch": [], "ok": False}


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


def serve(ws: Path) -> None:
    have = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    os.environ["PATH"] = os.pathsep.join(have + [os.path.expanduser(p) for p in EXTRA_PATH if os.path.expanduser(p) not in have])
    path = sock_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o077)
    try:
        srv.bind(str(path))
    finally:
        os.umask(old)
    mine = path.stat().st_ino
    srv.listen(8)
    srv.settimeout(60)
    asker = Asker(ws)
    last = time.time()
    try:
        while time.time() - last < CLEAR_AFTER:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            last = time.time()
            with conn:
                conn.settimeout(5)
                try:
                    msg = json.loads(conn.makefile(encoding="utf-8").readline() or "{}")
                except (ValueError, socket.timeout):
                    continue
                conn.settimeout(None)
                op, t0 = msg.get("op"), time.time()
                try:
                    if op == "ask":
                        out = asker.ask(str(msg.get("text", "")))
                    elif op == "warm":
                        if asker.session is None:
                            asker.session = session_for(ws)
                        asker.session.ready()
                        out = {"say": "Ready."}
                    elif op == "reset":
                        if asker.session is not None:
                            asker.session.start()
                        asker.results = ""
                        out = {"say": "A fresh conversation."}
                    elif op == "status":
                        s = asker.session
                        out = {"pid": os.getpid(), "session": bool(s and s.alive()), "turns": s.turns if s else 0,
                               "age_min": round((time.time() - s.started) / 60) if s and s.alive() else None}
                    elif op == "stop":
                        path.unlink()
                        conn.sendall((json.dumps({"say": "Stopped."}) + "\n").encode("utf-8"))
                        break
                    else:
                        out = {"say": "Unknown op %r." % (op,), "ok": False}
                except Bad as e:
                    out = {"say": "That did not work: %s." % e, "done": [], "launch": [], "ok": False}
                except Exception as e:  # a bug must still say so, and the server carry on
                    out = {"say": "Something went wrong: %s: %s." % (type(e).__name__, e), "done": [], "launch": [], "ok": False}
                out["ms"] = round((time.time() - t0) * 1000)
                if op == "ask":
                    log("%s  ->  %s %s %d ms %s" % (json.dumps(str(msg.get("text", ""))[:200], ensure_ascii=False),
                                                  json.dumps(out.get("say", ""), ensure_ascii=False),
                                                  json.dumps(out.get("done", []), ensure_ascii=False), out["ms"],
                                                  json.dumps(out.get("usage", {}))))
                conn.sendall((json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        if asker.session is not None:
            asker.session.stop()
        srv.close()
        try:
            if path.stat().st_ino == mine:      # never the socket of a server started since
                path.unlink()
        except FileNotFoundError:
            pass


def call(ws: Path, op: str, text: str = "", start: bool = True) -> Optional[dict]:
    """One op to the workspace's server, starting it first if asked and needed."""
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
    with c:
        c.sendall((json.dumps({"op": op, "text": text}) + "\n").encode("utf-8"))
        reply = c.makefile(encoding="utf-8").readline()
    if not reply and start and op != "stop":     # reached a server on its way out
        time.sleep(0.3)
        return call(ws, op, text, start)
    return json.loads(reply or "{}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="The status app's ask box: a request in plain words, answered and acted on.")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--json", action="store_true", help="print the whole answer as JSON, for the app")
    ap.add_argument("--list", action="store_true", help="print the workspace list the session is given")
    ap.add_argument("op", nargs="?", choices=("ask", "warm", "reset", "stop", "status", "serve"))
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
    elif args.op in ("ask", "warm") and not flag_on(ws):
        out = off()
    else:
        try:
            if args.op == "ask":
                text = " ".join(args.words).strip()
                out = call(ws, "ask", text) if text else {"say": "Ask what?", "ok": False}
            elif args.op in ("warm", "reset", "status"):
                out = call(ws, args.op, start=args.op == "warm") or {"say": "Not running."}
            elif args.op == "stop":
                out = call(ws, "stop", start=False) or {"say": "Not running."}
            else:
                ap.print_usage()
                return 2
        except Bad as e:
            out = {"say": "That did not work: %s." % e, "ok": False}
    if args.json or args.op == "status":
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(out.get("say", ""))
        for m in out.get("done", []):
            print("  " + m)
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
