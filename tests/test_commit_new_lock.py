"""N5 and the cleanup reset of `commit_new()`: a lock met while making a project or a thread leaves no folder behind and no file
staged, and the sentence ends on one full stop.

    cd tests && python3 -m unittest test_commit_new_lock
"""

from __future__ import annotations

import os
import sys
import unittest

sys.dont_write_bytecode = True

from test_scaffold_manage import ManageCase, pa  # noqa: E402

LOCK = "Not saved: another program was using this zone's history. Try again in a moment."
FILE_EXISTS = "fatal: Unable to create '.git/index.lock': File exists."


class Case(ManageCase):
    def setUp(self):
        super().setUp()
        os.environ["GARRICK_JOBS_DIR"] = str(self.base / "jobs")
        self._numbers = (pa.LOCK_TRIES, pa.LOCK_PAUSE)
        pa.LOCK_TRIES, pa.LOCK_PAUSE = 2, 0.02
        self.addCleanup(lambda: setattr(pa, "LOCK_TRIES", self._numbers[0]) or setattr(pa, "LOCK_PAUSE", self._numbers[1]))
        self.lock = self.work / ".git" / "index.lock"
        self.addCleanup(lambda: self.lock.unlink() if self.lock.exists() else None)

    def untracked_and_staged(self):
        return self.git("status", "--porcelain", "--untracked-files=all").stdout


class TestALockWhileMaking(Case):
    def test_a_project_made_under_a_held_lock_leaves_no_folder_and_one_full_stop(self):
        before = self.git("rev-parse", "HEAD").stdout
        self.lock.write_text("")
        with self.assertRaises(pa.Refused) as caught:
            pa.act(self.root, dict(verb="new-project", zone="Work", name="Birch", party="birch", thread="Pricing"))
        self.lock.unlink()
        say = str(caught.exception)
        self.assertTrue(say.startswith(LOCK), say)
        self.assertNotIn("..", say)
        self.assertTrue(say.endswith("."))
        self.assertFalse((self.work / "Birch").exists())
        self.assertEqual("", self.untracked_and_staged())
        self.assertEqual(before, self.git("rev-parse", "HEAD").stdout)

    def test_a_thread_made_under_a_held_lock_leaves_no_folder_and_the_hub_as_it_was(self):
        hub = self.work / "Acme" / "Acme.md"
        was = hub.read_bytes()
        self.lock.write_text("")
        with self.assertRaises(pa.Refused) as caught:
            pa.act(self.root, dict(verb="new-thread", zone="Work", project="Acme", name="Renewal"))
        self.lock.unlink()
        self.assertTrue(str(caught.exception).startswith(LOCK), str(caught.exception))
        self.assertNotIn("..", str(caught.exception))
        self.assertFalse((self.work / "Acme" / "Threads" / "Renewal").exists())
        self.assertEqual(was, hub.read_bytes())
        self.assertEqual("", self.untracked_and_staged())


class TestTheCleanupReset(Case):
    def test_a_lock_that_goes_after_the_commit_failed_leaves_no_file_staged(self):
        real = pa.git_once
        state = {"reset": 0}

        def flaky(zone, *args, **k):
            if args and args[0] == "commit":
                return 128, FILE_EXISTS
            if args and args[0] == "reset" and state["reset"] < 4:
                state["reset"] += 1
                return 128, FILE_EXISTS
            return real(zone, *args, **k)
        pa.git_once = flaky
        try:
            with self.assertRaises(pa.Refused) as caught:
                pa.act(self.root, dict(verb="new-project", zone="Work", name="Birch", party="birch"))
        finally:
            pa.git_once = real
        self.assertTrue(str(caught.exception).startswith(LOCK), str(caught.exception))
        self.assertEqual(4, state["reset"])
        self.assertEqual("", self.git("diff", "--cached", "--name-only").stdout)
        self.assertEqual("", self.untracked_and_staged())


if __name__ == "__main__":
    unittest.main()
