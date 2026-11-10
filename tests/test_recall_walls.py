"""Recall's raw records and the walls (#478): a record is in a scope only when every page that names it is.

    cd tests && python3 -m unittest test_recall_walls
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import write  # noqa: E402
from test_recall import ACME, BIRCH, Base  # noqa: E402


class KnowledgeRecordTest(Base):
    def test_a_knowledge_record_two_pages_name_is_out_when_one_is_walled(self):
        """A page that carries a zone is someone's, in no scope: the record it names stays out with it."""
        k = self.root / "Wikis/Knowledge/wiki/sources"
        write(k / "a-mine.md", "---\ntitle: A\nraw: raw/k.txt\nzone: Personal\n---\n\n# A\n\nnothing\n")
        write(k / "b-clean.md", "---\ntitle: B\nraw: raw/k.txt\n---\n\n# B\n\nnothing\n")
        write(self.root / "Wikis/Knowledge/raw/k.txt", "kwtoken in the frozen text\n")
        for project in (ACME, BIRCH, None):
            self.assertEqual([], self.paths("kwtoken", project, raw="always"), project)
            self.assertEqual([], self.paths("kwtoken", project), project)
        write(k / "a-mine.md", "---\ntitle: A\nraw: raw/other.txt\n---\n\n# A\n\nnothing\n")      # no longer a claimer
        self.assertEqual(["Wikis/Knowledge/raw/k.txt"], self.paths("kwtoken", ACME))
        write(k / "a-mine.md", "---\ntitle: A\nraw: raw/k.txt\nzone: Personal\n---\n\n# A\n\nnothing\n")  # claims it again, later
        self.assertEqual([], self.paths("kwtoken", ACME))                  # the index that held it lets it go


if __name__ == "__main__":
    unittest.main()
