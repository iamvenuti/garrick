"""#710: one short page on using the App, opened first in the Guide.

    cd tests && python3 -m unittest test_using_the_app

It reads docs/using-the-app.md, extras/status/status.py (for the App's own words) and a fixture
install's System/garrick-docs/, built by the installer into a temporary home.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent
PAGE = REPO / "docs" / "using-the-app.md"
REFERENCE = "extras/status-page.md"


def prose():
    """The page without its one allowed link target."""
    text = PAGE.read_text(encoding="utf-8")
    return text.replace("](%s)" % REFERENCE, "](reference)")


class UsingTheApp(unittest.TestCase):
    def test_the_page_is_about_six_hundred_words(self):
        words = len(re.findall(r"[A-Za-z0-9'’*]+", PAGE.read_text(encoding="utf-8")))
        self.assertTrue(450 <= words <= 750, words)

    def test_it_names_no_file_command_or_issue_number(self):
        text = prose()
        self.assertNotIn("`", text)
        self.assertEqual([], re.findall(r"\b[\w-]+\.(?:md|py|json|html|sh|plist|jsonl|swift)\b", text))
        self.assertEqual([], re.findall(r"#\d+", text))
        self.assertNotIn("python3", text)
        self.assertEqual([], re.findall(r"[\w~.-]+/[\w~./-]+", text))
        self.assertEqual([], re.findall(r"\b(?:git|claude|codex)\s+[a-z-]+\s+--", text))

    def test_the_long_page_is_one_link_away(self):
        self.assertEqual(1, PAGE.read_text(encoding="utf-8").count("](%s)" % REFERENCE))

    def test_it_covers_the_five_things_the_issue_names(self):
        text = PAGE.read_text(encoding="utf-8")
        for heading in ("## The Overview", "## Resume a piece of work", "## What needs you", "## Todo", "## Settings"):
            self.assertIn(heading, text)

    def test_every_word_it_quotes_from_the_app_is_in_the_app(self):
        source = (REPO / "extras" / "status" / "status.py").read_text(encoding="utf-8")
        docs = (REPO / "docs" / "extras" / "status-page.md").read_text(encoding="utf-8")
        for word in re.findall(r"\*([^*\n]+)\*", PAGE.read_text(encoding="utf-8")):
            self.assertTrue(word in source or word in docs, word)

    def test_no_dash_is_used_as_punctuation(self):
        text = prose()
        self.assertNotRegex(text, r"[ \t][-\u2013\u2014][ \t]|[\u2013\u2014]")

    def test_the_guide_of_a_fresh_install_opens_on_it(self):
        import test_install
        import tempfile
        import importlib.util
        box = test_install.Sandbox()
        try:
            root, result = box.install("ws")
            self.assertEqual(0, result.returncode, result.stderr)
            docs = root / "System" / "garrick-docs"
            self.assertTrue((docs / "using-the-app.md").is_file())
            spec = importlib.util.spec_from_file_location("garrick_guide", REPO / "extras" / "status" / "guide.py")
            guide = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(guide)
            body, end = guide.guide(docs)
            html = body + end
            first = re.search(r'<article class="gd-page" id="([^"]+)"', html).group(1)
            self.assertEqual(guide.page_id("using-the-app.md"), first)
            toc = re.findall(r'<li class="gd-it" data-p="([^"]+)"', html)
            self.assertEqual([guide.page_id("using-the-app.md"), guide.page_id("try-it-safely.md")], toc[:2])
            # the long page is still there, as the reference
            self.assertIn(guide.page_id("extras/status-page.md"), toc)
        finally:
            box.close()


if __name__ == "__main__":
    unittest.main()
