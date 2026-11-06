"""The wall decision, run from the cases table.

    cd tests && python3 -m unittest test_decide

`walls/cases.md` is the one table of what every enforcement point must
answer; this module runs its decide() rows against `garrick_lib.decide()`
alone, with roles standing for the fixture's tags.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import TOOLS, meeting_page, write  # noqa: E402,F401

import walls_fixture  # noqa: E402

import garrick_lib as lib  # noqa: E402

CASES = Path(__file__).resolve().parent / "walls" / "cases.md"
ROLES = {"near": "acme", "far": "birch", "other": "cedar", "hat": "lumen", "hat2": "lumen-adv",
         "ghost": "ghost", "public": "public"}
CONTEXT = {
    "parties": {"acme": {"party": "Acme Corp"}, "birch": {"party": "Birch & Co"}, "cedar": {"party": "Cedar Ltd"},
                "lumen": {"party": "Harbour Systems"}, "lumen-adv": {"party": "Harbour Systems"}},
    "walls": {frozenset(("acme", "birch")), frozenset(("lumen", "lumen-adv"))},
}


def tags(cell: str):
    """A scope or a labels cell as the decide() argument: `-` is none, `?` is None."""
    cell = cell.strip()
    if cell == "?":
        return None
    if cell == "*":
        return None
    if cell == "-":
        return set()
    return {ROLES[c.strip()] for c in cell.split(",")}


def rows():
    return lib.wall_cases(CASES.read_text(encoding="utf-8"))["decide()"]


class DecideCases(unittest.TestCase):
    def test_every_row(self):
        table = rows()
        self.assertGreaterEqual(len(table), 40)
        for ident, scope, labels, action, expect, source in table:
            with self.subTest(case=ident, source=source):
                scope_tags = tags(scope)
                if expect == "error":
                    with self.assertRaises(ValueError):
                        lib.decide(scope_tags, tags(labels), action, CONTEXT)
                else:
                    self.assertEqual(lib.decide(scope_tags, tags(labels), action, CONTEXT), expect, source)

    def test_ids_are_unique_and_tags_are_known(self):
        ids = [r[0] for r in rows()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_wall_is_read_the_same_both_ways(self):
        for action in ("read", "write", "file"):
            self.assertEqual(lib.decide({"acme"}, {"birch"}, action, CONTEXT),
                             lib.decide({"birch"}, {"acme"}, action, CONTEXT))

    def test_a_tag_wrapped_in_backticks_is_the_tag(self):
        self.assertEqual(lib.decide({"`acme`"}, {"`birch`"}, "read", CONTEXT), "deny")

    def test_crossings_name_the_pair(self):
        self.assertEqual(lib.crossings(CONTEXT, {"acme", "cedar"}, {"birch"}), [("acme", "birch")])
        self.assertEqual(lib.crossings(CONTEXT, {"birch", "acme", "cedar"}), [("acme", "birch")])
        self.assertEqual(lib.crossings(CONTEXT, {"acme"}, set()), [])


class LabelCases(unittest.TestCase):
    """The labels() rows of the cases table, on the fixture workspace."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = walls_fixture.build(Path(cls.tmp.name) / "ws")
        wiki = cls.root / "Wikis" / "Meetings" / "wiki"
        write(wiki / "sources" / "260320-one.md",
              meeting_page("Work", "[acme]", "One").replace("people:", 'transcript: "[[raw/260320-one-call]]"\npeople:'))
        write(cls.root / "Wikis" / "Meetings" / "raw" / "260320-one-call.txt", "Words.\n")
        write(cls.root / "Wikis" / "Knowledge" / "wiki" / "concepts" / "owned.md",
              "---\ntitle: Owned\nparties: [acme]\n---\n\n# Owned\n")
        write(cls.root / "Wikis" / "Meetings" / "wiki" / "people" / "kai-ross.md",
              "---\ntitle: Kai Ross\ntype: person\nparty: acme\n---\n\n# Kai Ross\n")
        inbox = cls.root / "Zones" / "Work" / "Inbox"
        write(inbox / "far.eml", "From: Kai <kai@birchco.example>\nTo: jo@example.invalid\nSubject: Hi\n\nHello.\n")
        write(inbox / "web.eml", "From: Kai <kai@gmail.com>\nTo: jo@example.invalid\nSubject: Hi\n\nHello.\n")
        write(inbox / "stamped.eml", "X-Garrick-Parties: acme, birch\nFrom: Kai <kai@gmail.com>\nSubject: Hi\n\nHello.\n")
        write(cls.root / "Zones" / "Work" / "NoHub" / "x.md", "# x\n")
        cls.ctx = lib.load_context(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def got(self, rel):
        return lib.labels(self.root, rel, self.ctx)

    def test_project_files_take_their_hub_and_thread(self):
        self.assertEqual(self.got("Zones/Work/Northwind/Threads/Pricing/Notes.md"), {"acme"})
        self.assertEqual(self.got("Zones/Work/Harbour/Threads/Sizing/Notes.md"), {"birch"})
        self.assertEqual(self.got("Zones/Work/Northwind/Threads/Odd/Notes.md"), {"acme", "birch"})
        self.assertEqual(self.got("Zones/Work/Northwind"), {"acme", "birch"})

    def test_a_project_with_no_party_is_unlabelled_and_not_public(self):
        self.assertIsNone(self.got("Zones/Work/Orchard/Threads/Drafts/Drafts.md"))
        self.assertIsNone(self.got("Zones/Work/NoHub/x.md"))
        self.assertEqual(self.got("Zones/Work/Reed/Threads/Notes/Notes.md"), {"public"})

    def test_a_page_whose_party_and_parties_disagree_has_no_label(self):
        self.assertIsNone(self.got("Wikis/Meetings/wiki/sources/260315-split.md"))
        self.assertIsNone(self.got("Wikis/Meetings/wiki/sources/260318-unfinished.md"))
        self.assertEqual(self.got("Wikis/Meetings/wiki/people/kai-ross.md"), {"acme"})
        self.assertEqual(self.got("Wikis/Meetings/wiki/sources/260310-acme-kickoff.md"), {"acme"})

    def test_a_raw_record_takes_every_page_that_cites_it(self):
        self.assertEqual(self.got("Wikis/Meetings/raw/260320-one-call.txt"), {"acme"})
        self.assertEqual(self.got("Wikis/Meetings/raw/260317-both-call.txt"), {"acme", "birch"})
        self.assertIsNone(self.got("Wikis/Meetings/raw/260319-orphan-call.txt"))

    def test_knowledge_is_public_unless_it_says_otherwise(self):
        self.assertEqual(self.got("Wikis/Knowledge/wiki/concepts/resilience.md"), {"public"})
        self.assertEqual(self.got("Wikis/Knowledge/wiki/concepts/owned.md"), {"acme"})

    def test_mail_takes_its_domains_or_its_stamp(self):
        self.assertEqual(self.got("Zones/Work/Inbox/far.eml"), {"birch"})
        self.assertIsNone(self.got("Zones/Work/Inbox/web.eml"))
        self.assertEqual(self.got("Zones/Work/Inbox/stamped.eml"), {"acme", "birch"})

    def test_a_path_outside_the_workspace_has_no_label(self):
        self.assertIsNone(lib.labels(self.root, "../elsewhere.md", self.ctx))
        self.assertIsNone(lib.labels(self.root, "Zones/Work/Todo.md", self.ctx))

    def test_the_rows_of_the_table_are_all_covered(self):
        self.assertEqual(len(lib.wall_cases(CASES.read_text(encoding="utf-8"))["labels()"]), 20)


if __name__ == "__main__":
    unittest.main()
