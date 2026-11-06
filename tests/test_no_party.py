"""No label, no permit: a project whose hub names no party commits nothing (#398).

    cd tests && python3 -m unittest test_no_party

Orchard is a project of the Work zone whose hub names no party. The hook refuses
a commit of any file in it and names the hub as the fix; a zone's own files and
its Inbox belong to no project, and are not refused for it.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, commit_all, git, project_hub, thread_note, write  # noqa: E402
from walls_fixture import build  # noqa: E402

import check  # noqa: E402


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class NoPartyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build(self.root)
        self.work = self.root / "Zones" / "Work"
        shutil.rmtree(self.work / ".git", ignore_errors=True)
        git(self.work, "init", "-q")
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        commit_all(self.work, "start")

    def staged(self):
        git(self.work, "add", "-A")
        return check.run_checks(self.root, staged=self.work)

    def test_a_file_of_a_project_with_no_party_is_refused_and_the_hub_is_named(self):
        write(self.work / "Orchard" / "Threads" / "Drafts" / "Notes.md", "# Notes\n\nPlain words.\n")
        found = [f for f in self.staged() if f.path.endswith("Orchard/Threads/Drafts/Notes.md")]
        self.assertTrue(found, "nothing was said about a file of a project with no party")
        self.assertEqual({"error"}, {f.severity for f in found})
        self.assertIn("Orchard/Orchard.md", found[0].message)
        self.assertIn("`party:`", found[0].message)

    def test_a_file_that_links_nothing_and_names_nobody_is_refused_all_the_same(self):
        write(self.work / "Orchard" / "Deliverables" / "260301 - memo.md", "# Memo\n")
        self.assertTrue([f for f in self.staged() if f.severity == "error" and "Orchard" in f.path])

    def test_a_zone_file_and_an_inbox_file_belong_to_no_project(self):
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] call Jo\n\n## Done\n")
        write(self.work / "AGENTS.local.md", "# Work\n")
        self.assertEqual([], [f for f in self.staged() if f.severity == "error"])

    def test_once_the_hub_names_a_party_the_project_commits(self):
        write(self.work / "Orchard" / "Orchard.md", project_hub("Work", "Orchard", "acme", ["Drafts"]))
        write(self.work / "Orchard" / "Threads" / "Drafts" / "Drafts.md", thread_note("Orchard", "Drafts", "acme"))
        write(self.work / "Orchard" / "Threads" / "Drafts" / "Notes.md", "# Notes\n\nPlain words.\n")
        self.assertEqual([], [f for f in self.staged() if f.severity == "error"])

    def test_a_project_with_no_party_is_not_read_as_public(self):
        write(self.work / "Orchard" / "Threads" / "Drafts" / "Notes.md", "# Notes\n\nSee [[260312-birch-kickoff]].\n")
        found = [f for f in self.staged() if f.path.endswith("Orchard/Threads/Drafts/Notes.md")]
        self.assertTrue(any("no party" in f.message for f in found), [f.message for f in found])

    def test_the_full_check_lists_each_hub_with_no_party(self):
        found = [f for f in check.run_checks(self.root) if f.check == "projects" and "no `party`" in f.message]
        self.assertEqual(["Zones/Work/Orchard/Orchard.md"], [f.path for f in found])
        self.assertEqual(["error"], [f.severity for f in found])


if __name__ == "__main__":
    unittest.main()
