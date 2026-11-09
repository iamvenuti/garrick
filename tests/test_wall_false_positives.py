"""Things the wall check read as pointers that were not (0.58.1).

    cd tests && python3 -m unittest test_wall_false_positives

A project kept in System/, markup and data files, bold round a folder name, a bare
name in a frontmatter value, and a copy of the repository git ignores. Each case
also holds its near miss: what is a pointer is still refused. Every name is
invented; Acme Corp and Birch & Co have a wall between them.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, build_workspace, git_init, project_hub, thread_note, write  # noqa: E402

import check  # noqa: E402

WALL_MESSAGE = "is walled and this project does not name it"


class FalsePositiveTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        self.meet = self.root / "Wikis" / "Meetings" / "wiki"
        # A Birch note reads the pages of Acme as across the wall.
        self.note = self.work / "Birch Entry" / "Threads" / "Market Sizing" / "Notes.md"

    def says(self, text, note=None, suffix=None):
        note = note or self.note
        if suffix:
            note = note.with_suffix(suffix)
        write(note, text)
        where = str(note.relative_to(self.root))
        return [(f.severity, f.message) for f in check.run_checks(self.root, walls_only=True) if f.path == where]

    def says_file(self, text, suffix):
        """The walls' findings for a code file of the Birch project, which the commit hook reads in a repository of a project."""
        note = self.work / "Birch Entry" / ("script" + suffix)
        write(note, text)
        ws = check.discover(self.root)
        ws.quick = True
        found = check.walls_for_file(ws, self.work / "Birch Entry", {"birch"}, note, text)
        return [(f.severity, f.message) for f in found if f.check == "walls"]

    def refused(self, found):
        return [m for s, m in found if s == "error"]

    # 1. System/ is no zone
    def test_a_project_in_system_with_no_party_is_not_checked_as_an_unlabelled_project(self):
        hub = self.root / "System" / "Ops" / "Ops.md"
        write(hub, "---\ntitle: Ops\ntype: project\nstatus: active\n---\n\n# Ops\n")
        note = self.root / "System" / "Ops" / "Notes.md"
        text = "See `260310-acme-kickoff` and [[dana-whitlock]] and `Wikis/Meetings/wiki/sources/260310-acme-kickoff.md`.\n"
        self.assertEqual([], self.says(text, note))

    def test_a_project_of_a_zone_with_no_party_still_commits_nothing(self):
        write(self.work / "Orphan" / "Orphan.md", project_hub("Work", "Orphan", ""))
        write(self.work / "Orphan" / "Threads" / "T" / "T.md", thread_note("Orphan", "T", ""))
        found = self.says("See `Wikis/Meetings/wiki/sources/260310-acme-kickoff.md`.\n",
                          self.work / "Orphan" / "Threads" / "T" / "Notes.md")
        self.assertTrue(any("no party" in m for m in self.refused(found)), found)

    def test_a_project_in_system_that_has_a_party_is_still_checked(self):
        write(self.root / "System" / "Ops" / "Ops.md", project_hub("System", "Ops", "birch"))
        found = self.says("See `Wikis/Meetings/wiki/sources/260310-acme-kickoff.md`.\n", self.root / "System" / "Ops" / "Notes.md")
        self.assertTrue(any(WALL_MESSAGE in m for m in self.refused(found)), found)

    # 2. Markup and data
    def test_an_svg_attribute_that_is_no_address_is_not_a_link(self):
        write(self.meet / "people" / "kai-ross.md", "---\ntitle: Kai Ross\ntype: person\nparty: acme\n---\n\n# Kai\n")
        self.assertEqual([], self.says('<svg><path data-edge-to="x" data-i="0" d="M0 0"/></svg>\n', suffix=".html"))
        # A page's own name in an attribute that is no address is still read.
        for attr in ('data-edge-to="kai-ross"', 'title="kai-ross"'):
            found = self.says('<svg><path %s d="M0 0"/></svg>\n' % attr, suffix=".html")
            self.assertTrue(self.refused(found), (attr, found))
        found = self.says('<svg><path data-edge-to="people/kai-ross" d="M0 0"/></svg>\n', suffix=".html")
        self.assertTrue(self.refused(found), found)
        found = self.says('<a href="../../../../../Wikis/Meetings/wiki/sources/260310-acme-kickoff.md">x</a>\n', suffix=".html")
        self.assertTrue(any(WALL_MESSAGE in m for m in self.refused(found)), found)

    def test_an_indented_stylesheet_and_script_are_not_code_blocks(self):
        write(self.meet / "people" / "t.md", "---\ntitle: T\ntype: person\nparty: acme\n---\n\n# T\n")
        css = ("<style>\n    /* Some stage is a viewer-only layer: nothing more. */\n"
               "    [data-preset=\"blueprint\"][data-theme=\"dark\"] { color: red }\n    * { margin: 0 }\n</style>\n")
        self.assertEqual([], self.says(css, suffix=".html"))

    def pages(self, n):
        for i in range(n):
            write(self.meet / "entities" / ("zeta-%d.md" % i), "---\ntitle: z\ntype: entity\nparty: acme\n---\n\n# z\n")

    def test_normal_css_and_script_do_not_count_as_globs(self):
        css = "<style>\n" + "".join("a%d { x: y }\n* { margin: 0 } [i%d] {}\n" % (i, i) for i in range(6000)) + "</style>\n"
        self.assertEqual([], self.says(css, suffix=".html"))
        self.pages(1000)       # a glob is text however many pages it could match: nothing is expanded (#422)
        many = "\n".join("ls zeta-%d*" % i for i in range(5200))
        self.assertEqual([], self.says("# Notes\n\n```\n%s\n```\n" % many))

    def test_a_string_in_json_that_holds_a_name_is_not_a_path(self):
        for name in ("owen-pike", "mara-quill"):
            write(self.meet / "people" / (name + ".md"), "---\ntitle: x\ntype: person\nparty: acme\n---\n\n# x\n")
        text = ('{\n    "subtitle": "Mara Quill · product readiness for partners",\n'
                '    "text": "Technical track — Mara Quill, Owen Pike (remote)",\n    "icon": "workflow"\n}\n')
        self.assertEqual([], self.says(text, suffix=".json"))
        for value in ("Wikis/Meetings/wiki/people/mara-quill.md", "wiki/people/owen-pike"):
            found = self.says('{\n    "p": "%s"\n}\n' % value, suffix=".json")
            self.assertTrue(any(WALL_MESSAGE in m for m in self.refused(found)), (value, found))

    # 3. Emphasis is not a glob
    def test_bold_round_a_folder_name_is_not_a_glob(self):
        self.assertEqual([], self.says("Keep %sSources/%s and %sThreads/%s and %sNotes%s here.\n" % ("**", "**", "**", "**", "***", "***")))
        # Stars round any name, and a glob, are text: a token names a page only when it is its path.
        for written in ("`%ssources/2603%s`" % ("**", "**"), "`wiki/sources/2603%s`" % "*", "`%s/sources/*`" % ("*" * 2)):
            self.assertEqual([], self.says("See %s now.\n" % written), written)

    # 4. A bare name in a frontmatter value
    def test_a_bare_person_name_in_frontmatter_is_a_name_not_a_pointer(self):
        ctx = self.root / "System" / "context.md"
        ctx.write_text(ctx.read_text().replace("| Theo Marsh | `birch` | Managing partner |",
                                               "| Theo Marsh | `birch` | Managing partner |\n| Dana Whitlock | `birch` | Known on both sides |"))
        acme_note = self.work / "Acme Review" / "Threads" / "Pricing" / "Notes.md"
        self.assertEqual([], self.says("---\naudience: Owen Pike, Dana Whitlock\nclient-sponsor: Dana Whitlock (Acme)\n---\n\nx\n", acme_note))
        for written in ("wiki/people/dana-whitlock",):
            found = self.says("---\nrelated: %s\n---\n\nx\n" % written, self.note)
            self.assertTrue(any(WALL_MESSAGE in m for m in self.refused(found)), (written, found))
        found = self.says("---\nrelated: \"[[dana-whitlock]]\"\n---\n\nx\n", self.note)
        self.assertTrue(any(WALL_MESSAGE in m for m in self.refused(found)), found)

    # B. Ordinary code is readable
    def test_code_files_with_ordinary_globs_are_read_not_refused_whole(self):
        code = "import re\n" + "".join("x%d = re.compile(r'x*y?[%d]') if z else None  # %d*\n" % (i, i, i) for i in range(6000))
        self.assertEqual([], self.says_file(code, ".py"))
        self.assertEqual([], self.says_file(code.replace("import re", "// js"), ".js"))
        self.assertEqual([], self.says_file(code, ".sh"))

    def test_a_path_shaped_glob_in_code_is_text(self):
        write(self.meet / "people" / "kai-ross.md", "---\ntitle: Kai Ross\ntype: person\nparty: acme\n---\n\n# Kai\n")
        for suffix in (".py", ".js", ".sh", ".css"):
            for glob in ("wiki/sources/2603*", "kai-*", "dana*", "people/*"):
                self.assertEqual([], self.says_file("# c\nGLOB = '%s'\n" % glob, suffix), (glob, suffix))
        # The exact path of a page in code is still a reference.
        found = self.says_file("# c\nPAGE = 'wiki/people/kai-ross.md'\n", ".py")
        self.assertTrue(any(WALL_MESSAGE in m for m in self.refused(found)), found)

    # 5. A longer page name is not cut to a shorter one
    def test_an_entity_whose_name_extends_another_is_read_as_itself(self):
        write(self.meet / "entities" / "quartz.md", "---\ntitle: quartz\ntype: entity\nparty: acme\n---\n\n# q\n")
        write(self.meet / "entities" / "quartz-advisory.md", "---\ntitle: quartz advisory\ntype: entity\nparty: birch\n---\n\n# q\n")
        found = self.says("See `entities/quartz-advisory` and "
                          "[x](obsidian://open?vault=v&file=Meetings/wiki/entities/quartz-advisory).\n")
        self.assertEqual([], found)
        found = self.says("See `wiki/entities/quartz`.\n")
        self.assertTrue(any(WALL_MESSAGE in m for m in self.refused(found)), found)

    # 6. What git ignores is no labelled material
    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_a_path_into_an_ignored_copy_points_at_nothing(self):
        git_init(self.work)
        write(self.work / ".gitignore", "Acme Review/Repo/\n")
        write(self.work / "Acme Review" / "Repo" / "template" / "System" / "rules.md", "# rules\n")
        self.assertEqual([], self.says("Edit `System/rules.md` and `template/System/rules.md`.\n"))
        found = self.says("Edit `Acme Review/Threads/Pricing/Pricing.md`.\n")
        self.assertTrue(any(WALL_MESSAGE in m or "leads into" in m for m in self.refused(found)), found)
        # A file git ignores in a walled project is still that project's: a path to it is refused.
        write(self.work / ".gitignore", "Acme Review/Repo/\nHarbour/Private/\n")
        write(self.work / "Harbour" / "Harbour.md", project_hub("Work", "Harbour", "acme"))
        write(self.work / "Harbour" / "Private" / "deal-terms.md", "# terms\n")
        for text in ("Edit `Zones/Work/Harbour/Private/deal-terms.md`.\n",):
            found = self.says(text)
            self.assertTrue(any(WALL_MESSAGE in m for m in self.refused(found)), (text, found))


class HubsAreNotRefusedForWhatTheyShareTest(unittest.TestCase):
    """#465: a project hub is not refused for its own zone name, for the wording hubs made from one template share,
    or for a relative path of its own."""

    CONTEXT_ZONE = ("| Work | Client work | | walled |\n| Cedar | A company's affairs and its clients | | walled |")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        ctx = self.root / "System" / "context.md"
        text = ctx.read_text(encoding="utf-8").replace("| Work | Client work | | walled |", self.CONTEXT_ZONE)
        text = text.replace("| Birch & Co |", "| Cedar | The company itself | Cedar | `cedar` | yes | |\n| Maple Ltd | A client | Cedar | `maple` | yes | |\n| Birch & Co |", 1)
        ctx.write_text(text, encoding="utf-8")
        self.cedar = self.root / "Zones" / "Cedar"
        self.hub = self.cedar / "Maple" / "Maple.md"

    def hub_says(self, hub, text):
        write(hub, text)
        ws = check.discover(self.root)
        project = hub.parent
        found = check.walls_for_file(ws, project, {"maple"}, hub, text)
        return [f.message for f in found if f.severity == "error" and f.check == "walls"]

    def test_the_zone_key_is_structure_and_the_same_name_in_prose_is_not(self):
        text = project_hub("Cedar", "Maple", "maple")
        self.assertEqual([], self.hub_says(self.hub, text))
        found = self.hub_says(self.hub, text + "\nCedar asked for the figures.\n")
        self.assertTrue(any("names Cedar" in m for m in found), found)

    def test_wording_that_hubs_share_with_a_shipped_template_is_common(self):
        template = "\n## Contents\n\n| Folder | Holds |\n|---|---|\n| `Sources/` | what the party sent, kept as received |\n| `Notes/` | working notes of the team |\n"
        write(self.root / "System" / "templates" / "project" / "{{PROJECT}}.md", "# {{PROJECT}}\n" + template)
        for name, party in (("Maple", "maple"), ("Elm", "cedar"), ("Fir", "acme")):
            write(self.cedar / name / (name + ".md"), project_hub("Cedar", name, party) + template)
        ws = check.discover(self.root)
        for name, party in (("Maple", "maple"), ("Elm", "cedar")):
            hub = self.cedar / name / (name + ".md")
            found = check.walls_for_file(ws, hub.parent, {party}, hub, hub.read_text(encoding="utf-8"))
            self.assertEqual([], [f.message for f in found if f.severity == "error"], name)

    def test_a_sentence_pasted_into_other_projects_is_never_common(self):
        leak = "\nThe lender wants the amended schedule before the quarter closes, so hold the draft.\n"
        for name, party in (("Elm", "cedar"), ("Fir", "acme"), ("Oak", "birch")):
            write(self.cedar / name / (name + ".md"), project_hub("Cedar", name, party) + leak)
        found = self.hub_says(self.hub, project_hub("Cedar", "Maple", "maple") + leak)
        self.assertTrue(any("repeats wording" in m for m in found), found)

    def test_eight_words_copied_from_one_hub_into_another_are_still_refused(self):
        own = project_hub("Cedar", "Elm", "cedar") + "\n### Resume here\n\nThe lender wants the amended schedule before the quarter closes, so hold the draft.\n"
        write(self.cedar / "Elm" / "Elm.md", own)
        copied = project_hub("Cedar", "Maple", "maple") + "\nNote: the lender wants the amended schedule before the quarter closes.\n"
        found = self.hub_says(self.hub, copied)
        self.assertTrue(any("repeats wording" in m for m in found), found)

    def test_a_relative_path_in_the_hub_resolves_in_its_own_project_first(self):
        write(self.cedar / "Maple" / "Papers" / "ledger-brief.docx", "maple brief\n")
        write(self.cedar / "Elm" / "Elm.md", project_hub("Cedar", "Elm", "cedar"))
        write(self.cedar / "Elm" / "Papers" / "ledger-brief.docx", "elm brief\n")
        text = project_hub("Cedar", "Maple", "maple") + "\nThe brief is `Papers/ledger-brief.docx`.\n"
        self.assertEqual([], self.hub_says(self.hub, text))
        note = self.cedar / "Elm" / "Notes.md"
        write(note, "# Notes\n\nSee `../Maple/Papers/ledger-brief.docx`.\n")
        ws = check.discover(self.root)
        found = check.walls_for_file(ws, note.parent, {"cedar"}, note, note.read_text(encoding="utf-8"))
        self.assertTrue([f for f in found if f.severity == "error"], found)


if __name__ == "__main__":
    unittest.main()
