"""What counts toward a run of words in the wording check (#498): the template's own structure does not.

A heading, a bold label that a template under System/templates/ holds, a line identical to a template line, and
the date that opens a dated entry carry no weight when the eight words are counted. The words either side of
them still add up, so a log of short dated entries copied across two walled zones is refused as before.

    cd tests && python3 -m unittest test_wall_runs

Invented parties only: Acme Corp (`acme`, zone Work) and Own affairs (`jo`, zone Home), walled from each other.
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
from zone_fixture import build  # noqa: E402

import check  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FRONT = "---\ntitle: %s\ntype: thread\nproject: \"[[%s]]\"\nparty: %s\nstatus: active\ncreated: 2026-11-09\nupdated: 2026-11-10\n---\n\n"
TABLE = ("| | |\n|---|---|\n| Live artifact | %s |\n| Rebuild with | Nothing to rebuild |\n| Next action | %s |\n"
         "| Keep in mind | Nothing |\n| Waiting on | Nobody |\n| Deadline | None |\n")
SHARED = "the Nordic depot volumes are split before the regional board handover"


def thread(title, project, party, artifact, action, newer, first="Thread opened today."):
    """A thread note as the thread template lays it out: its headings, a Resume here block with the template's
    label, the rule, two dated entries. `newer` is the text of the newer entry, `first` the older one's."""
    return (FRONT % (title, project, party) + "# %s\n\n## The ask\n\nWhat each side wants.\n\n## State of play\n\n"
            "### Resume here\n\n**Where it stands, 10 November 2026.** The work is under way.\n\n" % title
            + TABLE % (artifact, action) + "\n---\n\n**10 November 2026.** %s\n\n**9 November 2026.** %s\n" % (newer, first))


class Runs(unittest.TestCase):
    """check.runs() on its own, with the shipped templates' structure."""

    def setUp(self):
        self.structure = check.TemplateStructure.read(REPO / "template" / "System" / "templates")

    def runs(self, text):
        return check.runs(text, None, self.structure)

    def test_the_templates_own_headings_and_label_make_no_run(self):
        text = "## State of play\n\n### Resume here\n\n**Where it stands, 10 November 2026.**\n"
        self.assertEqual(set(), self.runs(text))

    def test_a_template_label_with_a_real_date_is_the_template_label(self):
        for date in ("1 January 2026", "10 November 2026", "31 December 2031"):
            with self.subTest(date=date):
                text = "**Where it stands, %s.** One two three four five six seven." % date
                self.assertEqual(self.runs("One two three four five six seven."), self.runs(text))

    def test_a_bold_date_placeholder_never_matches_a_bold_opener(self):
        # The template's own entry opener is a placeholder: no real note holds that text, and a bold opener
        # that only looks like a placeholder, or like a date, is read as the words it is.
        for opener in ("**<D Month YYYY>.**", "**{{DATE}}.**", "**<date>.**", "**Decision.**", "**Sizing basis agreed.**"):
            with self.subTest(opener=opener):
                text = "%s Seven eight nine ten eleven twelve thirteen fourteen." % opener
                self.assertTrue(self.runs(text))

    def test_a_date_that_opens_an_entry_has_no_weight_and_the_run_goes_on(self):
        a = "Both sides agreed the scope\n\n**10 November 2026.** and froze the budget until spring."
        b = "Both sides agreed the scope and froze the budget until spring."
        self.assertEqual(self.runs(b), self.runs(a))

    def test_eight_material_words_in_one_paragraph_are_a_run(self):
        self.assertTrue(self.runs("The memo notes %s today." % SHARED))
        self.assertEqual(self.runs("The memo notes %s today." % SHARED),
                         self.runs("**10 November 2026.** The memo notes %s today." % SHARED))

    def test_without_the_templates_the_words_count_as_before(self):
        plain = check.runs("**Where it stands, 10 November 2026.** One two three four five six seven eight nine ten.", None,
                           check.TemplateStructure.empty())
        self.assertTrue(plain)

    def test_a_log_of_short_dated_entries_still_runs_across_the_lines(self):
        log = "".join("**%d November 2026.** %s\n\n" % (day, line) for day, line in
                      ((3, "Sizing memo agreed"), (4, "with both distributors"), (5, "before the regional"), (6, "pilot starts in March")))
        flat = "Sizing memo agreed with both distributors before the regional pilot starts in March"
        self.assertTrue(self.runs(log))
        self.assertEqual(self.runs(flat), self.runs(log))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TwoThreadNotes(unittest.TestCase):
    """The issue's four cases, on a fixture workspace with the shipped templates installed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build(self.root)
        shutil.copytree(REPO / "template" / "System" / "templates", self.root / "System" / "templates", dirs_exist_ok=True)
        self.work = self.root / "Zones" / "Work"
        self.home = self.root / "Zones" / "Home"
        self.a = self.work / "Northwind" / "Threads" / "Pricing" / "Pricing.md"
        self.b = self.home / "Garden" / "Threads" / "Beds" / "Beds.md"
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)

    def both(self, a_newer="The pricing memo went to Dana, scope frozen.", b_newer="The bed plan went to Jo, scope frozen.",
             first="Thread opened today."):
        write(self.a, thread("Pricing", "Northwind", "acme", "`Deliverables/260310 - Memo.md`", "Rowan to send the memo", a_newer, first))
        write(self.b, thread("Beds", "Garden", "jo", "`Deliverables/260310 - Plan.md`", "Jo to mark the beds", b_newer, first))

    def refused(self):
        found = check.run_checks(self.root, walls_only=True)
        return {f.path for f in found if f.severity == "error"}

    def both_paths(self):
        return {self.a.relative_to(self.root).as_posix(), self.b.relative_to(self.root).as_posix()}

    # The issue's four Expected cases.

    def test_two_notes_opening_with_the_templates_headings_and_label_pass(self):
        self.both(a_newer="Opened.", b_newer="Opened.", first="Drafted.")
        self.assertEqual(set(), self.refused())

    def test_the_first_entry_worded_as_the_template_suggests_after_another_entrys_date_passes(self):
        self.both(a_newer="The memo went to Dana, scope frozen.", b_newer="The plan went to Jo, scope frozen.")
        self.assertEqual(set(), self.refused())

    def test_two_notes_with_the_templates_structure_and_the_same_first_entry_pass_check_and_the_hook(self):
        self.both()
        self.assertEqual(set(), self.refused())
        for zone in (self.work, self.home):
            git(zone, "init", "-q")
        notes = {p: p.read_text(encoding="utf-8") for p in (self.a, self.b)}
        for p in notes:
            p.unlink()
        for zone in (self.work, self.home):
            commit_all(zone, "start")
        for p, text in notes.items():
            write(p, text)
        git(self.work, "add", "-A")
        found = [f for f in check.run_checks(self.root, staged=self.work) if f.severity == "error"]
        self.assertEqual([], found)

    def test_eight_words_shared_inside_one_paragraph_still_refuse(self):
        self.both(a_newer="The memo notes %s today." % SHARED, b_newer="The plan notes %s today." % SHARED)
        self.assertEqual(self.both_paths(), self.refused())

    # What must not get through.

    def test_a_log_of_short_lines_with_bold_dates_copied_across_two_zones_still_refuses(self):
        lines = ("Sizing memo agreed", "with both distributors", "before the regional", "pilot starts in March")
        log = "".join("**%d November 2026.** %s\n\n" % (day, line) for day, line in zip((3, 4, 5, 6), lines))
        self.both(a_newer="Opened.", b_newer="Opened.")
        for p in (self.a, self.b):
            write(p, p.read_text(encoding="utf-8") + "\n" + log)
        self.assertEqual(self.both_paths(), self.refused())

    def test_a_log_of_short_lines_with_bold_labels_copied_across_two_zones_still_refuses(self):
        lines = ("Sizing memo agreed", "with both distributors", "before the regional", "pilot starts in March")
        log = "".join("**Decision %d.** %s\n\n" % (n, line) for n, line in enumerate(lines, 1))
        self.both(a_newer="Opened.", b_newer="Opened.")
        for p in (self.a, self.b):
            write(p, p.read_text(encoding="utf-8") + "\n" + log)
        self.assertEqual(self.both_paths(), self.refused())

    def test_a_label_no_template_holds_counts_by_its_own_words(self):
        self.both(a_newer="Opened.", b_newer="Opened.")
        for p in (self.a, self.b):
            write(p, p.read_text(encoding="utf-8") + "\n**Sizing basis agreed between both sides before the regional pilot starts.**\n")
        self.assertEqual(self.both_paths(), self.refused())

    LABELLED = "\n## Notes\n\n**Where it stands, 10 November 2026.** Nordic depot volumes split before regional board.\n"

    def test_the_templates_label_does_not_count_toward_the_words_after_it(self):
        self.both(a_newer="Opened.", b_newer="Opened.")
        for p in (self.a, self.b):
            write(p, p.read_text(encoding="utf-8") + self.LABELLED)
        self.assertEqual(set(), self.refused())

    def test_unreadable_templates_leave_the_words_to_count_as_before(self):
        shutil.rmtree(self.root / "System" / "templates")
        self.both(a_newer="Opened.", b_newer="Opened.")
        for p in (self.a, self.b):
            write(p, p.read_text(encoding="utf-8") + self.LABELLED)
        self.assertEqual(self.both_paths(), self.refused())


if __name__ == "__main__":
    unittest.main()
