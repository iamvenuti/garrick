#!/usr/bin/env python3
"""channels.py: how far each channel's requests may go (#571).

Ask and the Telegram channel run requests through one engine (engine.py). Each channel has three settings, kept in
`System/garrick-settings.json` under `channels` and shown in Settings:

    tier       haiku, sonnet or opus: a tier, never a model name          default sonnet
    effort     low, medium or high                                        default medium
    autonomy   read, act or full                                          default act

Read answers and proposes. Act does what git can undo (edits notes, files the inbox, ticks and adds Todo lines,
makes and moves threads, commits) and asks first before anything that leaves the machine or cannot be undone:
sending, sharing, deleting, writing to a synced shared folder, rewriting history. Full is Act, and it also sends
without asking. Full is offered for Ask only: nobody is at the desk to stop a wrong send from the phone, and an
unlocked phone must not be enough to send mail in the owner's name. Telegram's `full` is refused when it is saved
and read as `read` when it is found in the file, so a hand-edited file never widens it.

A request can raise itself, alone, with a leading `deep:`: it runs on `opus` at high effort, and the settings stay
as they were. Code finds the word; no model decides it. A plain "open X" or "park X" stays on `haiku`.

**Capabilities, not brands.** Act needs three things of the assistant, checked for the one the owner chose, at start
and when the assistant setting changes (`capability()`):

    resume               a session can be continued, so a follow-up does not repeat the discovery
    removable_tools      its tools can be taken out of a session, down to a fixed list of commands, so that the
                         send, share and delete tools are not there and `hold` is
    walls_outside_model  a write passes the engine's guard and the commit check, whatever the session does

An assistant that fails one runs the channel at Read, and Settings says which check failed. No brand is named: an
assistant gets the full engine on the day it passes.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
CHANNELS = ("ask", "telegram")
TIERS = ("haiku", "sonnet", "opus")
EFFORTS = ("low", "medium", "high")
LEVELS = ("read", "act", "full")
DEFAULTS = {"tier": "sonnet", "effort": "medium", "autonomy": "act"}
LEVELS_FOR = {"ask": LEVELS, "telegram": ("read", "act")}
DEEP_TIER, DEEP_EFFORT = "opus", "high"
PLAIN_TIER = "haiku"
CHECKS = ("resume", "removable_tools", "walls_outside_model")
CHECK_SAID = {
    "resume": "the assistant cannot continue a session",
    "removable_tools": "the assistant's tools cannot be narrowed to a fixed list",
    "walls_outside_model": "the guard on writes could not be loaded or did not stop a write",
}
DEEP = re.compile(r"^\s*deep\s*:\s*", re.I)
# A plain command keeps its fast path, and its small tier: open, park or wake something.
PLAIN = re.compile(r"^\s*(?:please\s+)?(?:open|park|wake|unpark)\s+\S", re.I)
# What a request that asks for work in the records reads as: an imperative that changes or files something. Questions
# are answered by Ask's own session, with citations; a plain command has its fast path. Code decides, no model.
WANTS_ACTION = re.compile(r"^\s*(?:please\s+)?(?:file|process|sort|tick|untick|mark|move|make|create|rename|edit|update|write|commit|"
                          r"tidy|clean\s+up|fix|archive|merge|split|remove|delete|send|forward|share|reply|draft)\b", re.I)


def jobs_dir() -> Path:
    given = os.environ.get("GARRICK_JOBS_DIR")
    if given:
        return Path(given).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "garrick-jobs"
    return Path.home() / ".local" / "state" / "garrick-jobs"


# ---------------------------------------------------------------- the settings


def clean_one(channel: str, given, kept=None) -> dict:
    """One channel's settings as they may be kept: `ValueError` with a sentence for the owner when a value is not
    one of the choices, or when Full is asked of a channel that never offers it. A key left out keeps the value
    already kept for the channel (`kept`), when that is one of the choices, else takes the default."""
    if channel not in CHANNELS:
        raise ValueError("there is no channel called %r" % (channel,))
    if not isinstance(given, dict) or set(given) - set(DEFAULTS):
        raise ValueError("a channel has a tier, an effort and an autonomy")
    out = dict(DEFAULTS)
    for key, allowed in (("tier", TIERS), ("effort", EFFORTS), ("autonomy", LEVELS)):
        if isinstance(kept, dict) and kept.get(key) in (LEVELS_FOR[channel] if key == "autonomy" else allowed):
            out[key] = kept[key]
        if key in given:
            if given[key] not in allowed:
                raise ValueError("%s is %s" % (key, " or ".join(allowed)))
            out[key] = given[key]
    if out["autonomy"] not in LEVELS_FOR[channel]:
        raise ValueError("Telegram does not offer Full: nobody is at the desk to stop a wrong send, and an unlocked phone "
                         "should not be enough to send mail in your name")
    return out


def clean(given, kept=None) -> dict:
    """The `channels` block as Settings sends it, validated: {"ask": {...}, "telegram": {...}}. A channel left out
    keeps no value, so it reads as its defaults. With `kept`, the block now in the file, a key a channel's entry
    leaves out keeps its kept value instead of going back to the default."""
    if not isinstance(given, dict):
        raise ValueError("not settings for the channels")
    kept = kept if isinstance(kept, dict) else {}
    return {channel: clean_one(channel, value, kept.get(channel)) for channel, value in given.items()}


def settings(ws: Path) -> Dict[str, dict]:
    """Both channels' settings, as the file holds them with the defaults under: a value that is not a choice, or
    Full on a channel that does not offer it, reads as the closed side (the default tier or effort, and Read)."""
    saved = {}
    try:
        import prefs
        saved = prefs.read(ws).get("channels")
    except Exception:
        saved = {}
    saved = saved if isinstance(saved, dict) else {}
    out = {}
    for channel in CHANNELS:
        row = dict(DEFAULTS)
        mine = saved.get(channel) if isinstance(saved.get(channel), dict) else {}
        for key, allowed in (("tier", TIERS), ("effort", EFFORTS), ("autonomy", LEVELS)):
            if mine.get(key) in allowed:
                row[key] = mine[key]
            elif key in mine:
                row[key] = "read" if key == "autonomy" else DEFAULTS[key]
        if row["autonomy"] not in LEVELS_FOR[channel]:
            row["autonomy"] = "read"
        out[channel] = row
    return out


def split_deep(text: str):
    """(whether the request starts with `deep:`, the request without it)."""
    m = DEEP.match(text or "")
    return (True, text[m.end():]) if m else (False, text or "")


def plan(cfg: dict, text: str) -> dict:
    """What one request runs as: its tier, effort, autonomy and text. `deep:` raises the request alone, to opus
    at high effort; a plain command stays on haiku. The channel's settings are not changed."""
    deep, body = split_deep(text)
    tier, effort = cfg["tier"], cfg["effort"]
    if deep:
        tier, effort = DEEP_TIER, DEEP_EFFORT
    elif PLAIN.match(body):
        tier = PLAIN_TIER
    return {"tier": tier, "effort": effort, "autonomy": cfg["autonomy"], "text": body.strip(), "deep": deep}


def wants_action(text: str) -> bool:
    """Whether a request asks for work in the records, as opposed to a question or a plain command."""
    return bool(WANTS_ACTION.match(split_deep(text)[1]))


# ---------------------------------------------------------------- the capability check


def assistant() -> str:
    return os.environ.get("GARRICK_HARNESS", "claude").strip().lower() or "claude"


def binary(name: str) -> Optional[str]:
    return shutil.which(name)


def probe_help(name: Optional[str] = None) -> str:
    """The assistant's own `--help`, which says what it can do: Garrick reads the flags, not the name."""
    exe = binary(name or assistant())
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (r.stdout or "") + (r.stderr or "")


def guard_works(ws: Path) -> bool:
    """Whether the engine's guard loads and does what it is for: stops a write into another zone, and lets one into
    the zone it is bound to. A guard that cannot be loaded fails the check."""
    try:
        import engine_guard
        base = Path(ws).resolve()
        zones = sorted(p.name for p in (base / "Zones").iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
        if not zones:
            return False
        here, other = zones[0], zones[1] if len(zones) > 1 else "_nowhere_"
        mine = {"tool_name": "Write", "tool_input": {"file_path": str(base / "Zones" / here / "x.md")}}
        theirs = {"tool_name": "Write", "tool_input": {"file_path": str(base / "Zones" / other / "x.md")}}
        system = {"tool_name": "Edit", "tool_input": {"file_path": str(base / "System" / "garrick-settings.json")}}
        git = {"tool_name": "Write", "tool_input": {"file_path": str(base / "Zones" / here / ".git" / "config")}}
        raw = {"tool_name": "Write", "tool_input": {"file_path": str(base / "Wikis" / "Meetings" / "raw" / "x.md")}}
        return (engine_guard.decide(mine, str(base), here) is None
                and engine_guard.decide(theirs, str(base), here) is not None
                and engine_guard.decide(system, str(base), here) is not None
                and engine_guard.decide(git, str(base), here) is not None
                and engine_guard.decide(raw, str(base), here) is not None
                and hook_line_works(base, here, engine_guard.hook_command(), system, mine))
    except Exception:
        return False


def hook_line_works(base: Path, zone: str, line: str, bad: dict, good: dict) -> bool:
    """Whether the hook's own command line, as the session's settings carry it and a shell runs it, stops a write
    outside the zone with the exit code Claude blocks on (2) and lets one inside the zone through. A hook that cannot
    start, or exits with any other code, blocks nothing."""
    env = dict(os.environ, GARRICK_ENGINE_WS=str(base), GARRICK_ENGINE_ZONE=zone)
    try:
        stopped = subprocess.run(line, shell=True, input=json.dumps(bad), capture_output=True, text=True, env=env, timeout=20)
        let = subprocess.run(line, shell=True, input=json.dumps(good), capture_output=True, text=True, env=env, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return stopped.returncode == 2 and let.returncode == 0


def evaluate(ws: Path, help_text: str, guard: bool) -> dict:
    flags = help_text or ""
    passed = {
        "resume": "--resume" in flags,
        # removable: tools can be named one by one, a shell narrowed to a fixed list of commands, and the servers
        # the session has can be limited to the ones Garrick gives it
        "removable_tools": "--allowedTools" in flags and "--strict-mcp-config" in flags and "Bash(" in flags,
        "walls_outside_model": bool(guard),
    }
    failed = [c for c in CHECKS if not passed[c]]
    return {"ok": not failed, "failed": failed, "said": [CHECK_SAID[c] for c in failed], "assistant": assistant(),
            "effort_flag": "--effort" in flags, "checked": dt.datetime.now().astimezone().isoformat(timespec="seconds")}


def capability(ws: Path, force: bool = False, probe: Optional[Callable[[], str]] = None, guard: Optional[bool] = None) -> dict:
    """The check for the assistant chosen: run at start, and again when the assistant setting changes. The answer is
    kept in the jobs folder with the assistant it was made for, so a changed setting is a new check."""
    path = jobs_dir() / "channels-capability.json"
    name = assistant()
    if not force:
        try:
            kept = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(kept, dict) and kept.get("assistant") == name and "ok" in kept:
                return kept
        except (OSError, ValueError):
            pass
    found = evaluate(ws, (probe or probe_help)(), guard_works(ws) if guard is None else guard)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".new")
        tmp.write_text(json.dumps(found), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        pass
    return found


def kept() -> Optional[dict]:
    """The last capability check made for this assistant, or None: never runs one. The page reads this, so building it
    never starts the assistant."""
    try:
        data = json.loads((jobs_dir() / "channels-capability.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("assistant") == assistant() and "ok" in data else None


def effective(ws: Path, channel: str, cap: Optional[dict] = None) -> dict:
    """The level a channel runs at now: the one set, or Read when the assistant failed a check, with the check named."""
    cfg = settings(ws)[channel]
    cap = cap if cap is not None else capability(ws)
    level = cfg["autonomy"]
    if level != "read" and not cap.get("ok"):
        return dict(cfg, autonomy="read", set=level, limited=list(cap.get("failed") or []), why="; ".join(cap.get("said") or []))
    return dict(cfg, set=level, limited=[], why="")
