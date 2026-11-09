"""The owner's own name is no walled name, and an everyday-word tag is only a tag (#458); a party's name is plain
text (#457).

    cd tests && python3 -m unittest test_owner_names

The fixture is built here: the owner is Jo Example, her own party is walled and named after her, an employer
is walled and has a person, Jo Smith, who shares her first name, and a client sits in a third zone.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import fixtures  # noqa: E402  (puts the tools folder on sys.path)
from fixtures import write  # noqa: E402

import check  # noqa: E402
import garrick_lib  # noqa: E402

CONTEXT = """\
# Context

## Me

**Jo Example**. Independent advisor.

## Zones

| Zone | Holds | Party | New parties |
|---|---|---|---|
| Employer | The employer | | walled |
| Private | Her own affairs | | walled |
| Clients | Client work | | walled |

## Parties

| Party | What it is | Zone | Tag | Walled | Domains |
|---|---|---|---|---|---|
| **Employer Ltd** | Employer | Employer | `emp` | yes | employer.example |
| **Jo Example** | Her own affairs | Private | `jo` | yes | |
| Own Affairs | Money and travel | Private | `private` | yes | |
| Acme Corp | Client | Clients | `acme` | yes | acme.example |

## People

| Name | Party | Role |
|---|---|---|
| **Jo Smith** | `emp` | Colleague |
| Dana Whitlock | `acme` | Procurement |

## Aliases

| Heard | Means |
|---|---|
"""


def build(root: Path) -> Path:
    write(root / "AGENTS.md", "# Workspace\n")
    write(root / "System" / "rules.md", "# Rules\n")
    write(root / "System" / "context.md", CONTEXT)
    for zone in ("Employer", "Private", "Clients"):
        (root / "Zones" / zone / ".git").mkdir(parents=True)
        write(root / "Zones" / zone / "AGENTS.md", "# %s\n" % zone)
    project = root / "Zones" / "Clients" / "Acme Review"
    write(project / "Acme Review.md", fixtures.project_hub("Clients", "Acme Review", "acme", ["Pricing"]))
    write(project / "Threads" / "Pricing" / "Pricing.md", fixtures.thread_note("Acme Review", "Pricing", "acme"))
    return root


class OwnerNamesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = build(Path(self._tmp.name).resolve())
        self.ws = check.discover(self.root)
        self.ws.quick = True
        self.project = self.root / "Zones" / "Clients" / "Acme Review"

    def refused(self, text: str) -> bool:
        note = self.project / "Threads" / "Pricing" / "Notes.md"
        found = check.walls_for_file(self.ws, self.project, {"acme"}, note, text)
        return any(f.severity == "error" and f.check == "walls" for f in found)

    def test_the_owner_is_read_from_the_me_section(self):
        self.assertEqual(self.ws.context["owner"], {"name": "Jo Example", "first": "Jo"})

    def test_a_placeholder_is_no_owner(self):
        for me in ("<Your name>.", ""):
            root = Path(self._tmp.name) / "p" / str(abs(hash(me)))
            build(root)
            text = CONTEXT.replace("**Jo Example**. Independent advisor.", me)
            (root / "System" / "context.md").write_text(text, encoding="utf-8")
            self.assertIsNone(garrick_lib.load_context(root)["owner"], me)

    def test_a_sentence_about_the_work_is_no_owner(self):
        for me in ("Emp sales engineer. Works on pricing.", "Birch consultant. Works alone.", "Jo_Ann Example. Advisor."):
            root = Path(self._tmp.name) / "q" / str(abs(hash(me)))
            build(root)
            text = CONTEXT.replace("**Jo Example**. Independent advisor.", me)
            (root / "System" / "context.md").write_text(text, encoding="utf-8")
            owner = garrick_lib.load_context(root)["owner"]
            if me.startswith("Jo_Ann"):
                self.assertEqual(owner, {"name": "Jo_Ann Example", "first": "Jo_Ann"})
            else:
                self.assertIsNone(owner, me)

    def test_a_tag_that_is_the_partys_own_name_is_matched_in_prose(self):
        text = CONTEXT.replace("| Acme Corp | Client |", "| Page | Client | Clients | `page` | yes | |\n| Acme Corp | Client |", 1)
        (self.root / "System" / "context.md").write_text(text, encoding="utf-8")
        self.ws = check.discover(self.root)
        self.ws.quick = True
        self.assertTrue(self.refused("# Notes\n\nPage wants a quote.\n"))

    def test_a_party_named_like_its_zone_is_matched_in_prose(self):
        text = CONTEXT.replace("| Clients | Client work | | walled |", "| Clients | Client work | | walled |\n| Northwind | A client's own zone | | walled |", 1)
        text = text.replace("| Acme Corp | Client |", "| Northwind | Client | Northwind | `northwind` | yes | |\n| Acme Corp | Client |", 1)
        (self.root / "System" / "context.md").write_text(text, encoding="utf-8")
        (self.root / "Zones" / "Northwind" / ".git").mkdir(parents=True)
        self.ws = check.discover(self.root)
        self.ws.quick = True
        self.assertTrue(self.refused("# Notes\n\nNorthwind asked for the figures.\n"))
        self.assertFalse(self.refused("# Notes\n\nA private matter, kept private.\n"))

    def test_the_owners_first_name_is_not_refused(self):
        self.assertFalse(self.refused("# Notes\n\nOn Jo's word, filed the quote.\n"))

    def test_the_owners_full_name_is_not_refused(self):
        self.assertFalse(self.refused("# Notes\n\nJo Example asked for the quote.\n"))

    def test_a_walled_person_with_the_owners_first_name_is_refused_by_the_full_name(self):
        self.assertTrue(self.refused("# Notes\n\nJo Smith asked for the quote.\n"))

    def test_the_other_walled_names_still_hold(self):
        self.assertTrue(self.refused("# Notes\n\nEmployer Ltd asked for the quote.\n"))

    def test_a_zone_name_tag_is_no_prose_word(self):
        self.assertFalse(self.refused("# Notes\n\nA private matter, kept private.\n"))

    def test_the_same_tag_in_parties_is_refused(self):
        self.assertTrue(self.refused("---\nparties: [private]\n---\n\n# Notes\n"))

    def test_the_same_tag_in_code_is_refused(self):
        self.assertTrue(self.refused("# Notes\n\nSee `private` for it.\n"))
        self.assertTrue(self.refused("# Notes\n\n```\nprivate\n```\n"))

    def test_another_tag_is_matched_as_before(self):
        # `emp` is no everyday word: it stays a form in prose
        self.assertTrue(self.refused("# Notes\n\nThe emp budget.\n"))


class PlainNamesTest(unittest.TestCase):
    def test_a_name_is_read_as_plain_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = garrick_lib.load_context(build(Path(tmp)))
        self.assertEqual(ctx["parties"]["emp"]["party"], "Employer Ltd")
        self.assertIn("Jo Smith", [p["name"] for p in ctx["people"]])

    def test_plain_helper(self):
        for cell in ("**Acme Corp**", "*Acme Corp*", "_Acme Corp_", "`Acme Corp`", " Acme Corp "):
            self.assertEqual(garrick_lib.plain_name(cell), "Acme Corp", cell)


if __name__ == "__main__":
    unittest.main()
