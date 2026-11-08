"""Flipping a party's flag, naming a second walled party, the same-name refusal, taking a party off a note, and
`party:` read as a list (#445). Invented names only.

    cd tests && python3 -m unittest test_party_flags
"""

from __future__ import annotations

import contextlib
import io
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
import recall  # noqa: E402
import scaffold  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build(self.root)
        self.work = self.root / "Zones" / "Work"
        (self.root / "System" / "tools").mkdir(parents=True, exist_ok=True)
        shutil.copy(Path(scaffold.__file__).with_name("check.py"), self.root / "System" / "tools" / "check.py")
        shutil.copytree(Path(scaffold.__file__).parent.parent / "templates", self.root / "System" / "templates")
        for name in ("garrick_lib.py",):
            shutil.copy(Path(scaffold.__file__).with_name(name), self.root / "System" / "tools" / name)

    def run_scaffold(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = scaffold.main(["--root", str(self.root), "--today", "2027-01-01", *argv])
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    def context(self):
        return (self.root / "System" / "context.md").read_text(encoding="utf-8")


class FlipTest(Base):
    def test_walled_to_open_names_the_files_it_releases_and_writes_only_on_yes(self):
        code, said, _ = self.run_scaffold("party", "--tag", "acme", "--open")
        self.assertEqual(0, code)
        self.assertRegex(said, r"releases \d+ files?")
        self.assertIn("| `acme` | yes |", self.context())
        code, said, _ = self.run_scaffold("party", "--tag", "acme", "--open", "--yes")
        self.assertIn("| `acme` | no |", self.context())
        self.assertIn("released", said)

    def test_open_to_walled_writes_and_lists_the_files_now_in_violation(self):
        write(self.work / "Reed" / "Threads" / "Notes" / "Deal.md", "# Deal\n\nSee [[260310-acme-kickoff]].\n")
        self.run_scaffold("party", "--tag", "acme", "--open", "--yes")
        code, said, _ = self.run_scaffold("party", "--tag", "acme", "--walled")
        self.assertEqual(0, code)
        self.assertIn("| `acme` | yes |", self.context())
        self.assertIn("Zones/Work/Reed/Threads/Notes/Deal.md", said)
        self.assertIn("refused until each is fixed or its project names the party", said)

    def test_the_two_hats_cannot_be_opened(self):
        code, _, err = self.run_scaffold("party", "--tag", "lumen", "--open", "--yes")
        self.assertEqual(1, code)
        self.assertIn("both hats stay walled", err)


class LabelTest(Base):
    def test_a_second_walled_party_says_the_materials_will_meet_and_writes_on_yes(self):
        code, _, err = self.run_scaffold("label", "--zone", "Work", "--project", "Northwind", "--add", "birch")
        self.assertEqual(1, code)
        self.assertIn("Acme Corp's and Birch & Co's material will meet in this project", err)
        self.assertNotIn("birch", (self.work / "Northwind" / "Northwind.md").read_text())
        code, said, _ = self.run_scaffold("label", "--zone", "Work", "--project", "Northwind", "--add", "birch", "--yes")
        self.assertEqual(0, code)
        self.assertEqual(["acme", "birch"], lib.tag_list(lib.parse_frontmatter(self.work / "Northwind" / "Northwind.md")["party"]))

    def test_two_hats_on_one_note_are_refused(self):
        self.run_scaffold("label", "--zone", "Work", "--project", "Northwind", "--add", "lumen", "--yes")
        code, _, err = self.run_scaffold("label", "--zone", "Work", "--project", "Northwind", "--add", "lumen-adv", "--yes")
        self.assertEqual(1, code)
        self.assertIn("one company under two hats", err)

    def test_the_check_refuses_a_hub_that_names_both_hats(self):
        hub = self.work / "Northwind" / "Northwind.md"
        hub.write_text(hub.read_text().replace("party: acme", "party: [lumen, lumen-adv]"), encoding="utf-8")
        found = [f for f in check.run_checks(self.root) if f.check == "projects" and "two hats" in f.message]
        self.assertEqual(1, len(found))

    def test_taking_a_party_off_names_the_files_and_writes_only_on_yes(self):
        self.run_scaffold("label", "--zone", "Work", "--project", "Both", "--remove", "birch")
        self.assertIn("birch", (self.work / "Both" / "Both.md").read_text())
        code, said, err = self.run_scaffold("label", "--zone", "Work", "--project", "Both", "--remove", "birch")
        self.assertIn("file", said)
        code, said, _ = self.run_scaffold("label", "--zone", "Work", "--project", "Both", "--remove", "birch", "--yes")
        self.assertEqual(["acme"], lib.tag_list(lib.parse_frontmatter(self.work / "Both" / "Both.md")["party"]))
        log = (self.root / "System" / "generated" / "label-changes.jsonl").read_text()
        self.assertIn("Zones/Work/Both/Both.md", log)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_check_refuses_a_dropped_party_that_scaffold_did_not_confirm(self):
        shutil.rmtree(self.work / ".git", ignore_errors=True)
        git(self.work, "init", "-q")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
            commit_all(self.work, "start")
            hub = self.work / "Both" / "Both.md"
            hub.write_text(hub.read_text().replace("[acme, birch]", "acme"), encoding="utf-8")
            git(self.work, "add", "-A")
            found = [f for f in check.run_checks(self.root, staged=self.work) if f.severity == "error"]
            self.assertTrue([f for f in found if "without the confirmation" in f.message], found)
            git(self.work, "reset", "-q", "--hard", "HEAD")
            self.run_scaffold("label", "--zone", "Work", "--project", "Both", "--remove", "birch", "--yes")
            git(self.work, "add", "-A")
            found = [f for f in check.run_checks(self.root, staged=self.work) if "without the confirmation" in f.message]
            self.assertEqual([], found)


class ListReadersTest(Base):
    def test_a_project_is_found_by_any_party_of_its_list(self):
        self.assertIn("Both", scaffold.projects_of(self.root, "birch", "Work"))
        self.assertIn("Both", scaffold.projects_of(self.root, "acme", "Work"))

    def test_check_party_takes_a_list_and_refuses_two_hats(self):
        self.assertEqual("[acme, birch]", scaffold.check_party(self.root, "acme,birch", "Work"))
        with self.assertRaises(scaffold.Refusal):
            scaffold.check_party(self.root, "lumen, lumen-adv", "Work")

    def test_a_changed_flag_makes_recall_build_its_index_again(self):
        ctx = lib.load_context(self.root)
        scope = recall.scopes_of(self.root, ctx)[1]
        before = recall.policy_stamp(ctx, scope)
        self.run_scaffold("party", "--tag", "acme", "--open", "--yes")
        ctx = lib.load_context(self.root)
        self.assertNotEqual(before, recall.policy_stamp(ctx, recall.scopes_of(self.root, ctx)[1]))


if __name__ == "__main__":
    unittest.main()
