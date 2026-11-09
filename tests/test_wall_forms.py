"""What the wall check reads as a reference: the vault's resolution, rule by rule.

    cd tests && python3 -m unittest test_wall_forms

A token is a reference only when the vault resolves it (docs/principles.md): a
link, as Obsidian resolves one (rule 1), or a token that is the exact path of a
file (rule 2). This module holds the unit test of that resolution, one case per
way of writing a path, and the end-to-end rows: one for each link form and page
kind, run on both sides of the wall. The reviewers' case files are in
`walls/forms/` and run in `test_wall_form_files.py`.

Northwind is a project for Acme, Harbour one for Birch & Co, with a wall
between the two parties; neither folder is named like its party. Every
workspace is built in a temporary folder with invented names only.
"""

from __future__ import annotations

import itertools
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, build_workspace, commit_all, git, meeting_page, project_hub, thread_note, write  # noqa: E402

import check  # noqa: E402

KINDS = ("source", "person", "entity", "decision", "question", "answer", "raw")
GRADES = ("", "dormant", "archive")           # live, then the two that faded

# Two pages of each kind and grade, one for each side of the wall.
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
    """The workspace: the base fixture, Northwind (Acme), Harbour (Birch & Co) and every page of every kind and
    grade for each party. Returns {(kind, grade, party): page path}."""
    build_workspace(root)
    work = root / "Zones" / "Work"
    for name, party, thread in (("Northwind", NEAR, "Freight"), ("Harbour", FAR, "Tender")):
        write(work / name / (name + ".md"), project_hub("Work", name, party, [thread]))
        write(work / name / "Threads" / thread / (thread + ".md"), thread_note(name, thread, party))
    write(work / "Harbour" / "Sources" / "brief.docx", "far brief\n")
    write(work / "Northwind" / "Sources" / "brief.docx", "near brief\n")
    pages = {}
    for kind, grade, party in itertools.product(KINDS, GRADES, (FAR, NEAR)):
        files = page_files(root, kind, grade, party, GRADES.index(grade))
        for path, text in files:
            write(path, text)
        if files:
            pages[(kind, grade, party)] = files[0][0]
    return pages


# --- The reviewers' case files -------------------------------------------------------------------------------------

FORMS = Path(__file__).resolve().parent / "walls" / "forms"
NAMES = {
    FAR: dict(person="wiki/people/kai-ross", pname="kai-ross", pesc="kai\\-ross", punder="kai_ross", pspace="kai ross",
              pstar="kai-ro*", ptail="ross", entity="wiki/entities/harvest-co", source="wiki/sources/260315-harvest",
              sname="260315-harvest", dec="wiki/decisions/260315 - pick-harvest", project="Harbour"),
    NEAR: dict(person="wiki/people/jo-lane", pname="jo-lane", pesc="jo\\-lane", punder="jo_lane", pspace="jo lane",
               pstar="jo-la*", ptail="lane", entity="wiki/entities/quarry-ltd", source="wiki/sources/260315-quarry",
               sname="260315-quarry", dec="wiki/decisions/260315 - pick-quarry", project="Northwind"),
}


def fill(text: str, party: str, root: str = "") -> str:
    names = dict(NAMES[party], long="x " * 600, root=root)
    harness = "Zones/Work/%s/.claude/harbour-ledger.md" % names["project"]
    names.update(harness=harness, abspath="%s/%s" % (root, harness), harnessuri=harness.replace("/", "%2F"))
    text = re.sub(r"<U\+([0-9A-Fa-f]{4,6})>", lambda m: chr(int(m.group(1), 16)), text)
    return re.sub(r"\{(\w+)\}", lambda m: names[m.group(1)], text)


def load(path: Path):
    """[(case name, far verdict, near verdict, template)] of one round's file."""
    cases, name, meta, body, fenced = [], None, {}, [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if fenced:
            if line.startswith("~~~~~"):
                cases.append((name, meta.get("far"), meta.get("near"), "\n".join(body) + "\n"))
                name, meta, body, fenced = None, {}, [], False
            else:
                body.append(line)
        elif line.startswith("~~~~~"):
            fenced = True
        elif line.startswith("### "):
            name, meta = line[4:].strip(), {}
        elif name and re.match(r"(far|near):", line):
            key, _, value = line.partition(":")
            meta[key] = value.strip()
    return cases


def all_cases():
    out = []
    for path in sorted(FORMS.glob("*.md")):
        if path.name != "README.md":
            out += [(path.stem, n) + case for n, case in enumerate(load(path), 1)]
    return out


# --- The end-to-end rows -------------------------------------------------------------------------------------------

NOTE = "# Notes\n\nSee %s now.\n"
# One for each way a note links or writes a path that the vault resolves.
LINKS = {
    "wikilink-name": lambda r: NOTE % ("[[%s]]" % r["name"]),
    "wikilink-path": lambda r: NOTE % ("[[%s]]" % r["path"]),
    "markdown-link": lambda r: NOTE % ("[the page](<%s>)" % r["path"]),
    "embed": lambda r: NOTE % ("![[%s]]" % r["name"]),
    "code-path": lambda r: NOTE % ("`%s`" % r["path"]),
    "frontmatter": lambda r: "---\nrelated: %s\n---\n\nx\n" % r["path"],
    "html-link": lambda r: NOTE % ('<a href="%s">x</a>' % r["path"]),
    "autolink": lambda r: NOTE % ("<file://%s>" % r["abs"]),
    "obsidian-uri": lambda r: NOTE % ("[x](obsidian://open?vault=Workspace&file=%s)"
                                      % r["path"].replace("/", "%2F").replace(" ", "%20")),
}


def named(root: Path, page: Path) -> dict:
    """How the forms of `LINKS` write a page: its name, its path from the top of the vault, its absolute path."""
    path = page.relative_to(root).as_posix()
    return {"name": page.name if page.suffix != ".md" else page.stem, "path": path, "abs": str(page)}


def rows(root: Path, pages: dict, party: str):
    """(label, text) for each row that points at a page of `party`: every kind and grade, in every form."""
    out = []
    for (kind, grade, owner), page in sorted(pages.items()):
        if owner != party:
            continue
        how = named(root, page)
        for form, write_it in LINKS.items():
            if " " in how["path"] and form in ("code-path", "frontmatter", "html-link", "autolink"):
                continue                       # a name with spaces is written in a link, not bare
            if grade and form not in ("wikilink-name", "wikilink-path", "embed"):
                continue                       # a faded page is reached by its name or by its path
            out.append(("%s/%s/%s" % (kind, grade or "live", form), write_it(how)))
    return out


class Table:
    """The rows and the reviewers' cases, run against one check module in one process."""

    def __init__(self, tools=check, root: Path = None):
        self.check = tools
        self.root = root
        self.pages = build(root)
        ctx = root / "System" / "context.md"       # a walled party named like its zone: the case 0.60.1's gate missed
        text = ctx.read_text(encoding="utf-8").replace("| Work | Client work | | walled |", "| Work | Client work | | walled |\n| Cedar | Its own affairs | | walled |")
        text = text.replace("| Acme Corp |", "| Cedar | The company itself | Cedar | `cedar` | yes | |\n| Acme Corp |", 1)
        ctx.write_text(text, encoding="utf-8")
        write(root / "Zones" / "Cedar" / "Todo.md", "# Todo\n")
        for project in ("Harbour", "Northwind"):
            write(root / "Zones" / "Work" / project / ".claude" / "harbour-ledger.md", "{}\n")
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

    ZONE_ROWS = {"cedar-zone/prose": "# Notes\n\nCedar asked for the figures.\n",
                 "cedar-zone/zone-key": "---\nzone: Cedar\ntype: note\n---\n\nx\n"}

    def expected(self):
        """{(project, party, label): what the tree owes}: refused across the wall, or by design (text) there too."""
        want = {}
        for project_name, own in (("Northwind", NEAR), ("Harbour", FAR)):
            for party in (FAR, NEAR):
                for label, _ in rows(self.root, self.pages, party):
                    want[(project_name, party, label)] = "refused" if party != own else "passed"
        want[("Northwind", "cedar", "cedar-zone/prose")] = "refused"
        want[("Northwind", "cedar", "cedar-zone/zone-key")] = "by design"       # #465: the `zone:` key is structure
        for rnd, n, name, far, near, _ in all_cases():
            want[("Northwind", FAR, "form/%s/%d %s" % (rnd, n, name))] = "refused" if far == "refused" else "by design"
            want[("Northwind", NEAR, "form/%s/%d %s" % (rnd, n, name))] = "passed"
        return want

    def run(self, full: bool = False):
        """{(project, party, label): verdict}: Northwind reads the pages of both parties, Harbour reads them back, and
        Northwind reads each case of the case files, naming a page of each party."""
        out = {}
        for project_name in ("Northwind", "Harbour"):
            for party in (FAR, NEAR):
                for label, text in rows(self.root, self.pages, party):
                    out[(project_name, party, label)] = self.verdict(project_name, text)
        for label, text in self.ZONE_ROWS.items():
            out[("Northwind", "cedar", label)] = self.verdict("Northwind", text)
        for rnd, n, name, far, near, template in all_cases():
            for party in (FAR, NEAR):
                out[("Northwind", party, "form/%s/%d %s" % (rnd, n, name))] = self.verdict(
                    "Northwind", fill(template, party, str(self.root)))
        return out


class EndToEndTest(unittest.TestCase):
    """Northwind (Acme) reads the rows: every one that points at a page of Birch & Co is refused, every one that points
    at a page of Acme passes with no finding. Harbour (Birch & Co) reads them the other way round."""

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
        return {k[2]: v for k, v in self.verdicts.items() if k[0] == project and k[1] == party and not k[2].startswith("form/")}

    def test_there_are_under_a_hundred_rows_a_side(self):
        far = rows(self.root, self.table.pages, FAR)
        self.assertEqual(len(far), len(rows(self.root, self.table.pages, NEAR)))
        self.assertTrue(40 < len(far) < 100, len(far))

    def test_every_row_across_the_wall_is_refused(self):
        for project, party in (("Northwind", FAR), ("Harbour", NEAR)):
            wrong = sorted(k for k, v in self.read(project, party).items() if v != "refused")
            self.assertEqual([], wrong[:15], "%s: %d rows pass" % (project, len(wrong)))

    def test_a_walled_party_named_like_its_zone_is_named_in_prose_but_not_by_the_zone_key(self):
        self.assertEqual("refused", self.verdicts[("Northwind", "cedar", "cedar-zone/prose")])
        self.assertEqual("passed", self.verdicts[("Northwind", "cedar", "cedar-zone/zone-key")])

    def test_every_row_on_the_near_side_passes_with_no_finding(self):
        for project, party in (("Northwind", NEAR), ("Harbour", FAR)):
            wrong = sorted((k, v) for k, v in self.read(project, party).items() if v != "passed")
            self.assertEqual([], wrong[:15], "%s: %d rows draw a finding" % (project, len(wrong)))


# --- The resolution, token in, file or nothing out -----------------------------------------------------------------

class ResolutionTest(unittest.TestCase):
    """`exact_files` (rule 2) and `link_references` (rule 1): what each way of writing a path resolves to."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name).resolve() / "Workspace"
        cls.pages = build(cls.root)
        cls.ws = check.discover(cls.root)
        cls.note = cls.root / "Zones" / "Work" / "Northwind" / "Threads" / "Freight" / "Notes.md"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def files(self, token):
        return [p.relative_to(self.root).as_posix() for p in check.exact_files(self.ws, self.note, token)]

    def test_a_path_that_is_a_file_resolves_in_every_way_it_is_written(self):
        person = "Wikis/Meetings/wiki/people/kai-ross.md"
        up = "../../../../../Wikis/Meetings/wiki/people/kai-ross"
        for token in ("Wikis/Meetings/wiki/people/kai-ross", person, "wiki/people/kai-ross", "wiki/people/kai-ross.md",
                      str(self.root / person), str(self.root / person)[:-3], "wikis/meetings/WIKI/people/Kai-Ross",
                      up, up + ".md", "./" + up):
            with self.subTest(token):
                self.assertEqual([person], self.files(token))

    def test_a_path_resolves_from_the_notes_own_folder_first(self):
        self.assertEqual(["Zones/Work/Northwind/Threads/Freight/Freight.md"], self.files("../Freight/Freight.md"))
        self.assertEqual(["Zones/Work/Northwind/Northwind.md"], self.files("../../Northwind.md"))
        self.assertEqual(["Zones/Work/Northwind/Northwind.md"], self.files("Zones/Work/Northwind/Northwind"))
        self.assertEqual(["Zones/Work/Northwind/Sources/brief.docx"], self.files("../../Sources/brief.docx"))
        self.assertEqual(["Zones/Work/Harbour/Sources/brief.docx"], self.files("Zones/Work/Harbour/Sources/brief.docx"))
        self.assertEqual([], self.files("Sources/brief.docx"))

    def test_a_page_resolves_at_the_place_it_stood_in_another_grade(self):
        self.assertEqual(["Wikis/Meetings/dormant/wiki/sources/260316-orchard.md"],
                         self.files("Wikis/Meetings/wiki/sources/260316-orchard"))
        self.assertEqual(["Wikis/Meetings/wiki/sources/260315-harvest.md"],
                         self.files("Wikis/Meetings/archive/wiki/sources/260315-harvest"))

    def test_a_raw_record_and_a_name_with_spaces_resolve(self):
        self.assertEqual(["Wikis/Meetings/raw/260315-harvest-call.txt"], self.files("raw/260315-harvest-call.txt"))
        self.assertEqual(["Wikis/Meetings/wiki/decisions/260315 - pick-harvest.md"],
                         self.files("wiki/decisions/260315 - pick-harvest"))

    def test_everything_else_is_text(self):
        for token in ("wiki/people/kai-*", "wiki/people/*", "people[/]kai-ross", "wiki/people/kai-{ross,x}", "wiki/people/kai-ro?s",
                      "wiki/people/kai\\-ross", "wiki/people/kai_ross", "wiki/people/kai ross", "wiki/people/kai-ross/",
                      "wiki//people/kai-ross", "wiki/./people/kai-ross", "wiki\\people\\kai-ross", "wiki／people／kai-ross",
                      "wiki&#47;people&#47;kai-ross", "wiki%2Fpeople%2Fkai-ross", "wiki/people/kai-ross%20", "wiki/people/kai-ross:3",
                      "wiki/people/kai-ross#heading", "wiki/people/​kai-ross", "wiki/people/kai­ross", "@wiki/people/kai-ross",
                      "path:wiki/people/kai-ross", "HEAD:Wikis/Meetings/wiki/people/kai-ross.md", "wiki/people", "Wikis/Meetings",
                      "kai-ross", "people/kai-ross", "a/" * 700 + "kai-ross",
                      "/Users/someone/elsewhere/Wikis/Meetings/wiki/people/kai-ross"):
            with self.subTest(token):
                self.assertEqual([], self.files(token))

    def test_a_token_is_found_in_the_text_where_it_is_written(self):
        person = "wiki/people/kai-ross"
        for text in ("See `%s`.\n" % person, "See %s.\n" % person, "See “%s”, then.\n" % person, "See (%s).\n" % person,
                     "---\nrelated: %s\n---\n" % person, "---\nrelated:\n  - '%s'\n---\n" % person, "```\ncat %s\n```\n" % person,
                     "See **%s**.\n" % person, "See `cat -n %s`.\n" % person, "See <%s>.\n" % person):
            with self.subTest(text):
                self.assertIn(person, check.reference_tokens(text))
        self.assertIn("wiki/decisions/260315 - pick-harvest", check.reference_tokens("`cat wiki/decisions/260315 - pick-harvest`"))
        self.assertEqual([], check.reference_tokens("A glob `*.md` and a word."))

    def test_a_link_resolves_as_obsidian_resolves_it(self):
        meetings = check.meeting_index(self.ws)

        def land(text):
            return [p.relative_to(self.root).as_posix() for _, hits in check.link_references(self.ws, self.note, text, meetings)
                    for p in hits]

        person = "Wikis/Meetings/wiki/people/kai-ross.md"
        for text in ("[[kai-ross]]", "[[kai-ross|Kai]]", "[[kai-ross#Heading]]", "![[kai-ross]]", "[[wiki/people/kai-ross]]",
                     "[[Wikis/Meetings/wiki/people/kai-ross.md]]", "[x](Wikis/Meetings/wiki/people/kai-ross.md)",
                     "[x](<Wikis/Meetings/wiki/people/kai-ross.md>)", "[x](../../../../../Wikis/Meetings/wiki/people/kai-ross.md)",
                     '<a href="../../../../../Wikis/Meetings/wiki/people/kai-ross.md">x</a>',
                     "[x](obsidian://open?vault=Workspace&file=wiki%2Fpeople%2Fkai-ross)", "<file://%s/%s>" % (self.root, person),
                     "[x]: Wikis/Meetings/wiki/people/kai-ross.md"):
            with self.subTest(text):
                self.assertIn(person, land(text))
        for text in ("[[kai-ro*]]", "[[nobody]]", "[x](https://example.com/kai-ross)", "[[people[/]kai-ross]]"):
            with self.subTest(text):
                self.assertEqual([], land(text))

    def test_the_index_is_built_once_a_run(self):
        self.assertIs(check.reference_index(self.ws), check.reference_index(self.ws))


# --- A few readings through the whole check ------------------------------------------------------------------------

class ThroughTheCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        self.pages = build(self.root)
        self.note = self.root / "Zones" / "Work" / "Northwind" / "Threads" / "Freight" / "Notes.md"
        self.where = "Zones/Work/Northwind/Threads/Freight/Notes.md"

    def says(self, text):
        write(self.note, text if text.startswith(("---", "#")) else "# Notes\n\nSee %s now.\n" % text)
        return [(f.severity, f.message) for f in check.run_checks(self.root, walls_only=True) if f.path == self.where]

    def test_a_reference_across_the_wall_is_refused_with_the_page_and_the_wall_named(self):
        found = self.says("`Wikis/Meetings/wiki/people/kai-ross.md`")
        self.assertEqual(["error"], [s for s, _ in found], found)
        self.assertIn("person page", found[0][1])
        self.assertIn("birch is walled and this project does not name it", found[0][1])

    def test_a_page_of_nobody_is_not_refused(self):
        write(self.root / "Wikis" / "Meetings" / "wiki" / "people" / "sam-nobody.md",
              "---\ntitle: Sam Nobody\ntype: person\nparty: none\n---\n\n# Sam Nobody\n")
        self.assertEqual([], self.says("`wiki/people/sam-nobody` and [[sam-nobody]]"))

    def test_globs_bold_classes_folders_and_web_addresses_name_nothing(self):
        for written in ("`ls *.txt`", "`ls **/*.txt`", "`Sources/**`", "**Work** and *Prep* and **live**", "`[A-Za-z0-9._-]*`",
                        "`wiki/people/kai-*`", "`Wikis/Meetings/wiki/people/`", "`Zones/Work/Harbour/`", "`harvest-co`",
                        "https://example.com/people/kai-ross", "[x](https://github.com/orchard-co)", "[Setup](#setup)",
                        "`wiki/people%2Fkai-ross`", "`wiki/people/kai\\-ross`"):
            with self.subTest(written):
                self.assertEqual([], self.says(written))

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_a_symbolic_link_into_the_wiki_or_a_walled_project_is_refused(self):
        work = self.root / "Zones" / "Work"
        thread = work / "Northwind" / "Threads" / "Freight"
        shutil.rmtree(work / ".git", ignore_errors=True)
        git(work, "init", "-q")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
            commit_all(work, "start")
            links = {"alias.md": self.root / "Wikis" / "Meetings" / "wiki" / "entities" / "harvest-co.md",
                     "harbour": work / "Harbour", "tender.md": work / "Harbour" / "Harbour.md"}
            for name, target in links.items():
                with self.subTest(name):
                    os.symlink(str(target), str(thread / name))
                    try:
                        git(work, "add", "-A")
                        staged = [f for f in check.run_checks(self.root, staged=work) if f.check == "walls"]
                        self.assertTrue(any("symbolic link" in f.message for f in staged), staged)
                    finally:
                        git(work, "reset", "-q")
                        os.unlink(str(thread / name))

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_commit_hook_reads_the_same_references(self):
        work = self.root / "Zones" / "Work"
        shutil.rmtree(work / ".git", ignore_errors=True)
        git(work, "init", "-q")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
            commit_all(work, "start")
            write(self.note, "# Notes\n\nSee [[kai-ross]], `wiki/sources/260315-harvest` and `wiki/entities/quarry-ltd`.\n")
            git(work, "add", "-A")
            found = check.run_checks(self.root, staged=work)
        self.assertEqual([("error", self.where), ("error", self.where)], [(f.severity, f.path) for f in found])

    def test_a_path_too_long_for_the_system_is_a_finding_not_a_crash(self):
        found = self.says("[x](%s/Wikis/Meetings/wiki/people/kai-ross.md)" % ("./a/.." * 1500))
        self.assertTrue(all(s == "error" for s, _ in found), found)


if __name__ == "__main__":
    unittest.main()
