"""N3: a lock met inside scaffold.py or wrap.py answers with the lock sentence, and no path.

    cd tests && python3 -m unittest test_lock_in_tools

git's own line names the workspace's `.git/index.lock`. A remote caller must never read it.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest

sys.dont_write_bytecode = True

import test_wrap_tool as twt  # noqa: E402
from test_scaffold_manage import ManageCase, pa  # noqa: E402

LOCK = "Not saved: another program was using this zone's history. Try again in a moment."


class TestScaffold(ManageCase):
    def setUp(self):
        super().setUp()
        r = self.scaffold("project", "--zone", "Work", "--name", "Apex", "--party", "acme", "--thread", "Kickoff")
        self.assertEqual(0, r.returncode, r.stderr)
        self.commit("Apex")
        self.lock = self.work / ".git" / "index.lock"
        self.lock.write_text("")
        self.addCleanup(lambda: self.lock.unlink() if self.lock.exists() else None)

    def said_the_lock_alone(self, r):
        self.assertEqual(1, r.returncode, r.stdout)
        self.assertEqual(LOCK, r.stderr.strip())
        self.assertNotIn(str(self.root), r.stderr)
        self.assertNotIn("index.lock", r.stderr)

    def test_a_rename_that_meets_the_lock_says_the_lock_and_no_path(self):
        self.said_the_lock_alone(self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Rates"))
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing").is_dir())

    def test_a_move_that_meets_the_lock_says_the_lock_and_no_path(self):
        self.said_the_lock_alone(self.scaffold("move", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--to", "Apex"))
        self.assertTrue((self.work / "Acme" / "Threads" / "Freight").is_dir())

    def test_the_sentence_is_one_sentence_in_three_files(self):
        spec = importlib.util.spec_from_file_location("scaffold_lock", str(self.root / "System" / "tools" / "scaffold.py"))
        sc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sc)
        self.assertEqual(LOCK, sc.lock_sentence())
        self.assertEqual(LOCK, sc.LOCK_FALLBACK)
        self.assertEqual(LOCK, pa.LOCK_REFUSAL)


class TestWrap(twt.Base):
    def lock_at_commit(self):
        (self.work / ".git" / "index.lock").write_text("")

    def test_a_wrap_that_meets_the_lock_says_the_lock_and_no_path(self):
        before = self.thread.read_text(encoding="utf-8")
        try:
            got = self.run_wrap(before_commit=self.lock_at_commit)
        finally:
            (self.work / ".git" / "index.lock").unlink()
        self.assertEqual("failed", got["outcome"], got)
        self.assertEqual("Failed: " + LOCK.rstrip(".") + ".", got["say"])
        self.assertNotIn(str(self.root), got["say"])
        self.assertNotIn("index.lock", got["say"])
        self.assertEqual(before, self.thread.read_text(encoding="utf-8"))
        self.assertTrue(self.clean())


if __name__ == "__main__":
    unittest.main()
