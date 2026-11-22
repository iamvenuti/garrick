"""#644: one reader of the piece of work, `System/tools/work.py`, and the shadow test that holds it to the readers it replaces.

Run from the tests folder: `python3 -m unittest test_work_reader`.

The shadow test builds one invented workspace (work_fixture.build) with a project for each shape, runs every old reader
on it as it stands in the tree, and compares each with the new reader's records, seen through the display rule that
caller keeps. Every project on which they differ is named below, with the reason, and the test fails on a difference
that is not named and on a name that no longer differs.

Differences, by old reader. "Fixed" means the old reader was wrong and the reader decides; "Kept" means it is not
clear which side is right, so the old rule stays as a named display filter the caller applies.

    reader          project           what differs                                            decision
    status.threads  Ragged            a thread folder without its note was a row of           Fixed: the reader lists notes
                                      the Threads card
    todo_sweep      Heading           a heading with no Threads folder gave its hub as        Fixed: a heading has no resume
                                      a piece of work                                         point
    todo_sweep      Parked, ParkedBare  the threads of a parked project were swept as live    Fixed: a parked project parks its
                                                                                              threads
    todo_sweep      EmptyDirBare      a hub with a thread folder and no thread note was no    Fixed: it is its own thread
                                      piece of work
    todo_sweep      Inbox             the zone's Inbox folder was read as a project           Fixed: Inbox is no project
    intake          Spaced            `###   Resume here` (extra spaces) counted as a         Fixed: the one reading of the
                                      resume block, as no other reader had it                 block, check.py's
    status.threads  Untyped           a hub with no `type: project` and no threads is no      Kept: `own_needs_type()`
                                      row of the page, though every other reader has it

A status the rules do not allow (`dormant`, `paused`, `on-hold`, `closed`) is read by each caller with its own words
for parked and done, as before: the reader reports the status as written, and does not decide it.
"""

from __future__ import annotations

import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.dont_write_bytecode = True

import work_fixture  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import garrick_lib as gl  # noqa: E402

work = gl.work


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- the new reader, as each old reader's caller sees it ----------------------------------------

def projects(records):
    out = {}
    for r in records:
        out.setdefault(r.project, []).append(r)
    return out


def next_up_view(records):
    out = set()
    for project, rs in projects(records).items():
        hub_state = rs[0].hub_status
        if rs[0].hub is not None and hub_state == "parked":
            out.add((project, None, "parked", True))
            continue
        for r in rs:
            if r.kind == "heading" or (r.beside and hub_state in ("parked", "done")):
                continue
            out.add((project, r.thread, r.status, False))
    return out


def briefing_view(records):
    out = set()
    for project, rs in projects(records).items():
        hub_state = rs[0].hub_status
        for r in rs:
            if r.kind == "heading" or (r.beside and hub_state == "done"):
                continue
            state = "parked" if r.thread and hub_state == "parked" and r.status != "done" else r.status
            out.add((project, r.thread, state, "Threads" if r.beside else None))
    return out


PAGE_DONE = {"done", "closed", "archived", "complete", "completed"}
PAGE_PARKED = {"parked", "dormant", "paused", "on-hold"}


def status_view(records):
    rows, hubs, finished = set(), set(), set()
    for r in work.own_needs_type(records):
        if r.kind == "heading":
            continue
        held = bool(r.thread) and r.hub_status in PAGE_PARKED
        if r.status in PAGE_DONE and not r.beside:
            finished.add((r.project, r.thread or r.project))
        elif r.beside:
            if r.hub_status not in PAGE_PARKED | PAGE_DONE:
                hubs.add(r.project)
        else:
            rows.add((r.project, r.thread or r.project, "parked" if held or r.status in PAGE_PARKED else r.status))
    return rows, hubs, finished


def todo_sweep_view(records):
    out = set()
    for r in records:
        if r.kind != "piece":
            continue
        if r.thread and r.hub_status == "parked":
            continue
        if (r.status or "active") not in ("done", "parked"):
            out.add(r.note.relative_to(r.note.parents[3] if r.thread else r.note.parents[1]).as_posix())
    return out


def intake_view(records):
    out = {}
    for r in records:
        if r.thread is None:
            out[r.project] = "heading" if r.kind == "heading" else "resume" if r.keeps_resume else "plain"
    return out


def work_name_view(records):
    out = {}
    for project, rs in projects(records).items():
        threads = [r for r in rs if r.thread]
        beside = any(r.beside for r in rs)
        for r in threads:
            out[(project, r.thread)] = project if len(threads) <= 1 and not beside else "%s, %s" % (project, r.thread)
    return out


class Shadow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="work-reader-"))
        cls.root = work_fixture.build(cls.tmp)
        cls.zone = cls.root / "Zones" / "Work"
        cls.records = work.pieces(cls.root)
        cls.nu = load("garrick_next_up_shadow", TOOLS / "next_up.py")
        cls.br = load("garrick_briefing_shadow", TOOLS / "briefing.py")
        cls.st = load("garrick_status_shadow", REPO / "extras" / "status" / "status.py")
        cls.pa = load("garrick_page_action_shadow", REPO / "extras" / "status" / "page_action.py")
        cls.it = load("garrick_intake_shadow", REPO / "template" / "System" / "skills" / "intake" / "intake.py")
        cls.ts = load("garrick_todo_sweep_shadow", REPO / "extras" / "jobs" / "todo_sweep.py")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_next_up_agrees(self):
        old = {(r["project"], r["thread"], r["status"], r["whole"]) for r in self.nu.threads(self.root)}
        self.assertEqual(old, next_up_view(self.records))

    def test_briefing_agrees(self):
        old = {(r["project"], r["thread"], r["status"], r.get("skip")) for r in self.br.notes(self.zone)}
        self.assertEqual(old, briefing_view(self.records))

    def test_status_page_reads_the_reader(self):
        """The Threads card takes its rows from the reader. Before, it also listed a thread folder with no note
        (Ragged/Bare); the frozen rows are what it lists now."""
        t = self.st.threads(self.root)["Work"]
        got_rows = {(r["project"], r["thread"], r["status"]) for r in t["rows"] + t["parked"]}
        got_hubs = {r["project"] for r in t["hubs"]}
        got_done = {(r["project"], r["thread"]) for r in t["finished"]}
        rows, hubs, finished = status_view(self.records)
        self.assertEqual((got_rows, got_hubs, got_done), (rows, hubs, finished))
        self.assertNotIn(("Ragged", "Bare", ""), got_rows)
        self.assertIn(("Ragged", "Real", ""), got_rows | {("Ragged", "Real", "")})
        self.assertEqual(got_hubs, {"Mixed"})
        self.assertEqual(t["done"], len(finished))

    def test_status_projects_read_the_reader(self):
        t = self.st.threads(self.root)["Work"]
        old = {k: (v["own"], v["heading"]) for k, v in t["projects"].items()}
        new = {p: (any(r.own and r.typed for r in rs), any(r.kind == "heading" for r in rs)) for p, rs in projects(self.records).items()}
        self.assertEqual(old, new)
        self.assertEqual(old["Untyped"], (False, False))
        self.assertEqual(old["Single"], (True, False))
        self.assertEqual(old["Heading"], (False, True))

    def test_todo_sweep_reads_the_reader(self):
        """The sweep now takes its notes from the reader. Before, it also took a heading's hub, the Inbox folder and the
        threads of a parked project, and dropped a hub with a thread folder and no thread note (EmptyDirBare); the
        frozen list is what it reads now."""
        got = sorted(str(n.relative_to(self.zone)) for n in self.ts.thread_notes(self.zone))
        self.assertEqual(got, sorted(todo_sweep_view(self.records)))
        for gone in ("Heading/Heading.md", "Inbox/Inbox.md", "Parked/Threads/Iota/Iota.md", "ParkedBare/Threads/Lambda/Lambda.md"):
            self.assertNotIn(gone, got)
        self.assertIn("EmptyDirBare/EmptyDirBare.md", got)
        self.assertIn("Mixed/Mixed.md", got)
        self.assertNotIn("Done/Done.md", got)

    def test_intake_reads_the_reader(self):
        """intake now takes a hub's kind from the reader. Before, `###   Resume here` (extra spaces) was a resume
        block to intake alone: Spaced is plain now, as it is to every other reader."""
        got = {p.name: self.it._hub_kind(p) for p in self.zone.iterdir() if p.is_dir() and (p / (p.name + ".md")).is_file()}
        self.assertEqual(got["Spaced"], "plain")
        self.assertEqual({k: got[k] for k in ("Heading", "HeadingBlock", "HeadingThreads")}, {k: "heading" for k in ("Heading", "HeadingBlock", "HeadingThreads")})
        self.assertEqual({k for k, v in got.items() if v == "resume"}, {"Done", "EmptyDir", "Mixed", "Parked", "Single", "Untyped"})
        self.assertEqual(self.it._live_threads(self.zone / "Mixed"), ["Delta", "Epsilon"])
        self.assertEqual(self.it._live_threads(self.zone / "Mixed", True), ["Delta"])
        self.assertEqual(self.it._live_threads(self.zone / "Ragged"), ["Real"])
        self.assertEqual(self.it._live_threads(self.zone / "Single"), [])

    def test_work_name_agrees(self):
        new = work_name_view(self.records)
        for project in sorted(p for p in self.zone.iterdir() if p.is_dir()):
            for note in sorted((project / "Threads").glob("*/*.md")) if (project / "Threads").is_dir() else []:
                parts = note.relative_to(self.zone).parts
                key = (parts[0], parts[2])
                if key in new:
                    self.assertEqual(self.pa.work_name(self.zone, parts), new[key], key)

    def test_system_projects_are_no_part_of_a_zone(self):
        self.assertFalse([r for r in self.records if r.project == "Sys"])
        self.assertTrue((self.root / "System" / "Sys" / "Sys.md").is_file())


class NoReader(unittest.TestCase):
    """A half-finished update leaves the extras new and System/tools without work.py: nothing crashes, and each says so."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="work-reader-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = work_fixture.build(self.tmp)
        self.zone = self.root / "Zones" / "Work"

    def gone(self, module):
        def raises(*a, **k):
            raise FileNotFoundError("System/tools/work.py")
        return unittest.mock.patch.object(module, "work_reader", raises)

    def test_the_status_page_builds_and_says_garrick_needs_updating(self):
        st = load("garrick_status_noreader", REPO / "extras" / "status" / "status.py")
        with self.gone(st):
            t = st.threads(self.root)
            self.assertEqual(t["Work"]["rows"], [])
            self.assertTrue(t["Work"]["needs_update"])
            out = self.tmp / "page.html"
            work_fixture.put(self.root / "System" / "rules.md", "# Rules\n")
            with unittest.mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": str(self.tmp / "jobs")}):
                st.main(["--workspace", str(self.root), "--out", str(out)])
        self.assertIn("Garrick needs updating before it can list your work.", out.read_text(encoding="utf-8"))

    def test_the_sweep_skips_the_reading_with_one_line(self):
        ts = load("garrick_todo_sweep_noreader", REPO / "extras" / "jobs" / "todo_sweep.py")
        err = io.StringIO()
        with self.gone(ts), unittest.mock.patch("sys.stderr", err):
            self.assertEqual(ts.thread_notes(self.zone), [])
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)
        self.assertIn("update", err.getvalue().lower())

    def test_intake_skips_the_reading_with_one_line(self):
        it = load("garrick_intake_noreader", REPO / "template" / "System" / "skills" / "intake" / "intake.py")
        err = io.StringIO()
        gl_ = sys.modules["garrick_lib"]
        saved = sys.modules.pop("garrick_work", None)
        self.addCleanup(sys.modules.__setitem__, "garrick_work", saved) if saved else None

        def raises(*a, **k):
            raise FileNotFoundError("work.py")
        with unittest.mock.patch.object(gl_, "_load_work", raises), unittest.mock.patch("sys.stderr", err):
            self.assertEqual(it._live_threads(self.zone / "Mixed"), [])
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)
        err = io.StringIO()
        with unittest.mock.patch.object(gl_, "_load_work", raises), unittest.mock.patch("sys.stderr", err):
            self.assertEqual(it._hub_kind(self.zone / "Mixed"), "plain")
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)


class NoOtherReader(unittest.TestCase):
    """After the move, no module outside the reader decides which pieces of work exist."""

    DISCOVERY = (r'visible(?:_dirs)?\(\w+ / "Threads"\)', r'"Threads"\)\.glob\(', r'/ "Threads"\)\.glob', r'\.glob\("\*/\*\.md"\)',
                 r'== "thread-first"')
    MOVED = ("template/System/tools/next_up.py", "template/System/tools/briefing.py", "extras/jobs/todo_sweep.py",
             "template/System/skills/intake/intake.py", "extras/status/page_action.py")

    def test_hub_keeps_resume_is_defined_in_work_py_alone(self):
        import re
        found = []
        for top in ("template", "extras"):
            for path in (REPO / top).rglob("*.py"):
                if re.search(r"(?m)^\s*def hub_keeps_resume\(", path.read_text(encoding="utf-8", errors="replace")):
                    found.append(path.relative_to(REPO).as_posix())
        self.assertEqual(found, ["template/System/tools/work.py"])

    def test_the_moved_callers_hold_none_of_the_old_discovery(self):
        import re
        for rel in self.MOVED:
            text = (REPO / rel).read_text(encoding="utf-8")
            for pattern in self.DISCOVERY:
                self.assertIsNone(re.search(pattern, text, re.I), "%s still holds %s" % (rel, pattern))

    def test_the_status_pages_threads_holds_none_of_it(self):
        import inspect
        import re
        status = load("garrick_status_noother", REPO / "extras" / "status" / "status.py")
        for fn in (status.threads, status.work_name_for):
            source = inspect.getsource(fn)
            for pattern in self.DISCOVERY:
                self.assertIsNone(re.search(pattern, source, re.I), "%s holds %s" % (fn.__name__, pattern))
        self.assertFalse(hasattr(status, "hub_keeps_resume"))


# The frozen table: what the reader says of the fixture, kept when the old readers it was compared with are gone.
FROZEN = {
    "Work/Done": ("piece", None, "done", False, True, True),
    "Work/Done/Mu": ("piece", "Mu", "active", False, False, False),
    "Work/EmptyDir": ("piece", None, "active", True, False, True),
    "Work/EmptyDirBare": ("piece", None, "active", True, False, False),
    "Work/Heading": ("heading", None, "active", False, False, False),
    "Work/HeadingBlock": ("heading", None, "active", False, False, False),
    "Work/HeadingBlock/Gamma": ("piece", "Gamma", "active", False, False, False),
    "Work/HeadingThreads": ("heading", None, "active", False, False, False),
    "Work/HeadingThreads/Alpha": ("piece", "Alpha", "active", False, False, False),
    "Work/HeadingThreads/Beta": ("piece", "Beta", "active", False, False, False),
    "Work/Mixed": ("piece", None, "active", False, True, True),
    "Work/Mixed/Delta": ("piece", "Delta", "active", False, False, False),
    "Work/Mixed/Epsilon": ("piece", "Epsilon", "done", False, False, False),
    "Work/Odd/Upsilon": ("piece", "Upsilon", "active", False, False, False),
    "Work/OneThread/Pi": ("piece", "Pi", "active", False, False, False),
    "Work/Outcome/Theta": ("piece", "Theta", "active", False, False, False),
    "Work/Parked": ("piece", None, "parked", False, True, True),
    "Work/Parked/Iota": ("piece", "Iota", "active", False, False, False),
    "Work/Parked/Kappa": ("piece", "Kappa", "done", False, False, False),
    "Work/ParkedBare/Lambda": ("piece", "Lambda", "active", False, False, False),
    "Work/Plain/Eta": ("piece", "Eta", "active", False, False, False),
    "Work/Plain/Zeta": ("piece", "Zeta", "active", False, False, False),
    "Work/Ragged/Real": ("piece", "Real", "active", False, False, False),
    "Work/Single": ("piece", None, "active", True, False, True),
    "Work/SingleBare": ("piece", None, "active", True, False, False),
    "Work/Spaced/Tau": ("piece", "Tau", "active", False, False, False),
    "Work/Threads/Nu": ("piece", "Nu", "parked", False, False, False),
    "Work/Threads/Omicron": ("piece", "Omicron", "active", False, False, False),
    "Work/Threads/Xi": ("piece", "Xi", "done", False, False, False),
    "Work/Untyped": ("piece", None, "active", True, False, True),
}


class Reader(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="work-reader-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = work_fixture.build(self.tmp)

    def test_the_fixture_is_read_as_the_frozen_table_says(self):
        got = {r.identity: (r.kind, r.thread, r.status, r.own, r.beside, r.keeps_resume) for r in work.pieces(self.root)}
        self.assertEqual(got, FROZEN)

    def test_the_record_carries_its_places(self):
        by = {r.identity: r for r in work.pieces(self.root)}
        hub, thread = by["Work/Mixed"], by["Work/Mixed/Delta"]
        self.assertEqual((hub.zone, hub.project, hub.note, hub.folder), ("Work", "Mixed", self.root / "Zones/Work/Mixed/Mixed.md", self.root / "Zones/Work/Mixed"))
        self.assertEqual((thread.note, thread.folder, thread.hub), (self.root / "Zones/Work/Mixed/Threads/Delta/Delta.md",
                                                                  self.root / "Zones/Work/Mixed/Threads/Delta", hub.note))
        self.assertEqual(thread.hub_status, "active")
        self.assertEqual(by["Work/Parked/Iota"].hub_status, "parked")
        self.assertFalse(by["Work/Untyped"].typed)
        self.assertTrue(by["Work/Single"].typed)
        self.assertIsNone(by["Work/Threads/Nu"].hub)
        self.assertEqual(sorted(hub.as_dict()), sorted(("identity zone project thread kind status hub_status note folder hub typed own "
                                                        "beside keeps_resume").split()))

    def test_one_zone_returns_no_record_of_another(self):
        for name in ("Personal", "Client"):
            work_fixture.put(self.root / "Zones" / name / "Secret" / "Secret.md", work_fixture.hub("Secret", body=work_fixture.BLOCK))
            work_fixture.put(self.root / "Zones" / name / "Secret" / "Threads" / "Quiet" / "Quiet.md", work_fixture.thread("Quiet"))
        only = work.pieces(self.root, zone="Work")
        self.assertTrue(only)
        self.assertEqual({r.zone for r in only}, {"Work"})
        self.assertEqual({r.zone for r in work.pieces(self.root, zone="Personal")}, {"Personal"})
        self.assertEqual(work.pieces(self.root, zone="Nowhere"), [])
        self.assertEqual({r.zone for r in work.pieces(self.root)}, {"Work", "Personal", "Client"})

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symbolic links")
    def test_a_link_is_not_followed_out_of_its_zone(self):
        other = self.root / "Zones" / "Personal"
        work_fixture.put(other / "Secret" / "Secret.md", work_fixture.hub("Secret", body=work_fixture.BLOCK))
        work_fixture.put(other / "Secret" / "Threads" / "Quiet" / "Quiet.md", work_fixture.thread("Quiet"))
        work_fixture.put(other / "Elsewhere" / "Elsewhere.md", work_fixture.hub("Elsewhere"))
        zone = self.root / "Zones" / "Work"
        os.symlink(other / "Secret", zone / "Linked")                          # a project that is another zone's
        os.symlink(other / "Elsewhere", zone / "Plain" / "Threads" / "Away")   # a thread folder that is
        (zone / "Mixed" / "Threads" / "Delta" / "Delta.md").unlink()
        os.symlink(other / "Secret" / "Secret.md", zone / "Mixed" / "Threads" / "Delta" / "Delta.md")   # a note that is
        got = work.pieces(self.root, zone="Work")
        self.assertEqual({r.zone for r in got}, {"Work"})
        for r in got:
            self.assertNotIn("Personal", r.note.resolve().parts)
            self.assertNotEqual(r.project, "Linked")
        self.assertNotIn("Work/Plain/Away", {r.identity for r in got})
        self.assertNotIn("Work/Mixed/Delta", {r.identity for r in got})

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symbolic links")
    def test_a_zone_that_is_a_link_to_another_zone_is_listed_once(self):
        os.symlink(self.root / "Zones" / "Work", self.root / "Zones" / "Alias")
        got = work.pieces(self.root)
        self.assertEqual({r.zone for r in got}, {"Work"})
        self.assertEqual(len(got), len(FROZEN))
        self.assertEqual(work.pieces(self.root, zone="Alias"), [])

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symbolic links")
    def test_a_zone_that_is_a_link_out_of_zones_is_no_zone(self):
        away = self.tmp.parent / (self.tmp.name + "-out")
        self.addCleanup(shutil.rmtree, away, ignore_errors=True)
        work_fixture.put(away / "Hub" / "Hub.md", work_fixture.hub("Hub", body=work_fixture.BLOCK))
        os.symlink(away, self.root / "Zones" / "Away")
        self.assertEqual({r.zone for r in work.pieces(self.root)}, {"Work"})

    def test_a_workspace_with_no_zones_has_no_work(self):
        empty = Path(tempfile.mkdtemp(prefix="work-reader-"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        self.assertEqual(work.pieces(empty), [])

    def test_own_needs_type_keeps_the_pages_rule(self):
        got = work.own_needs_type(work.pieces(self.root))
        self.assertNotIn("Work/Untyped", {r.identity for r in got})
        self.assertIn("Work/Single", {r.identity for r in got})
        self.assertEqual(len(got), len(FROZEN) - 1)

    def test_the_file_loads_under_a_name_of_its_own(self):
        """Callers outside System/tools load work.py by its path; a dataclass must survive that."""
        other = load("garrick_work_elsewhere", TOOLS / "work.py")
        self.assertTrue(other.pieces(self.root))

    def test_hub_keeps_resume(self):
        block = "# P\n\n### Resume here\n\nGoing.\n"
        self.assertTrue(work.hub_keeps_resume(block))
        self.assertTrue(work.hub_keeps_resume("### resume here\n"))
        self.assertFalse(work.hub_keeps_resume("# P\n\n### Outcome\n\nDone.\n"))
        self.assertFalse(work.hub_keeps_resume(block, {"layout": "thread-first"}))
        self.assertFalse(work.hub_keeps_resume(block, {"layout": " Thread-First "}) )
        self.assertFalse(work.hub_keeps_resume("###  Resume here\n"))
        for text in (block, "### Outcome\n", "###  Resume here\n", "x"):
            for fm in (None, {"layout": "thread-first"}):
                self.assertEqual(gl.hub_keeps_resume(text, fm), work.hub_keeps_resume(text, fm))
        self.assertIs(gl.hub_keeps_resume, work.hub_keeps_resume)


if __name__ == "__main__":
    unittest.main()
