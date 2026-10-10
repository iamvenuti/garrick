"""The ask preview, extras/status/ask.py, against a fictional workspace. Offline:
no model is called. A stand-in `claude` on PATH answers in stream-json where a
test needs the warm session itself.

    python3 -m unittest discover -s tests

The session proposes; ask.py checks each proposal against the workspace list
and runs it through page_action.act(), so the box can do what a page button
can and nothing more.
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
# the next answer from FAKE_ANSWERS, with the session's running cost, and its
# arguments go to FAKE_ARGS.
FAKE_CLAUDE = textwrap.dedent("""\
    #!%s
    import json, os, sys
    open(os.environ["FAKE_ARGS"], "w").write(json.dumps(sys.argv[1:]))
    answers = json.load(open(os.environ["FAKE_ANSWERS"]))
    n = 0
    for line in sys.stdin:
        msg = json.loads(line)
        with open(os.environ["FAKE_ARGS"] + ".seen", "a") as f:
            f.write(json.dumps(msg["message"]["content"]) + "\\n")
        n += 1
        print(json.dumps({"type": "assistant", "message": {"content": []}}), flush=True)
        print(json.dumps({"type": "result", "subtype": "success", "result": answers[n - 1], "num_turns": 1,
                          "total_cost_usd": 0.01 * n, "usage": {"input_tokens": 100, "output_tokens": 20}}), flush=True)
    """) % sys.executable


class AskCase(ActionCase):
    def setUp(self):
        super().setUp()
        write(self.root / "System" / "garrick-flags.json", json.dumps({"ask": True}))
        self.names = ask.scan(self.root)
        self._saved = {k: os.environ.get(k) for k in ("GARRICK_HARNESS", "GARRICK_ASK_TIER", "GARRICK_CAP_CALLS_HOUR", "PATH")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
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
        self.assertEqual(("act", {"verb": "todo-add", "zone": "Work", "text": "Call Dana", "target": "Acme Review/Pricing",
                                  "date": "2026-10-09"}),
                         ask.proposal({"verb": "todo-add", "zone": "Work", "text": " Call Dana ", "project": "Acme Review",
                                       "thread": "Pricing", "date": "2026-10-09"}, self.names, self.root))

    def test_refused(self):
        for a in ({"verb": "run", "job": "whats-open"}, {"verb": "shutdown"}, {"verb": "settings", "launchers": []},
                  {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "0" * 16}, {"verb": "rm", "zone": "Work"},
                  {"verb": "open", "zone": "Work", "project": "Nope"},
                  {"verb": "open", "zone": "Work", "project": "Acme Review", "thread": "Nope"},
                  {"verb": "open", "zone": "Elsewhere", "project": "Acme Review"},
                  {"verb": "open", "zone": "Work", "project": "Acme Review", "app": "terminal"},
                  {"verb": "open", "zone": "Work", "thread": "Pricing"},
                  {"verb": "park", "zone": "Work", "project": "Acme Review"},                 # it has threads
                  {"verb": "todo-add", "zone": "Work", "text": ""},
                  {"verb": "todo-add", "zone": "Work", "text": "x", "date": "tomorrow"},
                  {"verb": "open", "zone": "Work", "project": "../Personal"},
                  "open Pricing", None):
            with self.assertRaises(ask.Bad, msg=a):
                ask.proposal(a, self.names, self.root)


class FakeSession:
    remembers = True

    def __init__(self, *answers):
        self.answers, self.seen = list(answers), []

    def fresh(self):
        return not self.seen

    def ready(self):
        pass

    def turn(self, text):
        self.seen.append(text)
        return self.answers.pop(0), {"input_tokens": 1}


class TestCarryOut(AskCase):
    """Proposals run through page_action.act(), each logged as the page's are."""

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
        cmd = ask.ClaudeSession(self.root, "haiku").command()
        self.assertEqual(["claude", "-p"], cmd[:2])
        for flag, value in (("--model", "haiku"), ("--tools", ""), ("--permission-mode", "default"),
                            ("--settings", str(ask.agent().PROFILE)), ("--setting-sources", "user,project")):
            self.assertEqual(value, cmd[cmd.index(flag) + 1], flag)
        self.assertIn("--no-session-persistence", cmd)
        self.assertIn("--strict-mcp-config", cmd)
        self.assertEqual(ask.BRIEF.read_text(), cmd[cmd.index("--system-prompt") + 1])

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


@unittest.skipIf(sys.platform == "win32", "a stand-in executable on PATH")
class TestWarmSession(AskCase):
    """The warm Claude session, with a stand-in `claude`: two turns, one process, the ledger and the caps."""

    def setUp(self):
        super().setUp()
        bin_ = Path(self._tmp.name) / "bin"
        bin_.mkdir()
        fake = bin_ / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        os.environ["PATH"] = str(bin_) + os.pathsep + os.environ.get("PATH", "")
        self.args = Path(self._tmp.name) / "args.json"
        self.answers = Path(self._tmp.name) / "answers.json"
        os.environ["FAKE_ARGS"], os.environ["FAKE_ANSWERS"] = str(self.args), str(self.answers)
        self.addCleanup(os.environ.pop, "FAKE_ARGS", None)
        self.addCleanup(os.environ.pop, "FAKE_ANSWERS", None)

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
        self.assertIn('"open Pricing"  ->  "Opening Pricing."', (self.jobs / "ask.log").read_text())
        self.assertEqual([], list(self.jobs.glob("*.sock")))                         # stopped, and gone


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
