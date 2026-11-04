"""Garrick.app's Finder right-click menu (#346) and the signature that keeps its
Accessibility grant (#361): extras/status/app/.

The link rules live in GarrickShared.swift, which the app and the extension both
compile, so a test compiles that file alone and asks it. The build is tested into
a scratch folder with make-app.sh --scratch, with stubs for tccutil and pluginkit
on the PATH: no test reads or changes this Mac's installed app, its permissions
or its extension election.

    python3 -m unittest test_status_finder
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "extras" / "status" / "app"
SWIFT = shutil.which("swiftc") if sys.platform == "darwin" else None

HARNESS = r"""
import Foundation
let a = CommandLine.arguments
switch a[1] {
case "openable": print(GarrickLink.openable(a[3], workspace: a[2])?.path ?? "nil")
case "parse":
    if let r = GarrickLink.parse(URL(string: a[3])!, token: a[2]) { print(r.app + "|" + r.folder) } else { print("nil") }
case "url": print(GarrickLink.url(app: a[2], folder: a[3], token: a[4])?.absoluteString ?? "nil")
case "same": print(GarrickLink.sameToken(a[2], a[3]))
default: print("?")
}
"""


@unittest.skipUnless(SWIFT, "needs macOS with the Swift compiler")
class TestLinkRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()).resolve()
        (cls.tmp / "main.swift").write_text(HARNESS)
        cls.exe = cls.tmp / "harness"
        subprocess.run([SWIFT, "-Onone", "-o", str(cls.exe), str(cls.tmp / "main.swift"), str(APP / "GarrickShared.swift")],
                       check=True, capture_output=True)
        ws = cls.ws = cls.tmp / "ws"
        mk = lambda rel, note=None: ((ws / rel).mkdir(parents=True, exist_ok=True),
                                     note and (ws / rel / (note + ".md")).write_text("---\n---\n"))
        mk("Zones/Work/Acme Corp", "Acme Corp")
        mk("Zones/Work/Acme Corp/Threads/Pricing", "Pricing")
        mk("Zones/Work/Acme Corp/Threads/Pricing/Sources")
        mk("Zones/Work/Acme Corp/Sources")
        mk("Zones/Work/Acme Corp/Deliverables")
        mk("Zones/Work/Inbox", "Inbox")                       # a note by the folder's name does not make it a project
        mk("Zones/Work/Birch & Co", "Birch & Co")
        mk("Zones/Work/Empty")                                # no hub note
        mk("Zones/Work/Acme Corp/Threads/NoNote")             # no thread note
        mk("Zones/Work/.shared/Acme Corp", "Acme Corp")
        mk("Wikis/Meetings", "Meetings")
        mk("Wikis/Meetings/x", "x")
        mk("Elsewhere/Jo", "Jo")                              # in the workspace, outside Zones/
        (cls.tmp / "out" / "Theo").mkdir(parents=True)        # outside the workspace
        (cls.tmp / "out" / "Theo" / "Theo.md").write_text("x")
        (ws / "Zones" / "Work" / "Leak").symlink_to(cls.tmp / "out" / "Theo")
        (ws / "Zones" / "Work" / "Alias").symlink_to(ws / "Zones" / "Work" / "Acme Corp")
        (ws / "Zones" / "Work" / "Acme Corp" / "Threads" / "Back").symlink_to(ws / "Elsewhere" / "Jo")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_h(self, *args):
        return subprocess.run([str(self.exe), *args], capture_output=True, text=True, check=True).stdout.strip()

    def openable(self, rel):
        path = rel if rel.startswith("/") else str(self.ws / rel)
        return self.run_h("openable", str(self.ws), path)

    def test_a_project_and_a_thread_are_accepted(self):
        self.assertEqual(str(self.ws / "Zones/Work/Acme Corp"), self.openable("Zones/Work/Acme Corp"))
        self.assertEqual(str(self.ws / "Zones/Work/Birch & Co"), self.openable("Zones/Work/Birch & Co"))
        self.assertEqual(str(self.ws / "Zones/Work/Acme Corp/Threads/Pricing"), self.openable("Zones/Work/Acme Corp/Threads/Pricing/"))

    def test_everything_else_is_refused(self):
        for rel in ("Zones/Work/Acme Corp/Sources", "Zones/Work/Acme Corp/Deliverables", "Zones/Work/Acme Corp/Threads",
                    "Zones/Work/Acme Corp/Threads/Pricing/Sources", "Zones/Work/Inbox", "Zones/Work", "Zones", ".",
                    "Wikis/Meetings", "Wikis/Meetings/x", "Elsewhere/Jo", "Zones/Work/Empty",
                    "Zones/Work/Acme Corp/Threads/NoNote", "Zones/Work/Nothing", "Zones/Work/.shared/Acme Corp",
                    "Zones/Work/Acme Corp/Acme Corp.md"):
            self.assertEqual("nil", self.openable(rel), rel)
        self.assertEqual("nil", self.run_h("openable", str(self.ws), ""))

    def test_a_folder_outside_the_workspace_is_refused(self):
        self.assertEqual("nil", self.openable(str(self.tmp / "out" / "Theo")))
        self.assertEqual("nil", self.openable("/tmp"))

    def test_a_symlink_out_of_the_workspace_is_refused(self):
        self.assertEqual("nil", self.openable("Zones/Work/Leak"))
        self.assertEqual("nil", self.openable("Zones/Work/Acme Corp/Threads/Back"))

    def test_a_symlink_inside_resolves_to_what_it_names(self):
        self.assertEqual(str(self.ws / "Zones/Work/Acme Corp"), self.openable("Zones/Work/Alias"))

    def test_dot_dot_cannot_climb_out(self):
        self.assertEqual("nil", self.openable("Zones/Work/Acme Corp/../../../Elsewhere/Jo"))
        self.assertEqual("nil", self.openable("Zones/Work/Acme Corp/Threads/Pricing/../../Sources"))
        self.assertEqual("nil", self.openable(str(self.ws / "Zones" / ".." / ".." / "out" / "Theo")))
        self.assertEqual(str(self.ws / "Zones/Work/Acme Corp"), self.openable("Zones/Work/Acme Corp/Sources/.."))

    def test_the_workspace_may_itself_be_reached_through_a_symlink(self):
        link = self.tmp / "link"
        link.symlink_to(self.ws)
        self.assertEqual(str(self.ws / "Zones/Work/Acme Corp"),
                         self.run_h("openable", str(link), str(link / "Zones/Work/Acme Corp")))

    def test_the_link_without_the_token_says_nothing(self):
        good = self.run_h("url", "cmux", str(self.ws / "Zones/Work/Acme Corp"), "abc123")
        self.assertEqual("cmux|" + str(self.ws / "Zones/Work/Acme Corp"), self.run_h("parse", "abc123", good))
        self.assertEqual("nil", self.run_h("parse", "abc124", good))                              # wrong token
        self.assertEqual("nil", self.run_h("parse", "abc12", good))
        self.assertEqual("nil", self.run_h("parse", "abc1234", good))
        self.assertEqual("nil", self.run_h("parse", "", "garrick://open?app=cmux&folder=%2Ftmp&t="))
        self.assertEqual("nil", self.run_h("parse", "abc123", "garrick://open?app=cmux&folder=%2Ftmp"))  # no token
        self.assertEqual("nil", self.run_h("parse", "abc123", "garrick://open?app=cmux&folder=%2Ftmp&t=abc123&t=abc123"))
        self.assertEqual("nil", self.run_h("parse", "abc123", "garrick://open?app=finder&folder=%2Ftmp&t=abc123"))
        self.assertEqual("nil", self.run_h("parse", "abc123", "garrick://run?app=cmux&folder=%2Ftmp&t=abc123"))
        self.assertEqual("nil", self.run_h("parse", "abc123", "other://open?app=cmux&folder=%2Ftmp&t=abc123"))

    def test_a_path_with_an_ampersand_a_plus_and_a_space_survives_the_link(self):
        folder = "/w/Zones/Work/Birch & Co+Theo/Threads/Jo's one"
        link = self.run_h("url", "claude", folder, "tok")
        self.assertNotIn(" ", link)
        self.assertEqual(1, link.count("&t="))
        self.assertEqual("claude|" + folder, self.run_h("parse", "tok", link))

    def test_tokens_compare_whole(self):
        self.assertEqual("true", self.run_h("same", "abc", "abc"))
        self.assertEqual("false", self.run_h("same", "abc", "abd"))
        self.assertEqual("false", self.run_h("same", "", ""))


class TestHandlerSource(unittest.TestCase):
    """What Garrick.swift does with a link that parsed, read from its source."""

    @classmethod
    def setUpClass(cls):
        cls.swift = (APP / "Garrick.swift").read_text(encoding="utf-8")
        cls.handler = cls.swift[cls.swift.index("func handleLink("):cls.swift.index("func applicationDidFinishLaunching")]

    def test_the_token_comes_first_and_a_refusal_before_it_is_silent(self):
        h = self.handler
        self.assertLess(h.index("GarrickLink.parse(url, token: linkToken)"), h.index("toast("))
        self.assertRegex(h, r"guard !checking, let link = GarrickLink\.parse\(url, token: linkToken\) else \{ return \}")

    def test_the_folder_the_opener_and_the_install_are_checked_before_launch(self):
        h = self.handler
        order = [h.index(x) for x in ("GarrickLink.openable(link.folder, workspace: workspace.path)", "launcherOn(link.app)",
                                      "urlForApplication(withBundleIdentifier: bundle)", "launch(link.app, folder.path")]
        self.assertEqual(sorted(order), order)

    def test_the_handler_is_the_apple_event_for_a_url(self):
        self.assertIn("forEventClass: AEEventClass(kInternetEventClass), andEventID: AEEventID(kAEGetURL)", self.swift)
        self.assertIn('info["GarrickLinkToken"] as? String ?? ""', self.swift)   # no token: every link refused

    def test_the_comparison_is_constant_time(self):
        shared = (APP / "GarrickShared.swift").read_text(encoding="utf-8")
        self.assertIn("diff |= x[i] ^ y[i]", shared)
        self.assertNotRegex(shared, r"token\s*==|==\s*token|given\s*==")


if __name__ == "__main__":
    unittest.main()
