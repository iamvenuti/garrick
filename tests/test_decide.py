"""The wall decision, run from the cases table.

    cd tests && python3 -m unittest test_decide

`walls/cases.md` is the one table of what every enforcement point must
answer; this module runs its decide() rows against `garrick_lib.decide()`
alone, with roles standing for the fixture's zones.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import TOOLS  # noqa: E402,F401

import garrick_lib as lib  # noqa: E402

CASES = Path(__file__).resolve().parent / "walls" / "cases.md"
ROLES = {"near": "Work", "far": "Home", "open": "Ventures", "ghost": "ghost-zone", "unzoned": lib.UNZONED,
         "knowledge": lib.KNOWLEDGE}
CONTEXT = {"zone_walled": {"Work": True, "Home": True, "Ventures": False}}


def zones(cell: str):
    """A scope or a labels cell as the decide() argument: `?` and `*` are None, `-` is none."""
    cell = cell.strip()
    if cell in ("?", "*"):
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
                if expect == "error":
                    with self.assertRaises(ValueError):
                        lib.decide(zones(scope), zones(labels), action, CONTEXT)
                else:
                    self.assertEqual(lib.decide(zones(scope), zones(labels), action, CONTEXT), expect, source)

    def test_ids_are_unique(self):
        ids = [r[0] for r in rows()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_zone_wrapped_in_backticks_or_in_another_case_is_the_zone(self):
        self.assertEqual(lib.decide({"`work`"}, {"HOME"}, "read", CONTEXT), "deny")
        self.assertEqual(lib.decide({"work"}, {"WORK"}, "read", CONTEXT), "permit")

    def test_a_context_with_no_zones_denies_every_zone(self):
        self.assertEqual(lib.decide({"Work"}, {"Work"}, "read", {}), "deny")

    def test_always_asked_stays_for_a_company_under_two_tags(self):
        ctx = {"parties": {"a": {"party": "Harbour Systems"}, "b": {"party": "Harbour Systems"}, "c": {"party": "Cedar"}}}
        self.assertTrue(lib.always_asked(ctx, "a"))
        self.assertFalse(lib.always_asked(ctx, "c"))


if __name__ == "__main__":
    unittest.main()
