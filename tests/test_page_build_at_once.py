"""The app's own saved actions build the page at once (reload-0860, V3).

    cd tests && python3 -m unittest test_page_build_at_once

After an action the Mac app sent (`--via page`) saved, page_action.py asks for no page: the app builds at once, with
the check's kept result. Ask, a session, a hook and remote access still ask, with the ten seconds that make one page
from a burst. Both mixes work: an app from before this release rebuilds after any reply that has no `built`, and a
page_action.py from before it still asks, which a reply with `built` tells the new app to rely on.
The cases that run the app itself are in tools/app_check.py ("a saved action builds at once", "an older action
script still asks for the page").
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import test_scaffold_manage as base  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
pa = base.pa
SWIFT = (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")


class AtOnce(base.ManageCase):
    def setUp(self):
        super().setUp()
        self.lib = pa.prefs().lib(self.root)

    def perform(self, thread, via):
        req = {"verb": "park", "zone": "Work", "project": "Acme", "thread": thread}
        with mock.patch.object(self.lib, "detach", return_value=True) as spawn:
            out, _, _ = pa.perform(self.root, req, pa.ops_lib(self.root), via=via)
        return out, [c.args[0] for c in spawn.call_args_list]

    def test_the_apps_own_saved_action_asks_for_no_page(self):
        out, spawned = self.perform("Freight", "page")
        self.assertTrue(out["ok"])
        self.assertEqual("saved", out["outcome"])             # what the app reads to build with the check's kept result
        self.assertNotIn("built", out)                        # so the app builds, and an older app rebuilds as it always did
        self.assertEqual([], spawned)
        self.assertEqual("Acme, Freight: parked", self.git("log", "-1", "--format=%s").stdout.strip())

    def test_every_other_caller_still_asks_with_the_ten_seconds(self):
        for via, verb in (("session", "park"), ("ask", "wake")):
            with self.subTest(via=via):
                req = {"verb": verb, "zone": "Work", "project": "Acme", "thread": "Freight"}
                with mock.patch.object(pa, "ask_for_page", return_value=True) as asks:
                    out, _, _ = pa.perform(self.root, req, pa.ops_lib(self.root), via=via)
                self.assertTrue(out["ok"], out)
                asks.assert_called_once_with(self.root)
                self.assertIs(True, out["built"])

    def test_a_session_asks_for_the_settled_build(self):
        out, spawned = self.perform("Freight", "session")
        self.assertIs(True, out["built"])
        self.assertEqual(1, len(spawned))
        self.assertEqual("10", spawned[0][spawned[0].index("--settle") + 1])
        self.assertEqual(10, pa.PAGE_SETTLE)

    def test_a_refusal_still_has_no_built_for_the_app_to_rebuild_on(self):
        req = {"verb": "wake", "zone": "Work", "project": "Acme", "thread": "Pricing"}     # active already
        with mock.patch.object(self.lib, "detach", return_value=True) as spawn:
            out, _, _ = pa.perform(self.root, req, pa.ops_lib(self.root), via="page")
        self.assertEqual((False, False, 0), (out["ok"], "built" in out, spawn.call_count))


class TheApp(unittest.TestCase):
    def act(self):
        return SWIFT[SWIFT.index("\tfunc act(_ request"):SWIFT.index("\tfunc acted(")]

    def test_the_app_still_trusts_a_reply_that_says_it_built(self):
        """An older page_action.py asks for the page and says so: the app does not build as well."""
        self.assertIn('reply["built"] == nil', self.act())

    def test_the_app_builds_at_once_with_the_kept_result_only_when_the_reply_says_saved(self):
        self.assertIn('self.freshen(force: true, kept: reply["outcome"] as? String == "saved")', self.act())
        rebuild = SWIFT[SWIFT.index("\tfunc rebuild(queue"):SWIFT.index("\t// status.py writes a temporary file")]
        self.assertIn('(kept ? ["--reuse-check"] : [])', rebuild)
        self.assertIn("rebuild(kept: self.againKept)", rebuild)

    def test_the_build_queued_behind_a_running_one_keeps_the_result_only_if_every_request_did(self):
        self.assertIn("againKept = again ? againKept && kept : kept", SWIFT)

    def test_the_apps_request_is_still_the_page_route(self):
        self.assertIn('"--via", "page"]', self.act())          # writes do not move


if __name__ == "__main__":
    unittest.main()
