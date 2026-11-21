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

    def test_a_heading_written_in_capitals_is_a_heading_to_check_too(self):
        self.make("project", "--zone", "Work", "--name", "Cedar")
        hub = self.work / "Cedar" / "Cedar.md"
        text = hub.read_text(encoding="utf-8")
        hub.write_text(text.replace("---\n\n", "layout: Thread-First\n---\n\n", 1).replace("### Resume here", "### Notes"), encoding="utf-8")
        self.assertIn("layout: Thread-First", hub.read_text(encoding="utf-8"))
        self.assertEqual([], [f for f in self.findings("projects") if "Cedar" in f.path and "no threads" in f.message])

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


OUTCOME = "\n## State of play\n\n### Outcome\n\nDelivered and accepted.\n"


class TestLayout(LayoutCase):
    """scaffold.py layout: a thread's papers, or a project made a heading, files carried with their ledger rows and links."""

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

    def git(self, *args):
        import subprocess
        return subprocess.run(["git", *args], cwd=str(self.work), capture_output=True, text=True, env=self.env)

    def commit(self, message):
        self.git("add", "-A")
        r = self.git("commit", "-q", "-m", message)
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)

    def commits(self):
        return int(self.git("rev-list", "--count", "HEAD").stdout)

    def snapshot(self):
        return {str(p.relative_to(self.work)): p.read_bytes() for p in (self.work / "Acme").rglob("*") if p.is_file()}

    def layout(self, *args):
        return self.scaffold("layout", "--zone", "Work", "--project", "Acme", *args)

    def test_check_writes_nothing(self):
        before, count = self.snapshot(), self.commits()
        r = self.layout("--thread", "Pricing", "--papers", "own", "--check")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn(self.DECK, r.stdout)
        self.assertIn("Nothing was changed.", r.stdout)
        self.assertEqual(before, self.snapshot())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertEqual(count, self.commits())

    def test_a_thread_takes_only_the_files_its_own_note_names(self):
        count = self.commits()
        r = self.layout("--thread", "Pricing", "--papers", "own")
        self.assertEqual(0, r.returncode, r.stderr)
        a = self.work / "Acme"
        self.assertTrue((a / "Threads" / "Pricing" / "Deliverables" / self.DECK).is_file())
        self.assertFalse((a / "Deliverables" / self.DECK).exists())
        self.assertTrue((a / "Deliverables" / self.SHEET).is_file())            # Freight's, not Pricing's
        self.assertTrue((a / "Deliverables" / self.MISC).is_file())             # no thread names it
        self.assertTrue((a / "Sources" / self.BRIEF).is_file())                 # two threads name it
        self.assertIn(self.MISC, r.stdout)
        self.assertIn(self.BRIEF, r.stdout)
        self.assertEqual(count + 1, self.commits())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        # the commit stays inside the project
        names = [n for n in self.git("show", "--name-only", "--format=", "HEAD").stdout.split("\n") if n]
        self.assertTrue(names and all(n.startswith("Acme/") for n in names), names)

    def test_the_ledger_row_follows_its_file_and_its_destination_stays(self):
        self.layout("--thread", "Pricing", "--papers", "own")
        a = self.work / "Acme"
        project_rows = (a / "Deliverables" / "published.md").read_text()
        thread_rows = (a / "Threads" / "Pricing" / "Deliverables" / "published.md").read_text()
        self.assertNotIn(self.DECK, project_rows)
        self.assertIn(self.SHEET, project_rows)
        self.assertIn("| 2026-03-01 | `%s` | `acme/Decks/` | Dana | here |" % self.DECK, thread_rows)
        self.assertIn("## What left", thread_rows)

    def test_the_links_follow(self):
        self.layout("--thread", "Pricing", "--papers", "own")
        text = (self.work / "Acme" / "Threads" / "Pricing" / "Pricing.md").read_text()
        self.assertIn("(Deliverables/%s)" % self.DECK.replace(" ", "%20"), text)
        self.assertNotIn("../../Deliverables", text)

    def test_a_thread_can_go_back_to_the_projects_papers(self):
        self.layout("--thread", "Pricing", "--papers", "own")
        r = self.layout("--thread", "Pricing", "--papers", "project")
        self.assertEqual(0, r.returncode, r.stderr)
        a = self.work / "Acme"
        self.assertTrue((a / "Deliverables" / self.DECK).is_file())
        self.assertFalse((a / "Threads" / "Pricing" / "Deliverables").exists())
        self.assertFalse((a / "Threads" / "Pricing" / "Sources").exists())
        self.assertIn(self.DECK, (a / "Deliverables" / "published.md").read_text())
        self.assertEqual("", self.git("status", "--porcelain").stdout)

    def test_a_refused_commit_leaves_every_file_and_row_where_it_was(self):
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.write_text(hook.read_text().replace("exec python3", "echo 'refused by the fixture hook' >&2\nexit 1\nexec python3"))
        before, count = self.snapshot(), self.commits()
        r = self.layout("--thread", "Pricing", "--papers", "own")
        self.assertEqual(1, r.returncode)
        self.assertIn("every file and ledger row is where it was", r.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertEqual(count, self.commits())

    def test_a_project_becomes_a_heading_and_each_file_goes_to_its_one_thread(self):
        r = self.layout("--heading")
        self.assertEqual(0, r.returncode, r.stderr)
        a = self.work / "Acme"
        self.assertIn("layout: thread-first", (a / "Acme.md").read_text())
        self.assertTrue((a / "Threads" / "Pricing" / "Deliverables" / self.DECK).is_file())
        self.assertTrue((a / "Threads" / "Freight" / "Deliverables" / self.SHEET).is_file())
        self.assertTrue((a / "Deliverables" / self.MISC).is_file())             # left for the owner
        self.assertTrue((a / "Sources" / self.BRIEF).is_file())
        for t in ("Pricing", "Freight"):
            self.assertTrue((a / "Threads" / t / "Sources").is_dir())
        self.assertIn(self.MISC, r.stdout)
        self.assertIn("Resume here", r.stdout)
        self.assertIn(self.SHEET, (a / "Threads" / "Freight" / "Deliverables" / "published.md").read_text())

    def test_a_heading_is_not_made_a_heading_twice(self):
        self.layout("--heading")
        r = self.layout("--heading")
        self.assertEqual(1, r.returncode)
        self.assertIn("already", r.stderr)

    def test_a_dirty_project_is_refused(self):
        (self.work / "Acme" / "Sources" / "late.txt").write_text("late")
        r = self.layout("--thread", "Pricing", "--papers", "own")
        self.assertEqual(1, r.returncode)
        self.assertFalse((self.work / "Acme" / "Threads" / "Pricing" / "Deliverables").exists())

    def test_nothing_runs_on_its_own_and_it_asks_for_a_choice(self):
        r = self.layout()
        self.assertEqual(1, r.returncode)
        r = self.layout("--heading", "--thread", "Pricing")
        self.assertEqual(1, r.returncode)

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
        r = self.layout("--thread", "Pricing", "--papers", "own")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(before, {str(p.relative_to(other)): p.read_bytes() for p in (other / "Acme").rglob("*") if p.is_file()})
        self.assertEqual(count, subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=str(other), env=self.env,
                                               capture_output=True, text=True).stdout)
        self.assertNotIn("Personal", r.stdout)

    def test_the_page_verb_plans_and_does(self):
        import os
        os.environ["GARRICK_JOBS_DIR"] = str(self.base / "jobs")
        said = pa.act(self.root, {"verb": "layout", "zone": "Work", "project": "Acme", "thread": "Pricing", "papers": "own",
                                  "check": True})
        self.assertIn(self.DECK, said)
        self.assertFalse((self.work / "Acme" / "Threads" / "Pricing" / "Deliverables").exists())
        said = pa.act(self.root, {"verb": "layout", "zone": "Work", "project": "Acme", "thread": "Pricing", "papers": "own"})
        self.assertIn("moved", said)
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing" / "Deliverables" / self.DECK).is_file())
        with self.assertRaises(pa.Refused):
            pa.act(self.root, {"verb": "layout", "zone": "Work", "project": "Acme", "thread": "Pricing", "papers": "both"})

    def test_undo_takes_the_change_back(self):
        self.layout("--thread", "Pricing", "--papers", "own")
        head = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        r = self.scaffold("undo", "--zone", "Work", "--commit", head)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue((self.work / "Acme" / "Deliverables" / self.DECK).is_file())

    def test_a_bare_name_does_not_match_another_folders_file_of_that_name(self):
        a = self.work / "Acme"
        (a / "Sources" / "Terms.docx").write_bytes(b"source terms")
        (a / "Deliverables" / "Terms.docx").write_bytes(b"deliverable terms")
        pricing = a / "Threads" / "Pricing" / "Pricing.md"
        pricing.write_text(pricing.read_text() + "\nThe terms are Deliverables/Terms.docx.\n")
        self.commit("terms")
        for args in (("--thread", "Pricing", "--papers", "own"), ("--heading",)):
            moves, left, _ = sc.plan_layout(self.work, a, "Pricing", "own" if "--papers" in args else None,
                                                        "--heading" in args)
            self.assertIn(("Acme/Deliverables/Terms.docx", "Acme/Threads/Pricing/Deliverables/Terms.docx"), moves)
            self.assertNotIn("Acme/Sources/Terms.docx", [m[0] for m in moves])
        r = self.layout("--thread", "Pricing", "--papers", "own", "--check")
        self.assertIn("Sources/Terms.docx", r.stdout)
        self.assertTrue(sc.names_file("see ../../Deliverables/x.pptx", "Sources/x.pptx", "x.pptx") is False)
        self.assertTrue(sc.names_file("see x.pptx.", "Sources/x.pptx", "x.pptx"))

    def test_a_target_that_exists_is_left_for_the_owner_not_promised(self):
        a = self.work / "Acme"
        for t in ("Pricing", "Freight"):
            for k in ("Sources", "Deliverables"):
                (a / "Threads" / t / k).mkdir(exist_ok=True)
        (a / "Threads" / "Pricing" / "Deliverables" / self.DECK).write_bytes(b"already")
        self.commit("target exists")
        for args, kw in ((("--thread", "Pricing", "--papers", "own"), {}), (("--heading",), {})):
            r = self.layout(*args, "--check")
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn("the thread has a file of that name already", r.stdout)
            self.assertNotIn("%s to Threads" % self.DECK, r.stdout)
        r = self.layout("--thread", "Pricing", "--papers", "own")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(b"deck", (a / "Deliverables" / self.DECK).read_bytes())

    def test_a_note_that_is_a_symlink_is_never_written_through(self):
        outside = Path(tempfile.mkdtemp()) / "outside.md"
        outside.write_text("The deck is Deliverables/%s here.\n" % self.DECK)
        link = self.work / "Acme" / "Link.md"
        link.symlink_to(outside)
        self.commit("a link")
        self.assertNotIn(link, list(sc.zone_notes(self.work)))
        self.layout("--thread", "Pricing", "--papers", "own")
        self.assertEqual("The deck is Deliverables/%s here.\n" % self.DECK, outside.read_text())


class TestThePageBuildsBesideAHub(LayoutCase):
    """A hub that keeps `### Resume here` beside a thread is a row of Your work, not of the Threads card, and the
    page builds."""

    def test_the_page_builds_and_your_work_shows_both_rows(self):
        import subprocess
        import sys as _sys
        self.make("project", "--zone", "Work", "--name", "Gate Beside")
        self.make("thread", "--zone", "Work", "--project", "Gate Beside", "--name", "Side Thread", "--papers", "own")
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

    def test_a_heading_is_asked_for_by_the_heading_field(self):
        self.act(verb="new-project", zone="Work", name="Birch", heading=True)
        self.assertIn("layout: thread-first", self.hub_text("Birch"))
        self.assertFalse((self.work / "Birch" / "Sources").exists())
        with self.assertRaises(pa.Refused):
            self.act(verb="new-project", zone="Work", name="Cedar", heading="maybe")
        self.assertFalse((self.work / "Cedar").exists())

    def test_a_thread_in_a_piece_of_work_takes_its_papers_from_the_request(self):
        self.act(verb="new-project", zone="Work", name="Acme")
        self.act(verb="new-thread", zone="Work", project="Acme", name="Pricing")
        self.assertFalse((self.work / "Acme" / "Threads" / "Pricing" / "Deliverables").exists())
        self.act(verb="new-thread", zone="Work", project="Acme", name="Side Deal", papers="own")
        self.assertTrue((self.work / "Acme" / "Threads" / "Side Deal" / "Deliverables").is_dir())
        with self.assertRaises(pa.Refused):
            self.act(verb="new-thread", zone="Work", project="Acme", name="Freight", papers="shared")

    def test_a_heading_thread_always_has_its_own(self):
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

    def test_the_dialogs_ask_the_two_questions(self):
        text = (REPO / "extras" / "status" / "status.py").read_text(encoding="utf-8")
        self.assertIn("Is this project one piece of work, or a heading over separate pieces?", text)
        self.assertIn("Does this thread keep its own papers, or use the project’s?", text)
        self.assertIn("if(hd)o.heading=true", text)
        self.assertIn("if(own)q.papers='own'", text)
        self.assertNotIn("Empty gives", text)

    def test_the_papers_question_is_only_for_a_piece_of_work(self):
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

    def test_the_list_marks_a_heading(self):
        self.assertTrue(self.names["Work"]["Cedar"].get("heading"))
        self.assertFalse(self.names["Work"]["Maple"].get("heading"))
        text = ask.render(self.names)
        self.assertIn("- Cedar [active] heading threads: Freight; Pricing", text)
        self.assertIn("- Maple [active] threads: Rates", text)

    def test_opening_a_piece_of_work_opens_its_hub(self):
        kind, item = self.propose({"verb": "open", "zone": "Work", "project": "Maple"})
        self.assertEqual("launch", kind)
        self.assertTrue(item["note"].endswith("Maple/Maple.md"))

    def test_opening_a_heading_asks_which_thread_naming_them(self):
        with self.assertRaises(ask.Needs) as asked:
            self.propose({"verb": "open", "zone": "Work", "project": "Cedar"})
        self.assertEqual("Which thread of Cedar: Freight or Pricing?", asked.exception.question)
        self.assertEqual(["Freight", "Pricing"], [c["label"] for c in asked.exception.choices])
        self.assertNotIn("Private", asked.exception.question)           # the other zone's project of that name is not read
        kind, item = self.propose({"verb": "open", "zone": "Work", "project": "Cedar", "thread": "Pricing"})
        self.assertEqual("launch", kind)

    def test_a_new_project_has_no_thread_and_is_a_heading_only_when_the_request_says_so(self):
        _, item = self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "acme", "heading": True},
                               tam.project_named(parties=("acme",)))
        self.assertNotIn("heading", item)
        self.assertNotIn("thread", item)
        named = tam.Named({"acme"}, [])
        named = type("N", (), {"text": "new project Harbour as a heading for Acme", "parties": {"acme"}, "entries": [], "zone": "Work"})()
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

    def test_two_hashes_is_no_resume_point_in_all_five_readings(self):
        self.keep(HUB_BLOCK.replace("### Resume here", "## Resume here"))
        self.assertNotIn(("Acme Review", None), self.next_up_rows())
        self.assertNotIn(("Acme Review", None), self.briefing_rows())
        T = status.threads(self.root)
        self.assertEqual([], [r for r in T["Work"]["hubs"] if r["project"] == "Acme Review"])
        self.assertFalse(status.hub_keeps_resume(self.hub, None))
        self.assertFalse(pa.hub_keeps_resume(self.hub))
        # and the same without the workspace's garrick_lib, which both fall back from
        (self.root / "System" / "tools" / "garrick_lib.py").unlink()
        status._LIBS.clear()
        self.assertFalse(status.hub_keeps_resume(self.hub, None))
        self.assertFalse(pa.hub_keeps_resume(self.hub))
        self.hub.write_text(self.hub.read_text(encoding="utf-8").replace("## Resume here", "### Resume here"), encoding="utf-8")
        self.assertTrue(status.hub_keeps_resume(self.hub, None))
        self.assertTrue(pa.hub_keeps_resume(self.hub))

    def test_layout_is_read_from_the_front_matter_only(self):
        self.keep(HUB_BLOCK + "\nlayout: thread-first\n")                      # a body line is not the layout
        self.assertTrue(pa.hub_keeps_resume(self.hub))
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


if __name__ == "__main__":
    unittest.main()
