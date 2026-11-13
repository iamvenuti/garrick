"""A run of words that the whole workspace holds is stock wording, not a quote (#549).

An intake note carries the same fixed line in every zone. The wording check counts a shared run as common when files
of three zones or more hold it. A sentence lifted from one meeting, or from one note into one other, is still a
finding, however many notes of one or two zones repeat it.

    cd tests && python3 -m unittest test_wall_common

Invented names only: Work, Home and Study are walled zones of the fixture.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, commit_all, git, project_hub, thread_note, write  # noqa: E402
from zone_fixture import HOME_SAYS, build  # noqa: E402

import check  # noqa: E402
import garrick_lib as lib  # noqa: E402

STOCK = "Cedar quay survey results were forwarded without comment for the harbour budget review."
TAIL = " The owner asked for a second pass before the sailing season opens."


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Common(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build(self.root)
        base = self.root / "Zones" / "Study" / "Maple"
        write(base / "Maple.md", project_hub("Study", "Maple", "jo", ["Notes"]))
        write(base / "Threads" / "Notes" / "Notes.md", thread_note("Maple", "Notes", "jo"))
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)

    def put(self, zone, project, thread, name, text):
        path = self.root / "Zones" / zone / project / "Threads" / thread / name
        write(path, "# Note\n\n%s\n" % text)
        return path

    def intake(self, text=STOCK, work=1, home=1, study=1):
        """The sentence in `work` notes of Work, `home` of Home and `study` of Study."""
        out = []
        for zone, project, thread, count in (("Work", "Northwind", "Pricing", work), ("Home", "Garden", "Beds", home),
                                             ("Study", "Maple", "Notes", study)):
            out += [self.put(zone, project, thread, "Intake%d.md" % n, text) for n in range(count)]
        return out

    def refused(self, **kw):
        found = check.run_checks(self.root, walls_only=True, **kw)
        return {f.path for f in found if f.severity == "error" and "repeats wording" in f.message}

    def paths(self, files):
        return {p.relative_to(self.root).as_posix() for p in files}

    def staged_refused(self, path):
        work = self.root / "Zones" / "Work"
        text = path.read_text(encoding="utf-8")
        path.unlink()
        git(work, "init", "-q")
        commit_all(work, "start")
        write(path, text)
        git(work, "add", "-A")
        found = check.run_checks(self.root, staged=work)
        return {f.path for f in found if f.severity == "error" and "repeats wording" in f.message}

    def test_the_same_sentence_in_intake_notes_of_three_walled_zones_is_no_finding(self):
        self.intake()
        self.assertEqual(set(), self.refused())

    def test_the_same_sentence_in_two_walled_zones_is_still_a_finding(self):
        files = self.intake(study=0)
        self.assertEqual(self.paths(files), self.refused())

    def test_two_files_of_one_zone_and_one_of_another_is_three_files_in_two_zones_and_stands(self):
        files = self.intake(work=2, home=1, study=0)
        self.assertEqual(self.paths(files), self.refused())

    def test_a_sentence_lifted_from_one_walled_meeting_into_one_note_is_still_a_finding(self):
        note = self.put("Work", "Northwind", "Pricing", "Lifted.md", HOME_SAYS)
        self.assertEqual(self.paths([note]), self.refused())

    def test_many_files_of_two_zones_still_stand(self):
        files = self.intake(work=3, home=4, study=0)           # seven files, two zones
        self.assertEqual(self.paths(files), self.refused())

    def test_a_meeting_copied_into_many_notes_of_one_zone_is_still_a_finding(self):
        # The Home meeting's sentence pasted into five and then six Work notes: copies never vouch for the leak.
        notes = [self.put("Work", "Northwind", "Pricing", "Lifted%d.md" % n, HOME_SAYS) for n in range(5)]
        self.assertEqual(self.paths(notes), self.refused())
        notes.append(self.put("Work", "Northwind", "Pricing", "Lifted5.md", HOME_SAYS))
        self.assertEqual(self.paths(notes), self.refused())

    def test_a_note_copied_into_many_notes_of_one_zone_and_one_of_another_is_still_a_finding(self):
        home = [self.put("Home", "Garden", "Beds", "Own%d.md" % n, STOCK) for n in range(5)]
        leak = self.put("Work", "Northwind", "Pricing", "Leak.md", STOCK)
        self.assertIn(self.paths([leak]).pop(), self.refused())
        self.assertTrue(home)

    def test_a_run_is_common_only_as_a_whole(self):
        # The base sentence is in three zones; Work and Home also share a longer run that no third zone holds.
        self.put("Study", "Maple", "Notes", "Intake.md", STOCK)
        longer = [self.put("Work", "Northwind", "Pricing", "Long.md", STOCK + TAIL),
                  self.put("Home", "Garden", "Beds", "Long.md", STOCK + TAIL)]
        self.assertEqual(self.paths(longer), self.refused())

    def test_a_meeting_page_counts_as_a_file_but_names_no_zone(self):
        # The Home meeting, a Home note and a Work note hold the sentence: three files, but only two zones of notes.
        lifted = self.put("Work", "Northwind", "Pricing", "Intake.md", HOME_SAYS)
        self.put("Home", "Garden", "Beds", "Intake.md", HOME_SAYS)
        self.assertIn(lifted.relative_to(self.root).as_posix(), self.refused())

    def test_an_index_that_counts_nothing_leaves_the_finding_standing(self):
        files = self.intake()
        with mock.patch.object(check, "widespread_runs", lambda ws, owners: set()):
            self.assertEqual(self.paths(files), self.refused())

    def test_an_index_made_without_the_count_counts_nothing_as_widespread(self):
        self.assertEqual(set(), check.QuoteIndex({}, set()).widespread)

    def test_the_staged_check_gives_the_verdict_of_the_full_run(self):
        files = self.intake()
        self.assertEqual(set(), self.staged_refused(files[0]))
        self.assertEqual(set(), self.refused())

    def test_the_staged_check_still_refuses_what_the_full_run_refuses(self):
        files = self.intake(study=0)
        full = self.refused()
        self.assertEqual(self.paths(files), full)
        self.assertEqual({self.paths([files[0]]).pop()}, self.staged_refused(files[0]))


if __name__ == "__main__":
    unittest.main()
