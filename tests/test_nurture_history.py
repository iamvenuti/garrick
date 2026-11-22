"""Nurture and the history files (#502): a note over its cap is a mechanical finding that says its words before and
after and that the nightly run may apply; a Resume here block over its limit is judgment, never applied.

    cd tests && python3 -m unittest test_nurture_history
"""

from __future__ import annotations

import datetime
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import git, thread_note, write  # noqa: E402
from test_nurture import Base, nurture  # noqa: E402

TODAY = datetime.date(2026, 10, 17)            # the date Base.run_tool passes


def entries(count, words=250):
    out = []
    for i in range(count):
        d = TODAY - datetime.timedelta(days=i * 3 + 1)
        filler = " ".join("freight%d" % k for k in range(words))
        out.append("**%d %s %d.** Session %d settled the freight plan.\n\nMore: %s.\n" % (d.day, d.strftime("%B"), d.year, i, filler))
    return "\n".join(out)


class HistoryItems(Base):
    def setUp(self):
        super().setUp()
        self.freight = self.acme / "Threads" / "Freight" / "Freight.md"
        text = self.freight.read_text(encoding="utf-8")
        write(self.freight, text.rstrip("\n") + "\n\n---\n\n" + entries(30))
        self.commit(self.work, "2026-10-01T10:00:00")

    def history_items(self, out):
        return [i for i in out["items"] if i["path"].endswith("Freight/Freight.md") and i.get("fix", {}) and i["fix"].get("op") == "history"]

    def test_a_note_over_its_cap_is_a_mechanical_finding_with_both_counts(self):
        _, out = self.run_tool("list")
        (item,) = self.history_items(out)
        self.assertEqual("mechanical", item["kind"])
        self.assertGreater(item["fix"]["before"], 4000)
        self.assertLessEqual(item["fix"]["after"], 4000)
        self.assertIn("words down to", item["line"] if "line" in item else json.dumps(item))
        self.assertTrue(any("history/" in t for t in item["touches"]) if "touches" in item else True)

    def test_fix_moves_the_entries_in_one_commit_of_the_files_it_changed(self):
        before = len(self.log(self.work))
        code, out = self.run_tool("fix", "--yes")
        self.assertEqual(0, code, out)
        self.assertEqual(before + 1, len(self.log(self.work)))
        files = git(self.work, "show", "--name-only", "--format=", "HEAD").splitlines()
        self.assertIn("Acme Review/Threads/Freight/Freight.md", files)
        self.assertTrue([f for f in files if "/history/Freight history " in f])
        text = self.freight.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.split()), 4000)
        _, again = self.run_tool("list")
        self.assertEqual([], self.history_items(again))

    def test_the_nightly_run_may_apply_it(self):
        code, out = self.run_tool("nightly")
        self.assertEqual(0, code, out)
        self.assertIn("history", {i["fix"]["op"] for i in out["fixed"]})
        self.assertTrue(list((self.freight.parent / "history").glob("*.md")))

    def test_a_resume_block_over_its_limit_is_judgment_and_no_run_changes_it(self):
        text = self.freight.read_text(encoding="utf-8")
        long_block = "**Where it stands, 10 October 2026.** " + " ".join("stands%d" % k for k in range(600)) + "\n"
        text = text.replace("**Where it stands, 1 March 2026.** Drafting.\n", long_block)
        write(self.freight, text)
        self.commit(self.work, "2026-10-02T10:00:00")
        _, out = self.run_tool("list")
        found = [i for i in out["items"] if i["path"].endswith("Freight/Freight.md") and i["check"] == "resume"]
        self.assertEqual(["judgment"], [i["kind"] for i in found])
        self.assertIn("resume-max-words", found[0]["message"])
        self.run_tool("fix", "--yes")
        self.run_tool("nightly")
        self.assertIn(long_block, self.freight.read_text(encoding="utf-8"))

    def test_a_note_it_cannot_read_for_certain_is_held_and_nothing_moves(self):
        text = self.freight.read_text(encoding="utf-8").replace("\n---\n\n**", "\n\n**", 1)
        write(self.freight, text)
        self.commit(self.work, "2026-10-02T10:00:00")
        _, out = self.run_tool("fix", "--yes")
        self.assertFalse((self.freight.parent / "history").exists())
        self.assertEqual(text, self.freight.read_text(encoding="utf-8"))


class OldParentLinks(Base):
    """#627, point 3: a history file the first history.py wrote carries `parent: "[[<Note>]]"`; Nurture rewrites that one line to the
    current form as a mechanical fix, in one commit for the repository, through its hook. A file that is not that is never touched."""

    def setUp(self):
        super().setUp()
        self.freight = self.acme / "Threads" / "Freight" / "Freight.md"
        self.folder = self.freight.parent / "history"

    def history_file(self, name, parent='parent: "[[Freight]]"', extra="", kind="type: history"):
        path = self.folder / name
        write(path, "---\n%s\n%s\n%screated: 2026-10-01\n---\n\n# Freight: history, 2026-Q3\n\n**1 September 2026.** An old entry.\n"
              % (kind, parent, extra))
        return path

    def parents(self):
        return [i for i in self.run_tool("list")[1]["items"] if (i.get("fix") or {}).get("op") == "history-parent"]

    def test_the_old_form_is_a_mechanical_finding_and_fix_rewrites_the_one_line_in_one_commit(self):
        old = self.history_file("Freight history 2026-Q3.md")
        mine = self.history_file("Freight history 2026-Q2.md")
        self.commit(self.work, "2026-10-01T10:00:00")
        found = self.parents()
        self.assertEqual(2, len(found))
        self.assertEqual({"mechanical"}, {i["kind"] for i in found})
        before = len(self.log(self.work))
        code, out = self.run_tool("fix", "--yes")
        self.assertEqual(0, code, out)
        self.assertEqual(before + 1, len(self.log(self.work)))                       # one commit for the repository
        for f in (old, mine):
            text = f.read_text(encoding="utf-8")
            self.assertIn('parent: "[[Acme Review/Threads/Freight/Freight|Freight]]"', text)
            self.assertNotIn('parent: "[[Freight]]"', text)
            self.assertIn("An old entry.", text)
        self.assertEqual([], self.parents())
        self.assertEqual(2, len([f for f in git(self.work, "show", "--name-only", "--format=", "HEAD").splitlines() if "history" in f]))

    def test_the_nightly_run_applies_it_too(self):
        self.history_file("Freight history 2026-Q3.md")
        self.commit(self.work, "2026-10-01T10:00:00")
        code, out = self.run_tool("nightly")
        self.assertEqual(0, code, out)
        self.assertIn("history-parent", {i["fix"]["op"] for i in out["fixed"]})

    def test_a_file_with_another_notes_parent_or_with_status_or_the_current_form_is_not_touched(self):
        other = self.history_file("Freight history 2026-Q1.md", parent='parent: "[[Pricing]]"')
        status = self.history_file("Freight history 2026-Q2.md", extra="status: active\n")
        current = self.history_file("Freight history 2026-Q3.md", parent='parent: "[[Acme Review/Threads/Freight/Freight|Freight]]"')
        notype = self.history_file("Freight history 2026-Q4.md", kind="type: note")
        named = self.history_file("Pricing history 2026-Q3.md")                       # a note's name that is not the file's own
        self.commit(self.work, "2026-10-01T10:00:00")
        was = {f: f.read_text(encoding="utf-8") for f in (other, status, current, notype, named)}
        self.assertEqual([], self.parents())
        self.run_tool("fix", "--yes")
        self.run_tool("nightly")
        for f, text in was.items():
            self.assertEqual(text, f.read_text(encoding="utf-8"), f.name)

    def test_a_file_changed_since_it_was_found_is_held_not_rewritten(self):
        f = self.history_file("Freight history 2026-Q3.md")
        self.commit(self.work, "2026-10-01T10:00:00")
        self.assertEqual(1, len(self.parents()))
        f.write_text(f.read_text(encoding="utf-8").replace("type: history\n", "type: history\nstatus: active\n"), encoding="utf-8")
        self.commit(self.work, "2026-10-02T10:00:00")
        self.assertEqual([], self.parents())


if __name__ == "__main__":
    unittest.main()
