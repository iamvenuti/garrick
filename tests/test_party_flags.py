"""A wall is a flag on a zone (#484): `scaffold.py zone --walled | --open`, a project with or without a party,
and the party flip gone. Invented names only.

    cd tests && python3 -m unittest test_party_flags
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, git, write  # noqa: E402
from walls_fixture import build  # noqa: E402

import garrick_lib as lib  # noqa: E402
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


ZONES_WALLED = ("## Zones\n\n| Zone | Holds | Walled |\n|---|---|---|\n| Work | Client work | yes |\n"
                "| Personal | Everything else | yes |\n")


class ZoneBase(Base):
    """A workspace whose Zones table has the Walled column, and a stand-in for the check that names one file."""

    def setUp(self):
        super().setUp()
        import re
        text = self.context()
        text = re.sub(r"## Zones\n.*?(?=\n## )", ZONES_WALLED, text, count=1, flags=re.S)
        (self.root / "System" / "context.md").write_text(text, encoding="utf-8")
        self.stub(["Zones/Work/Reed/Threads/Notes/Deal.md"])

    def stub(self, paths):
        findings = [{"path": p, "severity": "error", "check": "walls", "message": "links a file of zone Personal"} for p in paths]
        (self.root / "System" / "tools" / "check.py").write_text(
            "import json\nprint(json.dumps({'findings': %r}))\n" % findings, encoding="utf-8")


class FlagTest(ZoneBase):
    def test_walled_to_open_names_the_files_it_releases_and_writes_only_on_yes(self):
        code, said, _ = self.run_scaffold("zone", "--name", "Work", "--open")
        self.assertEqual(0, code)
        self.assertRegex(said, r"releases \d+ files?")
        self.assertIn("| Work | Client work | yes |", self.context())
        code, said, _ = self.run_scaffold("zone", "--name", "Work", "--open", "--yes")
        self.assertIn("| Work | Client work | no |", self.context())
        self.assertIn("released", said)
        self.assertFalse(lib.walled(lib.load_context(self.root), "Work"))

    def test_the_count_is_the_zones_own_files_and_its_meetings_pages(self):
        _, said, _ = self.run_scaffold("zone", "--name", "Work", "--open")
        n = int(said.split("releases ")[1].split(" ")[0])
        self.assertGreaterEqual(n, 3)                       # the project notes and the Work meetings pages
        _, other, _ = self.run_scaffold("zone", "--name", "Personal", "--open")
        self.assertLess(int(other.split("releases ")[1].split(" ")[0]), n)

    def test_open_to_walled_writes_and_lists_the_files_now_in_violation(self):
        self.run_scaffold("zone", "--name", "Work", "--open", "--yes")
        code, said, _ = self.run_scaffold("zone", "--name", "Work", "--walled")
        self.assertEqual(0, code)
        self.assertIn("| Work | Client work | yes |", self.context())
        self.assertIn("Zones/Work/Reed/Threads/Notes/Deal.md", said)
        self.assertIn("1 file now in violation", said)

    def test_walling_a_zone_says_when_the_check_could_not_run(self):
        self.run_scaffold("zone", "--name", "Work", "--open", "--yes")
        (self.root / "System" / "tools" / "check.py").unlink()
        code, _, err = self.run_scaffold("zone", "--name", "Work", "--walled")
        self.assertEqual(1, code)
        self.assertIn("could not run", err)
        self.assertIn("| Work | Client work | yes |", self.context())      # the flag is written, and the user told to run the check

    def test_a_flag_already_set_changes_nothing(self):
        before = self.context()
        code, said, _ = self.run_scaffold("zone", "--name", "Work", "--walled")
        self.assertEqual((0, True), (code, "already walled" in said))
        self.assertEqual(before, self.context())

    def test_an_unknown_zone_is_refused(self):
        code, _, err = self.run_scaffold("zone", "--name", "Nowhere", "--walled")
        self.assertEqual(1, code)
        self.assertIn("not a zone yet", err)

    def test_the_party_flag_machinery_is_gone(self):
        for argv in (("party", "--tag", "acme", "--open"), ("party", "--name", "Fern Co", "--walled"), ("label", "--zone", "Work")):
            self.assertEqual(2, self.run_scaffold(*argv)[0], argv)      # argparse: not an option, not a verb
        for gone in ("party_flag", "cmd_flip", "cmd_label", "refuse_hats", "meet_sentence", "files_labelled", "set_flag", "wall_between"):
            self.assertFalse(hasattr(scaffold, gone), gone)
        text = Path(scaffold.__file__).read_text(encoding="utf-8")
        for gone in ("walled-from",):
            self.assertNotIn(gone, text, gone)


class PendingTest(Base):
    """The 0.62 context, before the update to zone walls is accepted: a flag is refused and nothing is written."""

    def test_a_flag_is_refused_and_writes_nothing_while_the_zones_table_has_no_walled_column(self):
        before = self.context()
        for flag in ("--walled", "--open"):
            code, _, err = self.run_scaffold("zone", "--name", "Work", flag, "--yes")
            self.assertEqual(1, code)
            self.assertIn("no Walled column", err)
        self.assertEqual(before, self.context())


class NewZoneTest(Base):
    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_a_new_zone_is_walled_unless_it_is_made_open(self):
        write(self.root / "System" / "templates" / "zone" / ".gitignore", "Inbox/\n")
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Sam")
        git(self.root, "config", "user.email", "sam@example.com")
        code, said, err = self.run_scaffold("zone", "Garden", "--holds", "The garden")
        self.assertEqual(0, code, err)
        self.assertIn("walled", said)
        code, said, err = self.run_scaffold("zone", "Meadow", "--holds", "The meadow", "--open")
        self.assertEqual(0, code, err)
        self.assertIn("open", said)
        ctx = self.context()
        self.assertRegex(ctx, r"\| Garden \| The garden \|[^\n]*walled \|")          # the 0.62 shape: the new-parties default
        self.assertRegex(ctx, r"\| Meadow \| The meadow \|[^\n]*open \|")


class OptionalPartyTest(Base):
    def test_a_project_without_a_party_has_no_party_line_and_its_thread_inherits_none(self):
        code, said, err = self.run_scaffold("project", "--zone", "Work", "--name", "Fern", "--thread", "Plan")
        self.assertEqual(0, code, err)
        hub = self.work / "Fern" / "Fern.md"
        note = self.work / "Fern" / "Threads" / "Plan" / "Plan.md"
        for f in (hub, note):
            self.assertNotIn("party:", f.read_text())
            self.assertNotIn("{{", f.read_text())
        code, _, err = self.run_scaffold("thread", "--zone", "Work", "--project", "Fern", "--name", "Budget")
        self.assertEqual(0, code, err)
        self.assertNotIn("party:", (self.work / "Fern" / "Threads" / "Budget" / "Budget.md").read_text())

    def test_a_project_may_still_name_a_party_as_an_index(self):
        code, _, err = self.run_scaffold("project", "--zone", "Work", "--name", "Moss", "--party", "acme", "--thread", "Plan")
        self.assertEqual(0, code, err)
        self.assertIn("party: acme", (self.work / "Moss" / "Moss.md").read_text())

    def test_two_parties_of_one_zone_need_no_confirmation(self):
        code, _, err = self.run_scaffold("project", "--zone", "Work", "--name", "Twin", "--party", "acme,birch", "--thread", "Plan")
        self.assertEqual(0, code, err)
        self.assertEqual(["acme", "birch"], lib.tag_list(lib.parse_frontmatter(self.work / "Twin" / "Twin.md")["party"]))

    def test_an_unknown_tag_and_a_party_of_another_zone_are_refused(self):
        code, _, err = self.run_scaffold("project", "--zone", "Work", "--name", "Ghost", "--party", "zzz", "--thread", "Plan")
        self.assertEqual((1, True), (code, "not a party tag" in err))
        code, _, err = self.run_scaffold("project", "--zone", "Work", "--name", "Ghost", "--party", "jo", "--thread", "Plan")
        self.assertEqual((1, True), (code, "party of Personal" in err))


class PartyTest(Base):
    def test_a_new_party_takes_a_zone_and_what_and_is_not_flagged(self):
        code, said, err = self.run_scaffold("party", "--name", "Fern Co", "--zone", "Work", "--what", "Supplier")
        self.assertEqual(0, code, err)
        self.assertNotIn("walled: only", said)
        self.assertIn("| Fern Co | Supplier | Work | `fern` |", self.context())

    def test_the_same_name_is_the_same_party_and_never_a_refusal_of_two(self):
        code, said, _ = self.run_scaffold("party", "--name", "Acme Corp", "--zone", "Work")
        self.assertEqual((0, True), (code, "already a party" in said))
        code, said, _ = self.run_scaffold("party", "--name", "Lumen Group", "--zone", "Work")
        self.assertEqual(0, code)                         # two hats are two rows; asking again is no error

    def test_a_second_hat_is_added_with_also_and_needs_no_wall_sentence(self):
        code, said, err = self.run_scaffold("party", "--name", "Acme Corp", "--zone", "Personal", "--also")
        self.assertEqual(0, code, err)
        self.assertNotIn("stay walled", said)


class ListReadersTest(Base):
    def test_a_project_is_found_by_any_party_of_its_list(self):
        self.assertIn("Both", scaffold.projects_of(self.root, "birch", "Work"))
        self.assertIn("Both", scaffold.projects_of(self.root, "acme", "Work"))

    def test_check_party_takes_a_list_and_two_hats_of_one_zone_are_only_an_index(self):
        self.assertEqual("[acme, birch]", scaffold.check_party(self.root, "acme,birch", "Work"))
        self.assertEqual("[lumen, lumen-adv]", scaffold.check_party(self.root, "lumen, lumen-adv", "Work"))
        self.assertEqual("", scaffold.check_party(self.root, "", "Work"))


if __name__ == "__main__":
    unittest.main()
