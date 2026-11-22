"""The report of what the Garrick App is used for (#651), `System/tools/usage.py`.

    python3 -m unittest test_usage_report

Acceptance lines held here: the report counts wraps and Ask actions from a fixture journal; it runs with the status extra
absent and says what it could not count; with counting off it says it has no card data. Card opens, the file's content and
the off switch are in test_usage_counts.py.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True

from test_usage_counts import Case, TOOLS, USAGE, TODAY, garrick_lib  # noqa: E402

spec = importlib.util.spec_from_file_location("garrick_usage_report_test", USAGE)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class TestReport(Case):
    def setUp(self):
        super().setUp()
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.today = dt.date(2026, 11, 22)
        self.when = dt.datetime(2026, 11, 20, 10, 0).timestamp()

    def counts_file(self, data):
        self.file.write_text(json.dumps(data), encoding="utf-8")

    def row(self, op, verb, zone, outcome, via="page", at=None, workspace=None):
        return json.dumps({"op": op, "workspace": workspace if workspace is not None else str(self.root), "verb": verb, "zone": zone,
                           "state": "completed" if outcome == "saved" else "failed", "at": at or self.when, "done": at or self.when,
                           "outcome": outcome, "via": via})

    def log(self, *lines):
        (self.jobs / "page-actions.log").write_text("".join(l + "\n" for l in lines), encoding="utf-8")

    def text(self, **kw):
        return report.report(self.root, 30, today=self.today, folder=self.jobs, **kw)

    def test_it_counts_card_opens_by_card_inside_the_period(self):
        self.counts_file({"v": 1, "counts": {"threads": {"2026-11-21": 4, "2026-11-22": 1, "2026-10-01": 9}, "checks": {"2026-11-22": 2}}})
        said, failed = self.text()
        self.assertRegex(said, r"threads\s+5\n")
        self.assertRegex(said, r"checks\s+2\n")
        self.assertNotIn("14", said)             # the day outside the period is not in the figure
        self.assertEqual([], [f for f in failed if "garrick-usage" in f])

    def test_it_counts_wraps_and_ask_actions_by_outcome_from_a_fixture_journal(self):
        (self.jobs / "operations.jsonl").write_text("\n".join([
            self.row("a1" * 4, "wrap", "Work", "saved"),
            self.row("a2" * 4, "wrap", "Work", "saved"),
            self.row("a3" * 4, "wrap", "Work", "refused"),
            self.row("a4" * 4, "wrap", "Home", "crashed"),
            self.row("a5" * 4, "todo-done", "Work", "saved", via="ask"),
            self.row("a6" * 4, "todo-add", "Work", "refused", via="ask"),
            self.row("a7" * 4, "park", "Home", "saved", via="ask"),
            self.row("a8" * 4, "wrap", "Work", "saved", workspace="/another/workspace"),    # another workspace's: not counted
            self.row("a9" * 4, "wrap", "Work", "saved", at=self.when - 90 * 86400),            # outside the period
        ]) + "\n", encoding="utf-8")
        said, failed = self.text()
        self.assertIn("Work: saved 2, refused 1", said)
        self.assertIn("Home: failed 1", said)
        asks = said.split("Ask actions, by outcome, for each zone")[1]
        self.assertIn("Work: saved 1, refused 1", asks)
        self.assertIn("Home: saved 1", asks)

    def test_it_counts_a_wrap_the_journal_does_not_keep_from_the_action_log_and_no_action_twice(self):
        (self.jobs / "operations.jsonl").write_text(self.row("b1" * 4, "todo-done", "Work", "saved", via="ask") + "\n")
        self.log('2026-11-21 09:00:00  wrap zone="Work" project="Acme Review"  ->  ok: Saved the wrap.  (page)',
                 '2026-11-21 09:05:00  wrap zone="Work" project="Acme Review"  ->  refused: Nothing was written.  (page)',
                 '2026-11-21 09:06:00  wrap zone="Home"  ->  ok: Saved.  (ask)',
                 '2026-11-21 09:07:00  todo-done zone="Work" key="x"  ->  ok: Ticked.  (ask)',     # the journal has this one
                 '2026-11-21 09:08:00  note-add zone="Work"  ->  ok: Added.  (ask)',
                 '2026-09-21 09:00:00  wrap zone="Work"  ->  ok: old.  (page)')
        said, _ = self.text()
        self.assertIn("Work: saved 1, refused 1", said.split("Wraps")[1].split("Ask actions")[0])
        self.assertIn("Home: saved 1", said.split("Wraps")[1].split("Ask actions")[0])
        asks = said.split("Ask actions, by outcome, for each zone")[1]
        self.assertIn("Work: saved 2", asks)         # the ticked line, from the journal, and the added note, from the log
        self.assertIn("Home: saved 1", asks)

    def test_no_figure_adds_two_zones_together(self):
        (self.jobs / "operations.jsonl").write_text("\n".join(self.row("c%d" % i * 4, "wrap", z, "saved")
                                                              for i, z in enumerate(("Work", "Home", "Work"))) + "\n")
        said, _ = self.text()
        self.assertIn("Work: saved 2", said)
        self.assertIn("Home: saved 1", said)
        self.assertNotRegex(said, r"saved 3")

    def test_it_says_it_has_no_card_data_when_counting_is_off_or_the_file_is_absent(self):
        said, _ = self.text()
        self.assertIn("No card data: no counts file.", said)
        self.counts_file({"v": 1, "counts": {"threads": {"2026-11-22": 1}}})
        garrick_lib.save_preferences(self.root, {"usage-counts": False})
        said, failed = self.text()
        self.assertIn("No card data: counting card opens is switched off.", said)
        self.assertNotIn("threads", said)

    def test_it_names_each_source_it_could_not_read(self):
        self.file.write_text("not json")
        said, failed = self.text()
        self.assertIn("Could not read:", said)
        self.assertIn("System/garrick-usage.json", said)
        self.assertIn("no operations journal", said)
        self.assertIn("no action log", said)
        self.assertEqual(3, len(failed))

    def test_it_runs_with_the_status_extra_absent_and_writes_nothing(self):
        self.assertFalse((self.root / "System" / "status").exists())
        self.counts_file({"v": 1, "counts": {"graph": {TODAY: 3}}})
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if "tools" not in p.parts)
        env = dict(os.environ, GARRICK_JOBS_DIR=str(self.jobs), HOME=str(self.home))
        done = subprocess.run([sys.executable, "-B", str(USAGE), "--root", str(self.root), "--days", "7"], capture_output=True,
                              text=True, env=env, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertRegex(done.stdout, r"graph\s+3")
        self.assertIn("Garrick usage, 7 days", done.stdout)
        after = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if "tools" not in p.parts)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
