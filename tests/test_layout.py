"""#604, #632: a project need not start with a thread, and is one job or separate jobs: every thread follows the project.

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
import garrick_lib as gl  # noqa: E402


REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"


HUB_BLOCK = ("\n## State of play\n\n### Resume here\n\n**Where it stands, 1 March 2026.** The main line goes on here.\n\n"
             "| | |\n|---|---|\n| Next action | send the draft |\n| Waiting on | nobody |\n")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = load("garrick_status_layout", REPO / "extras" / "status" / "status.py")
pa = load("garrick_page_action_layout", REPO / "extras" / "status" / "page_action.py")
sc = load("garrick_scaffold_layout", TOOLS / "scaffold.py")
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
    def test_no_thread_makes_one_job(self):
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

    def test_separate_jobs_have_no_resume_point_and_no_papers(self):
        self.make("project", "--zone", "Work", "--name", "Birch", "--separate")
        folder = self.work / "Birch"
        text = self.hub_text("Birch")
        self.assertIn("layout: thread-first", text)
        self.assertNotIn("### Resume here", text)
        self.assertFalse((folder / "Sources").exists())
        self.assertFalse((folder / "Deliverables").exists())
        self.assertFalse((folder / "Threads").exists())
        self.assertEqual([], [f for f in self.findings() if "Birch" in f.path and f.check in ("projects", "threads")])

    def test_a_heading_written_in_capitals_is_a_heading_to_check_too(self):
        self.make("project", "--zone", "Work", "--name", "Cedar")
        hub = self.work / "Cedar" / "Cedar.md"
        text = hub.read_text(encoding="utf-8")
        hub.write_text(text.replace("---\n\n", "layout: Thread-First\n---\n\n", 1).replace("### Resume here", "### Notes"), encoding="utf-8")
        self.assertIn("layout: Thread-First", hub.read_text(encoding="utf-8"))
        self.assertEqual([], [f for f in self.findings("projects") if "Cedar" in f.path and "no threads" in f.message])

    def test_one_job_with_no_resume_point_still_warns(self):
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

    def test_separate_jobs_may_start_with_a_thread_and_the_old_flag_still_says_it(self):
        self.make("project", "--zone", "Work", "--name", "Maple", "--heading", "--thread", "Pricing")
        self.assertIn("layout: thread-first", self.hub_text("Maple"))
        self.assertTrue((self.work / "Maple" / "Threads" / "Pricing" / "Pricing.md").is_file())

    def test_check_writes_nothing(self):
        r = self.make("project", "--zone", "Work", "--name", "Harbour", "--separate", "--check")
        self.assertIn("as separate jobs", r.stdout)
        self.assertFalse((self.work / "Harbour").exists())

    def test_a_first_thread_name_alone_is_refused_when_it_is_not_given(self):
        r = self.scaffold("project", "--zone", "Work", "--name", "Dana", "--thread-spoken", "pricing")
        self.assertEqual(1, r.returncode)


class TestMakingAThread(LayoutCase):
    def setUp(self):
        super().setUp()
        self.make("project", "--zone", "Work", "--name", "Acme")
        self.make("project", "--zone", "Work", "--name", "Birch", "--separate")

    def thread_dir(self, project, name):
        return self.work / project / "Threads" / name

    def test_a_thread_in_one_job_uses_the_projects_papers(self):
        r = self.make("thread", "--zone", "Work", "--project", "Acme", "--name", "Pricing")
        self.assertNotIn("papers", r.stdout)
        folder = self.thread_dir("Acme", "Pricing")
        self.assertTrue((folder / "Pricing.md").is_file())
        self.assertFalse((folder / "Sources").exists())
        self.assertFalse((folder / "Deliverables").exists())
        self.assertTrue((self.work / "Acme" / "Deliverables").is_dir())

    def test_a_thread_in_separate_jobs_keeps_its_own_papers_and_is_asked_nothing(self):
        self.make("thread", "--zone", "Work", "--project", "Birch", "--name", "Pricing")
        folder = self.thread_dir("Birch", "Pricing")
        self.assertTrue((folder / "Sources").is_dir())
        self.assertTrue((folder / "Deliverables").is_dir())
        self.assertEqual([], [f for f in self.findings() if "Birch" in f.path and f.check in ("projects", "threads")])

    def test_a_papers_choice_of_the_thread_is_refused_with_the_sentence_that_names_the_switch(self):
        for project in ("Acme", "Birch"):
            for papers in ("own", "project", "both"):
                for extra in ((), ("--check",)):
                    r = self.scaffold("thread", "--zone", "Work", "--project", project, "--name", "Cargo", "--papers", papers, *extra)
                    self.assertEqual(1, r.returncode, (project, papers, extra))
                    self.assertIn("one job or separate jobs", r.stderr)
                    self.assertFalse(self.thread_dir(project, "Cargo").exists())

    def test_check_says_it_and_writes_nothing(self):
        r = self.make("thread", "--zone", "Work", "--project", "Birch", "--name", "Side Deal", "--check")
        self.assertIn("keeps its own papers", r.stdout)
        self.assertFalse(self.thread_dir("Birch", "Side Deal").exists())
        r = self.make("thread", "--zone", "Work", "--project", "Acme", "--name", "Side Deal", "--check")
        self.assertNotIn("papers", r.stdout)

    def test_a_project_made_with_a_thread_in_separate_jobs_gives_it_papers(self):
        self.make("project", "--zone", "Work", "--name", "Maple", "--separate", "--thread", "Pricing")
        self.assertTrue((self.thread_dir("Maple", "Pricing") / "Sources").is_dir())


OUTCOME = "\n## State of play\n\n### Outcome\n\nDelivered and accepted.\n"


class LayoutFiles(LayoutCase):
    """A project's files and a git helper, for the cases that switch a layout."""

    def git(self, *args):
        import subprocess
        return subprocess.run(["git", *args], cwd=str(self.work), capture_output=True, text=True, env=self.env)

    def commit(self, message):
        self.git("add", "-A")
        r = self.git("commit", "-q", "-m", message)
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)

    def commits(self):
        return int(self.git("rev-list", "--count", "HEAD").stdout)

    def snapshot(self, project="Acme"):
        return {str(p.relative_to(self.work)): p.read_bytes() for p in (self.work / project).rglob("*") if p.is_file()}

    def layout(self, *args, project="Acme"):
        return self.scaffold("layout", "--zone", "Work", "--project", project, *args)


class TestLayout(LayoutFiles):
    """scaffold.py layout --split: a project made separate jobs, files carried with their ledger rows and links."""

    DECK = "260101 - Pricing deck.pptx"
    SHEET = "260102 - Freight sheet.xlsx"
    BRIEF = "brief.txt"
    MISC = "260103 - Misc.docx"

    def setUp(self):
        super().setUp()
        self.make("project", "--zone", "Work", "--name", "Acme")
        for t in ("Pricing", "Freight"):
            self.make("thread", "--zone", "Work", "--project", "Acme", "--name", t)
        a = self.work / "Acme"
        (a / "Deliverables" / self.DECK).write_bytes(b"deck")
        (a / "Deliverables" / self.SHEET).write_bytes(b"sheet")
        (a / "Deliverables" / self.MISC).write_bytes(b"misc")
        (a / "Sources" / self.BRIEF).write_text("brief")
        pricing = a / "Threads" / "Pricing" / "Pricing.md"
        freight = a / "Threads" / "Freight" / "Freight.md"
        pricing.write_text(pricing.read_text() + "\nThe deck is [the deck](../../Deliverables/%s) and %s is the brief.\n"
                           % (self.DECK.replace(" ", "%20"), self.BRIEF))
        freight.write_text(freight.read_text() + "\nThe sheet is %s. The brief is %s.\n" % (self.SHEET, self.BRIEF))
        (a / "Deliverables" / "published.md").write_text(
            "# Published\n\n## What left\n\n| Date | File | Destination | Recipients | Authoritative |\n|---|---|---|---|---|\n"
            "| 2026-03-01 | `%s` | `acme/Decks/` | Dana | here |\n"
            "| 2026-03-02 | `%s` | `acme/Sheets/` | Dana | share, Dana edits it there |\n" % (self.DECK, self.SHEET))
        self.commit("Acme set up")

    def test_check_writes_nothing(self):
        before, count = self.snapshot(), self.commits()
        r = self.layout("--split", "--check")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn(self.DECK, r.stdout)
        self.assertIn("Nothing was changed.", r.stdout)
        self.assertEqual(before, self.snapshot())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertEqual(count, self.commits())

    def test_a_project_becomes_separate_jobs_and_each_file_goes_to_its_one_thread(self):
        count = self.commits()
        r = self.layout("--split")
        self.assertEqual(0, r.returncode, r.stderr)
        a = self.work / "Acme"
        self.assertIn("layout: thread-first", (a / "Acme.md").read_text())
        self.assertTrue((a / "Threads" / "Pricing" / "Deliverables" / self.DECK).is_file())
        self.assertTrue((a / "Threads" / "Freight" / "Deliverables" / self.SHEET).is_file())
        self.assertTrue((a / "Deliverables" / self.MISC).is_file())             # no thread names it: left for the owner
        self.assertTrue((a / "Sources" / self.BRIEF).is_file())                 # two threads name it
        for t in ("Pricing", "Freight"):
            self.assertTrue((a / "Threads" / t / "Sources").is_dir())
        self.assertIn(self.MISC, r.stdout)
        self.assertIn(self.BRIEF, r.stdout)
        self.assertIn("Resume here", r.stdout)
        self.assertIn(self.SHEET, (a / "Threads" / "Freight" / "Deliverables" / "published.md").read_text())
        self.assertEqual(count + 1, self.commits())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        names = [n for n in self.git("show", "--name-only", "--format=", "HEAD").stdout.split("\n") if n]
        self.assertTrue(names and all(n.startswith("Acme/") for n in names), names)           # the commit stays inside the project

    def test_a_working_file_a_split_gave_a_thread_stays_there_after_a_join_and_the_docs_say_so(self):
        a = self.work / "Acme"
        (a / "Notes").mkdir()
        (a / "Notes" / "x.md").write_text("working note")
        pricing = a / "Threads" / "Pricing" / "Pricing.md"
        pricing.write_text(pricing.read_text() + "\nSee Notes/x.md for the working.\n")
        self.commit("a working note, named by Pricing")
        r = self.layout("--split")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue((a / "Threads" / "Pricing" / "Notes" / "x.md").is_file())
        r = self.layout("--join")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue((a / "Threads" / "Pricing" / "Notes" / "x.md").is_file())       # Join moves papers only
        self.assertFalse((a / "Notes" / "x.md").exists())
        docs = (REPO / "docs" / "commands.md").read_text(encoding="utf-8")
        self.assertIn("A Join moves papers only", docs)

    def test_the_ledger_row_follows_its_file_and_its_destination_stays(self):
        self.layout("--split")
        a = self.work / "Acme"
        project_rows = (a / "Deliverables" / "published.md").read_text()
        thread_rows = (a / "Threads" / "Pricing" / "Deliverables" / "published.md").read_text()
        self.assertNotIn(self.DECK, project_rows)
        self.assertNotIn(self.SHEET, project_rows)
        self.assertIn("| 2026-03-01 | `%s` | `acme/Decks/` | Dana | here |" % self.DECK, thread_rows)
        self.assertIn("## What left", thread_rows)

    def test_the_links_follow(self):
        self.layout("--split")
        text = (self.work / "Acme" / "Threads" / "Pricing" / "Pricing.md").read_text()
        self.assertIn("(Deliverables/%s)" % self.DECK.replace(" ", "%20"), text)
        self.assertNotIn("../../Deliverables", text)

    def test_a_refused_commit_leaves_every_file_and_row_where_it_was(self):
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.write_text(hook.read_text().replace("exec python3", "echo 'refused by the fixture hook' >&2\nexit 1\nexec python3"))
        before, count = self.snapshot(), self.commits()
        r = self.layout("--split")
        self.assertEqual(1, r.returncode)
        self.assertIn("every file and ledger row is where it was", r.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertEqual(count, self.commits())

    def test_a_project_is_not_split_twice(self):
        self.layout("--split")
        r = self.layout("--split")
        self.assertEqual(1, r.returncode)
        self.assertIn("separate jobs already", r.stderr)

    def test_the_old_word_for_it_still_splits(self):
        r = self.layout("--heading")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("layout: thread-first", self.hub_text("Acme"))

    def test_a_dirty_project_is_refused(self):
        (self.work / "Acme" / "Sources" / "late.txt").write_text("late")
        r = self.layout("--split")
        self.assertEqual(1, r.returncode)
        self.assertFalse((self.work / "Acme" / "Threads" / "Pricing" / "Deliverables").exists())

    def test_nothing_runs_on_its_own_and_it_asks_for_one_switch(self):
        self.assertEqual(1, self.layout().returncode)
        r = self.layout("--split", "--join")
        self.assertEqual(1, r.returncode)
        self.assertIn("Say what changes", r.stderr)

    def test_a_thread_has_no_layout_and_no_papers_choice(self):
        for args in (("--split", "--thread", "Pricing"), ("--thread", "Pricing", "--papers", "own"),
                     ("--thread", "Pricing", "--papers", "project", "--check"), ("--split", "--papers", "own"),
                     ("--join", "--thread", "Freight")):
            r = self.layout(*args)
            self.assertEqual(1, r.returncode, args)
            self.assertIn("one job or separate jobs", r.stderr)
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertFalse((self.work / "Acme" / "Threads" / "Pricing" / "Deliverables").exists())

    def test_nothing_in_another_zone_is_read_or_written(self):
        # A walled zone with a project of the same name, a note that names the same file, and a ledger row for it.
        other = self.root / "Zones" / "Personal"
        for rel, text in (("Acme/Acme.md", "---\ntitle: Acme\ntype: project\nzone: Personal\nstatus: active\ncreated: 2026-11-20\n"
                                           "updated: 2026-11-20\n---\n\n# Acme\n\nSee %s.\n" % self.DECK),
                          ("Acme/Deliverables/%s" % self.DECK, "personal deck")):
            path = other / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        import subprocess
        subprocess.run(["git", "add", "-A"], cwd=str(other), env=self.env, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "Acme in Personal"], cwd=str(other), env=self.env, check=True)
        before = {str(p.relative_to(other)): p.read_bytes() for p in (other / "Acme").rglob("*") if p.is_file()}
        count = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=str(other), env=self.env, capture_output=True,
                               text=True).stdout
        r = self.layout("--split")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(before, {str(p.relative_to(other)): p.read_bytes() for p in (other / "Acme").rglob("*") if p.is_file()})
        self.assertEqual(count, subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=str(other), env=self.env,
                                               capture_output=True, text=True).stdout)
        self.assertNotIn("Personal", r.stdout)

    def test_the_page_verb_plans_and_does(self):
        import os
        os.environ["GARRICK_JOBS_DIR"] = str(self.base / "jobs")
        said = pa.act(self.root, {"verb": "layout", "zone": "Work", "project": "Acme", "heading": True, "check": True})
        self.assertIn(self.DECK, said)
        self.assertFalse((self.work / "Acme" / "Threads" / "Pricing" / "Deliverables").exists())
        said = pa.act(self.root, {"verb": "layout", "zone": "Work", "project": "Acme", "heading": True})
        self.assertIn("moved", said)
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing" / "Deliverables" / self.DECK).is_file())
        for bad in ({"thread": "Pricing", "heading": True}, {"papers": "own", "heading": True}, {"thread": "Pricing", "join": True},
                    {"papers": "both"}, {}, {"heading": True, "join": True}):
            with self.assertRaises(pa.Refused, msg=bad):
                pa.act(self.root, dict({"verb": "layout", "zone": "Work", "project": "Acme"}, **bad))

    def test_undo_takes_the_change_back(self):
        self.layout("--split")
        head = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        r = self.scaffold("undo", "--zone", "Work", "--commit", head)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue((self.work / "Acme" / "Deliverables" / self.DECK).is_file())
        self.assertNotIn("thread-first", self.hub_text("Acme"))

    def test_a_bare_name_does_not_match_another_folders_file_of_that_name(self):
        a = self.work / "Acme"
        (a / "Sources" / "Terms.docx").write_bytes(b"source terms")
        (a / "Deliverables" / "Terms.docx").write_bytes(b"deliverable terms")
        pricing = a / "Threads" / "Pricing" / "Pricing.md"
        pricing.write_text(pricing.read_text() + "\nThe terms are Deliverables/Terms.docx.\n")
        self.commit("terms")
        moves, left, _ = sc.plan_layout(self.work, a, split=True)
        self.assertIn(("Acme/Deliverables/Terms.docx", "Acme/Threads/Pricing/Deliverables/Terms.docx"), moves)
        self.assertNotIn("Acme/Sources/Terms.docx", [m[0] for m in moves])
        self.assertTrue(sc.names_file("see ../../Deliverables/x.pptx", "Sources/x.pptx", "x.pptx") is False)
        self.assertTrue(sc.names_file("see x.pptx.", "Sources/x.pptx", "x.pptx"))

    def test_a_target_that_exists_is_left_for_the_owner_not_promised(self):
        a = self.work / "Acme"
        for t in ("Pricing", "Freight"):
            for k in ("Sources", "Deliverables"):
                (a / "Threads" / t / k).mkdir(exist_ok=True)
        (a / "Threads" / "Pricing" / "Deliverables" / self.DECK).write_bytes(b"already")
        self.commit("target exists")
        r = self.layout("--split", "--check")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("the thread has a file of that name already", r.stdout)
        self.assertNotIn("%s to Threads" % self.DECK, r.stdout)
        r = self.layout("--split")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(b"deck", (a / "Deliverables" / self.DECK).read_bytes())
        self.assertEqual(b"already", (a / "Threads" / "Pricing" / "Deliverables" / self.DECK).read_bytes())

    def test_a_note_that_is_a_symlink_is_never_written_through(self):
        outside = Path(tempfile.mkdtemp()) / "outside.md"
        outside.write_text("The deck is Deliverables/%s here.\n" % self.DECK)
        link = self.work / "Acme" / "Link.md"
        link.symlink_to(outside)
        self.commit("a link")
        self.assertNotIn(link, list(sc.zone_notes(self.work)))
        self.layout("--split")
        self.assertEqual("The deck is Deliverables/%s here.\n" % self.DECK, outside.read_text())

    def test_a_hub_that_is_a_link_is_never_written_through(self):
        hub = self.work / "Acme" / "Acme.md"
        outside = Path(tempfile.mkdtemp()) / "Acme.md"
        outside.write_text(hub.read_text())
        before = outside.read_text()
        hub.unlink()
        hub.symlink_to(outside)
        self.commit("the hub as a link")
        r = self.layout("--split")
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("is a link", r.stdout + r.stderr)
        self.assertEqual(before, outside.read_text())
        self.assertTrue(hub.is_symlink())


class TestALinkedThreadFolder(LayoutFiles):
    """S7: a thread folder that is a link is no thread of the project; a layout change never acts through it."""

    def linked(self):
        self.make("project", "--zone", "Work", "--name", "Acme")
        self.make("thread", "--zone", "Work", "--project", "Acme", "--name", "Pricing")
        outside = self.base / "elsewhere" / "Linked"
        outside.mkdir(parents=True)
        (outside / "Linked.md").write_text("---\ntype: thread\n---\n")
        (outside / "Sources").mkdir()
        (outside / "Sources" / ".gitkeep").write_text("")
        (self.work / "Acme" / "Threads" / "Linked").symlink_to(outside, target_is_directory=True)
        self.commit("a linked thread folder")
        return outside

    def test_split_makes_no_folder_through_a_link(self):
        outside = self.linked()
        before = sorted(p.name for p in outside.rglob("*"))
        r = self.layout("--split")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(before, sorted(p.name for p in outside.rglob("*")))
        self.assertFalse((outside / "Deliverables").exists())

    def test_join_removes_nothing_through_a_link(self):
        outside = self.linked()
        (self.work / "Acme" / "Threads" / "Pricing" / "Sources").mkdir(exist_ok=True)
        (self.work / "Acme" / "Threads" / "Pricing" / "Sources" / "brief.txt").write_text("brief")
        self.commit("papers in a real thread")
        r = self.layout("--join")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue((outside / "Sources" / ".gitkeep").is_file())

    def test_the_link_is_not_listed_as_a_thread(self):
        self.linked()
        names = [t.name for t in sc.thread_dirs_of(self.work / "Acme")]
        self.assertEqual(["Pricing"], names)


class TestALinkedPapersFolder(LayoutFiles):
    """G26: a Split or a Join never moves a file through a link, or out of the project: it refuses and nothing moves."""

    def one_job(self):
        self.make("project", "--zone", "Work", "--name", "Acme")
        for t in ("Pricing", "Freight"):
            self.make("thread", "--zone", "Work", "--project", "Acme", "--name", t)
        a = self.work / "Acme"
        (a / "Sources" / "brief.txt").write_text("brief")
        note = a / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text() + "\nThe brief is Sources/brief.txt.\n")
        self.commit("one job")
        return a

    def separate(self):
        self.make("project", "--zone", "Work", "--name", "Acme", "--separate")
        for t in ("Pricing", "Freight"):
            self.make("thread", "--zone", "Work", "--project", "Acme", "--name", t)
        a = self.work / "Acme"
        (a / "Threads" / "Pricing" / "Sources" / "brief.txt").write_text("brief")
        (a / "Threads" / "Pricing" / "Deliverables" / "260101 - Deck.pptx").write_bytes(b"deck")
        (a / "Threads" / "Pricing" / "Sources" / "sub").mkdir()
        (a / "Threads" / "Pricing" / "Sources" / "sub" / "extra.txt").write_text("extra")
        self.commit("separate jobs")
        return a

    def other_zone(self):
        folder = self.root / "Zones" / "Personal" / "Stuff"
        folder.mkdir(parents=True)
        (folder / "keep.txt").write_text("keep")
        return folder

    def link(self, folder, outside, commit=True):
        """Replace a folder with a link. A link in the index holds none of the files that were under it, so a source
        folder is linked without a commit: git still lists its files, and a move would follow the link."""
        import shutil
        if folder.exists():
            if not commit:                                        # the files are there on the other side, so the link reads as the folder did
                shutil.copytree(folder, outside, dirs_exist_ok=True)
            shutil.rmtree(folder)
        folder.symlink_to(outside, target_is_directory=True)
        if not commit:
            return
        # The zone's hook refuses a link into another walled zone, so the fixture commits the way a workspace
        # that got the link in before the hook did would hold it.
        self.git("add", "-A")
        r = self.git("-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "a linked folder")
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)

    def held(self, *args, outside):
        before, other, count = self.snapshot(), sorted(p.name for p in outside.rglob("*")), self.commits()
        r = self.layout(*args)
        self.assertNotEqual(0, r.returncode)
        self.assertIn("link", r.stderr + r.stdout)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(other, sorted(p.name for p in outside.rglob("*")))
        self.assertEqual(count, self.commits())

    def test_a_join_into_a_project_deliverables_that_is_a_link_moves_nothing(self):
        a = self.separate()
        outside = self.other_zone()
        self.link(a / "Deliverables", outside)
        self.held("--join", outside=outside)
        self.held("--join", "--check", "--json", outside=outside)
        self.assertTrue((a / "Threads" / "Pricing" / "Deliverables" / "260101 - Deck.pptx").is_file())
        self.assertEqual(["keep.txt"], [p.name for p in outside.iterdir()])

    def test_a_split_into_a_thread_folder_that_is_a_link_moves_nothing(self):
        a = self.one_job()
        outside = self.other_zone()
        self.link(a / "Threads" / "Pricing" / "Sources", outside)
        self.held("--split", outside=outside)
        self.assertTrue((a / "Sources" / "brief.txt").is_file())

    def test_a_split_of_a_project_papers_folder_that_is_a_link_moves_nothing(self):
        a = self.one_job()
        outside = self.other_zone()
        self.link(a / "Sources", outside, commit=False)
        self.held("--split", outside=outside)

    def test_a_join_of_a_thread_sources_that_is_a_link_moves_nothing(self):
        a = self.separate()
        outside = self.other_zone()
        self.link(a / "Threads" / "Pricing" / "Sources", outside, commit=False)
        self.held("--join", outside=outside)
        self.assertTrue((a / "Threads" / "Pricing" / "Deliverables" / "260101 - Deck.pptx").is_file())

    def test_a_join_through_a_link_inside_a_papers_folder_moves_nothing(self):
        a = self.separate()
        outside = self.other_zone()
        self.link(a / "Threads" / "Pricing" / "Sources" / "sub", outside, commit=False)
        self.held("--join", outside=outside)
        self.assertTrue((a / "Threads" / "Pricing" / "Sources" / "brief.txt").is_file())

    def test_the_check_names_a_path_through_a_link_and_one_inside_the_project_is_clean(self):
        a = self.separate()
        outside = self.other_zone()
        self.assertFalse(sc.through_a_link(a, a / "Threads" / "Pricing" / "Sources" / "brief.txt"))
        self.assertFalse(sc.through_a_link(a, a / "Deliverables" / "new.txt"))
        self.assertTrue(sc.through_a_link(a, outside / "keep.txt"))
        self.link(a / "Deliverables", outside)
        self.assertTrue(sc.through_a_link(a, a / "Deliverables" / "new.txt"))


class TestJoin(LayoutFiles):
    """scaffold.py layout --join: separate jobs made one job, the threads' papers moved up, and the switch back."""

    DECK = "260101 - Pricing deck.pptx"
    SHEET = "260102 - Freight sheet.xlsx"
    BRIEF = "brief.txt"
    NOTES = "notes.txt"

    def setUp(self):
        super().setUp()
        self.make("project", "--zone", "Work", "--name", "Acme", "--separate")
        for t in ("Pricing", "Freight"):
            self.make("thread", "--zone", "Work", "--project", "Acme", "--name", t)
        a = self.work / "Acme"
        self.p, self.f = a / "Threads" / "Pricing", a / "Threads" / "Freight"
        (self.p / "Deliverables" / self.DECK).write_bytes(b"deck")
        (self.f / "Deliverables" / self.SHEET).write_bytes(b"sheet")
        (self.p / "Sources" / self.BRIEF).write_text("pricing brief")
        (self.p / "Sources" / self.NOTES).write_text("notes")
        pricing = self.p / "Pricing.md"
        freight = self.f / "Freight.md"
        pricing.write_text(self.note_with(pricing, "send the pricing deck to Dana", "2026-03-01")
                           + "\nThe deck is [the deck](Deliverables/%s).\n" % self.DECK.replace(" ", "%20"))
        freight.write_text(self.note_with(freight, "chase the freight sheet", "2026-03-09"))
        (self.p / "Deliverables" / "published.md").write_text(
            "# Published\n\n## What left\n\n| Date | File | Destination | Recipients | Authoritative |\n|---|---|---|---|---|\n"
            "| 2026-03-01 | `%s` | `acme/Decks/` | Dana | here |\n" % self.DECK)
        (self.f / "Deliverables" / "published.md").write_text(
            "# Published\n\n## What left\n\n| Date | File | Destination | Recipients | Authoritative |\n|---|---|---|---|---|\n"
            "| 2026-03-02 | `%s` | `acme/Sheets/` | Dana | share, Dana edits it there |\n" % self.SHEET)
        self.commit("Acme set up")

    @staticmethod
    def note_with(path, action, updated):
        import re
        text = path.read_text()
        text = re.sub(r"(?m)^\| Next action \|.*$", "| Next action | %s |" % action, text, count=1)
        return re.sub(r"(?m)^updated: .*$", "updated: %s" % updated, text, count=1)

    def test_the_plan_writes_nothing_and_offers_each_threads_next_action_with_the_latest_touched_chosen(self):
        import json
        before, count = self.snapshot(), self.commits()
        r = self.layout("--join", "--check", "--json")
        self.assertEqual(0, r.returncode, r.stderr)
        plan = json.loads(r.stdout)
        self.assertEqual("Freight", plan["resume_from"])
        self.assertEqual([["Freight", "chase the freight sheet"], ["Pricing", "send the pricing deck to Dana"]], plan["next_actions"])
        self.assertTrue(plan["join"] and plan["opens_resume"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(count, self.commits())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        said = self.layout("--join", "--check").stdout
        self.assertIn("Nothing was changed.", said)
        self.assertIn("Next action of Freight", said)

    def test_it_moves_each_threads_papers_up_with_rows_and_links_in_one_commit(self):
        count = self.commits()
        r = self.layout("--join")
        self.assertEqual(0, r.returncode, r.stderr)
        a = self.work / "Acme"
        self.assertTrue((a / "Deliverables" / self.DECK).is_file())
        self.assertTrue((a / "Deliverables" / self.SHEET).is_file())
        self.assertTrue((a / "Sources" / self.NOTES).is_file())
        for t in ("Pricing", "Freight"):
            self.assertFalse((a / "Threads" / t / "Sources").exists(), t)
            self.assertFalse((a / "Threads" / t / "Deliverables").exists(), t)
        rows = (a / "Deliverables" / "published.md").read_text()
        self.assertIn("| 2026-03-01 | `%s` | `acme/Decks/` | Dana | here |" % self.DECK, rows)
        self.assertIn("| 2026-03-02 | `%s` | `acme/Sheets/` | Dana | share, Dana edits it there |" % self.SHEET, rows)
        self.assertIn("../../Deliverables/%s" % self.DECK.replace(" ", "%20"), (self.p / "Pricing.md").read_text())
        self.assertNotIn("layout:", self.hub_text("Acme"))
        self.assertEqual(count + 1, self.commits())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        names = [n for n in self.git("show", "--name-only", "--format=", "HEAD").stdout.split("\n") if n]
        self.assertTrue(names and all(n.startswith("Acme/") for n in names), names)
        self.assertEqual([], [f for f in self.findings() if "Acme" in f.path and f.check in ("projects", "threads")])

    def test_the_hub_gets_a_resume_block_that_opens_with_the_chosen_threads_next_action(self):
        self.layout("--join")
        text = self.hub_text("Acme")
        self.assertIn("### Resume here", text)
        self.assertIn("| Next action | chase the freight sheet |", text)           # the thread touched last
        self.assertIn("| Next action | send the pricing deck to Dana |", (self.p / "Pricing.md").read_text())   # the others stay as they are
        self.assertIn("| Next action | chase the freight sheet |", (self.f / "Freight.md").read_text())
        self.assertIn("| `Sources/` |", text)
        self.assertIn("| `Deliverables/` |", text)

    def test_the_user_can_choose_which_threads_next_action_opens_it(self):
        r = self.layout("--join", "--resume-from", "Pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("| Next action | send the pricing deck to Dana |", self.hub_text("Acme"))
        r = self.layout("--join", "--resume-from", "Nobody", "--check")
        self.assertEqual(1, r.returncode)

    def test_a_name_already_taken_moves_nothing_for_that_file_and_is_listed(self):
        (self.f / "Sources" / self.BRIEF).write_text("freight brief")             # the same name in two threads
        self.commit("the same name in two threads")
        r = self.layout("--join")
        self.assertEqual(0, r.returncode, r.stderr)
        a = self.work / "Acme"
        # brief.txt is in both threads: the first claims the name, the second is listed, never renamed or overwritten.
        left = [t for t in ("Pricing", "Freight") if (a / "Threads" / t / "Sources" / self.BRIEF).exists()]
        self.assertEqual(1, len(left))
        self.assertTrue((a / "Sources" / self.BRIEF).is_file())
        self.assertIn(self.BRIEF, r.stdout)
        self.assertIn("the project has a file of that name already", r.stdout)
        self.assertEqual([], [p.name for p in (a / "Sources").iterdir() if p.name not in (self.BRIEF, self.NOTES, ".gitkeep")])

    def test_a_file_the_project_already_has_is_never_overwritten(self):
        a = self.work / "Acme"
        (a / "Sources").mkdir(exist_ok=True)
        (a / "Sources" / self.NOTES).write_text("the project's own notes")
        self.commit("the project has notes")
        r = self.layout("--join")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("the project's own notes", (a / "Sources" / self.NOTES).read_text())
        self.assertEqual("notes", (self.p / "Sources" / self.NOTES).read_text())
        self.assertIn("the project has a file of that name already", r.stdout)

    def test_a_join_never_moves_a_file_into_another_zone(self):
        other = self.root / "Zones" / "Personal"
        (other / "Acme" / "Sources").mkdir(parents=True)
        (other / "Acme" / "Sources" / "secret.txt").write_text("personal")
        import subprocess
        subprocess.run(["git", "add", "-A"], cwd=str(other), env=self.env, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "Acme in Personal"], cwd=str(other), env=self.env, check=True)
        before = {str(p.relative_to(other)): p.read_bytes() for p in other.rglob("*") if p.is_file() and ".git" not in p.parts}
        moves, left, _ = sc.plan_layout(self.work, self.work / "Acme", join=True)
        self.assertTrue(moves)
        self.assertTrue(all(a.startswith("Acme/") and b.startswith("Acme/") for a, b in moves), moves)
        self.layout("--join")
        self.assertEqual(before, {str(p.relative_to(other)): p.read_bytes() for p in other.rglob("*")
                                  if p.is_file() and ".git" not in p.parts})
        self.assertFalse((self.work / "Acme" / "Sources" / "secret.txt").exists())

    def test_a_refused_commit_leaves_every_file_and_row_where_it_was(self):
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.write_text(hook.read_text().replace("exec python3", "echo 'refused by the fixture hook' >&2\nexit 1\nexec python3"))
        before, count = self.snapshot(), self.commits()
        r = self.layout("--join")
        self.assertEqual(1, r.returncode)
        self.assertIn("every file and ledger row is where it was", r.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertEqual(count, self.commits())

    def test_undo_takes_a_join_back(self):
        before = self.snapshot()
        self.layout("--join")
        head = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        r = self.scaffold("undo", "--zone", "Work", "--commit", head)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(before, self.snapshot())

    def test_split_then_join_gives_back_the_same_files_ledger_rows_and_links(self):
        self.layout("--join", "--resume-from", "Pricing")
        a = self.work / "Acme"
        one_job = {n: b for n, b in self.snapshot().items() if not n.startswith("Acme/Threads/")}
        rows = sorted(l for l in (a / "Deliverables" / "published.md").read_text().splitlines() if l.startswith("| 2026"))
        links = {t: [l for l in (a / "Threads" / t / (t + ".md")).read_text().splitlines() if self.DECK.split(" - ")[1] in l]
                 for t in ("Pricing", "Freight")}
        r = self.layout("--split")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("layout: thread-first", self.hub_text("Acme"))
        r = self.layout("--join", "--resume-from", "Pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        again = {n: b for n, b in self.snapshot().items() if not n.startswith("Acme/Threads/")}
        self.assertEqual(sorted(one_job), sorted(again))
        for name in one_job:
            if not name.endswith("Acme.md") and not name.endswith("published.md"):
                self.assertEqual(one_job[name], again[name], name)
        self.assertEqual(rows, sorted(l for l in (a / "Deliverables" / "published.md").read_text().splitlines() if l.startswith("| 2026")))
        self.assertEqual(links, {t: [l for l in (a / "Threads" / t / (t + ".md")).read_text().splitlines()
                                      if self.DECK.split(" - ")[1] in l] for t in ("Pricing", "Freight")})
        text = self.hub_text("Acme")
        self.assertIn("### Resume here", text)
        self.assertNotIn("layout:", text)
        self.assertEqual(1, text.count("### Resume here"))

    def test_a_project_that_is_one_job_with_no_threads_papers_is_refused(self):
        self.layout("--join")
        r = self.layout("--join")
        self.assertEqual(1, r.returncode)
        self.assertIn("one job already", r.stderr)

    def test_a_mixed_project_is_mended_by_the_same_move_and_its_hub_is_left_alone(self):
        self.make("project", "--zone", "Work", "--name", "Cedar")
        self.make("thread", "--zone", "Work", "--project", "Cedar", "--name", "Quay")
        c = self.work / "Cedar"
        for k in ("Sources", "Deliverables"):
            (c / "Threads" / "Quay" / k).mkdir(exist_ok=True)
        (c / "Threads" / "Quay" / "Deliverables" / "260201 - Quay plan.docx").write_bytes(b"plan")
        self.commit("Cedar has a thread with papers of its own")
        hub = (c / "Cedar.md").read_text()
        r = self.layout("--join", project="Cedar")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue((c / "Deliverables" / "260201 - Quay plan.docx").is_file())
        self.assertFalse((c / "Threads" / "Quay" / "Sources").exists())
        self.assertFalse((c / "Threads" / "Quay" / "Deliverables").exists())
        self.assertEqual(hub.replace(hub.split("updated: ")[1].split("\n")[0], "X"),
                         (c / "Cedar.md").read_text().replace((c / "Cedar.md").read_text().split("updated: ")[1].split("\n")[0], "X"))


class TestTheMixedProjectFinding(LayoutFiles):
    """check.py reports a one-job project with a thread holding papers of its own, and the one move fixes it."""

    def mixed(self, name="Cedar", threads=("Quay",), hold=("Quay",)):
        self.make("project", "--zone", "Work", "--name", name)
        for t in threads:
            self.make("thread", "--zone", "Work", "--project", name, "--name", t)
        for t in hold:
            for k in ("Sources", "Deliverables"):
                (self.work / name / "Threads" / t / k).mkdir(exist_ok=True)
            (self.work / name / "Threads" / t / "Sources" / "brief.txt").write_text("brief %s" % t)
        self.commit("%s set up" % name)

    def finding(self, name="Cedar"):
        return [f for f in self.findings("projects") if "Cedar" in f.path and check.MIXED_PAPERS in f.message and f.path.endswith(name + ".md")]

    def test_it_reports_a_one_job_project_with_a_thread_holding_its_own_papers(self):
        self.mixed(threads=("Quay", "Wharf"), hold=("Quay",))
        (found,) = self.finding()
        self.assertEqual("warning", found.severity)
        self.assertIn("Quay", found.message)
        self.assertNotIn("Wharf", found.message)
        self.assertNotIn("separate jobs", found.message)             # one thread of two: a mixed project, not separate jobs

    def test_an_empty_papers_folder_is_not_reported_and_one_real_file_is(self):
        self.make("project", "--zone", "Work", "--name", "Cedar")
        self.make("thread", "--zone", "Work", "--project", "Cedar", "--name", "Quay")
        quay = self.work / "Cedar" / "Threads" / "Quay"
        (quay / "Sources").mkdir(exist_ok=True)
        (quay / "Sources" / ".gitkeep").write_text("")
        (quay / "Deliverables").mkdir(exist_ok=True)
        self.commit("empty folders")
        self.assertEqual([], self.finding())
        (quay / "Sources" / "brief.txt").write_text("brief")
        self.commit("one real file")
        self.assertEqual(1, len(self.finding()))

    def test_what_a_join_never_moves_is_no_papers_for_the_check_or_the_chip(self):
        """N1: an untracked .DS_Store, and a ledger with no row, leave nothing to move: neither raises the finding."""
        status_page = status
        self.make("project", "--zone", "Work", "--name", "Cedar")
        self.make("thread", "--zone", "Work", "--project", "Cedar", "--name", "Quay")
        self.make("thread", "--zone", "Work", "--project", "Cedar", "--name", "Wharf")
        quay = self.work / "Cedar" / "Threads" / "Quay"
        (quay / "Sources").mkdir(exist_ok=True)
        (quay / "Deliverables").mkdir(exist_ok=True)
        (quay / "Deliverables" / "published.md").write_text("| Date | File | Destination | Copy |\n|---|---|---|---|\n")
        self.commit("empty ledger")
        (quay / "Sources" / ".DS_Store").write_text("x")                  # untracked
        self.assertEqual([], self.finding())
        self.assertFalse(status_page.mixed_papers(self.work / "Cedar"))
        (quay / "Sources" / "brief.txt").write_text("brief")              # untracked: still none
        self.assertEqual([], self.finding())
        self.assertFalse(status_page.mixed_papers(self.work / "Cedar"))
        self.commit("one real file")
        self.assertEqual(1, len(self.finding()))
        self.assertTrue(status_page.mixed_papers(self.work / "Cedar"))

    def test_a_project_whose_threads_all_keep_papers_also_offers_to_split(self):
        self.mixed(threads=("Quay", "Wharf"), hold=("Quay", "Wharf"))
        (found,) = self.finding()
        self.assertIn("split the project into separate jobs", found.message)

    def test_a_hub_with_no_resume_point_also_offers_to_split(self):
        self.mixed(threads=("Quay", "Wharf"), hold=("Quay",))
        hub = self.work / "Cedar" / "Cedar.md"
        hub.write_text(hub.read_text().replace("### Resume here", "### Notes"))
        self.commit("no resume point")
        (found,) = self.finding()
        self.assertIn("split the project into separate jobs", found.message)

    def test_separate_jobs_and_a_clean_one_job_are_not_reported(self):
        self.make("project", "--zone", "Work", "--name", "Birch", "--separate", "--thread", "Pricing")
        self.make("project", "--zone", "Work", "--name", "Cedar", "--thread", "Quay")
        self.assertEqual([], [f for f in self.findings("projects") if check.MIXED_PAPERS in f.message])

    def test_the_fix_moves_the_papers_up_in_one_commit_and_leaves_no_thread_folder_with_papers(self):
        self.mixed(threads=("Quay", "Wharf"), hold=("Quay", "Wharf"))
        (self.work / "Cedar" / "Threads" / "Wharf" / "Sources" / "brief.txt").unlink()      # no clash
        (self.work / "Cedar" / "Threads" / "Wharf" / "Sources" / "map.txt").write_text("map")
        self.commit("no clash")
        count = self.commits()
        r = self.layout("--join", project="Cedar")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(count + 1, self.commits())
        for t in ("Quay", "Wharf"):
            self.assertFalse((self.work / "Cedar" / "Threads" / t / "Sources").exists(), t)
            self.assertFalse((self.work / "Cedar" / "Threads" / t / "Deliverables").exists(), t)
        self.assertTrue((self.work / "Cedar" / "Sources" / "brief.txt").is_file())
        self.assertTrue((self.work / "Cedar" / "Sources" / "map.txt").is_file())
        self.assertEqual([], self.finding())
        head = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        self.assertEqual(0, self.scaffold("undo", "--zone", "Work", "--commit", head).returncode)
        self.assertTrue((self.work / "Cedar" / "Threads" / "Quay" / "Sources" / "brief.txt").is_file())
        self.assertEqual(1, len(self.finding()))


class TestThePageBuildsBesideAHub(LayoutCase):
    """A hub that keeps `### Resume here` beside a thread is a row of Your work, not of the Threads card, and the
    page builds."""

    def test_the_page_builds_and_your_work_shows_both_rows(self):
        import subprocess
        import sys as _sys
        self.make("project", "--zone", "Work", "--name", "Gate Beside")
        self.make("thread", "--zone", "Work", "--project", "Gate Beside", "--name", "Side Thread")
        out = self.base / "status.html"
        r = subprocess.run([_sys.executable, str(REPO / "extras" / "status" / "status.py"), "--workspace", str(self.root),
                            "--out", str(out), "--no-cmux"], capture_output=True, text=True, env=self.env)
        self.assertEqual(0, r.returncode, r.stderr[-1500:])
        T = status.threads(self.root)["Work"]
        self.assertEqual(["Side Thread"], [x["thread"] for x in T["rows"] if x["project"] == "Gate Beside"])
        self.assertEqual(["Gate Beside"], [x["thread"] for x in T["hubs"] if x["project"] == "Gate Beside"])
        names = status.short_names(status.threads(self.root))
        self.assertEqual("Gate Beside", names[("Work", "Gate Beside", "Gate Beside")])
        self.assertEqual("Side Thread", names[("Work", "Gate Beside", "Side Thread")])


class TestThePage(LayoutCase):
    """The page's verbs and dialogs (page_action.py, status.py)."""

    def setUp(self):
        super().setUp()
        import os
        os.environ["GARRICK_JOBS_DIR"] = str(self.base / "jobs")

    def act(self, **req):
        return pa.act(self.root, req)

    def log(self):
        import subprocess
        return subprocess.run(["git", "log", "-1", "--format=%s"], cwd=str(self.work), capture_output=True, text=True,
                              env=self.env).stdout.strip()

    def test_a_new_project_sends_no_thread_by_default_and_is_one_piece_of_work(self):
        self.act(verb="new-project", zone="Work", name="Acme")
        self.assertFalse((self.work / "Acme" / "Threads").exists())
        self.assertIn("### Resume here", self.hub_text("Acme"))
        self.assertEqual("New project Acme", self.log())

    def test_separate_jobs_are_asked_for_by_the_heading_field(self):
        self.act(verb="new-project", zone="Work", name="Birch", heading=True)
        self.assertIn("layout: thread-first", self.hub_text("Birch"))
        self.assertFalse((self.work / "Birch" / "Sources").exists())
        with self.assertRaises(pa.Refused):
            self.act(verb="new-project", zone="Work", name="Cedar", heading="maybe")
        self.assertFalse((self.work / "Cedar").exists())

    def test_the_separate_option_of_a_command_line_makes_separate_jobs(self):
        args = pa.command_parser().parse_args(["new-project", "--zone", "Work", "--name", "Cedar", "--separate", "yes"])
        req = pa.session_request(self.root, args)
        self.assertNotIn("separate", req)
        self.assertIn(req["heading"], ("yes", True))
        self.act(**req)
        self.assertIn("layout: thread-first", self.hub_text("Cedar"))

    def test_a_thread_in_one_job_uses_the_projects_papers_and_a_papers_choice_is_refused(self):
        self.act(verb="new-project", zone="Work", name="Acme")
        self.act(verb="new-thread", zone="Work", project="Acme", name="Pricing")
        self.assertFalse((self.work / "Acme" / "Threads" / "Pricing" / "Deliverables").exists())
        for papers in ("own", "project", "shared"):
            with self.assertRaises(pa.Refused) as why:
                self.act(verb="new-thread", zone="Work", project="Acme", name="Side Deal", papers=papers)
            self.assertIn("one job or separate jobs", str(why.exception))
        self.assertFalse((self.work / "Acme" / "Threads" / "Side Deal").exists())

    def test_a_thread_in_separate_jobs_always_has_its_own(self):
        self.act(verb="new-project", zone="Work", name="Birch", heading=True)
        self.act(verb="new-thread", zone="Work", project="Birch", name="Pricing")
        self.assertTrue((self.work / "Birch" / "Threads" / "Pricing" / "Sources").is_dir())

    def test_undo_takes_back_a_project_made_without_a_thread(self):
        self.act(verb="new-project", zone="Work", name="Acme")
        import subprocess
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(self.work), capture_output=True, text=True,
                              env=self.env).stdout.strip()
        self.act(verb="undo", zone="Work", commit=head)
        self.assertFalse((self.work / "Acme").exists())

    def test_the_dialogs_ask_one_question_of_a_new_project_and_none_of_a_new_thread(self):
        text = (REPO / "extras" / "status" / "status.py").read_text(encoding="utf-8")
        self.assertIn("One job or separate jobs?", text)
        self.assertIn("if(hd)o.heading=true", text)
        for gone in ("Does this thread keep its own papers", "q.papers='own'", "mg-papers", "A heading over separate pieces"):
            self.assertNotIn(gone, text)
        self.assertNotIn("Empty gives", text)

    def test_the_page_knows_which_projects_are_separate_jobs(self):
        import json
        self.act(verb="new-project", zone="Work", name="Acme")
        self.act(verb="new-project", zone="Work", name="Birch", heading=True)
        T = status.threads(self.root)
        data = status.manage_data(T, {"parties": {}}, True)["zones"]["Work"]
        self.assertIn("Acme", data["projects"])
        self.assertIn("Birch", data["projects"])
        self.assertEqual(["Birch"], data["headings"])
        self.assertNotIn("first", status.manage_data(T, {"parties": {}}, True))


import test_ask_make as tam  # noqa: E402  (its cases are not imported: they would run twice)
from test_ask import ask  # noqa: E402
from fixtures import project_hub, thread_note  # noqa: E402


def heading_hub(zone, project):
    return project_hub(zone, project, "acme", ["Pricing", "Freight"]).replace("status: active", "status: active\nlayout: thread-first")


class TestNaming(tam.MakeCase):
    """A project's name in a request: a piece of work resolves to its hub; a heading asks which thread, naming them;
    a question reads every thread under it; nothing reads another zone's project of the same name."""

    def setUp(self):
        super().setUp()
        write(self.work / "Cedar" / "Cedar.md", heading_hub("Work", "Cedar"))
        for t in ("Pricing", "Freight"):
            write(self.work / "Cedar" / "Threads" / t / (t + ".md"), thread_note("Cedar", t, "acme", body="The %s price is 40." % t))
        write(self.work / "Maple" / "Maple.md", project_hub("Work", "Maple", "acme", ["Rates"]) + HUB_BLOCK)
        write(self.work / "Maple" / "Threads" / "Rates" / "Rates.md", thread_note("Maple", "Rates", "acme"))
        far = self.root / "Zones" / "Personal"
        write(far / "Cedar" / "Cedar.md", heading_hub("Personal", "Cedar"))
        write(far / "Cedar" / "Threads" / "Private Plan" / "Private Plan.md",
              thread_note("Cedar", "Private Plan", "acme", body="The private price is 99."))
        self.names = ask.scan(self.root)

    def test_the_list_marks_separate_jobs(self):
        self.assertTrue(self.names["Work"]["Cedar"].get("heading"))
        self.assertFalse(self.names["Work"]["Maple"].get("heading"))
        text = ask.render(self.names)
        self.assertIn("- Cedar [active] separate jobs threads: Freight; Pricing", text)
        self.assertIn("- Maple [active] threads: Rates", text)

    def test_opening_one_job_opens_its_hub(self):
        kind, item = self.propose({"verb": "open", "zone": "Work", "project": "Maple"})
        self.assertEqual("launch", kind)
        self.assertTrue(item["note"].endswith("Maple/Maple.md"))

    def test_opening_separate_jobs_asks_which_thread_naming_them(self):
        with self.assertRaises(ask.Needs) as asked:
            self.propose({"verb": "open", "zone": "Work", "project": "Cedar"})
        self.assertEqual("Which thread of Cedar: Freight or Pricing?", asked.exception.question)
        self.assertEqual(["Freight", "Pricing"], [c["label"] for c in asked.exception.choices])
        self.assertNotIn("Private", asked.exception.question)           # the other zone's project of that name is not read
        kind, item = self.propose({"verb": "open", "zone": "Work", "project": "Cedar", "thread": "Pricing"})
        self.assertEqual("launch", kind)

    def test_a_new_project_has_no_thread_and_is_separate_jobs_only_when_the_request_says_so(self):
        _, item = self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "acme", "heading": True},
                               tam.project_named(parties=("acme",)))
        self.assertNotIn("heading", item)
        self.assertNotIn("thread", item)
        named = tam.Named({"acme"}, [])
        named = type("N", (), {"text": "new project Harbour as separate jobs for Acme", "parties": {"acme"}, "entries": [], "zone": "Work"})()
        _, item = self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "acme", "heading": True}, named)
        self.assertTrue(item["heading"])

    def test_a_question_about_a_heading_names_each_answers_thread_and_reads_one_zone(self):
        sc = ask_scope = ask.scope_lib()
        scope = ask_scope.Scope("thread", "Work", "Cedar", None, ["price"], set())
        found = ask_scope.search(self.root, scope, {"parties": {}, "zones": {}}, ask_scope.lib(self.root))
        paths = [r["path"] for r in found]
        self.assertTrue([r for r in found if r.get("thread") == "Pricing"], paths)
        self.assertTrue([r for r in found if r.get("thread") == "Freight"], paths)
        self.assertFalse([p for p in paths if p.startswith("Zones/Personal")], paths)
        self.assertFalse([r for r in found if r.get("thread") == "Private Plan"])


class TestTheDispatcherNames(unittest.TestCase):
    """The Telegram channel settles a project's name through the intake skill (purpose ask)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        for tool in ("garrick_lib.py",):
            write(self.root / "System" / "tools" / tool, (TOOLS / tool).read_text(encoding="utf-8"))
        self.intake = load("garrick_intake_layout", REPO / "template" / "System" / "skills" / "intake" / "intake.py")
        work = self.root / "Zones" / "Work"
        write(work / "Cedar" / "Cedar.md", heading_hub("Work", "Cedar"))
        for t in ("Pricing", "Freight"):
            write(work / "Cedar" / "Threads" / t / (t + ".md"), thread_note("Cedar", t, "acme"))
        write(work / "Maple" / "Maple.md", project_hub("Work", "Maple", "acme", ["Rates"]) + HUB_BLOCK)
        write(work / "Maple" / "Threads" / "Rates" / "Rates.md", thread_note("Maple", "Rates", "acme"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_piece_of_work_with_a_resume_point_settles_to_its_hub(self):
        place = self.intake.resolve_destination(self.root, "Maple", "x", purpose="ask")
        self.assertEqual(("Maple", None), (place["project"], place["thread"]))

    def test_a_piece_of_work_without_one_keeps_what_it_did(self):
        place = self.intake.resolve_destination(self.root, "Acme Review", "x", purpose="ask")
        self.assertEqual(("Acme Review", "Pricing"), (place["project"], place["thread"]))

    def test_a_heading_asks_which_thread_and_names_its_own_zones_threads_only(self):
        with self.assertRaises(self.intake.Confirm) as asked:
            self.intake.resolve_destination(self.root, "Cedar", "x", purpose="ask")
        self.assertEqual("Which thread of Cedar: Freight or Pricing?", str(asked.exception))
        self.assertEqual(["Freight", "Pricing"], [o["thread"] for o in asked.exception.offer])

    def test_a_note_keeps_its_wording(self):
        with self.assertRaises(self.intake.Confirm) as asked:
            self.intake.resolve_destination(self.root, "Cedar", "x")
        self.assertEqual("Which thread of Cedar is the note about: Freight or Pricing?", str(asked.exception))

    def test_a_heading_of_the_same_name_in_another_zone_is_asked_about_by_zone_and_never_read(self):
        write(self.root / "Zones" / "Personal" / "Cedar" / "Cedar.md", heading_hub("Personal", "Cedar"))
        write(self.root / "Zones" / "Personal" / "Cedar" / "Threads" / "Private Plan" / "Private Plan.md",
              thread_note("Cedar", "Private Plan", "acme"))
        with self.assertRaises(self.intake.Confirm) as asked:
            self.intake.resolve_destination(self.root, "Cedar", "x", purpose="ask")
        self.assertEqual("Which do you mean: Cedar in Personal or Cedar in Work?", str(asked.exception))
        self.assertNotIn("Private", str(asked.exception))
        self.assertEqual([], getattr(asked.exception, "offer", []))


class HubBesideThreads(unittest.TestCase):
    """The hub's `### Resume here` stays a resume point while the project has threads, and `### Outcome`
    in its place ends it. A heading never has one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        write(self.root / "System" / "rules.md", "# Rules\n")
        for tool in ("next_up.py", "garrick_lib.py", "briefing.py", "work.py"):
            write(self.root / "System" / "tools" / tool, (TOOLS / tool).read_text(encoding="utf-8"))
        self.work = self.root / "Zones" / "Work"
        self.hub = self.work / "Acme Review" / "Acme Review.md"

    def tearDown(self):
        self._tmp.cleanup()

    def keep(self, block):
        self.hub.write_text(self.hub.read_text(encoding="utf-8") + block, encoding="utf-8")

    def keeps(self):
        """Does the one reader find a resume point of its own in the hub?"""
        found = [r for r in gl.work.project_pieces(self.root, self.work, self.work / "Acme Review") if r.thread is None]
        return bool(found) and found[0].keeps_resume

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

    def test_two_hashes_is_no_resume_point_in_all_five_readings(self):
        self.keep(HUB_BLOCK.replace("### Resume here", "## Resume here"))
        self.assertNotIn(("Acme Review", None), self.next_up_rows())
        self.assertNotIn(("Acme Review", None), self.briefing_rows())
        T = status.threads(self.root)
        self.assertEqual([], [r for r in T["Work"]["hubs"] if r["project"] == "Acme Review"])
        self.assertFalse(status.hub_keeps_resume(self.hub, None))
        self.assertFalse(self.keeps())
        # and the same without the workspace's garrick_lib, which both fall back from
        (self.root / "System" / "tools" / "garrick_lib.py").unlink()
        status._LIBS.clear()
        self.assertFalse(status.hub_keeps_resume(self.hub, None))
        self.assertFalse(self.keeps())
        self.hub.write_text(self.hub.read_text(encoding="utf-8").replace("## Resume here", "### Resume here"), encoding="utf-8")
        self.assertTrue(status.hub_keeps_resume(self.hub, None))
        self.assertTrue(self.keeps())

    def test_layout_is_read_from_the_front_matter_only(self):
        self.keep(HUB_BLOCK + "\nlayout: thread-first\n")                      # a body line is not the layout
        self.assertTrue(self.keeps())
        self.assertTrue(status.hub_keeps_resume(self.hub, None))
        self.assertIn(("Acme Review", None), self.next_up_rows())

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



class TestTheDocsSayOneJob(unittest.TestCase):
    """#632: the docs and the skills describe one job and separate jobs, Split and Join, and nothing older."""

    OLD = ("Make a heading", "Own papers…", "Project’s papers…", "Project's papers…", "--papers", "--heading", "heading over",
           "a heading over", "separate pieces", "one piece of work, or a heading", "a row of the menu")

    def pages(self):
        for base in (REPO / "docs", REPO / "template" / "System" / "skills" / "threads"):
            yield from sorted(base.rglob("*.md"))

    def test_no_page_names_a_heading_as_a_layout_or_a_papers_choice_for_a_thread(self):
        seen = 0
        for path in self.pages():
            text = path.read_text(encoding="utf-8")
            seen += 1
            for old in self.OLD:
                self.assertNotIn(old, text, "%s still says %r" % (path.relative_to(REPO), old))
        self.assertGreater(seen, 20)

    def test_the_pages_that_describe_the_switch_name_both_ways(self):
        for rel in ("docs/commands.md", "docs/concepts.md", "docs/extras/status-page.md",
                    "template/System/skills/threads/reference/lifecycle.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn("separate jobs", text, rel)
            self.assertIn("one job", text, rel)
        for rel in ("docs/commands.md", "docs/extras/status-page.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn("Split into separate jobs…", text, rel)
            self.assertIn("Join into one job…", text, rel)


if __name__ == "__main__":
    unittest.main()
