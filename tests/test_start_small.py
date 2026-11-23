"""#667: the *Start small* table in docs/context.md says what every session loads and its limits. Each number in it is read
from the code or the settings defaults at this release, so a limit that moves fails here until the page says so.

    cd tests && python3 -m unittest test_start_small
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
PAGE = REPO / "docs" / "context.md"


def number(path, pattern):
    m = re.search(pattern, path.read_text(encoding="utf-8"), re.M)
    assert m, "%s has no %s" % (path.name, pattern)
    return int(m.group(1).replace("_", ""))


def table():
    """The *Start small* section and its table: {first cell: [cells]}."""
    text = PAGE.read_text(encoding="utf-8")
    start = text.index("\n## Start small\n")
    body = text[start:text.index("\n## ", start + 5)]
    rows = {}
    for line in body.splitlines():
        if line.startswith("|") and not line.startswith("|---") and not line.startswith("| File "):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[cells[0]] = cells
    return body, rows


def numbers(cell):
    return sorted(int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", cell))


class TestStartSmall(unittest.TestCase):
    def expected(self):
        check, lib, hist = TOOLS / "check.py", TOOLS / "garrick_lib.py", TOOLS / "history.py"
        defaults = re.search(r"DEFAULTS = \{([^}]*)\}", hist.read_text(encoding="utf-8")).group(1)

        def default(key):
            return int(re.search(r'"%s": (\d+)' % key, defaults).group(1))
        return {
            "`AGENTS.md`, `AGENTS.local.md`": sorted([number(check, r"^WORD_BUDGET_ROOT = (\d+)"), number(check, r"^WORD_BUDGET_OTHER = (\d+)")]),
            "`System/rules.md`": [number(check, r"^RULES_CHAR_BUDGET = (\d+)")],
            "`System/context.md`": [number(check, r"^CONTEXT_CHAR_BUDGET = (\d+)")],
            "The assistant's memory index, `MEMORY.md`": sorted([number(lib, r"^MEMORY_INDEX_MAX = (\d+)"), number(lib, r"^MEMORY_LINE_MAX = (\d+)")]),
            "A thread's Resume here block": [default("resume-max-words")],
            "A hub or thread note": sorted([default("note-max-words"), default("history-months")]),
            "A meeting page": [number(check, r"^MEETING_MAX_WORDS = (\d+)")],
        }

    def test_every_number_in_the_limit_column_is_the_one_in_the_code(self):
        _, rows = table()
        for first, want in self.expected().items():
            with self.subTest(row=first):
                self.assertIn(first, rows)
                self.assertEqual(want, numbers(rows[first][3 - 1]), "the Limit of %s" % first)

    def test_the_rows_without_a_limit_have_no_number(self):
        _, rows = table()
        for first in ("`System/rules.local.md`", "`System/names.md`", "A wiki's `index.md`"):
            with self.subTest(row=first):
                self.assertEqual([], numbers(rows[first][2]))

    def test_every_row_links_the_page_that_owns_its_detail(self):
        _, rows = table()
        self.assertEqual(10, len(rows))
        for first, cells in rows.items():
            with self.subTest(row=first):
                self.assertEqual(5, len(cells))
                links = re.findall(r"\]\(([^)#]*)(#[^)]*)?\)", cells[4])
                self.assertTrue(links, "no link for %s" % first)
                for target, anchor in links:
                    text = (PAGE.parent / target).read_text(encoding="utf-8") if target else PAGE.read_text(encoding="utf-8")
                    if anchor:
                        heads = {re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
                                 for h in re.findall(r"(?m)^#+ (.+)$", text)}
                        self.assertIn(anchor[1:], heads, "%s%s" % (target, anchor))

    def test_no_limit_is_explained_twice_before_the_pages_own_sections(self):
        text = PAGE.read_text(encoding="utf-8")
        body, _ = table()
        before = text.split("\n## Take in\n")[0].replace(body, "")
        for figure in ("8,000 characters", "800 words", "4,000 words", "450 words"):
            self.assertNotIn(figure, before, figure)

    def test_the_stage_table_and_the_readme_name_five_stages(self):
        text = PAGE.read_text(encoding="utf-8")
        stages = re.findall(r"(?m)^\| \[([^\]]+)\]\(#[a-z-]+\) \|", text)
        self.assertEqual(["Start small", "Take in", "Keep true", "Use within walls", "Let fade"], stages)
        self.assertIn("five stages", text)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        line = readme.split("five stages")[1].split("\n")[0]
        for name in ("start small", "take in", "keep true", "use within walls", "let fade"):
            self.assertIn(name, line)

    def test_start_small_comes_before_take_in_and_is_no_concept_heading(self):
        text = PAGE.read_text(encoding="utf-8")
        self.assertLess(text.index("\n## Start small\n"), text.index("\n## Take in\n"))
        self.assertNotIn("Start small", (REPO / "docs" / "concepts.md").read_text(encoding="utf-8"))

    def test_the_memory_bullet_says_park_wake_and_finish(self):
        text = PAGE.read_text(encoding="utf-8")
        bullet = next(l for l in text.splitlines() if l.startswith("- **Memory.**"))
        for word in ("parked/", "wakes", "finishes"):
            self.assertIn(word, bullet)


if __name__ == "__main__":
    unittest.main()
