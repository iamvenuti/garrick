"""Remote access (preview): the switch, its state folder, the host check and the actions of Settings (#695).

    cd tests && python3 -m unittest test_remote_state

Standard library only. The fake home, the fake state folder and a fake launchctl stand in for this Mac.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "remote" / "tests"))

from remote_fixture import RemoteCase, mod  # noqa: E402


class Case(RemoteCase):
    def setUp(self):
        super().setUp()
        self.act = mod("settings_actions")
        self.la = mod("launchagent")
        self.calls = []
        fake = self.home / "launchctl"
        fake.write_text("#!/bin/sh\necho \"$@\" >> %s\nexit 0\n" % (self.home / "launchctl.log"), encoding="utf-8")
        fake.chmod(0o755)
        os.environ["GARRICK_REMOTE_LAUNCHCTL"] = str(fake)

    def run_act(self, action, **kw):
        return self.act.run(self.ws, dict(kw, action=action))

    def make_runtime_ready(self):
        runtime = self.state.runtime_dir()
        (runtime / "python" / "bin").mkdir(parents=True)
        (runtime / "python" / "bin" / "python3").write_text("#!/bin/sh\n", encoding="utf-8")
        (runtime / "ready.json").write_text('{"ok": true, "lock": "%s"}' % self.state.lock_hash(), encoding="utf-8")

    def launchctl_log(self):
        p = self.home / "launchctl.log"
        return p.read_text() if p.exists() else ""


class StateFolder(Case):
    def test_the_state_folder_is_private_and_outside_the_workspace(self):
        self.state.set_status("on")
        folder = self.state.home()
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((folder / "settings.json").stat().st_mode), 0o600)
        self.assertNotIn(str(self.ws), str(folder))

    def test_default_folder_is_application_support_under_home(self):
        del os.environ["GARRICK_REMOTE_HOME"]
        self.assertEqual(self.state.home(), self.home / "Library" / "Application Support" / "Garrick" / "remote")

    def test_a_missing_or_broken_file_reads_as_off(self):
        self.assertEqual(self.state.status(), "off")
        self.state.ensure_home()
        (self.state.home() / "settings.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.state.status(), "off")
        (self.state.home() / "settings.json").write_text('{"status": "sure"}', encoding="utf-8")
        self.assertEqual(self.state.status(), "off")

    def test_secret_files_are_0600(self):
        code, _ = self.store.make_pairing_code()
        self.store.handle_key()
        for name in ("auth.json", "handle.key", "auth.lock"):
            self.assertEqual(stat.S_IMODE((self.state.home() / name).stat().st_mode), 0o600, name)

    def test_the_default_port_and_loopback(self):
        self.assertEqual(self.state.port(), 8781)
        self.assertEqual(self.state.LOOPBACK, "127.0.0.1")


class HostCheck(Case):
    def test_a_roaming_computer_cannot_turn_it_on(self):
        self.role("roaming")
        out = self.run_act("enable", adapter="own", address="https://home.example.test")
        self.assertFalse(out["ok"])
        self.assertIn("roaming", out["say"])
        self.assertEqual(self.state.status(), "off")
        self.assertFalse(self.la.written())
        self.assertEqual(self.spawned, [])

    def test_solo_and_server_may(self):
        for role in ("solo", "server"):
            self.role(role)
            self.assertEqual(self.state.host_refusal(self.ws), "", role)
            self.assertTrue(self.state.view(self.ws)["can_enable"])

    def test_a_computer_with_no_role_file_is_solo(self):
        self.assertEqual(self.state.role(self.ws), "solo")

    def test_a_workspace_that_cannot_say_its_role_is_refused(self):
        os.unlink(str(self.ws / "System" / "tools"))
        self.assertEqual(self.state.role(self.ws), "roaming")
        self.assertNotEqual(self.state.host_refusal(self.ws), "")

    def test_resume_on_a_roaming_computer_is_refused(self):
        self.turn_on()
        self.run_act("pause")
        self.role("roaming")
        out = self.run_act("resume")
        self.assertFalse(out["ok"])
        self.assertEqual(self.state.status(), "paused")

    def test_not_installed_changes_nothing(self):
        os.unlink(str(self.ws / "System" / "remote"))
        out = self.run_act("enable", adapter="own", address="https://home.example.test")
        self.assertFalse(out["ok"])
        self.assertEqual(self.state.status(), "off")
        self.assertEqual(self.state.view(self.ws)["installed"], False)


class Actions(Case):
    def test_enable_with_an_address_of_your_own_starts_the_setup_when_the_software_is_missing(self):
        out = self.run_act("enable", adapter="own", address="https://home.example.test")
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.state.status(), "on")
        self.assertEqual(self.state.address()["url"], "https://home.example.test")
        self.assertEqual(len(self.spawned), 1)
        self.assertIn("setup_runtime.py", " ".join(self.spawned[0][0]))
        self.assertFalse(self.la.written())                                  # nothing starts before the software is there

    def test_enable_with_the_software_ready_loads_the_agent(self):
        self.make_runtime_ready()
        out = self.run_act("enable", adapter="own", address="https://home.example.test")
        self.assertTrue(out["ok"], out)
        self.assertTrue(self.la.written())
        self.assertIn("bootstrap", self.launchctl_log())
        self.assertEqual(self.spawned, [])

    def test_a_runtime_made_from_an_older_lock_is_set_up_again(self):
        self.make_runtime_ready()
        (self.state.runtime_dir() / "ready.json").write_text('{"ok": true, "lock": "an-older-lock"}', encoding="utf-8")
        self.assertFalse(self.state.runtime_current())
        self.assertFalse({s["key"]: s["done"] for s in self.state.view(self.ws)["steps"]}["software"])
        out = self.run_act("enable", adapter="own", address="https://home.example.test")
        self.assertTrue(out["ok"])
        self.assertEqual(len(self.spawned), 1)
        self.assertFalse(self.la.written())

    def test_enable_never_runs_the_setup_twice_at_once(self):
        self.run_act("enable", adapter="own", address="https://home.example.test")
        self.state.write_json("setup.json", {"state": "running", "say": "x"})
        self.run_act("enable", adapter="own", address="https://home.example.test")
        self.assertEqual(len(self.spawned), 1)

    def test_a_bad_address_changes_nothing(self):
        for bad in ("http://home.example.test", "https://192.168.0.5", "https://localhost", "https://user:pw@home.example.test",
                    "https://home.example.test/path", "home.example.test", "https://nodots"):
            out = self.run_act("enable", adapter="own", address=bad)
            self.assertFalse(out["ok"], bad)
            self.assertEqual(self.state.status(), "off", bad)
            self.assertEqual(self.state.address()["url"], "", bad)

    def test_pause_closes_at_once_and_resume_opens(self):
        self.make_runtime_ready()
        self.turn_on()
        self.assertTrue(self.run_act("pause")["ok"])
        self.assertEqual(self.state.status(), "paused")
        self.assertFalse(self.run_act("pair")["ok"])                        # no code while paused
        self.assertTrue(self.run_act("resume")["ok"])
        self.assertEqual(self.state.status(), "on")

    def test_off_removes_the_agent_stops_the_relay_and_clears_the_code(self):
        self.make_runtime_ready()
        self.turn_on()
        self.assertTrue(self.run_act("pair")["ok"])
        self.la.plist_path().parent.mkdir(parents=True, exist_ok=True)
        self.la.plist_path().write_text("x")
        self.assertTrue(self.run_act("off")["ok"])
        self.assertEqual(self.state.status(), "off")
        self.assertFalse(self.la.written())
        self.assertFalse(self.store.pairing_state()["waiting"])
        self.assertIn("bootout", self.launchctl_log())

    def test_pair_gives_a_six_digit_code_and_keeps_only_its_hash(self):
        self.turn_on()
        out = self.run_act("pair")
        self.assertTrue(out["ok"])
        self.assertRegex(out["code"], r"^\d{6}$")
        self.assertEqual(out["seconds"], 300)
        self.assertNotIn(out["code"], out["say"])
        raw = (self.state.home() / "auth.json").read_text()
        self.assertNotIn(out["code"], raw)
        self.assertIn(self.store.sha(out["code"]), raw)

    def test_pair_needs_remote_access_on(self):
        self.assertFalse(self.run_act("pair")["ok"])

    def test_an_unknown_action_is_refused(self):
        self.assertFalse(self.run_act("wipe")["ok"])
        self.assertFalse(self.act.run(self.ws, "enable")["ok"])

    def test_actions_never_raise(self):
        with mock.patch.object(self.state, "set_status", side_effect=OSError("disk")):
            self.assertFalse(self.run_act("pause")["ok"])


class LaunchAgent(Case):
    def test_the_plist_starts_at_login_and_restarts_only_after_a_crash(self):
        py, svc = Path("/x/python3"), Path("/x/service.py")
        data = self.la.make_plist(self.ws, py, svc, self.home / "logs")
        self.assertTrue(data["RunAtLoad"])
        self.assertEqual(data["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(data["ProgramArguments"][:2], [str(py), str(svc)])

    def test_install_writes_under_the_fake_home_and_calls_the_fake_launchctl(self):
        res = self.la.install(self.ws, Path("/x/python3"), Path("/x/service.py"), self.home / "logs")
        self.assertTrue(res["ok"])
        self.assertTrue(str(self.la.plist_path()).startswith(str(self.home)))
        self.assertTrue(self.la.plist_path().is_file())
        self.assertIn("bootstrap", self.launchctl_log())

    def test_remove_unloads_and_deletes(self):
        self.la.install(self.ws, Path("/x/python3"), Path("/x/service.py"), self.home / "logs")
        self.assertTrue(self.la.remove())
        self.assertFalse(self.la.plist_path().exists())


class View(Case):
    def test_the_steps_follow_the_state(self):
        self.make_runtime_ready()
        v = self.state.view(self.ws)
        done = {s["key"]: s["done"] for s in v["steps"]}
        self.assertEqual(done, {"on": False, "software": True, "address": False, "service": False, "assistant": False})
        self.turn_on()
        self.assertTrue({s["key"]: s["done"] for s in self.state.view(self.ws)["steps"]}["address"])
        self.assertEqual(v["label"], "Preview")

    def test_the_view_holds_no_secret(self):
        self.turn_on()
        code, _ = self.store.make_pairing_code()
        gid = self.store.create_grant("c1", "Phone", ["read"])
        self.store.issue(gid, "c1", ["read"], "https://home.example.test/mcp")
        text = repr(self.state.view(self.ws))
        self.assertNotIn(code, text)
        self.assertNotIn("sha", text.lower().replace("shared", ""))
        self.assertEqual(self.state.view(self.ws)["grants"][0]["name"], "Phone")


if __name__ == "__main__":
    unittest.main()
