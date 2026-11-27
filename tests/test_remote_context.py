"""Remote access (preview): one reach for each client, set on the Mac (#698).

    cd tests && python3 -m unittest test_remote_context

The default reach is the open zones, Knowledge and Garrick's docs. A walled zone joins only through Settings, by name, reads and writes
apart, after the notice, with the day. A handle keeps a chat to the reach it was made under. Standard library only.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "remote" / "tests"))

from remote_fixture import EXTRA, RemoteCase, mod  # noqa: E402


class Case(RemoteCase):
    def setUp(self):
        super().setUp()
        self.ctx = mod("context")
        self.act = mod("settings_actions")
        self.turn_on()

    def grant(self, classes=("read", "write"), name="Phone"):
        return self.store.create_grant("client-" + name, name, list(classes))

    def session(self, gid):
        return self.ctx.session_for(self.ws, gid)

    def zone(self, gid, zone, read=False, write=False, ack=True):
        return self.act.run(self.ws, {"action": "zone", "grant": gid, "zone": zone, "read": read, "write": write, "acknowledged": ack})


class Defaults(Case):
    def test_a_fresh_grant_reaches_the_open_zones_knowledge_and_the_docs_and_nothing_walled(self):
        s = self.session(self.grant())
        self.assertEqual(set(s.readable), {"Home", "Garden", "Knowledge", "docs"})
        self.assertEqual(set(s.writable), {"Home", "Garden"})
        for walled in ("Work", "Vault"):
            self.assertFalse(s.zone_allowed(walled))
            self.assertFalse(s.zone_allowed(walled, write=True))

    def test_the_zone_flags_come_from_the_workspaces_own_zone_function(self):
        self.assertEqual({z["zone"]: z["walled"] for z in self.ctx.zones(self.ws)}, {"Work": True, "Home": False, "Garden": False, "Vault": True})
        src = (EXTRA / "context.py").read_text()
        self.assertIn("load_context", src)
        self.assertNotIn("context.md", src.replace("`System/context.md`", ""))        # it names the file only in prose

    def test_a_zone_no_flag_names_is_walled_and_a_zone_that_changes_to_walled_leaves_the_reach(self):
        gid = self.grant()
        self.assertTrue(self.session(gid).zone_allowed("Garden"))
        text = (self.ws / "System" / "context.md").read_text().replace("| Garden | Things of garden | no |", "| Garden | Things of garden | yes |")
        (self.ws / "System" / "context.md").write_text(text)
        self.assertFalse(self.session(gid).zone_allowed("Garden"))

    def test_no_zone_function_means_no_zone(self):
        (self.ws / "System" / "tools").unlink()
        self.assertEqual(self.ctx.zones(self.ws), [])
        s = self.session(self.grant())
        self.assertEqual(set(s.readable), {"Knowledge", "docs"})
        self.assertEqual(set(s.writable), set())

    def test_the_class_decides_before_the_zone(self):
        s = self.session(self.grant(classes=("read",)))
        self.assertTrue(s.zone_allowed("Home"))
        self.assertFalse(s.zone_allowed("Home", write=True))

    def test_knowledge_and_docs_are_never_writable(self):
        s = self.session(self.grant())
        self.assertTrue(s.zone_allowed("Knowledge") and s.zone_allowed("docs"))
        self.assertFalse(s.zone_allowed("Knowledge", write=True) or s.zone_allowed("docs", write=True))

    def test_a_name_that_is_not_a_plain_zone_name_says_no(self):
        s = self.session(self.grant())
        for odd in (None, "", " ", 7, ["Home"], "../Work", "Home/../Work", "Work", "Zones/Work", "Home\x00", "<no zone>"):
            self.assertFalse(s.zone_allowed(odd), repr(odd))

    def test_a_grant_that_is_gone_or_revoked_has_no_session(self):
        gid = self.grant()
        self.store.revoke(gid)
        with self.assertRaises(ValueError):
            self.session(gid)
        with self.assertRaises(ValueError):
            self.session("g-000000000000")


class Walled(Case):
    def test_a_walled_zone_joins_by_name_with_the_notice_acknowledged_and_the_day_recorded(self):
        gid = self.grant()
        refused = self.zone(gid, "Work", read=True, ack=False)
        self.assertFalse(refused["ok"])
        self.assertFalse(self.session(gid).zone_allowed("Work"))
        done = self.zone(gid, "work", read=True)                                   # the name is matched without regard to case
        self.assertTrue(done["ok"], done)
        self.assertTrue(self.session(gid).zone_allowed("Work"))
        self.assertFalse(self.session(gid).zone_allowed("Work", write=True))      # reads and writes are separate
        row = [r for r in self.ctx.reach_rows(self.ws, gid) if r["zone"] == "Work"][0]
        self.assertEqual((row["walled"], row["read"], row["write"]), (True, True, False))
        self.assertRegex(row["since"], r"^\d{4}-\d\d-\d\d$")

    def test_writes_are_a_second_choice_and_need_the_grant_to_write(self):
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        self.assertTrue(self.zone(gid, "Work", read=True, write=True)["ok"])
        self.assertTrue(self.session(gid).zone_allowed("Work", write=True))
        reader = self.grant(classes=("read",), name="Tablet")
        out = self.zone(reader, "Work", read=True, write=True)
        self.assertFalse(out["ok"])
        self.assertFalse(self.session(reader).zone_allowed("Work"))             # nothing was half done

    def test_turning_a_zone_off_takes_it_out_and_lets_another_in(self):
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        self.assertFalse(self.zone(gid, "Vault", read=True)["ok"])
        self.assertTrue(self.zone(gid, "Work", read=False, write=False, ack=False)["ok"])        # turning off needs no notice
        self.assertFalse(self.session(gid).zone_allowed("Work"))
        self.assertTrue(self.zone(gid, "Vault", read=True)["ok"])
        self.assertTrue(self.session(gid).zone_allowed("Vault"))

    def test_the_action_takes_only_walled_zones_known_to_the_workspace(self):
        gid = self.grant()
        self.assertFalse(self.zone(gid, "Home", read=True)["ok"])                 # open already
        self.assertFalse(self.zone(gid, "Nowhere", read=True)["ok"])
        self.assertFalse(self.zone(gid, "../Work", read=True)["ok"])
        self.assertFalse(self.zone("g-nope", "Work", read=True)["ok"])
        self.assertFalse(self.zone("", "Work", read=True)["ok"])

    def test_two_grants_with_different_reach_see_only_their_own(self):
        a, b = self.grant(name="Phone"), self.grant(name="Tablet")
        self.zone(a, "Work", read=True)
        self.zone(b, "Vault", read=True)
        sa, sb = self.session(a), self.session(b)
        self.assertTrue(sa.zone_allowed("Work") and not sa.zone_allowed("Vault"))
        self.assertTrue(sb.zone_allowed("Vault") and not sb.zone_allowed("Work"))

    def test_a_walled_zone_that_leaves_the_workspace_leaves_the_reach(self):
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        text = (self.ws / "System" / "context.md").read_text().replace("| Work | Things of work | yes |\n", "")
        (self.ws / "System" / "context.md").write_text(text)
        self.assertFalse(self.session(gid).zone_allowed("Work"))

    def test_the_notice_is_the_fixed_text_with_the_zone_in_it(self):
        text = (EXTRA / "notice.md").read_text().strip()
        self.assertEqual(text.count("{zone}"), 1)
        self.assertEqual(self.state.view(self.ws)["notice"], text)
        for must in ("leaves this Mac", "relay carries it but cannot read it", "stays in the chat history after you revoke",
                     "Another connector in the same chat", "commit check does not see a chat"):
            self.assertIn(must, text)


class OneWalledZone(Case):
    """W1: one connection reaches one walled zone, for reads or for writes, so one answer never holds two."""

    SAY = "One connection reaches one walled zone. Use another connection for the second zone."

    def test_a_second_walled_zone_is_refused_with_one_plain_sentence(self):
        gid = self.grant()
        self.assertTrue(self.zone(gid, "Work", read=True)["ok"])
        for kw in ({"read": True}, {"write": True}, {"read": True, "write": True}):
            out = self.zone(gid, "Vault", **kw)
            self.assertEqual(out, {"ok": False, "say": self.SAY})
        self.assertEqual(self.store.get_grant(gid)["zones"].keys(), {"Work"})

    def test_one_walled_zone_may_have_its_reads_and_its_writes(self):
        gid = self.grant()
        self.assertTrue(self.zone(gid, "Work", read=True)["ok"])
        self.assertTrue(self.zone(gid, "Work", read=True, write=True)["ok"])
        self.assertTrue(self.session(gid).zone_allowed("Work", write=True))

    def test_two_stored_by_hand_reach_none_and_settings_says_why(self):
        gid = self.grant()
        with self.store.txn() as db:                         # the case the reviewer ran: a file edited by hand
            db["grants"][gid]["zones"] = {z: {"read": "2026-11-26", "write": "", "marker": self.ctx.zone_marker(self.ws, z)} for z in ("Work", "Vault")}
        s = self.session(gid)
        self.assertFalse(s.zone_allowed("Work") or s.zone_allowed("Vault"))
        self.assertEqual(set(s.readable), {"Home", "Garden", "Knowledge", "docs"})
        row = self.state.view(self.ws)["grants"][0]
        self.assertIn("more than one walled zone", row["reach_note"])

    def test_an_open_zone_does_not_count_and_one_stored_still_reaches(self):
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        self.assertEqual(self.state.view(self.ws)["grants"][0]["reach_note"], "")
        self.assertTrue(self.session(gid).zone_allowed("Work"))


class OnlyWalledNow(Case):
    """N2: a zone that was walled and is open now does not count as the connection's walled zone."""

    def open_work(self):
        path = self.ws / "System" / "context.md"
        path.write_text(path.read_text().replace("| Work | Things of work | yes |", "| Work | Things of work | no |"))

    def test_a_zone_that_is_open_now_does_not_block_a_second_walled_zone(self):
        gid = self.grant()
        self.assertTrue(self.zone(gid, "Work", read=True)["ok"])
        self.open_work()
        self.assertTrue(self.zone(gid, "Vault", read=True)["ok"])
        s = self.session(gid)
        self.assertTrue(s.zone_allowed("Vault") and s.zone_allowed("Work"))        # Work is open for everyone now
        self.assertEqual(self.state.view(self.ws)["grants"][0]["reach_note"], "")

    def test_the_owner_can_clear_an_entry_for_a_zone_that_is_open_now(self):
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        self.open_work()
        self.assertFalse(self.zone(gid, "Work", read=True)["ok"])                  # it is open: nothing to turn on
        self.assertTrue(self.zone(gid, "Work", read=False, ack=False)["ok"])       # but the old entry can be cleared
        self.assertEqual(self.store.get_grant(gid)["zones"], {})

    def test_two_held_zones_with_one_open_now_still_reach_the_walled_one(self):
        gid = self.grant()
        with self.store.txn() as db:
            db["grants"][gid]["zones"] = {z: {"read": "2026-11-26", "write": "", "marker": self.ctx.zone_marker(self.ws, z)} for z in ("Work", "Vault")}
        self.open_work()
        self.assertTrue(self.session(gid).zone_allowed("Vault"))
        self.assertEqual(self.state.view(self.ws)["grants"][0]["reach_note"], "")


class ReadingDropsAbsentZones(Case):
    def remove_work(self):
        path = self.ws / "System" / "context.md"
        path.write_text(path.read_text().replace("| Work | Things of work | yes |\n", ""))

    def test_opening_settings_drops_the_entry_of_a_zone_that_left(self):
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        self.remove_work()
        self.state.view(self.ws)
        self.assertEqual(self.store.get_grant(gid)["zones"], {})

    def test_reach_rows_drops_it_too(self):
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        self.remove_work()
        self.ctx.reach_rows(self.ws, gid)
        self.assertEqual(self.store.get_grant(gid)["zones"], {})

    def test_an_unreadable_zone_list_drops_nothing(self):
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        (self.ws / "System" / "tools").unlink()
        self.state.view(self.ws)
        self.ctx.reach_rows(self.ws, gid)
        self.assertIn("Work", self.store.get_grant(gid)["zones"])


class Scopes(Case):
    def test_a_session_is_never_wider_than_its_token(self):
        gid = self.grant()                                    # the grant may read and write
        self.assertEqual(set(self.ctx.session_for(self.ws, gid, ["read"]).classes), {"read"})
        s = self.ctx.session_for(self.ws, gid, ["read"])
        self.assertFalse(s.zone_allowed("Home", write=True))
        self.assertEqual(set(self.ctx.session_for(self.ws, gid).classes), {"read", "write"})


class ZoneThatLeaves(Case):
    def test_an_entry_for_a_zone_that_left_is_dropped_so_a_new_zone_of_that_name_starts_empty(self):
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        path = self.ws / "System" / "context.md"
        text = path.read_text()
        path.write_text(text.replace("| Work | Things of work | yes |\n", ""))
        self.session(gid)                                     # a read of the grant drops the entry
        self.assertEqual(self.store.get_grant(gid)["zones"], {})
        path.write_text(text)                                 # a later zone with the same name
        self.assertFalse(self.session(gid).zone_allowed("Work"))

    def test_a_zone_function_that_cannot_load_drops_nothing(self):
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        (self.ws / "System" / "tools").unlink()
        self.session(gid)
        self.assertIn("Work", self.store.get_grant(gid)["zones"])


class ZoneMadeAgain(Case):
    """W4: the grant keeps a marker of the zone folder, and every read of the reach compares it."""

    def remake(self, zone="Work"):
        import os
        import shutil
        folder = self.ws / "Zones" / zone
        away = folder.with_name(zone + "-away")
        os.rename(str(folder), str(away))
        shutil.copytree(str(away), str(folder))
        shutil.rmtree(str(away))

    def test_a_zone_removed_and_made_again_starts_with_nothing(self):
        gid = self.grant()
        self.assertTrue(self.zone(gid, "Work", read=True, write=True)["ok"])
        self.assertTrue(self.session(gid).zone_allowed("Work", write=True))
        self.remake()
        s = self.session(gid)
        self.assertFalse(s.zone_allowed("Work") or s.zone_allowed("Work", write=True))
        self.assertTrue(self.zone(gid, "Work", read=True)["ok"])                       # the owner turns it on again, with the notice
        self.assertTrue(self.session(gid).zone_allowed("Work"))
        self.assertFalse(self.session(gid).zone_allowed("Work", write=True))

    def test_an_edit_inside_the_zone_keeps_the_grant(self):
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        (self.ws / "Zones" / "Work" / "Note.md").write_text("a note\n")
        self.assertTrue(self.session(gid).zone_allowed("Work"))

    def test_an_entry_saved_without_a_marker_is_refused_until_the_zone_is_turned_on_again(self):
        gid = self.grant()
        with self.store.txn() as db:
            db["grants"][gid]["zones"] = {"Work": {"read": "2026-11-20", "write": ""}}
        self.assertFalse(self.session(gid).zone_allowed("Work"))
        self.assertTrue(self.zone(gid, "Work", read=True)["ok"])
        self.assertTrue(self.session(gid).zone_allowed("Work"))

    def test_an_unreadable_marker_refuses_the_zone_and_the_entry_stays(self):
        import unittest.mock
        gid = self.grant()
        self.zone(gid, "Work", read=True)
        with unittest.mock.patch.object(self.ctx, "zone_marker", return_value=""):
            self.assertFalse(self.session(gid).zone_allowed("Work"))
        self.assertTrue(self.session(gid).zone_allowed("Work"))

    def test_settings_says_an_old_or_remade_zone_stays_off_until_turned_on_again(self):
        text = (EXTRA.parent / "status" / "settings_remote.py").read_text()
        self.assertIn("stays off until you turn it on here again", text)
        self.assertIn("Garrick 0.82.0 or earlier has no marker", (EXTRA.parent.parent / "docs" / "extras" / "remote-access.md").read_text())

    def test_the_docs_say_what_the_sign_in_number_proves_and_what_it_does_not(self):
        text = (EXTRA.parent.parent / "docs" / "extras" / "remote-access.md").read_text()
        self.assertIn("shows which row in Settings belongs to which sign-in page", text)
        self.assertIn("does not show who opened that page", text)
        self.assertNotIn("keeps a stranger's link", text)                      # the number never kept a stranger's link from your code
        self.assertIn("Pick the sign-in you started", text)


    def test_the_docs_give_each_sign_in_its_own_tries_and_the_ceiling_the_limits_file_holds(self):
        text = (EXTRA.parent.parent / "docs" / "extras" / "remote-access.md").read_text()
        limits = mod("limits")
        self.assertEqual((5, 30, 900, 900), (limits.CONSENT_TRIES_PER_REQUEST, limits.CONSENT_FLOOD_CEILING,
                                             limits.CONSENT_FLOOD_WINDOW, limits.CONSENT_FLOOD_LOCK))
        self.assertIn("Each sign-in request has its own five tries", text)
        self.assertIn("30 wrong codes in 15 minutes", text)
        self.assertIn("*Show a code* still works under it", text)
        self.assertIn("What a flood can still do", text)
        self.assertIn("Behind a relay all callers count as one, so a flood of 30 calls to the sign-in page in 10 minutes closes it for everyone", text)
        self.assertNotIn("its lock is for everyone", text)

    def test_the_docs_say_how_a_stopped_write_is_settled_from_the_zones_own_record(self):
        text = (EXTRA.parent.parent / "docs" / "extras" / "remote-access.md").read_text()
        self.assertIn("next status call reads the zone's history and says once whether the change was saved, was not saved, or cannot be told", text)
        self.assertIn("It never commits a second time", text)
        self.assertIn("The five Todo line changes and a checkpoint are not linked", text)

class Handles(Case):
    def setUp(self):
        super().setUp()
        self.gid = self.grant()
        self.s = self.session(self.gid)
        self.now = [1_000_000.0]
        self.ctx._clock = lambda: self.now[0]
        self.addCleanup(lambda: setattr(self.ctx, "_clock", __import__("time").time))

    def refused(self, handle, session=None):
        with self.assertRaises(self.ctx.HandleRefused) as caught:
            (session or self.s).check_handle(handle)
        self.assertIn("new chat", str(caught.exception).lower())

    def test_a_handle_this_grant_made_passes(self):
        self.s.check_handle(self.s.new_handle())
        self.s.check_handle(self.session(self.gid).new_handle())               # a new Session of the same grant and reach

    def test_a_made_up_handle_is_refused(self):
        for fake in ("", "h1", "h1.abc.def", "x" * 80, None, 7, "h1." + "A" * 60 + "." + "0" * 32):
            self.refused(fake)

    def test_a_tampered_handle_is_refused(self):
        h = self.s.new_handle()
        tag, body, sig = h.split(".")
        self.refused("%s.%s.%s" % (tag, body, "0" * 32))
        self.refused("%s.%sA.%s" % (tag, body, sig))

    def test_an_expired_handle_is_refused(self):
        h = self.s.new_handle()
        self.now[0] += 12 * 3600 + 1
        self.refused(h)

    def test_a_handle_stops_working_when_the_owner_changes_the_reach_and_works_again_when_it_returns(self):
        h = self.s.new_handle()
        self.zone(self.gid, "Work", read=True)
        self.refused(h, self.session(self.gid))
        self.zone(self.gid, "Work", read=False, ack=False)
        self.session(self.gid).check_handle(h)

    def test_another_grants_handle_is_refused(self):
        other = self.session(self.grant(name="Tablet"))
        self.refused(self.s.new_handle(), other)

    def test_a_handle_is_not_a_secret_and_carries_none(self):
        h = self.s.new_handle()
        self.assertNotIn(self.state.home().name, h)
        self.assertRegex(h, r"^h1\.[A-Za-z0-9_-]+\.[0-9a-f]{32}$")

    def test_the_key_behind_a_handle_is_private_and_stays_the_same(self):
        k = self.store.handle_key()
        self.assertEqual(len(k), 32)
        self.assertEqual(k, self.store.handle_key())
        self.assertEqual(oct(self.state.mode_of(self.state.home() / "handle.key")), "0o600")

    def test_the_machine_code_and_the_spoken_words(self):
        self.assertEqual(self.ctx.NEW_CONTEXT_REQUIRED, "new_context_required")
        self.assertIn("reach", self.ctx.NEW_CONTEXT_SAY)
        self.assertNotIn("context", self.ctx.NEW_CONTEXT_SAY.lower())


class NoToolChangesTheReach(unittest.TestCase):
    def test_nothing_the_service_serves_can_reach_the_actions_that_change_a_grant(self):
        for name in ("service.py", "provider.py", "consent.py"):
            text = (EXTRA / name).read_text()
            self.assertNotIn("settings_actions", text, name)
            self.assertNotIn("set_zone", text, name)
        tools = EXTRA / "tools"
        if tools.is_dir():
            for path in tools.rglob("*.py"):
                text = path.read_text()
                for bad in ("settings_actions", "set_zone", "store.revoke", "set_status", "make_pairing_code", "create_grant"):
                    self.assertNotIn(bad, text, path.name)

    def test_only_settings_actions_writes_a_reach(self):
        writers = [p.name for p in EXTRA.glob("*.py") if re.search(r"\bset_zone\(", p.read_text()) and p.name != "store.py"]
        self.assertEqual(writers, ["settings_actions.py"])

    def test_the_service_offers_no_tool_of_its_own(self):
        text = (EXTRA / "service.py").read_text()
        self.assertNotIn("@server.tool", text)
        self.assertNotIn(".tool(", text)


if __name__ == "__main__":
    unittest.main()
