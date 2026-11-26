"""Remote access (preview): the one stable address, from a relay or from an address of your own (#696).

    cd tests && python3 -m unittest test_remote_address

The relay is a fake command line, a shell script that answers from a file. Nothing here opens a public address or reaches a real relay.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "remote" / "tests"))

from remote_fixture import RemoteCase, mod  # noqa: E402

SCRIPT = """#!/bin/sh
D="$(dirname "$0")"
echo "$@" >> "$D/cli.log"
case "$1" in
  status) cat "$D/status.json"; exit 0;;
  funnel) [ -f "$D/funnel-refused" ] && { echo "Funnel not enabled" >&2; exit 1; }; echo ok; exit 0;;
esac
exit 2
"""


def status_json(state="Running", name="mac.tail1234.ts.net."):
    return json.dumps({"BackendState": state, "Self": {"DNSName": name}})


class Relay(RemoteCase):
    def setUp(self):
        super().setUp()
        self.ad = mod("address")
        self.act = mod("settings_actions")
        self.bin = Path(self._tmp.name) / "bin"
        self.bin.mkdir()
        self.cli = self.bin / "relay"
        self.cli.write_text(SCRIPT)
        self.cli.chmod(0o755)
        (self.bin / "status.json").write_text(status_json())
        os.environ["GARRICK_REMOTE_RELAY_CLI"] = str(self.cli)

    def log(self):
        p = self.bin / "cli.log"
        return p.read_text() if p.exists() else ""

    def test_setup_publishes_the_local_port_and_reads_the_address_back(self):
        out = self.ad.relay_setup(8781)
        self.assertEqual(out, {"ok": True, "url": "https://mac.tail1234.ts.net"})
        self.assertIn("funnel --bg 8781", self.log())

    def test_it_never_publishes_a_port_other_than_the_service_port(self):
        self.ad.relay_setup(8781)
        pushed = [l for l in self.log().splitlines() if l.startswith("funnel")]
        self.assertEqual(pushed, ["funnel --bg 8781"])

    def test_the_app_inside_the_relay_is_preferred_to_the_path(self):
        self.assertEqual(self.ad.APP_CLI, "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
        app, onpath = str(self.bin / "app-cli"), str(self.bin / "path-cli")
        (self.bin / "app-cli").write_text(SCRIPT)
        which = lambda name: onpath if name == "tailscale" else None
        self.assertEqual(self.ad.find_cli({}, app, which), app)
        self.assertEqual(self.ad.find_cli({}, str(self.bin / "no-app"), which), onpath)
        self.assertIsNone(self.ad.find_cli({}, str(self.bin / "no-app"), lambda name: None))
        self.assertEqual(self.ad.find_cli({self.ad.CLI_ENV: str(self.cli)}, app, which), str(self.cli))

    def test_the_missing_steps_are_plain_and_each_has_one_next_step(self):
        os.environ["GARRICK_REMOTE_RELAY_CLI"] = str(self.bin / "nothing")
        a = self.ad.relay_setup(8781)
        self.assertEqual(a, {"ok": False, "say": self.ad.NO_APP})
        os.environ["GARRICK_REMOTE_RELAY_CLI"] = str(self.cli)
        (self.bin / "status.json").write_text(status_json("NeedsLogin"))
        self.assertEqual(self.ad.relay_setup(8781)["say"], self.ad.NO_SIGN_IN)
        (self.bin / "status.json").write_text(status_json())
        (self.bin / "funnel-refused").write_text("")
        self.assertEqual(self.ad.relay_setup(8781)["say"], self.ad.NO_PUBLISH)
        (self.bin / "funnel-refused").unlink()
        (self.bin / "status.json").write_text(status_json(name=""))
        self.assertEqual(self.ad.relay_setup(8781)["say"], self.ad.NO_ADDRESS)
        for sentence in (self.ad.NO_APP, self.ad.NO_SIGN_IN, self.ad.NO_PUBLISH, self.ad.NO_ADDRESS, self.ad.NOT_AN_ORIGIN,
                         self.ad.LOST, self.ad.CHANGED):
            self.assertNotRegex(sentence, r"[/\\]|--|\.py|\bexit\b|Traceback")

    def test_a_lost_relay_and_a_changed_address_are_found_by_the_check(self):
        kept = "https://mac.tail1234.ts.net"
        self.assertEqual(self.ad.check_relay(kept), {"ok": True, "url": kept})
        (self.bin / "status.json").write_text(status_json("Stopped"))
        lost = self.ad.check_relay(kept)
        self.assertFalse(lost["ok"])
        (self.bin / "status.json").write_text(status_json(name="mac-2.tail1234.ts.net."))
        changed = self.ad.check_relay(kept)
        self.assertTrue(changed["ok"] and changed["changed"])
        self.assertEqual(changed["url"], "https://mac-2.tail1234.ts.net")
        self.assertIn("again", changed["say"])

    def test_enable_through_the_relay_keeps_the_address_and_says_when_it_changes(self):
        out = self.act.run(self.ws, {"action": "enable", "adapter": "relay"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.state.address(), dict(self.state.address(), url="https://mac.tail1234.ts.net", adapter="relay"))
        (self.bin / "status.json").write_text(status_json(name="other.tail1234.ts.net."))
        again = self.act.run(self.ws, {"action": "enable", "adapter": "relay"})
        self.assertIn(self.ad.CHANGED, again["say"])
        self.assertEqual(self.state.address()["url"], "https://other.tail1234.ts.net")

    def test_enable_with_a_relay_that_is_missing_still_says_the_one_next_step(self):
        os.environ["GARRICK_REMOTE_RELAY_CLI"] = str(self.bin / "nothing")
        out = self.act.run(self.ws, {"action": "enable", "adapter": "relay"})
        self.assertFalse(out["ok"])
        self.assertIn(self.ad.NO_APP, out["say"])
        self.assertEqual(self.state.address()["url"], "")
        self.assertEqual(self.state.status(), "off")                        # a relay that cannot publish turns nothing on
        self.assertFalse(self.act.run(self.ws, {"action": "pair"})["ok"])

    def test_the_address_survives_a_restart_and_an_update(self):
        self.act.run(self.ws, {"action": "enable", "adapter": "relay"})
        for name in list(sys.modules):
            if name.startswith("garrick_remote_"):
                del sys.modules[name]
        self.assertEqual(mod("state").address()["url"], "https://mac.tail1234.ts.net")

    def test_off_stops_publishing(self):
        self.act.run(self.ws, {"action": "enable", "adapter": "relay"})
        self.act.run(self.ws, {"action": "off"})
        self.assertIn("funnel --https=443 off", self.log())


class OwnAddress(RemoteCase):
    def setUp(self):
        super().setUp()
        self.ad = mod("address")

    def test_a_public_https_origin_is_taken(self):
        for good, kept in (("https://mcp.example.test", "https://mcp.example.test"), ("https://MCP.Example.test/", "https://mcp.example.test"),
                           ("https://mcp.example.test:8443", "https://mcp.example.test:8443")):
            self.assertEqual(self.ad.own_address(good), {"ok": True, "url": kept}, good)

    def test_anything_else_is_refused(self):
        for bad in ("", "mcp.example.test", "http://mcp.example.test", "https://", "https://10.0.0.5", "https://[::1]", "https://localhost",
                    "https://machine.local", "https://nodots", "https://mcp.example.test/mcp", "https://mcp.example.test?a=1",
                    "https://mcp.example.test#x", "https://a:b@mcp.example.test", "https://-bad.example.test", "javascript:alert(1)"):
            self.assertFalse(self.ad.own_address(bad)["ok"], bad)

    def test_the_callers_address_is_used_only_where_the_proxy_is_trusted(self):
        headers = {"x-forwarded-for": "203.0.113.9, 198.51.100.4"}
        self.assertEqual(self.ad.caller("127.0.0.1", headers, False), "127.0.0.1")
        self.assertEqual(self.ad.caller("127.0.0.1", headers, True), "198.51.100.4")      # the proxy's own entry, not the forged one
        self.assertEqual(self.ad.caller("127.0.0.1", {"x-forwarded-for": "not an ip"}, True), "127.0.0.1")

    def test_changing_the_own_address_is_reported(self):
        self.state.set_address("https://a.example.test", "own")
        self.assertEqual(self.state.set_address("https://b.example.test", "own"), {"changed": True, "previous": "https://a.example.test"})
        self.assertEqual(self.state.set_address("https://b.example.test", "own"), {"changed": False, "previous": "https://b.example.test"})


class NothingBeyondLoopback(unittest.TestCase):
    def test_the_service_names_no_address_but_loopback(self):
        src = (Path(__file__).resolve().parent.parent / "extras" / "remote" / "service.py").read_text()
        self.assertIn('HOST = "127.0.0.1"', src)
        self.assertNotIn("0.0.0.0", src)
        self.assertNotIn('host=""', src)
        self.assertIn("host=HOST", src)


if __name__ == "__main__":
    unittest.main()
