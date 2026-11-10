"""Where a run of words ends in the wording check (#498): at a heading, at a bold label that opens a line, and at the
date that opens a dated entry. Two thread notes in two walled zones that open with the thread template's structure
and have the same first entry, worded as the template suggests, quote nothing; eight words inside one paragraph
are still refused.

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


def thread(title, project, party, artifact, action, earlier, first="First draft sent today."):
    """A thread note as the thread template lays it out: its headings, a Resume here block, the rule, two dated
    entries. `earlier` is the last words of the newer entry; the older entry opens with the same date in both notes."""
    return (FRONT % (title, project, party) + "# %s\n\n## The ask\n\nWhat each side wants.\n\n## State of play\n\n"
            "### Resume here\n\n**Where it stands, 10 November 2026.** The work is under way.\n\n" % title
            + TABLE % (artifact, action) + "\n---\n\n**10 November 2026.** %s\n\n**9 November 2026.** %s\n" % (earlier, first))


class Runs(unittest.TestCase):
    def test_a_run_ends_at_a_heading(self):
        a = check.runs("Short end of a section.\n\n## Next steps\n\nThen the rest of the section follows on.\n")
        self.assertEqual(set(), a)

    def test_a_run_ends_at_a_bold_label_that_opens_a_line(self):
        text = "One two three four five six.\n\n**Decision.** Seven eight nine ten eleven twelve.\n"
        self.assertEqual(set(), check.runs(text))
        self.assertTrue(check.runs("One two three four five six seven eight nine ten.\n"))

    def test_a_run_ends_at_the_date_that_opens_an_entry(self):
        last = "Both sides agreed, scope frozen."
        for date in ("**10 November 2026.**", "10 November 2026.", "2026-11-10:"):
            with self.subTest(date=date):
                self.assertEqual(set(), check.runs("%s\n\n%s Thread opened and drafted.\n" % (last, date)))

    def test_bold_inside_a_line_is_not_a_break(self):
        self.assertTrue(check.runs("The plan was to send the **memo** to Dana before the end of the week.\n"))

    def test_eight_words_inside_one_paragraph_are_still_a_run(self):
        paragraph = "**Decision.** The Nordic depot volumes are split before the regional board handover meets."
        self.assertTrue(check.runs(paragraph))
        self.assertEqual(check.runs(paragraph), check.runs("Intro.\n\n" + paragraph))

    def test_a_resume_table_is_still_read_row_by_row_under_a_bold_lead_in(self):
        block = ("### Resume here\n\n**Where it stands, 10 November 2026.** Drafting.\n\n" + TABLE % ("a path", "Rowan to call")
                 + "\n---\n\n**10 November 2026.** Opened.\n")
        self.assertEqual(set(), check.runs(block))


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

    def both(self, a_earlier="The pricing memo went to Dana, scope frozen.",
             b_earlier="The bed plan went to Jo, scope frozen.", first="First draft sent today."):
        write(self.a, thread("Pricing", "Northwind", "acme", "`Deliverables/260310 - Memo.md`", "Rowan to send the memo", a_earlier, first))
        write(self.b, thread("Beds", "Garden", "jo", "`Deliverables/260310 - Plan.md`", "Jo to mark the beds", b_earlier, first))

    def refused(self):
        found = check.run_checks(self.root, walls_only=True)
        return {f.path for f in found if f.severity == "error"}

    def test_notes_that_open_with_the_templates_structure_and_the_same_first_entry_pass(self):
        self.both()
        self.assertEqual(set(), self.refused())

    def test_the_template_headings_and_labels_alone_make_no_quotation(self):
        # the Resume here block and the first entry carry the template's own words, the same in both notes
        self.both(a_earlier="Opened.", b_earlier="Opened.")
        self.assertEqual(set(), self.refused())

    def test_the_last_words_of_an_entry_the_next_date_and_a_first_entry_make_no_quotation(self):
        self.both(a_earlier="The memo went to Dana, scope frozen.", b_earlier="The plan went to Jo, scope frozen.")
        self.assertEqual(set(), self.refused())

    def test_the_commit_hook_passes_both_notes(self):
        self.both()
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
        shared = "the Nordic depot volumes are split before the regional board handover"
        self.both(a_earlier="The memo notes %s today." % shared, b_earlier="The plan notes %s today." % shared)
        self.assertEqual({self.a.relative_to(self.root).as_posix(), self.b.relative_to(self.root).as_posix()}, self.refused())

    def test_eight_words_after_a_bold_lead_in_still_refuse(self):
        shared = "the Nordic depot volumes are split before the regional board handover"
        self.both(a_earlier="**Decision.** %s." % shared, b_earlier="**Decision.** %s." % shared)
        self.assertEqual({self.a.relative_to(self.root).as_posix(), self.b.relative_to(self.root).as_posix()}, self.refused())

    LONG = "**Sizing basis agreed between both sides before the regional pilot starts.**"

    def with_label(self, template):
        """Both notes open an entry with the same long label; the workspace's thread template holds it, or not."""
        self.both()
        for p in (self.a, self.b):
            write(p, p.read_text(encoding="utf-8") + "\n%s\n" % self.LONG)
        if template:
            write(self.root / "System" / "templates" / "thread" / "Label.md", "# Label\n\n%s\n" % self.LONG)
        return self.refused()

    def test_a_label_the_installed_templates_hold_never_counts(self):
        self.assertEqual(set(), self.with_label(template=True))

    def test_a_label_no_template_holds_counts_by_its_own_words(self):
        self.assertEqual({self.a.relative_to(self.root).as_posix(), self.b.relative_to(self.root).as_posix()},
                         self.with_label(template=False))

    def test_unreadable_templates_leave_the_words_to_count_as_before(self):
        shutil.rmtree(self.root / "System" / "templates")
        self.both()
        for p in (self.a, self.b):
            write(p, p.read_text(encoding="utf-8") + "\n%s\n" % self.LONG)
        self.assertEqual(2, len(self.refused()))


if __name__ == "__main__":
    unittest.main()
