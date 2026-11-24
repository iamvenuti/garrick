"""Counting which cards of the App are opened (#651), and the report that reads the counts.

    python3 -m unittest test_usage_counts

Each line of the issue's *Acceptance* has its test:

- opening a card adds one to its count (TestCounting.test_opening_a_card_adds_one_to_its_count_for_the_day);
- the stored file holds no path, name or text (TestWhatIsKept);
- with counting off, opening a card writes nothing (TestOff);

The report that reads the counts is tested in test_usage_report.py.

Nothing here opens a real app: the page's script runs in Node against a stand-in for the bridge, and a request goes through
page_action.perform() as the bridge sends it, with a jobs folder and a home of its own.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import build_workspace  # noqa: E402
from test_page_action import pa  # noqa: E402
from test_status import REPO, status  # noqa: E402

TOOLS = REPO / "template" / "System" / "tools"
sys.path.insert(0, str(TOOLS))
import garrick_lib  # noqa: E402
import operations  # noqa: E402
import view  # noqa: E402

USAGE = TOOLS / "usage.py"
spec = importlib.util.spec_from_file_location("garrick_usage_counts_test", REPO / "extras" / "status" / "usage_counts.py")
counts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(counts)

TODAY = dt.date.today().isoformat()


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.root = base / "Workspace"
        self.jobs = base / "jobs"
        self.home = base / "home"
        self.home.mkdir()
        build_workspace(self.root)
        (self.root / "System" / "tools").rmdir() if (self.root / "System" / "tools").is_dir() else None
        (self.root / "System" / "tools").symlink_to(TOOLS, target_is_directory=True)
        self._env = {k: os.environ.get(k) for k in ("GARRICK_JOBS_DIR", "HOME")}
        os.environ["GARRICK_JOBS_DIR"] = str(self.jobs)
        os.environ["HOME"] = str(self.home)
        self.addCleanup(self.restore)
        self.addCleanup(self._tmp.cleanup)
        self.file = self.root / "System" / "garrick-usage.json"

    def restore(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def send(self, card, via="page", **more):
        """One `count-card` request, as the app's bridge hands it to page_action.py."""
        req = dict({"verb": "count-card", "card": card}, **more)
        return pa.perform(self.root, req, pa.ops_lib(self.root), via=via)

    def stored(self):
        return json.loads(self.file.read_text(encoding="utf-8"))


class TestCounting(Case):
    def test_opening_a_card_adds_one_to_its_count_for_the_day(self):
        for _ in range(2):
            out, _, _ = self.send("threads")
            self.assertTrue(out["ok"], out)
        self.send("checks")
        self.assertEqual({"v": 1, "counts": {"checks": {TODAY: 1}, "threads": {TODAY: 2}}}, self.stored())

    def test_every_card_the_page_draws_is_one_that_may_be_counted(self):
        html = status.build(self.root, now=dt.datetime.now(), folder=self.jobs)
        drawn = set(re.findall(r'<details class="card[^"]*" id="([^"]+)"', html))
        self.assertTrue(drawn)
        self.assertLessEqual(drawn, set(view.CARDS))

    def test_it_is_declared_page_only_and_commits_and_records_nothing(self):
        spec_ = operations.DECLARED["count-card"]
        self.assertEqual((("card",), False), (spec_.fields, spec_.commits))
        self.assertIn("count-card", pa.PAGE_ONLY)
        self.assertNotIn("count-card", operations.RECORDED)
        self.send("threads")
        self.assertFalse((self.jobs / operations.FILE).exists(), "no row in the operations journal")

    def test_the_ask_box_and_a_session_cannot_send_it(self):
        for via in ("ask", "session"):
            out, _, _ = self.send("threads", via=via)
            self.assertFalse(out["ok"], via)
        self.assertFalse(self.file.exists())

    def test_a_field_it_does_not_declare_is_refused(self):
        out, _, _ = self.send("threads", zone="Work")
        self.assertFalse(out["ok"])
        self.assertFalse(self.file.exists())


class TestWhatIsKept(Case):
    BAD = ("Zones/Work/Acme Review", "Acme Review", "Work", "Pricing", "../threads", "threads ", "Threads", "free text here",
           "", "a" * 200, "threads\nchecks", "{\"threads\": 1}", 5, None, ["threads"], {"card": "threads"}, "start‮")

    def test_only_an_id_a_day_and_a_count_are_kept(self):
        for card in view.CARDS:
            self.send(card)
        text = self.file.read_text(encoding="utf-8")
        data = json.loads(text)
        self.assertEqual({"v", "counts"}, set(data))
        for card, days in data["counts"].items():
            self.assertIn(card, view.CARDS)
            for day, n in days.items():
                self.assertRegex(day, r"^\d{4}-\d\d-\d\d$")
                self.assertIsInstance(n, int)
        for private in (str(self.root), "Acme Review", "Pricing", "Work", "Zones"):
            self.assertNotIn(private, text)

    def test_anything_that_is_not_a_card_id_is_refused_and_writes_nothing(self):
        for bad in self.BAD:
            out, _, _ = self.send(bad)
            self.assertFalse(out["ok"], repr(bad))
            self.assertFalse(self.file.exists(), repr(bad))
        # and one good one afterwards writes only itself
        self.send("jobs")
        self.assertEqual({"v": 1, "counts": {"jobs": {TODAY: 1}}}, self.stored())

    def test_a_thread_rows_card_data_is_never_a_card(self):
        html = status.build(self.root, now=dt.datetime.now(), folder=self.jobs)
        for name in ("Pricing", "Acme Review", "Market Sizing"):
            self.assertNotIn(name, view.CARDS)
        ids = re.search(r"IDS=(\[[^\]]*\])", html)
        self.assertEqual(list(view.CARDS), json.loads(ids.group(1)))

    def test_a_file_that_is_not_what_the_writer_wrote_is_not_read_into_the_next(self):
        bad_files = [
            "not json",
            json.dumps([1, 2]),
            json.dumps({"v": 2, "counts": {"threads": {"2026-01-01": 4}}}),
            json.dumps({"v": 1, "counts": {"threads": {"2026-01-01": 4}}, "extra": "/Users/x"}),
            json.dumps({"v": 1, "counts": {"/etc/passwd": {"2026-01-01": 1}, "threads": {"2026-01-01": 4}}}),
            json.dumps({"v": 1, "counts": {"threads": {"yesterday": 4}}}),
            json.dumps({"v": 1, "counts": {"threads": {"2026-01-01": "4"}}}),
            json.dumps({"v": 1, "counts": {"threads": {"2026-01-01": True}}}),
            json.dumps({"v": 1, "counts": {"threads": {"2026-01-01": -1}}}),
            json.dumps({"v": 1, "counts": {"threads": ["2026-01-01"]}}),
            json.dumps({"v": 1, "counts": {"threads": {"2026-13-45": 1}}}),
        ]
        for text in bad_files:
            self.file.write_text(text, encoding="utf-8")
            self.send("checks")
            self.assertEqual({"v": 1, "counts": {"checks": {TODAY: 1}}}, self.stored(), text)
            self.assertNotIn("passwd", self.file.read_text())
            self.assertNotIn("Users", self.file.read_text())

    def test_a_card_a_later_release_dropped_is_not_carried(self):
        self.file.write_text(json.dumps({"v": 1, "counts": {"old-card": {"2026-01-01": 3}, "threads": {"2026-01-01": 3}}}))
        self.send("threads")
        self.assertEqual({"v": 1, "counts": {"threads": {"2026-01-01": 3, TODAY: 1}}}, self.stored())

    def test_old_days_are_dropped(self):
        old = (dt.date.today() - dt.timedelta(days=counts.KEEP_DAYS + 5)).isoformat()
        self.file.write_text(json.dumps({"v": 1, "counts": {"threads": {old: 3}}}))
        self.send("threads")
        self.assertEqual({"v": 1, "counts": {"threads": {TODAY: 1}}}, self.stored())

    def test_the_root_gitignore_leaves_it_out(self):
        self.assertIn("System/garrick-usage.json", garrick_lib.garrick_ignores(["Work"])[".gitignore"])

    def test_an_update_brings_that_line_to_a_workspace_whose_block_lacks_it(self):
        """update.py puts Garrick's lines between the markers in again, and keeps the user's own outside them."""
        older = garrick_lib.ignore_block("Zones/\nWikis/\nSystem/generated/\n") + "mine/\n"
        got = garrick_lib.with_ignore_block(older, garrick_lib.garrick_ignores(["Work"])[".gitignore"])
        self.assertIn("System/garrick-usage.json*", got.splitlines())
        self.assertIn("mine/", got.splitlines())


class TestOff(Case):
    def off(self):
        out, _, _ = pa.perform(self.root, {"verb": "settings", "usage-counts": False}, pa.ops_lib(self.root), via="page")
        self.assertTrue(out["ok"], out)

    def test_with_counting_off_opening_a_card_writes_nothing(self):
        self.send("threads")
        before = self.file.read_bytes()
        self.off()
        out, _, _ = self.send("threads")
        self.assertTrue(out["ok"])
        self.assertIn("off", out["say"].lower())
        self.assertEqual(before, self.file.read_bytes())

    def test_off_from_the_start_never_makes_the_file(self):
        self.off()
        self.send("checks")
        self.assertFalse(self.file.exists())

    def test_the_setting_is_on_unless_it_says_false_and_takes_only_a_boolean(self):
        self.assertTrue(counts.on({}))
        self.assertTrue(counts.on({"usage-counts": True}))
        self.assertFalse(counts.on({"usage-counts": False}))
        out, _, _ = pa.perform(self.root, {"verb": "settings", "usage-counts": "no"}, pa.ops_lib(self.root), via="page")
        self.assertFalse(out["ok"])

    def test_the_page_says_what_is_kept_and_sends_nothing_when_the_box_is_clear(self):
        html = status.build(self.root, now=dt.datetime.now(), folder=self.jobs)
        self.assertRegex(html, r'id="usage-on" checked')
        self.off()
        html = status.build(self.root, now=dt.datetime.now(), folder=self.jobs)
        self.assertRegex(html, r'id="usage-on"(?! checked)')
        # #681's text: what is kept, where, and that nothing is sent
        self.assertIn("Counts which cards you open, on this computer only. No name or text is kept, and nothing is sent.", html)


NODE = shutil.which("node")
HARNESS = textwrap.dedent(r"""
    const vm = require("vm");
    const [js, cases] = JSON.parse(process.argv[1]);
    const out = [];
    for (const c of cases) {
      const posted = [];
      let handler = null;
      const cardOf = (id, open) => ({ id, open, tools: false });
      const el = (card, inTools) => ({
        closest(sel) {
          if (sel === "details.card>summary") return { parentNode: card };
          if (sel === ".tools") return inTools ? {} : null;
          return null;
        }
      });
      const doc = { getElementById: (id) => (id === "usage-on" && c.box !== null ? { checked: c.box, addEventListener() {} } : null),
                    addEventListener: (k, f) => { if (k === "click") handler = f; } };
      const win = c.host ? { webkit: { messageHandlers: { garrick: { postMessage: (m) => posted.push(m) } } } } : {};
      vm.runInNewContext(js, { window: win, document: doc });
      for (const click of c.clicks) handler({ target: el(cardOf(click.id, click.open), click.tools) });
      out.push(posted);
    }
    console.log(JSON.stringify(out));
""")


@unittest.skipUnless(NODE, "node is needed to run the page's script")
class TestThePageSendsOnlyACardId(unittest.TestCase):
    """USAGE_JS, run against a stand-in for the page and for the app's bridge."""

    def run_cases(self, cases):
        js = status.USAGE_JS % json.dumps(list(view.CARDS))
        done = subprocess.run([NODE, "-e", HARNESS, json.dumps([js, cases])], capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_a_closed_card_that_is_opened_is_sent_by_its_id_and_nothing_else(self):
        got = self.run_cases([{"host": True, "box": True, "clicks": [{"id": "threads", "open": False}]}])
        self.assertEqual([[{"act": {"verb": "count-card", "card": "threads"}}]], got)

    def test_nothing_is_sent_for_an_open_card_a_row_a_tool_button_or_a_name(self):
        clicks = [{"id": "threads", "open": True}, {"id": "row-work-acme-review-pricing", "open": False},
                  {"id": "Acme Review", "open": False}, {"id": "checks", "open": False, "tools": True}]
        self.assertEqual([[]], self.run_cases([{"host": True, "box": True, "clicks": clicks}]))

    def test_nothing_is_sent_in_a_browser_or_with_the_box_clear(self):
        click = [{"id": "threads", "open": False}]
        got = self.run_cases([{"host": False, "box": True, "clicks": click}, {"host": True, "box": False, "clicks": click},
                              {"host": True, "box": None, "clicks": click}])
        self.assertEqual([[], [], []], got)


if __name__ == "__main__":
    unittest.main()
