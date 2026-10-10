"""False alarms the wall check no longer raises: a zone's archive read as a
project, the code of HTML pages read as wording, a list of links to Knowledge
pages read as one run of words, and files git ignores read as the project's own.
Each test pairs the case that must pass with one that must still be found.

Invented parties only: Acme Corp (`acme`) and Birch & Co (`birch`), walled
from each other, as in fixtures.py.
"""

from __future__ import annotations

import shutil
import sys
import unittest

from fixtures import HAVE_GIT, git, meeting_page, write
from test_walls_deterministic import SECRET, WallCase, _copy_tools, _real_repo, _run

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)


class TestZoneArchive(WallCase):
    """#23: a zone's `archive/` holds retired material, not a project."""

    def retired(self, folder):
        write(folder / "Todo 2026-09.md",
              "# Done in September\n\n- [x] Read the notes of [[260312-birch-kickoff]] with Theo Marsh\n")
        write(folder / "Old Lane" / "Old Lane.md", "# Old Lane\n\nMoved here when it closed.\n")

    def found_in(self, folder):
        prefix = check.rel(check.discover(self.root), folder) + "/"
        return [f for f in check.run_checks(self.root) if f.path == prefix[:-1] or f.path.startswith(prefix)]

    def test_archive_any_case_is_not_a_project(self):
        for name in ("archive", "Archive"):
            with self.subTest(name):
                folder = self.root / "Zones" / "Work" / name
                self.retired(folder)
                self.assertEqual([], self.found_in(folder))
                self.assertNotIn(folder, [p for p, _ in check.discover(self.root).projects])
                retired = folder.rename(folder.with_name("Retired"))
                found = self.found_in(retired)  # under any other name it is a project
                self.assertIn(("walls", "error"), [(f.check, f.severity) for f in found])
                self.assertIn(("projects", "error"), [(f.check, f.severity) for f in found])
                shutil.rmtree(retired)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_committing_the_archive_passes_the_hook(self):
        _copy_tools(self.root)
        zone = self.root / "Zones" / "Work"
        _real_repo(zone)
        self.retired(zone / "archive")
        git(zone, "add", "-A")
        res = _run([sys.executable, self.root / "System" / "tools" / "check.py", "--staged", "--walls-only"], zone)
        self.assertEqual((0, ""), (res.returncode, res.stderr))


# Two slide pages built from one template: the same styles, scripts and
# comments, each with its own visible words.
SLIDE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>%(title)s</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: var(--font-body); background: var(--paper); color: var(--ink); }
  .slide { position: absolute; inset: 0; width: 1920px; height: 1080px; overflow: hidden; }
</style>
<!-- Keyboard and touch navigation: arrow keys, space bar and swipe move between slides -->
</head>
<body>
<section class="slide" data-transition="fade slow" aria-label="opening slide with title and subtitle">
<h1>%(title)s</h1>
<p>%(text)s</p>
</section>
<script>
  document.addEventListener('keydown', function (event) { if (event.key === 'ArrowRight') nextSlide(); });
  document.addEventListener('touchstart', function (event) { startX = event.touches[0].clientX; });
</script>
</body></html>
"""


class TestHtml(WallCase):
    """#24: an HTML page is compared by the words a reader sees."""

    def test_a_shared_template_is_not_wording(self):
        write(self.acme / "Deliverables" / "260302 - Pricing slides.html",
              SLIDE % {"title": "Pricing options", "text": "Three tiers, one floor price."})
        write(self.birch / "Deliverables" / "260302 - Market slides.html",
              SLIDE % {"title": "Nordic market", "text": "Demand grows in the north."})
        self.assertEqual([], self.walls())

    def test_visible_text_still_counts(self):
        text = "Freight volumes on the northern corridor doubled after the new customs rules came in"
        write(self.acme / "Deliverables" / "260302 - Pricing slides.html",
              SLIDE % {"title": "Pricing options", "text": text})
        write(self.birch / "Deliverables" / "260302 - Market slides.html",
              SLIDE % {"title": "Nordic market", "text": text})
        paths = sorted(f.path for f in self.walls())
        self.assertEqual(["Zones/Work/Acme Review/Deliverables/260302 - Pricing slides.html",
                          "Zones/Work/Birch Entry/Deliverables/260302 - Market slides.html"], paths)

    def test_a_meeting_quoted_on_a_page(self):
        write(self.meetings / "wiki" / "sources" / "260314-birch-call.md",
              meeting_page("Work", "[birch]", "Birch call").replace("Decisions.", SECRET + "."))
        write(self.acme / "Deliverables" / "260302 - Pricing slides.html",
              SLIDE % {"title": "Pricing", "text": SECRET.replace("Oslo depot", "<em>Oslo</em> depot")})
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn("260314-birch-call", found[0].message)
        self.assertNoLeak(found, "oslo", "depot", "november")

    def test_html_text(self):
        text = check.html_text('<p class="lead">Birch &amp; Co</p><!-- note --><script>var a = 1;</script>'
                               '<STYLE type="text/css">p { margin: 0 }</STYLE>')
        self.assertEqual(["birch", "and", "co"], check.words(text))


# The titles of three Knowledge pages, listed the same way in a note on each
# side of the wall: eight words and more of labels in a row.
KNOWLEDGE_PAGES = {
    "freight-corridors": "Freight corridors and cold chain capacity",
    "bonded-warehousing": "Bonded warehousing for regional distributors",
    "customs-rules": "Customs rules after the border reform",
}


class TestLinkLabels(WallCase):
    """#25: the label of a link to a shared file is that page's title, common to every side."""

    def setUp(self):
        super().setUp()
        for slug, title in KNOWLEDGE_PAGES.items():
            write(self.knowledge / "wiki" / "sources" / (slug + ".md"),
                  "---\ntitle: %s\ntype: source\nconfidence: medium\n---\n\n# %s\n" % (title, title))

    def reading_list(self, depth):
        up = "../" * depth
        slugs = list(KNOWLEDGE_PAGES)
        return ("# Reading\n\n"
                "- [[wiki/sources/%s|%s]]\n" % (slugs[0], KNOWLEDGE_PAGES[slugs[0]])
                + "- [%s](%sWikis/Knowledge/wiki/sources/%s.md)\n" % (KNOWLEDGE_PAGES[slugs[1]], up, slugs[1])
                + "- [%s](obsidian://open?vault=Knowledge&file=wiki%%2Fsources%%2F%s)\n" % (KNOWLEDGE_PAGES[slugs[2]], slugs[2]))

    def test_a_list_of_knowledge_pages_is_common(self):
        write(self.acme / "Threads" / "Pricing" / "Reading.md", self.reading_list(5))
        write(self.birch / "Threads" / "Market Sizing" / "Reading.md", self.reading_list(5))
        self.assertEqual([], self.walls())

    def test_obsidian_links_to_knowledge_pages(self):
        text = "".join("- [%s](obsidian://open?vault=Knowledge&file=wiki%%2Fsources%%2F%s)\n" % (title, slug)
                       for slug, title in KNOWLEDGE_PAGES.items())
        write(self.acme / "Threads" / "Pricing" / "Reading.md", text)
        write(self.birch / "Threads" / "Market Sizing" / "Reading.md", text)
        self.assertEqual([], self.walls())
        text = text.replace("wiki%2Fsources%2F", "Notes%2F")  # pages that are not there: their labels are wording
        write(self.acme / "Threads" / "Pricing" / "Reading.md", text)
        write(self.birch / "Threads" / "Market Sizing" / "Reading.md", text)
        self.assertEqual(2, len(self.walls()))

    def test_labels_of_other_links_still_count(self):
        text = self.reading_list(5).replace("wiki/sources/", "Notes/").replace("wiki%2Fsources%2F", "Notes%2F")
        write(self.acme / "Threads" / "Pricing" / "Reading.md", text)
        write(self.birch / "Threads" / "Market Sizing" / "Reading.md", text)
        self.assertEqual(2, len(self.walls()))


class TestIgnoredFiles(WallCase):
    """#26: files git never commits are not the project's own text."""

    def test_installed_packages_by_name(self):
        for name in ("node_modules", ".venv", "__pycache__", "dist"):
            write(self.acme / "Tool" / name / "pkg" / "README.md", "Built for Birch & Co pipelines. {{PROJECT}}\n")
        self.assertEqual([], [f for f in check.run_checks(self.root) if f.check in ("walls", "placeholders")])
        write(self.acme / "Tool" / "vendor" / "README.md", "Built for Birch & Co pipelines. {{PROJECT}}\n")
        found = [(f.check, f.path) for f in check.run_checks(self.root) if f.check in ("walls", "placeholders")]
        self.assertEqual([("placeholders", "Zones/Work/Acme Review/Tool/vendor/README.md"),
                          ("walls", "Zones/Work/Acme Review/Tool/vendor/README.md")], sorted(found))

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_what_the_zone_ignores(self):
        zone = self.root / "Zones" / "Work"
        _real_repo(zone)
        write(zone / ".gitignore", "Inbox/*\n!Inbox/.gitkeep\ncache/\n")
        write(self.acme / "Tool" / "cache" / "README.md", "Built for Birch & Co pipelines. {{PROJECT}}\n")
        (zone / "Inbox" / "call.m4a").write_bytes(b"\0audio")
        found = {(f.check, f.path) for f in check.run_checks(self.root)}
        self.assertNotIn("walls", {c for c, _ in found})
        self.assertNotIn("placeholders", {c for c, _ in found})
        self.assertIn(("inbox", "Zones/Work/Inbox/call.m4a"), found)  # the inbox is ignored by design, and still read
        write(zone / ".gitignore", "Inbox/*\n!Inbox/.gitkeep\n")
        found = {(f.check, f.path) for f in check.run_checks(self.root)}
        self.assertIn(("walls", "Zones/Work/Acme Review/Tool/cache/README.md"), found)
        self.assertIn(("placeholders", "Zones/Work/Acme Review/Tool/cache/README.md"), found)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_the_root_ignoring_the_zones_hides_nothing(self):
        git(self.root, "init", "-q")
        write(self.root / ".gitignore", "Zones/\nWikis/\nSystem/generated/\n")
        write(self.acme / "Notes.md", "Built for Birch & Co pipelines.\n")
        self.assertEqual(["Zones/Work/Acme Review/Notes.md"], [f.path for f in self.walls()])


if __name__ == "__main__":
    unittest.main()
