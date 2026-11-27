"""template/System/tools/operations.py: the commit record (#716).

    python3 -m unittest discover -s tests

The interface a caller other than page_action.py uses: prepare, execute,
settle, outcome and sweep, against a real repository in a temporary folder.
A run is stopped for real, in a child process that ends itself, never by an
exception.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
OPS_PATH = REPO / "template" / "System" / "tools" / "operations.py"
spec = importlib.util.spec_from_file_location("garrick_operations_rec", OPS_PATH)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)

OP = "0123456789abcdef"
REQ = {"verb": "park", "zone": "Work", "project": "Acme Review", "thread": "Pricing"}
GIT_ENV = {"GIT_AUTHOR_NAME": "Jo", "GIT_AUTHOR_EMAIL": "jo@acme.example", "GIT_COMMITTER_NAME": "Jo",
           "GIT_COMMITTER_EMAIL": "jo@acme.example", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def run_git(repo, *args):
    env = dict(os.environ, **GIT_ENV)
    return subprocess.run(["git", "-C", str(repo)] + list(args), env=env, capture_output=True, text=True, check=True).stdout.strip()


def make_repo(root: Path, name="Work") -> Path:
    repo = root / name
    repo.mkdir()
    run_git(repo, "init", "-q")
    (repo / "Todo.md").write_text("- [ ] Book the room\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "start")
    return repo


def commit_with(repo, trailer_text, name="note.md", text="x\n", message="Park the thread"):
    (repo / name).write_text(text)
    run_git(repo, "add", name)
    args = ["commit", "-q", "-m", message]
    if trailer_text:
        args += ["-m", trailer_text]
    run_git(repo, *args)
    return run_git(repo, "rev-parse", "HEAD")


def count(repo):
    return int(run_git(repo, "rev-list", "--count", "HEAD"))


# A child process that prepares and executes, and ends itself at the named point.
CHILD = textwrap.dedent('''
    import importlib.util, os, subprocess, sys, json
    spec = importlib.util.spec_from_file_location("o", sys.argv[1]); ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ops)
    repo, point = sys.argv[2], sys.argv[3]
    req = json.loads(sys.argv[4])
    def git(*a):
        subprocess.run(["git", "-C", repo] + list(a), check=True, capture_output=True)
    def work(trailers):
        if point == "before":
            os._exit(9)
        open(os.path.join(repo, "note.md"), "w").write("x\\n")
        git("add", "note.md")
        git("commit", "-q", "-m", "Park the thread", "-m", trailers)
        if point == "after":
            os._exit(9)
        return "ok"
    if point == "unsettled":
        ops.settle = lambda *a, **k: os._exit(9)
    ops.prepare(repo, req["verb"], req, op=sys.argv[5])
    ops.execute(repo, sys.argv[5], work)
''')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._env = {k: os.environ.get(k) for k in GIT_ENV}
        os.environ.update(GIT_ENV)
        self.repo = make_repo(self.root)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def stop_at(self, point, op=OP, req=REQ):
        env = dict(os.environ, **GIT_ENV)
        p = subprocess.run([sys.executable, "-I", "-c", CHILD, str(OPS_PATH), str(self.repo), point, json.dumps(req), op],
                           env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 9, p.stderr)


class TestRecord(Base):
    def test_prepare_writes_the_record_in_the_repository_and_nowhere_else(self):
        got = ops.prepare(self.repo, "park", REQ, op=OP, via="remote")
        self.assertTrue(got["recorded"] and got["run"])
        self.assertEqual((got["state"], got["result"]), ("prepared", None))
        path = self.repo / ".git" / "garrick-ops" / (OP + ".json")
        rec = json.loads(path.read_text())
        for key in ("op", "verb", "zone", "payload", "head", "state", "prepared", "via", "seal"):
            self.assertIn(key, rec)
        self.assertEqual((rec["verb"], rec["zone"], rec["via"]), ("park", "Work", "remote"))
        self.assertEqual(rec["head"], run_git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(run_git(self.repo, "status", "--porcelain"), "")

    def test_the_record_holds_no_words_of_the_request(self):
        req = {"verb": "note-add", "zone": "Work", "project": "Acme Review", "thread": "Pricing", "text": "Dana hinted the floor could move"}
        ops.prepare(self.repo, "note-add", req, op=OP)
        text = (self.repo / ".git" / "garrick-ops" / (OP + ".json")).read_text()
        for word in ("Dana", "floor", "Acme Review", "Pricing"):
            self.assertNotIn(word, text)

    def test_execute_settles_done_and_the_commit_carries_the_trailers(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        seen = []
        done, receipt = ops.execute(self.repo, OP, lambda tr: seen.append(tr) or commit_with(self.repo, tr))
        self.assertEqual((receipt["state"], receipt["result"]), ("settled", "done"))
        self.assertEqual(receipt["commit"], done)
        self.assertFalse(receipt["new"])
        self.assertIn("Garrick-Op: " + OP, seen[0])
        self.assertIn("Garrick-Payload: " + ops.payload_hash("park", REQ), seen[0])
        self.assertTrue(receipt["say"].startswith("This was done already"))

    def test_a_retry_with_the_same_id_returns_the_first_receipt_and_makes_no_second_commit(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        ops.execute(self.repo, OP, lambda tr: commit_with(self.repo, tr))
        before = count(self.repo)
        again = ops.prepare(self.repo, "park", REQ, op=OP)
        self.assertFalse(again["run"])
        self.assertEqual(again["result"], "done")
        called = []
        _, receipt = ops.execute(self.repo, OP, lambda tr: called.append(1))
        self.assertEqual(called, [])
        self.assertEqual(receipt["result"], "done")
        self.assertEqual(count(self.repo), before)

    def test_the_same_id_with_another_request_is_refused(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        with self.assertRaises(ops.BadOp):
            ops.prepare(self.repo, "park", dict(REQ, thread="Other"), op=OP)
        with self.assertRaises(ops.BadOp):
            ops.prepare(self.repo, "wake", dict(REQ, verb="wake"), op=OP)

    def test_a_forged_record_runs_nothing(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        path = self.repo / ".git" / "garrick-ops" / (OP + ".json")
        rec = json.loads(path.read_text())
        forged = dict(rec, payload=ops.payload_hash("park", dict(REQ, thread="Other")))      # the seal no longer fits
        path.write_text(json.dumps(forged))
        called = []
        with self.assertRaises(ops.BadOp):
            ops.prepare(self.repo, "park", dict(REQ, thread="Other"), op=OP)
        with self.assertRaises(ops.BadOp):
            ops.execute(self.repo, OP, lambda tr: called.append(1))
        with self.assertRaises(ops.BadOp):
            ops.outcome(self.repo, OP)
        self.assertEqual(called, [])
        path.write_text("{not json")
        with self.assertRaises(ops.BadOp):
            ops.prepare(self.repo, "park", REQ, op=OP)

    def test_a_forged_settled_record_does_not_stand_in_for_a_commit(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        ops.execute(self.repo, OP, lambda tr: commit_with(self.repo, tr))
        run_git(self.repo, "reset", "-q", "--hard", "HEAD~1")        # the commit is gone from the history
        again = ops.prepare(self.repo, "park", REQ, op=OP)
        self.assertFalse(again["run"])
        self.assertEqual(again["result"], "unsure")

    def test_a_not_done_operation_may_run_again_under_the_same_id(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        with self.assertRaises(RuntimeError):
            ops.execute(self.repo, OP, lambda tr: (_ for _ in ()).throw(RuntimeError("refused")))
        rec = ops.outcome(self.repo, OP)
        self.assertEqual(rec["result"], "not-done")
        again = ops.prepare(self.repo, "park", REQ, op=OP)
        self.assertTrue(again["run"])
        ops.execute(self.repo, OP, lambda tr: commit_with(self.repo, tr))
        self.assertEqual(count(self.repo), 2)

    def test_a_folder_that_is_not_a_repository_is_not_recorded(self):
        plain = self.root / "plain"
        plain.mkdir()
        got = ops.prepare(plain, "park", REQ, op=OP)
        self.assertFalse(got["recorded"])
        self.assertTrue(got["run"])
        inside = self.repo / "sub"
        inside.mkdir()
        self.assertFalse(ops.prepare(inside, "park", REQ, op=OP)["recorded"])

    def test_a_verb_that_makes_no_commit_has_no_record(self):
        with self.assertRaises(ops.BadOp):
            ops.prepare(self.repo, "operations", {"verb": "operations"}, op=OP)

    def test_every_committing_verb_can_be_prepared_and_none_other(self):
        for verb, spec_ in ops.DECLARED.items():
            req = {"verb": verb, "zone": "Work"}
            if spec_.commits:
                got = ops.prepare(self.repo, verb, req, op=ops.mint_op())
                self.assertTrue(got["recorded"], verb)
            else:
                with self.assertRaises(ops.BadOp, msg=verb):
                    ops.prepare(self.repo, verb, req, op=ops.mint_op())

    def test_the_payload_is_the_request_and_nothing_else(self):
        a = ops.payload_hash("todo-add", {"zone": "Work", "text": "Book the room"})
        self.assertEqual(a, ops.payload_hash("todo-add", {"zone": "Work", "text": "Book the room", "target": "", "date": None, "op": OP, "confirm": "x"}))
        self.assertNotEqual(a, ops.payload_hash("todo-add", {"zone": "Work", "text": "Book the large room"}))
        self.assertEqual(ops.payload_hash("todo-done", {"zone": "Work", "file": "Todo.md", "keys": ["b", "a"]}),
                         ops.payload_hash("todo-done", {"zone": "Work", "file": "Todo.md", "keys": ["a", "b"]}))

    def test_no_shipped_code_can_be_told_to_stop_itself(self):
        for src in (OPS_PATH, REPO / "extras" / "status" / "page_action.py"):
            self.assertNotIn("os._exit", src.read_text(encoding="utf-8"), src.name)


class TestCrash(Base):
    """The run is stopped for real at each point. The next run says what became of it, once, and never commits twice."""

    def test_stopped_before_the_commit_it_is_not_done(self):
        self.stop_at("before")
        self.assertEqual(count(self.repo), 1)
        first = ops.outcome(self.repo, OP)
        self.assertEqual((first["result"], first["new"]), ("not-done", True))
        self.assertEqual(ops.outcome(self.repo, OP)["new"], False)
        self.assertEqual(ops.sweep(self.repo), [])
        self.assertEqual(count(self.repo), 1)

    def test_stopped_after_the_commit_it_is_done_with_that_commit(self):
        self.stop_at("after")
        self.assertEqual(count(self.repo), 2)
        first = ops.outcome(self.repo, OP)
        self.assertEqual((first["result"], first["new"]), ("done", True))
        self.assertEqual(first["commit"], run_git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(ops.outcome(self.repo, OP)["new"], False)

    def test_stopped_after_the_commit_but_before_it_was_settled_it_is_done(self):
        self.stop_at("unsettled")
        rec = json.loads((self.repo / ".git" / "garrick-ops" / (OP + ".json")).read_text())
        self.assertEqual(rec["state"], "running")
        got = ops.sweep(self.repo)
        self.assertEqual([r["result"] for r in got], ["done"])
        self.assertEqual(ops.sweep(self.repo), [])
        self.assertEqual(count(self.repo), 2)

    def test_a_retry_after_each_stop_never_makes_a_second_commit(self):
        for point, op in (("before", "aaaaaaaa11111111"), ("after", "bbbbbbbb22222222"), ("unsettled", "cccccccc33333333")):
            self.stop_at(point, op=op)
            ops.outcome(self.repo, op)
            got = ops.prepare(self.repo, "park", REQ, op=op)
            if got["run"]:
                ops.execute(self.repo, op, lambda tr: commit_with(self.repo, tr, name=op + ".md"))
            carrying = run_git(self.repo, "log", "--format=%B").count("Garrick-Op: " + op)
            self.assertEqual(carrying, 1, point)

    def test_a_commit_with_the_id_and_another_payload_is_unsure_and_runs_nothing(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        d = self.repo / ".git" / "garrick-ops"
        rec = json.loads((d / (OP + ".json")).read_text())
        rec["state"] = "running"
        (d / (OP + ".json")).write_text(json.dumps(rec))     # the seal covers payload and head, not the state
        sha = commit_with(self.repo, ops.trailers(OP, ops.payload_hash("park", dict(REQ, thread="Other"))))
        got = ops.outcome(self.repo, OP)
        self.assertEqual(got["result"], "unsure")
        self.assertEqual(got["found"], [sha])
        self.assertIn(sha[:7], got["say"])
        self.assertFalse(ops.prepare(self.repo, "park", REQ, op=OP)["run"])

    def test_head_moved_by_something_else_is_unsure_and_names_the_commit(self):
        self.stop_at("before")
        sha = commit_with(self.repo, "", name="other.md")
        got = ops.outcome(self.repo, OP)
        self.assertEqual((got["result"], got["found"]), ("unsure", [sha]))
        self.assertIn(sha[:7], got["say"])

    def test_a_commit_that_may_still_be_running_is_unsure_not_not_done(self):
        self.stop_at("before")
        (self.repo / ".git" / "index.lock").write_text("")      # git's own lock, held while a commit runs
        self.assertEqual(ops.outcome(self.repo, OP, mark=False)["result"], "unsure")

    def test_two_commits_with_one_id_are_unsure(self):
        self.stop_at("after")
        commit_with(self.repo, ops.trailers(OP, ops.payload_hash("park", REQ)), name="two.md")
        got = ops.outcome(self.repo, OP)
        self.assertEqual(got["result"], "unsure")
        self.assertEqual(len(got["found"]), 2)

    def test_a_repository_that_cannot_be_read_is_unsure(self):
        self.stop_at("after")
        real = ops._git
        ops._git = lambda *a, **k: (128, "")
        try:
            got = ops._decide(self.repo, json.loads((self.repo / ".git" / "garrick-ops" / (OP + ".json")).read_text()), None)
        finally:
            ops._git = real
        self.assertEqual(got["result"], "unsure")

    def test_the_sentences_never_read_as_a_success_unless_done(self):
        for result in ("not-done", "unsure"):
            rec = {"op": OP, "state": "settled", "result": result, "found": ["a" * 40], "commit": ""}
            self.assertFalse(ops.affirms(ops._receipt(rec)["say"]), result)
        self.assertFalse(ops.affirms(ops._receipt({"op": OP, "state": "settled", "result": "unsure", "found": []})["say"]))


class TestFixRound(Base):
    """The fix round of 0.84.0: each test failed before its fix."""

    def record_path(self, op=OP):
        return self.repo / ".git" / "garrick-ops" / (op + ".json")

    def edit(self, op=OP, **change):
        rec = json.loads(self.record_path(op).read_text())
        rec.update(change)               # the seal covers op, verb, zone, payload and head only
        self.record_path(op).write_text(json.dumps(rec))

    def test_c2_a_second_execute_and_a_reader_leave_a_live_worker_alone(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        inside, release, results = threading.Event(), threading.Event(), {}

        def work(tr):
            inside.set()
            release.wait(20)
            return commit_with(self.repo, tr)
        first = threading.Thread(target=lambda: results.update(first=ops.execute(self.repo, OP, work)))
        first.start()
        self.assertTrue(inside.wait(20))
        called = []
        second = ops.execute(self.repo, OP, lambda tr: called.append(1))
        self.assertEqual((second[0], second[1]["state"]), (None, "running"))
        self.assertTrue((self.repo / ".git" / "garrick-ops" / (OP + ".run")).exists())
        self.assertEqual(ops.outcome(self.repo, OP)["state"], "running")
        self.assertEqual(ops.sweep(self.repo), [])
        self.assertFalse(ops.prepare(self.repo, "park", REQ, op=OP)["run"])
        release.set()
        first.join(20)
        self.assertEqual(called, [])
        self.assertEqual(results["first"][1]["result"], "done")
        self.assertEqual(count(self.repo), 2)

    def test_s1_an_edited_record_does_not_run_a_done_operation_again(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        ops.execute(self.repo, OP, lambda tr: commit_with(self.repo, tr))
        for change in ({"state": "prepared"}, {"result": "not-done"}, {"state": "running", "result": None}, {"state": "prepared", "result": None, "commit": "", "found": []}):
            self.edit(**change)
            got = ops.prepare(self.repo, "park", REQ, op=OP)
            self.assertFalse(got["run"], change)
            called = []
            ops.execute(self.repo, OP, lambda tr: called.append(1))
            self.assertEqual(called, [], change)
        self.assertEqual(count(self.repo), 2)

    def test_s1_a_record_deleted_does_not_run_a_done_operation_again(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        ops.execute(self.repo, OP, lambda tr: commit_with(self.repo, tr))
        self.record_path().unlink()
        self.assertFalse(ops.prepare(self.repo, "park", REQ, op=OP)["run"])
        self.assertEqual(count(self.repo), 2)

    def test_s1_a_prepared_operation_whose_commit_is_already_there_does_not_run(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        sha = commit_with(self.repo, ops.trailers(OP, ops.payload_hash("park", REQ)))     # made by another process
        called = []
        _, receipt = ops.execute(self.repo, OP, lambda tr: called.append(1))
        self.assertEqual((called, receipt["result"], receipt["commit"]), ([], "done", sha))

    def test_s1_two_commits_with_the_op_are_unsure_and_never_run(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        for n in range(2):
            commit_with(self.repo, ops.trailers(OP, ops.payload_hash("park", REQ)), name="n%d.md" % n)
        got = ops.prepare(self.repo, "park", REQ, op=OP)
        self.assertEqual((got["run"], got["result"], len(got["found"])), (False, "unsure", 2))

    def test_s5_separators_in_a_message_do_not_forge_a_commit(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        message = "a\x1eNOT-A-COMMIT\x1fb\n\n" + ops.trailers(OP, ops.payload_hash("park", REQ))
        (self.repo / "x.md").write_text("x")
        run_git(self.repo, "add", "x.md")
        run_git(self.repo, "commit", "-q", "-m", message)
        sha = run_git(self.repo, "rev-parse", "HEAD")
        found, readable = ops._carrying(self.repo, OP)
        self.assertEqual([c for c, _ in found], [sha])         # a hand-made commit with the two lines is taken as the action's own
        self.assertTrue(all(ops.SHA_RE.fullmatch(c) for c, _ in found))

    def test_s3_a_busy_record_is_refused_not_gone_past(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        import fcntl
        fd = os.open(str(self.repo / ".git" / "garrick-ops" / ".lock"), os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        old, ops.LOCK_WAIT = ops.LOCK_WAIT, 0.2
        try:
            for call in (lambda: ops.prepare(self.repo, "park", REQ, op=OP), lambda: ops.settle(self.repo, OP),
                         lambda: ops.outcome(self.repo, OP), lambda: ops.execute(self.repo, OP, lambda tr: None)):
                with self.assertRaises(ops.BadOp):
                    call()
            self.assertEqual(ops.sweep(self.repo), [])
        finally:
            ops.LOCK_WAIT = old
            os.close(fd)

    def test_s4_a_linked_record_folder_or_file_is_refused(self):
        other = make_repo(self.root, "Personal")
        ops.prepare(other, "park", REQ, op="aaaaaaaa11111111")
        (self.repo / ".git" / "garrick-ops").symlink_to(other / ".git" / "garrick-ops")
        self.assertFalse(ops.prepare(self.repo, "park", REQ, op=OP)["recorded"])
        with self.assertRaises(ops.BadOp):
            ops.outcome(self.repo, "aaaaaaaa11111111")
        (self.repo / ".git" / "garrick-ops").unlink()
        ops.prepare(self.repo, "park", REQ, op=OP)
        real = self.record_path()
        moved = self.root / "elsewhere.json"
        real.rename(moved)
        real.symlink_to(moved)
        with self.assertRaises(ops.BadOp):
            ops.outcome(self.repo, OP)

    def test_s4_records_are_private_and_leave_no_temporary_file(self):
        ops.prepare(self.repo, "park", REQ, op=OP)
        self.assertEqual(oct(self.record_path().stat().st_mode & 0o777), "0o600")
        self.assertEqual(list((self.repo / ".git" / "garrick-ops").glob("*.tmp")), [])

    def test_s4_prune_takes_the_op_from_the_file_name(self):
        victim = self.root / "victim.run"
        victim.write_text("x")
        d = self.repo / ".git" / "garrick-ops"
        ops.prepare(self.repo, "park", REQ, op=OP)
        rec = dict(json.loads(self.record_path().read_text()), op="../../../victim", state="settled", reported=True, settled=1)
        (d / "deadbeef00000000.json").write_text(json.dumps(rec))
        ops._prune(d, time_now())
        self.assertTrue(victim.exists())

    def test_w4_a_verb_of_the_workspace_keeps_no_zone(self):
        got = ops.prepare(self.repo, "walls-allow", {"verb": "walls-allow", "zone": "Secret Zone", "path": "a", "id": "b"}, op=OP)
        self.assertEqual(got["zone"], "")
        self.assertEqual(json.loads(self.record_path().read_text())["zone"], "")

    def test_c3_a_commit_without_trailers_is_still_done_on_a_retry(self):
        ops.prepare(self.repo, "rename", dict(REQ, verb="rename", to="Cost"), op=OP)

        def work(tr):
            (self.repo / "r.md").write_text("x")
            run_git(self.repo, "add", "r.md")
            run_git(self.repo, "commit", "-q", "-m", "renamed")      # a tool that does not carry the trailers
            return "ok"
        _, receipt = ops.execute(self.repo, OP, work)
        self.assertEqual(receipt["result"], "done")
        again = ops.prepare(self.repo, "rename", dict(REQ, verb="rename", to="Cost"), op=OP)
        self.assertEqual((again["run"], again["result"]), (False, "done"))
        self.assertEqual(count(self.repo), 2)


def time_now():
    import time
    return time.time()


class TestAnotherRepository(Base):
    def test_a_record_never_names_another_zone(self):
        other = make_repo(self.root, "Personal")
        ops.prepare(self.repo, "park", REQ, op=OP)
        self.assertFalse((other / ".git" / "garrick-ops").exists())
        self.assertEqual(ops.sweep(other), [])
        with self.assertRaises(ops.BadOp):
            ops.outcome(other, OP)


if __name__ == "__main__":
    unittest.main()
