"""The wall docs stay short, say the same three sentences everywhere, and name no pair and no party wall.

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
THREE = re.compile(r"^> (Each zone is either .*)$", re.M)
BANNED = ("Walls table", "between two parties", "both ways", "not transitive",
          "walled from", "no wall between", "walled party", "walled parties", "label set", "who sees what", "zone party")
# Pages another branch of 0.63.0 rewrites with its code: the status page's guide and the skills that file and
# sort. Empty once they have.
SKIPPED = ("docs/extras/status-page.md", "template/System/tools/walls-cases.md",
           "template/System/skills/intake/SKILL.md", "template/System/skills/meetings/SKILL.md",
           "template/System/skills/nurture/SKILL.md", "template/System/skills/threads/SKILL.md")


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

    def test_concepts_zones_and_walls(self):
        self.check_limit("docs/concepts.md", "Zones and walls", 600)

    def test_enforced_known_gaps(self):
        self.check_limit("docs/enforced.md", "The wall check's known gaps", 600)

    def test_three_sentences_identical(self):
        found = {}
        for page in ("docs/principles.md", "docs/concepts.md", "docs/context.md", "README.md"):
            hits = THREE.findall((REPO / page).read_text(encoding="utf-8"))
            self.assertEqual(1, len(hits), "%s must hold the three sentences once" % page)
            found[page] = hits[0]
        self.assertEqual(1, len(set(found.values())), "the three sentences differ between pages")
        self.assertEqual(3, len(re.findall(r"[.!?](?:\s|$)", found["README.md"].replace("**", ""))))

    def test_the_template_context_and_rules_say_it_in_the_same_words(self):
        sentence = THREE.search((REPO / "README.md").read_text(encoding="utf-8")).group(1).replace("**", "")
        for page in ("template/System/context.md", "template/System/rules.md"):
            text = (REPO / page).read_text(encoding="utf-8").replace("**", "")
            self.assertIn(sentence.split(" Knowledge")[0], text, page)

    def test_no_pair_or_party_wall_phrases(self):
        paths = sorted(DOCS.rglob("*.md")) + [REPO / "README.md"] + sorted((REPO / "template").rglob("*.md"))
        for path in paths:
            if path.relative_to(REPO).as_posix() in SKIPPED:
                continue
            text = path.read_text(encoding="utf-8")
            for phrase in BANNED:
                self.assertNotIn(phrase.lower(), text.lower(),
                                 "%s uses %r" % (path.relative_to(REPO), phrase))


if __name__ == "__main__":
    unittest.main()
