"""System/tools/briefing.py: what "catch me up" rests on (#27).

    python3 -m unittest discover -s tests -p test_briefing.py
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

from fixtures import GIT_ENV, HAVE_GIT, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "template" / "System" / "tools" / "briefing.py"
_spec = importlib.util.spec_from_file_location("garrick_briefing", str(TOOL))
br = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(br)

TODAY = dt.date(2026, 10, 23)          # a Friday
OLD, NEW = "2026-10-12T10:00:00", "2026-10-21T15:30:00"


def note(status="active", stands="Where it stands, 12 October 2026.", body="The price sheet is drafted.",
         nxt="Send the sheet to Dana", entries=("**12 October 2026.** Drafted the price sheet.",), extra=""):
    return ("---\ntype: thread\nstatus: %s\nupdated: 2026-10-12\n---\n# T\n\n## State of play\n\n### Resume here\n\n"
            "**%s** %s\n\n| | |\n|---|---|\n| Live artifact | `Deliverables/261012 - Price sheet.xlsx` |\n"
            "| Next action | %s |\n| Waiting on | nobody |\n| Deadline | not given |\n%s\n---\n\n%s\n"
            % (status, stands, body, nxt, extra, "\n\n".join(entries)))


TODO_OLD = """# Work: open actions

## Inbox

- [ ] [[Pricing]]: Send the sheet to Dana 📅 2026-10-15
- [ ] [[Freight]]: Book the carrier call
- [ ] [[<Thread>]]: <action> 📅 2026-10-01

## Done
"""

TODO_NEW = """# Work: open actions

## Inbox

- [ ] [[Pricing]]: Send the sheet to Dana 📅 2026-10-15
- [ ] [[Pricing]]: Confirm volumes per [[2026-10-20 Acme call]] “by Friday” · [src](../../Wikis/Meetings/wiki/sources/2026-10-20 Acme call.md) 📅 2026-10-30
- [ ] [[Freight]]: Book the carrier call
- [ ] [[Launch]]: Draft the launch note

## Done

- [x] [[Pricing]]: Check the tier-two rate ✅ 2026-10-21
"""


def commit(repo: Path, message: str, when: str) -> None:
    env = dict(GIT_ENV, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), env=env, check=True, capture_output=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull, "commit", "-q",
                    "--allow-empty", "-m", message], cwd=str(repo), env=env, check=True, capture_output=True)


def workspace(root: Path) -> Path:
    """Work, a git repository: Acme with Pricing (changed lately), Freight
    (quiet), Rebate (parked, changed), Old Terms (done, quiet); Birch
    Entry with Launch (changed only on its Todo line). Personal, untouched."""
    write(root / "System" / "rules.md", "# Rules\n")
    for tool in ("briefing.py", "next_up.py", "garrick_lib.py"):
        write(root / "System" / "tools" / tool, (REPO / "template" / "System" / "tools" / tool).read_text(encoding="utf-8"))
    write(root / "System" / "skills" / "todo" / "todo.py",
          (REPO / "template" / "System" / "skills" / "todo" / "todo.py").read_text(encoding="utf-8"))
    write(root / "System" / "briefing.md", "# Briefing\n")
    write(root / "Wikis" / "Meetings" / "wiki" / "sources" / "2026-10-20 Acme call.md", "---\nzone: Work\n---\n# Call\n")
    work = root / "Zones" / "Work"
    acme = work / "Acme"
    write(acme / "Acme.md", "---\ntype: project\nstatus: active\nparty: acme\n---\n# Acme\n")
    write(acme / "Threads" / "Pricing" / "Pricing.md", note())
    write(acme / "Threads" / "Freight" / "Freight.md", note(nxt="Book the call"))
    write(acme / "Threads" / "Rebate" / "Rebate.md", note("parked"))
    write(acme / "Threads" / "Old Terms" / "Old Terms.md", note("done"))
    birch = work / "Birch Entry"
    write(birch / "Birch Entry.md", "---\ntype: project\nstatus: active\nparty: birch\n---\n# Birch Entry\n")
    write(birch / "Threads" / "Launch" / "Launch.md", note(nxt="Draft the note"))
    write(work / "Todo.md", TODO_OLD)
    write(root / "Zones" / "Personal" / "Garden" / "Garden.md", "---\ntype: project\nstatus: active\n---\n# Garden\n")
    subprocess.run(["git", "init", "-q"], cwd=str(work), env=GIT_ENV, check=True)
    commit(work, "Work: first notes", OLD)
    # the period: Pricing wrapped, with a new entry and a link to the call; Rebate touched while parked
    write(acme / "Threads" / "Pricing" / "Pricing.md", note(
        stands="Where it stands, 21 October 2026.", body="The sheet went to Dana; waiting on her volumes.",
        nxt="Chase Dana's volumes", entries=("**21 October 2026.** Sent the sheet, as agreed on [[2026-10-20 Acme call]]. "
                                              "Dana decided tier two stays.",
                                              "**12 October 2026.** Drafted the price sheet.")))
    write(acme / "Threads" / "Rebate" / "Rebate.md", note("parked", body="Set aside until spring."))
    write(work / "Todo.md", TODO_NEW)
    commit(work, "Pricing: wrap; the sheet went to Dana\n\nTier two stays.", NEW)
    return root


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class BriefingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = workspace(Path(self.tmp.name).resolve())

    def tearDown(self):
        self.tmp.cleanup()

    def gather(self, **kw):
        kw.setdefault("zones", ["Work"])
        kw.setdefault("today", TODAY)
        return br.gather(self.root, **kw)

    def by_name(self, found):
        return {t["thread"] or t["project"]: t for t in found["threads"]}

    # ---- what is listed ----

    def test_lists_the_threads_that_changed_newest_first(self):
        found = self.gather(days=7)
        self.assertEqual(["Pricing", "Launch"], [t["thread"] for t in found["threads"]])
        self.assertEqual(["Freight"], [q["thread"] for q in found["quiet"]])   # live, unchanged: named, no more
        self.assertEqual(1, found["parked_left_out"])                          # Rebate, counted, never named

    def test_nothing_before_the_period(self):
        found = self.gather(since=dt.date(2026, 10, 22))
        self.assertEqual([], found["threads"])
        self.assertEqual({"Pricing", "Freight", "Launch"}, {q["thread"] for q in found["quiet"]})

    def test_a_parked_thread_only_when_named(self):
        self.assertNotIn("Rebate", self.by_name(self.gather(days=7)))
        named = self.by_name(self.gather(days=7, threads=["Rebate"]))
        self.assertEqual(["Rebate"], list(named))
        self.assertEqual("parked", named["Rebate"]["status"])
        self.assertIn("Rebate", self.by_name(self.gather(days=7, projects=["acme"])))   # its project named

    def test_a_named_thread_is_listed_unchanged(self):
        found = self.by_name(self.gather(days=7, threads=["Acme/Freight"]))
        self.assertEqual(["Freight"], list(found))
        self.assertFalse(found["Freight"]["changed"])

    def test_a_done_thread_only_if_it_changed(self):
        self.assertNotIn("Old Terms", self.by_name(self.gather(days=7, projects=["Acme"])))
        self.assertIn("Old Terms", self.by_name(self.gather(days=30, projects=["Acme"])))   # made in the period

    def test_a_project_narrows_the_zone(self):
        found = self.gather(days=7, projects=["Birch Entry"])
        self.assertEqual(["Launch"], [t["thread"] for t in found["threads"]])
        self.assertEqual([], found["quiet"])

    def test_a_name_that_matches_nothing_is_said(self):
        self.assertEqual(["roofing"], self.gather(days=7, threads=["Roofing"])["unmatched"])

    # ---- what a thread carries ----

    def test_commits_with_their_messages_and_files(self):
        pricing = self.by_name(self.gather(days=7))["Pricing"]
        self.assertEqual(1, len(pricing["commits"]))
        c = pricing["commits"][0]
        self.assertEqual(("Pricing: wrap; the sheet went to Dana", "Tier two stays."), (c["subject"], c["body"]))
        self.assertEqual(["Acme/Threads/Pricing/Pricing.md"], c["files"])
        self.assertTrue(c["when"].startswith("2026-10-21"))

    def test_the_resume_block_now_and_as_it_was(self):
        r = self.by_name(self.gather(days=7))["Pricing"]["resume"]
        self.assertTrue(r["changed"])
        self.assertIn("waiting on her volumes", r["now"])
        self.assertIn("The price sheet is drafted.", r["before"])
        self.assertEqual("Chase Dana's volumes", r["rows"]["Next action"])

    def test_only_the_entries_added_in_the_period(self):
        e = self.by_name(self.gather(days=7))["Pricing"]["entries"]
        self.assertEqual(["2026-10-21"], [x["date"] for x in e])
        self.assertIn("Dana decided tier two stays.", e[0]["text"])

    def test_todo_lines_split_three_ways(self):
        todo = self.by_name(self.gather(days=7))["Pricing"]["todo"]
        self.assertEqual(["Pricing: Check the tier-two rate"], [x["said"] for x in todo["ticked"]])
        self.assertEqual(["2026-10-21"], [x["done"] for x in todo["ticked"]])
        self.assertEqual(["Pricing: Confirm volumes per"], [x["said"] for x in todo["added"]])
        self.assertEqual([("Pricing: Send the sheet to Dana", "overdue", 8)],
                         [(x["said"], x["state"], x["late"]) for x in todo["open"]])

    def test_a_todo_line_alone_is_a_change(self):
        launch = self.by_name(self.gather(days=7))["Launch"]
        self.assertEqual([], launch["commits"])
        self.assertEqual(["Launch: Draft the launch note"], [x["said"] for x in launch["todo"]["added"]])

    def test_ticked_lines_are_found_in_the_archive_too(self):
        write(self.root / "Zones" / "Work" / "archive" / "Todo-2026.md",
              "# Work: done, 2026\n\n- [x] [[Freight]]: Get the quote ✅ 2026-10-20\n")
        freight = self.by_name(self.gather(days=7))["Freight"]
        self.assertEqual(["Freight: Get the quote"], [x["said"] for x in freight["todo"]["ticked"]])

    def test_never_quotes_a_meeting(self):
        found = json.dumps(self.gather(days=7)["threads"][0]["todo"])
        for leak in ("by Friday", "src", "Acme call", "Meetings/"):
            self.assertNotIn(leak, found)

    def test_meetings_only_as_the_links_the_note_holds(self):
        pricing = self.by_name(self.gather(days=7))["Pricing"]
        self.assertEqual(["2026-10-20 Acme call"], pricing["meetings"])
        self.assertEqual([], self.by_name(self.gather(days=7))["Launch"]["meetings"])

    def test_a_waiting_checkpoint(self):
        sys.path.insert(0, str(REPO / "template" / "System" / "tools"))
        import garrick_lib as gl
        path = self.root / "Zones" / "Work" / "Acme" / "Threads" / "Freight" / "Freight.md"
        text = path.read_text(encoding="utf-8")
        item = gl.checkpoint_item_line("next", "Ring the carrier", "n")
        block, _ = gl.render_checkpoint("2026-10-22T09:15", gl.resume_hash(text), [{"line": item}])
        path.write_text(gl.place_checkpoint(text, "### Checkpoint\n\n" + block + "\n"), encoding="utf-8")
        freight = self.by_name(self.gather(days=7))["Freight"]
        self.assertTrue(freight["changed"])
        self.assertEqual([{"kind": "next", "text": "Ring the carrier"}], freight["checkpoint"]["items"])
        self.assertFalse(freight["checkpoint"]["stale"])
        self.assertEqual(["Acme/Threads/Freight/Freight.md"], freight["uncommitted"])    # written, not committed

    def test_two_threads_of_one_name_say_a_bare_link_could_be_either(self):
        write(self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Pricing" / "Pricing.md", note())
        found = [t for t in self.gather(days=7, threads=["Pricing"])["threads"]]
        self.assertEqual(2, len(found))
        for t in found:
            self.assertTrue(all(x.get("either") for x in t["todo"]["ticked"]), t["project"])

    def test_without_history_entries_go_by_their_date(self):
        os.rename(str(self.root / "Zones" / "Work" / ".git"), str(self.root / "Zones" / "Work" / "git-away"))
        pricing = self.by_name(self.gather(days=7))["Pricing"]
        self.assertFalse(pricing["history"])
        self.assertEqual(["2026-10-21"], [x["date"] for x in pricing["entries"]])
        self.assertIsNone(pricing["resume"]["changed"])                  # no history to tell

    # ---- the period ----

    def test_the_period_by_default_is_the_settings(self):
        self.assertEqual(("2026-10-22", "settings", "since yesterday"),
                         tuple(self.gather()["period"][k] for k in ("since", "given", "said")))
        write(self.root / "System" / "garrick-settings.json", json.dumps({"catch-up": {"period": "week"}}))
        p = self.gather()["period"]
        self.assertEqual(("2026-10-19", "since Monday 19 October"), (p["since"], p["said"]))

    def test_each_period(self):
        for kw, since in (({"days": 3}, "2026-10-20"), ({"named_period": "7-days"}, "2026-10-16"),
                          ({"named_period": "14-days"}, "2026-10-09"), ({"since": dt.date(2026, 10, 1)}, "2026-10-01")):
            self.assertEqual(since, self.gather(**kw)["period"]["since"], kw)

    def test_clean_refuses_what_the_page_could_not_mean(self):
        self.assertEqual({"period": "day"}, br.clean({}))
        self.assertEqual({"period": "14-days"}, br.clean({"period": "14-days"}))
        for bad in ({"period": "month"}, {"colour": 1}, []):
            with self.assertRaises(ValueError, msg=bad):
                br.clean(bad)

    def test_a_setting_that_does_not_read_falls_back(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"catch-up": {"period": "fortnight"}}))
        self.assertEqual({"period": "day"}, br.settings(self.root))

    def test_the_settings_key_is_a_kept_preference(self):
        sys.path.insert(0, str(REPO / "template" / "System" / "tools"))
        import garrick_lib
        self.assertIn(br.KEY, garrick_lib.PREFERENCES)

    # ---- zones ----

    def test_one_zone_unless_more_are_named(self):
        with self.assertRaises(ValueError):
            br.gather(self.root, today=TODAY)                           # two zones here: say which
        self.assertEqual(["Work", "Personal"], self.gather(zones=["work", "Personal"], days=7)["zones"])
        with self.assertRaises(ValueError):
            self.gather(zones=["Home"])

    def test_names_the_guidance_there_is(self):
        self.assertEqual(["System/briefing.md"], self.gather()["guidance"])
        write(self.root / "System" / "briefing.local.md", "# Mine\n")
        self.assertEqual(["System/briefing.md", "System/briefing.local.md"], self.gather()["guidance"])

    # ---- the command line ----

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(self.root / "System" / "tools" / "briefing.py"), "--today",
                               TODAY.isoformat()] + list(args), capture_output=True, text=True, timeout=60)

    def test_prints_json(self):
        done = self.run_tool("--zone", "Work", "--days", "7")
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual("Pricing", json.loads(done.stdout)["threads"][0]["thread"])

    def test_changes_nothing(self):
        before = {p: p.stat().st_mtime_ns for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts}
        self.run_tool("--zone", "Work", "--period", "week")
        after = {p: p.stat().st_mtime_ns for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts}
        self.assertEqual(before, after)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=str(self.root / "Zones" / "Work"),
                                capture_output=True, text=True, env=GIT_ENV)
        self.assertEqual("", status.stdout)

    def test_usage_errors_exit_two(self):
        self.assertEqual(2, self.run_tool("--zone", "Nowhere").returncode)
        self.assertEqual(2, self.run_tool("--zone", "Work", "--days", "0").returncode)
        with tempfile.TemporaryDirectory() as other:
            done = subprocess.run([sys.executable, str(TOOL), "--root", other], capture_output=True, text=True, timeout=60)
        self.assertEqual(2, done.returncode)


if __name__ == "__main__":
    unittest.main()
