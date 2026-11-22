"""The view model (#650): `System/tools/view.py` builds one JSON document of what the App shows, and the page only draws it.

    python3 -m unittest test_view_model

The shadow test. On each fixture workspace the page's old reads, frozen word for word in `old_status_reads.py` as
v0.76.0 had them, and the view model are compared field by field. Every difference is written here:

    difference                                               why the view model is right
    ------------------------------------------------------   -----------------------------------------------------------
    A zone folder that is a link: the old inbox read counted a link is no zone (work.py). The old read gave one zone's
    the files of the folder it points at, under the link's    files under a second name: a wall defect. The view model
    name.                                                      lists the link with no work and no inbox.
    A hub note that is a link to a file outside its zone: the  A file of another zone is no part of this project. The view
    old read took it for the project's hub and read it.        model has no hub for it, and reads nothing through it.
    An `Inbox` that is a link to a folder outside its zone:    The count must be of one zone. The view model leaves an
    the old read counted that folder's files.                  Inbox out whose real path is outside the zone it sits in.

Nothing else differs: pieces, their order, their states, resume points, checkpoints, parties, dates and counts match the
old reads exactly. The display rules (what "late" means, what a chip says) are the page's and are not in the view model.

Also here: the view model writes nothing; it is JSON-serialisable; every record carries its zone; a scope that should
not see a zone gets none of its records, through a link too; every action it offers is declared in operations.DECLARED.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import work_fixture  # noqa: E402
from fixtures import build_workspace, thread_note, write  # noqa: E402
from old_status_reads import old_reads  # noqa: E402
from test_status import REPO, status  # noqa: E402

TOOLS = REPO / "template" / "System" / "tools"
sys.path.insert(0, str(TOOLS))
import view  # noqa: E402
import operations  # noqa: E402

CHECKPOINT = "\n### Checkpoint\n\n<!-- garrick-checkpoint at=2026-11-01T09:30:00 base=0123456789ab -->\n"


def snapshot(root: Path) -> dict:
    """Every file under `root`: its mtime and its bytes, so that a build that wrote anything shows."""
    out = {}
    for dirpath, dirs, files in os.walk(root, followlinks=False):
        for name in files:
            p = Path(dirpath) / name
            try:
                st = p.lstat()
                out[p.relative_to(root).as_posix()] = (st.st_mtime_ns, p.read_bytes() if p.is_file() and not p.is_symlink() else b"link")
            except OSError:
                out[p.relative_to(root).as_posix()] = None
    return out


def make_workspace(root: Path, tools: bool = True) -> Path:
    """Invented workspaces in one: the standard two zones, the reader's shapes in Work, and a third zone, Home, with
    parked work, a checkpoint, a done thread, a spoken name, a party list and an inbox; a zone that is a link; an Inbox that
    is a link out of its zone; and a project kept in System/."""
    root = Path(root)
    build_workspace(root)
    if tools:       # a workspace has the core's tools, so the page's old read hashes a resume point as the core does
        (root / "System" / "tools").symlink_to(TOOLS, target_is_directory=True)
    work_fixture.build(root)
    home = root / "Zones" / "Home"
    write(home / "Inbox" / "a.txt", "x\n")
    write(home / "Inbox" / "b.eml", "x\n")
    write(home / "Inbox" / ".hidden", "x\n")
    write(home / "Cedar" / "Cedar.md",
          "---\ntitle: Cedar\ntype: project\nstatus: active\nparty: [cedar, maple]\nspoken: the cedar job\n---\n\n# Cedar\n")
    write(home / "Cedar" / "Threads" / "Fence" / "Fence.md",
          thread_note("Cedar", "Fence", "cedar").replace("updated: 2026-03-01", "updated: 2026-10-30") + CHECKPOINT)
    write(home / "Cedar" / "Threads" / "Gate" / "Gate.md", thread_note("Cedar", "Gate", "cedar", status="done"))
    write(home / "Cedar" / "Threads" / "Latch" / "Latch.md",
          thread_note("Cedar", "Latch", "cedar", status="parked").replace("created: 2026-03-01", "created: 2026-03-01\nspoken: the latch"))
    write(home / "Maple" / "Maple.md", "---\ntitle: Maple\ntype: project\nstatus: parked\nparty: maple\n---\n\n# Maple\n")
    write(home / "Maple" / "Threads" / "Bark" / "Bark.md", thread_note("Maple", "Bark", "maple"))
    # A thread note with an unreadable date and no resume block.
    write(home / "Maple" / "Threads" / "Leaf" / "Leaf.md",
          "---\ntitle: Leaf\ntype: thread\nstatus: active\nupdated: not a day\n---\n\n# Leaf\n\nA first sentence.\n")
    # The Meetings wiki's inbox holds a file.
    write(root / "Wikis" / "Meetings" / "raw" / "inbox" / "call.txt", "x\n")
    # A zone that is a link to another zone, and an Inbox that is a link out of its zone.
    (root / "Zones" / "Linked").symlink_to(home, target_is_directory=True)
    garden = root / "Zones" / "Garden"
    write(garden / "Plot" / "Plot.md", "---\ntitle: Plot\ntype: project\nstatus: active\n---\n\n# Plot\n")
    (garden / "Inbox").symlink_to(home / "Inbox", target_is_directory=True)
    (garden / "Plot" / "Threads").mkdir(parents=True)
    (garden / "Plot" / "Threads" / "Leak").symlink_to(home / "Cedar" / "Threads" / "Fence", target_is_directory=True)
    (garden / "Borrowed").symlink_to(home / "Cedar", target_is_directory=True)      # a whole project of another zone, by a link
    write(garden / "Twin" / "Threads" / "Copy" / "Copy.md", "---\ntitle: Copy\nstatus: active\n---\n\n# Copy\n")
    (garden / "Twin" / "Twin.md").symlink_to(home / "Maple" / "Maple.md")           # a hub note that is another zone's file
    write(root / "System" / "Sys" / "Sys.md", "---\ntitle: Sys\ntype: project\nstatus: active\n---\n\n# Sys\n")
    return root


def bare(threads: dict) -> dict:
    """The page's threads with the manage data section 3 added taken off, which the old read did not have."""
    out = {}
    for name, data in threads.items():
        data = {k: v for k, v in data.items() if k != "open_links"}
        data["projects"] = {n: {k: v for k, v in p.items() if k not in ("files", "layout")} for n, p in data["projects"].items()}
        for key in ("rows", "parked", "finished", "hubs"):
            data[key] = [{k: v for k, v in r.items() if k not in ("files", "open")} for r in data[key]]
        out[name] = data
    return out


def outside(path) -> bool:
    """A note that is a link leading out of its zone: the old read took it for the project's hub."""
    if path is None or not path.is_symlink():
        return False
    zone = next(p for p in path.parents if p.parent.name == "Zones")
    real = path.resolve()
    return not (real == zone.resolve() or zone.resolve() in real.parents)


def walled(threads: dict) -> dict:
    """The old read's threads with a hub that leads out of its zone taken for none, as the view model does (the second
    named difference in the docstring)."""
    out = {}
    for name, data in threads.items():
        data = dict(data)
        for key in ("rows", "parked", "finished", "hubs"):
            data[key] = [dict(r, hub=None) if outside(r.get("hub")) else r for r in data[key]]
        data["projects"] = {n: dict(p, hub=None) if outside(p.get("hub")) else p for n, p in data["projects"].items()}
        out[name] = data
    return out


def as_row(root: Path, p: dict) -> dict:
    """A piece of the view model as the page's old row has it: paths and dates restored."""
    day = lambda s: dt.date.fromisoformat(s) if s else None  # noqa: E731
    path = lambda s: root / s if s else None  # noqa: E731
    base = {"zone": p["zone"], "project": p["project"], "thread": p["thread"], "note": path(p["note"]), "hub": path(p["hub"]),
            "status": p["state"], "party": p["party"], "updated": day(p["updated"]), "spoken": p["spoken"]}
    if p["shown"] == "done":
        return base
    read = p["read"]
    mark = p["checkpoint"]
    base.update({"rel": p["rel"], "resume": p["resume"], "resumed": day(p["resumed"]),
                 "checkpoint": dict(mark, at=dt.datetime.fromisoformat(mark["at"]) if mark["at"] else None) if mark else None,
                 "touched": day(p["touched"]), "heading": p["heading"],
                 "read": dict(read, date=day(read["date"]), entry=(day(read["entry"][0]), read["entry"][1]) if read["entry"] else None)})
    if p["held"]:
        base["held"] = True
    return base


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        make_workspace(self.root)
        self.addCleanup(self._tmp.cleanup)
        self.old = old_reads(status)
        self.model = view.build(self.root)

    def zone(self, name):
        return next(z for z in self.model["zones"] if z["name"] == name)


class TestShadowThreads(Case):
    """The page's old read of the threads, zone by zone, against the view model."""

    def test_every_zone_the_old_read_lists_is_in_the_view(self):
        old = self.old["threads"](self.root)
        self.assertEqual(list(old), [z["name"] for z in self.model["zones"]])

    def test_pieces_match_the_old_rows_exactly(self):
        old = walled(self.old["threads"](self.root))
        for name, data in old.items():
            z = self.zone(name)
            for shown, key in (("row", "rows"), ("parked", "parked"), ("done", "finished"), ("hub", "hubs")):
                got = [as_row(self.root, p) for p in z["work"] if p["shown"] == shown]
                self.assertEqual(data[key], got, "%s / %s" % (name, key))

    def test_zone_figures_match(self):
        old = self.old["threads"](self.root)
        for name, data in old.items():
            z = self.zone(name)
            self.assertEqual(data["done"], z["done"], name)
            self.assertEqual(data["held"], z["held"], name)
            self.assertEqual({k: dict({a: b for a, b in v.items() if a not in ("files", "layout")},
                                      hub=self.root / v["hub"] if v["hub"] else None) for k, v in z["projects"].items()},
                             data["projects"], name)

    def test_the_fixture_covers_what_the_brief_names(self):
        work = self.zone("Work")
        shapes = {(p["project"], p["shown"]) for p in work["work"]}
        for needed in (("Single", "row"), ("Heading", None), ("Mixed", "hub"), ("Parked", "parked"), ("Threads", "done")):
            if needed[1] is None:
                self.assertIn("Heading", work["projects"])
                self.assertTrue(work["projects"]["Heading"]["heading"])
            else:
                self.assertIn(needed, shapes)
        home = self.zone("Home")
        self.assertTrue(any(p["checkpoint"] for p in home["work"]))
        self.assertEqual(1, home["done"])
        self.assertEqual(["Maple"], home["held"])

    def test_the_frozen_table_of_the_reader_fixture(self):
        """Regression: what the view lists for the reader's fixture project shapes, frozen."""
        got = [(p["id"], p["shown"], p["state"]) for p in self.zone("Work")["work"]
               if p["project"] in ("Single", "Mixed", "Parked", "Threads", "Heading", "HeadingThreads", "Odd")]
        self.assertEqual(FROZEN_WORK, got)


FROZEN_WORK = [
    ("Work/HeadingThreads/Alpha", "row", "active"),
    ("Work/HeadingThreads/Beta", "row", "active"),
    ("Work/Mixed/Delta", "row", "active"),
    ("Work/Threads/Omicron", "row", "active"),
    ("Work/Single", "row", "active"),
    ("Work/Parked/Iota", "parked", "parked"),
    ("Work/Threads/Nu", "parked", "parked"),
    ("Work/Odd/Upsilon", "parked", "parked"),     # `dormant` is a parked word
    ("Work/Mixed/Epsilon", "done", "done"),
    ("Work/Parked/Kappa", "done", "done"),
    ("Work/Threads/Xi", "done", "done"),
    ("Work/Mixed", "hub", "active"),
]


class TestPageThreads(Case):
    """Section 1, the Threads card's data: the page's `threads()` now takes it from the view model, and must give what
    the old read gave, row for row."""

    def test_the_page_reads_the_same_threads_as_the_old_read(self):
        self.assertEqual(walled(self.old["threads"](self.root)), bare(status.threads(self.root)))

    def test_the_page_reads_the_notes_through_the_view_alone(self):
        calls = []
        real = view.build
        with mock.patch.object(view, "build", lambda *a, **k: calls.append(a) or real(*a, **k)), \
                mock.patch.object(status, "view_reader", lambda ws=None: view):
            status.threads(self.root)
        self.assertEqual(1, len(calls))

    def test_a_page_is_drawn_from_one_build_of_the_view(self):
        calls = []
        real = view.build
        with mock.patch.object(view, "build", lambda *a, **k: calls.append(a) or real(*a, **k)), \
                mock.patch.object(status, "view_reader", lambda ws=None: view):
            with tempfile.TemporaryDirectory() as jobs:
                with mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": jobs}):
                    status.build(self.root, now=dt.datetime(2026, 11, 22, 12), folder=Path(jobs))
        self.assertEqual(1, len(calls))

    def test_a_workspace_with_no_view_module_yet_builds_a_page_that_says_so(self):
        with mock.patch.object(status, "view_reader", mock.Mock(side_effect=FileNotFoundError("System/tools/view.py"))):
            got = status.threads(self.root)
        self.assertEqual({"Garden", "Home", "Linked", "Personal", "Work"}, set(got))
        for data in got.values():
            self.assertTrue(data["needs_update"])
            self.assertEqual([], data["rows"])

    def test_the_resume_helpers_the_tests_and_the_page_still_call_give_the_view_models_answer(self):
        note = self.root / "Zones" / "Home" / "Cedar" / "Threads" / "Fence" / "Fence.md"
        self.assertEqual((True, dt.date(2026, 3, 1)), status.resume_point(note))
        self.assertEqual(view.checkpoint_mark(note), status.checkpoint_mark(note, self.root))
        for text in (None, "", "<next step>", " a real line ", "<a> and <b>"):
            self.assertEqual(view.filled(text), status.filled(text))


class TestShadowManageData(Case):
    """Section 3, what the Threads card's Rename, Move and Delete dialogs say: the files a delete would take, the open lines it
    would remove, and the layout change a project offers. The page asked the folders itself; the view model holds them."""

    def setUp(self):
        super().setUp()
        # Open lines that link notes, by their names, one naming two threads, one with an alias and a heading.
        write(self.root / "Zones" / "Home" / "Todo.md",
              "# Home\n\n## Inbox\n\n- [ ] Call about [[Fence]] today\n- [ ] Both [[Fence]] and [[Gate|the gate]]\n"
              "- [ ] Heading [[Cedar/Threads/Latch/Latch#Next|Latch]]\n- [x] Done [[Fence]]\n- [ ] No link here\n")
        write(self.root / "Zones" / "Home" / "Cedar" / "Threads" / "Fence" / "Deliverables" / "260301 - memo.md", "x\n")
        write(self.root / "Zones" / "Home" / "Cedar" / "Threads" / "Fence" / ".hidden", "x\n")
        self.model = view.build(self.root)

    def test_a_threads_files_and_open_lines_are_what_the_old_read_counted(self):
        for z in self.model["zones"]:
            for p in z["work"]:
                if p["shown"] in ("row", "parked"):
                    note = self.root / p["note"]
                    if p["note"] == p["hub"]:
                        self.assertNotIn("files", p, p["id"])
                        continue
                    self.assertEqual(self.old["files_in"](note.parent), p["files"], p["id"])
                    self.assertEqual(self.old["open_naming"](note.parents[3], {p["thread"]}), p["open"], p["id"])

    def test_open_lines_are_counted_once_each_and_only_while_open(self):
        home = self.zone("Home")
        by = {p["thread"]: p["open"] for p in home["work"] if p["shown"] in ("row", "parked")}
        self.assertEqual({"Fence": 2, "Latch": 1, "Leaf": 0, "Bark": 0}, by)
        self.assertEqual([["Fence"], ["Fence", "Gate"], ["Latch"]], home["open_links"])

    def test_naming_several_threads_counts_a_line_once(self):
        zone = self.root / "Zones" / "Home"
        for names in ({"Fence"}, {"Fence", "Gate"}, {"Gate", "Latch", "Cedar"}, {"Fence", "Cedar", "Latch"}, set(), {"Nobody"}):
            self.assertEqual(self.old["open_naming"](zone, names), view.open_naming(self.zone("Home")["open_links"], names), names)

    def test_a_projects_files_and_layout_offer_match_the_old_read(self):
        for z in self.model["zones"]:
            for name, project in z["projects"].items():
                folder = self.root / "Zones" / z["name"] / name
                if project["hub"] is None or not (folder / (name + ".md")).is_file():
                    self.assertNotIn("files", project, name)
                    continue
                self.assertEqual(self.old["files_in"](folder), project["files"], name)
                self.assertEqual(self.old["layout_offers"](folder, project["heading"], True), project["layout"], name)

    def test_the_layout_offers_the_old_page_made_for_each_shape(self):
        work = self.zone("Work")["projects"]
        self.assertEqual(["join"], work["Heading"]["layout"])
        self.assertEqual(["split"], work["Single"]["layout"])
        self.assertEqual(["split"], work["Mixed"]["layout"])

    def test_the_page_card_data_is_unchanged(self):
        """The row's and the project's `mg`, as the page builds them, against the old functions."""
        T = status.threads(self.root)
        for z, data in T.items():
            for r in data["rows"] + data["parked"]:
                if r["note"] == r["hub"]:
                    continue
                want = [r["zone"], r["project"], r["thread"], self.old["files_in"](r["note"].parent),
                        self.old["open_naming"](r["note"].parents[3], {r["thread"]}), [],
                        self.old["layout_offers"](r["note"].parent, bool(r.get("heading")), r["hub"] is not None)]
                got = json.loads(status.thread_card(r, {(r["zone"], r["project"], r["thread"]): r["thread"]}, lambda p: "x", 1)).get("mg")
                self.assertEqual(want, got, r["thread"])

    def test_the_helpers_the_tests_still_call_on_the_page_answer_as_the_view_does(self):
        folder = self.root / "Zones" / "Work" / "Mixed"
        self.assertEqual(view.layout_offers(folder, False, True), status.layout_offers(folder, False, True))
        self.assertEqual(view.mixed_papers(folder), status.mixed_papers(folder))


# What status.py still reads from the folders for itself, by function, and why: no core module owns it yet. The acceptance
# line "status.py has no direct read of Zones/, Wikis/ or a thread note" is met when this table is empty; until then it
# is the list of what is left (#650 is `Part of`). A function that reads anew fails the test below, and one that stops
# reading must leave the table, so the list never goes stale.
LEFT = {
    "example_zone": "the worked example's marker, .example.json",
    "graph": "Explore: the notes of one zone or one wiki, for the graph",
    "is_workspace": "whether a folder holds System/rules.md and Zones/",
    "jobs": "the jobs folder's logs",
    "launchd_jobs": "this Mac's launchd agents",
    "question_needs": "the wiki questions that wait, for Waiting on you now",
    "questions_in": "a wiki's question files",
    "repos": "each repository's own state",
    "system_notes": "the projects kept in System/, which the work reader does not cover",
    "threads": "zone names only, while view.py is missing (a half-finished update)",
    "todo": "each zone's open-line counts (no caller is left)",
    "todo_list": "the Todo tab: each zone's Todo.md and the action lines in thread notes",
    "visible_dirs": "the helper the others list folders with",
    "wikis": "each wiki's log",
}


class TestWhatThePageStillReads(unittest.TestCase):
    """The acceptance line of #650: status.py has no direct read of Zones/, Wikis/ or a thread note. It is not met yet, and
    this says exactly what is left."""

    @staticmethod
    def readers():
        import ast
        tree = ast.parse((REPO / "extras" / "status" / "status.py").read_text(encoding="utf-8"))
        found = {}

        class Walk(ast.NodeVisitor):
            def __init__(self):
                self.stack = []

            def visit_FunctionDef(self, node):
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def hit(self, why):
                if self.stack:
                    found.setdefault(self.stack[0], set()).add(why)

            def visit_BinOp(self, node):
                if isinstance(node.op, ast.Div) and isinstance(node.right, ast.Constant) and node.right.value in ("Zones", "Wikis"):
                    self.hit("path " + node.right.value)
                self.generic_visit(node)

            def visit_Call(self, node):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if name in ("glob", "rglob", "iterdir", "walk", "visible_dirs", "listdir", "scandir"):
                    self.hit("call " + name)
                if name in ("Path", "joinpath", "join") and any(isinstance(a, ast.Constant) and a.value in ("Zones", "Wikis") for a in node.args):
                    self.hit("path join")
                self.generic_visit(node)

        Walk().visit(tree)
        return found

    def test_what_the_page_still_reads_is_exactly_the_list_of_what_is_left(self):
        self.assertEqual(sorted(LEFT), sorted(self.readers()))

    def test_the_sections_that_moved_read_no_folder(self):
        found = self.readers()
        for name in ("inboxes", "thread_row", "resume_read", "checkpoint_mark", "thread_card", "project_card", "layout_offers",
                     "mixed_papers", "files_in", "open_naming", "threads_card", "build"):
            self.assertNotIn(name, found, name)

    def test_the_view_model_names_what_is_left_for_it(self):
        for name in ("Todo lists", "waiting sessions", "settings", "operations journal", "the Explore graph", "repositories"):
            self.assertIn(name, view.LEFT)


class TestShadowInbox(Case):
    def test_inbox_matches_the_old_read_except_the_named_differences(self):
        old = {name: (folder, n) for name, folder, n in self.old["inboxes"](self.root)}
        new = {q["place"]: (self.root / q["folder"], q["count"]) for q in self.model["queues"]["inbox"]}
        # Difference 1: a zone that is a link has no inbox here. Difference 2: nor has an Inbox that leads out of its zone.
        self.assertEqual({"Linked", "Garden"}, set(old) - set(new))
        for name in set(new):
            self.assertEqual(old[name], new[name], name)

    def test_the_page_reads_the_inbox_through_the_view(self):
        """Section 2, the inbox rows: the page's `inboxes()` is the view's queue, and differs from the old read only by
        the two walls named above."""
        page = {name: (folder, n) for name, folder, n in status.inboxes(self.root)}
        old = {name: (folder, n) for name, folder, n in self.old["inboxes"](self.root)}
        self.assertEqual({"Linked", "Garden"}, set(old) - set(page))
        for name in page:
            self.assertEqual(old[name], page[name], name)
        self.assertEqual(["Home", "Personal", "Work", "Meetings"], [n for n, _, _ in status.inboxes(self.root)])

    def test_a_half_finished_update_has_no_inbox_rows(self):
        with mock.patch.object(status, "view_reader", mock.Mock(side_effect=FileNotFoundError("view.py"))):
            self.assertEqual([], status.inboxes(self.root))

    def test_the_wiki_inbox_is_one_wiki_and_the_zones_are_one_zone_each(self):
        counts = {q["place"]: (q["kind"], q["count"]) for q in self.model["queues"]["inbox"]}
        self.assertEqual(("wiki", 1), counts["Meetings"])
        self.assertEqual(("zone", 2), counts["Home"])     # the dot file is not counted
        self.assertNotIn("Linked", counts)
        self.assertNotIn("Garden", counts)


class TestDisplayRules(unittest.TestCase):
    """A display rule kept from the old page, named: a workspace with no System/tools/garrick_lib.py of its own judges no
    checkpoint, whatever the core could say, as the old read could not hash a resume point."""

    def test_a_checkpoint_is_never_out_of_date_in_a_workspace_with_no_library_of_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_workspace(Path(tmp).resolve() / "W", tools=False)
            old = old_reads(status)["threads"](root)
            fence = next(r for r in old["Home"]["rows"] if r["thread"] == "Fence")
            new = next(p for p in view.build(root)["zones"][1]["work"] if p["thread"] == "Fence")
            self.assertFalse(fence["checkpoint"]["stale"])
            self.assertFalse(new["checkpoint"]["stale"])
            self.assertEqual(old["Home"]["rows"], bare(status.threads(root))["Home"]["rows"])


class TestWalls(Case):
    def test_a_link_is_no_zone_and_carries_no_work(self):
        z = self.zone("Linked")
        self.assertTrue(z["linked"])
        self.assertEqual([], z["work"])

    def test_a_thread_folder_linked_into_another_zone_is_left_out(self):
        garden = self.zone("Garden")
        self.assertEqual([], [p for p in garden["work"] if p["thread"] == "Leak"])
        self.assertEqual({"Plot", "Twin"}, {p["project"] for p in garden["work"]})

    def test_a_project_or_a_hub_note_that_is_a_link_into_another_zone_shows_none_of_it(self):
        garden = self.zone("Garden")
        self.assertEqual(["Plot", "Twin"], sorted({p["project"] for p in garden["work"]}))
        text = json.dumps(garden)
        for other in ("Fence", "Latch", "Gate", "Cedar", "Bark", "Maple"):
            self.assertFalse(other in text, other)
        self.assertIsNone(garden["projects"]["Twin"]["hub"])
        self.assertNotIn("files", garden["projects"]["Twin"])

    def test_a_todo_note_that_is_a_link_out_of_its_zone_names_nothing(self):
        (self.root / "Zones" / "Garden" / "Todo.md").symlink_to(self.root / "Zones" / "Home" / "Todo.md")
        write(self.root / "Zones" / "Home" / "Todo.md", "# Home\n\n- [ ] See [[Fence]]\n")
        model = view.build(self.root)
        self.assertEqual([["Fence"]], next(z for z in model["zones"] if z["name"] == "Home")["open_links"])
        self.assertEqual([], next(z for z in model["zones"] if z["name"] == "Garden")["open_links"])

    def test_a_scope_holds_its_zones_alone(self):
        scoped = view.build(self.root, scope=["Garden"])
        self.assertEqual(["Garden"], [z["name"] for z in scoped["zones"]])
        text = json.dumps(scoped)
        for other in ("Cedar", "Maple", "Acme Review", "Meetings", "call.txt"):
            self.assertFalse(other in text, other)
        self.assertEqual([], scoped["queues"]["inbox"])        # no wiki, and Garden's Inbox leads out of it

    def test_every_record_carries_its_zone_and_its_zone_is_its_path(self):
        for z in self.model["zones"]:
            for p in z["work"]:
                self.assertEqual(z["name"], p["zone"])
                self.assertTrue(p["note"].startswith("Zones/%s/" % z["name"]), p["note"])

    def test_no_count_adds_two_places(self):
        places = [q["place"] for q in self.model["queues"]["inbox"]]
        self.assertEqual(len(places), len(set(places)))


class TestShape(Case):
    def test_it_is_json(self):
        self.assertEqual(self.model, json.loads(json.dumps(self.model)))

    def test_it_writes_nothing(self):
        before = snapshot(self.root)
        view.build(self.root)
        view.build(self.root, scope=["Home"])
        self.assertEqual(before, snapshot(self.root))

    def test_actions_are_declared_verbs(self):
        for z in self.model["zones"]:
            for p in z["work"]:
                self.assertTrue(p["actions"])
                for verb in p["actions"]:
                    self.assertIn(verb, operations.DECLARED)

    def test_a_live_piece_may_be_parked_and_a_parked_one_woken(self):
        pieces = {p["id"]: p for z in self.model["zones"] for p in z["work"]}
        self.assertIn("park", pieces["Home/Cedar/Fence"]["actions"])
        self.assertNotIn("wake", pieces["Home/Cedar/Fence"]["actions"])
        self.assertIn("wake", pieces["Home/Cedar/Latch"]["actions"])
        self.assertNotIn("park", pieces["Home/Cedar/Latch"]["actions"])

    def test_the_checkpoint_is_read_from_its_comment_line_alone(self):
        piece = next(p for p in self.zone("Home")["work"] if p["thread"] == "Fence")
        self.assertEqual("09:30", piece["checkpoint"]["said"])
        self.assertEqual("2026-11-01", piece["touched"])
        self.assertFalse("garrick-checkpoint" in json.dumps(self.model))

    def test_the_module_is_reexported_by_the_library(self):
        import garrick_lib
        self.assertEqual(view.build.__code__.co_filename, garrick_lib.view.build.__code__.co_filename)

    def test_the_page_constants_match(self):
        self.assertEqual(status.DONE, view.DONE)
        self.assertEqual(status.PARKED, view.PARKED)


if __name__ == "__main__":
    unittest.main()
