"""The ask preview, extras/status/ask.py, against a fictional workspace. Offline:
no model is called. A stand-in `claude` on PATH answers in stream-json where a
test needs the warm session itself.

    python3 -m unittest discover -s tests

The session proposes; ask.py checks each proposal against the workspace list
and runs it through page_action.perform(), so the box can do what a page
button can and nothing more, and keeps the same record of it.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import thread_note, write  # noqa: E402
from test_page_action import ActionCase, git  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "extras" / "status" / "ask.py"


def _load():
    spec = importlib.util.spec_from_file_location("garrick_ask", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ask = _load()

# A stand-in for `claude -p --input-format stream-json`: each user message gets
# the next answer from FAKE_ANSWERS, counted across every process started, with
# the session's running cost, and a plain answer once they run out. Its
# arguments go to FAKE_ARGS; each process adds a line to FAKE_ARGS.procs, its
# pid, how it was run and its environment, and each message it is sent to
# FAKE_ARGS.msgs with its pid. An answer that is null is the error Claude
# reports when the session's budget is spent; one that is a number takes that
# many seconds, then answers plainly.
FAKE_CLAUDE = textwrap.dedent("""\
    #!%s
    import json, os, sys, time
    open(os.environ["FAKE_ARGS"], "w").write(json.dumps(sys.argv[1:]))
    with open(os.environ["FAKE_ARGS"] + ".procs", "a") as f:
        f.write(json.dumps({"pid": os.getpid(), "run": sys.argv[0], "argv": sys.argv[1:], "env": dict(os.environ)}) + "\\n")
    answers = json.load(open(os.environ["FAKE_ANSWERS"]))
    n = 0
    for line in sys.stdin:
        msg = json.loads(line)
        with open(os.environ["FAKE_ARGS"] + ".seen", "a") as f:
            f.write(json.dumps(msg["message"]["content"]) + "\\n")
        with open(os.environ["FAKE_ARGS"] + ".msgs", "a") as f:
            f.write(json.dumps({"pid": os.getpid(), "content": msg["message"]["content"]}) + "\\n")
        seen = len(open(os.environ["FAKE_ARGS"] + ".seen").read().splitlines())
        n += 1
        print(json.dumps({"type": "assistant", "message": {"content": []}}), flush=True)
        answer = answers[seen - 1] if seen <= len(answers) else '{"say": "ok", "do": []}'
        if isinstance(answer, (int, float)):
            time.sleep(answer)
            answer = '{"say": "Late.", "do": []}'
        if answer is None:
            print(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "num_turns": 1,
                              "total_cost_usd": 0.01 * n}), flush=True)
            continue
        print(json.dumps({"type": "result", "subtype": "success", "result": answer, "num_turns": 1,
                          "total_cost_usd": 0.01 * n, "usage": {"input_tokens": 100, "output_tokens": 20}}), flush=True)
    """) % sys.executable


class AskCase(ActionCase):
    def setUp(self):
        super().setUp()
        write(self.root / "System" / "garrick-flags.json", json.dumps({"ask": True}))
        self.names = ask.scan(self.root)
        # All of it: a server run in a thread here changes this process's own
        # environment, as it does its own (the marker, PATH, no CMUX_*).
        self._saved = dict(os.environ)
        os.environ["GARRICK_CMUX"] = str(self.root / "no-cmux")        # whatever this Mac has: no cmux, so no desk

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)
        super().tearDown()


class TestScan(AskCase):
    def test_live_projects_and_threads(self):
        write(self.work / "Acme Review" / "Threads" / "Launch Video" / "Launch Video.md",
              thread_note("Acme Review", "Launch Video", status="parked"))
        write(self.work / "Acme Review" / "Threads" / "Old" / "Old.md", thread_note("Acme Review", "Old", status="done"))
        write(self.work / "_template" / "_template.md", "---\nstatus: active\n---\n")
        names = ask.scan(self.root)
        self.assertEqual(["Personal", "Work"], sorted(names))
        self.assertEqual(["Acme Review", "Birch Entry"], sorted(names["Work"]))
        self.assertEqual({"Launch Video": "parked", "Pricing": "active"}, names["Work"]["Acme Review"]["threads"])
        text = ask.render(names)
        self.assertIn("- Acme Review [active] threads: Launch Video (parked); Pricing", text)

    def test_the_shortest_unique_name(self):
        self.assertEqual("Pricing", ask.spoken(self.names, "Work", "Acme Review", "Pricing"))
        self.assertEqual("Acme Review", ask.spoken(self.names, "Work", "Acme Review", None))
        write(self.work / "Birch Entry" / "Threads" / "Pricing" / "Pricing.md", thread_note("Birch Entry", "Pricing"))
        names = ask.scan(self.root)
        self.assertEqual("Acme Review, Pricing", ask.spoken(names, "Work", "Acme Review", "Pricing"))


class TestProposals(AskCase):
    """What the session proposes, checked before anything runs."""

    def test_parse(self):
        self.assertEqual(("Done.", []), ask.parse('{"say": "Done.", "do": []}'))
        self.assertEqual(("x", [{"verb": "open"}]), ask.parse('```json\n{"say": "x", "do": [{"verb": "open"}]}\n```'))
        self.assertEqual(("", []), ask.parse('{"do": "everything"}'))
        for bad in ("I opened it.", '{"say": "x", "do": [}', "[1, 2]"):
            with self.assertRaises(ask.Bad, msg=bad):
                ask.parse(bad)

    def test_open_comes_back_as_a_folder(self):
        kind, item = ask.proposal({"verb": "open", "zone": "Work", "project": "Acme Review", "thread": "Pricing", "app": "claude"},
                                  self.names, self.root)
        self.assertEqual("launch", kind)
        self.assertEqual({"app": "claude", "folder": str(self.root / "Zones/Work/Acme Review/Threads/Pricing"),
                          "phrase": "open Pricing", "name": "Pricing"}, item)
        self.assertEqual("", ask.proposal({"verb": "open", "zone": "Work", "project": "Birch Entry"}, self.names, self.root)[1]["app"])

    def test_park_and_add_become_page_actions(self):
        self.assertEqual(("act", {"verb": "park", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md"}),
                         ask.proposal({"verb": "park", "zone": "Work", "project": "Acme Review", "thread": "Pricing"},
                                      self.names, self.root))
        self.assertEqual(("act", {"verb": "park", "zone": "Work", "project": "Acme Review"}),     # all of it, threads and all
                         ask.proposal({"verb": "park", "zone": "Work", "project": "Acme Review"}, self.names, self.root))
        self.assertEqual(("act", {"verb": "todo-add", "zone": "Work", "text": "Call Dana", "target": "Acme Review/Pricing",
                                  "date": "2026-10-09"}),
                         ask.proposal({"verb": "todo-add", "zone": "Work", "text": " Call Dana ", "project": "Acme Review",
                                       "thread": "Pricing", "date": "2026-10-09"}, self.names, self.root))

    def test_an_app_switched_off_in_settings(self):
        a = {"verb": "open", "zone": "Work", "project": "Acme Review", "app": "codex"}
        settings = self.root / "System" / "garrick-settings.json"
        write(settings, json.dumps({"launchers": {"note": True, "codex": False}, "default": "note"}))
        with self.assertRaisesRegex(ask.Bad, "Codex is switched off in Settings"):
            ask.proposal(a, self.names, self.root)
        self.assertEqual("launch", ask.proposal(dict(a, app="cmux"), self.names, self.root)[0])     # left out: on
        self.assertEqual("launch", ask.proposal(dict(a, app=""), self.names, self.root)[0])         # the app picks
        write(settings, json.dumps({"launchers": ["note", "claude"]}))
        with self.assertRaisesRegex(ask.Bad, "cmux is switched off"):
            ask.proposal(dict(a, app="cmux"), self.names, self.root)

    def test_refused(self):
        for a in ({"verb": "run", "job": "whats-open"}, {"verb": "shutdown"}, {"verb": "settings", "launchers": []},
                  {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "0" * 16}, {"verb": "rm", "zone": "Work"},
                  {"verb": "open", "zone": "Work", "project": "Nope"},
                  {"verb": "open", "zone": "Work", "project": "Acme Review", "thread": "Nope"},
                  {"verb": "open", "zone": "Elsewhere", "project": "Acme Review"},
                  {"verb": "open", "zone": "Work", "project": "Acme Review", "app": "terminal"},
                  {"verb": "open", "zone": "Work", "thread": "Pricing"},
                  {"verb": "todo-add", "zone": "Work", "text": ""},
                  {"verb": "todo-add", "zone": "Work", "text": "x", "date": "tomorrow"},
                  {"verb": "open", "zone": "Work", "project": "../Personal"},
                  "open Pricing", None):
            with self.assertRaises(ask.Bad, msg=a):
                ask.proposal(a, self.names, self.root)


class FakeSession:
    remembers = True
    started = 0.0

    def __init__(self, *answers):
        self.answers, self.seen = list(answers), []

    def fresh(self):
        return not self.seen

    def ready(self):
        pass

    def turn(self, text, **kw):
        self.seen.append(text)
        return self.answers.pop(0), {"input_tokens": 1}


class TestCarryOut(AskCase):
    """Proposals run through page_action.perform(), each logged as the page's are."""

    def test_actions_run_and_are_logged(self):
        session = FakeSession(json.dumps({"say": "Added it, and parked Pricing.", "do": [
            {"verb": "todo-add", "zone": "Work", "text": "Call Dana", "project": "Acme Review"},
            {"verb": "park", "zone": "Work", "project": "Acme Review", "thread": "Pricing"},
            {"verb": "open", "zone": "Work", "project": "Birch Entry", "app": "cmux"},
            {"verb": "run", "job": "whats-open"}]}))
        out = ask.Asker(self.root, session).ask("add call Dana to Acme, park Pricing, open Birch, run the job")
        self.assertEqual("Added it, and parked Pricing.", out["say"])
        self.assertEqual(["Added to Inbox: Call Dana", "Acme Review, Pricing is parked", "Opening Birch Entry in Cmux",
                          "Refused: not something the box does: 'run'"], out["done"])
        self.assertFalse(out["ok"])
        self.assertEqual([{"app": "cmux", "folder": str(self.root / "Zones/Work/Birch Entry"), "phrase": "open Birch Entry",
                           "name": "Birch Entry"}], out["launch"])
        self.assertIn("- [ ] [[Acme Review]]: Call Dana\n", (self.work / "Todo.md").read_text())
        self.assertIn("\nstatus: parked\n", self.thread.read_text())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        log = (self.jobs / "page-actions.log").read_text().splitlines()
        self.assertEqual(2, len(log))
        self.assertTrue(all(line.endswith("(ask)") for line in log))

    def test_what_the_session_is_told(self):
        session = FakeSession('{"say": "Two projects.", "do": []}', '{"say": "Parked.", "do": '
                              '[{"verb": "park", "zone": "Work", "project": "Acme Review", "thread": "Pricing"}]}',
                              '{"say": "Still two.", "do": []}')
        asker = ask.Asker(self.root, session)
        asker.ask("what's open", today=dt.date(2026, 10, 5))
        self.assertIn("<today>2026-10-05</today>\n<workspace>\nPersonal:\nWork:\n- Acme Review [active] threads: Pricing", session.seen[0])
        self.assertTrue(session.seen[0].endswith("<request>\nwhat's open\n</request>"))
        asker.ask("park Pricing")
        self.assertIn("<workspace unchanged/>", session.seen[1])
        asker.ask("and now?")
        self.assertIn("threads: Pricing (parked)", session.seen[2])                    # the list changed, so it is sent again
        self.assertIn("<last-results>\nAcme Review, Pricing is parked\n</last-results>", session.seen[2])

    def test_the_flag_off_asks_nothing(self):
        write(self.root / "System" / "garrick-flags.json", json.dumps({"ask": False}))
        session = FakeSession()
        out = ask.Asker(self.root, session).ask("open Pricing")
        self.assertFalse(out["ok"])
        self.assertIn("preview feature, and it is off", out["say"])
        self.assertEqual([], session.seen)

    def test_actions_need_only_the_ask_flag(self):
        write(self.root / "System" / "garrick-flags.json", json.dumps({"ask": True}))
        session = FakeSession(json.dumps({"say": "Parked.", "do": [
            {"verb": "park", "zone": "Work", "project": "Acme Review", "thread": "Pricing"},
            {"verb": "open", "zone": "Work", "project": "Acme Review"}]}))
        out = ask.Asker(self.root, session).ask("park Pricing, then open Acme")
        self.assertEqual(["Acme Review, Pricing is parked", "Opening Acme Review"], out["done"])
        self.assertIn("\nstatus: parked\n", self.thread.read_text())

    def test_the_ask_flag_switched_off_mid_turn(self):
        write(self.root / "System" / "garrick-flags.json", json.dumps({}))
        out = ask.Asker(self.root).carry_out("Parked.", [{"verb": "park", "zone": "Work", "project": "Acme Review",
                                                          "thread": "Pricing"}], self.names)
        self.assertFalse(out["ok"])
        self.assertIn("\nstatus: active\n", self.thread.read_text())

    def test_a_fault_in_an_action_is_a_refusal(self):
        pa = ask.page_action()
        real = pa.act

        def broken(ws, req, today=None):
            raise OSError("the disk went away")
        pa.act = broken
        try:
            out = ask.Asker(self.root).carry_out("Parked.", [{"verb": "park", "zone": "Work", "project": "Acme Review",
                                                              "thread": "Pricing"}], self.names)
        finally:
            pa.act = real
        self.assertEqual(["Refused: OSError: the disk went away"], out["done"])
        self.assertTrue((self.jobs / "page-actions.log").read_text().rstrip().endswith(
            "refused: OSError: the disk went away  (ask)"))

    def test_a_park_the_wall_check_refuses_is_the_rules_sentence_with_nothing_added(self):
        """#172: the box lists a refusal as "Refused: <why>", but a wall's is
        #116's sentence alone, never what the check printed."""
        import check
        pa = ask.page_action()
        line = check.report_staged([check.Finding(check.ERROR, "walls", "Acme Review/Threads/Pricing/Pricing.md",
                                                  "names Birch & Co (`birch`), or one of its people; "
                                                  "a wall stands between acme and birch")])
        hook = self.work / ".git" / "hooks" / "pre-commit"
        write(hook, "#!/bin/sh\ncat >&2 <<'EOF'\n%s\nEOF\nexit 1\n" % line)
        hook.chmod(0o755)
        out = ask.Asker(self.root).carry_out("Parked.", [{"verb": "park", "zone": "Work", "project": "Acme Review",
                                                          "thread": "Pricing"}], self.names)
        self.assertFalse(out["ok"])
        self.assertEqual([pa.ops_lib(self.root).WALL_REFUSAL], out["done"])
        self.assertNotIn("birch", (self.jobs / "page-actions.log").read_text())
        self.assertIn("\nstatus: active\n", self.thread.read_text())

    def test_the_flag_off_from_the_command_line(self):
        os.remove(self.root / "System" / "garrick-flags.json")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = ask.main(["--workspace", str(self.root), "--json", "ask", "open", "Pricing"])
        self.assertEqual(1, code)
        self.assertFalse(json.loads(buf.getvalue())["ok"])
        self.assertFalse(self.jobs.exists())                                         # no server, no socket, no log


class TestAskingAgain(AskCase):
    """#92: the box used to stop waiting while the commit was still running,
    and tell you to ask again. The second turn writes the line from the words
    again, so it need not be the line the first turn wrote."""

    def test_the_wait_covers_the_slowest_request(self):
        import re
        pa = ask.page_action()
        ops = pa.ops_lib()
        self.assertGreaterEqual(ask.ASK_WAIT, 2 * ask.TURN_TIMEOUT + pa.COMMIT_TIMEOUT + pa.GIT_TIMEOUT)
        self.assertEqual((ops.ASK_WAIT, ops.TURN_TIMEOUT), (ask.ASK_WAIT, ask.TURN_TIMEOUT))   # the clock's, #137
        swift = (Path(ask.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")
        app = float(re.search(r"let askWait = ([\d.]+)", swift).group(1))
        self.assertGreaterEqual(app, ask.ASK_WAIT)                  # ask.py's own message comes first
        self.assertGreaterEqual(ops.LOOKBACK, app)                  # and the retry it invites is recognised
        self.assertNotIn("Ask again", swift)                        # neither of them invites the retry
        self.assertNotIn("Ask again", ask.GAVE_UP)
        for said in (ask.GAVE_UP, swift):
            self.assertIn("may still be on its way", said)
            self.assertIn("Todo list", said)

    def test_asking_again_leaves_one_line(self):
        soon = (dt.date.today() + dt.timedelta(days=3)).isoformat()
        line = {"verb": "todo-add", "zone": "Work", "text": "Call Dana about the quote",
                "project": "Acme Review", "thread": "Pricing"}
        again = dict(line, text="call Dana  about the quote.", date=soon)    # the same thing, worded again
        asker = ask.Asker(self.root, FakeSession(json.dumps({"say": "Added it.", "do": [line]}),
                                                 json.dumps({"say": "Added it.", "do": [again]})))
        first = asker.ask("add call Dana about the quote to Pricing")
        self.assertEqual(["Added to Inbox: Call Dana about the quote"], first["done"])
        out = asker.ask("add call Dana about the quote to Pricing")
        self.assertEqual(["Refused: that line is already in the list"], out["done"])
        self.assertFalse(out["ok"])
        self.assertEqual(1, (self.work / "Todo.md").read_text().count("Dana about the quote"))
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())


class TestAskingLater(AskCase):
    """#137: a request asked again past a double click's window goes through
    the same record as the page's clicks, and is asked about, not done again."""

    LINE = {"verb": "todo-add", "zone": "Work", "text": "Call Dana", "project": "Acme Review"}

    def age(self, seconds):
        path = self.jobs / "operations.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        for r in records:
            for k in ("at", "done"):
                if isinstance(r.get(k), (int, float)):
                    r[k] -= seconds
        path.write_text("".join(json.dumps(r) + "\n" for r in records))

    def tick_by_hand(self):
        todo = self.work / "Todo.md"
        write(todo, todo.read_text().replace("- [ ] [[Acme Review]]: Call Dana", "- [x] [[Acme Review]]: Call Dana ✅ 2026-10-05"))
        git(self.work, "commit", "-q", "-am", "ticked by hand")

    def open_lines(self):
        return (self.work / "Todo.md").read_text().count("- [ ] [[Acme Review]]: Call Dana")

    def test_inside_the_window_it_is_answered_once(self):
        session = FakeSession(*[json.dumps({"say": "Added it.", "do": [self.LINE]})] * 2)
        asker = ask.Asker(self.root, session)
        asker.ask("add call Dana to Acme")
        head = git(self.work, "rev-parse", "HEAD")
        out = asker.ask("add call Dana to Acme")
        self.assertEqual(["Added to Inbox: Call Dana"], out["done"])                   # the first one's result
        self.assertEqual(head, git(self.work, "rev-parse", "HEAD"))
        self.assertEqual(1, self.open_lines())

    def test_past_the_window_it_is_asked_and_a_yes_does_it_again(self):
        session = FakeSession(json.dumps({"say": "Added it.", "do": [self.LINE]}),
                              json.dumps({"say": "Added it.", "do": [self.LINE]}),
                              json.dumps({"say": "Adding it again.", "do": [dict(self.LINE, again=True)]}))
        asker = ask.Asker(self.root, session)
        asker.ask("add call Dana to Acme")
        self.tick_by_hand()
        self.age(300)
        head = git(self.work, "rev-parse", "HEAD")
        out = asker.ask("add call Dana to Acme")
        (question,) = out["done"]
        self.assertTrue(question.startswith("The same request was done 5 minutes ago, at "), question)
        self.assertIn(": Added to Inbox: Call Dana. It has not been done again. Do you want it done a second time?", question)
        self.assertEqual((question, False), (out["say"], out["ok"]))                # not the session's "Added it."
        self.assertEqual(head, git(self.work, "rev-parse", "HEAD"))                  # no second edit
        self.assertEqual(0, self.open_lines())
        yes = asker.ask("yes")
        self.assertIn("<last-results>\n%s\n</last-results>" % question, session.seen[2])
        self.assertEqual(["Added to Inbox: Call Dana"], yes["done"])
        self.assertTrue(yes["ok"])
        self.assertEqual(1, self.open_lines())                                       # the second edit, asked for
        log = (self.jobs / "page-actions.log").read_text().splitlines()
        self.assertEqual(3, len(log))                                                # each of the three, as the page's are
        self.assertTrue(log[1].endswith("(ask)") and "The same request was done" in log[1], log[1])

    def test_again_with_no_question_before_it_is_asked_all_the_same(self):
        session = FakeSession(json.dumps({"say": "Added it.", "do": [self.LINE]}),
                              json.dumps({"say": "Adding it again.", "do": [dict(self.LINE, again=True)]}))
        asker = ask.Asker(self.root, session)
        asker.ask("add call Dana to Acme")
        self.tick_by_hand()
        self.age(300)
        out = asker.ask("add call Dana to Acme again")
        self.assertTrue(out["done"][0].startswith("The same request was done"), out["done"])
        self.assertEqual(0, self.open_lines())

    def test_a_different_request_past_the_window_runs(self):
        other = dict(self.LINE, text="Send Dana the deck")
        session = FakeSession(json.dumps({"say": "Added it.", "do": [self.LINE]}),
                              json.dumps({"say": "Added it.", "do": [other]}))
        asker = ask.Asker(self.root, session)
        asker.ask("add call Dana to Acme")
        self.age(300)
        out = asker.ask("add send Dana the deck to Acme")
        self.assertEqual(["Added to Inbox: Send Dana the deck"], out["done"])


class TestHarness(AskCase):
    def test_tier_and_harness_are_checked(self):
        os.environ["GARRICK_ASK_TIER"] = "gpt-9"
        with self.assertRaisesRegex(ask.Bad, "GARRICK_ASK_TIER"):
            ask.session_for(self.root)
        os.environ["GARRICK_ASK_TIER"] = "sonnet"
        os.environ["GARRICK_HARNESS"] = "other"
        with self.assertRaisesRegex(ask.Bad, "GARRICK_HARNESS"):
            ask.session_for(self.root)
        os.environ["GARRICK_HARNESS"] = "codex"
        self.assertIsInstance(ask.session_for(self.root), ask.OnceSession)
        os.environ["GARRICK_HARNESS"] = "claude"
        session = ask.session_for(self.root)
        self.assertEqual("sonnet", session.tier)

    def test_the_claude_session_loads_the_deny_profile(self):
        cli = self.root.parent / "bin" / "claude"
        write(cli, "#!/usr/bin/env node\n")             # the CLI as npm installs it, never a wrapper
        cli.chmod(0o755)
        os.environ["GARRICK_CLAUDE"] = str(cli)
        cmd = ask.ClaudeSession(self.root, "haiku").command()
        self.assertEqual([str(cli), "-p"], cmd[:2])
        for flag, value in (("--model", "haiku"), ("--tools", ""), ("--permission-mode", "default"),
                            ("--settings", str(ask.agent().PROFILE)), ("--setting-sources", "")):
            self.assertEqual(value, cmd[cmd.index(flag) + 1], flag)
        self.assertIn("--no-session-persistence", cmd)
        self.assertIn("--strict-mcp-config", cmd)
        self.assertEqual(ask.BRIEF.read_text(), cmd[cmd.index("--system-prompt") + 1])

    def test_the_cli_is_the_one_continue_finds(self):
        """#261: handoff.find_claude(), never a terminal's wrapper on PATH; GARRICK_CLAUDE wins."""
        os.environ["GARRICK_CLAUDE"] = str(self.root.parent / "no-claude")      # names nothing: looks nowhere else
        self.assertEqual(str(self.root.parent / "no-claude"), ask.claude_binary())
        os.environ.pop("GARRICK_CLAUDE")
        h = ask.handoff()
        real = h.find_claude
        h.find_claude = lambda env=None: None                                   # none found, whatever this Mac has
        try:
            self.assertEqual("claude", ask.claude_binary())
        finally:
            h.find_claude = real

    def test_codex_runs_read_only_with_history(self):
        calls = []
        real = ask.agent().run
        ask.agent().run = lambda tier, prompt, allow=(), cwd=None, job=None: calls.append((tier, prompt, list(allow), job)) or (0, '{"say": "ok", "do": []}')
        try:
            s = ask.OnceSession(self.root, "haiku")
            s.turn("<request>\nfirst\n</request>")
            s.turn("<request>\nsecond\n</request>")
        finally:
            ask.agent().run = real
        self.assertEqual(("haiku", [], "ask"), (calls[0][0], calls[0][2], calls[0][3]))       # nothing allowed: Codex runs read-only
        self.assertIn("<earlier-request>\nfirst\n</earlier-request>", calls[1][1])
        self.assertTrue(calls[1][1].startswith(ask.BRIEF.read_text()))

    def test_codex_runs_in_an_empty_folder_outside_the_workspace(self):
        """Sealed as the Claude sessions are: from there Codex finds no AGENTS.md of the workspace's."""
        seen = []

        def run(tier, prompt, allow=(), cwd=None, job=None):
            seen.append((Path(cwd), sorted(p.name for p in Path(cwd).iterdir())))
            return 0, '{"say": "ok", "do": []}'
        real = ask.agent().run
        ask.agent().run = run
        try:
            s = ask.OnceSession(self.root, "haiku")
            s.turn("<request>\nfirst\n</request>")
            s.turn("<request>\nsecond\n</request>")
        finally:
            ask.agent().run = real
        (one, files), (two, _) = seen
        self.assertEqual([], files)                                                  # empty
        self.assertNotEqual(one, two)                                                # a folder per call
        for home in (one, two):
            self.assertNotIn(self.root.resolve(), [home, *home.parents])             # outside the workspace
            self.assertFalse(home.exists())                                          # removed when it returned

    def test_a_folder_inside_the_workspace_starts_nothing(self):
        inside = self.root / "tmp"
        inside.mkdir()

        def mkdtemp(prefix=""):                                                      # a TMPDIR inside the workspace
            made = inside / (prefix + "x")
            made.mkdir()
            return str(made)
        with mock.patch.object(ask.tempfile, "mkdtemp", mkdtemp):
            with self.assertRaisesRegex(ask.Bad, "inside the workspace"):
                ask.sealed_folder(self.root)
        self.assertEqual([], list(inside.iterdir()))                                 # and it was removed


class StandInCase(AskCase):
    """A stand-in `claude`, named by GARRICK_CLAUDE and first on PATH."""

    def setUp(self):
        super().setUp()
        bin_ = Path(self._tmp.name) / "bin"
        bin_.mkdir()
        fake = bin_ / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        os.environ["PATH"] = str(bin_) + os.pathsep + os.environ.get("PATH", "")
        os.environ["GARRICK_CLAUDE"] = str(fake)          # the CLI it runs, so nothing on this Mac is looked for
        self.fake = fake
        self.args = Path(self._tmp.name) / "args.json"
        self.answers = Path(self._tmp.name) / "answers.json"
        os.environ["FAKE_ARGS"], os.environ["FAKE_ANSWERS"] = str(self.args), str(self.answers)
        self.addCleanup(os.environ.pop, "FAKE_ARGS", None)
        self.addCleanup(os.environ.pop, "FAKE_ANSWERS", None)

    def serve_in_thread(self):
        import threading
        t = threading.Thread(target=ask.serve, args=(self.root,), daemon=True)
        t.start()
        return t


@unittest.skipIf(sys.platform == "win32", "a stand-in executable on PATH")
class TestWarmSession(StandInCase):
    """The warm Claude session, with a stand-in `claude`: two turns, one process, the ledger and the caps."""

    def test_two_turns_one_process_and_the_ledger(self):
        self.answers.write_text(json.dumps(['{"say": "Two projects in Work.", "do": []}',
                                            '{"say": "Parked.", "do": [{"verb": "park", "zone": "Work", '
                                            '"project": "Acme Review", "thread": "Pricing"}]}']))
        asker = ask.Asker(self.root, ask.ClaudeSession(self.root, "haiku"))
        try:
            self.assertEqual("Two projects in Work.", asker.ask("what's open")["say"])
            pid = asker.session.proc.pid
            out = asker.ask("park Pricing")
            self.assertEqual(pid, asker.session.proc.pid)
        finally:
            asker.session.stop()
        self.assertEqual(["Acme Review, Pricing is parked"], out["done"])
        ledger = [json.loads(line) for line in (self.jobs / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual(["ask", "ask"], [e["job"] for e in ledger])
        self.assertEqual([0.01, 0.01], [round(e["cost_usd"], 4) for e in ledger])      # each request's share of the running total
        self.assertEqual(2, len((Path(str(self.args) + ".seen")).read_text().splitlines()))

    def test_a_cap_asks_nothing(self):
        self.answers.write_text(json.dumps([]))
        os.environ["GARRICK_CAP_CALLS_HOUR"] = "1"
        a = ask.agent()
        a.append_ledger(a.ledger_path(), a.ledger_entry(__import__("time").time(), "whats-open", "haiku", {}, 1, 0))
        session = ask.ClaudeSession(self.root, "haiku")
        with self.assertRaisesRegex(ask.Bad, "not asked: 1 calls in the last hour"):
            ask.Asker(self.root, session).ask("open Pricing")
        self.assertIsNone(session.proc)                                               # no process started
        self.assertFalse(self.args.exists())
        self.assertTrue(json.loads((self.jobs / "ledger.jsonl").read_text().splitlines()[-1])["refused"])


    def test_a_spent_budget_starts_a_fresh_session(self):
        self.answers.write_text(json.dumps([None, '{"say": "Fresh.", "do": []}']))
        asker = ask.Asker(self.root, ask.ClaudeSession(self.root, "haiku"))
        try:
            with self.assertRaisesRegex(ask.Bad, "error_max_budget_usd; the next request starts a new session"):
                asker.ask("what's open")
            self.assertIsNone(asker.session.proc)                                  # stopped, not left to refuse
            self.assertEqual("Fresh.", asker.ask("what's open")["say"])
            self.assertIn("<workspace>", (Path(str(self.args) + ".seen")).read_text().splitlines()[1])   # told it all again
        finally:
            asker.session.stop()

    def test_one_server_per_workspace(self):
        import socket
        import threading
        path = ask.sock_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        first = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)          # a server that has the socket already
        first.bind(str(path))
        first.listen(1)
        inode = path.stat().st_ino
        real, ask.SERVE_WAIT = ask.SERVE_WAIT, 0.2
        try:
            with ask.page_action().held(path.with_suffix(".lock").name):
                t = self.serve_in_thread()
                t.join(10)
            self.assertFalse(t.is_alive())                                          # the second left at once
            self.assertEqual(inode, path.stat().st_ino)                             # and left the socket alone
        finally:
            ask.SERVE_WAIT = real
            first.close()

    def test_a_server_that_never_answers(self):
        import socket
        import threading
        import time
        path = ask.sock_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        wedged = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        wedged.bind(str(path))
        wedged.listen(1)

        def hold():
            conn, _ = wedged.accept()
            time.sleep(3)
            conn.close()
        threading.Thread(target=hold, daemon=True).start()
        real, ask.ASK_WAIT = ask.ASK_WAIT, 0.5
        try:
            t0 = time.time()
            out = ask.call(self.root, "status", start=False)
            self.assertLess(time.time() - t0, 2.5)
        finally:
            ask.ASK_WAIT = real
            wedged.close()
        self.assertFalse(out["ok"])
        self.assertIn("did not answer", out["say"])

    def test_a_client_that_leaves_mid_turn(self):
        import socket
        self.answers.write_text(json.dumps(['{"say": "Two projects.", "do": []}']))
        t = self.serve_in_thread()
        try:
            path = ask.sock_path(self.root)
            for _ in range(100):                # the socket is there from bind(), and refuses until listen()
                c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    c.connect(str(path))
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    c.close()
                    __import__("time").sleep(0.05)
            else:
                self.fail("the server never listened")
            c.sendall(b'{"op": "ask", "text": "what\'s open"}\n')
            c.close()                                                               # gone before the answer
            t.join(3)
            out = ask.call(self.root, "status", start=False)
            self.assertIsNotNone(out)                                               # the server carried on
            self.assertTrue(out["session"])
        finally:
            ask.call(self.root, "stop", start=False)
            t.join(10)

    def test_through_the_server(self):
        import contextlib
        import io
        self.answers.write_text(json.dumps(['{"say": "Opening Pricing.", "do": [{"verb": "open", "zone": "Work", '
                                            '"project": "Acme Review", "thread": "Pricing"}]}']))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = ask.main(["--workspace", str(self.root), "--json", "ask", "open", "Pricing"])
        finally:
            with contextlib.redirect_stdout(io.StringIO()):
                ask.main(["--workspace", str(self.root), "stop"])
        self.assertEqual(0, code)
        out = json.loads(buf.getvalue())
        self.assertEqual("Opening Pricing.", out["say"])
        self.assertEqual("open Pricing", out["launch"][0]["phrase"])
        self.assertEqual("command", out["kind"])
        log = (self.jobs / "ask.log").read_text()
        self.assertRegex(log, r"  ask command \d+ ms \{\"input_tokens\": 100, ")      # the time, the op, the ms, the tokens
        self.assertNotIn("Pricing", log)                                             # and no request or answer text (#261)
        self.assertEqual([], list(self.jobs.glob("*.sock")))                         # stopped, and gone

    def test_the_log_keeps_text_only_when_asked(self):
        line = ask.log_line("open Pricing", {"kind": "command", "say": "Opening Pricing.", "done": ["Opening Pricing"],
                                             "ok": True, "ms": 12, "usage": {"input_tokens": 3}})
        self.assertEqual('ask command 12 ms {"input_tokens": 3}', line)
        os.environ[ask.LOG_TEXT] = "1"
        line = ask.log_line("open Pricing", {"kind": "answer", "reset": "wall", "say": "Opening Pricing.", "ms": 12})
        self.assertEqual('ask answer reset 12 ms {}  "open Pricing"  ->  "Opening Pricing." []', line)


class ServerCase(StandInCase):
    """The server in a thread, and what the stand-in's processes were sent."""

    def setUp(self):
        super().setUp()
        self.answers.write_text(json.dumps([]))                 # a plain answer to everything
        self._clock = {k: getattr(ask, k) for k in ("LEASE", "TICK", "IDLE_TICK", "CLEAR_AFTER")}
        self.server = None

    def tearDown(self):
        if self.server is not None and self.server.is_alive():
            ask.call(self.root, "stop", start=False)
            self.server.join(10)
        for k, v in self._clock.items():
            setattr(ask, k, v)
        super().tearDown()

    def up(self):
        """The server, in a thread, once it answers."""
        import time
        self.server = self.serve_in_thread()
        for _ in range(200):
            try:
                if ask.call(self.root, "status", start=False) is not None:
                    return
            except (ConnectionRefusedError, FileNotFoundError):
                pass
            time.sleep(0.05)
        self.fail("the server never listened")

    def op(self, op, text=""):
        return ask.call(self.root, op, text, start=False)

    def procs(self, at_least=1, wait=10.0):
        """Each stand-in process started, in order, once there are this many."""
        import time
        path = Path(str(self.args) + ".procs")
        until = time.time() + wait
        while time.time() < until:
            got = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
            if len(got) >= at_least:
                return got
            time.sleep(0.05)
        self.fail("%d stand-in processes, not %d" % (len(got), at_least))

    def first_message(self, pid):
        path = Path(str(self.args) + ".msgs")
        for line in path.read_text().splitlines():
            m = json.loads(line)
            if m["pid"] == pid:
                return m["content"]
        self.fail("process %d was sent nothing" % pid)

    def kill(self, pid):
        import signal
        import time
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)                                         # dead, for the server's poll() to see

    def gone(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False


@unittest.skipIf(sys.platform == "win32", "a stand-in executable on PATH")
class TestBackgroundSession(ServerCase):
    """#261, slice A: the app keeps the session from launch. It is marked, out
    of cmux's sight, started again if it dies, and stopped when the app goes."""

    def test_the_session_is_marked_and_kept_out_of_cmux(self):
        os.environ.update({"CMUX_SURFACE_ID": "S1", "CMUX_SOCKET_PASSWORD": "pw", "CLAUDECODE": "1"})
        self.up()
        self.assertEqual("Kept.", self.op("keep")["say"])
        (p,) = self.procs()
        self.assertEqual("ask", p["env"].get(ask.MARKER))
        self.assertEqual([], [k for k in p["env"] if k.startswith("CMUX_") or k == "CLAUDECODE"])
        self.assertEqual(str(self.fake), p["run"])                                  # GARRICK_CLAUDE's, never a wrapper
        self.assertIn("--no-session-persistence", p["argv"])                       # no transcript, so in no list
        self.assertTrue(self.op("status")["leased"])

    def test_keep_starts_a_session_and_never_replaces_a_live_one(self):
        ask.CLEAR_AFTER = 1
        self.up()
        self.assertFalse(self.op("status")["leased"])
        self.op("keep")
        (first,) = self.procs()
        __import__("time").sleep(1.2)                           # past the age a request replaces
        self.op("keep")
        self.assertTrue(self.op("status")["session"])
        self.assertEqual([first["pid"]], [p["pid"] for p in self.procs()])         # kept, not replaced
        self.op("ask", "what's open")
        procs = self.procs(2)
        self.assertEqual(2, len(procs))                                           # a request still replaces it
        self.assertTrue(self.gone(first["pid"]))

    def test_a_session_that_dies_is_started_again(self):
        ask.TICK = 0.2
        self.up()
        self.op("keep")
        (first,) = self.procs()
        self.kill(first["pid"])
        second = self.procs(2, wait=5)[1]                       # within a tick, asked for by nobody
        self.assertNotEqual(first["pid"], second["pid"])
        self.kill(second["pid"])
        __import__("time").sleep(1)                             # five ticks
        self.assertEqual(2, len(self.procs()))                  # once between keeps, never every tick
        self.op("keep")                                         # and the app's next keep starts it at once
        third = self.procs(3, wait=2)[2]
        self.assertNotIn(third["pid"], (first["pid"], second["pid"]))
        log = (self.jobs / "ask.log").read_text()
        self.assertEqual(2, log.count("session restarted"))
        self.assertNotIn("what", log)                           # the line says so, and nothing else

    def test_a_lapsed_lease_stops_the_server(self):
        ask.LEASE, ask.TICK = 0.5, 0.1
        self.up()
        self.op("keep")
        (p,) = self.procs()
        self.server.join(5)
        self.assertFalse(self.server.is_alive())                # the app went without a word: so does the server
        self.assertTrue(self.gone(p["pid"]))
        self.assertEqual([], list(self.jobs.glob("*.sock")))
        self.assertIn("lease lapsed", (self.jobs / "ask.log").read_text())

    def test_with_no_lease_the_idle_rule_is_unchanged(self):
        import time
        ask.LEASE, ask.IDLE_TICK, ask.CLEAR_AFTER = 0.2, 0.1, 1.5
        self.up()
        self.op("warm")
        time.sleep(0.6)
        self.assertTrue(self.server.is_alive())                 # no lease to lapse
        self.server.join(5)
        self.assertFalse(self.server.is_alive())                # idle for CLEAR_AFTER: gone, as before
        self.assertEqual([], list(self.jobs.glob("*.sock")))

    def test_keep_with_the_flag_off_stops_the_server(self):
        import contextlib
        import io
        self.up()
        self.op("keep")
        write(self.root / "System" / "garrick-flags.json", json.dumps({"ask": False}))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = ask.main(["--workspace", str(self.root), "--json", "keep"])
        self.assertEqual(1, code)
        self.assertIn("preview feature, and it is off", json.loads(buf.getvalue())["say"])
        self.server.join(10)
        self.assertFalse(self.server.is_alive())
        self.assertEqual([], list(self.jobs.glob("*.sock")))
        with contextlib.redirect_stdout(io.StringIO()):
            ask.main(["--workspace", str(self.root), "--json", "keep"])       # and starts nothing
        self.assertEqual([], list(self.jobs.glob("*.sock")))
        self.assertEqual(1, len(self.procs()))

    def test_a_new_session_is_told_the_names(self):
        """The regression: a new process, after a reset, a warm that replaced an
        aged session, or a restart, used to be told `<workspace unchanged/>`."""
        import time
        ask.CLEAR_AFTER = 1
        self.up()
        self.op("keep")                                         # held, so the short age is no idle limit
        self.op("ask", "what's open")
        self.op("ask", "and Birch?")
        (kept,) = self.procs()
        self.assertIn("<workspace>\n", self.first_message(kept["pid"]))
        said = [json.loads(l)["content"] for l in Path(str(self.args) + ".msgs").read_text().splitlines()]
        self.assertIn("<workspace unchanged/>", said[1])        # the same process, told once
        self.op("reset")
        self.op("ask", "what's open")
        time.sleep(1.2)
        self.op("warm")                                         # an aged session, replaced
        self.op("ask", "what's open")
        self.kill(self.procs(3)[2]["pid"])
        self.op("keep")                                         # started again
        self.op("ask", "what's open")
        procs = self.procs(4)
        self.assertEqual(4, len(procs))
        for p in procs:
            self.assertIn("<workspace>\n", self.first_message(p["pid"]), p["pid"])

    def test_the_marker_is_the_hooks(self):
        spec = importlib.util.spec_from_file_location("garrick_notifications_for_ask",
                                                      REPO / "template" / "System" / "tools" / "notifications.py")
        notifications = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(notifications)
        self.assertEqual(ask.MARKER, notifications.BACKGROUND)


@unittest.skipIf(sys.platform == "win32", "a stand-in executable on PATH")
class TestOneConnection(ServerCase):
    """#261, slice B: a request's reply is JSON lines on its one connection,
    progress first and one final line with its kind, and Stop is said there too."""

    def connect(self, request):
        import socket
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.connect(str(ask.sock_path(self.root)))
        c.sendall((json.dumps(request) + "\n").encode("utf-8"))
        return c

    def lines(self, c):
        with c:
            return [json.loads(line) for line in c.makefile("rb")]

    def reading(self, pause=0.0):
        """Asker.ask as slice C's answers will run it: progress said as the turn goes."""
        import time
        real = ask.Asker.ask

        def ask_(asker, request, today=None):
            asker.progress("Reading the thread note")
            asker.progress("Writing the answer")
            time.sleep(pause)
            return real(asker, request, today)
        return mock.patch.object(ask.Asker, "ask", ask_)

    def asked(self, wait=10.0):
        """Once the stand-in has the request: the turn is under way."""
        import time
        msgs = Path(str(self.args) + ".msgs")
        until = time.time() + wait
        while not msgs.exists() and time.time() < until:
            time.sleep(0.05)
        self.assertTrue(msgs.exists(), "the session was never asked")

    def test_progress_lines_then_one_final_line_with_its_kind(self):
        self.up()
        with self.reading():
            lines = self.lines(self.connect({"op": "ask", "text": "what's open"}))
        self.assertEqual([{"progress": "Reading the thread note"}, {"progress": "Writing the answer"}], lines[:-1])
        self.assertEqual(("command", "ok"), (lines[-1]["kind"], lines[-1]["say"]))
        (alone,) = self.lines(self.connect({"op": "ask", "text": "and now?"}))     # that connection's only
        self.assertEqual("command", alone["kind"])
        for op in ("warm", "keep", "status", "reset", "nonsense"):
            (final,) = self.lines(self.connect({"op": op}))
            self.assertIn(final["kind"], ask.KINDS, op)                            # every final line says what it is

    def test_the_client_relays_progress_as_it_comes(self):
        import contextlib
        import io
        import time
        self.up()
        heard = []
        with self.reading(pause=0.6):
            out = ask.call(self.root, "ask", "what's open", start=False, progress=lambda t: heard.append((t, time.time())))
        done = time.time()
        self.assertEqual(["Reading the thread note", "Writing the answer"], [t for t, _ in heard])
        self.assertGreater(done - heard[-1][1], 0.4)                               # as it came, not at the end
        self.assertEqual("command", out["kind"])
        buf = io.StringIO()
        with self.reading(), contextlib.redirect_stdout(buf):
            code = ask.main(["--workspace", str(self.root), "--json", "ask", "what's", "open"])
        printed = [json.loads(line) for line in buf.getvalue().splitlines()]
        self.assertEqual(0, code)
        self.assertEqual([{"progress": "Reading the thread note"}, {"progress": "Writing the answer"}], printed[:2])
        self.assertEqual((3, "command"), (len(printed), printed[2]["kind"]))

    def test_stop_on_the_connection_ends_the_session(self):
        import time
        self.answers.write_text(json.dumps([30]))                  # the first answer would take half a minute
        self.up()
        c = self.connect({"op": "ask", "text": "what's open"})
        self.asked()
        t0 = time.time()
        c.sendall(ask.STOP)
        (final,) = self.lines(c)
        self.assertLess(time.time() - t0, 5)
        self.assertEqual({"kind": "command", "ok": False, "stopped": True, "say": ask.STOPPED},
                         {k: final[k] for k in ("kind", "ok", "stopped", "say")})
        (first,) = self.procs()
        self.assertTrue(self.gone(first["pid"]))                   # ended, never left to finish
        self.assertFalse(self.op("status")["session"])
        self.assertEqual("ok", self.op("ask", "what's open")["say"])   # the next request starts a new one
        second = self.procs(2)[1]
        self.assertNotEqual(first["pid"], second["pid"])
        self.assertIn("<workspace>\n", self.first_message(second["pid"]))     # told everything again
        ledger = [json.loads(line) for line in (self.jobs / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual(["stopped", "success"], [e["subtype"] for e in ledger])  # the stopped turn is a call all the same

    def test_an_interrupt_is_a_stop_said_on_the_connection(self):
        """The app's Stop sends SIGINT to ask.py, as Ctrl-C does: it says STOP
        on its connection and waits for the final line."""
        import signal
        import threading
        import time
        self.answers.write_text(json.dumps([30]))
        self.up()

        def interrupt():
            self.asked()
            os.kill(os.getpid(), signal.SIGINT)
        threading.Thread(target=interrupt, daemon=True).start()
        t0 = time.time()
        out = ask.call(self.root, "ask", "what's open", start=False)
        self.assertLess(time.time() - t0, 10)
        self.assertTrue(out["stopped"])
        self.assertTrue(self.gone(self.procs()[0]["pid"]))
        self.assertIs(signal.default_int_handler, signal.getsignal(signal.SIGINT))   # put back as it was

    def test_new_conversation_is_a_reset(self):
        """The window's New conversation sends `reset`: a new process, told
        the whole list, and nothing of what was said before."""
        self.answers.write_text(json.dumps(['{"say": "Parked.", "do": [{"verb": "park", "zone": "Work", '
                                            '"project": "Acme Review", "thread": "Pricing"}]}']))
        self.up()
        self.assertEqual(["Acme Review, Pricing is parked"], self.op("ask", "park Pricing")["done"])
        reset = self.op("reset")
        self.assertEqual(("A fresh conversation.", "command"), (reset["say"], reset["kind"]))
        self.op("ask", "what's open")
        first, second = self.procs(2)
        told = self.first_message(second["pid"])
        self.assertIn("<workspace>\n", told)
        self.assertNotIn("<last-results>", told)
        self.assertNotIn("park Pricing", told)


class TestTheAppKeepsIt(unittest.TestCase):
    """#261: what Garrick.swift does with the session, read from its source,
    since CI compiles no Swift."""

    @classmethod
    def setUpClass(cls):
        cls.swift = (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")

    def body(self, signature):
        import re
        m = re.search(r"\n(\t)(?:@objc )?func %s\b[^\n]*\{\n(.*?)\n\1\}\n" % re.escape(signature), self.swift, re.S)
        self.assertIsNotNone(m, signature)
        return m.group(2)

    def test_launch_keeps_it_once_the_window_shows(self):
        launch = self.body("applicationDidFinishLaunching")
        self.assertLess(launch.index("showWindow()"), launch.index("askKeep()"))
        self.assertLess(launch.index("freshen()"), launch.index("askKeep()"))
        self.assertIn("asyncAfter", launch[launch.index("freshen()"):])
        self.assertIn("askKeepEvery", launch)

    def test_keep_does_nothing_under_check(self):
        keep = self.body("askKeep")
        self.assertTrue(keep.strip().startswith("if checking { return }"), keep)
        self.assertIn('askCall(["keep"])', keep)
        self.assertIn('askCall(["stop"])', keep)

    def test_quit_stops_it_and_waits(self):
        quit_ = self.body("applicationWillTerminate")
        self.assertIn('"stop"', quit_)
        self.assertIn("addingTimeInterval(2)", quit_)
        self.assertIn("isRunning", quit_)
        self.assertNotIn("askCall", quit_)                      # it would return before the app is gone

    def test_the_lease_outlasts_two_keeps(self):
        import re
        every = float(re.search(r"let askKeepEvery = ([\d.]+)", self.swift).group(1))
        self.assertLess(2 * every, ask.LEASE)

    def test_the_app_never_resets_unasked_and_still_warms(self):
        self.assertEqual(1, self.swift.count('askCall(["reset"])'))
        self.assertIn('askCall(["reset"])', self.body("askNew"))      # New conversation, and nothing else
        self.assertIn("askWarm()", self.body("showAsk"))
        self.assertIn('askCall(["warm"])', self.body("askWarm"))
        self.assertIn('askCall(["warm"])', self.body("hotKeyPressed"))


class TestTheAskWindow(unittest.TestCase):
    """#261, slice B: one window that expands, read from Garrick.swift's source."""

    @classmethod
    def setUpClass(cls):
        cls.swift = (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")

    body = TestTheAppKeepsIt.body

    def between(self, start, end):
        return self.swift[self.swift.index(start):self.swift.index(end, self.swift.index(start))]

    def test_return_sends_and_shift_return_breaks_the_line(self):
        typed = self.between("final class AskInput: NSTextView {", "\n}\n")
        command = typed[typed.index("override func doCommand(by sel: Selector)"):typed.index("override func didChangeText()")]
        self.assertIn("if sel == #selector(insertNewline(_:)) {", command)
        self.assertLess(command.index("modifierFlags.contains(.shift)"), command.index("return submit()"))
        self.assertIn("insertNewlineIgnoringFieldEditor(nil)", command)
        self.assertIn("askField = AskInput(", self.body("showAsk"))
        self.assertIn("askField.submit = { [weak self] in self?.askSubmit(nil) }", self.body("showAsk"))
        self.assertNotIn("askField.action", self.swift)                 # a field's action would send on any Return

    def test_escape_hides_the_window_and_keeps_the_exchange(self):
        panel = self.between("final class AskPanel: NSPanel {", "\n}\n")
        self.assertIn("override func cancelOperation(_ sender: Any?) { orderOut(nil) }", panel)
        typed = self.between("final class AskInput: NSTextView {", "\n}\n")
        self.assertIn("if sel == #selector(cancelOperation(_:)) || sel == #selector(complete(_:)) { return hide() }", typed)
        self.assertIn("askField.hide = { [weak self] in self?.askPanel?.orderOut(nil) }", self.body("showAsk"))
        self.assertNotIn("askPanel?.close()", self.swift)

    def test_only_new_conversation_and_quit_clear_the_exchange(self):
        import re
        self.assertEqual(["askTurns.removeAll()"], re.findall(r"askTurns\.remove\w*\([^)]*\)", self.swift))
        self.assertIn("askTurns.removeAll()", self.body("askNew"))
        self.assertEqual([], re.findall(r"askTurns\s*=[^=]", self.swift))  # never set anew, only appended to
        self.assertIn("var askTurns: [AskTurn] = []", self.swift)          # held by the app, so it goes with it on quit
        self.assertNotIn("askTurns", self.body("askWarm"))

    def test_the_shortcut_brings_the_one_window_forward(self):
        self.assertEqual(1, self.swift.count("AskPanel(contentRect"))
        self.assertIn("if askPanel == nil {", self.body("showAsk"))
        self.assertIn("if which == 2 { return showAsk() }", self.body("hotKeyPressed"))

    def test_a_wall_reset_keeps_the_exchange_under_a_divider(self):
        submit = self.body("askSubmit")
        self.assertIn('turn.afresh = out["reset"] as? String == "wall"', submit)
        self.assertIn("if turn.kind != \"command\" || turn.afresh { self.askExpanded = true }", submit)
        shown = self.body("askTranscript")
        self.assertLess(shown.index("if turn.afresh && i > 0 {"), shown.index("askAfresh"))
        self.assertLess(shown.index("askAfresh"), shown.index("turn.request"))   # above the turn it came with
        self.assertNotIn("askTurns", self.between("let askAfresh", "\n"))

    def test_lines_are_read_as_they_come_and_stop_interrupts(self):
        stream = self.between("func askStream(", "\n}\n")
        self.assertIn("readabilityHandler", stream)
        self.assertNotIn("readDataToEndOfFile", stream)                # never all of it at the end
        self.assertIn('if said["kind"] == nil, let text = said["progress"] as? String {', stream)
        self.assertIn("askStream(args, progress: { _ in }, done: done)", self.swift)   # askCall is one too
        self.assertIn("process.interrupt()", self.between("final class AskRequest {", "\n}\n"))
        self.assertIn("askRunning?.stop()", self.body("askStop"))
        self.assertIn("signal.SIGINT", (REPO / "extras" / "status" / "ask.py").read_text(encoding="utf-8"))
        submit = self.body("askSubmit")
        self.assertIn("guard !text.isEmpty, askRunning == nil else { return }", submit)   # one request at a time
        self.assertIn("progress: { [weak self] said in self?.askProgress(said) }", submit)

    def test_every_state_is_drawn_in_one_place(self):
        drawn = self.body("askRender")
        for said in ('"Preparing the assistant…"', '"Waiting for the assistant to start…"', '"Working…"', '"Stopping…"'):
            self.assertIn(said, drawn)
        self.assertIn("askStopButton.isHidden = !running", drawn)
        self.assertIn("askNewButton.isEnabled = !running", drawn)


class TestDesk(AskCase):
    """With the cmux extra's desk ready, an open comes back marked so the app
    opens cmux through it, the session started, as the page's buttons do."""

    def fake_cmux(self):
        fake = self.root.parent / "bin" / "cmux"           # only looked for, never run
        write(fake, "#!/bin/sh\nexit 1\n")
        fake.chmod(0o755)
        os.environ["GARRICK_CMUX"] = str(fake)

    def test_ready_needs_cmux(self):
        self.assertFalse(ask.desk_ready(self.root))                         # no cmux
        self.fake_cmux()
        self.assertTrue(ask.desk_ready(self.root))
        write(self.root / "System" / "garrick-flags.json", json.dumps({"ask": True}))
        self.assertTrue(ask.desk_ready(self.root))                          # the actions need no flag of their own

    def test_an_open_carries_the_desk_when_it_is_ready(self):
        do = [{"verb": "open", "zone": "Work", "project": "Acme Review", "thread": "Pricing", "app": "cmux"},
              {"verb": "open", "zone": "Work", "project": "Birch Entry"}]
        self.assertNotIn("dk", ask.Asker(self.root).carry_out("Opening.", do, self.names)["launch"][0])
        self.fake_cmux()
        out = ask.Asker(self.root).carry_out("Opening.", do, self.names)
        self.assertEqual([1, 1], [item["dk"] for item in out["launch"]])
        self.assertEqual("open Pricing", out["launch"][0]["phrase"])


class TestFlag(unittest.TestCase):
    def test_listed_with_the_preview_features(self):
        spec = importlib.util.spec_from_file_location("garrick_status_for_ask", REPO / "extras" / "status" / "status.py")
        status = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(status)
        self.assertIn("ask", status.FLAGS)
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp) / "System" / "garrick-flags.json", json.dumps({"ask": True}))
            self.assertTrue(status.preview_flags(Path(tmp))["ask"])
            self.assertTrue(ask.flag_on(Path(tmp)))


if __name__ == "__main__":
    unittest.main()
