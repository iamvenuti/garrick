"""One engine for Ask and Telegram (#571): channels.py, engine.py, engine_guard.py, hold.py and hold_tools.py.

    python3 -m unittest discover -s tests

The assistant is a stub throughout: a runner function that gets the command the engine built and answers JSON. Nothing
calls a real assistant, and no test runs the assistant's own `--help`: the capability check is given its text.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from test_notes import NoteCase, REPO, git  # noqa: E402

STATUS = REPO / "extras" / "status"
HELP_OK = "--resume <id>  --allowedTools  --strict-mcp-config  Bash(git *) --effort <level>"


def load(name):
    sys.path.insert(0, str(STATUS))
    spec = importlib.util.spec_from_file_location("garrick_test_" + name, str(STATUS / (name + ".py")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class EngineCase(NoteCase):
    def setUp(self):
        super().setUp()
        for name in ("channels", "hold", "hold_tools", "engine_guard", "engine"):
            sys.modules.pop(name, None)
        self.channels = load("channels")
        sys.modules["channels"] = self.channels
        self.hold = load("hold")
        sys.modules["hold"] = self.hold
        self.guard = load("engine_guard")
        sys.modules["engine_guard"] = self.guard
        self.tools = load("hold_tools")
        self.engine = load("engine")
        self.cap_ok = self.channels.evaluate(self.root, HELP_OK, True)
        self._harness = os.environ.get("GARRICK_HARNESS")
        os.environ["GARRICK_HARNESS"] = "claude"

    def tearDown(self):
        for k in [k for k in os.environ if k.startswith("GARRICK_ENGINE")]:
            os.environ.pop(k)
        if self._harness is None:
            os.environ.pop("GARRICK_HARNESS", None)
        else:
            os.environ["GARRICK_HARNESS"] = self._harness
        super().tearDown()

    def settings(self, **channels):
        self.pa.perform(self.root, {"verb": "settings", "channels": channels}, self.pa.ops_lib(self.root), via="page")

    def reply(self, text="Done.", session="s-1"):
        return json.dumps({"type": "result", "result": text, "session_id": session, "usage": {"input_tokens": 12}, "total_cost_usd": 0.01})

    def runner(self, text="Done.", session="s-1", act=None):
        seen = []

        def run(cmd, tier, cwd, env):
            seen.append({"cmd": cmd, "tier": tier, "cwd": cwd, "env": env})
            if act and len(seen) == 1:                      # the assistant acts in its own turn, not in the held action's
                act(cmd, env)
            return 0, {"text": text, "session_id": session, "usage": {"input_tokens": 12}, "cost_usd": 0.01}
        run.seen = seen
        return run


class TestSettings(EngineCase):
    def test_both_channels_default_to_sonnet_medium_act(self):
        got = self.channels.settings(self.root)
        self.assertEqual({"tier": "sonnet", "effort": "medium", "autonomy": "act"}, got["ask"])
        self.assertEqual(got["ask"], got["telegram"])

    def test_settings_keeps_a_choice_and_refuses_full_for_telegram(self):
        self.settings(ask={"tier": "opus", "effort": "high", "autonomy": "full"})
        self.assertEqual({"tier": "opus", "effort": "high", "autonomy": "full"}, self.channels.settings(self.root)["ask"])
        out = self.pa.perform(self.root, {"verb": "settings", "channels": {"telegram": {"autonomy": "full"}}},
                              self.pa.ops_lib(self.root), via="page")[0]
        self.assertFalse(out["ok"])
        self.assertIn("Telegram does not offer Full", out["say"])
        self.assertEqual("act", self.channels.settings(self.root)["telegram"]["autonomy"])

    def test_a_full_found_in_the_file_for_telegram_reads_as_read(self):
        path = self.root / "System" / "garrick-settings.json"
        write(path, json.dumps({"channels": {"telegram": {"autonomy": "full", "tier": "gpt"}}}))
        got = self.channels.settings(self.root)["telegram"]
        self.assertEqual(("read", "sonnet"), (got["autonomy"], got["tier"]))

    def test_a_choice_that_is_not_one_is_refused(self):
        for bad in ({"tier": "claude-sonnet-5"}, {"effort": "max"}, {"autonomy": "root"}, {"colour": "red"}):
            out = self.pa.perform(self.root, {"verb": "settings", "channels": {"ask": bad}}, self.pa.ops_lib(self.root), via="page")[0]
            self.assertFalse(out["ok"], bad)

    def test_deep_raises_one_request_and_leaves_the_settings(self):
        cfg = self.channels.settings(self.root)["ask"]
        got = self.channels.plan(cfg, "deep: why did the floor move")
        self.assertEqual(("opus", "high", True, "why did the floor move"), (got["tier"], got["effort"], got["deep"], got["text"]))
        self.assertEqual(("sonnet", "medium", False), tuple(self.channels.plan(cfg, "file the inbox")[k] for k in ("tier", "effort", "deep")))
        self.assertEqual("sonnet", self.channels.settings(self.root)["ask"]["tier"])

    def test_a_plain_command_stays_on_the_small_tier(self):
        cfg = self.channels.settings(self.root)["ask"]
        for text in ("open Pricing", "park the launch video", "please wake Pricing"):
            self.assertEqual("haiku", self.channels.plan(cfg, text)["tier"], text)
        self.assertEqual("opus", self.channels.plan(cfg, "deep: open Pricing")["tier"])

    def test_what_asks_for_work_is_found_by_code(self):
        for text in ("file the inbox", "tick the Dana line", "Move the September call into Renewal", "send the price sheet to Dana",
                     "deep: delete the old draft"):
            self.assertTrue(self.channels.wants_action(text), text)
        for text in ("where does Pricing stand", "what do I owe", "open Pricing", "add call Dana to Acme", "why did the floor move"):
            self.assertFalse(self.channels.wants_action(text), text)


class TestCapability(EngineCase):
    def test_an_assistant_that_can_do_the_three_things_passes(self):
        self.assertEqual((True, []), (self.cap_ok["ok"], self.cap_ok["failed"]))

    def test_each_failed_check_is_named_and_drops_the_channel_to_read(self):
        for missing, check in (("--resume", "resume"), ("--allowedTools", "removable_tools"),
                               ("--strict-mcp-config", "removable_tools"), ("Bash(", "removable_tools")):
            cap = self.channels.evaluate(self.root, HELP_OK.replace(missing, ""), True)
            self.assertEqual([check], cap["failed"], missing)
            now = self.channels.effective(self.root, "ask", cap)
            self.assertEqual(("read", "act", [check]), (now["autonomy"], now["set"], now["limited"]))
            self.assertTrue(now["why"])
        cap = self.channels.evaluate(self.root, HELP_OK, False)
        self.assertEqual(["walls_outside_model"], cap["failed"])

    def test_a_failed_hook_load_fails_the_check(self):
        with mock.patch.dict(sys.modules, {"engine_guard": None}):
            self.assertFalse(self.channels.guard_works(self.root))
        self.assertTrue(self.channels.guard_works(self.root))

    def test_the_check_runs_again_when_the_assistant_changes(self):
        calls = []
        probe = lambda: calls.append(1) or HELP_OK            # noqa: E731
        self.channels.capability(self.root, probe=probe, guard=True)
        self.channels.capability(self.root, probe=probe, guard=True)
        self.assertEqual(1, len(calls))                     # kept for this assistant
        with mock.patch.dict(os.environ, {"GARRICK_HARNESS": "other"}):
            self.channels.capability(self.root, probe=probe, guard=True)
        self.assertEqual(2, len(calls))

    def test_a_failed_check_runs_a_request_at_read_and_says_which(self):
        cap = self.channels.evaluate(self.root, HELP_OK.replace("--resume", ""), True)
        run = self.runner()
        got = self.engine.run(self.root, "ask", "file the inbox", "Work", {"id": "e1"}, run, cap)
        self.assertEqual(("read", ["resume"]), (got["autonomy"], got["limited"]))
        cmd = run.seen[0]["cmd"]
        self.assertEqual("", cmd[cmd.index("--tools") + 1])
        self.assertNotIn("Edit", cmd)
        self.assertFalse(any(a.startswith("Bash(") for a in cmd))

    def test_the_page_names_the_check_that_failed(self):
        status = importlib.util.spec_from_file_location("garrick_test_status_ch", str(STATUS / "status.py"))
        mod = importlib.util.module_from_spec(status)
        status.loader.exec_module(mod)
        self.channels.capability(self.root, probe=lambda: HELP_OK.replace("--resume", ""), guard=True)
        html = mod.channels_settings(self.root)
        self.assertIn("Running at Read", html)
        self.assertIn("resume", html)
        self.assertNotIn('<option value="full" selected', html.split("Telegram", 1)[1])
        self.assertEqual(1, html.count('value="full"'))     # Ask offers Full, Telegram never does


class TestWhatTheSessionHas(EngineCase):
    def build(self, level="act", exchange=None):
        folder = Path(os.environ["GARRICK_JOBS_DIR"]) / "engine" / "e1"
        planned = {"tier": "sonnet", "effort": "medium", "prompt": "<request>x</request>", "fresh": False}
        return self.engine.build(self.root, "telegram", "Work", planned, level, exchange or {"id": "e1"}, folder, self.cap_ok), folder

    def test_at_act_there_is_no_open_shell_and_no_send_tool(self):
        (cmd, env), folder = self.build()
        tools = cmd[cmd.index("--allowedTools") + 1:]
        self.assertNotIn("Bash", tools)
        self.assertFalse([t for t in tools if t.startswith("Bash") and not t.startswith("Bash(")])
        self.assertTrue(any(t.startswith("Bash(git -C ") and t.endswith(" commit:*)") and "/Zones/Work" in t for t in tools))
        for forbidden in ("curl", "gh ", "mail", "ssh", "scp", "rsync", "scaffold.py party", "intake.py learn", "page_action", "allow"):
            self.assertFalse([t for t in tools if forbidden in t], forbidden)
        self.assertIn("mcp__garrick_hold__hold", tools)
        for tool in tools:
            self.assertNotRegex(tool, r"(?i)send|forward|share|trash|delete|Gmail|Calendar|Drive")
        self.assertIn("--strict-mcp-config", cmd)                      # the owner's connectors are not in the session
        servers = json.loads((folder / "mcp.json").read_text())["mcpServers"]
        self.assertEqual({"garrick", "garrick_hold"}, set(servers))

    def test_git_is_the_exchanges_zone_only(self):
        (cmd, _), _ = self.build()
        git_tools = [t for t in cmd[cmd.index("--allowedTools") + 1:] if t.startswith("Bash(git")]
        self.assertTrue(git_tools)
        self.assertTrue(all("/Zones/Work" in t and "Personal" not in t for t in git_tools))

    def test_the_guard_is_the_sessions_own_pre_tool_hook(self):
        (cmd, env), folder = self.build()
        settings = json.loads((folder / "settings.json").read_text())
        hook = settings["hooks"]["PreToolUse"][0]
        self.assertIn("Edit", hook["matcher"])
        self.assertIn("engine_guard.py", hook["hooks"][0]["command"])
        self.assertEqual("Work", env["GARRICK_ENGINE_ZONE"])
        self.assertIn("mcp__claude_ai_Gmail__send_message", settings["permissions"]["deny"])

    def test_at_read_the_session_has_the_read_tools_alone(self):
        (cmd, _), folder = self.build("read")
        tools = cmd[cmd.index("--allowedTools") + 1:]
        self.assertEqual(["mcp__garrick__%s" % t for t in self.engine.READ_TOOLS], tools)
        self.assertNotIn("hooks", json.loads((folder / "settings.json").read_text()))

    def test_a_follow_up_resumes_the_session_and_the_first_turn_does_not(self):
        (first, _), _ = self.build()
        self.assertNotIn("--resume", first)
        (second, _), _ = self.build(exchange={"id": "e1", "session": "s-9"})
        self.assertEqual("s-9", second[second.index("--resume") + 1])

    def test_the_effort_flag_is_passed_only_when_the_assistant_has_one(self):
        (cmd, _), _ = self.build()
        self.assertEqual("medium", cmd[cmd.index("--effort") + 1])
        cap = self.channels.evaluate(self.root, HELP_OK.replace("--effort", ""), True)
        folder = Path(os.environ["GARRICK_JOBS_DIR"]) / "engine" / "e2"
        cmd, _ = self.engine.build(self.root, "ask", "Work", {"tier": "sonnet", "effort": "low", "prompt": "x", "fresh": False}, "act",
                                   {"id": "e2"}, folder, cap)
        self.assertNotIn("--effort", cmd)

    def test_the_hold_server_has_one_tool_and_none_that_sends_to_telegram(self):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        names = [t["name"] for t in self.tools.handle(msg)["result"]["tools"]]
        self.assertEqual(["hold"], names)
        self.assertEqual(-32602, self.tools.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "telegram_send"}})["error"]["code"])


class TestWallsAtAct(EngineCase):
    def decide(self, path, tool="Write", zone="Work"):
        return self.guard.decide({"tool_name": tool, "tool_input": {"file_path": path}}, str(self.root), zone)

    def test_a_write_into_another_zone_is_refused(self):
        denied = self.decide(str(self.personal / "Home Move" / "x.md"))
        self.assertEqual("deny", denied["hookSpecificOutput"]["permissionDecision"])

    def test_the_zone_a_wiki_and_the_inbox_are_allowed(self):
        for path in (self.work / "Acme Review" / "x.md", self.root / "Wikis" / "Meetings" / "wiki" / "x.md", self.root / "Inbox" / "x.md",
                     self.work / "Todo.md"):
            self.assertIsNone(self.decide(str(path)), path)

    def test_system_the_settings_and_a_shared_folder_are_refused(self):
        for path in (self.root / "System" / "garrick-settings.json", self.root / "System" / "rules.md",
                     self.work / ".shared" / "team" / "x.docx", self.root / "AGENTS.md"):
            self.assertIsNotNone(self.decide(str(path)), path)

    def test_a_link_out_of_the_zone_is_judged_where_it_leads(self):
        link = self.work / "Acme Review" / "out"
        link.symlink_to(self.personal)
        self.assertIsNotNone(self.decide(str(link / "x.md")))

    def test_a_path_that_climbs_out_is_refused(self):
        self.assertIsNotNone(self.decide(str(self.work / ".." / "Personal" / "x.md")))

    def test_a_read_is_not_a_write(self):
        self.assertIsNone(self.guard.decide({"tool_name": "Read", "tool_input": {"file_path": str(self.personal / "x")}}, str(self.root), "Work"))

    def test_the_hook_runs_as_claude_runs_it_and_fails_closed(self):
        script = str(STATUS / "engine_guard.py")
        env = dict(os.environ, GARRICK_ENGINE_WS=str(self.root), GARRICK_ENGINE_ZONE="Work")
        bad = {"tool_name": "Edit", "tool_input": {"file_path": str(self.personal / "Home Move" / "Home Move.md")}}
        out = subprocess.run([sys.executable, script], input=json.dumps(bad), capture_output=True, text=True, env=env)
        self.assertEqual("deny", json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"])
        fine = {"tool_name": "Edit", "tool_input": {"file_path": str(self.work / "Todo.md")}}
        out = subprocess.run([sys.executable, script], input=json.dumps(fine), capture_output=True, text=True, env=env)
        self.assertEqual("", out.stdout.strip())
        out = subprocess.run([sys.executable, script], input="not json", capture_output=True, text=True, env=env)
        self.assertEqual("deny", json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"])
        out = subprocess.run([sys.executable, script], input=json.dumps(fine), capture_output=True, text=True,
                             env={k: v for k, v in env.items() if k != "GARRICK_ENGINE_ZONE"})
        self.assertEqual("deny", json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"])


class TestActDoesTheWork(EngineCase):
    def test_a_request_to_file_edits_and_commits_with_no_click(self):
        def assistant(cmd, env):
            write(self.work / "Acme Review" / "Threads" / "Pricing" / "Notes" / "261114 - from the engine.md", "a note\n")
            git(self.work, "add", "-A")
            git(self.work, "commit", "-q", "-m", "Work: filed by the engine")
        run = self.runner("Pricing: filed one note.", act=assistant)
        got = self.engine.run(self.root, "ask", "file the inbox", "Work", {"id": "e1"}, run, self.cap_ok)
        self.assertEqual((True, "Pricing: filed one note.", [], "act"), (got["ok"], got["say"], got["held"], got["autonomy"]))
        self.assertEqual("Work: filed by the engine", git(self.work, "log", "-1", "--format=%s").strip())
        self.assertEqual("s-1", got["session"])
        self.assertEqual("sonnet", run.seen[0]["tier"])

    def test_deep_runs_that_request_on_opus_at_high_effort(self):
        run = self.runner()
        got = self.engine.run(self.root, "ask", "deep: file the inbox", "Work", {"id": "e1"}, run, self.cap_ok)
        cmd = run.seen[0]["cmd"]
        self.assertEqual(("opus", "high"), (cmd[cmd.index("--model") + 1], cmd[cmd.index("--effort") + 1]))
        self.assertEqual((True, "sonnet"), (got["deep"], self.channels.settings(self.root)["ask"]["tier"]))

    def test_the_session_is_kept_for_the_next_turn(self):
        run = self.runner(session="s-5")
        ex = {"id": "e1"}
        first = self.engine.run(self.root, "telegram", "file the inbox", "Work", ex, run, self.cap_ok)
        ex["session"] = first["session"]
        self.engine.run(self.root, "telegram", "and the second one", "Work", ex, run, self.cap_ok)
        self.assertNotIn("--resume", run.seen[0]["cmd"])
        cmd = run.seen[1]["cmd"]
        self.assertEqual("s-5", cmd[cmd.index("--resume") + 1])

    def test_a_failed_call_says_so_and_does_nothing_more(self):
        got = self.engine.run(self.root, "ask", "file the inbox", "Work", {"id": "e1"}, lambda *a: (1, {"text": ""}), self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertIn("did not work", got["say"])

    def test_a_call_past_a_cap_is_not_run_and_says_why(self):
        got = self.engine.run(self.root, "ask", "file the inbox", "Work", {"id": "e1"},
                              lambda *a: (8, {"text": "", "refused": "the hourly limit of 60 calls is reached"}), self.cap_ok)
        self.assertEqual((False, "Not run: the hourly limit of 60 calls is reached."), (got["ok"], got["say"]))


class TestASendIsHeld(EngineCase):
    def asking(self, cmd, env):
        """The assistant, told by a record to forward something: the only way out it has is hold."""
        os.environ.update({k: v for k, v in env.items() if k.startswith("GARRICK_ENGINE")})
        wanted = {"what": "Forward the price sheet", "where": "dana@example.com",
                  "tool": "mcp__mail__forward", "args": {"to": "dana@example.com"}}
        msg = {"params": {"arguments": wanted, "name": "hold"}, "method": "tools/call"}
        msg.update(id=1, jsonrpc="2.0")
        self.assertFalse(self.tools.handle(msg)["result"]["isError"])

    def test_a_record_asking_for_a_send_produces_only_a_held_action(self):
        ran = []
        run = self.runner("I queued it.", act=self.asking)
        got = self.engine.run(self.root, "ask", "forward the price sheet to Dana", "Work", {"id": "e1"}, run, self.cap_ok)
        [held] = got["held"]
        self.assertEqual(("send", "held", "dana@example.com", "Work", "e1"), (held["kind"], held["state"], held["where"], held["zone"], held["exchange"]))
        self.assertEqual(1, len(run.seen))                         # nothing ran the forward: only the one assistant call
        self.assertEqual([], ran)
        self.assertEqual("held", self.hold.get(held["id"])["state"])

    def test_a_held_send_runs_on_a_yes_once(self):
        got = self.engine.run(self.root, "ask", "forward the price sheet", "Work", {"id": "e1"}, self.runner(act=self.asking), self.cap_ok)
        hid = got["held"][0]["id"]
        did = []
        said = self.hold.run(hid, self.root, lambda ws, rec: (did.append(rec["request"]["tool"]) or True, "Sent."))
        self.assertEqual(("Sent.", ["mcp__mail__forward"]), (said, did))
        self.assertEqual("done", self.hold.get(hid)["state"])
        again = self.hold.run(hid, self.root, lambda ws, rec: (did.append("twice") or True, "Sent."))
        self.assertEqual(("That action is not waiting any more.", ["mcp__mail__forward"]), (again, did))

    def test_a_held_send_that_is_refused_never_runs(self):
        got = self.engine.run(self.root, "ask", "forward the price sheet", "Work", {"id": "e1"}, self.runner(act=self.asking), self.cap_ok)
        hid = got["held"][0]["id"]
        self.assertEqual("Cancelled. Nothing was done.", self.hold.cancel(hid))
        did = []
        self.assertEqual("That action is not waiting any more.", self.hold.run(hid, self.root, lambda w, r: (did.append(1) or True, "x")))
        self.assertEqual([], did)

    def test_a_held_action_expires_after_a_day(self):
        got = self.engine.run(self.root, "ask", "forward it", "Work", {"id": "e1"}, self.runner(act=self.asking), self.cap_ok)
        hid = got["held"][0]["id"]
        later = time.time() + 24 * 3600 + 5
        self.assertEqual([], self.hold.pending(later))
        self.assertIn("more than a day", self.hold.run(hid, self.root, lambda w, r: (True, "x"), now=later))
        self.assertEqual("expired", self.hold.get(hid)["state"])

    def test_the_page_lists_what_waits_until_it_expires(self):
        self.engine.run(self.root, "ask", "forward it", "Work", {"id": "e1"}, self.runner(act=self.asking), self.cap_ok)
        [row] = self.hold.listing()
        self.assertEqual(("Forward the price sheet", "dana@example.com", 24), (row["what"], row["where"], row["hours_left"]))
        status = importlib.util.spec_from_file_location("garrick_test_status_held", str(STATUS / "status.py"))
        mod = importlib.util.module_from_spec(status)
        status.loader.exec_module(mod)
        self.assertIn("Forward the price sheet", mod.held_list())

    def test_the_telegram_yes_is_a_reply_to_the_message_that_asked(self):
        got = self.engine.run(self.root, "telegram", "forward it", "Work", {"id": "t1"}, self.runner(act=self.asking), self.cap_ok)
        hid = got["held"][0]["id"]
        self.hold.note_message(hid, 501)
        self.assertIsNone(self.hold.by_message(502))               # a yes that replies to another message runs nothing
        self.assertEqual(hid, self.hold.by_message(501)["id"])

    def test_full_runs_the_send_for_ask_without_asking(self):
        self.settings(ask={"autonomy": "full"})
        run = self.runner("Forwarded.", act=self.asking)
        got = self.engine.run(self.root, "ask", "forward the price sheet", "Work", {"id": "e1"}, run, self.cap_ok)
        self.assertEqual("full", got["autonomy"])
        self.assertEqual([], got["held"])
        self.assertEqual(2, len(run.seen))                         # the request, then the one allowed tool
        self.assertEqual(["mcp__mail__forward"], run.seen[1]["cmd"][run.seen[1]["cmd"].index("--allowedTools") + 1:])
        self.assertEqual([], self.hold.listing())

    def test_telegram_never_runs_at_full_even_if_it_is_asked_to(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"channels": {"telegram": {"autonomy": "full"}}}))
        run = self.runner("x", act=self.asking)
        got = self.engine.run(self.root, "telegram", "forward the price sheet", "Work", {"id": "t1"}, run, self.cap_ok)
        self.assertEqual("read", got["autonomy"])
        self.assertEqual(1, len(run.seen))

    def test_a_held_connector_tool_is_run_with_that_one_tool_allowed(self):
        rec = {"request": {"tool": "mcp__mail__forward", "args": {"to": "dana@example.com"}}}
        run = self.runner("Forwarded.")
        ok, said = self.engine.execute_held(self.root, rec, run)
        cmd = run.seen[0]["cmd"]
        self.assertEqual((True, "Forwarded."), (ok, said))
        self.assertEqual(["mcp__mail__forward"], cmd[cmd.index("--allowedTools") + 1:])

    def test_a_held_write_under_a_shared_folder_is_codes_and_never_overwrites(self):
        shared = self.work / ".shared" / "team"
        shared.mkdir(parents=True)
        rec = {"zone": "Work", "request": {"write": ".shared/team/brief.md", "text": "hello"}}
        self.assertEqual((True, "Written to the shared folder."), self.engine.execute_held(self.root, rec))
        self.assertEqual("hello", (shared / "brief.md").read_text())
        ok, said = self.engine.execute_held(self.root, dict(rec, request={"write": ".shared/team/brief.md", "text": "other"}))
        self.assertFalse(ok)
        self.assertEqual("hello", (shared / "brief.md").read_text())
        ok, _ = self.engine.execute_held(self.root, {"zone": "Work", "request": {"write": "Acme Review/x.md", "text": "x"}})
        self.assertFalse(ok)
        ok, _ = self.engine.execute_held(self.root, {"zone": "Work", "request": {"write": ".shared/../../Personal/x.md", "text": "x"}})
        self.assertFalse(ok)


class TestAskUsesTheEngine(EngineCase):
    def asker(self):
        self.ask_mod = self.ask
        sess = mock.Mock(spec=self.ask.AgentSession)
        return self.ask.Asker(self.root, sess)

    def test_the_box_hands_work_to_the_engine_and_keeps_questions(self):
        asker = self.asker()
        with mock.patch.object(self.ask.engine_lib().channels, "effective", return_value={"autonomy": "act"}):
            self.assertTrue(asker.engine_wanted("file the inbox"))
            self.assertFalse(asker.engine_wanted("where does Pricing stand"))
        with mock.patch.object(self.ask.engine_lib().channels, "effective", return_value={"autonomy": "read"}):
            self.assertFalse(asker.engine_wanted("file the inbox"))

    def test_a_send_comes_back_with_run_it_and_cancel(self):
        asker = self.asker()
        eng = self.ask.engine_lib()
        entry = self.hold.add("ask", "Work", "e1", "Forward the price sheet", "dana@example.com", {"tool": "mcp__mail__forward", "args": {}})
        fake = {"ok": True, "say": "Queued.", "held": [entry], "session": "s", "usage": {}}
        with mock.patch.object(eng, "run", return_value=fake):
            out = asker.act_engine("forward the price sheet", {"Work": {}}, "Work")
        self.assertEqual(["Run it", "Cancel"], [c["label"] for c in out["choices"]])
        self.assertEqual("run held %s" % entry["id"], out["choices"][0]["request"])
        self.assertIn("dana@example.com", out["say"])

    def test_the_dialogs_buttons_run_or_drop_the_action_and_nothing_else_does(self):
        asker = self.asker()
        entry = self.hold.add("ask", "Work", "e1", "Forward it", "dana@example.com", {"tool": "mcp__mail__forward", "args": {}})
        eng = self.ask.engine_lib()
        with mock.patch.object(eng, "execute_held", return_value=(True, "Forwarded.")) as ran:
            self.assertEqual("Forwarded.", asker.held_answer("run", entry["id"])["say"])
            self.assertEqual("That action is not waiting any more.", asker.held_answer("run", entry["id"])["say"])
        self.assertEqual(1, ran.call_count)
        other = self.hold.add("ask", "Work", "e1", "Share it", "the team", {"tool": "mcp__drive__share_file", "args": {}})
        self.assertEqual("Cancelled. Nothing was done.", asker.held_answer("cancel", other["id"])["say"])
        self.assertTrue(self.ask.HELD_REQUEST.match("run held 0a1b2c3d"))
        self.assertFalse(self.ask.HELD_REQUEST.match("please run held 0a1b2c3d"))

    def test_with_no_zone_settled_the_box_asks_which(self):
        out = self.asker().act_engine("file the inbox", {"Work": {}, "Personal": {}}, None)
        self.assertEqual("clarify", out["kind"])
        self.assertIn("Which zone", out["say"])


class TestPreparedCalls(unittest.TestCase):
    def test_a_prepared_call_counts_against_the_ledger_and_returns_the_session(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": tmp.name}):
            spec = importlib.util.spec_from_file_location("garrick_test_agent_prepared", str(REPO / "extras" / "jobs" / "agent.py"))
            agent = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(agent)
            out = json.dumps({"type": "result", "result": "ok", "session_id": "s-7", "usage": {"input_tokens": 5}, "num_turns": 1,
                              "total_cost_usd": 0.02})
            with mock.patch.object(agent, "call", return_value=(0, out, "")) as call:
                code, got = agent.run_prepared(["claude", "-p", "x"], "sonnet", job="ask", env={"GARRICK_ENGINE_ZONE": "Work"})
            self.assertEqual((0, "ok", "s-7", {"input_tokens": 5}), (code, got["text"], got["session_id"], got["usage"]))
            self.assertEqual(["/usr/bin/env", "GARRICK_ENGINE_ZONE=Work", "claude", "-p", "x"], call.call_args[0][0])
            ledger = [json.loads(l) for l in (Path(tmp.name) / "ledger.jsonl").read_text().splitlines()] if (Path(tmp.name) / "ledger.jsonl").exists() \
                else [json.loads(l) for p in Path(tmp.name).glob("*ledger*") for l in p.read_text().splitlines()]
            self.assertEqual(["ask"], [e["job"] for e in ledger])


if __name__ == "__main__":
    unittest.main()
