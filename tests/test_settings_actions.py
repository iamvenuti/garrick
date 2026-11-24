"""Settings' two actions (#621): this computer's role, and the read guard. Both are the page's own buttons, so a session and
a command line that only says `--via page` are refused. Every failure each can show is one plain sentence with one next step,
and the tool's own words are kept for Details (#511). A fake HOME holds the role file and each assistant's settings; this
Mac's own are never read or written.

    cd tests && python3 -m unittest test_settings_actions
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import test_page_action as base  # noqa: E402

pa = base.pa
SCRIPT = base.SCRIPT
REPO = Path(__file__).resolve().parent.parent
MACHINE = REPO / "template" / "System" / "tools" / "machine.py"


class SettingsCase(base.ActionCase):
    def setUp(self):
        super().setUp()
        self.home = Path(self._tmp.name).resolve() / "home"
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.settings_file = self.root / "System" / "garrick-settings.json"

    def go(self, req, via="page"):
        """One request as the app's bridge sends it (the check for the app's process replaced in this process), or as a
        session sends it; the reply the command prints."""
        out = io.StringIO()
        with mock.patch.object(pa, "page_route", return_value=True), mock.patch.object(sys, "stdin", io.StringIO(json.dumps(req))), \
                contextlib.redirect_stdout(out):
            pa.main(["--workspace", str(self.root), "--via", via])
        return json.loads(out.getvalue())

    def saved(self):
        try:
            return json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def role_file(self):
        path = self.home / ".config" / "garrick" / "machine.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def assistants(self, claude=True, codex=True):
        if claude:
            (self.home / ".claude").mkdir(exist_ok=True)
        if codex:
            (self.home / ".codex").mkdir(exist_ok=True)

    def claude(self):
        return json.loads((self.home / ".claude" / "settings.json").read_text(encoding="utf-8"))

    def failed(self, out, code):
        """A refusal that names its row: not ok, nothing saved, the row's sentence and next step, the tool's words kept."""
        self.assertFalse(out["ok"], out)
        self.assertEqual(code, out["plain"]["code"], out)
        row = next(r for r in pa.FAILURES if r[0] == code)
        self.assertEqual((row[1], row[2]), (out["plain"]["say"], out["plain"]["next"]))
        self.assertTrue(out["say"].strip())
        self.assertNotEqual(row[1], out["say"])                       # the tool's own words, for Details


class TestOnlyTheApp(SettingsCase):
    def subprocess_reply(self, req, via):
        argv = [sys.executable, str(SCRIPT), "--workspace", str(self.root)] + (["--via", via] if via else [])
        done = subprocess.run(argv, input=json.dumps(req), capture_output=True, text=True,
                              env=dict(os.environ, GARRICK_JOBS_DIR=str(self.jobs), HOME=str(self.home)))
        return json.loads(done.stdout)

    REQUESTS = ({"verb": "machine-role", "role": "server", "name": "mini"}, {"verb": "read-guard", "mode": "warn"},
                {"verb": "connected-service", "service": "Weather", "choice": "leave"})

    def test_a_session_and_a_command_line_that_says_page_are_refused_and_nothing_is_written(self):
        self.assistants()
        for req in self.REQUESTS:
            for via in ("session", "page", None):
                with self.subTest(verb=req["verb"], via=via):
                    out = self.subprocess_reply(req, via)
                    self.assertFalse(out["ok"], out)
                    self.assertEqual(pa.PAGE_REFUSED, out["say"])
        self.assertIsNone(self.role_file())
        self.assertFalse((self.home / ".claude" / "settings.json").exists())
        self.assertEqual({}, self.saved())

    def test_both_are_the_pages_own_verbs_and_declared(self):
        for verb in ("machine-role", "read-guard", "connected-service"):
            self.assertIn(verb, pa.PAGE_ONLY)
            self.assertIn(verb, pa.VERBS)
            self.assertIn(verb, pa.ops_lib(self.root).DECLARED)

    def test_the_ask_box_is_refused_too(self):
        for req in self.REQUESTS:
            out, _, _ = pa.perform(self.root, req, pa.ops_lib(self.root), via="ask")
            self.assertFalse(out["ok"])
        self.assertIsNone(self.role_file())


class TestTheRole(SettingsCase):
    def test_it_writes_what_machine_py_set_writes(self):
        out = self.go({"verb": "machine-role", "role": "roaming", "name": "laptop", "server": "mini"})
        self.assertTrue(out["ok"], out)
        self.assertEqual("This computer is now a laptop copy of mini.", out["say"])
        other = Path(self._tmp.name) / "other-home"
        other.mkdir()
        subprocess.run([sys.executable, str(MACHINE), "set", "--role", "roaming", "--name", "laptop", "--server", "mini"],
                       env=dict(os.environ, HOME=str(other)), check=True, capture_output=True)
        mine = (self.home / ".config" / "garrick" / "machine.json").read_text(encoding="utf-8")
        self.assertEqual((other / ".config" / "garrick" / "machine.json").read_text(encoding="utf-8"), mine)
        self.assertEqual({"role": "roaming", "name": "laptop", "server": "mini"}, json.loads(mine))

    def test_each_role_has_its_sentence_and_a_server_is_kept_only_for_a_laptop_copy(self):
        self.assertEqual("This computer is now the home server.", self.go({"verb": "machine-role", "role": "server", "name": "mini", "server": "x"})["say"])
        self.assertEqual({"role": "server", "name": "mini"}, self.role_file())
        self.assertEqual("This computer is now one computer.", self.go({"verb": "machine-role", "role": "solo"})["say"])
        self.assertEqual({"role": "solo", "name": "mini"}, self.role_file())             # the name is kept when none is sent

    def test_the_workspace_path_and_the_name_an_earlier_file_named_are_kept(self):
        target = self.home / ".config" / "garrick" / "machine.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"role": "roaming", "name": "laptop", "server": "mini", "workspace": "/Users/jo/Garrick"}))
        self.go({"verb": "machine-role", "role": "roaming", "server": "mini2"})            # no name sent
        self.assertEqual({"role": "roaming", "name": "laptop", "server": "mini2", "workspace": "/Users/jo/Garrick"}, self.role_file())
        self.go({"verb": "machine-role", "role": "solo", "name": "desk"})                  # a new name wins; the path stays
        self.assertEqual({"role": "solo", "name": "desk", "workspace": "/Users/jo/Garrick"}, self.role_file())

    def test_the_peers_an_earlier_file_named_are_kept(self):
        target = self.home / ".config" / "garrick" / "machine.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"role": "server", "name": "mini", "peers": ["laptop"]}))
        self.go({"verb": "machine-role", "role": "server", "name": "mini2"})
        self.assertEqual(["laptop"], self.role_file()["peers"])

    def test_it_changes_nothing_in_the_workspace(self):
        before = subprocess.run(["git", "-C", str(self.work), "status", "--porcelain"], capture_output=True, text=True).stdout
        self.go({"verb": "machine-role", "role": "server", "name": "mini"})
        after = subprocess.run(["git", "-C", str(self.work), "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertEqual(before, after)
        self.assertEqual({}, self.saved())

    def test_a_laptop_copy_can_change_its_own_role_back(self):
        self.go({"verb": "machine-role", "role": "roaming", "server": "mini"})
        out = self.go({"verb": "machine-role", "role": "solo"})
        self.assertTrue(out["ok"], out)
        self.assertEqual("solo", self.role_file()["role"])

    def test_with_no_role_file_nothing_changes_for_one_computer(self):
        """The default, solo with no machine.json (#621 changes nothing there): a Todo action is done, not queued, and no role file or
        outbox appears."""
        self.assertIsNone(self.role_file())
        out = self.go({"verb": "todo-add", "zone": "Work", "text": "Book the room"})
        self.assertTrue(out["ok"], out)
        self.assertIn("Book the room", (self.work / "Todo.md").read_text(encoding="utf-8"))
        self.assertIsNone(self.role_file())
        self.assertFalse((self.work / "Inbox" / ".outbox").exists())
        self.assertEqual({}, self.saved())

    # one test for each failure it can show
    def test_failure_a_laptop_copy_without_the_servers_name(self):
        out = self.go({"verb": "machine-role", "role": "roaming", "name": "laptop"})
        self.failed(out, "role-server")
        self.assertIsNone(self.role_file())

    def test_failure_a_name_that_cannot_be_a_file_name(self):
        for req in ({"role": "server", "name": "a/b"}, {"role": "roaming", "server": "..", "name": "x"}, {"role": "server", "name": "two words"},
                    {"role": "nonsense"}):
            with self.subTest(req=req):
                self.failed(self.go(dict(req, verb="machine-role")), "role-name")
        self.assertIsNone(self.role_file())

    def test_failure_no_tool_to_write_it(self):
        with mock.patch.object(pa, "machine_lib", return_value=None):
            self.failed(self.go({"verb": "machine-role", "role": "server"}), "role-tool")

    def test_failure_the_settings_folder_cannot_be_written(self):
        (self.home / ".config").write_text("a file where the folder should be", encoding="utf-8")
        out = self.go({"verb": "machine-role", "role": "server", "name": "mini"})
        self.failed(out, "role-write")
        self.assertEqual("The role was not changed: this computer's settings folder could not be written.", out["plain"]["say"])
        self.assertEqual("Try again", out["plain"]["next"])

    def test_a_laptop_copy_reaches_it_and_the_zone_guard_still_refuses_an_assistants_edit(self):
        self.go({"verb": "machine-role", "role": "roaming", "server": "mini"})
        out = self.go({"verb": "machine-role", "role": "server", "name": "mini"})      # not queued, not refused
        self.assertTrue(out["ok"], out)
        text = (REPO / "extras" / "hooks" / "zone_guard.py").read_text(encoding="utf-8")
        self.assertIn("machine.json", text)                              # the role-file refusal is still there; test_machine_guard holds it


class TestTheReadGuard(SettingsCase):
    def hook(self, claude=True):
        return self.claude() if claude else json.loads((self.home / ".codex" / "hooks.json").read_text(encoding="utf-8"))

    def hooked(self, table):
        return sorted(e for e, entries in table.get("hooks", {}).items()
                      if any("read_guard.py" in h.get("command", "") for entry in entries for h in entry.get("hooks", [])))

    def test_off_to_watch_only_registers_the_hook_and_sets_warn(self):
        self.assistants()
        out = self.go({"verb": "read-guard", "mode": "warn"})
        self.assertTrue(out["ok"], out)
        self.assertEqual("The read guard is watch, and its hook shows as registered.", out["say"])
        self.assertEqual(["PostToolUse", "PreToolUse", "SessionStart"], self.hooked(self.hook()))
        self.assertEqual(["PreToolUse", "SessionStart"], self.hooked(self.hook(False)))
        self.assertEqual("warn", self.saved()["read-guard"])

    def test_on_sets_enforce_and_off_takes_the_hook_out_and_leaves_warn(self):
        self.assistants()
        self.go({"verb": "read-guard", "mode": "warn"})
        self.assertEqual("enforce", self.go({"verb": "read-guard", "mode": "enforce"}) and self.saved()["read-guard"])
        self.assertEqual(["PostToolUse", "PreToolUse", "SessionStart"], self.hooked(self.hook()))        # once each, not twice
        self.assertEqual(1, len([e for e in self.hook()["hooks"]["PreToolUse"]]))
        out = self.go({"verb": "read-guard", "mode": "off"})
        self.assertTrue(out["ok"], out)
        self.assertEqual("The read guard is off.", out["say"])
        self.assertEqual([], self.hooked(self.claude()))
        self.assertEqual("warn", self.saved()["read-guard"])

    def test_it_is_the_registration_check_that_confirms(self):
        self.assistants()
        self.go({"verb": "read-guard", "mode": "enforce"})
        done = subprocess.run([sys.executable, str(REPO / "extras" / "hooks" / "read_guard.py"), "--check"], capture_output=True, text=True,
                              env=dict(os.environ, HOME=str(self.home)))
        self.assertEqual(0, done.returncode, done.stdout)
        self.assertIn("Claude Code: the read guard is registered", done.stdout)
        self.assertIn("Codex: the read guard is registered", done.stdout)

    def test_other_hooks_stay_and_only_the_assistant_found_is_written(self):
        self.assistants(codex=False)
        path = self.home / ".claude" / "settings.json"
        path.write_text(json.dumps({"theme": "x", "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [
            {"type": "command", "command": "python3 /x/zone_guard.py"}]}]}}))
        self.go({"verb": "read-guard", "mode": "warn"})
        self.assertEqual("x", self.claude()["theme"])
        self.assertIn("zone_guard.py", json.dumps(self.claude()["hooks"]["PreToolUse"]))
        self.assertFalse((self.home / ".codex").exists())
        self.go({"verb": "read-guard", "mode": "off"})
        self.assertEqual({"theme": "x", "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [
            {"type": "command", "command": "python3 /x/zone_guard.py"}]}]}}, self.claude())

    def test_the_cross_wall_choice_and_the_two_lists(self):
        self.assistants()
        out = self.go({"verb": "read-guard", "cross": "ask", "tools": ["mcp__*Gmail*", "mcp__*Calendar*", "mcp__*Mail*", "mcp__*mail*"],
                       "skip": ["mcp__weather__*"]})
        self.assertTrue(out["ok"], out)
        self.assertEqual({"read-guard-cross-zone": "ask", "connector-tools": ["mcp__*Gmail*", "mcp__*Calendar*", "mcp__*Mail*"],
                          "connector-tools-skip": ["mcp__weather__*"]}, self.saved())           # a repeat in another case is folded
        self.assertFalse((self.home / ".claude" / "settings.json").exists())                      # no mode named: no registration
        self.assertEqual("deny", self.go({"verb": "read-guard", "cross": "deny"}) and self.saved()["read-guard-cross-zone"])

    def test_the_other_keys_of_the_settings_file_stay(self):
        self.assistants()
        self.settings_file.write_text(json.dumps({"launchers": {"note": True}, "default": "note"}))
        self.go({"verb": "read-guard", "mode": "warn"})
        self.assertEqual({"note": True}, self.saved()["launchers"])

    def test_the_connector_lists_take_a_name_or_a_pattern_and_nothing_else(self):
        self.assistants()
        for bad in ("", " ", "a b", "a/b", "../x", "a\\b", "x..y", "x" * 101, 5, None):
            with self.subTest(item=bad):
                self.failed(self.go({"verb": "read-guard", "tools": [bad]}), "guard-value")
        self.failed(self.go({"verb": "read-guard", "tools": ["mcp__x"] * 41 and [str(i) for i in range(41)]}), "guard-value")
        self.failed(self.go({"verb": "read-guard", "tools": "mcp__x"}), "guard-value")
        self.assertEqual({}, self.saved())

    # one test for each failure it can show
    def test_failure_a_choice_it_does_not_take(self):
        for req in ({"mode": "maybe"}, {"cross": "sometimes"}, {"mode": True}):
            with self.subTest(req=req):
                self.failed(self.go(dict(req, verb="read-guard")), "guard-value")
        self.assertEqual({}, self.saved())

    def test_failure_no_assistant_on_this_computer(self):
        out = self.go({"verb": "read-guard", "mode": "enforce"})
        self.failed(out, "guard-assistant")
        self.assertEqual({}, self.saved())

    def test_failure_the_hook_file_is_not_there(self):
        self.assistants()
        with mock.patch.object(pa, "guard_hooks", return_value=(None, None)):
            out = self.go({"verb": "read-guard", "mode": "warn"})
        self.failed(out, "guard-file")
        self.assertEqual({}, self.saved())

    def test_failure_the_assistants_settings_do_not_read_and_are_left_as_they_are(self):
        self.assistants()
        path = self.home / ".claude" / "settings.json"
        path.write_text("{not json", encoding="utf-8")
        out = self.go({"verb": "read-guard", "mode": "warn"})
        self.failed(out, "guard-read")
        self.assertEqual("{not json", path.read_text(encoding="utf-8"))
        self.assertFalse((self.home / ".codex" / "hooks.json").exists())          # nothing was written anywhere
        self.assertEqual({}, self.saved())

    def test_failure_the_assistants_settings_cannot_be_written(self):
        self.assistants(codex=False)
        folder = self.home / ".claude"
        folder.chmod(0o500)
        try:
            out = self.go({"verb": "read-guard", "mode": "warn"})
        finally:
            folder.chmod(0o700)
        self.failed(out, "guard-write")
        self.assertEqual({}, self.saved())

    def test_failure_the_check_does_not_show_it_registered(self):
        self.assistants()
        real, src = pa.guard_hooks()

        class Liar:
            RegisterError = real.RegisterError

            @staticmethod
            def register(*a, **k):
                return []

            @staticmethod
            def check_lines(home=None):
                return ["Claude Code: the read guard is not registered. x."], False
        with mock.patch.object(pa, "guard_hooks", return_value=(Liar, src)):
            out = self.go({"verb": "read-guard", "mode": "warn"})
        self.failed(out, "guard-check")
        self.assertEqual({}, self.saved())

    def test_failure_the_workspaces_settings_cannot_be_written(self):
        self.assistants()
        keep = pa.prefs()
        with mock.patch.object(keep, "save", side_effect=OSError("disk full")):
            out = self.go({"verb": "read-guard", "mode": "enforce"})
        self.failed(out, "guard-save")
        self.assertNotEqual("enforce", self.saved().get("read-guard"))

    def test_an_empty_mail_and_calendar_list_and_a_pattern_of_only_wildcards_are_refused(self):
        self.assistants()
        self.failed(self.go({"verb": "read-guard", "tools": []}), "guard-value")
        for bad in ("*", "**", "?*", "*?*"):
            for key in ("tools", "skip"):
                with self.subTest(key=key, pattern=bad):
                    self.failed(self.go({"verb": "read-guard", key: [bad]}), "guard-value")
        self.assertEqual({}, self.saved())
        self.assertTrue(self.go({"verb": "read-guard", "skip": []})["ok"])               # nothing to skip is a list that can be empty
        self.assertTrue(self.go({"verb": "read-guard", "tools": ["mcp__x*"]})["ok"])

    def test_a_refused_change_never_shows_as_saved(self):
        self.assistants()
        out = self.go({"verb": "read-guard", "mode": "bogus"})
        self.assertFalse(out["ok"])
        self.assertNotEqual("saved", out.get("outcome"))
        self.assertNotIn("saved", out["say"].lower().replace("was not saved", ""))

    def test_a_laptop_copy_does_not_change_the_workspaces_settings(self):
        self.assistants()
        self.go({"verb": "machine-role", "role": "roaming", "server": "mini"})
        out = self.go({"verb": "read-guard", "mode": "warn"})
        self.assertFalse(out["ok"], out)
        self.assertIn("only receives", out["say"])
        self.assertIn("set on the home server", out["say"])
        self.assertNotIn("waits", out["say"])
        self.assertEqual({}, self.saved())

    def test_every_failure_row_has_a_sentence_and_one_next_step_and_no_path_or_key(self):
        rows = [r for r in pa.FAILURES if r[0].startswith(("role-", "guard-"))]
        self.assertEqual(13, len(rows))
        for code, sentence, button, act, band in rows:
            with self.subTest(code=code):
                self.assertIn(act, ("why", "retry", "refresh"))
                self.assertTrue(sentence.endswith("."))
                for word in (".json", ".py", "--", "/", "System/"):
                    self.assertNotIn(word, sentence)


class TestConnectedServices(SettingsCase):
    """Settings › Walls › Connected services (#683): a service by its plain name; the page writes the patterns."""

    def seen(self, *tools):
        folder = self.jobs.parent / "garrick-read-guard"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "tools-seen.json").write_text(json.dumps({t: "2026-11-20" for t in tools}))

    def refused(self, out):
        """A service's choice refused with its own sentence: the `guard-service` row once fixes-0800's FAILURES has it (review C2)."""
        if "guard-service" in pa.FAILURE_CODES:
            self.failed(out, "guard-service")
        else:
            self.assertFalse(out["ok"], out)
            self.assertTrue(out["say"].strip())

    def findings(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("garrick_check_services_test", str(REPO / "template/System/tools/check.py"))
        check = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = check
        spec.loader.exec_module(check)
        return check.check_connector_tools(mock.Mock(root=self.root))

    def test_leave_it_for_weather_writes_its_pattern_to_the_skip_list_and_the_check_goes_quiet(self):
        self.seen("mcp__claude_ai_Weather__forecast", "mcp__claude_ai_Gmail__search_threads")
        self.assertEqual(["Settings › Walls › Connected services: Weather is not decided, so its results are not checked "
                          "against the walls. Choose Check it or Leave it there"], [f.message for f in self.findings()])
        out = self.go({"verb": "connected-service", "service": "Weather", "choice": "leave"})
        self.assertTrue(out["ok"], out)
        self.assertEqual("Weather is now Leave it.", out["say"])
        self.assertEqual(["mcp__*Weather__*"], self.saved()["connector-tools-skip"])
        self.assertEqual(["mcp__*Gmail*", "mcp__*Calendar*"], self.saved()["connector-tools"])     # the defaults, kept
        self.assertEqual([], self.findings())

    def test_outlook_typed_in_add_a_service_is_checked(self):
        out = self.go({"verb": "connected-service", "service": "Outlook", "choice": "check", "add": True})
        self.assertTrue(out["ok"], out)
        self.assertEqual(["mcp__*Gmail*", "mcp__*Calendar*", "mcp__*Outlook__*"], self.saved()["connector-tools"])
        out = self.go({"verb": "connected-service", "service": "Google Calendar", "choice": "check", "add": True})
        self.assertIn("mcp__*Google_Calendar__*", self.saved()["connector-tools"])                   # spaces become underscores

    def test_a_choice_moves_a_lines_own_pattern_a_hand_written_one_too(self):
        self.settings_file.write_text(json.dumps({"connector-tools": ["mcp__*Gmail*", "mcp__acme_mail__*"]}))
        self.go({"verb": "connected-service", "service": "acme mail", "choice": "leave"})
        self.assertEqual({"connector-tools": ["mcp__*Gmail*"], "connector-tools-skip": ["mcp__acme_mail__*"]}, self.saved())
        self.go({"verb": "connected-service", "service": "acme mail", "choice": "check"})
        self.assertEqual({"connector-tools": ["mcp__*Gmail*", "mcp__acme_mail__*"], "connector-tools-skip": []}, self.saved())

    def test_add_a_service_refuses_what_it_cannot_build_and_nothing_is_written(self):
        self.settings_file.write_text(json.dumps({"connector-tools-skip": ["mcp__*Weather__*"]}))
        before = self.saved()
        for bad in ("", " ", "*", "Mail*", "a/b", "a.b", "_x", "claude ai", "MCP", "x" * 61,
                    "a", "c", "e", "i", "ab", "laude", "claude_a", "Aude", "de a",              # too short, or inside claude_ai (review S2)
                    "Acme__mail", "a__b"):                                                     # a server part has no __ (review C4)
            with self.subTest(name=bad):
                self.refused(self.go({"verb": "connected-service", "service": bad, "choice": "check", "add": True}))
        for bad in (5, None):                                                                  # no name at all: the request's shape
            self.failed(self.go({"verb": "connected-service", "service": bad, "choice": "check", "add": True}), "guard-value")
        out = self.go({"verb": "connected-service", "service": "Weather", "choice": "check", "add": True})
        self.refused(out)                                                                     # on the other list: not moved unasked
        self.assertIn("on the list already", out["say"])
        self.refused(self.go({"verb": "connected-service", "service": "Weather", "choice": "maybe"}))
        self.failed(self.go({"verb": "connected-service", "service": "Weather", "choice": "check", "add": "yes"}), "guard-value")
        self.assertEqual(before, self.saved())

    def test_a_leave_it_on_a_word_never_takes_in_another_services_tool(self):
        # review W1: the pattern is held to the server part, so "search" does not reach Outlook's search tool
        self.seen("mcp__claude_ai_Outlook__search_messages")
        out = self.go({"verb": "connected-service", "service": "search", "choice": "leave", "add": True})
        self.assertTrue(out["ok"], out)
        self.assertEqual(["mcp__*search__*"], self.saved()["connector-tools-skip"])
        self.assertEqual(["Settings › Walls › Connected services: Outlook is not decided, so its results are not checked "
                          "against the walls. Choose Check it or Leave it there"], [f.message for f in self.findings()])
        import importlib.util
        spec = importlib.util.spec_from_file_location("sg_w1", str(REPO / "extras" / "status" / "settings_guard.py"))
        sg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sg)
        lib = pa.prefs().lib(self.root)
        lines = sg.service_lines(lib.connector_patterns(self.root), lib.connector_skips(self.root), sg.seen_tools(lib),
                                 lib.service_name, lib.tool_matches)
        self.assertIn({"name": "Outlook", "choice": "", "patterns": [], "unmatched": True}, lines)

    def test_a_built_pattern_never_decides_for_a_seen_service_of_another_name(self):
        # review S2: a seen tool of another named service that the pattern would match refuses it, on Leave it of a line too
        self.seen("mcp__claude_ai_Acme_mail__find", "mcp__claude_ai_mail__get")
        before = self.saved()
        out = self.go({"verb": "connected-service", "service": "mail", "choice": "leave"})
        self.refused(out)
        self.assertIn("Acme mail", out["say"])
        self.assertEqual(before, self.saved())

    def test_a_refusal_names_its_own_row_with_its_own_sentence(self):
        # review C2: never the general guard-value row; the sentence is the refusal's own, for Show why
        with self.assertRaises(pa.Refused) as caught:
            pa.set_connected_service(self.root, {"verb": "connected-service", "service": "a__b", "choice": "check", "add": True})
        self.assertEqual("guard-service", caught.exception.reply["failure"])
        self.assertEqual("A service's name is letters and numbers, with spaces, dashes or underscores.", str(caught.exception))

    def test_a_garrick_lib_with_no_service_names_is_no_write_failure(self):
        # review C2: an older garrick_lib is never guard-save
        old = mock.Mock(spec=["preferences", "save_preferences"])
        with mock.patch.object(pa.prefs(), "lib", return_value=old):
            with self.assertRaises(pa.Refused) as caught:
                pa.set_connected_service(self.root, {"verb": "connected-service", "service": "Weather", "choice": "leave"})
        failure = (getattr(caught.exception, "reply", None) or {}).get("failure")
        self.assertNotEqual("guard-save", failure)
        self.assertIn(failure, ("guard-old", None))
        self.assertIn("update Garrick", str(caught.exception) if failure is None else "update Garrick")
        self.assertEqual({}, self.saved())

    def test_a_pattern_of_wildcards_only_names_every_connected_service(self):
        # review C3: no empty name on the line, nor in the reply
        self.settings_file.write_text(json.dumps({"connector-tools": ["mcp__*Gmail*"], "connector-tools-skip": ["mcp__*"]}))
        sg, lib = pa.guard_settings(), pa.prefs().lib(self.root)
        lines = sg.service_lines(["mcp__*Gmail*"], ["mcp__*"], [], lib.service_name, lib.tool_matches)
        self.assertEqual(["Gmail", "Every connected service"], [l["name"] for l in lines])
        out = self.go({"verb": "connected-service", "service": "Every connected service", "choice": "check"})
        self.assertTrue(out["ok"], out)
        self.assertEqual("Every connected service is now Check it.", out["say"])
        self.assertEqual({"connector-tools": ["mcp__*Gmail*", "mcp__*"], "connector-tools-skip": []}, self.saved())

    def test_the_mail_and_calendar_list_never_ends_empty(self):
        self.settings_file.write_text(json.dumps({"connector-tools": ["mcp__*Gmail*"]}))
        out = self.go({"verb": "connected-service", "service": "Gmail", "choice": "leave"})
        self.refused(out)
        self.assertEqual({"connector-tools": ["mcp__*Gmail*"]}, self.saved())


class TestOnlyGarricksOwnHookFolder(SettingsCase):
    """S1: the page loads `read_guard.py` only from the folder beside it, or from a folder whose two files read the same.
    A folder an assistant's settings name is never run on its word alone."""

    def planted(self, copy=False):
        folder = Path(self._tmp.name).resolve() / "planted"
        folder.mkdir()
        hooks = REPO / "extras" / "hooks"
        if copy:
            for name in ("zone_guard.py", "read_guard.py"):
                (folder / name).write_bytes((hooks / name).read_bytes())
        else:
            (folder / "zone_guard.py").write_text("print('zone')\n")
            (folder / "read_guard.py").write_text(
                "import os\nopen(os.path.join(%r, 'ran'), 'w').write('x')\n" % str(folder))
        return folder

    def name_it(self, folder):
        (self.home / ".claude").mkdir(exist_ok=True)
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": "python3 %s" % (folder / "zone_guard.py")}]}]}}))

    def test_a_planted_folder_is_not_trusted_and_never_imported(self):
        folder = self.planted()
        self.name_it(folder)
        sg = pa_settings_guard()
        self.assertNotIn(folder, sg.hook_folders(str(self.home)))
        self.assertIsNone(self.hook_from_planted_only(sg))
        self.assertFalse((folder / "ran").exists())

    def test_the_button_takes_the_hook_from_beside_the_page_and_runs_nothing_planted(self):
        folder = self.planted()
        self.name_it(folder)
        self.assistants()
        mod, src = pa.guard_hooks()
        self.assertEqual(REPO / "extras" / "hooks" / "read_guard.py", src)
        self.assertFalse((folder / "ran").exists())

    def installed_page(self):
        """A page with no hooks folder beside it, as an installed workspace has: only the release digests decide."""
        status = Path(self._tmp.name).resolve() / "installed" / "status"
        status.mkdir(parents=True)
        (status / "settings_guard.py").write_bytes((REPO / "extras" / "status" / "settings_guard.py").read_bytes())
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(pa, "HERE", status))
        stack.enter_context(mock.patch.object(pa, "_OUTBOX", pa._OUTBOX))       # the page's own cache, put back after
        return stack

    def test_a_download_of_another_version_has_its_own_failure_and_is_never_imported(self):
        folder = self.planted(copy=True)
        (folder / "read_guard.py").write_bytes((folder / "read_guard.py").read_bytes() + b"\nopen('ran','w')\n")
        self.name_it(folder)
        self.assistants()
        with self.installed_page():
            out = self.go({"verb": "read-guard", "mode": "warn"})
        self.failed(out, "guard-version")
        self.assertFalse((folder / "ran").exists())
        self.assertEqual({}, self.saved())

    def test_a_folder_with_no_hook_files_still_gives_guard_file(self):
        folder = Path(self._tmp.name).resolve() / "empty"
        folder.mkdir()
        (folder / "zone_guard.py").write_text("x\n")
        (folder / "zone_guard.py").unlink()
        self.name_it(folder)
        self.assistants()
        with self.installed_page():
            out = self.go({"verb": "read-guard", "mode": "warn"})
        self.failed(out, "guard-file")

    def test_a_copy_with_the_same_bytes_is_trusted(self):
        folder = self.planted(copy=True)
        self.name_it(folder)
        self.assertIn(folder, pa_settings_guard().hook_folders(str(self.home)))

    def test_a_quoted_path_with_a_space_is_read_whole(self):
        folder = Path(self._tmp.name).resolve() / "my hooks"
        folder.mkdir()
        for name in ("zone_guard.py", "read_guard.py"):
            (folder / name).write_bytes((REPO / "extras" / "hooks" / name).read_bytes())
        (self.home / ".claude").mkdir(exist_ok=True)
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": 'python3 "%s"' % (folder / "zone_guard.py")}]}]}}))
        self.assertIn(folder, pa_settings_guard().hook_folders(str(self.home)))

    def test_one_changed_byte_in_either_file_is_not(self):
        for name in ("zone_guard.py", "read_guard.py"):
            with self.subTest(name=name):
                folder = Path(self._tmp.name).resolve() / ("p-" + name)
                folder.mkdir()
                for n in ("zone_guard.py", "read_guard.py"):
                    (folder / n).write_bytes((REPO / "extras" / "hooks" / n).read_bytes())
                (folder / name).write_bytes((folder / name).read_bytes() + b"\n#\n")
                self.assertFalse(pa_settings_guard().trusted_hook_folder(folder))

    def test_where_no_hooks_sit_beside_the_page_the_release_digests_decide(self):
        sg = pa_settings_guard()
        good = self.planted(copy=True)
        with mock.patch.object(sg, "HERE", Path(self._tmp.name) / "nowhere" / "status"):
            self.assertTrue(sg.trusted_hook_folder(good))
            (good / "read_guard.py").write_bytes((good / "read_guard.py").read_bytes() + b"#")
            self.assertFalse(sg.trusted_hook_folder(good))

    def test_the_digests_are_the_ones_of_the_files_this_release_ships(self):
        import hashlib
        for name, digest in pa_settings_guard().RELEASE_HOOKS.items():
            self.assertEqual(hashlib.sha256((REPO / "extras" / "hooks" / name).read_bytes()).hexdigest(), digest,
                             "%s changed: put its new SHA-256 in RELEASE_HOOKS in extras/status/settings_guard.py" % name)

    def hook_from_planted_only(self, sg):
        with mock.patch.object(sg, "HERE", Path(self._tmp.name) / "nowhere" / "status"):
            return sg.guard_module()


def pa_settings_guard():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sg_for_tests", str(REPO / "extras" / "status" / "settings_guard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
