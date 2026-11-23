"""A new session in the Claude or Codex desktop app (#652), the one row for each app since 0.80.0 (#682): the build check,
the link, its refusals, the fallback, and a 0.79.0 settings file read into the one row.

    python3 -m unittest test_new_session

Nothing here opens an app or runs an assistant. The build check reads app bundles a test makes in a temporary
folder; the link is page_action.py's session-url, which only reads; the fallback is GarrickShared.swift's, compiled
with a stub for the opener, the app and the clipboard.
"""

from __future__ import annotations

import importlib.util
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
from fixtures import build_workspace, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STATUS = REPO / "extras" / "status"
APP = STATUS / "app"
SWIFT = shutil.which("swiftc") if sys.platform == "darwin" else None


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pa = load("garrick_page_action_ns", STATUS / "page_action.py")
status = load("garrick_status_ns", STATUS / "status.py")


def bundle(folder: Path, name: str, ident: str, schemes=None) -> Path:
    app = folder / (name + ".app")
    (app / "Contents").mkdir(parents=True)
    info = {"CFBundleIdentifier": ident}
    if schemes is not None:
        info["CFBundleURLTypes"] = [{"CFBundleURLSchemes": list(schemes)}]
    with (app / "Contents" / "Info.plist").open("wb") as f:
        plistlib.dump(info, f)
    return app


@unittest.skipUnless(sys.platform == "darwin", "the launchers are Mac apps")
class TestBuildCheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.apps = Path(self._tmp.name) / "Applications"

    def tearDown(self):
        self._tmp.cleanup()

    def test_each_app_that_takes_its_scheme_is_offered(self):
        bundle(self.apps, "Claude", "com.anthropic.claudefordesktop", ["claude"])
        bundle(self.apps, "Codex", "com.openai.codex", ["codex"])
        state = status.launcher_state([self.apps])
        self.assertIsNone(state["claude"])
        self.assertIsNone(state["codex"])
        self.assertIn("claude", status.launchers_installed([self.apps]))
        self.assertIn("codex", status.launchers_installed([self.apps]))

    def test_it_needs_no_command_line_tool(self):
        bundle(self.apps, "Codex", "com.openai.codex", ["codex"])          # no launcher inside the bundle
        state = status.launcher_state([self.apps])
        self.assertIsNone(state["codex"])                                  # the folder-only route left with its launcher (#682)
        self.assertFalse(hasattr(status, "CODEX_CLI"))

    def test_an_app_without_the_scheme_is_greyed_with_the_reason(self):
        bundle(self.apps, "Claude", "com.anthropic.claudefordesktop")                       # no URL types at all
        bundle(self.apps, "Codex", "com.openai.codex", ["https", "other"])                  # another scheme
        state = status.launcher_state([self.apps])
        self.assertEqual("Installed, but this version cannot open a new session: update the Claude app", state["claude"])
        self.assertEqual("Installed, but this version cannot open a new session: update the Codex app", state["codex"])
        self.assertNotIn("claude", status.launchers_installed([self.apps]))
        self.assertNotIn("codex", status.launchers_installed([self.apps]))

    def test_a_scheme_is_read_whatever_its_case_and_a_broken_plist_fails_closed(self):
        bundle(self.apps, "Claude", "com.anthropic.claudefordesktop", ["Claude"])
        self.assertIsNone(status.launcher_state([self.apps])["claude"])
        (self.apps / "Claude.app" / "Contents" / "Info.plist").write_bytes(b"not a plist")
        self.assertEqual(status.NO_NEW_SESSION % "Claude", status.launcher_state([self.apps])["claude"])

    def test_not_installed_says_so(self):
        self.assertEqual(status.NOT_INSTALLED, status.launcher_state([self.apps])["claude"])

    def test_one_row_for_each_app(self):
        self.assertEqual("Claude", status.VERB["claude"])
        self.assertEqual("Codex", status.VERB["codex"])
        self.assertEqual(("finder", "cmux", "codex", "claude"), tuple(k for k, *_ in status.LAUNCHERS))
        self.assertEqual({"claude", "codex"}, set(status.NEW_SESSION))

    def test_settings_lists_one_row_for_each_app_chosen_and_greyed_like_the_others(self):
        why = {"codex": status.NO_NEW_SESSION % "Codex", "finder": None, "cmux": None, "claude": None}
        dialog = status.launcher_choices(("finder", "claude"), why=why)
        self.assertIn('for="launch-claude"><i class="lico" aria-hidden="true" style="--ic:var(--icon-claude)"></i>'
                      '<span>Claude<small>Opens a new session on the thread. You press Enter.</small></span>', dialog)
        self.assertIn('data-launcher="codex" disabled', dialog)
        self.assertIn("Codex<small>Installed, but this version cannot open a new session: update the Codex app</small>", dialog)
        self.assertIn('name="garrick-default" value="claude"', dialog)
        self.assertIn('name="garrick-default" value="codex" disabled', dialog)
        self.assertEqual(1, dialog.count('data-launcher="claude"'))
        self.assertEqual(1, dialog.count('data-launcher="codex"'))
        for gone in ("claude-new", "codex-new", "Open in Claude", "Open in Codex", "New session in"):
            self.assertNotIn(gone, dialog)

    def test_the_page_draws_and_remembers_one_key_for_each_app(self):
        self.assertNotIn("claude-new", status.LAUNCH_KEYS)
        self.assertNotIn("codex-new", status.LAUNCH_KEYS)
        self.assertEqual(status.LAUNCH_KEYS, pa.LAUNCHERS)
        js = status.PANEL_JS
        self.assertIn("verb:'session-url',key:k,folder:o.f", js)
        self.assertIn("var NS={claude:'Claude',codex:'Codex'};", js)
        self.assertNotIn("verb:'continue'", js)                            # the command-line route left the cards (#682)
        self.assertNotIn("dataset.cli", js)
        # the button carries the key and the folder to find the work by, and no link, path to open or prompt
        self.assertNotIn("data-url", js[js.index("function launch("):js.index("function deskReq")])


class TestTheIconRow(unittest.TestCase):
    """Seven app icons on a card (#652): one row inside 264px with 4px gaps; five or fewer keep today's 28px squares."""

    def test_the_rule_shrinks_the_squares_only_from_the_sixth_icon(self):
        css = status.CSS if hasattr(status, "CSS") else ""
        css = css or "".join(v for v in vars(status).values() if isinstance(v, str) and ".gacts.popen" in v)
        self.assertIn(".appicons .gacts.popen .act[data-k]{flex:none;width:28px;height:28px;min-height:0;background-size:20px}", css)
        rule = ".appicons .gacts.popen:has(>.act[data-k]:nth-child(7)) .act[data-k]{width:24px;height:24px;background-size:18px}"
        self.assertIn(rule, css)
        self.assertGreater(css.index(rule), css.index(".appicons .gacts.popen .act[data-k]{flex:none;width:28px"))   # it wins by order
        self.assertIn(".appicons .gacts.popen{flex-wrap:nowrap}", css)                  # one row, never wrapped

    def test_seven_icons_fit_where_five_did(self):
        # Measured by the page gate: seven 28px squares with 4px gaps end 26px past the card's right edge.
        over = 7 * 28 + 6 * 4 - 26                  # what the icons may take: 194px beside the label
        self.assertLessEqual(5 * 28 + 4 * 4, over)  # five squares fit, as before
        self.assertLessEqual(7 * 24 + 6 * 4, over)  # seven 24px squares: 192px, inside the card


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.root = self.tmp / "Workspace"
        build_workspace(self.root)
        (self.root / "System" / "tools").mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "template" / "System" / "tools" / "operations.py", self.root / "System" / "tools" / "operations.py")
        self.work = self.root / "Zones" / "Work"

    def tearDown(self):
        self._tmp.cleanup()

    def url(self, key, folder, **more):
        return pa.act(self.root, dict(verb="session-url", key=key, folder=str(folder), **more))

    def thread(self, project, name):
        return self.work / project / "Threads" / name

    def add_thread(self, project, name):
        write(self.thread(project, name) / (name + ".md"), "---\nstatus: active\n---\n# %s\n" % name)


class TestTheLink(WorkspaceCase):
    def test_claude_gets_its_folder_and_the_prompt_encoded(self):
        folder = self.thread("Acme Review", "Pricing").resolve()
        reply = self.url("claude", folder)
        self.assertEqual("claude://code/new?folder=%s&q=open%%20Pricing" % quote(str(folder), safe=""), reply["url"])
        self.assertEqual("open Pricing", reply["prompt"])
        self.assertEqual("Claude", reply["app"])

    def test_codex_gets_its_own_route_and_names(self):
        folder = self.thread("Acme Review", "Pricing").resolve()
        reply = self.url("codex", folder)
        self.assertEqual("codex://threads/new?path=%s&prompt=open%%20Pricing" % quote(str(folder), safe=""), reply["url"])
        self.assertEqual("Codex", reply["app"])

    def test_a_name_with_url_characters_cannot_add_a_parameter(self):
        self.add_thread("Birch Entry", "Q&A #1 = ok?")
        folder = self.thread("Birch Entry", "Q&A #1 = ok?").resolve()
        url = self.url("claude", folder)["url"]
        from urllib.parse import parse_qs, urlsplit
        parts = urlsplit(url)
        self.assertEqual(["folder", "q"], sorted(parse_qs(parts.query)))
        self.assertEqual([str(folder)], parse_qs(parts.query)["folder"])
        self.assertEqual(["open Q&A #1 = ok?"], parse_qs(parts.query)["q"])
        self.assertEqual("", parts.fragment)

    def test_the_prompt_is_the_shortest_unique_name(self):
        # the thread alone, while no other thread has the name
        self.assertEqual("open Pricing", self.url("claude", self.thread("Acme Review", "Pricing"))["prompt"])
        # a project alone
        self.assertEqual("open Acme Review", self.url("claude", self.work / "Acme Review")["prompt"])
        # two threads of one name: project and thread
        self.add_thread("Birch Entry", "Pricing")
        self.assertEqual("open Birch Entry, Pricing", self.url("codex", self.thread("Birch Entry", "Pricing"))["prompt"])
        self.assertEqual("open Acme Review, Pricing", self.url("codex", self.thread("Acme Review", "Pricing"))["prompt"])

    def test_the_reply_says_what_the_fallback_does(self):
        reply = self.url("codex", self.thread("Acme Review", "Pricing"))
        self.assertEqual("Codex did not open a new session. Opened Codex instead; the clipboard now holds “open Pricing”. "
                         "Paste it into a new session.", reply["fallback"])
        self.assertEqual("Opening a new session in Codex", reply["say"])


class TestTheRefusals(WorkspaceCase):
    def refused(self, key, folder, **more):
        with self.assertRaises(pa.Refused):
            self.url(key, folder, **more)

    def test_a_folder_outside_the_workspace_is_refused(self):
        outside = self.tmp / "elsewhere" / "Cedar"
        write(outside / "Cedar.md", "x")
        self.refused("claude", outside)
        self.refused("codex", "/tmp")

    def test_a_link_out_of_the_workspace_is_refused(self):
        outside = self.tmp / "elsewhere" / "Cedar"
        write(outside / "Cedar.md", "x")
        (self.work / "Cedar").symlink_to(outside)
        self.refused("claude", self.work / "Cedar")
        self.refused("codex", self.work / "Cedar")

    def test_what_is_not_a_project_or_a_thread_is_refused(self):
        for rel in ("", "Acme Review/Sources", "Acme Review/Deliverables", "Acme Review/Threads", "Inbox", "../Personal"):
            self.refused("claude", (self.work / rel) if rel else self.root)
        self.refused("claude", self.root / "Wikis" / "Meetings")
        self.refused("claude", "relative/Acme Review")

    def test_a_request_cannot_carry_a_link_a_path_or_a_prompt(self):
        folder = self.thread("Acme Review", "Pricing")
        for extra in ({"url": "claude://code/new?folder=/etc&q=x"}, {"prompt": "open something else"}, {"path": "/etc"},
                      {"q": "x"}, {"app": "Other"}):
            self.refused("claude", folder, **extra)

    def test_only_the_two_keys_are_ways_to_open_a_session(self):
        folder = self.thread("Acme Review", "Pricing")
        for key in ("claude-new", "codex-new", "cmux", "finder", "", None, 3, "claude ", "../claude"):
            self.refused(key, folder)


class TestTheSwiftSide(unittest.TestCase):
    """The rules of GarrickShared.swift's GarrickSession, compiled with stubs: no app, no clipboard."""

    HARNESS = r"""
import Foundation
let a = CommandLine.arguments
var calls: [String] = []
switch a[1] {
case "link": print(GarrickSession.link(key: a[2], text: a[3])?.absoluteString ?? "nil")
case "make": print(GarrickSession.make(key: a[2], folder: a[3], prompt: a[4])?.absoluteString ?? "nil")
case "open":
    let took = GarrickSession.open(URL(string: a[3])!, prompt: a[4],
        opener: { calls.append("open " + $0.absoluteString); return a[2] == "takes" },
        openApp: { calls.append("app") }, copy: { calls.append("copy " + $0) })
    print(took, calls.joined(separator: " | "))
default: print("?")
}
"""

    @classmethod
    def setUpClass(cls):
        if not SWIFT:
            raise unittest.SkipTest("needs macOS with the Swift compiler")
        cls.tmp = Path(tempfile.mkdtemp()).resolve()
        (cls.tmp / "main.swift").write_text(cls.HARNESS)
        cls.exe = cls.tmp / "harness"
        subprocess.run([SWIFT, "-Onone", "-o", str(cls.exe), str(cls.tmp / "main.swift"), str(APP / "GarrickShared.swift")],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_h(self, *args):
        return subprocess.run([str(self.exe), *args], capture_output=True, text=True, check=True).stdout.strip()

    def test_a_link_must_be_its_keys_own(self):
        ok = "claude://code/new?folder=%2FWs%2FZones&q=open%20Pricing"
        self.assertEqual(ok, self.run_h("link", "claude", ok))
        self.assertEqual("nil", self.run_h("link", "codex", ok))                     # the other app's scheme
        self.assertEqual("nil", self.run_h("link", "claude", "claude://other/new?x=1"))
        self.assertEqual("nil", self.run_h("link", "claude", "https://code/new"))
        self.assertEqual("nil", self.run_h("link", "claude", "file:///etc/passwd"))
        self.assertEqual("nil", self.run_h("link", "claude-new", ok))                    # 0.79.0's key is not a route any more
        self.assertEqual("codex://threads/new?path=%2FWs&prompt=x", self.run_h("link", "codex", "codex://threads/new?path=%2FWs&prompt=x"))

    def test_a_link_must_have_its_keys_path_and_query_names_only(self):
        for text in ("claude://code/other?folder=%2FWs&q=x",                  # another route
                     "claude://code/new/more?folder=%2FWs&q=x",
                     "claude://code/new/?folder=%2FWs&q=x",                   # a trailing slash
                     "claude://code/new?folder=%2FWs",                        # a name missing
                     "claude://code/new?folder=%2FWs&q=x&extra=1",            # a name added
                     "claude://code/new?folder=%2FWs&folder=%2FOther&q=x",    # a name twice
                     "claude://code/new?folder=%2FWs&prompt=x",               # the other app's name
                     "claude://code/new"):
            self.assertEqual("nil", self.run_h("link", "claude", text), text)
        for text in ("codex://threads/other?path=%2FWs&prompt=x", "codex://threads/new?path=%2FWs&q=x",
                     "codex://threads/new?folder=%2FWs&prompt=x", "codex://threads/new?path=%2FWs&prompt=x&a=b"):
            self.assertEqual("nil", self.run_h("link", "codex", text), text)

    def test_the_menu_builds_the_same_link_the_page_gets(self):
        self.assertEqual("claude://code/new?folder=%2FWs%2FZones%2FWork%2FAcme%20Review&q=open%20Acme%20Review",
                         self.run_h("make", "claude", "/Ws/Zones/Work/Acme Review", "open Acme Review"))
        self.assertEqual("codex://threads/new?path=%2FWs%2FQ%26A&prompt=open%20Q%26A",
                         self.run_h("make", "codex", "/Ws/Q&A", "open Q&A"))
        self.assertEqual("nil", self.run_h("make", "claude-new", "/Ws", "open X"))

    def test_a_link_the_app_takes_is_opened_once_and_nothing_is_copied(self):
        self.assertEqual("true open claude://code/new?folder=%2FWs&q=open%20X",
                         self.run_h("open", "takes", "claude://code/new?folder=%2FWs&q=open%20X", "open X"))

    def test_a_refused_link_opens_the_app_and_copies_the_prompt(self):
        said = self.run_h("open", "refuses", "codex://threads/new?path=%2FWs&prompt=open%20X", "open X")
        self.assertEqual("false open codex://threads/new?path=%2FWs&prompt=open%20X | copy open X | app", said)


class TestAnOlderSettingsFile(unittest.TestCase):
    """A settings file 0.79.0 wrote, with two rows for each app, read as one row (#682)."""

    def test_either_old_row_on_puts_the_row_on_and_either_default_becomes_its(self):
        merge = status.prefs().launchers_merged
        self.assertEqual(({"claude": True, "codex": False, "note": True}, "claude"),
                         merge({"claude": False, "claude-new": True, "codex": False, "codex-new": False, "note": True}, "claude-new"))
        self.assertEqual((["note", "codex"], "codex"), merge(["note", "codex"], "codex-new"))
        self.assertEqual((["note", "claude"], "note"), merge(["note", "claude-new"], "note"))
        self.assertEqual(({"claude": False}, "claude"), merge({"claude": False}, "claude"))    # a file 0.80.0 saved keeps what it says
        self.assertEqual(({"codex": True}, None), merge({"codex": True, "codex-new": False}))

    def test_the_page_the_app_and_ask_read_it_the_same_way(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve() / "Workspace"
        build_workspace(root)
        tools = root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "template" / "System" / "tools" / "garrick_lib.py", tools / "garrick_lib.py")
        import json
        (root / "System" / "garrick-settings.json").write_text(json.dumps(
            {"launchers": {"note": True, "preview": True, "finder": True, "cmux": True, "codex": True, "claude": False,
                           "claude-new": True, "codex-new": False}, "default": "claude-new"}))
        shared = status.shared_launchers(root)
        self.assertIn("claude", shared["launchers"])
        self.assertEqual("claude", shared["default"])
        (root / "System" / "garrick-settings.json").write_text(json.dumps({"launchers": ["codex"], "default": "note"}))
        self.assertIn("codex", status.shared_launchers(root)["launchers"])
        ask = load("garrick_ask_ns", STATUS / "ask.py")
        (root / "System" / "garrick-settings.json").write_text(json.dumps({"launchers": {"claude": False, "claude-new": True}}))
        self.assertTrue(ask.launcher_on(root, "claude"))
        js = status.PANEL_JS
        self.assertIn("var OLD={claude:'claude-new',codex:'codex-new'};", js)          # a window's own storage, as the file
        self.assertIn("return d==='claude-new'?'claude':d==='codex-new'?'codex':d", js)
        swift = (APP / "Garrick.swift").read_text(encoding="utf-8")
        self.assertIn('let mergedLaunchers = ["claude": "claude-new", "codex": "codex-new"]', swift)
        self.assertIn("return mine || on[old] as? Bool != false", swift)

    def test_the_old_keys_are_dropped_on_the_next_save_and_never_before(self):
        self.assertNotIn("claude-new", pa.LAUNCHERS)                       # the save writes every key it knows, and only those
        src = (STATUS / "page_action.py").read_text(encoding="utf-8")
        self.assertIn('new = {"launchers": {k: k in on for k in LAUNCHERS}, "default": default}', src)


class TestTheAppCode(unittest.TestCase):
    def test_the_app_opens_the_reply_link_through_the_shared_rules_and_falls_back(self):
        src = (APP / "Garrick.swift").read_text(encoding="utf-8")
        body = src[src.index("func openNewSession"):src.index("// Whether the page says the desk opens cmux here")]
        self.assertIn("GarrickSession.link(key: key", body)
        self.assertIn("GarrickSession.open(url, prompt: prompt", body)
        self.assertIn('"session-url"', src[src.index("func reading("):src.index("func rebuilds(")])   # a read: no rebuild under the page
        self.assertNotIn("body[\"url\"]", src)            # the page's message never carries a link to open

    def test_the_app_opens_claude_and_codex_by_their_link_and_never_runs_the_command_line_tool(self):
        src = (APP / "Garrick.swift").read_text(encoding="utf-8")
        launch = src[src.index("func launch(_ app: String"):src.index("// Sends the link to a Claude whose window is up")]
        self.assertIn('case "claude", "codex":', launch)
        self.assertIn("GarrickSession.make(key: app, folder: folder.path, prompt: phrase)", launch)
        self.assertNotIn("codex-cli", launch)                              # the folder-only route of Codex left (#682)
        self.assertNotIn('"verb": "continue"', src)                        # no code path runs Continue's command-line route
        self.assertNotIn('["oc"]', src)
        self.assertIn('let apps = ["claude": (claudeBundle, "Claude"), "codex": (codexBundle, "Codex")]', src)

    def test_the_page_action_reply_is_what_the_app_reads(self):
        self.assertIn("session-url", pa.VERBS)
        self.assertIn("session-url", pa.__doc__)


if __name__ == "__main__":
    unittest.main()
