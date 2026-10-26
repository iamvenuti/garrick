"""The one notifier, template/System/tools/notifications.py (#110, #227), and what sends through it.

    cd tests && python3 -m unittest test_notifications

Nothing here reaches this Mac's notifications: the module's way out, _run,
is a fake that records what it was asked. Invented names only.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


n = _load("garrick_notifications_test", TOOLS / "notifications.py")
NOON = dt.datetime(2026, 10, 14, 12, 0)
NIGHT = dt.datetime(2026, 10, 14, 23, 30)
MORNING = dt.datetime(2026, 10, 15, 8, 0)


class Recorder:
    """Stands in for subprocess.run: records each call, answers as told."""

    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def __call__(self, args, **kw):
        self.calls.append((list(args), kw))
        out = self.answers.get(Path(args[0]).name if args else "", (0, ""))
        if callable(out):
            out = out(args, kw)
        return subprocess.CompletedProcess(args, out[0], out[1], "")

    def named(self, name):
        return [a for a, _ in self.calls if a and Path(a[0]).name == name]


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.ws = self.base / "Workspace"
        build_workspace(self.ws)
        self.run_ = Recorder()
        for p in (mock.patch.object(n, "_run", self.run_), mock.patch.object(n.sys, "platform", "darwin")):
            p.start()
            self.addCleanup(p.stop)

    def save(self, cfg):
        write(self.ws / "System" / "garrick-settings.json", json.dumps({"notifications": cfg}))

    def send(self, event, title="Title", message="Message", zone=None, now=NOON, env=None):
        return n.send(event, title, message, zone, root=self.ws, now=now, env=env if env is not None else {})

    def osascripts(self):
        return self.run_.named("osascript")


class TestSettings(Case):
    def test_defaults(self):
        cfg = n.settings(self.ws)
        self.assertEqual({"tell": {"needs-you": True, "finished": True, "todo-summary": True, "job-failed": True},
                          "after": 2, "quiet": {"on": True, "from": "22:00", "to": "07:00"}}, cfg)
        self.assertEqual(["needs-you", "finished", "todo-summary", "job-failed"], list(n.TELL_NAMES))
        self.assertEqual({"needs-you": "send", "finished": "drop", "desk": "send"},
                         {k: v for k, v in n.QUIET.items() if v != "hold"})

    def test_the_settings_file_is_garrick_libs(self):
        lib = _load("garrick_lib_for_notifications", TOOLS / "garrick_lib.py")
        self.assertEqual(lib.SETTINGS, n.SETTINGS)
        self.assertIn(n.KEY, lib.PREFERENCES)
        ops = _load("garrick_ops_for_notifications", TOOLS / "operations.py")
        self.assertIn("notifications", ops.DECLARED["settings"].fields)
        self.assertFalse({"test", "token", "find-chat"} & set(ops.DECLARED["settings"].fields))

    def test_clean_keeps_what_the_page_sends(self):
        given = {"tell": {"needs-you": True, "finished": False, "todo-summary": True, "job-failed": False},
                 "after": 5, "quiet": {"on": True, "from": "21:30", "to": "06:45"}}
        self.assertEqual(given, n.clean(given))
        self.assertEqual(n.normal(given), n.normal(n.clean(given)))
        self.assertEqual({"needs-you": True, "finished": True, "todo-summary": True, "job-failed": True},
                         n.clean({})["tell"])

    def test_clean_refuses(self):
        for bad in ({"token": "x"},
                    {"channels": {"telegram": True}},           # an older Garrick's shape, never sent by this page
                    {"telegram": {"chat": "4242"}},
                    {"command": "/bin/true"},
                    {"zones": {"Work": {"to": ["mac"]}}},
                    {"tell": {"birthday": True}},
                    {"tell": {"todo-refreshed": True}},
                    {"tell": {"finished": "yes"}},
                    {"after": 999},
                    {"after": True},
                    {"quiet": {"from": "25:00"}},
                    {"quiet": {"on": "yes"}},
                    "everything"):
            with self.assertRaises(n.Invalid, msg=bad):
                n.clean(bad)

    def test_an_older_garricks_settings_still_read(self):
        old = {"channels": {"mac": True, "cmux": True, "telegram": True, "command": True},
               "telegram": {"chat": "4242"}, "command": "/bin/sh /opt/acme/notify.sh",
               "events": {"needs-you": {"to": ["mac", "telegram"], "quiet": "hold", "away": True},
                          "finished": {"to": ["telegram"], "quiet": "drop", "after": 7},
                          "todo-summary": {"to": ["telegram"]}, "job-failed": {"to": ["mac", "command"]}},
               "quiet": {"on": False, "from": "23:00", "to": "06:00"},
               "zones": {"Personal": {"to": ["telegram"], "chat": "777"}}}
        self.assertEqual({"tell": {"needs-you": True, "finished": False, "todo-summary": False, "job-failed": True},
                          "after": 7, "quiet": {"on": False, "from": "23:00", "to": "06:00"}}, n.normal(old))
        self.assertEqual({"needs-you": False, "finished": False, "todo-summary": False, "job-failed": False},
                         n.normal(dict(old, channels={"mac": False}))["tell"])        # this Mac switched off: every notice off
        self.assertEqual(n.settings(self.ws)["tell"], n.normal({"events": {}})["tell"])
        self.save(old)
        self.assertTrue(self.send("needs-you"))                                        # no crash, and to this Mac alone
        self.assertEqual(1, len(self.osascripts()))
        self.assertEqual([], self.run_.named("sh"))
        n.keep(self.ws, n.settings(self.ws))                                           # the next save drops what is gone
        self.assertEqual({"tell", "after", "quiet"}, set(json.loads(
            (self.ws / "System" / "garrick-settings.json").read_text())["notifications"]))


class TestSend(Case):
    def test_this_mac_by_default(self):
        self.assertTrue(self.send("job-failed", "Job failed", "sweep exited 3"))
        (args,) = self.osascripts()
        self.assertEqual(["sweep exited 3", "Job failed"], args[-2:])

    def test_todo_refreshed_is_never_sent(self):
        self.assertFalse(self.send("todo-refreshed"))
        self.assertEqual([], self.run_.calls)

    def test_an_event_switched_off_goes_nowhere(self):
        self.save({"tell": {"todo-summary": False}})
        self.assertFalse(self.send("todo-summary"))
        self.assertTrue(self.send("job-failed"))
        self.assertEqual(1, len(self.osascripts()))

    def test_job_idle_and_the_desk_go_while_any_of_the_four_is_on(self):
        self.save({"tell": {"needs-you": False, "finished": False, "todo-summary": False, "job-failed": True}})
        self.assertTrue(self.send("job-idle"))
        self.assertTrue(self.send("desk"))
        self.save({"tell": {e: False for e in n.TELL_NAMES}})
        self.assertFalse(self.send("job-idle"))
        self.assertFalse(self.send("desk"))
        self.assertEqual(2, len(self.osascripts()))

    def test_no_workspace_no_notice(self):
        self.assertFalse(n.send("job-failed", "t", "m", env={}, root=self.base))
        self.assertEqual([], self.run_.calls)

    def test_a_legacy_kind_names_its_event(self):
        self.save({"tell": {"job-failed": False, "needs-you": True}})
        self.assertFalse(n.send("recovered", "Job recovered", "m", root=self.ws, now=NOON, env={}))
        self.assertTrue(n.send("idle", "Job idle", "m", root=self.ws, now=NOON, env={}))
        self.assertFalse(n.send("refreshed", "Todo", "m", root=self.ws, now=NOON, env={}))

    def test_a_mac_that_says_no_is_a_line_in_the_log(self):
        self.run_.answers["osascript"] = (1, "")
        log = io.StringIO()
        self.assertFalse(n.send("job-failed", "Job failed", "m", root=self.ws, now=NOON, env={}, log=log, prefix="job"))
        self.assertEqual("job: this Mac said no: exit 1\n", log.getvalue())

    def test_GARRICK_NOTIFY_CMD_gets_what_it_always_got(self):
        self.save({"tell": {e: False for e in n.TELL_NAMES}})                          # past the settings, whatever they say
        env = {"GARRICK_NOTIFY_CMD": "/bin/sh /opt/acme/notify.sh", "PATH": "/usr/bin"}
        self.assertTrue(n.send("todo-summary", "Todo", "Todo · Work", self.ws / "Zones" / "Work", root=self.ws,
                               kind="digest", now=NOON, env=env))
        (args, kw), = self.run_.calls
        self.assertEqual(["/bin/sh", "/opt/acme/notify.sh", "Todo", "Todo · Work"], args)
        self.assertEqual(("digest", "todo-summary", "Work"), (kw["env"]["GARRICK_NOTIFY_KIND"], kw["env"]["GARRICK_NOTIFY_EVENT"],
                                                              kw["env"]["GARRICK_ZONE"]))
        self.assertEqual(str(self.ws / "Zones" / "Work"), kw["env"]["GARRICK_ZONE_DIR"])
        self.assertEqual(str(self.ws / "Zones" / "Work"), kw["cwd"])

    def test_the_old_variables_override_the_settings(self):
        env = {"GARRICK_NOTIFY_CMD": "/opt/acme/plist-notify"}
        self.assertTrue(self.send("job-failed", env=env))
        self.assertEqual([["/opt/acme/plist-notify", "Title", "Message"]], [a for a, _ in self.run_.calls])
        self.assertEqual(("GARRICK_NOTIFY_CMD",), n.override(env))
        self.assertEqual(("GARRICK_NOTIFY",), n.override({"GARRICK_NOTIFY": "1", "GARRICK_NOTIFY_CMD": " "}))
        self.run_.calls.clear()
        self.assertTrue(self.send("todo-refreshed", env={"GARRICK_NOTIFY": "1"}))      # even an event Settings never sends
        self.assertEqual(1, len(self.osascripts()))

    def test_the_command_line(self):
        out, err = io.StringIO(), io.StringIO()
        outside = {k: v for k, v in os.environ.items() if not k.startswith(("CMUX_", "GARRICK_"))}     # never this Mac's own cmux
        with mock.patch.object(n.sys, "stdout", out), mock.patch.object(n.sys, "stderr", err), \
                mock.patch.dict(n.os.environ, outside, clear=True):
            self.assertEqual(0, n.main(["test", "mac", "--root", str(self.ws)]))
            self.assertEqual(1, n.main(["test", "cmux", "--root", str(self.ws)]))
            with self.assertRaises(SystemExit):
                n.main(["telegram-token"])
        self.assertIn("A test went to this Mac.", out.getvalue())
        self.assertIn("Cmux runs only from a session inside cmux", err.getvalue())


class TestQuietHours(Case):
    def test_held_till_morning_dropped_or_sent(self):
        self.assertTrue(self.send("job-failed", "Job failed", "held one", now=NIGHT))     # held
        self.assertFalse(self.send("finished", now=NIGHT))                               # dropped
        self.assertTrue(self.send("desk", "Desk", "sent anyway", now=NIGHT))
        self.assertEqual([["sent anyway", "Desk"]], [a[-2:] for a in self.osascripts()])
        self.assertEqual(0, n.flush(self.ws, now=NIGHT, env={}))
        self.send("desk", "Desk", "a later one", now=MORNING)                             # the first notice after: held first
        self.assertEqual(["sent anyway", "held one", "a later one"], [a[-2] for a in self.osascripts()])
        self.assertFalse((self.ws / "System" / "generated" / "notifications" / "held.json").exists())

    def test_quiet_hours_over_midnight_or_within_a_day(self):
        cfg = n.normal({})
        self.assertTrue(n.is_quiet(cfg, NIGHT))
        self.assertTrue(n.is_quiet(cfg, dt.datetime(2026, 10, 15, 6, 59)))
        self.assertFalse(n.is_quiet(cfg, dt.datetime(2026, 10, 15, 7, 0)))
        cfg = n.normal({"quiet": {"from": "12:00", "to": "14:00"}})
        self.assertTrue(n.is_quiet(cfg, NOON))
        self.assertFalse(n.is_quiet(n.normal({"quiet": {"on": False}}), NIGHT))

    def test_a_notice_held_too_long_is_let_go(self):
        self.send("job-failed", "Job failed", "stale", now=NIGHT - dt.timedelta(days=2))
        self.assertEqual(0, n.flush(self.ws, now=MORNING, env={}))

    def test_a_held_notice_switched_off_since_is_let_go(self):
        self.send("job-failed", "Job failed", "held", now=NIGHT)
        self.save({"tell": {"job-failed": False}})
        self.assertEqual(0, n.flush(self.ws, now=MORNING, env={}))
        self.assertEqual([], self.osascripts())


class TestHooks(Case):
    def setUp(self):
        super().setUp()
        self.thread = self.ws / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing"

    def event(self, name, at, **more):
        payload = dict({"hook_event_name": name, "session_id": "abc-123", "cwd": str(self.thread)}, **more)
        n.hook(payload, ws=self.ws, env={}, now=at, detach=False)

    def notes(self):
        return [a[-2] for a in self.osascripts()]

    def test_finished_after_a_long_turn_names_the_thread_and_nothing_else(self):
        start = time.mktime(NOON.timetuple())
        self.event("UserPromptSubmit", start, prompt="the renewal floor is a private figure")
        self.event("Stop", start + 185, last_assistant_message="the renewal floor is 41,000")
        self.assertEqual(["Work, Pricing: done, after 3 minutes."], self.notes())
        self.event("Stop", start + 400)                      # its start was used up: not timed, not sent
        self.assertEqual(1, len(self.notes()))

    def test_a_quick_turn_sends_nothing(self):
        start = time.mktime(NOON.timetuple())
        self.event("UserPromptSubmit", start)
        self.event("Stop", start + 30)
        self.assertEqual([], self.notes())

    def test_needs_you_in_words_of_our_own(self):
        self.event("Notification", time.time(), notification_type="permission_prompt",
                   message="Claude needs your permission to use Bash: cat Zones/Work/secret.md")
        self.event("Notification", time.time(), message="Claude is waiting for your input")
        self.event("Notification", time.time(), notification_type="auth_success", message="Signed in")
        self.assertEqual(["Work, Pricing: needs you. Permission asked.", "Work, Pricing: needs you. Waiting for your answer."],
                         self.notes())

    def test_headless_or_outside_the_workspace_sends_nothing(self):
        n.hook({"hook_event_name": "Notification", "cwd": str(self.thread)}, ws=self.ws, env={"GARRICK_HEADLESS": "1"},
               detach=False)
        n.hook({"hook_event_name": "Notification", "cwd": str(self.base)}, ws=self.ws, env={}, detach=False)
        self.assertEqual([], self.run_.calls)

    def test_places(self):
        self.assertEqual(("Work, Acme Review", "Work"), n.place(self.ws, str(self.ws / "Zones" / "Work" / "Acme Review")))
        self.assertEqual(("Work", "Work"), n.place(self.ws, str(self.ws / "Zones" / "Work")))
        self.assertEqual(("Meetings", None), n.place(self.ws, str(self.ws / "Wikis" / "Meetings" / "wiki")))
        self.assertEqual(("The workspace", None), n.place(self.ws, str(self.ws)))
        self.assertIsNone(n.place(self.ws, str(self.base)))

    def test_in_cmux_a_sessions_notice_lands_on_its_tab_with_no_switch_for_it(self):
        cmux = self.base / "cmux"
        write(cmux, "#!/bin/sh\n")
        cmux.chmod(0o755)
        env = {"CMUX_SURFACE_ID": "S1", "GARRICK_CMUX": str(cmux)}
        self.save({"channels": {"cmux": False}})                      # an older Garrick's switch: ignored
        n.send("needs-you", "Needs you", "Work, Pricing: needs you. Permission asked.", "Work", root=self.ws, now=NOON, env=env)
        (args,) = self.run_.named("cmux")
        self.assertEqual(["notify", "--title", "Garrick", "--subtitle", "Needs you", "--body"], args[1:7])
        self.assertEqual([], self.osascripts())
        n.send("job-failed", "Job failed", "m", root=self.ws, now=NOON, env=env)   # not a session's: the Mac's own
        self.assertEqual(1, len(self.osascripts()))
        self.run_.answers["cmux"] = (1, "")                                        # a cmux that will not take it
        n.send("finished", "Finished", "m", root=self.ws, now=NOON, env=env)
        self.assertEqual(2, len(self.osascripts()))


class TestInstallHooks(Case):
    def setUp(self):
        super().setUp()
        self.home = self.base / "home"
        write(self.home / ".claude" / "settings.json", json.dumps({
            "model": "opus", "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "guard.py"}]}],
                                       "Stop": [{"hooks": [{"type": "command", "command": "afplay done.aiff"}]}]}}))
        (self.home / ".codex").mkdir()

    def test_install_keeps_the_rest_and_is_idempotent(self):
        state = n.hooks(self.ws, home=self.home, install=True)
        self.assertEqual({"claude": "on, for UserPromptSubmit, Notification, Stop", "codex": "on, for UserPromptSubmit, Stop"}, state)
        data = json.loads((self.home / ".claude" / "settings.json").read_text())
        self.assertEqual("opus", data["model"])
        self.assertEqual("guard.py", data["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
        self.assertEqual(2, len(data["hooks"]["Stop"]))
        self.assertEqual(n.hook_command(self.ws), data["hooks"]["Notification"][0]["hooks"][0]["command"])
        self.assertNotIn("Notification", json.loads((self.home / ".codex" / "hooks.json").read_text())["hooks"])
        n.hooks(self.ws, home=self.home, install=True)
        self.assertEqual(data, json.loads((self.home / ".claude" / "settings.json").read_text()))
        self.assertEqual({"claude": "off", "codex": "off"}, n.hooks(self.ws, home=self.home, install=False))
        data = json.loads((self.home / ".claude" / "settings.json").read_text())
        self.assertEqual(["PreToolUse", "Stop"], sorted(data["hooks"]))

    def test_a_moved_workspaces_hook_is_replaced(self):
        old = {"hooks": [{"type": "command", "command": "python3 /gone/System/tools/notifications.py hook"}]}
        write(self.home / ".codex" / "hooks.json", json.dumps({"hooks": {"Stop": [old]}}))
        n.hooks(self.ws, home=self.home, install=True)
        stop = json.loads((self.home / ".codex" / "hooks.json").read_text())["hooks"]["Stop"]
        self.assertEqual([n.hook_command(self.ws)], [e["hooks"][0]["command"] for e in stop])

    def test_a_file_that_does_not_read_is_left_alone(self):
        write(self.home / ".claude" / "settings.json", "{not json")
        with self.assertRaises(ValueError):
            n.hooks(self.ws, home=self.home, install=True)
        self.assertEqual("{not json", (self.home / ".claude" / "settings.json").read_text())


class TestThroughJobPy(unittest.TestCase):
    """job.py, as launchd runs it, sends through the module: a plist's GARRICK_NOTIFY_CMD
    keeps delivering exactly as before, whatever Settings says."""

    NOTIFIER = ("import json, os, sys\nwith open(os.environ['NOTICES'], 'a') as f:\n"
                "    f.write(json.dumps(sys.argv[1:-1] + [os.environ.get('GARRICK_NOTIFY_EVENT'), os.environ['GARRICK_NOTIFY_KIND']])"
                " + '\\n')\n")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.ws = base / "Workspace"
        build_workspace(self.ws)
        self.notices = base / "notices.jsonl"
        notifier = base / "notifier.py"
        notifier.write_text(self.NOTIFIER, encoding="utf-8")
        self.cmd = "%s %s" % (sys.executable, notifier)
        # every notice off, so nothing in these runs reaches this Mac's own notifications
        write(self.ws / "System" / "garrick-settings.json", json.dumps({"notifications": {
            "tell": {"needs-you": False, "finished": False, "todo-summary": False, "job-failed": False}}}))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("GARRICK_", "CMUX_"))}
        self.env.update(GARRICK_JOBS_DIR=str(base / "jobs"), GARRICK_WORKSPACE=str(self.ws), NOTICES=str(self.notices))

    def job(self, code, env=None):
        return subprocess.run([sys.executable, str(REPO / "extras" / "jobs" / "job.py"), "sweep", "--",
                               sys.executable, "-c", "import sys; sys.exit(%d)" % code],
                              env=dict(self.env, **(env or {})), capture_output=True, text=True)

    def seen(self):
        return [json.loads(l) for l in self.notices.read_text().splitlines()] if self.notices.exists() else []

    def test_settings_switched_off_send_nothing(self):
        self.assertEqual(3, self.job(3).returncode)
        self.assertEqual([], self.seen())

    def test_a_plists_GARRICK_NOTIFY_CMD_still_delivers(self):
        self.assertEqual(3, self.job(3, {"GARRICK_NOTIFY_CMD": self.cmd + " plist"}).returncode)
        self.assertEqual([["plist", "Job failed", "job-failed", "failed"]], self.seen())

    def test_a_line_of_its_own_names_an_event(self):
        r = subprocess.run([sys.executable, str(REPO / "extras" / "jobs" / "job.py"), "notify", "--event", "todo-summary",
                            "Digest", "Three open."], env=dict(self.env, GARRICK_NOTIFY_CMD=self.cmd + " plist"),
                           capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual([["plist", "Digest", "todo-summary", "message"]], self.seen())


class TestPageAndSettings(Case):
    """Settings › Notifications: what the page shows, and what page_action.py keeps."""

    def setUp(self):
        super().setUp()
        self.pa = _load("garrick_page_action_notify", REPO / "extras" / "status" / "page_action.py")
        self.status = _load("garrick_status_notify", REPO / "extras" / "status" / "status.py")
        self.lib = self.pa.notifications_lib(self.ws)
        p = mock.patch.object(self.lib, "_run", self.run_)
        p.start()
        self.addCleanup(p.stop)

    def section(self):
        html = self.status.build(self.ws, folder=self.base / "jobs")
        start = html.index('<section class="setsec apponly" id="notify-settings"')
        return html[start:html.index("</section>", start)]

    def page_request(self, **more):
        return dict({"tell": {"needs-you": True, "finished": False, "todo-summary": True, "job-failed": True},
                     "after": 4, "quiet": {"on": True, "from": "22:30", "to": "07:00"}}, **more)

    def test_saved_with_the_other_settings_then_shown(self):
        write(self.ws / "System" / "garrick-settings.json", json.dumps({"zones": {"Work": {"color": "Teal"}}}))
        self.assertEqual("Settings saved", self.pa.save_settings(self.ws, {"verb": "settings", "notifications": self.page_request()}))
        data = json.loads((self.ws / "System" / "garrick-settings.json").read_text())
        self.assertEqual({"Work": {"color": "Teal"}}, data["zones"])
        self.assertEqual(self.page_request(), data["notifications"])
        sec = self.section()
        self.assertIn('<input type="checkbox" data-nt="needs-you" checked>', sec)
        self.assertIn('<input type="checkbox" data-nt="finished" aria-label="a long task finishes">', sec)
        self.assertIn('id="n-after" min="0" max="240" value="4"', sec)
        self.assertIn('id="n-from" value="22:30"', sec)

    def test_a_refusal_keeps_what_was_saved(self):
        for bad in (self.page_request(after=999), dict(self.page_request(), channels={"telegram": True})):
            with self.assertRaises(self.pa.Refused):
                self.pa.save_settings(self.ws, {"verb": "settings", "notifications": bad})
        self.assertFalse((self.ws / "System" / "garrick-settings.json").exists())

    def test_tests_and_telegram_are_not_settings_any_more(self):
        ops = _load("garrick_ops_for_page", TOOLS / "operations.py")
        for gone in ({"test": "mac"}, {"token": "x"}, {"find-chat": True}, {"catch-up": {"period": "week"}}):
            self.assertIsNotNone(ops.validate("settings", dict({"verb": "settings"}, **gone)), gone)
        with self.assertRaises(self.pa.Refused):
            self.pa.save_settings(self.ws, {"verb": "settings", "test": "mac"})
        self.assertEqual([], self.run_.calls)

    def test_four_choices_and_quiet_hours_and_nothing_else(self):
        sec = self.section()
        for words in ("Notices appear on this Mac.", "Tell me when", "a session needs me", "a long task finishes",
                      "the morning Todo summary is ready", "a scheduled job fails", "Quiet from"):
            self.assertIn(words, sec)
        self.assertIn('a long task finishes, <span class="nsafter">after <input type="number" id="n-after"', sec)
        self.assertIn('<p class="hint nsrule">At night only &#8220;a session needs me&#8221; and the desk get through.</p>', sec)
        self.assertIn("With all four off, Garrick sends nothing.", sec)                      # behind the "?"
        for gone in ("Telegram", "My phone", "More options", "data-nch", "n-chat", "A command of your own", "data-nzto",
                     "Send to", "Send a test", "custom", "data-naway", "nover"):
            self.assertNotIn(gone, sec)
        self.assertEqual(4, sec.count('data-nt="'))

    def test_the_jobs_that_override_are_not_a_line_of_state(self):
        agents = self.base / "LaunchAgents"
        agents.mkdir()
        import plistlib
        (agents / "todo-sweep.plist").write_bytes(plistlib.dumps({
            "Label": "garrick.todo-sweep", "ProgramArguments": ["/usr/bin/python3", "/w/System/jobs/job.py", "todo-sweep", "--", "true"],
            "EnvironmentVariables": {"GARRICK_NOTIFY_CMD": "/bin/sh /opt/acme/notify.sh"}}))
        with mock.patch.object(self.status, "launch_agents", lambda: agents):
            sec = self.section()
        self.assertNotIn("scheduled job sends", sec)
        self.assertIn("A scheduled job whose launchd plist sets GARRICK_NOTIFY or GARRICK_NOTIFY_CMD sends its notices its own way.",
                      sec)                                                                      # said once, behind the "?"

    def test_the_script_reads_the_form_into_what_clean_takes(self):
        js = self.status.NOTIFY_JS
        self.assertIn("return{tell:t,after:", js)
        self.assertIn("quiet:{on:!!(qt&&qt.checked),from:val('n-from')||'22:00',to:val('n-to')||'07:00'}}", js)
        self.assertIn("if(n)q.notifications=N.request()", self.status.JS)                  # sent when Settings closes
        if shutil.which("node"):
            done = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0,'utf8'))"], input=js,
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(0, done.returncode, done.stderr)


if __name__ == "__main__":
    unittest.main()
