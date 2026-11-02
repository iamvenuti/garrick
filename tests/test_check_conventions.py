"""The checks on Garrick's own conventions: a file that follows what Garrick
documents or writes draws no warning the workspace cannot act on.

    python3 -m unittest discover -s tests -p test_check_conventions.py

A thread may carry a party its hub does not, unless a wall stands between
them; a Knowledge lint report is the knowledge skill's own output; a Resume
here path may lead into another project of the same zone; and a thread note
made by scaffold.py passes the parent-links rule as it is made.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, build_workspace, commit_all, git, project_hub, thread_note, write  # noqa: E402
from test_setup import Installed  # noqa: E402

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"

_spec = importlib.util.spec_from_file_location("garrick_nurture_conventions", str(TOOLS / "nurture.py"))
nurture = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = nurture
_spec.loader.exec_module(nurture)

# A third invented party, with no wall to Acme or Birch: the organisers of a
# trade fair, whose confidence one thread of a project holds.
CEDAR_ROW = "| Cedar Fairs | Organisers of an invented trade fair | Work | `cedar` | |\n"


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        context = self.root / "System" / "context.md"
        text = context.read_text()
        birch = next(l for l in text.splitlines(True) if "`birch`" in l and l.startswith("| Birch"))
        context.write_text(text.replace(birch, birch + CEDAR_ROW, 1))
        self.work = self.root / "Zones" / "Work"
        self.acme = self.work / "Acme Review"
        self.pricing = self.acme / "Threads" / "Pricing" / "Pricing.md"

    def findings(self, name):
        return [f for f in check.run_checks(self.root) if f.check == name]


class TestThreadParty(Case):
    def party(self, value):
        self.pricing.write_text(self.pricing.read_text().replace("party: acme", "party: %s" % value))

    def test_a_party_the_hub_lacks_with_no_wall_passes(self):
        self.party("[acme, cedar]")
        self.assertEqual([], [f.message for f in self.findings("threads")])

    def test_a_thread_of_another_unwalled_party_alone_passes(self):
        self.party("cedar")
        self.assertEqual([], [f.message for f in self.findings("threads")])

    def test_a_party_across_a_wall_still_warns(self):
        self.party("[acme, birch]")
        hits = [f for f in self.findings("threads") if "differs from the project's" in f.message]
        self.assertEqual(1, len(hits))
        self.assertEqual("warning", hits[0].severity)

    def test_a_thread_wholly_across_the_wall_still_warns(self):
        self.party("birch")
        self.assertTrue([f for f in self.findings("threads") if "differs from the project's" in f.message])

    def test_an_unwalled_party_beside_a_walled_one_still_warns(self):
        self.party("[birch, cedar]")
        self.assertTrue([f for f in self.findings("threads") if "differs from the project's" in f.message])


class TestNurtureThreadParty(Case):
    """Nurture never proposes the hub's party for a thread, and never a party
    across a wall: a walled finding is named as a wall, and nothing else
    about a thread's party reaches it."""

    def items(self):
        ctx = nurture.Ctx(self.root)
        return [nurture.sort_item(ctx, i) for i in nurture.from_check(ctx) if i.check == "threads"]

    def test_an_unwalled_thread_party_is_not_asked_about(self):
        self.pricing.write_text(self.pricing.read_text().replace("party: acme", "party: [acme, cedar]"))
        self.assertEqual([], [(i.kind, i.question, i.proposal) for i in self.items()])

    def test_a_walled_thread_party_is_a_wall_with_no_proposal(self):
        self.pricing.write_text(self.pricing.read_text().replace("party: acme", "party: [acme, birch]"))
        items = self.items()
        self.assertEqual(["wall"], [i.kind for i in items])
        self.assertEqual("", items[0].proposal)
        self.assertEqual("", items[0].message)       # the wall is named, the material never repeated

    def test_a_finding_handed_in_proposes_no_party(self):
        # A finding from an older check, or one stored before this one: still
        # asked, but the hub's party is never offered as the answer.
        ctx = nurture.Ctx(self.root)
        item = nurture.sort_item(ctx, nurture.Item(
            "check", "threads", "Zones/Work/Acme Review/Threads/Pricing/Pricing.md",
            "`party` acme, cedar differs from the project's acme"))
        self.assertEqual("attribution", item.kind)
        self.assertEqual("", item.proposal)


BRIEF = "The board plans to close the northern plant by the end of the third quarter and move the pump line south.\n"


class TestThreadsWalledFromEachOther(Case):
    """A project for cedar with one thread for acme and one for birch, walled
    from each other and from neither the hub: the threads check says so, and
    wording carried from one thread's notes into the other's is refused, by
    the full check and by the commit check alike."""

    def setUp(self):
        super().setUp()
        self.fair = self.work / "Trade Fair"
        write(self.fair / "Trade Fair.md", project_hub("Work", "Trade Fair", "cedar", ["Stand A", "Stand B", "Stand C"]))
        write(self.fair / "Threads" / "Stand A" / "Stand A.md", thread_note("Trade Fair", "Stand A", "acme"))
        write(self.fair / "Threads" / "Stand B" / "Stand B.md", thread_note("Trade Fair", "Stand B", "birch"))
        write(self.fair / "Threads" / "Stand C" / "Stand C.md", thread_note("Trade Fair", "Stand C", "cedar"))
        write(self.fair / "Threads" / "Stand B" / "Brief.md", '---\nparent: "[[Stand B]]"\n---\n\n' + BRIEF)
        self.notes = self.fair / "Threads" / "Stand A" / "Notes.md"

    def quotes(self, found):
        return [f for f in found if f.check == "walls" and f.path.endswith("Stand A/Notes.md")
                and "repeats wording from" in f.message]

    def test_the_threads_check_names_the_wall(self):
        hits = [f for f in self.findings("threads") if "walled from thread Stand A's" in f.message]
        self.assertEqual(["Zones/Work/Trade Fair/Threads/Stand B/Stand B.md"], [f.path for f in hits])
        self.assertIn("a wall stands between acme and birch", hits[0].message)

    def test_wording_copied_between_the_threads_is_refused(self):
        write(self.notes, '---\nparent: "[[Stand A]]"\n---\n\n' + BRIEF)
        hits = self.quotes(check.run_checks(self.root))
        self.assertEqual(1, len(hits))
        self.assertEqual("error", hits[0].severity)
        self.assertIn("Stand B/Brief.md", hits[0].message)

    def test_the_commit_check_refuses_it_too(self):
        if not HAVE_GIT:
            self.skipTest("git is not installed")
        shutil.rmtree(self.work / ".git")
        git(self.work, "init", "-q")
        commit_all(self.work, "start")
        write(self.notes, '---\nparent: "[[Stand A]]"\n---\n\n' + BRIEF)
        git(self.work, "add", "-A")
        hits = self.quotes(check.run_checks(self.root, walls_only=True, staged=self.work))
        self.assertEqual(["error"], [f.severity for f in hits])

    def test_wording_shared_with_an_unwalled_thread_of_the_project_is_not_refused(self):
        write(self.fair / "Threads" / "Stand C" / "Notes.md", '---\nparent: "[[Stand C]]"\n---\n\n' + BRIEF)
        write(self.fair / "Threads" / "Stand B" / "Brief.md", '---\nparent: "[[Stand B]]"\n---\n\nNothing here.\n')
        write(self.notes, '---\nparent: "[[Stand A]]"\n---\n\n' + BRIEF)
        self.assertEqual([], self.quotes(check.run_checks(self.root)))

    def test_nurture_names_it_as_a_wall(self):
        ctx = nurture.Ctx(self.root)
        items = [nurture.sort_item(ctx, i) for i in nurture.from_check(ctx) if i.check == "threads"]
        self.assertEqual([("wall", "acme and birch", "")], [(i.kind, i.wall, i.message) for i in items])


class TestThreadHoldingBothSides(Case):
    def test_a_thread_naming_both_sides_of_a_wall_warns_under_any_hub(self):
        fair = self.work / "Trade Fair"
        write(fair / "Trade Fair.md", project_hub("Work", "Trade Fair", "cedar", ["Stand"]))
        write(fair / "Threads" / "Stand" / "Stand.md", thread_note("Trade Fair", "Stand", "[acme, birch]"))
        hits = [f for f in self.findings("threads") if f.path.endswith("Stand/Stand.md")]
        self.assertEqual(1, len(hits))
        self.assertIn("holds both sides of a wall; a wall stands between acme and birch", hits[0].message)


class TestKnowledgeLintReport(Case):
    def setUp(self):
        super().setUp()
        self.lint = self.root / "Wikis" / "Knowledge" / "wiki" / "lint"

    def test_a_lint_report_as_the_skill_writes_it_passes(self):
        write(self.lint / "2026-03-14.md",
              "---\ntitle: Library lint, 14 March 2026\ntype: report\ndate: 2026-03-14\n---\n\n"
              "## Contradictions\n\nNothing found.\n")
        self.assertEqual([], [f.message for f in self.findings("knowledge")])

    def test_a_report_outside_lint_is_still_an_unknown_kind(self):
        write(self.root / "Wikis" / "Knowledge" / "wiki" / "concepts" / "2026-03-14.md",
              "---\ntitle: A report\ntype: report\n---\n\nText.\n")
        self.assertTrue([f for f in self.findings("knowledge") if "`type: report` is not a kind" in f.message])

    def test_another_type_in_lint_is_still_an_unknown_kind(self):
        write(self.lint / "2026-03-14.md", "---\ntitle: Odd\ntype: memo\n---\n\nText.\n")
        self.assertTrue([f for f in self.findings("knowledge") if "`type: memo` is not a kind" in f.message])

    def test_a_lint_report_still_carries_no_party(self):
        write(self.lint / "2026-03-14.md", "---\ntitle: Lint\ntype: report\nparties: [acme]\n---\n\nText.\n")
        self.assertTrue([f for f in self.findings("knowledge") if f.message.startswith("carries ")])


class TestResumeSiblingProject(Case):
    def setUp(self):
        super().setUp()
        self.launch = self.work / "Acme Launch"
        write(self.launch / "Acme Launch.md", project_hub("Work", "Acme Launch", "acme", ["Deck"]))
        write(self.launch / "Threads" / "Deck" / "Deck.md", thread_note("Acme Launch", "Deck", "acme"))
        write(self.launch / "Deliverables" / "260301 - Launch deck.pptx", "deck")
        write(self.launch / "Threads" / "Deck" / "Deliverables" / "260302 - Speaker notes.md", "# Notes\n")

    def resume(self, row):
        self.pricing.write_text(self.pricing.read_text() + "\n| | |\n|---|---|\n| Keep in mind | %s |\n" % row)

    def unfound(self):
        return [f.message for f in self.findings("resume") if "is not there" in f.message]

    def test_a_path_in_a_sibling_project_is_found(self):
        self.resume("the next delivery starts from the other project's `Deliverables/260301 - Launch deck.pptx`")
        self.assertEqual([], self.unfound())

    def test_a_path_in_a_sibling_projects_thread_is_found(self):
        self.resume("`Deliverables/260302 - Speaker notes.md`")
        self.assertEqual([], self.unfound())

    def test_a_path_found_nowhere_is_still_reported(self):
        self.resume("`Deliverables/260301 - Launch deck-v2.pptx`")
        self.assertEqual(["Resume here names `Deliverables/260301 - Launch deck-v2.pptx`, which is not there"],
                         self.unfound())

    def test_a_project_in_another_zone_is_never_looked_in(self):
        personal = self.root / "Zones" / "Personal" / "Home"
        write(personal / "Home.md", project_hub("Personal", "Home", "acme"))
        write(personal / "Deliverables" / "260303 - Budget.md", "# Budget\n")
        self.resume("`Deliverables/260303 - Budget.md`")
        self.assertEqual(["Resume here names `Deliverables/260303 - Budget.md`, which is not there"], self.unfound())

    def test_a_project_across_a_wall_is_never_looked_in(self):
        write(self.work / "Birch Entry" / "Deliverables" / "260304 - Entry plan.md", "# Plan\n")
        self.resume("`Deliverables/260304 - Entry plan.md`")
        self.assertEqual(["Resume here names `Deliverables/260304 - Entry plan.md`, which is not there"],
                         self.unfound())


class TestResumeSiblingGuards(Case):
    """A sibling project is searched only where the note may draw: never
    through a link that leads out of the sibling's folder, and never into a
    sibling's thread written for a party walled from the note's."""

    def setUp(self):
        super().setUp()
        self.launch = self.work / "Acme Launch"
        write(self.launch / "Acme Launch.md", project_hub("Work", "Acme Launch", "acme", ["Deck"]))
        write(self.launch / "Threads" / "Deck" / "Deck.md", thread_note("Acme Launch", "Deck", "acme"))
        write(self.launch / "Deliverables" / "260301 - Launch deck.md", "# Deck\n")
        write(self.work / "Birch Entry" / "Deliverables" / "260304 - Entry plan.md", "# Plan\n")
        self.fair = self.work / "Trade Fair"
        write(self.fair / "Trade Fair.md", project_hub("Work", "Trade Fair", "cedar", ["Stand B"]))
        write(self.fair / "Threads" / "Stand B" / "Stand B.md", thread_note("Trade Fair", "Stand B", "birch"))
        write(self.fair / "Threads" / "Stand B" / "Deliverables" / "260305 - Stand plan.md", "# Plan\n")
        self.home = self.root / "Zones" / "Personal" / "Home"
        write(self.home / "Home.md", project_hub("Personal", "Home", "acme"))
        write(self.home / "Deliverables" / "260303 - Budget.md", "# Budget\n")

    def unfound(self, note, row):
        note.write_text(note.read_text() + "\n| | |\n|---|---|\n| Keep in mind | %s |\n" % row)
        return [f.message for f in check.run_checks(self.root)
                if f.check == "resume" and f.path.endswith(note.name) and "is not there" in f.message]

    def test_a_link_into_a_walled_project_confirms_nothing(self):
        os.symlink(self.work / "Birch Entry" / "Deliverables", self.launch / "Linked")
        self.assertEqual(["Resume here names `Linked/260304 - Entry plan.md`, which is not there"],
                         self.unfound(self.pricing, "`Linked/260304 - Entry plan.md`"))

    def test_a_link_into_another_zone_confirms_nothing(self):
        os.symlink(self.home / "Deliverables", self.launch / "Linked")
        self.assertEqual(["Resume here names `Linked/260303 - Budget.md`, which is not there"],
                         self.unfound(self.pricing, "`Linked/260303 - Budget.md`"))

    def test_a_link_inside_the_sibling_still_counts(self):
        os.symlink(self.launch / "Deliverables", self.launch / "Linked")
        self.assertEqual([], self.unfound(self.pricing, "`Linked/260301 - Launch deck.md`"))

    def test_a_siblings_thread_walled_from_the_note_is_not_searched(self):
        self.assertEqual(["Resume here names `Deliverables/260305 - Stand plan.md`, which is not there",
                          "Resume here names `Threads/Stand B/Deliverables/260305 - Stand plan.md`, which is not there"],
                         self.unfound(self.pricing, "`Deliverables/260305 - Stand plan.md` and "
                                                    "`Threads/Stand B/Deliverables/260305 - Stand plan.md`"))

    def test_the_notes_own_thread_party_is_held_against_the_sibling(self):
        # Stand B is for birch under a cedar hub: the acme project is walled from its note.
        note = self.fair / "Threads" / "Stand B" / "Stand B.md"
        self.assertEqual(["Resume here names `Deliverables/260301 - Launch deck.md`, which is not there"],
                         self.unfound(note, "`Deliverables/260301 - Launch deck.md`"))

    def test_the_sibling_bases_are_worked_out_once_per_note(self):
        with mock.patch.object(check, "sibling_bases", wraps=check.sibling_bases) as spy:
            self.unfound(self.pricing, "`Deliverables/gone one.md` and `Deliverables/gone two.md`")
        notes = [c.args[2] for c in spy.call_args_list]
        self.assertEqual(len(notes), len(set(notes)))
        self.assertIn(self.pricing, notes)


class TestThreadProjectLink(Case):
    """A thread note's `project:` links its hub, so the parent-links rule
    asks it for no `parent:` as well."""

    def setUp(self):
        super().setUp()
        write(self.root / "System" / "garrick-checks.json", json.dumps({"parent-links": ["Work"]}))

    def missing(self):
        return sorted(f.path for f in self.findings("links") if "no `parent:`" in f.message)

    def test_a_thread_note_with_project_only_passes(self):
        self.assertNotIn("Zones/Work/Acme Review/Threads/Pricing/Pricing.md", self.missing())

    def test_a_path_to_the_hub_counts_too(self):
        self.pricing.write_text(self.pricing.read_text().replace(
            'project: "[[Acme Review]]"', 'project: "[[Zones/Work/Acme Review/Acme Review]]"'))
        self.assertNotIn("Zones/Work/Acme Review/Threads/Pricing/Pricing.md", self.missing())

    def test_a_hub_of_the_same_name_in_another_zone_is_not_its_hub(self):
        other = self.root / "Zones" / "Personal" / "Acme Review"
        write(other / "Acme Review.md", project_hub("Personal", "Acme Review", "acme"))
        for link in ("Zones/Personal/Acme Review/Acme Review", "Personal/Acme Review/Acme Review"):
            self.pricing.write_text(self.pricing.read_text().replace(
                self.pricing.read_text().split('project: "[[', 1)[1].split("]]", 1)[0], link, 1))
            self.assertIn("Zones/Work/Acme Review/Threads/Pricing/Pricing.md", self.missing(), link)

    def test_links_hub_takes_only_the_three_forms(self):
        for link, ok in (("Acme Review", True), ("Acme Review/Acme Review", True),
                         ("Zones/Work/Acme Review/Acme Review", True), ("Zones/Work/Acme Review/Acme Review.md", True),
                         ("Zones/Personal/Acme Review/Acme Review", False), ("Work/Acme Review/Acme Review", False),
                         ("Old/Acme Review/Acme Review", False), ("Birch Entry", False)):
            self.assertEqual(ok, check.links_hub('project: "[[%s]]"' % link, "Work", "Acme Review"), link)

    def test_a_project_link_elsewhere_is_still_asked(self):
        self.pricing.write_text(self.pricing.read_text().replace('project: "[[Acme Review]]"', 'project: "[[Birch Entry]]"'))
        self.assertIn("Zones/Work/Acme Review/Threads/Pricing/Pricing.md", self.missing())

    def test_a_working_note_with_project_only_is_still_asked(self):
        note = self.acme / "Threads" / "Pricing" / "Rates.md"
        write(note, '---\nproject: "[[Acme Review]]"\n---\n\n# Rates\n')
        self.assertIn("Zones/Work/Acme Review/Threads/Pricing/Rates.md", self.missing())


class TestScaffoldedThread(Installed):
    """A thread made by `scaffold.py project` or `scaffold.py thread` passes
    the links check the moment it is made, and a project's rename carries its
    `parent:` with it."""

    def setUp(self):
        super().setUp()
        self.work = self.root / "Zones" / "Work"
        write(self.root / "System" / "garrick-checks.json", json.dumps({"parent-links": ["Work"]}))
        for args in (("project", "--zone", "Work", "--name", "Acme", "--party", "acme", "--thread", "Pricing"),
                     ("thread", "--zone", "Work", "--project", "Acme", "--name", "Freight")):
            r = self.run_tool("scaffold.py", *args)
            self.assertEqual(0, r.returncode, r.stderr)

    def test_both_thread_notes_carry_parent_and_pass(self):
        for thread in ("Pricing", "Freight"):
            note = (self.work / "Acme" / "Threads" / thread / (thread + ".md")).read_text()
            self.assertIn('project: "[[Acme]]"\nparent: "[[Acme]]"\n', note)
        found = [f for f in check.run_checks(self.root) if f.check == "links" and "Threads/" in f.path]
        self.assertEqual([], [(f.path, f.message) for f in found])

    def test_a_project_rename_carries_parent(self):
        for args in (("add", "-A"), ("commit", "-q", "-m", "Acme set up")):
            g = subprocess.run(["git", *args], cwd=str(self.work), capture_output=True, text=True, env=self.env)
            self.assertEqual(0, g.returncode, g.stderr)
        r = self.run_tool("scaffold.py", "rename", "--zone", "Work", "--project", "Acme", "--to", "Apex")
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)
        note = (self.work / "Apex" / "Threads" / "Freight" / "Freight.md").read_text()
        self.assertIn('project: "[[Apex]]"\nparent: "[[Apex]]"\n', note)


if __name__ == "__main__":
    unittest.main()
