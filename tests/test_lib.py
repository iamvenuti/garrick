"""Unit tests for garrick_lib."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fixtures import CONTEXT, write

import garrick_lib as lib  # noqa: E402  (fixtures puts the tools folder on sys.path)


class TestFrontmatter(unittest.TestCase):
    def parse(self, text):
        return lib.parse_frontmatter_text(text)

    def test_scalars_quotes_and_comments(self):
        fm = self.parse(
            "---\n"
            "title: Acme kick-off\n"
            "zone: Work   # the zone\n"
            "project: \"[[Acme Review]]\"\n"
            "quoted: 'it''s # not a comment'\n"
            "empty:\n"
            "---\n# Body\n"
        )
        self.assertEqual("Acme kick-off", fm["title"])
        self.assertEqual("Work", fm["zone"])
        self.assertEqual("[[Acme Review]]", fm["project"])
        self.assertEqual("it's # not a comment", fm["quoted"])
        self.assertIsNone(fm["empty"])

    def test_inline_list(self):
        fm = self.parse("---\nparties: [acme, birch]      # tags\npeople: [\"[[wiki/people/a, b]]\", 'c']\n---\n")
        self.assertEqual(["acme", "birch"], fm["parties"])
        self.assertEqual(["[[wiki/people/a, b]]", "c"], fm["people"])

    def test_block_list(self):
        fm = self.parse("---\nparties:\n  - acme\n  - \"birch\"\nzone: Work\n---\n")
        self.assertEqual(["acme", "birch"], fm["parties"])
        self.assertEqual("Work", fm["zone"])

    def test_unquoted_wikilink_is_a_scalar(self):
        self.assertEqual("[[Acme Review]]", self.parse("---\nproject: [[Acme Review]]\n---\n")["project"])

    def test_no_frontmatter(self):
        self.assertEqual({}, self.parse("# Just a note\n"))
        self.assertEqual({}, self.parse("---\ntitle: never closed\n"))

    def test_from_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(Path(tmp) / "a.md", "﻿---\ntype: project\n---\n")
            self.assertEqual({"type": "project"}, lib.parse_frontmatter(p))
            self.assertEqual({}, lib.parse_frontmatter(Path(tmp) / "missing.md"))


class TestSpeakable(unittest.TestCase):
    def test_good_names(self):
        for name in ("Work", "Acme Review", "Birch & Co", "O'Neill Pricing", "Go-to-market", "Café Opening"):
            self.assertEqual((True, ""), lib.is_speakable(name), name)

    def test_bad_names(self):
        cases = {
            "": "empty",
            "   ": "empty",
            "_project": "underscore",
            "Q3 Plan": "digit",
            "2026-03 Review": "digit",
            "pricing_v": "underscore",
            "Acme.Review": "'.'",
            "Acme/Birch": "'/'",
            "&": "no letters",
            " Acme": "space",
        }
        for name, reason in cases.items():
            ok, why = lib.is_speakable(name)
            self.assertFalse(ok, name)
            self.assertIn(reason, why, name)


class TestSoundsAlike(unittest.TestCase):
    def test_alike(self):
        for a, b in [
            ("Pricing", "pricing"),
            ("Birch & Co", "Birch and Co"),
            ("Blue Bird", "Bluebird"),
            ("Pricing", "Prizing"),
            ("Acme", "Akme"),
            ("Philips", "Fillips"),
            ("Contract", "Contracts"),
            ("Knight", "Night"),
        ]:
            self.assertTrue(lib.sounds_alike(a, b), (a, b))

    def test_distinct(self):
        for a, b in [
            ("Pricing", "Procurement"),
            ("Operations", "Opportunities"),
            ("Work", "Personal"),
            ("Supply Review", "Market Entry"),
            ("Tax", "Tip"),
            ("Acme Review", "Birch Entry"),
        ]:
            self.assertFalse(lib.sounds_alike(a, b), (a, b))

    def test_one_edit_counts_only_from_four_letters(self):
        self.assertEqual(1, lib.edit_distance("tax", "tab"))
        self.assertFalse(lib.sounds_alike("Tax", "Tab"))
        self.assertTrue(lib.sounds_alike("Tabs", "Taps"))


class TestContext(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write(self.root / "System" / "rules.md", "# Rules\n")
        write(self.root / "System" / "context.md", CONTEXT)
        self.ctx = lib.load_context(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_parties(self):
        self.assertEqual({"acme", "birch"}, set(self.ctx["parties"]))
        self.assertEqual({"party": "Birch & Co", "what": "Client. Market-entry advice; competes with Acme", "zone": "Work",
                          "domains": ["birchco.example", "mail.birchco.example"]},
                         self.ctx["parties"]["birch"])
        self.assertEqual(["acmecorp.example"], self.ctx["parties"]["acme"]["domains"])

    def test_walls(self):
        self.assertEqual({frozenset({"acme", "birch"})}, self.ctx["walls"])
        self.assertTrue(lib.walled(self.ctx, "acme", "birch"))
        self.assertTrue(lib.walled(self.ctx, "`birch`", "acme"))
        self.assertFalse(lib.walled(self.ctx, "acme", "acme"))
        self.assertFalse(lib.walled(self.ctx, "acme", ""))

    def test_people_and_aliases(self):
        self.assertEqual({"name": "Theo Marsh", "party": "birch", "role": "Managing partner"}, self.ctx["people"][1])
        self.assertEqual("Birch & Co", self.ctx["aliases"]["birchen co"])
        self.assertEqual("Birch & Co", self.ctx["aliases"]["birch and co"])
        self.assertEqual("Dana Whitlock", self.ctx["aliases"]["dana whitlaw"])

    def test_zones(self):
        self.assertEqual(["Work", "Personal"], list(self.ctx["zones"]))

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = lib.load_context(tmp)
        self.assertEqual({}, ctx["parties"])
        self.assertEqual(set(), ctx["walls"])


class TestWorkspaceRoot(unittest.TestCase):
    def test_walks_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write(root / "System" / "rules.md", "# Rules\n")
            deep = root / "Zones" / "Work" / "Acme Review"
            deep.mkdir(parents=True)
            note = write(deep / "Acme Review.md", "x")
            self.assertEqual(root, lib.workspace_root(deep))
            self.assertEqual(root, lib.workspace_root(note))
            self.assertEqual(root, lib.workspace_root(root))

    def test_none_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                lib.workspace_root(tmp)


if __name__ == "__main__":
    unittest.main()
