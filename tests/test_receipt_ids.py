"""S6: the App's own receipts hold the whole commit id, and undo takes a whole id (a short one only from an older receipt).

    cd tests && python3 -m unittest test_receipt_ids
"""

from __future__ import annotations

import os
import re
import sys
import unittest

sys.dont_write_bytecode = True

from test_scaffold_manage import ManageCase, pa  # noqa: E402


class Case(ManageCase):
    def setUp(self):
        super().setUp()
        os.environ["GARRICK_JOBS_DIR"] = str(self.base / "jobs")
        r = self.scaffold("project", "--zone", "Work", "--name", "Apex", "--party", "acme", "--thread", "Kickoff")
        self.assertEqual(0, r.returncode, r.stderr)
        self.commit("Apex")

    def head(self):
        return self.git("rev-parse", "HEAD").stdout.strip()


class TestReceipts(Case):
    def test_the_page_receipt_of_a_rename_and_of_a_move_holds_the_whole_id(self):
        out, _, _ = pa.perform(self.root, dict(verb="rename", zone="Work", project="Acme", thread="Pricing", to="Rates"),
                               pa.ops_lib(self.root), via="page")
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.head(), out["commit"])
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", out["commit"]))
        out, _, _ = pa.perform(self.root, dict(verb="move", zone="Work", project="Acme", thread="Freight", to="Apex"),
                               pa.ops_lib(self.root), via="page")
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.head(), out["commit"])

    def test_undo_by_the_whole_id_of_a_rename_receipt(self):
        out, _, _ = pa.perform(self.root, dict(verb="rename", zone="Work", project="Acme", thread="Pricing", to="Rates"),
                               pa.ops_lib(self.root), via="page")
        undone, _, _ = pa.perform(self.root, dict(verb="undo", zone="Work", commit=out["commit"]), pa.ops_lib(self.root), via="page")
        self.assertTrue(undone["ok"], undone)
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing").is_dir())


class TestUndoTakesIds(Case):
    def rename(self):
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Rates")
        self.assertEqual(0, r.returncode, r.stderr)

    def test_a_name_that_is_not_an_id_is_refused_even_when_it_names_the_last_commit(self):
        self.rename()
        for name in ("HEAD", "main", "HEAD^{commit}", "abc12", "ABCDEF1234"):
            r = self.scaffold("undo", "--zone", "Work", "--commit", name)
            self.assertEqual(1, r.returncode, name)
            self.assertIn("is not a commit id", r.stderr)
        self.assertTrue((self.work / "Acme" / "Threads" / "Rates").is_dir())

    def test_a_short_id_of_seven_or_more_from_an_older_receipt_still_works(self):
        self.rename()
        short = self.git("rev-parse", "--short=7", "HEAD").stdout.strip()
        r = self.scaffold("undo", "--zone", "Work", "--commit", short)
        self.assertEqual(0, r.returncode, r.stderr)

    def test_a_prefix_that_names_no_commit_is_refused(self):
        self.rename()
        wrong = ("0" if self.head()[0] != "0" else "1") + self.head()[1:7]
        r = self.scaffold("undo", "--zone", "Work", "--commit", wrong)
        self.assertEqual(1, r.returncode)
        self.assertTrue((self.work / "Acme" / "Threads" / "Rates").is_dir())


if __name__ == "__main__":
    unittest.main()
