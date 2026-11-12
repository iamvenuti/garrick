"""System/tools/next_up.py: what "what's next" offers, by six fixed rules (#111, #529).

    python3 -m unittest discover -s tests -p test_next_up.py
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "template" / "System" / "tools" / "next_up.py"
_spec = importlib.util.spec_from_file_location("garrick_next_up", str(TOOL))
nu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nu)

TODAY = dt.date(2026, 10, 14)

WORK_TODO = """# Work: open actions

## Inbox

- [ ] [[Renewal]]: Draft the renewal deck 📅 2026-10-14
- [ ] [[Renewal]]: Reply on the renewal dates · [src](../../Wikis/Meetings/wiki/meetings/2026-10-01 Acme kick-off.md) 📅 2026-10-14
- [ ] [[Pricing]]: Send the price list to Dana per [[2026-10-01 Acme kick-off]] “we need it by Friday” — as Dana said on the call 📅 2026-10-10
- [ ] [[Pricing]]: Build the rate model 📅 2026-10-30
- [ ] [[<Thread>]]: <action> 📅 2026-10-01

## Waiting on

- [ ] [[Renewal]]: Owen to return the signed order #waiting ⏳ 2026-10-13
- [ ] [[Pricing]]: Dana to confirm volumes #waiting ⏳ 2026-10-20

## Done
"""

HOME_TODO = """# Personal: open actions

## Inbox

- [ ] [[Garden]]: Call the nursery 📅 2026-10-14

## Done
"""


def thread(status: str = "active", stands: str = "Where it stands, 12 October 2026.", updated: str = "2026-10-12") -> str:
    return ("---\ntype: thread\nstatus: %s\nupdated: %s\n---\n# T\n\n## State of play\n\n### Resume here\n\n"
            "**%s** The work is going well.\n\n| | |\n|---|---|\n| Next action | something |\n" % (status, updated, stands))


def hub(status: str = "active") -> str:
    return "---\ntype: project\nstatus: %s\nparty: acme\n---\n# Hub\n" % status


def workspace(root: Path) -> Path:
    write(root / "System" / "rules.md", "# Rules\n")
    for tool in ("next_up.py", "garrick_lib.py"):
        write(root / "System" / "tools" / tool, (REPO / "template" / "System" / "tools" / tool).read_text(encoding="utf-8"))
    write(root / "System" / "skills" / "todo" / "todo.py",
          (REPO / "template" / "System" / "skills" / "todo" / "todo.py").read_text(encoding="utf-8"))
    work = root / "Zones" / "Work"
    write(work / "Todo.md", WORK_TODO)
    write(work / "Acme" / "Acme.md", hub())
    write(work / "Acme" / "Threads" / "Renewal" / "Renewal.md", thread())
    write(work / "Acme" / "Threads" / "Pricing" / "Pricing.md", thread())
    write(work / "Acme" / "Threads" / "Freight" / "Freight.md", thread(stands="Where it stands, 1 August 2026."))
    write(work / "Acme" / "Threads" / "Rebate" / "Rebate.md", thread("parked", updated="2026-08-01"))
    write(work / "Birch" / "Birch.md", hub("parked") + "\n### Resume here\n\nSet aside, 2026-07-01.\n")
    when = dt.datetime.combine(TODAY - dt.timedelta(days=90), dt.time(12)).timestamp()
    os.utime(work / "Birch" / "Birch.md", (when, when))
    write(work / "Inbox" / "renewal.eml", "From: dana@acme.example\n")
    write(work / "Inbox" / "rates.eml", "From: dana@acme.example\n")
    write(work / "Inbox" / ".DS_Store", "")
    home = root / "Zones" / "Personal"
    write(home / "Todo.md", HOME_TODO)
    write(home / "Garden" / "Garden.md", hub())
    write(home / "Garden" / "Threads" / "Garden" / "Garden.md", thread())
    write(root / "Wikis" / "Meetings" / "wiki" / "meetings" / "2026-10-01 Acme kick-off.md", "# Kick-off\n")
    # The record of where a thread stood is its note's modification time (#367): two were written
    # today, the later one at 10:40, and every other note is older.
    def stamp(note: Path, when: dt.datetime) -> None:
        os.utime(note, (when.timestamp(), when.timestamp()))
    for note in root.glob("Zones/*/*/Threads/*/*.md"):
        stamp(note, dt.datetime(2026, 10, 1, 12, 0))
    stamp(work / "Acme" / "Threads" / "Renewal" / "Renewal.md", dt.datetime(2026, 10, 14, 10, 40))
    stamp(work / "Acme" / "Threads" / "Pricing" / "Pricing.md", dt.datetime(2026, 10, 14, 9, 15))
    stamp(work / "Acme" / "Threads" / "Rebate" / "Rebate.md", dt.datetime(2026, 10, 14, 11, 30))     # parked: never offered
    return root


def leftover(root: Path, **chosen) -> None:
    """What an older workspace's While you wait settings left behind: read by nothing now (#529)."""
    write(root / "System" / "garrick-settings.json", json.dumps({"while-you-wait": chosen}))


class NextUpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = workspace(Path(self.tmp.name).resolve())

    def tearDown(self):
        self.tmp.cleanup()

    def picks(self, **kw):
        return nu.next_up(self.root, today=TODAY, **kw)["picks"]

    def says(self, **kw):
        return [p["say"] for p in self.picks(**kw)]

    # ---- the six rules, in their order ----

    def test_the_rules_rank_in_their_order(self):
        sources = [p["source"] for p in self.picks()]
        self.assertEqual(sources, sorted(sources, key=nu.SOURCES.index))
        self.assertEqual(sources[0], "back")
        self.assertEqual(set(sources), set(nu.SOURCES))

    def test_the_thread_left_most_recently_comes_first_and_alone(self):
        back = [p for p in self.picks() if p["source"] == "back"]
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0]["say"], "Back to Renewal, left at 10:40")
        self.assertEqual(back[0]["note"], "Zones/Work/Acme/Threads/Renewal/Renewal.md")

    def test_the_thread_in_focus_is_left_out_and_the_next_one_offered(self):
        back = [p for p in self.picks(exclude="Zones/Work/Acme/Threads/Renewal") if p["source"] == "back"]
        self.assertEqual([p["say"] for p in back], ["Back to Pricing, left at 09:15"])

    def test_a_finished_or_parked_thread_is_never_the_one_to_go_back_to(self):
        done = self.root / "Zones" / "Work" / "Acme" / "Threads" / "Renewal" / "Renewal.md"
        done.write_text(done.read_text().replace("status: active", "status: done"), encoding="utf-8")
        when = dt.datetime(2026, 10, 14, 10, 40).timestamp()
        os.utime(done, (when, when))
        back = [p for p in self.picks() if p["source"] == "back"]
        self.assertEqual([p["say"] for p in back], ["Back to Pricing, left at 09:15"])     # not Renewal, not the parked Rebate

    def test_a_note_written_before_today_is_not_offered(self):
        for note in self.root.glob("Zones/*/*/Threads/*/*.md"):
            os.utime(note, (dt.datetime(2026, 10, 13, 18, 0).timestamp(),) * 2)
        self.assertNotIn("back", [p["source"] for p in self.picks()])

    def test_due_lines_quickest_first_then_the_latest(self):
        due = [p["say"] for p in self.picks() if p["source"] == "due"]
        self.assertEqual(due, [
            "Pricing: Send the price list to Dana per (Work, 4 days late)",
            "Garden: Call the nursery (Personal, due today)",
            "Renewal: Reply on the renewal dates (Work, due today)",
            "Renewal: Draft the renewal deck (Work, due today)",
        ])

    def test_a_chase_counts_once_its_day_has_come(self):
        chase = [p["say"] for p in self.picks() if p["source"] == "chase"]
        self.assertEqual(chase, ["Chase: Renewal: Owen to return the signed order (Work)"])

    def test_an_inbox_is_one_pick_and_hidden_files_do_not_count(self):
        inbox = [p for p in self.picks() if p["source"] == "inbox"]
        self.assertEqual([p["say"] for p in inbox], ["2 files in Work's Inbox: say “process the inbox”"])
        self.assertEqual(inbox[0]["note"], "Zones/Work/Inbox")

    def test_parked_past_its_days_asks_park_or_finish(self):
        parked = [p["say"] for p in self.picks() if p["source"] == "parked"]
        self.assertEqual(parked, ["Park or finish? Birch, untouched 90 days", "Park or finish? Rebate (Acme), untouched 74 days"])

    def test_a_live_thread_not_wrapped_lately_asks_wrap(self):
        wrap = [p["say"] for p in self.picks() if p["source"] == "wrap"]
        self.assertEqual(wrap, ["Wrap? Freight (Acme), resume point 74 days old"])

    def test_the_example_line_is_never_offered(self):
        self.assertFalse(any("<action>" in s for s in self.says()))

    def test_a_todo_pick_carries_the_tick_page_action_takes(self):
        due = [p for p in self.picks() if p["source"] == "due"][0]
        todo = nu.todo_lib()
        line = [l for l in WORK_TODO.splitlines() if "Send the price list" in l][0]
        self.assertEqual(due["tick"], {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": todo.key(line)})
        self.assertEqual(due["note"], "Zones/Work/Acme/Threads/Pricing/Pricing.md")
        self.assertEqual((due["project"], due["thread"]), ("Acme", "Pricing"))

    # ---- what a pick never says or names ----

    def test_never_quotes_a_meeting(self):
        text = " ".join(self.says())
        for leak in ("kick-off", "Kick-off", "src", "we need it by Friday", "as Dana said", "Meetings/"):
            self.assertNotIn(leak, text)

    def test_never_the_running_thread(self):
        excluded = self.picks(exclude="Zones/Work/Acme/Threads/Renewal/Renewal.md")
        self.assertFalse([p for p in excluded if p["thread"] == "Renewal"], [p["say"] for p in excluded])
        self.assertEqual(excluded[0]["say"], "Back to Pricing, left at 09:15")      # the next one left
        self.assertTrue([p for p in excluded if p["thread"] == "Pricing"])

    def test_a_project_excludes_every_thread_in_it(self):
        excluded = self.picks(exclude=str(self.root / "Zones" / "Work" / "Acme"))
        self.assertFalse([p for p in excluded if p["project"] == "Acme"], [p["say"] for p in excluded])
        self.assertTrue([p for p in excluded if p["project"] == "Birch"])

    # ---- zones ----

    def test_every_zone_by_default(self):
        zones = {p["zone"] for p in self.picks(zone="Work")}
        self.assertIn("Personal", zones)

    def test_a_zone_never_narrows_the_picks(self):
        found = nu.next_up(self.root, zone="Personal", today=TODAY)
        self.assertFalse(found["same_zone"])
        self.assertEqual({p["zone"] for p in found["picks"]}, {p["zone"] for p in self.picks()})

    # ---- no settings (#529) ----

    def test_the_rules_are_fixed(self):
        chosen = nu.next_up(self.root, today=TODAY)["settings"]
        self.assertEqual(chosen, {"on": True, "threshold": 45, "same-zone": False, "sources": list(nu.SOURCES),
                                  "parked-days": 30, "wrap-days": 14})
        for gone in ("KEY", "clean", "settings", "SOURCE_LABELS", "THRESHOLD", "DAYS"):
            self.assertFalse(hasattr(nu, gone), gone)

    def test_leftover_settings_change_nothing(self):
        before = nu.next_up(self.root, zone="Personal", today=TODAY)
        leftover(self.root, **{"same-zone": True, "sources": ["inbox"], "parked-days": 80, "wrap-days": 100,
                               "threshold": 600, "on": False})
        self.assertEqual(before, nu.next_up(self.root, zone="Personal", today=TODAY))

    def test_the_output_with_no_settings_is_what_it_was(self):
        found = nu.next_up(self.root, zone="Work", today=TODAY)
        self.assertEqual(list(found), ["on", "threshold", "zone", "same_zone", "exclude", "settings", "picks"])
        self.assertEqual((found["on"], found["threshold"], found["zone"], found["same_zone"], found["exclude"]),
                         (True, 45, "Work", False, None))
        self.assertEqual([p["source"] for p in found["picks"]][:1], ["back"])
        self.assertEqual(len(found["picks"]), 10)

    # ---- the command line ----

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(self.root / "System" / "tools" / "next_up.py"), "--today", TODAY.isoformat()]
                              + list(args), capture_output=True, text=True, timeout=60)

    def test_prints_json_and_its_first_pick_for_the_ear(self):
        done = self.run_tool("--zone", "Work")
        self.assertEqual(done.returncode, 0, done.stderr)
        data = json.loads(done.stdout)
        self.assertEqual((data["on"], data["threshold"]), (True, 45))
        said = self.run_tool("--say")
        self.assertEqual(said.stdout.strip(), data["picks"][0]["say"])

    def test_the_exclusion_and_the_say_line_agree_on_the_first_pick(self):
        band = json.loads(self.run_tool("--zone", "Work", "--exclude", "Zones/Work/Acme/Threads/Renewal").stdout)
        skill = self.run_tool("--zone", "Work", "--exclude", "Zones/Work/Acme/Threads/Renewal/Renewal.md", "--say")
        self.assertEqual(skill.stdout.strip(), band["picks"][0]["say"])

    def test_changes_nothing(self):
        before = {p: p.stat().st_mtime_ns for p in self.root.rglob("*") if p.is_file()}
        self.run_tool()
        after = {p: p.stat().st_mtime_ns for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_nothing_waiting_says_so(self):
        with tempfile.TemporaryDirectory() as empty:
            write(Path(empty) / "System" / "rules.md", "# Rules\n")
            done = subprocess.run([sys.executable, str(TOOL), "--root", empty, "--say"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.stdout.strip(), "Nothing is waiting.")

    def test_outside_a_workspace_it_stops(self):
        with tempfile.TemporaryDirectory() as other:
            done = subprocess.run([sys.executable, str(TOOL), "--root", other], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
