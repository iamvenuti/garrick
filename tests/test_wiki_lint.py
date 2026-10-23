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

    def test_a_file_beside_a_page_is_not_a_missing_page(self):
        write(self.k / "wiki" / "presentations" / "acme.md", "# Acme\n\nSee [[acme.html]].\n\n![[acme.png]]\n")
        write(self.k / "wiki" / "presentations" / "acme.html", "<html></html>")
        write(self.k / "wiki" / "presentations" / "acme.png", "PNG")
        write(self.k / "wiki" / "concepts" / "y.md", "# Y\n\nThe deck: [[../presentations/acme.html|deck]].\n")
        found = wiki_lint.lint(self.k)
        self.assertEqual(["Gone Concept"], [m["target"] for m in found["missing"]])
        (self.k / "wiki" / "presentations" / "acme.png").unlink()
        found = wiki_lint.lint(self.k)
        self.assertEqual([{"target": "acme.png", "linked_from": ["wiki/presentations/acme"]}],
                         [m for m in found["missing"] if m["target"] != "Gone Concept"])

    def test_other_files_resolve_as_obsidian_finds_them_and_are_not_pages(self):
        before = wiki_lint.lint(self.k)
        write(self.k / "wiki" / "presentations" / "birch.html", "<html></html>")
        write(self.k / "wiki" / "presentations" / "birch.archify.json", "{}")
        write(self.k / "wiki" / "presentations" / "map.png", "PNG")
        write(self.k / "wiki" / "sources" / "map.png", "PNG")
        write(self.k / "wiki" / "concepts" / "y.md",
              "# Y\n\n[[wiki/presentations/birch.html]], [[presentations/birch.html]], [[birch.archify.json]],\n"
              "[[../../raw/a.pdf]], [[map.png]] and [[gone.png]].\n")
        found = wiki_lint.lint(self.k)
        self.assertEqual(["Gone Concept", "gone.png", "map.png"], sorted(m["target"] for m in found["missing"]))
        self.assertEqual(before["pages"] + 1, found["pages"])                # a file that is not a page is not counted
        self.assertEqual(sorted(before["orphans"] + ["wiki/concepts/y"]), found["orphans"])   # nor does linking one

    def test_faded_pages_are_not_working_pages_but_links_into_them_land(self):
        before = wiki_lint.lint(self.k)
        write(self.k / "dormant" / "wiki" / "sources" / "old.md", '---\nraw: "[[dormant/raw/old.pdf]]"\n---\n\n[[nowhere]]\n')
        write(self.k / "dormant" / "raw" / "old.pdf", "%PDF")
        write(self.k / "dormant" / "wiki" / "sources" / "old.png", "PNG")
        write(self.k / "archive" / "wiki" / "concepts" / "past.md", "# Past\n\nLinks nowhere at all.\n")
        write(self.k / "wiki" / "index-dormant.md", "# Dormant\n\n- [[dormant/wiki/sources/old|Old]], 2026-10-01: not read in a year\n")
        write(self.k / "wiki" / "concepts" / "y.md",
              "# Y\n\n[[old]], [[dormant/wiki/sources/old]], [[Wikis/Knowledge/archive/wiki/concepts/past]], [[past]],\n"
              "[[dormant/raw/old.pdf]], [[old.png]], [[x]] and [[dormant/wiki/sources/gone]].\n")
        found = wiki_lint.lint(self.k)
        self.assertEqual(before["pages"] + 1, found["pages"])                # only y: no faded page, nor the dormant index
        self.assertEqual(before["orphans"], found["orphans"])                # no faded page is an orphan
        self.assertEqual(["Gone Concept", "dormant/wiki/sources/gone"], sorted(m["target"] for m in found["missing"]))
        self.assertNotIn("nowhere", [m["target"] for m in found["missing"]])  # a faded page is not read for its links

    def test_a_working_page_wins_its_name_over_a_faded_one(self):
        write(self.k / "archive" / "wiki" / "concepts" / "x.md", "# X, as it was\n")
        write(self.k / "wiki" / "concepts" / "y.md", "# Y\n\n[[x]]\n")
        found = wiki_lint.lint(self.k)
        self.assertNotIn("wiki/concepts/y", found["orphans"])               # the link landed on the working x

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
