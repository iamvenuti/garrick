"""The remote access manifest (#702, gate A17): every declared verb has a remote disposition.

extras/remote/manifest.json lists each verb of operations.DECLARED, each shipped skill and the five read tools,
each with one disposition. These tests fail when the list and the code disagree, whichever way, and hold the
counts and the docs table to the manifest. Standard library only: the service's own tests, which need its
runtime, are in extras/remote/tests/.

    python3 -m unittest discover -s tests -p test_remote_manifest.py
"""

from __future__ import annotations

import copy
import importlib.util
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
EXTRA = REPO / "extras" / "remote"
DOCS = REPO / "docs" / "extras" / "remote-access.md"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


manifest = _load("garrick_remote_manifest_under_test", EXTRA / "tools" / "manifest.py")
operations = _load("garrick_operations_for_manifest", REPO / "template" / "System" / "tools" / "operations.py")
SKILLS = sorted(p.name for p in (REPO / "template" / "System" / "skills").iterdir() if (p / "SKILL.md").is_file())
PAGE_ONLY = ("walls-look", "walls-allow", "commit-files", "chase", "layout", "outbox-drop", "inbox-run", "intake-answer",
             "machine-role", "read-guard", "connected-service", "channel-answers", "count-card", "session-url")


class TestEveryVerbHasADisposition(unittest.TestCase):
    def setUp(self):
        self.m = manifest.load()
        self.declared = manifest.declared_verbs(operations)

    def test_the_manifest_is_whole_against_the_code(self):
        self.assertEqual([], manifest.check(self.m, self.declared, SKILLS))

    def test_a_declared_verb_the_manifest_lacks_fails(self):
        bad = manifest.check(self.m, self.declared + ["a-new-verb"], SKILLS)
        self.assertEqual(["the verb a-new-verb is declared and the manifest does not list it"], bad)

    def test_a_verb_the_manifest_lists_and_nothing_declares_fails(self):
        bad = manifest.check(self.m, [v for v in self.declared if v != "park"], SKILLS)
        self.assertEqual(["the manifest lists park, which is not a declared verb"], bad)

    def test_adding_a_verb_to_a_fixture_declaration_proves_it(self):
        fake = type("Ops", (), {"DECLARED": dict(operations.DECLARED, **{"fixture-verb": operations.DECLARED["park"]})})
        self.assertTrue(manifest.check(self.m, manifest.declared_verbs(fake), SKILLS))

    def test_a_skill_the_manifest_lacks_fails(self):
        self.assertTrue(manifest.check(self.m, self.declared, SKILLS + ["a-new-skill"]))

    def test_a_row_with_no_disposition_or_no_reason_fails(self):
        for field, value in (("disposition", "maybe"), ("release", "soon")):
            m = copy.deepcopy(self.m)
            m["rows"][0][field] = value
            self.assertTrue(manifest.check(m, self.declared, SKILLS), field)
        m = copy.deepcopy(self.m)
        row = next(r for r in m["rows"] if r["disposition"] == "internal")
        row["reason"] = ""
        self.assertTrue(manifest.check(m, self.declared, SKILLS))
        m = copy.deepcopy(self.m)
        row = next(r for r in m["rows"] if r["disposition"] == "owner-approval")
        row["reason"] = ""
        self.assertTrue(manifest.check(m, self.declared, SKILLS))

    def test_a_served_row_must_be_now_and_nothing_else_is(self):
        m = copy.deepcopy(self.m)
        next(r for r in m["rows"] if r["disposition"] == "served")["release"] = "later"
        self.assertTrue(manifest.check(m, self.declared, SKILLS))

    def test_a_row_listed_twice_fails(self):
        m = copy.deepcopy(self.m)
        m["rows"].append(dict(m["rows"][0]))
        self.assertTrue(manifest.check(m, self.declared, SKILLS))


class TestTheCounts(unittest.TestCase):
    def setUp(self):
        self.m = manifest.load()

    def test_the_counts_are_the_ones_the_issue_gives_and_one_internal_more(self):
        # 0.85.0 serves the six lifecycle verbs (#724): check-name, new-project, new-thread, rename, move and undo
        self.assertEqual({"served": 16, "owner-approval": 17, "internal": 7, "not-yet": 27}, manifest.counts(self.m))
        self.assertEqual(len(operations.DECLARED), sum(manifest.counts(self.m).values()))

    def test_the_served_verbs(self):
        self.assertEqual(sorted(["note-add", "todo-add", "todo-done", "todo-undo", "todo-date", "todo-edit", "todo-retire",
                                 "park", "wake", "checkpoint",
                                 "check-name", "new-project", "new-thread", "rename", "move", "undo"]), sorted(manifest.served_verbs(self.m)))

    def test_the_five_read_tools_are_served_apart(self):
        self.assertEqual(["places", "thread_state", "search", "read", "owed"], sorted(
            manifest.served_tools(self.m), key=["places", "thread_state", "search", "read", "owed"].index))

    def test_owner_approval_is_twelve_of_the_page_only_verbs_and_five_more(self):
        approval = {r["name"] for r in manifest.rows(self.m, "verb") if r["disposition"] == "owner-approval"}
        page_only = set(PAGE_ONLY) - {"count-card", "session-url"}
        self.assertEqual(12, len(page_only))
        self.assertEqual(page_only | {"new-project-party", "delete", "settings", "release-update", "run"}, approval)

    def test_internal_verbs_have_no_tool(self):
        internal = {r["name"] for r in manifest.rows(self.m, "verb") if r["disposition"] == "internal"}
        self.assertEqual({"operations", "files-progress", "files-stop", "count-card", "session-url", "note-read", "remote"}, internal)
        self.assertEqual("changes only at the Mac", next(r for r in self.m["rows"] if r["name"] == "remote")["reason"])

    def test_note_read_is_never_served(self):
        self.assertNotIn("note-read", manifest.served_verbs(self.m))


class TestAnAnswerForAVerbNotServed(unittest.TestCase):
    def setUp(self):
        self.m = manifest.load()

    def test_a_not_yet_verb_gets_a_plain_reason_and_its_release(self):
        self.assertEqual("wrap is not available from a remote assistant yet. It is planned in the next release.",
                         manifest.answer(self.m, "wrap"))
        self.assertIn("in a later release", manifest.answer(self.m, "question-answer"))

    def test_an_owner_approval_verb_says_so(self):
        self.assertIn("runs only after the owner approves it", manifest.answer(self.m, "delete"))

    def test_an_internal_verb_is_not_offered(self):
        self.assertIn("not offered", manifest.answer(self.m, "note-read"))

    def test_a_name_that_is_no_verb_gets_no_detail(self):
        self.assertEqual("That is not something this service does.", manifest.answer(self.m, "../../etc/passwd"))


class TestTheDocsTable(unittest.TestCase):
    def test_the_table_is_printed_by_a_module_entry(self):
        out = subprocess.run([sys.executable, "-m", "tools.manifest"], cwd=str(EXTRA), capture_output=True, text=True)
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertEqual(manifest.table(manifest.load()), out.stdout)

    def test_the_table_lists_every_row_once(self):
        m = manifest.load()
        lines = manifest.table(m).splitlines()[2:]
        self.assertEqual(len(m["rows"]), len(lines))

    @unittest.skipUnless(DOCS.is_file(), "the docs page is not in this branch yet")
    def test_the_docs_page_holds_the_generated_table(self):
        text = DOCS.read_text(encoding="utf-8")
        got = re.search(r"<!-- manifest -->\n(.*?)<!-- /manifest -->", text, re.S)
        self.assertIsNotNone(got, "the page has no manifest markers")
        self.assertEqual(manifest.table(manifest.load()).strip(), got.group(1).strip())


if __name__ == "__main__":
    unittest.main()
