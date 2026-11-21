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
        self.assertTrue(any(t.startswith("Bash(python3 ") and "engine_cmd.py git commit:*)" in t for t in tools))
        for forbidden in ("curl", "gh ", "mail", "ssh", "scp", "rsync", "scaffold.py party", "intake.py learn", "page_action", "allow",
                          "git -C", "list", "process-notes", "intake.py", "scaffold.py"):
            self.assertFalse([t for t in tools if forbidden in t], forbidden)
        self.assertIn("mcp__garrick_hold__hold", tools)
        for tool in tools:
            self.assertNotRegex(tool, r"(?i)send|forward|share|trash|delete|Gmail|Calendar|Drive")
        self.assertIn("--strict-mcp-config", cmd)                      # the owner's connectors are not in the session
        servers = json.loads((folder / "mcp.json").read_text())["mcpServers"]
        self.assertEqual({"garrick", "garrick_hold"}, set(servers))

    def test_every_command_is_one_call_of_the_wrapper_and_none_names_a_zone(self):
        (cmd, _), _ = self.build()
        bash = [t for t in cmd[cmd.index("--allowedTools") + 1:] if t.startswith("Bash(")]
        self.assertTrue(bash)
        self.assertTrue(all("engine_cmd.py " in t for t in bash))
        self.assertTrue(all("Zones/Work" not in t for t in bash))          # the zone is the exchange's own environment, not a pattern
        self.assertFalse([t for t in bash if "intake list" in t or "process-notes" in t or " learn" in t])

    def test_the_guard_is_the_sessions_own_pre_tool_hook(self):
        (cmd, env), folder = self.build()
        settings = json.loads((folder / "settings.json").read_text())
        hook = settings["hooks"]["PreToolUse"][0]
        self.assertIn("Edit", hook["matcher"])
        self.assertIn("engine_guard.py", hook["hooks"][0]["command"])
        self.assertIn("Bash", hook["matcher"])
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


class TestHardenedGuard(EngineCase):
    def decide(self, path, tool="Write", zone="Work"):
        return self.guard.decide({"tool_name": tool, "tool_input": {"file_path": str(path)}}, str(self.root), zone)

    def test_the_notes_ledger_is_never_written_by_an_exchange(self):
        for name in ("notes-ledger.json", "notes-ledger.json.lock", "notes-ledger.json.new", "Notes-Ledger.json"):
            for tool in ("Write", "Edit"):
                got = self.decide(self.root / "System" / name, tool=tool)
                self.assertIsNotNone(got, name)
                self.assertIn("notes ledger", got["hookSpecificOutput"]["permissionDecisionReason"])

    def test_a_write_into_a_git_folder_or_a_git_file_is_refused_anywhere(self):
        for path in (self.work / ".git" / "config", self.work / ".git" / "hooks" / "pre-commit", self.work / ".GIT" / "config",
                     self.work / "Acme Review" / ".gitattributes", self.work / "Acme Review" / ".gitmodules",
                     self.work / "Acme Review" / ".GitAttributes", self.root / "Wikis" / "Meetings" / "wiki" / ".git" / "config"):
            self.assertIsNotNone(self.decide(path), path)
        self.assertIsNone(self.decide(self.work / "Acme Review" / "gitignore notes.md"))

    def test_a_dot_folder_or_dot_file_holds_settings_another_program_runs_and_is_refused(self):
        for path in (self.work / ".claude" / "settings.json", self.work / ".mcp.json", self.work / ".envrc",
                     self.work / ".vscode" / "tasks.json", self.work / ".codex" / "config.toml",
                     self.work / "Acme Review" / ".claude" / "settings.local.json", self.root / "Inbox" / ".hidden.md"):
            self.assertIsNotNone(self.decide(path), path)
        self.assertIsNone(self.decide(self.work / "Acme Review" / "Notes" / "251114 - v1.2 plan.md"))

    def test_only_a_wikis_wiki_folder_and_the_meetings_inbox_are_open(self):
        for path in (self.root / "Wikis" / "Meetings" / "wiki" / "x.md", self.root / "Wikis" / "Knowledge" / "wiki" / "sources" / "x.md",
                     self.root / "Wikis" / "Meetings" / "raw" / "inbox" / "x.md"):
            self.assertIsNone(self.decide(path), path)
        for path in (self.root / "Wikis" / "Meetings" / "raw" / "x.eml", self.root / "Wikis" / "Knowledge" / "raw" / "x.pdf",
                     self.root / "Wikis" / "Meetings" / "questions" / "x.md", self.root / "Wikis" / "x.md",
                     self.root / "Wikis" / "Knowledge" / "raw" / "inbox" / "x.md"):
            self.assertIsNotNone(self.decide(path), path)

    def test_a_refusal_exits_2_and_so_does_a_failure(self):
        script = str(STATUS / "engine_guard.py")
        env = dict(os.environ, GARRICK_ENGINE_WS=str(self.root), GARRICK_ENGINE_ZONE="Work")
        bad = {"tool_name": "Write", "tool_input": {"file_path": str(self.work / ".git" / "config")}}
        out = subprocess.run([sys.executable, script], input=json.dumps(bad), capture_output=True, text=True, env=env)
        self.assertEqual(2, out.returncode)
        self.assertEqual("deny", json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"])
        out = subprocess.run([sys.executable, script], input="not json", capture_output=True, text=True, env=env)
        self.assertEqual(2, out.returncode)
        fine = {"tool_name": "Write", "tool_input": {"file_path": str(self.work / "Todo.md")}}
        self.assertEqual(0, subprocess.run([sys.executable, script], input=json.dumps(fine), capture_output=True, text=True, env=env).returncode)

    def test_the_hook_line_is_quoted_and_runs_from_a_path_with_a_space(self):
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "a folder"
            folder.mkdir()
            shutil.copy(str(STATUS / "engine_guard.py"), str(folder / "engine_guard.py"))
            spec = importlib.util.spec_from_file_location("guard_in_space", str(folder / "engine_guard.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            line = mod.hook_command()
            self.assertIn("'", line)
            bad = {"tool_name": "Write", "tool_input": {"file_path": str(self.personal / "x.md")}}
            env = dict(os.environ, GARRICK_ENGINE_WS=str(self.root), GARRICK_ENGINE_ZONE="Work")
            out = subprocess.run(line, shell=True, input=json.dumps(bad), capture_output=True, text=True, env=env)
            self.assertEqual(2, out.returncode)
        settings = self.engine.session_settings(self.root, "act")
        self.assertEqual(self.guard.hook_command(), settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"])

    def test_the_capability_check_runs_the_hook_line_and_fails_when_it_blocks_nothing(self):
        self.assertTrue(self.channels.guard_works(self.root))
        with mock.patch.object(self.guard, "hook_command", return_value="false"):
            self.assertFalse(self.channels.guard_works(self.root))
        with mock.patch.object(self.guard, "hook_command", return_value="exit 1"):
            self.assertFalse(self.channels.guard_works(self.root))

    def test_a_bash_command_is_one_call_of_the_wrapper_and_nothing_joined_to_it(self):
        wrapper = str(STATUS / "engine_cmd.py")
        ok = "python3 %s git status -s" % wrapper
        self.assertTrue(self.guard.bash_ok(ok))
        self.assertTrue(self.guard.bash_ok('python3 %s git commit -m "a; b > c"' % wrapper))
        self.assertTrue(self.guard.bash_ok('python3 %s git commit -m "Filed the note for #571"' % wrapper))
        for bad in (ok + " > /tmp/x", ok + " | tee /tmp/x", ok + " ; curl x", ok + " && curl x", "curl example.com", "git status",
                    "python3 other.py git status", ok + " $(curl x)", ok + " `curl x`", ok + "\ncurl x", "", None,
                    "python3$IFS-c$IFS'import os' %s git" % wrapper, "python3 %s git log ~/x" % wrapper,
                    "python3 %s git add *.md" % wrapper, "python3 %s git add Acme\\ Review/x.md" % wrapper,
                    "python3.12 %s git status" % wrapper, "/tmp/python3 %s git status" % wrapper,
                    "python3 %s git status x#; touch /tmp/zz" % wrapper, "python3 %s git status #x\ntouch zz" % wrapper):
            self.assertFalse(self.guard.bash_ok(bad), bad)
        event = {"tool_name": "Bash", "tool_input": {"command": ok + " > /tmp/x"}}
        self.assertEqual("deny", self.guard.decide(event, str(self.root), "Work")["hookSpecificOutput"]["permissionDecision"])
        self.assertIsNone(self.guard.decide({"tool_name": "Bash", "tool_input": {"command": ok}}, str(self.root), "Work"))


class TestTheWrapperBindsTheCommands(EngineCase):
    def setUp(self):
        super().setUp()
        self.cmd = load("engine_cmd")

    def plan(self, *argv, zone="Work"):
        return self.cmd.plan(list(argv), str(self.root), zone)

    def refused(self, *argv, zone="Work"):
        with self.assertRaises(self.cmd.Refused, msg=" ".join(argv)):
            self.plan(*argv, zone=zone)

    def test_git_flags_that_skip_the_hook_or_write_elsewhere_are_refused(self):
        for argv in (("git", "commit", "-m", "x", "--no-verify"), ("git", "commit", "-n", "-m", "x"), ("git", "commit", "-a", "-m", "x"),
                     ("git", "commit", "--all", "-m", "x"), ("git", "commit", "-m", "x", "--amend"), ("git", "commit", "-F", "/etc/passwd"),
                     ("git", "commit", "-m", "x", "--author=x <y>"), ("git", "commit"), ("git", "commit", "-m", " "),
                     ("git", "log", "--output=/tmp/x"), ("git", "diff", "--output", "/tmp/x"), ("git", "diff", "--no-index", "/a", "/b"),
                     ("git", "diff", "--ext-diff"), ("git", "status", "-c", "core.x=y"), ("git", "add", "-A"), ("git", "add", "."),
                     ("git", "add", "--all"), ("git", "add"), ("git", "add", "../Personal/x.md"), ("git", "add", ".git/config"),
                     ("git", "add", "/etc/passwd"), ("git", "log", "--exec-path"), ("git", "status", "--git-dir=/x"),
                     ("git", "status", "--work-tree=/x"), ("git", "push"), ("git", "config", "x", "y"), ("git", "reset", "--hard")):
            self.refused(*argv)

    def test_a_name_is_never_a_path_and_the_owners_confirmation_is_not_offered(self):
        for argv in (("intake", "notes", "--project", "Acme Review", "--thread", "../../../../Personal/Home/Threads/Move"),
                     ("scaffold", "project", "--zone", "Work", "--name", "../Personal/X"),
                     ("scaffold", "project", "--zone", "Work", "--name", "Fine", "--thread", "a/b"),
                     ("scaffold", "thread", "--zone", "Work", "--project", "Acme Review", "--name", ".hidden"),
                     ("intake", "file-conversation", "--file", "Inbox/x.md", "--confirmed"),
                     ("intake", "file-to-project", "--file", "Inbox/x.md", "--project", "Acme Review", "--confirmed")):
            self.refused(*argv)

    def test_git_that_stays_in_the_zone_is_planned_with_the_zones_repository(self):
        cmd, _ = self.plan("git", "commit", "-m", "Work: filed a note")
        self.assertEqual(["git", "-C", str(self.work.resolve()), "--no-pager", "commit", "-m", "Work: filed a note"], cmd)
        cmd, _ = self.plan("git", "add", "Acme Review/Todo.md", "--", "Todo.md")
        self.assertEqual(["Acme Review/Todo.md", "--", "Todo.md"], cmd[-3:])
        cmd, _ = self.plan("git", "log", "-n", "3", "--oneline")
        self.assertIn("--no-ext-diff", cmd)
        self.plan("git", "diff", "--cached", "--stat")
        self.plan("git", "status", "-s")

    def test_a_real_commit_with_no_verify_is_refused_and_a_plain_one_runs_the_hook(self):
        env = dict(os.environ, GARRICK_ENGINE_WS=str(self.root), GARRICK_ENGINE_ZONE="Work")
        script = str(STATUS / "engine_cmd.py")
        write(self.work / "Acme Review" / "from-wrapper.md", "x\n")
        got = subprocess.run([sys.executable, script, "git", "commit", "-m", "x", "--no-verify"], capture_output=True, text=True, env=env)
        self.assertEqual(2, got.returncode)
        got = subprocess.run([sys.executable, script, "git", "add", "Acme Review/from-wrapper.md"], capture_output=True, text=True, env=env)
        self.assertEqual(0, got.returncode, got.stderr)
        got = subprocess.run([sys.executable, script, "git", "commit", "-q", "-m", "Work: from the wrapper"], capture_output=True, text=True, env=env)
        self.assertEqual(0, got.returncode, got.stderr)
        self.assertEqual("Work: from the wrapper", git(self.work, "log", "-1", "--format=%s").strip())

    def test_no_environment_binding_no_command(self):
        got = subprocess.run([sys.executable, str(STATUS / "engine_cmd.py"), "git", "status"], capture_output=True, text=True,
                             env={k: v for k, v in os.environ.items() if not k.startswith("GARRICK_ENGINE")})
        self.assertEqual(2, got.returncode)

    def test_scaffold_and_todo_take_the_exchanges_zone_only(self):
        cmd, _ = self.plan("scaffold", "project", "--zone", "work", "--name", "Birch", "--thread", "Intro")
        self.assertEqual(["project", "--zone", "Work", "--name", "Birch", "--thread", "Intro"], cmd[2:])
        cmd, _ = self.plan("scaffold", "thread", "--zone=Work", "--project", "Acme Review", "--name", "Kickoff")
        self.assertIn("Kickoff", cmd)
        self.refused("scaffold", "project", "--zone", "Personal", "--name", "Birch", "--thread", "Intro")
        self.refused("scaffold", "thread", "--zone", "Personal", "--project", "Home Move", "--name", "x")
        self.refused("scaffold", "thread", "--zone", "Work", "--project", "../../Personal/Home Move", "--name", "x")
        self.refused("scaffold", "project", "--name", "Birch", "--thread", "Intro")            # no zone given: refused, not defaulted
        self.refused("scaffold", "party", "--name", "x")
        self.refused("scaffold", "project", "--root", "/tmp", "--zone", "Work", "--name", "b", "--thread", "t")
        self.plan("todo", "digest", "--zone", "Work")
        self.refused("todo", "digest", "--zone", "Personal")
        self.refused("todo", "all", "--zone", "Work")
        self.plan("check", "--quick")
        self.refused("check", "--quick", "--fix")
        self.refused("check", "allow")

    def test_the_checkpoint_request_names_the_exchanges_zone(self):
        cmd, stdin = self.plan("scaffold", "checkpoint", "--json", json.dumps({"verb": "checkpoint", "zone": "Work", "project": "Acme Review"}))
        self.assertEqual(["checkpoint"], cmd[2:])
        self.assertIn("Acme Review", stdin)
        self.refused("scaffold", "checkpoint", "--json", json.dumps({"verb": "checkpoint", "zone": "Personal", "project": "Home Move"}))
        self.refused("scaffold", "checkpoint", "--json", "not json")

    def test_intake_is_bound_to_the_zones_inbox_and_projects(self):
        inbox = self.work / "Inbox"
        inbox.mkdir(exist_ok=True)
        mine = inbox / "a.md"
        mine.write_text("x")
        other = self.personal / "Inbox"
        other.mkdir(exist_ok=True)
        (other / "b.md").write_text("x")
        top = self.root / "Inbox"
        top.mkdir(exist_ok=True)
        (top / "c.md").write_text("x")
        cmd, _ = self.plan("intake", "file-note", "--file", str(mine), "--destination", "Acme, Pricing")
        self.assertEqual(str(mine.resolve()), cmd[cmd.index("--file") + 1])
        self.plan("intake", "file-to-project", "--file", str(mine), "--project", "Zones/Work/Acme Review")
        self.plan("intake", "notes", "--project", "Acme Review")
        self.plan("intake", "parse", "--file", str(top / "c.md"))
        self.plan("intake", "move-to-zone", "--file", str(top / "c.md"), "--zone", "Work")
        self.refused("intake", "file-note", "--file", str(other / "b.md"))
        self.refused("intake", "file-note", "--file", str(top / "c.md"))                       # a note is filed from the zone's inbox
        self.refused("intake", "file-note", "--file", str(mine) + "/../../../Personal/Inbox/b.md")
        self.refused("intake", "move-to-zone", "--file", str(top / "c.md"), "--zone", "Personal")
        self.refused("intake", "file-to-project", "--file", str(mine), "--project", "Zones/Personal/Home Move")
        self.refused("intake", "file-to-project", "--file", str(mine), "--project", "../Personal/Home Move")
        self.refused("intake", "notes", "--project", "Zones/Personal/Home Move")
        self.refused("intake", "extract-attachment", "--mail", "x", "--project", "Zones/Personal/Home Move")
        self.refused("intake", "list")
        self.refused("intake", "list", "--json")
        self.refused("intake", "process-notes", "--dry-run")
        self.refused("intake", "learn", "--domain", "x.com", "--party", "x")
        self.refused("intake", "parse", "--file", str(mine), "--root", "/tmp")

    def test_a_link_out_of_the_inbox_is_judged_where_it_leads(self):
        inbox = self.work / "Inbox"
        inbox.mkdir(exist_ok=True)
        other = self.personal / "Inbox"
        other.mkdir(exist_ok=True)
        (other / "b.md").write_text("x")
        (inbox / "link.md").symlink_to(other / "b.md")
        self.refused("intake", "parse", "--file", str(inbox / "link.md"))


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


class TestBoundedRun(EngineCase):
    """#592: one bounded edit, or one commit, in one zone or one wiki, through the repository's own hook."""

    def setUp(self):
        super().setUp()
        self.rel = "Zones/Work/Acme Review/Threads/Pricing/Pricing.md"
        self.file = self.root / self.rel
        self.hook = self.work / ".git" / "hooks" / "pre-commit"

    def edit(self, text="Shorter.\n", extra=None):
        def act(cmd, env):
            self.file.write_text(self.file.read_text() + text)
            for path, body in (extra or {}).items():
                write(path, body)
        return self.runner("Done.", act=act)

    def head(self):
        return git(self.work, "rev-parse", "HEAD").strip()

    def test_an_edit_is_committed_with_the_trailer_through_the_hook(self):
        self.hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\ntouch \"$(git rev-parse --git-dir)/hook-ran\"\n")
        before = self.head()
        run = self.edit()
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "Work: shorten the resume point", run, self.cap_ok)
        self.assertTrue(got["ok"], got)
        self.assertEqual(("Zones/Work", [self.rel]), (got["repo"], got["files"]))
        self.assertEqual(got["commit"], self.head())
        self.assertNotEqual(before, self.head())
        body = git(self.work, "log", "-1", "--format=%B")
        self.assertTrue(body.startswith("Work: shorten the resume point"))
        self.assertRegex(body, r"Garrick-Bounded: [0-9a-f]{8}")
        self.assertTrue((self.work / ".git" / "hook-ran").exists())                       # the hook ran: never --no-verify
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_the_session_has_no_git_add_or_commit_and_runs_at_act_on_the_ask_tier(self):
        run = self.edit()
        self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", run, self.cap_ok)
        cmd = run.seen[0]["cmd"]
        allowed = " ".join(cmd[cmd.index("--allowedTools"):])
        self.assertNotIn(" git add", allowed)
        self.assertNotIn(" git commit", allowed)
        self.assertIn(" git diff", allowed)
        self.assertIn("Edit", allowed)
        self.assertEqual("sonnet", run.seen[0]["tier"])
        self.assertIn("<autonomy>act</autonomy>", cmd[cmd.index("-p") + 1])

    def test_c11_each_file_is_read_once_through_a_refused_commit(self):
        """#600 C11: the files git reports changed are read once per state they are in, not once for every snapshot."""
        import collections
        import pathlib
        other = self.root / "Zones" / "Work" / "Acme Review" / "Notes" / "loose.md"
        write(other, "A note nobody committed.\n")
        self.hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\necho refused >&2\nexit 1\n")
        reads = collections.Counter()
        real = pathlib.Path.read_bytes

        def counting(path):
            reads[str(path)] += 1
            return real(path)
        with mock.patch.object(pathlib.Path, "read_bytes", counting):
            got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", self.edit(), self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertTrue(reads[str(other)] or reads[str(self.file)], "the check read the changed files")
        self.assertEqual([], [(p, n) for p, n in reads.items() if n > 1])
        self.assertEqual("A note nobody committed.\n", other.read_text())                 # what it restores is unchanged

    def test_a_refused_commit_leaves_no_edit(self):
        self.hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\necho refused >&2\nexit 1\n")
        before, text = self.head(), self.file.read_text()
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", self.edit(), self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertIn("refused", got["say"])
        self.assertEqual((before, text), (self.head(), self.file.read_text()))
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_a_change_outside_the_file_fails_and_only_the_named_file_is_put_back(self):
        other = self.work / "Acme Review" / "Stray.md"
        todo = self.work / "Todo.md"
        was = todo.read_text()
        run = self.edit(extra={other: "stray\n"})
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", run, self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertTrue(other.exists())                  # not named: never deleted (N2); the guard stops a real run writing it
        self.assertNotIn("Shorter.", self.file.read_text())
        self.assertEqual(was, todo.read_text())
        self.assertEqual("?? \"Acme Review/Stray.md\"", git(self.work, "status", "--porcelain").strip())   # only the stray is left

    def test_an_assistant_that_commits_on_its_own_is_a_failure(self):
        def act(cmd, env):
            self.file.write_text(self.file.read_text() + "x\n")
            git(self.work, "commit", "-qam", "its own")
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", self.runner("Done.", act=act), self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertIn("commit of its own", got["say"])

    def test_every_path_is_checked_before_anything_runs(self):
        run = self.runner()
        wiki = self.root / "Wikis" / "Meetings"
        write(wiki / "raw" / "a.md", "raw\n")
        git(self.root / "Wikis" / "Meetings", "init", "-q")
        bad = [("Work", ["Zones/Personal/Home Move/Home Move.md"]), ("Work", ["../Personal/x.md"]), ("Work", ["/etc/passwd"]),
               ("Work", ["Zones/Work/Missing.md"]), ("Work", ["Zones/Work/.git/config"]), ("Work", []), ("Work", [None]),
               ("Nowhere", [self.rel]), ("Work/x", [self.rel]), ("..", [self.rel]), ("Meetings", ["Wikis/Meetings/raw/a.md"]),
               ("Meetings", [self.rel]), ("Work", ["Wikis/Meetings/raw/a.md"])]
        for zone, files in bad:
            got = self.engine.run_bounded(self.root, zone, files, "Shorten it", "m", run, self.cap_ok)
            self.assertFalse(got["ok"], (zone, files))
            self.assertNotIn("unavailable", got)
        self.assertEqual([], run.seen)                                                      # nothing ran for any of them

    def test_a_symlink_out_of_the_zone_is_refused(self):
        link = self.work / "Acme Review" / "out.md"
        link.symlink_to(self.personal / "Home Move" / "Home Move.md")
        run = self.runner()
        got = self.engine.run_bounded(self.root, "Work", ["Zones/Work/Acme Review/out.md"], "Shorten it", "m", run, self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertEqual([], run.seen)

    def test_a_file_with_unsaved_changes_is_refused(self):
        self.file.write_text(self.file.read_text() + "mine\n")
        run = self.edit()
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", run, self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertEqual([], run.seen)
        self.assertIn("mine", self.file.read_text())

    def test_an_unavailable_engine_touches_nothing(self):
        run = self.edit()
        bad = dict(self.cap_ok, ok=False, failed=["resume"], said=["x"])
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", run, bad)
        self.assertEqual((False, True), (got["ok"], got.get("unavailable")))
        self.assertEqual([], run.seen)
        self.settings(ask={"autonomy": "read"})
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", run, self.cap_ok)
        self.assertTrue(got.get("unavailable"))
        self.assertEqual([], run.seen)
        with mock.patch.dict(os.environ, {"GARRICK_HARNESS": "codex"}):
            self.settings(ask={"autonomy": "act"})
            self.assertTrue(self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", run, self.cap_ok).get("unavailable"))
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_a_held_send_is_cancelled_and_the_edit_is_not_kept(self):
        def act(cmd, env):
            self.file.write_text(self.file.read_text() + "x\n")
            self.hold.add("ask", "Work", env["GARRICK_ENGINE_EXCHANGE"], "Send it", "dana@example.com",
                          {"tool": "mcp__mail__send_message", "args": {"to": "dana@example.com"}})
        before = self.head()
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", self.runner("Done.", act=act), self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertEqual(before, self.head())
        self.assertNotIn("x\n", self.file.read_text())
        self.assertEqual([], self.hold.pending())

    def test_a_commit_only_request_commits_just_the_files_named_and_the_assistant_writes_the_message(self):
        other = self.work / "Todo.md"
        other.write_text(other.read_text() + "- [ ] stray\n")
        self.file.write_text(self.file.read_text() + "made by hand\n")
        run = self.runner("Work: add a line to the Pricing resume point")
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "", "", run, self.cap_ok)
        self.assertTrue(got["ok"], got)
        self.assertEqual("Work: add a line to the Pricing resume point", git(self.work, "log", "-1", "--format=%s").strip())
        self.assertEqual(" M Todo.md", git(self.work, "status", "--porcelain").rstrip())     # the other file is not in it
        self.assertIn("<autonomy>read</autonomy>", run.seen[0]["cmd"][run.seen[0]["cmd"].index("-p") + 1])

    def test_a_wiki_page_is_bounded_to_its_wiki(self):
        wiki = self.root / "Wikis" / "Meetings"
        write(wiki / "wiki" / "261012 - Call.md", "---\ntitle: Call\n---\nlong\n")
        git(wiki, "init", "-q")
        for cfg in (("user.name", "Sam Rivera"), ("user.email", "sam@example.com"), ("gc.auto", "0"), ("maintenance.auto", "false")):
            git(wiki, "config", *cfg)
        git(wiki, "add", "-A")
        git(wiki, "commit", "-q", "-m", "start")
        rel = "Wikis/Meetings/wiki/261012 - Call.md"

        def act(cmd, env):
            (self.root / rel).write_text("---\ntitle: Call\n---\nshort\n")
        got = self.engine.run_bounded(self.root, "Meetings", [rel], "Shorten it", "Meetings: shorten the call", self.runner("ok", act=act), self.cap_ok)
        self.assertTrue(got["ok"], got)
        self.assertEqual("Wikis/Meetings", got["repo"])
        self.assertEqual("Meetings: shorten the call", git(wiki, "log", "-1", "--format=%s").strip())

    def test_undo_reverts_only_a_bounded_commit_nobody_touched_since(self):
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", self.edit("one more\n"), self.cap_ok)
        self.assertTrue(got["ok"], got)
        undone = self.engine.undo_bounded(self.root, got["repo"], got["commit"])
        self.assertTrue(undone["ok"], undone)
        self.assertNotIn("one more", self.file.read_text())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        self.assertTrue(git(self.work, "log", "-1", "--format=%s").startswith("Undo:"))

    def test_undo_refuses_when_a_later_commit_touched_the_file(self):
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", self.edit("one more\n"), self.cap_ok)
        self.file.write_text(self.file.read_text() + "later\n")
        git(self.work, "commit", "-qam", "later edit")
        head = self.head()
        undone = self.engine.undo_bounded(self.root, got["repo"], got["commit"])
        self.assertFalse(undone["ok"])
        self.assertEqual(head, self.head())
        self.assertIn("one more", self.file.read_text())

    def test_undo_refuses_a_commit_that_run_bounded_did_not_make(self):
        self.file.write_text(self.file.read_text() + "by hand\n")
        git(self.work, "commit", "-qam", "by hand")
        head = self.head()
        undone = self.engine.undo_bounded(self.root, "Zones/Work", head)
        self.assertFalse(undone["ok"])
        self.assertEqual(head, self.head())
        for repo, commit in (("Zones/Work", "zzz"), ("Zones", head), ("Zones/Nowhere", head), ("Wikis/Work", head), ("../x", head), (None, head)):
            self.assertFalse(self.engine.undo_bounded(self.root, repo, commit)["ok"])

    def test_undo_refused_by_the_hook_changes_nothing(self):
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", self.edit("one more\n"), self.cap_ok)
        self.hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\nexit 1\n")
        head = self.head()
        undone = self.engine.undo_bounded(self.root, got["repo"], got["commit"])
        self.assertFalse(undone["ok"])
        self.assertEqual(head, self.head())
        self.assertIn("one more", self.file.read_text())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())


class TestBoundedRunFixes(EngineCase):
    """0.70.0's fix round: what a bounded run may change, restore and commit."""

    def setUp(self):
        super().setUp()
        self.rel = "Zones/Work/Acme Review/Threads/Pricing/Pricing.md"
        self.file = self.root / self.rel
        self.hook = self.work / ".git" / "hooks" / "pre-commit"

    def edit(self, text="Shorter.\n", also=None):
        def act(cmd, env):
            self.file.write_text(self.file.read_text() + text)
            if also:
                also()
        return self.runner("Done.", act=act)

    def head(self, repo=None):
        return git(repo or self.work, "rev-parse", "HEAD").strip()

    def made(self, text="one more\n"):
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", self.edit(text), self.cap_ok)
        self.assertTrue(got["ok"], got)
        return got

    def wiki(self, own=True):
        wiki = self.root / "Wikis" / "Meetings"
        write(wiki / "wiki" / "261012 - Call.md", "---\ntitle: Call\n---\nlong\n")
        other = self.root / "Wikis" / "Knowledge"
        write(other / "wiki" / "Vendor.md", "---\ntitle: Vendor\n---\nfacts\n")
        top = wiki if own else self.root / "Wikis"
        git(top, "init", "-q")
        for cfg in (("user.name", "Sam Rivera"), ("user.email", "sam@example.com"), ("gc.auto", "0"), ("maintenance.auto", "false")):
            git(top, "config", *cfg)
        git(top, "add", "-A")
        git(top, "commit", "-q", "-m", "start")
        return top, "Wikis/Meetings/wiki/261012 - Call.md"

    # S1
    def test_undo_refuses_when_something_else_is_staged_and_changes_nothing(self):
        got = self.made()
        write(self.work / "Acme Review" / "Other.md", "mine\n")
        git(self.work, "add", "Acme Review/Other.md")
        head = self.head()
        undone = self.engine.undo_bounded(self.root, got["repo"], got["commit"])
        self.assertFalse(undone["ok"])
        self.assertEqual(head, self.head())
        self.assertRegex(git(self.work, "status", "--porcelain").rstrip(), r'^A  "?Acme Review/Other.md"?$')
        self.assertIn("one more", self.file.read_text())

    def test_the_undo_commit_holds_the_reverted_files_only(self):
        got = self.made()
        undone = self.engine.undo_bounded(self.root, got["repo"], got["commit"])
        self.assertTrue(undone["ok"], undone)
        self.assertEqual("Acme Review/Threads/Pricing/Pricing.md", git(self.work, "show", "--name-only", "--format=", "HEAD").strip())

    # S2
    def test_a_file_that_was_dirty_before_and_changed_during_the_run_is_left_as_it_is(self):
        mine = self.work / "Todo.md"
        mine.write_text(mine.read_text() + "- [ ] mine\n")
        was = mine.read_text()
        run = self.edit(also=lambda: mine.write_text(was + "- [ ] changed while it ran\n"))
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", run, self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertIn("not given", got["say"])
        self.assertIn("changed while it ran", mine.read_text())                         # never reverted
        self.assertNotIn("Shorter.", self.file.read_text())                              # the named file is put back

    def test_a_tracked_clean_file_the_run_changed_is_left_and_reported_not_reverted(self):
        todo = self.work / "Todo.md"
        run = self.edit(also=lambda: todo.write_text(todo.read_text() + "- [ ] from the run\n"))
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", run, self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertIn("not given", got["say"])
        self.assertIn("from the run", todo.read_text())
        self.assertNotIn("Shorter.", self.file.read_text())

    def test_a_new_file_someone_else_makes_during_a_failed_run_is_kept(self):
        theirs = self.work / "Inbox note.md"
        run = self.edit(also=lambda: theirs.write_text("made by another session\n"))
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", run, self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertTrue(theirs.exists())                                                 # never deleted
        self.assertNotIn("Shorter.", self.file.read_text())

    # C7
    def test_a_refused_commit_keeps_what_was_staged_before(self):
        self.file.write_text(self.file.read_text() + "made by hand\n")
        git(self.work, "add", str(self.file))
        self.hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\nexit 1\n")
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "", "m", self.runner(), self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertRegex(git(self.work, "status", "--porcelain").rstrip(), r'^M  "?Acme Review/Threads/Pricing/Pricing.md"?$')

    # C3
    def test_a_wiki_without_a_repository_of_its_own_uses_the_one_of_wikis(self):
        top, rel = self.wiki(own=False)

        def act(cmd, env):
            (self.root / rel).write_text("---\ntitle: Call\n---\nshort\n")
        got = self.engine.run_bounded(self.root, "Meetings", [rel], "Shorten it", "Meetings: shorten the call", self.runner("ok", act=act), self.cap_ok)
        self.assertTrue(got["ok"], got)
        self.assertEqual("Wikis/Meetings", got["repo"])
        self.assertEqual("Meetings: shorten the call", git(top, "log", "-1", "--format=%s").strip())
        undone = self.engine.undo_bounded(self.root, got["repo"], got["commit"], rel)
        self.assertTrue(undone["ok"], undone)
        self.assertIn("long", (self.root / rel).read_text())

    def test_a_change_in_the_other_wiki_of_the_shared_repository_fails_the_run(self):
        top, rel = self.wiki(own=False)
        stray = self.root / "Wikis" / "Knowledge" / "wiki" / "Stray.md"

        def act(cmd, env):
            (self.root / rel).write_text("---\ntitle: Call\n---\nshort\n")
            stray.write_text("stray\n")
        before = self.head(top)
        got = self.engine.run_bounded(self.root, "Meetings", [rel], "Shorten it", "m", self.runner("ok", act=act), self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertEqual(before, self.head(top))
        self.assertTrue(stray.exists())                                             # not named: left as it is (N2); the guard stops a real run writing it
        self.assertIn("long", (self.root / rel).read_text())

    def test_a_wiki_with_no_repository_at_all_is_unavailable_and_touches_nothing(self):
        write(self.root / "Wikis" / "Meetings" / "wiki" / "261012 - Call.md", "long\n")
        run = self.runner()
        got = self.engine.run_bounded(self.root, "Meetings", ["Wikis/Meetings/wiki/261012 - Call.md"], "Shorten it", "m", run, self.cap_ok)
        self.assertEqual((False, True), (got["ok"], got.get("unavailable")))
        self.assertEqual([], run.seen)

    # W3
    def test_the_guard_is_bound_to_the_files_of_the_run(self):
        run = self.edit()
        self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", run, self.cap_ok)
        env = run.seen[0]["env"]
        self.assertEqual([self.rel], json.loads(env["GARRICK_ENGINE_ONLY"]))
        plain = self.runner()
        self.engine.run(self.root, "ask", "hello", "Work", {"id": "x1"}, plain, self.cap_ok)
        self.assertNotIn("GARRICK_ENGINE_ONLY", plain.seen[0]["env"])

    def test_the_guard_refuses_any_write_but_the_named_files(self):
        only = self.guard.only_files(json.dumps([self.rel]), str(self.root))
        for path in ("Zones/Work/Acme Review/Other.md", "Wikis/Knowledge/wiki/Vendor.md", "Inbox/x.md", "Zones/Work/Todo.md"):
            event = {"tool_name": "Write", "tool_input": {"file_path": str(self.root / path)}, "cwd": str(self.root)}
            self.assertIsNotNone(self.guard.decide(event, str(self.root), "Work", only), path)
            self.assertIsNone(self.guard.decide(event, str(self.root), "Work") if path.startswith("Zones/Work") else None)
        event = {"tool_name": "Edit", "tool_input": {"file_path": str(self.file)}, "cwd": str(self.root)}
        self.assertIsNone(self.guard.decide(event, str(self.root), "Work", only))
        for bad in ("", "nope", "[]", "{}", '[1]'):
            with self.assertRaises(Exception):
                self.guard.only_files(bad, str(self.root))

    def test_a_change_in_another_zone_after_the_run_fails_it(self):
        stray = self.personal / "Home Move" / "Stray.md"
        git(self.personal, "init", "-q")
        run = self.edit(also=lambda: stray.write_text("stray\n"))
        before = self.head()
        got = self.engine.run_bounded(self.root, "Work", [self.rel], "Shorten it", "m", run, self.cap_ok)
        self.assertFalse(got["ok"])
        self.assertEqual(before, self.head())
        self.assertNotIn("Shorter.", self.file.read_text())

    # W2 and C2
    def test_a_commit_only_call_takes_fifty_files_and_an_edit_takes_eight(self):
        files = []
        for n in range(12):
            path = self.work / "Acme Review" / ("Bulk%02d.md" % n)
            write(path, "x\n")
            files.append("Zones/Work/Acme Review/Bulk%02d.md" % n)
        run = self.runner("Work: add the bulk pages")
        got = self.engine.run_bounded(self.root, "Work", files, "", "", run, self.cap_ok)
        self.assertTrue(got["ok"], got)
        self.assertEqual(12, len(got["files"]))
        many = ["Zones/Work/Acme Review/Bulk%02d.md" % n for n in range(9)]
        self.assertFalse(self.engine.run_bounded(self.root, "Work", many, "Shorten it", "m", self.runner(), self.cap_ok)["ok"])
        self.assertFalse(self.engine.run_bounded(self.root, "Work", many * 6, "", "m", self.runner(), self.cap_ok)["ok"])

    def test_a_deleted_file_is_committed_when_git_shows_it_changed(self):
        gone = self.work / "Acme Review" / "Gone.md"
        write(gone, "x\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "add gone")
        gone.unlink()
        rel = "Zones/Work/Acme Review/Gone.md"
        got = self.engine.run_bounded(self.root, "Work", [rel], "", "Work: remove the page", self.runner(), self.cap_ok)
        self.assertTrue(got["ok"], got)
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        # a file that is neither there nor changed is refused, and so is one outside the folder
        self.assertFalse(self.engine.run_bounded(self.root, "Work", ["Zones/Work/Acme Review/Never.md"], "", "m", self.runner(), self.cap_ok)["ok"])
        self.assertFalse(self.engine.run_bounded(self.root, "Work", ["Zones/Personal/Gone.md"], "", "m", self.runner(), self.cap_ok)["ok"])
        self.assertFalse(self.engine.run_bounded(self.root, "Work", ["Zones/Work/../Personal/Gone.md"], "", "m", self.runner(), self.cap_ok)["ok"])

    # S6
    def test_a_finding_undo_acts_only_on_a_commit_of_its_own_page(self):
        got = self.made()
        other = "Zones/Work/Acme Review/Acme Review.md"
        req = {"verb": "finding", "kind": "resume-long", "answer": "undo-bounded", "path": other, "commit": got["commit"], "repo": got["repo"]}
        with self.assertRaises(self.pa.Refused):
            self.pa.answer_finding(self.root, req, None)
        self.assertIn("one more", self.file.read_text())
        req = dict(req, path=self.rel, repo="Zones/Personal")
        with self.assertRaises(self.pa.Refused):
            self.pa.answer_finding(self.root, req, None)
        self.assertIn("one more", self.file.read_text())
        done = self.pa.answer_finding(self.root, dict(req, repo=got["repo"]), None)
        self.assertIn("Undone", done["say"])
        self.assertNotIn("one more", self.file.read_text())

    # S7
    def test_a_trailer_line_in_the_middle_of_a_message_is_not_the_trailer(self):
        self.file.write_text(self.file.read_text() + "by hand\n")
        git(self.work, "commit", "-qam", "by hand\n\nGarrick-Bounded: abcd1234\n\nand then more words")
        head = self.head()
        self.assertFalse(self.engine.undo_bounded(self.root, "Zones/Work", head)["ok"])
        self.assertEqual(head, self.head())
        got = self.made("again\n")
        self.assertTrue(self.engine.undo_bounded(self.root, got["repo"], got["commit"])["ok"])

    # C6
    def test_the_commit_subject_of_a_finding_is_a_fixed_sentence_with_no_path(self):
        seen = {}

        class Stub:
            @staticmethod
            def run_bounded(ws, zone, files, request, message="", *a, **k):
                seen.update(message=message)
                return {"ok": False, "say": "no"}
        with mock.patch.object(self.pa, "engine_module", lambda: Stub):
            for kind, answer in (("wall", "take-out"), ("resume-long", "shorten"), ("meeting-long", "shorten"), ("fix-failed", "fix-now")):
                with self.assertRaises(self.pa.Refused):
                    self.pa.finding_bounded(self.root, {}, kind, answer, self.rel)
                self.assertTrue(seen["message"] and "/" not in seen["message"] and "Pricing" not in seen["message"], seen)


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


class TestWhatTheOwnerSees(EngineCase):
    def test_a_tool_must_be_a_connector_tool_that_sends_shares_or_deletes(self):
        for tool in ("Bash", "mcp__mail__", "mcp__mail__forward --x", "mcp__mail__forward;ls", "mail__forward", "../mcp__a__send", "",
                     "mcp__gmail__create_draft", "mcp__gmail__list_threads", "mcp__a__b__c d"):
            with self.assertRaises(ValueError, msg=tool):
                self.hold.add("ask", "Work", "e1", "x", "y", {"tool": tool, "args": {}})
        for tool in ("mcp__mail__forward", "mcp__claude_ai_Gmail__send_message", "mcp__drive__share_file", "mcp__drive__delete_file"):
            self.hold.add("ask", "Work", "e1", "x", "y", {"tool": tool, "args": {}})
        with self.assertRaises(ValueError):
            self.hold.add("ask", "Work", "e1", "x", "y", {"tool": "mcp__mail__forward", "args": "to=x"})
        self.assertEqual([], self.hold.pending(channel="telegram"))

    def test_the_hold_tool_refuses_an_unknown_tool(self):
        text, bad = self.tools.call({"what": "x", "where": "y", "tool": "Bash", "args": {}})
        self.assertTrue(bad)
        self.assertEqual([], self.hold.pending())

    def test_the_confirmation_shows_the_tool_and_the_recipients_from_the_arguments(self):
        entry = self.hold.add("telegram", "Work", "e1", "Forward the price sheet", "Dana", {
            "tool": "mcp__claude_ai_Gmail__send_message",
            "args": {"to": ["eve@example.net", "dana@example.com"], "cc": "bob@example.org", "bcc": [{"email": "fay@example.io"}],
                     "body": "long private text"}})
        said = self.hold.say(entry)
        for expected in ("Forward the price sheet (Dana)?", "tool send_message", "eve@example.net, dana@example.com", "bob@example.org",
                         "fay@example.io"):
            self.assertIn(expected, said)
        self.assertNotIn("long private text", said)
        self.assertIn("send_message", self.hold.listing()[0]["detail"])

    def test_a_shared_write_shows_its_path(self):
        entry = self.hold.add("ask", "Work", "e1", "Write the brief", "team folder", {"write": ".shared/team/brief.md", "text": "hi"})
        self.assertIn(".shared/team/brief.md", self.hold.say(entry))

    def test_a_held_action_with_a_made_up_tool_never_reaches_the_assistant(self):
        run = self.runner("x")
        for tool in ("Bash", "mcp__gmail__create_draft", "mcp__mail__forward --dangerously"):
            ok, said = self.engine.execute_held(self.root, {"request": {"tool": tool, "args": {}}}, run)
            self.assertFalse(ok, tool)
        self.assertEqual([], run.seen)

    def test_two_yes_replies_run_the_action_once(self):
        import threading
        entry = self.hold.add("telegram", "Work", "e1", "Forward it", "Dana", {"tool": "mcp__mail__forward", "args": {}})
        did, out = [], []

        def runner(ws, rec):
            did.append(1)
            time.sleep(0.3)
            return True, "Sent."
        threads = [threading.Thread(target=lambda: out.append(self.hold.run(entry["id"], self.root, runner))) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(1, len(did))
        self.assertEqual(3, out.count("That action is not waiting any more."))
        self.assertEqual("done", self.hold.get(entry["id"])["state"])

    def test_writes_from_two_threads_are_all_kept(self):
        import threading
        threads = [threading.Thread(target=lambda: self.hold.add("ask", "Work", "e1", "x", "y", {"tool": "mcp__mail__forward", "args": {}}))
                   for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(12, len(self.hold.load()["held"]))


class TestAPartialSave(EngineCase):
    def test_a_partial_channels_save_keeps_the_other_keys(self):
        self.settings(telegram={"tier": "opus", "effort": "high"})
        self.settings(telegram={"autonomy": "read"})
        self.assertEqual({"tier": "opus", "effort": "high", "autonomy": "read"}, self.channels.settings(self.root)["telegram"])
        self.settings(ask={"effort": "low"})
        self.assertEqual({"tier": "sonnet", "effort": "low", "autonomy": "act"}, self.channels.settings(self.root)["ask"])
        self.assertEqual({"tier": "opus", "effort": "high", "autonomy": "read"}, self.channels.settings(self.root)["telegram"])

    def test_a_hand_edited_full_for_telegram_does_not_block_a_save_and_is_not_kept(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"channels": {"telegram": {"autonomy": "full", "tier": "opus"}}}))
        self.settings(telegram={"effort": "low"})
        self.assertEqual({"tier": "opus", "effort": "low", "autonomy": "act"}, self.channels.settings(self.root)["telegram"])


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
    def test_a_prepared_call_stopped_at_its_limit_records_an_estimate_not_null(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": tmp.name}):
            spec = importlib.util.spec_from_file_location("garrick_test_agent_estimate", str(REPO / "extras" / "jobs" / "agent.py"))
            agent = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(agent)
            seen = []
            agent.estimated_cost = lambda tier, seconds, budget=0: seen.append((tier, budget)) or 0.25   # the jobs release's estimate
            with mock.patch.object(agent, "call", return_value=(agent.EXIT_TIMEOUT, "", "")):
                code, got = agent.run_prepared(["claude", "-p", "x"], "sonnet", job="ask", timeout=1)
            self.assertEqual(agent.EXIT_TIMEOUT, code)
            self.assertEqual(0.25, got["cost_usd"])
            self.assertTrue(got["estimated"])
            self.assertEqual("sonnet", seen[0][0])


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
