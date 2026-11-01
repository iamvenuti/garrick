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
        # Out of scope, and said so: a letter from another script that looks Latin, and a possessive.
        self.assertEqual("[[wiki/entities/acme-corp]]", self.link("Row\u0430n Blake", "acme"))

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
        for names in (("Elias Moor",), ("David Whitlock",), ("Dana Whitmore",), ("Theo Cohen",)):
            self.assertEqual("[[wiki/entities/acme-corp]]", self.link(names, "acme"), names)
        self.assertEqual({"acme", "birch"}, garrick_lib.people_parties(self.context, "Eli Cohen"))
        self.assertEqual(set(), garrick_lib.people_parties(self.context, "David Whitlock"))

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
        self.assertEqual([], self.findings("people"))                     # so Dana is owed no link

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

    def test_a_link_to_another_partys_entity_page(self):
        write(self.entities / "cedar-ltd.md", entity("cedar", "Cedar Ltd"))
        write(self.people / "dana-whitlock.md", person("Dana Whitlock", "acme", "[[wiki/entities/cedar-ltd]]"))
        found = self.findings("people")
        self.assertEqual(1, len(found))
        self.assertIn("links the entity page of cedar, and the page names acme", found[0].message)

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

    def offered(self, items):
        return {Path(i["path"]).name: i["fix"]["link"] for i in items
                if i["kind"] == "mechanical" and (i.get("fix") or {}).get("op") == "organisation"}

    def test_the_list_names_every_page_that_lacks_the_link_and_no_other(self):
        _, out = self.run_tool("list", "--scope", "Wikis/Meetings")
        self.assertEqual({"dana-whitlock.md": "[[wiki/entities/acme-corp]]",
                          "mira-holt.md": "[[wiki/entities/acme-corp]]",
                          "theo-marsh.md": "[[wiki/entities/birch-co]]"}, self.offered(out["items"]))
        line = next(i["line"] for i in out["items"] if i["path"].endswith("theo-marsh.md"))
        self.assertIn('add organisation: "[[wiki/entities/birch-co]]"', line)
        self.assertEqual(self.before, {p.name: p.read_text() for p in self.people.glob("*.md")})

    def test_one_yes_adds_only_those_frontmatter_lines(self):
        code, out = self.run_tool("fix", "--scope", "Wikis/Meetings", "--yes")
        self.assertEqual(0, code, out)
        fixed = {Path(i["path"]).name for i in out["fixed"] if i["fix"]["op"] == "organisation"}
        self.assertEqual({"dana-whitlock.md", "mira-holt.md", "theo-marsh.md"}, fixed)
        after = {p.name: p.read_text() for p in self.people.glob("*.md")}
        for name in ("rowan-blake.md", "r-blake.md", "ines-varga.md"):
            self.assertEqual(self.before[name], after[name])
        for name, link in (("dana-whitlock.md", "acme-corp"), ("mira-holt.md", "acme-corp"), ("theo-marsh.md", "birch-co")):
            old, new = self.before[name].splitlines(), after[name].splitlines()
            added = [l for l in new if l not in old]
            self.assertEqual(['organisation: "[[wiki/entities/%s]]"' % link], added, name)
            self.assertEqual(old, [l for l in new if l not in added], name)
            fm = garrick_lib.parse_frontmatter_text(after[name])
            self.assertEqual("[[wiki/entities/%s]]" % link, fm["organisation"])
        self.assertEqual(["acme"], garrick_lib.parse_frontmatter_text(after["mira-holt.md"])["party"])
        changed = git(self.wikis, "show", "--name-only", "--format=", "HEAD").split()
        self.assertEqual(sorted("Meetings/wiki/people/%s" % n for n in fixed), sorted(changed))
        self.assertEqual("", git(self.wikis, "status", "--porcelain").strip())
        # Once there, nothing is owed and nothing is offered again.
        _, out = self.run_tool("list", "--scope", "Wikis/Meetings")
        self.assertEqual({}, self.offered(out["items"]))
        self.assertEqual([], [f for f in check.run_checks(self.root) if f.check == "people"])

    def test_with_nobody_watching_it_is_offered_and_never_written(self):
        head = git(self.wikis, "rev-parse", "HEAD")
        for args, env in ((("nightly",), None), (("fix", "--yes"), {"GARRICK_HEADLESS": "1"})):
            code, out = self.run_tool(*args, env=env)
            self.assertTrue(out["headless"])
            self.assertEqual([], [i for i in out["fixed"] if i["fix"].get("op") == "organisation"])
            self.assertEqual(3, len(self.offered(out["items"])))
            self.assertGreaterEqual(out["waiting"], 3)
            self.assertIn("Waiting for you:", out["digest"])
        self.assertEqual(head, git(self.wikis, "rev-parse", "HEAD"))
        self.assertEqual(self.before, {p.name: p.read_text() for p in self.people.glob("*.md")})

    def test_a_page_with_changes_not_committed_is_held(self):
        page = self.people / "theo-marsh.md"
        page.write_text(page.read_text() + "\nA line being written.\n")
        _, out = self.run_tool("fix", "--scope", "Wikis/Meetings", "--yes")
        held = [i for i in out["held"] if i["path"].endswith("theo-marsh.md")]
        self.assertEqual(1, len(held))
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
