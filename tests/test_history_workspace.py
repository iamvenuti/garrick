"""History files in an installed workspace (#502): two walled zones and one open, the wall check and the commit
hook, a second run, a rename and a move, and the places that list threads.

    cd tests && python3 -m unittest test_history_workspace

The workspace is made by the installer into a temporary folder. Invented parties only.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import test_setup  # noqa: E402
from test_setup import Installed  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TODAY = datetime.date.today()
STOCK = "Thread opened and scoped the work."     # seven words after its date: the wording check reads eight


def day(n):
    return TODAY - datetime.timedelta(days=n)


def stamp(d):
    return "%d %s %d" % (d.day, d.strftime("%B"), d.year)


class Made(Installed):
    """Work and Home walled, Ventures open, one project each, and a long note in every one."""

    def setUp(self):
        self.tmp_config = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_config.cleanup)
        config = {"owner": {"name": "Sam Rivera", "description": "Independent advisor."},
                  "zones": [{"name": "Work", "holds": "Client work"}, {"name": "Home", "holds": "Home"},
                            {"name": "Ventures", "holds": "Own ventures", "new-parties": "open"}],
                  "parties": [{"name": "Acme Corp", "what": "Client", "zone": "Work", "tag": "acme", "domains": ["acmecorp.example"]},
                              {"name": "Own affairs", "what": "Personal", "zone": "Home", "tag": "own", "domains": []},
                              {"name": "Cedar Ltd", "what": "Own venture", "zone": "Ventures", "tag": "cedar", "domains": [],
                               "walled": False}],
                  "people": [], "aliases": [], "allow-commands": True}
        path = Path(self.tmp_config.name) / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        original = test_setup.EXAMPLE
        test_setup.EXAMPLE = path
        try:
            super().setUp()
        finally:
            test_setup.EXAMPLE = original
        self.zones = {"Work": ("Northwind", "Pricing", "acme"), "Home": ("Garden", "Beds", "own"),
                      "Ventures": ("Orchard", "Drafts", "cedar")}
        for zone, (project, thread, party) in self.zones.items():
            r = self.run_tool("scaffold.py", "project", "--zone", zone, "--name", project, "--party", party, "--thread", thread)
            self.assertEqual(0, r.returncode, r.stderr)
            self.write_long(zone)
            self.git(zone, "add", "-A")
            done = self.git(zone, "commit", "-q", "-m", "long note")
            self.assertEqual(0, done.returncode, done.stdout + done.stderr)

    def note(self, zone):
        project, thread, _ = self.zones[zone]
        return self.root / "Zones" / zone / project / "Threads" / thread / (thread + ".md")

    def git(self, zone, *args):
        return subprocess.run(["git", *args], cwd=str(self.root / "Zones" / zone), capture_output=True, text=True, env=self.env)

    def write_long(self, zone, count=40, words=250):
        note = self.note(zone)
        text = note.read_text(encoding="utf-8")
        fm_end = text.index("\n---\n") + 5                 # the end of the frontmatter
        rule = text.index("\n---\n", fm_end)               # the rule under the Resume here block
        head, sep = text[:rule], "\n---\n"
        thread = zone.lower()          # the zone's own words, so only the thread names are shared
        entries = []
        for i in range(count):
            d = day(i * 9)
            filler = " ".join("%s%d" % (thread, k) for k in range(words))
            body = STOCK if i == count - 1 else "Session %d settled the %s plan." % (i, thread)
            entries.append("**%s.** %s\n\n%s notes, see [the memo](Deliverables/%s-memo.md): %s.\n" % (stamp(d), body, thread.capitalize(), thread, filler))
        note.write_text(head + sep + "\n" + "\n".join(entries), encoding="utf-8")

    def history(self, *args):
        return self.run_tool("history.py", *args)

    def errors(self, where="Zones"):
        found = json.loads(self.run_tool("check.py", "--json").stdout)["findings"]
        return [f for f in found if f["severity"] == "error" and f["path"].startswith(where)]


class Wrapped(Made):
    def test_a_long_note_in_each_zone_is_trimmed_in_one_commit_that_passes_the_wall_check_and_the_hook(self):
        for zone in self.zones:
            note = self.note(zone)
            rel = note.relative_to(self.root).as_posix()
            before = note.read_text(encoding="utf-8").split("\n")
            r = self.history("apply", rel, "--commit", "%s: older entries moved to history" % zone)
            self.assertEqual(0, r.returncode, r.stdout + r.stderr)
            self.assertIn("moved", r.stdout)
            self.assertEqual("%s: older entries moved to history" % zone, self.git(zone, "log", "-1", "--format=%s").stdout.strip())
            self.assertEqual("", self.git(zone, "status", "--porcelain").stdout)
            text = note.read_text(encoding="utf-8")
            self.assertLessEqual(len(text.split()), 4000 + 200)
            self.assertEqual(1, text.count("*Older entries:"))
            held = set()
            for path in (note.parent / "history").glob("*.md"):
                held.update(path.read_text(encoding="utf-8").split("\n"))
            now = set(text.split("\n"))
            for line in before:
                if line.strip() and line not in now:
                    self.assertIn(line.replace("](Deliverables/", "](../Deliverables/"), held)
        self.assertEqual([], self.errors())

    def test_a_second_run_changes_nothing(self):
        for zone in self.zones:
            rel = self.note(zone).relative_to(self.root).as_posix()
            self.assertEqual(0, self.history("apply", rel, "--commit", "m").returncode)
        heads = {zone: self.git(zone, "rev-parse", "HEAD").stdout for zone in self.zones}
        for zone in self.zones:
            rel = self.note(zone).relative_to(self.root).as_posix()
            r = self.history("apply", rel, "--commit", "again")
            self.assertEqual(0, r.returncode)
            self.assertEqual(heads[zone], self.git(zone, "rev-parse", "HEAD").stdout)
            self.assertEqual("", self.git(zone, "status", "--porcelain").stdout)

    def test_the_dry_run_lists_every_note_with_both_counts_and_writes_nothing(self):
        r = self.history("dry-run")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(3, r.stdout.count("would move"))
        for zone in self.zones:
            self.assertIn(self.note(zone).relative_to(self.root).as_posix(), r.stdout)
        self.assertRegex(r.stdout, r"\d+ words -> \d+ words")
        for zone in self.zones:
            self.assertFalse((self.note(zone).parent / "history").exists())
            self.assertEqual("", self.git(zone, "status", "--porcelain").stdout)

    def test_check_warns_about_a_long_note_naming_the_note_and_both_counts_then_not(self):
        found = json.loads(self.run_tool("check.py", "--json").stdout)["findings"]
        over = [f for f in found if "note-max-words" in f["message"]]
        self.assertEqual(3, len(over), over)
        for f in over:
            self.assertEqual("warning", f["severity"])
            self.assertRegex(f["message"], r"\d+ words.*4,?000")
        for zone in self.zones:
            self.assertEqual(0, self.history("apply", self.note(zone).relative_to(self.root).as_posix(), "--commit", "m").returncode)
        found = json.loads(self.run_tool("check.py", "--json").stdout)["findings"]
        self.assertEqual([], [f for f in found if "note-max-words" in f["message"]])

    def test_history_files_are_not_read_as_threads_anywhere(self):
        for zone in self.zones:
            self.assertEqual(0, self.history("apply", self.note(zone).relative_to(self.root).as_posix(), "--commit", "m").returncode)
        found = json.loads(self.run_tool("check.py", "--json").stdout)["findings"]
        self.assertEqual([], [f for f in found if "history" in f["path"].lower() and f["severity"] == "error"])
        self.assertEqual([], [f for f in found if "history" in f["path"].lower() and "status" in f["message"]])
        r = self.run_tool("briefing.py", "--zone", "Work")
        self.assertEqual(0, r.returncode, r.stderr)
        rows = json.loads(r.stdout)
        names = {t["thread"] for t in rows["threads"]} | set(rows.get("quiet", []) and [])
        self.assertFalse([n for n in names if n and "history" in n])

    def test_the_status_page_and_the_todo_list_see_threads_not_history_files(self):
        for zone in self.zones:
            self.assertEqual(0, self.history("apply", self.note(zone).relative_to(self.root).as_posix(), "--commit", "m").returncode)
        out = self.root / "System" / "generated" / "history-test.html"
        r = subprocess.run([sys.executable, str(self.root / "System" / "status" / "status.py"), "--workspace", str(self.root),
                            "--out", str(out), "--no-graph", "--no-cmux"], capture_output=True, text=True, env=self.env, cwd=str(self.root))
        self.assertEqual(0, r.returncode, r.stderr[-400:])
        page = out.read_text(encoding="utf-8")
        for zone, (project, thread, _) in self.zones.items():
            self.assertIn(thread, page)
        self.assertNotIn(" history 20", page)
        r = subprocess.run([sys.executable, str(self.root / "System" / "skills" / "todo" / "todo.py"), "list", "--zone", "Work"],
                           capture_output=True, text=True, env=self.env, cwd=str(self.root))
        self.assertNotIn(" history 20", r.stdout)

    def test_a_dead_link_inside_a_history_file_is_no_finding(self):
        zone = "Work"
        note = self.note(zone)
        self.assertEqual(0, self.history("apply", note.relative_to(self.root).as_posix(), "--commit", "m").returncode)
        found = json.loads(self.run_tool("check.py", "--json").stdout)["findings"]
        self.assertEqual([], [f for f in found if "/history/" in f["path"]])


class Renamed(Made):
    def test_a_rename_takes_the_history_files_with_the_thread(self):
        note = self.note("Work")
        rel = note.relative_to(self.root).as_posix()
        self.assertEqual(0, self.history("apply", rel, "--commit", "m").returncode)
        quarters = sorted(p.name.rsplit(" ", 1)[1] for p in (note.parent / "history").glob("*.md"))
        r = self.run_tool("scaffold.py", "rename", "--zone", "Work", "--project", "Northwind", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(0, r.returncode, r.stderr)
        new = note.parent.parent / "Renewal"
        self.assertTrue((new / "Renewal.md").is_file())
        files = sorted(p.name for p in (new / "history").glob("*.md"))
        self.assertEqual(["Renewal history %s" % q for q in quarters], [f for f in files])
        text = (new / "Renewal.md").read_text(encoding="utf-8")
        line = next(l for l in text.split("\n") if l.startswith("*Older entries:"))
        for q in quarters:
            self.assertIn("[[Northwind/Threads/Renewal/history/Renewal history %s]]" % q[:-3], line)
        self.assertNotIn("Pricing history", text)
        one = (new / "history" / files[0]).read_text(encoding="utf-8")
        self.assertIn('parent: "[[Northwind/Threads/Renewal/Renewal|Renewal]]"', one)
        self.assertIn("# Renewal: history, %s" % files[0].rsplit(" ", 1)[1][:-3], one)
        self.assertNotIn("Pricing", "\n".join(one.split("\n")[:12]))       # the header: parent, heading
        self.assertEqual("", self.git("Work", "status", "--porcelain").stdout)
        self.assertEqual([], self.errors())


class SameName(Made):
    """Threads of one name in two walled zones and an open one: every link a history file or a link line holds
    names its own zone's file (a path from the project), so the wall check reads none of them as crossing."""

    def setUp(self):
        super().setUp()
        for zone, (project, thread, party) in list(self.zones.items()):
            if thread == "Pricing":
                continue
            new = (project, "Pricing", party)
            self.run_tool("scaffold.py", "rename", "--zone", zone, "--project", project, "--thread", thread, "--to", "Pricing")
            self.zones[zone] = new
            self.write_long(zone)
            self.git(zone, "add", "-A")
            self.git(zone, "commit", "-q", "-m", "long note")

    def test_each_zone_moves_its_own_thread_in_any_order_and_every_link_stays_home(self):
        for n, order in enumerate((("Work", "Home", "Ventures"), ("Ventures", "Home", "Work"))):
            for zone in order:
                project = self.zones[zone][0]
                note = self.note(zone)
                if n:                                         # long again, so the second order moves it again
                    self.write_long(zone)
                    self.git(zone, "add", "-A")
                    self.git(zone, "commit", "-q", "-m", "long again")
                r = self.history("apply", note.relative_to(self.root).as_posix(), "--commit", "%s: older entries moved" % zone)
                self.assertEqual(0, r.returncode, r.stdout + r.stderr)
                text = note.read_text(encoding="utf-8")
                line = next(l for l in text.split("\n") if l.startswith("*Older entries:"))
                files = sorted((note.parent / "history").glob("*.md"))
                self.assertTrue(files)
                for path in files:
                    self.assertIn("[[%s/Threads/Pricing/history/%s]]" % (project, path.stem), line)
                    self.assertIn('parent: "[[%s/Threads/Pricing/Pricing|Pricing]]"' % project, path.read_text(encoding="utf-8"))
                self.assertNotIn("[[Pricing", line)
        self.assertEqual([], self.errors())

class FreshInstall(Made):
    def test_no_instruction_file_is_over_its_word_budget(self):
        found = json.loads(self.run_tool("check.py", "--json").stdout)["findings"]
        self.assertEqual([], [f for f in found if f["check"] == "instructions" and "over its" in f["message"]])


class Moved(Made):
    def test_a_move_takes_the_history_folder_with_the_thread_and_its_links_still_lead_where_they_led(self):
        r = self.run_tool("scaffold.py", "project", "--zone", "Work", "--name", "Apex", "--party", "acme", "--thread", "Kickoff")
        self.assertEqual(0, r.returncode, r.stderr)
        self.git("Work", "add", "-A")
        self.git("Work", "commit", "-q", "-m", "apex")
        note = self.note("Work")
        (note.parent / "Deliverables").mkdir()
        (note.parent / "Deliverables" / "work-memo.md").write_text("# Memo\n", encoding="utf-8")
        self.git("Work", "add", "-A")
        self.git("Work", "commit", "-q", "-m", "memo")
        self.assertEqual(0, self.history("apply", note.relative_to(self.root).as_posix(), "--commit", "m").returncode)
        r = self.run_tool("scaffold.py", "move", "--zone", "Work", "--project", "Northwind", "--thread", "Pricing", "--to", "Apex")
        self.assertEqual(0, r.returncode, r.stderr)
        new = self.root / "Zones" / "Work" / "Apex" / "Threads" / "Pricing"
        self.assertTrue(list((new / "history").glob("Pricing history *.md")))
        for path in (new / "history").glob("*.md"):
            for target in __import__("re").findall(r"\]\((\.\./[^)]+)\)", path.read_text(encoding="utf-8")):
                self.assertTrue((path.parent / target).resolve().exists(), (path.name, target))
        self.assertEqual("", self.git("Work", "status", "--porcelain").stdout)
        self.assertEqual([], self.errors())


if __name__ == "__main__":
    unittest.main()
