"""A fixture workspace and a fake home for the remote access tests. Invented names only; nothing here reads this Mac.

The workspace is the smallest one the extra's zone reading needs: a context file with a Zones table that has a Walled column, the
zone folders, and links to the repository's own System/tools and the extra itself (so `System/remote/service.py` is "installed").
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[3]
EXTRA = REPO / "extras" / "remote"
TOOLS = REPO / "template" / "System" / "tools"

ZONES = {"Work": True, "Home": False, "Garden": False, "Vault": True}      # zone -> walled


def mod(name: str):
    """A module of the extra, loaded the way the extra loads its own (one copy, under garrick_remote_<name>)."""
    key = "garrick_remote_" + name
    hit = sys.modules.get(key)
    if hit is None:
        spec = importlib.util.spec_from_file_location(key, str(EXTRA / (name + ".py")))
        hit = importlib.util.module_from_spec(spec)
        sys.modules[key] = hit
        try:
            spec.loader.exec_module(hit)
        except BaseException:
            sys.modules.pop(key, None)
            raise
    return hit


def make_workspace(root: Path, zones=None) -> Path:
    zones = ZONES if zones is None else zones
    rows = "\n".join("| %s | Things of %s | %s |" % (z, z.lower(), "yes" if walled else "no") for z, walled in zones.items())
    (root / "System").mkdir(parents=True)
    (root / "System" / "context.md").write_text(
        "# Context\n\n## Me\n\nJo Example. An invented owner.\n\n## Zones\n\n| Zone | Holds | Walled |\n|---|---|---|\n%s\n" % rows,
        encoding="utf-8")
    os.symlink(str(TOOLS), str(root / "System" / "tools"))
    os.symlink(str(EXTRA), str(root / "System" / "remote"))
    for z in zones:
        (root / "Zones" / z).mkdir(parents=True)
    return root


class RemoteCase(unittest.TestCase):
    """A fake home, a fake state folder, a workspace, and nothing of this Mac."""

    zones = None

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="garrick-remote-")
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.home = base / "home"
        self.home.mkdir()
        self.state_dir = base / "state"
        self.ws = make_workspace(base / "ws", self.zones)
        self._env = dict(os.environ)
        os.environ["HOME"] = str(self.home)
        os.environ["GARRICK_REMOTE_HOME"] = str(self.state_dir)
        os.environ.pop("GARRICK_REMOTE_LAUNCHCTL", None)
        os.environ["GARRICK_REMOTE_RELAY_CLI"] = str(base / "no-relay-here")          # a test never reaches this Mac's own relay
        self.addCleanup(self._restore)
        self.state, self.store = mod("state"), mod("store")
        # the background setup would download an interpreter: a test only records that it was asked for
        self.spawned = []
        self._real_spawn = mod("settings_actions").spawn
        mod("settings_actions").spawn = lambda *a, **k: self.spawned.append(a)
        self.addCleanup(lambda: setattr(mod("settings_actions"), "spawn", self._real_spawn))

    def _restore(self):
        os.environ.clear()
        os.environ.update(self._env)

    def role(self, role: str) -> None:
        folder = self.home / ".config" / "garrick"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "machine.json").write_text(json.dumps({"role": role}), encoding="utf-8")

    def turn_on(self, address: str = "https://home.example.test", adapter: str = "own") -> None:
        self.state.set_address(address, adapter)
        self.state.set_status("on")
