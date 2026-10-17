#!/usr/bin/env python3
"""notifications.py: the one way Garrick tells you something.

    python3 System/tools/notifications.py send <event> <title> <message> [--zone Work]
    python3 System/tools/notifications.py test <mac|cmux|telegram|command>
    python3 System/tools/notifications.py flush        send what quiet hours held, if they are over
    python3 System/tools/notifications.py hook         what an assistant's hook runs, its event on stdin
    python3 System/tools/notifications.py hooks [--install | --uninstall]   Needs you and Finished, for Claude Code and Codex
    python3 System/tools/notifications.py telegram-token [--forget]         keep the bot's token in the keychain

Every sender calls send(): the scheduled jobs (job.py), the todo sweep, the
cmux desk, and the session hooks. Where a notice goes is set on the status
page, Settings › Notifications, and kept under `notifications` in
System/garrick-settings.json, committed with the workspace:

    {"channels": {"mac": true, "cmux": true, "telegram": false, "command": false},
     "telegram": {"chat": "123456789"},
     "command": "/bin/sh /Users/<you>/notify.sh",
     "events": {"needs-you": {"to": ["mac"], "quiet": "send", "away": false},
                "finished": {"to": ["mac"], "quiet": "drop", "away": false, "after": 2}, ...},
     "quiet": {"on": true, "from": "22:00", "to": "07:00"},
     "zones": {"Personal": {"to": ["mac", "telegram"], "chat": "987654321"}}}

**Events** (EVENTS) are what happened; **channels** are where it goes:

- `mac`, a notification on this Mac. For a session running in cmux, with
  the cmux channel on, cmux's own notification takes its place, so the
  notice lands on that session's tab.
- `telegram`, a message from your bot, through the Bot API's sendMessage,
  standard library only. The bot's token is a secret: it lives in the macOS
  keychain (`telegram-token` puts it there, read from the terminal or from
  standard input, never from an argument), never in the settings file, a
  log or this page. The chat is one ID, or one per zone.
- `command`, a command of yours, run as `<command> <title> <message>` with
  GARRICK_NOTIFY_EVENT, GARRICK_NOTIFY_KIND, GARRICK_JOB, GARRICK_EXIT and,
  for a notice about one zone, GARRICK_ZONE and GARRICK_ZONE_DIR set, in that
  zone's folder: what job.py's GARRICK_NOTIFY_CMD has always been given.

Each event goes to the channels it lists that are switched on, and a notice
about one zone only to the channels that zone allows. **Quiet hours** (22:00
to 07:00 unless set otherwise) hold each event to its choice: `send` anyway,
`hold` it for the morning, or `drop` it. A held notice goes out with the
first notice, flush or session prompt after the quiet hours end. `away`, for
Needs you and Finished, sends nothing while you are looking at that very
cmux tab; it is offered for cmux alone, the one place that can be asked.

**What a notice says** is short and plain: the zone or thread, what
happened, never the content of a note or a meeting, since a phone shows it
on a locked screen. Finished says only that a session is done, in which
thread and after how long.

**An override.** GARRICK_NOTIFY=1 or GARRICK_NOTIFY_CMD in a sender's
environment, as a job's launchd plist may set them, keep working exactly as
before for that sender, and these settings do not apply to it: the status
page names the plists that do this.

**The hooks.** `hooks --install` adds this file's `hook` to Claude Code's
UserPromptSubmit, Notification and Stop events (~/.claude/settings.json),
and to Codex's UserPromptSubmit and Stop (~/.codex/hooks.json): Codex has no
event for a session waiting on you. The prompt marks when a turn began, so
Finished can wait for a turn longer than the set minutes. A hook never
blocks the session: it answers nothing, sends from a process of its own,
and does nothing for a session outside this workspace or for a headless job
(GARRICK_HEADLESS=1).

What it keeps for itself, never committed, is in
System/generated/notifications/: the notices quiet hours hold, when each
session's turn began, and the day a Telegram token was stored on this Mac.

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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent

SETTINGS = ("System", "garrick-settings.json")      # garrick_lib.SETTINGS; a test keeps the two in step
KEY = "notifications"
STATE = ("System", "generated", "notifications")

# (name, label, what it is). The order is the order Settings lists them in.
EVENTS = (
    ("needs-you", "Needs you", "A session is waiting: a permission to give, a question, an idle prompt"),
    ("finished", "Finished", "A session has ended its turn, after running longer than the minutes set"),
    ("todo-refreshed", "Todo refreshed", "The nightly sweep has run: lines added, folded, expired"),
    ("todo-summary", "Todo summary", "Each zone's morning digest from the sweep: overdue, due today, chases due"),
    ("job-failed", "Job failed or recovered", "A scheduled job fails or works again, and a line a job sends of its own"),
    ("job-idle", "Job idle", "A job has run cleanly but done nothing for days"),
    ("desk", "Desk", "The cmux desk starting the day or shutting down"),
)
EVENT_NAMES = tuple(e[0] for e in EVENTS)
LABELS = {e[0]: e[1] for e in EVENTS}
SESSION_EVENTS = ("needs-you", "finished")       # from a session: cmux may stand in for the Mac, "away" applies
CHANNELS = ("mac", "telegram", "command")         # what an event can list
SWITCHES = ("mac", "cmux", "telegram", "command")  # what can be switched on
CHANNEL_LABELS = {"mac": "This Mac", "cmux": "cmux", "telegram": "Telegram", "command": "Your command"}
QUIET_CHOICES = ("send", "hold", "drop")
DEFAULT_EVENTS = {
    "needs-you": {"to": ["mac"], "quiet": "send"},
    "finished": {"to": ["mac"], "quiet": "drop", "after": 2},
    "todo-refreshed": {"to": [], "quiet": "hold"},
    "todo-summary": {"to": None, "quiet": "hold"},          # Telegram once it is set up, else this Mac
    "job-failed": {"to": list(CHANNELS), "quiet": "hold"},
    "job-idle": {"to": ["mac"], "quiet": "hold"},
    "desk": {"to": ["mac"], "quiet": "send"},
}
# job.py's kinds, as GARRICK_NOTIFY_KIND has always carried them, and the event each is.
KINDS = {"failed": "job-failed", "recovered": "job-failed", "message": "job-failed", "idle": "job-idle",
         "digest": "todo-summary", "refreshed": "todo-refreshed"}
AFTER_MAX = 240
CHAT = re.compile(r"^(?:-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")
TOKEN = re.compile(r"^\d{3,20}:[A-Za-z0-9_-]{20,100}$")
CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
COMMAND_MAX = 400
HELD_MAX = 50
HELD_HOURS = 24
TURN_DAYS = 2
TELEGRAM_API = "https://api.telegram.org/bot%s/sendMessage"
TELEGRAM_TEXT = 3500
TIMEOUT = 8            # seconds a channel may take: Telegram, cmux, osascript
COMMAND_TIMEOUT = 60   # what job.py has always given a notifier
KEYCHAIN_SERVICE = "Garrick Telegram bot"
KEYCHAIN_ACCOUNT = "garrick"
CMUX_APPS = ("/Applications/cmux.app/Contents/Resources/bin/cmux", "~/Applications/cmux.app/Contents/Resources/bin/cmux")
CMUX_BUNDLE = "com.cmuxterm.app"
HOOK_TIMEOUT = 10
CLAUDE_HOOKS = ("UserPromptSubmit", "Notification", "Stop")
CODEX_HOOKS = ("UserPromptSubmit", "Stop")       # Codex has no event for a session waiting on you

# The ways out, as module attributes, so a test puts fakes in their place and
# nothing reaches the network, the keychain or this Mac's notifications.
_run = subprocess.run
_urlopen = urllib.request.urlopen


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


def zones_of(ws: Path) -> List[str]:
    folder = ws / "Zones"
    return sorted(z.name for z in folder.iterdir() if z.is_dir() and not z.name.startswith((".", "_"))) \
        if folder.is_dir() else []


def settings(ws: Path) -> dict:
    """The settings, every part filled in: what was saved where it reads,
    the defaults for the rest. Never raises; an unreadable part is its default."""
    return normal(saved(ws))


def normal(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    ch = raw.get("channels") if isinstance(raw.get("channels"), dict) else {}
    tg = raw.get("telegram") if isinstance(raw.get("telegram"), dict) else {}
    chat = tg.get("chat") if isinstance(tg.get("chat"), str) and CHAT.match(tg.get("chat", "")) else ""
    command = raw.get("command") if isinstance(raw.get("command"), str) else ""
    channels = {"mac": ch.get("mac", True) is not False, "cmux": ch.get("cmux", True) is not False,
                "telegram": ch.get("telegram") is True, "command": ch.get("command") is True and bool(command.strip())}
    zones = {}
    for zone, z in (raw.get("zones") or {}).items() if isinstance(raw.get("zones"), dict) else ():
        if not isinstance(z, dict):
            continue
        entry = {}
        if isinstance(z.get("to"), list):
            entry["to"] = [c for c in CHANNELS if c in z["to"]]
        if isinstance(z.get("chat"), str) and CHAT.match(z["chat"]):
            entry["chat"] = z["chat"]
        zones[str(zone)] = entry
    if channels["telegram"] and not (chat or any(z.get("chat") for z in zones.values())):
        channels["telegram"] = False            # nowhere to send it
    events = {}
    given = raw.get("events") if isinstance(raw.get("events"), dict) else {}
    for name in EVENT_NAMES:
        d, g = DEFAULT_EVENTS[name], given.get(name) if isinstance(given.get(name), dict) else {}
        to = g.get("to") if isinstance(g.get("to"), list) else d["to"]
        if to is None:                          # the summary: Telegram once it is set up, else this Mac
            to = ["telegram"] if channels["telegram"] else ["mac"]
        e = {"to": [c for c in CHANNELS if c in to],
             "quiet": g.get("quiet") if g.get("quiet") in QUIET_CHOICES else d["quiet"],
             "away": g.get("away") is True and name in SESSION_EVENTS}
        if name == "finished":
            after = g.get("after", d["after"])
            e["after"] = after if isinstance(after, int) and not isinstance(after, bool) and 0 <= after <= AFTER_MAX else d["after"]
        events[name] = e
    q = raw.get("quiet") if isinstance(raw.get("quiet"), dict) else {}
    quiet = {"on": q.get("on", True) is not False,
             "from": q.get("from") if isinstance(q.get("from"), str) and CLOCK.match(q["from"]) else "22:00",
             "to": q.get("to") if isinstance(q.get("to"), str) and CLOCK.match(q["to"]) else "07:00"}
    return {"channels": channels, "telegram": {"chat": chat}, "command": command, "events": events,
            "quiet": quiet, "zones": zones}


class Invalid(ValueError):
    """A setting the page sent that cannot be kept, in words."""


def clean(given, zones: Optional[List[str]] = None) -> dict:
    """The settings as the page sends them, checked strictly, in the shape
    they are saved in. Raises Invalid with the reason. A zone no longer in
    the workspace is left out, as Settings › Zones does."""
    if not isinstance(given, dict):
        raise Invalid("not a set of notification settings")
    unknown = sorted(set(given) - {"channels", "telegram", "command", "events", "quiet", "zones"})
    if unknown:
        raise Invalid("not a notification setting: %s" % ", ".join(unknown))
    out: dict = {}
    ch = given.get("channels", {})
    if not isinstance(ch, dict) or set(ch) - set(SWITCHES) or not all(isinstance(v, bool) for v in ch.values()):
        raise Invalid("not a set of channels, each on or off")
    out["channels"] = {k: ch.get(k, k in ("mac", "cmux")) for k in SWITCHES}
    tg = given.get("telegram", {})
    if not isinstance(tg, dict) or set(tg) - {"chat"}:
        raise Invalid("not a Telegram chat")
    chat = (tg.get("chat") or "").strip() if isinstance(tg.get("chat", ""), str) else None
    if chat is None or (chat and not CHAT.match(chat)):
        raise Invalid("a Telegram chat ID is a number, such as 123456789, or -100 and a number for a group")
    out["telegram"] = {"chat": chat}
    command = given.get("command", "")
    if not isinstance(command, str) or len(command) > COMMAND_MAX or "\n" in command:
        raise Invalid("a command is one line of up to %d characters" % COMMAND_MAX)
    try:
        shlex.split(command)
    except ValueError:
        raise Invalid("the command does not read: a quote is not closed")
    out["command"] = command.strip()
    if out["channels"]["command"] and not out["command"]:
        raise Invalid("name the command to run, or switch it off")
    events = given.get("events", {})
    if not isinstance(events, dict) or set(events) - set(EVENT_NAMES):
        raise Invalid("not an event Garrick sends: %s" % ", ".join(sorted(set(events) - set(EVENT_NAMES)))
                      if isinstance(events, dict) else "not a set of events")
    out["events"] = {}
    for name, e in events.items():
        allowed = {"to", "quiet"} | ({"away"} if name in SESSION_EVENTS else set()) | ({"after"} if name == "finished" else set())
        if not isinstance(e, dict) or set(e) - allowed:
            raise Invalid("not a choice for %s" % LABELS[name])
        entry = {}
        if "to" in e:
            if not isinstance(e["to"], list) or set(e["to"]) - set(CHANNELS):
                raise Invalid("not a list of channels for %s" % LABELS[name])
            entry["to"] = [c for c in CHANNELS if c in e["to"]]
        if "quiet" in e:
            if e["quiet"] not in QUIET_CHOICES:
                raise Invalid("in quiet hours, %s is sent, held or dropped" % LABELS[name])
            entry["quiet"] = e["quiet"]
        if "away" in e:
            if not isinstance(e["away"], bool):
                raise Invalid("not a choice for %s" % LABELS[name])
            entry["away"] = e["away"]
        if "after" in e:
            a = e["after"]
            if not isinstance(a, int) or isinstance(a, bool) or not 0 <= a <= AFTER_MAX:
                raise Invalid("Finished waits from 0 to %d minutes" % AFTER_MAX)
            entry["after"] = a
        out["events"][name] = entry
    q = given.get("quiet", {})
    if not isinstance(q, dict) or set(q) - {"on", "from", "to"}:
        raise Invalid("not a time for quiet hours")
    if "on" in q and not isinstance(q["on"], bool):
        raise Invalid("quiet hours are on or off")
    for k in ("from", "to"):
        if k in q and not (isinstance(q[k], str) and CLOCK.match(q[k])):
            raise Invalid("quiet hours are times such as 22:00")
    out["quiet"] = {"on": q.get("on", True), "from": q.get("from", "22:00"), "to": q.get("to", "07:00")}
    zs = given.get("zones", {})
    if not isinstance(zs, dict):
        raise Invalid("not a choice for each zone")
    out["zones"] = {}
    for zone, z in zs.items():
        if not isinstance(z, dict) or set(z) - {"to", "chat"}:
            raise Invalid("not a choice for %s" % zone)
        if zones is not None and zone not in zones:
            continue
        entry = {}
        if "to" in z:
            if not isinstance(z["to"], list) or set(z["to"]) - set(CHANNELS):
                raise Invalid("not a list of channels for %s" % zone)
            entry["to"] = [c for c in CHANNELS if c in z["to"]]
        c = z.get("chat", "")
        if not isinstance(c, str) or (c.strip() and not CHAT.match(c.strip())):
            raise Invalid("%s's Telegram chat is not a chat ID" % zone)
        if c.strip():
            entry["chat"] = c.strip()
        out["zones"][zone] = entry
    if out["channels"]["telegram"] and not (chat or any(z.get("chat") for z in out["zones"].values())):
        raise Invalid("Telegram needs a chat ID to send to, or switch it off")
    return out


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
    """Send what quiet hours held, once they are over: each to the channels
    its event and zone allow now. A notice held longer than HELD_HOURS is
    let go. How many went."""
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
        to = route(cfg, n["event"], n.get("zone"))
        if to and deliver(ws, cfg, n, to, env=env, log=log, prefix=prefix, session=False):
            sent += 1
    return sent


# --------------------------------------------------------------------------- sending

def route(cfg: dict, event: str, zone: Optional[str]) -> List[str]:
    """The channels a notice goes to: its event's, switched on, and allowed by its zone."""
    to = [c for c in cfg["events"][event]["to"] if cfg["channels"].get(c)]
    z = cfg["zones"].get(zone) if zone else None
    if z and "to" in z:
        to = [c for c in to if c in z["to"]]
    if "telegram" in to and not chat_for(cfg, zone):
        to.remove("telegram")
    return to


def chat_for(cfg: dict, zone: Optional[str]) -> str:
    z = cfg["zones"].get(zone) if zone else None
    return (z or {}).get("chat") or cfg["telegram"]["chat"]


def send(event: str, title: str, message: str, zone: Union[str, Path, None] = None, root=None,
         kind: Optional[str] = None, job: str = "", code: Optional[int] = None, log=None,
         prefix: str = "notifications", now: Optional[dt.datetime] = None, env=None) -> bool:
    """Send one notice wherever the settings say. `zone` is a zone's name or
    its folder. `log`, a file open for writing, gets a line for a channel
    that failed; a failure never raises. True when it went somewhere, or
    was held for after quiet hours."""
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
    if zone_dir is None and zone_name and (ws / "Zones" / zone_name).is_dir():
        zone_dir = ws / "Zones" / zone_name
    cfg = settings(ws)
    now = now or dt.datetime.now()
    try:
        flush(ws, cfg, now, env, log, prefix)
    except Exception:
        pass                    # what was held waits for the next one
    to = route(cfg, event, zone_name)
    if not to:
        return False
    if is_quiet(cfg, now):
        choice = cfg["events"][event]["quiet"]
        if choice == "drop":
            return False
        if choice == "hold":
            try:
                hold(ws, notice, now)
                return True
            except OSError:
                return False
    if event in SESSION_EVENTS and cfg["events"][event]["away"] and cfg["channels"]["cmux"] and looking(env):
        return False
    return deliver(ws, cfg, notice, to, zone_dir=zone_dir, env=env, log=log, prefix=prefix,
                   session=event in SESSION_EVENTS)


def deliver(ws: Path, cfg: dict, notice: dict, to: List[str], zone_dir: Optional[Path] = None, env=None, log=None,
            prefix: str = "notifications", session: bool = False) -> bool:
    env = os.environ if env is None else env
    if zone_dir is None and notice.get("zone") and (ws / "Zones" / notice["zone"]).is_dir():
        zone_dir = ws / "Zones" / notice["zone"]
    went = False
    for channel in to:
        if channel == "mac":
            problem = local(notice["title"], notice["message"], env, cmux=session and cfg["channels"]["cmux"])
        elif channel == "telegram":
            problem = telegram(chat_for(cfg, notice.get("zone")), text_of(notice))
        else:
            problem = command(cfg["command"], notice, zone_dir, env)
        if problem:
            say(log, "%s: %s %s" % (prefix, "the notifier" if channel == "command" else CHANNEL_LABELS[channel], problem))
        else:
            went = True
    return went


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


def text_of(notice: dict) -> str:
    """One message for a chat: the title, then what happened, unless it already says it."""
    title, message = notice["title"], notice["message"]
    return message if message.startswith(title) else "%s\n%s" % (title, message)


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
    in cmux with that channel on, else the Mac's own. A cmux that will not
    take it falls back to the Mac's."""
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


def looking(env=None) -> bool:
    """Whether you are looking at the session this runs in: cmux in front,
    with this session's tab the one in focus. Asked of cmux alone; anything
    that does not answer counts as away, so the notice goes."""
    env = os.environ if env is None else env
    if not in_cmux(env):
        return False
    try:
        r = _run([cmux_binary(env), "identify", "--json"], capture_output=True, text=True, timeout=3,
                 env=dict(env), stdin=subprocess.DEVNULL)
        data = json.loads(r.stdout) if r.returncode == 0 else {}
        caller = (data.get("caller") or {}).get("surface_ref")
        focused = (data.get("focused") or {}).get("surface_ref")
        if not caller or caller != focused:
            return False
        front = _run(["lsappinfo", "front"], capture_output=True, text=True, timeout=3)
        asn = (front.stdout or "").strip()
        if front.returncode != 0 or not asn:
            return False
        info = _run(["lsappinfo", "info", "-only", "bundleid", asn], capture_output=True, text=True, timeout=3)
        return CMUX_BUNDLE in (info.stdout or "")
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
        return False


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


# --------------------------------------------------------------------------- Telegram

def token() -> Optional[str]:
    """The bot's token from the macOS keychain, or None. Never logged."""
    if sys.platform != "darwin":
        return None
    try:
        r = _run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
                 capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = (r.stdout or "").strip()
    return found if r.returncode == 0 and TOKEN.match(found) else None


def store_token(value: str, ws: Optional[Path] = None) -> None:
    """Keep the bot's token in the login keychain. It reaches `security`
    on its standard input, never as an argument, so no process list shows
    it. Raises Invalid when it is not a token, OSError when it did not keep."""
    value = value.strip()
    if not TOKEN.match(value):
        raise Invalid("that is not a bot token: BotFather gives one such as 123456789:AA… ")
    if sys.platform != "darwin":
        raise OSError("the keychain is only on a Mac")
    line = 'add-generic-password -U -s "%s" -a "%s" -w "%s"\n' % (KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, value)
    r = _run(["security", "-i"], input=line, capture_output=True, text=True, timeout=30)
    if r.returncode != 0 or token() != value:
        raise OSError("the keychain did not keep it")
    if ws is not None:
        _write_json(state_dir(ws) / "telegram.json", {"stored": dt.date.today().isoformat()})


def forget_token(ws: Optional[Path] = None) -> bool:
    gone = False
    if sys.platform == "darwin":
        r = _run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
                 capture_output=True, text=True, timeout=TIMEOUT)
        gone = r.returncode == 0
    if ws is not None:
        try:
            (state_dir(ws) / "telegram.json").unlink()
        except OSError:
            pass
    return gone


def token_stored(ws: Path) -> Optional[str]:
    """The day a token was stored on this Mac, as this file recorded it,
    without reading the keychain: what the status page shows. None if never."""
    found = _read_json(state_dir(ws) / "telegram.json", {}).get("stored")
    return found if isinstance(found, str) else None


def scrub(text: str, secret: Optional[str]) -> str:
    return text.replace(secret, "<token>") if secret else text


def telegram(chat: str, text: str, tok: Optional[str] = None) -> str:
    """sendMessage to one chat, plain text. "" when Telegram took it."""
    if not chat:
        return "has no chat ID to send to"
    tok = tok or token()
    if not tok:
        return "has no bot token in the keychain: run python3 System/tools/notifications.py telegram-token"
    data = urllib.parse.urlencode({"chat_id": chat, "text": text[:TELEGRAM_TEXT],
                                   "disable_web_page_preview": "true"}).encode("utf-8")
    req = urllib.request.Request(TELEGRAM_API % tok, data=data, method="POST")
    try:
        with _urlopen(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            body = {}
        return scrub("said no: %s" % (body.get("description") or "HTTP %d" % e.code), tok)
    except Exception as e:          # no network, a timeout, a certificate: say what, never the URL
        reason = getattr(e, "reason", None) or type(e).__name__
        return scrub("could not be reached: %s" % reason, tok)
    if not isinstance(body, dict) or body.get("ok") is not True:
        return scrub("said no: %s" % ((body or {}).get("description") or "no reason given"), tok)
    return ""


# --------------------------------------------------------------------------- a test from the page

def test(ws: Path, channel: str, env=None) -> str:
    """Send a test on one channel, as the settings now stand, whatever the
    events and quiet hours say. "" when it went, else why it did not."""
    env = os.environ if env is None else env
    cfg = settings(ws)
    title, message = "Test", "A test from Garrick's Settings. Notices on this channel will look like this."
    if channel == "mac":
        return mac(title, message)
    if channel == "cmux":
        if not in_cmux(env):
            return "runs only from a session inside cmux"
        return local(title, message, env, cmux=True)
    if channel == "telegram":
        chat = cfg["telegram"]["chat"] or next((z["chat"] for z in cfg["zones"].values() if z.get("chat")), "")
        return telegram(chat, "Garrick\n" + message)
    if channel == "command":
        if not cfg["command"]:
            return "has no command to run"
        return command(cfg["command"], {"event": "test", "kind": "test", "title": title, "message": message}, None, env)
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
        after = settings(ws)["events"]["finished"]["after"]
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
    t = sub.add_parser("test", help="send a test on one channel")
    t.add_argument("channel", choices=SWITCHES)
    sub.add_parser("flush", help="send what quiet hours held, if they are over")
    sub.add_parser("hook", help="one hook event from Claude Code or Codex, on standard input")
    d = sub.add_parser("deliver")                # the hook's own sender, a notice on standard input
    d.add_argument("--workspace", required=True)
    h = sub.add_parser("hooks", help="the Needs you and Finished hooks for Claude Code and Codex")
    g = h.add_mutually_exclusive_group()
    g.add_argument("--install", action="store_true")
    g.add_argument("--uninstall", action="store_true")
    k = sub.add_parser("telegram-token", help="keep the Telegram bot's token in the keychain, typed or piped in")
    k.add_argument("--forget", action="store_true", help="remove it from the keychain")
    for p in (s, t, h, k, sub.choices["flush"]):
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
            print("notifications: nothing sent: no channel is on for %s%s, or it is quiet hours"
                  % (LABELS[a.event], " in %s" % a.zone if a.zone else ""), file=sys.stderr)
        return 0
    if a.cmd == "test":
        problem = test(ws, a.channel)
        print("A test went to %s." % {"mac": "this Mac", "command": "your command"}.get(a.channel, CHANNEL_LABELS[a.channel])
              if not problem else
              "%s %s" % (CHANNEL_LABELS[a.channel], problem), file=sys.stdout if not problem else sys.stderr)
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
    if a.cmd == "telegram-token":
        if a.forget:
            print("Removed from the keychain." if forget_token(ws) else "There was no token in the keychain.")
            return 0
        if sys.stdin.isatty():
            import getpass
            value = getpass.getpass("The bot's token from BotFather (not shown as you paste it): ")
        else:
            value = sys.stdin.readline()
        try:
            store_token(value, ws)
        except (Invalid, OSError) as e:
            print("notifications: %s" % e, file=sys.stderr)
            return 1
        print("Kept in the keychain as \"%s\". Send a test from Settings › Notifications." % KEYCHAIN_SERVICE)
        return 0
    return 64


if __name__ == "__main__":
    sys.exit(main())
