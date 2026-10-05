"""Tests for the first-run setup: System/tools/probe.py, and the check that a
thread's resume point is more than the template's prompts.

    python3 -m unittest discover -s tests

Each workspace is a real install in a temporary folder, with HOME and git's
global config pointed at temporary files. The apps the probe looks for are
fake .app folders, so the result does not depend on the Mac running the tests.
"""

import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "install.py"
EXAMPLE = REPO / "examples" / "acme.json"
PROBE = REPO / "template" / "System" / "tools" / "probe.py"
sys.path.insert(0, str(REPO / "template" / "System" / "tools"))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load(PROBE, "garrick_probe")


def fake_app(folder, name, bundle=None):
    app = folder / (name + ".app")
    (app / "Contents").mkdir(parents=True)
    if bundle:
        with (app / "Contents" / "Info.plist").open("wb") as f:
            plistlib.dump({"CFBundleIdentifier": bundle}, f)
    return app


class Installed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        (base / "home").mkdir()
        gitconfig = base / "gitconfig"
        gitconfig.write_text("[user]\n\tname = Test Runner\n\temail = test@example.invalid\n"
                             "[commit]\n\tgpgsign = false\n")
        self.env = dict(os.environ, HOME=str(base / "home"), GIT_CONFIG_GLOBAL=str(gitconfig),
                        GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")
        self.patch = mock.patch.dict(os.environ, self.env)
        self.patch.start()
        self.base = base
        self.root = base / "ws"
        r = subprocess.run([sys.executable, str(INSTALL), "--config", str(EXAMPLE), "--target", str(self.root)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(0, r.returncode, r.stderr)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def run_tool(self, name, *args):
        return subprocess.run([sys.executable, str(self.root / "System" / "tools" / name), *args],
                              capture_output=True, text=True, env=self.env, cwd=str(self.root))


class TestFindApps(unittest.TestCase):
    def test_known_by_bundle_id_not_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            fake_app(folder, "Claude", "com.anthropic.claudefordesktop")
            fake_app(folder, "Codex", "com.openai.chat")       # not Codex, whatever its name
            fake_app(folder, "Obsidian")                       # no Info.plist: taken at its name
            found = probe.find_apps([folder])
            self.assertEqual({"claude", "obsidian"}, set(found))

    def test_nothing_found_is_said_plainly(self):
        found = {"macos": "15.0", "python": "3.9.6", "git": "git version 2.39.5", "apps": {}, "commands": {},
                 "git_identity": {"name": "", "email": "", "garrick_address": False}, "hooks_skipped": [],
                 "obsidian_vaults": [], "zones": []}
        said = probe.say(found)
        self.assertIn("Apps: none of Claude, Codex, ChatGPT, cmux or Obsidian.", said)
        self.assertIn("saving history will fail", said)


class TestProbe(Installed):
    def test_reads_this_workspace(self):
        apps = self.base / "Applications"
        apps.mkdir()
        fake_app(apps, "cmux", "com.cmuxterm.app")
        fake_app(apps, "Obsidian", "md.obsidian")
        (self.root / ".obsidian").mkdir()
        subprocess.run(["git", "-C", str(self.root / "Zones" / "Work"), "config", "core.hooksPath", "/elsewhere"],
                       check=True, env=self.env)
        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        tool = bin_dir / "codex"
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)
        with mock.patch.object(probe, "app_folders", return_value=[apps]), \
                mock.patch.object(probe.sys, "platform", "darwin"):
            found = probe.probe(self.root, path=str(bin_dir))
        self.assertEqual({"cmux", "obsidian"}, set(found["apps"]))
        self.assertEqual({"codex"}, set(found["commands"]))
        self.assertEqual(["Zones/Work"], found["hooks_skipped"])
        self.assertEqual(["the workspace"], found["obsidian_vaults"])
        self.assertEqual(["Personal", "Work"], found["zones"])
        self.assertEqual("test@example.invalid", found["git_identity"]["email"])
        said = probe.say(found)
        self.assertIn("Apps: cmux, Obsidian.", said)
        self.assertIn("git skips the wall check in: Zones/Work.", said)

    def test_command_line_changes_nothing(self):
        before = subprocess.run(["git", "-C", str(self.root), "status", "--porcelain"], capture_output=True,
                                text=True, env=self.env).stdout
        r = self.run_tool("probe.py", "--json")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("zones", json.loads(r.stdout))
        self.assertEqual(0, self.run_tool("probe.py").returncode)
        after = subprocess.run(["git", "-C", str(self.root), "status", "--porcelain"], capture_output=True,
                               text=True, env=self.env).stdout
        self.assertEqual(before, after)


class TestResumePoints(Installed):
    def resume_findings(self):
        r = self.run_tool("check.py", "--root", str(self.root), "--json")
        return [f for f in json.loads(r.stdout)["findings"]
                if f["check"] == "resume" and "still the template's" in f["message"]]

    def test_a_thread_from_the_template_is_flagged_until_filled_in(self):
        r = self.run_tool("scaffold.py", "project", "--zone", "Work", "--name", "Acme", "--party", "acme",
                          "--thread", "Pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        found = self.resume_findings()
        self.assertEqual(["Zones/Work/Acme/Threads/Pricing/Pricing.md"], [f["path"] for f in found])
        self.assertIn('say "wrap Pricing"', found[0]["message"])
        self.assertIn("next action", found[0]["message"])
        note = self.root / "Zones/Work/Acme/Threads/Pricing/Pricing.md"
        text = note.read_text()
        start = text.index("**Where it stands, <")
        end = text.index("\n---\n", start) + 1
        note.write_text(text[:start] + "**Where it stands, 6 October 2026.** First draft sent.\n\n"
                        "| | |\n|---|---|\n| Live artifact | none yet |\n| Rebuild with | nothing to rebuild |\n"
                        "| Next action | Sam: read Dana's answer |\n| Waiting on | Dana |\n| Deadline | none |\n\n"
                        + text[end:])
        self.assertEqual([], self.resume_findings())

    def test_a_parked_thread_is_left_alone(self):
        self.run_tool("scaffold.py", "project", "--zone", "Work", "--name", "Acme", "--party", "acme",
                      "--thread", "Pricing")
        note = self.root / "Zones/Work/Acme/Threads/Pricing/Pricing.md"
        note.write_text(note.read_text().replace("status: active", "status: parked", 1))
        self.assertEqual([], self.resume_findings())


if __name__ == "__main__":
    unittest.main()
