"""A walled zone removed and made again keeps nothing of its old grant (#708, W4).

Run with the extra's runtime:  python -m unittest test_zone_marker       (from extras/remote/tests)

The grant stores a marker of the zone's folder when the owner turns the zone on. Every read of the reach compares it, so a new folder
of the same name starts with nothing, an unreadable marker refuses the zone, and a grant saved before markers reaches no walled zone
until the owner turns it on again. The reads and writes here run on the Session that `context.session_for` builds, as the service builds
one for each call.
"""

from __future__ import annotations

import os
import shutil
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.dont_write_bytecode = True

import tools_support as support  # noqa: E402
from remote_fixture import EXTRA, mod  # noqa: E402
from test_tools_writes import WritesCase  # noqa: E402
from tools import reads, writes  # noqa: E402


class Marked(WritesCase):
    def setUp(self):
        super().setUp()
        self.ctx, self.store, self.act = mod("context"), mod("store"), mod("settings_actions")
        remote = self.root / "System" / "remote"
        if not remote.exists():
            os.symlink(str(EXTRA), str(remote))
        self.gid = self.store.create_grant("client-phone", "Phone", ["read", "write"])
        self.turn_on_work()

    def turn_on_work(self, read=True, write=True):
        return self.act.run(self.root, {"action": "zone", "grant": self.gid, "zone": "Work", "read": read, "write": write, "acknowledged": True})

    def live(self):
        return self.ctx.session_for(self.root, self.gid)

    def remade(self):
        """Work removed and made again under the same name, with the same files: the old folder is still there while the new one is made,
        so the two never share an inode."""
        work = self.root / "Zones" / "Work"
        away = work.with_name("Work-away")
        os.rename(str(work), str(away))
        shutil.copytree(str(away), str(work))
        shutil.rmtree(str(away))

    def test_the_zone_untouched_keeps_working_after_an_ordinary_edit_inside_it(self):
        self.assertTrue(self.live().zone_allowed("Work") and self.live().zone_allowed("Work", write=True))
        (self.work / "Acme Review" / "Notes.md").write_text("# Notes\n\nAn edit.\n")
        (self.work / "Todo.md").write_text((self.work / "Todo.md").read_text() + "- [ ] One more line\n")
        s = self.live()
        self.assertTrue(s.zone_allowed("Work") and s.zone_allowed("Work", write=True))
        self.assertIn("Acme Review", reads.Reads(s).places()["text"])

    def test_the_grant_stores_a_marker_with_the_day_when_the_zone_is_turned_on(self):
        entry = self.store.get_grant(self.gid)["zones"]["Work"]
        self.assertTrue(entry["marker"])
        self.assertEqual(entry["marker"], self.ctx.zone_marker(self.root, "Work"))
        self.assertTrue(entry["read"] and entry["write"])

    def test_a_zone_removed_and_made_again_reaches_nothing_through_session_for(self):
        self.remade()
        s = self.live()
        self.assertFalse(s.zone_allowed("Work"))
        self.assertFalse(s.zone_allowed("Work", write=True))
        self.assertNotIn("Work", s.readable | s.writable)

    def test_a_zone_removed_and_made_again_reaches_nothing_through_the_read_tools(self):
        before = reads.Reads(self.live())
        found = before.search("pallet quote")["text"]
        self.assertIn("Acme kick-off", found)
        self.remade()
        r = reads.Reads(self.live())
        self.assertNotIn("Acme Review", r.places()["text"])
        self.assertNotIn("Acme kick-off", r.search("pallet quote")["text"])
        ids = support_ids(found)
        self.assertTrue(ids)
        self.assertNotIn("pallet quote holds at forty a unit", r.read(ids[0])["text"])

    def test_a_zone_removed_and_made_again_cannot_be_prepared_for_a_write(self):
        self.remade()
        made = writes.Writes(self.live()).prepare("todo-add", "Work", text="Ask Jo about the pallets")
        self.assertNotEqual("prepared", made.get("state"), made)
        self.assertNotIn("Ask Jo about the pallets", (self.work / "Todo.md").read_text())

    def test_a_write_prepared_before_the_zone_was_made_again_is_refused_at_execute(self):
        made = writes.Writes(self.live()).prepare("todo-add", "Work", text="Ask Jo about the pallets")
        self.assertEqual("prepared", made.get("state"), made)
        self.remade()
        out = writes.Writes(self.live()).execute(made["operation_id"])
        self.assertNotEqual("saved", out.get("state"), out)
        self.assertNotIn("Ask Jo about the pallets", (self.work / "Todo.md").read_text())

    def test_a_handle_and_a_prepared_write_from_before_do_not_come_back_when_the_zone_is_turned_on_again(self):
        s = self.live()
        handle = s.new_handle()
        made = writes.Writes(s).prepare("todo-add", "Work", text="Ask Jo about the pallets")
        self.assertEqual("prepared", made.get("state"), made)
        old_reach = s.reach_id()
        self.remade()
        self.assertTrue(self.turn_on_work()["ok"])                                           # the owner turns the new zone on
        fresh = self.live()
        self.assertTrue(fresh.zone_allowed("Work", write=True))
        self.assertNotEqual(old_reach, fresh.reach_id())
        with self.assertRaises(self.ctx.HandleRefused):
            fresh.check_handle(handle)
        out = writes.Writes(fresh).execute(made["operation_id"])
        self.assertNotEqual("saved", out.get("state"), out)
        self.assertNotEqual("running", out.get("state"), out)
        self.assertNotIn("Ask Jo about the pallets", (self.work / "Todo.md").read_text())
        fresh.check_handle(fresh.new_handle())                                                # a new handle works

    def test_the_same_line_prepared_again_in_a_new_chat_runs_and_the_old_refusal_names_the_change(self):
        s = self.live()
        made = writes.Writes(s).prepare("todo-add", "Work", text="Ask Jo about the pallets")
        self.remade()
        self.assertTrue(self.turn_on_work()["ok"])
        fresh = self.live()
        old = writes.Writes(fresh).execute(made["operation_id"])
        self.assertEqual("new_context_required", old.get("error"), old)
        self.assertIn("changed what this connection may reach", old["say"])
        self.assertNotIn("outside what this connection may reach", old["say"])
        again = writes.Writes(fresh).prepare("todo-add", "Work", text="Ask Jo about the pallets")
        self.assertEqual("prepared", again.get("state"), again)
        self.assertNotEqual(made["operation_id"], again["operation_id"])
        out = writes.Writes(fresh).execute(again["operation_id"])
        self.assertNotIn("error", out, out)
        self.assertIn(out.get("state"), ("running", "saved"), out)
        stale = writes.Writes(fresh).execute(made["operation_id"])           # the old prepared write stays refused
        self.assertEqual("new_context_required", stale.get("error"), stale)
        by_id = writes.Writes(fresh).prepare("todo-add", "Work", operation_id=made["operation_id"], text="Ask Jo about the pallets")
        self.assertEqual("changed", by_id.get("error") or by_id.get("state"), by_id)

    def test_the_old_entry_does_not_come_back_when_a_walled_zone_is_turned_on_again(self):
        self.remade()
        self.assertFalse(self.live().zone_allowed("Work"))
        self.assertTrue(self.turn_on_work(read=True, write=False)["ok"])                  # the owner reads the notice again
        s = self.live()
        self.assertTrue(s.zone_allowed("Work"))
        self.assertFalse(s.zone_allowed("Work", write=True))                               # the old write choice did not come back
        row = [z for z in self.ctx.reach_rows(self.root, self.gid) if z["zone"] == "Work"][0]
        self.assertTrue(row["read"] and not row["write"])

    def test_turning_one_choice_off_never_brings_a_stale_entry_back(self):
        self.remade()
        out = self.turn_on_work(read=False, write=True)
        self.assertTrue(out["ok"])                                                         # the owner chose write alone, with the notice
        s = self.live()
        self.assertTrue(s.zone_allowed("Work", write=True))
        self.assertFalse(s.zone_allowed("Work"))                                           # and the old read did not come back

    def test_a_grant_saved_before_markers_reaches_no_walled_zone(self):
        with self.store.txn() as db:
            db["grants"][self.gid]["zones"] = {"Work": {"read": "2026-11-20", "write": "2026-11-20"}}
        s = self.live()
        self.assertFalse(s.zone_allowed("Work") or s.zone_allowed("Work", write=True))
        row = self.state_view()
        work = [z for z in row["reach"] if z["zone"] == "Work"][0]
        self.assertFalse(work["read"] or work["write"])
        self.assertTrue(self.turn_on_work()["ok"])                                         # turned on again in Settings: it works
        self.assertTrue(self.live().zone_allowed("Work", write=True))

    def state_view(self):
        return mod("state").view(self.root)["grants"][0]

    def test_a_marker_that_cannot_be_read_refuses_the_zone(self):
        with unittest.mock.patch.object(self.ctx, "zone_marker", return_value=""):
            s = self.live()
            self.assertFalse(s.zone_allowed("Work"))
            self.assertFalse(s.zone_allowed("Work", write=True))
        self.assertTrue(self.live().zone_allowed("Work"))                                  # nothing was dropped for a failed read

    def test_a_marker_that_cannot_be_read_cannot_turn_a_zone_on(self):
        other = self.store.create_grant("client-two", "Tablet", ["read"])
        with unittest.mock.patch.object(self.ctx, "zone_marker", return_value=""):
            out = self.act.run(self.root, {"action": "zone", "grant": other, "zone": "Work", "read": True, "acknowledged": True})
        self.assertFalse(out["ok"])
        self.assertEqual({}, self.store.get_grant(other)["zones"])

    def test_a_stored_marker_that_is_not_text_refuses_the_zone(self):
        with self.store.txn() as db:
            db["grants"][self.gid]["zones"]["Work"]["marker"] = 12345
        self.assertFalse(self.live().zone_allowed("Work"))

    def test_the_marker_changes_when_the_folder_is_made_again_and_not_when_it_is_edited(self):
        first = self.ctx.zone_marker(self.root, "Work")
        (self.work / "Another.md").write_text("x\n")
        self.assertEqual(first, self.ctx.zone_marker(self.root, "Work"))
        self.remade()
        self.assertNotEqual(first, self.ctx.zone_marker(self.root, "Work"))
        self.assertEqual("", self.ctx.zone_marker(self.root, "Nowhere"))
        self.assertEqual("", self.ctx.zone_marker(self.root, "../System"))

    def test_without_a_birth_time_the_zone_has_no_marker_and_cannot_be_turned_on(self):
        real = os.stat

        def bare(path, *a, **k):
            got = real(path, *a, **k)
            if str(path).endswith("Work"):
                return os.stat_result(tuple(got)[:10])                       # no birth time field
            return got
        with unittest.mock.patch.object(self.ctx.os, "stat", side_effect=bare):
            self.assertEqual("", self.ctx.zone_marker(self.root, "Work"))
            other = self.store.create_grant("client-two", "Tablet", ["read"])
            out = self.act.run(self.root, {"action": "zone", "grant": other, "zone": "Work", "read": True, "acknowledged": True})
            self.assertFalse(out["ok"], out)
            self.assertFalse(self.live().zone_allowed("Work"))               # and one already on is refused: fail closed
        self.assertTrue(self.live().zone_allowed("Work"))

    def test_a_disk_with_no_folder_creation_time_gets_a_true_sentence_and_a_next_step(self):
        real = os.stat
        for case in ("no attribute", "float zero", "ns zero"):
            def stub(path, *a, **k):
                got = real(path, *a, **k)
                if not str(path).endswith("Work"):
                    return got
                if case == "no attribute":
                    return os.stat_result(tuple(got)[:10])
                fields = tuple(got)[:10]
                extra = {"st_birthtime": 0.0} if case == "float zero" else {"st_birthtime_ns": 0}
                return _Bare(fields, extra)
            with unittest.mock.patch.object(self.ctx.os, "stat", side_effect=stub):
                other = self.store.create_grant("client-" + case, "Tablet", ["read"])
                out = self.act.run(self.root, {"action": "zone", "grant": other, "zone": "Work", "read": True, "acknowledged": True})
            self.assertFalse(out["ok"], (case, out))
            say = out["say"]
            self.assertNotIn("could not be read", say, case)
            self.assertIn("keeps no creation time for folders", say, case)
            self.assertIn("made again under the same name", say, case)
            self.assertIn("the Mac's own disk", say, case)

    def test_any_other_empty_marker_keeps_could_not_be_read(self):
        other = self.store.create_grant("client-other", "Tablet", ["read"])
        with unittest.mock.patch.object(self.ctx, "zone_marker", return_value=""):      # a folder that is there, a stat that is fine
            out = self.act.run(self.root, {"action": "zone", "grant": other, "zone": "Work", "read": True, "acknowledged": True})
        self.assertFalse(out["ok"], out)
        self.assertIn("could not be read", out["say"])
        self.assertNotIn("creation time", out["say"])

    def test_a_zone_named_dot_or_dot_dot_has_no_marker(self):
        for name in ("", ".", "..", " ", "Work/..", "Work/.", "./Work"):
            self.assertEqual("", self.ctx.zone_marker(self.root, name), repr(name))
        self.assertTrue(self.ctx.zone_marker(self.root, "Work"))


class _Bare:
    """A stat result with a birth time field of 0, to stand in for a disk that keeps none."""

    def __init__(self, fields, extra):
        real = os.stat_result(fields)
        for name in ("st_mode", "st_ino", "st_dev", "st_nlink", "st_uid", "st_gid", "st_size", "st_atime", "st_mtime", "st_ctime"):
            setattr(self, name, getattr(real, name))
        for name, value in extra.items():
            setattr(self, name, value)


def support_ids(text):
    import re
    return re.findall(r"^\[([0-9a-f]{12}~r\d+-[0-9a-f]+)\]", text, re.M)


if __name__ == "__main__":
    unittest.main()
