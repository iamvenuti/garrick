#!/usr/bin/env python3
"""notifications.py: the one way Garrick tells you something.

    python3 System/tools/notifications.py send <event> <title> <message> [--zone Work]
    python3 System/tools/notifications.py test <mac|cmux>
    python3 System/tools/notifications.py flush        send what quiet hours held, if they are over
    python3 System/tools/notifications.py hook         what an assistant's hook runs, its event on stdin
    python3 System/tools/notifications.py hooks [--install | --uninstall]   Needs you and Finished, for Claude Code and Codex

Every sender calls send(): the scheduled jobs (job.py), the todo sweep, the
cmux desk, and the session hooks. Notices go to this Mac and nowhere else
(#227). Which ones is set on the status page, Settings › Notifications, and
kept under `notifications` in System/garrick-settings.json, committed with
the workspace:

    {"tell": {"needs-you": true, "finished": true, "todo-summary": true, "job-failed": true},
     "after": 2,
     "quiet": {"on": true, "from": "22:00", "to": "07:00"}}

**Events** (EVENTS) are what happened. Settings offers four of them (TELL),
each on or off, and the minutes a turn must run before Finished is sent.
Job idle and the Desk (FOLLOW) are sent whenever any of the four is on, so
four boxes left empty mean no notice at all; Todo refreshed is never sent.

A notice from a session running in cmux lands on that session's own tab,
through cmux's own notification; anything else, or a cmux that will not
take it, is a notification in the corner of the screen.

**Quiet hours** (22:00 to 07:00 unless set otherwise) hold each event to its
choice in QUIET: Needs you and the Desk are sent anyway, Finished is
dropped, the rest are held for the morning. A held notice goes out with the
first notice, flush or session prompt after the quiet hours end.

**What a notice says** is short and plain: the zone or thread, what
happened, never the content of a note or a meeting. Finished says only
that a session is done, in which thread and after how long.

**An override.** GARRICK_NOTIFY=1 or GARRICK_NOTIFY_CMD in a sender's
environment, as a job's launchd plist may set them, keep working exactly as
before for that sender, and these settings do not apply to it. Settings no
longer offers a command of its own; GARRICK_NOTIFY_CMD is how to run one.

**Older settings.** Keys an older Garrick saved here (`channels`,
`telegram`, `command`, `zones`, and each event's `to`, `quiet` and `away`)
are read only for what still means something: an event that went to this
Mac is on, and this Mac switched off turns every event off. The rest is
ignored, and goes the next time Settings saves.

**The hooks.** `hooks --install` adds this file's `hook` to Claude Code's
UserPromptSubmit, Notification and Stop events (~/.claude/settings.json),
and to Codex's UserPromptSubmit and Stop (~/.codex/hooks.json): Codex has no
event for a session waiting on you. The prompt marks when a turn began, so
Finished can wait for a turn longer than the set minutes. A hook never
blocks the session: it answers nothing, sends from a process of its own,
and does nothing for a session outside this workspace or for a headless job
(GARRICK_HEADLESS=1).

What it keeps for itself, never committed, is in
System/generated/notifications/: the notices quiet hours hold, and when each
session's turn began.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent

SETTINGS = ("System", "garrick-settings.json")      # garrick_lib.SETTINGS; a test keeps the two in step
KEY = "notifications"
STATE = ("System", "generated", "notifications")

# (name, label, what it is).
EVENTS = (
    ("needs-you", "Needs you", "A session is waiting: a permission to give, a question, an idle prompt"),
    ("finished", "Finished", "A session has ended its turn, after running longer than the minutes set"),
    ("todo-refreshed", "Todo refreshed", "The nightly sweep has run: lines added, folded, expired"),
    ("todo-summary", "Todo summary", "Each zone's morning digest from the sweep: what is late and what is due today"),
    ("job-failed", "Job failed or recovered", "A scheduled job fails or works again, and a line a job sends of its own"),
    ("job-idle", "Job idle", "A job has run cleanly but done nothing for days"),
    ("desk", "Desk", "The cmux desk starting the day or shutting down"),
)
EVENT_NAMES = tuple(e[0] for e in EVENTS)
LABELS = {e[0]: e[1] for e in EVENTS}
SESSION_EVENTS = ("needs-you", "finished")       # from a session: cmux takes the Mac's place
# What Settings offers, in its order and its words: each event on or off.
TELL = (("needs-you", "a session needs me"), ("finished", "a long task finishes"),
        ("todo-summary", "the morning Todo summary is ready"), ("job-failed", "a scheduled job fails"))
TELL_NAMES = tuple(e for e, _ in TELL)
FOLLOW = ("job-idle", "desk")                    # sent while any of TELL is on
QUIET_CHOICES = ("send", "hold", "drop")
QUIET = {"needs-you": "send", "finished": "drop", "todo-refreshed": "hold", "todo-summary": "hold",
         "job-failed": "hold", "job-idle": "hold", "desk": "send"}
# job.py's kinds, as GARRICK_NOTIFY_KIND has always carried them, and the event each is.
KINDS = {"failed": "job-failed", "recovered": "job-failed", "message": "job-failed", "idle": "job-idle",
         "digest": "todo-summary", "refreshed": "todo-refreshed"}
AFTER = 2
AFTER_MAX = 240
CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
HELD_MAX = 50
HELD_HOURS = 24
TURN_DAYS = 2
TIMEOUT = 8            # seconds a channel may take: cmux, osascript
COMMAND_TIMEOUT = 60   # what job.py has always given a notifier
CMUX_APPS = ("/Applications/cmux.app/Contents/Resources/bin/cmux", "~/Applications/cmux.app/Contents/Resources/bin/cmux")
HOOK_TIMEOUT = 10
CLAUDE_HOOKS = ("UserPromptSubmit", "Notification", "Stop")
CODEX_HOOKS = ("UserPromptSubmit", "Stop")       # Codex has no event for a session waiting on you

# The way out, as a module attribute, so a test puts a fake in its place and
# nothing reaches this Mac's notifications.
_run = subprocess.run


# --------------------------------------------------------------------------- where

def is_workspace(folder: Path) -> bool:
    return (folder / "System" / "rules.md").is_file() and (folder / "Zones").is_dir()


def workspace(root=None, env=None) -> Optional[Path]:
    """The workspace whose settings apply: the one given, else
    GARRICK_WORKSPACE, else the one this file is installed in. None when
    none of them is one, as for a Garrick clone's template."""
    env = os.environ if env is None else env
    for candidate in (root, env.get("GARRICK_WORKSPACE"), HERE.parent.parent):
        if candidate and is_workspace(Path(candidate).expanduser()):
            return Path(candidate).expanduser().resolve()
    return None


def state_dir(ws: Path) -> Path:
    return ws.joinpath(*STATE)


# --------------------------------------------------------------------------- settings

def saved(ws: Path) -> object:
    """What the settings file holds under `notifications`, as it is."""
    try:
        data = json.loads(ws.joinpath(*SETTINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get(KEY) if isinstance(data, dict) else None


def settings(ws: Path) -> dict:
    """The settings, every part filled in: what was saved where it reads,
    the defaults for the rest. Never raises; an unreadable part is its default."""
    return normal(saved(ws))


def _minutes_ok(a) -> bool:
    return isinstance(a, int) and not isinstance(a, bool) and 0 <= a <= AFTER_MAX


def normal(raw) -> dict:
    """{"tell": {event: on}, "after": minutes, "quiet": {"on", "from", "to"}},
    from what was saved, in this shape or an older Garrick's."""
    raw = raw if isinstance(raw, dict) else {}
    given = raw.get("tell") if isinstance(raw.get("tell"), dict) else None
    events = raw.get("events") if isinstance(raw.get("events"), dict) else {}
    if given is not None:
        tell = {e: given.get(e, True) is not False for e in TELL_NAMES}
    else:                                       # an older Garrick's: an event that went to this Mac is on
        ch = raw.get("channels") if isinstance(raw.get("channels"), dict) else {}
        mac = ch.get("mac", True) is not False
        tell = {}
        for e in TELL_NAMES:
            g = events.get(e) if isinstance(events.get(e), dict) else {}
            to = g.get("to") if isinstance(g.get("to"), list) else ["mac"]
            tell[e] = mac and "mac" in to
    after = raw.get("after")
    if not _minutes_ok(after):
        old = events.get("finished") if isinstance(events.get("finished"), dict) else {}
        after = old.get("after") if _minutes_ok(old.get("after")) else AFTER
    q = raw.get("quiet") if isinstance(raw.get("quiet"), dict) else {}
    quiet = {"on": q.get("on", True) is not False,
             "from": q.get("from") if isinstance(q.get("from"), str) and CLOCK.match(q["from"]) else "22:00",
             "to": q.get("to") if isinstance(q.get("to"), str) and CLOCK.match(q["to"]) else "07:00"}
    return {"tell": tell, "after": after, "quiet": quiet}


class Invalid(ValueError):
    """A setting the page sent that cannot be kept, in words."""


def clean(given) -> dict:
    """The settings as the page sends them, checked strictly, in the shape
    they are saved in. Raises Invalid with the reason."""
    if not isinstance(given, dict):
        raise Invalid("not a set of notification settings")
    unknown = sorted(set(given) - {"tell", "after", "quiet"})
    if unknown:
        raise Invalid("not a notification setting: %s" % ", ".join(unknown))
    tell = given.get("tell", {})
    if not isinstance(tell, dict) or set(tell) - set(TELL_NAMES) or not all(isinstance(v, bool) for v in tell.values()):
        raise Invalid("not a set of notices, each on or off")
    after = given.get("after", AFTER)
    if not _minutes_ok(after):
        raise Invalid("a long task is from 0 to %d minutes" % AFTER_MAX)
    q = given.get("quiet", {})
    if not isinstance(q, dict) or set(q) - {"on", "from", "to"}:
        raise Invalid("not a time for quiet hours")
    if "on" in q and not isinstance(q["on"], bool):
        raise Invalid("quiet hours are on or off")
    for k in ("from", "to"):
        if k in q and not (isinstance(q[k], str) and CLOCK.match(q[k])):
            raise Invalid("quiet hours are times such as 22:00")
    return {"tell": {e: tell.get(e, True) for e in TELL_NAMES}, "after": after,
            "quiet": {"on": q.get("on", True), "from": q.get("from", "22:00"), "to": q.get("to", "07:00")}}


def _garrick_lib(ws: Path):
    """garrick_lib.py, which writes the settings file: the workspace's own, else the one beside this file."""
    import importlib.util
    for src in (ws / "System" / "tools" / "garrick_lib.py", HERE / "garrick_lib.py"):
        if src.is_file():
            spec = importlib.util.spec_from_file_location("garrick_notifications_lib", str(src))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if callable(getattr(mod, "save_preferences", None)):
                return mod
    raise OSError("cannot find System/tools/garrick_lib.py, which keeps the settings")


def keep(ws: Path, cfg: dict) -> dict:
    """Save these settings, checked as the page's are, leaving the rest of
    the settings file as it is. What was saved, in clean()'s shape."""
    out = clean(cfg)
    _garrick_lib(ws).save_preferences(ws, {KEY: out})
    return out


def wanted(cfg: dict, event: str) -> bool:
    """Whether this event is sent at all, as the settings stand."""
    if event in cfg["tell"]:
        return cfg["tell"][event]
    return event in FOLLOW and any(cfg["tell"].values())


# --------------------------------------------------------------------------- the legacy override

def override(env=None) -> Tuple[str, ...]:
    """The variables in force that take a sender past these settings."""
    env = os.environ if env is None else env
    return tuple(k for k in ("GARRICK_NOTIFY", "GARRICK_NOTIFY_CMD")
                 if (env.get(k) == "1" if k == "GARRICK_NOTIFY" else (env.get(k) or "").strip()))


# --------------------------------------------------------------------------- quiet hours

def minutes(clock: str) -> int:
    h, m = clock.split(":")
    return int(h) * 60 + int(m)


def is_quiet(cfg: dict, now: dt.datetime) -> bool:
    q = cfg["quiet"]
    if not q["on"]:
        return False
    start, end, n = minutes(q["from"]), minutes(q["to"]), now.hour * 60 + now.minute
    if start == end:
        return False
    return start <= n < end if start < end else n >= start or n < end


def _held_file(ws: Path) -> Path:
    return state_dir(ws) / "held.json"


def _read_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))


def hold(ws: Path, notice: dict, now: dt.datetime) -> None:
    held = _read_json(_held_file(ws), [])
    held.append(dict(notice, at=now.timestamp()))
    _write_json(_held_file(ws), held[-HELD_MAX:])


def flush(ws: Path, cfg: Optional[dict] = None, now: Optional[dt.datetime] = None, env=None, log=None,
          prefix: str = "notifications") -> int:
    """Send what quiet hours held, once they are over: each whose event is
    still switched on. A notice held longer than HELD_HOURS is let go. How
    many went."""
    path = _held_file(ws)
    if not path.is_file():
        return 0
    cfg = cfg or settings(ws)
    now = now or dt.datetime.now()
    if is_quiet(cfg, now):
        return 0
    held = _read_json(path, [])
    try:
        path.unlink()
    except OSError:
        return 0                # another process took them
    sent = 0
    for n in held:
        if not isinstance(n, dict) or n.get("event") not in EVENT_NAMES:
            continue
        if now.timestamp() - float(n.get("at") or 0) > HELD_HOURS * 3600:
            continue
        if wanted(cfg, n["event"]) and deliver(ws, n, env=env, log=log, prefix=prefix, session=False):
            sent += 1
    return sent


# --------------------------------------------------------------------------- sending

def send(event: str, title: str, message: str, zone: Union[str, Path, None] = None, root=None,
         kind: Optional[str] = None, job: str = "", code: Optional[int] = None, log=None,
         prefix: str = "notifications", now: Optional[dt.datetime] = None, env=None) -> bool:
    """Send one notice to this Mac, if the settings want it. `zone` is a
    zone's name or its folder, which only GARRICK_NOTIFY_CMD is told. `log`,
    a file open for writing, gets a line when it failed; a failure never
    raises. True when it went, or was held for after quiet hours."""
    if event in KINDS and event not in EVENT_NAMES:
        kind, event = kind or event, KINDS[event]
    if event not in EVENT_NAMES:
        raise ValueError("not an event Garrick sends: %r" % (event,))
    env = os.environ if env is None else env
    zone_dir = zone if isinstance(zone, Path) else None
    zone_name = zone.name if isinstance(zone, Path) else zone
    notice = {"event": event, "kind": kind or event, "title": title, "message": message, "zone": zone_name,
              "job": job or env.get("GARRICK_JOB", ""), "code": code}
    if override(env):
        return legacy(notice, zone_dir, env, log, prefix)
    ws = workspace(root, env)
    if ws is None:
        return False
    cfg = settings(ws)
    now = now or dt.datetime.now()
    try:
        flush(ws, cfg, now, env, log, prefix)
    except Exception:
        pass                    # what was held waits for the next one
    if not wanted(cfg, event):
        return False
    if is_quiet(cfg, now):
        choice = QUIET[event]
        if choice == "drop":
            return False
        if choice == "hold":
            try:
                hold(ws, notice, now)
                return True
            except OSError:
                return False
    return deliver(ws, notice, env=env, log=log, prefix=prefix, session=event in SESSION_EVENTS)


def deliver(ws: Path, notice: dict, env=None, log=None, prefix: str = "notifications", session: bool = False) -> bool:
    """To this Mac: on a session's own cmux tab when it runs in cmux, else the Mac's own."""
    problem = local(notice["title"], notice["message"], env, cmux=session)
    if problem:
        say(log, "%s: this Mac %s" % (prefix, problem))
    return not problem


def legacy(notice: dict, zone_dir: Optional[Path], env, log, prefix: str) -> bool:
    """GARRICK_NOTIFY=1 and GARRICK_NOTIFY_CMD, as job.py has always read them."""
    sent = False
    if env.get("GARRICK_NOTIFY") == "1" and sys.platform == "darwin":
        mac(notice["title"], notice["message"])
        sent = True
    cmd = (env.get("GARRICK_NOTIFY_CMD") or "").strip()
    if cmd:
        sent = True
        problem = command(cmd, notice, zone_dir, env)
        if problem:
            say(log, "%s: the notifier %s" % (prefix, problem))
    return sent


def say(log, line: str) -> None:
    if log is not None:
        log.write(line + "\n")
    else:
        sys.stderr.write(line + "\n")


# --------------------------------------------------------------------------- the channels

def mac(title: str, message: str) -> str:
    if sys.platform != "darwin":
        return "is only on a Mac"
    try:
        r = _run(["osascript", "-e", "on run argv", "-e",
                  'display notification (item 1 of argv) with title "Garrick" subtitle (item 2 of argv)',
                  "-e", "end run", message, title], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "did not answer: %s" % type(e).__name__
    return "" if r.returncode == 0 else "said no: %s" % ((r.stderr or "").strip().splitlines() or ["exit %d" % r.returncode])[-1]


def cmux_binary(env=None) -> Optional[str]:
    env = os.environ if env is None else env
    for named in (env.get("GARRICK_CMUX"), env.get("CMUX_BUNDLED_CLI_PATH")):
        if named:
            p = Path(named).expanduser()
            if p.is_file() and os.access(str(p), os.X_OK):
                return str(p)
    found = shutil.which("cmux", path=env.get("PATH"))
    if found:
        return found
    for candidate in CMUX_APPS:
        p = Path(candidate).expanduser()
        if p.is_file() and os.access(str(p), os.X_OK):
            return str(p)
    return None


def in_cmux(env=None) -> bool:
    env = os.environ if env is None else env
    return bool(env.get("CMUX_SURFACE_ID")) and cmux_binary(env) is not None


def local(title: str, message: str, env=None, cmux: bool = False) -> str:
    """This Mac: cmux's notification on the session's own tab, for a session
    in cmux, else the Mac's own. A cmux that will not take it falls back to
    the Mac's."""
    env = os.environ if env is None else env
    if cmux and in_cmux(env):
        try:
            r = _run([cmux_binary(env), "notify", "--title", "Garrick", "--subtitle", title, "--body", message],
                     capture_output=True, text=True, timeout=TIMEOUT, env=dict(env), stdin=subprocess.DEVNULL)
            if r.returncode == 0:
                return ""
        except (OSError, subprocess.TimeoutExpired):
            pass
    return mac(title, message)


def command(cmd: str, notice: dict, zone_dir: Optional[Path], env=None) -> str:
    """Run a command of yours with the title and the message, as
    GARRICK_NOTIFY_CMD has always been run. "" when it worked, else why not."""
    env = os.environ if env is None else env
    run_env = dict(env, GARRICK_NOTIFY_KIND=notice.get("kind") or notice["event"], GARRICK_NOTIFY_EVENT=notice["event"],
                   GARRICK_JOB=notice.get("job") or env.get("GARRICK_JOB", ""),
                   GARRICK_EXIT="" if notice.get("code") is None else str(notice["code"]))
    if zone_dir is not None:
        run_env.update(GARRICK_ZONE=zone_dir.name, GARRICK_ZONE_DIR=str(zone_dir))
    elif notice.get("zone"):
        run_env.update(GARRICK_ZONE=notice["zone"])
    try:
        r = _run(shlex.split(cmd) + [notice["title"], notice["message"]], env=run_env, capture_output=True, text=True,
                 stdin=subprocess.DEVNULL, timeout=COMMAND_TIMEOUT, cwd=str(zone_dir) if zone_dir is not None else None)
    except (OSError, ValueError) as exc:
        return "could not start: %s" % exc
    except subprocess.TimeoutExpired:
        return "took longer than %ds and was stopped" % COMMAND_TIMEOUT
    if r.returncode:
        output = ((r.stdout or "") + (r.stderr or "")).strip()
        return "exited %d%s" % (r.returncode, (": " + output.splitlines()[-1]) if output else "")
    return ""


# --------------------------------------------------------------------------- a test

def test(channel: str, env=None) -> str:
    """Send a test, whatever the settings and quiet hours say: to this Mac,
    or (`cmux`) to the cmux tab this runs in. "" when it went, else why not."""
    env = os.environ if env is None else env
    title, message = "Test", "A test from Garrick. Notices will look like this."
    if channel == "mac":
        return mac(title, message)
    if channel == "cmux":
        if not in_cmux(env):
            return "runs only from a session inside cmux"
        return local(title, message, env, cmux=True)
    return "is not a channel"


# --------------------------------------------------------------------------- the session hooks

def place(ws: Path, cwd: str) -> Optional[Tuple[str, Optional[str]]]:
    """(what to call where a session runs, its zone) or None outside the workspace."""
    try:
        rel = Path(cwd).resolve().relative_to(ws.resolve())
    except (ValueError, OSError):
        return None
    parts = rel.parts
    if not parts:
        return ("The workspace", None)
    if parts[0] == "Zones" and len(parts) >= 2:
        zone = parts[1]
        if len(parts) >= 5 and parts[3] == "Threads":
            return ("%s, %s" % (zone, parts[4]), zone)
        if len(parts) >= 3 and not parts[2].startswith((".", "_")) and parts[2] not in ("Inbox", "archive"):
            return ("%s, %s" % (zone, parts[2]), zone)
        return (zone, zone)
    if parts[0] == "Wikis" and len(parts) >= 2:
        return (parts[1], None)
    return (parts[0], None)


def waiting_for(payload: dict) -> Optional[str]:
    """What a session waits for, in a few words of our own: never the
    assistant's message, which may quote a file or a command. None for a
    notification that is not a wait, such as a sign-in that went through."""
    kind = str(payload.get("notification_type") or "")
    if kind == "auth_success":
        return None
    text = str(payload.get("message") or "").lower()
    if kind == "permission_prompt" or (not kind and "permission" in text):
        return "Permission asked"
    if kind == "elicitation_dialog":
        return "A question to answer"
    return "Waiting for your answer"


def took(seconds: float) -> str:
    m = int(round(seconds / 60.0))
    if m < 1:
        return "under a minute"
    if m < 60:
        return "a minute" if m == 1 else "%d minutes" % m
    h, r = divmod(m, 60)
    return ("an hour" if h == 1 else "%d hours" % h) + ("" if r < 5 else " %d minutes" % r)


SESSION_ID = re.compile(r"[^A-Za-z0-9_-]")


def _turn_file(ws: Path, session: str) -> Path:
    return state_dir(ws) / "turns" / (SESSION_ID.sub("", session)[:80] or "unnamed")


def hook(payload: dict, ws: Optional[Path] = None, env=None, now: Optional[float] = None, detach: bool = True) -> None:
    """One hook event from Claude Code or Codex. Never raises, never prints."""
    env = os.environ if env is None else env
    if env.get("GARRICK_HEADLESS") == "1" or not isinstance(payload, dict):
        return
    ws = ws or workspace(None, {})          # the workspace this file is in, whatever the session set
    if ws is None:
        return
    where = place(ws, str(payload.get("cwd") or os.getcwd()))
    if where is None:
        return
    label, zone = where
    name = payload.get("hook_event_name") or ""
    session = str(payload.get("session_id") or "")
    now = time.time() if now is None else now
    if name == "UserPromptSubmit":
        if session:
            f = _turn_file(ws, session)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("%f\n" % now, encoding="utf-8")
            prune(f.parent, now)
        cfg = settings(ws)
        if (state_dir(ws) / "held.json").is_file() and not is_quiet(cfg, dt.datetime.fromtimestamp(now)):
            dispatch({"flush": True}, ws, env, detach, now)
        return
    if name == "Notification":
        why = waiting_for(payload)
        if why:
            dispatch({"event": "needs-you", "title": "Needs you",
                      "message": "%s: needs you. %s." % (label, why), "zone": zone}, ws, env, detach, now)
        return
    if name == "Stop":
        if payload.get("stop_hook_active"):
            return
        f = _turn_file(ws, session) if session else None
        try:
            began = float(f.read_text(encoding="utf-8").split()[0]) if f else None
        except (OSError, ValueError, IndexError):
            began = None
        if began is None:
            return                  # a turn this hook did not see begin: not timed, not sent
        try:
            f.unlink()
        except OSError:
            pass
        after = settings(ws)["after"]
        if now - began < after * 60:
            return
        dispatch({"event": "finished", "title": "Finished",
                  "message": "%s: done, after %s." % (label, took(now - began)), "zone": zone}, ws, env, detach, now)


def prune(folder: Path, now: float) -> None:
    """Turns begun over TURN_DAYS ago whose Stop never came."""
    try:
        for f in folder.iterdir():
            if now - f.stat().st_mtime > TURN_DAYS * 86400:
                f.unlink()
    except OSError:
        pass


def dispatch(notice: dict, ws: Path, env, detach: bool, now: Optional[float] = None) -> None:
    """Send from a process of its own, so a slow network never holds the session.
    Sent in this process (`detach` false), quiet hours are judged at `now`, the
    hook's own time; a process of its own judges them when it sends."""
    if not detach:
        at = dt.datetime.fromtimestamp(now) if now is not None else None
        if notice.get("flush"):
            flush(ws, now=at, env=env)
        else:
            send(notice["event"], notice["title"], notice["message"], notice.get("zone"), root=ws, env=env, now=at)
        return
    try:
        p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "deliver", "--workspace", str(ws)],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, env=dict(env))
        p.stdin.write(json.dumps(notice).encode("utf-8"))
        p.stdin.close()
    except OSError:
        pass


# --------------------------------------------------------------------------- installing the hooks

def hook_command(ws: Path) -> str:
    return "python3 %s hook" % shlex.quote(str(ws / "System" / "tools" / "notifications.py"))


def _ours(entry) -> Optional[str]:
    """The notifications.py an entry runs, when it is one of ours."""
    for h in (entry.get("hooks") if isinstance(entry, dict) and isinstance(entry.get("hooks"), list) else []):
        cmd = h.get("command") if isinstance(h, dict) else None
        if isinstance(cmd, str) and cmd.rstrip().endswith(" hook") and "notifications.py" in cmd:
            try:
                return shlex.split(cmd)[1]
            except (ValueError, IndexError):
                return cmd
    return None


def assistants(home: Path) -> Dict[str, Tuple[Path, Tuple[str, ...]]]:
    """The assistants with a folder in `home`: {name: (their hooks file, the events)}."""
    out = {}
    if (home / ".claude").is_dir():
        out["claude"] = (home / ".claude" / "settings.json", CLAUDE_HOOKS)
    if (home / ".codex").is_dir():
        out["codex"] = (home / ".codex" / "hooks.json", CODEX_HOOKS)
    return out


def hooks(ws: Path, home: Optional[Path] = None, install: Optional[bool] = None) -> Dict[str, str]:
    """Each assistant's state, after installing (True), removing (False) or
    only looking (None). An assistant's other hooks are kept as they are; an
    entry of ours whose notifications.py has gone, from a workspace moved
    since, is replaced. Raises ValueError for a file that does not read."""
    home = Path(home) if home is not None else Path.home()
    mine = str(ws / "System" / "tools" / "notifications.py")
    out = {}
    for name, (path, events) in assistants(home).items():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except ValueError:
            raise ValueError("%s does not read as JSON; nothing was changed" % path)
        if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
            raise ValueError("%s has a \"hooks\" that is not an object; nothing was changed" % path)
        table = data.setdefault("hooks", {})
        changed = False
        for event in events:
            entries = table.get(event, [])
            if not isinstance(entries, list):
                raise ValueError("%s has a hooks.%s that is not a list; nothing was changed" % (path, event))
            keep = [e for e in entries if not (_ours(e) and (_ours(e) == mine or not Path(_ours(e)).is_file()))]
            if install:
                keep.append({"hooks": [{"type": "command", "command": hook_command(ws), "timeout": HOOK_TIMEOUT}]})
            if install is not None and keep != entries:
                changed = True
                if keep:
                    table[event] = keep
                else:
                    table.pop(event, None)
        if changed:
            if not table:
                data.pop("hooks", None)
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_pretty(path, data)
        have = [e for e in events if any(_ours(x) == mine for x in (table.get(e) or []))]
        out[name] = ("on, for %s" % ", ".join(have) if len(have) == len(events) else
                     "partly, for %s only" % ", ".join(have) if have else "off")
    return out


def _write_json_pretty(path: Path, data) -> None:
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


# --------------------------------------------------------------------------- the command line

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Send a notice where Settings › Notifications says, or set up what sends one.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send", help="send one notice")
    s.add_argument("event", choices=EVENT_NAMES)
    s.add_argument("title")
    s.add_argument("message")
    s.add_argument("--zone")
    t = sub.add_parser("test", help="send a test to this Mac, or to the cmux tab this runs in")
    t.add_argument("channel", choices=("mac", "cmux"))
    sub.add_parser("flush", help="send what quiet hours held, if they are over")
    sub.add_parser("hook", help="one hook event from Claude Code or Codex, on standard input")
    d = sub.add_parser("deliver")                # the hook's own sender, a notice on standard input
    d.add_argument("--workspace", required=True)
    h = sub.add_parser("hooks", help="the Needs you and Finished hooks for Claude Code and Codex")
    g = h.add_mutually_exclusive_group()
    g.add_argument("--install", action="store_true")
    g.add_argument("--uninstall", action="store_true")
    for p in (s, t, h, sub.choices["flush"]):
        p.add_argument("--root", help="the workspace; default the one this file is in, or GARRICK_WORKSPACE")
    a = ap.parse_args(argv)

    if a.cmd == "hook":
        try:
            payload = json.loads(sys.stdin.read() or "{}")
            hook(payload)
        except Exception:
            pass                # a hook never stops a session
        return 0
    if a.cmd == "deliver":
        try:
            notice = json.loads(sys.stdin.read() or "{}")
            ws = Path(a.workspace)
            if notice.get("flush"):
                flush(ws)
            else:
                send(notice["event"], notice["title"], notice["message"], notice.get("zone"), root=ws)
        except Exception:
            pass
        return 0
    ws = workspace(a.root)
    if ws is None:
        print("notifications: no workspace here; pass --root or set GARRICK_WORKSPACE", file=sys.stderr)
        return 64
    if a.cmd == "send":
        went = send(a.event, a.title, a.message, a.zone, root=ws)
        if not went:
            print("notifications: nothing sent: %s%s is switched off, or it is quiet hours"
                  % (LABELS[a.event], " in %s" % a.zone if a.zone else ""), file=sys.stderr)
        return 0
    if a.cmd == "test":
        problem = test(a.channel)
        where = "this Mac" if a.channel == "mac" else "cmux"
        print("A test went to %s." % where if not problem else "%s %s" % (where[:1].upper() + where[1:], problem),
              file=sys.stdout if not problem else sys.stderr)
        return 0 if not problem else 1
    if a.cmd == "flush":
        print("%d held notice(s) sent" % flush(ws))
        return 0
    if a.cmd == "hooks":
        try:
            found = hooks(ws, install=True if a.install else False if a.uninstall else None)
        except ValueError as e:
            print("notifications: %s" % e, file=sys.stderr)
            return 1
        if not found:
            print("No Claude Code or Codex folder in your home: nothing to set up.")
            return 1
        for name, state in found.items():
            print("%s: %s" % ({"claude": "Claude Code", "codex": "Codex"}[name], state))
        if a.install and "codex" in found:
            print("In Codex, run /hooks and trust the new hooks: Codex skips a hook until you do.")
        return 0
    return 64


if __name__ == "__main__":
    sys.exit(main())
