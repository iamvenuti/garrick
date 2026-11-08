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

NAMES = ("Acme", "acme", "Birch", "birch", "Dana", "Whitlock", "Theo", "Marsh", "Northwind", "Harbour", "Notes.md")


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
        write(self.work / "Northwind" / "Threads" / "Pricing" / "Leak.md", "# N\n\nAsk Theo Marsh at Birch & Co.\n")
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
        self.assertEqual(("Work", "zone", "name", True), (rows[0]["zone"], rows[0]["repo"], rows[0]["kind"], rows[0]["walled"]))
        text = self.record.read_text(encoding="utf-8")
        for name in NAMES:
            self.assertNotIn(name, text)
        self.assertTrue(all(r["kind"] in lib.REFUSAL_KINDS for r in rows))

    def test_the_hook_route_records_it_too(self):
        write(self.work / "Northwind" / "Threads" / "Pricing" / "Leak.md", "# N\n\nAsk Theo Marsh.\n")
        git(self.work, "add", "-A")
        cwd = os.getcwd()
        os.chdir(self.work)
        try:
            code = check.main(["--root", str(self.root), "--staged", "--walls-only"])
        finally:
            os.chdir(cwd)
        self.assertEqual(1, code)
        self.assertEqual("name", self.rows()[0]["kind"])

    def test_the_kinds(self):
        for message, kind in (("repeats wording from a page", "wording"), ("writes the path x, a path that leads", "path"),
                              ("names X, or one of its people", "name"), ("links y, a file that names no party", "unlabelled"),
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
        self.assertEqual({"name": len(self.rows()) - 1}, got["kinds"])        # the old line is outside the 30 days
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
        self.assertIn("name", shown)
        self.assertNotIn("Theo", shown)


if __name__ == "__main__":
    unittest.main()
