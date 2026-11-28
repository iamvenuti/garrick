"""The app holds a reload while the page has something to lose (reload-0860, V1).

    cd tests && python3 -m unittest test_page_hold

The hold itself runs in the Mac app's web view and is shown by `python3 tools/app_check.py` (the cases for the field,
the loss of focus, the dialog, the drag, the ticks and three builds in one hold). Here: what the page's script is and
may do, and what the app's source says, which a test can read without a window.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STATUS = REPO / "extras" / "status" / "status.py"
SWIFT = (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")


def _load():
    spec = importlib.util.spec_from_file_location("garrick_status_hold", str(STATUS))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = _load()
NOW = dt.datetime(2026, 11, 20, 9, 0, 0)


class ThePageScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ws = build_workspace(Path(cls.tmp.name) / "ws")
        cls.page = status.build(cls.ws, now=NOW, show_graph=False)
        with mock.patch.object(status, "BUSY_JS", ""):
            cls.bare = status.build(cls.ws, now=NOW, show_graph=False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_it_is_one_script_element_and_nothing_else_on_the_page_changes(self):
        element = "<script>%s</script>" % status.BUSY_JS
        self.assertEqual(1, self.page.count(element))
        self.assertEqual(self.bare, self.page.replace(element, "", 1))

    def test_it_only_reads_and_only_tells_the_app_busy_or_idle(self):
        js = status.BUSY_JS
        self.assertEqual(["{busy:b}"], re.findall(r"postMessage\((\{[^}]*\})\)", js))
        for forbidden in ("setItem", "removeItem", "act:", "rebuild", "location", "innerHTML", "GarrickAct", "GarrickTick("):
            self.assertNotIn(forbidden, js)
        self.assertIn("sessionStorage.getItem('garrick-work-ticks')", js)      # the queue is read where WORK_JS keeps it

    def test_it_reads_the_four_things_a_reload_would_lose(self):
        js = status.BUSY_JS
        for word in ("TEXTAREA", "isContentEditable", "dialog[open]", "dragstart", "dragend", "garrick-work-ticks", "document.hasFocus()"):
            self.assertIn(word, js)

    def test_it_stops_at_once_in_a_browser(self):
        self.assertRegex(status.BUSY_JS, r"if\(!host\)return;")

    def test_the_queue_it_reads_is_the_one_the_work_script_writes(self):
        self.assertIn("KEY+'-ticks'", status.WORK_JS)
        self.assertIn("KEY='garrick-work'", status.WORK_JS)


class TheApp(unittest.TestCase):
    def body(self, name):
        i = SWIFT.index("func %s(" % name)
        return SWIFT[i:SWIFT.index("\n\t}\n", i)]

    def test_the_busy_message_is_answered_before_any_action_and_never_reaches_one(self):
        handler = SWIFT[SWIFT.index("func userContentController(_ c:"):]
        self.assertLess(handler.index('body["busy"]'), handler.index('body["act"]'))
        self.assertIn('if let b = body["busy"] as? Bool { return setBusy(b) }', handler)
        self.assertNotIn("act(", self.body("setBusy"))

    def test_a_busy_page_holds_the_reload_and_says_so_in_the_subtitle(self):
        self.assertIn('let pageWaiting = "A newer page is waiting"', SWIFT)
        reload = self.body("reload")
        self.assertIn("if !force && busy {", reload)
        self.assertIn("window.subtitle = pageWaiting", reload)
        self.assertLess(reload.index("pageGeneration(page)"), reload.index("if !force && busy"))

    def test_idle_loads_the_newest_page_once(self):
        busy = self.body("setBusy")
        self.assertIn("if !now && newerWaiting { newerWaiting = false; reload() }", busy)
        self.assertNotIn("asyncAfter", busy)                      # no time limit

    def test_the_hold_is_not_ended_by_leaving_the_app(self):
        for hook in ("applicationDidResignActive", "applicationWillResignActive", "applicationDidHide", "windowDidResignKey"):
            for m in re.finditer(r"func %s\(" % hook, SWIFT):
                self.assertNotIn("busy", SWIFT[m.start():m.start() + 300].split("\n\t}\n")[0])

    def test_the_subtitle_clears_when_the_page_loads_or_the_user_reloads(self):
        self.assertIn('if window.subtitle == pageWaiting { window.subtitle = "" }', self.body("clearHold"))
        self.assertIn("reload(force: true)", SWIFT)
        self.assertIn("clearHold()", self.body("load"))

    def test_a_build_that_lands_while_the_subtitle_says_rebuilding_does_not_lose_the_waiting_note(self):
        self.assertIn("(self.newerWaiting ? pageWaiting : \"\")", SWIFT)


if __name__ == "__main__":
    unittest.main()
