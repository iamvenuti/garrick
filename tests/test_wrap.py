"""One Wrap, and Back from the record (#367): the wrap's lock and what the threads skill says.

    python3 -m unittest discover -s tests -p test_wrap.py

The background run and the band are checked by hand; this is the part a test
reaches: the lock a running wrap holds (taken once, gone after ten minutes),
and the skill's words (no question first, no stack, Hold as no command).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "template" / "System" / "tools" / "wrap_lock.py"
SKILL = REPO / "template" / "System" / "skills" / "threads" / "SKILL.md"
REFERENCE = SKILL.parent / "reference"
_spec = importlib.util.spec_from_file_location("garrick_wrap_lock", str(TOOL))
wl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wl)

NOTE = "Zones/Work/Acme/Threads/Pricing/Pricing.md"


class LockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def lock(self, note=NOTE):
        return wl.lock_path(self.root, note)

    def test_the_lock_is_a_file_in_generated_named_for_the_note(self):
        self.assertTrue(wl.start(self.root, NOTE))
        path = self.lock()
        self.assertEqual(path.parent, self.root / "System" / "generated")
        self.assertEqual(path.name, "wrap-Zones__Work__Acme__Threads__Pricing__Pricing.md.lock")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["note"], NOTE)
        self.assertRegex(data["started"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_a_wrap_cannot_be_started_twice(self):
        self.assertTrue(wl.start(self.root, NOTE))
        self.assertFalse(wl.start(self.root, NOTE))
        self.assertTrue(wl.running(self.lock()))

    def test_another_thread_has_its_own_lock(self):
        self.assertTrue(wl.start(self.root, NOTE))
        self.assertTrue(wl.start(self.root, "Zones/Work/Acme/Threads/Terms/Terms.md"))

    def test_end_records_when_the_wrap_finished_beside_the_lock(self):
        wl.start(self.root, NOTE)
        self.assertIsNone(wl.finished(wl.done_path(self.root, NOTE)))
        wl.end(self.root, NOTE, now=1_700_000_000.25)
        done = wl.done_path(self.root, NOTE)
        self.assertEqual(done.parent, self.lock().parent)
        self.assertEqual(done.name, "wrap-Zones__Work__Acme__Threads__Pricing__Pricing.md.done")
        self.assertAlmostEqual(wl.finished(done), 1_700_000_000.25, places=2)
        self.assertEqual(json.loads(done.read_text())["note"], NOTE)
        self.assertFalse(self.lock().exists())

    def test_end_abandon_records_nothing(self):
        wl.start(self.root, NOTE)
        wl.end(self.root, NOTE, abandon=True)
        self.assertFalse(self.lock().exists())
        self.assertFalse(wl.done_path(self.root, NOTE).exists())

    def test_a_record_that_does_not_read_is_no_record(self):
        done = wl.done_path(self.root, NOTE)
        done.parent.mkdir(parents=True)
        for bad in ("", "not json", "{}", '{"finished": "soon"}'):
            done.write_text(bad)
            self.assertIsNone(wl.finished(done))

    def test_end_removes_it_and_a_second_wrap_may_start(self):
        wl.start(self.root, NOTE)
        wl.end(self.root, NOTE)
        self.assertFalse(self.lock().exists())
        wl.end(self.root, NOTE)                     # none there: still fine
        self.assertTrue(wl.start(self.root, NOTE))

    def test_a_lock_older_than_ten_minutes_counts_as_gone(self):
        now = time.time()
        wl.start(self.root, NOTE, now=now - 601)
        self.assertFalse(wl.running(self.lock(), now=now))
        self.assertTrue(wl.start(self.root, NOTE, now=now))     # replaces the dead one
        self.assertTrue(wl.running(self.lock(), now=now + 599))
        self.assertFalse(wl.running(self.lock(), now=now + 600))

    def test_a_lock_that_does_not_read_expires_by_its_files_time(self):
        path = self.lock()
        path.parent.mkdir(parents=True)
        path.write_text("not json", encoding="utf-8")
        self.assertTrue(wl.running(path))
        old = time.time() - 700
        os.utime(path, (old, old))
        self.assertFalse(wl.running(path))

    def test_a_lock_dated_far_ahead_counts_as_gone_as_in_the_band(self):
        now = time.time()
        wl.start(self.root, NOTE, now=now + 3600)
        self.assertFalse(wl.running(self.lock(), now=now))
        self.assertTrue(wl.start(self.root, NOTE, now=now))

    def test_at_most_one_of_many_starters_wins_over_a_dead_lock(self):
        import threading
        now = time.time()
        wl.start(self.root, NOTE, now=now - 700)
        wins, barrier = [], threading.Barrier(8)

        def go():
            barrier.wait()
            wins.append(wl.start(self.root, NOTE))
        threads = [threading.Thread(target=go) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(1, wins.count(True), wins)
        self.assertTrue(wl.running(self.lock()))

    def test_only_a_thread_note_under_zones(self):
        for bad in ("System/rules.md", "Zones/../x.md", "Zones/Work/Acme", ""):
            with self.assertRaises(ValueError):
                wl.lock_path(self.root, bad)

    def test_the_command_line(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(wl.main(["start", NOTE, "--root", str(self.root)]), 0)
        self.assertEqual(out.getvalue().strip(), "locked")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(wl.main(["start", NOTE, "--root", str(self.root)]), 1)
        self.assertIn("already running", err.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(wl.main(["status", NOTE, "--root", str(self.root)]), 0)
            self.assertEqual(wl.main(["end", NOTE, "--root", str(self.root)]), 0)
            self.assertEqual(wl.main(["status", NOTE, "--root", str(self.root)]), 0)
        self.assertEqual(out.getvalue().split(), ["running", "unlocked", "idle"])


class SkillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dispatcher = SKILL.read_text(encoding="utf-8")
        cls.head = cls.dispatcher.split("---", 2)[1]
        wrap_ref = (REFERENCE / "wrap.md").read_text(encoding="utf-8")
        cls.wrap = wrap_ref[wrap_ref.index("## Wrap:"):wrap_ref.index("## Close for the day")]
        cls.back = (REFERENCE / "catch-up.md").read_text(encoding="utf-8").split("## Back:", 1)[1]
        cls.text = "\n".join(f.read_text(encoding="utf-8") for f in [SKILL] + sorted(REFERENCE.glob("*.md")))

    def test_the_trigger_phrases_still_work(self):
        for phrase in ("I'm being interrupted", "hold this", "hold X", "back", "where was I", "back to X",
                       "wrap it", "wrap X", "close for the day"):
            self.assertIn('"%s"' % phrase, self.head, phrase)

    def test_hold_runs_the_wrap_and_is_no_command_of_its_own(self):
        self.assertIn('## Wrap: "close X", "wrap X", "I\'m being interrupted", "hold this", "hold X"', self.text)
        self.assertNotRegex(self.text, r"(?m)^## (Interrupted|Hold)")
        self.assertNotIn("Hold,", self.head)
        self.assertNotIn(" hold,", self.head)

    def test_no_stack_and_no_interrupted_file(self):
        for gone in ("interrupted.json", "interruption stack", "unstack", "the stack", "page_action.py --workspace . --via session <<'EOF'\n{\"verb\": \"interrupt\""):
            self.assertNotIn(gone, self.text, gone)
        self.assertNotRegex(self.text, r'"verb": "(interrupt|back|stack)"')

    def test_the_wrap_asks_nothing_before_it_takes_the_lock(self):
        wrap = self.wrap
        self.assertIn("**Ask nothing.**", wrap)
        self.assertLess(wrap.index("**Ask nothing.**"), wrap.index("wrap_lock.py start"))
        self.assertNotIn("Anything only in your head", wrap)
        self.assertNotIn("Ask the one question", wrap)
        self.assertNotIn("the answer to the question", wrap)
        self.assertIn("what the user said with the request", " ".join(wrap.split()))
        self.assertIn("Keep in mind", wrap)
        self.assertIn("or `nothing`", wrap)

    def test_what_the_user_says_with_the_request_goes_into_keep_in_mind(self):
        wrap = " ".join(self.wrap.split())
        self.assertIn("goes into *Keep in mind* as said", wrap)
        self.assertIn("I was leaning towards the lower tier", wrap)

    def test_the_background_brief_carries_the_walls(self):
        wrap = self.wrap
        brief = " ".join(wrap[wrap.index("Brief the subagent"):wrap.index("The last act of the wrap")].split())
        for needed in ("the project's zone and whether it is walled", "Walled column of the Zones table in `System/context.md`", 'named only as "held back"',
                       "wall check (*The wall check*, step 4 above) before it writes anything",
                       "write nothing it cannot place", "The foreground run needs none of this"):
            self.assertIn(needed, brief)

    def test_the_wrap_takes_and_releases_the_lock(self):
        wrap = self.wrap
        self.assertIn("wrap_lock.py start", wrap)
        self.assertIn("wrap_lock.py end", wrap)
        self.assertIn("ten minutes", wrap)

    def test_back_goes_by_the_notes_modification_time(self):
        back = self.back
        self.assertIn("written most recently", back)
        self.assertIn("never the answer", back)
        self.assertIn("stat -f %m", back)
        self.assertIn("After two wraps it is the later one", back)


BAND = REPO / "extras" / "mods" / "garrick-band" / "hooks" / "register.tsx"


def band_slot(done, turn):
    """The band's choice between Wrap and Resume for a live thread, as `bandSlot` in
    register.tsx makes it from the two times (the decision lines are checked below)."""
    if turn is None:
        return "resume"
    if done is None:
        return "wrap"
    return "resume" if done >= turn else "wrap"


class FailedWrapTest(unittest.TestCase):
    """A wrap that failed or was refused releases the lock and records no success (#wrap-marker):
    releasing the lock and declaring the wrap finished are two things."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.done = wl.done_path(self.root, NOTE)

    def test_a_failed_wrap_cleans_up_and_leaves_no_record_so_the_band_still_offers_wrap(self):
        self.assertTrue(wl.start(self.root, NOTE))
        wl.end(self.root, NOTE, abandon=True)                       # step 13 after a refused commit
        self.assertFalse(wl.lock_path(self.root, NOTE).exists())    # cleanup ran
        self.assertFalse(self.done.exists())                        # and recorded nothing
        self.assertIsNone(wl.finished(self.done))
        self.assertEqual("wrap", band_slot(wl.finished(self.done), 2000.0))

    def test_the_earlier_record_stands_and_is_older_than_the_failed_attempt(self):
        self.assertTrue(wl.start(self.root, NOTE, now=1000.0))
        wl.end(self.root, NOTE, now=1000.0)                         # a wrap that landed
        earlier = wl.finished(self.done)
        self.assertEqual(1000.0, earlier)
        self.assertTrue(wl.start(self.root, NOTE, now=5000.0))
        wl.end(self.root, NOTE, now=5000.0, abandon=True)           # a later wrap whose commit was refused
        self.assertEqual(earlier, wl.finished(self.done))           # still the first one's time, not the attempt's
        self.assertFalse(wl.lock_path(self.root, NOTE).exists())
        self.assertEqual("wrap", band_slot(wl.finished(self.done), 4000.0))   # work since: Wrap, not Resume

    def test_a_wrap_that_landed_is_recorded_and_the_band_offers_resume(self):
        self.assertTrue(wl.start(self.root, NOTE, now=1000.0))
        wl.end(self.root, NOTE, now=3000.0)                         # step 13 after a successful commit
        self.assertFalse(wl.lock_path(self.root, NOTE).exists())
        self.assertEqual(3000.0, wl.finished(self.done))
        self.assertEqual("resume", band_slot(wl.finished(self.done), 2000.0))

    def test_a_wrap_with_nothing_new_to_commit_counts_as_finished(self):
        """The note was already current: step 13 calls `end`, as in 0.64.0, so the band shows Resume."""
        self.assertTrue(wl.start(self.root, NOTE, now=1000.0))
        wl.end(self.root, NOTE, now=3000.0)
        self.assertEqual(3000.0, wl.finished(self.done))
        self.assertEqual("resume", band_slot(wl.finished(self.done), 2000.0))
        wrap = " ".join((REFERENCE / "wrap.md").read_text(encoding="utf-8").split())
        self.assertIn("there was nothing to commit because the note was already current", wrap)
        self.assertIn("once the commit has succeeded or there was nothing to commit", BAND.read_text(encoding="utf-8"))

    def test_the_command_line_abandon_writes_no_record(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(0, wl.main(["start", NOTE, "--root", str(self.root)]))
            self.assertEqual(0, wl.main(["end", "--abandon", NOTE, "--root", str(self.root)]))
        self.assertEqual(["locked", "unlocked"], out.getvalue().split())
        self.assertFalse(self.done.exists())

    def test_the_band_decides_as_the_replica_says(self):
        text = BAND.read_text(encoding="utf-8")
        for line in ("if (s.turnMs === null) return 'resume'", "if (s.doneMs === null) return 'wrap'",
                     "return s.doneMs >= s.turnMs ? 'resume' : 'wrap'"):
            self.assertIn(line, text, line)

    def test_the_skill_records_the_finish_only_after_the_commit_and_abandons_on_failure(self):
        wrap = " ".join((REFERENCE / "wrap.md").read_text(encoding="utf-8").split())
        step = wrap[wrap.index("13. **Release the lock**"):wrap.index("Spoken, when the wrap runs in the background")]
        self.assertIn("**The commit succeeded, or there was nothing to commit because the note was already current:** `end` removes the lock and writes the time the wrap finished", step)
        self.assertIn("**Anything else:** the commit was refused or failed, the save failed", step)
        self.assertIn("`end --abandon` removes the lock and writes no record, and leaves an earlier record as it was", step)
        self.assertIn("python3 System/tools/wrap_lock.py end --abandon", step)
        self.assertIn("Never use `end` to clean up after a failure", step)
        self.assertIn("the record is written only after step 12's commit has succeeded", wrap)
        self.assertNotIn("**Remove the lock**, whatever happened above", wrap)
        self.assertLess(wrap.index("12. **Commit in the zone's repository.**"), wrap.index("13. **Release the lock**"))

    def test_the_bands_own_prompts_release_the_lock_the_same_way(self):
        text = BAND.read_text(encoding="utf-8")
        self.assertNotIn("and remove it as the last step", text)
        self.assertIn("wrap_lock.py end --abandon ${n.rel}", text)             # the lock the band took
        self.assertIn("end --abandon\\` when the wrap failed or the commit was refused", text)   # the lock the wrap takes


class WordsTest(unittest.TestCase):
    """One vocabulary (#367): Wrap and Resume, and no stack, in the pages and the band's README."""

    PAGES = ("README.md", "docs/commands.md", "docs/concepts.md", "docs/principles.md", "docs/architecture.md",
             "docs/extras/status-page.md", "docs/extras/cmux.md", "extras/mods/README.md", "extras/cmux/desk/SKILL.md",
             "presentation/index.html", "docs/architecture/overview.html")

    def test_no_page_mentions_a_stack_or_the_file_it_kept(self):
        for page in self.PAGES:
            text = (REPO / page).read_text(encoding="utf-8").lower()
            for gone in ("interruption stack", "interrupted.json", "stack of held", "unstack", "off the stack"):
                self.assertNotIn(gone, text, "%s: %s" % (page, gone))

    def test_no_page_offers_hold_as_a_command_of_its_own(self):
        for page in self.PAGES:
            text = (REPO / page).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?i)\bhold this\b[^.]{0,40}(when|if) (someone|something) (interrupts|cuts)", page)
            self.assertNotIn("**\"Hold", text, page)
            self.assertNotIn("thirty-second", text, page)

    def test_nothing_still_names_an_interrupt_or_an_interruption_as_a_verb(self):
        for page in ("docs/concepts.md", "docs/extras/status-page.md"):
            text = (REPO / page).read_text(encoding="utf-8")
            self.assertNotIn("or an interrupt confirms", text, page)
            self.assertNotIn("*Wake*, an interruption", text, page)
        self.assertIn("modification time", (REPO / "docs" / "concepts.md").read_text(encoding="utf-8"))

    def test_the_band_readme_names_wrap_and_resume_in_one_slot(self):
        text = (REPO / "extras" / "mods" / "README.md").read_text(encoding="utf-8")
        self.assertIn("*Wrap* (`w`) and *Resume* (`r`) share one slot", text)
        self.assertIn("older than ten minutes counts as gone", text)

    def test_the_commands_page_says_no_question_and_the_record(self):
        text = (REPO / "docs" / "commands.md").read_text(encoding="utf-8")
        self.assertIn("A wrap asks nothing", text)
        self.assertIn("the thread whose note was written most recently and is not finished or parked", text)

    def test_no_shipped_page_or_skill_says_the_wrap_asks_a_question(self):
        skill = "template/System/skills/threads/"
        for page in self.PAGES + (skill + "SKILL.md",) + tuple(skill + "reference/" + f.name for f in sorted(REFERENCE.glob("*.md"))):
            text = (REPO / page).read_text(encoding="utf-8")
            self.assertNotIn("Anything only in your head?", text, page)
            self.assertNotRegex(text, r"(?i)\bwrap\b[^.]{0,40}\basks one line", page)


class BackTest(unittest.TestCase):
    """The shell the skill gives for "back", run against a workspace: the
    thread whose note was written most recently and is not finished or parked."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        back = (REFERENCE / "catch-up.md").read_text(encoding="utf-8").split("## Back:", 1)[1]
        self.script = re.search(r"```sh\n\s*(find Zones.*?)```", back, re.S).group(1)

    def note(self, thread, status="active", at=0, project="Acme"):
        path = self.root / "Zones" / "Work" / project / "Threads" / thread / (thread + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nstatus: %s\n---\n# %s\n" % (status, thread), encoding="utf-8")
        os.utime(path, (1_800_000_000 + at, 1_800_000_000 + at))

    def back(self):
        done = subprocess.run(["sh", "-c", self.script], cwd=str(self.root), capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)
        return [line.split("\t", 1)[1].split("/")[4] for line in done.stdout.splitlines()]

    def test_after_two_wraps_it_is_the_later_one(self):
        self.note("Pricing", at=10)
        self.note("Freight", at=20)
        self.assertEqual(["Freight", "Pricing"], self.back())
        self.note("Pricing", at=30)                       # wrapped again
        self.assertEqual("Pricing", self.back()[0])

    def test_a_finished_or_parked_thread_is_never_the_answer(self):
        self.note("Pricing", at=10)
        self.note("Freight", status="done", at=50)
        self.note("Rebate", status="parked", at=60)
        self.assertEqual(["Pricing"], self.back())

    def test_nothing_to_resume_prints_nothing(self):
        self.note("Freight", status="done", at=50)
        self.assertEqual([], self.back())

    def test_a_folder_that_starts_with_an_underscore_is_not_work(self):
        self.note("Pricing", at=10)
        self.note("_Scratch", at=90)
        self.assertEqual(["Pricing"], self.back())


if __name__ == "__main__":
    unittest.main()
