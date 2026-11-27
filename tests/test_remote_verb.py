"""The page-only verb `remote` (#701, decision 7): Settings' switch for remote access, done only at the Mac.

    cd tests && python3 -m unittest test_remote_verb

The handler is the extra's own System/remote/settings_actions.py, which these tests replace with a fake one in a fixture
workspace. The core only checks the action, loads the module by path and hands the request over.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import test_page_action as base  # noqa: E402

pa = base.pa

FAKE = '''
import json
from pathlib import Path

def run(ws, req):
    Path(ws, "System", "remote", "seen.json").write_text(json.dumps(req), encoding="utf-8")
    if req.get("grant") == "bad":
        return {"ok": False, "say": "No such grant."}
    if req.get("grant") == "boom":
        raise RuntimeError("secret detail")
    if req.get("grant") == "mute":
        return {"ok": True}
    return {"ok": True, "say": "Done: %s." % req["action"], "state": "on"}
'''


class RemoteVerbCase(base.ActionCase):
    def install(self, text=FAKE):
        folder = self.root / "System" / "remote"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "settings_actions.py").write_text(text, encoding="utf-8")

    def go(self, req, via="page"):
        return pa.perform(self.root, dict({"verb": "remote"}, **req), pa.ops_lib(self.root), via=via)[0]


class TestDeclared(RemoteVerbCase):
    def test_it_is_declared_page_only_and_a_verb(self):
        self.assertIn("remote", pa.ops_lib(self.root).DECLARED)
        self.assertIn("remote", pa.PAGE_ONLY)
        self.assertIn("remote", pa.VERBS)
        self.assertNotIn("remote", pa.ops_lib(self.root).RECORDED)

    def test_the_actions_are_the_seven(self):
        self.assertEqual(("enable", "pause", "resume", "off", "pair", "zone", "revoke"), pa.REMOTE_ACTIONS)

    def test_every_caller_but_the_page_is_refused(self):
        self.install()
        for via in ("ask", "session", "outbox", "remote"):
            with self.subTest(via=via):
                out = self.go({"action": "enable"}, via=via)
                self.assertFalse(out["ok"], out)
        self.assertFalse((self.root / "System" / "remote" / "seen.json").exists())


class TestDispatch(RemoteVerbCase):
    def test_without_the_extra_it_says_so(self):
        out = self.go({"action": "enable"})
        self.assertEqual({"ok": False, "say": "Remote access is not installed."}, {k: out[k] for k in ("ok", "say")})

    def test_each_action_reaches_the_module(self):
        self.install()
        for action in pa.REMOTE_ACTIONS:
            with self.subTest(action=action):
                out = self.go({"action": action, "zone": "Work"})
                self.assertTrue(out["ok"], out)
                self.assertEqual("Done: %s." % action, out["say"])
                seen = json.loads((self.root / "System" / "remote" / "seen.json").read_text(encoding="utf-8"))
                self.assertEqual((action, "Work"), (seen["action"], seen["zone"]))

    def test_an_action_outside_the_seven_never_reaches_it(self):
        self.install()
        for action in ("delete", "", None, 3, ["enable"], "ENABLE"):
            with self.subTest(action=action):
                self.assertFalse(self.go({"action": action})["ok"])
        self.assertFalse(self.go({})["ok"])
        self.assertFalse((self.root / "System" / "remote" / "seen.json").exists())

    def test_the_fields_the_settings_page_sends_are_declared(self):
        """Settings' script sends adapter and address with enable, and acknowledged with zone (settings_remote.py)."""
        self.install()
        for req in ({"action": "enable", "adapter": "own", "address": "https://mcp.acme.example"},
                    {"action": "zone", "grant": "g1", "zone": "Work", "read": True, "write": False, "acknowledged": True},
                    {"action": "revoke", "grant": "g1"}):
            with self.subTest(req=req):
                self.assertTrue(self.go(req)["ok"], req)

    def test_an_undeclared_field_is_refused_by_name(self):
        self.install()
        out = self.go({"action": "enable", "path": "/etc"})
        self.assertFalse(out["ok"], out)
        self.assertFalse((self.root / "System" / "remote" / "seen.json").exists())

    def test_the_modules_refusal_and_fault_are_plain(self):
        self.install()
        self.assertEqual("No such grant.", self.go({"action": "revoke", "grant": "bad"})["say"])
        out = self.go({"action": "revoke", "grant": "boom"})
        self.assertFalse(out["ok"])
        self.assertNotIn("secret detail", json.dumps(out))
        out = self.go({"action": "revoke", "grant": "mute"})
        self.assertFalse(out["ok"], out)

    def test_a_module_that_does_not_load_counts_as_absent(self):
        self.install("def run(:\n")
        self.assertEqual("Remote access is not installed.", self.go({"action": "enable"})["say"])
        self.install("x = 1\n")
        self.assertEqual("Remote access is not installed.", self.go({"action": "enable"})["say"])

    def test_a_link_out_of_the_folder_is_not_followed(self):
        outside = Path(self._tmp.name).resolve() / "elsewhere.py"
        outside.write_text(FAKE, encoding="utf-8")
        folder = self.root / "System" / "remote"
        folder.mkdir(parents=True)
        os.symlink(outside, folder / "settings_actions.py")
        self.assertEqual("Remote access is not installed.", self.go({"action": "enable"})["say"])


if __name__ == "__main__":
    unittest.main()
