"""The docs and skills for machines (#612) say what the code does.

    python3 -m unittest test_machine_docs
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "template" / "System" / "skills"


def text(path):
    return (REPO / path).read_text(encoding="utf-8")


class MachineDocs(unittest.TestCase):
    def test_the_page_names_the_roles_the_file_and_the_sync_rules(self):
        page = text("docs/machines.md")
        for word in ("`solo`", "`server`", "`roaming`", "~/.config/garrick/machine.json", "Send Only", "Receive Only", "iCloud Drive",
                     "Dropbox", "both ways", "same absolute path", ".outbox", "Drop it", "Show me the line",
                     "sync-conflict", "conflicted copy", "not reachable here"):
            self.assertIn(word, page, word)

    def test_the_page_says_a_session_cannot_write_the_role_file(self):
        page = text("docs/machines.md")
        self.assertRegex(page, r"(?s)assistant session cannot write anything in `~/.config/garrick/`")
        self.assertIn("python3 System/tools/machine.py set --role", page)

    def test_one_link_from_each_page_that_should_have_one(self):
        self.assertIn("(machines.md)", text("docs/harnesses.md"))
        self.assertIn("(../machines.md)", text("docs/extras/scheduled-jobs.md"))
        self.assertIn("System/garrick-docs/machines.md", text("template/System/skills/setup/SKILL.md"))

    def test_the_setup_skill_asks_only_when_told_and_never_writes_the_file(self):
        skill = text("template/System/skills/setup/SKILL.md")
        self.assertIn("Only when the user says it", skill)
        self.assertIn("Never write `~/.config/garrick/machine.json` with an edit tool", skill)
        self.assertIn("python3 System/tools/machine.py set --role", skill)

    def test_the_wrap_records_the_copy_step_when_the_server_cannot_reach_the_share(self):
        wrap = text("template/System/skills/threads/reference/wrap.md")
        self.assertIn("When this machine cannot reach the share", wrap)
        self.assertRegex(wrap, r"(?s)machine\.py.{0,400}`server`.{0,900}`Todo\.md`")
        self.assertIn("A copy to a share is a send", wrap)

    def test_no_skill_or_doc_page_for_this_names_an_assistant(self):
        for path in ("docs/machines.md", "template/System/skills/threads/reference/wrap.md"):
            body = text(path)
            if path.endswith("machines.md"):
                self.assertIsNone(re.search(r"Claude|Codex", body), path)


if __name__ == "__main__":
    unittest.main()
