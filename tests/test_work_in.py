"""The nightly run works in the answers still waiting (#550), and what it cannot is asked on the Context card.

    cd tests && python3 -m unittest test_work_in

The assistant is never called: agent.run is replaced. Invented names only: the zones are Work and Personal.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import GIT_ENV, git, git_init, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
JOBS = REPO / "extras" / "jobs"
sys.path.insert(0, str(JOBS))
sys.path.insert(0, str(REPO / "extras" / "status"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


work_in = load("garrick_work_in", JOBS / "work_in.py")
agent = work_in.agent                                 # the module work_in calls, so the patches below reach it
import finding_queue as fq  # noqa: E402

DAY = dt.date(2026, 11, 13)
DONE = "WORKED 1 HELD 0\n" + work_in.SENTINEL
TWO_PLACES = [("Zones/Work", "Work", 1), ("Wikis/Knowledge", "the Knowledge wiki", 2)]


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name).resolve() / "ws"
        patch = mock.patch.dict(os.environ, {k: v for k, v in GIT_ENV.items() if k.startswith(("GIT_", "HOME"))})
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("GIT_DIR", None)
        for wiki in ("Meetings", "Knowledge"):
            write(self.ws / "Wikis" / wiki / "wiki" / "index.md", "# Index\n")
        git_init(self.ws / "Wikis")
        git(self.ws / "Wikis", "add", "-A")
        git(self.ws / "Wikis", "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")

    def held(self):
        return json.loads(self.ws.joinpath(*work_in.HELD_FILE).read_text())["held"] if self.ws.joinpath(*work_in.HELD_FILE).exists() else {}

    def run_main(self, places, runs):
        """main() with these places waiting, and agent.run answering each call with the next of `runs`: (code, text, a file it writes)."""
        calls = []

        def fake(tier, prompt, allow=(), cwd=None, **kw):
            calls.append(prompt)
            code, text, wrote = runs[len(calls) - 1]
            if wrote:
                write(self.ws / wrote, "# Answered\n")
            return code, text
        with mock.patch.object(work_in, "waiting", return_value=places), mock.patch.object(agent, "run", fake):
            code = work_in.main(["--workspace", str(self.ws), "--today", DAY.isoformat()])
        return code, calls


class TestTheNightlyWorksInWhatIsWaiting(Case):
    def test_one_call_for_each_place_that_holds_an_answer_and_each_names_its_own_place_only(self):
        code, calls = self.run_main(TWO_PLACES, [(0, DONE, "Wikis/Meetings/wiki/a.md"), (0, DONE, "Wikis/Knowledge/wiki/b.md")])
        self.assertEqual(0, code)
        self.assertEqual(2, len(calls))
        self.assertTrue(calls[0].startswith("work in the answers in Work.\n"))
        self.assertTrue(calls[1].startswith("work in the answers in the Knowledge wiki.\n"))
        self.assertNotIn("Knowledge", calls[0])
        self.assertNotIn("Work only", calls[1])
        self.assertNotIn("meetings skill", calls[1])
        self.assertEqual({}, self.held())

    def test_a_place_with_nothing_waiting_costs_no_call(self):
        code, calls = self.run_main([], [])
        self.assertEqual((0, []), (code, calls))
        self.assertFalse(self.ws.joinpath(*work_in.HELD_FILE).exists())

    def test_what_the_call_wrote_is_committed_by_name_in_the_wikis_repository(self):
        self.run_main(TWO_PLACES[:1], [(0, DONE, "Wikis/Meetings/wiki/a.md")])
        self.assertIn("Answers worked in for Work", git(self.ws / "Wikis", "log", "-1", "--format=%s"))
        self.assertEqual("", git(self.ws / "Wikis", "status", "--porcelain").strip())

    def test_a_refused_commit_puts_the_files_back_in_the_index_and_the_place_is_left(self):
        hook = self.ws / "Wikis" / ".git" / "hooks" / "pre-commit"
        write(hook, "#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.run_main(TWO_PLACES[:1], [(0, DONE, "Wikis/Meetings/wiki/a.md")])
        self.assertEqual({"Zones/Work": {"why": "commit", "day": "2026-11-13"}}, self.held())
        self.assertEqual("", git(self.ws / "Wikis", "diff", "--cached", "--name-only").strip())

    def test_the_reasons_a_place_is_left_are_kept_as_codes_and_nothing_else(self):
        for runs, why in (([(agent.EXIT_CAP, "", None)], "cap"), ([(1, "", None)], "assistant"), ([(0, "no sentinel", None)], "incomplete"),
                          ([(0, "WORKED 1 HELD 1\n" + work_in.SENTINEL, None)], "held")):
            code, _ = self.run_main(TWO_PLACES[:1], runs)
            self.assertEqual(0, code)                                                   # a place left is no fault of the night
            self.assertEqual({"Zones/Work": {"why": why, "day": "2026-11-13"}}, self.held(), why)
            self.assertIn(why, fq.ANSWERS_HELD)
        raw = self.ws.joinpath(*work_in.HELD_FILE).read_text()
        self.assertNotIn("Wikis/", raw)

    def test_a_clean_run_takes_the_place_out_and_a_place_with_nothing_waiting_is_dropped(self):
        work_in.write_held(self.ws, {"Zones/Work": {"why": "cap", "day": "2026-11-12"}, "Zones/Personal": {"why": "held", "day": "2026-11-12"}})
        self.run_main(TWO_PLACES[:1], [(0, DONE, "Wikis/Meetings/wiki/a.md")])
        self.assertEqual({}, self.held())

    def test_without_the_panel_the_step_is_a_no_op_with_its_own_exit(self):
        with mock.patch.object(work_in, "STATUS", Path(self.tmp.name) / "none"):
            self.assertEqual(work_in.EXIT_NO_PANEL, work_in.main(["--workspace", str(self.ws)]))

    def test_the_call_runs_under_the_jobs_caps_and_profile_and_writes_no_commit(self):
        seen = {}

        def fake(tier, prompt, allow=(), cwd=None, **kw):
            seen.update(allow=list(allow), cwd=cwd, kw=kw, prompt=prompt)
            return 0, DONE
        with mock.patch.object(work_in, "waiting", return_value=TWO_PLACES[:1]), mock.patch.object(agent, "run", fake):
            work_in.main(["--workspace", str(self.ws)])
        self.assertEqual({}, seen["kw"])                                                # no budget, job name or cap of its own: agent.run's defaults hold
        self.assertIn("Never commit", seen["prompt"])
        self.assertTrue(all(not a.startswith("Bash(git") for a in seen["allow"]))


class TestAFailedCallLeavesNothingBehind(Case):
    def refusing_hook(self):
        hook = self.ws / "Wikis" / ".git" / "hooks" / "pre-commit"
        write(hook, "#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)

    def test_a_refusing_hook_leaves_the_tree_as_it_was_and_the_place_is_held(self):
        self.refusing_hook()
        index = self.ws / "Wikis" / "Meetings" / "wiki" / "index.md"
        dirty = self.ws / "Wikis" / "Meetings" / "wiki" / "mine.md"
        write(dirty, "# Mine\n")                          # dirty before the call: never touched

        def fake(tier, prompt, allow=(), cwd=None, **kw):
            index.write_text("# Index\nrefused text\n")
            write(self.ws / "Wikis" / "Meetings" / "wiki" / "new.md", "# New\n")
            return 0, DONE
        with mock.patch.object(work_in, "waiting", return_value=TWO_PLACES[:1]), mock.patch.object(agent, "run", fake):
            work_in.main(["--workspace", str(self.ws), "--today", DAY.isoformat()])
        self.assertEqual("# Index\n", index.read_text())
        self.assertFalse((self.ws / "Wikis" / "Meetings" / "wiki" / "new.md").exists())
        self.assertEqual("# Mine\n", dirty.read_text())
        self.assertEqual("?? Meetings/wiki/mine.md", git(self.ws / "Wikis", "status", "--porcelain").strip())
        self.assertEqual({"Zones/Work": {"why": "commit", "day": "2026-11-13"}}, self.held())

    def test_a_call_without_its_sentinel_or_timed_out_is_put_back(self):
        index = self.ws / "Wikis" / "Meetings" / "wiki" / "index.md"
        for code, text, why in ((0, "no sentinel", "incomplete"), (124, "", "assistant")):
            def fake(tier, prompt, allow=(), cwd=None, **kw):
                index.write_text("# Index\nhalf written\n")
                return code, text
            with mock.patch.object(work_in, "waiting", return_value=TWO_PLACES[:1]), mock.patch.object(agent, "run", fake):
                work_in.main(["--workspace", str(self.ws), "--today", DAY.isoformat()])
            self.assertEqual("# Index\n", index.read_text(), why)
            self.assertEqual(why, self.held()["Zones/Work"]["why"])

    def test_with_a_short_deadline_the_second_place_is_not_started_and_is_held(self):
        calls, now = [], [1000.0]

        def fake(tier, prompt, allow=(), cwd=None, **kw):
            calls.append(kw)
            now[0] += 90                                  # the first call uses most of the 100 seconds
            return 0, DONE
        with mock.patch.object(work_in, "waiting", return_value=TWO_PLACES), mock.patch.object(agent, "run", fake), \
                mock.patch.object(work_in.time, "time", lambda: now[0]):
            work_in.main(["--workspace", str(self.ws), "--limit", "100", "--today", DAY.isoformat()])
        self.assertEqual(1, len(calls))
        self.assertIn("timeout", calls[0])
        self.assertLess(calls[0]["timeout"], 100)
        self.assertEqual({"Wikis/Knowledge": {"why": "cap", "day": "2026-11-13"}}, self.held())


class TestWhatTheNightCouldNotWorkInIsAskedOnTheCard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        self.places = {"Zones/Work": "Work", "Zones/Personal": "Personal", "Wikis/Knowledge": "the Knowledge wiki"}

    def save(self, held):
        write(self.ws.joinpath(*fq.HELD_FILE), json.dumps({"held": held}))

    def test_a_place_left_with_an_answer_still_waiting_is_a_question_with_its_reason_and_real_answers(self):
        self.save({"Zones/Work": {"why": "cap", "day": "2026-11-13"}})
        out = fq.held_answers(self.ws, self.places, {"Zones/Work": 2, "Zones/Personal": 1}, set())
        self.assertEqual(["Zones/Work"], list(out))                                      # its own place only
        q = out["Zones/Work"][0]
        self.assertEqual("answers-held", q["id"])
        self.assertIn("limit", q["why"])
        self.assertEqual(["Work them in with my assistant", "Not now"], [a["label"] for a in q["answers"]])
        self.assertEqual("work in the answers in Work", q["answers"][0]["phrase"])
        self.assertEqual(fq.QUESTION, fq.KIND_CLASS["answers-held"])
        shown = fq.question_html(q)
        for word in ("Wikis/", ".md", "`", "python3"):
            self.assertNotIn(word, shown)

    def test_no_question_for_a_place_with_no_answer_left_or_an_unknown_reason_or_a_put_off_one(self):
        self.save({"Zones/Work": {"why": "cap", "day": "2026-11-13"}, "Zones/Personal": {"why": "weird", "day": "x"}})
        self.assertEqual({}, fq.held_answers(self.ws, self.places, {"Zones/Work": 0, "Zones/Personal": 3}, set()))
        key = fq.later_key("answers-held", "Zones/Work")
        self.assertEqual({}, fq.held_answers(self.ws, self.places, {"Zones/Work": 1}, {key}))
        self.assertEqual({}, fq.held_answers(self.ws / "nowhere", self.places, {"Zones/Work": 1}, set()))

    def test_not_now_is_a_valid_finding_answer(self):
        self.assertEqual(("later",), fq.VERB_ANSWERS["answers-held"])


if __name__ == "__main__":
    unittest.main()
