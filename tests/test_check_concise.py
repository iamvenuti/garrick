"""check.py and the length of meeting pages (#479): a page over `meeting-max-words`, for pages filed after the user
turned the concise format on (`meetings-concise` in System/garrick-settings.json).

    cd tests && python3 -m unittest test_check_concise
"""

from __future__ import annotations

import json
import sys
import unittest

sys.dont_write_bytecode = True

from fixtures import meeting_page, write  # noqa: E402
from test_check import CheckCase  # noqa: E402


class ConcisePages(CheckCase):
    def page(self, name, words, created):
        text = meeting_page("Work", "[acme]", "Call").replace("created:", "created:")
        head, _, _ = text.partition("\n---\n\n")
        head = "\n".join(l for l in head.split("\n") if not l.startswith("created:"))
        write(self.meetings / "wiki" / "sources" / name,
              head + "\ncreated: %s\n---\n\n## Key points\n\n%s.\n" % (created, " ".join("p%d" % k for k in range(words))))

    def long_pages(self):
        return [f.path for f in self.findings("meetings") if "meeting-max-words" in f.message]

    def test_without_the_switch_the_check_says_nothing(self):
        self.page("260401-long.md", 900, "2026-04-01")
        self.assertEqual([], self.long_pages())

    def test_a_page_filed_after_the_switch_and_over_the_limit_warns(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"meetings-concise": "2026-04-01"}))
        self.page("260401-long.md", 500, "2026-04-01")
        self.page("260402-short.md", 300, "2026-04-02")
        self.assertEqual(["Wikis/Meetings/wiki/sources/260401-long.md"], self.long_pages())
        [f] = [f for f in self.findings("meetings") if "meeting-max-words" in f.message]
        self.assertEqual("warning", f.severity)
        self.assertRegex(f.message, r"its body is \d+ words, over the 450 of `meeting-max-words`")

    def test_a_page_filed_before_the_switch_never_counts(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"meetings-concise": "2026-04-01"}))
        self.page("260301-old.md", 1500, "2026-03-01")
        self.assertEqual([], self.long_pages())

    def test_the_limit_is_settable(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"meetings-concise": "2026-04-01", "meeting-max-words": 200}))
        self.page("260401-mid.md", 300, "2026-04-01")
        self.assertEqual(["Wikis/Meetings/wiki/sources/260401-mid.md"], self.long_pages())

    def test_a_switch_that_is_not_a_date_turns_nothing_on(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"meetings-concise": "yesterday"}))
        self.page("260401-long.md", 900, "2026-04-01")
        self.assertEqual([], self.long_pages())


if __name__ == "__main__":
    unittest.main()
