"""The wall cases, run against the model, the check and the Meetings lint on a fixture workspace.

    cd tests && python3 -m unittest test_walls_cases

`walls/cases.md` is the one table of what the points must answer. Its first table is run against decide() in
test_decide; the others are run here, row by row: the enforcement points against the pre-commit check, the Meetings
rows against `zone_of()` and the lint. A row with no handler here fails the test, so a new case is run before it is
merged. The allow ledger, which stays, is tested at the end.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, commit_all, git, write  # noqa: E402
from zone_fixture import HOME_SAYS, UNZONED_SAYS, build  # noqa: E402

import check  # noqa: E402
import garrick_lib as lib  # noqa: E402

CASES = Path(__file__).resolve().parent / "walls" / "cases.md"
REPO = Path(__file__).resolve().parent.parent


def table(name):
    return lib.wall_cases(CASES.read_text(encoding="utf-8"))[name]


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name).resolve() / "Workspace"
        build(cls.root)
        cls.work = cls.root / "Zones" / "Work"
        git(cls.work, "init", "-q")
        cls.env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        cls.env.start()
        commit_all(cls.work, "start")

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls._tmp.cleanup()

    # -- the points ----------------------------------------------------------

    def restore(self):
        git(self.work, "reset", "-q", "--hard", "HEAD")
        git(self.work, "clean", "-fdq")

    def verdict(self, where, found):
        return "refused" if any(f.severity == "error" and f.path == where for f in found) else "permitted"

    def note(self, rel, text, suffix=".md", data=None):
        path = self.work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if data is not None:
            path.write_bytes(data)
        else:
            path.write_text(text, encoding="utf-8")
        self.addCleanup(self.restore)
        return path

    def check_note(self, rel, text):
        """The full walls check over a note written into Work."""
        path = self.note(rel, text)
        return self.verdict(path.relative_to(self.root).as_posix(), check.run_checks(self.root, walls_only=True))

    def staged(self, rel, text=None, data=None):
        """The commit hook's check over a file staged in Work."""
        path = self.note(rel, text or "", data=data)
        git(self.work, "add", "-A")
        return self.verdict(path.relative_to(self.root).as_posix(), check.run_checks(self.root, staged=self.work))

    PRICING = "Northwind/Threads/Pricing/CaseNote.md"

    def pricing(self, text):
        return self.check_note(self.PRICING, text)

    def handlers(self):
        garden = "Zones/Home/Garden/Threads/Beds/Notes.md"
        return {
            "e01": lambda: self.pricing("# N\n\nSee [[Zones/Home/Garden/Threads/Beds/Notes]].\n"),
            "e02": lambda: self.pricing("# N\n\n![[Zones/Home/Garden/Threads/Beds/Plan.md]]\n"),
            "e03": lambda: self.pricing("# N\n\nThe file is `%s`.\n" % garden),
            "e04": lambda: self.pricing("# N\n\nSee [[Zones/Work/Harbour/Threads/Sizing/Notes]].\n"),
            "e05": lambda: self.pricing("# N\n\nSee [[Zones/Ventures/Orchard/Threads/Drafts/Notes]].\n"),
            "e06": lambda: self.open_note("# N\n\nSee [[Zones/Work/Northwind/Threads/Pricing/Notes]].\n"),
            "e07": lambda: self.pricing("# N\n\nSee [[wiki/concepts/resilience]].\n"),
            "e08": lambda: self.pricing("# N\n\nSee [[260311-home-call]].\n"),
            "e09": lambda: self.pricing("# N\n\nSee [[260310-work-call]].\n"),
            "e10": lambda: self.pricing("# N\n\nSee [[260312-ventures-call]].\n"),
            "e11": lambda: self.pricing("# N\n\nSee [[260313-unzoned-call]].\n"),
            "e12": lambda: self.pricing("# N\n\nSee [[260314-two-zones-call]].\n"),
            "e13": lambda: self.pricing("# N\n\nThe record is `Wikis/Meetings/raw/260311-home-call.txt`.\n"),
            "e14": lambda: self.pricing("# N\n\nThe record is `Wikis/Meetings/raw/260319-orphan-call.txt`.\n"),
            "e15": lambda: self.pricing("# N\n\nAsk Jo Lane of Own affairs, and Pat.\n"),
            "e16": lambda: self.pricing("# N\n\nGarden plan: the beds go along the south wall, spaced a metre apart, with a path between.\n"),
            "e28": lambda: self.pricing("# N\n\nHarbour plan: the quay works come first, then the sheds.\n"),
            "e29": lambda: self.pricing("# N\n\nOrchard plan: the trees go in rows, one row for each variety.\n"),
            "e30": lambda: self.pricing("# N\n\n%s\n" % HOME_SAYS),
            "e31": lambda: self.pricing("# N\n\n%s\n" % UNZONED_SAYS),
            "e32": lambda: self.knowledge_says(),
            "e37": lambda: self.staged("Northwind/Threads/Pricing/Todo.md", data=self.plan("Home/Todo.md")),
            "e38": lambda: self.held_twice(),
            "e36": lambda: self.pricing("# N\n\nSee [[bare]].\n"),
            "e33": lambda: self.staged("Northwind/Threads/Pricing/Raw.txt", data=self.raw("260310-work-call")),
            "e34": lambda: self.staged("Northwind/Threads/Pricing/Raw.txt", data=self.raw("260312-ventures-call")),
            "e35": lambda: self.staged("Northwind/Threads/Pricing/Raw.txt", data=self.raw("260311-home-call", fill=True)),
            "e17": lambda: self.staged("Northwind/Threads/Pricing/Copy.md", data=self.plan("Home/Garden/Threads/Beds/Plan.md")),
            "e18": lambda: self.staged("Northwind/Threads/Pricing/Copy.md", data=self.plan("Ventures/Orchard/Threads/Drafts/Plan.md")),
            "e19": lambda: self.staged("Northwind/Threads/Pricing/Copy.md", data=self.plan("Work/Harbour/Threads/Sizing/Plan.md")),
            "e20": lambda: self.short_copy(),
            "e21": lambda: self.knowledge_copy(),
            "e22": lambda: self.symlink(),
            "e23": lambda: self.zone_file(),
            "e24": lambda: self.pricing("# N\n\nSee [[Sizing]].\n"),
            "e25": lambda: self.party_key(),
            "e26": lambda: self.staged("Northwind/Threads/Pricing/tool.py", "# see [[260311-home-call]]\n"),
            "e27": lambda: self.staged("Northwind/Threads/Pricing/Blob.md", data=b"see\x00there"),
        }

    def raw(self, stem, fill=False):
        path = self.root / "Wikis" / "Meetings" / "raw" / (stem + ".txt")
        if fill:      # a record long enough to count as a copy
            path.write_text("Jo: the beds are marked along the south wall, and the path is laid.\n", encoding="utf-8")
        return path.read_bytes()

    def held_twice(self):
        text = b"Shared wording of a note kept by two zones, held word for word in each of them.\n"
        for zone in ("Home", "Ventures"):
            path = self.root / "Zones" / zone / "Garden-copy.md"
            path.write_bytes(text)
            self.addCleanup(path.unlink)
        return self.staged("Northwind/Threads/Pricing/Copy.md", data=text)

    def plan(self, rel):
        return (self.root / "Zones" / rel).read_bytes()

    def open_note(self, text):
        path = self.root / "Zones" / "Ventures" / "Orchard" / "Threads" / "Drafts" / "CaseNote.md"
        write(path, text)
        self.addCleanup(lambda: path.exists() and path.unlink())
        return self.verdict(path.relative_to(self.root).as_posix(), check.run_checks(self.root, walls_only=True))

    def short_copy(self):
        small = b"tiny\n"
        (self.root / "Zones" / "Home" / "Garden" / "Tiny.md").write_bytes(small)
        self.addCleanup(lambda: (self.root / "Zones" / "Home" / "Garden" / "Tiny.md").unlink())
        return self.staged("Northwind/Threads/Pricing/Tiny.md", data=small)

    def knowledge_copy(self):
        ws = check.discover(self.root, None)
        page = self.root / "Wikis" / "Knowledge" / "wiki" / "concepts" / "copied.md"
        found = check.copy_findings(ws, [(page, self.plan("Home/Garden/Threads/Beds/Plan.md"))])
        return "refused" if found else "permitted"

    def knowledge_says(self):
        page = self.root / "Wikis" / "Knowledge" / "wiki" / "concepts" / "says.md"
        write(page, "# Says\n\n%s\n" % HOME_SAYS)
        self.addCleanup(lambda: page.exists() and page.unlink())
        found = [f for f in check.run_checks(self.root) if f.path == page.relative_to(self.root).as_posix()]
        return "warned" if any(f.severity == "warning" for f in found) else "permitted"

    def symlink(self):
        link = self.work / "Northwind" / "Linked"
        os.symlink(self.root / "Zones" / "Home" / "Garden", link)
        self.addCleanup(lambda: link.unlink() if link.is_symlink() else None)
        return self.verdict("Zones/Work/Northwind/Linked", check.run_checks(self.root, walls_only=True))

    def zone_file(self):
        path = self.work / "Todo.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nSee [[Zones/Home/Garden/Threads/Beds/Notes]].\n", encoding="utf-8")
        self.addCleanup(self.restore)
        return self.verdict("Zones/Work/Todo.md", check.run_checks(self.root, walls_only=True))

    def party_key(self):
        hub = self.work / "Northwind" / "Northwind.md"
        hub.write_text(hub.read_text(encoding="utf-8").replace("party: acme", "party: [acme, jo]"), encoding="utf-8")
        self.addCleanup(self.restore)
        return self.pricing("# N\n\nSee [[Zones/Home/Garden/Threads/Beds/Notes]].\n")

    def test_every_enforcement_row_has_a_handler_and_its_verdict(self):
        rows = table("Enforcement points")
        handlers = self.handlers()
        self.assertEqual(sorted(handlers), sorted(r[0] for r in rows))
        for ident, point, item, expect, source in rows:
            with self.subTest(case=ident, item=item):
                self.assertEqual(handlers[ident](), expect, source)

    # -- the Meetings wiki ------------------------------------------------------

    def test_every_meetings_row_has_its_zone(self):
        meetings = self.root / "Wikis" / "Meetings"
        wiki = meetings / "wiki" / "sources"
        extra = {
            "m02": ("sources/260316-lower.md", "---\ntitle: x\nzone: work\n---\n"),
            "m05": ("sources/260317-nowhere.md", "---\ntitle: x\nzone: Nowhere\n---\n"),
        }
        for rel, text in extra.values():
            write(meetings / "wiki" / rel, text)
        self.addCleanup(lambda: [(meetings / "wiki" / rel).unlink() for rel, _ in extra.values()])
        where = {
            "m01": wiki / "260310-work-call.md", "m02": meetings / "wiki" / extra["m02"][0],
            "m03": wiki / "260313-unzoned-call.md", "m04": wiki / "260314-two-zones-call.md",
            "m05": meetings / "wiki" / extra["m05"][0], "m06": meetings / "wiki" / "entities" / "acme-corp.md",
            "m07": meetings / "raw" / "260310-work-call.txt", "m08": meetings / "raw" / "260315-both-call.txt",
            "m09": meetings / "raw" / "260319-orphan-call.txt",
            "m10": self.root / "Wikis" / "Knowledge" / "wiki" / "concepts" / "resilience.md",
            "m11": self.root / "System" / "rules.md",
        }
        want = {"Work": "Work", "unzoned": lib.UNZONED, "none": None}
        rows = table("Meetings")
        self.assertEqual(sorted(where), sorted(r[0] for r in rows))
        ws = check.discover(self.root, None)
        for ident, page, zone, source in rows:
            with self.subTest(case=ident, page=page):
                path = where[ident]
                if path.suffix == ".md" and path.parent.name in ("sources", "entities") or ident in ("m10", "m11"):
                    self.assertEqual(want[zone], lib.zone_of(self.root, path), source)
                if ident in ("m07", "m08", "m09"):
                    self.assertEqual(want[zone], check.page_names(ws).zone(path), source)

    # -- the Meetings lint (#481) -------------------------------------------------

    def lint(self):
        ws = check.discover(self.root, None)
        return {f.path: f for f in check.check_meeting_zones(ws)}

    def test_lint_rows(self):
        found = self.lint()
        rows = {r[0]: r for r in table("Meetings lint")}
        base = "Wikis/Meetings/wiki/"
        mixed = found.get(base + "entities/mixed.md")
        self.assertIsNotNone(mixed, rows["l01"][1])
        self.assertIn("split", mixed.message)
        self.assertNotIn(base + "entities/mixed-open.md", found)                                        # l02
        self.assertIn(base + "sources/260313-unzoned-call.md", found)                                   # l03
        self.assertNotIn(base + "entities/whole.md", found)                                             # l04
        both = found.get(base + "entities/open-and-walled.md")       # an open source forces no split: the walled zone is proposed
        self.assertIsNotNone(both)
        self.assertIn("takes Work", both.message)
        pat = found.get(base + "people/pat.md")                                                         # l05
        self.assertIsNotNone(pat)
        self.assertIn("Home", pat.message)

    def test_the_lint_finding_is_a_warning_of_the_meetings_kind(self):
        for f in self.lint().values():
            self.assertEqual(("warning", "meetings"), (f.severity, f.check))

    # -- the allow ledger stays ----------------------------------------------------

    def test_allowing_a_refusal_once_lets_that_file_through(self):
        path = self.note(self.PRICING, "# N\n\nSee [[Zones/Home/Garden/Threads/Beds/Notes]].\n")
        git(self.work, "add", "-A")
        where = path.relative_to(self.root).as_posix()
        found = [f for f in check.run_checks(self.root, staged=self.work) if f.path == where]
        self.assertEqual(1, len(found))
        self.assertTrue(check.allowable(found[0]))
        blob = check.index_blobs(self.work)[path.relative_to(self.work).as_posix().casefold()]
        gl_root = self.root
        git(gl_root, "init", "-q") if not (gl_root / ".git").exists() else None
        lib.allow_add(gl_root, where, check.finding_id(found[0]), blob, check.finding_rule(found[0]), "terminal")
        lib.allow_commit(gl_root, "ledger")
        self.addCleanup(lambda: shutil.rmtree(gl_root / ".git", ignore_errors=True))
        self.assertEqual("permitted", self.verdict(where, check.run_checks(self.root, staged=self.work)))

    # -- the table itself --------------------------------------------------------

    def test_the_shipped_table_is_the_tests_table(self):
        shipped = REPO / "template" / "System" / "tools" / "walls-cases.md"
        self.assertEqual(CASES.read_text(encoding="utf-8"), shipped.read_text(encoding="utf-8"))

    def test_ids_are_unique(self):
        ids = [r[0] for name in ("decide()", "Enforcement points", "Meetings", "Meetings lint") for r in table(name)]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
