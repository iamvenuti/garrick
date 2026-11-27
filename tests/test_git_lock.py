"""#722: a tick that meets a git lock waits for it, and says so in its own words when the lock stays.

    python3 -m unittest tests.test_git_lock

Every case works in a fixture workspace under a temporary folder. The wait is shortened where a test needs the lock to
outlast it; the one-second case runs at the shipped numbers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import test_page_action as tpa  # noqa: E402
from test_page_action import ActionCase, git, write  # noqa: E402

pa = tpa.pa
REPO = tpa.REPO
LOCK = "Not saved: another program was using this zone's history. Try again in a moment."


class LockCase(ActionCase):
    def setUp(self):
        super().setUp()
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n" + "".join(
            "- [ ] Acme Corp: Invoice %d\n" % i for i in range(1, 6)) + "\n## Done\n")
        git(self.work, "commit", "-qam", "five lines")
        self.lock = self.work / ".git" / "index.lock"
        self.ops = pa.ops_lib(self.root)

    def tick(self, n):
        key = self.key("Invoice %d" % n)
        return pa.perform(self.root, {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": key}, self.ops, via="page")

    def head(self):
        return git(self.work, "rev-parse", "HEAD").strip()

    def tearDown(self):
        try:
            self.lock.unlink()
        except OSError:
            pass
        super().tearDown()


class TestTheWait(LockCase):
    def test_five_ticks_in_a_row_all_save(self):
        before = int(git(self.work, "rev-list", "--count", "HEAD"))
        for n in range(1, 6):
            out, _, _ = self.tick(n)
            self.assertTrue(out["ok"], out)
        self.assertEqual(before + 5, int(git(self.work, "rev-list", "--count", "HEAD")))
        self.assertEqual(5, (self.work / "Todo.md").read_text().count("- [x] "))

    def test_two_ticks_sent_at_the_same_time_both_commit(self):
        script = self.root / "tick.py"
        script.write_text(
            "import importlib.util, sys\nfrom pathlib import Path\n"
            "spec = importlib.util.spec_from_file_location('pa', %r)\npa = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(pa)\nroot = Path(sys.argv[1])\nops = pa.ops_lib(root)\n"
            "tl = pa.todo_lines()\nkey = next(t['key'] for t in tl.tasks(sys.argv[2]) if sys.argv[3] in t['text'])\n"
            "out, _, _ = pa.perform(root, {'verb': 'todo-done', 'zone': 'Work', 'file': 'Todo.md', 'key': key}, ops, via='page')\n"
            "sys.exit(0 if out['ok'] else 1)\n" % str(tpa.SCRIPT))
        before = int(git(self.work, "rev-list", "--count", "HEAD"))
        procs = [subprocess.Popen([sys.executable, str(script), str(self.root), str(self.work), "Invoice %d" % n],
                                  env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for n in (1, 2)]
        results = [(p.wait(), p.stderr.read()) for p in procs]
        for p in procs:
            p.stdout.close()
            p.stderr.close()
        self.assertEqual([0, 0], [r[0] for r in results], results)
        self.assertEqual(before + 2, int(git(self.work, "rev-list", "--count", "HEAD")))
        self.assertEqual(2, (self.work / "Todo.md").read_text().count("- [x] "))

    def test_a_lock_held_one_second_is_waited_out(self):
        self.lock.write_text("")
        threading.Timer(1.0, lambda: self.lock.unlink()).start()
        out, _, _ = self.tick(1)
        self.assertTrue(out["ok"], out)
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        self.assertIn("Invoice 1", git(self.work, "log", "-1", "--format=%s"))

    def test_a_retried_commit_is_one_commit_with_one_trailer(self):
        self.lock.write_text("")
        threading.Timer(0.7, lambda: self.lock.unlink()).start()
        before = int(git(self.work, "rev-list", "--count", "HEAD"))
        out, _, _ = self.tick(2)
        self.assertTrue(out["ok"], out)
        self.assertEqual(before + 1, int(git(self.work, "rev-list", "--count", "HEAD")))
        self.assertEqual(1, git(self.work, "log", "-1", "--format=%B").count("Garrick-Op: "))

    def test_only_the_lock_is_tried_again(self):
        calls = []
        real = pa.git_once

        def counting(zone, *args, **k):
            calls.append(args[0])
            return real(zone, *args, **k)
        pa.git_once = counting
        try:
            code, said = pa.git(self.work, "checkout", "no-such-branch")
        finally:
            pa.git_once = real
        self.assertNotEqual(0, code)
        self.assertEqual(["checkout"], calls)


class TestALockThatStays(LockCase):
    def setUp(self):
        super().setUp()
        self._numbers = (pa.LOCK_TRIES, pa.LOCK_PAUSE)
        pa.LOCK_TRIES, pa.LOCK_PAUSE = 2, 0.05
        self.lock.write_text("")

    def tearDown(self):
        pa.LOCK_TRIES, pa.LOCK_PAUSE = self._numbers
        super().tearDown()

    def test_it_fails_in_words_that_name_the_lock_and_writes_nothing(self):
        before, records = self.head(), (self.work / ".git" / "garrick-ops")
        todo = (self.work / "Todo.md").read_bytes()
        out, _, _ = self.tick(1)
        self.assertFalse(out["ok"])
        self.assertTrue(out["say"].startswith(LOCK), out["say"])
        self.assertNotIn("check", out["say"].lower())
        self.assertEqual("lock", pa.failure_code(out, {"verb": "todo-done"}))
        self.assertEqual(LOCK, pa.plain_failure("lock")["say"])
        self.assertEqual(before, self.head())
        self.assertEqual(todo, (self.work / "Todo.md").read_bytes())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        if records.is_dir():
            for f in records.glob("*.json"):
                self.assertNotEqual("running", json.loads(f.read_text()).get("state"), f.name)

    def test_a_lock_file_older_than_the_stale_age_is_named_as_possibly_stale(self):
        old = time.time() - pa.LOCK_STALE - 600
        os.utime(self.lock, (old, old))
        out, _, _ = self.tick(1)
        self.assertTrue(out["say"].startswith(LOCK))
        self.assertIn("index.lock", out["say"])
        self.assertIn("may be stale", out["say"])
        self.assertNotIn("index.lock", pa.plain_failure("lock")["band"])

    def test_a_fresh_lock_file_is_not_called_stale(self):
        out, _, _ = self.tick(1)
        self.assertEqual(LOCK, out["say"])


class TestNoMessageBlamesACheck(unittest.TestCase):
    def test_what_a_lock_says_is_never_a_check(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("garrick_ops_lock", str(REPO / "template" / "System" / "tools" / "operations.py"))
        ops = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ops)
        req = {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "0" * 16}
        lock_whys = (LOCK, LOCK + " The lock file /x/.git/index.lock is 9 minutes old and may be stale.",
                     "not committed, so nothing changed: " + LOCK)
        for why in lock_whys:
            said = ops.say("refused", "todo-done", req, why=why)
            self.assertTrue(said.startswith("Not saved: another program"), said)
            self.assertNotIn("check", said.lower())
            self.assertEqual("lock", pa.failure_code({"say": said, "outcome": "refused"}, req))
        # The others keep their words: a wall, a stale line, a check's own refusal.
        self.assertEqual(ops.WALL_REFUSAL, ops.say("refused", "todo-done", req, why=ops.WALL_REFUSAL))
        self.assertEqual("Not done. That line has changed since the page was built; it rebuilds now, try again.",
                         ops.say("refused", "todo-done", req, why="that line has changed since the page was built; it rebuilds now, try again"))
        self.assertEqual("refused", pa.failure_code({"say": "Not done. Commit refused.", "outcome": "refused"}, req))
        self.assertEqual("Not done. A check refused it.", ops.say("refused", "todo-done", req))


if __name__ == "__main__":
    unittest.main()
