"""One Wrap, and Back from the record (#367): the wrap's lock and what the threads skill says.

    python3 -m unittest discover -s tests -p test_wrap.py

The background run and the band are checked by hand; this is the part a test
reaches: the lock a running wrap holds (taken once, gone after ten minutes),
and the skill's words (one question first, no stack, Hold as no command).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "template" / "System" / "tools" / "wrap_lock.py"
SKILL = REPO / "template" / "System" / "skills" / "threads" / "SKILL.md"
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
        cls.text = SKILL.read_text(encoding="utf-8")
        cls.head = cls.text.split("---", 2)[1]

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

    def test_the_one_question_comes_first_and_skips_on_enter(self):
        wrap = self.text[self.text.index("## Wrap:"):self.text.index("## Back:")]
        self.assertIn('"Anything only in your head?"', wrap)
        self.assertLess(wrap.index("Ask the one question"), wrap.index("background subagent"))
        self.assertIn("Enter", wrap)
        self.assertIn("Keep in mind", wrap)
        self.assertRegex(wrap, r"foreground")

    def test_the_wrap_takes_and_releases_the_lock(self):
        wrap = self.text[self.text.index("## Wrap:"):self.text.index("## Back:")]
        self.assertIn("wrap_lock.py start", wrap)
        self.assertIn("wrap_lock.py end", wrap)
        self.assertIn("ten minutes", wrap)

    def test_back_goes_by_the_notes_modification_time(self):
        back = self.text[self.text.index("## Back:"):self.text.index("## Close for the day")]
        self.assertIn("written most recently", back)
        self.assertIn("never the answer", back)
        self.assertIn("stat -f %m", back)
        self.assertIn("After two wraps it is the later one", back)


if __name__ == "__main__":
    unittest.main()
