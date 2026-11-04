"""A Meetings person page links the entity page of its party (#319).

    cd tests && python3 -m unittest test_person_organisation

An entity page in Meetings names the party it stands for, `party: acme`, and
a person page of that party links it as `organisation:`. ingest.py writes the
link on a new page, check.py warns where it is missing, wrong or doubled,
and nurture.py offers it for pages written before, on a yes, never with
nobody watching. A person page is read on every side of a wall, so the link
carries identity alone, and a name the People table places on both sides of
a wall gets none. Every workspace here is built in a temporary folder.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
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

import fixtures  # noqa: E402  (puts the tools folder on sys.path)
from fixtures import GIT_ENV, HAVE_GIT, build_workspace, git, write  # noqa: E402

import check  # noqa: E402
import garrick_lib  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
INGEST = REPO / "template" / "System" / "skills" / "meetings" / "ingest.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ingest = load("garrick_meetings_ingest_319", INGEST)
nurture = load("garrick_nurture_319", TOOLS / "nurture.py")

# Cedar is a party no wall divides from Acme; Acme and Birch are walled, as in
# the shared fixture. Rowan Blake is known under both Acme and Birch: one
# name, two hats, one person page between them.
CONTEXT = fixtures.CONTEXT.replace(
    "| Birch & Co | Client.",
    "| Cedar Ltd | Supplier to Acme | Work | `cedar` | cedarltd.example |\n| Birch & Co | Client.",
).replace(
    "| Theo Marsh | `birch` | Managing partner |",
    "| Theo Marsh | `birch` | Managing partner |\n"
    "| Rowan Blake | `acme` | Adviser |\n"
    "| Rowan Blake | `birch` | Adviser |\n"
    "| Ines Varga | `acme` | Buyer |\n"
    "| Ines Varga | `cedar` | Account lead |\n"
    "| Aurélien Moreau | `acme` | Counsel |\n"
    "| Aurélien Moreau | `birch` | Counsel |\n"
    "| Søren Kjær | `acme` | Engineer |\n"
    "| Søren Kjær | `birch` | Engineer; signs as S. K. Lund |\n"
    "| Kit \"Kestrel\" Avery | `acme` | Analyst |\n"
    "| Kit \"Kestrel\" Avery | `birch` | Analyst |\n",
).replace("| dana whitlaw | Dana Whitlock |", "| dana whitlaw | Dana Whitlock |\n| ro blake, rowie | Rowan Blake |")


def entity(party: str, title: str = "Acme Corp", extra: str = "") -> str:
    party_line = "party: %s\n" % party if party else ""
    return ("---\ntitle: %s\ntype: entity\n%s%screated: 2026-03-10\nupdated: 2026-03-10\n---\n\n# %s\n\nAn organisation.\n"
            % (title, party_line, extra, title))


def person(name: str, party: str, organisation: str = "") -> str:
    org = 'organisation: "%s"\n' % organisation if organisation else ""
    return ("---\ntitle: %s\ntype: person\nparty: %s\n%screated: 2026-03-10\nupdated: 2026-03-10\n---\n\n# %s\n\n"
            "Someone at a party.\n" % (name, party, org, name))


class Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        write(self.root / "System" / "context.md", CONTEXT)
        self.meetings = self.root / "Wikis" / "Meetings"
        self.entities = self.meetings / "wiki" / "entities"
        self.people = self.meetings / "wiki" / "people"
        self.context = garrick_lib.load_context(self.root)

    def link(self, name: str, party) -> str:
        return garrick_lib.organisation_link(self.root, self.context, name, party)


# ---------------------------------------------------------------------------
# The rule: garrick_lib.organisation_link
# ---------------------------------------------------------------------------

class LinkRuleTest(Workspace):
    def test_one_entity_page_for_the_party_is_linked(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        self.assertEqual("[[wiki/entities/acme-corp]]", self.link("Dana Whitlock", "acme"))
        self.assertEqual("[[wiki/entities/acme-corp]]", self.link("dana  whitlock", "`acme`"))

    def test_no_entity_page_no_link(self):
        self.assertEqual("", self.link("Dana Whitlock", "acme"))
        write(self.entities / "birch-co.md", entity("birch", "Birch & Co"))
        self.assertEqual("", self.link("Dana Whitlock", "acme"))

    def test_two_entity_pages_for_one_party_link_neither(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.entities / "acme-holdings.md", entity("acme", "Acme Holdings"))
        self.assertEqual("", self.link("Dana Whitlock", "acme"))

    def test_an_entity_page_naming_two_parties_or_none_stands_for_neither(self):
        write(self.entities / "acme-corp.md", entity("[acme, cedar]"))
        write(self.entities / "nobody.md", entity("none", "Nobody"))
        self.assertEqual({}, garrick_lib.party_entities(self.root))
        self.assertEqual("", self.link("Dana Whitlock", "acme"))

    def test_an_entity_page_reached_through_a_link_is_passed_over(self):
        outside = write(Path(self._tmp.name) / "elsewhere" / "acme.md", entity("acme"))
        self.entities.mkdir(parents=True)
        os.symlink(str(outside), str(self.entities / "acme-corp.md"))
        self.assertEqual("", self.link("Dana Whitlock", "acme"))

    def test_a_page_with_no_one_known_party_links_nothing(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.entities / "nobody.md", entity("none", "Nobody"))
        for party in ("", None, "none", "fernway", ["acme", "cedar"], ["acme", "birch"]):
            self.assertEqual("", self.link("Dana Whitlock", party), party)

    def test_a_name_on_both_sides_of_a_wall_links_neither_hat(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.entities / "birch-co.md", entity("birch", "Birch & Co"))
        self.assertEqual("", self.link("Rowan Blake", "acme"))
        self.assertEqual("", self.link("Rowan Blake", "birch"))

    def test_both_hats_are_found_by_any_name_the_page_goes_by(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        self.assertEqual("", self.link("ROWAN-blake", "acme"))
        self.assertEqual("", self.link(("R. B.", "rowan-blake"), "acme"))     # a title written otherwise, its file name
        self.assertEqual("[[wiki/entities/acme-corp]]", self.link(("R. B.",), "acme"))

    def test_spellings_of_a_two_hat_name_all_find_both_hats(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        for name in ("Rowan Bláke", "Rowan-Blake", "\uff32owan Blake", "Rowan\u200bBlake", "Rowan\xa0Blake",
                     "Rowan J. Blake", "Aurelien Moreau", "Aurélien Moreau", "AURÉLIEN MOREAU",
                     "Soren Kjaer", "Søren Kjær", "Kit Avery", "Kestrel", 'Kit "Kestrel" Avery',
                     "Ro Blake", "rowie", "S. K. Lund"):
            self.assertEqual("", self.link(name, "acme"), name)
        # A letter from another script that looks Latin leaves the surname's other letters: read as theirs (#340).
        self.assertEqual("", self.link("Row\u0430n Blake", "acme"))

    def test_a_short_form_of_a_two_hat_name_finds_both_hats(self):
        """Fail closed on a name written short: a People row of one word
        meets a page name opening with it, `Surname, First` meets `First
        Surname`, and an initial with a surname, or a first name with an
        initial, meets the full name. Two full names never meet."""
        write(self.root / "System" / "context.md", CONTEXT.replace(
            "| Theo Marsh | `birch` | Managing partner |",
            "| Theo Marsh | `birch` | Managing partner |\n| Eli | `acme` | |\n| Eli | `birch` | |\n"
            "| Dana Whitlock | `birch` | Board observer |"))
        self.context = garrick_lib.load_context(self.root)
        write(self.entities / "acme-corp.md", entity("acme"))
        for names in (("Eli Cohen", "eli-cohen"), ("Eli", "eli"), ("Dana Whitlock", "dana-whitlock"),
                      ("Whitlock, Dana", "whitlock-dana"), ("D. Whitlock", "d-whitlock"), ("Dana W.", "dana-w"),
                      ("ELI COHEN",), ("Whitlock, Dana",), ("D. Whitlock",), ("Dana W.",), ("Rowan B.",), ("R. Blake",),
                      ("Blake, Rowan",)):
            self.assertEqual("", self.link(names, "acme"), names)
        for names in (("Elias Moor",), ("Dana Whitmore",), ("Theo Cohen",)):
            self.assertEqual("[[wiki/entities/acme-corp]]", self.link(names, "acme"), names)
        self.assertEqual({"acme", "birch"}, garrick_lib.people_parties(self.context, "Eli Cohen"))
        # Sharing a surname word with a two-hat person is enough (#340): asked about, not linked.
        self.assertEqual("", self.link(("David Whitlock",), "acme"))
        self.assertEqual({"acme", "birch"}, garrick_lib.people_parties(self.context, "David Whitlock"))

    def test_a_name_with_two_parties_no_wall_divides_links_its_own(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.entities / "cedar-ltd.md", entity("cedar", "Cedar Ltd"))
        self.assertEqual("[[wiki/entities/acme-corp]]", self.link("Ines Varga", "acme"))
        self.assertEqual("[[wiki/entities/cedar-ltd]]", self.link("Ines Varga", "cedar"))

    def test_a_page_whose_party_the_people_table_does_not_give_links_nothing(self):
        write(self.entities / "birch-co.md", entity("birch", "Birch & Co"))
        self.assertEqual("", self.link("Dana Whitlock", "birch"))        # People has Dana under acme alone
        self.assertEqual("[[wiki/entities/birch-co]]", self.link("Pat Newcomer", "birch"))   # not in People yet


# ---------------------------------------------------------------------------
# ingest.py person
# ---------------------------------------------------------------------------

class IngestPersonTest(Workspace):
    def run_person(self, name: str, party: str):
        return subprocess.run([sys.executable, str(INGEST), "--root", str(self.root), "--today", "2026-03-10",
                               "person", "--name", name, "--party", party], capture_output=True, text=True)

    def test_with_an_entity_page_for_the_party_it_writes_the_link(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        r = self.run_person("Mira Holt", "acme")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("created\tWikis/Meetings/wiki/people/mira-holt.md", r.stdout.strip())
        self.assertEqual(
            '---\ntitle: Mira Holt\ntype: person\nparty: acme\norganisation: "[[wiki/entities/acme-corp]]"\n'
            "created: 2026-03-10\nupdated: 2026-03-10\n---\n\n# Mira Holt\n\n"
            "<Who they are, and which party, in a sentence.>\n",
            (self.people / "mira-holt.md").read_text())

    def test_without_one_it_writes_none(self):
        r = self.run_person("Mira Holt", "acme")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertNotIn("organisation", (self.people / "mira-holt.md").read_text())

    def test_a_name_on_both_sides_of_a_wall_gets_no_link(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.entities / "birch-co.md", entity("birch", "Birch & Co"))
        path, created = ingest.ensure_person(self.root, "Rowan Blake", "acme", "2026-03-10")
        self.assertTrue(created)
        text = path.read_text()
        self.assertNotIn("organisation", text)
        self.assertNotIn("birch", text)

    def test_two_entity_pages_for_the_party_get_no_link(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.entities / "acme-holdings.md", entity("acme", "Acme Holdings"))
        path, _ = ingest.ensure_person(self.root, "Mira Holt", "acme", "2026-03-10")
        self.assertNotIn("organisation", path.read_text())

    def test_an_existing_page_is_never_touched(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        before = (self.people / "dana-whitlock.md").read_text()
        _, created = ingest.ensure_person(self.root, "Dana Whitlock", "acme", "2026-03-11")
        self.assertFalse(created)
        self.assertEqual(before, (self.people / "dana-whitlock.md").read_text())

    def test_the_link_carries_identity_alone(self):
        # The entity page lists meetings; none of it, nor the entity's own text, reaches the person page.
        write(self.entities / "acme-corp.md",
              entity("acme", extra='sources:\n  - "[[wiki/sources/260310-acme-kickoff]]"\n').replace(
                  "An organisation.", "Renewal talks with Birch in view."))
        path, _ = ingest.ensure_person(self.root, "Mira Holt", "acme", "2026-03-10")
        text = path.read_text()
        self.assertIn('organisation: "[[wiki/entities/acme-corp]]"', text)
        for leak in ("260310", "kickoff", "Renewal", "Birch", "birch", "sources"):
            self.assertNotIn(leak, text)
        links = [l for l in text.splitlines() if "[[" in l]
        self.assertEqual(['organisation: "[[wiki/entities/acme-corp]]"'], links)


# ---------------------------------------------------------------------------
# check.py
# ---------------------------------------------------------------------------

class CheckTest(Workspace):
    def findings(self, name: str):
        return [f for f in check.run_checks(self.root) if f.check == name]

    def test_a_clean_page_and_its_entity_page_find_nothing(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.people / "dana-whitlock.md", person("Dana Whitlock", "acme", "[[wiki/entities/acme-corp]]"))
        self.assertEqual([], self.findings("people"))
        self.assertEqual([], [f for f in self.findings("meetings") if "entities" in f.path])

    def test_a_page_missing_the_link_is_warned_with_the_link_it_would_get(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        found = [f for f in self.findings("people") if f.path.endswith("dana-whitlock.md")]
        self.assertEqual(1, len(found), found)
        self.assertEqual("warning", found[0].severity)
        self.assertEqual("%s, [[wiki/entities/acme-corp]]" % check.NO_ORGANISATION, found[0].message)

    def test_no_warning_where_no_link_is_due(self):
        write(self.people / "rowan-blake.md", person("Rowan Blake", "acme"))
        write(self.entities / "birch-co.md", entity("birch", "Birch & Co"))
        self.assertEqual([], self.findings("people"))                     # no acme entity page
        write(self.entities / "acme-corp.md", entity("acme"))
        found = self.findings("people")
        self.assertEqual(["Wikis/Meetings/wiki/people/dana-whitlock.md"], [f.path for f in found])  # Rowan: both hats

    def test_two_entity_pages_with_one_party_are_warned(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.entities / "acme-holdings.md", entity("acme", "Acme Holdings"))
        found = [f for f in self.findings("meetings") if "entities" in f.path]
        self.assertEqual({"Wikis/Meetings/wiki/entities/acme-corp.md", "Wikis/Meetings/wiki/entities/acme-holdings.md"},
                         {f.path for f in found})
        for f in found:
            self.assertEqual("warning", f.severity)
            self.assertIn("names party acme, and so does", f.message)
        # So Dana is owed no link by her party; her first line names Acme Corp, which one page goes by (#330).
        self.assertEqual(["%s, [[wiki/entities/acme-corp]]" % check.NO_EMPLOYER],
                         [f.message for f in self.findings("people")])

    def test_an_entity_page_naming_an_unknown_party_is_warned(self):
        write(self.entities / "fernway.md", entity("fernway", "Fernway"))
        found = [f for f in self.findings("meetings") if "entities" in f.path]
        self.assertEqual(1, len(found))
        self.assertIn("party `fernway` is not a tag in the Parties table", found[0].message)

    def test_a_link_to_an_entity_page_that_is_not_there(self):
        write(self.people / "dana-whitlock.md", person("Dana Whitlock", "acme", "[[wiki/entities/acme-corp]]"))
        found = self.findings("people")
        self.assertEqual(1, len(found))
        self.assertIn("leads to no entity page", found[0].message)

    def test_a_link_to_another_partys_entity_page_is_where_they_work(self):
        """#330: `organisation:` names where the person works, whatever the
        page's party, so another party's entity page no wall divides from
        it is no finding."""
        write(self.entities / "cedar-ltd.md", entity("cedar", "Cedar Ltd"))
        write(self.people / "dana-whitlock.md", person("Dana Whitlock", "acme", "[[wiki/entities/cedar-ltd]]"))
        self.assertEqual([], self.findings("people"))
        self.assertEqual([], self.findings("walls"))

    def test_a_link_across_a_wall_is_a_wall_finding(self):
        write(self.entities / "birch-co.md", entity("birch", "Birch & Co"))
        write(self.people / "dana-whitlock.md", person("Dana Whitlock", "acme", "[[wiki/entities/birch-co]]"))
        self.assertEqual([], self.findings("people"))                     # said once, by the walls check
        found = self.findings("walls")
        self.assertEqual(["Wikis/Meetings/wiki/people/dana-whitlock.md"], [f.path for f in found])
        self.assertEqual("error", found[0].severity)
        self.assertTrue(found[0].message.endswith("a wall stands between acme and birch"), found[0].message)
        item = nurture.sort_item(nurture.Ctx(self.root), nurture.check_items(vars(found[0]))[0])
        self.assertEqual("wall", item.kind)
        self.assertEqual("acme and birch", item.wall)

    def test_a_link_on_a_page_both_hats_share_is_a_wall_finding(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.people / "rowan-blake.md", person("Rowan Blake", "acme", "[[wiki/entities/acme-corp]]"))
        found = self.findings("walls")
        self.assertEqual(["Wikis/Meetings/wiki/people/rowan-blake.md"], [f.path for f in found])
        rowan = found[0]
        self.assertTrue(rowan.message.endswith("a wall stands between acme and birch"), rowan.message)

    def test_a_link_on_a_page_a_short_name_puts_on_both_sides_is_a_wall_finding(self):
        write(self.root / "System" / "context.md", CONTEXT.replace(
            "| Theo Marsh | `birch` | Managing partner |",
            "| Theo Marsh | `birch` | Managing partner |\n| Eli | `acme` | |\n| Eli | `birch` | |"))
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.people / "eli-cohen.md", person("Eli Cohen", "acme", "[[wiki/entities/acme-corp]]"))
        write(self.people / "blake-rowan.md", person("Blake, Rowan", "acme", "[[wiki/entities/acme-corp]]"))
        found = self.findings("walls")
        self.assertEqual(["Wikis/Meetings/wiki/people/blake-rowan.md", "Wikis/Meetings/wiki/people/eli-cohen.md"],
                         sorted(f.path for f in found))
        for f in found:
            self.assertTrue(f.message.endswith("a wall stands between acme and birch"), f.message)

    def test_a_page_titled_otherwise_is_still_known_by_its_file_name(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.people / "rowan-blake.md", person("R. Blake", "acme"))
        self.assertEqual([], [f for f in self.findings("people") if "rowan" in f.path])
        write(self.people / "rowan-blake.md", person("R. Blake", "acme", "[[wiki/entities/acme-corp]]"))
        rowan = self.findings("walls")
        self.assertEqual(1, len(rowan))
        self.assertTrue(rowan[0].message.endswith("a wall stands between acme and birch"), rowan[0].message)

    def test_an_alias_heading_or_other_path_is_warned(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        for value in ("[[wiki/entities/acme-corp|met about the bid]]", "[[wiki/entities/acme-corp#Merger talks]]",
                      "[[wiki/entities/../entities/acme-corp]]", "[[entities/acme-corp]]", "[[acme-corp]]",
                      "wiki/entities/acme-corp", "[[wiki/entities/acme-corp]] and more"):
            write(self.people / "dana-whitlock.md", person("Dana Whitlock", "acme", value))
            found = self.findings("people")
            self.assertEqual(1, len(found), value)
            self.assertIn("is exactly", found[0].message, value)

    def test_a_link_to_an_entity_page_reached_through_a_symbolic_link_leads_nowhere(self):
        outside = write(self.root / "Zones" / "Work" / "Acme Review" / "Notes.md", entity("acme"))
        self.entities.mkdir(parents=True)
        os.symlink(str(outside), str(self.entities / "acme-corp.md"))
        write(self.people / "dana-whitlock.md", person("Dana Whitlock", "acme", "[[wiki/entities/acme-corp]]"))
        found = self.findings("people")
        self.assertEqual(1, len(found))
        self.assertIn("leads to no entity page", found[0].message)

    def test_entity_pages_in_subfolders_count_for_one_page_per_party(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.entities / "clients" / "acme-holdings.md", entity("acme", "Acme Holdings"))
        self.assertEqual({"acme": ["acme-corp", "clients/acme-holdings"]}, garrick_lib.party_entities(self.root))
        found = [f for f in self.findings("meetings") if "entities" in f.path]
        self.assertEqual(2, len(found))
        self.assertEqual("", self.link("Dana Whitlock", "acme"))
        (self.entities / "acme-corp.md").unlink()
        self.assertEqual("[[wiki/entities/clients/acme-holdings]]", self.link("Dana Whitlock", "acme"))

    def test_an_entity_page_carrying_parties_stands_for_no_party(self):
        write(self.entities / "acme-corp.md", entity("acme", extra="parties: [acme]\nzone: Work\n"))
        self.assertEqual({}, garrick_lib.party_entities(self.root))
        self.assertEqual("", self.link("Dana Whitlock", "acme"))

    def test_an_entity_page_naming_two_walled_parties_is_warned(self):
        write(self.entities / "plain.md", entity("[acme, birch]", "Plain"))
        found = [f for f in self.findings("meetings") if "entities" in f.path]
        self.assertEqual(1, len(found))
        self.assertIn("names both acme and birch, which a wall keeps apart", found[0].message)

    def test_more_than_one_link_is_warned(self):
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.people / "dana-whitlock.md",
              person("Dana Whitlock", "acme").replace("party: acme\n", "party: acme\norganisation: [\"[[wiki/entities/acme-corp]]\", \"[[wiki/entities/acme-corp]]\"]\n"))
        found = self.findings("people")
        self.assertEqual(1, len(found))
        self.assertIn("is exactly", found[0].message)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class StagedWallCheckTest(Workspace):
    """The commit hook's wall check passes on what the change writes: a person
    page carrying the link, staged in the Wikis repository, and a project note
    linking that person page."""

    def test_the_hook_passes_on_a_new_page_with_its_link(self):
        wikis = self.root / "Wikis"
        git(wikis, "init", "-q")
        write(self.entities / "acme-corp.md", entity("acme"))
        path, _ = ingest.ensure_person(self.root, "Mira Holt", "acme", "2026-03-10")
        self.assertIn("organisation:", path.read_text())
        git(wikis, "add", "-A")
        findings = check.run_checks(self.root, walls_only=True, staged=wikis)
        self.assertEqual([], findings)

    def test_the_hook_refuses_a_person_page_linked_across_a_wall(self):
        wikis = self.root / "Wikis"
        git(wikis, "init", "-q")
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.entities / "birch-co.md", entity("birch", "Birch & Co"))
        write(self.people / "dana-whitlock.md", person("Dana Whitlock", "acme", "[[wiki/entities/birch-co]]"))
        write(self.people / "rowan-blake.md", person("Rowan Blake", "acme", "[[wiki/entities/acme-corp]]"))
        git(wikis, "add", "-A")
        found = check.run_checks(self.root, walls_only=True, staged=wikis)
        self.assertEqual({("error", "walls", "Wikis/Meetings/wiki/people/dana-whitlock.md"),
                          ("error", "walls", "Wikis/Meetings/wiki/people/rowan-blake.md")},
                         {(f.severity, f.check, f.path) for f in found})
        r = subprocess.run([sys.executable, str(TOOLS / "check.py"), "--root", str(self.root), "--staged",
                            "--walls-only"], cwd=str(wikis), capture_output=True, text=True, env=GIT_ENV)
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        # What is staged counts, not the disk: the link taken out but not staged is still refused.
        write(self.people / "dana-whitlock.md", person("Dana Whitlock", "acme"))
        write(self.people / "rowan-blake.md", person("Rowan Blake", "acme"))
        self.assertEqual(2, len(check.run_checks(self.root, walls_only=True, staged=wikis)))
        git(wikis, "add", "-A")
        self.assertEqual([], check.run_checks(self.root, walls_only=True, staged=wikis))

    def test_the_hook_reads_the_person_pages_of_an_entity_page_it_commits(self):
        """An entity page whose party changes can put a link across a wall
        that no person page staged: the commit reads the pages that link it."""
        wikis = self.root / "Wikis"
        git(wikis, "init", "-q")
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.people / "mira-holt.md", person("Mira Holt", "acme", "[[wiki/entities/acme-corp]]"))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch"))
        git(wikis, "add", "-A")
        git(wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")
        write(self.entities / "acme-corp.md", entity("birch"))
        git(wikis, "add", "-A")
        found = check.run_checks(self.root, walls_only=True, staged=wikis)
        self.assertEqual([("error", "walls", "Wikis/Meetings/wiki/people/mira-holt.md")],
                         [(f.severity, f.check, f.path) for f in found])
        self.assertTrue(found[0].message.endswith("a wall stands between acme and birch"), found[0].message)
        # Unstaged edits do not count: git's copy of the person page is what is read.
        write(self.people / "mira-holt.md", person("Mira Holt", "acme"))
        self.assertEqual(1, len(check.run_checks(self.root, walls_only=True, staged=wikis)))
        git(wikis, "add", "-A")
        self.assertEqual([], check.run_checks(self.root, walls_only=True, staged=wikis))

    def test_the_hook_passes_on_a_project_note_linking_that_person(self):
        work = self.root / "Zones" / "Work"
        shutil.rmtree(str(work / ".git"))
        git(work, "init", "-q")
        write(self.entities / "acme-corp.md", entity("acme"))
        ingest.ensure_person(self.root, "Mira Holt", "acme", "2026-03-10")
        note = work / "Acme Review" / "Threads" / "Pricing" / "Contacts.md"
        write(note, '---\nparent: "[[Pricing]]"\n---\n# Contacts\n\n[[mira-holt]] buys for Acme.\n')
        git(work, "add", "-A")
        findings = check.run_checks(self.root, walls_only=True, staged=work)
        self.assertEqual([], [f for f in findings if f.check == "walls"])


# ---------------------------------------------------------------------------
# nurture.py
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAVE_GIT, "git is not installed")
class NurtureTest(Workspace):
    def setUp(self):
        super().setUp()
        env = {k: v for k, v in GIT_ENV.items() if k.startswith("GIT_")}
        env.pop("GIT_DIR", None)
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("GARRICK_HEADLESS", None)
        self.wikis = self.root / "Wikis"
        git(self.wikis, "init", "-q")
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.entities / "birch-co.md", entity("birch", "Birch & Co"))
        write(self.people / "mira-holt.md", person("Mira Holt", "acme").replace(
            "party: acme\n", "party:\n  - acme\n"))                         # a party written as a list
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch"))
        write(self.people / "rowan-blake.md", person("Rowan Blake", "birch"))   # both hats: never offered
        write(self.people / "r-blake.md", person("rowan blake", "acme"))        # nor under another spelling
        write(self.people / "ines-varga.md", person("Ines Varga", "cedar"))     # no cedar entity page
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")
        self.before = {p.name: p.read_text() for p in self.people.glob("*.md")}

    def run_tool(self, *args: str, env=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            code = nurture.main(list(args) + ["--root", str(self.root), "--json", "--today", "2026-10-17"])
        return code, json.loads(out.getvalue())

    def asked(self, items):
        """What Nurture asks about each person page's organisation (#330): one
        question per page, never a mechanical fix."""
        return {Path(i["path"]).name: (i["question"], i["proposal"]) for i in items
                if i["kind"] == "attribution" and i["question"].startswith("Does ")}

    def organisation(self, page: str, *more: str, env=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = nurture.main(["organisation", "--path", "Wikis/Meetings/wiki/people/%s" % page, "--root",
                                 str(self.root), "--today", "2026-10-17"] + list(more))
        return code, out.getvalue(), err.getvalue()

    def test_each_page_that_lacks_the_link_is_one_question_and_no_fix(self):
        _, out = self.run_tool("list", "--scope", "Wikis/Meetings")
        self.assertEqual({"dana-whitlock.md": ("Does Dana Whitlock work at Acme Corp? (yes / no / another page)",
                                               "[[wiki/entities/acme-corp]]"),
                          "mira-holt.md": ("Does Mira Holt work at Acme Corp? (yes / no / another page)",
                                           "[[wiki/entities/acme-corp]]"),
                          "theo-marsh.md": ("Does Theo Marsh work at Birch & Co? (yes / no / another page)",
                                            "[[wiki/entities/birch-co]]")}, self.asked(out["items"]))
        self.assertEqual([], [i for i in out["items"] if (i.get("fix") or {}).get("op") == "organisation"])
        self.assertEqual(self.before, {p.name: p.read_text() for p in self.people.glob("*.md")})

    def test_a_batch_yes_writes_none_of_them(self):
        code, out = self.run_tool("fix", "--scope", "Wikis/Meetings", "--yes")
        self.assertEqual(0, code, out)
        self.assertEqual([], [i for i in out["fixed"] if i["fix"].get("op") == "organisation"])
        self.assertEqual(self.before, {p.name: p.read_text() for p in self.people.glob("*.md")})

    def test_one_pages_own_yes_adds_only_its_line(self):
        head = git(self.wikis, "rev-parse", "HEAD")
        code, said, err = self.organisation("mira-holt.md", "--yes")
        self.assertEqual(0, code, err)
        self.assertIn("Committed", said)
        after = {p.name: p.read_text() for p in self.people.glob("*.md")}
        old, new = self.before["mira-holt.md"].splitlines(), after["mira-holt.md"].splitlines()
        added = [l for l in new if l not in old]
        self.assertEqual(['organisation: "[[wiki/entities/acme-corp]]"'], added)
        self.assertEqual(old, [l for l in new if l not in added])
        self.assertEqual(["acme"], garrick_lib.parse_frontmatter_text(after["mira-holt.md"])["party"])
        for name in self.before:
            if name != "mira-holt.md":
                self.assertEqual(self.before[name], after[name], name)
        self.assertEqual(["Meetings/wiki/people/mira-holt.md"],
                         git(self.wikis, "diff", "--name-only", head.strip(), "HEAD").split())
        _, out = self.run_tool("list", "--scope", "Wikis/Meetings")
        self.assertNotIn("mira-holt.md", self.asked(out["items"]))
        # Another page the user names instead goes through the same rules: a walled one is refused.
        code, _, err = self.organisation("theo-marsh.md", "--yes", "--entity", "acme-corp")
        self.assertNotEqual(0, code)
        self.assertIn("a wall stands between", err)
        self.assertNotIn("organisation", (self.people / "theo-marsh.md").read_text())

    def test_with_nobody_watching_it_is_asked_and_never_written(self):
        head = git(self.wikis, "rev-parse", "HEAD")
        for args, env in ((("nightly",), None), (("fix", "--yes"), {"GARRICK_HEADLESS": "1"})):
            code, out = self.run_tool(*args, env=env)
            self.assertTrue(out["headless"])
            self.assertEqual([], [i for i in out["fixed"] if i["fix"].get("op") == "organisation"])
            self.assertEqual(3, len(self.asked(out["items"])))
        code, _, err = self.organisation("mira-holt.md", "--yes", env={"GARRICK_HEADLESS": "1"})
        self.assertNotEqual(0, code)
        self.assertIn("never with nobody watching", err)
        self.assertEqual(head, git(self.wikis, "rev-parse", "HEAD"))
        self.assertEqual(self.before, {p.name: p.read_text() for p in self.people.glob("*.md")})

    def test_a_page_with_changes_not_committed_is_held(self):
        page = self.people / "theo-marsh.md"
        page.write_text(page.read_text() + "\nA line being written.\n")
        code, _, err = self.organisation("theo-marsh.md", "--yes")
        self.assertNotEqual(0, code)
        self.assertIn("held", err)
        self.assertNotIn("organisation", page.read_text())


class DocsTest(unittest.TestCase):
    def test_the_meetings_skill_and_schema_say_what_the_link_is(self):
        skill = (REPO / "template" / "System" / "skills" / "meetings" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("| Entity page, one per party at most | `Wikis/Meetings/wiki/entities/<slug>.md` |", skill)
        self.assertIn('organisation: "[[wiki/entities/<slug>]]"', skill)
        schema = (REPO / "template" / "Wikis" / "Meetings" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("## An entity page", schema)
        self.assertIn("organisation:", schema)
        nurture_skill = (REPO / "template" / "System" / "skills" / "nurture" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("organisation", nurture_skill)


if __name__ == "__main__":
    unittest.main()
