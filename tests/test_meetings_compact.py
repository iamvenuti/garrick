"""compact.py (#479): what "compact the meetings" would change, and the guard that names what a rewrite lost.

    cd tests && python3 -m unittest test_meetings_compact

Invented names only. Nothing here compacts a page anywhere but in a fixture.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import GIT_ENV, HAVE_GIT, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("garrick_compact", str(REPO / "template" / "System" / "skills" / "meetings" / "compact.py"))
compact = importlib.util.module_from_spec(_spec)
sys.modules["garrick_compact"] = compact
_spec.loader.exec_module(compact)


def page(title, words, zone="Work", date="2026-03-10", extra="", pinned=False):
    front = "---\ntitle: %s\ntype: meeting\ndate: %s\nzone: %s\nparties: [acme]\n%sraw: \"[[raw/%s]]\"\ncreated: %s\n---\n" % (
        title, date, zone, "pinned: true\n" if pinned else "", date.replace("-", "")[2:] + "-x", date)
    body = "\n## Key points\n\nThey agreed 2,500 pallets by 15 September: “we commit to Friday”. See [[wiki/people/dana]].\n\n" \
           "| What | Who | By |\n|---|---|---|\n| Send the sheet | Sam | 20 September |\n\n%s%s\n" % (
               " ".join("word" + "x" * (k % 7) for k in range(words)), extra)
    return front + body


class Plan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        write(self.root / "System" / "rules.md", "# Rules\n")
        self.sources = self.root / "Wikis" / "Meetings" / "wiki" / "sources"

    def add(self, name, text):
        write(self.sources / name, text)

    def test_it_lists_the_pages_over_the_limit_largest_first_with_words_before_and_after(self):
        self.add("260310-big.md", page("Big", 900))
        self.add("260311-mid.md", page("Mid", 600))
        self.add("260312-small.md", page("Small", 100))
        res = compact.plan(self.root)
        self.assertEqual(450, res["limit"])
        self.assertEqual(2, res["pages"])
        self.assertEqual(["Wikis/Meetings/wiki/sources/260310-big.md", "Wikis/Meetings/wiki/sources/260311-mid.md"],
                         [p["page"] for p in res["all"]])
        self.assertGreater(res["words"], res["words_after"])
        self.assertEqual(2 * 350, res["words_after"])

    def test_a_pinned_page_is_left_out_unless_asked(self):
        self.add("260310-big.md", page("Big", 900, pinned=True))
        self.assertEqual(0, compact.plan(self.root)["pages"])
        self.assertEqual(1, compact.plan(self.root, include_pinned=True)["pages"])

    def test_a_superseded_page_and_a_faded_page_are_left_out(self):
        self.add("260310-old.md", page("Old", 900).replace("pinned", "pinned").replace("parties: [acme]", "parties: [acme]\nsuperseded: \"newer\""))
        write(self.root / "Wikis" / "Meetings" / "dormant" / "wiki" / "sources" / "250101-faded.md", page("Faded", 900))
        write(self.root / "Wikis" / "Meetings" / "archive" / "wiki" / "sources" / "240101-gone.md", page("Gone", 900))
        self.assertEqual(0, compact.plan(self.root)["pages"])

    def test_the_limit_is_the_setting_or_the_flag(self):
        self.add("260310-mid.md", page("Mid", 300))
        self.assertEqual(0, compact.plan(self.root)["pages"])
        write(self.root / "System" / "garrick-settings.json", json.dumps({"meeting-max-words": 200}))
        self.assertEqual(1, compact.plan(self.root)["pages"])
        self.assertEqual(0, compact.plan(self.root, limit=800)["pages"])

    def test_the_pilot_is_about_ten_pages_spread_over_zones_and_years(self):
        for i in range(30):
            zone = ("Work", "Home", "Study")[i % 3]
            self.add("%02d-p%d.md" % (i, i), page("P%d" % i, 600, zone=zone, date="%d-%02d-10" % (2024 + i // 12, i % 12 + 1)))
        res = compact.plan(self.root, with_pilot=True)
        picked = res["pilot"]
        self.assertEqual(10, len(picked))
        self.assertEqual({"Work", "Home", "Study"}, {p["zone"] for p in picked})
        self.assertGreater(len({p["date"][:4] for p in picked}), 1)
        self.assertEqual(len(picked), len({p["page"] for p in picked}))

    def test_a_dry_plan_changes_nothing(self):
        self.add("260310-big.md", page("Big", 900))
        before = (self.sources / "260310-big.md").read_bytes()
        self.assertEqual(0, compact.main(["--root", str(self.root), "plan", "--pilot"]))
        self.assertEqual(before, (self.sources / "260310-big.md").read_bytes())


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Verify(unittest.TestCase):
    """The guard compares a rewritten page with its last committed version."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        write(self.root / "System" / "rules.md", "# Rules\n")
        self.path = self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260310-call.md"
        write(self.path, page("Call", 700, extra="\n\n[00:12:30] Sam: small talk about the weather, which goes.\n"))
        wikis = self.root / "Wikis"
        for args in (["init", "-q"], ["add", "-A"], ["-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "x"]):
            subprocess.run(["git", *args], cwd=str(wikis), env=GIT_ENV, check=True, capture_output=True)
        self.old = self.path.read_text(encoding="utf-8")

    def run_verify(self):
        return compact.main(["--root", str(self.root), "verify", self.path.relative_to(self.root).as_posix()])

    def shorten(self, text=None):
        front, _, rest = self.old.partition("\n## Key points")
        keep = rest.split("\n\nword0")[0]
        self.path.write_text(text if text is not None else front + "\n## Key points" + keep + "\n", encoding="utf-8")

    def test_a_rewrite_that_keeps_everything_passes(self):
        self.shorten()
        self.assertEqual(0, self.run_verify())

    def test_the_timestamps_a_compact_page_drops_are_not_missing_numbers(self):
        self.shorten()
        self.assertEqual([], compact.verify_text(self.old, self.path.read_text(encoding="utf-8")))

    def test_it_names_a_lost_number_quote_link_row_and_a_changed_frontmatter(self):
        text = self.old.replace("2,500", "many").replace("“we commit to Friday”", "a promise").replace("[[wiki/people/dana]]", "Dana")
        text = text.replace("| Send the sheet | Sam | 20 September |\n", "").replace("title: Call", "title: Call two")
        said = compact.verify_text(self.old, text)
        self.assertIn("a number is gone: 2,500", said)
        self.assertTrue([s for s in said if s.startswith("a quoted phrase is gone")])
        self.assertIn("a link is gone: wiki/people/dana", said)
        self.assertTrue([s for s in said if s.startswith("the table has")])
        self.assertIn("the frontmatter changed", said)
        self.path.write_text(text, encoding="utf-8")
        self.assertEqual(1, self.run_verify())

    def test_nothing_is_written_by_verify(self):
        self.shorten()
        before = self.path.read_bytes()
        self.run_verify()
        self.assertEqual(before, self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
