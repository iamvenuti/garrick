"""wiki_lint.py: the part of a wiki's lint a script can do, orphans and
missing pages, without changing anything.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import build_workspace, write  # noqa: E402

import wiki_lint  # noqa: E402  (fixtures puts the tools folder on sys.path)


class WikiLintTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.k = self.root / "Wikis" / "Knowledge"
        write(self.k / "wiki" / "index.md", "# Index\n\n| Page | Type |\n|---|---|\n| [[wiki/sources/a\\|A]] | source |\n"
              "| [[wiki/sources/lonely\\|Lonely]] | source |\n| [[wiki/concepts/x]] | concept |\n")
        write(self.k / "wiki" / "log.md", "# Log\n\n- 2026-10-01: [[wiki/sources/a|A]]\n")
        write(self.k / "wiki" / "sources" / "a.md", '---\nraw: "[[raw/a.pdf]]"\n---\n\nTouches [[x]] and [[Gone Concept]].\n')
        write(self.k / "raw" / "a.pdf", "%PDF")
        write(self.k / "wiki" / "concepts" / "x.md", "# X\n\nFrom [[wiki/sources/a|A]]. Not `[[code]]`.\n")
        write(self.k / "wiki" / "sources" / "lonely.md", "# Lonely\n\nNo links at all.\n")
        write(self.k / "wiki" / "lint" / "2026-10-01.md", "# Lint\n\n[[nowhere]]\n")

    def test_orphans_and_missing_pages(self):
        found = wiki_lint.lint(self.k)
        names = [q.relative_to(self.k).as_posix() for q in wiki_lint.pages(self.k)]
        self.assertEqual(len(names), found["pages"])
        for listed in ("wiki/index.md", "wiki/log.md", "wiki/lint/2026-10-01.md"):
            self.assertNotIn(listed, names)                                   # the lists and the reports are not pages
        self.assertEqual(["wiki/sources/lonely"], found["orphans"])        # listed in the index, linked from no page
        self.assertEqual([{"target": "Gone Concept", "linked_from": ["wiki/sources/a"]}], found["missing"])

    def test_it_changes_nothing_and_speaks_plainly(self):
        before = sorted((p, p.read_bytes()) for p in self.k.rglob("*") if p.is_file())
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(0, wiki_lint.main(["--root", str(self.root), "--wiki", "Knowledge"]))
        self.assertRegex(out.getvalue(), r"^Knowledge: \d+ pages, 1 orphans, 1 missing pages\.")
        self.assertIn("[[Gone Concept]], from wiki/sources/a", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            wiki_lint.main(["--root", str(self.root), "--wiki", "Knowledge", "--json"])
        self.assertEqual(["wiki/sources/lonely"], json.loads(out.getvalue())["orphans"])
        self.assertEqual(before, sorted((p, p.read_bytes()) for p in self.k.rglob("*") if p.is_file()))


if __name__ == "__main__":
    unittest.main()
