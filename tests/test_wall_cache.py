"""The commit check's cache: after the first commit, the staged wall check
reads what is committed and what changed since, not every note in the
workspace, and finds what it found before.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations
import sys
sys.dont_write_bytecode = True  # keep the repo free of __pycache__

import io
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fixtures import HAVE_GIT, build_workspace, commit_all, git, install_wall_hook, meeting_page, write  # noqa: E402

import check  # noqa: E402

# Invented wording, one run per meeting, long enough to count as a quotation.
QUOTE = "the northern depot contract renews at eleven percent unless volumes fall below forecast"
LATER = "the harbour warehouse lease moves to quarterly billing once the crane upgrade finishes"
ALIAS = "the board approved the confidential freight schedule for every southern terminal"
OLD = time.time() - 3600


def _age(root: Path) -> None:
    """Every file an hour old, as files are when nobody touched them since the last commit."""
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            os.utime(os.path.join(folder, name), (OLD, OLD))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestWallCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = build_workspace(Path(self._tmp.name).resolve() / "ws")
        self.work = self.root / "Zones" / "Work"
        self.acme = self.work / "Acme Review"
        self.birch = self.work / "Birch Entry"
        self.meetings = self.root / "Wikis" / "Meetings"
        # A workspace of some size on the far side of the wall: Birch's notes and meetings.
        for i in range(20):
            write(self.birch / "Threads" / "Market Sizing" / ("Note %d.md" % i),
                  "Sizing pass %d: freight lanes, depot counts and the regional demand curve for quarter %d.\n" % (i, i))
            page = meeting_page("Work", "[birch]", "Birch call %d" % i)
            write(self.meetings / "wiki" / "sources" / ("2603%02d-birch-call-%d.md" % (i + 1, i)),
                  page.replace("Decisions.", QUOTE + "." if i == 7 else "Decisions taken on call %d." % i))
            write(self.meetings / "raw" / ("2603%02d-birch-call-%d.txt" % (i + 1, i)), "Transcript of call %d.\n" % i)
        shutil.rmtree(self.work / ".git")
        git(self.work, "init", "-q")
        install_wall_hook(self.work)
        commit_all(self.work, "start")
        _age(self.root)
        self.cache = Path(git(self.work, "rev-parse", "--absolute-git-dir").strip()) / check.NoteCache.NAME
        self.note = self.acme / "Threads" / "Pricing" / "Notes.md"

    def tearDown(self):
        self._tmp.cleanup()

    def stage(self, text: str) -> None:
        write(self.note, text)
        git(self.work, "add", "-A")

    def staged(self):
        """The commit check's findings, and every file it opened to find them."""
        opened = []
        real = io.open

        def recording(file, *args, **kwargs):
            opened.append(Path(os.fspath(file)) if isinstance(file, (str, os.PathLike)) else None)
            return real(file, *args, **kwargs)

        with mock.patch("io.open", recording), mock.patch("builtins.open", recording):
            found = check.run_checks(self.root, staged=self.work)
        return [f.message for f in found], {p for p in opened if p is not None}

    def corpus(self) -> set:
        """What the wording check compares a commit with, other than the commit itself."""
        out = set()
        for top in (self.meetings, self.root / "Wikis" / "Knowledge", self.birch):
            out |= {p for p in top.rglob("*") if p.is_file() and ".git" not in p.parts}
        return out

    def test_a_warm_commit_reads_the_commit_not_the_workspace(self):
        self.stage("Pricing notes, first pass at the September figures for the regional desks.\n")
        _, cold = self.staged()
        self.assertTrue(cold & self.corpus(), "the first commit reads the workspace, and keeps what it read")
        self.assertTrue(self.cache.is_file())
        self.stage("Pricing notes. Overheard: " + QUOTE + ".\n")
        found, warm = self.staged()
        self.assertEqual(1, len(found), found)
        self.assertIn("repeats wording from meeting 260308-birch-call-7", found[0])
        self.assertEqual(set(), warm & self.corpus())

    def test_a_file_changed_since_is_read_again(self):
        self.stage("Pricing notes, first pass at the September figures for the regional desks.\n")
        self.staged()
        page = self.meetings / "wiki" / "sources" / "260303-birch-call-2.md"
        write(page, page.read_text().replace("Decisions taken on call 2.", LATER + "."))
        os.utime(page, (OLD + 60, OLD + 60))           # a new stamp, but long enough ago to be kept
        self.stage("Pricing notes. Overheard: " + LATER + ".\n")
        found, opened = self.staged()
        self.assertEqual(1, len(found), found)
        self.assertIn("260303-birch-call-2", found[0])
        self.assertEqual({page}, opened & self.corpus())

    def test_a_new_shared_page_changes_what_a_cached_note_says(self):
        page = self.meetings / "wiki" / "sources" / "260304-birch-call-3.md"
        write(page, page.read_text().replace("Decisions taken on call 3.", "See [[Freight Schedule|%s]]." % ALIAS))
        os.utime(page, (OLD, OLD))
        self.stage("Pricing notes. " + ALIAS + ".\n")
        found, _ = self.staged()
        self.assertEqual(1, len(found), found)                 # the link's words are the meeting's own
        # Published now: the link's words become the title of a page every side reads.
        write(self.root / "Wikis" / "Knowledge" / "wiki" / "sources" / "Freight Schedule.md", "# A published schedule\n")
        found, opened = self.staged()
        self.assertEqual([], found)
        self.assertIn(page, opened)

    def test_the_same_findings_with_or_without_a_cache(self):
        self.stage("Pricing notes. Theo Marsh said: " + QUOTE + ".\n")
        cold, _ = self.staged()
        warm, _ = self.staged()
        self.cache.write_bytes(b"not a cache")
        broken, _ = self.staged()
        self.cache.unlink()
        none, _ = self.staged()
        self.assertEqual(2, len(cold), cold)                  # the name and the quote
        self.assertEqual([cold] * 3, [warm, broken, none])

    def test_a_recent_file_is_never_kept(self):
        """Changed in the last seconds, a file could change again with the same stamp: it is read every time."""
        page = self.meetings / "wiki" / "sources" / "260302-birch-call-1.md"
        write(page, page.read_text())
        self.stage("Pricing notes, first pass at the September figures for the regional desks.\n")
        self.staged()
        _, opened = self.staged()
        self.assertEqual({page}, opened & self.corpus())


if __name__ == "__main__":
    unittest.main()
