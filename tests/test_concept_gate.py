"""The concept check (#654): a pull request that adds a concept must link its decision.

    cd tests && python3 -m unittest test_concept_gate
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import concept_gate as gate

REPO = Path(__file__).resolve().parent.parent
BASE = """# Concepts

## Where work lives

### Zone

A zone is one side of your life or work. It is its own folder.

### Thread

A thread is one line of work with one resume point.

## Instructions

### `AGENTS.md`

The entry point any assistant reads.
"""
COMMENT = "https://github.com/iamvenuti/garrick/issues/700#issuecomment-123456"


def note(concept, issue=700):
    return ("---\nconcept: %s\nissue: https://github.com/iamvenuti/garrick/issues/%d\n---\n\n# %s\n\n"
            "**The concept.** One sentence.\n" % (concept, issue, concept))


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.dir), True)
        self.git("init", "-q")
        self.git("config", "user.email", "jo@acme.example")
        self.git("config", "user.name", "Jo")
        self.write("docs/concepts.md", BASE)
        self.base = self.commit("base")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=str(self.dir), check=True, stdout=subprocess.PIPE,
                              text=True).stdout.strip()

    def write(self, rel, text):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode())

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def run_check(self, concepts, body, files=None, name="pull_request", payload=None):
        self.write("docs/concepts.md", concepts)
        for rel, text in (files or {}).items():
            self.write(rel, text)
        head = self.commit("head")
        event = self.dir.parent / (self.dir.name + ".json")
        self.addCleanup(lambda: event.exists() and event.unlink())
        event.write_text(payload if payload is not None else json.dumps(
            {"pull_request": {"body": body, "base": {"sha": self.base}, "head": {"sha": head}}}))
        return gate.check(name, str(event), self.dir)


class TheRule(Case):
    def test_a_new_heading_with_no_link_fails(self):
        ok, msg = self.run_check(BASE + "\n### Cedar\n\nA cedar is a tree.\n", "Adds Cedar.")
        self.assertFalse(ok)
        self.assertIn("Cedar", msg)

    def test_a_new_heading_with_a_comment_link_passes(self):
        ok, _ = self.run_check(BASE + "\n### Cedar\n\nA cedar is a tree.\n", "- Cedar: " + COMMENT)
        self.assertTrue(ok)

    def test_a_decision_file_whose_concept_matches_passes(self):
        ok, _ = self.run_check(BASE + "\n### Cedar\n\nA cedar is a tree.\n", "- Cedar: docs/decisions/700-cedar.md",
                               {"docs/decisions/700-cedar.md": note("Cedar")})
        self.assertTrue(ok)

    def test_a_backticked_heading_matches_by_its_text(self):
        ok, _ = self.run_check(BASE + "\n### `System/cedar.md`\n\nA file.\n", "- System/cedar.md: docs/decisions/1-c.md",
                               {"docs/decisions/1-c.md": note("System/cedar.md")})
        self.assertTrue(ok)

    def test_a_decision_file_whose_concept_differs_fails(self):
        ok, _ = self.run_check(BASE + "\n### Cedar\n\nA cedar is a tree.\n", "- Cedar: docs/decisions/700-cedar.md",
                               {"docs/decisions/700-cedar.md": note("Maple")})
        self.assertFalse(ok)

    def test_a_missing_decision_file_fails(self):
        ok, _ = self.run_check(BASE + "\n### Cedar\n\nA cedar is a tree.\n", "- Cedar: docs/decisions/700-cedar.md")
        self.assertFalse(ok)

    def test_a_decision_file_the_pull_request_did_not_touch_fails(self):
        self.write("docs/decisions/700-cedar.md", note("Cedar"))
        self.base = self.commit("an older note")
        ok, _ = self.run_check(BASE + "\n### Cedar\n\nA cedar is a tree.\n", "- Cedar: docs/decisions/700-cedar.md")
        self.assertFalse(ok)

    def test_a_wording_fix_below_an_unchanged_first_sentence_passes(self):
        ok, _ = self.run_check(BASE.replace("It is its own folder.", "It is its own folder, and its own repository."),
                               "Fixes wording.")
        self.assertTrue(ok)

    def test_a_new_paragraph_below_an_unchanged_first_sentence_passes(self):
        ok, _ = self.run_check(BASE.replace("### Thread", "More about zones.\n\n### Thread"), "")
        self.assertTrue(ok)

    def test_a_changed_first_sentence_with_no_link_fails(self):
        ok, msg = self.run_check(BASE.replace("A zone is one side of your life or work.", "A zone is a wall."), "x")
        self.assertFalse(ok)
        self.assertIn("Zone", msg)

    def test_a_changed_first_sentence_with_a_link_passes(self):
        ok, _ = self.run_check(BASE.replace("A zone is one side of your life or work.", "A zone is a wall."),
                               "- Zone: " + COMMENT)
        self.assertTrue(ok)

    def test_a_removed_heading_needs_nothing(self):
        ok, _ = self.run_check(BASE.replace("### Thread\n\nA thread is one line of work with one resume point.\n", ""), "")
        self.assertTrue(ok)

    def test_a_renamed_heading_counts_as_new(self):
        ok, _ = self.run_check(BASE.replace("### Thread", "### Strand"), "")
        self.assertFalse(ok)

    def test_a_bare_issue_link_fails(self):
        ok, _ = self.run_check(BASE + "\n### Cedar\n\nA cedar is a tree.\n",
                               "- Cedar: https://github.com/iamvenuti/garrick/issues/700")
        self.assertFalse(ok)

    def test_a_link_to_another_repository_fails(self):
        ok, _ = self.run_check(BASE + "\n### Cedar\n\nA cedar is a tree.\n",
                               "- Cedar: https://github.com/birch/other/issues/7#issuecomment-1")
        self.assertFalse(ok)

    def test_a_link_on_another_line_fails(self):
        ok, _ = self.run_check(BASE + "\n### Cedar\n\nA cedar is a tree.\n", "Cedar is new.\n" + COMMENT)
        self.assertFalse(ok)


class NoWayRound(Case):
    NEW = "\n\nA cedar is a tree.\n"

    def test_a_deeper_heading_is_not_hidden(self):
        self.assertFalse(self.run_check(BASE + "\n#### Cedar" + self.NEW, "")[0])

    def test_a_heading_with_closing_hashes_is_not_hidden(self):
        self.assertFalse(self.run_check(BASE + "\n### Cedar ###" + self.NEW, "")[0])

    def test_a_setext_heading_is_not_hidden(self):
        self.assertFalse(self.run_check(BASE + "\nCedar\n-----" + self.NEW, "")[0])
        self.assertFalse(self.run_check(BASE + "\nMaple\n=====" + self.NEW, "")[0])

    def test_an_html_heading_that_spans_lines_is_not_hidden(self):
        self.assertFalse(self.run_check(BASE + "\n<h2>\nCedar\n</h2>" + self.NEW, "")[0])
        self.assertFalse(self.run_check(BASE + "\n<h3 id=a\n>Cedar</h3>" + self.NEW, "")[0])
        self.assertTrue(self.run_check(BASE + "\n```\n<h2>\nCedar\n</h2>\n```\n", "")[0])

    def test_an_html_heading_is_not_hidden(self):
        self.assertFalse(self.run_check(BASE + "\n<h3>Cedar</h3>" + self.NEW, "")[0])

    def test_a_heading_in_a_quote_or_a_list_is_not_hidden(self):
        self.assertFalse(self.run_check(BASE + "\n> ### Cedar" + self.NEW, "")[0])
        self.assertFalse(self.run_check(BASE + "\n- ### Maple" + self.NEW, "")[0])

    def test_a_heading_in_a_code_block_is_no_heading(self):
        self.assertTrue(self.run_check(BASE + "\n```\n### Cedar\n```\n", "")[0])

    def test_a_heading_after_a_code_block_still_counts(self):
        self.assertFalse(self.run_check(BASE + "\n```\ncode\n```\n\n### Cedar" + self.NEW, "")[0])

    def test_a_heading_with_the_same_first_sentence_but_new_text_is_new(self):
        self.assertFalse(self.run_check(BASE.replace("### Thread", "### Strand"), "")[0])

    def test_one_comment_link_on_a_line_naming_two_headings_serves_neither(self):
        new = BASE + "\n### Cedar" + self.NEW + "\n### Maple\n\nA maple is a tree.\n"
        self.assertFalse(self.run_check(new, "- Cedar and Maple: " + COMMENT)[0])

    def test_two_lines_serve_two_headings(self):
        new = BASE + "\n### Cedar" + self.NEW + "\n### Maple\n\nA maple is a tree.\n"
        self.assertTrue(self.run_check(new, "- Cedar: %s\n- Maple: %s" % (COMMENT, COMMENT))[0])

    def test_a_short_heading_inside_a_longer_ones_line_is_not_served(self):
        new = BASE + "\n### Cedar" + self.NEW + "\n### Cedar wood\n\nA wood.\n"
        self.assertFalse(self.run_check(new, "- Cedar wood: " + COMMENT)[0])

    def test_windows_line_endings_read_the_same(self):
        crlf = (BASE + "\n### Cedar" + self.NEW).replace("\n", "\r\n")
        self.assertFalse(self.run_check(crlf, "")[0])
        self.assertTrue(self.run_check(crlf, "- Cedar: " + COMMENT.replace("700", "700") + "\r\n")[0])

    def test_a_body_with_windows_line_endings_reads(self):
        ok, _ = self.run_check(BASE + "\n### Cedar" + self.NEW, "Adds:\r\n- Cedar: " + COMMENT + "\r\nDone.")
        self.assertTrue(ok)

    def test_a_decision_note_for_another_pull_request_is_not_taken_twice(self):
        # a note for the old text is no note for a new heading of another text
        ok, _ = self.run_check(BASE + "\n### Cedar" + self.NEW, "- Cedar: docs/decisions/700-cedar.md",
                               {"docs/decisions/700-cedar.md": note("Cedar wood")})
        self.assertFalse(ok)

    def test_a_decision_path_that_climbs_out_is_no_note(self):
        ok, _ = self.run_check(BASE + "\n### Cedar" + self.NEW, "- Cedar: docs/decisions/../concepts.md")
        self.assertFalse(ok)


class AgainstTheMergeBase(Case):
    def test_a_change_made_on_the_base_since_the_branch_is_not_the_pull_requests(self):
        self.git("checkout", "-q", "-b", "pr")
        self.write("docs/concepts.md", BASE + "\nAn aside.\n")
        head = self.commit("pr work")
        self.git("checkout", "-q", "-")
        self.write("docs/concepts.md", BASE.replace("A zone is one side of your life or work.", "A zone is a wall."))
        tip = self.commit("main moves on")
        event = self.dir.parent / (self.dir.name + "-mb.json")
        self.addCleanup(lambda: event.exists() and event.unlink())
        event.write_text(json.dumps({"pull_request": {"body": "", "base": {"sha": tip}, "head": {"sha": head}}}))
        ok, msg = gate.check("pull_request", str(event), self.dir)
        self.assertTrue(ok, msg)


class FailsClosed(Case):
    def test_no_pull_request_event_passes(self):
        ok, msg = self.run_check(BASE + "\n### Cedar\n\nA tree.\n", "", name="push")
        self.assertTrue(ok)
        self.assertIn("Not a pull request", msg)

    def test_an_unreadable_payload_fails(self):
        self.assertFalse(self.run_check(BASE, "", payload="not json")[0])
        self.assertFalse(self.run_check(BASE, "", payload="{}")[0])
        self.assertFalse(self.run_check(BASE, "", payload='{"pull_request": {"base": {}, "head": {}}}')[0])

    def test_a_missing_payload_file_fails(self):
        ok, _ = gate.check("pull_request", str(self.dir / "nothing.json"), self.dir)
        self.assertFalse(ok)

    def test_a_missing_base_or_head_fails(self):
        for base, head in (("0" * 40, None), (None, "0" * 40), ("--output=x", None)):
            self.write("docs/concepts.md", BASE + "\n### Cedar\n\nA tree.\n")
            real = self.commit("head")
            event = self.dir / "event.json"
            event.write_text(json.dumps({"pull_request": {"body": "", "base": {"sha": base or self.base},
                                                          "head": {"sha": head or real}}}))
            self.assertFalse(gate.check("pull_request", str(event), self.dir)[0], (base, head))

    def test_a_pull_request_with_no_body_and_no_new_concept_passes(self):
        ok, _ = self.run_check(BASE, None)
        self.assertTrue(ok)


class ThisBranch(unittest.TestCase):
    def test_this_branch_names_a_decision_for_every_heading_it_adds(self):
        tag = subprocess.run(["git", "rev-parse", "--verify", "-q", "v0.76.0^{commit}"], cwd=str(REPO),
                             stdout=subprocess.PIPE, text=True)
        if tag.returncode:
            self.skipTest("No v0.76.0 tag in this clone.")
        base = tag.stdout.strip()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO), stdout=subprocess.PIPE, text=True).stdout.strip()
        # An unstaged or uncommitted docs/concepts.md is not what a pull request carries: read the commit.
        need = gate.triggered(gate.show(base, gate.CONCEPTS), gate.show(head, gate.CONCEPTS))
        notes = {}
        for p in sorted((REPO / "docs" / "decisions").glob("*.md")):
            if p.name != "README.md":
                notes[gate.concept_of(p.read_text(encoding="utf-8"))] = "docs/decisions/" + p.name
        body = "\n".join("- %s: %s" % (h, notes.get(h, "")) for h in need)
        event = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(event), True)
        (event / "e.json").write_text(json.dumps({"pull_request": {"body": body, "base": {"sha": base}, "head": {"sha": head}}}))
        ok, msg = gate.check("pull_request", str(event / "e.json"))
        self.assertTrue(ok, msg)

    def test_every_decision_note_has_its_shape(self):
        for p in sorted((REPO / "docs" / "decisions").glob("*.md")):
            if p.name == "README.md":
                continue
            text = p.read_text(encoding="utf-8")
            self.assertTrue(gate.concept_of(text), p.name + " has no concept:")
            self.assertRegex(text, r"(?m)^issue: https://github\.com/iamvenuti/garrick/issues/\d+$", p.name)
            for part in ("The concept.", "What it touches.", "What was measured.", "What would show it is wrong."):
                self.assertIn("**%s**" % part, text, p.name)


class TheNotesStayHere(unittest.TestCase):
    def test_a_workspace_is_not_given_the_decision_notes(self):
        import sys
        sys.path.insert(0, str(REPO))
        self.addCleanup(sys.path.remove, str(REPO))
        import install
        shipped = install.docs_files()
        self.assertIn("concepts.md", shipped)
        self.assertEqual([], [n for n in shipped if n.startswith("decisions/")])


    def test_the_guide_does_not_take_a_decision_note_for_a_page(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("garrick_guide_t", str(REPO / "extras" / "status" / "guide.py"))
        guide = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guide)
        pages = guide.doc_pages(REPO / "docs")
        self.assertIn("concepts.md", pages)
        self.assertEqual([], [p for p in pages if p.startswith("decisions/")])


class TheWorkflow(unittest.TestCase):
    def test_ci_runs_the_check_on_every_pull_request_and_waits_for_it(self):
        text = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertIn("python3 tests/concept_gate.py", text)
        self.assertRegex(text, r"(?s)concept:.*?github\.event_name == 'pull_request'.*?fetch-depth: 0")
        self.assertRegex(text, r"needs: \[plan, branch, test, concept\]")
        self.assertIn("edited", text)


if __name__ == "__main__":
    unittest.main()
