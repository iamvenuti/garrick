"""#604: a project need not start with a thread, and each thread chooses whether it keeps its own papers.

Part 1, making a project. Run from the tests folder: `python3 -m unittest test_layout`.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import build_workspace, write  # noqa: E402
from test_setup import Installed  # noqa: E402

import check  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = load("garrick_status_layout", REPO / "extras" / "status" / "status.py")
pa = load("garrick_page_action_layout", REPO / "extras" / "status" / "page_action.py")
nu = load("garrick_next_up_layout", TOOLS / "next_up.py")
br = load("garrick_briefing_layout", TOOLS / "briefing.py")


class LayoutCase(Installed):
    def setUp(self):
        super().setUp()
        self.work = self.root / "Zones" / "Work"

    def scaffold(self, *args):
        return self.run_tool("scaffold.py", *args)

    def make(self, *args):
        r = self.scaffold(*args)
        self.assertEqual(0, r.returncode, r.stderr)
        return r

    def hub_text(self, project):
        return (self.work / project / (project + ".md")).read_text(encoding="utf-8")

    def findings(self, name=None):
        return [f for f in check.run_checks(self.root) if name is None or f.check == name]


class TestMakingAProject(LayoutCase):
    def test_no_thread_makes_one_piece_of_work(self):
        self.make("project", "--zone", "Work", "--name", "Acme")
        folder = self.work / "Acme"
        text = self.hub_text("Acme")
        self.assertIn("### Resume here", text)
        self.assertNotIn("layout:", text)
        self.assertTrue((folder / "Sources").is_dir())
        self.assertTrue((folder / "Deliverables").is_dir())
        self.assertFalse((folder / "Threads").exists())
        self.assertNotIn("<what it produces>", text)
        self.assertEqual([], [f for f in self.findings("projects") if f.path.endswith("Acme")])

    def test_a_heading_has_no_resume_point_and_no_papers(self):
        self.make("project", "--zone", "Work", "--name", "Birch", "--heading")
        folder = self.work / "Birch"
        text = self.hub_text("Birch")
        self.assertIn("layout: thread-first", text)
        self.assertNotIn("### Resume here", text)
        self.assertFalse((folder / "Sources").exists())
        self.assertFalse((folder / "Deliverables").exists())
        self.assertFalse((folder / "Threads").exists())
        self.assertEqual([], [f for f in self.findings() if "Birch" in f.path and f.check in ("projects", "threads")])

    def test_a_piece_of_work_with_no_resume_point_still_warns(self):
        self.make("project", "--zone", "Work", "--name", "Acme")
        hub = self.work / "Acme" / "Acme.md"
        hub.write_text(hub.read_text().replace("### Resume here", "### Notes"))
        self.assertTrue([f for f in self.findings("projects") if "no threads" in f.message])

    def test_with_a_thread_it_is_as_it_was(self):
        self.make("project", "--zone", "Work", "--name", "Cedar", "--thread", "Pricing")
        text = self.hub_text("Cedar")
        self.assertNotIn("### Resume here", text)
        self.assertIn("[[Cedar/Threads/Pricing/Pricing|Pricing]]", text)
        self.assertTrue((self.work / "Cedar" / "Threads" / "Pricing" / "Pricing.md").is_file())
        self.assertTrue((self.work / "Cedar" / "Sources").is_dir())
        self.assertTrue((self.work / "Cedar" / "Deliverables").is_dir())

    def test_a_heading_may_start_with_a_thread(self):
        self.make("project", "--zone", "Work", "--name", "Maple", "--heading", "--thread", "Pricing")
        self.assertIn("layout: thread-first", self.hub_text("Maple"))
        self.assertTrue((self.work / "Maple" / "Threads" / "Pricing" / "Pricing.md").is_file())

    def test_check_writes_nothing(self):
        r = self.make("project", "--zone", "Work", "--name", "Harbour", "--heading", "--check")
        self.assertIn("a heading over separate pieces of work", r.stdout)
        self.assertFalse((self.work / "Harbour").exists())

    def test_a_first_thread_name_alone_is_refused_when_it_is_not_given(self):
        r = self.scaffold("project", "--zone", "Work", "--name", "Dana", "--thread-spoken", "pricing")
        self.assertEqual(1, r.returncode)


class TestMakingAThread(LayoutCase):
    def setUp(self):
        super().setUp()
        self.make("project", "--zone", "Work", "--name", "Acme")
        self.make("project", "--zone", "Work", "--name", "Birch", "--heading")

    def thread_dir(self, project, name):
        return self.work / project / "Threads" / name

    def test_a_thread_in_a_piece_of_work_uses_the_projects_papers(self):
        self.make("thread", "--zone", "Work", "--project", "Acme", "--name", "Pricing")
        folder = self.thread_dir("Acme", "Pricing")
        self.assertTrue((folder / "Pricing.md").is_file())
        self.assertFalse((folder / "Sources").exists())
        self.assertFalse((folder / "Deliverables").exists())
        self.assertTrue((self.work / "Acme" / "Deliverables").is_dir())

    def test_its_own_papers_make_both_folders(self):
        r = self.make("thread", "--zone", "Work", "--project", "Acme", "--name", "Side Deal", "--papers", "own")
        self.assertIn("It keeps its own papers.", r.stdout)
        folder = self.thread_dir("Acme", "Side Deal")
        self.assertTrue((folder / "Sources").is_dir())
        self.assertTrue((folder / "Deliverables").is_dir())
        self.assertEqual([], [f for f in self.findings() if "Acme" in f.path and f.check in ("projects", "threads")])

    def test_a_heading_asks_nothing_and_gives_every_thread_its_own_papers(self):
        self.make("thread", "--zone", "Work", "--project", "Birch", "--name", "Pricing")
        folder = self.thread_dir("Birch", "Pricing")
        self.assertTrue((folder / "Sources").is_dir())
        self.assertTrue((folder / "Deliverables").is_dir())
        self.make("thread", "--zone", "Work", "--project", "Birch", "--name", "Freight", "--papers", "own")
        self.assertTrue((self.thread_dir("Birch", "Freight") / "Deliverables").is_dir())
        r = self.scaffold("thread", "--zone", "Work", "--project", "Birch", "--name", "Cargo", "--papers", "project")
        self.assertEqual(1, r.returncode)
        self.assertIn("keeps its own papers", r.stderr)
        self.assertFalse(self.thread_dir("Birch", "Cargo").exists())
        self.assertEqual([], [f for f in self.findings() if "Birch" in f.path and f.check in ("projects", "threads")])

    def test_check_says_it_and_writes_nothing(self):
        r = self.make("thread", "--zone", "Work", "--project", "Acme", "--name", "Side Deal", "--papers", "own", "--check")
        self.assertIn("keeps its own papers", r.stdout)
        self.assertFalse(self.thread_dir("Acme", "Side Deal").exists())

    def test_a_project_made_with_a_thread_in_a_heading_gives_it_papers(self):
        self.make("project", "--zone", "Work", "--name", "Maple", "--heading", "--thread", "Pricing")
        self.assertTrue((self.thread_dir("Maple", "Pricing") / "Sources").is_dir())

    def test_a_papers_word_that_is_neither_is_refused(self):
        r = self.scaffold("thread", "--zone", "Work", "--project", "Acme", "--name", "Pricing", "--papers", "both")
        self.assertNotEqual(0, r.returncode)


HUB_BLOCK = ("\n## State of play\n\n### Resume here\n\n**Where it stands, 1 March 2026.** The main line goes on here.\n\n"
             "| | |\n|---|---|\n| Next action | send the draft |\n| Waiting on | nobody |\n")
OUTCOME = "\n## State of play\n\n### Outcome\n\nDelivered and accepted.\n"


class HubBesideThreads(unittest.TestCase):
    """The hub's `### Resume here` stays a resume point while the project has threads, and `### Outcome`
    in its place ends it. A heading never has one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        write(self.root / "System" / "rules.md", "# Rules\n")
        for tool in ("next_up.py", "garrick_lib.py", "briefing.py"):
            write(self.root / "System" / "tools" / tool, (TOOLS / tool).read_text(encoding="utf-8"))
        self.work = self.root / "Zones" / "Work"
        self.hub = self.work / "Acme Review" / "Acme Review.md"

    def tearDown(self):
        self._tmp.cleanup()

    def keep(self, block):
        self.hub.write_text(self.hub.read_text(encoding="utf-8") + block, encoding="utf-8")

    def next_up_rows(self):
        return [(r["project"], r["thread"]) for r in nu.threads(self.root) if r["project"] == "Acme Review"]

    def briefing_rows(self):
        return [(r["project"], r["thread"]) for r in br.notes(self.work) if r["project"] == "Acme Review"]

    def test_the_hub_is_a_row_beside_its_threads_while_it_keeps_a_resume_point(self):
        before = self.next_up_rows()
        self.assertTrue(before and all(t for _, t in before), before)
        self.keep(HUB_BLOCK)
        for rows in (self.next_up_rows(), self.briefing_rows()):
            self.assertIn(("Acme Review", None), rows)
            self.assertTrue([r for r in rows if r[1]], "its threads are still there")

    def test_an_outcome_in_its_place_ends_it(self):
        self.keep(OUTCOME)
        self.assertNotIn(("Acme Review", None), self.next_up_rows())
        self.assertNotIn(("Acme Review", None), self.briefing_rows())

    def test_a_heading_never_has_one(self):
        self.hub.write_text(self.hub.read_text(encoding="utf-8").replace("status: active", "status: active\nlayout: thread-first"),
                            encoding="utf-8")
        self.keep(HUB_BLOCK)
        self.assertNotIn(("Acme Review", None), self.next_up_rows())
        self.assertNotIn(("Acme Review", None), self.briefing_rows())

    def test_a_parked_project_offers_its_hub_as_one_parked_row_and_no_more(self):
        self.hub.write_text(self.hub.read_text(encoding="utf-8").replace("status: active", "status: parked"), encoding="utf-8")
        self.keep(HUB_BLOCK)
        self.assertEqual([("Acme Review", None)], [r for r in self.next_up_rows() if r[1] is None])
        self.assertEqual(1, len(self.next_up_rows()))

    def test_the_briefing_reads_the_hub_without_the_threads_commits(self):
        self.keep(HUB_BLOCK)
        row = next(r for r in br.notes(self.work) if r["thread"] is None and r["project"] == "Acme Review")
        self.assertEqual("Threads", row["skip"])

    def test_your_work_shows_both(self):
        self.keep(HUB_BLOCK)
        T = status.threads(self.root)
        self.assertEqual(["Acme Review"], [h["project"] for h in T["Work"]["hubs"]])
        self.assertNotIn("Acme Review", [r["thread"] for r in T["Work"]["rows"]])    # the Threads card is as it was
        status.thread_actions(T, [], None, self.root)
        names = [w["name"] for w in status.works(self.root, T, dt.date(2026, 3, 2)) if w["project"] == "Acme Review"]
        self.assertIn("Acme Review", names)
        self.assertTrue([n for n in names if n.startswith("Acme Review, ")], names)

    def test_your_work_shows_only_the_threads_after_an_outcome(self):
        self.keep(OUTCOME)
        T = status.threads(self.root)
        self.assertEqual([], T["Work"]["hubs"])
        status.thread_actions(T, [], None, self.root)
        names = [w["thread"] for w in status.works(self.root, T, dt.date(2026, 3, 2)) if w["project"] == "Acme Review"]
        self.assertNotIn("Acme Review", names)          # no row for the hub: the one thread's row is the work

    def test_one_thread_beside_a_hub_is_named_with_its_project(self):
        self.keep(HUB_BLOCK)
        zone = self.work
        for t in list((zone / "Acme Review" / "Threads").iterdir())[1:]:
            import shutil
            shutil.rmtree(t)
        only = next(p.name for p in (zone / "Acme Review" / "Threads").iterdir())
        self.assertEqual("Acme Review, %s" % only, pa.work_name(zone, ("Acme Review", "Threads", only, only + ".md")))
        self.hub.write_text(self.hub.read_text(encoding="utf-8").replace("### Resume here", "### Outcome"), encoding="utf-8")
        self.assertEqual("Acme Review", pa.work_name(zone, ("Acme Review", "Threads", only, only + ".md")))


    def test_an_empty_heading_is_no_piece_of_work(self):
        write(self.work / "Cedar" / "Cedar.md", "---\ntitle: Cedar\ntype: project\nzone: Work\nstatus: active\nlayout: thread-first\n"
                                              "created: 2026-03-01\nupdated: 2026-03-01\n---\n\n# Cedar\n")
        self.assertEqual([], [r for r in nu.threads(self.root) if r["project"] == "Cedar"])
        self.assertEqual([], [r for r in br.notes(self.work) if r["project"] == "Cedar"])
        T = status.threads(self.root)
        self.assertEqual([], [r for r in T["Work"]["rows"] + T["Work"]["parked"] if r["project"] == "Cedar"])
        self.assertTrue(T["Work"]["projects"]["Cedar"]["heading"])
        self.hub.parent.parent.joinpath("Cedar", "Cedar.md").write_text(
            "---\ntitle: Cedar\ntype: project\nzone: Work\nstatus: active\ncreated: 2026-03-01\nupdated: 2026-03-01\n---\n\n# Cedar\n")
        self.assertEqual(1, len([r for r in nu.threads(self.root) if r["project"] == "Cedar"]))       # one piece of work still is


if __name__ == "__main__":
    unittest.main()
