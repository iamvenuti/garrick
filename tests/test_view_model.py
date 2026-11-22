"""The view model (#650): `System/tools/view.py` builds one JSON document of what the App shows, and the page only draws it.

    python3 -m unittest test_view_model

The shadow test. On each fixture workspace the page's old reads, frozen word for word in `old_status_reads.py` as
v0.76.0 had them, and the view model are compared field by field. Every difference is written here:

    difference                                               why the view model is right
    ------------------------------------------------------   -----------------------------------------------------------
    A zone folder that is a link: the old inbox read counted a link is no zone (work.py). The old read gave one zone's
    the files of the folder it points at, under the link's    files under a second name: a wall defect. The view model
    name.                                                      lists the link with no work and no inbox.
    An `Inbox` that is a link to a folder outside its zone:    The count must be of one zone. The view model leaves an
    the old read counted that folder's files.                  Inbox out whose real path is outside the zone it sits in.

    A workspace with no System/tools/garrick_lib.py: the old   The core always has its own `resume_hash`, so the view model
    read could not hash a resume point, so a checkpoint never  can tell a checkpoint written against an older resume point
    read as out of date.                                       from a current one (TestNamedDifferences).

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
    write(root / "System" / "Sys" / "Sys.md", "---\ntitle: Sys\ntype: project\nstatus: active\n---\n\n# Sys\n")
    return root


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
        old = self.old["threads"](self.root)
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
            self.assertEqual({k: dict(v, hub=self.root / v["hub"] if v["hub"] else None) for k, v in z["projects"].items()},
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


class TestShadowInbox(Case):
    def test_inbox_matches_the_old_read_except_the_named_differences(self):
        old = {name: (folder, n) for name, folder, n in self.old["inboxes"](self.root)}
        new = {q["place"]: (self.root / q["folder"], q["count"]) for q in self.model["queues"]["inbox"]}
        # Difference 1: a zone that is a link has no inbox here. Difference 2: nor has an Inbox that leads out of its zone.
        self.assertEqual({"Linked", "Garden"}, set(old) - set(new))
        for name in set(new):
            self.assertEqual(old[name], new[name], name)

    def test_the_wiki_inbox_is_one_wiki_and_the_zones_are_one_zone_each(self):
        counts = {q["place"]: (q["kind"], q["count"]) for q in self.model["queues"]["inbox"]}
        self.assertEqual(("wiki", 1), counts["Meetings"])
        self.assertEqual(("zone", 2), counts["Home"])     # the dot file is not counted
        self.assertNotIn("Linked", counts)
        self.assertNotIn("Garden", counts)


class TestNamedDifferences(unittest.TestCase):
    def test_a_checkpoint_is_out_of_date_where_the_old_read_had_no_library_to_hash_with(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_workspace(Path(tmp).resolve() / "W", tools=False)
            old = old_reads(status)["threads"](root)
            fence = next(r for r in old["Home"]["rows"] if r["thread"] == "Fence")
            new = next(p for p in view.build(root)["zones"][1]["work"] if p["thread"] == "Fence")
            self.assertFalse(fence["checkpoint"]["stale"])
            self.assertTrue(new["checkpoint"]["stale"])


class TestWalls(Case):
    def test_a_link_is_no_zone_and_carries_no_work(self):
        z = self.zone("Linked")
        self.assertTrue(z["linked"])
        self.assertEqual([], z["work"])

    def test_a_thread_folder_linked_into_another_zone_is_left_out(self):
        garden = self.zone("Garden")
        self.assertEqual([], [p for p in garden["work"] if p["thread"] == "Leak"])
        self.assertEqual("Plot", garden["work"][0]["project"])

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
