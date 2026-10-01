"""The skills folder as a whole: every skill is where the installer links it,
and no spoken trigger belongs to two skills.

    python3 -m unittest discover -s tests

Two skills answering to the same phrase would leave the assistant to pick one,
which is exactly the guess the rules forbid. "Process the inbox" belongs to
intake alone; meetings and knowledge are the procedures it calls.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "template" / "System" / "skills"


def description(skill: Path) -> str:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---", 2)[1]
    return head.split("description:", 1)[1]


def triggers(skill: Path) -> set:
    """The phrases in quotes in a skill's description, lower-cased, with any
    trailing punctuation dropped."""
    found = re.findall(r'"([^"]+)"', " ".join(description(skill).split()))
    return {re.sub(r"[.,;:!?]+$", "", f.strip().lower()) for f in found}


class SkillsTest(unittest.TestCase):
    def skills(self):
        return sorted(p.parent for p in SKILLS.glob("*/SKILL.md"))

    def test_the_skills(self):
        self.assertEqual(["intake", "interview", "knowledge", "meetings", "threads"],
                         [p.name for p in self.skills()])

    def test_every_skill_names_itself(self):
        for skill in self.skills():
            head = (skill / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
            self.assertIn("name: %s\n" % skill.name, head, skill)

    def test_no_trigger_is_claimed_twice(self):
        owners = {}
        for skill in self.skills():
            phrases = triggers(skill)
            self.assertTrue(phrases, skill)
            for phrase in phrases:
                owners.setdefault(phrase, []).append(skill.name)
        shared = {p: o for p, o in owners.items() if len(o) > 1}
        self.assertEqual({}, shared)

    def test_intake_owns_the_inbox(self):
        for phrase in ("process the inbox", "check the inbox", "file my mail", "file this mail"):
            self.assertIn(phrase, triggers(SKILLS / "intake"), phrase)
        self.assertIn("file this transcript", triggers(SKILLS / "meetings"))
        self.assertIn("read this", triggers(SKILLS / "knowledge"))

    def test_intake_procedure_points_at_the_rules_and_the_two_memories(self):
        text = (SKILLS / "intake" / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("*Ways in*", "`meetings`", "`knowledge`", "file-reading", "file-to-project",
                       "extract-attachment", "A wall held something back.", "## What this skill does not do"):
            self.assertIn(needle, text, needle)
        rules = (REPO / "template" / "System" / "rules.md").read_text(encoding="utf-8")
        self.assertIn("## Ways in", rules)

    def test_interview_asks_first_and_builds_on_a_yes(self):
        text = (SKILLS / "interview" / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("one question at a time", "Whose confidences you hold", "System/interviews/",
                       "## Proposal", "What I still don't know", "## On a yes", "Never push",
                       "never guesses a wall", "who and what kind"):
            self.assertIn(needle.lower(), text.lower(), needle)
        self.assertEqual({"interview me", "get to know me", "ask me about my work",
                          "help me set up my workspace", "where do i start"}, triggers(SKILLS / "interview"))

    def test_no_dashes_in_the_new_prose(self):
        for path in (SKILLS / "intake" / "SKILL.md", SKILLS / "interview" / "SKILL.md",
                     REPO / "template" / "System" / "rules.md"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("—", text, path)
            self.assertNotIn("–", text, path)


if __name__ == "__main__":
    unittest.main()
