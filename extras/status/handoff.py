#!/usr/bin/env python3
"""handoff.py: opening a piece of work in Claude's desktop app, already oriented.

The simple home's Continue and Ask something (status.py) hand the work over
to Claude's desktop app, where the conversation happens. page_action.py's
`continue` and `ask-desktop` verbs do it with what is here; status.py reads
the record this keeps, to say when the desktop app cannot open work on this
Mac and what is new in a work's files since it was last continued.

The one documented way in from another app is the Claude Code CLI's
`claude --desktop`: run in a folder it opens the desktop app on that folder,
and with `--resume <session id>` on that session. It takes no prompt, so a
session is started first and handed over:

1. `claude -p "<the question>" --output-format json`, headless, in the work's
   folder: it reads the workspace's AGENTS.md and answers, and its JSON
   carries `session_id` (prime());
2. `claude --desktop --resume <that id>` in the same folder (open_desktop()).
   `--desktop` refuses to run without a terminal, so it runs under a
   pseudo-terminal of its own; and it refuses `--settings` and
   `--mcp-config`, so it is given the real binary (find_claude()), never a
   wrapper that adds them.

The user lands on Claude's answer rather than an empty box. Nothing here
types into the desktop app or sends anything: the question is Garrick's own
("Where am I on Pricing?") or the words the user typed into Ask something.

**What is kept**, in System/generated/desktop-sessions.json, never committed:
it is this Mac's state, as the interruption stack is.

    {"sessions": {"<Zone>/<note from the zone>": {"id", "at", "folder",
                  "files": {"<path>": [mtime, size]}, "seen"}},
     "local_off": {"at", "why"} or absent}

A session is keyed by the work's note (its thread note, or the hub of a
project that is one thread), and kept with the files of the work's folder as
they stood when it was continued, which is what the work's page compares
with to say what is new, changed or missing. `local_off` is set when the
desktop app refused because local sessions are switched off, and cleared by
the next hand-off that opens.

**When local sessions are switched off.** An organisation can turn off the
desktop app's on-device sessions with a managed setting,
`disableDesktopLocalSessions`, pushed by MDM on macOS. managed_off() reads
the managed preferences where MDM puts them; refused_locally() reads what
the CLI said when it refused for that reason. Either way the home says so in
plain words (LOCAL_OFF), and Ask something still answers, on the page.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import plistlib
import pwd
import re
import select
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

RECORD = ("System", "generated", "desktop-sessions.json")
# A session continued again within this many hours is resumed as it is; an
# older one is primed afresh, so Claude reads where the work stands now.
FRESH_HOURS = 12
PRIME_TIMEOUT = 180           # seconds for the headless call that answers first
DESKTOP_TIMEOUT = 45          # seconds for `claude --desktop` to hand over and exit
FILES_MAX = 400               # files of a work's folder kept and compared
SKIP_PARTS = {".git", ".obsidian", ".trash", "archive", "Needs you", "__pycache__", "node_modules"}
DESKTOP_BUNDLE = "com.anthropic.claudefordesktop"
MANAGED_KEY = "disableDesktopLocalSessions"
# Where MDM writes an app's managed preferences on macOS: for the Mac, and for
# the one user. And Claude Code's own managed settings, which an organisation
# may use for the same switch.
MANAGED_PLACES = ("/Library/Managed Preferences/%s.plist" % DESKTOP_BUNDLE,
                  "/Library/Managed Preferences/{user}/%s.plist" % DESKTOP_BUNDLE,
                  "/Library/Application Support/ClaudeCode/managed-settings.json")
# Where the CLI lives when it is installed as Anthropic documents it, nearest
# first; then every folder on PATH. A Mac app starts with a short PATH, so the
# usual places are looked in by name.
CLAUDE_PLACES = ("~/.local/bin/claude", "~/.claude/local/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude")
# What the CLI says when the desktop app will not take a local session. Its
# wording is not documented, so this matches the setting's own name and the
# plain words around it.
REFUSED_LOCAL = re.compile(r"disableDesktopLocalSessions|local sessions?\b[^.\n]*\b(?:disabled|turned off|not allowed|"
                           r"switched off|unavailable|blocked)|(?:disabled|turned off)[^.\n]*\blocal sessions?", re.I)
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\r")

# What the home says when the desktop app cannot open work here, word for
# word in the sketch Marco approved: the work is safe, Ask still answers, and
# who can change it.
LOCAL_OFF_TITLE = "Claude can't open work on this Mac."
LOCAL_OFF = ("Your company has turned off Claude's local sessions. Garrick still keeps where each piece of work stands, "
             "and Ask something still answers. Your IT team can turn local sessions back on for you.")
NO_CLI = ("Claude Code's command-line tool is not installed on this Mac, and Continue needs it to open your work in Claude. "
          "Install it from claude.com/code, sign in once, then press Continue again.")


class HandOffError(Exception):
    """A hand-off that did not happen, in words to show the user."""


class LocalOff(HandOffError):
    """The desktop app will not take a local session on this Mac."""


# --------------------------------------------------------------------------- the record

def record_path(ws: Path) -> Path:
    return Path(ws).joinpath(*RECORD)


def load(ws: Path) -> dict:
    """The record as saved, {} when it is missing or does not read."""
    try:
        data = json.loads(record_path(ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(ws: Path, data: dict) -> None:
    """Written beside the file and renamed over it, so a reader sees one whole file or the other."""
    path = record_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".desktop-sessions-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def session_for(ws: Path, key: str) -> Optional[dict]:
    s = load(ws).get("sessions")
    entry = s.get(key) if isinstance(s, dict) else None
    return entry if isinstance(entry, dict) and isinstance(entry.get("id"), str) else None


def keep_session(ws: Path, key: str, sid: str, folder: Path, files: Dict[str, list], primed: bool,
                 now: Optional[dt.datetime] = None) -> None:
    """The work's session, and its files as they stand now; local_off cleared,
    since the desktop app has just opened."""
    now = now or dt.datetime.now()
    data = load(ws)
    sessions = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
    was = sessions.get(key) if isinstance(sessions.get(key), dict) else {}
    sessions[key] = {"id": sid, "folder": str(folder), "files": files, "seen": now.isoformat(timespec="seconds"),
                     "at": now.isoformat(timespec="seconds") if primed else was.get("at", now.isoformat(timespec="seconds"))}
    data["sessions"] = sessions
    data.pop("local_off", None)
    save(ws, data)


def mark_local_off(ws: Path, why: str, now: Optional[dt.datetime] = None) -> None:
    data = load(ws)
    data["local_off"] = {"at": (now or dt.datetime.now()).isoformat(timespec="seconds"), "why": why}
    save(ws, data)


def clear_local_off(ws: Path) -> None:
    data = load(ws)
    if "local_off" in data:
        data.pop("local_off")
        save(ws, data)


def resolve_folder(ws: Path, given: str) -> Optional[Path]:
    """A hub's `folder:` as a folder on disk: from the workspace's root, or
    absolute, or from `~/`. None when it names nothing there."""
    given = (given or "").strip().strip("\"'")
    if not given:
        return None
    p = Path(given).expanduser()
    p = p if p.is_absolute() else Path(ws) / p
    return p if p.is_dir() else None


def fresh(entry: Optional[dict], now: Optional[dt.datetime] = None) -> bool:
    """Whether a kept session is recent enough to resume as it is."""
    if not entry:
        return False
    try:
        at = dt.datetime.fromisoformat(str(entry.get("at")))
    except ValueError:
        return False
    return (now or dt.datetime.now()) - at < dt.timedelta(hours=FRESH_HOURS)


# --------------------------------------------------------------------------- local sessions switched off

def managed_places(places: Optional[Iterable[str]] = None) -> List[Path]:
    try:
        user = pwd.getpwuid(os.getuid()).pw_name    # a Mac app may start with no $USER
    except (KeyError, OSError):
        user = os.environ.get("USER") or ""
    return [Path(p.replace("{user}", user)) for p in (places if places is not None else MANAGED_PLACES)]


def managed_off(places: Optional[Iterable[Path]] = None) -> bool:
    """Whether a managed setting turns the desktop app's local sessions off:
    `disableDesktopLocalSessions` true in a managed preferences plist, or in
    Claude Code's managed settings. `places` names the files to read; a test
    passes its own, since a test never reads this Mac."""
    for path in (managed_places() if places is None else places):
        path = Path(path)
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        try:
            data = json.loads(raw.decode("utf-8")) if path.suffix == ".json" else plistlib.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict) and data.get(MANAGED_KEY) is True:
            return True
    return False


def refused_locally(said: str) -> bool:
    """Whether what the CLI said is the desktop app refusing a local session."""
    return bool(REFUSED_LOCAL.search(said or ""))


def local_off(ws: Path, places: Optional[Iterable[Path]] = None) -> Optional[str]:
    """Why the desktop app cannot open work here, or None: "managed" when a
    managed setting says so, "refused" when it last refused for that reason.
    With `places` None, only the record is read: the page passes this Mac's
    places from main(), and a test passes its own."""
    if places is not None and managed_off(places):
        return "managed"
    off = load(ws).get("local_off")
    return "refused" if isinstance(off, dict) else None


# --------------------------------------------------------------------------- the CLI

def is_wrapper(path: Path) -> bool:
    """A shell script standing in front of the CLI, such as one a terminal
    app puts first on PATH to add --settings: `--desktop` refuses those, so
    it is passed over. A node script is the CLI as npm installs it."""
    try:
        with open(str(path), "rb") as f:
            head = f.read(128)
    except OSError:
        return True
    if not head.startswith(b"#!"):
        return False
    line = head.split(b"\n", 1)[0].decode("utf-8", "replace")
    return not re.search(r"\bnode\b", line)


def find_claude(env: Optional[dict] = None) -> Optional[Path]:
    """The real `claude`: GARRICK_CLAUDE when it is set, as it is given, then
    the documented places and PATH, each followed through its links and passed
    over when it is a shell wrapper."""
    env = os.environ if env is None else env
    given = env.get("GARRICK_CLAUDE")
    if given:
        p = Path(given).expanduser()
        return p if p.is_file() and os.access(str(p), os.X_OK) else None
    places = [Path(p).expanduser() for p in CLAUDE_PLACES]
    places += [Path(d) / "claude" for d in (env.get("PATH") or "").split(os.pathsep) if d]
    seen = set()
    for p in places:
        try:
            real = p.resolve()
        except OSError:
            continue
        if real in seen or not real.is_file() or not os.access(str(real), os.X_OK):
            continue
        seen.add(real)
        if not is_wrapper(real):
            return real
    return None


def child_env(claude: Path, env: Optional[dict] = None) -> dict:
    """The environment the CLI runs in: this one, with the CLI's own folder and
    the usual places for node on PATH, since a Mac app starts with a short one."""
    out = dict(os.environ if env is None else env)
    path = [str(claude.parent), "/opt/homebrew/bin", "/usr/local/bin"] + (out.get("PATH") or "/usr/bin:/bin").split(os.pathsep)
    out["PATH"] = os.pathsep.join(dict.fromkeys(p for p in path if p))
    out.pop("CLAUDECODE", None)       # a hand-off from inside a session is still a new session
    return out


def first_line(text: str) -> str:
    lines = [l.strip() for l in ANSI.sub("", text or "").splitlines() if l.strip()]
    return lines[-1][:240] if lines else ""


def stop_group(pid: int, waited=None) -> None:
    """Stop the process group `pid` leads, which is everything it started:
    politely first, then for good, so nothing it left behind lives on with no
    parent. `waited`, when given, is called after each signal to let the
    leader go and be reaped."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except OSError:                       # the group is gone already
            pass
        if waited is not None:
            waited()


def prime(claude: Path, folder: Path, prompt: str, timeout: Optional[float] = None,
          env: Optional[dict] = None) -> Tuple[str, str]:
    """The headless call that answers first: (its session id, its answer).
    HandOffError in plain words when it did not answer. It runs in a process
    group of its own, so what it started is stopped with it at the time."""
    timeout = PRIME_TIMEOUT if timeout is None else timeout
    try:
        p = subprocess.Popen([str(claude), "-p", prompt, "--output-format", "json"], cwd=str(folder),
                             env=child_env(claude, env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as e:
        raise HandOffError("Claude Code's command-line tool did not start: %s" % (e.strerror or e))
    try:
        stdout, stderr = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        def gone(grace=3.0):
            try:
                p.communicate(timeout=grace)
                return True
            except subprocess.TimeoutExpired:
                return False
        stop_group(p.pid, gone)
        raise HandOffError("Claude took longer than %s to answer, so nothing was opened. Try again in a moment."
                           % ("%d minutes" % round(timeout / 60) if timeout >= 120 else
                              "%d second%s" % (round(timeout), "" if round(timeout) == 1 else "s")))
    data = None
    for chunk in (stdout or "").strip().splitlines()[::-1] or [""]:
        try:
            data = json.loads(chunk)
            break
        except ValueError:
            continue
    if data is None:
        try:
            data = json.loads(stdout or "")
        except ValueError:
            data = None
    if not isinstance(data, dict) or not isinstance(data.get("session_id"), str):
        said = first_line(stderr) or first_line(stdout) or "it gave no answer"
        raise HandOffError("Claude did not answer, so nothing was opened: %s" % said)
    if data.get("is_error"):
        raise HandOffError("Claude did not answer, so nothing was opened: %s" % (first_line(str(data.get("result") or "")) or
                                                                                "it reported an error"))
    return data["session_id"], str(data.get("result") or "")


def exit_code(status: int) -> int:
    return os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else status >> 8


def in_terminal(argv: List[str], cwd: Path, env: dict, timeout: Optional[float] = None) -> Tuple[Optional[int], str]:
    """Run `argv` with a pseudo-terminal as its terminal: (its exit code, or
    None when it was stopped at `timeout`, and what it wrote, without colour).
    The deadline is read on every pass, so a child that never stops writing,
    a spinner, is stopped at the time too; and it is stopped with everything
    it started, since the terminal makes it the leader of a session and a
    process group of its own."""
    import pty
    timeout = DESKTOP_TIMEOUT if timeout is None else timeout
    pid, fd = pty.fork()
    if pid == 0:                                    # the child: the terminal is its own
        try:
            os.chdir(str(cwd))
            os.execve(argv[0], argv, env)
        finally:
            os._exit(127)
    out, code, open_ = b"", None, True
    deadline = time.time() + timeout

    def reaped() -> bool:
        nonlocal pid, code
        try:
            done, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            done, status = pid, 0
        if done:
            code, pid = exit_code(status), 0
        return not pid

    def stopped() -> Tuple[None, str]:
        def gone() -> bool:
            for _ in range(10):
                if reaped():
                    return True
                time.sleep(0.05)
            return False
        stop_group(pid, gone)
        if pid:
            try:
                os.waitpid(pid, 0)
            except OSError:
                pass
        return None, ANSI.sub("", out.decode("utf-8", "replace"))

    try:
        while True:
            if time.time() > deadline:
                return stopped()
            if open_:
                ready, _, _ = select.select([fd], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:                 # EIO: the child has closed its end
                        chunk = b""
                    if chunk:
                        out += chunk
                        continue
                    open_ = False                   # its end closed: wait for it to exit, as long as the time allows
            else:
                time.sleep(0.1)
            if reaped():
                break
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    return code, ANSI.sub("", out.decode("utf-8", "replace"))


def open_desktop(claude: Path, folder: Path, sid: str, timeout: Optional[float] = None,
                 env: Optional[dict] = None) -> str:
    """`claude --desktop --resume <sid>` in `folder`, under a pseudo-terminal.
    What it said, or LocalOff / HandOffError."""
    timeout = DESKTOP_TIMEOUT if timeout is None else timeout
    code, said = in_terminal([str(claude), "--desktop", "--resume", sid], folder, child_env(claude, env), timeout)
    if refused_locally(said):
        raise LocalOff(LOCAL_OFF_TITLE + " " + LOCAL_OFF)
    if code is None:
        raise HandOffError("Claude's desktop app did not say it had opened within %d seconds. If it did not open, "
                           "press Continue again." % round(timeout))
    if code != 0:
        raise HandOffError("Claude's desktop app did not open: %s" % (first_line(said) or "exit %d" % code))
    return said


# --------------------------------------------------------------------------- a work's files

def walk(folder: Path, limit: int = FILES_MAX, project: bool = False) -> Dict[str, list]:
    """The files under `folder`, by path from it: [mtime, size], at most
    `limit`. With `project`, the folder is the project's own, and Garrick's
    record of it is left out: its hub note and its Threads/. Hidden files and
    folders, git and archives are skipped everywhere."""
    out: Dict[str, list] = {}
    folder = Path(folder)
    if not folder.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(str(folder)):
        top = Path(dirpath) == folder
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_PARTS
                             and not (project and top and d == "Threads"))
        for name in sorted(filenames):
            if name.startswith(".") or name.endswith("~") or (project and top and name == folder.name + ".md"):
                continue
            p = Path(dirpath) / name
            try:
                st = p.stat()
            except OSError:
                continue
            out[p.relative_to(folder).as_posix()] = [int(st.st_mtime), st.st_size]
            if len(out) >= limit:
                return out
    return out


def compare(before: Optional[Dict[str, list]], now: Dict[str, list]) -> Dict[str, List[str]]:
    """What is new, changed and missing in `now` against `before`."""
    before = before or {}
    return {"new": sorted(p for p in now if p not in before),
            "changed": sorted(p for p in now if p in before and list(before[p]) != list(now[p])),
            "missing": sorted(p for p in before if p not in now)}
