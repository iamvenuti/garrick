"""The zone wall's model: zone_of, walled, may_flow and the zone flags load_context reads.

    cd tests && python3 -m unittest test_zones
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import TOOLS, write  # noqa: E402,F401

import garrick_lib as lib  # noqa: E402

NEW = """# Context

## Me

Jo Example. Works at Acme.

## Zones

| Zone | Holds | Walled |
|---|---|---|
| Work | the job | yes |
| Ventures | published work | no |
| Home | everything else | Yes |
| Odd | no cell | |

## Parties

| Party | What it is | Zone | Tag | Domains | Learned |
|---|---|---|---|---|---|
| Acme Corp | client | Work | `acme` | acme.example | |
"""

OLD = """# Context

## Zones

| Zone | Holds | Party | New parties |
|---|---|---|---|
| Work | the job | `acme` | open |
| Ventures | published work | | open |
| Home | everything else | `jo` | walled |
| Bare | no cells | | |

## Parties

| Party | What it is | Zone | Tag | Walled | Domains |
|---|---|---|---|---|---|
| Acme Corp | client | Work | `acme` | yes | acme.example |
| Jo Example | own | Home | `jo` | yes | |
"""

OLD059 = """# Context

## Zones

| Zone | Holds | Party | New parties |
|---|---|---|---|
| Work | the job | `acme` | open |

## Parties

| Party | What it is | Zone | Tag | Domains |
|---|---|---|---|---|
| Acme Corp | client | Work | `acme` | acme.example |

## Walls

| Between | And |
|---|---|
| `acme` | `birch` |
"""


def workspace(tmp: str, context: str) -> Path:
    root = Path(tmp)
    write(root / "System" / "context.md", context)
    for zone in ("Work", "Ventures", "Home", "Odd"):
        (root / "Zones" / zone / "Proj").mkdir(parents=True, exist_ok=True)
    return root


def page(root: Path, rel: str, zone=None) -> Path:
    head = "---\ntitle: x\n" + ("zone: %s\n" % zone if zone is not None else "") + "---\nbody\n"
    return write(root / "Wikis" / "Meetings" / rel, head)


class ZoneFlags(unittest.TestCase):
    def test_walled_column_read_and_only_no_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = lib.load_context(workspace(tmp, NEW))
        self.assertFalse(ctx["pending"])
        self.assertEqual({"Work": True, "Ventures": False, "Home": True, "Odd": True}, ctx["zone_walled"])

    def test_old_tables_derive_flags_and_are_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = lib.load_context(workspace(tmp, OLD))
        self.assertTrue(ctx["pending"])
        self.assertEqual({"Work": True, "Ventures": False, "Home": True, "Bare": True}, ctx["zone_walled"])

    def test_a_059_context_reads_every_zone_walled(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = lib.load_context(workspace(tmp, OLD059))
        self.assertTrue(ctx["pending"])
        self.assertEqual({"Work": True}, ctx["zone_walled"])

    def test_the_final_switch_reads_derived_flags_as_final(self):
        from unittest import mock
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = workspace(tmp, OLD)
            with mock.patch.dict(os.environ, {"GARRICK_ZONE_FLAGS_FINAL": "1"}):
                ctx = lib.load_context(root)
            self.assertFalse(ctx["pending"])
            self.assertEqual({"Work": True, "Ventures": False, "Home": True, "Bare": True}, ctx["zone_walled"])

    def test_no_context_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = lib.load_context(tmp)
        self.assertEqual({}, ctx["zone_walled"])
        self.assertFalse(ctx["pending"])


class ZoneOf(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = workspace(self._tmp.name, NEW)

    def test_zone_folder(self):
        self.assertEqual("Work", lib.zone_of(self.root, self.root / "Zones" / "Work" / "Proj" / "a.md"))
        self.assertEqual("Work", lib.zone_of(self.root, "Zones/Work/Proj/a.md"))
        self.assertEqual("Ventures", lib.zone_of(self.root, "Zones/ventures/Proj/a.md"))     # matched by case

    def test_outside_zones_is_none(self):
        for rel in ("System/rules.md", "Wikis/Knowledge/wiki/a.md", "AGENTS.md", "Zones/Todo.md", "Wikis/Other/a.md"):
            self.assertIsNone(lib.zone_of(self.root, rel), rel)
        self.assertIsNone(lib.zone_of(self.root, "/elsewhere/Zones/Work/a.md"))

    def test_meetings_page_takes_its_zone(self):
        p = page(self.root, "wiki/meetings/a.md", "work")
        self.assertEqual("Work", lib.zone_of(self.root, p))
        self.assertEqual("Home", lib.zone_of(self.root, page(self.root, "wiki/b.md", '"[[Home]]"')))

    def test_meetings_page_with_no_or_unknown_or_two_zones_is_unzoned(self):
        for rel, zone in (("wiki/n.md", None), ("wiki/u.md", "Nowhere"), ("wiki/two.md", "[Work, Home]"),
                          ("wiki/two2.md", "Work, Home"), ("wiki/empty.md", '""')):
            self.assertEqual(lib.UNZONED, lib.zone_of(self.root, page(self.root, rel, zone)), rel)
        self.assertEqual(lib.UNZONED, lib.zone_of(self.root, self.root / "Wikis" / "Meetings" / "wiki" / "missing.md"))

    def test_raw_record_counts_by_its_own_zone_else_unzoned(self):
        self.assertEqual("Work", lib.zone_of(self.root, page(self.root, "raw/260101 - a.md", "Work")))
        self.assertEqual(lib.UNZONED, lib.zone_of(self.root, page(self.root, "raw/inbox/b.md")))

    def test_one_zone_listed_twice_is_one_zone(self):
        self.assertEqual("Work", lib.zone_of(self.root, page(self.root, "wiki/d.md", "[Work, work]")))


class Rule(unittest.TestCase):
    CTX = {"zone_walled": {"Work": True, "Home": True, "Ventures": False}}

    def test_walled(self):
        self.assertFalse(lib.walled(self.CTX, None))
        self.assertTrue(lib.walled(self.CTX, "Work"))
        self.assertFalse(lib.walled(self.CTX, "Ventures"))
        self.assertTrue(lib.walled(self.CTX, "Undeclared"))        # fails closed
        self.assertTrue(lib.walled(self.CTX, lib.UNZONED))
        self.assertTrue(lib.walled({}, "Work"))

    def test_may_flow(self):
        f = lambda a, b: lib.may_flow(self.CTX, a, b)
        self.assertTrue(f(None, "Work"))
        self.assertTrue(f(None, None))
        self.assertTrue(f("Work", "Work"))
        self.assertFalse(f("Work", "Home"))      # walled into another zone
        self.assertFalse(f("Work", None))        # walled out to Knowledge, System or the root
        self.assertTrue(f("Ventures", "Work"))   # open zone goes anywhere
        self.assertTrue(f("Ventures", None))
        self.assertTrue(f("Ventures", "Ventures"))
        self.assertTrue(f("Ventures", lib.UNZONED))
        self.assertFalse(f("Undeclared", "Work"))
        self.assertFalse(f(lib.UNZONED, "Work"))
        self.assertFalse(f(lib.UNZONED, lib.UNZONED))
        self.assertFalse(f("Work", lib.UNZONED))


if __name__ == "__main__":
    unittest.main()
