"""The walls migration and the owner's own name (#458): a party named after the owner is proposed renamed, and the
report lists the files a name would refuse once the flags are written, before the yes."""

import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import test_update  # noqa: E402  (its Case builds a real install; imported as a module so its tests are not collected twice)
from fixtures import write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


class TestOwnerNamedParty(test_update.Case):
    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(REPO / "tests"))
        import legacy_walls
        legacy_walls.build(self.root)
        self.context = self.root / "System" / "context.md"
        text = self.context.read_text(encoding="utf-8")
        # the owner's own party carries the owner's name, as a real workspace's does
        self.context.write_text(text.replace("| Jo Example | Own affairs |", "| Sam Rivera | Own affairs |"), encoding="utf-8")
        # a note outside Personal that names a walled client's person in full
        write(self.root / "Zones" / "Work" / "Northwind" / "Threads" / "Pricing" / "Notes.md",
              "# Notes\n\nDana Whitlock asked for the figures.\n")
        self.commit(self.root, "the 0.59 context")

    def study(self):
        import migrate_walls
        return migrate_walls.study(self.root, test_update.update.install.lib())

    def test_the_owner_is_the_first_sentence_of_me(self):
        import migrate_walls
        self.assertEqual({"name": "Sam Rivera", "first": "Sam"}, migrate_walls._owner(self.root))
        self.context.write_text(self.context.read_text().replace("Sam Rivera. Independent", "<Your name>. Independent"))
        self.assertEqual({}, migrate_walls._owner(self.root))
        self.context.write_text(self.context.read_text().replace("<Your name>. Independent", "**Sam Rivera**. Independent"))
        self.assertEqual("Sam Rivera", migrate_walls._owner(self.root)["name"])

    def test_a_party_named_after_the_owner_is_proposed_renamed(self):
        found = self.study()
        self.assertEqual({"jo": "Own affairs"}, found["prop"]["renames"])
        self.assertIn("| `jo` | yes | Own affairs |", found["text"])
        self.assertTrue(any("named after you" in n for n in found["prop"]["notes"]))
        import migrate_walls
        text = migrate_walls.rewrite(self.context.read_text(), found["prop"])
        self.assertIn("| Own affairs | Own affairs | Personal | `jo` | yes |", text)
        self.assertNotIn("| Sam Rivera |", text)

    def test_a_party_with_another_name_is_not_renamed(self):
        self.context.write_text(self.context.read_text().replace("| Sam Rivera | Own affairs |", "| Jo Example | Own affairs |"))
        self.assertEqual({}, self.study()["prop"]["renames"])

    def test_the_report_lists_the_files_a_name_would_refuse(self):
        found = self.study()
        self.assertTrue(found["refused"], "the check run with the flags finds the walled client's person in a Work note")
        self.assertTrue(any("Northwind/Threads/Pricing/Notes.md" in f for f in found["refused"]), found["refused"])
        self.assertIn("would refuse", found["text"])
        self.assertIn("Notes.md", found["text"])
        self.assertTrue(self.context.read_text().count("## Walls"), "the study writes nothing")


if __name__ == "__main__":
    unittest.main()
