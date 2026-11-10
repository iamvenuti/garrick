"""Allow once: the ledger of wall findings the user let through (System/walls-allowed.json).

    python3 -m unittest test_walls_allow
"""

from __future__ import annotations
import sys
sys.dont_write_bytecode = True  # keep the repo free of __pycache__

import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fixtures import GIT_ENV, HAVE_GIT, git  # noqa: E402  (puts System/tools on the path)

import check  # noqa: E402
import garrick_lib as gl  # noqa: E402
from test_walls_deterministic import WallCase, _copy_tools, _real_repo, _run  # noqa: E402
from fixtures import TOOLS, write  # noqa: E402
from test_page_action import pa  # noqa: E402

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


NAME_A = "Compare with what Dana Whitlock expects.\n"          # an Acme person named in a Birch note


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class AllowCase(WallCase):
    """A workspace with a real zone repository and the hook, and the helpers that stage, run it and allow."""

    def setUp(self):
        super().setUp()
        _copy_tools(self.root)
        self.zone = self.root / "Zones" / "Work"
        _real_repo(self.zone)
        self.rel = "Zones/Work/Birch Entry/Threads/Market Sizing/Notes.md"
        self.note = self.root / self.rel

    def stage(self, text):
        write(self.note, text)
        git(self.zone, "add", "-A")

    def hook(self, *extra):
        return _run([sys.executable, self.root / "System" / "tools" / "check.py", "--staged", "--walls-only", *extra], self.zone)

    def ids(self):
        got = check.run_checks(self.root, staged=self.zone, use_ledger=False)
        return {check.finding_rule(f): check.finding_id(f) for f in got if f.path == self.rel}

    def allow(self, fid=None, remove=False, tty=True):
        argv = ["allow", "--root", str(self.root)] + (["--remove"] if remove else []) + [self.rel] + ([fid] if fid else [])
        err, out = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", TTY() if tty else io.StringIO()), mock.patch("sys.stderr", err), mock.patch("sys.stdout", out):
            code = check.main(argv)
        return code, out.getvalue() + err.getvalue()

    def stage_hub(self):
        """The Birch hub staged under the other party: one file with several refusals."""
        self.rel = "Zones/Work/Birch Entry/Birch Entry.md"
        hub = self.root / self.rel
        hub.write_text(hub.read_text().replace("party: birch", "party: acme"))
        git(self.zone, "add", "-A")

    def findings(self):
        got = check.run_checks(self.root, staged=self.zone, use_ledger=False)
        return [f for f in got if f.path == self.rel and check.allowable(f)]


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestAllowOnce(AllowCase):
    """The hook with a ledger: a refused commit, an allowance, the commit through, an edit, refused again."""

    def test_allow_once_round_trip(self):
        self.stage(NAME_A)
        self.assertEqual(1, self.hook().returncode)
        fid = self.ids()["name"]
        code, said = self.allow(fid)
        self.assertEqual(0, code, said)
        entry = gl.allow_read(self.root)[0]
        self.assertEqual((self.rel, fid, "name", "terminal"), (entry["path"], entry["id"], entry["rule"], entry["by"]))
        blob = git(self.zone, "ls-files", "-s", "--", "Birch Entry/Threads/Market Sizing/Notes.md").split()[1]
        self.assertEqual(blob, entry["blob"])
        res = self.hook()                                         # the same staged file now passes, silently
        self.assertEqual((0, ""), (res.returncode, res.stderr), res.stderr)
        self.assertEqual(1, len([f for f in check.run_checks(self.root, staged=self.zone, use_ledger=False)
                                 if f.path == self.rel]))         # the ledger is what drops it, not the check

    def test_an_edited_file_loses_its_allowance(self):
        self.stage(NAME_A)
        self.allow(self.ids()["name"])
        self.assertEqual(0, self.hook().returncode)
        self.stage(NAME_A + "More about the same person, Dana Whitlock.\n")
        res = self.hook()
        self.assertEqual(1, res.returncode)
        self.assertIn("Commit refused", res.stderr)

    def test_a_finding_not_in_the_ledger_still_refuses(self):
        self.stage(NAME_A)
        self.assertEqual(1, self.hook().returncode)
        self.assertEqual([], gl.allow_read(self.root))

    def test_an_allowance_for_one_finding_does_not_cover_another_in_the_file(self):
        self.stage_hub()
        found = self.findings()
        self.assertGreaterEqual(len(found), 2)
        first, rest = found[0], found[1:]
        self.assertTrue(all(check.finding_id(f) != check.finding_id(first) for f in rest))
        self.assertEqual(0, self.allow(check.finding_id(first))[0])
        left = [f for f in check.run_checks(self.root, staged=self.zone) if f.path == self.rel]
        self.assertEqual(len(found) - 1, len(left))
        self.assertNotIn(check.finding_id(first), [check.finding_id(f) for f in left])
        self.assertEqual(1, self.hook().returncode)
        for f in rest:
            self.assertEqual(0, self.allow(check.finding_id(f))[0])
        self.assertEqual(0, self.hook().returncode)

    def test_the_short_report_is_a_line_for_each_file_and_one_command(self):
        self.stage_hub()
        res = self.hook()
        lines = res.stderr.strip().splitlines()[::-1]           # the command comes first, the refusal last
        self.assertEqual(2, len(lines), res.stderr)            # the file, then the command
        self.assertRegex(lines[0], r"^Commit refused: Zones/Work/Birch Entry/.* holds \d refusals \(.*\)\. .*commit again; --verbose lists each\.$")
        self.assertTrue(pa_line(lines[0]), lines[0])
        self.assertIn("name", lines[0])
        self.assertIn("python3 System/tools/check.py allow", lines[1])
        self.assertLess(len(res.stderr), len(self.hook("--verbose").stderr))
        full = self.hook("--verbose").stderr.strip().splitlines()
        self.assertGreater(len(full), 2)
        for line in full:
            self.assertTrue(line.startswith("Commit refused: Zones/Work/Birch Entry/"), line)
        ids = {check.finding_id(f) for f in self.findings()}
        self.assertTrue(ids and all(any("[id %s," % i in l for l in full) for i in ids))

    def test_no_terminal_writes_nothing(self):
        self.stage(NAME_A)
        code, said = self.allow(self.ids()["name"], tty=False)
        self.assertEqual(2, code)
        self.assertIn("nothing was written", said)
        self.assertFalse(gl.allow_ledger_path(self.root).exists())
        res = _run([sys.executable, self.root / "System" / "tools" / "check.py", "allow", "--root", self.root, self.rel,
                    self.ids()["name"]], self.zone)           # a subprocess has no terminal on stdin either
        self.assertEqual(2, res.returncode)
        self.assertFalse(gl.allow_ledger_path(self.root).exists())

    def test_remove_brings_the_refusal_back(self):
        self.stage(NAME_A)
        fid = self.ids()["name"]
        self.allow(fid)
        self.assertEqual(0, self.hook().returncode)
        self.assertEqual(0, self.allow(fid, remove=True)[0])
        self.assertEqual(1, self.hook().returncode)
        self.assertEqual(1, self.allow(fid, remove=True)[0])      # nothing left to take away

    def test_an_id_the_file_does_not_have_is_refused(self):
        self.stage(NAME_A)
        code, said = self.allow("0123456789")
        self.assertEqual(1, code)
        self.assertEqual([], gl.allow_read(self.root))

    def test_a_refusal_with_another_fix_cannot_be_allowed(self):
        found = [check.Finding(check.ERROR, "walls", self.rel, "cannot be read, so the walls cannot check it"),
                 check.Finding(check.ERROR, "walls", self.rel, "has no party to check the walls against"),
                 check.Finding(check.ERROR, "inbox", self.rel, "is waiting in the inbox to be filed"),
                 check.Finding(check.WARNING, "walls", self.rel, "names Acme Corp")]
        self.assertEqual([False] * 4, [check.allowable(f) for f in found])

    def test_the_list_without_an_id(self):
        self.stage(NAME_A)
        code, said = self.allow()
        self.assertEqual(0, code)
        self.assertIn(self.ids()["name"], said)
        self.assertEqual([], gl.allow_read(self.root))

    def test_a_full_run_drops_the_allowed_finding_while_the_file_is_unchanged(self):
        self.stage(NAME_A)
        commit_all_ok = git(self.zone, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "unchecked")
        self.assertEqual("", commit_all_ok)
        before = [f for f in check.run_checks(self.root, walls_only=True) if f.path == self.rel]
        self.assertEqual(1, len(before), before)
        fid = check.finding_id(before[0])
        code, said = check.allow_page(self.root, self.rel, fid, "terminal")
        self.assertEqual(0, code, said)
        self.assertEqual([], [f for f in check.run_checks(self.root, walls_only=True) if f.path == self.rel])
        write(self.note, NAME_A + "Edited.\n")
        self.assertEqual(1, len([f for f in check.run_checks(self.root, walls_only=True) if f.path == self.rel]))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestPageVerbs(AllowCase):
    """The page's verbs walls-allow and walls-unallow: the same code, written by the page, and by nothing else."""

    def setUp(self):
        super().setUp()
        shutil.copy2(TOOLS / "operations.py", self.root / "System" / "tools" / "operations.py")
        self._jobs = tempfile.TemporaryDirectory()
        self.addCleanup(self._jobs.cleanup)
        patcher = mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": self._jobs.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, verb, fid, via="page"):
        out, _, why = pa.perform(self.root, {"verb": verb, "path": self.rel, "id": fid}, None, via)
        return out

    def test_a_click_allows_and_removes(self):
        self.stage(NAME_A)
        fid = self.ids()["name"]
        out = self.send("walls-allow", fid)
        self.assertTrue(out["ok"], out)
        self.assertEqual("page", gl.allow_read(self.root)[0]["by"])
        self.assertEqual(0, self.hook().returncode)
        out = self.send("walls-unallow", fid)
        self.assertTrue(out["ok"], out)
        self.assertEqual([], gl.allow_read(self.root))
        self.assertEqual(1, self.hook().returncode)

    def test_a_session_or_the_ask_box_cannot_allow(self):
        self.stage(NAME_A)
        fid = self.ids()["name"]
        for via in ("session", "ask"):
            out = self.send("walls-allow", fid, via)
            self.assertFalse(out["ok"], out)
            self.assertIn("nothing was written", out["say"])
        self.assertFalse(gl.allow_ledger_path(self.root).exists())

    def test_the_verbs_are_not_on_the_command_line(self):
        self.assertNotIn("walls-allow", pa.CLI_FIELDS)
        self.assertNotIn("walls-unallow", pa.CLI_FIELDS)

    def test_a_malformed_id_is_refused(self):
        self.stage(NAME_A)
        for bad in ("", "xyz", "3F9A1C2B7D", "0123456789ab"):
            self.assertFalse(self.send("walls-allow", bad)["ok"])
        self.assertFalse(gl.allow_ledger_path(self.root).exists())


def pa_line(line):
    import re
    return bool(re.match(r"^Commit refused: .+\. [^.\n]*\bcommit again\b", line))


if __name__ == "__main__":
    unittest.main()
