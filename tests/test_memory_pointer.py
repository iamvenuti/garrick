"""The memory index and the pointers a parked thread leaves it for (#664): park moves a thread's pointer out of
MEMORY.md to parked/, wake puts it back exactly, finish deletes it; the budget check; nurture's kind.

    cd tests && python3 -m unittest test_memory_pointer

Run in a workspace the installer made, with a memory folder of its own in the temporary folder. Nothing reads this Mac.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import test_scaffold_manage as base  # noqa: E402
from test_scaffold_manage import REPO  # noqa: E402

sys.path.insert(0, str(REPO / "template" / "System" / "tools"))
import garrick_lib as lib  # noqa: E402

PRICING = "Zones/Work/Acme/Threads/Pricing/Pricing.md"
FREIGHT = "Zones/Work/Acme/Threads/Freight/Freight.md"
HUB = "Zones/Work/Acme/Acme.md"


def entry(name, text):
    return "---\nname: %s\ndescription: a pointer\ntype: project\nsource: user\ncreated: 2026-11-01\n---\n\n%s\n" % (name, text)


INDEX = ("# Memory Index\n\nPointers only.\n\n## Work\n\n"
         "- [Acme pricing](acme-pricing.md) - resume from the thread note\n"
         "- [Acme freight](acme-freight.md) - resume from the thread note\n\n"
         "## Projects\n\n- [Cedar](cedar.md) - resume from the hub\n")


class Memory(base.ManageCase):
    """A workspace with Acme (threads Pricing and Freight), and a memory folder the settings name."""

    def setUp(self):
        super().setUp()
        self.mem = self.base / "memory"
        self.mem.mkdir()
        self.index = self.mem / "MEMORY.md"
        self.index.write_text(INDEX, encoding="utf-8")
        (self.mem / "acme-pricing.md").write_text(entry("Acme pricing", "Resume from %s. Never mix in Birch." % PRICING))
        (self.mem / "acme-freight.md").write_text(entry("Acme freight", "Resume from %s." % FREIGHT))
        (self.mem / "cedar.md").write_text(entry("Cedar", "A venture outside the zones."))
        self.settings(memory=str(self.mem))

    def settings(self, **values):
        path = self.root / "System" / "garrick-checks.json"
        data = json.loads(path.read_text()) if path.is_file() else {}
        data.update(values)
        path.write_text(json.dumps(data), encoding="utf-8")

    def park(self, thread="Pricing", verb="park", via_page=False):
        """scaffold.py as a session runs it (the page's own variable is not set), or the page's executor."""
        if via_page:
            done = subprocess.run([sys.executable, str(REPO / "extras" / "status" / "page_action.py"), "--workspace",
                                   str(self.root)], input=json.dumps({"verb": verb, "zone": "Work", "project": "Acme",
                                                                      "thread": thread}),
                                  capture_output=True, text=True, env=dict(self.env, GARRICK_JOBS_DIR=str(self.base / "jobs")))
            return json.loads(done.stdout)["say"]
        env = {k: v for k, v in self.env.items() if k != "GARRICK_CALLER_BUILDS_PAGE"}
        r = subprocess.run([sys.executable, str(self.root / "System" / "tools" / "scaffold.py"), verb, "--zone", "Work",
                            "--project", "Acme", "--thread", thread], capture_output=True, text=True, env=env, cwd=str(self.root))
        self.assertEqual(0, r.returncode, r.stderr)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "%s %s" % (thread, verb))
        return r.stdout.strip()


class TheMove(Memory):
    def test_parking_a_thread_moves_its_pointer_to_parked_and_takes_its_line_out(self):
        said = self.park()
        self.assertEqual("Acme, Pricing is parked. Its memory pointer is set aside until it wakes.", said)
        self.assertFalse((self.mem / "acme-pricing.md").exists())
        self.assertTrue((self.mem / "parked" / "acme-pricing.md").is_file())
        text = self.index.read_text()
        self.assertNotIn("acme-pricing.md", text)
        self.assertIn("acme-freight.md", text)
        self.assertEqual(INDEX.replace("- [Acme pricing](acme-pricing.md) - resume from the thread note\n", ""), text)

    def test_waking_it_puts_both_back_and_the_index_is_what_it_was(self):
        self.park()
        said = self.park(verb="wake")
        self.assertEqual("Acme, Pricing is awake again. Its memory pointer is back in the memory index.", said)
        self.assertTrue((self.mem / "acme-pricing.md").is_file())
        self.assertFalse((self.mem / "parked" / "acme-pricing.md").exists())
        self.assertEqual(INDEX, self.index.read_text())
        self.assertEqual([], [p.name for p in (self.mem / "parked").iterdir()])      # the line kept beside it is gone

    def test_the_page_parks_and_wakes_the_pointer_too(self):
        self.assertIn("Its memory pointer is set aside until it wakes.", self.park(via_page=True))
        self.assertTrue((self.mem / "parked" / "acme-pricing.md").is_file())
        self.assertIn("Its memory pointer is back in the memory index.", self.park(verb="wake", via_page=True))
        self.assertEqual(INDEX, self.index.read_text())

    def test_the_move_is_not_committed_and_nothing_in_a_zone_changes_for_it(self):
        self.park()
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertEqual("Pricing park", self.git("log", "-1", "--format=%s").stdout.strip())
        self.assertEqual([PRICING.split("Zones/Work/", 1)[1]], self.git("show", "--name-only", "--format=", "HEAD").stdout.split())

    def test_a_file_of_the_same_name_already_in_parked_holds_the_move_and_nothing_is_overwritten(self):
        (self.mem / "parked").mkdir()
        (self.mem / "parked" / "acme-pricing.md").write_text("older, kept\n")
        said = self.park()
        self.assertEqual("Acme, Pricing is parked. Its memory pointer was not moved: one of the same name is already "
                         "set aside.", said)
        self.assertEqual("older, kept\n", (self.mem / "parked" / "acme-pricing.md").read_text())
        self.assertTrue((self.mem / "acme-pricing.md").is_file())
        self.assertEqual(INDEX, self.index.read_text())

    def test_with_no_memory_setting_nothing_moves_and_nothing_is_said(self):
        self.settings(memory=[])
        self.assertEqual("Acme, Pricing is parked", self.park())
        self.assertEqual(INDEX, self.index.read_text())
        self.assertFalse((self.mem / "parked").exists())

    def test_a_thread_with_no_pointer_moves_nothing_and_says_nothing(self):
        self.assertEqual("Acme, Freight is parked", self.park("Freight") if self.drop("acme-freight.md") else "")
        self.assertEqual(INDEX.replace("- [Acme freight](acme-freight.md) - resume from the thread note\n", ""),
                         self.index.read_text())

    def drop(self, name):
        self.index.write_text("\n".join(l for l in self.index.read_text().split("\n") if name not in l))
        INDEX_NOW = self.index.read_text()
        return bool(INDEX_NOW)

    def test_two_entries_that_name_the_thread_are_not_told_apart_so_neither_moves(self):
        (self.mem / "pricing-again.md").write_text(entry("Pricing again", "Also %s." % PRICING))
        self.index.write_text(INDEX + "- [Pricing again](pricing-again.md) - more\n")
        said = self.park()
        self.assertEqual("Acme, Pricing is parked. Its memory pointer was not moved: more than one memory entry names it.", said)
        self.assertTrue((self.mem / "acme-pricing.md").is_file() and (self.mem / "pricing-again.md").is_file())

    def test_an_entry_that_names_two_notes_is_no_ones_pointer(self):
        (self.mem / "acme-pricing.md").write_text(entry("Acme", "See %s and %s." % (PRICING, FREIGHT)))
        self.assertEqual("Acme, Pricing is parked", self.park())
        self.assertTrue((self.mem / "acme-pricing.md").is_file())

    def test_an_entry_the_index_does_not_link_is_no_pointer(self):
        self.index.write_text(INDEX.replace("- [Acme pricing](acme-pricing.md) - resume from the thread note\n", ""))
        self.assertEqual("Acme, Pricing is parked", self.park())
        self.assertTrue((self.mem / "acme-pricing.md").is_file())

    def test_a_project_with_a_live_thread_keeps_its_hub_pointer(self):
        (self.mem / "acme.md").write_text(entry("Acme", "The hub is %s." % HUB))
        self.index.write_text(INDEX + "- [Acme](acme.md) - the hub\n")
        env = {k: v for k, v in self.env.items() if k != "GARRICK_CALLER_BUILDS_PAGE"}
        r = subprocess.run([sys.executable, str(self.root / "System" / "tools" / "scaffold.py"), "park", "--zone", "Work",
                            "--project", "Acme"], capture_output=True, text=True, env=env, cwd=str(self.root))
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue((self.mem / "acme.md").is_file())
        self.assertIn("acme.md", self.index.read_text())

    def test_the_lifecycle_says_finish_deletes_it_and_park_moves_it(self):
        text = (REPO / "template/System/skills/threads/reference/lifecycle.md").read_text()
        park = text.split("## Park:", 1)[1].split("## New:", 1)[0]
        self.assertIn("`parked/`", park)
        finish = text.split("## Finish:", 1)[1].split("## Park:", 1)[0]
        self.assertIn("Delete the memory pointer", finish)


class Light(unittest.TestCase):
    """The same moves on a small invented workspace with no install: fast, and room for the cases that must refuse."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "ws"
        for rel, status in (("Zones/Work/Acme/Acme.md", "parked"), ("Zones/Work/Acme/Threads/Pricing/Pricing.md", "active"),
                            ("Zones/Work/Birch/Threads/Rates/Rates.md", "parked")):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("---\nstatus: %s\n---\n\nbody\n" % status)
        (self.root / "Zones/Work/Birch/Birch.md").write_text("---\nstatus: active\n---\n")
        (self.root / "System").mkdir(exist_ok=True)
        self.mem = self.base / "memory"
        self.mem.mkdir()
        self.settings(str(self.mem))
        self.rates = "Zones/Work/Birch/Threads/Rates/Rates.md"
        self.index = self.mem / "MEMORY.md"
        self.index.write_text("# Index\n\n- [Rates](rates.md) - resume\n- [Pricing](pricing.md) - resume\n")
        (self.mem / "rates.md").write_text("Resume from %s.\n" % self.rates)
        (self.mem / "pricing.md").write_text("Resume from Zones/Work/Acme/Threads/Pricing/Pricing.md.\n")

    def tearDown(self):
        self.tmp.cleanup()

    def settings(self, folder):
        (self.root / "System" / "garrick-checks.json").write_text(json.dumps({"memory": folder}))

    def test_a_live_thread_of_a_parked_project_is_not_listed_as_leaving(self):
        report = lib.memory_index_report(self.root, self.mem)
        self.assertEqual(["rates.md"], [f for f, _ in report["leaving"]])

    def test_a_folder_that_is_a_link_into_another_zone_is_not_read_as_this_zones_work(self):
        (self.root / "Zones/Personal/Home/Threads/Roof/Roof.md").parent.mkdir(parents=True)
        (self.root / "Zones/Personal/Home/Threads/Roof/Roof.md").write_text("---\nstatus: parked\n---\n")
        os.symlink("../Personal/Home", str(self.root / "Zones/Work/Linked"))
        self.assertEqual([], [n for n in lib.work_notes(self.root) if n.startswith("Zones/Work/Linked")])
        self.assertIn("Zones/Personal/Home/Threads/Roof/Roof.md", lib.work_notes(self.root))
        (self.mem / "roof.md").write_text("Zones/Work/Linked/Threads/Roof/Roof.md\n")
        self.index.write_text(self.index.read_text() + "- [Roof](roof.md) - x\n")
        self.assertEqual("", lib.park_memory_pointer(self.root, "Zones/Work/Linked/Threads/Roof/Roof.md"))
        self.assertTrue((self.mem / "roof.md").is_file())
        self.assertNotIn("roof.md", [f for f, _ in lib.memory_index_report(self.root, self.mem)["leaving"]])

    def test_a_link_that_leaves_the_workspace_may_stay(self):
        outside = self.base / "elsewhere" / "Threads" / "Far"
        outside.mkdir(parents=True)
        (outside / "Far.md").write_text("---\nstatus: parked\n---\n")
        os.symlink(str(self.base / "elsewhere"), str(self.root / "Zones/Work/Away"))
        self.assertIn("Zones/Work/Away/Threads/Far/Far.md", lib.work_notes(self.root))

    def test_an_index_that_is_a_link_holds_and_writes_nothing(self):
        real = self.base / "real-index.md"
        real.write_text(self.index.read_text())
        self.index.unlink()
        os.symlink(str(real), str(self.index))
        before = real.read_text()
        said = lib.park_memory_pointer(self.root, self.rates)
        self.assertIn("not moved", said)
        self.assertEqual(before, real.read_text())
        self.assertTrue((self.mem / "rates.md").is_file())
        self.assertFalse((self.mem / "parked").exists())

    def test_a_parked_folder_that_is_a_link_holds(self):
        elsewhere = self.base / "else"
        elsewhere.mkdir()
        os.symlink(str(elsewhere), str(self.mem / "parked"))
        self.assertIn("not moved", lib.park_memory_pointer(self.root, self.rates))
        self.assertEqual([], list(elsewhere.iterdir()))
        self.assertTrue((self.mem / "rates.md").is_file())

    def test_a_memory_folder_inside_the_workspace_moves_nothing_and_says_so(self):
        for inside in ("Zones/Work/memory", "Wikis/memory", "System/memory", ""):
            folder = self.root / inside if inside else self.root
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "MEMORY.md").write_text(self.index.read_text())
            (folder / "rates.md").write_text("Resume from %s.\n" % self.rates)
            self.settings(str(folder))
            self.assertEqual("Its memory pointer was not moved: the memory folder is inside the workspace.",
                             lib.park_memory_pointer(self.root, self.rates), inside)
            self.assertTrue((folder / "rates.md").is_file())
            self.assertFalse((folder / "parked").exists())

    def test_a_kept_line_with_a_line_break_is_not_put_back(self):
        self.assertIn("set aside", lib.park_memory_pointer(self.root, self.rates))
        side = self.mem / "parked" / "rates.md.index-line"
        side.write_text(json.dumps({"line": "- [Rates](rates.md)\n- [Evil](evil.md)", "heading": "", "after": "", "offset": 0}))
        before = self.index.read_text()
        self.assertIn("not moved", lib.park_memory_pointer(self.root, self.rates, wake=True))
        self.assertEqual(before, self.index.read_text())
        self.assertTrue((self.mem / "parked" / "rates.md").is_file())


class TheSkill(unittest.TestCase):
    """The threads skill's words: a skill is read by an assistant, so what it must say is held here as text."""

    def test_no_match_names_the_nearest_live_thread_and_then_a_parked_one_with_parked_after_it(self):
        text = (REPO / "template/System/skills/threads/SKILL.md").read_text()
        step = text.split("6. **None:", 1)[1].split("7. **Learn it.**", 1)[0]
        flat = " ".join(step.split())
        self.assertIn('nearest live threads and the nearest parked one**, marked "parked"', flat)
        self.assertIn("No thread called roofing. Closest: roofing quotes; roof repair is parked.", flat)
        lifecycle = " ".join((REPO / "template/System/skills/threads/reference/lifecycle.md").read_text().split())
        self.assertIn("A parked thread of another walled zone is never named, and nothing says that one exists", lifecycle)

    def test_the_skill_names_no_assistant(self):
        for path in (REPO / "template/System/skills/threads").rglob("*.md"):
            self.assertNotRegex(path.read_text(), r"(?i)claude code|codex")


if __name__ == "__main__":
    unittest.main()
