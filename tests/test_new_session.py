"""A new session in the Claude or Codex desktop app (#652): the build check, the link, its refusals and the fallback.

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
        self.assertIsNone(state["claude-new"])
        self.assertIsNone(state["codex-new"])
        self.assertIn("claude-new", status.launchers_installed([self.apps]))
        self.assertIn("codex-new", status.launchers_installed([self.apps]))

    def test_it_needs_no_command_line_tool(self):
        bundle(self.apps, "Codex", "com.openai.codex", ["codex"])          # no launcher inside the bundle
        state = status.launcher_state([self.apps])
        self.assertEqual(status.NO_CODEX_CLI, state["codex"])              # the old row is as it was
        self.assertIsNone(state["codex-new"])

    def test_an_app_without_the_scheme_is_greyed_with_the_reason(self):
        bundle(self.apps, "Claude", "com.anthropic.claudefordesktop")                       # no URL types at all
        bundle(self.apps, "Codex", "com.openai.codex", ["https", "other"])                  # another scheme
        state = status.launcher_state([self.apps])
        self.assertEqual("Installed, but this version cannot open a new session: update the Claude app", state["claude-new"])
        self.assertEqual("Installed, but this version cannot open a new session: update the Codex app", state["codex-new"])
        self.assertNotIn("claude-new", status.launchers_installed([self.apps]))
        self.assertNotIn("codex-new", status.launchers_installed([self.apps]))
        self.assertIn("claude", status.launchers_installed([self.apps]))              # the old row works as it did

    def test_a_scheme_is_read_whatever_its_case_and_a_broken_plist_fails_closed(self):
        bundle(self.apps, "Claude", "com.anthropic.claudefordesktop", ["Claude"])
        self.assertIsNone(status.launcher_state([self.apps])["claude-new"])
        (self.apps / "Claude.app" / "Contents" / "Info.plist").write_bytes(b"not a plist")
        self.assertEqual(status.NO_NEW_SESSION % "Claude", status.launcher_state([self.apps])["claude-new"])

    def test_not_installed_says_so(self):
        self.assertEqual(status.NOT_INSTALLED, status.launcher_state([self.apps])["claude-new"])

    def test_the_old_rows_are_unchanged(self):
        self.assertEqual("Open in Claude", status.VERB["claude"])
        self.assertEqual("Open in Codex", status.VERB["codex"])
        self.assertEqual("New session in Claude", status.VERB["claude-new"])
        self.assertEqual("New session in Codex", status.VERB["codex-new"])
        self.assertEqual(("finder", "cmux", "codex", "claude"), tuple(k for k, *_ in status.LAUNCHERS)[:4])

    def test_settings_lists_the_new_rows_chosen_and_greyed_like_the_others(self):
        why = {"claude-new": None, "codex-new": status.NO_NEW_SESSION % "Codex", "finder": None, "cmux": None, "codex": None,
               "claude": None}
        dialog = status.launcher_choices(("finder", "claude-new"), why=why)
        self.assertIn('for="launch-claude-new"><i class="lico" aria-hidden="true" style="--ic:var(--icon-claude)"></i>'
                      '<span>New session in Claude</span>', dialog)
        self.assertIn('data-launcher="codex-new" disabled', dialog)
        self.assertIn("New session in Codex<small>Installed, but this version cannot open a new session: update the Codex app</small>",
                      dialog)
        self.assertIn('name="garrick-default" value="claude-new"', dialog)
        self.assertIn('name="garrick-default" value="codex-new" disabled', dialog)

    def test_the_page_draws_and_remembers_the_new_keys(self):
        self.assertIn("claude-new", status.LAUNCH_KEYS)
        self.assertIn("codex-new", status.LAUNCH_KEYS)
        self.assertEqual(status.LAUNCH_KEYS, pa.LAUNCHERS)
        js = status.PANEL_JS
        self.assertIn("verb:'session-url',key:k,folder:o.f", js)
        self.assertIn("'claude-new':'Claude','codex-new':'Codex'", js)
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
        reply = self.url("claude-new", folder)
        self.assertEqual("claude://code/new?folder=%s&q=open%%20Pricing" % quote(str(folder), safe=""), reply["url"])
        self.assertEqual("open Pricing", reply["prompt"])
        self.assertEqual("Claude", reply["app"])

    def test_codex_gets_its_own_route_and_names(self):
        folder = self.thread("Acme Review", "Pricing").resolve()
        reply = self.url("codex-new", folder)
        self.assertEqual("codex://threads/new?path=%s&prompt=open%%20Pricing" % quote(str(folder), safe=""), reply["url"])
        self.assertEqual("Codex", reply["app"])

    def test_a_name_with_url_characters_cannot_add_a_parameter(self):
        self.add_thread("Birch Entry", "Q&A #1 = ok?")
        folder = self.thread("Birch Entry", "Q&A #1 = ok?").resolve()
        url = self.url("claude-new", folder)["url"]
        from urllib.parse import parse_qs, urlsplit
        parts = urlsplit(url)
        self.assertEqual(["folder", "q"], sorted(parse_qs(parts.query)))
        self.assertEqual([str(folder)], parse_qs(parts.query)["folder"])
        self.assertEqual(["open Q&A #1 = ok?"], parse_qs(parts.query)["q"])
        self.assertEqual("", parts.fragment)

    def test_the_prompt_is_the_shortest_unique_name(self):
        # the thread alone, while no other thread has the name
        self.assertEqual("open Pricing", self.url("claude-new", self.thread("Acme Review", "Pricing"))["prompt"])
        # a project alone
        self.assertEqual("open Acme Review", self.url("claude-new", self.work / "Acme Review")["prompt"])
        # two threads of one name: project and thread
        self.add_thread("Birch Entry", "Pricing")
        self.assertEqual("open Birch Entry, Pricing", self.url("codex-new", self.thread("Birch Entry", "Pricing"))["prompt"])
        self.assertEqual("open Acme Review, Pricing", self.url("codex-new", self.thread("Acme Review", "Pricing"))["prompt"])

    def test_the_reply_says_what_the_fallback_does(self):
        reply = self.url("codex-new", self.thread("Acme Review", "Pricing"))
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
        self.refused("claude-new", outside)
        self.refused("codex-new", "/tmp")

    def test_a_link_out_of_the_workspace_is_refused(self):
        outside = self.tmp / "elsewhere" / "Cedar"
        write(outside / "Cedar.md", "x")
        (self.work / "Cedar").symlink_to(outside)
        self.refused("claude-new", self.work / "Cedar")
        self.refused("codex-new", self.work / "Cedar")

    def test_what_is_not_a_project_or_a_thread_is_refused(self):
        for rel in ("", "Acme Review/Sources", "Acme Review/Deliverables", "Acme Review/Threads", "Inbox", "../Personal"):
            self.refused("claude-new", (self.work / rel) if rel else self.root)
        self.refused("claude-new", self.root / "Wikis" / "Meetings")
        self.refused("claude-new", "relative/Acme Review")

    def test_a_request_cannot_carry_a_link_a_path_or_a_prompt(self):
        folder = self.thread("Acme Review", "Pricing")
        for extra in ({"url": "claude://code/new?folder=/etc&q=x"}, {"prompt": "open something else"}, {"path": "/etc"},
                      {"q": "x"}, {"app": "Other"}):
            self.refused("claude-new", folder, **extra)

    def test_only_the_two_keys_are_ways_to_open_a_session(self):
        folder = self.thread("Acme Review", "Pricing")
        for key in ("claude", "codex", "cmux", "finder", "", None, 3, "claude-new ", "../claude-new"):
            self.refused(key, folder)


class TestTheSwiftSide(unittest.TestCase):
    """The rules of GarrickShared.swift's GarrickSession, compiled with stubs: no app, no clipboard."""

    HARNESS = r"""
import Foundation
let a = CommandLine.arguments
var calls: [String] = []
switch a[1] {
case "link": print(GarrickSession.link(key: a[2], text: a[3])?.absoluteString ?? "nil")
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
        self.assertEqual(ok, self.run_h("link", "claude-new", ok))
        self.assertEqual("nil", self.run_h("link", "codex-new", ok))                     # the other app's scheme
        self.assertEqual("nil", self.run_h("link", "claude-new", "claude://other/new?x=1"))
        self.assertEqual("nil", self.run_h("link", "claude-new", "https://code/new"))
        self.assertEqual("nil", self.run_h("link", "claude-new", "file:///etc/passwd"))
        self.assertEqual("nil", self.run_h("link", "claude", ok))                        # not a key of this route
        self.assertEqual("codex://threads/new?path=%2FWs&prompt=x", self.run_h("link", "codex-new", "codex://threads/new?path=%2FWs&prompt=x"))

    def test_a_link_must_have_its_keys_path_and_query_names_only(self):
        for text in ("claude://code/other?folder=%2FWs&q=x",                  # another route
                     "claude://code/new/more?folder=%2FWs&q=x",
                     "claude://code/new/?folder=%2FWs&q=x",                   # a trailing slash
                     "claude://code/new?folder=%2FWs",                        # a name missing
                     "claude://code/new?folder=%2FWs&q=x&extra=1",            # a name added
                     "claude://code/new?folder=%2FWs&folder=%2FOther&q=x",    # a name twice
                     "claude://code/new?folder=%2FWs&prompt=x",               # the other app's name
                     "claude://code/new"):
            self.assertEqual("nil", self.run_h("link", "claude-new", text), text)
        for text in ("codex://threads/other?path=%2FWs&prompt=x", "codex://threads/new?path=%2FWs&q=x",
                     "codex://threads/new?folder=%2FWs&prompt=x", "codex://threads/new?path=%2FWs&prompt=x&a=b"):
            self.assertEqual("nil", self.run_h("link", "codex-new", text), text)

    def test_a_link_the_app_takes_is_opened_once_and_nothing_is_copied(self):
        self.assertEqual("true open claude://code/new?folder=%2FWs&q=open%20X",
                         self.run_h("open", "takes", "claude://code/new?folder=%2FWs&q=open%20X", "open X"))

    def test_a_refused_link_opens_the_app_and_copies_the_prompt(self):
        said = self.run_h("open", "refuses", "codex://threads/new?path=%2FWs&prompt=open%20X", "open X")
        self.assertEqual("false open codex://threads/new?path=%2FWs&prompt=open%20X | copy open X | app", said)


class TestTheAppCode(unittest.TestCase):
    def test_the_app_opens_the_reply_link_through_the_shared_rules_and_falls_back(self):
        src = (APP / "Garrick.swift").read_text(encoding="utf-8")
        body = src[src.index("func openNewSession"):src.index("// Whether the page says the desk opens cmux here")]
        self.assertIn("GarrickSession.link(key: key", body)
        self.assertIn("GarrickSession.open(url, prompt: prompt", body)
        self.assertIn('"session-url"', src[src.index("func reading("):src.index("func rebuilds(")])   # a read: no rebuild under the page
        self.assertNotIn("body[\"url\"]", src)            # the page's message never carries a link to open

    def test_the_page_action_reply_is_what_the_app_reads(self):
        self.assertIn("session-url", pa.VERBS)
        self.assertIn("session-url", pa.__doc__)


if __name__ == "__main__":
    unittest.main()
