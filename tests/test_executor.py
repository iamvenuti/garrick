"""One way to run an action (#344): page_action.py's command line for a session,
the one page request every caller ends on, and the caller named in the log and
the record. Run in a workspace the installer made, with the build spawn mocked:
no build runs, and no real jobs folder is written.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import test_scaffold_manage as base  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
pa = base.pa
SKILLS = REPO / "template" / "System" / "skills"


class ExecutorCase(base.ManageCase):
    def setUp(self):
        super().setUp()
        self.jobs = self.base / "jobs"
        os.environ["GARRICK_JOBS_DIR"] = str(self.jobs)          # undone with the rest of the environment, as Installed's patch stops
        self.builder = self.root / "System" / "status" / "status.py"
        self.assertTrue(self.builder.is_file(), "the installer puts the status page in place")
        self.lib = pa.prefs().lib(self.root)
        self.build = [sys.executable, str(self.builder), "--workspace", str(self.root), "--same-flags",
                      "--reuse-check", "600", "--settle", "10"]

    def session(self, *args, via=None):
        """page_action.py's main(), as a session runs it: the exit code, what it
        printed, what it printed as an error, and every build it started."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(self.lib, "detach", return_value=True) as spawn, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pa.main(["--workspace", str(self.root), *args] + (["--via", via] if via else []))
        return code, out.getvalue(), err.getvalue(), [c.args[0] for c in spawn.call_args_list]

    def log(self):
        return (self.jobs / "page-actions.log").read_text(encoding="utf-8").splitlines()

    def records(self):
        return [json.loads(line) for line in (self.jobs / "operations.jsonl").read_text(encoding="utf-8").splitlines()]

    def head(self):
        return self.git("log", "-1", "--format=%s").stdout.strip()


class TestTheCommandLine(ExecutorCase):
    def test_a_park_is_the_same_action_as_the_buttons(self):
        code, out, err, spawned = self.session("park", "--zone", "Work", "--project", "Acme", "--thread", "Freight")
        self.assertEqual((0, ""), (code, err))
        self.assertEqual("Acme, Freight is parked", out.strip())              # the sentence the toast says
        self.assertIn("status: parked", self.freight.read_text(encoding="utf-8"))
        self.assertEqual("Acme, Freight: parked", self.head())                 # committed, through the wall check
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertEqual([self.build], spawned)                                # and the page asked for, once
        self.assertEqual(0, self.session("wake", "--zone", "Work", "--project", "Acme", "--thread", "Freight")[0])
        self.assertIn("status: active", self.freight.read_text(encoding="utf-8"))

    def test_a_new_thread_and_a_new_project(self):
        code, out, err, spawned = self.session("new-thread", "--zone", "Work", "--project", "Acme", "--name", "Renewal")
        self.assertEqual((0, ""), (code, err))
        self.assertTrue((self.work / "Acme" / "Threads" / "Renewal" / "Renewal.md").is_file())
        self.assertEqual("Acme: new thread Renewal", self.head())
        self.assertEqual([self.build], spawned)
        code, out, err, spawned = self.session("new-project", "--zone", "Work", "--name", "Birch", "--party", "birch",
                                               "--thread", "Launch Plan")
        self.assertEqual((0, ""), (code, err))
        self.assertTrue((self.work / "Birch" / "Threads" / "Launch Plan" / "Launch Plan.md").is_file())
        self.assertEqual("New project Birch (birch), first thread Launch Plan", self.head())
        self.assertEqual([self.build], spawned)

    def test_a_rename_a_delete_and_the_undo_it_offers(self):
        self.assertEqual(0, self.session("rename", "--zone", "Work", "--project", "Acme", "--thread", "Freight",
                                         "--to", "Lanes")[0])
        self.assertTrue((self.work / "Acme" / "Threads" / "Lanes" / "Lanes.md").is_file())
        code, out, err, spawned = self.session("delete", "--zone", "Work", "--project", "Acme", "--thread", "Lanes")
        self.assertEqual((0, []), (code, spawned))                             # the first form only says what would go
        self.assertTrue((self.work / "Acme" / "Threads" / "Lanes").is_dir())
        code, out, err, spawned = self.session("delete", "--zone", "Work", "--project", "Acme", "--thread", "Lanes",
                                               "--confirm", "Lanes")
        self.assertEqual((0, [self.build]), (code, spawned))
        self.assertFalse((self.work / "Acme" / "Threads" / "Lanes").exists())
        commit = out.split("--commit ")[1].split()[0]
        self.assertIn("To undo: python3 System/status/page_action.py undo --zone Work", out)
        code, out, err, spawned = self.session("undo", "--zone", "Work", "--commit", commit)
        self.assertEqual((0, [self.build]), (code, spawned), err)
        self.assertTrue((self.work / "Acme" / "Threads" / "Lanes" / "Lanes.md").is_file())

    def test_a_todo_line_is_ticked_by_its_words(self):
        code, out, err, spawned = self.session("todo-done", "--zone", "Work", "--line", "send the lanes")
        self.assertEqual((0, "Done: send the lanes", [self.build]), (code, out.strip(), spawned), err)
        self.assertRegex((self.work / "Todo.md").read_text(encoding="utf-8"),
                         r"- \[x\] \[\[Freight\]\]: send the lanes ✅ \d{4}-\d\d-\d\d")
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        code, out, err, spawned = self.session("todo-undo", "--zone", "Work", "--line", "send the lanes")
        self.assertEqual((0, "Reopened: send the lanes", [self.build]), (code, out.strip(), spawned), err)
        self.assertEqual(0, self.session("todo-add", "--zone", "Work", "--text", "Book the room",
                                         "--target", "Acme/Freight")[0])
        self.assertEqual(0, self.session("todo-date", "--zone", "Work", "--line", "Book the room", "--date", "2026-12-01")[0])
        self.assertIn("Book the room 📅 2026-12-01", (self.work / "Todo.md").read_text(encoding="utf-8"))

    def test_a_line_that_nothing_or_two_lines_say_is_refused_and_nothing_is_written(self):
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text(encoding="utf-8").replace(
            "## Inbox\n", "## Inbox\n\n- [ ] Chase Dana about lanes\n- [ ] Chase Dana about rates\n", 1), encoding="utf-8")
        self.commit("two Dana lines")
        before = todo.read_bytes()
        for line, why in (("chase dana", "2 lines say that in Work: say more of the line"),
                          ("order the pallets", "no open line says that in Work"), ("  ", "no line given")):
            code, out, err, spawned = self.session("todo-done", "--zone", "Work", "--line", line)
            self.assertEqual((1, "", []), (code, out, spawned), line)
            self.assertIn(why, err)
        self.assertEqual(before, todo.read_bytes())
        self.assertEqual("two Dana lines", self.head())

    def test_a_zone_is_always_named(self):
        code, out, err, spawned = self.session("park", "--project", "Acme", "--thread", "Freight")
        self.assertEqual((1, "no zone given: say which, with --zone\n", []), (code, err, spawned))
        self.assertNotIn("status: parked", self.freight.read_text(encoding="utf-8"))

    def test_a_refusal_writes_nothing_and_asks_for_nothing(self):
        code, out, err, spawned = self.session("new-thread", "--zone", "Work", "--project", "Acme", "--name", "Pricing")
        self.assertEqual((1, []), (code, spawned))                             # taken: scaffold.py's own words
        self.assertTrue(err.strip())
        self.assertEqual(1, self.session("wake", "--zone", "Work", "--project", "Acme", "--thread", "Freight")[0])
        self.assertEqual("", self.git("status", "--porcelain").stdout)

    def test_the_json_form_is_still_there_for_the_verbs_with_no_options(self):
        request = json.dumps({"verb": "stack"})
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(request)), contextlib.redirect_stdout(out):
            code = pa.main(["--workspace", str(self.root), "--via", "session"])
        self.assertEqual(0, code)
        self.assertTrue(json.loads(out.getvalue())["ok"])


class TestWhatTheExecutorRefuses(ExecutorCase):
    """Review of #344: it fails closed where scaffold.py would ask or where a party is not the zone's."""

    def test_a_name_that_does_not_say_how_it_is_said_is_asked_about_and_nothing_is_written(self):
        code, out, err, spawned = self.session("new-project", "--zone", "Work", "--name", "Q4 Planning", "--party",
                                               "acme", "--thread", "Kickoff")
        self.assertEqual((1, "", []), (code, out, spawned))
        self.assertIn("Q4 Planning does not say how it is said", err)
        self.assertFalse((self.work / "Q4 Planning").exists())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        code, out, err, spawned = self.session("new-thread", "--zone", "Work", "--project", "Acme", "--name", "Q4 Review")
        self.assertEqual((1, []), (code, spawned))
        self.assertFalse((self.work / "Acme" / "Threads" / "Q4 Review").exists())

    def test_with_the_spoken_form_it_is_made_and_committed_with_it(self):
        code, out, err, spawned = self.session("new-project", "--zone", "Work", "--name", "Q4 Planning", "--party", "acme",
                                               "--thread", "Kickoff", "--spoken", "fourth quarter planning")
        self.assertEqual((0, ""), (code, err))
        self.assertIn("spoken: fourth quarter planning", (self.work / "Q4 Planning" / "Q4 Planning.md").read_text())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        code, out, err, spawned = self.session("new-thread", "--zone", "Work", "--project", "Acme", "--name", "Q4 Review",
                                               "--spoken", "fourth quarter review")
        self.assertEqual((0, ""), (code, err))
        self.assertIn("spoken: fourth quarter review", (self.work / "Acme" / "Threads" / "Q4 Review" / "Q4 Review.md").read_text())
        self.assertEqual("", self.git("status", "--porcelain").stdout)

    def test_a_party_of_another_zone_is_refused(self):
        ctx = self.root / "System" / "context.md"
        ctx.write_text(ctx.read_text().replace("\n## Walls", "| Marco | own | Personal | `personal` |  |\n\n## Walls", 1))
        for args in (("--zone", "Work", "--name", "Taxes", "--party", "personal", "--thread", "Return"),):
            code, out, err, spawned = self.session("new-project", *args)
            self.assertEqual((1, []), (code, spawned))
            self.assertIn("Marco is a party of Personal, not of Work", err)
        self.assertFalse((self.work / "Taxes").exists())
        self.assertEqual("", self.git("status", "--porcelain").stdout)

    def test_the_page_reply_to_a_click_has_no_built_after_a_refusal(self):
        """"It rebuilds now, try again" is only true if the host rebuilds: a refusal leaves `built` out."""
        with mock.patch.object(self.lib, "detach", return_value=True) as spawn:
            out, _, _ = pa.perform(self.root, {"verb": "wake", "zone": "Work", "project": "Acme", "thread": "Pricing"},
                                   pa.ops_lib(self.root))
        self.assertEqual((False, False, 0), (out["ok"], "built" in out, spawn.call_count))

    def test_the_page_does_not_close_a_click_with_the_ask_reply(self):
        text = (REPO / "extras" / "status" / "status.py").read_text(encoding="utf-8")
        self.assertIn("||(q.op?null:running(q.zone)));", text)


class TestOnePageRequest(ExecutorCase):
    def perform(self, req, via="page"):
        with mock.patch.object(self.lib, "detach", return_value=True) as spawn:
            out, _, _ = pa.perform(self.root, req, pa.ops_lib(self.root), via=via)
        return out, [c.args[0] for c in spawn.call_args_list]

    def park(self, thread="Freight"):
        return {"verb": "park", "zone": "Work", "project": "Acme", "thread": thread}

    def test_a_saved_action_asks_once_after_the_commit_and_says_so(self):
        seen = []
        real = pa.ask_for_page

        def asks(ws):
            seen.append((self.head(), self.git("status", "--porcelain").stdout))     # what the build would read
            return real(ws)
        with mock.patch.object(pa, "ask_for_page", asks):
            out, spawned = self.perform(self.park())
        self.assertEqual([("Acme, Freight: parked", "")], seen)                # after the commit, nothing left over
        self.assertEqual([self.build], spawned)
        self.assertTrue(out["ok"] and out["built"] is True)

    def test_a_refusal_a_repeat_and_a_read_ask_for_nothing(self):
        self.assertEqual(1, len(self.perform(self.park())[1]))
        wake = {"verb": "wake", "zone": "Work", "project": "Acme", "thread": "Pricing"}
        out, spawned = self.perform(wake)                                      # active already
        self.assertEqual((False, False, []), (out["ok"], "built" in out, spawned))     # the host rebuilds, as the refusal says
        out, spawned = self.perform({"verb": "stack"})
        self.assertEqual(([], False), (spawned, "built" in out))               # a read has no say in it
        out, spawned = self.perform({"verb": "delete", "zone": "Work", "project": "Acme", "thread": "Pricing"})
        self.assertEqual(([], False), (spawned, out.get("built") is True))      # the first form of a delete
        out, spawned = self.perform({"verb": "park", "zone": "Work", "project": "Acme", "thread": "Freight",
                                     "op": "a19f3c80"})
        self.assertEqual((False, []), ("built" in out, spawned))

    def test_a_burst_asks_the_same_settled_build_each_time_so_the_builder_makes_one_page(self):
        for thread in ("Pricing", "Freight"):
            out, spawned = self.perform(self.park(thread))
            self.assertEqual([self.build], spawned)
        for flag in ("--settle", "--same-flags"):
            self.assertIn(flag, self.build)
        self.assertEqual("10", self.build[self.build.index("--settle") + 1])

    def test_a_verb_the_page_does_not_build_for_says_nothing_of_it(self):
        out, spawned = self.perform({"verb": "settings", "launchers": ["note"], "default": "note"})
        self.assertEqual(([], False), (spawned, "built" in out))                # the app rebuilds after it, as it did

    def test_without_the_status_page_a_session_acts_as_it_did(self):
        self.builder.unlink()
        code, out, err, spawned = self.session("park", "--zone", "Work", "--project", "Acme", "--thread", "Freight")
        self.assertEqual((0, "Acme, Freight is parked", ""), (code, out.strip(), err))
        self.assertEqual([], spawned)
        self.assertEqual("Acme, Freight: parked", self.head())
        reply, spawned = self.perform(self.park("Pricing"))
        self.assertTrue(reply["ok"])
        self.assertNotIn("built", reply)                                        # nothing was asked, so the app rebuilds as before

    def test_a_garrick_lib_that_cannot_say_how_asks_for_nothing(self):
        with mock.patch.object(self.lib, "status_command", None):
            out, spawned = self.perform(self.park())
        self.assertTrue(out["ok"])
        self.assertEqual(([], False), (spawned, "built" in out))

    def test_the_build_the_page_asks_for_is_not_asked_a_second_time_by_scaffold(self):
        """scaffold.py is told the caller builds the page: one request, made in one place."""
        seen = []
        real = pa.subprocess.run

        def spy(*a, **kw):
            seen.append(kw["env"].get("GARRICK_CALLER_BUILDS_PAGE"))
            return real(*a, **kw)
        with mock.patch.object(pa.subprocess, "run", spy):
            self.perform(self.park())
        self.assertEqual(["1"], seen)


class TestTheCallerIsNamed(ExecutorCase):
    def test_every_record_names_its_caller(self):
        ops = pa.ops_lib(self.root)
        self.session("park", "--zone", "Work", "--project", "Acme", "--thread", "Freight")           # session
        with mock.patch.object(self.lib, "detach", return_value=True):
            pa.perform(self.root, {"verb": "wake", "zone": "Work", "project": "Acme", "thread": "Freight"}, ops, via="ask")
            pa.perform(self.root, {"verb": "park", "zone": "Work", "project": "Acme", "thread": "Pricing"}, ops, via="page")
        queued = [r for r in self.records() if r["state"] == "queued"]
        self.assertEqual(["session", "ask", "page"], [r["via"] for r in queued])
        self.assertEqual(["park", "wake", "park"], [r["verb"] for r in queued])

    def test_the_log_ends_each_line_with_the_caller(self):
        self.session("park", "--zone", "Work", "--project", "Acme", "--thread", "Freight")
        self.session("wake", "--zone", "Work", "--project", "Acme", "--thread", "Pricing")           # refused: active already
        with mock.patch("sys.stdin", io.StringIO(json.dumps({"verb": "stack"}))), \
                contextlib.redirect_stdout(io.StringIO()):
            pa.main(["--workspace", str(self.root)])                                                  # a read: no line
        with mock.patch("sys.stdin", io.StringIO(json.dumps({"verb": "wake", "zone": "Work", "project": "Acme",
                                                              "thread": "Freight"}))), \
                mock.patch.object(self.lib, "detach", return_value=True), contextlib.redirect_stdout(io.StringIO()):
            pa.main(["--workspace", str(self.root)])                                                  # as the app sends it
        lines = self.log()
        self.assertEqual(4, len(lines), lines)         # the stack is read, and a read is logged too
        self.assertRegex(lines[0], r"  ->  ok: Acme, Freight is parked  \(session\)$")
        self.assertRegex(lines[1], r"  ->  refused: .*  \(session\)$")
        self.assertRegex(lines[2], r"^\S+ \S+  stack  ->  ok: .*  \(page\)$")
        self.assertRegex(lines[3], r"  ->  ok: Acme, Freight is awake again  \(page\)$")

    def test_an_unknown_caller_is_not_recorded(self):
        with mock.patch.object(self.lib, "detach", return_value=True):
            pa.perform(self.root, {"verb": "park", "zone": "Work", "project": "Acme", "thread": "Freight"},
                       pa.ops_lib(self.root), via="somebody")
        self.assertNotIn("via", self.records()[0])

    def test_an_older_operations_py_is_called_as_it_always_was(self):
        calls = []

        class Old:
            OPS = {}

            @staticmethod
            def start(folder, req, now=None):
                calls.append(req["verb"])
                return None, None
        self.assertEqual((None, None), pa.start_record(Old, {"verb": "park"}, "ask"))
        self.assertEqual(["park"], calls)


class TestTheAppFollowsEveryCaller(unittest.TestCase):
    """The Mac app and the Obsidian plugin, read as source: they run no Python here."""

    def setUp(self):
        self.swift = (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")
        self.plugin = (REPO / "extras" / "status" / "obsidian" / "main.js").read_text(encoding="utf-8")

    def test_the_app_does_not_rebuild_after_a_reply_that_settled_the_page(self):
        self.assertIn('if self.rebuilds(request) && reply["built"] == nil { self.freshen(force: true) }', self.swift)
        self.assertIn("if (this.rebuilds(request) && said.built === undefined) this.rebuild(true);", self.plugin)

    def test_an_ask_action_is_handed_to_the_page_as_a_click_is(self):
        self.assertIn('let ran = out["acted"] as? [[String: Any]] ?? []', self.swift)
        self.assertIn("self.acted(request, reply, toasting: false)", self.swift)
        self.assertIn("func acted(_ request: [String: Any], _ said: [String: Any], toasting: Bool = true)", self.swift)
        # the same call that hands a button's reply to the page
        self.assertIn("window.GarrickActed&&window.GarrickActed(a[0],a[1])", self.swift)

    def test_the_box_rebuilds_only_where_a_reply_has_not_settled_the_page(self):
        self.assertIn('let settled = !ran.isEmpty && ran.allSatisfy { ($0["reply"] as? [String: Any])?["built"] != nil }',
                      self.swift)
        self.assertIn("if !settled && lines.count >", self.swift)


class TestTheSkillsDegrade(unittest.TestCase):
    def setUp(self):
        self.threads = (SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8")
        self.todo = (SKILLS / "todo" / "SKILL.md").read_text(encoding="utf-8")

    def flat(self, text):
        return " ".join(text.split())

    def test_the_threads_skill_runs_each_verb_through_the_executor(self):
        for command in ("page_action.py park --zone", "page_action.py new-project --zone", "page_action.py new-thread --zone",
                        "page_action.py rename --zone", "page_action.py delete --zone", "page_action.py undo --zone",
                        "page_action.py unstack --zone", "page_action.py todo-done --zone"):
            self.assertIn(command, self.threads)
        self.assertIn("python3 System/status/page_action.py todo-done", self.todo)

    def test_each_one_says_what_to_do_without_the_status_page(self):
        flat = self.flat(self.threads)
        self.assertIn("**Check for it first**: `test -f System/status/page_action.py`", flat)
        self.assertIn("each section's steps below are the way, exactly as before", flat)
        for fallback in ("python3 System/tools/scaffold.py park --zone", "python3 System/tools/scaffold.py project --zone",
                         "python3 System/tools/scaffold.py thread --zone", "python3 System/tools/scaffold.py rename --zone",
                         "python3 System/tools/scaffold.py delete --zone"):
            self.assertIn(fallback, self.threads)
        self.assertIn("Without the status page", self.todo)
        self.assertIn("edit the line by hand", self.flat(self.todo))
        self.assertIn("Without the status page, edit the line by hand and let step 12 commit it.", flat)

    def test_nothing_the_executor_does_is_done_by_hand_beside_it(self):
        flat = self.flat(self.threads)
        self.assertIn("do not also run `scaffold.py`, commit or `unstack` by hand for them: it has done all three", flat)
        self.assertIn("**Where `System/status/page_action.py` exists, tick through it, before appending anything**", flat)

    def test_the_skills_stay_harness_neutral(self):
        for text in (self.threads, self.todo):
            for word in ("Claude Code", "Codex", "CLAUDE.md"):
                self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
