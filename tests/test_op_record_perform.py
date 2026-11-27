"""page_action.perform(): every verb that commits keeps a commit record (#716).

    python3 -m unittest discover -s tests

Each committing verb of operations.DECLARED goes through perform() with the
handler replaced by one that commits through page_action's own git(), so the
record, the trailers and the settling are the real ones. The crash cases stop
a child process for real, at the three points that matter.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
OPS_PATH = REPO / "template" / "System" / "tools" / "operations.py"
PA_PATH = REPO / "extras" / "status" / "page_action.py"
GIT_ENV = {"GIT_AUTHOR_NAME": "Jo", "GIT_AUTHOR_EMAIL": "jo@acme.example", "GIT_COMMITTER_NAME": "Jo",
           "GIT_COMMITTER_EMAIL": "jo@acme.example", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ops = load("garrick_operations_perform", OPS_PATH)
pa = load("garrick_page_action_perform", PA_PATH)


def git(repo, *args):
    env = dict(os.environ, **GIT_ENV)
    return subprocess.run(["git", "-C", str(repo)] + list(args), env=env, capture_output=True, text=True, check=True).stdout.strip()


def workspace(root: Path) -> Path:
    ws = root / "ws"
    (ws / "System").mkdir(parents=True)
    (ws / "System" / "rules.md").write_text("rules\n")
    (ws / ".gitignore").write_text("Zones/\n")
    git_init(ws)
    zone = ws / "Zones" / "Work"
    zone.mkdir(parents=True)
    git_init(zone)
    return ws


def git_init(repo: Path):
    git(repo, "init", "-q")
    (repo / "Todo.md").write_text("- [ ] Book the room\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "start")


def commits(repo) -> int:
    return int(git(repo, "rev-list", "--count", "HEAD"))


def committer(ws, zone="Work", scope="zone"):
    """A stand-in for act(): one commit, through page_action's own git(), in the repository the verb touches."""
    def fake(ws_, req, *a, **k):
        repo = ws_ / "Zones" / zone if scope == "zone" else ws_
        (repo / ("n-%s.md" % req["verb"])).write_text("x\n")
        pa.git(repo, "add", "-A")
        code, why = pa.git(repo, "commit", "-q", "-m", "Do it: %s" % req["verb"])
        if code != 0:
            raise RuntimeError(why)
        return "Done."
    return fake


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.env = {k: os.environ.get(k) for k in list(GIT_ENV) + ["GARRICK_JOBS_DIR", "HOME"]}
        os.environ.update(GIT_ENV)
        os.environ["GARRICK_JOBS_DIR"] = str(self.root / "jobs")
        os.environ["HOME"] = str(self.root / "home")
        self.ws = workspace(self.root)
        self.zone = self.ws / "Zones" / "Work"
        self.saved = (pa.act, pa.ask_for_page)
        pa.ask_for_page = lambda ws: False

    def tearDown(self):
        pa.act, pa.ask_for_page = self.saved
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()


class TestEveryCommittingVerb(Base):
    def test_each_verb_that_commits_is_recorded_before_and_settled_after(self):
        seen = []
        for verb, spec in sorted(ops.DECLARED.items()):
            if not spec.commits or verb in ("new-project-party",):
                continue
            scope = spec.scope
            repo = self.zone if scope == "zone" else self.ws
            pa.act = committer(self.ws, scope=scope)
            op = ops.mint_op()
            before = commits(repo)
            req = {"verb": verb, "zone": "Work", "op": op}
            out, _, _ = pa.perform(self.ws, req, ops, via="page")
            self.assertTrue(out["ok"], (verb, out))
            self.assertEqual(commits(repo), before + 1, verb)
            body = git(repo, "log", "-1", "--format=%B")
            self.assertIn("Garrick-Op: " + op, body, verb)
            self.assertIn("Garrick-Payload: " + ops.payload_hash(verb, req), body, verb)
            rec = json.loads((repo / ".git" / "garrick-ops" / (op + ".json")).read_text())
            self.assertEqual((rec["state"], rec["result"], rec["commit"]), ("settled", "done", git(repo, "rev-parse", "HEAD")), verb)
            seen.append(verb)
        self.assertEqual(sorted(seen), sorted(v for v, s in ops.DECLARED.items() if s.commits and v != "new-project-party"))

    def test_a_verb_that_does_not_commit_keeps_no_record(self):
        pa.act = lambda ws, req, *a, **k: "Done."
        out, _, _ = pa.perform(self.ws, {"verb": "chase", "zone": "Work", "file": "Todo.md", "key": "0123456789abcdef"}, ops, via="page")
        self.assertFalse((self.zone / ".git" / "garrick-ops").exists())

    def test_a_verb_that_is_refused_leaves_a_record_settled_as_not_done(self):
        def refuse(ws, req, *a, **k):
            raise pa.Refused("that line has changed")
        pa.act = refuse
        out, _, _ = pa.perform(self.ws, {"verb": "todo-add", "zone": "Work", "text": "Book the room", "op": "feedface12345678"}, ops, via="page")
        self.assertFalse(out["ok"])
        rec = json.loads((self.zone / ".git" / "garrick-ops" / "feedface12345678.json").read_text())
        self.assertEqual(rec["result"], "not-done")

    def test_a_retry_with_the_same_id_returns_the_first_receipt_and_makes_no_second_commit(self):
        pa.act = committer(self.ws)
        req = {"verb": "rename", "zone": "Work", "project": "Acme", "thread": "Pricing", "to": "Cost", "op": "abcabcabcabcabca"}
        first, _, _ = pa.perform(self.ws, dict(req), ops, via="session")
        n = commits(self.zone)
        again, _, _ = pa.perform(self.ws, dict(req), ops, via="session")
        self.assertTrue(first["ok"] and again["ok"])
        self.assertEqual(commits(self.zone), n)
        self.assertTrue(again.get("receipt"))
        self.assertEqual(again["commit"], git(self.zone, "rev-parse", "HEAD"))

    def test_the_same_id_with_another_request_is_refused(self):
        pa.act = committer(self.ws)
        pa.perform(self.ws, {"verb": "rename", "zone": "Work", "project": "Acme", "thread": "A", "to": "B", "op": "abcabcabcabcabca"}, ops, via="session")
        out, _, _ = pa.perform(self.ws, {"verb": "rename", "zone": "Work", "project": "Acme", "thread": "A", "to": "C", "op": "abcabcabcabcabca"}, ops, via="session")
        self.assertFalse(out["ok"])
        self.assertEqual(commits(self.zone), 2)

    def test_a_forged_record_runs_nothing(self):
        pa.act = committer(self.ws)
        req = {"verb": "rename", "zone": "Work", "project": "Acme", "thread": "A", "to": "B", "op": "abcabcabcabcabca"}
        ops.prepare(self.zone, "rename", req, op=req["op"])
        path = self.zone / ".git" / "garrick-ops" / (req["op"] + ".json")
        rec = json.loads(path.read_text())
        rec["payload"] = "0" * 64
        path.write_text(json.dumps(rec))
        out, _, _ = pa.perform(self.ws, dict(req), ops, via="session")
        self.assertFalse(out["ok"])
        self.assertEqual(commits(self.zone), 1)


class TestHalfUpdated(Base):
    def test_a_newer_page_action_with_an_older_operations_py_carries_on(self):
        class Old:                  # what 0.83.0's operations.py offers: no record
            OPS = ops.OPS
            DECLARED = ops.DECLARED
            BadOp = ops.BadOp
            start = staticmethod(ops.start)
        pa.act = committer(self.ws)
        out, _, _ = pa.perform(self.ws, {"verb": "rename", "zone": "Work", "project": "A", "thread": "B", "to": "C"}, Old, via="session")
        self.assertTrue(out["ok"])
        self.assertNotIn("Garrick-Op", git(self.zone, "log", "-1", "--format=%B"))
        self.assertFalse((self.zone / ".git" / "garrick-ops").exists())

    def test_an_older_page_action_with_a_newer_operations_py_is_not_disturbed(self):
        # The older page_action never calls prepare, execute or sweep, and operations.start() is unchanged.
        op = "abababababababab"
        run, joined = ops.start(self.root / "jobs", {"verb": "park", "zone": "Work", "project": "A", "thread": "B", "op": op}, workspace=str(self.ws))
        self.assertIsNone(joined)
        run.finish("saved", {"verb": "park", "zone": "Work"}, said="Parked.")
        run.close({"verb": "park", "zone": "Work"})
        self.assertEqual(ops.read(self.root / "jobs", workspace=str(self.ws))["ops"][0]["outcome"], "saved")

    def test_a_record_of_0_83_0_is_a_journal_row_and_still_joins(self):
        pa.act = lambda ws, req, *a, **k: "Parked."
        req = {"verb": "park", "zone": "Work", "project": "A", "thread": "B"}
        run, _ = ops.start(self.root / "jobs", dict(req, op="1111111111111111"), workspace=str(self.ws))
        out, _, _ = pa.perform(self.ws, dict(req, op="2222222222222222"), ops, via="page")
        self.assertEqual(out["state"], "running")        # joined to the journal's own, as before
        run.close(req)


CHILD = textwrap.dedent('''
    import importlib.util, os, subprocess, sys, json
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path); mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod); return mod
    ops = load("o", sys.argv[1]); pa = load("p", sys.argv[2])
    from pathlib import Path
    ws, point, op = Path(sys.argv[3]), sys.argv[4], sys.argv[5]
    pa.ask_for_page = lambda w: False
    def act(w, req, *a, **k):
        zone = w / "Zones" / "Work"
        if point == "before":
            os._exit(9)
        (zone / "n.md").write_text("x\\n")
        pa.git(zone, "add", "-A")
        pa.git(zone, "commit", "-q", "-m", "Park the thread")
        if point == "after":
            os._exit(9)
        return "Parked."
    pa.act = act
    if point == "unsettled":
        ops.settle = lambda *a, **k: os._exit(9)
    pa.perform(ws, {"verb": "park", "zone": "Work", "project": "A", "thread": "B", "op": op}, ops, via="page")
''')


class TestCrashThroughPerform(Base):
    OP = "c0ffee00c0ffee00"
    REQ = {"verb": "park", "zone": "Work", "project": "A", "thread": "B"}

    def stop_at(self, point):
        p = subprocess.run([sys.executable, "-I", "-c", CHILD, str(OPS_PATH), str(PA_PATH), str(self.ws), point, self.OP],
                           env=dict(os.environ), capture_output=True, text=True)
        self.assertEqual(p.returncode, 9, p.stderr)

    def next_run(self):
        """The page's own `operations` request settles what a worker left, and says it once."""
        first = pa.sweep_receipts(self.ws, ops)
        return first, pa.sweep_receipts(self.ws, ops)

    def retry(self):
        pa.act = committer(self.ws)
        out, _, _ = pa.perform(self.ws, dict(self.REQ, op=self.OP), ops, via="page")
        return out

    def test_stopped_before_the_commit_the_next_run_says_not_done_once(self):
        self.stop_at("before")
        first, second = self.next_run()
        self.assertEqual([r["result"] for r in first], ["not-done"])
        self.assertEqual(second, [])
        self.assertEqual(commits(self.zone), 1)
        self.assertTrue(self.retry()["ok"])
        self.assertEqual(commits(self.zone), 2)

    def test_stopped_after_the_commit_the_next_run_says_done_once_and_a_retry_adds_nothing(self):
        self.stop_at("after")
        first, second = self.next_run()
        self.assertEqual([r["result"] for r in first], ["done"])
        self.assertEqual(first[0]["commit"], git(self.zone, "rev-parse", "HEAD"))
        self.assertEqual(second, [])
        self.assertTrue(self.retry()["ok"])
        self.assertEqual(commits(self.zone), 2)

    def test_stopped_after_the_commit_but_before_it_was_settled_the_next_run_says_done(self):
        self.stop_at("unsettled")
        first, second = self.next_run()
        self.assertEqual([r["result"] for r in first], ["done"])
        self.assertEqual(second, [])
        self.assertEqual(commits(self.zone), 2)
        self.assertTrue(self.retry()["ok"])
        self.assertEqual(commits(self.zone), 2)

    def test_the_status_page_record_is_corrected_to_what_git_says(self):
        self.stop_at("after")
        pa.sweep_receipts(self.ws, ops)
        self.assertEqual([o["outcome"] for o in ops.read(self.root / "jobs", workspace=str(self.ws))["ops"]], ["saved"])

    def test_the_operations_request_carries_what_it_settled(self):
        self.stop_at("after")
        pa.act = None
        out = subprocess.run([sys.executable, "-I", str(PA_PATH), "--workspace", str(self.ws)], input=json.dumps({"verb": "operations"}),
                             env=dict(os.environ), capture_output=True, text=True)
        said = json.loads(out.stdout)
        self.assertEqual([r["result"] for r in said["settled"]], ["done"])
        self.assertIn("It did go through", said["settled"][0]["say"])


if __name__ == "__main__":
    unittest.main()
