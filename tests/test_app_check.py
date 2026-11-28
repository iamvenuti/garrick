"""The app cases (tools/app_check.py) and the switch they drive the app by: what can be held without a window.

The cases themselves open a web view and run from the command line on a Mac:

    python3 tools/app_check.py

Here: that the tool starts only a scratch build, that it never names the installed app, that the app's test switch
is shut in any other build, and that it opens no port and asks for no permission.

    cd tests && python3 -m unittest test_app_check
"""

import importlib.util
import plistlib
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "app_check.py"
SWIFT = (ROOT / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")
MAKE_APP = (ROOT / "extras" / "status" / "app" / "make-app.sh").read_text(encoding="utf-8")


def load():
    spec = importlib.util.spec_from_file_location("app_check", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bundle(folder: Path, ident: str) -> Path:
    app = folder / "Garrick.app"
    (app / "Contents").mkdir(parents=True)
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleIdentifier": ident}, f)
    return app


class OnlyAScratchAppIsStarted(unittest.TestCase):
    def setUp(self):
        self.mod = load()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_an_app_without_the_scratch_identity_is_refused(self):
        for ident in ("local.garrick.status", "local.garrick.status.finder", "com.example.other", ""):
            with self.subTest(ident=ident):
                app = bundle(Path(self.tmp.name) / (ident or "none"), ident)
                with self.assertRaises(self.mod.Cannot) as caught:
                    self.mod.refuse_unless_scratch(app)
                self.assertIn("not a scratch build", str(caught.exception))

    def test_a_scratch_app_and_nothing_else_is_accepted(self):
        app = bundle(Path(self.tmp.name), "local.garrick.status.scratch")
        self.mod.refuse_unless_scratch(app)

    def test_a_folder_that_is_no_app_is_refused(self):
        with self.assertRaises(self.mod.Cannot):
            self.mod.refuse_unless_scratch(Path(self.tmp.name) / "nothing")

    def test_the_drive_will_not_start_an_app_that_is_not_scratch(self):
        app = bundle(Path(self.tmp.name), "local.garrick.status")
        with self.assertRaises(self.mod.Cannot):
            self.mod.Drive(app, None, Path(self.tmp.name) / "log")
        self.assertFalse((Path(self.tmp.name) / "log").exists(), "nothing was started")

    def test_the_tool_never_names_the_installed_app(self):
        text = TOOL.read_text(encoding="utf-8")
        for named in ("~/Applications", "/Applications", "Library/Application Support", "Library/Preferences",
                      'local.garrick.status"', "open -a", "osascript", "launchctl", "lsregister"):
            self.assertNotIn(named, text)
        # It builds with --scratch and starts the binary inside that build, never through Launch Services.
        self.assertIn('"--scratch"', text)
        self.assertNotIn("NSWorkspace", text)

    def test_the_tool_opens_no_port_and_asks_for_no_permission(self):
        text = TOOL.read_text(encoding="utf-8")
        for named in ("socket", "http.server", "tccutil", "Accessibility", "AppleEvent", "screencapture"):
            self.assertNotIn(named, text)

    def test_the_tool_runs_only_on_a_mac(self):
        self.assertIn('sys.platform != "darwin"', TOOL.read_text(encoding="utf-8"))

    def test_the_cases_the_plan_names_are_there(self):
        names = [n for n, _ in self.mod.CASES]
        for want in ("edit survives a build", "it survives a loss of focus", "one click sends one request",
                     "an older build that finishes last loses"):
            self.assertIn(want, names)


class TheTestSwitchIsShutInEveryOtherBuild(unittest.TestCase):
    def test_the_switch_needs_the_argument_and_the_scratch_identity(self):
        m = re.search(r'^let driving = (.+)$', SWIFT, re.M)
        self.assertIsNotNone(m)
        line = m.group(1)
        self.assertIn('CommandLine.arguments.contains("--drive")', line)
        self.assertIn('hasSuffix(".scratch")', line)
        self.assertIn('info["CFBundleIdentifier"]', line)

    def test_the_comment_beside_it_says_so(self):
        i = SWIFT.index("let driving =")
        note = SWIFT[max(0, i - 900):i]
        self.assertIn("scratch identity", note)
        self.assertIn("does nothing at all", note)

    def test_the_only_ways_in_are_behind_the_switch(self):
        # Every place the app listens or records for a case is under `driving`.
        for use in ("startDriving()", "driveSay(", "bridgeLog.append"):
            for m in re.finditer(re.escape(use), SWIFT):
                start = SWIFT.rfind("\n", 0, m.start())
                line = SWIFT[start + 1:SWIFT.find("\n", m.start())]
                if line.lstrip().startswith(("func ", "//")):
                    continue
                self.assertTrue("driving" in line or "driveSay" in line or "startDriving" in line, line)

    def test_a_normal_build_gets_the_regular_policy_and_no_listener(self):
        self.assertIn('app.setActivationPolicy(driving ? .accessory : checking ? .prohibited : .regular)', SWIFT)
        self.assertNotIn("NWListener", SWIFT)
        self.assertNotIn("socket(", SWIFT)

    def test_make_app_gives_a_normal_build_an_identity_with_no_scratch_suffix(self):
        self.assertIn('APP_ID="local.garrick.status"', MAKE_APP)
        self.assertRegex(MAKE_APP, r'if \[ "\$SCRATCH" = 1 \]; then APP_ID="\$APP_ID\.scratch"')

    def test_the_switch_adds_nothing_to_the_launcher(self):
        # No launcher, plist key or login item passes --drive.
        for path in (ROOT / "extras" / "status").rglob("*"):
            if path.suffix in (".py", ".sh", ".swift", ".plist") and path.name != "Garrick.swift":
                self.assertNotIn("--drive", path.read_text(encoding="utf-8", errors="ignore"), str(path))


if __name__ == "__main__":
    unittest.main()
