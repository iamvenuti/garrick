"""#721: a filesystem path is not wording in the repeated-wording check.

    cd tests && python3 -m unittest test_wall_paths

An open-zone file (Orchard, zone Ventures) and a walled-zone file (Garden, zone Home) that share only an application's
install path are not held back. Content words written as a path's parts, next to a path, or beside it on a line are
still counted, and the reference rules still refuse a path into a walled project. Invented names only.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, write  # noqa: E402
from zone_fixture import build  # noqa: E402

import check  # noqa: E402

APP = "/Applications/Cedar Browser.app/Contents/MacOS/Cedar Browser"
EIGHT = "the Nordic depot volumes are split before the regional board handover"
CONTENT = ["harvest", "ledger", "quarry", "pallets", "freight", "tariff", "customs", "invoices"]


class Runs(unittest.TestCase):
    def runs(self, text):
        return check.runs(text, None, check.TemplateStructure.empty())

    def test_an_application_path_alone_is_no_run(self):
        self.assertEqual(set(), self.runs('"browser": "%s"' % APP))
        self.assertEqual(set(), self.runs('BROWSER = "%s"' % APP))
        self.assertEqual(set(), self.runs("open -a %s now" % APP))

    def test_system_folders_and_the_app_suffix_go_and_the_rest_stays(self):
        words = check.words(check.without_link_targets("/Users/jo/Library/Application Support/Cedar/notes.json"))
        self.assertEqual(["jo", "application", "support", "cedar", "notes", "json"], words)

    def test_content_words_written_as_a_path_are_still_counted(self):
        for text in ("/Users/jo/Notes/" + "/".join(CONTENT), "~/" + "-".join(CONTENT), "~/Notes/" + "/".join(CONTENT),
                     "/Applications/" + " ".join(CONTENT) + ".app/Contents/MacOS/x"):
            with self.subTest(text=text):
                self.assertTrue(self.runs(text))

    def test_words_each_side_of_a_path_run_on_across_it(self):
        split = "harvest ledger quarry pallets %s freight tariff customs invoices" % "/usr/local/bin"
        plain = "harvest ledger quarry pallets freight tariff customs invoices"
        self.assertTrue(self.runs(split))
        self.assertEqual(self.runs(plain), self.runs(split))

    def test_a_system_word_that_is_not_in_a_path_is_a_word(self):
        self.assertEqual(["the", "library", "and", "the", "users", "bin"], check.words(check.without_link_targets("the library and the users bin")))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TwoFiles(unittest.TestCase):
    """The issue's two cases and the ones that must not get through, on a fixture workspace."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build(self.root)
        self.script = self.root / "Zones" / "Ventures" / "Orchard" / "Threads" / "Drafts" / "build.txt"
        self.json = self.root / "Zones" / "Home" / "Garden" / "Threads" / "Beds" / "run.json"
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)

    def refused(self):
        found = check.run_checks(self.root, walls_only=True)
        return {f.path for f in found if f.severity == "error"}

    def pair(self, script, data):
        write(self.script, script)
        write(self.json, data)

    def test_only_an_install_path_in_common_passes(self):
        self.pair('BROWSER = "%s"\nprint("start")\n' % APP, '{"browser": "%s", "ran": "tuesday"}\n' % APP)
        self.assertEqual(set(), self.refused())

    def test_the_same_files_with_eight_content_words_repeated_are_refused(self):
        self.pair('BROWSER = "%s"\n# %s\n' % (APP, EIGHT), '{"browser": "%s", "note": "%s"}\n' % (APP, EIGHT))
        self.assertIn(self.script.relative_to(self.root).as_posix(), self.refused())

    def test_eight_content_words_written_as_a_path_are_refused(self):
        for path in ("/Users/jo/Notes/" + "/".join(CONTENT), "~/" + "-".join(CONTENT), "~/Notes/" + "/".join(CONTENT)):
            with self.subTest(path=path):
                self.pair("see %s\n" % path, '{"said": "%s"}\n' % " ".join(CONTENT))
                self.assertIn(self.script.relative_to(self.root).as_posix(), self.refused())

    def test_eight_content_words_split_around_a_path_are_refused(self):
        words = "harvest ledger quarry pallets {} freight tariff customs invoices"
        self.pair(words.format(APP) + "\n", '{"said": "%s"}\n' % words.format(APP))
        self.assertIn(self.script.relative_to(self.root).as_posix(), self.refused())
        self.pair(words.format("/usr/local/bin") + "\n", '{"said": "%s"}\n' % words.format(""))
        self.assertIn(self.script.relative_to(self.root).as_posix(), self.refused())

    def test_a_path_into_a_walled_project_is_still_refused_as_a_reference(self):
        target = self.root / "Zones" / "Home" / "Garden" / "Threads" / "Beds" / "Plan.md"
        write(self.script, "See %s now.\n" % target)
        found = [f for f in check.run_checks(self.root, walls_only=True) if f.severity == "error"]
        self.assertTrue([f for f in found if f.path == self.script.relative_to(self.root).as_posix()], found)


if __name__ == "__main__":
    unittest.main()
