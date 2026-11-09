"""The reviewers' cases, kept: `tests/walls/forms/*.md` run through the staged-commit check.

    cd tests && python3 -m unittest test_wall_form_files

Each file is one review round: note texts with the verdict owed each side of the
wall (format in `walls/forms/README.md`). All the cases are staged in one fixture
workspace and the check runs once over the commit, as the hook runs it; the
verdict of a case is what the check finds on its file.
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
from test_wall_forms import FAR, NEAR, all_cases, build, fill  # noqa: E402

import check  # noqa: E402


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class WallFormFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name).resolve() / "Workspace"
        build(cls.root)
        work = cls.root / "Zones" / "Work"
        shutil.rmtree(work / ".git", ignore_errors=True)
        git(work, "init", "-q")
        for project in ("Harbour", "Northwind"):
            write(work / project / ".claude" / "harbour-ledger.md", "{}\n")
        cls.cases = all_cases()
        folder = work / "Northwind" / "Threads" / "Freight" / "Cases"
        cls.paths = {}
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
            commit_all(work, "start")
            for rnd, n, name, far, near, template in cls.cases:
                for side, party in (("far", FAR), ("near", NEAR)):
                    rel = folder / ("%s-%02d-%s.md" % (rnd, n, side))
                    write(rel, fill(template, party, str(cls.root)))
                    cls.paths[(rnd, n, side)] = str(rel.relative_to(cls.root))
            git(work, "add", "-A")
            found = check.run_checks(cls.root, staged=work)
        cls.found = {}
        for f in found:
            if f.check == "walls":
                cls.found.setdefault(f.path, []).append(f)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def verdict(self, key):
        found = self.found.get(self.paths[key], [])
        if any(f.severity == "error" for f in found):
            return "refused"
        return "warned" if found else "passed"

    def test_there_are_cases_from_both_rounds(self):
        rounds = {c[0] for c in self.cases}
        self.assertEqual({"round-1", "round-2", "round-4"}, rounds & {"round-1", "round-2", "round-4"})
        self.assertGreaterEqual(len(self.cases), 40)

    def test_every_case_gets_its_verdict_on_each_side_of_the_wall(self):
        for rnd, n, name, far, near, _ in self.cases:
            with self.subTest(case="%s: %s" % (rnd, name)):
                self.assertIn(far, ("refused", "by design"), "a form across the wall is refused, or by design is text")
                self.assertEqual("passed", near, "a form on the near side passes with no finding")
                got_far, got_near = self.verdict((rnd, n, "far")), self.verdict((rnd, n, "near"))
                self.assertEqual(near, got_near, "the near side draws a finding")
                if far == "by design":
                    self.assertEqual("passed", got_far, "a token that does not resolve is text: it passes on both sides")
                else:
                    self.assertEqual(far, got_far, "a form that resolves is refused across the wall")


if __name__ == "__main__":
    unittest.main()
