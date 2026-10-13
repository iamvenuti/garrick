"""The cmux extra's sidebar (#22): what each tab is called, its dot, where
the mark leads, and that the file owes nothing to the templates cmux ships.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
SIDEBAR = REPO / "extras" / "cmux" / "garrick-sidebar.js"
TEMPLATES = Path("/Applications/cmux.app/Contents/Resources/CmuxSettings_CmuxSettings.bundle/Contents/Resources/CustomSidebarTemplates")

# Runs the sidebar with cmux's globals stubbed, then calls its helpers.
HARNESS = r"""
const vm = require("vm");
const [code, calls] = JSON.parse(process.argv[1]);
const ctx = { sidebar: () => {} };
vm.createContext(ctx);
vm.runInContext(code, ctx);
process.stdout.write(JSON.stringify(calls.map(([f, args]) => ctx[f](...args))));
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestHelpers(unittest.TestCase):
    def call(self, *calls):
        done = subprocess.run(["node", "-e", HARNESS, json.dumps([SIDEBAR.read_text(encoding="utf-8"), list(calls)])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_a_tab_is_called_by_its_work(self):
        folder = "/Users/sam/Garrick/Zones/Work/Acme Review/Threads/Pricing"
        names = self.call(
            ["tabName", [{"title": "Pricing terms", "directory": folder}]],          # a real title stays
            ["tabName", [{"title": "✳ Claude Code", "directory": folder}]],           # the program, after its spinner
            ["tabName", [{"title": "codex", "directory": folder}]],
            ["tabName", [{"title": "-zsh", "directory": folder}]],
            ["tabName", [{"title": "~/Garrick/Zones/Work", "directory": folder + "/"}]],   # a path
            ["tabName", [{"title": "", "directory": ""}]],
        )
        self.assertEqual(["Pricing terms", "Pricing", "Pricing", "Pricing", "Pricing", "Tab"], names)

    def test_the_dot(self):
        w = {"agents": [{"panelId": "a", "status": "working"}, {"panelId": "b", "status": "needs_input"}]}
        dots = self.call(["dot", [w, {"id": "a", "hasUnread": True}]],              # working wins
                         ["dot", [w, {"id": "b", "hasUnread": False}]],             # a finished turn alone is grey
                         ["dot", [w, {"id": "b", "hasUnread": True}]],
                         ["dot", [{}, {"id": "c"}]])
        self.assertEqual(["#8EB1F5", "#8A8F98", "orange", "#8A8F98"], dots)

    def test_a_workspace_shows_its_colour(self):
        # The desk colours a zone's workspace (#67); the bar before its name shows it, or nothing.
        bars = self.call(["swatch", [{"color": "#006B6B"}]], ["swatch", [{"color": "#006b6b80"}]],
                         ["swatch", [{}]], ["swatch", [{"color": "teal"}]], ["swatch", [{"color": "#06B"}]])
        self.assertEqual(["#006B6B", "#006b6b80", "clear", "clear", "clear"], bars)

    def test_the_mark_finds_the_status_page(self):
        pages = self.call(
            ["statusPage", [[{"directory": "/tmp", "tabs": [{"directory": "/Users/sam/My Work/Zones/Work/Acme Review"}]}]]],
            ["statusPage", [[{"directory": "/Users/sam/Garrick/System", "tabs": []}]]],
            ["statusPage", [[{"directory": "/Users/sam/code", "tabs": [{"directory": "/Users/sam/code/app"}]}]]],
            ["statusPage", [[]]],
        )
        self.assertEqual(["file:///Users/sam/My%20Work/System/generated/status.html",
                          "file:///Users/sam/Garrick/System/generated/status.html", None, None], pages)


class TestCleanRoom(unittest.TestCase):
    def test_nothing_from_cmuxs_templates(self):
        # cmux's templates are GPL-3.0-or-later; this file stays MIT. No line of
        # any length that says something is shared with one of them.
        if not TEMPLATES.is_dir():
            self.skipTest("cmux's templates are not on this machine")
        ours = {l.strip() for l in SIDEBAR.read_text(encoding="utf-8").splitlines() if len(l.strip()) >= 25}
        for template in TEMPLATES.iterdir():
            theirs = {l.strip() for l in template.read_text(encoding="utf-8", errors="replace").splitlines()}
            self.assertEqual(set(), ours & theirs, template.name)

    def test_documented_with_its_install_step(self):
        guide = (REPO / "docs" / "extras" / "cmux.md").read_text(encoding="utf-8")
        self.assertIn("extras/cmux/garrick-sidebar.js", guide)
        self.assertIn("cmux sidebar select garrick", guide)
        self.assertIn("cmux.md#a-sidebar", (REPO / "docs" / "extras" / "index.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
