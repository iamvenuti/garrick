"""The wall docs stay short, say the same five sentences everywhere, and name no pair.

    cd tests && python3 -m unittest test_docs_limits

A review that wants to add to a limited section has to raise the limit here, which is a decision.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
FIVE = re.compile(r"^> (Every party you deal with is either .*)$", re.M)
BANNED = ("Walls table", "between two parties", "both ways", "not transitive",
          "walled from", "no wall between")


def section(page: str, heading: str) -> str:
    """The text under an H2 heading, up to the next H2, subsections included."""
    text = (REPO / page).read_text(encoding="utf-8")
    m = re.search(r"^## " + re.escape(heading) + r"\s*$", text, re.M)
    assert m, "%s has no heading %r" % (page, heading)
    rest = text[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


class WallDocLimits(unittest.TestCase):
    def check_limit(self, page, heading, limit):
        words = len(section(page, heading).split())
        self.assertLess(words, limit, "%s, %s: %d words, limit %d" % (page, heading, words, limit))

    def test_principles_walled_use(self):
        self.check_limit("docs/principles.md", "One memory, walled use", 1500)

    def test_concepts_parties_and_walls(self):
        self.check_limit("docs/concepts.md", "Parties and walls", 600)

    def test_enforced_known_gaps(self):
        self.check_limit("docs/enforced.md", "The wall check's known gaps", 600)

    def test_five_sentences_identical(self):
        found = {}
        for page in ("docs/principles.md", "docs/concepts.md", "README.md"):
            hits = FIVE.findall((REPO / page).read_text(encoding="utf-8"))
            self.assertEqual(1, len(hits), "%s must hold the five sentences once" % page)
            found[page] = hits[0]
        self.assertEqual(1, len(set(found.values())), "the five sentences differ between pages")
        self.assertEqual(5, len(re.findall(r"[.!?](?:\s|$)", found["README.md"].replace("**", ""))))

    def test_no_pair_phrases_under_docs(self):
        for path in sorted(DOCS.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            for phrase in BANNED:
                self.assertNotIn(phrase.lower(), text.lower(),
                                 "%s uses %r" % (path.relative_to(REPO), phrase))


if __name__ == "__main__":
    unittest.main()
