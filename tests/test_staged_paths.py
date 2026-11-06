"""A staged path finds its project however the folder is spelt, and a text file the walls cannot read is refused (#398).

    cd tests && python3 -m unittest test_staged_paths
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

from fixtures import HAVE_GIT, commit_all, git, write  # noqa: E402
from walls_fixture import build  # noqa: E402

import check  # noqa: E402
import garrick_lib as lib  # noqa: E402


class ProjectSpellings(unittest.TestCase):
    def ws(self, folder):
        ws = check.Workspace.__new__(check.Workspace)
        ws.projects = [(Path(folder), {"party": "acme"})]
        ws.project_norm = None
        return ws

    def test_nfd_and_nfc_are_one_project(self):
        nfd = "/w/Zones/Work/Café Run"
        ws = self.ws(nfd)
        staged = Path("/w/Zones/Work/Café Run/Threads/T/x.md")
        self.assertEqual(Path(nfd), check.project_of(ws, staged)[0])
        self.assertEqual(Path(nfd + "/Threads/T/x.md"), check.canonical_path(ws, staged))

    def test_a_case_only_rename_is_the_same_project(self):
        ws = self.ws("/w/Zones/Work/northwind")
        staged = Path("/w/Zones/Work/Northwind/Notes.md")
        self.assertIsNotNone(check.project_of(ws, staged))
        self.assertEqual(Path("/w/Zones/Work/northwind/Notes.md"), check.canonical_path(ws, staged))

    def test_a_path_in_no_project_is_in_none(self):
        self.assertIsNone(check.project_of(self.ws("/w/Zones/Work/Northwind"), Path("/w/Zones/Work/Todo.md")))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class StagedFiles(unittest.TestCase):
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

    def errors(self, suffix):
        return [f for f in check.run_checks(self.root, staged=self.work) if f.severity == "error" and f.path.endswith(suffix)]

    def stage(self, rel, data):
        path = self.work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        git(self.work, "add", "-A")

    def test_a_text_file_with_nul_bytes_is_refused(self):
        self.stage("Northwind/Threads/Pricing/utf16.md", "Ask Theo Marsh".encode("utf-16"))
        found = self.errors("utf16.md")
        self.assertEqual(1, len(found), found)
        self.assertIn("cannot read", found[0].message)

    def test_a_text_file_over_the_cap_is_refused(self):
        self.stage("Northwind/Threads/Pricing/big.txt", b"a " * (check.MAX_SCAN_BYTES // 2 + 10))
        self.assertEqual(1, len(self.errors("big.txt")))

    def test_a_binary_file_of_a_labelled_project_keeps_the_old_rule(self):
        self.stage("Northwind/Threads/Pricing/pic.png", b"\x89PNG\x00\x01\x02")
        self.assertEqual([], self.errors("pic.png"))

    def test_a_binary_file_of_a_project_with_no_party_is_refused(self):
        self.stage("Orchard/Threads/Drafts/pic.png", b"\x89PNG\x00\x01\x02")
        self.assertEqual(1, len(self.errors("pic.png")))

    def test_a_case_renamed_project_folder_is_still_checked(self):
        os.rename(self.work / "Harbour", self.work / "Harbour-tmp")
        os.rename(self.work / "Harbour-tmp", self.work / "harbour")
        write(self.work / "harbour" / "Threads" / "Sizing" / "Leak.md", "# n\n\nAsk Dana Whitlock of Acme Corp.\n")
        git(self.work, "add", "-A")
        found = [f for f in check.run_checks(self.root, staged=self.work) if f.severity == "error"]
        self.assertTrue(any(f.path.lower().endswith("leak.md") for f in found), found)

    def test_labels_find_a_folder_in_another_spelling(self):
        ctx = lib.load_context(self.root)
        self.assertEqual({"acme"}, lib.labels(self.root, "Zones/Work/northwind/Threads/Pricing/x.md", ctx))
        self.assertEqual({"birch"}, lib.labels(self.root, "Zones/work/HARBOUR/Sources/x.md", ctx))


if __name__ == "__main__":
    unittest.main()
