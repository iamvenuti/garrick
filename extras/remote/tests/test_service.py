"""The service as a process (#695): when it starts, where it listens, and what stops it.

    <runtime python> -m unittest test_service        (from extras/remote/tests)

Each test starts `service.py` as launchd would, with the fake home and state folder, on a port that was free a moment ago; none opens a
public address.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

import httpx2

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from remote_fixture import EXTRA, RemoteCase, mod  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Process(RemoteCase):
    def setUp(self):
        super().setUp()
        self.port = free_port()
        self.state.set_port(self.port)
        self.proc = None
        self.addCleanup(self.stop)

    def command(self, *more):
        return [sys.executable, str(EXTRA / "service.py"), "--workspace", str(self.ws), *more]

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def start(self):
        self.proc = subprocess.Popen(self.command(), env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
        for _ in range(100):
            try:
                if httpx2.get("http://127.0.0.1:%d/health" % self.port, timeout=2).status_code in (200, 503):
                    return
            except httpx2.HTTPError:
                time.sleep(0.1)
        self.fail("the service did not come up: %s" % self.proc.poll())

    def check(self):
        return subprocess.run(self.command("--check"), capture_output=True, text=True, env=dict(os.environ)).stdout.strip()


class Refusals(Process):
    def test_check_says_why_it_would_not_start(self):
        self.assertEqual(self.check(), "Remote access is off.")
        self.state.set_address("https://home.example.test", "own")
        self.state.set_status("paused")
        self.assertEqual(self.check(), "Remote access is paused.")
        self.state.set_status("on")
        self.assertEqual(self.check(), "ok")
        self.role("roaming")
        self.assertIn("roaming", self.check())
        self.role("solo")
        self.state.clear_address()
        self.assertEqual(self.check(), "Remote access has no address yet.")
        self.state.set_address("http://home.example.test", "own")
        self.assertEqual(self.check(), "The address is not a secure one.")

    def test_off_paused_and_roaming_start_nothing_and_exit_cleanly(self):
        for prepare in (lambda: None, lambda: (self.state.set_address("https://home.example.test", "own"), self.state.set_status("paused")),
                        lambda: (self.state.set_status("on"), self.role("roaming"))):
            prepare()
            r = subprocess.run(self.command(), capture_output=True, text=True, timeout=30, env=dict(os.environ))
            self.assertEqual(r.returncode, 0)                    # a clean stop: launchd does not start it again in a loop
            with self.assertRaises(httpx2.HTTPError):
                httpx2.get("http://127.0.0.1:%d/health" % self.port, timeout=1)

    def test_a_workspace_that_will_not_say_its_role_starts_nothing(self):
        self.turn_on()
        (self.ws / "System" / "tools").unlink()
        self.assertIn("roaming", self.check())


class Listening(Process):
    def test_it_listens_on_loopback_alone(self):
        self.turn_on()
        self.start()
        self.assertEqual(httpx2.get("http://127.0.0.1:%d/health" % self.port).status_code, 200)
        lsof = shutil.which("lsof")
        if not lsof:
            self.skipTest("no lsof to read the sockets")
        out = subprocess.run([lsof, "-nP", "-a", "-p", str(self.proc.pid), "-iTCP", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        listening = [line.split()[-2] for line in out.splitlines()[1:] if "LISTEN" in line]
        self.assertTrue(listening, out)
        for name in listening:
            self.assertTrue(name.startswith("127.0.0.1:"), name)

    def test_a_pause_blocks_the_next_call_without_a_restart_and_an_off_does_too(self):
        self.turn_on()
        self.start()
        url = "http://127.0.0.1:%d/health" % self.port
        self.assertEqual(httpx2.get(url).status_code, 200)
        self.state.set_status("paused")
        self.assertEqual(httpx2.get(url).status_code, 503)
        self.state.set_status("on")
        self.assertEqual(httpx2.get(url).status_code, 200)
        self.state.set_status("off")
        self.assertEqual(httpx2.get(url).status_code, 503)

    def test_a_roaming_role_set_while_it_runs_closes_it_within_seconds(self):
        self.turn_on()
        self.start()
        url = "http://127.0.0.1:%d/health" % self.port
        self.role("roaming")
        for _ in range(80):
            if httpx2.get(url).status_code == 503:
                return
            time.sleep(0.1)
        self.fail("a roaming computer kept serving")

    def test_nothing_the_libraries_say_leaves_the_process(self):
        self.turn_on()
        self.start()
        httpx2.post("http://127.0.0.1:%d/token" % self.port, data={"grant_type": "authorization_code", "code": "SECRET-CODE-123"}, timeout=5)
        httpx2.post("http://127.0.0.1:%d/mcp" % self.port, content=b"{not json SECRET-BODY-456", timeout=5,
                    headers={"Content-Type": "application/json", "Authorization": "Bearer SECRET-TOKEN-789"})
        self.stop()
        out, err = self.proc.stdout.read(), self.proc.stderr.read()
        for secret in ("SECRET-CODE-123", "SECRET-BODY-456", "SECRET-TOKEN-789"):
            self.assertNotIn(secret, out + err)
        log = (self.state.home() / "service.log")
        if log.exists():
            for secret in ("SECRET-CODE-123", "SECRET-BODY-456", "SECRET-TOKEN-789"):
                self.assertNotIn(secret, log.read_text())

    def test_the_service_starts_without_the_tools_folder_and_says_so_in_its_log(self):
        self.turn_on()
        if not (EXTRA / "tools").is_dir():
            self.start()
            self.assertIn('"tool": "no-tools"', (self.state.home() / "service.log").read_text())


if __name__ == "__main__":
    unittest.main()
