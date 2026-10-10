"""The cmux extra, extras/cmux/: desk, cmuxlib, and the status page's tab verbs.

    python3 -m unittest tests.test_cmux

No real cmux is called. A fake one, written for each test, answers from a JSON
file and records every call it gets; a test that would quit, notify or bring
an app forward patches that call out.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True

from fixtures import build_workspace, thread_note, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXTRA = REPO / "extras" / "cmux"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


desk = _load("garrick_desk", EXTRA / "desk.py")
cx = desk.cx
pa = _load("garrick_page_action_cmux", REPO / "extras" / "status" / "page_action.py")

FAKE = """#!%s
import json, os, sys, time
state = json.load(open(os.environ["FAKE_CMUX_STATE"]))
with open(os.environ["FAKE_CMUX_LOG"], "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "password": bool(os.environ.get("CMUX_SOCKET_PASSWORD"))}) + "\\n")
time.sleep(state.get("sleep", 0))
if state.get("fail"):
    sys.stderr.write("Error: socket refused\\n")
    sys.exit(1)
a = sys.argv[1:]
if a[:2] == ["sessions", "list"]:
    print(state.get("raw") or json.dumps({"sessions": state.get("sessions", [])}))
elif a[:1] == ["list-windows"]:
    print(json.dumps({"windows": [{"id": "window-1"}]}))
elif a[:2] == ["workspace", "list"]:
    print(json.dumps({"workspaces": state.get("workspaces", [])}))
elif a[:1] == ["list-pane-surfaces"]:
    print(json.dumps({"surfaces": state.get("surfaces", {}).get(a[a.index("--workspace") + 1], [])}))
else:
    print("OK")
"""


def claude_rows(done=True):
    rows = [{"type": "user", "message": {"content": "open Pricing"}}]
    return rows + ([{"type": "system", "subtype": "turn_duration"}] if done else [])


def event(kind, turn="turn-1"):
    return {"type": "event_msg", "payload": {"type": kind, "turn_id": turn}}


def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


class CmuxCase(unittest.TestCase):
    """A workspace, a jobs folder and a fake cmux, all in a temporary folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.ws = build_workspace(self.tmp / "Workspace")
        self.work = self.ws / "Zones" / "Work"
        self.pricing = self.work / "Acme Review" / "Threads" / "Pricing"
        self.state_file, self.log = self.tmp / "cmux-state.json", self.tmp / "cmux-calls.jsonl"
        fake = self.tmp / "bin" / "cmux"
        write(fake, FAKE % sys.executable)
        fake.chmod(0o755)
        self.state({})
        env = {"GARRICK_CMUX": str(fake), "FAKE_CMUX_STATE": str(self.state_file), "FAKE_CMUX_LOG": str(self.log),
               "GARRICK_JOBS_DIR": str(self.tmp / "jobs"), "GARRICK_WORKSPACE": str(self.ws)}
        for gone in ("CMUX_SOCKET_PASSWORD", "GARRICK_CMUX_PASSWORD_FILE", "GARRICK_DESK_CONFIG"):
            env[gone] = ""
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for gone in ("CMUX_SOCKET_PASSWORD", "GARRICK_CMUX_PASSWORD_FILE", "GARRICK_DESK_CONFIG"):
            os.environ.pop(gone, None)
        self.addCleanup(setattr, cx, "PASSWORD_FILE", None)
        for name in ("notify", "quit_cmux", "bring_forward"):
            p = patch.object(desk, name)
            p.start()
            self.addCleanup(p.stop)

    def state(self, data):
        self.state_file.write_text(json.dumps(data), encoding="utf-8")

    def calls(self):
        if not self.log.is_file():
            return []
        return [json.loads(l) for l in self.log.read_text(encoding="utf-8").splitlines()]

    def verbs(self):
        return [c["argv"][0] for c in self.calls()]

    def transcript(self, name, rows):
        p = self.tmp / "transcripts" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return p

    def append(self, path, rows):
        with open(path, "a", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))

    def session(self, sid, folder, rows, agent="claude", pid=None, surface=None):
        return {"session_id": sid, "agent": agent, "pid": pid or os.getpid(), "cwd": str(folder),
                "surface_id": surface or sid + "-surface", "workspace_id": "ws-work",
                "transcript_path": str(self.transcript(sid + ".jsonl", rows)), "agent_lifecycle": "running"}

    def run_desk(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = desk.main(["--workspace", str(self.ws)] + list(args))
        return code, out.getvalue(), err.getvalue()


class TurnStateTest(CmuxCase):
    def test_claude_turn_ends_with_turn_duration_or_an_interruption(self):
        p = self.transcript("c.jsonl", claude_rows())
        self.assertEqual(cx.turn_state(p), ("idle", 1))
        self.append(p, [{"type": "user", "message": {"content": "next"}}, {"type": "assistant", "message": {}}])
        self.assertEqual(cx.turn_state(p, "claude"), ("working", 2))
        self.append(p, [{"type": "user", "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}}])
        self.assertEqual(cx.turn_state(p)[0], "idle")

    def test_codex_commentary_and_final_text_do_not_end_a_turn(self):
        p = self.transcript("x.jsonl", [{"type": "session_meta", "payload": {}}, event("task_started"),
                                        {"type": "response_item", "payload": {"type": "message", "phase": "final_answer"}}])
        self.assertEqual(cx.turn_state(p), ("working", 1))
        self.append(p, [event("task_complete")])
        self.assertEqual(cx.turn_state(p, "codex"), ("idle", 1))

    def test_codex_old_completion_does_not_hide_a_newer_turn(self):
        p = self.transcript("x.jsonl", [event("task_started", "a"), event("task_started", "b"), event("task_complete", "a")])
        self.assertEqual(cx.turn_state(p, "codex"), ("working", 2))

    def test_unknown_missing_and_other_agents_read_unknown(self):
        self.assertEqual(cx.turn_state(None), ("?", 0))
        self.assertEqual(cx.turn_state(self.tmp / "missing.jsonl"), ("?", 0))
        self.assertEqual(cx.turn_state(self.transcript("f.jsonl", [{"type": "future"}])), ("?", 0))
        self.assertEqual(cx.turn_state(self.transcript("o.jsonl", claude_rows()), "opencode"), ("?", 0))

    def test_the_tail_is_enough_for_the_state(self):
        p = self.transcript("long.jsonl", claude_rows() + [{"type": "assistant", "message": {"content": "x" * 4000}}] * 50
                            + [{"type": "user", "message": {"content": "again"}}])
        self.assertEqual(cx.turn_state(p, tail=8192)[0], "working")


class SessionsByFolderTest(CmuxCase):
    def test_live_sessions_in_the_workspace_by_folder(self):
        project = self.work / "Acme Review"
        self.state({"sessions": [
            self.session("a", self.pricing, claude_rows(done=False)),
            self.session("b", project, claude_rows()),
            self.session("c", project, [{"type": "session_meta", "payload": {}}, event("task_started")], agent="codex"),
            self.session("d", self.work / "Birch Entry", claude_rows(done=False), pid=dead_pid()),
            self.session("e", self.tmp, claude_rows(done=False)),
            self.session("f", self.ws / "Wikis" / "Meetings", [{"type": "unknown"}]),
        ]})
        self.assertEqual(cx.sessions_by_folder(self.ws), {
            str(self.pricing): "working", str(project): "working", str(self.ws / "Wikis" / "Meetings"): "idle"})
        self.assertFalse(any(c["password"] for c in self.calls()))

    def test_empty_when_cmux_is_absent_failing_slow_or_garbled(self):
        self.state({"sessions": [self.session("a", self.pricing, claude_rows())]})
        self.assertEqual(len(cx.sessions_by_folder(self.ws)), 1)
        with patch.dict(os.environ, {"GARRICK_CMUX": str(self.tmp / "no-cmux")}):
            self.assertEqual(cx.sessions_by_folder(self.ws), {})
        self.state({"fail": True})
        self.assertEqual(cx.sessions_by_folder(self.ws), {})
        self.state({"raw": "Welcome to cmux"})
        self.assertEqual(cx.sessions_by_folder(self.ws), {})
        self.state({"sleep": 6})
        began = time.time()
        self.assertEqual(cx.sessions_by_folder(self.ws), {})
        self.assertLess(time.time() - began, 3.5)


class PasswordTest(CmuxCase):
    def test_the_password_file_goes_in_the_environment_and_only_when_private(self):
        f = self.tmp / "jobs" / "cmux-socket.password"
        write(f, "fixture-secret\n")
        f.chmod(0o600)
        self.assertEqual(cx.socket_env()["CMUX_SOCKET_PASSWORD"], "fixture-secret")
        cx.cmux("ping")
        self.assertTrue(self.calls()[-1]["password"])
        self.assertNotIn("fixture-secret", json.dumps(self.calls()))
        f.chmod(0o644)
        with self.assertRaisesRegex(cx.CmuxError, "chmod 600"):
            cx.socket_env()
        cx.cmux("sessions", "list", "--json", "--all", password=False)      # reading records goes on without it
        with patch.dict(os.environ, {"CMUX_SOCKET_PASSWORD": "from-the-environment"}):
            self.assertEqual(cx.socket_env()["CMUX_SOCKET_PASSWORD"], "from-the-environment")

    def test_the_config_and_the_environment_name_the_file(self):
        f = self.tmp / "elsewhere.password"
        write(f, "x")
        f.chmod(0o600)
        write(self.ws / "System" / "desk.json", json.dumps({"socket_password_file": str(f)}))
        desk.load_config(self.ws)
        self.assertEqual(cx.password_file(), f)
        with patch.dict(os.environ, {"GARRICK_CMUX_PASSWORD_FILE": str(self.tmp / "other")}):
            self.assertEqual(cx.password_file(), self.tmp / "other")


class ConfigTest(CmuxCase):
    def config(self, data):
        write(self.ws / "System" / "desk.json", data if isinstance(data, str) else json.dumps(data))
        return desk.load_config(self.ws)

    def test_defaults_without_a_file(self):
        cfg = desk.load_config(self.ws)
        self.assertEqual(cfg["agent"], "claude")
        self.assertEqual(cfg["before_quit"], [])
        self.assertEqual(desk.Desk(self.ws, cfg).workspace_for("Work"), "Work")
        self.assertEqual(desk.Desk(self.ws, cfg).workspace_for("neutral"), "System")

    def test_the_example_config_loads(self):
        cfg = self.config((EXTRA / "desk.example.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["workspaces"]["neutral"], "System")

    def test_settings_merge_and_commands_parse(self):
        cfg = self.config({"workspaces": {"Work": "Client work"}, "agent": "codex", "aliases": {"the price": "Pricing"},
                           "before_quit": ["git -C 'Zones/Work' status", ["python3", "backup.py", "--all"]]})
        d = desk.Desk(self.ws, cfg)
        self.assertEqual(d.workspace_for("Work"), "Client work")
        self.assertEqual(d.workspace_for("Personal"), "Personal")
        self.assertEqual(cfg["agent"], "codex")
        self.assertEqual(cfg["before_quit"], [["git", "-C", "Zones/Work", "status"], ["python3", "backup.py", "--all"]])

    def test_bad_settings_are_refused_by_name(self):
        for data, said in (("{not json", "not valid JSON"), ([], "one JSON object"), ({"agents": "codex"}, "agents"),
                           ({"agent": "opencode"}, "agent should be"), ({"before_quit": "backup.sh"}, "list of commands"),
                           ({"before_quit": [3]}, "not a command"), ({"skip": "archive"}, "skip"),
                           ({"workspaces": {"Work": 1}}, "workspaces")):
            with self.subTest(data=data), self.assertRaisesRegex(desk.DeskError, said):
                self.config(data)


class ResolveTest(CmuxCase):
    def setUp(self):
        super().setUp()
        self.desk = desk.Desk(self.ws, desk.load_config(self.ws))

    def test_threads_projects_and_wikis_by_name(self):
        for heard, folder in (("pricing", self.pricing), ("the Pricing thread", self.pricing),
                              ("acme review, pricing", self.pricing), ("Acme Review", self.work / "Acme Review"),
                              ("market sizing", self.work / "Birch Entry" / "Threads" / "Market Sizing"),
                              ("ms", self.work / "Birch Entry" / "Threads" / "Market Sizing"),
                              ("meetings", self.ws / "Wikis" / "Meetings"), ("system", self.ws / "System"),
                              ("prising", self.pricing)):
            with self.subTest(heard=heard):
                self.assertEqual(self.desk.resolve(heard)["path"], folder)

    def test_an_alias_from_the_config(self):
        write(self.ws / "System" / "desk.json", json.dumps({"aliases": {"the price": "Pricing"}}))
        self.assertEqual(desk.Desk(self.ws).resolve("the price")["path"], self.pricing)

    def test_two_threads_with_one_name_are_asked_about(self):
        write(self.work / "Birch Entry" / "Threads" / "Pricing" / "Pricing.md", thread_note("Birch Entry", "Pricing", "birch"))
        with self.assertRaisesRegex(desk.DeskError, "Acme Review, Pricing in Work; Birch Entry, Pricing in Work"):
            self.desk.resolve("pricing")
        self.assertEqual(self.desk.resolve("birch entry pricing")["project"], "Birch Entry")

    def test_nothing_found_names_some_that_exist(self):
        with self.assertRaisesRegex(desk.DeskError, "nothing called 'roofing'"):
            self.desk.resolve("roofing")


class DeskVerbTest(CmuxCase):
    def test_open_starts_a_named_session_in_the_zones_workspace(self):
        self.state({"workspaces": [{"id": "ws-work", "title": "Work"}]})
        code, out, err = self.run_desk("open", "pricing", "--prompt", "open pricing")
        self.assertEqual((code, err), (0, ""))
        call = next(c["argv"] for c in self.calls() if c["argv"][0] == "new-surface")
        self.assertEqual(call[call.index("--workspace") + 1], "ws-work")
        self.assertEqual(call[call.index("--working-directory") + 1], str(self.pricing))
        self.assertEqual(shlex.split(call[call.index("--command") + 1]), ["claude", "-n", "Acme Review, Pricing", "open pricing"])
        self.assertIn("a new tab in Work", out)

    def test_open_makes_the_workspace_when_it_is_missing_and_uses_the_agent_setting(self):
        write(self.ws / "System" / "desk.json", json.dumps({"agent": "codex", "workspaces": {"Work": "Clients"}}))
        code, out, _ = self.run_desk("open", "acme review")
        self.assertEqual(code, 0)
        call = next(c["argv"] for c in self.calls() if c["argv"][0] == "new-workspace")
        self.assertEqual(call[call.index("--name") + 1], "Clients")
        self.assertEqual(call[call.index("--command") + 1], "codex")

    def test_open_dry_run_and_the_folders_that_hold_projects(self):
        code, out, _ = self.run_desk("open", "pricing", "--dry-run")
        self.assertIn("would open Zones/Work/Acme Review/Threads/Pricing in Work, running: claude -n", out)
        self.assertNotIn("new-surface", self.verbs())
        for where in ("Zones/Work", str(self.ws / "Zones"), str(self.ws / "Wikis")):
            code, _, err = self.run_desk("open", where)
            self.assertEqual(code, 2, where)
            self.assertIn("holds projects", err)
        self.assertEqual(self.run_desk("open", str(self.ws), "--dry-run")[0], 0)   # the root, by its full path

    def test_open_sends_the_prompt_to_an_idle_tab_and_nothing_to_a_busy_one(self):
        self.state({"sessions": [self.session("a", self.pricing, claude_rows())]})
        self.assertEqual(self.run_desk("open", "pricing", "--prompt", "open pricing")[0], 0)
        self.assertIn(["send", "--surface", "a-surface", "--", "open pricing"], [c["argv"] for c in self.calls()])
        self.assertNotIn("new-surface", self.verbs())
        self.log.unlink()
        self.state({"sessions": [self.session("a", self.pricing, claude_rows(done=False))]})
        code, _, err = self.run_desk("open", "pricing", "--prompt", "open pricing")
        self.assertEqual(code, 2)
        self.assertIn("mid-turn", err)
        self.assertNotIn("send", self.verbs())

    def test_close_refuses_busy_and_unreadable_tabs_and_closes_none(self):
        project = self.work / "Acme Review"
        for rows in (claude_rows(done=False), [{"type": "unknown"}]):
            self.state({"sessions": [self.session("a", project, claude_rows()), self.session("b", self.pricing, rows)]})
            code, _, err = self.run_desk("close", "--folder", str(project), "--yes")
            self.assertEqual(code, 2)
            self.assertNotIn("close-surface", self.verbs())

    def test_close_asks_first_then_closes_every_tab_below_the_folder(self):
        project = self.work / "Acme Review"
        self.state({"sessions": [self.session("a", project, claude_rows()), self.session("b", self.pricing, claude_rows()),
                                 self.session("c", self.work / "Birch Entry", claude_rows())]})
        code, out, _ = self.run_desk("close", "--folder", str(project))
        self.assertIn("would close", out)
        self.assertIn("claude --resume a", out)
        self.assertNotIn("close-surface", self.verbs())
        self.assertEqual(self.run_desk("close", "--folder", str(project), "--yes")[0], 0)
        closed = [c["argv"][2] for c in self.calls() if c["argv"][0] == "close-surface"]
        self.assertEqual(sorted(closed), ["a-surface", "b-surface"])

    def test_close_with_a_wrap_waits_for_the_tabs_own_wrap(self):
        s = self.session("a", self.pricing, claude_rows())
        self.state({"sessions": [s]})
        sent = []

        def answer(surface, text):
            sent.append(text)
            self.append(s["transcript_path"], [{"type": "user", "message": {"content": text}},
                                               {"type": "system", "subtype": "turn_duration"}])

        with patch.object(desk, "send", side_effect=answer), patch.object(desk.time, "sleep"):
            self.assertEqual(self.run_desk("close", "pricing", "--wrap", "--yes")[0], 0)
        self.assertTrue(sent[0].startswith("/threads wrap it. "))
        self.assertIn("close-surface", self.verbs())

    def test_shutdown_dry_run_wraps_in_turn_then_runs_the_before_quit_commands(self):
        marker = self.tmp / "before-quit.txt"
        write(self.ws / "System" / "desk.json", json.dumps({"before_quit": [
            [sys.executable, "-c", "open(%r, 'w').write('ran')" % str(marker)]]}))
        sessions = [self.session("a", self.pricing, claude_rows()),
                    self.session("b", self.work / "Birch Entry", [event("task_started"), event("task_complete")], agent="codex")]
        self.state({"sessions": sessions})
        code, out, _ = self.run_desk("shutdown")
        self.assertIn("2 tab(s) open; 2 used today would be wrapped", out)
        self.assertFalse(marker.exists())
        prompts = []

        def answer(surface, text):
            s = next(x for x in sessions if x["surface_id"] == surface)
            for other in sessions:                      # the one before has finished first
                self.assertEqual(cx.turn_state(other["transcript_path"])[0], "idle")
            prompts.append(text)
            self.append(s["transcript_path"], [event("task_started", "w"), event("task_complete", "w")]
                        if s["agent"] == "codex" else claude_rows())

        with patch.object(desk, "send", side_effect=answer), patch.object(desk.time, "sleep"):
            self.assertEqual(self.run_desk("shutdown", "--yes")[0], 0)
        self.assertEqual(sorted(p.split(".")[0] for p in prompts), ["/threads wrap it", "Use the threads skill to wrap it"])
        self.assertEqual(marker.read_text(), "ran")
        desk.quit_cmux.assert_called_once()
        snap = json.loads((self.tmp / "jobs" / "desk-snapshot.json").read_text())
        self.assertEqual(sorted(t["session_id"] for t in snap["tabs"]), ["a", "b"])

    def test_shutdown_refuses_a_busy_or_unreadable_tab(self):
        for rows in (claude_rows(done=False), [{"type": "unknown"}]):
            self.state({"sessions": [self.session("a", self.pricing, rows)]})
            code, _, err = self.run_desk("shutdown", "--yes")
            self.assertEqual(code, 2)
            self.assertNotIn("send", self.verbs())
            desk.quit_cmux.assert_not_called()

    def test_a_wrap_that_never_finishes_leaves_cmux_running(self):
        self.state({"sessions": [self.session("a", self.pricing, claude_rows())]})
        clock = [0.0]

        def tick(_):
            clock[0] += desk.WRAP_LIMIT_S + 1

        with patch.object(desk, "send"), patch.object(desk.time, "sleep", side_effect=tick), \
                patch.object(desk.time, "time", side_effect=lambda: clock[0]):
            code, _, err = self.run_desk("shutdown", "--yes")
        self.assertEqual(code, 2)
        self.assertIn("never started", err)
        desk.quit_cmux.assert_not_called()

    def test_start_resumes_tabs_that_came_back_empty(self):
        write(self.tmp / "jobs" / "desk-snapshot.json", json.dumps({"tabs": [
            {"session_id": "gone", "agent": "codex", "surface": "s-1", "workspace": "Work", "tab": "Pricing",
             "cwd": str(self.pricing)},
            {"session_id": "here", "agent": "claude", "surface": "s-2", "workspace": "Work", "tab": "Birch",
             "cwd": str(self.work / "Birch Entry")}]}))
        self.state({"sessions": [self.session("here", self.work / "Birch Entry", claude_rows(), surface="s-2")],
                    "workspaces": [{"id": "ws-work", "title": "Work"}],
                    "surfaces": {"ws-work": [{"id": "s-1", "title": "Pricing"}, {"id": "s-2", "title": "Birch"}]}})
        resumed, lost = desk.resume_missing()
        self.assertEqual((resumed, lost), (["Pricing"], []))
        typed = [c["argv"][-1] for c in self.calls() if c["argv"][0] == "send"]
        self.assertEqual(shlex.split(typed[0]), ["cd", str(self.pricing), "&&", "codex", "resume", "gone"])


class PageVerbTest(CmuxCase):
    def act(self, req):
        return pa.act(self.ws, req)

    def test_refused_without_the_extra_or_without_cmux(self):
        with patch.object(pa, "CMUX_EXTRA", self.tmp / "nothing"):
            with self.assertRaisesRegex(pa.Refused, "need the cmux extra"):
                self.act({"verb": "startup"})
        with patch.dict(os.environ, {"GARRICK_CMUX": str(self.tmp / "no-cmux")}):
            with self.assertRaisesRegex(pa.Refused, "not installed"):
                self.act({"verb": "open", "zone": "Work", "project": "Acme Review"})

    def test_open_a_thread_starts_its_session_on_open(self):
        self.state({"workspaces": [{"id": "ws-work", "title": "Work"}]})
        said = self.act({"verb": "open", "zone": "Work", "project": "Acme Review", "thread": "Pricing"})
        self.assertTrue(said.startswith("Opened Acme Review, Pricing"), said)
        call = next(c["argv"] for c in self.calls() if c["argv"][0] == "new-surface")
        self.assertEqual(call[call.index("--working-directory") + 1], str(self.pricing))
        self.assertEqual(shlex.split(call[call.index("--command") + 1])[-1], "open Acme Review, Pricing")

    def test_open_and_close_refuse_what_is_not_a_project_or_thread(self):
        for req in ({"zone": "Work", "project": "../Personal"}, {"zone": "Work", "project": "Nothing"},
                    {"zone": "Work", "project": "Acme Review", "thread": "Nothing"}, {"zone": "Elsewhere", "project": "Acme Review"},
                    {"zone": "Work", "project": "Threads"}, {"zone": "Work"}):
            for verb in ("open", "close"):
                with self.subTest(req=req, verb=verb), self.assertRaises(pa.Refused):
                    self.act(dict(req, verb=verb))
        self.assertEqual(self.calls(), [])

    def test_close_refuses_while_a_session_is_mid_turn(self):
        self.state({"sessions": [self.session("a", self.pricing, claude_rows(done=False))]})
        with self.assertRaisesRegex(pa.Refused, "mid-turn"):
            self.act({"verb": "close", "zone": "Work", "project": "Acme Review"})
        self.assertNotIn("close-surface", self.verbs())
        self.state({"sessions": [self.session("a", self.pricing, claude_rows())]})
        self.assertIn("Acme Review", self.act({"verb": "close", "zone": "Work", "project": "Acme Review"}))
        self.assertIn("close-surface", self.verbs())

    def test_shutdown_runs_the_dry_run_here_and_the_rest_detached(self):
        self.state({"sessions": [self.session("a", self.pricing, claude_rows(done=False))]})
        with patch.object(pa, "desk_detached") as spawn:
            with self.assertRaisesRegex(pa.Refused, "mid-turn or waiting"):
                self.act({"verb": "shutdown"})
            spawn.assert_not_called()
        self.state({"sessions": [self.session("a", self.pricing, claude_rows())]})
        with patch.object(pa, "desk_detached") as spawn:
            self.assertEqual(self.act({"verb": "shutdown"}), "Shutting down: wrapping 1 tab, then cmux quits")
        spawn.assert_called_once_with(self.ws, "shutdown", "--yes")

    def test_startup_goes_on_detached_in_a_session_of_its_own(self):
        with patch.object(pa, "desk_detached") as spawn:
            self.assertIn("Starting cmux", self.act({"verb": "startup"}))
        spawn.assert_called_once_with(self.ws, "start", "--notify")
        with patch.object(pa.subprocess, "Popen") as popen:
            pa.desk_detached(self.ws, "start", "--notify")
        self.assertEqual(popen.call_args.args[0][-4:], ["--workspace", str(self.ws), "start", "--notify"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_the_reply_is_json_from_the_command_line(self):
        done = subprocess.run([sys.executable, str(REPO / "extras" / "status" / "page_action.py"), "--workspace", str(self.ws)],
                              input=json.dumps({"verb": "close", "zone": "Work", "project": "Acme Review"}),
                              capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(json.loads(done.stdout), {"ok": False, "say": "no open tab in Zones/Work/Acme Review"})


if __name__ == "__main__":
    unittest.main()
