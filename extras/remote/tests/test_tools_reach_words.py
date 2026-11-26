"""The machine code and the spoken sentence for a request outside the reach are context.py's: the tools keep one copy, and this fails when they differ.
It skips only while extras/remote/context.py is not in the tree."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
EXTRA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXTRA))

from tools import common  # noqa: E402


@unittest.skipUnless((EXTRA / "context.py").is_file(), "extras/remote/context.py is not in this tree")
class ReachWords(unittest.TestCase):
    def constant(self, name):
        text = (EXTRA / "context.py").read_text(encoding="utf-8")
        return re.search(r'(?m)^%s = "([^"]*)"' % name, text).group(1)

    def test_the_code_and_the_sentence_are_contexts(self):
        self.assertEqual(self.constant("NEW_CONTEXT_REQUIRED"), common.NEW_REACH)
        self.assertEqual(self.constant("NEW_CONTEXT_SAY"), common.REACH_SAY)
        self.assertEqual(common.REACH_SAY, common.WRITE_REACH_SAY)

    def test_the_handle_words_are_contexts(self):
        self.assertEqual(self.constant("HANDLE_WORDS"), common.NEW_CHAT_SAY)


if __name__ == "__main__":
    unittest.main()
