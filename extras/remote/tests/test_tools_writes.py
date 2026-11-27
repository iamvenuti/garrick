"""The ten write verbs (#700): note-add, the six Todo verbs, park, wake and checkpoint, as prepare, execute and status.

The effect is checked against the workspace's real page_action.py and scaffold.py, run as processes of their own as a
click runs them, in a fixture workspace with a real git repository. The one change to the fixture's copy of
page_action.py is the caller name `remote`, which `core-0820` adds to CALLERS in the core.

Run with the extra's runtime:  python -m unittest discover -s extras/remote/tests -p "test_tools_*.py"
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import threading
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import tools_support as support  # noqa: E402
from tools import common, manifest, run_op, writes  # noqa: E402

TH = "Zones/Work/Acme Review/Threads/Pricing/Pricing.md"


def git(zone, *args):
    return subprocess.run(["git", "-C", str(zone), *args], capture_output=True, text=True, check=True).stdout


class WritesCase(support.ToolsCase):
    def setUp(self):
        super().setUp()
        status = self.root / "System" / "status" / "page_action.py"
        text = status.read_text()
        if '"remote"' not in text.split("CALLERS = (", 1)[1].split(")", 1)[0]:
            status.write_text(text.replace('CALLERS = ("page", "ask", "session", "outbox")',
                                           'CALLERS = ("page", "ask", "session", "outbox", "remote")', 1))
        self.work = self.root / "Zones" / "Work"
        git(self.work, "add", "-A")
        subprocess.run(["git", "-C", str(self.work), "commit", "-q", "-m", "fixture"], capture_output=True)
        self.s = self.session(readable=("Work", "Knowledge", "docs"), writable=("Work",))
        self.w = writes.Writes(self.s)

    def commits(self):
        return len(git(self.work, "log", "--oneline").splitlines())

    def go(self, verb, zone="Work", wait=True, **fields):
        made = self.w.prepare(verb, zone, **fields)
        self.assertEqual("prepared", made.get("state"), made)
        out = self.w.execute(made["operation_id"])
        if wait:
            out = self.wait(made["operation_id"])
        return made["operation_id"], out

    def wait(self, op, w=None, timeout=90):
        w = w or self.w
        end = time.time() + timeout
        while time.time() < end:
            out = w.status(op)
            if out.get("state") not in ("running", "prepared"):
                return out
            time.sleep(0.2)
        self.fail("the operation did not finish: %s" % out)


class TestPrepare(WritesCase):
    def test_a_verb_that_is_not_served_gets_a_plain_reason_and_its_release(self):
        for verb in ("wrap", "delete", "note-read", "settings", "rename"):
            out = self.w.prepare(verb, "Work")
            self.assertEqual("not_available", out["error"], verb)
        self.assertIn("planned in the next release", self.w.prepare("wrap", "Work")["say"])

    def test_the_verbs_are_the_manifests_served_verbs(self):
        self.assertEqual(sorted(manifest.served_verbs(manifest.load())), sorted(writes.TAKES))
        self.assertEqual(sorted(writes.TAKES), sorted(writes.MUST))

    def test_a_zone_outside_the_write_reach_is_new_context_required_and_stores_nothing(self):
        for zone in ("Personal", "personal"):
            out = self.w.prepare("todo-add", zone, text="x")
            self.assertEqual(common.NEW_REACH, out["error"])
            self.assertIn("reach", out["say"])
        self.assertEqual([], list(self.w.store.all()))

    def test_a_read_only_grant_cannot_prepare_a_write(self):
        w = writes.Writes(self.session(readable=("Work",), writable=()))
        self.assertEqual(common.NEW_REACH, w.prepare("todo-add", "Work", text="x")["error"])

    def test_a_zone_that_does_not_exist(self):
        self.assertEqual({"text": common.NO_ZONE}, self.w.prepare("todo-add", "Nowhere", text="x"))

    def test_no_field_the_model_could_use_to_confirm_or_aim_is_taken(self):
        for field in ("confirm", "file", "key", "destination", "op", "via", "keys"):
            out = self.w.prepare("todo-done", "Work", line="x", **{field: "y"})
            self.assertEqual("not_prepared", out["error"], field)
            self.assertIn(field, out["say"])

    def test_each_verb_takes_only_its_own_fields_and_needs_its_own(self):
        self.assertIn("does not take", self.w.prepare("park", "Work", project="Acme Review", text="x")["say"])
        self.assertIn("needs", self.w.prepare("note-add", "Work", text="x")["say"])
        self.assertIn("YYYY-MM-DD", self.w.prepare("todo-add", "Work", text="x", date="soon")["say"])
        self.assertIn("not the name", self.w.prepare("park", "Work", project="../Personal")["say"])
        self.assertIn("not the name", self.w.prepare("note-add", "Work", project="Acme Review", thread="a/b", text="x")["say"])
        self.assertIn("project, or Project/Thread", self.w.prepare("todo-add", "Work", text="x", target="../x")["say"])

    def test_prepare_says_what_would_change_and_changes_nothing(self):
        before = self.commits()
        out = self.w.prepare("todo-add", "Work", text="Call Dana about pallets", target="Acme Review/Pricing")
        self.assertEqual("prepared", out["state"])
        self.assertIn("Call Dana about pallets", out["would"])
        self.assertRegex(out["operation_id"], r"^[0-9a-f]{16}$")
        self.assertEqual(before, self.commits())

    def test_the_same_request_prepared_twice_is_one_operation(self):
        a = self.w.prepare("park", "Work", project="Acme Review", thread="Pricing")
        b = self.w.prepare("park", "Work", project="Acme Review", thread="Pricing")
        self.assertEqual(a["operation_id"], b["operation_id"])

    def test_a_changed_payload_under_the_same_id_is_refused(self):
        a = self.w.prepare("note-add", "Work", project="Acme Review", text="first words")
        same = self.w.prepare("note-add", "Work", project="Acme Review", text="first words", operation_id=a["operation_id"])
        self.assertEqual(a["operation_id"], same["operation_id"])
        changed = self.w.prepare("note-add", "Work", project="Acme Review", text="other words", operation_id=a["operation_id"])
        self.assertEqual("changed", changed["error"])
        self.assertEqual("not_found", self.w.prepare("note-add", "Work", project="Acme Review", text="x", operation_id="0" * 16)["error"])
        self.assertEqual("not_found", self.w.prepare("note-add", "Work", project="Acme Review", text="x", operation_id="../../x")["error"])

    def test_another_grants_operation_is_not_found(self):
        a = self.w.prepare("park", "Work", project="Acme Review", thread="Pricing")
        other = writes.Writes(self.session(readable=("Work",), writable=("Work",), grant_id="grant-two"))
        for call in (other.execute, other.status):
            self.assertEqual("not_found", call(a["operation_id"])["error"])
        self.assertEqual("prepared", self.w.status(a["operation_id"])["state"])


class TestTheEffectIsTheRightOne(WritesCase):
    def test_a_note_is_a_dated_note_in_the_thread(self):
        op, out = self.go("note-add", project="Acme Review", thread="Pricing", text="Dana confirmed the pallet price. NOTEMARK", title="Pallet price")
        self.assertEqual("saved", out["state"], out)
        notes = list((self.work / "Acme Review" / "Threads" / "Pricing").rglob("*NOTEMARK*")) or \
            [p for p in (self.work / "Acme Review").rglob("*.md") if "NOTEMARK" in p.read_text() and p.name != "Pricing.md"]
        self.assertEqual(1, len(notes))
        self.assertRegex(notes[0].name, r"^\d{6}|\d{4}-\d{2}-\d{2}")
        self.assertIn("Notes", notes[0].parts)
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_an_action_reaches_the_zones_todo(self):
        op, out = self.go("todo-add", text="Call Dana about the pallets", target="Acme Review/Pricing", date="2026-12-01")
        self.assertEqual("saved", out["state"], out)
        todo = (self.work / "Todo.md").read_text()
        self.assertIn("Call Dana about the pallets", todo)
        self.assertIn("2026-12-01", todo)
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_tick_untick_redate_reword_and_retire_a_line(self):
        line = "Invoice for September"
        self.assertEqual("saved", self.go("todo-done", line=line)[1]["state"])
        self.assertRegex((self.work / "Todo.md").read_text(), r"- \[x\].*Invoice for September")
        self.assertEqual("saved", self.go("todo-undo", line=line)[1]["state"])
        self.assertRegex((self.work / "Todo.md").read_text(), r"- \[ \].*Invoice for September")
        self.assertEqual("saved", self.go("todo-date", line=line, date="2026-12-15")[1]["state"])
        self.assertIn("2026-12-15", (self.work / "Todo.md").read_text())
        self.assertEqual("saved", self.go("todo-edit", line=line, text="Acme Corp: Invoice for October")[1]["state"])
        self.assertIn("Invoice for October", (self.work / "Todo.md").read_text())
        out = self.go("todo-retire", line="Invoice for October", reason="the order moved to Birch")[1]
        self.assertEqual("saved", out["state"], out)
        self.assertNotIn("Invoice for October", (self.work / "Todo.md").read_text())
        expired = list((self.work / "archive").glob("Todo-expired-*.md"))
        self.assertTrue(expired and "superseded by the order moved to Birch" in expired[0].read_text())

    def test_a_line_that_is_not_there_or_not_one_is_refused_and_nothing_is_written(self):
        before = (self.work / "Todo.md").read_text()
        out = self.go("todo-done", line="no such line anywhere")[1]
        self.assertEqual("refused", out["state"])
        self.assertIn("no open line says that", out["say"])
        self.assertEqual(before, (self.work / "Todo.md").read_text())

    def test_park_and_wake_change_the_status_of_the_thread(self):
        self.assertEqual("saved", self.go("park", project="Acme Review", thread="Pricing")[1]["state"])
        self.assertIn("status: parked", (self.root / TH).read_text())
        self.assertEqual("saved", self.go("wake", project="Acme Review", thread="Pricing")[1]["state"])
        self.assertIn("status: active", (self.root / TH).read_text())

    def test_a_checkpoint_lands_under_resume_here_and_writes_no_commit(self):
        before = self.commits()
        items = [{"id": "d1", "kind": "decided", "said": "Dana said the pallet price holds."}]
        op, out = self.go("checkpoint", project="Acme Review", thread="Pricing", items=items)
        self.assertEqual("saved", out["state"], out)
        text = (self.root / TH).read_text()
        self.assertIn("Dana said the pallet price holds", text)
        self.assertEqual(before, self.commits())

    def test_a_second_checkpoint_may_follow_the_first_though_the_note_is_still_uncommitted(self):
        a = [{"id": "d1", "kind": "decided", "said": "Dana said the price holds."}]
        b = [{"id": "d2", "kind": "decided", "said": "Theo agreed to the terms."}]
        self.assertEqual("saved", self.go("checkpoint", project="Acme Review", thread="Pricing", items=a)[1]["state"])
        out = self.go("checkpoint", project="Acme Review", thread="Pricing", items=b)[1]
        self.assertEqual("saved", out["state"], out)
        self.assertIn("Theo agreed", (self.root / TH).read_text())

    def test_a_checkpoint_does_not_overwrite_another_hand_edit_of_the_note(self):
        a = [{"id": "d1", "kind": "decided", "said": "Dana said the price holds."}]
        self.go("checkpoint", project="Acme Review", thread="Pricing", items=a)
        note = self.root / TH
        note.write_text(note.read_text() + "\nAn edit from the desk. DESKMARK\n")
        out = self.go("checkpoint", project="Acme Review", thread="Pricing",
                      items=[{"id": "d2", "kind": "decided", "said": "Theo agreed to the terms."}])[1]
        self.assertEqual("refused", out["state"])
        self.assertIn("DESKMARK", note.read_text())
        self.assertNotIn("Theo agreed", note.read_text())


class TestRetries(WritesCase):
    """A9: each verb retried during execution, after success and across a restart saves once."""

    CASES = [
        ("note-add", dict(project="Acme Review", thread="Pricing", text="RETRYNOTE once"), lambda c: sum(
            p.read_text().count("RETRYNOTE") for p in (c.work / "Acme Review").rglob("*.md"))),
        ("todo-add", dict(text="RETRYADD once"), lambda c: (c.work / "Todo.md").read_text().count("RETRYADD")),
        ("todo-done", dict(line="Invoice for September"), lambda c: len(re.findall(r"- \[x\]", (c.work / "Todo.md").read_text()))),
        ("todo-date", dict(line="Invoice for September", date="2026-12-31"), lambda c: (c.work / "Todo.md").read_text().count("2026-12-31")),
        ("todo-edit", dict(line="Invoice for September", text="Invoice RETRYEDIT"), lambda c: (c.work / "Todo.md").read_text().count("RETRYEDIT")),
        ("todo-retire", dict(line="Invoice for September", reason="RETRYRETIRE"), lambda c: sum(
            p.read_text().count("RETRYRETIRE") for p in (c.work / "archive").glob("Todo-expired-*.md"))
            if (c.work / "archive").is_dir() else 0),
        ("park", dict(project="Acme Review", thread="Pricing"), lambda c: len(git(c.work, "log", "--oneline").splitlines())),
        ("todo-undo", dict(line="Line for undo"), lambda c: (c.work / "Todo.md").read_text().count("- [ ] Line for undo")),
        ("wake", dict(project="Acme Review", thread="Pricing"), lambda c: len(git(c.work, "log", "--oneline").splitlines())),
        ("checkpoint", dict(project="Acme Review", thread="Pricing", items=[{"id": "r1", "kind": "decided", "said": "RETRYCP said once."}]),
         lambda c: (c.root / TH).read_text().count("RETRYCP")),
    ]

    def test_each_verb_saves_once_when_asked_again_during_after_and_across_a_restart(self):
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text().replace("## Done", "".join(
            "- [ ] Line for %s\n" % v for v in ("date", "edit", "retire", "undo")) + "\n## Done"))
        git(self.work, "add", "-A")
        subprocess.run(["git", "-C", str(self.work), "commit", "-q", "-m", "lines"], capture_output=True)
        for verb, fields, effect in self.CASES:
            fields = {k: (v.replace("Invoice for September", "Line for " + verb.split("-")[1]) if isinstance(v, str) and verb in (
                "todo-date", "todo-edit", "todo-retire", "todo-undo") and k == "line" else v) for k, v in fields.items()}
            with self.subTest(verb=verb):
                if verb == "todo-undo":
                    self.assertEqual("saved", self.go("todo-done", line="Line for undo")[1]["state"])
                if verb == "wake":
                    self.assertEqual("saved", self.go("park", project="Acme Review", thread="Pricing")[1]["state"])
                made = self.w.prepare(verb, "Work", **fields)
                op = made["operation_id"]
                base = effect(self)
                first = self.w.execute(op)
                again = self.w.execute(op)                                # during execution (or at once after)
                self.assertIn(again["state"], ("running", "saved"))
                self.assertEqual(op, again["operation_id"])
                done = self.wait(op)
                self.assertEqual("saved", done["state"], done)
                after = effect(self)
                self.assertEqual(base + 1, after)
                self.assertEqual(done["say"], self.w.execute(op)["say"])  # after success: the first receipt
                restarted = writes.Writes(self.s, store=writes.Store(self.w.store.root.parent))
                self.assertEqual(done["say"], restarted.execute(op)["say"])  # across a restart of the service
                self.assertEqual(done["say"], restarted.status(op)["say"])
                again2 = restarted.prepare(verb, "Work", operation_id=op, **fields)
                self.assertEqual(op, again2["operation_id"])
                time.sleep(0.3)
                self.assertEqual(after, effect(self))
                if verb == "park":
                    self.go("wake", project="Acme Review", thread="Pricing")

    def test_two_executes_at_once_run_the_page_action_once(self):
        fake = self.root / "System" / "status" / "page_action.py"
        count = Path(self._tmp.name) / "runs.txt"
        fake.write_text(textwrap.dedent("""\
            import json, sys, time
            time.sleep(2)
            open(%r, "a").write(sys.stdin.read() + "\\n")
            print(json.dumps({"ok": True, "say": "Added to Inbox."}))
            """ % str(count)))
        op = self.w.prepare("todo-add", "Work", text="Once only")["operation_id"]
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.w.execute(op)["state"])) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(["running"] * 4, results)
        self.assertEqual("saved", self.wait(op)["state"])
        self.assertEqual(1, len(count.read_text().strip().splitlines()))

    def test_a_worker_that_is_gone_leaves_an_unknown_that_is_never_run_again(self):
        op = self.w.prepare("todo-add", "Work", text="Lost worker")["operation_id"]
        rec = self.w.store.read(op)
        rec.update({"state": "running", "started": time.time() - 600})
        self.w.store.write(op, rec)
        out = self.w.status(op)
        self.assertEqual("unknown", out["state"])
        self.assertFalse(out["saved"])
        before = (self.work / "Todo.md").read_text()
        self.assertEqual("unknown", self.w.execute(op)["state"])
        time.sleep(0.5)
        self.assertEqual(before, (self.work / "Todo.md").read_text())

    def test_what_was_asked_is_not_kept_after_the_receipt(self):
        op, out = self.go("note-add", project="Acme Review", text="KEEPNOT words")
        self.assertNotIn("KEEPNOT", json.dumps(self.w.store.read(op)))


CHILD = textwrap.dedent('''
    import importlib.util, os, subprocess, sys, json
    spec = importlib.util.spec_from_file_location("o", sys.argv[1]); ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ops)
    repo, point, req, op = sys.argv[2], sys.argv[3], json.loads(sys.argv[4]), sys.argv[5]
    def git(*a):
        subprocess.run(["git", "-C", repo] + list(a), check=True, capture_output=True)
    def work(trailers):
        if point == "before":
            os._exit(9)
        if point == "other":
            trailers = "Garrick-Op: " + op + "\\nGarrick-Payload: " + "0" * 64
        if req["verb"] == "todo-done":
            text = open(os.path.join(repo, "Todo.md")).read().replace("- [ ] Acme Corp: Invoice for September", "- [x] Acme Corp: Invoice for September")
            open(os.path.join(repo, "Todo.md"), "w").write(text)
        else:
            with open(os.path.join(repo, "Todo.md"), "a") as f:
                f.write("- [ ] " + req["text"] + "\\n")
        git("add", "Todo.md")
        git("commit", "-q", "-m", "Add a line", "-m", trailers)
        if point in ("after", "other"):
            os._exit(9)
        return "ok"
    if point == "unsettled":
        ops.settle = lambda *a, **k: os._exit(9)
    ops.prepare(repo, req["verb"], req, op=op, via="remote")
    ops.execute(repo, op, work)
''')


class TestStoppedInTheMiddle(WritesCase):
    """O1 (#716): a write that stops before, after, or after the commit but before it is settled is settled once from the zone's
    own record of the commit, and never committed twice."""

    def stopped(self, point, text, payload_text=None, verb="todo-add", **fields):
        made = self.w.prepare(verb, "Work", **(fields or {"text": text}))
        op = made["operation_id"]
        req = {"verb": verb, "zone": "Work", "op": op, "text": payload_text or text}
        done = subprocess.run([sys.executable, "-I", "-c", CHILD, str(self.root / "System" / "tools" / "operations.py"), str(self.work),
                               point, json.dumps(req), op], capture_output=True, text=True,
                              env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull))
        self.assertEqual(9, done.returncode, done.stderr)
        rec = self.w.store.read(op)
        rec.update({"state": "running", "started": time.time() - 600})
        self.w.store.write(op, rec)
        return op

    def ops(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("garrick_ops_test", str(self.root / "System" / "tools" / "operations.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_stopped_before_the_commit_it_is_reported_not_saved_once_and_never_runs_again(self):
        before = self.commits()
        op = self.stopped("before", "STOPBEFORE line")
        out = self.w.status(op)
        self.assertEqual(("refused", False), (out["state"], out["saved"]), out)
        self.assertEqual(out["say"], self.w.status(op)["say"])
        self.assertEqual("refused", self.w.execute(op)["state"])
        time.sleep(0.4)
        self.assertEqual(before, self.commits())
        self.assertNotIn("STOPBEFORE", (self.work / "Todo.md").read_text())
        self.assertEqual([op], [r["op"] for r in self.ops().sweep(self.work)])   # the page's sweep says it once

    def test_stopped_after_the_commit_it_is_saved_with_that_commit_and_never_commits_twice(self):
        before = self.commits()
        op = self.stopped("after", "STOPAFTER line")
        out = self.w.status(op)
        self.assertEqual(("saved", True), (out["state"], out["saved"]), out)
        self.assertEqual(before + 1, self.commits())
        self.assertEqual(1, (self.work / "Todo.md").read_text().count("STOPAFTER"))
        self.assertEqual(out["say"], self.w.status(op)["say"])
        self.assertEqual("saved", self.w.execute(op)["state"])
        time.sleep(0.4)
        self.assertEqual(before + 1, self.commits())
        self.assertEqual([op], [r["op"] for r in self.ops().sweep(self.work)])

    def test_stopped_after_the_commit_but_before_it_was_settled_it_is_saved_once(self):
        before = self.commits()
        op = self.stopped("unsettled", "STOPUNSETTLED line")
        self.assertEqual("saved", self.w.status(op)["state"])
        self.assertEqual(before + 1, self.commits())
        self.assertEqual("saved", self.w.execute(op)["state"])
        self.assertEqual(before + 1, self.commits())
        self.assertEqual([op], [r["op"] for r in self.ops().sweep(self.work)])

    def test_a_commit_with_this_id_and_another_request_is_unknown_and_names_nothing_to_run(self):
        before = self.commits()
        op = self.stopped("other", "ASKED line")
        out = self.w.status(op)
        self.assertEqual(("unknown", False), (out["state"], out["saved"]), out)
        self.assertEqual("unknown", self.w.execute(op)["state"])
        time.sleep(0.4)
        self.assertEqual(before + 1, self.commits())

    def test_the_core_is_not_asked_when_the_grant_no_longer_reaches_the_zone(self):
        op = self.stopped("after", "REVOKED line")
        self.s.change_reach(writable=())                                  # the owner took the zone out of reach
        out = self.w.status(op)
        self.assertEqual(("unknown", run_op.CRASHED), (out["state"], out["say"]), out)
        self.assertNotIn("commit", out)

    def test_the_core_is_not_asked_after_the_reach_changed_or_the_zone_was_replaced(self):
        self.s.reach_id = lambda: "reach-one"
        op = self.stopped("after", "REPLACED line")
        self.s.reach_id = lambda: "reach-two"                              # the zone was made again, and turned on again
        out = self.w.status(op)
        self.assertEqual(("unknown", run_op.CRASHED), (out["state"], out["say"]), out)

    def test_the_remote_read_never_uses_up_the_report_the_page_makes(self):
        op = self.stopped("after", "ONCEPAGE line")
        self.assertEqual("saved", self.w.status(op)["state"])
        got = self.ops().sweep(self.work)                                  # the page's sweep still says it, once
        self.assertEqual([op], [r["op"] for r in got])
        self.assertEqual([], self.ops().sweep(self.work))

    def test_a_todo_tick_that_stops_in_the_middle_is_settled_from_the_core_record_once(self):
        before = self.commits()
        op = self.stopped("after", "", verb="todo-done", line="Invoice for September")
        out = self.w.status(op)
        self.assertEqual(("saved", True), (out["state"], out["saved"]), out)
        self.assertEqual(before + 1, self.commits())
        self.assertRegex((self.work / "Todo.md").read_text(), r"- \[x\].*Invoice for September")
        self.assertEqual("saved", self.w.execute(op)["state"])
        time.sleep(0.4)
        self.assertEqual(before + 1, self.commits())
        self.assertEqual([op], [r["op"] for r in self.ops().sweep(self.work)])       # S6: the remote read marked nothing

    def test_each_todo_line_verb_sends_the_remote_id_and_leaves_a_record_under_it(self):
        steps = (("todo-done", dict(line="Invoice for September")), ("todo-undo", dict(line="Invoice for September")),
                 ("todo-edit", dict(line="Invoice for September", text="Invoice LINEOP")),
                 ("todo-date", dict(line="Invoice LINEOP", date="2026-12-30")),
                 ("todo-retire", dict(line="Invoice LINEOP", reason="LINEOPRETIRE")))
        for verb, fields in steps:
            with self.subTest(verb=verb):
                op, out = self.go(verb, **fields)
                self.assertEqual("saved", out["state"], out)
                rec = json.loads((self.work / ".git" / "garrick-ops" / (op + ".json")).read_text())
                self.assertEqual((verb, "settled", "done", "remote"), (rec["verb"], rec["state"], rec["result"], rec["via"]))
        argv = run_op.command(str(self.root), {"id": "0123456789abcdef", "verb": "todo-done", "zone": "Work", "fields": {"line": "x"}})[0]
        self.assertIn("--op=0123456789abcdef", argv)

    def test_a_write_that_stopped_before_the_core_began_says_unknown_as_before(self):
        op = self.w.prepare("todo-add", "Work", text="NOCORE line")["operation_id"]
        rec = self.w.store.read(op)
        rec.update({"state": "running", "started": time.time() - 600})
        self.w.store.write(op, rec)
        out = self.w.status(op)
        self.assertEqual(("unknown", run_op.CRASHED), (out["state"], out["say"]))

    def test_a_remote_write_is_recorded_by_the_core_with_the_remote_caller_and_settled_done(self):
        op, out = self.go("todo-add", text="RECORDED line")
        self.assertEqual("saved", out["state"], out)
        rec = json.loads((self.work / ".git" / "garrick-ops" / (op + ".json")).read_text())
        self.assertEqual(("todo-add", "settled", "done", "remote"), (rec["verb"], rec["state"], rec["result"], rec["via"]))
        self.assertNotIn("RECORDED", json.dumps(rec))                     # the record holds no words of the request
        self.assertIn("Garrick-Op: " + op, git(self.work, "log", "-1", "--format=%B"))

    def test_a_write_prepared_by_the_older_extra_before_the_update_still_runs_or_says_why(self):
        made = self.w.prepare("todo-add", "Work", text="OLDPREP line")
        op = made["operation_id"]
        rec = self.w.store.read(op)
        rec.pop("reach", None)                                          # a record as 0.82.0 left it
        self.w.store.write(op, rec)
        out = self.w.execute(op)
        self.assertIn(out.get("state") or out.get("error"), ("running", "new_context_required"), out)
        if out.get("state"):
            self.assertEqual("saved", self.wait(op)["state"])
            self.assertEqual(1, (self.work / "Todo.md").read_text().count("OLDPREP"))
        else:
            self.assertTrue(out["say"])
        stuck = self.w.prepare("todo-add", "Work", text="OLDRUN line")["operation_id"]      # one that was running when the update came
        rec = self.w.store.read(stuck)
        rec.update({"state": "running", "started": time.time() - 600})
        self.w.store.write(stuck, rec)
        said = self.w.status(stuck)
        self.assertEqual(("unknown", run_op.CRASHED), (said["state"], said["say"]))

    def test_the_reach_check_still_holds_on_this_path_and_a_refused_write_leaves_no_record(self):
        self.s.reach_id = lambda: "reach-one"
        made = self.w.prepare("todo-add", "Work", text="REACHLESS line")
        self.s.reach_id = lambda: "reach-two"
        before = self.commits()
        out = self.w.execute(made["operation_id"])
        self.assertEqual(common.NEW_REACH, out["error"])
        self.assertIn("changed what this connection may reach", out["say"])
        time.sleep(0.3)
        self.assertEqual(before, self.commits())
        self.assertFalse((self.work / ".git" / "garrick-ops" / (made["operation_id"] + ".json")).exists())


class TestTheRecord(WritesCase):
    def test_an_unknown_id_makes_no_file(self):
        files = lambda: sorted(p.name for p in self.w.store.root.iterdir() if p.name != "prepare.lock")     # the one fixed lock
        before = files()
        for bad in ("0123456789abcdef", "fedcba9876543210"):
            for call in (self.w.status, self.w.execute):
                self.assertEqual("not_found", call(bad)["error"])
            self.assertEqual("not_found", self.w.prepare("todo-add", "Work", text="x", operation_id=bad)["error"])
        self.assertEqual(before, files())

    def test_what_would_change_is_dropped_with_the_words(self):
        op, out = self.go("note-add", project="Acme Review", text="WOULDMARK words")
        rec = self.w.store.read(op)
        self.assertNotIn("would", rec)
        self.assertNotIn("WOULDMARK", json.dumps(rec))
        refused = self.w.prepare("todo-add", "Work", text="WOULD2 words")
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text() + "- [ ] dirty\n")
        self.w.execute(refused["operation_id"])
        self.assertNotIn("WOULD2", json.dumps(self.w.store.read(refused["operation_id"])))

    def test_a_repeat_the_record_asks_about_is_a_plain_receipt_without_a_question(self):
        asked = {"ok": False, "state": "asked", "say": "The same request was done 4 minutes ago: Added. It has not been done again. Do you want it done a second time?", "op": "x", "again": "x"}
        made = run_op.receipt("todo-add", 1, json.dumps(asked), "")
        self.assertFalse(made["ok"])
        self.assertEqual("This was already done a few minutes ago. Nothing was saved again.", made["say"])
        text = run_op.receipt("todo-done", 1, "", asked["say"])
        self.assertNotIn("?", text["say"])
        self.assertIn("Nothing was saved again", text["say"])
        running = dict(asked, say="The same request is still running, started 1 minute ago: Adding. It has not been sent again. Do you want it done a second time once that one ends?")
        self.assertNotIn("?", run_op.receipt("note-add", 1, json.dumps(running), "")["say"])


class TestAUsersOwnWordsAreNotAQuestion(WritesCase):
    def test_a_line_that_says_done_a_second_time_is_saved_and_says_so(self):
        text = "Ask Jo whether the survey is to be done a second time"
        made = run_op.receipt("todo-add", 0, json.dumps({"ok": True, "say": "Added to Inbox: " + text}), "")
        self.assertTrue(made["ok"])
        plain = run_op.receipt("todo-done", 0, "Ticked: " + text, "")
        self.assertTrue(plain["ok"])
        op, out = self.go("todo-add", text=text)
        self.assertEqual("saved", out["state"], out)
        self.assertIn(text, (self.work / "Todo.md").read_text())

    def test_the_fixed_question_at_the_end_of_a_failed_plain_text_answer_is_a_repeat(self):
        q = "It has not been done again. Do you want it done a second time?"
        self.assertIn("Nothing was saved again", run_op.receipt("todo-done", 1, "", "The same request was done 4 minutes ago: Ticked. " + q)["say"])
        self.assertTrue(run_op.receipt("todo-done", 0, "Ticked. " + q, "")["ok"])

    def test_a_note_whose_words_hold_still_running_gets_the_receipt_of_an_action_that_ended(self):
        said = ("The same request was done 4 minutes ago: Added to Inbox: Check whether the pump is still running. "
                "It has not been done again. Do you want it done a second time?")
        asked = {"ok": False, "state": "asked", "say": said, "op": "x", "again": "x"}
        self.assertEqual(run_op.REPEAT_DONE, run_op.receipt("todo-add", 1, json.dumps(asked), "")["say"])
        self.assertEqual(run_op.REPEAT_DONE, run_op.receipt("todo-add", 1, "", said)["say"])
        running = dict(asked, say="The same request is still running, started 1 minute ago: Adding. It has not been sent again. "
                                  "Do you want it done a second time once that one ends?")
        self.assertEqual(run_op.REPEAT_RUNNING, run_op.receipt("todo-add", 1, json.dumps(running), "")["say"])


class TestTheDeskIsSafe(WritesCase):
    def test_a_todo_with_changes_not_committed_is_not_overwritten(self):
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text() + "- [ ] A line typed at the desk. DESKLINE\n")
        before, commits = todo.read_text(), self.commits()
        out = self.go("todo-add", text="From the phone")[1]
        self.assertEqual("refused", out["state"])
        self.assertIn("not saved to its history", out["say"])
        self.assertEqual(before, todo.read_text())
        self.assertEqual(commits, self.commits())

    def test_a_note_open_with_unsaved_changes_is_not_overwritten(self):
        note = self.root / TH
        note.write_text(note.read_text() + "\nA sentence being typed. TYPEDMARK\n")
        before = note.read_text()
        for verb, fields in (("park", {}), ("checkpoint", dict(items=[{"id": "x", "kind": "decided", "said": "Dana said yes."}]))):
            out = self.go(verb, project="Acme Review", thread="Pricing", **fields)[1]
            self.assertEqual("refused", out["state"], verb)
            self.assertEqual(before, note.read_text(), verb)

    def test_a_wrap_that_is_running_blocks_the_thread(self):
        subprocess.run([sys.executable, str(self.root / "System" / "tools" / "wrap_lock.py"), "start", TH], cwd=str(self.root), check=True,
                       capture_output=True)
        before = (self.root / TH).read_text()
        out = self.go("park", project="Acme Review", thread="Pricing")[1]
        self.assertEqual("refused", out["state"])
        self.assertIn("wrap is running", out["say"])
        self.assertEqual(before, (self.root / TH).read_text())
        subprocess.run([sys.executable, str(self.root / "System" / "tools" / "wrap_lock.py"), "end", "--abandon", TH], cwd=str(self.root),
                       capture_output=True)
        self.assertEqual("saved", self.go("park", project="Acme Review", thread="Pricing")[1]["state"])

    def test_a_missing_lock_tool_counts_as_a_wrap_that_may_be_running(self):
        (self.root / "System" / "tools" / "wrap_lock.py").unlink()
        self.assertEqual("refused", self.go("park", project="Acme Review", thread="Pricing")[1]["state"])

    def test_the_reach_changed_between_prepare_and_execute_runs_nothing(self):
        made = self.w.prepare("todo-add", "Work", text="Too late")
        self.s.change_reach(writable=())
        before, commits = (self.work / "Todo.md").read_text(), self.commits()
        out = self.w.execute(made["operation_id"])
        self.assertEqual(common.NEW_REACH, out["error"])
        self.assertEqual(before, (self.work / "Todo.md").read_text())
        self.assertEqual(commits, self.commits())


class TestWhatIsSentAndKept(WritesCase):
    def stand_in(self):
        fake = self.root / "System" / "status" / "page_action.py"
        seen = Path(self._tmp.name) / "seen.jsonl"
        fake.write_text(textwrap.dedent("""\
            import json, sys
            open(%r, "a").write(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read()}) + "\\n")
            print(json.dumps({"ok": True, "say": "Done."}))
            """ % str(seen)))
        return seen

    def test_the_request_is_built_here_and_carries_no_confirm(self):
        seen = self.stand_in()
        for verb, fields in (("todo-add", dict(text="One", target="Acme Review")), ("park", dict(project="Acme Review", thread="Pricing")),
                             ("note-add", dict(project="Acme Review", text="A note")), ("todo-done", dict(line="Invoice"))):
            self.go(verb, **fields)
        rows = [json.loads(line) for line in seen.read_text().splitlines()]
        self.assertEqual(4, len(rows))
        for row in rows:
            self.assertIn("--via", row["argv"])
            self.assertEqual("remote", row["argv"][row["argv"].index("--via") + 1])
            blob = json.dumps(row)
            for never in ("confirm", "destination", '"key"', '"file"'):
                self.assertNotIn(never, blob.replace("--file=Todo.md", ""))
        line = rows[-1]
        self.assertIn("--file=Todo.md", line["argv"])
        self.assertEqual(json.loads(rows[0]["stdin"])["op"], json.loads(rows[0]["stdin"])["op"])

    def test_nothing_in_the_tools_imports_page_action(self):
        """The service never holds page_action.py: it is named only in the command of a process, and Ask's read server,
        which loads it, is a process of its own too."""
        for p in sorted((support.REPO / "extras" / "remote" / "tools").glob("*.py")):
            text = p.read_text()
            self.assertNotRegex(text, r"(?m)^\s*(import|from)\s+page_action", p.name)
            self.assertNotIn("exec_module", text, p.name)
            self.assertNotIn("spec_from_file_location", text, p.name)
            for m in re.finditer(r"page_action", text):
                line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.start())]
                self.assertRegex(line, r'page_action\.py|^\s*(#|""")|^[A-Za-z`*"\' ]', p.name + ": " + line)

    def test_the_service_log_holds_no_text(self):
        with self.assertLogs("garrick.remote.tools", level="INFO") as logs:
            import asyncio
            from mcp.server.mcpserver import MCPServer
            from tools import register
            server = MCPServer("t")
            register(server, lambda ctx: self.s)
            made = asyncio.run(server.call_tool("prepare", {"verb": "note-add", "zone": "Work", "project": "Acme Review", "text": "LOGSECRET words"}))
            op = json.loads(made.content[0].text)["operation_id"]
            asyncio.run(server.call_tool("execute", {"operation_id": op}))
            self.wait(op)
            asyncio.run(server.call_tool("status", {"operation_id": op}))
        text = "\n".join(logs.output)
        self.assertNotIn("LOGSECRET", text)
        self.assertIn("tool=prepare", text)
        self.assertIn("grant=grant-one", text)

    def test_the_operation_store_is_private(self):
        op = self.w.prepare("todo-add", "Work", text="x")["operation_id"]
        self.assertEqual(0o700, os.stat(self.w.store.root).st_mode & 0o777)
        self.assertEqual(0o600, os.stat(self.w.store.path(op)).st_mode & 0o777)

    def test_the_tool_list_has_the_three_write_tools_and_the_five_reads(self):
        import asyncio
        from mcp.server.mcpserver import MCPServer
        from tools import register
        server = MCPServer("t")
        names = register(server, lambda ctx: self.s)
        self.assertEqual(["places", "thread_state", "search", "read", "owed", "prepare", "execute", "status"], names)
        listed = {t.name: t for t in asyncio.run(server.list_tools())}
        self.assertFalse(listed["prepare"].annotations.read_only_hint)
        self.assertFalse(listed["execute"].annotations.read_only_hint)
        self.assertTrue(listed["status"].annotations.read_only_hint)
        for name in ("prepare", "execute", "status"):
            props = set(listed[name].input_schema["properties"])
            self.assertFalse(props & {"confirm", "file", "key", "destination", "op", "via", "reach", "grant"}, name)


if __name__ == "__main__":
    unittest.main()
