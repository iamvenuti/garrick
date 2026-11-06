"""`public`: material anyone may read, into which nothing is written down (#398).

    cd tests && python3 -m unittest test_public

Reed is a project whose hub names `public`. Every scope reads it. Its own files
are checked as a project walled from every party: a person of any party, a
meeting page, quoted wording or a link to a project of a party is refused, and a
link to a Knowledge page or to another public project is not.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import project_hub, thread_note, write  # noqa: E402
from walls_fixture import build  # noqa: E402

import check  # noqa: E402
import garrick_lib as lib  # noqa: E402
import scaffold  # noqa: E402


class PublicProjectTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build(self.root)
        work = self.root / "Zones" / "Work"
        write(work / "Reed Two" / "Reed Two.md", project_hub("Work", "Reed Two", "public", ["Notes"]))
        write(work / "Reed Two" / "Threads" / "Notes" / "Notes.md", thread_note("Reed Two", "Notes", "public"))
        write(work / "Reed Two" / "Threads" / "Notes" / "Guide.md", "# Guide\n\nAnyone may read this.\n")
        write(work / "Northwind" / "Threads" / "Pricing" / "Memo.md", "# Memo\n\nPrivate to Acme.\n")
        self.note = work / "Reed" / "Threads" / "Notes" / "Draft.md"

    def says(self, text):
        write(self.note, text)
        return [(f.severity, f.message) for f in check.run_checks(self.root, walls_only=True)
                if f.path == "Zones/Work/Reed/Threads/Notes/Draft.md"]

    def test_a_person_of_any_party_is_refused(self):
        for name in ("Dana Whitlock", "Theo Marsh"):
            with self.subTest(name):
                found = self.says("# Draft\n\nAsk %s about it.\n" % name)
                self.assertEqual(["error"], [s for s, _ in found], found)

    def test_a_meeting_page_of_any_party_is_refused(self):
        for page in ("260310-acme-kickoff", "260312-birch-kickoff"):
            with self.subTest(page):
                found = self.says("# Draft\n\nSee [[%s]].\n" % page)
                self.assertTrue(found and {s for s, _ in found} == {"error"}, found)

    def test_a_project_of_a_party_is_refused(self):
        found = self.says("# Draft\n\nSee [[Memo]].\n")
        self.assertEqual(["error"], [s for s, _ in found], found)

    def test_a_knowledge_page_and_another_public_record_are_not(self):
        found = self.says("# Draft\n\nSee [[resilience]] and [[Guide]].\n")
        self.assertEqual([], found)

    def test_a_project_with_no_party_is_not_public(self):
        write(self.root / "Zones" / "Work" / "Orchard" / "Threads" / "Drafts" / "Draft.md", "# Draft\n\nPlain.\n")
        found = [f for f in check.run_checks(self.root) if f.check == "projects" and "Orchard" in f.path]
        self.assertTrue(any(f.severity == "error" and "no `party`" in f.message for f in found))

    def test_a_party_row_for_public_is_refused(self):
        ctx = self.root / "System" / "context.md"
        text = ctx.read_text(encoding="utf-8").replace(
            "| Birch & Co |", "| Open Notes | Anyone | Work | `public` | |\n| Birch & Co |")
        ctx.write_text(text, encoding="utf-8")
        found = [f for f in check.run_checks(self.root) if f.check == "context" and "public" in f.message]
        self.assertTrue(found and found[0].severity == "error", found)

    def test_public_does_not_stand_with_a_party(self):
        hub = self.root / "Zones" / "Work" / "Reed" / "Reed.md"
        hub.write_text(hub.read_text(encoding="utf-8").replace("party: public", "party: [public, acme]"), encoding="utf-8")
        found = [f for f in check.run_checks(self.root) if f.path.endswith("Reed/Reed.md") and "stands alone" in f.message]
        self.assertEqual(1, len(found))

    def test_the_hub_names_public_without_an_unknown_party_error(self):
        found = [f for f in check.run_checks(self.root) if f.path.endswith("Reed/Reed.md") and f.severity == "error"]
        self.assertEqual([], found)

    def test_scaffold_takes_public_with_no_parties_row(self):
        self.assertEqual("public", scaffold.check_party(self.root, "public", "Work"))
        self.assertEqual("public", scaffold.check_party(self.root, "`public`"))

    def test_nothing_defines_public_as_a_party_by_scaffold(self):
        args = type("A", (), dict(name="Public", zone="Work", what="x", also=None, walled_from=None, why=None,
                                  check=False, spoken=None))()
        with self.assertRaises(scaffold.Refusal):
            scaffold.cmd_party(self.root, args, "2026-11-06")

    def test_every_scope_reads_a_public_record_and_none_writes_into_it(self):
        ctx = lib.load_context(self.root)
        got = lib.labels(self.root, "Zones/Work/Reed/Threads/Notes/Notes.md", ctx)
        self.assertEqual({"public"}, got)
        for scope in ({"acme"}, {"birch"}, set()):
            self.assertEqual("permit", lib.decide(scope, got, "read", ctx))
        for material in ({"acme"}, {"birch"}):
            self.assertEqual("deny", lib.decide(got, material, "write", ctx))
            self.assertEqual("deny", lib.decide(got, material, "file", ctx))
        self.assertEqual("permit", lib.decide(got, {"public"}, "write", ctx))


if __name__ == "__main__":
    unittest.main()
