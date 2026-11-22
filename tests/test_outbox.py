"""The outbox of a roaming machine's Todo actions (#612): queued on the laptop, applied once on the server, held and
asked about when the line is not as it was. A fake HOME and a fake jobs folder; invented names only.

    python3 -m unittest test_outbox
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
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

import fixtures  # noqa: E402
from fixtures import build_workspace, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STATUS = REPO / "extras" / "status"
sys.path.insert(0, str(STATUS))


def _load(name):
    spec = importlib.util.spec_from_file_location("garrick_" + name, STATUS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pa = _load("page_action")
sys.modules["page_action"] = pa                    # the one outbox.py finds running, so one Refused is caught
import outbox  # noqa: E402
import status  # noqa: E402

tl = pa.todo_lines()
LINE_A = "- [ ] [[Pricing]]: Send the revised terms 📅 2026-10-09"
LINE_B = "- [ ] Acme Corp: Invoice for September"


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True, text=True, check=True).stdout


class OutboxCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.root = base / "Workspace"
        self.jobs = base / "jobs"
        self.home = base / "home"
        self.home.mkdir()
        patch = mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": str(self.jobs), "HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)
        build_workspace(self.root)
        (self.root / "System" / "tools").mkdir(parents=True, exist_ok=True)
        for tool in ("scaffold.py", "garrick_lib.py", "operations.py", "machine.py"):
            shutil.copy2(REPO / "template" / "System" / "tools" / tool, self.root / "System" / "tools" / tool)
        self.work = self.root / "Zones" / "Work"
        self.personal = self.root / "Zones" / "Personal"
        for zone in (self.work, self.personal):
            shutil.rmtree(zone / ".git")
            git(zone, "init", "-q")
            git(zone, "config", "user.name", "Sam Rivera")
            git(zone, "config", "user.email", "sam@example.com")
            git(zone, "config", "maintenance.auto", "false")
            git(zone, "config", "gc.auto", "0")
            hook = zone / ".git" / "hooks" / "pre-commit"
            hook.parent.mkdir(parents=True, exist_ok=True)
            hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\n")
            hook.chmod(0o755)
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n%s\n%s\n\n## Done\n" % (LINE_A, LINE_B))
        write(self.personal / "Todo.md", "# Personal: open actions\n\n## Inbox\n\n- [ ] Renew the passport\n\n## Done\n")
        for zone in (self.work, self.personal):
            git(zone, "add", "-A")
            git(zone, "commit", "-q", "-m", "start")
        self.ops = pa.ops_lib(self.root)

    # helpers

    def role(self, role, **more):
        target = self.home / ".config" / "garrick" / "machine.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(dict(role=role, **more)))

    def key(self, line):
        return tl.key(line)

    def tick(self, line=LINE_A, via="page", zone="Work"):
        return pa.perform(self.root, {"verb": "todo-done", "zone": zone, "file": "Todo.md", "key": self.key(line)}, self.ops, via)

    def commits(self, zone):
        return int(git(zone, "rev-list", "--count", "HEAD").strip())

    def outbox(self, zone=None):
        return sorted(((zone or self.work) / "Inbox" / ".outbox").glob("*.json")) if (zone or self.work).joinpath("Inbox", ".outbox").is_dir() else []

    def todo(self, zone=None):
        return ((zone or self.work) / "Todo.md").read_text()


class Queue(OutboxCase):
    def test_a_tick_from_the_page_on_a_roaming_machine_is_queued_and_changes_nothing(self):
        self.role("roaming", name="laptop", server="mini")
        before, commits = self.todo(), self.commits(self.work)
        out, _, _ = self.tick()
        self.assertTrue(out["ok"], out)
        self.assertIn("waits for the server", out["say"])
        self.assertEqual(before, self.todo())
        self.assertEqual(commits, self.commits(self.work))
        [req] = self.outbox()
        data = json.loads(req.read_text())
        self.assertEqual(req.stem, data["id"])
        self.assertEqual({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A)}, data["request"])
        self.assertEqual("Send the revised terms 📅 2026-10-09", data["line"].replace("[[Pricing]]: ", ""))
        self.assertEqual("laptop", data["machine"])
        self.assertEqual([], list((self.personal / "Inbox").glob(".outbox*")))                # nothing in another zone

    def test_the_four_verbs_are_queued_and_a_batch_is_one_request_a_line(self):
        self.role("roaming", name="laptop")
        pa.perform(self.root, {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "keys": [self.key(LINE_A), self.key(LINE_B)]}, self.ops, "page")
        pa.perform(self.root, {"verb": "todo-undo", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A)}, self.ops, "page")
        pa.perform(self.root, {"verb": "todo-edit", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_B), "text": "Invoice for October"}, self.ops, "page")
        pa.perform(self.root, {"verb": "todo-add", "zone": "Work", "text": "Call the carrier"}, self.ops, "page")
        verbs = sorted(json.loads(p.read_text())["request"]["verb"] for p in self.outbox())
        self.assertEqual(["todo-add", "todo-done", "todo-done", "todo-edit", "todo-undo"], verbs)

    def test_every_other_action_that_writes_waits_until_the_server_can_be_reached(self):
        self.role("roaming", name="laptop")
        for req in ({"verb": "park", "zone": "Work", "project": "Acme Review", "thread": "Pricing"},
                    {"verb": "rename", "zone": "Work", "project": "Acme Review", "to": "Acme"},
                    {"verb": "delete", "zone": "Work", "project": "Acme Review", "confirm": "yes"},
                    {"verb": "todo-date", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A), "date": "2026-10-10"},
                    {"verb": "todo-retire", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A), "reason": "x"}):
            out, _, _ = pa.perform(self.root, req, self.ops, "page")
            self.assertFalse(out["ok"], req["verb"])
            self.assertIn("only receives", out["say"], req["verb"])
        self.assertEqual([], self.outbox())
        self.assertEqual(1, self.commits(self.work))

    def test_a_line_in_a_thread_note_is_not_queued(self):
        self.role("roaming")
        out, _, _ = pa.perform(self.root, {"verb": "todo-done", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md",
                                           "key": self.key(LINE_A)}, self.ops, "page")
        self.assertFalse(out["ok"])
        self.assertEqual([], self.outbox())

    def test_a_request_with_a_field_the_verb_does_not_declare_is_refused_and_writes_nothing(self):
        self.role("roaming")
        out, _, _ = pa.perform(self.root, {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A),
                                           "path": "../Personal/Todo.md"}, self.ops, "page")
        self.assertFalse(out["ok"])
        self.assertEqual([], self.outbox())

    def test_solo_and_server_tick_as_before_and_make_no_outbox(self):
        write(self.work / "Todo.md", self.todo().replace(LINE_B, LINE_B + "\n- [ ] Third action"))
        git(self.work, "commit", "-q", "-am", "third")
        for role, line in ((None, LINE_A), ("solo", LINE_B), ("server", "- [ ] Third action")):
            if role:
                self.role(role, name="mini")
            out, _, _ = self.tick(line)
            self.assertTrue(out["ok"], (role, out))
            self.assertNotIn("waits for the server", out["say"])
        self.assertEqual(5, self.commits(self.work))
        self.assertFalse((self.work / "Inbox" / ".outbox").exists())

    def test_via_outbox_carries_the_four_verbs_and_no_other(self):
        for verb in ("park", "todo-date", "todo-retire", "delete", "settings"):
            out, _, _ = pa.perform(self.root, {"verb": verb, "zone": "Work"}, self.ops, "outbox")
            self.assertFalse(out["ok"], verb)
            self.assertIn("only a tick", out["say"], verb)
        self.assertEqual(1, self.commits(self.work))
        self.assertIn("outbox", self.ops.CALLERS)
        self.assertEqual(("todo-done", "todo-undo", "todo-edit", "todo-add"), self.ops.OUTBOX_VERBS)


class HandTicks(OutboxCase):
    def test_a_tick_typed_into_todo_md_becomes_one_request(self):
        self.role("roaming", name="laptop")
        self.assertEqual(0, outbox.hand_ticks(self.root))                       # the first sight keeps the delivered file
        (self.work / "Todo.md").write_text(self.todo().replace(LINE_B, LINE_B.replace("- [ ]", "- [x]") + " ✅ 2026-10-05"))
        self.assertEqual(1, outbox.hand_ticks(self.root))
        self.assertEqual(0, outbox.hand_ticks(self.root))                       # not made twice
        [req] = self.outbox()
        data = json.loads(req.read_text())
        self.assertEqual({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_B)}, data["request"])

    def test_the_server_catching_up_is_the_new_delivery(self):
        self.role("roaming", name="laptop")
        outbox.hand_ticks(self.root)
        ticked = self.todo().replace(LINE_B, LINE_B.replace("- [ ]", "- [x]") + " ✅ 2026-10-05")
        (self.work / "Todo.md").write_text(ticked)
        outbox.hand_ticks(self.root)
        self.outbox()[0].unlink()                                               # the server applied it, and the sync took the file away
        (self.work / "Todo.md").write_text(ticked.replace("2026-10-05", "2026-10-06"))      # and delivered its own version
        self.assertEqual(0, outbox.hand_ticks(self.root))
        self.assertEqual([], self.outbox())
        self.assertEqual(0, outbox.hand_ticks(self.root))

    def test_a_server_and_a_solo_machine_make_none(self):
        for role in ("server", None):
            if role:
                self.role(role)
            outbox.hand_ticks(self.root)
            (self.work / "Todo.md").write_text(self.todo().replace(LINE_B, LINE_B.replace("- [ ]", "- [x]")))
            self.assertEqual(0, outbox.hand_ticks(self.root))
        self.assertEqual([], self.outbox())

    def test_the_kept_copy_is_outside_the_workspace(self):
        self.role("roaming")
        outbox.hand_ticks(self.root)
        self.assertTrue((self.jobs / "outbox-base" / "Work.md").is_file())
        self.assertFalse(list(self.root.rglob("outbox-base")))


    # C5, C6: what a hand tick does when it is taken back, and what counts as a new tick

    def ticked(self, line, date="2026-10-05"):
        return line.replace("- [ ]", "- [x]") + " ✅ " + date

    def test_a_hand_tick_taken_back_before_the_server_applies_it_ends_open(self):
        self.role("roaming", name="laptop")
        outbox.hand_ticks(self.root)
        start = self.todo()
        (self.work / "Todo.md").write_text(start.replace(LINE_B, self.ticked(LINE_B)))
        now = dt.datetime(2026, 10, 5, 10, 0, 0)
        self.assertEqual(1, outbox.hand_ticks(self.root, now))
        (self.work / "Todo.md").write_text(start)                                # the user unticks it again
        self.assertEqual(1, outbox.hand_ticks(self.root, now))                   # an untick, after the tick
        self.assertEqual(0, outbox.hand_ticks(self.root, now))                   # and only one
        reqs = [json.loads(p.read_text()) for p in self.outbox()]
        self.assertEqual(["todo-done", "todo-undo"], [r["request"]["verb"] for r in sorted(reqs, key=lambda r: r["made"])])
        self.assertTrue(all(r["request"]["key"] == self.key(LINE_B) for r in reqs))
        self.role("server", name="mini")
        self.assertEqual({"applied": 2, "held": 0, "skipped": 0}, outbox.replay(self.root))
        self.assertIn(LINE_B, self.todo())
        self.assertNotIn("- [x] Acme Corp", self.todo())

    def test_the_untick_is_ordered_after_the_tick_even_when_the_clock_is_behind(self):
        self.role("roaming", name="laptop")
        outbox.hand_ticks(self.root)
        start = self.todo()
        (self.work / "Todo.md").write_text(start.replace(LINE_B, self.ticked(LINE_B)))
        outbox.hand_ticks(self.root, dt.datetime(2026, 10, 5, 10, 0, 30))
        (self.work / "Todo.md").write_text(start)
        outbox.hand_ticks(self.root, dt.datetime(2026, 10, 5, 10, 0, 0))
        made = sorted(json.loads(p.read_text())["made"] for p in self.outbox())
        self.assertLess(made[0], made[1])

    def test_a_tick_again_after_the_untick_is_a_new_request(self):
        self.role("roaming", name="laptop")
        outbox.hand_ticks(self.root)
        start = self.todo()
        now = dt.datetime(2026, 10, 5, 10, 0, 0)
        for text in (start.replace(LINE_B, self.ticked(LINE_B)), start, start.replace(LINE_B, self.ticked(LINE_B))):
            (self.work / "Todo.md").write_text(text)
            outbox.hand_ticks(self.root, now)
        verbs = [json.loads(p.read_text()) for p in self.outbox()]
        self.assertEqual(["todo-done", "todo-undo", "todo-done"], [r["request"]["verb"] for r in sorted(verbs, key=lambda r: r["made"])])
        self.role("server", name="mini")
        outbox.replay(self.root)
        self.assertIn("- [x] Acme Corp: Invoice for September", self.todo())

    def test_a_line_with_trailing_space_in_the_base_is_still_a_tick(self):
        self.role("roaming", name="laptop")
        write(self.work / "Todo.md", self.todo().replace(LINE_B, LINE_B + "  "))        # the delivered copy has it
        outbox.hand_ticks(self.root)
        (self.work / "Todo.md").write_text(self.todo().replace(LINE_B + "  ", self.ticked(LINE_B)))
        self.assertEqual(1, outbox.hand_ticks(self.root))
        (self.work / "Todo.md").write_text(self.todo().replace(self.ticked(LINE_B), self.ticked(LINE_B) + "   "))
        self.assertEqual(0, outbox.hand_ticks(self.root))

    def test_a_line_the_server_added_after_the_snapshot_and_ticked_here_is_a_tick(self):
        self.role("roaming", name="laptop")
        outbox.hand_ticks(self.root)
        added = "- [ ] Birch & Co: Send the contract"
        (self.work / "Todo.md").write_text(self.todo().replace(LINE_B, LINE_B + "\n" + self.ticked(added)))
        self.assertEqual(1, outbox.hand_ticks(self.root))
        [req] = self.outbox()
        self.assertEqual(self.key(added), json.loads(req.read_text())["request"]["key"])

    def test_a_line_ticked_in_the_delivered_copy_is_not_a_tick(self):
        self.role("roaming", name="laptop")
        done = self.todo().replace(LINE_B, self.ticked(LINE_B))
        write(self.work / "Todo.md", done)
        outbox.hand_ticks(self.root)
        (self.work / "Todo.md").write_text(done.replace("2026-10-05", "2026-10-06"))     # the server's own re-delivery
        self.assertEqual(0, outbox.hand_ticks(self.root))


class Replay(OutboxCase):
    def queue(self, line=LINE_A, verb="todo-done", **more):
        self.role("roaming", name="laptop")
        req = dict({"verb": verb, "zone": "Work", "file": "Todo.md", "key": self.key(line)}, **more)
        out, _, _ = pa.perform(self.root, req, self.ops, "page")
        self.assertTrue(out["ok"], out)
        self.role("server", name="mini")
        return self.outbox()[-1]

    def test_the_server_applies_a_request_once_with_a_commit_and_takes_the_file_out(self):
        req = self.queue()
        done = outbox.replay(self.root)
        self.assertEqual({"applied": 1, "held": 0, "skipped": 0}, done)
        self.assertIn("- [x] [[Pricing]]: Send the revised terms 📅 2026-10-09 ✅", self.todo())
        self.assertEqual(2, self.commits(self.work))
        self.assertFalse(req.exists())
        self.assertIn(req.stem, outbox.applied_ids())
        log = (self.jobs / "operations.jsonl").read_text()
        self.assertIn('"via":"outbox"', log)

    def test_a_replayed_id_is_skipped(self):
        req = self.queue()
        body = req.read_text()
        outbox.replay(self.root)
        req.write_text(body)                                                    # the sync brings the same file back
        self.assertEqual({"applied": 0, "held": 0, "skipped": 1}, outbox.replay(self.root))
        self.assertEqual(2, self.commits(self.work))
        self.assertFalse(req.exists())

    def test_the_wall_check_still_runs_on_the_server_commit(self):
        req = self.queue()
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\necho refused >&2\nexit 1\n")
        outbox.replay(self.root)
        self.assertEqual(1, self.commits(self.work))
        self.assertIn(LINE_A, self.todo())                                      # nothing changed
        self.assertTrue(req.with_name(req.stem + ".held.json").is_file())

    def test_a_tick_on_a_line_reworded_on_the_server_meanwhile_is_held_and_asked_about(self):
        req = self.queue()
        self.role("server", name="mini")
        out, _, _ = pa.perform(self.root, {"verb": "todo-edit", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A),
                                           "text": "Send the revised terms to Dana"}, self.ops, "page")
        self.assertTrue(out["ok"], out)
        before, commits = self.todo(), self.commits(self.work)
        self.assertEqual({"applied": 0, "held": 1, "skipped": 0}, outbox.replay(self.root))
        self.assertEqual(before, self.todo())
        self.assertEqual(commits, self.commits(self.work))
        self.assertFalse(req.exists())
        [held] = outbox.held_requests(self.root, "Work")
        self.assertEqual(req.stem, held["id"])
        self.assertIn("Send the revised terms to Dana", " ".join(held["now"]))
        self.assertEqual({}, {k: v for k, v in outbox.applied_ids().items() if k == req.stem})
        self.assertEqual({"applied": 0, "held": 0, "skipped": 0}, outbox.replay(self.root))      # held stays held

    def test_drop_it_removes_a_held_request_and_changes_nothing_else(self):
        req = self.queue()
        pa.perform(self.root, {"verb": "todo-edit", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A), "text": "Other words"},
                   self.ops, "page")
        outbox.replay(self.root)
        before = self.todo()
        out, _, _ = pa.perform(self.root, {"verb": "outbox-drop", "zone": "Work", "id": req.stem}, self.ops, "page")
        self.assertTrue(out["ok"], out)
        self.assertEqual([], outbox.held_requests(self.root, "Work"))
        self.assertEqual(before, self.todo())
        out, _, _ = pa.perform(self.root, {"verb": "outbox-drop", "zone": "Work", "id": req.stem}, self.ops, "page")
        self.assertFalse(out["ok"])

    def test_drop_is_only_the_pages_button_and_only_for_a_held_request(self):
        req = self.queue()
        out, _, _ = pa.perform(self.root, {"verb": "outbox-drop", "zone": "Work", "id": req.stem}, self.ops, "session")
        self.assertFalse(out["ok"])
        out, _, _ = pa.perform(self.root, {"verb": "outbox-drop", "zone": "Work", "id": req.stem}, self.ops, "page")
        self.assertFalse(out["ok"])                                             # it waits to be applied: not held
        self.assertTrue(req.exists())

    def hold(self):
        """One held request in Work's outbox, as the server leaves it; the id."""
        req = self.queue()
        pa.perform(self.root, {"verb": "todo-edit", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A), "text": "Other words"},
                   self.ops, "page")
        outbox.replay(self.root)
        return req.stem

    def drop(self, rid, via="page"):
        return pa.perform(self.root, {"verb": "outbox-drop", "zone": "Work", "id": rid}, self.ops, via)[0]

    def test_drop_it_works_on_a_roaming_machine_and_the_page_shows_it_gone(self):
        rid = self.hold()
        self.role("roaming", name="laptop", server="mini")
        self.assertEqual(1, len(outbox.held_requests(self.root, "Work")))
        before, commits = self.todo(), self.commits(self.work)
        out = self.drop(rid)
        self.assertTrue(out["ok"], out)
        self.assertEqual("Dropped. Nothing was changed in Work.", out["say"])
        self.assertEqual([], outbox.held_requests(self.root, "Work"))
        self.assertEqual([], self.outbox())
        self.assertEqual((before, commits), (self.todo(), self.commits(self.work)))      # no line, no commit
        link = status.Links(self.root)
        lists = status.todo_list(self.root, link, dt.date(2026, 10, 5))
        self.assertNotIn("held", [z for z in lists if z["zone"] == "Work"][0])
        self.assertNotIn('data-outbox="drop"', status.todo_list_card(lists, dt.date(2026, 10, 5), True, {}, link, {}))

    def test_on_a_roaming_machine_it_removes_only_a_held_file_and_only_for_the_page(self):
        rid = self.hold()
        self.role("roaming", name="laptop", server="mini")
        self.assertFalse(self.drop(rid, via="session")["ok"])
        self.assertTrue((self.work / "Inbox" / ".outbox" / (rid + ".held.json")).is_file())
        self.assertFalse(self.drop("0" * 16)["ok"])                                       # no such request
        self.assertFalse(self.drop("../../Todo")["ok"])                                   # not an id
        pending = self.queue()
        self.role("roaming", name="laptop", server="mini")
        self.assertFalse(self.drop(pending.stem)["ok"])                                   # it waits to be applied: not held
        self.assertTrue(pending.exists())

    def test_roaming_still_refuses_every_other_write(self):
        self.role("roaming", name="laptop", server="mini")
        out = pa.perform(self.root, {"verb": "park", "zone": "Work", "project": "Acme Review", "thread": "Pricing"}, self.ops, "page")[0]
        self.assertFalse(out["ok"])
        self.assertIn("only receives", out["say"])

    def test_drop_it_on_a_server_and_on_one_computer(self):
        rid = self.hold()                                                       # the server's own page
        self.assertTrue(self.drop(rid)["ok"])
        self.assertEqual([], outbox.held_requests(self.root, "Work"))
        self.role("solo")                                                       # one computer: nothing is ever held, nothing to drop
        self.assertFalse(self.drop(rid)["ok"])
        self.assertEqual("no held request has that id in Work", self.drop(rid)["say"])

    def envelope(self, request, folder=None, **more):
        folder = folder or self.work
        rid = "a1b2c3d4e5f60718"
        env = dict({"id": rid, "made": "2026-10-05T10:00:00", "machine": "laptop", "line": "x", "request": request}, **more)
        path = folder / "Inbox" / ".outbox" / (rid + ".json")
        write(path, json.dumps(env))
        return path

    def test_a_fifth_verb_in_a_request_file_is_held_and_writes_nothing(self):
        self.role("server")
        for verb in ("park", "todo-date", "todo-retire", "delete", "run"):
            path = self.envelope({"verb": verb, "zone": "Work", "project": "Acme Review", "thread": "Pricing", "file": "Todo.md",
                                  "key": self.key(LINE_A), "date": "2026-10-10", "reason": "x", "confirm": "y", "job": "x"})
            self.assertEqual({"applied": 0, "held": 1, "skipped": 0}, outbox.replay(self.root), verb)
            self.assertFalse(path.exists())
            path.with_name(path.stem + ".held.json").unlink()
        self.assertEqual(1, self.commits(self.work))
        self.assertEqual(LINE_A + "\n" + LINE_B, self.todo().split("## Inbox\n\n")[1].split("\n\n## Done")[0])

    def test_an_undeclared_field_is_held(self):
        self.role("server")
        self.envelope({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A), "path": "../x"})
        self.assertEqual(1, outbox.replay(self.root)["held"])
        self.assertIn(LINE_A, self.todo())
        [held] = outbox.held_requests(self.root, "Work")
        self.assertIn("path", held["why"])

    def test_another_zones_file_is_refused_and_writes_nothing_in_either_zone(self):
        self.role("server")
        before = self.todo(self.personal)
        self.envelope({"verb": "todo-done", "zone": "Personal", "file": "Todo.md", "key": self.key("- [ ] Renew the passport")})
        self.assertEqual(1, outbox.replay(self.root)["held"])                   # a Work outbox, a request for Personal
        self.assertEqual(before, self.todo(self.personal))
        self.assertEqual(1, self.commits(self.personal))
        self.envelope({"verb": "todo-done", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md", "key": self.key(LINE_A)},
                      folder=self.work)
        self.assertEqual(1, outbox.replay(self.root)["held"])
        self.assertEqual(1, self.commits(self.work))

    def test_a_file_whose_name_is_not_its_id_and_one_that_does_not_read_are_held(self):
        self.role("server")
        path = self.envelope({"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A)}, id="ffffffffffffffff")
        self.assertEqual(1, outbox.replay(self.root)["held"])
        write(self.work / "Inbox" / ".outbox" / "0123456789abcdef.json", "{not json")
        self.assertEqual(1, outbox.replay(self.root)["held"])
        self.assertEqual(1, self.commits(self.work))

    def test_an_add_is_applied_once(self):
        self.role("roaming", name="laptop")
        pa.perform(self.root, {"verb": "todo-add", "zone": "Work", "text": "Call the carrier"}, self.ops, "page")
        self.role("server")
        self.assertEqual(1, outbox.replay(self.root)["applied"])
        self.assertEqual(1, self.todo().count("Call the carrier"))
        self.assertEqual(0, outbox.replay(self.root)["applied"])

    def made_request(self, rid, made, verb, line=LINE_A, folder=None):
        folder = folder or self.work
        env = {"id": rid, "made": made, "machine": "laptop", "line": line[6:],
               "request": {"verb": verb, "zone": folder.name, "file": "Todo.md", "key": self.key(line)}}
        write(folder / "Inbox" / ".outbox" / (rid + ".json"), json.dumps(env))

    def test_requests_apply_in_the_order_they_were_made_not_the_order_of_their_names(self):
        self.role("server", name="mini")
        self.made_request("b1b1b1b1b1b1b1b1", "2026-10-05T10:00:00", "todo-done")       # the tick, made first, named last
        self.made_request("a1a1a1a1a1a1a1a1", "2026-10-05T10:05:00", "todo-undo")
        self.assertEqual({"applied": 2, "held": 0, "skipped": 0}, outbox.replay(self.root))
        self.assertIn(LINE_A, self.todo())
        self.assertEqual(3, self.commits(self.work))

    def test_the_same_second_falls_back_to_the_id(self):
        self.role("server", name="mini")
        self.made_request("c1c1c1c1c1c1c1c1", "2026-10-05T10:00:00", "todo-done")
        self.made_request("b1b1b1b1b1b1b1b1", "2026-10-05T10:00:00", "todo-undo", line=LINE_B)
        self.assertEqual([("b1b1b1b1b1b1b1b1", False), ("c1c1c1c1c1c1c1c1", False)],
                         [(p.stem, h) for p, _, h in outbox._envelopes(self.work)])

    def test_a_busy_lock_a_timeout_or_a_missing_git_leaves_the_file_for_the_next_run(self):
        self.role("server", name="mini")
        self.made_request("a1a1a1a1a1a1a1a1", "2026-10-05T10:00:00", "todo-done")
        self.made_request("b1b1b1b1b1b1b1b1", "2026-10-05T10:01:00", "todo-undo")
        for say in ("another action in Work is still running; try again in a moment", "git took longer than 30 s and was stopped",
                    "not committed, so nothing changed: git did not run: No such file or directory",
                    "cannot take the lock in /x: Permission denied"):
            calls = []

            def busy(ws, req, ops, via, say=say):
                calls.append(req["verb"])
                return {"ok": False, "say": say}, None, say
            done = outbox.replay(self.root, perform=busy)
            self.assertEqual({"applied": 0, "held": 0, "skipped": 0, "retry": 1}, done, say)
            self.assertEqual(["todo-done"], calls)                              # the untick waits behind the tick
            self.assertEqual(["a1a1a1a1a1a1a1a1.json", "b1b1b1b1b1b1b1b1.json"], [p.name for p in self.outbox()])
        self.assertEqual({"applied": 2, "held": 0, "skipped": 0}, outbox.replay(self.root))      # the next run applies both
        self.assertIn(LINE_A, self.todo())

    def test_a_stale_key_and_a_wall_refusal_are_held_not_retried(self):
        self.role("server", name="mini")
        self.made_request("a1a1a1a1a1a1a1a1", "2026-10-05T10:00:00", "todo-done", line="- [ ] A line nobody has")
        self.assertEqual(1, outbox.replay(self.root)["held"])
        self.made_request("b1b1b1b1b1b1b1b1", "2026-10-05T10:01:00", "todo-done")
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\necho refused >&2\nexit 1\n")
        self.assertEqual(1, outbox.replay(self.root)["held"])

    def test_a_roaming_machine_does_not_apply(self):
        self.queue()
        self.role("roaming")
        out = subprocess.run([sys.executable, str(STATUS / "outbox.py"), "replay", "--workspace", str(self.root)],
                             capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home), GARRICK_JOBS_DIR=str(self.jobs)))
        self.assertEqual(1, out.returncode)
        self.assertEqual(1, self.commits(self.work))


class RunningElsewhere(OutboxCase):
    """#641: a replay that joins a running request keeps its envelope until that request really ends."""

    queue = Replay.queue

    def running(self, workspace=None):
        """The same request, already running under another op: its worker is alive until `run` is closed."""
        req = {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A)}
        run, reply = self.ops.start(self.jobs, dict(req, op="a19f3c80"), workspace=self.root if workspace is None else workspace)
        self.assertIsNone(reply)
        run.running()
        self.addCleanup(run.close, req)
        return run, req

    def test_a_joined_running_request_keeps_the_envelope_with_its_operation(self):
        envelope = self.queue()
        run, req = self.running()
        done = outbox.replay(self.root)
        self.assertEqual({"applied": 0, "held": 0, "skipped": 0, "waiting": 1}, done)
        self.assertTrue(envelope.exists())
        self.assertEqual("a19f3c80", json.loads(envelope.read_text())["op"])      # the envelope id's operation is kept in the envelope
        self.assertNotIn(envelope.stem, outbox.applied_ids())
        self.assertEqual(1, self.commits(self.work))
        self.assertEqual({"applied": 0, "held": 0, "skipped": 0, "waiting": 1}, outbox.replay(self.root))   # still running: still kept

    def test_when_that_request_saves_the_envelope_goes_without_a_second_apply(self):
        envelope = self.queue()
        run, req = self.running()
        outbox.replay(self.root)
        run.finish("saved", req, said="Ticked")
        run.close(req)
        self.assertEqual({"applied": 1, "held": 0, "skipped": 0}, outbox.replay(self.root))
        self.assertFalse(envelope.exists())
        self.assertIn(envelope.stem, outbox.applied_ids())
        self.assertEqual(1, self.commits(self.work))                             # the first run's save is the only one

    def test_when_that_request_fails_the_envelope_is_replayed_later(self):
        envelope = self.queue()
        run, req = self.running()
        outbox.replay(self.root)
        run.finish("crashed", req, why="the action was stopped before it finished.")
        run.close(req)
        self.assertTrue(envelope.exists())                                       # nothing lost while it was waiting
        self.assertEqual({"applied": 1, "held": 0, "skipped": 0}, outbox.replay(self.root))
        self.assertFalse(envelope.exists())
        self.assertIn("- [x] [[Pricing]]: Send the revised terms", self.todo())
        self.assertEqual(2, self.commits(self.work))

    def test_two_replays_at_once_never_lose_the_request(self):
        envelope = self.queue()
        run, req = self.running()
        for _ in range(2):
            outbox.replay(self.root)
        self.assertTrue(envelope.exists())

    def test_a_request_of_another_workspace_is_never_joined_by_a_replay(self):
        envelope = self.queue()
        self.running(workspace="/somewhere/else/Workspace")                      # same zone name, same Todo line
        self.assertEqual({"applied": 1, "held": 0, "skipped": 0}, outbox.replay(self.root))
        self.assertFalse(envelope.exists())
        self.assertIn("- [x] [[Pricing]]: Send the revised terms", self.todo())

    def test_a_row_without_a_workspace_matches_nothing_and_stays_as_it_was(self):
        envelope = self.queue()
        req = {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A)}
        fields = {k: self.ops._norm(k, req.get(k)) for k in sorted(self.ops.OPS["todo-done"].identity)}
        if "keys" in fields:
            del fields["keys"]
            fields["key"] = self.key(LINE_A)
        body = {"verb": "todo-done", "zone": "Work", "fields": fields}          # how 0.75.0 hashed it: no workspace
        old_key = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        row = {"op": "d49f3c80", "key": old_key, "verb": "todo-done", "zone": "Work", "state": "running", "phase": "", "at": time.time(),
               "request": {}, "done": None, "outcome": None, "say": None, "label": "x"}
        self.jobs.mkdir(parents=True, exist_ok=True)
        (self.jobs / "operations.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.assertEqual({"applied": 1, "held": 0, "skipped": 0}, outbox.replay(self.root))
        self.assertFalse(envelope.exists())
        first = (self.jobs / "operations.jsonl").read_text().splitlines()[0]
        self.assertEqual(row, json.loads(first))                                 # its row was never rewritten


class Page(OutboxCase):
    def build(self):
        link = status.Links(self.root)
        lists = status.todo_list(self.root, link, dt.date(2026, 10, 5))
        return lists, status.todo_list_card(lists, dt.date(2026, 10, 5), True, {}, link, {})

    def test_the_header_says_the_role_only_when_it_is_not_solo(self):
        solo = status.bar("<svg/>", "Garrick", "now", "<tabs/>", "<c/>")
        self.assertEqual(solo, status.bar("<svg/>", "Garrick", "now", "<tabs/>", "<c/>", status.machine_said(self.root)))
        self.assertNotIn("role", solo)
        self.role("roaming", name="laptop")
        self.assertEqual("Roaming · laptop", status.machine_said(self.root))
        self.assertIn("Roaming · laptop", status.bar("<svg/>", "Garrick", "now", "<tabs/>", "<c/>", status.machine_said(self.root)))
        self.role("server", name="mini")
        self.assertEqual("Server · mini", status.machine_said(self.root))
        self.role("solo")
        self.assertEqual("", status.machine_said(self.root))

    def test_a_row_ticked_on_a_roaming_machine_waits_for_the_server(self):
        self.role("roaming", name="laptop")
        self.tick()
        lists, card = self.build()
        work = [z for z in lists if z["zone"] == "Work"][0]
        row = [r for _, rows in work["groups"] for r in rows if r["key"] == self.key(LINE_A)][0]
        self.assertEqual("todo-done", row["waits"])
        self.assertIn("ticked, waits for the server", card)
        self.assertEqual(0, card.count("waits for the server") % 2)               # the flat view and the threaded view draw it
        html = status.todo_row(row, dt.date(2026, 10, 5), True)
        self.assertIn('class="trow done', html)

    def test_a_solo_page_has_no_waiting_row_and_no_question(self):
        _, card = self.build()
        self.assertNotIn("waits for the server", card)
        self.assertNotIn("tqi", card.replace(".tqi", ""))

    def test_a_held_request_is_a_question_with_two_answers_on_the_server_page(self):
        self.role("roaming", name="laptop")
        self.tick()
        self.role("server", name="mini")
        pa.perform(self.root, {"verb": "todo-edit", "zone": "Work", "file": "Todo.md", "key": self.key(LINE_A), "text": "New words"}, self.ops, "page")
        outbox.replay(self.root)
        lists, card = self.build()
        self.assertEqual(1, len([z for z in lists if z["zone"] == "Work"][0]["held"]))
        self.assertIn("Show me the line", card)
        self.assertIn("Drop it", card)
        self.assertNotIn("anyway", card.lower())
        self.assertIn('data-outbox="drop"', card)
        self.assertIn("laptop", card)
        self.role("roaming", name="laptop")                                     # the laptop's page asks too (#621): the held file syncs back
        card = self.build()[1]
        self.assertIn('data-outbox="drop"', card)
        self.assertIn("was not changed on the server", card)
        self.assertNotIn("was not changed here", card)
        self.role("solo")
        self.assertNotIn('data-outbox="drop"', self.build()[1])

    def test_a_server_build_applies_the_outbox_and_a_roaming_build_queues_a_hand_tick(self):
        self.role("roaming", name="laptop")
        self.tick()
        self.role("server", name="mini")
        status.settle_outbox(self.root)
        self.assertIn("✅", self.todo())
        self.assertEqual([], self.outbox())
        self.role("roaming", name="laptop")
        status.settle_outbox(self.root)
        (self.work / "Todo.md").write_text(self.todo().replace(LINE_B, LINE_B.replace("- [ ]", "- [x]")))
        status.settle_outbox(self.root)
        self.assertEqual(1, len(self.outbox()))

    def test_intake_and_the_checks_leave_the_outbox_alone(self):
        self.role("roaming", name="laptop")
        self.tick()
        sys.path.insert(0, str(REPO / "template" / "System" / "skills" / "intake"))
        try:
            import intake
            self.assertEqual([], [p for p in intake._waiting(self.work / "Inbox") if p.name != ".gitkeep"])
        finally:
            sys.path.remove(str(REPO / "template" / "System" / "skills" / "intake"))
        import check
        self.assertEqual([], [f for f in check.run_checks(self.root) if f.check == "inbox" and ".outbox" in f.path])


if __name__ == "__main__":
    unittest.main()
