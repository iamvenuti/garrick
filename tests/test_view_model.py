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

Since 0.78.0 the page's other reads are the view model's too (the Todo tab, the questions, the wikis' logs, the
repositories, the worked example's marker, the graph, the projects kept in System/), each frozen in
`old_status_reads_0770.py` as v0.77.0 had it and held to the same answer here. The only differences are the one wall: a zone folder that is a link is no zone and has no Todo list, questions, repository or graph notes; a note,
folder, log or marker that is a link into another zone or a wiki is not read; a link to a file outside the workspace is read
as it was. The old reads followed such a link and showed another place's records under this one's name.

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
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import work_fixture  # noqa: E402
from fixtures import build_workspace, thread_note, write  # noqa: E402
from old_status_reads import old_reads  # noqa: E402
from old_status_reads_0770 import old_reads as old_reads_0770  # noqa: E402
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


TODAY = dt.date(2026, 11, 22)
HOME_TODO = (
    "# Home: open actions\n\n## Inbox\n\n"
    "- [ ] [[Fence]]: Order posts 📅 2026-11-20 #waiting ⏳ 2026-11-21\n"
    "- [ ] Unplaced thing\n\n## Soon\n\n"
    "- [ ] [[Sys/Job|Job]]: system one 📅 2026-11-25\n"
    "- [ ] [[Cedar/Threads/Gate/Gate]]: link by path ⏫ #ask\n"
    "- [ ] ⚠️ thread?: not sure of the thread · [src](x.md) (also in [A](a.md))\n"
    "- [ ] <action> a template line\n"
    "- [x] [[Fence]]: done today ✅ 2026-11-22\n"
    "- [x] [[Fence]]: done long ago ✅ 2026-11-01\n"
    "```\n- [ ] inside a fence\n```\n\n"
    "## Active threads\n\n- [ ] [[Fence]]: a workstream\n\n"
    "## Someday\n\n- [ ] Later thing\n")


def add_todo(root: Path) -> None:
    """Todo lines for the Todo shadow test: sections, links by name, by path and to a System project, a waiting line, an
    unsure line, a template line, a fence, ticked lines, a line in a thread note, in a project note and in a note
    beside the projects; and a note in the Garden zone that is a link to Home's Todo.md (a line of another zone)."""
    home = root / "Zones" / "Home"
    write(home / "Todo.md", HOME_TODO)
    leaf = home / "Maple" / "Threads" / "Leaf" / "Leaf.md"
    write(leaf, leaf.read_text(encoding="utf-8") + "\n- [ ] A line in the thread note 📅 2026-11-23\n")
    write(home / "Cedar" / "Notes.md", "- [ ] A project-level line\n")
    write(home / "Loose.md", "- [ ] A line in a note beside the projects\n")
    write(root / "Zones" / "Work" / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] Work thing\n\n## Done\n")
    garden = root / "Zones" / "Garden"
    garden.mkdir(parents=True, exist_ok=True)
    (garden / "Leak.md").symlink_to(home / "Todo.md")


def question(ask="Which fence?", status="open", asked="2026-11-10", extra="", options=("Cedar", "Pine")) -> str:
    return ("---\nstatus: %s\nasked: %s\n%s---\n\n%s\n\n%s\n"
            % (status, asked, extra, "**%s**" % ask if ask else "No bold line here.", "".join("- [%s] Use %s\n" % (o, o) for o in options)))


def add_questions(root: Path) -> None:
    """Needs you files for the shadow test: the zone's own box (only what an inbox run asked), a project's, a thread's, one
    put off to a day that has come, one put off to a day that has not, an answered one, one with nothing to ask; and, in
    Garden, a project that is a link to Home's and a file that is a link to one of Home's."""
    home = root / "Zones" / "Home"
    write(home / "Needs you" / "inbox-run.md", question("File this mail?", extra="intake: true\nown: Other\n"))
    write(home / "Needs you" / "stray.md", question("Not an inbox question"))
    write(home / "Cedar" / "Needs you" / "q1.md", question())
    write(home / "Cedar" / "Needs you" / "q2.md", question("Put off, due", status="later", extra="later: 2026-11-21\n", asked="2026-11-01"))
    write(home / "Cedar" / "Needs you" / "q3.md", question("Put off, not due", status="later", extra="later: 2026-11-30\n"))
    write(home / "Cedar" / "Needs you" / "q4.md", question("Answered", status="answered"))
    write(home / "Cedar" / "Needs you" / "q5.md", question(""))
    write(home / "Cedar" / "Threads" / "Fence" / "Needs you" / "t.md", question("Thread question", asked="2026-11-05"))
    out = root / "Zones" / "Garden" / "Plot" / "Needs you"
    out.mkdir(parents=True, exist_ok=True)
    (out / "Out.md").symlink_to(home / "Cedar" / "Needs you" / "q1.md")


def add_wikis(root: Path) -> None:
    """Wiki logs for the shadow test: the three forms of an entry, a page that is there and one that is not, a log with
    lines that read as none of them, one with no log, and a log that is a link out of its wiki."""
    wikis = root / "Wikis"
    write(wikis / "Meetings" / "wiki" / "log.md",
          "# Log\n\n- 2026-11-18: [[wiki/sources/review|Weekly review]] (touched a)\n"
          "- 2026-11-20: [[wiki/sources/gone|A page that is not there]]\n- 2026-11-19: [[wiki/sources/review]]\n")
    write(wikis / "Meetings" / "wiki" / "sources" / "review.md", "# Review\n")
    write(wikis / "Knowledge" / "wiki" / "log.md",
          "# Log\n\n## 2026-11-15\n- [[wiki/sources/paper|Paper]]; touched b\n\n## 2026-11-12 · Older **entry** (x)\n"
          "- 2026-11-10: A line with [a link](http://acme.example/x) in it; and more\n")
    write(wikis / "Knowledge" / "wiki" / "sources" / "paper.md", "# Paper\n")
    write(wikis / "Odd" / "wiki" / "log.md", "# Log\n\n- something happened\n- and again\n")
    write(wikis / "Bare" / "wiki" / "index.md", "# Index\n")
    (wikis / "Leaky" / "wiki").mkdir(parents=True, exist_ok=True)
    (wikis / "Leaky" / "wiki" / "log.md").symlink_to(root / "Zones" / "Home" / "Todo.md")


def add_graph(root: Path) -> None:
    """Notes and links for the graph shadow test: links by name, by path, with an escaped alias pipe and across places; a
    folder the graph skips (Inbox, archive), an instructions file, a hidden note, a note the vault excludes, three pages
    of a type no model kind takes, wiki pages of the model's kinds; and, in Garden, a note that is a link to one of Home's."""
    home = root / "Zones" / "Home"
    write(home / "Cedar" / "Cedar.md", (home / "Cedar" / "Cedar.md").read_text(encoding="utf-8") + "\nSee [[Fence]] and [[Cedar/Threads/Gate/Gate]] and [[Loose]].\n")
    write(home / "Loose.md", "- [ ] A line in a note beside the projects\n\nBack to [[Cedar]], [[Cedar\\|alias]], [[wiki/sources/paper]] and [[nowhere]].\n")
    write(home / "Inbox" / "in.md", "---\ntitle: Inbox note\n---\n")
    write(home / "Cedar" / "archive" / "old.md", "---\ntitle: Archived note\n---\n")
    write(home / "AGENTS.md", "# Agents\n")
    write(home / "_hidden.md", "---\ntitle: Hidden note\n---\n")
    write(home / "Cedar" / "Scratch" / "idea.md", "---\ntitle: An idea\n---\n\n# Idea\n")
    write(home / ".obsidian" / "app.json", json.dumps({"userIgnoreFilters": ["Cedar/Scratch/"]}))
    for n in range(3):
        write(root / "Wikis" / "Knowledge" / "wiki" / "domains" / ("d%d.md" % n), "---\ntype: domain\ntitle: Domain %d\n---\n\nSee [[paper]].\n" % n)
    write(root / "Wikis" / "Knowledge" / "wiki" / "concepts" / "lane.md", "---\ntype: concept\n---\n# Lane\n\nFrom [[paper]].\n")
    write(root / "Wikis" / "Meetings" / "wiki" / "people" / "jo.md", "---\ntype: person\ntitle: Jo\n---\n\nIn [[call-1]] and [[acme-corp]].\n")
    write(root / "Wikis" / "Meetings" / "wiki" / "people" / "theo.md", "---\ntype: person\ntitle: Theo\n---\n\nIn [[call-1]] and [[acme-corp]].\n")
    write(root / "Wikis" / "Meetings" / "wiki" / "meetings" / "call-1.md", "---\ntype: meeting\nparties: [acme, birch]\n---\n# Call\n")
    write(root / "Wikis" / "Meetings" / "wiki" / "entities" / "acme-corp.md", "---\ntype: entity\n---\n# Acme Corp\n")
    write(root / "Wikis" / "Meetings" / "wiki" / "mail" / "m1.md", "---\ntype: email\n---\n# Mail\n")
    plot = root / "Zones" / "Garden" / "Plot"
    plot.mkdir(parents=True, exist_ok=True)
    (plot / "Peek.md").symlink_to(home / "Cedar" / "Cedar.md")


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
    add_todo(root)
    add_questions(root)
    add_wikis(root)
    add_graph(root)
    write(root / "System" / "Sys" / "Sys.md", "---\ntitle: Sys\ntype: project\nstatus: active\n---\n\n# Sys\n")
    write(root / "System" / "Sys" / "Threads" / "Job" / "Job.md", thread_note("Sys", "Job", "sys"))
    write(root / "System" / "Sys" / "Threads" / "Bare" / "notes.md", "# no thread note\n")          # a thread folder with no note
    write(root / "System" / "Loose" / "Loose.md", "---\ntitle: Loose\ntype: thread\n---\n\n# Loose\n")   # not a project
    write(root / "System" / "_hidden" / "_hidden.md", "---\ntype: project\n---\n")
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

    def test_a_view_module_from_before_the_parts_builds_a_page_that_says_so(self):
        old = mock.Mock(spec=["build"])                  # 0.77.0's view.py: no PARTS, and build() takes no `only`
        with mock.patch.object(status, "view_reader", mock.Mock(return_value=old)):
            self.assertIsNone(status.view_model(self.root))
            got = status.threads(self.root)
            self.assertEqual([], status.todo_list(self.root, status.Links(self.root), TODAY))
            self.assertEqual([], status.wikis(self.root))
            self.assertEqual([], status.repos(self.root))
            self.assertIsNone(status.example_zone(self.root))
        self.assertTrue(all(data["needs_update"] for data in got.values()))
        old.build.assert_not_called()

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


# What status.py still reads from the folders for itself, by function, and why. The acceptance line "status.py has no
# direct read of Zones/, Wikis/ or a thread note" is met except for what is named here: the page's own guard for a
# half-finished update (`threads`, and `visible_dirs`, which only it uses), the check that a folder is a workspace
# (`is_workspace`), and this Mac's own state, which no workspace holds (`launchd_jobs`, `jobs`: the launchd agents and the
# jobs folder's logs; the waiting sessions are not read from a folder of the workspace at all). It is `Part of #650`, not
# `Closes`, while `jobs` and `is_workspace` stand beside the three exceptions the plan names. A function that reads anew
# fails the test below, and one that stops reading must leave the table, so the list never goes stale.
LEFT = {
    "is_workspace": "whether a folder holds System/rules.md and Zones/",
    "jobs": "the jobs folder's logs",
    "launchd_jobs": "this Mac's launchd agents",
    "threads": "zone names only, while view.py is missing (a half-finished update)",
    "visible_dirs": "the helper the others list folders with",
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
        for name in ("graph", "example_zone", "todo_list", "question_needs", "questions_in", "wikis", "repos", "inboxes", "thread_row", "resume_read", "checkpoint_mark", "thread_card", "project_card", "layout_offers",
                     "mixed_papers", "files_in", "open_naming", "threads_card", "build"):
            self.assertNotIn(name, found, name)

    def test_the_view_model_names_what_is_left_for_it(self):
        for name in ("waiting sessions", "settings", "operations journal"):
            self.assertIn(name, view.LEFT)


class TestShadowSystem(Case):
    """The projects kept in System/ (#650, 0.78.0): the view model names their notes, the page draws the lookup."""

    def test_the_lookup_the_page_makes_is_the_old_reads(self):
        old = old_reads_0770(status, "SYSTEM")
        got = {k: self.root / v for k, v in view.system_lookup(self.model["system"]).items()}
        self.assertEqual(old["system_notes"](self.root), got)
        self.assertEqual({"system/sys/sys", "sys", "system/sys/threads/job/job", "job"}, set(got))

    def test_a_folder_that_is_no_project_and_a_thread_with_no_note_are_left_out(self):
        notes = [n for p in self.model["system"] for n in p["notes"]]
        self.assertEqual(["System/Sys/Sys.md", "System/Sys/Threads/Job/Job.md"], notes)
        self.assertEqual(["Sys"], [p["name"] for p in self.model["system"]])

    def test_a_scoped_build_holds_none_of_system(self):
        self.assertEqual([], view.build(self.root, scope=["Home"])["system"])

    def test_only_builds_the_parts_named(self):
        part = view.build(self.root, only=("system",))
        self.assertEqual([], part["zones"])
        self.assertEqual(1, len(part["system"]))
        self.assertNotIn("system", view.build(self.root, only=("work",)))


class TestShadowTodo(Case):
    """The Todo tab (#650, 0.78.0): the view model reads each zone's open actions and decides which note each line names;
    the page decides what late means and how a row sorts. Held to v0.77.0's own `todo_list`, frozen."""

    def setUp(self):
        super().setUp()
        self.link = status.Links(self.root)
        self.old_list = old_reads_0770(status, "SYSTEM", "TODO")["todo_list"](self.root, self.link, TODAY)
        self.new_list = status.todo_list(self.root, self.link, TODAY)

    def by_zone(self, lists):
        return {z["zone"]: z for z in lists}

    def test_every_zone_the_old_read_listed_is_the_same_except_the_two_named_differences(self):
        old, new = self.by_zone(self.old_list), self.by_zone(self.new_list)
        self.assertEqual({"Home", "Work", "Linked", "Garden"} & set(old), {"Home", "Work", "Linked", "Garden"})
        for name in ("Home", "Work"):
            self.assertEqual(old[name], new[name], name)

    def test_a_zone_that_is_a_link_has_no_todo_list(self):
        # The old read gave the zone a link points at a second list, under the link's name: a wall defect.
        self.assertIn("Linked", self.by_zone(self.old_list))
        self.assertNotIn("Linked", self.by_zone(self.new_list))
        self.assertNotIn("todo", self.zone("Linked"))

    def test_a_note_that_is_a_link_out_of_its_zone_gives_that_zone_none_of_its_lines(self):
        old = self.by_zone(self.old_list)["Garden"]
        self.assertTrue(any(r["file"] == "Leak.md" for _, rows in old["groups"] for r in rows))
        self.assertNotIn("Garden", self.by_zone(self.new_list))
        self.assertEqual([], self.zone("Garden")["todo"]["tasks"])

    def test_the_fixture_covers_what_the_card_reads(self):
        home = self.by_zone(self.new_list)["Home"]
        names = [g for g, _ in home["groups"]]
        self.assertEqual(["Inbox", "Soon", "Someday", "In thread notes"], names[:3] + names[-1:])
        rows = [r for _, rs in home["groups"] for r in rs]
        self.assertTrue(any(r["waiting"] and r["late"] for r in rows))
        self.assertTrue(any(r["unsure"] for r in rows))
        self.assertTrue(any(r["project"] == "Sys" or r["label"] == "Job" and r["link"] for r in rows))
        self.assertEqual(1, len(home["done"]))
        self.assertFalse(any("fence" in r["text"] for r in rows))
        self.assertFalse(any("template line" in r["text"] for r in rows))

    def test_a_line_names_the_note_the_view_model_says(self):
        tasks = {t["text"]: t for t in self.zone("Home")["todo"]["tasks"]}
        self.assertEqual("Zones/Home/Cedar/Threads/Fence/Fence.md", tasks["Order posts"]["note"])
        self.assertEqual(("Cedar", "Fence"), (tasks["Order posts"]["project"], tasks["Order posts"]["tname"]))
        self.assertEqual("System/Sys/Threads/Job/Job.md", tasks["system one"]["note"])
        self.assertEqual("Zones/Home/Maple/Threads/Leaf/Leaf.md", tasks["A line in the thread note"]["note"])
        self.assertIsNone(tasks["Unplaced thing"]["note"])

    def test_the_done_lines_are_those_ticked_on_the_day_given(self):
        done = self.zone("Home")["todo"]["done"]
        self.assertEqual([], done if self.model["today"] != "2026-11-22" else [])
        again = view.build(self.root, only=("todo",), today=TODAY)
        self.assertEqual(["done today"], [t["text"].split(":")[-1].strip() for t in next(z for z in again["zones"] if z["name"] == "Home")["todo"]["done"]])
        self.assertEqual("2026-11-22", again["today"])

    def test_the_reader_answers_as_the_pages_own_todo_lines_does(self):
        # The extra keeps an editing copy of the reading half, so an update of one can never change what the other reads.
        tl = status.todo_lines()
        vt = view._todo()
        lib = view._lib()
        for name in ("Home", "Work"):
            zone = self.root / "Zones" / name
            paths = vt.notes(zone, lib.live_files, view._work()._within)
            self.assertEqual(sorted(tl.notes(str(zone))), sorted(paths), name)
            self.assertEqual(json.loads(json.dumps(tl.tasks(str(zone)))), json.loads(json.dumps(vt.tasks(zone, paths))), name)
            self.assertEqual(json.loads(json.dumps(tl.done_on(str(zone), TODAY))), json.loads(json.dumps(vt.done_on(zone, paths, TODAY))), name)

    def test_a_scoped_build_holds_the_todo_of_its_zones_alone(self):
        scoped = view.build(self.root, scope=["Work"], only=("todo",), today=TODAY)
        self.assertEqual(["Work"], [z["name"] for z in scoped["zones"]])
        self.assertEqual(["Work thing"], [t["text"] for t in scoped["zones"][0]["todo"]["tasks"]])
        self.assertNotIn("Order posts", json.dumps(scoped))

    def test_the_page_draws_the_todo_from_one_build_of_the_view(self):
        model = view.build(self.root, only=("todo",), today=TODAY)
        calls = []
        with mock.patch.object(status, "view_model", side_effect=lambda *a, **k: calls.append(1)):
            lists = status.todo_list(self.root, self.link, TODAY, model)
        self.assertEqual([], calls)
        self.assertEqual(self.new_list, lists)


class TestShadowQuestions(Case):
    """The questions that wait (#650, 0.78.0): the view model finds the files in each `Needs you` folder; the page draws a
    row for each. Held to v0.77.0's own `question_needs`, frozen."""

    def setUp(self):
        super().setUp()
        self.old_rows = old_reads_0770(status, "QUESTIONS")["question_needs"](self.root, TODAY)
        self.new_rows = status.question_needs(self.root, TODAY)

    def test_the_rows_are_the_old_rows_except_a_link_out_of_its_zone(self):
        keep = lambda rows: [r for r in rows if r["zone"] not in ("Linked", "Garden")]  # noqa: E731
        self.assertEqual(keep(self.old_rows), keep(self.new_rows))
        self.assertEqual(["Home"], sorted({r["zone"] for r in self.new_rows}))

    def test_the_fixture_covers_what_the_card_reads(self):
        asks = [r["text"] for r in self.new_rows]
        self.assertEqual(["Cedar: Put off, due", "Cedar: Which fence?", "Fence: Thread question", "File this mail?"], sorted(asks))
        self.assertTrue(any("data-q=" in r["act"] and "intake-answer" in r["act"] for r in self.new_rows))

    def test_a_linked_zone_and_a_linked_project_or_file_hold_none_of_another_zones_questions(self):
        self.assertTrue({"Linked", "Garden"} <= {r["zone"] for r in self.old_rows})
        self.assertNotIn("questions", self.zone("Linked"))
        self.assertEqual([], self.zone("Garden")["questions"])

    def test_a_scoped_build_holds_the_questions_of_its_zones_alone(self):
        scoped = view.build(self.root, scope=["Work"], only=("questions",), today=TODAY)
        self.assertEqual([[]], [z["questions"] for z in scoped["zones"]])
        self.assertNotIn("fence", json.dumps(scoped).lower())

    def test_the_page_draws_the_rows_from_one_build_of_the_view(self):
        model = view.build(self.root, only=("questions",), today=TODAY)
        with mock.patch.object(status, "view_model", side_effect=AssertionError("built again")):
            self.assertEqual(self.new_rows, status.question_needs(self.root, TODAY, model))


class TestShadowWikis(Case):
    """The wikis' logs (#650, 0.78.0): the view model reads each log; the page shortens a title and names a page. Held to
    v0.77.0's own `wikis`, frozen. A wiki crosses every zone, as it did: a scoped build holds none."""

    def setUp(self):
        super().setUp()
        self.old_w = old_reads_0770(status, "WIKIS")
        self.old_rows = self.old_w["wikis"](self.root)
        self.new_rows = status.wikis(self.root)

    def test_the_rows_are_the_old_rows_except_a_log_that_is_a_link_out_of_its_wiki(self):
        self.assertEqual([r for r in self.old_rows if r["name"] != "Leaky"], self.new_rows)
        self.assertIn("Leaky", [r["name"] for r in self.old_rows])

    def test_the_fixture_covers_what_the_card_reads(self):
        by = {r["name"]: r for r in self.new_rows}
        self.assertEqual(["Knowledge", "Meetings", "Odd"], sorted(by))
        self.assertEqual(3, by["Meetings"]["count"])
        self.assertEqual("A page that is not there", by["Meetings"]["title"])
        self.assertIsNone(by["Meetings"]["page"])                       # the page is not there
        self.assertEqual("Paper", by["Knowledge"]["title"])
        self.assertTrue(by["Odd"]["unread"])
        self.assertIsNone(by["Odd"]["when"])

    def test_a_title_the_log_wrote_as_markdown_is_read_as_plain_words(self):
        write(self.root / "Wikis" / "Knowledge" / "wiki" / "log.md", "- 2026-11-10: A **bold** line with `code`; and more\n")
        row = next(r for r in status.wikis(self.root) if r["name"] == "Knowledge")
        self.assertEqual("A bold line with code", row["title"])
        self.assertEqual(next(r for r in self.old_w["wikis"](self.root) if r["name"] == "Knowledge"), row)

    def test_the_entries_the_page_reads_are_the_old_ones(self):
        text = (self.root / "Wikis" / "Knowledge" / "wiki" / "log.md").read_text(encoding="utf-8")
        self.assertEqual(self.old_w["log_entries"](text), status.log_entries(text))

    def test_a_scoped_build_holds_no_wiki(self):
        self.assertEqual([], view.build(self.root, scope=["Home"], only=("wikis",))["wikis"])

    def test_the_page_draws_the_rows_from_one_build_of_the_view(self):
        model = view.build(self.root, only=("wikis",))
        with mock.patch.object(status, "view_model", side_effect=AssertionError("built again")):
            self.assertEqual(self.new_rows, status.wikis(self.root, model))


class TestShadowRepos(Case):
    """The repositories (#650, 0.78.0): the view model asks git; the page draws what it says. Held to v0.77.0's own `repos`,
    frozen. Each repository is its own: nothing adds two."""

    def setUp(self):
        super().setUp()
        from fixtures import commit_all, git_init
        for place in (self.root, self.root / "Zones" / "Home", self.root / "Zones" / "Work", self.root / "Wikis"):
            git_init(place)
            commit_all(place)
        write(self.root / "Zones" / "Home" / "Cedar" / "new.md", "x\n")
        hub = self.root / "Zones" / "Work" / "Acme Review" / "Acme Review.md"
        hub.write_text(hub.read_text() + "\nEdited.\n")
        self.old_rows = old_reads_0770(status, "REPOS")["repos"](self.root)
        self.new_rows = status.repos(self.root)

    def test_the_rows_are_the_old_rows_except_a_zone_that_is_a_link(self):
        self.assertEqual([r for r in self.old_rows if r["name"] != "Linked"], self.new_rows)
        self.assertIn("Linked", [r["name"] for r in self.old_rows])

    def test_the_fixture_covers_what_the_card_reads(self):
        by = {r["name"]: r for r in self.new_rows}
        self.assertTrue({"Workspace", "Home", "Work", "Wikis"} <= set(by))
        self.assertEqual(1, by["Home"]["dirty"])
        self.assertEqual(("untracked",), by["Home"]["changes"][0][1])
        self.assertIsNotNone(by["Work"]["since"])
        self.assertIsNotNone(by["Work"]["last"])
        self.assertEqual(self.root, by["Workspace"]["folder"])

    def test_a_scoped_build_holds_the_repositories_of_its_zones_alone(self):
        scoped = view.build(self.root, scope=["Work"], only=("repos",))["repos"]
        self.assertEqual(["Work"], [r["name"] for r in scoped])
        self.assertNotIn("new.md", json.dumps(scoped))

    def test_a_record_has_the_fields_the_docs_example_names(self):
        import re
        text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
        doc = json.loads(re.search(r"```json\n(.*?)\n```", text[text.index("#### The view model"):], re.S).group(1))
        record = view.build(self.root, only=("repos",))["repos"][0]
        self.assertEqual(set(doc["repos"][0]), set(record))

    def test_building_the_whole_view_writes_nothing_even_to_a_repository(self):
        before = snapshot(self.root)
        json.dumps(view.build(self.root))
        self.assertEqual(before, snapshot(self.root))

    def test_a_git_that_fails_is_never_clean(self):
        run = subprocess.run

        def slow(cmd, *args, **kw):
            if "status" in cmd:
                raise subprocess.TimeoutExpired(cmd, 30)
            return run(cmd, *args, **kw)
        with mock.patch.object(subprocess, "run", slow):
            rows = status.repos(self.root)
        self.assertTrue(all(r["unread"] for r in rows))

    def test_the_page_draws_the_rows_from_one_build_of_the_view(self):
        model = view.build(self.root, only=("repos",))
        with mock.patch.object(status, "view_model", side_effect=AssertionError("built again")):
            self.assertEqual(self.new_rows, status.repos(self.root, model))

    def test_the_helpers_the_tests_still_call_answer_as_the_view_does(self):
        porcelain = " M a.md\0?? b.md\0R  new.md\0old.md\0UU c.md\0"
        self.assertEqual(view.changed_files(porcelain), status.changed_files(porcelain))
        self.assertEqual(old_reads_0770(status, "REPOS")["changed_files"](porcelain), status.changed_files(porcelain))


class TestShadowExample(Case):
    """The worked example's marker (#650, 0.78.0): the view model names the zone it is in, as the page's old read did."""

    def mark(self, zone, says=None):
        write(self.root / "Zones" / zone / ".example.json", json.dumps({"zone": says or zone}))

    def test_the_zone_is_the_one_the_old_read_names(self):
        old = old_reads_0770(status, "EXAMPLE")["example_zone"]
        self.assertIsNone(status.example_zone(self.root))
        self.assertEqual(old(self.root), status.example_zone(self.root))
        self.mark("Home")
        self.assertEqual("Home", status.example_zone(self.root))
        self.assertEqual(old(self.root), status.example_zone(self.root))

    def test_a_marker_that_names_another_zone_is_not_the_example(self):
        self.mark("Home", says="Work")
        self.assertIsNone(status.example_zone(self.root))
        self.assertIsNone(old_reads_0770(status, "EXAMPLE")["example_zone"](self.root))

    def test_a_zone_that_is_a_link_is_never_the_example(self):
        self.mark("Home")
        self.assertEqual("Home", view.build(self.root, only=("example",))["example"])
        (self.root / "Zones" / "Home" / ".example.json").unlink()
        self.mark("Home", says="Linked")                       # Linked is a link to Home: its marker names it, and it is no zone
        self.assertIsNone(view.build(self.root, only=("example",))["example"])

    def test_a_scoped_build_names_the_example_only_among_its_zones(self):
        self.mark("Home")
        self.assertIsNone(view.build(self.root, scope=["Work"], only=("example",))["example"])
        self.assertEqual("Home", view.build(self.root, scope=["Home"], only=("example",))["example"])


class TestShadowGraph(Case):
    """Explore's graph (#650, 0.78.0): the view model lists the notes and the links between them; the page draws a node for
    each. Held to v0.77.0's own `graph`, frozen, on the workspace with every link taken out; the links are tested apart."""

    def setUp(self):
        super().setUp()
        self.old_g = old_reads_0770(status, "GRAPH")["graph"]

    def clean(self):
        """The workspace with no link in Zones/ or Wikis/, where the old read and the new agree."""
        for p in list(self.root.rglob("*")):
            if p.is_symlink() and p != self.root / "System" / "tools":
                p.unlink()

    def both(self, **kw):
        link = status.Links(self.root)
        T = status.threads(self.root)
        args = (self.root, T, link, dt.datetime(2026, 11, 22, 12, 0))
        return self.old_g(*args, **kw), status.graph(*args, **kw)

    def test_the_graph_is_the_old_graph(self):
        self.clean()
        old, new = self.both()
        self.assertEqual(old, new)
        self.assertGreater(len(new["nodes"]), 20)
        self.assertGreater(len(new["edges"]), 5)

    def test_the_graph_is_the_old_graph_with_every_button_and_a_desk_and_a_late_ring(self):
        self.clean()
        desk = {str(self.root / "Zones" / "Home" / "Cedar"): "cmux"}
        old, new = self.both(cmux=True, actions=True, desk=desk, drive=True, urgent={("Home", "Cedar", "Fence")})
        self.assertEqual(old, new)
        self.assertTrue(any("lt" in n for n in new["nodes"]))

    def test_the_fixture_covers_what_the_graph_reads(self):
        self.clean()
        _, new = self.both()
        names = {n["n"] for n in new["nodes"]}
        self.assertIn("Fence", names)
        self.assertNotIn("An idea", names)                                        # the vault excludes it
        self.assertFalse({"Inbox note", "Archived note", "Agents", "Hidden note"} & names)               # Inbox, archive, instructions, hidden
        self.assertTrue(any(k == "domain" for _, k in new["kinds"]))              # a kind found from three pages
        self.assertTrue(new["ce"])                                                # two people who share a meeting

    def test_a_note_that_is_a_link_out_of_its_zone_and_a_zone_that_is_a_link_add_none_of_their_notes(self):
        model = view.build(self.root, only=("graph",))["graph"]
        places = {p["name"] for p in model["places"]}
        self.assertNotIn("Linked", places)
        self.assertNotIn("Zones/Garden/Plot/Peek.md", [n["path"] for n in model["notes"]])
        old, new = self.both()
        self.assertIn("Linked", {n["z"] for n in old["nodes"]})                    # the old graph drew the link's notes twice
        self.assertNotIn("Linked", {n["z"] for n in new["nodes"]})
        self.assertTrue(any(n["z"] == "Garden" and n["m"] == "Plot/Peek" for n in old["nodes"]))
        self.assertFalse(any(n["z"] == "Garden" and n["m"] == "Plot/Peek" for n in new["nodes"]))

    def test_a_note_that_is_a_link_to_a_file_outside_the_workspace_stays(self):
        outside = Path(self._tmp.name).resolve() / "Shared" / "Shared notes.md"
        write(outside, "---\ntitle: Shared notes\n---\n\n- [ ] A line in a shared file\n")
        os.symlink(str(outside), str(self.root / "Zones" / "Home" / "Cedar" / "Shared notes.md"))
        paths = [n["path"] for n in view.build(self.root, only=("graph",))["graph"]["notes"]]
        self.assertIn("Zones/Home/Cedar/Shared notes.md", paths)
        tasks = view.build(self.root, only=("todo",), today=TODAY)["zones"]
        home = next(z for z in tasks if z["name"] == "Home")["todo"]["tasks"]
        self.assertIn("A line in a shared file", [t["text"] for t in home])

    def test_a_scoped_build_holds_the_notes_of_its_zones_and_no_wiki(self):
        scoped = view.build(self.root, scope=["Home"], only=("graph",))["graph"]
        self.assertEqual(["Home"], [p["name"] for p in scoped["places"]])
        self.assertTrue(all(n["place"] == "Home" for n in scoped["notes"]))
        for a, b in scoped["edges"]:
            self.assertEqual("Home", scoped["notes"][a]["place"])
            self.assertEqual("Home", scoped["notes"][b]["place"])
        self.assertNotIn("paper", json.dumps(scoped["notes"]))

    def test_a_link_names_a_note_by_path_or_by_name_and_never_itself(self):
        model = view.build(self.root, only=("graph",))["graph"]
        paths = [n["path"] for n in model["notes"]]
        pairs = {(paths[a], paths[b]) for a, b in model["edges"]}
        pairs = {frozenset(p) for p in pairs}
        self.assertIn(frozenset(("Zones/Home/Cedar/Cedar.md", "Zones/Home/Loose.md")), pairs)
        self.assertIn(frozenset(("Zones/Home/Cedar/Cedar.md", "Zones/Home/Cedar/Threads/Gate/Gate.md")), pairs)   # by path
        self.assertTrue(all(a < b for a, b in model["edges"]))

    def test_the_page_draws_the_graph_from_one_build_of_the_view(self):
        self.clean()
        model = view.build(self.root, only=("graph",))
        link, T = status.Links(self.root), status.threads(self.root)
        with mock.patch.object(status, "view_model", side_effect=AssertionError("built again")):
            drawn = status.graph(self.root, T, link, dt.datetime(2026, 11, 22, 12, 0), model=model)
        self.assertEqual(self.both()[1], drawn)


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


class TestDocumentedShape(Case):
    """The acceptance line of #650: the view model's JSON shape is documented in docs/architecture.md, with one example. The
    example names every field the view model builds, at each level, so a field added without the docs fails here."""

    def example(self):
        import re
        text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
        start = text.index("#### The view model")
        return json.loads(re.search(r"```json\n(.*?)\n```", text[start:], re.S).group(1))

    def test_the_example_names_every_top_level_field(self):
        self.assertEqual(set(self.model), set(self.example()))

    def test_the_example_names_every_field_of_a_zone_and_of_what_it_holds(self):
        doc, zone = self.example()["zones"][0], self.zone("Home")
        self.assertEqual(set(zone), set(doc))
        self.assertEqual(set(zone["todo"]), set(doc["todo"]))
        self.assertEqual(set(zone["todo"]["tasks"][0]), set(doc["todo"]["tasks"][0]))
        self.assertEqual(set(zone["questions"][0]), set(doc["questions"][0]))
        self.assertEqual(set(zone["work"][0]), set(doc["work"][0]))

    def test_the_example_names_every_field_of_the_other_parts(self):
        doc = self.example()
        self.assertEqual(set(self.model["wikis"][0]), set(doc["wikis"][0]))
        self.assertEqual(set(self.model["graph"]), set(doc["graph"]))
        self.assertEqual(set(self.model["graph"]["notes"][0]), set(doc["graph"]["notes"][0]))
        self.assertEqual(set(self.model["graph"]["places"][0]), set(doc["graph"]["places"][0]))
        self.assertEqual(set(self.model["system"][0]), set(doc["system"][0]))
        self.assertEqual(set(self.model["queues"]["inbox"][0]), set(doc["queues"]["inbox"][0]))


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
