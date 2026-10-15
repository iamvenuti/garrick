"""The clean-room scan runs in a linked worktree, and never skips in one.

`.cleanroom` is gitignored, so it sits in the primary working tree and nowhere
else. The scan used to look for it beside its own root, found nothing in a
worktree, and skipped; a skip is not a failure, so the suite reported OK with
the one check that protects the clean-room rule switched off.

Proving the code path exists is not enough here, because what went wrong was a
whole suite run reporting success. So each test below builds a repository of its
own, puts a list in its primary tree, adds a linked worktree, copies
`tests/test_cleanroom.py` into it and runs `unittest discover` there, then reads
the run's own report: the scan has to find a planted name, and no run may be
reported as skipped.

Invented party only: Quill & Harrow, which is nobody. The repositories are built
here from nothing and read nothing of the machine they run on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import fixtures  # noqa: F401  (sets sys.dont_write_bytecode)
from fixtures import GIT_ENV, HAVE_GIT, commit_all, git, git_init, write

ROOT = Path(__file__).resolve().parent.parent
INVENTED = "Quill & Harrow"

# The suite's own environment may carry a list of names; these runs must be
# answered by the file alone.
ENV = dict(GIT_ENV, PYTHONDONTWRITEBYTECODE="1")
ENV.pop("GARRICK_CLEANROOM_NAMES", None)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class CleanRoomInAWorktreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="garrick-cleanroom-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), ignore_errors=True)
        self.primary = self.tmp / "primary"
        self.primary.mkdir()
        git_init(self.primary)
        # Mirrors this repository: the list is ignored, so it is never committed
        # and so a worktree's checkout cannot carry it.
        write(self.primary / ".gitignore", ".cleanroom\n__pycache__/\n")
        (self.primary / "tests").mkdir()
        shutil.copy2(str(ROOT / "tests" / "test_cleanroom.py"),
                     str(self.primary / "tests" / "test_cleanroom.py"))
        write(self.primary / "prose.md", "A page that names nobody.\n")
        commit_all(self.primary, "the repository under test")

    def worktree(self) -> Path:
        """A linked worktree of the repository, detached so no branch is named."""
        where = self.tmp / "linked"
        git(self.primary, "worktree", "add", "-q", "--detach", str(where), "HEAD")
        return where

    def report(self, tree: Path):
        """(everything the suite run said, its exit status), run in `tree`."""
        res = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover",
                              "-s", "tests", "-v"],
                             cwd=str(tree), env=ENV, capture_output=True, text=True)
        return res.stdout + res.stderr, res.returncode

    def test_the_scan_runs_in_a_worktree_and_catches_a_planted_name(self):
        write(self.primary / ".cleanroom", INVENTED + "\n")
        linked = self.worktree()
        write(linked / "prose.md", "A page that names %s, which may never be here.\n" % INVENTED)
        out, code = self.report(linked)
        self.assertEqual(1, code, out)
        self.assertIn("name 1 of the list", out)
        self.assertIn("prose.md", out)
        self.assertNotIn(INVENTED, out)  # the position in the list, never the name
        self.assertNotIn("skipped", out)

    def test_a_clean_worktree_passes_the_scan_rather_than_skipping_it(self):
        write(self.primary / ".cleanroom", INVENTED + "\n")
        linked = self.worktree()
        out, code = self.report(linked)
        self.assertEqual(0, code, out)
        self.assertIn("Ran 1 test", out)
        self.assertNotIn("skipped", out)  # the whole point: the check was not switched off

    def test_a_repository_with_no_list_anywhere_still_skips(self):
        linked = self.worktree()
        out, code = self.report(linked)
        self.assertEqual(0, code, out)
        self.assertIn("skipped", out)  # a fresh clone has no names to check against

    def test_a_list_that_cannot_be_decoded_fails_in_either_tree(self):
        (self.primary / ".cleanroom").write_bytes(b"\xff\xfe not text at all\n")
        for tree, said in ((self.worktree(), "the primary working tree"),
                           (self.primary, "this working tree")):
            out, code = self.report(tree)
            self.assertEqual(1, code, out)
            self.assertIn("could not be read", out)
            self.assertIn(said, out)
            self.assertNotIn("skipped", out)
            # The primary tree sees one list, not the same one twice.
            self.assertEqual(1, out.count("working tree)"), out)

    def test_a_list_the_user_cannot_read_fails_rather_than_skipping(self):
        listing = write(self.primary / ".cleanroom", INVENTED + "\n")
        os.chmod(str(listing), 0o000)
        self.addCleanup(os.chmod, str(listing), 0o600)
        try:
            listing.read_text(encoding="utf-8")
        except OSError:
            pass
        else:
            self.skipTest("this user can read a file with no permissions")
        out, code = self.report(self.worktree())
        self.assertEqual(1, code, out)
        self.assertIn("could not be read", out)
        self.assertIn("the primary working tree", out)
        self.assertNotIn("skipped", out)


if __name__ == "__main__":
    unittest.main()
