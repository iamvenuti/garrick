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

import importlib.util
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
case "phrase": print(GarrickLink.phrase(for: URL(fileURLWithPath: a[2], isDirectory: true)))
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
        mk("Zones/Work/Sources/Threads/X", "X")                # a thread under a folder that is not a project
        mk("Zones/Work/Sources", "Sources")
        mk("Zones/Work/Inbox/Threads/X", "X")
        mk("Zones/Work/NoHub/Threads/X", "X")                  # a project folder without its hub note
        mk("Zones/Work/DirHub/DirHub.md/Threads/X", "X")       # a hub that is a folder
        mk("Zones/Work/DirHub/Threads/X", "X")
        mk("Zones/Work/DirNote/DirNote.md")                    # a note that is a folder
        mk("Zones/Work/Acme Corp/Threads/Dir/Dir.md")
        mk("Zones/Work/Bad\nName", "Bad\nName")               # a name with a newline would become prompt text
        mk("Zones/Work/Acme Corp/Threads/Tab\tX", "Tab\tX")
        mk("Zones/Work/Sep\u2028Name", "Sep\u2028Name")
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

    def test_a_thread_needs_a_real_project_and_real_notes(self):
        for rel in ("Zones/Work/Sources/Threads/X", "Zones/Work/Inbox/Threads/X", "Zones/Work/NoHub/Threads/X",
                    "Zones/Work/DirHub/Threads/X", "Zones/Work/DirNote", "Zones/Work/Acme Corp/Threads/Dir"):
            self.assertEqual("nil", self.openable(rel), rel)

    def test_a_name_with_a_control_character_is_refused(self):
        for rel in ("Zones/Work/Bad\nName", "Zones/Work/Acme Corp/Threads/Tab\tX", "Zones/Work/Sep\u2028Name"):
            self.assertEqual("nil", self.openable(rel), repr(rel))

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

    def test_the_phrase_names_the_project_of_a_thread(self):
        self.assertEqual("open Acme Corp, Pricing", self.run_h("phrase", str(self.ws / "Zones/Work/Acme Corp/Threads/Pricing")))
        self.assertEqual("open Acme Corp", self.run_h("phrase", str(self.ws / "Zones/Work/Acme Corp")))
        self.assertEqual("open Birch & Co", self.run_h("phrase", str(self.ws / "Zones/Work/Birch & Co")))

    def test_tokens_compare_whole(self):
        self.assertEqual("true", self.run_h("same", "abc", "abc"))
        self.assertEqual("false", self.run_h("same", "abc", "abd"))
        self.assertEqual("false", self.run_h("same", "", ""))


def build_app(dest, home, extra_env=None, *flags):
    """make-app.sh into a scratch folder, in a home of its own, with tccutil, pluginkit and lsregister
    stubs that only write down that they were called. Returns the log of those calls."""
    home = Path(home)
    stubs = home / "stubs"
    stubs.mkdir(exist_ok=True)
    log = home / "calls.log"
    for name in ("tccutil", "pluginkit"):
        stub = stubs / name
        stub.write_text('#!/bin/sh\necho "%s $*" >> "%s"\n[ "$1" = "-m" ] && [ -n "$STUB_ENABLED" ] && echo "+    local.garrick.status.finder(1.0)"\nexit 0\n' % (name, log))
        stub.chmod(0o755)
    ws = home / "ws"
    (ws / "Zones").mkdir(parents=True, exist_ok=True)
    (ws / "System").mkdir(exist_ok=True)
    (ws / "System" / "rules.md").write_text("x")
    env = dict(os.environ, HOME=str(home), PATH=str(stubs) + os.pathsep + os.environ["PATH"], GARRICK_SWIFT_OPT="-Onone",
               GARRICK_LSREGISTER=str(stubs / "lsregister"), GARRICK_WORKSPACE=str(ws))
    (stubs / "lsregister").write_text('#!/bin/sh\necho "lsregister $*" >> "%s"\n' % log)
    (stubs / "lsregister").chmod(0o755)
    env.update(extra_env or {})
    done = subprocess.run(["bash", str(APP / "make-app.sh"), "--dest", str(dest), *flags], env=env, capture_output=True, text=True, timeout=600)
    return done, (log.read_text() if log.exists() else "")


def plist(path):
    with open(path, "rb") as f:
        return plistlib.load(f)


@unittest.skipUnless(SWIFT, "needs macOS with the Swift compiler")
class TestScratchBuild(unittest.TestCase):
    """make-app.sh --scratch builds the app and its Finder extension into a folder and
    touches nothing else: not the installed app, the permissions, the extension list or Launch Services."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()).resolve()
        cls.dest = cls.tmp / "out"
        cls.done, cls.calls = build_app(cls.dest, cls.tmp, None, "--scratch")
        cls.app = cls.dest / "Garrick.app"
        cls.appex = cls.app / "Contents" / "PlugIns" / "GarrickFinder.appex"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_it_built(self):
        self.assertEqual(0, self.done.returncode, self.done.stderr)
        self.assertEqual(str(self.app), self.done.stdout.strip())
        self.assertTrue(self.appex.is_dir())

    def test_the_app_and_the_extension_verify(self):
        done = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(self.app)], capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)

    def test_each_is_signed_with_a_requirement_that_does_not_change(self):
        def requirement(path):
            done = subprocess.run(["codesign", "-d", "-r-", str(path)], capture_output=True, text=True)
            return re.search(r"designated => (.*)", done.stdout + done.stderr).group(1)
        self.assertEqual('identifier "local.garrick.status.scratch"', requirement(self.app))     # not the installed app's
        self.assertEqual('identifier "local.garrick.status.finder.scratch"', requirement(self.appex))

    def test_the_extension_carries_the_app_icon_for_its_menu_item(self):
        icon = self.appex / "Contents" / "Resources" / "AppIcon.icns"
        self.assertEqual((self.app / "Contents" / "Resources" / "AppIcon.icns").read_bytes(), icon.read_bytes())
        self.assertIn('Bundle.main.image(forResource: "AppIcon")', (APP / "GarrickFinder.swift").read_text())

    def test_the_extension_has_the_sandbox_and_nothing_else(self):
        out = subprocess.run(["codesign", "-d", "--entitlements", "-", "--xml", str(self.appex)], capture_output=True).stdout
        self.assertEqual({"com.apple.security.app-sandbox": True}, plistlib.loads(out[out.index(b"<?xml"):]))

    def test_the_app_registers_the_link_and_both_hold_the_same_token(self):
        app, ext = plist(self.app / "Contents" / "Info.plist"), plist(self.appex / "Contents" / "Info.plist")
        self.assertEqual([{"CFBundleURLName": "Garrick link", "CFBundleURLSchemes": ["garrick"]}], app["CFBundleURLTypes"])
        self.assertRegex(app["GarrickLinkToken"], r"^[0-9a-f]{32}$")
        self.assertEqual(app["GarrickLinkToken"], ext["GarrickLinkToken"])
        self.assertEqual(app["GarrickFinderState"], ext["GarrickFinderState"])
        self.assertEqual(str(self.dest / ".finder-state"), app["GarrickFinderState"])    # a scratch build keeps its own
        self.assertEqual(app["GarrickWorkspace"], ext["GarrickWorkspace"])
        self.assertEqual({"NSExtensionPointIdentifier": "com.apple.FinderSync", "NSExtensionPrincipalClass": "GarrickFinder.GarrickFinder"},
                         ext["NSExtension"])
        self.assertEqual("XPC!", ext["CFBundlePackageType"])
        self.assertEqual("local.garrick.status.scratch", app["CFBundleIdentifier"])      # its own defaults, beside the installed app
        self.assertEqual("local.garrick.status.finder.scratch", app["GarrickFinderId"])
        self.assertEqual("local.garrick.status.finder.scratch", ext["CFBundleIdentifier"])

    def test_every_build_has_a_token_of_its_own(self):
        other = self.tmp / "again"
        done, _ = build_app(other, self.tmp, None, "--scratch")
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertNotEqual(plist(self.app / "Contents" / "Info.plist")["GarrickLinkToken"],
                            plist(other / "Garrick.app" / "Contents" / "Info.plist")["GarrickLinkToken"])

    def test_nothing_outside_the_folder_was_touched(self):
        self.assertEqual("", self.calls)                                  # no tccutil, no pluginkit, no lsregister
        self.assertFalse((self.tmp / "Library" / "Application Support" / "Garrick").exists())


@unittest.skipUnless(SWIFT, "needs macOS with the Swift compiler")
class TestInstallBuild(unittest.TestCase):
    """A build that is not --scratch is an install: it makes the extension known to macOS, switches it
    off and on only for a user who had it on, and resets Accessibility once, only when it replaces an
    app signed the old way. All of it against stubs in a home of its own."""

    def test_the_install_steps(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t).resolve()
            dest, log = tmp / "Applications", tmp / "calls.log"
            appex = dest / "Garrick.app" / "Contents" / "PlugIns" / "GarrickFinder.appex"

            done, calls = build_app(dest, tmp)                    # first build: nothing there, extension never turned on
            self.assertEqual(0, done.returncode, done.stderr)
            self.assertEqual(["pluginkit -m -i local.garrick.status.finder", "lsregister -f %s" % (dest / "Garrick.app"),
                              "pluginkit -a %s" % appex], calls.splitlines())

            log.unlink()
            done, calls = build_app(dest, tmp, {"STUB_ENABLED": "1"})      # the user had it on: off and on again
            self.assertEqual(0, done.returncode, done.stderr)
            self.assertEqual(["pluginkit -m -i local.garrick.status.finder", "lsregister -f %s" % (dest / "Garrick.app"),
                              "pluginkit -a %s" % appex, "pluginkit -e ignore -i local.garrick.status.finder",
                              "pluginkit -e use -i local.garrick.status.finder"], calls.splitlines())     # same requirement: no tccutil

            subprocess.run(["codesign", "--force", "--sign", "-", str(dest / "Garrick.app")], check=True, capture_output=True)
            log.unlink()
            done, calls = build_app(dest, tmp)                    # an app signed the old way is replaced
            self.assertEqual(0, done.returncode, done.stderr)
            self.assertEqual(["tccutil reset Accessibility local.garrick.status"], [c for c in calls.splitlines() if c.startswith("tccutil")])
            self.assertFalse([c for c in calls.splitlines() if "-e " in c])      # never enabled for a user who had it off
            self.assertIn("Accessibility was reset", done.stderr)


class TestByFolder(unittest.TestCase):
    """page_action.by_folder, which the desk's open goes through, holds the same rule as the Finder menu."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("page_action_finder", REPO / "extras" / "status" / "page_action.py")
        self.pa = importlib.util.module_from_spec(spec)
        sys.modules["page_action_finder"] = self.pa
        spec.loader.exec_module(self.pa)
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        z = self.tmp / "Zones" / "Work"
        def mk(rel, note=None):
            (z / rel).mkdir(parents=True)
            if note:
                (z / rel / (note + ".md")).write_text("x")
        mk("Acme Corp", "Acme Corp")
        mk("Acme Corp/Threads/Pricing", "Pricing")
        mk("Sources/Threads/X", "X")
        mk("Inbox/Threads/X", "X")
        mk("NoHub/Threads/X", "X")
        mk("Bad\nName", "Bad\nName")
        mk("Acme Corp/Threads/Tab\tX", "Tab\tX")
        mk("Acme Corp/Threads/NoNote")
        mk("Acme Corp/Threads/DirNote/DirNote.md")

    def folder(self, rel):
        req = {"verb": "open", "folder": str(self.tmp / "Zones" / "Work" / rel)}
        return req, self.pa.by_folder(self.tmp, req)

    def test_a_project_and_a_thread_are_accepted(self):
        req, prompt = self.folder("Acme Corp")
        self.assertEqual((None, "Acme Corp"), (prompt, req["project"]))
        req, prompt = self.folder("Acme Corp/Threads/Pricing")
        self.assertEqual((None, "Pricing"), (prompt, req["thread"]))

    def test_a_thread_of_no_project_a_missing_note_or_a_control_character_is_refused(self):
        for rel in ("Sources/Threads/X", "Inbox/Threads/X", "NoHub/Threads/X", "Bad\nName", "Acme Corp/Threads/Tab\tX",
                    "Acme Corp/Threads/NoNote", "Acme Corp/Threads/DirNote", "Acme Corp/Sources", "Acme Corp/Threads"):
            with self.subTest(rel=rel), self.assertRaises(self.pa.Refused):
                self.folder(rel)


@unittest.skipUnless(SWIFT, "needs macOS with the Swift compiler")
class TestCustomDest(unittest.TestCase):
    """A build into a folder that is not an Applications folder must not act on macOS's lists, which are by identifier."""

    def test_no_reset_and_no_extension_steps(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t).resolve()
            dest = tmp / "Elsewhere"
            done, calls = build_app(dest, tmp, {"STUB_ENABLED": "1"})
            self.assertEqual(0, done.returncode, done.stderr)
            self.assertEqual(["lsregister -f %s" % (dest / "Garrick.app")], calls.splitlines())
            self.assertIn("is not an Applications folder, so the Accessibility reset and the Finder extension steps are skipped", done.stderr)
            subprocess.run(["codesign", "--force", "--sign", "-", str(dest / "Garrick.app")], check=True, capture_output=True)
            (tmp / "calls.log").unlink()
            done, calls = build_app(dest, tmp, {"STUB_ENABLED": "1"})      # an app signed the old way, replaced here
            self.assertEqual(0, done.returncode, done.stderr)
            self.assertEqual(["lsregister -f %s" % (dest / "Garrick.app")], calls.splitlines())

    def test_the_quit_check_matches_the_start_of_a_command_line(self):
        script = (APP / "make-app.sh").read_text(encoding="utf-8")
        self.assertIn("index($0, p) == 1", script)
        self.assertNotIn("grep -qF \"$DEST", script)


@unittest.skipUnless(SWIFT, "needs macOS with the Swift compiler")
class TestExtensionSignature(unittest.TestCase):
    def test_an_extension_that_does_not_sign_is_not_shipped(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t).resolve()
            stubs = tmp / "stubs"
            stubs.mkdir()
            (stubs / "codesign").write_text('#!/bin/sh\ncase "$*" in *--entitlements*) exit 1;; esac\nexec /usr/bin/codesign "$@"\n')
            (stubs / "codesign").chmod(0o755)
            done, calls = build_app(tmp / "out", tmp, {"PATH": str(stubs) + os.pathsep + os.environ["PATH"]}, "--scratch")
            self.assertEqual(0, done.returncode, done.stderr)
            self.assertIn("the app has no Finder menu: its signature failed", done.stderr)
            self.assertFalse((tmp / "out" / "Garrick.app" / "Contents" / "PlugIns").exists())
            ok = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(tmp / "out" / "Garrick.app")], capture_output=True)
            self.assertEqual(0, ok.returncode)


class TestUpdateSaysWhatHappened(unittest.TestCase):
    def test_the_place_comes_from_stdout_and_a_notice_follows_as_a_sentence(self):
        sys.path.insert(0, str(REPO))
        self.addCleanup(sys.path.remove, str(REPO))
        import update
        with tempfile.TemporaryDirectory() as t:
            stub = Path(t) / "make-app.sh"
            stub.write_text('#!/bin/sh\necho "make-app: Accessibility was reset for Garrick once; allow it again when macOS asks." >&2\necho /Applications/Garrick.app\n')
            stub.chmod(0o755)
            code, said = update.make_app([str(stub)])
            self.assertEqual(0, code)
            self.assertEqual("/Applications/Garrick.app. Accessibility was reset for Garrick once; allow it again when macOS asks", said)
            self.assertEqual("Rebuilt Garrick.app: %s." % said, update.say_make_app([str(stub)]))
            stub.write_text('#!/bin/sh\necho /Applications/Garrick.app\n')
            self.assertEqual((0, "/Applications/Garrick.app"), update.make_app([str(stub)]))
            stub.write_text('#!/bin/sh\necho "make-app: no Swift compiler" >&2\nexit 1\n')
            self.assertEqual((1, "make-app: no Swift compiler"), update.make_app([str(stub)]))


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
                                      "openerInstalled(link.app)", "guard let now = GarrickLink.openable(link.folder, workspace: workspace.path)",
                                      "launch(link.app, now.path")]
        self.assertEqual(sorted(order), order)

    def test_the_link_opens_by_the_phrase_with_the_project(self):
        self.assertIn("phrase: GarrickLink.phrase(for: now))", self.handler)
        self.assertNotIn("lastPathComponent", self.handler)

    def test_the_handler_is_the_apple_event_for_a_url(self):
        self.assertIn("forEventClass: AEEventClass(kInternetEventClass), andEventID: AEEventID(kAEGetURL)", self.swift)
        self.assertIn('info["GarrickLinkToken"] as? String ?? ""', self.swift)   # no token: every link refused

    def test_the_only_files_the_app_writes_for_finder_are_empty_markers_in_its_state_folder(self):
        """test_status's 'the app changes no file' reads FileManager.default.x; the markers go through `fm`, so they are held here."""
        body = self.swift[self.swift.index("func syncFinderOpeners()"):self.swift.index("// One request to ask.py, running")]
        self.assertEqual(["fm.createFile(atPath: file, contents: Data())"], re.findall(r"fm\.createFile\([^\n]*\)", body))
        self.assertEqual(1, body.count("removeItem("))
        self.assertIn("try? fm.removeItem(atPath: file)", body)
        self.assertIn('dir.appendingPathComponent(k).path', body)
        self.assertIn('for k in ["cmux", "claude", "codex"]', body)

    def test_settings_says_whether_the_extension_is_on_and_opens_the_pane(self):
        status = (REPO / "extras" / "status" / "status.py").read_text(encoding="utf-8")
        self.assertIn('id="menu-finder"', status)
        self.assertIn("Open Login Items &amp; Extensions", status)
        self.assertIn("tell(e,{finder:'settings'})", status)
        self.assertIn('"finder": finderStatus', self.swift)
        self.assertIn("x-apple.systempreferences:com.apple.LoginItems-Settings.extension", self.swift)
        self.assertIn('request["finder"] as? String == "settings"', self.swift)
        self.assertIn('arguments = ["-m", "-i", finderId]', self.swift)       # read, never set: the app never enables it

    def test_the_toast_names_the_earlier_build(self):
        self.assertIn("The permission may belong to an earlier build of Garrick. In System Settings", self.swift)
        self.assertIn("remove Garrick with the minus button, then allow it again", self.swift)

    def test_the_comparison_is_constant_time(self):
        shared = (APP / "GarrickShared.swift").read_text(encoding="utf-8")
        self.assertIn("diff |= x[i] ^ y[i]", shared)
        self.assertNotRegex(shared, r"token\s*==|==\s*token|given\s*==")


if __name__ == "__main__":
    unittest.main()
