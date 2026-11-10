"""check.py and the size of notes (#502): a hub or thread note over `note-max-words` and a Resume here block over
`resume-max-words`.

    cd tests && python3 -m unittest test_check_history
"""

from __future__ import annotations

import json
import sys
import unittest

sys.dont_write_bytecode = True

from fixtures import thread_note, write  # noqa: E402
from test_check import CheckCase  # noqa: E402


def long_note(entries=0, entry_words=300, block_words=0):
    text = thread_note("Acme Review", "Pricing", "acme")
    if block_words:
        text = text.replace("**Where it stands, 1 March 2026.** Drafting.\n",
                            "**Where it stands, 1 March 2026.** " + " ".join("stands%d" % k for k in range(block_words)) + "\n")
    text += "\n---\n\n"
    for i in range(entries):
        text += "**%d March 2026.** Session %d.\n\n%s.\n\n" % (i % 28 + 1, i, " ".join("w%d" % k for k in range(entry_words)))
    return text


class NoteLimits(CheckCase):
    def pricing(self, text):
        write(self.acme / "Threads" / "Pricing" / "Pricing.md", text)

    def over(self):
        return [f for f in self.findings() if "note-max-words" in f.message or "resume-max-words" in f.message]

    def test_a_note_over_four_thousand_words_warns_naming_the_note_and_both_counts(self):
        self.pricing(long_note(entries=20))
        [f] = [f for f in self.over() if "note-max-words" in f.message]
        self.assertEqual(("warning", "threads"), (f.severity, f.check))
        self.assertEqual("Zones/Work/Acme Review/Threads/Pricing/Pricing.md", f.path)
        self.assertRegex(f.message, r"^has \d+ words, over the 4000 of `note-max-words`")
        self.assertIn("history.py", f.message)

    def test_a_short_note_says_nothing(self):
        self.pricing(long_note(entries=3))
        self.assertEqual([], self.over())

    def test_a_hub_is_held_to_the_same_cap(self):
        hub = self.acme / "Acme Review.md"
        hub.write_text(hub.read_text(encoding="utf-8") + "\n## State of play\n\n### Resume here\n\n---\n\n"
                       + "\n\n".join("**%d March 2026.** %s." % (i + 1, " ".join("h%d" % k for k in range(400))) for i in range(12)),
                       encoding="utf-8")
        [f] = [f for f in self.over() if "note-max-words" in f.message]
        self.assertEqual(("warning", "projects"), (f.severity, f.check))

    def test_the_limits_are_the_settings(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"note-max-words": 100000, "resume-max-words": 5}))
        self.pricing(long_note(entries=20))
        self.assertEqual([], [f for f in self.over() if "note-max-words" in f.message])
        found = [f for f in self.over() if "resume-max-words" in f.message]
        self.assertTrue(found)
        self.assertRegex(found[0].message, r"has \d+ words, over the 5 of `resume-max-words`")

    def test_a_resume_block_over_four_hundred_words_warns_in_the_resume_check(self):
        self.pricing(long_note(entries=1, block_words=500))
        [f] = [f for f in self.over() if "resume-max-words" in f.message]
        self.assertEqual(("warning", "resume"), (f.severity, f.check))
        self.assertRegex(f.message, r"has \d+ words, over the 400 of `resume-max-words`")

    def test_a_history_file_is_no_note_and_has_no_limit(self):
        self.pricing(long_note(entries=3))
        write(self.acme / "Threads" / "Pricing" / "history" / "Pricing history 2025-Q4.md",
              '---\ntype: history\nparent: "[[Pricing]]"\ncreated: 2026-03-02\n---\n\n# Pricing: history, 2025-Q4\n\n'
              + "**5 December 2025.** " + " ".join("old%d" % k for k in range(6000)) + ".\n")
        self.assertEqual([], self.over())
        self.assertEqual([], [f for f in self.findings() if "history" in f.path and f.check in ("threads", "projects", "links")])


if __name__ == "__main__":
    unittest.main()
