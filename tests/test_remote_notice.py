"""Remote access (preview): the notice before a walled zone is turned on is one text, in Settings and in the docs (#698, #703).

    cd tests && python3 -m unittest test_remote_notice

`extras/remote/notice.md` is the text Settings shows, `{zone}` the one placeholder. `docs/extras/remote-access.md` carries the same words
between `<!-- notice -->` and `<!-- /notice -->`. This test skips only while that docs page is absent; the release gate checks that it ran.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
NOTICE = REPO / "extras" / "remote" / "notice.md"
DOCS = REPO / "docs" / "extras" / "remote-access.md"

TEXT = ("Turning on {zone} lets a connected assistant see what this zone holds. What it reads leaves this Mac. It goes through your address: "
        "the relay carries it but cannot read it, and a server of your own that forwards it can. Then it goes to the assistant's provider, where "
        "it becomes part of the chat. It stays in the chat history after you revoke access. Another connector in the same chat, such as mail, "
        "can carry it further. The commit check does not see a chat.")


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class Notice(unittest.TestCase):
    def test_the_notice_is_the_fixed_text_with_one_placeholder(self):
        text = squash(NOTICE.read_text(encoding="utf-8"))
        self.assertEqual(text, TEXT)
        self.assertEqual(text.count("{zone}"), 1)
        self.assertEqual(len(re.findall(r"\{[^}]*\}", text)), 1)

    def test_the_docs_carry_the_same_words(self):
        if not DOCS.is_file():
            self.skipTest("docs/extras/remote-access.md is not in this branch yet")
        page = DOCS.read_text(encoding="utf-8")
        block = re.search(r"<!-- notice -->(.*?)<!-- /notice -->", page, re.S)
        self.assertIsNotNone(block, "the docs page has no notice block")
        shown = squash(re.sub(r"^>\s?", "", block.group(1), flags=re.M))
        self.assertEqual(shown, squash(NOTICE.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
