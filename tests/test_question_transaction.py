"""The one transaction behind every write that changes pages (#224, point 6):
the files are written, the checks are counted before and after, and a count
made worse puts every file back, a file the write made removed. Where the
action commits it commits once per repository.

    python3 -m unittest test_question_transaction
"""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import git, write  # noqa: E402
from test_page_action import TODAY, pa  # noqa: E402
from test_wiki_answers import WikiAnswerCase, question, snapshot  # noqa: E402


class TestTransaction(WikiAnswerCase):
    def test_a_count_made_worse_leaves_every_file_as_it_was(self):
        self.ask()
        before = snapshot(self.root)
        with mock.patch.object(pa, "check_counts", side_effect=[{"check:error": 0}, {"check:error": 1}]):
            with self.assertRaisesRegex(pa.Refused, r"a check got worse \(errors 0 to 1\).*back as it was"):
                self.do("question-answer", words="It is 500 pallets.")
        self.assertEqual(before, snapshot(self.root))
        self.assertFalse((self.meetings / "raw" / "answers").exists())     # the folder the write made goes too

    def test_a_lint_count_made_worse_does_the_same(self):
        self.ask()
        before = snapshot(self.root)
        with mock.patch.object(pa, "check_counts", side_effect=[{"lint:Meetings:orphans": 1}, {"lint:Meetings:orphans": 2}]):
            with self.assertRaisesRegex(pa.Refused, "Meetings orphans 1 to 2"):
                self.do("question-close")
        self.assertEqual(before, snapshot(self.root))

    def test_an_equal_or_better_count_keeps_the_write(self):
        self.ask()
        with mock.patch.object(pa, "check_counts", side_effect=[{"check:error": 2}, {"check:error": 1}]):
            self.do("question-close")
        self.assertIn("status: closed", (self.meetings / self.q).read_text())

    def test_a_check_that_cannot_run_writes_nothing(self):
        self.ask()
        before = snapshot(self.root)
        for counts in ([None], [{"check:error": 0}, None]):
            with mock.patch.object(pa, "check_counts", side_effect=counts):
                with self.assertRaisesRegex(pa.Refused, "cannot run|could not run"):
                    self.do("question-answer", words="500")
            self.assertEqual(before, snapshot(self.root))

    def test_a_fault_in_the_write_puts_the_files_back(self):
        self.ask()
        before = snapshot(self.root)
        with mock.patch.object(pa, "write_question", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.do("question-close")
        self.assertEqual(before, snapshot(self.root))

    def test_the_wiki_question_actions_commit_nothing(self):
        self.ask()
        git(self.meetings, "init", "-q")
        git(self.meetings, "add", "-A")
        git(self.meetings, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-qm", "start")
        self.do("question-answer", words="500")
        self.assertEqual("start", git(self.meetings, "log", "-1", "--format=%s").strip())
        self.assertNotEqual("", git(self.meetings, "status", "--porcelain").strip())

    def test_the_check_runs_for_work_in_too(self):
        self.ask()
        self.do("question-answer", words="500")
        before = snapshot(self.root)
        with mock.patch.object(pa, "check_counts", side_effect=[{"check:error": 0}, {"check:error": 3}]):
            with self.assertRaisesRegex(pa.Refused, "got worse"):
                self.do("question-done")
        self.assertEqual(before, snapshot(self.root))


class TestWrites(unittest.TestCase):
    def test_restore_is_byte_for_byte_and_removes_what_was_made(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            keep = root / "keep.md"
            keep.write_bytes(b"caf\xc3\xa9\r\nline\n")
            w = pa.Writes()
            w.write(keep, "changed\n")
            w.write(root / "deep" / "new" / "file.md", "new\n")
            w.restore()
            self.assertEqual(b"caf\xc3\xa9\r\nline\n", keep.read_bytes())
            self.assertFalse((root / "deep").exists())

    def test_a_folder_that_was_there_stays(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "there").mkdir()
            w = pa.Writes()
            w.write(root / "there" / "a.md", "x")
            w.restore()
            self.assertTrue((root / "there").is_dir())
            self.assertFalse((root / "there" / "a.md").exists())


if __name__ == "__main__":
    unittest.main()
