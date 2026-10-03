"""What the check promises and now holds: the gaps between the rules and the
check, each closed with a case that must be caught and one that must pass.

Invented parties only: Acme Corp (`acme`) and Birch & Co (`birch`), walled
from each other, as in fixtures.py.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from fixtures import build_workspace, write

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)


class GapCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        self.acme = self.work / "Acme Review"
        self.birch = self.work / "Birch Entry"
        self.meetings = self.root / "Wikis" / "Meetings"
        self.knowledge = self.root / "Wikis" / "Knowledge"

    def tearDown(self):
        self._tmp.cleanup()

    def findings(self, name=None, severity=None):
        return [f for f in check.run_checks(self.root)
                if (name is None or f.check == name) and (severity is None or f.severity == severity)]

    def assertClean(self, name):
        self.assertEqual([], [(f.severity, f.path, f.message) for f in self.findings(name)])


class TestLinkIndex(GapCase):
    """Each link is matched against an index built once, not against every file."""

    def test_links_resolve_as_before(self):
        ws = check.discover(self.root)
        files = check.PathIndex(ws, check.walk_files(self.root))
        note = self.acme / "Threads" / "Pricing" / "Pricing.md"
        kickoff = self.meetings / "wiki" / "sources" / "260310-acme-kickoff.md"
        for target in ("260310-acme-kickoff", "Sources/260310-ACME-Kickoff.md", "Meetings/wiki/sources/260310-acme-kickoff",
                       "obsidian:Wikis:Meetings/wiki/sources/260310-acme-kickoff",
                       "../../../../../Wikis/Meetings/wiki/sources/260310-acme-kickoff.md",
                       "../../../../../Wikis/Meetings/wiki/sources/260310-acme-kickoff",
                       str(kickoff)):
            with self.subTest(target):
                self.assertEqual([kickoff], check.resolve(ws, note, target, files))
                self.assertEqual([kickoff], check.resolve(ws, note, target, list(check.walk_files(self.root))))
        for target in ("260310-acme", "wiki/260310-acme-kickoff", "../260310-acme-kickoff", "./", ""):
            with self.subTest(target):
                self.assertEqual([], check.resolve(ws, note, target, files))

    def test_knowledge_links_cost_one_lookup_each(self):
        concepts = self.knowledge / "wiki" / "concepts"
        n = 300
        for i in range(n):
            write(concepts / ("idea-%d.md" % i), "# Idea\n\nSee [[idea-%d]] and [[wiki/sources/supply-chain-report]].\n"
                  % ((i + 1) % n))
        write(concepts / "leak.md", "As heard in [[260310-acme-kickoff]].\n")
        calls = []
        real = check.rel
        check.rel = lambda ws, path: calls.append(path) or real(ws, path)
        try:
            found = check.check_knowledge(check.discover(self.root))
        finally:
            check.rel = real
        self.assertEqual(["Wikis/Knowledge/wiki/concepts/leak.md"], [f.path for f in found])
        # Once per file to index it, and a few per finding: never once per file per link.
        self.assertLess(len(calls), 4 * n, len(calls))


if __name__ == "__main__":
    unittest.main()
