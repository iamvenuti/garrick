"""The one notifier, template/System/tools/notifications.py (#110), and what sends through it.

    cd tests && python3 -m unittest test_notifications

Nothing here reaches the network, the keychain or this Mac's notifications:
every way out (the module's _run and _urlopen) is a fake that records what it
was asked. The bot token below is invented, in the shape BotFather gives.
Invented names only.
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
import urllib.error
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
FAKE_TOKEN = "123456789:FAKEfakeFAKEfakeFAKEfakeFAKEfake123"


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


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.ws = self.base / "Workspace"
        build_workspace(self.ws)
        self.run_ = Recorder({"security": (0, FAKE_TOKEN + "\n")})
        self.posts = []
        for p in (mock.patch.object(n, "_run", self.run_), mock.patch.object(n, "_urlopen", self.urlopen),
                  mock.patch.object(n.sys, "platform", "darwin")):
            p.start()
            self.addCleanup(p.stop)
        self.reply = {"ok": True, "result": {}}

    def urlopen(self, req, timeout=None):
        self.posts.append((req.full_url, dict(x.split("=", 1) for x in req.data.decode().split("&"))))
        if isinstance(self.reply, Exception):
            raise self.reply
        return FakeResponse(json.dumps(self.reply).encode())

    def save(self, cfg):
        write(self.ws / "System" / "garrick-settings.json", json.dumps({"notifications": cfg}))

    def send(self, event, title="Title", message="Message", zone=None, now=NOON, env=None):
        return n.send(event, title, message, zone, root=self.ws, now=now, env=env if env is not None else {})

    def osascripts(self):
        return self.run_.named("osascript")


class TestSettings(Case):
    def test_defaults(self):
        cfg = n.settings(self.ws)
        self.assertEqual({"mac": True, "cmux": True, "telegram": False, "command": False}, cfg["channels"])
        self.assertEqual(["mac"], cfg["events"]["needs-you"]["to"])
        self.assertEqual(2, cfg["events"]["finished"]["after"])
        self.assertEqual([], cfg["events"]["todo-refreshed"]["to"])
        self.assertEqual(["mac"], cfg["events"]["todo-summary"]["to"])          # Telegram not set up yet
        self.assertEqual(["mac", "telegram", "command"], cfg["events"]["job-failed"]["to"])
        self.assertEqual({"on": True, "from": "22:00", "to": "07:00"}, cfg["quiet"])

    def test_the_summary_goes_to_telegram_once_it_is_set_up(self):
        self.save({"channels": {"telegram": True}, "telegram": {"chat": "4242"}})
        self.assertEqual(["telegram"], n.settings(self.ws)["events"]["todo-summary"]["to"])

    def test_telegram_without_a_chat_is_off(self):
        self.save({"channels": {"telegram": True}})
        self.assertFalse(n.settings(self.ws)["channels"]["telegram"])

    def test_the_settings_file_is_garrick_libs(self):
        lib = _load("garrick_lib_for_notifications", TOOLS / "garrick_lib.py")
        self.assertEqual(lib.SETTINGS, n.SETTINGS)
        self.assertIn(n.KEY, lib.PREFERENCES)
        ops = _load("garrick_ops_for_notifications", TOOLS / "operations.py")
        self.assertTrue({"notifications", "test"} <= set(ops.DECLARED["settings"].fields))

    def test_clean_keeps_what_the_page_sends(self):
        given = {"channels": {"mac": True, "cmux": False, "telegram": True, "command": False},
                 "telegram": {"chat": " -1001234 "}, "command": "",
                 "events": {"needs-you": {"to": ["mac", "telegram"], "quiet": "send", "away": True},
                            "finished": {"to": ["mac"], "quiet": "drop", "away": False, "after": 5}},
                 "quiet": {"on": True, "from": "21:30", "to": "06:45"},
                 "zones": {"Work": {"to": ["mac"]}, "Personal": {"to": ["mac", "telegram"], "chat": "777"}, "Gone": {"to": []}}}
        out = n.clean(given, zones=["Work", "Personal"])
        self.assertEqual("-1001234", out["telegram"]["chat"])
        self.assertEqual({"Work": {"to": ["mac"]}, "Personal": {"to": ["mac", "telegram"], "chat": "777"}}, out["zones"])
        self.assertEqual(5, out["events"]["finished"]["after"])
        self.assertTrue(out["events"]["needs-you"]["away"])

    def test_clean_refuses(self):
        for bad in ({"token": "x"},
                    {"channels": {"telegram": True}},
                    {"telegram": {"chat": "my phone"}},
                    {"channels": {"command": True}, "command": ""},
                    {"command": "say 'unclosed"},
                    {"events": {"birthday": {}}},
                    {"events": {"finished": {"after": 999}}},
                    {"events": {"todo-summary": {"away": True}}},
                    {"events": {"needs-you": {"to": ["pager"]}}},
                    {"events": {"job-idle": {"quiet": "later"}}},
                    {"quiet": {"from": "25:00"}},
                    {"zones": {"Work": {"chat": "nope"}}},
                    "everything"):
            with self.assertRaises(n.Invalid, msg=bad):
                n.clean(bad, zones=["Work", "Personal"])


class TestSend(Case):
    def test_this_mac_by_default(self):
        self.assertTrue(self.send("job-failed", "Job failed", "sweep exited 3"))
        (args,) = self.osascripts()
        self.assertEqual(["sweep exited 3", "Job failed"], args[-2:])

    def test_an_event_nobody_switched_on_goes_nowhere(self):
        self.assertFalse(self.send("todo-refreshed"))
        self.assertEqual([], self.run_.calls)

    def test_no_workspace_no_notice(self):
        self.assertFalse(n.send("job-failed", "t", "m", env={}, root=self.base))
        self.assertEqual([], self.run_.calls)

    def test_a_legacy_kind_names_its_event(self):
        self.save({"events": {"job-idle": {"to": []}}})
        self.assertFalse(n.send("idle", "Job idle", "m", root=self.ws, now=NOON, env={}))
        self.assertTrue(n.send("recovered", "Job recovered", "m", root=self.ws, now=NOON, env={}))

    def test_telegram_with_the_zones_own_chat(self):
        self.save({"channels": {"mac": False, "telegram": True}, "telegram": {"chat": "1111"},
                   "events": {"todo-summary": {"to": ["telegram"]}},
                   "zones": {"Personal": {"chat": "2222"}}})
        self.assertTrue(self.send("todo-summary", "Todo", "Todo · Work\n\nDue today · 1", zone="Work"))
        self.assertTrue(self.send("todo-summary", "Todo", "Todo · Personal", zone="Personal"))
        self.assertEqual(["1111", "2222"], [d["chat_id"] for _, d in self.posts])
        self.assertTrue(self.posts[0][0].endswith("/sendMessage"))
        self.assertEqual([["security", "find-generic-password", "-s", n.KEYCHAIN_SERVICE, "-a", n.KEYCHAIN_ACCOUNT, "-w"]] * 2,
                         self.run_.named("security"))

    def test_a_zone_keeps_its_notices_off_a_channel(self):
        self.save({"channels": {"telegram": True}, "telegram": {"chat": "1111"},
                   "events": {"job-failed": {"to": ["mac", "telegram"]}}, "zones": {"Work": {"to": ["mac"]}}})
        self.send("job-failed", zone="Work")
        self.assertEqual(([], 1), (self.posts, len(self.osascripts())))
        self.send("job-failed", zone="Personal")
        self.assertEqual(1, len(self.posts))

    def test_telegram_failures_never_carry_the_token(self):
        self.save({"channels": {"mac": False, "telegram": True}, "telegram": {"chat": "1111"}})
        log = io.StringIO()
        self.reply = urllib.error.URLError("no route to https://api.telegram.org/bot%s/sendMessage" % FAKE_TOKEN)
        self.assertFalse(n.send("job-failed", "Job failed", "m", root=self.ws, now=NOON, env={}, log=log))
        self.assertIn("Telegram could not be reached", log.getvalue())
        self.assertNotIn(FAKE_TOKEN, log.getvalue())
        self.reply = {"ok": False, "description": "Bad Request: chat not found"}
        self.assertEqual("said no: Bad Request: chat not found", n.telegram("1111", "x"))

    def test_no_token_says_how_to_store_one(self):
        self.run_.answers["security"] = (44, "")
        self.assertIn("telegram-token", n.telegram("1111", "x"))
        self.assertEqual([], self.posts)

    def test_a_command_of_your_own_gets_what_GARRICK_NOTIFY_CMD_got(self):
        self.save({"channels": {"mac": False, "command": True}, "command": "/bin/sh /opt/acme/notify.sh",
                   "events": {"todo-summary": {"to": ["command"]}}})
        self.assertTrue(n.send("todo-summary", "Todo", "Todo · Work", self.ws / "Zones" / "Work", root=self.ws,
                               kind="digest", now=NOON, env={"PATH": "/usr/bin"}))
        (args, kw), = self.run_.calls
        self.assertEqual(["/bin/sh", "/opt/acme/notify.sh", "Todo", "Todo · Work"], args)
        self.assertEqual(("digest", "todo-summary", "Work"), (kw["env"]["GARRICK_NOTIFY_KIND"], kw["env"]["GARRICK_NOTIFY_EVENT"],
                                                              kw["env"]["GARRICK_ZONE"]))
        self.assertEqual(str(self.ws / "Zones" / "Work"), kw["cwd"])

    def test_the_old_variables_override_the_settings(self):
        self.save({"channels": {"mac": True, "command": True}, "command": "/opt/acme/settings-notify"})
        env = {"GARRICK_NOTIFY_CMD": "/opt/acme/plist-notify"}
        self.assertTrue(self.send("job-failed", env=env))
        self.assertEqual([["/opt/acme/plist-notify", "Title", "Message"]], [a for a, _ in self.run_.calls])
        self.assertEqual(("GARRICK_NOTIFY_CMD",), n.override(env))
        self.assertEqual(("GARRICK_NOTIFY",), n.override({"GARRICK_NOTIFY": "1", "GARRICK_NOTIFY_CMD": " "}))


class TestQuietHours(Case):
    def test_held_till_morning_dropped_or_sent(self):
        self.save({"events": {"job-idle": {"quiet": "drop"}, "desk": {"quiet": "send"}}})
        self.assertTrue(self.send("job-failed", "Job failed", "held one", now=NIGHT))     # hold, the default
        self.assertFalse(self.send("job-idle", now=NIGHT))
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

    def test_in_cmux_the_notice_lands_on_the_tab_unless_you_are_looking(self):
        cmux = self.base / "cmux"
        write(cmux, "#!/bin/sh\n")
        cmux.chmod(0o755)
        env = {"CMUX_SURFACE_ID": "S1", "GARRICK_CMUX": str(cmux)}
        n.send("needs-you", "Needs you", "Work, Pricing: needs you. Permission asked.", "Work", root=self.ws, now=NOON, env=env)
        (args,) = self.run_.named("cmux")
        self.assertEqual(["notify", "--title", "Garrick", "--subtitle", "Needs you", "--body"], args[1:7])
        self.assertEqual([], self.osascripts())
        self.save({"events": {"needs-you": {"away": True}}})
        same = json.dumps({"caller": {"surface_ref": "surface:7"}, "focused": {"surface_ref": "surface:7"}})
        self.run_.answers.update({"cmux": lambda a, k: (0, same if "identify" in a else ""),
                                  "lsappinfo": lambda a, k: (0, '"CFBundleIdentifier"="com.cmuxterm.app"' if "info" in a else "ASN:0x1")})
        self.assertFalse(n.send("needs-you", "Needs you", "m", "Work", root=self.ws, now=NOON, env=env))
        other = json.dumps({"caller": {"surface_ref": "surface:7"}, "focused": {"surface_ref": "surface:9"}})
        self.run_.answers["cmux"] = lambda a, k: (0, other if "identify" in a else "")
        self.assertTrue(n.send("needs-you", "Needs you", "m", "Work", root=self.ws, now=NOON, env=env))


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


class TestToken(Case):
    def test_the_token_goes_in_on_stdin_never_as_an_argument(self):
        n.store_token(FAKE_TOKEN + "\n", self.ws)
        (args, kw), = [c for c in self.run_.calls if "-i" in c[0]]
        self.assertEqual(["security", "-i"], args)
        self.assertIn(FAKE_TOKEN, kw["input"])
        for a, _ in self.run_.calls:
            self.assertNotIn(FAKE_TOKEN, " ".join(a))
        self.assertEqual(dt.date.today().isoformat(), n.token_stored(self.ws))
        state = (self.ws / "System" / "generated" / "notifications" / "telegram.json").read_text()
        self.assertNotIn(FAKE_TOKEN, state)

    def test_not_a_token(self):
        with self.assertRaises(n.Invalid):
            n.store_token('123:abc" ; delete-keychain', self.ws)
        self.assertEqual([], self.run_.calls)


class TestThroughJobPy(unittest.TestCase):
    """job.py, as launchd runs it, sends through the module: the settings, or a plist's override."""

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
        write(self.ws / "System" / "garrick-settings.json", json.dumps({"notifications": {
            "channels": {"mac": False, "command": True}, "command": self.cmd + " settings", "quiet": {"on": False},
            "events": {"todo-summary": {"to": ["command"]}}}}))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("GARRICK_", "CMUX_"))}
        self.env.update(GARRICK_JOBS_DIR=str(base / "jobs"), GARRICK_WORKSPACE=str(self.ws), NOTICES=str(self.notices))

    def job(self, code, env=None):
        return subprocess.run([sys.executable, str(REPO / "extras" / "jobs" / "job.py"), "sweep", "--",
                               sys.executable, "-c", "import sys; sys.exit(%d)" % code],
                              env=dict(self.env, **(env or {})), capture_output=True, text=True)

    def seen(self):
        return [json.loads(l) for l in self.notices.read_text().splitlines()] if self.notices.exists() else []

    def test_the_settings_send_it(self):
        self.assertEqual(3, self.job(3).returncode)
        self.assertEqual([["settings", "Job failed", "job-failed", "failed"]], self.seen())

    def test_a_plists_GARRICK_NOTIFY_CMD_still_delivers(self):
        self.assertEqual(3, self.job(3, {"GARRICK_NOTIFY_CMD": self.cmd + " plist"}).returncode)
        self.assertEqual([["plist", "Job failed", "job-failed", "failed"]], self.seen())       # and not the settings' too

    def test_a_line_of_its_own_names_an_event(self):
        r = subprocess.run([sys.executable, str(REPO / "extras" / "jobs" / "job.py"), "notify", "--event", "todo-summary",
                            "Digest", "Three open."], env=self.env, capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual([["settings", "Digest", "todo-summary", "message"]], self.seen())


class TestPageAndSettings(Case):
    """Settings › Notifications: what the page shows, and what page_action.py keeps and tests."""

    def setUp(self):
        super().setUp()
        self.pa = _load("garrick_page_action_notify", REPO / "extras" / "status" / "page_action.py")
        self.status = _load("garrick_status_notify", REPO / "extras" / "status" / "status.py")
        self.lib = self.pa.notifications_lib(self.ws)
        for p in (mock.patch.object(self.lib, "_run", self.run_), mock.patch.object(self.lib, "_urlopen", self.urlopen)):
            p.start()
            self.addCleanup(p.stop)
        self.agents = self.base / "LaunchAgents"
        p = mock.patch.object(self.status, "launch_agents", lambda: self.agents)
        p.start()
        self.addCleanup(p.stop)

    def section(self):
        html = self.status.build(self.ws, folder=self.base / "jobs")
        start = html.index('<section class="setsec apponly" id="notify-settings">')
        return html[start:html.index("</section>", start)]

    def page_request(self, **more):
        return dict({"channels": {"mac": True, "cmux": True, "telegram": True, "command": False},
                     "telegram": {"chat": "4242"}, "command": "",
                     "events": {"needs-you": {"to": ["mac", "telegram"], "quiet": "send", "away": False}},
                     "quiet": {"on": True, "from": "22:00", "to": "07:00"},
                     "zones": {"Work": {"to": ["mac"]}, "Personal": {"to": ["mac", "telegram"], "chat": "777"}}}, **more)

    def test_saved_with_the_other_settings_then_shown(self):
        write(self.ws / "System" / "garrick-settings.json", json.dumps({"zones": {"Work": {"color": "Teal"}}}))
        self.assertEqual("Settings saved", self.pa.save_settings(self.ws, {"verb": "settings", "notifications": self.page_request()}))
        data = json.loads((self.ws / "System" / "garrick-settings.json").read_text())
        self.assertEqual({"Work": {"color": "Teal"}}, data["zones"])
        self.assertEqual("4242", data["notifications"]["telegram"]["chat"])
        sec = self.section()
        self.assertIn('id="n-chat" value="4242"', sec)
        self.assertIn('<tr data-nev="needs-you">', sec)
        self.assertRegex(sec, r'<tr data-nev="needs-you">.*?<input type="checkbox" data-nto="telegram" checked')
        self.assertRegex(sec, r'data-zone="Personal">.*?data-nzchat value="777"')
        self.assertIn("No token on this Mac yet", sec)
        self.assertIn('<tr data-nev="desk">', sec)                 # the cmux extra is beside the page here
        self.assertIn("data-naway", sec)

    def test_a_refusal_keeps_what_was_saved(self):
        with self.assertRaises(self.pa.Refused) as said:
            self.pa.save_settings(self.ws, {"verb": "settings", "notifications": self.page_request(telegram={"chat": ""}, zones={})})
        self.assertIn("Telegram needs a chat ID", str(said.exception))
        self.assertFalse((self.ws / "System" / "garrick-settings.json").exists())

    def test_send_a_test_saves_first_and_says_whether_it_went(self):
        req = {"verb": "settings", "notifications": self.page_request(), "test": "telegram"}
        self.assertEqual("Settings saved. A test went to Telegram", self.pa.save_settings(self.ws, req))
        self.assertEqual("4242", self.posts[0][1]["chat_id"])
        self.reply = {"ok": False, "description": "Forbidden: bot was blocked by the user"}
        with self.assertRaises(self.pa.Refused) as said:
            self.pa.save_settings(self.ws, req)
        self.assertEqual("Settings saved, but the test did not go: Telegram said no: Forbidden: bot was blocked by the user",
                         str(said.exception))
        self.assertEqual("A test went to this Mac", self.pa.save_settings(self.ws, {"verb": "settings", "test": "mac"}))
        with self.assertRaises(self.pa.Refused):
            self.pa.save_settings(self.ws, {"verb": "settings", "test": "pager"})

    def test_the_token_never_reaches_the_page_or_the_log(self):
        n.store_token(FAKE_TOKEN, self.ws)
        self.assertIn("Token kept in this Mac&#39;s keychain since", self.section())
        self.assertNotIn(FAKE_TOKEN, self.status.build(self.ws, folder=self.base / "jobs"))
        self.assertNotIn("notifications", self.pa.LOGGED)            # the audit log names the channel tested, nothing more
        self.assertIn("test", self.pa.LOGGED)

    def test_a_plist_that_overrides_is_named(self):
        import plistlib
        self.agents.mkdir()
        body = {"Label": "garrick.todo-sweep", "ProgramArguments": ["/usr/bin/python3", "/w/System/jobs/job.py", "todo-sweep", "--", "true"],
                "EnvironmentVariables": {"GARRICK_NOTIFY_CMD": "/bin/sh /opt/acme/notify.sh"}}
        (self.agents / "todo-sweep.plist").write_bytes(plistlib.dumps(body))
        self.assertIn("In force: GARRICK_NOTIFY_CMD for todo-sweep, set in a launchd plist", self.section())


if __name__ == "__main__":
    unittest.main()
