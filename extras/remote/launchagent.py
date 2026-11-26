#!/usr/bin/env python3
"""launchagent.py: starts the remote access service when you log in, while remote access is on (preview).

A LaunchAgent in `~/Library/LaunchAgents/`, label `garrick.remote`. It runs the extra's own interpreter on `service.py`. The agent
is written and loaded when remote access is turned on or resumed, and unloaded and removed when it is turned off. Pause leaves it
loaded: the service reads the switch on every call, so a pause closes access at once and a resume needs no restart.

`launchctl` is passed in, so a test replaces it with a fake and never touches the real launchd. HOME is read when called, so a test
points it at a fake home folder. Standard library only; runs on the Python that macOS ships (3.9).
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

sys.dont_write_bytecode = True

LABEL = "garrick.remote"
LAUNCHCTL_ENV = "GARRICK_REMOTE_LAUNCHCTL"      # a test points it at a fake


def plist_path() -> Path:
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return Path(home) / "Library" / "LaunchAgents" / (LABEL + ".plist")


def written() -> bool:
    return plist_path().is_file()


def launchctl() -> str:
    return os.environ.get(LAUNCHCTL_ENV) or "/bin/launchctl"


def _domain() -> str:
    return "gui/%d" % os.getuid()


def program(workspace: Path, python: Path, service: Path) -> List[str]:
    return [str(python), str(service), "--workspace", str(workspace)]


def make_plist(workspace: Path, python: Path, service: Path, log_dir: Path) -> dict:
    """The agent: start at login, start again after a crash, not after a clean exit. The service exits cleanly when remote access is
    off or paused or this computer is a roaming one, so launchd does not restart it into a loop."""
    env = {}
    if os.environ.get("GARRICK_REMOTE_HOME"):
        env["GARRICK_REMOTE_HOME"] = os.environ["GARRICK_REMOTE_HOME"]
    if os.environ.get("HOME"):
        env["HOME"] = os.environ["HOME"]
    out = {"Label": LABEL, "ProgramArguments": program(workspace, python, service), "RunAtLoad": True,
           "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": 30, "ProcessType": "Background",
           "StandardOutPath": str(log_dir / "launchd.out"), "StandardErrorPath": str(log_dir / "launchd.err")}
    if env:
        out["EnvironmentVariables"] = env
    return out


def install(workspace: Path, python: Path, service: Path, log_dir: Path, runner: Callable = subprocess.run) -> dict:
    """Write the agent and load it. {"ok": True} or {"ok": False, "say": plain sentence}."""
    path = plist_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        data = plistlib.dumps(make_plist(workspace, python, service, log_dir))
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(str(tmp), str(path))
    except OSError:
        return {"ok": False, "say": "Garrick could not write the start-up file, so the service will not start by itself."}
    runner([launchctl(), "bootout", _domain() + "/" + LABEL], capture_output=True, text=True)       # a stale copy, if any
    r = runner([launchctl(), "bootstrap", _domain(), str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        return {"ok": False, "say": "The service did not start. Turn remote access off and on again."}
    return {"ok": True}


def remove(runner: Callable = subprocess.run) -> bool:
    """Unload the agent and remove its file. True when nothing is left."""
    runner([launchctl(), "bootout", _domain() + "/" + LABEL], capture_output=True, text=True)
    try:
        plist_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


def loaded(runner: Callable = subprocess.run) -> bool:
    try:
        return runner([launchctl(), "print", _domain() + "/" + LABEL], capture_output=True, text=True).returncode == 0
    except OSError:
        return False
