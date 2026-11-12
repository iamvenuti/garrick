"""The record of wall refusals (#437): one line per refused finding, by kind and zone, with no content.

    cd tests && python3 -m unittest test_refusals
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, commit_all, git, write  # noqa: E402
from walls_fixture import build  # noqa: E402

import check  # noqa: E402
import garrick_lib as lib  # noqa: E402

NAMES = ("Acme", "acme", "Birch", "birch", "Dana", "Whitlock", "Theo", "Marsh", "Northwind", "Harbour", "Notes.md", "Garden", "Plan", "Leak")


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class RefusalRecord(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build(self.root)
        self.work = self.root / "Zones" / "Work"
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        git(self.work, "init", "-q")
        commit_all(self.work, "start")
        self.record = self.root.joinpath(*lib.REFUSALS)

    def refuse(self):
        write(self.work / "Northwind" / "Threads" / "Pricing" / "Leak.md", "# N\n\nSee [[Zones/Personal/Garden/Threads/Beds/Plan]].\n")
        git(self.work, "add", "-A")
        found = [f for f in check.run_checks(self.root, staged=self.work) if f.severity == "error"]
        lib.record_refusals(self.root, self.work, [f.message for f in found])
        return found

    def rows(self):
        return [json.loads(line) for line in self.record.read_text(encoding="utf-8").splitlines()]

    def test_a_refusal_leaves_one_line_per_finding_with_no_content(self):
        found = self.refuse()
        rows = self.rows()
        self.assertEqual(len(found), len(rows))
        self.assertEqual({"at", "zone", "repo", "kind", "walled"}, set(rows[0]))
        self.assertEqual(("Work", "zone", "link", True), (rows[0]["zone"], rows[0]["repo"], rows[0]["kind"], rows[0]["walled"]))
        text = self.record.read_text(encoding="utf-8")
        for name in NAMES:
            self.assertNotIn(name, text)
        self.assertTrue(all(r["kind"] in lib.REFUSAL_KINDS for r in rows))

    def test_the_hook_route_records_it_too(self):
        write(self.work / "Northwind" / "Threads" / "Pricing" / "Leak.md", "# N\n\nSee [[Zones/Personal/Garden/Threads/Beds/Plan]].\n")
        git(self.work, "add", "-A")
        cwd = os.getcwd()
        os.chdir(self.work)
        try:
            code = check.main(["--root", str(self.root), "--staged", "--walls-only"])
        finally:
            os.chdir(cwd)
        self.assertEqual(1, code)
        self.assertEqual("link", self.rows()[0]["kind"])

    def test_the_kinds(self):
        for message, kind in (("repeats wording from a page", "wording"), ("writes the path x, a path that leads", "path"),
                              ("names X, or one of its people", "name"), ("links y, a page that names no zone, so nothing says whose it is", "unlabelled"),
                              ("is a copy, whole, of a file of the Home zone", "copy"),
                              ("holds NUL bytes, so the walls cannot read it", "unreadable"), ("links z, a note of q", "link")):
            self.assertEqual(kind, lib.refusal_kind(message), message)

    def test_the_card_counts_thirty_days_and_the_overridden_commits(self):
        self.refuse()
        commit_all(self.work, "went through anyway")          # a commit within ten minutes of the refusal
        old = {"at": (datetime.datetime.now().astimezone() - datetime.timedelta(days=45)).isoformat(timespec="seconds"),
               "zone": "Work", "repo": "zone", "kind": "link", "walled": True}
        with self.record.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(old) + "\n")
        got = lib.refusal_counts(self.root)
        self.assertEqual({"link": 1}, got["kinds"])        # one refusal, whatever its lines; the old line is outside the 30 days
        self.assertEqual(1, got["refusals"])
        self.assertEqual(1, got["overridden"])
        self.assertEqual(1, len(got["days"]))

    def test_the_status_page_shows_them(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "status"))
        import status
        self.refuse()
        (self.root / "System" / "tools").mkdir(parents=True, exist_ok=True)
        (self.root / "System" / "tools" / "garrick_lib.py").write_text(Path(lib.__file__).read_text(encoding="utf-8"), encoding="utf-8")
        shown = status.refusals_block(self.root)
        self.assertIn("Wall refusals, 30 days", shown)
        self.assertIn("link", shown)
        self.assertNotIn("Plan", shown)

    def lines(self, at, n, zone="Work", repo="zone", kind="link"):
        self.record.parent.mkdir(parents=True, exist_ok=True)
        with self.record.open("a", encoding="utf-8") as fh:
            for _ in range(n):
                fh.write(json.dumps({"at": at, "zone": zone, "repo": repo, "kind": kind, "walled": True}) + "\n")

    def test_refusals_are_counted_not_lines_and_nested_and_outside_repositories_are_apart(self):
        now = datetime.datetime.now().astimezone()
        at = lambda h: (now - datetime.timedelta(hours=h)).isoformat(timespec="seconds")
        self.lines(at(5), 3, kind="wording")                     # one refusal, three lines
        self.lines(at(5), 2, kind="link")                        # the same refusal, another kind
        self.lines(at(9), 1, kind="name")                        # a kind this release no longer produces
        self.lines(at(7), 4000, repo="nested", kind="path")      # one refused commit of fixtures in a nested repository
        self.lines(at(7), 50, zone="", repo="nested", kind="copy")    # a repository outside the workspace
        self.lines(at(3), 1, zone="Garden", repo="wiki", kind="link")
        got = lib.refusal_counts(self.root, now=now)
        self.assertEqual(3, got["refusals"])
        self.assertEqual({"wording": 1, "link": 2, "name": 1}, got["kinds"])
        self.assertEqual(1, got["nested"])
        self.assertEqual({"path": 1}, got["nested_kinds"])
        self.assertEqual(["name"], got["older"])
        self.assertNotIn("copy", got["kinds"])
        self.assertNotIn("copy", got["nested_kinds"])

    def test_the_card_says_refusals_with_one_unit_and_marks_an_older_kind(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "status"))
        import status
        now = datetime.datetime.now().astimezone()
        self.lines((now - datetime.timedelta(hours=2)).isoformat(timespec="seconds"), 500, kind="name")
        self.lines((now - datetime.timedelta(hours=1)).isoformat(timespec="seconds"), 900, repo="nested", kind="path")
        (self.root / "System" / "tools").mkdir(parents=True, exist_ok=True)
        (self.root / "System" / "tools" / "garrick_lib.py").write_text(Path(lib.__file__).read_text(encoding="utf-8"), encoding="utf-8")
        shown = status.refusals_block(self.root)
        self.assertIn("1 refusal, of kinds name 1 (older release)", shown)
        self.assertIn("Overridden: 0 of 1", shown)
        self.assertIn("1 refusal in repositories nested in a zone, of kinds path 1", shown)
        self.assertNotIn("500", shown)
        self.assertNotIn("900", shown)


if __name__ == "__main__":
    unittest.main()
