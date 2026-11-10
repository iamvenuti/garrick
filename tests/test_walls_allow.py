"""Allow once: the ledger of wall findings the user let through (System/walls-allowed.json).

    python3 -m unittest test_walls_allow
"""

from __future__ import annotations
import sys
sys.dont_write_bytecode = True  # keep the repo free of __pycache__

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fixtures import GIT_ENV, HAVE_GIT, git  # noqa: E402  (puts System/tools on the path)

import garrick_lib as gl  # noqa: E402

BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
PATH = "Zones/Work/Harbour/Harbour.md"


class TTY(io.StringIO):
    def isatty(self):
        return True


class TestLedger(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def test_id_is_ten_hex_of_sha1_over_path_rule_token(self):
        fid = gl.allow_finding_id(PATH, "name", "Cedar")
        self.assertEqual(10, len(fid))
        int(fid, 16)
        self.assertEqual(fid, gl.allow_finding_id(PATH, "name", "Cedar"))
        for other in (gl.allow_finding_id(PATH + "x", "name", "Cedar"), gl.allow_finding_id(PATH, "link", "Cedar"),
                      gl.allow_finding_id(PATH, "name", "Maple")):
            self.assertNotEqual(fid, other)
        import hashlib
        self.assertEqual(hashlib.sha1(("%s\0name\0Cedar" % PATH).encode()).hexdigest()[:10], fid)

    def test_round_trip(self):
        fid = gl.allow_finding_id(PATH, "name", "Cedar")
        entry = gl.allow_add(self.root, PATH, fid, BLOB, "name", "terminal", today="2026-11-10")
        self.assertEqual({"path": PATH, "id": fid, "blob": BLOB, "rule": "name", "date": "2026-11-10",
                          "by": "terminal"}, entry)
        data = json.loads(gl.allow_ledger_path(self.root).read_text(encoding="utf-8"))
        self.assertEqual(1, data["version"])
        self.assertEqual([entry], data["allowed"])
        self.assertEqual([entry], gl.allow_read(self.root))
        self.assertIn((PATH, fid, BLOB), gl.allow_set(self.root))

    def test_the_ledger_names_no_token(self):
        gl.allow_add(self.root, PATH, gl.allow_finding_id(PATH, "name", "Cedar Holdings"), BLOB, "name", "page")
        self.assertNotIn("Cedar", gl.allow_ledger_path(self.root).read_text(encoding="utf-8"))

    def test_a_new_blob_renews_and_a_second_finding_is_kept(self):
        a, b = gl.allow_finding_id(PATH, "name", "Cedar"), gl.allow_finding_id(PATH, "link", "Maple")
        gl.allow_add(self.root, PATH, a, BLOB, "name", "terminal")
        gl.allow_add(self.root, PATH, b, BLOB, "link", "terminal")
        gl.allow_add(self.root, PATH, a, "f" * 40, "name", "page")
        rows = {(e["id"], e["blob"], e["by"]) for e in gl.allow_read(self.root)}
        self.assertEqual({(a, "f" * 40, "page"), (b, BLOB, "terminal")}, rows)

    def test_remove(self):
        a, b = gl.allow_finding_id(PATH, "name", "Cedar"), gl.allow_finding_id(PATH, "link", "Maple")
        gl.allow_add(self.root, PATH, a, BLOB, "name", "terminal")
        gl.allow_add(self.root, PATH, b, BLOB, "link", "terminal")
        self.assertEqual(1, gl.allow_remove(self.root, PATH, a))
        self.assertEqual([b], [e["id"] for e in gl.allow_read(self.root)])
        self.assertEqual(0, gl.allow_remove(self.root, PATH, a))

    def test_missing_or_unreadable_ledger_holds_nothing(self):
        self.assertEqual([], gl.allow_read(self.root))
        path = gl.allow_ledger_path(self.root)
        path.parent.mkdir(parents=True)
        for text in ("{not json", "[]", '{"version": 2, "allowed": []}', '{"version": 1, "allowed": 3}', ""):
            path.write_text(text, encoding="utf-8")
            self.assertEqual([], gl.allow_read(self.root), text)
        path.write_bytes(b"\xff\xfe\x00")
        self.assertEqual([], gl.allow_read(self.root))

    def test_a_malformed_entry_is_left_out_and_the_rest_read(self):
        good = {"path": PATH, "id": "0123456789", "blob": BLOB, "rule": "link", "date": "2026-11-10", "by": "page"}
        bad = [dict(good, by="assistant"), dict(good, rule="inbox"), {k: v for k, v in good.items() if k != "blob"},
               dict(good, id=5), "x"]
        path = gl.allow_ledger_path(self.root)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"version": 1, "allowed": bad + [good]}), encoding="utf-8")
        self.assertEqual([good], gl.allow_read(self.root))

    def test_a_kind_or_a_writer_outside_the_format_is_refused(self):
        with self.assertRaises(ValueError):
            gl.allow_add(self.root, PATH, "0123456789", BLOB, "unreadable", "terminal")
        with self.assertRaises(ValueError):
            gl.allow_add(self.root, PATH, "0123456789", BLOB, "name", "assistant")
        self.assertFalse(gl.allow_ledger_path(self.root).exists())

    def test_only_a_terminal_or_the_page_may_write(self):
        self.assertTrue(gl.allow_may_write("terminal", TTY()))
        self.assertFalse(gl.allow_may_write("terminal", io.StringIO()))      # an assistant's shell: stdin is no terminal
        self.assertFalse(gl.allow_may_write("terminal", object()))
        self.assertTrue(gl.allow_may_write("page"))
        self.assertFalse(gl.allow_may_write("assistant", TTY()))

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_commit_ledger_commits_only_the_ledger(self):
        git(self.root, "init", "-q")
        (self.root / "other.txt").write_text("staged\n")
        git(self.root, "add", "other.txt")
        gl.allow_add(self.root, PATH, "0123456789", BLOB, "name", "terminal")
        with mock.patch.dict(os.environ, GIT_ENV):
            said = gl.allow_commit(self.root, "Allow once")
        self.assertEqual("", said)
        self.assertEqual("System/walls-allowed.json\n", git(self.root, "show", "--name-only", "--format=", "HEAD"))
        self.assertIn("other.txt", git(self.root, "diff", "--cached", "--name-only"))


if __name__ == "__main__":
    unittest.main()
