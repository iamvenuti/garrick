"""The reviewers' cases, kept: `tests/walls/forms/*.md` run through the staged-commit check.

    cd tests && python3 -m unittest test_wall_form_files

Each file is one review round: note texts with the verdict owed each side of the
wall (format in `walls/forms/README.md`). All the cases are staged in one fixture
workspace and the check runs once over the commit, as the hook runs it; the
verdict of a case is what the check finds on its file.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, commit_all, git, write  # noqa: E402
from test_wall_forms import FAR, NEAR, build  # noqa: E402

import check  # noqa: E402

FORMS = Path(__file__).resolve().parent / "walls" / "forms"

NAMES = {
    FAR: dict(person="wiki/people/kai-ross", pname="kai-ross", pesc="kai\\-ross", punder="kai_ross", pspace="kai ross",
              pstar="kai-ro*", ptail="ross", entity="wiki/entities/harvest-co", source="wiki/sources/260315-harvest",
              sname="260315-harvest", dec="wiki/decisions/260315 - pick-harvest"),
    NEAR: dict(person="wiki/people/jo-lane", pname="jo-lane", pesc="jo\\-lane", punder="jo_lane", pspace="jo lane",
               pstar="jo-la*", ptail="lane", entity="wiki/entities/quarry-ltd", source="wiki/sources/260315-quarry",
               sname="260315-quarry", dec="wiki/decisions/260315 - pick-quarry"),
}


def unicode_marks(text: str) -> str:
    return re.sub(r"<U\+([0-9A-Fa-f]{4,6})>", lambda m: chr(int(m.group(1), 16)), text)


def fill(text: str, party: str) -> str:
    names = dict(NAMES[party], long="x " * 600)
    return unicode_marks(re.sub(r"\{(\w+)\}", lambda m: names[m.group(1)], text))


def load(path: Path):
    """[(case id, far verdict, near verdict, gap reason, template)] of one round's file."""
    cases, name, meta, body, fenced = [], None, {}, [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if fenced:
            if line.startswith("~~~~~"):
                cases.append((name, meta.get("far"), meta.get("near"), meta.get("gap"), "\n".join(body) + "\n"))
                name, meta, body, fenced = None, {}, [], False
            else:
                body.append(line)
        elif line.startswith("~~~~~"):
            fenced = True
        elif line.startswith("### "):
            name, meta = line[4:].strip(), {}
        elif name and re.match(r"(far|near|gap):", line):
            key, _, value = line.partition(":")
            meta[key] = value.strip()
    return cases


def all_cases():
    out = []
    for path in sorted(FORMS.glob("*.md")):
        if path.name == "README.md":
            continue
        for n, case in enumerate(load(path), 1):
            out.append((path.stem, n) + case)
    return out


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
        cls.cases = all_cases()
        folder = work / "Northwind" / "Threads" / "Freight" / "Cases"
        cls.paths = {}
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
            commit_all(work, "start")
            for rnd, n, name, far, near, gap, template in cls.cases:
                for side, party in (("far", FAR), ("near", NEAR)):
                    rel = folder / ("%s-%02d-%s.md" % (rnd, n, side))
                    write(rel, fill(template, party))
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
        self.assertEqual({"round-1", "round-2"}, rounds & {"round-1", "round-2"})
        self.assertGreaterEqual(len(self.cases), 40)

    def test_every_case_gets_its_verdict_on_each_side_of_the_wall(self):
        for rnd, n, name, far, near, gap, _ in self.cases:
            with self.subTest(case="%s: %s" % (rnd, name)):
                self.assertEqual("refused", far, "a form across the wall is always refused")
                self.assertEqual("passed", near, "a form on the near side passes with no finding")
                got_far, got_near = self.verdict((rnd, n, "far")), self.verdict((rnd, n, "near"))
                self.assertEqual(near, got_near, "the near side draws a finding")
                if gap:
                    self.assertNotEqual(far, got_far, "refused now: drop the gap line of this case (%s)" % gap)
                else:
                    self.assertEqual(far, got_far, "a way past the wall")

    def test_known_gaps_are_named(self):
        gaps = [(c[0], c[2], c[5]) for c in self.cases if c[5]]
        print("\nknown gaps: %s" % (gaps or "none"), file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
