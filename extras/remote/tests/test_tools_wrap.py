"""The wrap verb (#723): a thread wrapped through remote access runs System/tools/wrap.py, as a wrap at the Mac does.

The effect is checked against the workspace's real page_action.py and wrap.py, run as processes of their own, in a fixture
workspace with real git repositories. A twin of the workspace takes the same words at the Mac (page_action.py as a session
runs it), and the two are compared file by file and by the tree of the commit.

Run with the extra's runtime:  python -m unittest discover -s extras/remote/tests -p "test_tools_wrap.py"
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import test_tools_writes as base  # noqa: E402
import tools_support as support  # noqa: E402
from tools import common, run_op, wrap_verb, writes  # noqa: E402

git = base.git
TH = base.TH
PROJECT, THREAD = "Acme Review", "Pricing"
WORDS = {
    "resume": {"stands": "The sheet is drafted and sent to Dana. The tier-two volume is still open.",
               "rows": {"Live artifact": "the pricing sheet in Deliverables", "Rebuild with": "open the sheet, no script",
                        "Next action": "fill in the tier-two volume", "Keep in mind": "Dana reads it on Monday",
                        "Waiting on": "Dana, the volumes", "Deadline": "none set"}},
    "entry": "Sent the draft to Dana.",
    "message": "Acme Review, Pricing: draft sent",
    "todo": {"add": ["[[Pricing]]: fill in the tier-two volume 📅 2026-12-02"], "tick": ["Invoice for September"]},
}


def words(**over):
    out = copy.deepcopy(WORDS)
    out.update(over)
    return out


class WrapCase(base.WritesCase):
    def head(self):
        return git(self.work, "rev-parse", "HEAD").strip()

    def snapshot(self):
        return git(self.work, "status", "--porcelain").strip(), self.head()

    def put(self, **over):
        return self.w.prepare("wrap", "Work", project=PROJECT, thread=THREAD, **words(**over))

    def do_wrap(self, **over):
        made = self.put(**over)
        self.assertEqual("prepared", made.get("state"), made)
        self.w.execute(made["operation_id"])
        return made["operation_id"], self.wait(made["operation_id"])


class TestAWrapIsAWrapAtTheMac(WrapCase):
    def twin(self):
        out = Path(self._tmp.name) / "twin"
        shutil.copytree(str(self.root), str(out), ignore=shutil.ignore_patterns("__pycache__"), symlinks=True)
        return out

    def at_the_mac(self, root, **over):
        req = {"verb": "wrap", "zone": "Work", "project": PROJECT, "thread": THREAD, "input": words(**over)}
        got = subprocess.run([sys.executable, str(root / "System" / "status" / "page_action.py"), "--workspace", str(root), "--via", "session"],
                             input=json.dumps(req), capture_output=True, text=True, timeout=300,
                             env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull))
        return json.loads(got.stdout)

    def test_the_block_the_entry_and_the_todo_lines_are_those_of_a_wrap_at_the_mac_and_it_is_one_commit(self):
        twin = self.twin()
        before = self.commits()
        mac = self.at_the_mac(twin)
        self.assertTrue(mac["ok"], mac)
        op, out = self.do_wrap()
        self.assertEqual("saved", out["state"], out)
        self.assertEqual(before + 1, self.commits())
        for rel in (TH.split("/", 2)[2], "Todo.md"):
            self.assertEqual((twin / "Zones" / "Work" / rel).read_text(), (self.work / rel).read_text(), rel)
        text = (self.root / TH).read_text()
        self.assertIn("The sheet is drafted and sent to Dana", text)
        self.assertIn("Sent the draft to Dana.", text)
        self.assertIn("fill in the tier-two volume", (self.work / "Todo.md").read_text())
        tree = lambda zone: git(zone, "rev-parse", "HEAD^{tree}").strip()
        self.assertEqual(tree(twin / "Zones" / "Work"), tree(self.work))
        self.assertEqual("Acme Review, Pricing: draft sent", git(self.work, "log", "-1", "--format=%s").strip())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_the_receipt_names_the_commit_and_the_core_record_is_the_remote_ones(self):
        op, out = self.do_wrap()
        self.assertEqual("saved", out["state"], out)
        self.assertTrue(out["say"].startswith("Saved"), out)
        self.assertEqual(self.head()[:7], out["commit"][:7])
        rec = json.loads((self.work / ".git" / "garrick-ops" / (op + ".json")).read_text())
        self.assertEqual(("wrap", "settled", "done", "remote"), (rec["verb"], rec["state"], rec["result"], rec["via"]))
        self.assertIn("Garrick-Op: " + op, git(self.work, "log", "-1", "--format=%B"))

    def test_a_checkpoint_the_note_holds_is_folded_and_the_uncommitted_note_does_not_stop_the_wrap(self):
        items = [{"id": "d1", "kind": "decided", "said": "Dana said the pallet price holds."}]
        self.assertEqual("saved", self.go("checkpoint", project=PROJECT, thread=THREAD, items=items)[1]["state"])
        self.assertNotEqual("", git(self.work, "status", "--porcelain").strip())
        op, out = self.do_wrap(checkpoint="folded")
        self.assertEqual("saved", out["state"], out)
        self.assertNotIn("Dana said the pallet price holds", (self.root / TH).read_text())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_a_checkpoint_the_wrap_does_not_say_it_folded_fails_and_writes_nothing(self):
        items = [{"id": "d1", "kind": "decided", "said": "Dana said the pallet price holds."}]
        self.go("checkpoint", project=PROJECT, thread=THREAD, items=items)
        before = self.snapshot()
        op, out = self.do_wrap()
        self.assertEqual("refused", out["state"], out)
        self.assertEqual(before, self.snapshot())

    def test_a_note_someone_changed_by_hand_is_not_wrapped_over(self):
        note = self.root / TH
        note.write_text(note.read_text() + "\nA hand edit.\n")
        made = self.put()
        out = self.w.execute(made["operation_id"])
        self.assertEqual("refused", out["state"], out)
        self.assertIn("not saved to its history", out["say"])
        self.assertIn("A hand edit.", note.read_text())

    def test_the_zones_todo_list_with_changes_not_committed_stops_the_wrap(self):
        (self.work / "Todo.md").write_text((self.work / "Todo.md").read_text() + "- [ ] by hand\n")
        out = self.w.execute(self.put()["operation_id"])
        self.assertEqual("refused", out["state"], out)
        self.assertIn("Todo.md", out["say"])

    def test_a_wrap_that_is_running_at_the_desk_blocks_the_thread(self):
        tool = self.root / "System" / "tools" / "wrap_lock.py"
        subprocess.run([sys.executable, str(tool), "start", TH], cwd=str(self.root), check=True, capture_output=True)
        out = self.w.execute(self.put()["operation_id"])
        self.assertEqual("refused", out["state"], out)
        self.assertIn("wrap is running", out["say"])


class TestOnceOnly(WrapCase):
    def test_the_same_operation_sent_twice_makes_one_commit_and_the_second_answer_is_the_first_receipt(self):
        before = self.commits()
        op, first = self.do_wrap()
        self.assertEqual("saved", first["state"], first)
        again = self.w.execute(op)
        retried = self.w.prepare("wrap", "Work", project=PROJECT, thread=THREAD, operation_id=op, **words())
        time.sleep(0.5)
        self.assertEqual(before + 1, self.commits())
        self.assertEqual(first["say"], again["say"])
        self.assertEqual(first.get("commit"), again.get("commit"))
        self.assertEqual("saved", retried["state"])
        self.assertEqual(first["say"], retried["say"])
        self.assertEqual(1, (self.root / TH).read_text().count("Sent the draft to Dana."))

    def test_the_core_gives_the_first_receipt_to_the_same_id_and_runs_nothing(self):
        op, first = self.do_wrap()
        req = {"verb": "wrap", "zone": "Work", "op": op, "project": PROJECT, "thread": THREAD, "input": words()}
        before = self.commits()
        got = subprocess.run([sys.executable, str(self.root / "System" / "status" / "page_action.py"), "--workspace", str(self.root),
                              "--via", "remote"], input=json.dumps(req), capture_output=True, text=True, timeout=300,
                             env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull))
        out = json.loads(got.stdout)
        self.assertTrue(out["ok"] and out.get("receipt"), out)
        self.assertEqual(before, self.commits())
        self.assertEqual(1, (self.root / TH).read_text().count("Sent the draft to Dana."))

    def test_the_same_id_for_other_words_is_refused(self):
        op, first = self.do_wrap()
        out = self.w.prepare("wrap", "Work", project=PROJECT, thread=THREAD, operation_id=op, **words(entry="Other words."))
        self.assertEqual("changed", out["error"])


CHILD = textwrap.dedent('''
    import importlib.util, os, subprocess, sys, json
    spec = importlib.util.spec_from_file_location("o", sys.argv[1]); ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ops)
    ws, repo, point, req, op = sys.argv[2], sys.argv[3], sys.argv[4], json.loads(sys.argv[5]), sys.argv[6]
    def work(trailers):
        if point == "before":
            os._exit(9)
        done = subprocess.run([sys.executable, os.path.join(ws, "System", "tools", "wrap.py"), "--root", ws, "--json"],
                              input=json.dumps(dict(req["input"], zone=req["zone"], project=req["project"], thread=req["thread"])), capture_output=True, text=True,
                              env=dict(os.environ, GARRICK_COMMIT_TRAILERS=trailers))
        assert json.loads(done.stdout)["outcome"] == "saved", done.stdout
        if point == "after":
            os._exit(9)
        return "ok"
    if point == "unsettled":
        ops.settle = lambda *a, **k: os._exit(9)
    ops.prepare(repo, "wrap", req, op=op, via="remote")
    ops.execute(repo, op, work)
''')


class TestStoppedInTheMiddle(WrapCase):
    """A wrap that stops before the commit, after it, or after it and before it is settled is settled from git on the next
    run, once, and never committed twice (#716)."""

    def stopped(self, point):
        made = self.put()
        op = made["operation_id"]
        req = {"verb": "wrap", "zone": "Work", "project": PROJECT, "thread": THREAD, "op": op, "input": dict(words())}
        done = subprocess.run([sys.executable, "-I", "-c", CHILD, str(self.root / "System" / "tools" / "operations.py"), str(self.root),
                               str(self.work), point, json.dumps(req), op], capture_output=True, text=True,
                              env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull))
        self.assertEqual(9, done.returncode, done.stderr)
        rec = self.w.store.read(op)
        rec.update({"state": "running", "started": time.time() - 600})
        self.w.store.write(op, rec)
        return op

    def test_stopped_before_the_commit_nothing_is_saved_and_it_is_said_so(self):
        before = self.snapshot()
        op = self.stopped("before")
        out = self.w.status(op)
        self.assertEqual(("refused", False), (out["state"], out["saved"]), out)
        self.assertEqual(before, self.snapshot())

    def test_stopped_after_the_commit_it_is_saved_with_that_commit_and_never_commits_twice(self):
        before = self.commits()
        op = self.stopped("after")
        out = self.w.status(op)
        self.assertEqual(("saved", True), (out["state"], out["saved"]), out)
        self.assertEqual(before + 1, self.commits())
        self.assertEqual("saved", self.w.execute(op)["state"])
        time.sleep(0.4)
        self.assertEqual(before + 1, self.commits())
        self.assertEqual(1, (self.root / TH).read_text().count("Sent the draft to Dana."))

    def test_stopped_after_the_commit_but_before_it_was_settled_it_is_saved_once(self):
        before = self.commits()
        op = self.stopped("unsettled")
        self.assertEqual("saved", self.w.status(op)["state"])
        self.assertEqual("saved", self.w.execute(op)["state"])
        self.assertEqual(before + 1, self.commits())


class TestTheReach(WrapCase):
    def test_a_thread_in_a_zone_the_connection_does_not_reach_is_refused_and_names_nothing_in_it(self):
        pers = self.root / "Zones" / "Personal"
        project = next(p.name for p in pers.iterdir() if p.is_dir() and not p.name.startswith(".") and (p / "Threads").is_dir())
        thread = next((pers / project / "Threads").iterdir()).name
        before = self.snapshot()
        out = self.w.prepare("wrap", "Personal", project=project, thread=thread, **words())
        self.assertEqual(common.NEW_REACH, out["error"])
        self.assertEqual("", out.get("project", ""))
        for name in (project, thread, "Todo.md", "Pricing"):
            self.assertNotIn(name, json.dumps(out))
        self.assertEqual([], list(self.w.store.all()))
        self.assertEqual(before, self.snapshot())

    def test_a_read_only_grant_cannot_prepare_a_wrap(self):
        w = writes.Writes(self.session(readable=("Work",), writable=()))
        self.assertEqual(common.NEW_REACH, w.prepare("wrap", "Work", project=PROJECT, thread=THREAD, **words())["error"])

    def test_the_reach_taken_away_between_prepare_and_execute_stops_the_wrap(self):
        made = self.put()
        self.s.change_reach(writable=())
        before = self.snapshot()
        self.assertEqual(common.NEW_REACH, self.w.execute(made["operation_id"])["error"])
        self.assertEqual(before, self.snapshot())


class TestRefusedWritesNothing(WrapCase):
    def refused(self, **given):
        before = self.snapshot()
        stored = len(list(self.w.store.all()))
        out = self.w.prepare("wrap", "Work", **given)
        self.assertEqual("not_prepared", out.get("error"), out)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(stored, len(list(self.w.store.all())))
        return out["say"]

    def given(self, **over):
        out = dict(project=PROJECT, thread=THREAD, **words())
        out.update(over)
        return {k: v for k, v in out.items() if v is not None}

    def test_a_key_the_tool_does_not_take_is_refused_by_name(self):
        self.assertIn("extra", self.refused(**self.given(extra="x")))
        self.assertIn("file", self.refused(**self.given(file="x.md")))

    def test_each_missing_key_is_refused(self):
        for key in ("project", "resume", "entry", "message"):
            with self.subTest(key=key):
                self.assertIn("needs " + key, self.refused(**self.given(**{key: None})))

    def test_memory_is_never_passed_and_the_refusal_says_so(self):
        for value in ({"path": "/tmp/x.md"}, {}, "x"):
            self.assertIn("memory", self.refused(**self.given(memory=value)))

    def test_a_held_lock_is_never_passed_and_the_refusal_says_so(self):
        for value in ("held", "take", ""):
            self.assertIn("lock", self.refused(**self.given(lock=value)))

    def test_memory_and_lock_are_refused_for_every_verb(self):
        self.assertIn("memory", self.w.prepare("park", "Work", project=PROJECT, thread=THREAD, memory={"path": "x"})["say"])

    def test_words_that_are_not_the_shape_the_tool_takes_are_refused(self):
        bad_rows = dict(WORDS["resume"]["rows"])
        bad_rows.pop("Deadline")
        extra_rows = dict(WORDS["resume"]["rows"], Other="x")
        for over in ({"resume": {"stands": "x", "rows": bad_rows}}, {"resume": {"stands": "x", "rows": extra_rows}},
                     {"resume": {"stands": "x"}}, {"resume": "text"},
                     {"resume": {"stands": "x", "rows": dict(WORDS["resume"]["rows"], Deadline="two\nlines")}},
                     {"resume": {"stands": "x", "rows": dict(WORDS["resume"]["rows"], Deadline="")}},
                     {"resume": {"stands": "# a heading", "rows": WORDS["resume"]["rows"]}},
                     {"entry": "fine\n---\nrule"}, {"entry": "| a | b |"}, {"message": "two\nlines"}, {"message": "x" * 301},
                     {"todo": {"add": "not a list"}}, {"todo": {"other": []}}, {"todo": {"tick": ["a\nb"]}},
                     {"todo": {"add": ["x" * 201]}}, {"checkpoint": "yes"}):
            with self.subTest(over=str(over)[:60]):
                self.refused(**self.given(**over))

    def test_a_line_end_python_reads_but_the_note_does_not_is_refused_in_a_one_line_field(self):
        rows = WORDS["resume"]["rows"]
        for sep in ("\u2028", "\u2029", "\x85", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e"):
            with self.subTest(sep=repr(sep)):
                self.refused(**self.given(resume={"stands": "x", "rows": dict(rows, **{"Next action": "go" + sep + "## Heading"})}))
                self.refused(**self.given(todo={"add": ["one" + sep + "- [ ] two"]}))
                self.refused(**self.given(todo={"tick": ["one" + sep + "two"]}))
                self.refused(**self.given(message="m" + sep + "n"))
                self.refused(**self.given(entry="fine" + sep + "## Heading"))
                self.refused(**self.given(resume={"stands": "fine" + sep + "x", "rows": rows}))

    def test_a_project_or_thread_that_is_not_a_folder_name_is_refused(self):
        for bad in ("..", "../Personal", "a/b", "/etc", "/Users/x", ".hidden", "_x", "a\\b", "Threads"):
            with self.subTest(bad=bad):
                self.refused(**self.given(project=bad))
                self.refused(**self.given(thread=bad))

    def test_a_link_out_of_the_zone_is_refused_at_prepare(self):
        outside = Path(self._tmp.name) / "outside"
        (outside / "Threads" / "Loot").mkdir(parents=True)
        (outside / "Threads" / "Loot" / "Loot.md").write_text("x")
        os.symlink(str(outside), str(self.work / "Linked"))
        self.assertIn("not a folder of this zone", self.refused(**self.given(project="Linked", thread="Loot")))
        threads = self.work / PROJECT / "Threads"
        os.symlink(str(outside / "Threads" / "Loot"), str(threads / "Sneak"))
        self.assertIn("not a folder of this zone", self.refused(**self.given(thread="Sneak")))
        os.remove(str(threads / "Sneak"))
        (threads / "Note").mkdir()
        os.symlink(str(outside / "Threads" / "Loot" / "Loot.md"), str(threads / "Note" / "Note.md"))
        self.assertIn("not a folder of this zone", self.refused(**self.given(thread="Note")))
        self.assertEqual("x", (outside / "Threads" / "Loot" / "Loot.md").read_text())
        os.remove(str(self.work / "Linked"))
        shutil.rmtree(str(threads / "Note"))

    def test_a_link_put_in_place_after_prepare_is_refused_at_execute(self):
        made = self.put()
        commits = self.commits()
        outside = Path(self._tmp.name) / "outside2"
        shutil.copytree(str(self.work / PROJECT), str(outside))
        shutil.rmtree(str(self.work / PROJECT / "Threads" / THREAD))
        os.symlink(str(outside / "Threads" / THREAD), str(self.work / PROJECT / "Threads" / THREAD))
        out = self.w.execute(made["operation_id"])
        self.assertEqual("refused", out["state"], out)
        self.assertEqual(commits, self.commits())                                            # nothing was committed
        self.assertNotIn("Sent the draft", (outside / "Threads" / THREAD / (THREAD + ".md")).read_text())

    def test_a_thread_that_is_not_there_is_the_tools_own_refusal_and_nothing_is_written(self):
        before = self.snapshot()
        op, out = self.run_for("Nowhere")
        self.assertEqual("refused", out["state"], out)
        self.assertEqual(before, self.snapshot())

    def run_for(self, thread):
        made = self.w.prepare("wrap", "Work", project=PROJECT, thread=thread, **words())
        self.w.execute(made["operation_id"])
        return made["operation_id"], self.wait(made["operation_id"])


class TestTheWallHoldsThingsBack(WrapCase):
    """A wrap the zone's wall hook refuses answers with the rule's sentence only (L2): no zone, project, thread or file of the
    zone it names, and the same for every note of that zone. (A link to a note that is not there is not refused by the hook at all,
    at the Mac or here; that is the hook's rule, not this verb's.)"""

    def refused_for(self, link):
        sys.path.insert(0, str(support.REPO / "template" / "System" / "tools"))
        try:
            from garrick_lib import install_wall_hook
            install_wall_hook(self.work)
        finally:
            sys.path.pop(0)
        git(self.work, "add", "-A")
        subprocess.run(["git", "-C", str(self.work), "commit", "-q", "--no-verify", "-m", "hook"], capture_output=True)
        before = self.snapshot()
        op, out = self.do_wrap(entry="See [[%s]]." % link)
        self.assertEqual("refused", out["state"], out)
        self.assertEqual(before, self.snapshot())
        return out

    def test_the_hooks_refusal_is_the_wall_sentence_and_names_nothing_of_the_walled_zone(self):
        said = []
        for link in ("Birch Entry/Threads/Market Sizing/Market Sizing", "Birch Entry/Birch Entry"):
            out = self.refused_for(link)
            said.append(json.dumps(out, sort_keys=True))
            self.assertEqual(run_op.WALL_SAYS, out["say"])
            for name in ("Birch", "Market Sizing", "Personal", "walled", "Commit refused", ".md"):
                self.assertNotIn(name, json.dumps(out))
        out0, out1 = (json.loads(x) for x in said)
        out0.pop("operation_id"), out1.pop("operation_id")
        self.assertEqual(out0, out1)

    def test_the_sentence_is_the_rules_own(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ops_t", str(self.root / "System" / "tools" / "operations.py"))
        ops = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ops)
        self.assertEqual(ops.WALL_REFUSAL, run_op.WALL_SAYS)


class TestTheServiceHoldsNoWords(WrapCase):
    def test_the_record_and_the_service_log_hold_none_of_the_wraps_words(self):
        from mcp.server.mcpserver import MCPServer
        from tools import register
        marked = words(entry="WRAPSECRET entry words.", message="WRAPSECRET message")
        marked["resume"]["stands"] = "WRAPSECRET stands."
        with self.assertLogs("garrick.remote.tools", level="INFO") as logs:
            server = MCPServer("t")
            register(server, lambda ctx: self.s)
            args = dict(marked, verb="wrap", zone="Work", project=PROJECT, thread=THREAD)
            made = asyncio.run(server.call_tool("prepare", args))
            data = json.loads(made.content[0].text)
            self.assertEqual("prepared", data["state"], data)
            op = data["operation_id"]
            asyncio.run(server.call_tool("execute", {"operation_id": op}))
            self.wait(op)
            done = json.loads(asyncio.run(server.call_tool("status", {"operation_id": op})).content[0].text)
        self.assertEqual("saved", done["state"], done)
        self.assertNotIn("WRAPSECRET", "\n".join(logs.output))
        self.assertNotIn("WRAPSECRET", json.dumps(self.w.store.read(op)))
        self.assertNotIn("WRAPSECRET", json.dumps(data) + json.dumps(done))

    def test_the_tool_call_takes_no_memory_or_lock_and_refuses_them_in_words(self):
        from mcp.server.mcpserver import MCPServer
        from tools import register
        server = MCPServer("t")
        register(server, lambda ctx: self.s)
        for extra in ({"memory": {"path": "x.md"}}, {"lock": "held"}):
            args = dict(words(), verb="wrap", zone="Work", project=PROJECT, thread=THREAD, **extra)
            data = json.loads(asyncio.run(server.call_tool("prepare", args)).content[0].text)
            self.assertEqual("not_prepared", data.get("error"), data)
        self.assertEqual([], list(self.w.store.all()))

    def test_the_wrap_is_not_a_second_path_for_the_reads_or_the_reach(self):
        self.assertEqual(set(wrap_verb.TAKES), set(writes.TAKES["wrap"]))
        for banned in ("memory", "lock", "file", "key", "confirm", "destination", "op", "via"):
            self.assertNotIn(banned, writes.FIELDS)
            self.assertNotIn(banned, wrap_verb.TAKES)


if __name__ == "__main__":
    unittest.main()
