"""One-word names, the user's own templates, and the check's own words (0.62.0).

    cd tests && python3 -m unittest test_names

The fixture is the wall cases' (walls_fixture): Northwind is Acme's, Reed is Cedar Ltd's, an open party's. Kit and
Wren are two people of Acme who go by one word; `kit` is Kit's person page. Invented names only.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from walls_fixture import build  # noqa: E402

import check  # noqa: E402

LINE = ("Commit refused: Zones/Work/Reed/Threads/Notes/X.md names Acme Corp, or one of its people; acme is walled and "
        "this project does not name it. Take it out and commit again; only if you mean it, git commit --no-verify.")
SENTENCE = "The quarterly review covers pallet routing, supplier lead times and the harbour handover plan."


class NamesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name).resolve() / "Workspace"
        build(cls.root)
        cls.work = cls.root / "Zones" / "Work"
        context = cls.root / "System" / "context.md"
        text = context.read_text(encoding="utf-8")
        context.write_text(text.replace("| dana whitlaw | Dana Whitlock |\n", "| dana whitlaw | Dana Whitlock |\n| kitten | Kit |\n"),
                           encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def found(self, text, project="Reed", thread="Notes"):
        path = self.work / project / "Threads" / thread / "Case.md"
        write(path, text)
        try:
            where = path.relative_to(self.root).as_posix()
            return [f for f in check.run_checks(self.root, walls_only=True) if f.path == where]
        finally:
            path.unlink()

    def verdict(self, text, **kw):
        got = self.found(text, **kw)
        return "refused" if any(f.severity == "error" for f in got) else "warned" if got else "clear"

    # -- one-word names -------------------------------------------------------

    def test_a_one_word_name_alone_warns_and_does_not_refuse(self):
        self.assertEqual("warned", self.verdict("# N\n\nAsk Kit about the order.\n"))
        self.assertEqual("warned", self.verdict("# N\n\nask kit about the order.\n"))
        self.assertEqual("warned", self.verdict("# N\n\nAsk kitten about the order.\n"))     # an alias of the same row
        self.assertEqual("warned", self.verdict("# N\n\nAsk Kit; Kit knows.\n"))             # the same person twice

    def test_the_warning_names_no_one(self):
        message = self.found("# N\n\nAsk Kit.\n")[0].message
        self.assertNotIn("Kit", message)
        self.assertIn("one word", message)

    def test_it_refuses_beside_the_partys_name_a_longer_name_or_a_second_one_word_person(self):
        for text in ("Ask Kit at Acme Corp.", "Ask Kit about acmecorp.example.", "Ask Kit and Dana Whitlock.",
                     "Ask Kit and Wren.", "Ask kitten and Wren.", "Ask Kit, who works for acme."):
            with self.subTest(text=text):
                self.assertEqual("refused", self.verdict("# N\n\n%s\n" % text))

    def test_it_refuses_a_link_to_the_persons_page(self):
        self.assertEqual("refused", self.verdict("# N\n\nAsk [[kit]].\n"))
        self.assertEqual("refused", self.verdict("# N\n\nAsk [[wiki/people/kit|Kit]].\n"))

    def test_full_names_and_the_partys_own_names_refuse_alone_as_before(self):
        for text in ("Ask Dana Whitlock.", "Ask Acme Corp.", "Ask dana whitlaw.", "Write to a@acmecorp.example."):
            with self.subTest(text=text):
                self.assertEqual("refused", self.verdict("# N\n\n%s\n" % text))

    def test_the_near_side_may_write_its_own_one_word_names(self):
        self.assertEqual("clear", self.verdict("# N\n\nAsk Kit and Wren at Acme Corp.\n", project="Northwind", thread="Pricing"))

    def test_the_wording_check_still_catches_a_quotation(self):
        write(self.work / "Northwind" / "Threads" / "Pricing" / "Source.md", "# S\n\n%s\n" % SENTENCE)
        try:
            self.assertEqual("refused", self.verdict("# N\n\nKit said: %s\n" % SENTENCE))
        finally:
            (self.work / "Northwind" / "Threads" / "Pricing" / "Source.md").unlink()

    # -- the user's own templates ----------------------------------------------

    def mine(self, name="hub.md", text="# Hub\n\n%s\n" % SENTENCE):
        path = self.root / "System" / "templates.local" / name
        write(path, text)
        self.addCleanup(shutil.rmtree, path.parent, True)
        return path

    def test_a_sentence_in_templates_local_is_common_wording_and_the_same_sentence_from_a_walled_note_is_not(self):
        write(self.work / "Northwind" / "Threads" / "Pricing" / "Source.md", "# S\n\n%s\n" % SENTENCE)
        self.addCleanup((self.work / "Northwind" / "Threads" / "Pricing" / "Source.md").unlink)
        self.assertEqual("refused", self.verdict("# N\n\n%s\n" % SENTENCE))
        self.mine()
        self.assertEqual("clear", self.verdict("# N\n\n%s\n" % SENTENCE))

    def test_a_file_there_that_names_a_party_or_carries_a_party_key_is_warned_about(self):
        self.mine("clean.md")
        self.mine("named.md", "# Hub\n\nAsk Dana Whitlock.\n")
        self.mine("keyed.md", "---\nparty: acme\n---\n\n# Hub\n")
        self.mine("keyed-upper.md", "---\nParties: [acme]\n---\n\n# Hub\n")
        got = {f.path.split("/")[-1]: f for f in check.run_checks(self.root, walls_only=True) if "templates.local" in f.path}
        self.assertEqual({"named.md", "keyed.md", "keyed-upper.md"}, set(got))
        self.assertTrue(all(f.severity == "warning" for f in got.values()))
        self.assertIn("carries a party key", got["keyed.md"].message)

    def test_templates_local_is_a_template_path(self):
        ws = check.discover(self.root, None)
        self.assertTrue(check.is_template_path(ws, self.root / "System" / "templates.local" / "x.md"))
        self.assertTrue(check.is_template_path(ws, self.root / "System" / "templates" / "x.md"))
        self.assertFalse(check.is_template_path(ws, self.root / "System" / "templates.localx" / "x.md"))



if __name__ == "__main__":
    unittest.main()
