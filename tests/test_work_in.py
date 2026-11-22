"""The nightly run works in the answers still waiting (#550), and what it cannot is asked on the Context card.

    cd tests && python3 -m unittest test_work_in

The assistant is never called: agent.run is replaced. Invented names only: the zones are Work and Personal.
"""

from __future__ import annotations

import datetime as dt
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

from fixtures import GIT_ENV, git, git_init, write  # noqa: E402
from panel_case import PanelCase, commit_all  # noqa: E402
from test_questions_panel import ACME, question  # noqa: E402

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
REAL_LISTED = work_in.listed_paths                   # the Case below replaces it, since most tests do not care which pages are listed
agent = work_in.agent                                 # the module work_in calls, so the patches below reach it
import finding_queue as fq  # noqa: E402

DAY = dt.date(2026, 11, 13)
DONE = "WORKED 1 HELD 0\n" + work_in.SENTINEL
TWO_PLACES = [("Zones/Work", "Work", 1), ("Wikis/Knowledge", "the Knowledge wiki", 2)]


class Everything:
    """The paths `question-work` would list, when a test does not care which: any path."""

    def __contains__(self, item):
        return True


def expand(places):
    """(scope, place, how many answers) as the one entry each answer has: the scope, the place, its wiki and its question file."""
    return [(scope, place, "Knowledge" if scope == work_in.KNOWLEDGE else "Meetings", "questions/q%d.md" % (i + 1))
            for scope, place, n in places for i in range(n)]


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name).resolve() / "ws"
        listing = mock.patch.object(work_in, "listed_paths", return_value=Everything())
        listing.start()
        self.addCleanup(listing.stop)
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
        with mock.patch.object(work_in, "answers", return_value=expand(places)), mock.patch.object(agent, "run", fake):
            code = work_in.main(["--workspace", str(self.ws), "--today", DAY.isoformat()])
        return code, calls


class TestTheRequestNamesTheTools(unittest.TestCase):
    """#635: the call is told which tools it has, so it does not spend turns on shell commands the allow list refuses."""

    def test_the_request_names_the_tools_and_what_not_to_do(self):
        text = work_in.prompt_for("Zones/Work", "Work", "Meetings", "questions/q1.md")
        for needle in ("Read, Grep and Glob", "question-work", "question-done", "no other shell command", "never wait for a file to change",
                       "never run the lint"):
            self.assertIn(needle, text)

    def test_the_request_and_both_skills_agree_with_the_allow_list(self):
        bash = [a for a in work_in.ALLOW if a.startswith("Bash(")]
        verbs = sorted(re.search(r"page_action\.py ([a-z-]+):\*\)", a).group(1) for a in bash)
        self.assertEqual(["question-done", "question-work"], verbs)
        self.assertEqual(["Edit", "Glob", "Grep", "Read", "Write"], sorted(a for a in work_in.ALLOW if not a.startswith("Bash(")))
        text = work_in.prompt_for("Zones/Work", "Work", "Meetings", "questions/q1.md")
        for skill in ("meetings", "knowledge"):
            body = (REPO / "template" / "System" / "skills" / skill / "SKILL.md").read_text()
            note = body[body.index("**Run unattended.**"):]
            note = note[:note.index("\n\n")]
            for verb in verbs:
                self.assertIn(verb, note, skill)
                self.assertIn(verb, text)
            for needle in ("Read, Grep and Glob", "never\nwait for a file to change", "never run the lint"):
                self.assertIn(needle, note, skill)
        shell = set(re.findall(r"`python3 ([\w/.]+ [a-z-]+)`", text))
        self.assertEqual({"System/status/page_action.py question-work", "System/status/page_action.py question-done"}, shell)


class TestTheNightlyWorksInWhatIsWaiting(Case):
    def test_one_call_for_each_answer_and_each_names_its_own_question_and_place_only(self):
        code, calls = self.run_main(TWO_PLACES, [(0, DONE, "Wikis/Meetings/wiki/a.md"), (0, DONE, "Wikis/Knowledge/wiki/b.md"),
                                                 (0, DONE, "Wikis/Knowledge/wiki/c.md")])
        self.assertEqual(0, code)
        self.assertEqual(3, len(calls))
        self.assertTrue(calls[0].startswith("work in the answer in Work.\n"))
        self.assertIn("`questions/q1.md` in the Meetings wiki", calls[0])
        self.assertTrue(calls[1].startswith("work in the answer in the Knowledge wiki.\n"))
        self.assertIn("`questions/q1.md` in the Knowledge wiki", calls[1])
        self.assertIn("`questions/q2.md` in the Knowledge wiki", calls[2])
        self.assertNotIn("Knowledge", calls[0])
        self.assertNotIn("meetings skill", calls[1])
        self.assertEqual({}, self.held())

    def test_a_call_stopped_at_its_limit_fails_the_step_and_the_place_is_still_left(self):
        """#566: exit 124 for the nightly summary, and the other places are still tried."""
        code, calls = self.run_main(TWO_PLACES, [(agent.EXIT_TIMEOUT, "", None), (0, DONE, "Wikis/Knowledge/wiki/b.md"),
                                                 (0, DONE, "Wikis/Knowledge/wiki/c.md")])
        self.assertEqual(agent.EXIT_TIMEOUT, code)
        self.assertEqual(3, len(calls))
        self.assertEqual({"Zones/Work": {"why": "assistant", "day": "2026-11-13"}}, self.held())

    def test_a_run_with_no_stopped_call_still_exits_0_after_one(self):
        self.run_main(TWO_PLACES[:1], [(agent.EXIT_TIMEOUT, "", None)])
        code, _ = self.run_main(TWO_PLACES[:1], [(0, DONE, "Wikis/Meetings/wiki/a.md")])
        self.assertEqual(0, code)

    def test_a_place_with_nothing_waiting_costs_no_call(self):
        code, calls = self.run_main([], [])
        self.assertEqual((0, []), (code, calls))
        self.assertFalse(self.ws.joinpath(*work_in.HELD_FILE).exists())

    def test_what_the_call_wrote_is_committed_by_name_in_the_wikis_repository(self):
        self.run_main(TWO_PLACES[:1], [(0, DONE, "Wikis/Meetings/wiki/a.md")])
        self.assertIn("Answers worked in for Work", git(self.ws / "Wikis", "log", "-1", "--format=%s"))
        self.assertEqual("", git(self.ws / "Wikis", "status", "--porcelain").strip())

    def test_a_file_named_with_a_glob_is_committed_by_its_literal_name_and_never_takes_a_dirty_file_beside_it(self):
        wiki = self.ws / "Wikis"
        write(wiki / "Meetings" / "wiki" / "ab.md", "# Mine\n")
        git(wiki, "add", "-A")
        git(wiki, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "ab")
        (wiki / "Meetings" / "wiki" / "ab.md").write_text("# Mine, edited and not committed\n")
        self.run_main(TWO_PLACES[:1], [(0, DONE, "Wikis/Meetings/wiki/a*.md")])
        self.assertEqual(["Meetings/wiki/a*.md"], git(wiki, "show", "--name-only", "--format=", "HEAD").split("\n")[:1])
        self.assertEqual(" M Meetings/wiki/ab.md", git(wiki, "status", "--porcelain").rstrip())

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
        with mock.patch.object(work_in, "answers", return_value=expand(TWO_PLACES[:1])), mock.patch.object(agent, "run", fake):
            work_in.main(["--workspace", str(self.ws)])
        self.assertEqual({}, seen["kw"])                                                # no budget, job name or cap of its own: agent.run's defaults hold
        self.assertIn("Never commit", seen["prompt"])
        self.assertTrue(all(not a.startswith("Bash(git") for a in seen["allow"]))


class TestOneCallForEachAnswer(Case):
    """#629: each answer is its own call and its own commit, so a call stopped at the limit loses only its own question."""

    FOUR = [("Zones/Work", "Work", 4)]

    def wiki(self, name):
        return self.ws / "Wikis" / "Meetings" / "wiki" / name

    def timed(self, spend, runs, places=FOUR, limit="480"):
        """main() with a clock the calls move on: `spend` seconds for each call. Returns (exit code, prompts, the lines printed)."""
        import contextlib
        import io
        calls, now = [], [1000.0]

        def fake(tier, prompt, allow=(), cwd=None, **kw):
            calls.append(prompt)
            code, text, wrote = runs[len(calls) - 1]
            now[0] += spend[len(calls) - 1]
            for name in ([wrote] if isinstance(wrote, str) else wrote or []):
                write(self.ws / name, "# Answered %d\n" % len(calls))
            return code, text
        out = io.StringIO()
        with mock.patch.object(work_in, "answers", return_value=expand(places)), mock.patch.object(agent, "run", fake), \
                mock.patch.object(work_in.time, "time", lambda: now[0]), contextlib.redirect_stdout(out):
            code = work_in.main(["--workspace", str(self.ws), "--limit", limit, "--today", DAY.isoformat()])
        return code, calls, out.getvalue()

    def log(self):
        return git(self.ws / "Wikis", "log", "--format=%s", "-n", "10").strip().splitlines()

    def test_four_answers_where_the_third_call_is_stopped_commit_two_put_back_one_and_leave_one(self):
        runs = [(0, DONE, "Wikis/Meetings/wiki/a1.md"), (0, DONE, "Wikis/Meetings/wiki/a2.md"),
                (agent.EXIT_TIMEOUT, "", "Wikis/Meetings/wiki/a3.md"), (0, DONE, "Wikis/Meetings/wiki/a4.md")]
        code, calls, said = self.timed([100, 100, 280, 10], runs)
        self.assertEqual(agent.EXIT_TIMEOUT, code)                       # a call stopped while it ran
        self.assertEqual(3, len(calls))                                  # the fourth was not started: no time was left
        self.assertTrue(self.wiki("a1.md").exists() and self.wiki("a2.md").exists())
        self.assertFalse(self.wiki("a3.md").exists())                    # the stopped call's own question is put back
        self.assertFalse(self.wiki("a4.md").exists())
        self.assertEqual(["Answers worked in for Work: 1 question"] * 2 + ["start"], self.log())
        self.assertEqual("", git(self.ws / "Wikis", "status", "--porcelain").strip())
        self.assertEqual({"Zones/Work": {"why": "assistant", "day": "2026-11-13"}}, self.held())
        self.assertIn("Work: 2 worked in, 2 left", said)

    def test_the_limit_reached_between_two_answers_reports_what_was_worked_in_and_what_is_left_and_exits_0(self):
        runs = [(0, DONE, "Wikis/Meetings/wiki/a1.md"), (0, DONE, "Wikis/Meetings/wiki/a2.md"), (0, DONE, "Wikis/Meetings/wiki/a3.md")]
        code, calls, said = self.timed([230, 230, 10], runs)
        self.assertEqual(0, code)                                        # not exit 124: no call was stopped
        self.assertEqual(2, len(calls))
        self.assertIn("work_in: Work: 2 worked in, 2 left (cap)", said)
        self.assertNotIn("124", said)
        self.assertEqual({"Zones/Work": {"why": "cap", "day": "2026-11-13"}}, self.held())

    def test_the_next_night_works_in_the_rest_and_no_answer_is_redone(self):
        runs = [(0, DONE, "Wikis/Meetings/wiki/a%d.md" % i) for i in (1, 2)]
        self.timed([230, 230], runs)                                     # the first night: two of four
        code, calls, said = self.timed([100, 100], [(0, DONE, "Wikis/Meetings/wiki/a3.md"), (0, DONE, "Wikis/Meetings/wiki/a4.md")],
                                       places=[("Zones/Work", "Work", 2)])
        self.assertEqual(0, code)
        self.assertIn("Work: 2 worked in, 0 left", said)
        self.assertEqual({}, self.held())
        self.assertEqual(4, len([l for l in self.log() if l.startswith("Answers worked in")]))

    def test_each_commit_goes_through_the_repositorys_hook_and_never_around_it(self):
        hook = self.ws / "Wikis" / ".git" / "hooks" / "pre-commit"
        ran = self.ws / "hook-ran"
        write(hook, "#!/bin/sh\necho x >> '%s'\nexit 0\n" % ran)
        hook.chmod(0o755)
        self.timed([10, 10], [(0, DONE, "Wikis/Meetings/wiki/a1.md"), (0, DONE, "Wikis/Meetings/wiki/a2.md")], places=[("Zones/Work", "Work", 2)])
        self.assertEqual(2, len(ran.read_text().split()))                # once for each answer
        self.assertNotIn("no-verify", (JOBS / "work_in.py").read_text())

    def test_a_refusing_hook_puts_back_only_the_answer_it_refused(self):
        hook = self.ws / "Wikis" / ".git" / "hooks" / "pre-commit"
        write(hook, "#!/bin/sh\ngit diff --cached --name-only | grep -q a2.md && exit 1\nexit 0\n")
        hook.chmod(0o755)
        self.timed([10, 10], [(0, DONE, "Wikis/Meetings/wiki/a1.md"), (0, DONE, "Wikis/Meetings/wiki/a2.md")], places=[("Zones/Work", "Work", 2)])
        self.assertTrue(self.wiki("a1.md").exists())
        self.assertFalse(self.wiki("a2.md").exists())
        self.assertEqual("commit", self.held()["Zones/Work"]["why"])

    def test_each_count_is_of_one_place_and_no_line_adds_two_places(self):
        places = [("Zones/Work", "Work", 2), ("Zones/Personal", "Personal", 1)]
        runs = [(0, DONE, "Wikis/Meetings/wiki/a%d.md" % i) for i in (1, 2, 3)]
        code, calls, said = self.timed([10, 10, 10], runs, places=places)
        self.assertEqual(3, len(calls))
        lines = [l for l in said.splitlines() if l.startswith("work_in:")]
        self.assertEqual(["work_in: Work: 2 worked in, 0 left", "work_in: Personal: 1 worked in, 0 left"], lines)
        for call in calls:
            self.assertEqual(1, call.count("work in the answer in "))     # a call names one place
        self.assertNotIn("3 worked in", said)

    def test_the_answers_come_oldest_first_in_each_place_zones_by_name_then_the_knowledge_wiki(self):
        class Panel:
            @staticmethod
            def build(ws, C, today, link, collect=None):
                collect += [("Personal", "Meetings", "questions/p1.md", "2026-11-02"), ("Knowledge", "Knowledge", "questions/k1.md", "2026-10-01"),
                            ("Work", "Meetings", "questions/w2.md", "2026-11-05"), ("Work", "Meetings", "questions/w1.md", "2026-11-01"),
                            ("Work", "Meetings", "questions/w1.md", "2026-11-01")]
                return {"buckets": {}}
        with mock.patch.object(work_in, "panel", return_value=Panel):
            got = work_in.answers(self.ws, DAY)
        self.assertEqual([("Zones/Personal", "Personal", "Meetings", "questions/p1.md"), ("Zones/Work", "Work", "Meetings", "questions/w1.md"),
                          ("Zones/Work", "Work", "Meetings", "questions/w2.md"),
                          ("Wikis/Knowledge", "the Knowledge wiki", "Knowledge", "questions/k1.md")], got)


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
        with mock.patch.object(work_in, "answers", return_value=expand(TWO_PLACES[:1])), mock.patch.object(agent, "run", fake):
            work_in.main(["--workspace", str(self.ws), "--today", DAY.isoformat()])
        self.assertEqual("# Index\n", index.read_text())
        self.assertFalse((self.ws / "Wikis" / "Meetings" / "wiki" / "new.md").exists())
        self.assertEqual("# Mine\n", dirty.read_text())
        kept = list((self.ws / "Wikis" / ".git" / "garrick-put-back").glob("*/Meetings/wiki/*.md"))
        self.assertEqual({"index.md": "# Index\nrefused text\n", "new.md": "# New\n"},
                         {k.name: k.read_text() for k in kept})          # what was put back is kept, in that repository
        self.assertEqual("?? Meetings/wiki/mine.md", git(self.ws / "Wikis", "status", "--porcelain").strip())
        self.assertEqual({"Zones/Work": {"why": "commit", "day": "2026-11-13"}}, self.held())

    def test_a_call_without_its_sentinel_or_timed_out_is_put_back(self):
        index = self.ws / "Wikis" / "Meetings" / "wiki" / "index.md"
        for code, text, why in ((0, "no sentinel", "incomplete"), (124, "", "assistant")):
            def fake(tier, prompt, allow=(), cwd=None, **kw):
                index.write_text("# Index\nhalf written\n")
                return code, text
            with mock.patch.object(work_in, "answers", return_value=expand(TWO_PLACES[:1])), mock.patch.object(agent, "run", fake):
                work_in.main(["--workspace", str(self.ws), "--today", DAY.isoformat()])
            self.assertEqual("# Index\n", index.read_text(), why)
            self.assertEqual(why, self.held()["Zones/Work"]["why"])

    def test_a_call_that_worked_nothing_in_and_held_nothing_is_incomplete(self):
        index = self.ws / "Wikis" / "Meetings" / "wiki" / "index.md"

        def fake(tier, prompt, allow=(), cwd=None, **kw):
            index.write_text("# Index\nhalf written\n")
            return 0, "WORKED 0 HELD 0\n" + work_in.SENTINEL
        before = git(self.ws / "Wikis", "rev-parse", "HEAD").strip()
        with mock.patch.object(work_in, "answers", return_value=expand(TWO_PLACES[:1])), mock.patch.object(agent, "run", fake):
            work_in.main(["--workspace", str(self.ws), "--today", DAY.isoformat()])
        self.assertEqual("# Index\n", index.read_text())
        self.assertEqual(before, git(self.ws / "Wikis", "rev-parse", "HEAD").strip())
        self.assertNotIn("0 questions", git(self.ws / "Wikis", "log", "--format=%s"))
        self.assertEqual({"Zones/Work": {"why": "incomplete", "day": "2026-11-13"}}, self.held())

    def test_with_a_short_deadline_the_second_place_is_not_started_and_is_held(self):
        calls, now = [], [1000.0]

        def fake(tier, prompt, allow=(), cwd=None, **kw):
            calls.append(kw)
            now[0] += 90                                  # the first call uses most of the 100 seconds
            return 0, DONE
        with mock.patch.object(work_in, "answers", return_value=expand(TWO_PLACES)), mock.patch.object(agent, "run", fake), \
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



class TestAQuestionStoppedTwice(TestOneCallForEachAnswer):
    """#629, the optional part: a question whose call is stopped at the limit on two runs is held as too long, the card says so, and the
    night works in the others. The file keeps a hash of the question, never its path."""

    TWO = [("Zones/Work", "Work", 2)]

    def stops(self):
        return json.loads(self.ws.joinpath(*work_in.HELD_FILE).read_text()).get("stopped", {})

    def test_stopped_once_is_not_held_and_the_count_waits_for_the_next_night(self):
        runs = [(agent.EXIT_TIMEOUT, "", None), (0, DONE, "Wikis/Meetings/wiki/a2.md")]
        code, calls, said = self.timed([100, 10], runs, places=self.TWO)
        self.assertEqual(agent.EXIT_TIMEOUT, code)
        self.assertEqual(2, len(calls))
        self.assertEqual({"Zones/Work": {"why": "assistant", "day": "2026-11-13"}}, self.held())          # the reason is the stopped call's, not too long
        self.assertEqual([1], [v["n"] for v in self.stops().values()])

    def test_stopped_on_two_runs_it_is_held_as_too_long_and_the_next_night_skips_it_and_works_the_others(self):
        self.timed([100, 10], [(agent.EXIT_TIMEOUT, "", None), (0, DONE, "Wikis/Meetings/wiki/a2.md")], places=self.TWO)
        code, calls, said = self.timed([100], [(agent.EXIT_TIMEOUT, "", None)], places=[("Zones/Work", "Work", 1)])          # the second run stops it
        self.assertEqual(agent.EXIT_TIMEOUT, code)
        self.assertEqual({"Zones/Work": {"why": "long", "day": "2026-11-13"}}, self.held())
        self.assertEqual([2], [v["n"] for v in self.stops().values()])
        code, calls, said = self.timed([10, 10], [(0, DONE, "Wikis/Meetings/wiki/a3.md")], places=self.TWO)               # the third night
        self.assertEqual(0, code)                                        # no call was stopped
        self.assertEqual(1, len(calls))                                  # the held question is not called again; the other is
        self.assertIn("`questions/q2.md`", calls[0])
        self.assertIn("Work: 1 worked in, 1 left (long)", said)
        self.assertEqual({"Zones/Work": {"why": "long", "day": "2026-11-13"}}, self.held())

    def test_the_file_holds_a_hash_and_nothing_that_names_the_question(self):
        self.timed([100], [(agent.EXIT_TIMEOUT, "", None)], places=[("Zones/Work", "Work", 1)])
        raw = self.ws.joinpath(*work_in.HELD_FILE).read_text()
        self.assertNotIn("questions", raw)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{12}", k) for k in self.stops()))
        self.assertIn("long", fq.ANSWERS_HELD)

    def test_a_question_that_runs_to_its_end_after_a_stop_starts_its_count_again(self):
        self.timed([100], [(agent.EXIT_TIMEOUT, "", None)], places=[("Zones/Work", "Work", 1)])
        self.timed([10], [(0, DONE, "Wikis/Meetings/wiki/a1.md")], places=[("Zones/Work", "Work", 1)])
        self.assertEqual({}, self.stops())

    def test_the_card_shows_the_held_question_in_plain_words(self):
        self.assertIn("longer than a night", fq.ANSWERS_HELD["long"])
        write(self.ws.joinpath(*fq.HELD_FILE), json.dumps({"held": {"Zones/Work": {"why": "long", "day": "2026-11-13"}}}))
        out = fq.held_answers(self.ws, {"Zones/Work": "Work"}, {"Zones/Work": 1}, set())
        (q,) = out["Zones/Work"]
        self.assertEqual("answers-held", q["id"])
        self.assertIn("could not be worked in", q["sentence"])
        self.assertIn("longer than a night", q["why"])
        self.assertNotRegex(q["why"] + q["sentence"], r"questions/|\.md|exit|124")


class TestOnlyTheListedPathsAreCommitted(TestOneCallForEachAnswer):
    """W6: the commit holds the paths `question-work` listed for that answer. Any other path the wiki holds changed is left as it is,
    and the summary line says how many, by place, never a page's title."""

    def run_listed(self, listed, runs):
        with mock.patch.object(work_in, "listed_paths", return_value=listed):
            return self.timed([10], runs, places=[("Zones/Work", "Work", 1)])

    def test_the_listed_page_is_committed_and_another_changed_path_is_left_and_counted(self):
        listed = {"Meetings/wiki/a1.md"}          # another writer's file appears while the call runs
        code, calls, said = self.run_listed(listed, [(0, DONE, ["Wikis/Meetings/wiki/a1.md", "Wikis/Meetings/wiki/other.md"])])
        self.assertEqual(0, code)
        self.assertEqual(["Meetings/wiki/a1.md"], git(self.ws / "Wikis", "show", "--name-only", "--format=", "HEAD").split())
        self.assertEqual("?? Meetings/wiki/other.md", git(self.ws / "Wikis", "status", "--porcelain").strip())      # left exactly as it was
        self.assertTrue((self.ws / "Wikis" / "Meetings" / "wiki" / "other.md").exists())
        self.assertIn("1 other changed path in the wiki left as it is", said)
        self.assertNotIn("other.md", said)                                                                         # by count and place, never a title

    def test_a_page_the_call_wrote_that_is_not_listed_is_not_committed_either(self):
        code, calls, said = self.run_listed({"Meetings/wiki/a1.md"}, [(0, DONE, "Wikis/Meetings/wiki/a9.md")])
        self.assertEqual([], [l for l in self.log() if l.startswith("Answers worked in")])
        self.assertIn("1 other changed path in the wiki left as it is", said)

    def test_with_no_list_nothing_is_kept(self):
        code, calls, said = self.run_listed(None, [(0, DONE, "Wikis/Meetings/wiki/a1.md")])
        self.assertFalse((self.ws / "Wikis" / "Meetings" / "wiki" / "a1.md").exists())
        self.assertEqual("", git(self.ws / "Wikis", "status", "--porcelain").strip())
        self.assertEqual({"Zones/Work": {"why": "incomplete", "day": "2026-11-13"}}, self.held())

    def test_the_real_list_is_the_pages_the_question_names_its_own_file_and_its_raw_answer(self):
        pa = work_in.page_action()
        self.assertIsNotNone(pa)
        self.assertTrue(callable(pa.question_pages) and callable(pa.own_record))
        self.assertIsNone(REAL_LISTED(self.ws, "Meetings", "questions/missing.md", self.ws / "Wikis"))      # unreadable: no list


class TestTheRealList(PanelCase):
    """W6: the list the step holds a commit to, from the page's own reading of the question."""

    def test_it_is_the_pages_the_question_names_its_own_file_and_its_raw_answer_from_the_top_of_the_repository(self):
        q = "questions/261001 - acme.md"
        write(self.meetings / q, question(ACME, status="answered", pages="[[wiki/sources/260310-acme-kickoff]]",
                                          extra='answer: "[[raw/answers/261005 - acme]]"\n'))
        write(self.meetings / "raw" / "answers" / "261005 - acme.md",
              "---\ntype: answer\nanswered: 2026-10-05\nzone: Work\nparties: [acme]\nquestion: \"[[questions/261001 - acme]]\"\n---\n\nQuestion: x\n\n```\n500\n```\n")
        commit_all(self.meetings, "a question")
        self.assertEqual({"wiki/sources/260310-acme-kickoff.md", q, "raw/answers/261005 - acme.md"},
                         REAL_LISTED(self.root, "Meetings", q, self.meetings))
        self.assertIsNone(REAL_LISTED(self.root, "Meetings", "questions/261001 - nothing.md", self.meetings))


if __name__ == "__main__":
    unittest.main()
