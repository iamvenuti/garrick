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

    # -- the check's own words -------------------------------------------------

    def test_a_quoted_refusal_line_is_not_material(self):
        for text in (LINE, LINE.replace("Acme Corp", "<acme>"), "  error   Zones/x.md: names Acme Corp (as \"acme\"), or one of "
                     "its people; acme is walled and this project does not name it",
                     "> " + LINE, "`" + LINE + "`",
                     "A note in Reed names Acme Corp",
                     "A wall holds some material back from this project, so I have not used it. Nothing was written."):
            with self.subTest(text=text):
                self.assertEqual("clear", self.verdict("# N\n\nThe hook said:\n\n%s\n" % text))

    def test_a_line_that_holds_more_than_the_check_prints_is_the_notes_own(self):
        for text in (LINE + " Ask Dana Whitlock.", LINE.replace("acme is walled", "Kit is walled"), "Ask Acme Corp. " + LINE.split(".")[0],
                     "Commit refused: Zones/x.md names Acme Corp."):
            with self.subTest(text=text):
                self.assertEqual("refused", self.verdict("# N\n\n%s\n" % text))
        # the party named beside the line, not in it
        self.assertEqual("refused", self.verdict("# N\n\nAcme Corp.\n\n%s\n" % LINE))

    def test_a_link_on_a_quoted_line_is_still_a_link(self):
        self.assertEqual("refused", self.verdict("# N\n\n%s [[260310-acme-kickoff]]\n" % LINE))

    def run_main(self, *args, tty=False):
        out, err = io.StringIO(), io.StringIO()
        for stream in (out, err):
            stream.isatty = lambda tty=tty: tty
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(check, "record_refusals", lambda *a, **k: None):
            code = check.main(["--root", str(self.root)] + list(args))
        return code, out.getvalue(), err.getvalue()

    def test_json_and_a_run_with_no_terminal_name_a_walled_party_by_its_tag(self):
        path = self.work / "Reed" / "Threads" / "Notes" / "Case.md"
        write(path, "# N\n\nAsk Dana Whitlock.\n")
        self.addCleanup(path.unlink)
        code, out, _ = self.run_main("--walls-only", "--json")
        self.assertEqual(1, code)
        message = [f for f in json.loads(out)["findings"] if f["path"].endswith("Reed/Threads/Notes/Case.md")][0]
        self.assertEqual("names <acme>, or one of its people; acme is walled and this project does not name it", message["message"])
        self.assertNotIn("Acme Corp", message["ear"])
        self.assertIn("<acme>", message["ear"])
        _, text, _ = self.run_main("--walls-only")
        self.assertNotIn("Acme Corp", text)
        self.assertIn("<acme>", text)

    def test_a_terminal_is_shown_the_name(self):
        path = self.work / "Reed" / "Threads" / "Notes" / "Case.md"
        write(path, "# N\n\nAsk Dana Whitlock.\n")
        self.addCleanup(path.unlink)
        _, text, _ = self.run_main("--walls-only", tty=True)
        self.assertIn("names Acme Corp", text)

    def test_the_hooks_line_pasted_back_names_nobody_and_is_not_refused(self):
        findings = [check.Finding("error", "walls", "Zones/Work/Reed/x.md",
                                  "names Acme Corp (as \"acme\"), or one of its people; acme is walled and this project does not name it")]
        shown = check.assistant_findings(self.root, findings)[0]
        line = "Commit refused: %s %s. Take it out and commit again; only if you mean it, git commit --no-verify." % (shown.path, shown.message)
        self.assertNotIn("Acme", line)
        self.assertEqual("clear", self.verdict("# N\n\n%s\n" % line))

    def test_a_name_that_is_an_everyday_word_is_left_alone(self):
        shown = check.assistant_findings(self.root, [check.Finding("warning", "x", "p", "the Personal zone and Acme Corp", "")])[0]
        self.assertEqual("the Personal zone and <acme>", shown.message)


if __name__ == "__main__":
    unittest.main()
