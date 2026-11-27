"""#709: a current page never names a host, card or wall model Garrick has retired.

    cd tests && python3 -m unittest test_retired_claims

It reads README.md and every page under docs/ except docs/decisions/ and docs/assets/ (the notes
behind a concept and the images), plus the installer's summary line. CHANGELOG.md is history and is
not read. docs/updating.md keeps a section of release history, so it is left out of the host rule only.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent

# (what is retired, the words that name it, pages where the words are history and so allowed)
RETIRED = (
    ("Resume opens Claude with its answer already shown (since 0.80.0 a new session opens, request typed, not sent)",
     re.compile(r"Claude's answer already on screen|with the answer already on screen|Claude's answer to where it stands already on screen"), ("docs/concepts.md",)),
    ("the Obsidian plugin as a host that acts",
     re.compile(r"in the Mac app and in Obsidian|Mac app and in Obsidian, its buttons|in Obsidian, its buttons act", re.I), ()),
    ("the Obsidian status plugin as the page's host", re.compile(r"Obsidian (status )?plugin"), ("docs/updating.md",)),
    ("the wall model by party", re.compile(r"walls? between (the )?parties|walled part(y|ies)|\d+ part(y|ies) \(\d+ walled\)"
                                           r"|Walls between the parties", re.I), ()),
    ("a card the App no longer has", re.compile(r"\*At a glance\*|\*All findings\*|[Ss]imple home|tile row"), ()),
)


def pages():
    yield "README.md", (REPO / "README.md").read_text(encoding="utf-8")
    for path in sorted((REPO / "docs").rglob("*.md")):
        rel = path.relative_to(REPO).as_posix()
        if not rel.startswith(("docs/decisions/", "docs/assets/")):
            yield rel, path.read_text(encoding="utf-8")


class RetiredClaims(unittest.TestCase):
    def test_no_current_page_names_a_retired_host_card_or_wall_model(self):
        found = []
        for rel, text in pages():
            for what, pattern, allowed in RETIRED:
                if rel in allowed:
                    continue
                for m in pattern.finditer(text):
                    found.append("%s: %s (%r)" % (rel, what, m.group(0)))
        self.assertEqual([], found)

    def test_the_ladder_image_source_walls_zones(self):
        html = (REPO / "docs" / "assets" / "adoption-ladder.html").read_text(encoding="utf-8")
        self.assertIn("Walls around the zones you mark walled.", html)
        self.assertNotRegex(html, r"(?i)walls between")

    def test_the_installer_summary_counts_zones_not_a_party_wall(self):
        source = (REPO / "install.py").read_text(encoding="utf-8")
        self.assertNotIn("walled) in System/context.md", source)
        self.assertNotRegex(source, r"\{len\(walled\)\} walled\) in")


if __name__ == "__main__":
    unittest.main()
