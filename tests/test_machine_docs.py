"""The docs and skills for machines (#612) say what the code does.

    python3 -m unittest test_machine_docs
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "template" / "System" / "skills"


def text(path):
    return (REPO / path).read_text(encoding="utf-8")


class MachineDocs(unittest.TestCase):
    def test_the_wrap_records_the_copy_step_when_the_server_cannot_reach_the_share(self):
        wrap = text("template/System/skills/threads/reference/wrap.md")
        self.assertIn("When this machine cannot reach the share", wrap)
        self.assertRegex(wrap, r"(?s)machine\.py.{0,400}`server`.{0,900}`Todo\.md`")
        self.assertIn("A copy to a share is a send", wrap)


if __name__ == "__main__":
    unittest.main()
