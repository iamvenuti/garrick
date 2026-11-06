"""One normaliser and one resolver for the tokens that name a Meetings page.

    cd tests && python3 -m unittest test_wall_forms

The wall check once learned one form at a time: a slash path, a `./` path, a
bare name. This module builds the forms instead of listing them. A token is a
product of page kind x grade x path depth x prefix x suffix x wrapper, and
every row is refused across a wall and passes on the near side. A form a review
finds later is a new value of one factor, not a new test.

Northwind is a project for Acme, Harbour one for Birch & Co, with a wall
between the two parties; neither folder is named like its party. Every
workspace is built in a temporary folder with invented names only.
"""

from __future__ import annotations

import itertools
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import GIT_ENV, HAVE_GIT, build_workspace, commit_all, git, meeting_page, project_hub, thread_note, write  # noqa: E402

import check  # noqa: E402

KINDS = ("source", "person", "entity", "decision", "question", "answer", "raw")
GRADES = ("", "dormant", "archive")           # live, then the two that faded
PREFIXES = ("", "./", "././", "/", "//")
SUFFIXES = ("", "/", ":3", "#heading", ".md", ".md/")
WRAPPERS = ("code", "quoted", "cat", "link", "wikilink")

# Two pages of each kind and grade, one for each side of the wall. A name is
# not shared between two pages, so a bare name leads to one page.
FAR, NEAR = "birch", "acme"
SLUGS = {FAR: ("harvest", "orchard", "meadow"), NEAR: ("quarry", "forge", "lantern")}
PEOPLE = {FAR: ("kai-ross", "lee-ross", "max-ross"), NEAR: ("jo-lane", "ana-lane", "tom-lane")}
ENTITIES = {FAR: ("harvest-co", "orchard-co", "meadow-co"), NEAR: ("quarry-ltd", "forge-ltd", "lantern-ltd")}

DECISION_BODY = ("\n# Pick a supplier\n\n## Decision\n\nGo.\n\n## Assumptions\n\nNone.\n\n"
                 "## Options turned down\n\nNone.\n\n## Revisit when\n\nNever.\n")


def meetings_home(root: Path, grade: str) -> Path:
    home = root / "Wikis" / "Meetings"
    return home / grade if grade else home


def page_files(root: Path, kind: str, grade: str, party: str, n: int):
    """(path, text) of each file one page of `kind` needs, the page first."""
    home = meetings_home(root, grade)
    slug = SLUGS[party][n]
    day = "26031%d" % (5 + n)
    if kind == "source":
        return [(home / "wiki" / "sources" / ("%s-%s.md" % (day, slug)),
                 meeting_page("Work", "[%s]" % party, slug.title()).replace(
                     "people:", "transcript: \"[[raw/%s-%s-call]]\"\npeople:" % (day, slug)))]
    if kind == "raw":
        return [(home / "raw" / ("%s-%s-call.txt" % (day, slug)), "Someone: we start Monday.\n")]
    if kind == "person":
        name = PEOPLE[party][n]
        return [(home / "wiki" / "people" / (name + ".md"),
                 "---\ntitle: %s\ntype: person\nparty: %s\n---\n\n# %s\n" % (name.replace("-", " ").title(), party, name))]
    if kind == "entity":
        name = ENTITIES[party][n]
        return [(home / "wiki" / "entities" / (name + ".md"),
                 "---\ntitle: %s\ntype: entity\nparty: %s\n---\n\n# %s\n" % (name, party, name))]
    if kind == "decision":
        text = ("---\ntitle: Pick a supplier\ntype: decision\nstatus: valid\nzone: Work\nparties: [%s]\n---\n" % party
                + DECISION_BODY)
        return [(home / "wiki" / "decisions" / ("%s - pick-%s.md" % (day, slug)), text)]
    if kind == "question":
        if grade:
            return []
        text = "---\ntitle: Which region\ntype: question\nzone: Work\nparties: [%s]\n---\n\n# Which region\n" % party
        return [(home / "questions" / ("%s - region-%s.md" % (day, slug)), text)]
    if kind == "answer":
        text = "---\ntitle: Which region\ntype: answer\nzone: Work\nparties: [%s]\n---\n\nThe north.\n" % party
        return [(home / "raw" / "answers" / ("%s - region-%s.md" % (day, slug)), text)]
    raise ValueError(kind)


def build(root: Path):
    """The workspace: the base fixture, Northwind (Acme), Harbour (Birch & Co)
    and every page of every kind and grade for each party. Returns
    {(kind, grade, party): page path}."""
    build_workspace(root)
    work = root / "Zones" / "Work"
    for name, party, thread in (("Northwind", NEAR, "Freight"), ("Harbour", FAR, "Tender")):
        write(work / name / (name + ".md"), project_hub("Work", name, party, [thread]))
        write(work / name / "Threads" / thread / (thread + ".md"), thread_note(name, thread, party))
    pages = {}
    for kind, grade, party in itertools.product(KINDS, GRADES, (FAR, NEAR)):
        files = page_files(root, kind, grade, party, GRADES.index(grade))
        for path, text in files:
            write(path, text)
        if files:
            pages[(kind, grade, party)] = files[0][0]
    return pages


def depths(root: Path, page: Path):
    """Every tail of the page's path from the wiki's name down to its own name,
    without the extension, then the whole path from the disk's top."""
    parts = list(page.relative_to(root).parts)
    parts[-1] = page.stem
    tails = ["/".join(parts[-i:]) for i in range(1, len(parts) + 1)]
    return tails + [str(root / "/".join(parts))]


def wrap(wrapper: str, token: str) -> str:
    if wrapper == "code":
        return "`%s`" % token
    if wrapper == "quoted":
        return "`\"%s\"`" % token
    if wrapper == "cat":
        return "`cat %s`" % token
    if wrapper == "link":
        return "[the page](<%s>)" % token if " " in token else "[the page](%s)" % token
    return "[[%s]]" % token


def rows(root: Path, pages: dict, party: str):
    """(label, text) for every row that names a page of `party`."""
    out = []
    for (kind, grade, owner), page in sorted(pages.items()):
        if owner != party:
            continue
        for depth in dict.fromkeys(depths(root, page)):
            for prefix, suffix, wrapper in itertools.product(PREFIXES, SUFFIXES, WRAPPERS):
                token = prefix + depth + suffix
                label = "%s/%s/%s: %s" % (kind, grade or "live", wrapper, token)
                out.append((label, "# Notes\n\nSee %s now.\n" % wrap(wrapper, token)))
    return out


class Table:
    """The rows run against one check module, in one process: the page index
    is built once, as a run of the check builds it."""

    def __init__(self, tools=check, root: Path = None):
        self.check = tools
        self.root = root
        self.pages = build(root)
        self.ws = tools.discover(root)
        self.ws.quick = True            # the wording comparison is not the subject here
        self.notes = {}
        for name, party, thread in (("Northwind", NEAR, "Freight"), ("Harbour", FAR, "Tender")):
            project = root / "Zones" / "Work" / name
            self.notes[name] = (project, {party}, project / "Threads" / thread / "Notes.md")

    def verdict(self, project_name: str, text: str) -> str:
        project, ptags, note = self.notes[project_name]
        found = self.check.walls_for_file(self.ws, project, ptags, note, text)
        walls = [f for f in found if f.check == "walls"]
        if any(f.severity == "error" for f in walls):
            return "refused"
        return "warned" if walls else "passed"

    def run(self, full: bool = False):
        """{(project, label): verdict} for the four readings: each project
        naming the pages of each party."""
        out = {}
        for project_name, own in (("Northwind", NEAR), ("Harbour", FAR)):
            for party in (FAR, NEAR):
                for i, (label, text) in enumerate(rows(self.root, self.pages, party)):
                    if project_name == "Northwind" or full or i % 11 == 0:
                        out[(project_name, party, label)] = self.verdict(project_name, text)
        return out


class WallFormsTest(unittest.TestCase):
    """The table, read from Northwind (Acme): the pages of Birch & Co are across
    the wall and every row naming one is refused; the pages of Acme are on the
    near side and every row naming one passes with no finding at all. Harbour
    (Birch & Co) reads the same table the other way round, one row in eleven."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name).resolve() / "Workspace"
        cls.table = Table(root=cls.root)
        cls.verdicts = cls.table.run()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def read(self, project, party):
        return {k[2]: v for k, v in self.verdicts.items() if k[0] == project and k[1] == party}

    def test_the_table_is_as_wide_as_its_factors(self):
        per_depth = len(PREFIXES) * len(SUFFIXES) * len(WRAPPERS)
        self.assertEqual(150, per_depth)
        self.assertEqual(len(self.read("Northwind", FAR)), len(self.read("Northwind", NEAR)))
        self.assertGreater(len(self.read("Northwind", FAR)), 9000)

    def test_every_row_across_the_wall_is_refused(self):
        for project, party in (("Northwind", FAR), ("Harbour", NEAR)):
            wrong = sorted(k for k, v in self.read(project, party).items() if v != "refused")
            self.assertEqual([], wrong[:15], "%s: %d rows pass" % (project, len(wrong)))

    def test_every_row_on_the_near_side_passes_with_no_finding(self):
        for project, party in (("Northwind", NEAR), ("Harbour", FAR)):
            wrong = sorted((k, v) for k, v in self.read(project, party).items() if v != "passed")
            self.assertEqual([], wrong[:15], "%s: %d rows draw a finding" % (project, len(wrong)))


class WallFormsRowsTest(unittest.TestCase):
    """The forms the 0.57.0 release review named, one by one, through the whole
    check, so that the table and the commit hook's path are the same code."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        self.pages = build(self.root)
        self.note = self.root / "Zones" / "Work" / "Northwind" / "Threads" / "Freight" / "Notes.md"
        self.where = "Zones/Work/Northwind/Threads/Freight/Notes.md"

    def says(self, written):
        write(self.note, "# Notes\n\nSee %s now.\n" % written)
        return [(f.severity, f.message) for f in check.run_checks(self.root, walls_only=True) if f.path == self.where]

    def test_the_forms_the_release_review_found_are_refused(self):
        for written in ("`Wikis/Meetings/wiki/people/kai-ross/`", "`cat Wikis/Meetings/wiki/people/kai-ross/`",
                        "`Wikis/Meetings/wiki/people/kai-ross//`", "`//Wikis/Meetings/wiki/people/kai-ross`",
                        "`./Wikis/Meetings/wiki/sources/260315-harvest/`", "`./wiki/sources/260315-harvest/`",
                        "`./260315-harvest/`", "`././260315-harvest.md`", "`260315-harvest`", "`260315-harvest:3`",
                        "`\"260315-harvest\"`", "`./wiki/decisions/260315 - pick-harvest/`",
                        "`wiki/entities/harvest-co/`", "`harvest-co`", "`cat -n wiki/entities/harvest-co.md`"):
            with self.subTest(written):
                found = self.says(written)
                self.assertEqual(["error"], [s for s, _ in found], found)
                self.assertIn("a wall stands between acme and birch", found[0][1])

    def test_a_message_names_the_page_and_the_wall_and_nothing_it_holds(self):
        found = self.says("`./wiki/people/kai-ross/`")
        self.assertEqual(1, len(found), found)
        self.assertIn("person page", found[0][1])
        self.assertIn("a wall stands between acme and birch", found[0][1])

    def test_a_raw_record_by_its_name_or_its_path_is_refused(self):
        for written in ("`raw/260315-harvest-call.txt`", "`./raw/260315-harvest-call/`", "`260315-harvest-call`",
                        "`cat -n Wikis/Meetings/raw/260315-harvest-call.txt:3`"):
            with self.subTest(written):
                found = self.says(written)
                self.assertEqual(["error"], [s for s, _ in found], found)

    def test_a_page_of_nobody_is_not_refused(self):
        write(self.root / "Wikis" / "Meetings" / "wiki" / "people" / "sam-nobody.md",
              "---\ntitle: Sam Nobody\ntype: person\nparty: none\n---\n\n# Sam Nobody\n")
        self.assertEqual([], self.says("`wiki/people/sam-nobody/` and `sam-nobody`"))

    def test_a_folder_that_only_shares_a_name_is_still_a_folder(self):
        write(self.root / "Zones" / "Work" / "Harbour" / "Notes" / "Demo.md", "# Demo\n")
        for written in ("`Demo/`", "`Notes/Demo/`", "`./Demo/`", "`~/Applications/Garrick Demo/`"):
            with self.subTest(written):
                self.assertEqual([], self.says(written))

    def test_the_hook_reads_the_same_forms(self):
        ws = check.discover(self.root)
        ws.quick = True
        project = self.root / "Zones" / "Work" / "Northwind"
        text = "# Notes\n\nSee `./wiki/people/kai-ross/` and `260315-harvest`.\n"
        found = check.walls_for_file(ws, project, {NEAR}, self.note, text)
        self.assertEqual(["error", "error"], [f.severity for f in found])

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_commit_hook_refuses_the_forms_too(self):
        work = self.root / "Zones" / "Work"
        shutil.rmtree(work / ".git", ignore_errors=True)
        git(work, "init", "-q")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
            commit_all(work, "start")
            write(self.note, "# Notes\n\nSee `./wiki/people/kai-ross/`, `260315-harvest` and `wiki/entities/quarry-ltd/`.\n")
            git(work, "add", "-A")
            found = check.run_checks(self.root, staged=work)
        self.assertEqual([("error", self.where), ("error", self.where)], [(f.severity, f.path) for f in found])

    def test_plain_forms_settle_every_token_to_one_plain_form(self):
        want = "wiki/sources/260315-harvest"
        for token in ("wiki/sources/260315-harvest", "./wiki/sources/260315-harvest/", "././wiki//sources/260315-harvest.md/",
                      "cat -n wiki/sources/260315-harvest.md:3", '"wiki/sources/260315-harvest"', "//wiki/sources/260315-harvest",
                      "wiki/sources/260315-harvest#heading", "wiki\\sources\\260315-harvest", "wiki/sources/260315-harvest.md/:3"):
            with self.subTest(token):
                self.assertIn(want, check.plain_forms(token))

    def test_the_page_index_is_built_once_a_run(self):
        calls = []
        real = check.PageNames.__init__

        def counting(self, ws):
            calls.append(1)
            real(self, ws)

        check.PageNames.__init__ = counting
        try:
            ws = check.discover(self.root)
            ws.quick = True
            project = self.root / "Zones" / "Work" / "Northwind"
            for n in range(5):
                check.walls_for_file(ws, project, {NEAR}, self.note, "See `./wiki/people/kai-ross/` %d.\n" % n)
        finally:
            check.PageNames.__init__ = real
        self.assertEqual(1, len(calls))


if __name__ == "__main__":
    unittest.main()
