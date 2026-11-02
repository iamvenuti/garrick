"""A Meetings person page links the entity page of where the person works,
whatever their party (#330).

    cd tests && python3 -m unittest test_person_employer

`organisation:` names the employer's entity page: `ingest.py person
--organisation` writes it, Nurture proposes it from the page's first line
("Identity architect at Birch & Co"), and #319's link to the party's own
entity page holds when nothing else is known. The walls hold as in #319: no
proposal, and the commit hook refuses a link written by hand, when the
entity page, or any entity page that goes by the same name under another
spelling, names a party walled from the person's, or when the People table
has the person under two walled parties. An entity page with no `party:` is
walled from nobody. Every workspace here is built in a temporary folder.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
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


ingest = load("garrick_meetings_ingest_330", INGEST)
nurture = load("garrick_nurture_330", TOOLS / "nurture.py")

# Acme and Birch are walled, as in the shared fixture; Cedar is walled from
# nobody. Dana Whitlock is Acme's, Theo Marsh Birch's. Rowan Blake and Søren
# Kjær are known under both Acme and Birch: one name, two hats. Kit Avery is
# in no row at all, as a customer's architect would be.
CONTEXT = fixtures.CONTEXT.replace(
    "| Birch & Co | Client.",
    "| Cedar Ltd | Supplier to Acme | Work | `cedar` | cedarltd.example |\n| Birch & Co | Client.",
).replace(
    "| Theo Marsh | `birch` | Managing partner |",
    "| Theo Marsh | `birch` | Managing partner |\n"
    "| Rowan Blake | `acme` | Adviser |\n"
    "| Rowan Blake | `birch` | Adviser |\n"
    "| Søren Kjær | `acme` | Engineer |\n"
    "| Søren Kjær | `birch` | Engineer |\n",
)


def entity(title: str, party: str = "none", aliases: str = "") -> str:
    lines = ["---", "title: %s" % title, "type: entity"]
    lines += ["party: %s" % party] if party else []
    lines += ["aliases: %s" % aliases] if aliases else []
    return "\n".join(lines + ["---", "", "# %s" % title, "", "An organisation.", ""])


def person(name: str, party: str, line: str, organisation: str = "") -> str:
    org = 'organisation: "%s"\n' % organisation if organisation else ""
    party_line = "party: %s\n" % party if party else ""
    return ("---\ntitle: %s\ntype: person\n%s%screated: 2026-03-10\nupdated: 2026-03-10\n---\n\n# %s\n\n%s\n"
            % (name, party_line, org, name, line))


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
        (self.people / "dana-whitlock.md").unlink()            # each test writes the people it needs
        self.context = garrick_lib.load_context(self.root)
        write(self.entities / "acme-corp.md", entity("Acme Corp", "acme"))
        write(self.entities / "birch-co.md", entity("Birch & Co", "birch"))
        write(self.entities / "cedar-ltd.md", entity("Cedar Ltd", "cedar"))
        write(self.entities / "larch-partners.md", entity("Larch Partners", aliases="[Larch]"))   # a customer: no party

    def propose(self, name: str, party, line: str):
        text = person(name, party if isinstance(party, str) else "", line)
        return garrick_lib.organisation_proposal(self.root, self.context, (name, ingest.person_slug(name)),
                                                 party, text)

    def findings(self, name: str):
        return [f for f in check.run_checks(self.root) if f.check == name]


# ---------------------------------------------------------------------------
# The rule: garrick_lib.organisation_proposal
# ---------------------------------------------------------------------------

class ProposalTest(Workspace):
    def test_a_first_line_naming_one_entity_page_proposes_it_whatever_the_party(self):
        self.assertEqual(("[[wiki/entities/birch-co]]", []),
                         self.propose("Kit Avery", "none", "Identity architect at Birch & Co, a customer."))
        self.assertEqual(("[[wiki/entities/larch-partners]]", []),
                         self.propose("Kit Avery", "cedar", "Buyer at Larch Partners."))

    def test_the_first_line_wins_over_the_party_and_the_party_holds_when_it_names_none(self):
        self.assertEqual(("[[wiki/entities/cedar-ltd]]", []),
                         self.propose("Pat Newcomer", "acme", "Now at Cedar Ltd."))
        self.assertEqual(("[[wiki/entities/acme-corp]]", []), self.propose("Pat Newcomer", "acme", "Buyer."))
        self.assertEqual(("", []), self.propose("Pat Newcomer", "none", "Buyer."))

    def test_spellings_of_an_entity_name_all_find_its_page(self):
        write(self.entities / "sorvik-freight.md", entity("Sørvik Freight", aliases='["Hüttelmoor Logistik"]'))
        for line, rel in (("at birch and co", "birch-co"), ("at Birch-Co.", "birch-co"), ("at BIRCH & CO", "birch-co"),
                          ("at BirchCo", "birch-co"), ("at Ｂirch & Co", "birch-co"), ("at Larch", "larch-partners"),
                          ("at Larch Partner", "larch-partners"), ("at larch-partners", "larch-partners"),
                          ("at Soervik Freight", "sorvik-freight"), ("at Sorvik Freights", "sorvik-freight"),
                          ("at SØRVIK FREIGHT", "sorvik-freight"), ("at Huettelmoor Logistik", "sorvik-freight"),
                          ("at Huttelmoor logistik", "sorvik-freight")):
            self.assertEqual(("[[wiki/entities/%s]]" % rel, []), self.propose("Kit Avery", "none", line), line)

    def test_a_name_inside_a_longer_one_gives_way_to_it(self):
        write(self.entities / "larch-digital.md", entity("Larch Digital"))
        self.assertEqual(("[[wiki/entities/larch-digital]]", []),
                         self.propose("Kit Avery", "none", "Designer at Larch Digital."))

    def test_two_entity_pages_named_are_asked_about(self):
        self.assertEqual(("", ["birch-co", "larch-partners"]),
                         self.propose("Kit Avery", "none", "Analyst at Larch Partners, seconded to Birch & Co."))

    def test_one_name_two_pages_go_by_is_asked_about(self):
        write(self.entities / "larch-uk.md", entity("LARCH-partners", aliases="[Larch UK]"))
        self.assertEqual(("", ["larch-partners", "larch-uk"]), self.propose("Kit Avery", "none", "Buyer at Larch."))

    def test_no_party_several_or_an_unknown_one_proposes_nothing(self):
        for party in ("", None, "fernway", ["none", "cedar"], ["acme", "cedar"]):
            self.assertEqual(("", []), self.propose("Kit Avery", party, "Buyer at Larch Partners."), party)

    def test_the_placeholder_line_and_headings_are_not_read(self):
        self.assertEqual("", garrick_lib.first_line(person("Kit Avery", "none", "<Who they are, and which party.>")))
        self.assertEqual("At Birch & Co.", garrick_lib.first_line("---\ntitle: x\n---\n# Kit\n\n## Role\n\nAt Birch & Co.\n"))


class ProposalWallTest(Workspace):
    """No proposal, and no question either, wherever a wall stands in the way."""

    def test_an_entity_page_of_a_party_walled_from_the_persons_is_not_proposed(self):
        self.assertEqual(("", []), self.propose("Pat Newcomer", "acme", "Consultant at Birch & Co."))
        self.assertEqual(("", []), self.propose("Pat Newcomer", "birch", "Consultant at Acme Corp."))

    def test_a_page_saying_none_does_not_hide_its_people_rows(self):
        # Theo is Birch's in the People table: Acme's page is walled from him, whatever his page says.
        self.assertEqual(("", []), self.propose("Theo Marsh", "none", "Now at Acme Corp."))
        self.assertEqual(("[[wiki/entities/larch-partners]]", []), self.propose("Theo Marsh", "none", "Now at Larch."))

    def test_a_person_under_two_walled_parties_gets_nothing_even_from_an_entity_with_no_party(self):
        for name in ("Rowan Blake", "ROWAN-BLAKE", "Søren Kjær", "Soren Kjaer", "Soeren Kjaer", "Sören Kjaer"):
            self.assertEqual(("", []), self.propose(name, "none", "Buyer at Larch Partners."), name)
            self.assertEqual(("", []), self.propose(name, "acme", "Buyer at Acme Corp."), name)

    def test_an_entity_page_with_no_party_is_walled_from_nobody(self):
        for name, party in (("Dana Whitlock", "acme"), ("Theo Marsh", "birch"), ("Kit Avery", "none")):
            self.assertEqual(("[[wiki/entities/larch-partners]]", []),
                             self.propose(name, party, "Buyer at Larch Partners."), name)

    def test_a_variant_spelled_page_with_no_party_cannot_carry_a_link_past_the_wall(self):
        """A second page for Acme, under another spelling and with no party,
        goes by Acme's name: proposing it would be proposing Acme."""
        for title, aliases in (("ACME-Corp.", ""), ("Acmé Corp", ""), ("Acme Corps", ""), ("AcmeCorp", ""),
                               ("Ａcme Corp", ""), ("Ledger Co", '["Ácme Corp"]')):
            write(self.entities / "variant.md", entity(title, aliases=aliases))
            for line in ("Buyer at %s." % title, "Buyer at Acme Corp.", "Buyer at acme-corp."):
                self.assertEqual(("", []), self.propose("Theo Marsh", "birch", line), (title, line))
                self.assertEqual(("", []), self.propose("Kit Avery", "birch", line), (title, line))
        # The party default stops too: no link for Acme's people to a name a Birch page goes by as well.
        write(self.entities / "variant.md", entity("Acme Corp", "birch"))
        self.assertEqual(("", []), self.propose("Dana Whitlock", "acme", "Buyer."))
        self.assertEqual("", garrick_lib.organisation_link(self.root, self.context, "Dana Whitlock", "acme"))

    def test_a_question_never_offers_a_page_across_a_wall(self):
        self.assertEqual(("", []), self.propose("Pat Newcomer", "acme", "Between Larch Partners and Birch & Co."))
        write(self.entities / "larch-birch.md", entity("Larch Partners", "birch"))
        self.assertEqual(("", []), self.propose("Pat Newcomer", "acme", "Buyer at Larch Partners."))

    def test_a_page_named_after_a_party_is_read_as_that_partys(self):
        """An entity page with no `party:` is walled from nobody, unless its
        name is a party's, in the Parties table or a heard form the Aliases
        table gives for it."""
        write(self.entities / "birch-co.md", entity("Birch & Co"))                              # no `party:`
        self.assertEqual(("", []), self.propose("Pat Newcomer", "acme", "Consultant at Birch & Co."))
        self.assertEqual(("[[wiki/entities/birch-co]]", []), self.propose("Kit Avery", "none", "At Birch & Co."))
        write(self.entities / "birchen.md", entity("Birchen Co"))
        self.assertEqual(("", []), self.propose("Pat Newcomer", "acme", "Consultant at Birchen Co."))

    def test_one_company_under_two_walled_tags_still_links_each_hats_own_page(self):
        context = CONTEXT.replace("| Cedar Ltd | Supplier to Acme | Work | `cedar` | cedarltd.example |",
                                  "| Birch & Co | Advisory client | Work | `birch-adv` | |")
        write(self.root / "System" / "context.md", context.replace(
            "| `acme` | `birch` | Competitors, and both are clients |",
            "| `acme` | `birch` | Competitors, and both are clients |\n| `birch` | `birch-adv` | Two hats |"))
        self.context = garrick_lib.load_context(self.root)
        write(self.entities / "birch-adv.md", entity("Birch & Co (advisory)", "birch-adv"))
        self.assertEqual(("[[wiki/entities/birch-co]]", []), self.propose("Theo Marsh", "birch", "Partner at Birch & Co."))
        self.assertEqual(("[[wiki/entities/birch-adv]]", []), self.propose("Ivy Stone", "birch-adv", "Founder."))
        write(self.entities / "untagged.md", entity("Birch and Co"))                            # either hat's name, no tag
        self.assertEqual(("", []), self.propose("Kit Avery", "none", "At Birch and Co."))


# ---------------------------------------------------------------------------
# ingest.py person --organisation
# ---------------------------------------------------------------------------

class IngestTest(Workspace):
    def run_person(self, *args: str):
        return subprocess.run([sys.executable, str(INGEST), "--root", str(self.root), "--today", "2026-03-10",
                               "person"] + list(args), capture_output=True, text=True)

    def test_it_writes_the_link_named(self):
        r = self.run_person("--name", "Kit Avery", "--party", "none", "--organisation", "birch-co")
        self.assertEqual((0, ""), (r.returncode, r.stderr))
        self.assertEqual("created\tWikis/Meetings/wiki/people/kit-avery.md", r.stdout.strip())
        self.assertEqual(
            '---\ntitle: Kit Avery\ntype: person\nparty: none\norganisation: "[[wiki/entities/birch-co]]"\n'
            "created: 2026-03-10\nupdated: 2026-03-10\n---\n\n# Kit Avery\n\n"
            "<Who they are, and which party, in a sentence.>\n", (self.people / "kit-avery.md").read_text())

    def test_by_title_alias_or_link_too(self):
        for name, value, rel in (("Ana One", "Birch & Co", "birch-co"), ("Ana Two", "birch and co", "birch-co"),
                                 ("Ana Three", "Larch", "larch-partners"),
                                 ("Ana Four", "[[wiki/entities/cedar-ltd]]", "cedar-ltd")):
            path, created = ingest.ensure_person(self.root, name, "none", "2026-03-10", value)
            self.assertTrue(created)
            self.assertIn('organisation: "[[wiki/entities/%s]]"' % rel, path.read_text(), value)

    def test_never_an_entity_page_made_and_never_a_guess(self):
        before = sorted(p.name for p in self.entities.iterdir())
        r = self.run_person("--name", "Kit Avery", "--party", "none", "--organisation", "Fernway Bank")
        self.assertEqual(0, r.returncode)
        self.assertIn("no organisation link: no entity page", r.stderr)
        self.assertNotIn("organisation", (self.people / "kit-avery.md").read_text())
        self.assertEqual(before, sorted(p.name for p in self.entities.iterdir()))
        write(self.entities / "larch-uk.md", entity("Larch", "cedar"))
        why = []
        path, _ = ingest.ensure_person(self.root, "Ana Five", "none", "2026-03-10", "Larch", why)
        self.assertNotIn("organisation", path.read_text())
        self.assertIn("wiki/entities/larch-partners or wiki/entities/larch-uk", why[0])

    def test_across_a_wall_the_page_is_written_without_it(self):
        r = self.run_person("--name", "Pat Newcomer", "--party", "acme", "--organisation", "birch-co")
        self.assertEqual(0, r.returncode)
        self.assertIn("no organisation link: a wall stands between", r.stderr)
        text = (self.people / "pat-newcomer.md").read_text()
        for leak in ("organisation", "birch", "Birch"):
            self.assertNotIn(leak, text)

    def test_two_hats_and_variant_spelled_duplicates_get_no_link(self):
        why = []
        path, _ = ingest.ensure_person(self.root, "Rowan Blake", "none", "2026-03-10", "larch-partners", why)
        self.assertNotIn("organisation", path.read_text())
        self.assertIn("both sides of a wall", why[0])
        write(self.entities / "acme-customer.md", entity("ACME-Corps"))       # Acme's name, no party
        why = []
        path, _ = ingest.ensure_person(self.root, "Theo Marsh", "birch", "2026-03-10", "acme-customer", why)
        self.assertNotIn("organisation", path.read_text())
        self.assertIn("a wall stands between", why[0])

    def test_an_existing_page_is_left_as_it_is(self):
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Architect."))
        before = (self.people / "kit-avery.md").read_text()
        r = self.run_person("--name", "Kit Avery", "--party", "none", "--organisation", "birch-co")
        self.assertEqual(0, r.returncode)
        self.assertTrue(r.stdout.startswith("exists"))
        self.assertIn("the page was there already", r.stderr)
        self.assertEqual(before, (self.people / "kit-avery.md").read_text())


# ---------------------------------------------------------------------------
# check.py
# ---------------------------------------------------------------------------

class CheckTest(Workspace):
    def test_a_page_owed_the_link_of_where_they_work(self):
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Identity architect at Birch & Co, a customer."))
        self.assertEqual([("warning", "%s, [[wiki/entities/birch-co]]" % check.NO_EMPLOYER)],
                         [(f.severity, f.message) for f in self.findings("people")])
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Identity architect at Birch & Co.",
                                                   "[[wiki/entities/birch-co]]"))
        self.assertEqual([], self.findings("people"))
        self.assertEqual([], self.findings("walls"))

    def test_a_line_that_could_mean_two_pages_is_a_question(self):
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "At Larch Partners, then Birch & Co."))
        self.assertEqual(["%s: [[wiki/entities/birch-co]], [[wiki/entities/larch-partners]]" % check.ORGANISATION_ASK],
                         [f.message for f in self.findings("people")])

    def test_where_a_wall_stands_nothing_is_said(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant at Birch & Co."))
        write(self.people / "rowan-blake.md", person("Rowan Blake", "none", "Buyer at Larch Partners."))
        self.assertEqual([], self.findings("people"))

    def test_a_link_to_no_entity_page_is_warned_as_before(self):
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Architect.", "[[wiki/entities/birch-and-co]]"))
        found = self.findings("people")
        self.assertEqual(1, len(found))
        self.assertIn("leads to no entity page", found[0].message)

    def test_two_entity_pages_going_by_one_name_are_warned(self):
        for title, aliases in (("LARCH-partners", ""), ("Larch Partner", ""), ("Lärch Partners", ""),
                               ("Ledger Co", '["Larch & Partners"]'), ("Ledger Co", "[larch]")):
            write(self.entities / "variant.md", entity(title, aliases=aliases))
            found = [f for f in self.findings("meetings") if "entities" in f.path]
            self.assertEqual({"Wikis/Meetings/wiki/entities/larch-partners.md", "Wikis/Meetings/wiki/entities/variant.md"},
                             {f.path for f in found}, title)
            for f in found:
                self.assertEqual("warning", f.severity)
                self.assertIn("goes by a name that wiki/entities/", f.message)
        (self.entities / "variant.md").unlink()
        self.assertEqual([], [f for f in self.findings("meetings") if "entities" in f.path])

    def test_a_hand_written_link_to_a_variant_spelled_page_is_a_wall_finding(self):
        write(self.entities / "acme-customer.md", entity("Acmé-Corp"))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner.", "[[wiki/entities/acme-customer]]"))
        found = self.findings("walls")
        self.assertEqual(["Wikis/Meetings/wiki/people/theo-marsh.md"], [f.path for f in found])
        self.assertTrue(found[0].message.endswith("a wall stands between acme and birch"), found[0].message)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class HookTest(Workspace):
    """`check.py --staged --walls-only`, the commit hook's check, on a link
    written by hand."""

    def setUp(self):
        super().setUp()
        self.wikis = self.root / "Wikis"
        git(self.wikis, "init", "-q")

    def staged(self):
        git(self.wikis, "add", "-A")
        return sorted((f.severity, f.check, f.path) for f in check.run_checks(self.root, walls_only=True,
                                                                               staged=self.wikis))

    def commit(self):
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")

    def refused(self, *names: str):
        return [("error", "walls", "Wikis/Meetings/wiki/people/%s.md" % n) for n in names]

    def test_the_link_of_where_they_work_passes(self):
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Architect at Birch & Co.",
                                                   "[[wiki/entities/birch-co]]"))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Buyer.", "[[wiki/entities/larch-partners]]"))
        self.assertEqual([], self.staged())

    def test_a_link_to_a_walled_partys_page_is_refused(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/birch-co]]"))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "none", "Partner.", "[[wiki/entities/acme-corp]]"))
        self.assertEqual(self.refused("pat-newcomer", "theo-marsh"), self.staged())
        r = subprocess.run([sys.executable, str(TOOLS / "check.py"), "--root", str(self.root), "--staged",
                            "--walls-only"], cwd=str(self.wikis), capture_output=True, text=True, env=GIT_ENV)
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)

    def test_a_person_under_two_walled_parties_is_refused_any_link(self):
        write(self.people / "rowan-blake.md", person("Rowan Blake", "none", "Buyer.", "[[wiki/entities/larch-partners]]"))
        write(self.people / "soeren-kjaer.md", person("Soeren Kjaer", "cedar", "Engineer.",
                                                      "[[wiki/entities/cedar-ltd]]"))
        self.assertEqual(self.refused("rowan-blake", "soeren-kjaer"), self.staged())

    def test_a_link_to_a_variant_spelled_page_of_a_walled_name_is_refused(self):
        variants = (("ACME-Corp.", ""), ("Acmé Corp", ""), ("Acme Corps", ""), ("Ａcme Corp", ""),
                    ("Ledger Co", '["Ácme Corp"]'), ("Ledger Co", '["acme and corp"]'))
        for i, (title, aliases) in enumerate(variants):
            write(self.entities / ("variant-%d.md" % i), entity(title, aliases=aliases))
            write(self.people / ("theo-%d.md" % i), person("Theo Marsh", "birch", "Partner.",
                                                           "[[wiki/entities/variant-%d]]" % i))
        self.assertEqual(self.refused(*("theo-%d" % i for i in range(len(variants)))), self.staged())

    def test_committing_an_entity_page_that_takes_a_walled_name_reads_the_links_to_its_namesakes(self):
        write(self.entities / "ledger-co.md", entity("Ledger Co"))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner.", "[[wiki/entities/ledger-co]]"))
        self.commit()
        self.assertEqual([], self.staged())
        write(self.entities / "ledger-co.md", entity("Ledger Co", aliases='["Acme Corp"]'))    # an alias, staged
        self.assertEqual(self.refused("theo-marsh"), self.staged())
        write(self.entities / "ledger-co.md", entity("Ledger Co"))
        self.assertEqual([], self.staged())
        write(self.entities / "ledger-acme.md", entity("Ledger Co", "acme"))                   # a namesake, staged
        self.assertEqual(self.refused("theo-marsh"), self.staged())

    def test_a_page_named_after_a_party_is_that_partys_though_it_names_none(self):
        (self.entities / "acme-corp.md").unlink()
        write(self.entities / "acme.md", entity("Acme Corp"))                                   # no `party:`
        write(self.entities / "birchen.md", entity("Birchen Co"))                               # an alias of Birch's
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner.", "[[wiki/entities/acme]]"))
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer.", "[[wiki/entities/birchen]]"))
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Architect.", "[[wiki/entities/acme]]"))
        self.assertEqual(self.refused("pat-newcomer", "theo-marsh"), self.staged())


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
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Identity architect at Birch & Co, a customer."))
        write(self.people / "ana-holt.md", person("Ana Holt", "none", "Analyst at Larch Partners, seconded to Birch & Co."))
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant at Birch & Co."))
        write(self.people / "rowan-blake.md", person("Rowan Blake", "none", "Buyer at Larch Partners."))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "none", "Now at Acme Corp."))
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")
        self.before = {p.name: p.read_text() for p in self.people.glob("*.md")}

    def run_tool(self, *args: str, env=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            code = nurture.main(list(args) + ["--root", str(self.root), "--json", "--today", "2026-10-17"])
        return code, json.loads(out.getvalue())

    def about(self, items, name: str):
        """What the run says of a person page, but the wiki lint's orphan, which every page here is."""
        return [i for i in items if i["path"].endswith("/" + name) and i["check"] != "orphan"]

    def test_one_page_one_proposal_and_an_ambiguous_one_asked(self):
        _, out = self.run_tool("list", "--scope", "Wikis/Meetings")
        kit = self.about(out["items"], "kit-avery.md")
        self.assertEqual([("attribution", "Does Kit Avery work at Birch & Co? (yes / no / another page)",
                           "[[wiki/entities/birch-co]]", None)],
                         [(i["kind"], i["question"], i["proposal"], i["fix"]) for i in kit])
        ana = self.about(out["items"], "ana-holt.md")
        self.assertEqual([("attribution", "Where does Ana Holt work: Birch & Co or Larch Partners?")],
                         [(i["kind"], i["question"]) for i in ana])
        self.assertEqual(self.before, {p.name: p.read_text() for p in self.people.glob("*.md")})

    def test_across_a_wall_no_proposal_and_no_question(self):
        _, out = self.run_tool("list", "--scope", "Wikis/Meetings")
        for name in ("pat-newcomer.md", "rowan-blake.md", "theo-marsh.md"):
            self.assertEqual([], self.about(out["items"], name), name)

    def organisation(self, page: str, *more: str, env=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = nurture.main(["organisation", "--path", "Wikis/Meetings/wiki/people/%s" % page, "--root",
                                 str(self.root), "--today", "2026-10-17"] + list(more))
        return code, err.getvalue()

    def test_the_link_on_that_pages_own_yes_and_only_that_line(self):
        code, out = self.run_tool("fix", "--scope", "Wikis/Meetings", "--yes")
        self.assertEqual([], [i for i in out["fixed"] if i["fix"]["op"] == "organisation"])   # never a batch
        self.assertEqual(self.before, {p.name: p.read_text() for p in self.people.glob("*.md")})
        code, err = self.organisation("kit-avery.md", "--yes")
        self.assertEqual(0, code, err)
        for name in ("ana-holt.md", "pat-newcomer.md", "rowan-blake.md", "theo-marsh.md"):
            self.assertNotEqual(0, self.organisation(name, "--yes")[0], name)    # a question, or a wall: nothing
        after = {p.name: p.read_text() for p in self.people.glob("*.md")}
        old, new = self.before["kit-avery.md"].splitlines(), after["kit-avery.md"].splitlines()
        self.assertEqual(['organisation: "[[wiki/entities/birch-co]]"'], [l for l in new if l not in old])
        self.assertEqual(old, [l for l in new if l != 'organisation: "[[wiki/entities/birch-co]]"'])
        for name in ("ana-holt.md", "pat-newcomer.md", "rowan-blake.md", "theo-marsh.md"):
            self.assertEqual(self.before[name], after[name], name)
        self.assertEqual([], [f for f in check.run_checks(self.root) if f.check == "walls"])

    def test_never_overnight(self):
        for args, env in ((("nightly",), None), (("fix", "--yes"), {"GARRICK_HEADLESS": "1"})):
            _, out = self.run_tool(*args, env=env)
            self.assertEqual([], [i for i in out["fixed"] if i["fix"].get("op") == "organisation"])
        self.assertEqual(self.before, {p.name: p.read_text() for p in self.people.glob("*.md")})



# ---------------------------------------------------------------------------
# The release review's ways past the wall, each closed
# ---------------------------------------------------------------------------

def untagged(title: str, aliases: str = "") -> str:
    """An entity page with no `party:` key at all."""
    return entity(title, party="", aliases=aliases)


class UntaggedEntityTest(Workspace):
    """An entity page with no `party:` key is never linked by a tool: it may be
    a walled party's under a name no folding reads as that party's."""

    FORMS = ("Acme", "Acme Corporation", "Acme Corp Ltd", "The Acme Corp", "Асме Corp", "Αcme Corp",
             "Ac​me Corp", "Ac­me Corp", "Larch Logistics")

    def test_no_proposal_for_an_untagged_page_under_any_name(self):
        for title in self.FORMS:
            write(self.entities / "probe.md", untagged(title))
            for who, party in (("Theo Marsh", "none"), ("Theo Marsh", "birch"), ("Kit Avery", "none")):
                self.assertEqual(("", []), self.propose(who, party, "Now at %s." % title), (title, who))

    def test_ingest_writes_no_link_to_an_untagged_page_and_names_no_wall(self):
        write(self.entities / "acme.md", untagged("Acme"))
        r = subprocess.run([sys.executable, str(INGEST), "--root", str(self.root), "--today", "2026-03-10", "person",
                            "--name", "Kit Avery", "--party", "none", "--organisation", "acme"],
                           capture_output=True, text=True)
        self.assertEqual(0, r.returncode)
        self.assertIn("needs a `party:`", r.stderr)
        self.assertNotIn("wall", r.stderr)
        self.assertNotIn("organisation", (self.people / "kit-avery.md").read_text())

    def untagged_warnings(self):
        return [f for f in self.findings("meetings") if f.message.startswith(check.NO_ENTITY_PARTY)]

    def test_an_untagged_page_nothing_points_at_is_not_warned(self):
        write(self.entities / "spring-summit.md", untagged("Spring Summit"))      # an event, not an organisation
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Architect at Larch Partners."))
        self.assertEqual([], self.untagged_warnings())
        _, out = self.nurture_list()
        self.assertEqual([], [i for i in out["items"] if i["path"].endswith("spring-summit.md") and i["check"] != "orphan"])

    def test_one_a_first_line_names_is_warned_and_asked_about(self):
        write(self.entities / "acme.md", untagged("Acme"))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Managing partner; formerly at Acme."))
        found = self.untagged_warnings()
        self.assertEqual(["Wikis/Meetings/wiki/entities/acme.md"], [f.path for f in found])
        for leak in ("theo", "Theo", "birch"):
            self.assertNotIn(leak, found[0].message + found[0].ear)
        item = nurture.sort_item(nurture.Ctx(self.root), nurture.check_items(vars(found[0]))[0])
        self.assertEqual(("attribution", "Whose is Acme: none, or a party?"), (item.kind, item.question))

    def test_one_the_party_default_would_reach_is_warned(self):
        write(self.entities / "acme-two.md", untagged("Acme Corp"))               # a namesake of Acme's own page
        write(self.people / "dana-whitlock.md", person("Dana Whitlock", "acme", "Head of procurement."))
        self.assertEqual(["Wikis/Meetings/wiki/entities/acme-two.md"], [f.path for f in self.untagged_warnings()])

    def nurture_list(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = nurture.main(["list", "--scope", "Wikis/Meetings", "--root", str(self.root), "--json",
                                 "--today", "2026-10-17"])
        return code, json.loads(out.getvalue())

    def test_the_hook_refuses_a_hand_written_link_to_an_untagged_page(self):
        write(self.entities / "acme.md", untagged("Acme"))
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Buyer.", "[[wiki/entities/acme]]"))
        found = self.findings("walls")
        self.assertEqual(["Wikis/Meetings/wiki/people/kit-avery.md"], [f.path for f in found])
        self.assertTrue(found[0].message.startswith(check.ORGANISATION_ONE), found[0].message)
        self.assertEqual(["Wikis/Meetings/wiki/entities/acme.md"], [f.path for f in self.untagged_warnings()])


class NamedAfterTest(Workspace):
    """A page saying `party: none` is walled from nobody, unless it is named
    after a party: a short form, a suffix, a leading `The`, the party's tag,
    a qualifier in its Parties cell. A name with letters the folding drops is
    linked by no tool."""

    def test_short_forms_and_suffixes_read_as_the_partys(self):
        for title in ("Acme", "Acme Corporation", "Acme Corp Ltd", "The Acme Corp", "Acme Corp, Inc.", "ACME"):
            write(self.entities / "probe.md", entity(title))
            self.assertEqual(("", []), self.propose("Theo Marsh", "birch", "Now at %s." % title), title)
            self.assertEqual(("", []), self.propose("Theo Marsh", "none", "Now at %s." % title), title)

    def test_a_qualifier_in_the_parties_cell_is_a_name_too(self):
        write(self.root / "System" / "context.md",
              CONTEXT.replace("| Acme Corp | Client.", "| **Acme Corp** (formerly Anvil Works) | Client."))
        self.context = garrick_lib.load_context(self.root)
        write(self.entities / "anvil.md", entity("Anvil Works"))
        self.assertEqual(("", []), self.propose("Theo Marsh", "birch", "Now at Anvil Works."))
        write(self.entities / "acme-two.md", entity("Acme Corp"))
        self.assertEqual(("", []), self.propose("Kit Avery", "birch", "Now at Acme Corp."))

    def test_a_suspect_name_is_linked_by_no_tool(self):
        for title in ("Асме Corp", "Αcme Corp", "Ac​me Corp", "Ac­me Corp"):
            write(self.entities / "probe.md", entity(title))
            self.assertEqual(("", []), self.propose("Kit Avery", "none", "Now at %s." % title), title)
            why = []
            path, _ = ingest.ensure_person(self.root, "Ana %d" % len(title), "none", "2026-03-10", "probe", why)
            self.assertNotIn("organisation", path.read_text(), title)
            path.unlink()

    def test_a_customer_saying_none_is_still_linked(self):
        self.assertEqual(("[[wiki/entities/larch-partners]]", []),
                         self.propose("Theo Marsh", "birch", "Buyer at Larch Partners."))


class SubsumedMatchTest(Workspace):
    def test_a_walled_name_inside_a_longer_one_still_stops_the_proposal(self):
        write(self.entities / "acme-corp.md", entity("Acme Corp", "acme", aliases="[Quill]"))
        write(self.entities / "quill-labs.md", entity("Quill Labs"))
        self.assertEqual(("", []), self.propose("Theo Marsh", "birch", "Now at Quill Labs."))
        self.assertEqual(("[[wiki/entities/quill-labs]]", []), self.propose("Kit Avery", "none", "Now at Quill Labs."))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class HookFormsTest(Workspace):
    """The hook reads the page a link opens, whatever case or form it is
    written in, and refuses a value that opens no one entity page."""

    def setUp(self):
        super().setUp()
        self.wikis = self.root / "Wikis"
        git(self.wikis, "init", "-q")

    def staged_paths(self):
        git(self.wikis, "add", "-A")
        return sorted(f.path for f in check.run_checks(self.root, walls_only=True, staged=self.wikis))

    def write_org(self, slug: str, name: str, party: str, line: str):
        write(self.people / (slug + ".md"),
              "---\ntitle: %s\ntype: person\nparty: %s\n%s\n---\n\n# %s\n\nPartner.\n" % (name, party, line, name))

    def test_the_real_page_is_found_whatever_the_case(self):
        write(self.entities / "acme.md", entity("Acme"))
        found = garrick_lib.entity_page(self.root, "ACME")
        self.assertTrue(found is None or found.name == "acme.md", found)

    def test_case_variant_links_meet_the_namesake_and_named_after_rules(self):
        write(self.entities / "acme.md", entity("Acme"))                         # named after Acme Corp
        write(self.entities / "ledger.md", entity("Ledger Co"))
        write(self.entities / "ledger-acme.md", entity("Ledger Co", "acme"))      # a walled namesake
        self.write_org("theo-1", "Theo Marsh", "birch", 'organisation: "[[wiki/entities/ACME]]"')
        self.write_org("theo-2", "Theo Marsh", "birch", 'organisation: "[[wiki/entities/Ledger]]"')
        self.assertEqual(["Wikis/Meetings/wiki/people/theo-1.md", "Wikis/Meetings/wiki/people/theo-2.md"],
                         self.staged_paths())

    def test_a_case_variant_link_is_read_when_its_entity_page_is_committed(self):
        write(self.entities / "ledger.md", entity("Ledger Co"))
        self.write_org("theo-marsh", "Theo Marsh", "birch", 'organisation: "[[wiki/entities/Ledger]]"')
        self.assertEqual([], self.staged_paths())
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")
        write(self.entities / "ledger.md", entity("Ledger Co", "acme"))
        self.assertEqual(["Wikis/Meetings/wiki/people/theo-marsh.md"], self.staged_paths())

    def test_every_form_of_a_cross_wall_link_is_refused(self):
        forms = ('organisation: "[[wiki/entities/birch-co|Birch]]"', 'organisation: "[[wiki/entities/birch-co#About]]"',
                 'organisation: "[[wiki/entities/birch-co^abc]]"', 'organisation: "[Birch](wiki/entities/birch-co.md)"',
                 'organisation: "[[wiki/entities/birch-co.md]]"', 'organisation: "[[wiki/entities/./birch-co]]"',
                 'organisation: "[[Wikis/Meetings/wiki/entities/birch-co]]"', 'organisation: "[[wiki/entities/birch-co ]]"',
                 'organisation: "[[wiki/entities/Birch-Co]]"', 'Organisation: "[[wiki/entities/birch-co]]"',
                 'organization: "[[wiki/entities/birch-co]]"', 'organisation:\n  - "[[wiki/entities/birch-co]]"')
        for i, line in enumerate(forms):
            self.write_org("pat-%d" % i, "Pat Newcomer", "acme", line)
        self.assertEqual(sorted("Wikis/Meetings/wiki/people/pat-%d.md" % i for i in range(len(forms))),
                         self.staged_paths())

    def test_a_value_that_opens_no_one_entity_page_is_refused_in_plain_words(self):
        forms = ('organisation: "[[birch-co]]"', 'organisation: "[[wiki/entities/fernway]]"',
                 'organisation: "Birch & Co"',
                 'organisation: ["[[wiki/entities/larch-partners]]", "[[wiki/entities/cedar-ltd]]"]',
                 'organisation: "[[wiki/entities/larch-partners]] [[wiki/entities/cedar-ltd]]"',
                 'organisation: "[[wiki/entities/larch-partners]]"\norganization: "[[wiki/entities/cedar-ltd]]"',
                 'organisation: "[[wiki/entities/elsewhere]]"')
        outside = write(Path(self._tmp.name) / "elsewhere.md", entity("Elsewhere"))
        os.symlink(str(outside), str(self.entities / "elsewhere.md"))
        for i, line in enumerate(forms):
            self.write_org("kit-%d" % i, "Kit Avery", "none", line)
        git(self.wikis, "add", "-A")
        found = check.run_checks(self.root, walls_only=True, staged=self.wikis)
        self.assertEqual(sorted("Wikis/Meetings/wiki/people/kit-%d.md" % i for i in range(len(forms))),
                         sorted(f.path for f in found))
        for f in found:
            self.assertEqual("error", f.severity)
            self.assertTrue(f.message.startswith((check.ORGANISATION_ONE, check.PERSON_SHAPE)), f.message)

    def test_an_unwalled_link_in_another_form_passes_the_hook(self):
        self.write_org("kit-avery", "Kit Avery", "none", 'organisation: "[[wiki/entities/larch-partners|Larch]]"')
        self.write_org("theo-marsh", "Theo Marsh", "birch", 'organisation: "[[wiki/entities/Birch-Co]]"')
        self.assertEqual([], self.staged_paths())

    def test_a_person_page_naming_its_party_under_parties_is_read_too(self):
        write(self.people / "pat-newcomer.md", '---\ntitle: Pat Newcomer\ntype: person\nparties: [acme]\n'
              'organisation: "[[wiki/entities/birch-co]]"\n---\n\n# Pat Newcomer\n\nConsultant.\n')
        self.assertEqual(["Wikis/Meetings/wiki/people/pat-newcomer.md"], self.staged_paths())


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class NurtureUntaggedTest(Workspace):
    """End to end: an untagged page that is Acme's own short page is never
    written into a Birch person page, by a list, a yes or a night."""

    def test_never_proposed_never_written(self):
        env = {k: v for k, v in GIT_ENV.items() if k.startswith("GIT_")}
        env.pop("GIT_DIR", None)
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("GARRICK_HEADLESS", None)
        wikis = self.root / "Wikis"
        git(wikis, "init", "-q")
        write(self.entities / "acme.md", untagged("Acme"))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Managing partner; formerly at Acme."))
        git(wikis, "add", "-A")
        git(wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")
        before = (self.people / "theo-marsh.md").read_text()
        for args in (("list", "--scope", "Wikis/Meetings"), ("nightly",), ("fix", "--scope", "Wikis/Meetings", "--yes")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                nurture.main(list(args) + ["--root", str(self.root), "--json", "--today", "2026-10-17"])
            data = json.loads(out.getvalue())
            self.assertEqual([], [i for i in data["items"] if i["path"].endswith("theo-marsh.md")
                                  and (i.get("fix") or {}).get("op") == "organisation"], args)
        self.assertEqual(before, (self.people / "theo-marsh.md").read_text())



# ---------------------------------------------------------------------------
# The second review's ways past the wall, each closed
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAVE_GIT, "git is not installed")
class MisreadFrontmatterTest(Workspace):
    """Valid YAML the frontmatter reader misreads: any line naming
    organisation that is not the one clean `organisation:` line is refused."""

    def setUp(self):
        super().setUp()
        self.wikis = self.root / "Wikis"
        git(self.wikis, "init", "-q")

    def page(self, slug: str, front: str, title: str = "Pat Newcomer"):
        write(self.people / (slug + ".md"),
              "---\ntitle: %s\ntype: person\nparty: acme\n%s\ncreated: 2026-03-10\nupdated: 2026-03-10\n---\n\n"
              "# %s\n\nConsultant.\n" % (title, front, title))

    def test_each_misread_form_is_refused_in_plain_words(self):
        b = "[[wiki/entities/birch-co]]"
        forms = ('organisation:\n  "%s"' % b, '"organisation": "%s"' % b, "'organisation': \"%s\"" % b,
                 '? organisation\n: "%s"' % b, 'organisatıon: "%s"' % b, 'ORGANISATION: "%s"' % b,
                 'organisation: "%s"\norganisation: ""' % b, 'organisation:\n  - "%s"' % b,
                 'organisation: >\n  %s' % b, 'organisation: "[[wiki/entities/\n  birch-co]]"',
                 'organisation : "%s"' % b, 'organi­sation: "%s"' % b)
        for i, front in enumerate(forms):
            self.page("pat-%d" % i, front)
        git(self.wikis, "add", "-A")
        found = check.run_checks(self.root, walls_only=True, staged=self.wikis)
        self.assertEqual(sorted("Wikis/Meetings/wiki/people/pat-%d.md" % i for i in range(len(forms))),
                         sorted(f.path for f in found))
        for f in found:
            self.assertTrue(f.message.startswith(check.PERSON_SHAPE), f.message)

    def test_a_clean_line_and_a_title_naming_an_organisation_pass(self):
        self.page("kit-avery", 'organisation: "[[wiki/entities/larch-partners]]"', title="Organisation Design Lead")
        self.page("ana-holt", "organisation:")
        git(self.wikis, "add", "-A")
        self.assertEqual([], check.run_checks(self.root, walls_only=True, staged=self.wikis))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class AskedPageByPageTest(Workspace):
    """A name can stand for a walled party under a form no matching reads
    (initials, digits, a translated name), so an employer link is never a
    batch fix: each page is asked about, and only its own yes writes it."""

    def test_a_page_the_matching_cannot_place_is_asked_never_written_by_a_batch(self):
        env = {k: v for k, v in GIT_ENV.items() if k.startswith("GIT_")}
        env.pop("GIT_DIR", None)
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("GARRICK_HEADLESS", None)
        wikis = self.root / "Wikis"
        git(wikis, "init", "-q")
        write(self.entities / "ac-corp.md", entity("AC Corp"))          # Acme's, under initials: no rule reads it
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Managing partner; formerly at AC Corp."))
        git(wikis, "add", "-A")
        git(wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")
        before = (self.people / "theo-marsh.md").read_text()
        for args, extra in ((("list", "--scope", "Wikis/Meetings"), {}), (("nightly",), {}),
                            (("fix", "--scope", "Wikis/Meetings", "--yes"), {}),
                            (("fix", "--yes"), {"GARRICK_HEADLESS": "1"})):
            out = io.StringIO()
            with mock.patch.dict(os.environ, extra), contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                nurture.main(list(args) + ["--root", str(self.root), "--json", "--today", "2026-10-17"])
            data = json.loads(out.getvalue())
            theo = [i for i in data["items"] if i["path"].endswith("theo-marsh.md") and i["check"] != "orphan"]
            self.assertEqual([("attribution", "Does Theo Marsh work at AC Corp? (yes / no / another page)")],
                             [(i["kind"], i["question"]) for i in theo], args)
            self.assertEqual([], [i for i in data.get("fixed", []) if i["fix"].get("op") == "organisation"], args)
        self.assertEqual(before, (self.people / "theo-marsh.md").read_text())


class LesserFaultsTest(Workspace):
    def test_the_hook_refuses_a_link_to_a_party_none_page_with_a_suspect_name(self):
        write(self.entities / "asme.md", entity("Асме Corp"))
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Buyer.", "[[wiki/entities/asme]]"))
        found = self.findings("walls")
        self.assertEqual(["Wikis/Meetings/wiki/people/kit-avery.md"], [f.path for f in found])
        self.assertTrue(found[0].message.startswith(check.ORGANISATION_ONE), found[0].message)

    def test_ingest_takes_a_file_name_with_md(self):
        path, created = ingest.ensure_person(self.root, "Kit Avery", "none", "2026-03-10", "larch-partners.md")
        self.assertTrue(created)
        self.assertIn('organisation: "[[wiki/entities/larch-partners]]"', path.read_text())

    def test_every_bracketed_name_in_a_parties_cell_is_a_name_of_its_own(self):
        write(self.root / "System" / "context.md",
              CONTEXT.replace("| Acme Corp | Client.", "| **Acme Corp** (product Lanternfish) | Client."))
        self.context = garrick_lib.load_context(self.root)
        write(self.entities / "lanternfish.md", entity("Lanternfish"))
        self.assertEqual(("", []), self.propose("Theo Marsh", "birch", "Now at Lanternfish."))
        write(self.entities / "product-hall.md", entity("Product Hall"))   # the lead word alone reads as nobody's
        self.assertEqual(("[[wiki/entities/product-hall]]", []), self.propose("Theo Marsh", "birch", "At Product Hall."))



# ---------------------------------------------------------------------------
# The third review: a person page's frontmatter has a strict shape
# ---------------------------------------------------------------------------

B = '"[[wiki/entities/birch-co]]"'
HEAD = "title: Pat Newcomer\ntype: person\nparty: acme\n"
TAIL = "created: 2026-03-10\nupdated: 2026-03-10\n"


def doc(front: str, opener: str = "---", closer: str = "---", nl: str = "\n", bom: str = "") -> str:
    return ("%s%s\n%s\n%s%s\n\n# Pat Newcomer\n\nConsultant.\n" % (bom, opener, front, TAIL, closer)).replace("\n", nl)


class ShapeTest(Workspace):
    """Every form a YAML reader turns into an `organisation:` link and a line
    reader does not, refused; every shape the tools write, passed."""

    MISREAD = {
        "bom_next_line": doc(HEAD + "organisation:\n  " + B, bom="﻿"),
        "bom_quoted_key": doc(HEAD + '"organisation": ' + B, bom="﻿"),
        "crlf_next_line": doc(HEAD + "organisation:\n  " + B, nl="\r\n"),
        "cr_only": doc(HEAD + "organisation:\n  " + B, nl="\r"),
        "opener_trailing_space": doc(HEAD + "organisation:\n  " + B, opener="--- "),
        "closer_dots": doc(HEAD + "organisation:\n  " + B, closer="..."),
        "block_scalar_dashes": doc(HEAD + "note: |\n  ---\norganisation:\n  " + B),
        "block_scalar_dots": doc(HEAD + "note: |\n  ...\norganisation:\n  " + B),
        "flow_whole_doc": doc("{title: Pat Newcomer, type: person, party: acme, organisation: %s}" % B),
        "flow_anchor_merge": doc(HEAD + "base: &b {organisation: %s}\n<<: *b" % B),
        "block_anchor_merge": doc(HEAD + "base: &b\n  organisation: %s\n<<: *b" % B),
        "escaped_key_x": doc(HEAD + '"organi\\x73ation": ' + B),
        "escaped_key_u": doc(HEAD + '"organi\\u0073ation": ' + B),
        "single_quoted_key": doc(HEAD + "'organisation': " + B),
        "cyrillic_o_key": doc(HEAD + "оrganisation: " + B),
        "fullwidth_key": doc(HEAD + "ｏrganisation: " + B),
        "zero_width_key": doc(HEAD + "organi​sation: " + B),
        "complex_key": doc(HEAD + "? [organisation]\n: " + B),
        "tag_key": doc(HEAD + "!!str organisation: " + B),
        "anchor_key": doc(HEAD + "&k organisation: " + B),
        "value_tag": doc(HEAD + "organisation: !!str " + B),
        "value_alias": doc(HEAD + "x: &v " + B + "\norganisation: *v"),
        "json_style": doc(HEAD + '{"organisation": %s}' % B),
        "tab_value": doc(HEAD + "organisation:\n\t" + B),
        "comment_between": doc(HEAD + "organisation:\n# c\n  " + B),
        "blank_between": doc(HEAD + "organisation:\n\n  " + B),
        "organization": doc(HEAD + "organization: " + B),
        "twice": doc(HEAD + 'organisation: ""\norganisation: ' + B),
        "list_under_it": doc(HEAD + "organisation:\n  - " + B),
        "no_closer": "---\n" + HEAD + "organisation: " + B + "\n\n# Pat\n",
    }

    def test_every_misread_form_fails_the_shape(self):
        for name, text in self.MISREAD.items():
            self.assertTrue(check.person_shape_problem(text), name)

    def test_the_shapes_the_tools_write_pass(self):
        texts = [person("Kit \"Kestrel\" Avery", "none", "Architect.", "[[wiki/entities/birch-co]]"),
                 "---\ntitle: Mira Holt\ntype: person\nparty:\n  - acme\naliases:\n- Mira\norganisation:\n---\n",
                 "---\ntitle: Rowan Blake\ntype: person\nparty: [acme, birch]\n---\n\n# Rowan Blake\n",
                 "---\ntitle: Ana\ntype: person\nparty: ['acme', \"birch\"]\norganisation: [[wiki/entities/x|X]]\n---\n",
                 "# No frontmatter at all\n", "---\r\ntitle: Ana\r\ntype: person\r\nparty: none\r\n---\r\n"]
        path, _ = ingest.ensure_person(self.root, "Mira Holt", "acme", "2026-03-10", "acme-corp")
        texts.append(path.read_text())
        demo = REPO / "examples" / "demo" / "content" / "Wikis" / "Meetings" / "wiki" / "people"
        texts += [p.read_text(encoding="utf-8") for p in sorted(demo.glob("*.md"))]
        schema = (REPO / "template" / "Wikis" / "Meetings" / "AGENTS.md").read_text(encoding="utf-8")
        block = schema.split("## A person page", 1)[1].split("```yaml\n", 1)[1].split("```", 1)[0]
        texts.append(block.replace("<their name>", "Kit Avery").replace("<tag>", "none"))
        for text in texts:
            self.assertFalse(check.person_shape_problem(text), text[:120])

    def test_a_two_hat_flow_list_passes_the_shape_and_still_meets_the_wall(self):
        text = "---\ntitle: Pat Newcomer\ntype: person\nparty: [acme, birch]\n---\n\n# Pat Newcomer\n\nAt Larch Partners.\n"
        self.assertFalse(check.person_shape_problem(text))
        write(self.people / "pat-newcomer.md", text.replace("party: [acme, birch]\n",
                                                            'party: [acme, birch]\norganisation: "[[wiki/entities/larch-partners]]"\n'))
        found = self.findings("walls")
        self.assertEqual(["Wikis/Meetings/wiki/people/pat-newcomer.md"], [f.path for f in found])
        self.assertTrue(found[0].message.endswith("a wall stands between acme and birch"), found[0].message)
        self.assertEqual(("", []), self.propose("Pat Newcomer", ["acme", "birch"], "At Larch Partners."))

    def test_the_hook_refuses_a_misread_page_in_plain_words(self):
        for name, text in self.MISREAD.items():
            write(self.people / ("pat-%s.md" % name.replace("_", "-")), text)
        found = self.findings("walls")
        self.assertEqual(sorted("Wikis/Meetings/wiki/people/pat-%s.md" % n.replace("_", "-") for n in self.MISREAD),
                         sorted(f.path for f in found))
        for f in found:
            self.assertTrue(f.message.startswith(check.PERSON_SHAPE), (f.path, f.message))

    def test_a_symlinked_person_page_is_not_read(self):
        outside = write(Path(self._tmp.name) / "outside.md", person("Pat Newcomer", "acme", "x.",
                                                                    "[[wiki/entities/birch-co]]"))
        self.people.mkdir(parents=True, exist_ok=True)
        os.symlink(str(outside), str(self.people / "pat-newcomer.md"))
        self.assertEqual([], [p for p, _ in check.person_pages(check.discover(self.root, None))
                              if p.name == "pat-newcomer.md"])


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class OrganisationActionTest(Workspace):
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
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant at Larch Partners."))
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Architect at Birch & Co.")
              .replace("party: none\n", 'party: none\nOrganisation: "[[wiki/entities/larch-partners]]"\n'))
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")
        self.head = git(self.wikis, "rev-parse", "HEAD").strip()

    def organisation(self, page: str, *more: str, env=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = nurture.main(["organisation", "--path", "Wikis/Meetings/wiki/people/%s" % page, "--root",
                                 str(self.root), "--today", "2026-10-17", "--yes"] + list(more))
        return code, err.getvalue()

    def test_the_walls_check_runs_on_the_staged_change_with_no_hook(self):
        before = (self.people / "pat-newcomer.md").read_text()
        with mock.patch.object(nurture, "organisation_proposal",
                               lambda *a, **k: ("[[wiki/entities/birch-co]]", [])):      # a proposal gone wrong
            code, err = self.organisation("pat-newcomer.md")
        self.assertNotEqual(0, code)
        self.assertIn("the walls check refused it", err)
        self.assertEqual(before, (self.people / "pat-newcomer.md").read_text())
        self.assertEqual(self.head, git(self.wikis, "rev-parse", "HEAD").strip())
        self.assertEqual("", git(self.wikis, "diff", "--cached", "--name-only").strip())

    def test_a_variant_organisation_key_already_there_is_refused(self):
        before = (self.people / "kit-avery.md").read_text()
        code, err = self.organisation("kit-avery.md")
        self.assertNotEqual(0, code)
        self.assertIn("nothing was written", err)
        self.assertEqual(before, (self.people / "kit-avery.md").read_text())

    def test_any_value_of_garrick_headless_but_0_means_nobody_is_watching(self):
        for value in ("1", "yes", "true", " on "):
            code, err = self.organisation("pat-newcomer.md", env={"GARRICK_HEADLESS": value})
            self.assertNotEqual(0, code, value)
            self.assertIn("never with nobody watching", err)
        code, err = self.organisation("pat-newcomer.md", env={"GARRICK_HEADLESS": "0"})
        self.assertEqual(0, code, err)
        self.assertIn('organisation: "[[wiki/entities/larch-partners]]"', (self.people / "pat-newcomer.md").read_text())


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class CorrectionAcrossAWallTest(Workspace):
    def test_correct_never_rewrites_an_organisation_across_a_wall(self):
        env = {k: v for k, v in GIT_ENV.items() if k.startswith("GIT_")}
        env.pop("GIT_DIR", None)
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("GARRICK_HEADLESS", None)
        wikis = self.root / "Wikis"
        git(wikis, "init", "-q")
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer.", "[[wiki/entities/larch-partners]]"))
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Buyer.", "[[wiki/entities/larch-partners]]"))
        git(wikis, "add", "-A")
        git(wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            nurture.main(["correct", "--old", "wiki/entities/larch-partners", "--new", "wiki/entities/birch-co", "--yes",
                          "--root", str(self.root), "--today", "2026-10-17"])
        self.assertIn("[[wiki/entities/larch-partners]]", (self.people / "pat-newcomer.md").read_text())
        self.assertIn("[[wiki/entities/birch-co]]", (self.people / "kit-avery.md").read_text())   # walled from nobody
        self.assertIn(nurture.WALL_REFUSAL, out.getvalue())
        self.assertEqual([], [f for f in check.run_checks(self.root, walls_only=True)])



# ---------------------------------------------------------------------------
# The fourth review
# ---------------------------------------------------------------------------

class LineBreakTest(Workspace):
    """A character str.splitlines() ends a line at, and YAML reads as text,
    cannot hide or shadow a key from Garrick's frontmatter reader."""

    BREAKS = (" ", " ", "\x85", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e")

    def test_the_shape_refuses_each_of_them(self):
        for ch in self.BREAKS:
            text = doc(HEAD + "note: 'x%s---%sy'\norganisation: %s" % (ch, ch, B))
            self.assertTrue(check.person_shape_problem(text), repr(ch))

    def test_the_reader_ends_lines_at_newline_alone(self):
        for ch in (" ", " ", "\x85"):
            text = doc(HEAD + "note: 'x%s---%sy'\norganisation: %s" % (ch, ch, B))
            fm = garrick_lib.parse_frontmatter_text(text)
            self.assertEqual("[[wiki/entities/birch-co]]", fm.get("organisation"), repr(ch))
            self.assertEqual("x%s---%sy" % (ch, ch), fm.get("note"), repr(ch))
        self.assertEqual({"title": "Ana", "party": "none"},
                         garrick_lib.parse_frontmatter_text("---\r\ntitle: Ana\r\nparty: none\r\n---\r\nBody.\r\n"))

    def test_the_hook_refuses_a_hidden_link(self):
        write(self.people / "pat-newcomer.md", doc(HEAD + "note: 'x --- y'\norganisation: " + B))
        found = self.findings("walls")
        self.assertEqual(["Wikis/Meetings/wiki/people/pat-newcomer.md"], [f.path for f in found])

    def test_a_colon_space_in_a_plain_value_or_item_is_a_mapping(self):
        for front in (HEAD + 'aliases:\n- organisation: ' + B, HEAD + "aliases:\n  - organisation:",
                      HEAD + 'note: 2026-03-10 # organisation: ' + B, HEAD + "note: Lead: Pricing"):
            self.assertTrue(check.person_shape_problem(doc(front)), front)
        self.assertFalse(check.person_shape_problem(doc(HEAD + 'note: "Lead: Pricing"')))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class EveryCommitCheckedTest(Workspace):
    """Every Nurture commit runs the walls check on its staged change first,
    whether or not the repository has a hook, and puts it back if refused."""

    def setUp(self):
        super().setUp()
        env = {k: v for k, v in GIT_ENV.items() if k.startswith("GIT_")}
        env.pop("GIT_DIR", None)
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("GARRICK_HEADLESS", None)
        write(self.root / "System" / "context.md", CONTEXT)        # Cedar is walled from nobody
        self.context = garrick_lib.load_context(self.root)
        self.wikis = self.root / "Wikis"
        git(self.wikis, "init", "-q")
        write(self.entities / "ledger.md", entity("Ledger Co", "cedar"))
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer.", "[[wiki/entities/ledger]]"))
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")
        self.head = git(self.wikis, "rev-parse", "HEAD").strip()

    def run_tool(self, *args: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = nurture.main(list(args) + ["--root", str(self.root), "--today", "2026-10-17"])
        return code, out.getvalue(), err.getvalue()

    def test_a_correction_to_an_entity_page_that_puts_a_link_across_a_wall_is_put_back(self):
        ledger = (self.entities / "ledger.md").read_text()
        for old, new in (("Ledger Co", "Birch & Co"), ("party: cedar", "party: birch")):
            code, said, _ = self.run_tool("correct", "--old", old, "--new", new, "--yes")
            self.assertNotEqual(0, code, (old, said))
            self.assertIn("the walls check refused it", said)
            self.assertEqual(ledger, (self.entities / "ledger.md").read_text(), old)
            self.assertEqual(self.head, git(self.wikis, "rev-parse", "HEAD").strip(), old)
            self.assertEqual("", git(self.wikis, "diff", "--cached", "--name-only").strip(), old)
        self.assertEqual([], check.run_checks(self.root, walls_only=True))

    def test_a_fix_refused_by_the_walls_check_is_put_back(self):
        calls = []
        with mock.patch.object(nurture, "walls_refusal", lambda ctx, repo: calls.append(repo) or "refused here"):
            code, said, _ = self.run_tool("correct", "--old", "Buyer.", "--new", "Lead buyer.", "--yes")
        self.assertEqual([self.wikis.resolve()], [Path(r).resolve() for r in calls])
        self.assertNotEqual(0, code)
        self.assertIn("Buyer.", (self.people / "pat-newcomer.md").read_text())
        self.assertEqual(self.head, git(self.wikis, "rev-parse", "HEAD").strip())

    def test_the_organisation_action_commits_only_what_it_checked(self):
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Architect at Larch Partners."))
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "kit")
        write(self.wikis / "Meetings" / "wiki" / "scratch.md", "Another session's work.\n")
        git(self.wikis, "add", "--", "Meetings/wiki/scratch.md")                 # staged by somebody else
        real = nurture.walls_refusal

        def changed_after_reading(ctx, repo):                                     # the page changes once checked
            said = real(ctx, repo)
            page = self.people / "kit-avery.md"
            page.write_text(page.read_text().replace("Architect", "Architect and buyer"))
            return said
        head = git(self.wikis, "rev-parse", "HEAD").strip()
        with mock.patch.object(nurture, "walls_refusal", changed_after_reading):
            code, _, err = self.run_tool("organisation", "--path", "Wikis/Meetings/wiki/people/kit-avery.md", "--yes")
        self.assertNotEqual(0, code)
        self.assertIn("changed again after the walls check read it", err)
        self.assertEqual(head, git(self.wikis, "rev-parse", "HEAD").strip())
        git(self.wikis, "checkout", "--", "Meetings/wiki/people/kit-avery.md")
        code, _, err = self.run_tool("organisation", "--path", "Wikis/Meetings/wiki/people/kit-avery.md", "--yes")
        self.assertEqual(0, code, err)
        self.assertEqual(["Meetings/wiki/people/kit-avery.md"],
                         git(self.wikis, "show", "--name-only", "--format=", "HEAD").split())
        self.assertEqual("Meetings/wiki/scratch.md", git(self.wikis, "diff", "--cached", "--name-only").strip())

    def test_a_walls_check_that_does_not_finish_puts_the_page_back(self):
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Architect at Larch Partners."))
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "kit")
        head = git(self.wikis, "rev-parse", "HEAD").strip()
        before = (self.people / "kit-avery.md").read_text()
        real = subprocess.run

        def slow(cmd, *a, **k):
            if any(str(c).endswith("check.py") for c in cmd):
                raise subprocess.TimeoutExpired(cmd, 600)
            return real(cmd, *a, **k)
        with mock.patch.object(nurture.subprocess, "run", slow):
            code, _, err = self.run_tool("organisation", "--path", "Wikis/Meetings/wiki/people/kit-avery.md", "--yes")
        self.assertNotEqual(0, code)
        self.assertIn("did not finish", err)
        self.assertEqual(before, (self.people / "kit-avery.md").read_text())
        self.assertEqual(head, git(self.wikis, "rev-parse", "HEAD").strip())

    def test_a_correction_held_back_by_a_wall_says_only_the_wall_sentence(self):
        code, said, _ = self.run_tool("correct", "--old", "wiki/entities/ledger", "--new", "wiki/entities/birch-co",
                                      "--yes")
        self.assertIn(nurture.WALL_REFUSAL, said)
        self.assertNotIn("Nothing live holds", said)
        self.assertIn("[[wiki/entities/ledger]]", (self.people / "pat-newcomer.md").read_text())



# ---------------------------------------------------------------------------
# The final review
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAVE_GIT, "git is not installed")
class CorrectPyTest(Workspace):
    """`correct.py --apply`, run directly as the threads skill runs it, has
    the walls check run on every commit inside correct.apply() itself."""

    def test_a_direct_correction_that_crosses_a_wall_is_refused_and_put_back(self):
        write(self.root / "System" / "context.md", CONTEXT)
        wikis = self.root / "Wikis"
        git(wikis, "init", "-q")
        write(self.entities / "ledger.md", entity("Ledger Co", "cedar"))
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer.", "[[wiki/entities/ledger]]"))
        git(wikis, "add", "-A")
        git(wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")
        head = git(wikis, "rev-parse", "HEAD").strip()
        files = {p: p.read_bytes() for p in (self.entities / "ledger.md", self.people / "pat-newcomer.md")}
        for old, new in (("Ledger Co", "Birch & Co"), ("party: cedar", "party: birch"),
                         ("wiki/entities/ledger", "wiki/entities/birch-co")):
            r = subprocess.run([sys.executable, str(TOOLS / "correct.py"), "--root", str(self.root), "--old", old,
                                "--new", new, "--apply", "--why", "test"], capture_output=True, text=True, env=GIT_ENV)
            self.assertEqual(1, r.returncode, (old, r.stdout, r.stderr))
            self.assertIn("the walls check refused it", r.stdout)
            self.assertNotIn("Nothing live holds", r.stdout)
            self.assertEqual(files, {p: p.read_bytes() for p in files}, old)
            self.assertEqual(head, git(wikis, "rev-parse", "HEAD").strip(), old)
            self.assertEqual("", git(wikis, "diff", "--cached", "--name-only").strip(), old)

    def test_correct_apply_checks_walls_unless_given_its_own_check(self):
        import correct
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Buyer at Larch Partners."))
        wikis = self.root / "Wikis"
        git(wikis, "init", "-q")
        git(wikis, "add", "-A")
        git(wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")
        seen = []
        with mock.patch.object(correct, "walls_refusal", lambda root, repo: seen.append(repo) or ""):
            done = correct.apply(self.root, "Buyer at", "Lead buyer at", rebuild=False)
        self.assertEqual([wikis.resolve()], [Path(r).resolve() for r in seen])
        self.assertEqual(1, len(done.commits))
        done = correct.apply(self.root, "Lead buyer at", "Buyer at", rebuild=False, verify=lambda repo: "no")
        self.assertEqual([("Wikis", "no")], done.refused)
        self.assertIn("Lead buyer at", (self.people / "kit-avery.md").read_text())


class LoneCarriageReturnTest(Workspace):
    def test_a_lone_cr_ends_a_line_for_every_reader(self):
        self.assertEqual({"title": "Acme Corp", "party": "acme"},
                         garrick_lib.parse_frontmatter_text("---\rtitle: Acme Corp\rparty: acme\r---\r\rBody.\r"))
        for nl in ("\n", "\r", "\r\n"):
            text = "---\ntitle: Acme Corp\ntype: entity\nparty: acme\n---\n\n# Acme Corp\n\nSee [[260312-birch-kickoff]].\n"
            (self.entities / "acme-corp.md").write_bytes(text.replace("\n", nl).encode())
            found = [f for f in check.run_checks(self.root) if f.path.endswith("acme-corp.md") and "across a wall" in f.message]
            self.assertEqual(1, len(found), repr(nl))

    def test_the_shape_still_refuses_a_lone_cr_in_a_person_page(self):
        self.assertTrue(check.person_shape_problem("---\rtitle: Kit Avery\rtype: person\rparty: none\r---\r"))


if __name__ == "__main__":
    unittest.main()
