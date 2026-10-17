"""System/tools/next_up.py: what the band offers while a long turn runs (#111).

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


def workspace(root: Path, stack: bool = True) -> Path:
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
    if stack:
        write(root / "System" / "status" / "page_action.py", "# the status extra\n")
    write(root / "System" / "generated" / "interrupted.json", json.dumps({"stack": [
        {"zone": "Work", "project": "Acme", "thread": "Renewal", "file": "Acme/Threads/Renewal/Renewal.md", "at": "2026-10-14T10:40"},
        {"zone": "Work", "project": "Acme", "thread": "Pricing", "file": "Acme/Threads/Pricing/Pricing.md", "at": "2026-10-14T09:15"},
    ]}))
    return root


def settings(root: Path, **chosen) -> None:
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
        self.assertEqual(sources[0], "stack")
        self.assertEqual(set(sources), set(nu.SOURCES))

    def test_the_top_of_the_stack_comes_first_and_alone(self):
        stack = [p for p in self.picks() if p["source"] == "stack"]
        self.assertEqual(len(stack), 1)
        self.assertEqual(stack[0]["say"], "Back to Renewal, on hold since 10:40")
        self.assertEqual(stack[0]["note"], "Zones/Work/Acme/Threads/Renewal/Renewal.md")

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
        self.assertEqual(excluded[0]["say"], "Back to Pricing, on hold since 09:15")      # the next one held
        self.assertTrue([p for p in excluded if p["thread"] == "Pricing"])

    def test_a_project_excludes_every_thread_in_it(self):
        excluded = self.picks(exclude=str(self.root / "Zones" / "Work" / "Acme"))
        self.assertFalse([p for p in excluded if p["project"] == "Acme"], [p["say"] for p in excluded])
        self.assertTrue([p for p in excluded if p["project"] == "Birch"])

    # ---- zones ----

    def test_every_zone_by_default(self):
        zones = {p["zone"] for p in self.picks(zone="Work")}
        self.assertIn("Personal", zones)

    def test_same_zone_only_narrows_to_the_sessions_zone(self):
        settings(self.root, **{"same-zone": True})
        found = nu.next_up(self.root, zone="Personal", today=TODAY)
        self.assertTrue(found["same_zone"])
        self.assertEqual({p["zone"] for p in found["picks"]}, {"Personal"})

    def test_same_zone_without_a_zone_is_every_zone(self):
        settings(self.root, **{"same-zone": True})
        self.assertIn("Personal", {p["zone"] for p in self.picks()})

    # ---- the stack needs the status extra ----

    def test_no_stack_without_the_status_extra(self):
        (self.root / "System" / "status" / "page_action.py").unlink()
        self.assertNotIn("stack", [p["source"] for p in self.picks()])
        self.assertEqual(self.picks()[0]["source"], "due")

    # ---- settings ----

    def test_sources_switched_off_or_reordered(self):
        settings(self.root, sources=["inbox", "due"])
        self.assertEqual(sorted({p["source"] for p in self.picks()}, key=["inbox", "due"].index), ["inbox", "due"])
        self.assertEqual(self.picks()[0]["source"], "inbox")

    def test_staleness_is_a_setting(self):
        settings(self.root, **{"parked-days": 80, "wrap-days": 100})
        sources = [p["source"] for p in self.picks()]
        self.assertEqual(sources.count("parked"), 1)
        self.assertNotIn("wrap", sources)

    def test_clean_refuses_what_the_page_could_not_mean(self):
        self.assertEqual(nu.clean({})["threshold"], 45)
        self.assertEqual(nu.clean({"threshold": 90, "same-zone": True})["same-zone"], True)
        for bad in ({"threshold": 3}, {"threshold": "45"}, {"on": "yes"}, {"sources": ["due", "due"]},
                    {"sources": ["mail"]}, {"wrap-days": 0}, {"colour": 1}, []):
            with self.assertRaises(ValueError, msg=bad):
                nu.clean(bad)

    def test_a_setting_that_does_not_read_falls_back(self):
        settings(self.root, threshold="soon", on=False)
        chosen = nu.settings(self.root)
        self.assertEqual((chosen["threshold"], chosen["on"]), (45, False))

    def test_the_settings_key_is_a_kept_preference(self):
        sys.path.insert(0, str(REPO / "template" / "System" / "tools"))
        import garrick_lib
        self.assertIn(nu.KEY, garrick_lib.PREFERENCES)

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

    def test_the_skill_and_the_band_get_the_same_first_pick(self):
        band = json.loads(self.run_tool("--zone", "Work", "--exclude", "Zones/Work/Acme/Threads/Renewal").stdout)
        skill = self.run_tool("--zone", "Work", "--exclude", "Zones/Work/Acme/Threads/Renewal/Renewal.md", "--say")
        self.assertEqual(skill.stdout.strip(), band["picks"][0]["say"])

    def test_changes_nothing(self):
        before = {p: p.stat().st_mtime_ns for p in self.root.rglob("*") if p.is_file()}
        self.run_tool()
        after = {p: p.stat().st_mtime_ns for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_nothing_waiting_says_so(self):
        settings(self.root, sources=[])
        self.assertEqual(self.run_tool("--say").stdout.strip(), "Nothing is waiting.")

    def test_outside_a_workspace_it_stops(self):
        with tempfile.TemporaryDirectory() as other:
            done = subprocess.run([sys.executable, str(TOOL), "--root", other], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
