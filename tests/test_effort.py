"""The time and token ledger, extras/status/effort.py, and the Effort card that shows it.

    python3 -m unittest discover -s tests

Transcripts are written here in the shape Claude Code gives them, for a
fictional workspace. The ledger must place each session in its thread, count
each message once, leave idle gaps and headless runs out, keep days past their
transcripts, and never put a word of a transcript on the page.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace, project_hub, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


effort = _load("garrick_effort_test", REPO / "extras" / "status" / "effort.py")
status = _load("garrick_status_effort_test", REPO / "extras" / "status" / "status.py")

SECRET = "the walk-away price is forty"        # said in a session; must never reach the page
USAGE = {"input_tokens": 10, "output_tokens": 1000, "cache_read_input_tokens": 100000, "cache_creation_input_tokens": 20000,
         "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 20000}}
# opus-5-5 at $4 in, $20 out, $0.20 cache read, $8 an hour-long cache write, per million tokens
COST = (10 * 4 + 1000 * 20 + 100000 * .2 + 20000 * 8) / 1e6


class EffortCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.root = base / "Workspace"
        build_workspace(self.root)
        write(self.root / "Zones" / "Work" / "Cedar Notes" / "Cedar Notes.md", project_hub("Work", "Cedar Notes", "cedar"))
        self.claude = base / "claude"
        self.store = base / "jobs" / "effort.jsonl"
        self.env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude)})
        self.env.start()
        self.day = dt.datetime.now().replace(hour=10, minute=0, second=0, microsecond=0) - dt.timedelta(days=1)
        self.n = 0

    def tearDown(self):
        self.env.stop()
        self._tmp.cleanup()

    def at(self, minutes):
        return (self.day + dt.timedelta(minutes=minutes)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def session(self, cwd, minutes=(0, 1, 2), writes=(), entry="cli", model="claude-opus-5-5", sub=None):
        """A transcript: a user message, then assistant messages at `minutes`,
        each written twice, as Claude Code does for a message with two blocks."""
        self.n += 1
        sid = "s%d" % self.n
        cwd = str(cwd)
        folder = self.claude / "projects" / effort.encoded(Path(cwd))
        folder.mkdir(parents=True, exist_ok=True)
        lines = [{"type": "user", "entrypoint": entry, "cwd": cwd, "sessionId": sid, "timestamp": self.at(minutes[0]),
                  "message": {"role": "user", "content": SECRET}}]
        for i, m in enumerate(minutes):
            content = [{"type": "text", "text": SECRET}]
            if i == 0:
                content += [{"type": "tool_use", "name": "Edit", "input": {"file_path": str(w), "old_string": SECRET}} for w in writes]
            for _ in range(2):
                lines.append({"type": "assistant", "entrypoint": entry, "cwd": cwd, "sessionId": sid, "timestamp": self.at(m),
                              "message": {"id": "%s-m%d" % (sid, i), "model": model, "usage": USAGE, "content": content}})
        (folder / (sid + ".jsonl")).write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")
        if sub:
            subs = folder / sid / "subagents"
            subs.mkdir(parents=True)
            (subs / "agent-1.jsonl").write_text(json.dumps(
                {"type": "assistant", "cwd": cwd, "timestamp": self.at(sub),
                 "message": {"id": "sub-1", "model": model, "usage": USAGE, "content": []}}) + "\n", encoding="utf-8")
        return folder / (sid + ".jsonl")

    def ledger(self, **kw):
        out = {}
        for (day, zone, project, thread), r in effort.ledger(self.root, self.store, **kw).items():
            t = out.setdefault((zone, project, thread), {"seconds": 0, "cost": 0.0, "sessions": 0})
            for k in t:
                t[k] += r[k]
        return out


class TestAttribution(EffortCase):
    def test_a_thread_folder_names_the_thread(self):
        self.session(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing")
        self.assertIn(("Work", "Acme Review", "Pricing"), self.ledger())

    def test_a_project_session_takes_the_thread_it_wrote_in(self):
        acme = self.root / "Zones" / "Work" / "Acme Review"
        self.session(acme, writes=[acme / "Threads" / "Pricing" / "Pricing.md", acme / "Acme Review.md"])
        self.assertEqual(list(self.ledger()), [("Work", "Acme Review", "Pricing")])

    def test_the_rest_is_unassigned_never_guessed(self):
        self.session(self.root / "Zones" / "Work" / "Acme Review", writes=[self.root / "Zones" / "Work" / "Acme Review" / "Acme Review.md"])
        self.assertEqual(list(self.ledger()), [("Work", "Acme Review", "")])

    def test_a_project_without_thread_notes_is_its_own_thread(self):
        self.session(self.root / "Zones" / "Work" / "Cedar Notes")
        self.assertEqual(list(self.ledger()), [("Work", "Cedar Notes", "Cedar Notes")])

    def test_a_session_at_the_root_is_placed_by_what_it_wrote(self):
        self.session(self.root, writes=[self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md"])
        self.session(self.root / "System")
        self.assertEqual(sorted(self.ledger()), [("", "System", ""), ("Work", "Birch Entry", "Market Sizing")])

    def test_a_former_location_counts_as_the_workspace(self):
        old = Path(self._tmp.name).resolve() / "OldPlace"
        self.session(old / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing")
        self.assertEqual(self.ledger(), {})
        self.assertIn(("Work", "Acme Review", "Pricing"), self.ledger(also=[old]))

    def test_a_renamed_project_counts_under_its_new_name(self):
        old = Path(self._tmp.name).resolve() / "OldPlace"
        self.session(old / "Zones" / "Work" / "Acme Old" / "Threads" / "Pricing")
        self.session(self.root / "Zones" / "Work" / "Acme Old")
        moved = {"Zones/Work/Acme Old": "Zones/Work/Acme Review"}
        self.assertEqual(sorted(self.ledger(also=[old], moved=moved)), [("Work", "Acme Review", ""), ("Work", "Acme Review", "Pricing")])

    def test_a_folder_beside_the_workspace_is_not_it(self):
        self.session(Path(str(self.root) + "-demo") / "Zones" / "Work" / "Acme Review")
        self.assertEqual(self.ledger(), {})

    def test_headless_runs_are_the_jobs_ledgers(self):
        self.session(self.root / "Zones" / "Work" / "Cedar Notes", entry="sdk-cli")
        self.assertEqual(self.ledger(), {})


class TestCounting(EffortCase):
    def test_each_message_once_and_subagents_added(self):
        self.session(self.root / "Zones" / "Work" / "Cedar Notes", minutes=(0, 1), sub=1)
        row = self.ledger()[("Work", "Cedar Notes", "Cedar Notes")]
        self.assertAlmostEqual(row["cost"], 3 * COST, places=4)            # two messages and a subagent's, each line pair once
        self.assertEqual(row["sessions"], 1)

    def test_idle_gaps_are_not_work(self):
        self.session(self.root / "Zones" / "Work" / "Cedar Notes", minutes=(0, 4, 30, 33))
        self.assertEqual(self.ledger()[("Work", "Cedar Notes", "Cedar Notes")]["seconds"], 7 * 60)

    def test_a_model_without_a_price_counts_time_not_cost(self):
        self.session(self.root / "Zones" / "Work" / "Cedar Notes", model="claude-unknown-9")
        rows = effort.ledger(self.root, self.store)
        r = next(iter(rows.values()))
        self.assertEqual((r["cost"], r["unpriced"]), (0.0, 3))
        self.assertGreater(r["seconds"], 0)

    def test_prices(self):
        self.assertAlmostEqual(effort.usage_cost("claude-opus-5-5[1m]", USAGE), COST)
        self.assertAlmostEqual(effort.usage_cost("claude-opus-5-5", dict(USAGE, speed="fast")), 2 * COST)
        self.assertAlmostEqual(effort.usage_cost("claude-haiku-4-5-20251001", {"input_tokens": 1e6}), 1.0)
        self.assertIsNone(effort.usage_cost("<synthetic>", USAGE))


class TestHistory(EffortCase):
    def test_a_recorded_day_outlives_its_transcript(self):
        path = self.session(self.root / "Zones" / "Work" / "Cedar Notes")
        before = self.ledger()
        self.assertEqual(effort.record(self.root, self.store), 1)
        path.unlink()
        self.assertEqual(self.ledger(), before)
        self.assertNotIn(SECRET.split()[1], self.store.read_text())

    def test_the_fuller_count_wins(self):
        self.session(self.root / "Zones" / "Work" / "Cedar Notes")
        effort.record(self.root, self.store)
        lines = [json.loads(l) for l in self.store.read_text().splitlines()]
        lines[0]["cost"] = 999.0                                              # a day recorded before some of it was cleaned up
        self.store.write_text("".join(json.dumps(l) + "\n" for l in lines))
        self.assertEqual(self.ledger()[("Work", "Cedar Notes", "Cedar Notes")]["cost"], 999.0)


class TestThreadsView(EffortCase):
    """Time and Cost on the Threads card: the last 30 days over the same rows."""

    def page(self):
        return status.build(self.root, folder=self.store.parent)

    def on(self):
        write(self.root / "System" / "garrick-flags.json", json.dumps({"effort": True}))

    def threads(self, html):
        start = html.index('id="threads"')
        return html[start:html.index('<details class="card"', start + 1)]

    def test_off_unless_switched_on(self):
        self.session(self.root / "Zones" / "Work" / "Cedar Notes")
        html = self.page()
        self.assertNotIn('class="tmodes"', html)
        self.assertNotIn('data-s="', html)
        self.assertNotIn('id="effort"', html)

    def test_the_same_rows_with_figures(self):
        self.on()
        acme = self.root / "Zones" / "Work" / "Acme Review"
        self.session(acme / "Threads" / "Pricing", minutes=(0, .5, 1))       # 1 minute, three messages
        self.session(acme, minutes=(0, 4))                                   # 4 minutes in the project, in no thread
        self.session(self.root / "Zones" / "Work" / "Cedar Notes")           # a project that is its own thread
        self.session(self.root / "System")                                   # outside the zones
        html = self.page()
        card = self.threads(html)
        self.assertNotIn('id="effort"', html)                                # no card of its own
        self.assertIn('<button type="button" data-tm="cost">Cost</button>', card)
        self.assertIn('class="tview" data-tm="updated"', card)
        unit = re.search(r'<div class="tunit" data-a="\d+" data-s="(\d+)" data-c="([\d.]+)"><div class="thread proj"[^>]*data-card="([^"]*)"', card)
        self.assertEqual(json.loads(htmllib.unescape(unit.group(3)))["n"], "Acme Review")
        self.assertEqual(int(unit.group(1)), 5 * 60)                         # its thread and its own work
        self.assertAlmostEqual(float(unit.group(2)), 5 * COST, places=3)
        self.assertIn(">5 min<", card)
        self.assertIn("Outside the zones 2 min", card)                       # what no row took, said once
        self.assertIn("Last 30 days: 9 min active", card)
        self.assertNotIn(SECRET.split()[1], html)

    def test_a_parked_thread_keeps_its_figures_in_the_parked_fold(self):
        self.on()
        pricing = self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        pricing.write_text(pricing.read_text().replace("status: active", "status: parked"))
        self.session(pricing.parent)
        html = self.page()
        parked = html[html.index('id="parked-work"'):]
        parked = parked[:parked.index("</details>")]
        self.assertIn('data-s="120"', parked)

    def test_the_view_sorts_and_is_remembered(self):
        self.assertIn("garrick-threads-view", status.TVIEW_JS)
        self.assertIn("return a.dataset.a-b.dataset.a", status.TVIEW_JS)     # Updated puts them back by name


if __name__ == "__main__":
    unittest.main()
