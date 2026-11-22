"""#604, #632, the rest: the layout control on the page and in the Ask box.

A project's card offers its one switch, Split into separate jobs or Join into one job, and no thread's card offers
any. A dialog asks for the plan (nothing is written), and Move them makes the change, once, in one commit; a file
no thread names is never placed by the control. The Ask box offers the same dialog and runs nothing.

    cd tests && python3 -m unittest test_layout_control
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import test_layout as tl  # noqa: E402  (its cases are not imported: they would run twice)
from fixtures import write  # noqa: E402
from test_ask import FakeSession, ask  # noqa: E402

REPO = tl.REPO
STATUS_SRC = (REPO / "extras" / "status" / "status.py").read_text(encoding="utf-8")
SWIFT_SRC = (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")
status, pa = tl.status, tl.pa


class ControlCase(tl.LayoutCase):
    """The fixture of scaffold.py layout's own tests: Acme, with threads Pricing and Freight, a deck only Pricing's
    note names, a sheet only Freight's names, a brief both name, and a file nobody names."""

    DECK, SHEET, BRIEF, MISC = "260101 - Pricing deck.pptx", "260102 - Freight sheet.xlsx", "brief.txt", "260103 - Misc.docx"

    def setUp(self):
        super().setUp()
        os.environ["GARRICK_JOBS_DIR"] = str(self.base / "jobs")
        self.make("project", "--zone", "Work", "--name", "Acme")
        for t in ("Pricing", "Freight"):
            self.make("thread", "--zone", "Work", "--project", "Acme", "--name", t)
        a = self.work / "Acme"
        (a / "Deliverables" / self.DECK).write_bytes(b"deck")
        (a / "Deliverables" / self.SHEET).write_bytes(b"sheet")
        (a / "Deliverables" / self.MISC).write_bytes(b"misc")
        (a / "Sources" / self.BRIEF).write_text("brief")
        pricing, freight = a / "Threads" / "Pricing" / "Pricing.md", a / "Threads" / "Freight" / "Freight.md"
        pricing.write_text(pricing.read_text() + "\nThe deck is %s and %s is the brief.\n" % (self.DECK, self.BRIEF))
        freight.write_text(freight.read_text() + "\nThe sheet is %s. The brief is %s.\n" % (self.SHEET, self.BRIEF))
        (a / "Deliverables" / "published.md").write_text(
            "# Published\n\n## What left\n\n| Date | File | Destination | Recipients | Authoritative |\n|---|---|---|---|---|\n"
            "| 2026-03-01 | `%s` | `acme/Decks/` | Dana | here |\n" % self.DECK)
        self.commit("Acme set up")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=str(self.work), capture_output=True, text=True, env=self.env)

    def commit(self, message):
        self.git("add", "-A")
        r = self.git("commit", "-q", "-m", message)
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)

    def commits(self):
        return int(self.git("rev-list", "--count", "HEAD").stdout)

    def snapshot(self, zone=None, project="Acme"):
        zone = zone or self.work
        return {str(p.relative_to(zone)): p.read_bytes() for p in (zone / project).rglob("*") if p.is_file()}

    def clean(self):
        return self.git("status", "--porcelain").stdout == ""

    def request(self, **extra):
        return dict({"verb": "layout", "zone": "Work", "project": "Acme", "heading": True}, **extra)

    def look(self, **extra):
        """The plan, as the dialog asks for it, through the executor the app's bridge uses."""
        out, _, _ = pa.perform(self.root, self.request(check=True, plan=True, **extra), pa.ops_lib(self.root), via="page")
        return out


class TestTheControlShowsThePlan(ControlCase):
    def test_the_plan_is_data_and_the_check_writes_nothing(self):
        before, count = self.snapshot(), self.commits()
        out = self.look()
        self.assertTrue(out["ok"], out)
        plan = out["plan"]
        self.assertEqual([[f"Deliverables/{self.DECK}", f"Threads/Pricing/Deliverables/{self.DECK}"],
                          [f"Deliverables/{self.SHEET}", f"Threads/Freight/Deliverables/{self.SHEET}"]], sorted(plan["moves"]))
        self.assertEqual({self.MISC: "no thread names it", self.BRIEF: "more than one note names it"},
                         {n.split("/")[-1]: why for n, why in plan["left"]})
        self.assertEqual(["Freight", "Pricing"], sorted(plan["threads"]))
        self.assertIn("Nothing was changed.", out["say"])
        self.assertEqual(before, self.snapshot())
        self.assertTrue(self.clean())
        self.assertEqual(count, self.commits())
        self.assertTrue(plan["heading"])
        self.assertFalse(plan["join"])

    def test_a_join_plan_offers_each_threads_next_action_and_writes_nothing(self):
        self.make("project", "--zone", "Work", "--name", "Cedar", "--separate", "--thread", "Harbour")
        self.make("thread", "--zone", "Work", "--project", "Cedar", "--name", "Quay")
        self.commit("Cedar")
        before, count = self.snapshot(project="Cedar"), self.commits()
        out, _, _ = pa.perform(self.root, {"verb": "layout", "zone": "Work", "project": "Cedar", "join": True, "check": True,
                                           "plan": True}, pa.ops_lib(self.root), via="page")
        self.assertTrue(out["ok"], out)
        plan = out["plan"]
        self.assertTrue(plan["join"] and plan["opens_resume"])
        self.assertEqual(["Harbour", "Quay"], sorted(n for n, _ in plan["next_actions"]))
        self.assertIn(plan["resume_from"], ("Harbour", "Quay"))
        self.assertEqual(before, self.snapshot(project="Cedar"))
        self.assertEqual(count, self.commits())
        self.assertTrue(self.clean())

    def test_a_plan_is_only_of_a_check(self):
        out, _, why = pa.perform(self.root, self.request(plan=True), pa.ops_lib(self.root), via="page")
        self.assertFalse(out["ok"])
        self.assertIn("plan is for check", out["say"])
        self.assertEqual(0, self.commits() - self.commits())

    def test_a_look_is_no_record_and_no_rebuild(self):
        out, _, _ = pa.perform(self.root, self.request(check=True), pa.ops_lib(self.root), via="page")
        self.assertTrue(out["ok"], out)
        self.assertNotIn("built", out)                  # a rebuild would reload the page under the open dialog
        jobs = Path(os.environ["GARRICK_JOBS_DIR"])
        recorded = [p for p in jobs.rglob("*") if p.is_file() and "layout" in p.read_text(errors="replace")] if jobs.exists() else []
        self.assertEqual([], recorded)                  # a look is not an action to keep a record of
        self.assertTrue(pa.only_looks(self.request(check=True)))
        self.assertFalse(pa.only_looks(self.request()))
        self.assertFalse(pa.builds_page(self.request(check=True)))
        self.assertTrue(pa.builds_page(self.request()))

    def test_the_change_after_a_look_is_made(self):
        # The change that follows a look is made: the look left nothing behind that could stand in for it.
        looked, _, _ = pa.perform(self.root, self.request(check=True), pa.ops_lib(self.root), via="page")
        self.assertTrue(looked["ok"], looked)
        out, _, _ = pa.perform(self.root, self.request(), pa.ops_lib(self.root), via="page")
        self.assertTrue(out["ok"], out)
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing" / "Deliverables" / self.DECK).is_file())

    def test_a_thread_or_a_papers_choice_is_refused_by_the_verb_with_the_sentence_that_names_the_switch(self):
        for extra in ({"thread": "Pricing"}, {"papers": "own"}, {"thread": "Pricing", "papers": "project", "heading": None, "join": True}):
            for look in (True, False):
                out, _, _ = pa.perform(self.root, self.request(check=look, **extra), pa.ops_lib(self.root), via="page")
                self.assertFalse(out["ok"], extra)
                self.assertIn("one job or separate jobs", out["say"])
        self.assertTrue(self.clean())


class TestMoveThem(ControlCase):
    def test_it_moves_and_commits_once_and_places_nothing_listed(self):
        count = self.commits()
        listed = {self.MISC: (self.work / "Acme" / "Deliverables" / self.MISC).read_bytes(),
                  self.BRIEF: (self.work / "Acme" / "Sources" / self.BRIEF).read_bytes()}
        out, _, _ = pa.perform(self.root, self.request(), pa.ops_lib(self.root), via="page")
        self.assertTrue(out["ok"], out)
        self.assertEqual(count + 1, self.commits())
        self.assertTrue(self.clean())
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing" / "Deliverables" / self.DECK).is_file())
        self.assertTrue((self.work / "Acme" / "Threads" / "Freight" / "Deliverables" / self.SHEET).is_file())
        self.assertEqual(listed[self.MISC], (self.work / "Acme" / "Deliverables" / self.MISC).read_bytes())
        self.assertEqual(listed[self.BRIEF], (self.work / "Acme" / "Sources" / self.BRIEF).read_bytes())
        self.assertFalse(any((self.work / "Acme" / "Threads" / t / k / self.MISC).exists() for t in ("Pricing", "Freight")
                             for k in ("Deliverables", "Sources")))

    def test_the_reply_carries_the_commit_and_no_command(self):
        out, _, _ = pa.perform(self.root, self.request(), pa.ops_lib(self.root), via="page")
        self.assertRegex(out["say"], r"Changed in commit [0-9a-f]{7,40}\.")
        self.assertNotIn("scaffold.py", out["say"])
        self.assertIn("Undo takes it back.", out["say"])

    def test_a_refused_commit_leaves_every_file_and_row_where_it_was(self):
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.write_text(hook.read_text().replace("exec python3", "echo 'refused by the fixture hook' >&2\nexit 1\nexec python3"))
        before, count = self.snapshot(), self.commits()
        out, _, _ = pa.perform(self.root, self.request(), pa.ops_lib(self.root), via="page")
        self.assertFalse(out["ok"])
        self.assertIn("every file and ledger row is where it was", out["say"])
        self.assertEqual(before, self.snapshot())
        self.assertTrue(self.clean())
        self.assertEqual(count, self.commits())

    def test_it_never_moves_a_file_outside_its_project_or_zone(self):
        # Another project of the same thread name that names the same files, and a second walled zone with the same project.
        for rel, text in (("Birch/Birch.md", "---\ntitle: Birch\ntype: project\nzone: Work\nstatus: active\ncreated: 2026-11-20\n"
                                           "updated: 2026-11-20\n---\n\n# Birch\n\nSee %s.\n" % self.DECK),
                          ("Birch/Threads/Pricing/Pricing.md", "---\ntitle: Pricing\ntype: thread\nzone: Work\nproject: Birch\n"
                           "status: active\ncreated: 2026-11-20\nupdated: 2026-11-20\n---\n\n# Pricing\n\nThe deck is %s.\n" % self.DECK),
                          ("Birch/Deliverables/%s" % self.DECK, "birch deck")):
            write(self.work / rel, text)
        self.commit("Birch")
        other = self.root / "Zones" / "Personal"
        write(other / "Acme" / "Acme.md", "---\ntitle: Acme\ntype: project\nzone: Personal\nstatus: active\ncreated: 2026-11-20\n"
                                           "updated: 2026-11-20\n---\n\n# Acme\n\nSee %s.\n" % self.DECK)
        write(other / "Acme" / "Deliverables" / self.DECK, "personal deck")
        subprocess.run(["git", "add", "-A"], cwd=str(other), env=self.env, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "Acme in Personal"], cwd=str(other), env=self.env, check=True)
        birch, theirs = self.snapshot(project="Birch"), self.snapshot(other)
        count = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=str(other), env=self.env, capture_output=True, text=True).stdout
        looked = self.look()
        self.assertNotIn("Birch", json.dumps(looked))
        self.assertNotIn("Personal", json.dumps(looked))
        out, _, _ = pa.perform(self.root, self.request(), pa.ops_lib(self.root), via="page")
        self.assertTrue(out["ok"], out)
        self.assertEqual(birch, self.snapshot(project="Birch"))
        self.assertEqual(theirs, self.snapshot(other))
        self.assertEqual(count, subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=str(other), env=self.env,
                                               capture_output=True, text=True).stdout)
        names = [n for n in self.git("show", "--name-only", "--format=", "HEAD").stdout.split("\n") if n]
        self.assertTrue(names and all(n.startswith("Acme/") for n in names), names)


class TestTheControlIsOfferedWhereItApplies(ControlCase):
    def offers(self, project, thread=None):
        T = status.threads(self.root)["Work"]
        if thread is None:
            return status.layout_offers(self.work / project, bool(T["projects"][project]["heading"]), True)
        row = [r for r in T["rows"] if r["project"] == project and r["thread"] == thread][0]
        return status.layout_offers(row["note"].parent, bool(row.get("heading")), row["hub"] is not None)

    def test_a_project_that_is_one_job_offers_to_split_and_a_project_of_separate_jobs_offers_to_join(self):
        self.assertEqual(["split"], self.offers("Acme"))
        self.make("project", "--zone", "Work", "--name", "Cedar", "--separate", "--thread", "Harbour")
        self.assertEqual(["join"], self.offers("Cedar"))

    def test_a_mixed_project_offers_the_join_and_threads_that_look_separate_offer_the_split(self):
        # Acme is one job with two threads, Pricing and Freight; its hub keeps the Resume here block.
        pricing = self.work / "Acme" / "Threads" / "Pricing"
        (pricing / "Sources").mkdir(exist_ok=True)
        (pricing / "Sources" / ".gitkeep").write_text("")
        self.assertEqual(["split"], self.offers("Acme"))                      # an empty folder is no papers
        (pricing / "Sources" / "brief.txt").write_text("brief")
        self.assertEqual(["mend"], self.offers("Acme"))                       # one of two threads holds papers: mixed
        freight = self.work / "Acme" / "Threads" / "Freight"
        (freight / "Deliverables").mkdir(exist_ok=True)
        (freight / "Deliverables" / "260101 - Rates.xlsx").write_bytes(b"x")
        self.assertEqual(["split"], self.offers("Acme"))                      # every thread holds papers: they look like separate jobs

    def test_the_mixed_chip_opens_the_join(self):
        text = (REPO / "extras" / "status" / "status.py").read_text(encoding="utf-8")
        self.assertIn("['mend','One job','Join ',' into one job…'", text)
        self.assertIn("v==='layout-mend'", text)
        self.assertIn("layout({zone:mg[0],project:mg[1],join:true})", text)

    def test_no_thread_offers_a_layout_whatever_its_papers_(self):
        self.assertEqual([], self.offers("Acme", "Pricing"))
        (self.work / "Acme" / "Threads" / "Pricing" / "Sources").mkdir()                  # a mixed project: still the project's switch
        self.assertEqual([], self.offers("Acme", "Pricing"))
        self.make("project", "--zone", "Work", "--name", "Cedar", "--separate", "--thread", "Harbour")
        self.assertEqual([], self.offers("Cedar", "Harbour"))

    def test_a_projects_card_offers_exactly_one_layout_action_and_a_threads_none(self):
        self.make("project", "--zone", "Work", "--name", "Cedar", "--separate", "--thread", "Harbour")
        out = self.base / "status.html"
        r = subprocess.run([sys.executable, str(REPO / "extras" / "status" / "status.py"), "--workspace", str(self.root),
                            "--out", str(out), "--no-cmux"], capture_output=True, text=True, env=self.env)
        self.assertEqual(0, r.returncode, r.stderr[-1500:])
        cards = [json.loads(html_lib.unescape(m)) for m in re.findall(r'data-card="(\{[^"]*)"', out.read_text(encoding="utf-8"))]
        offers = {(c["kl"], c["n"]): c["mg"][6] for c in cards if c.get("mg")}
        self.assertEqual(["split"], offers[("project", "Acme")])
        self.assertEqual(["join"], offers[("project", "Cedar")])
        for (kind, name), offered in offers.items():
            if kind == "thread":
                self.assertEqual([], offered, name)

    def test_the_cards_carry_it_and_the_page_builds_the_buttons(self):
        out = self.base / "status.html"
        r = subprocess.run([sys.executable, str(REPO / "extras" / "status" / "status.py"), "--workspace", str(self.root),
                            "--out", str(out), "--no-cmux"], capture_output=True, text=True, env=self.env)
        self.assertEqual(0, r.returncode, r.stderr[-1500:])
        html = out.read_text(encoding="utf-8")
        for word in ("layout-'+l[0]", "' into separate jobs…'", "' into one job…'", "'One job'", "'Separate jobs'", "window.GarrickLayout",
                     "window.GarrickLayoutChip"):
            self.assertIn(word, html)
        for gone in ("layout-own", "layout-project", "layout-heading", "Own papers…", "Project’s papers…", "Make a heading…"):
            self.assertNotIn(gone, html)
        self.assertIn('["split"]', html.replace("&quot;", '"'))

    def test_the_join_dialog_lists_the_next_actions_and_preselects_the_last_touched(self):
        for word in ("p.opens_resume", 'name="lay-from"', "(n[0]===p.resume_from?' checked'", "no Next action written",
                     "var from=d.querySelector('#lay-resume input:checked')", "more.resume_from=from.value"):
            self.assertIn(word, STATUS_SRC)
        self.assertEqual(2, STATUS_SRC.count("host.postMessage({act:Object.assign({},base"))     # the look, and Move them only

    def test_the_dialog_checks_first_and_moves_only_on_the_owners_click(self):
        self.assertIn("check:true,plan:true", STATUS_SRC)
        self.assertIn("Move them", STATUS_SRC)
        self.assertIn("Left for you to place. Nothing here puts them anywhere", STATUS_SRC)
        # the move request is sent from the Move them button's click only
        sends = [i for i in range(len(STATUS_SRC)) if STATUS_SRC.startswith("host.postMessage({act:Object.assign({},base", i)]
        self.assertEqual(2, len(sends))
        self.assertIn("d.querySelector('[data-go]').onclick=function(){if(busy(d,o.zone))return;", STATUS_SRC)
        self.assertIn("lresult", STATUS_SRC)

    def test_a_left_file_goes_to_the_assistant_as_a_request_never_to_a_move_of_its_own(self):
        self.assertIn("Ask my assistant", STATUS_SRC)
        self.assertIn("data-request=", STATUS_SRC)
        self.assertIn("place the file \"'+lbase(f[0])+'\" in the papers of the '+s.value+' thread", STATUS_SRC)

    def test_a_left_file_gets_the_assistant_button_only_for_a_plain_name(self):
        # the name goes into the text handed to the assistant, so only letters, digits, spaces and ._-()&,' may
        self.assertIn("function lsafe(name){return /^[\\p{L}\\p{N} ._\\-()&,']+$/u.test(name)}", STATUS_SRC)
        self.assertIn("z.folder&&lsafe(lbase(f[0]))?' <button", STATUS_SRC)
        self.assertNotIn("place '+f[0]+'", STATUS_SRC)

    def test_the_zones_folder_is_in_the_page_data_only_for_a_zone_with_an_offer_and_a_page_that_acts(self):
        one = {"hub": Path("/x/Acme/Acme.md"), "status": "active"}
        heading = {"hub": Path("/x/Cedar/Cedar.md"), "status": "active", "heading": True}
        with_offer = {"folder": Path("/x"), "rows": [], "parked": [], "projects": {"Acme": one}}
        without = {"folder": Path("/y"), "rows": [], "parked": [], "projects": {"Cedar": heading}}
        empty = {"folder": Path("/z"), "rows": [], "parked": [], "projects": {}}
        T = {"Work": with_offer, "Personal": without, "Home": empty}
        zones = status.manage_data(T, {}, True)["zones"]
        self.assertEqual("/x", zones["Work"]["folder"])
        self.assertNotIn("folder", zones["Personal"])
        self.assertNotIn("folder", zones["Home"])
        for zone in status.manage_data(T, {}, False)["zones"].values():
            self.assertNotIn("folder", zone)

    def test_the_app_treats_a_look_as_reading_and_opens_the_dialog_for_a_choice(self):
        self.assertIn('request["verb"] as? String == "layout", let flag = request["check"] as? NSNumber,', SWIFT_SRC)
        self.assertIn("CFGetTypeID(flag) == CFBooleanGetTypeID(), flag.boolValue { return true }", SWIFT_SRC)
        self.assertNotIn('request["check"] as? Bool', SWIFT_SRC)      # the number 1 would bridge to true; the page's rule is `is True`
        self.assertIn('choice["layout"] as? [String: Any]', SWIFT_SRC)
        self.assertIn("window.GarrickLayout&&window.GarrickLayout(", SWIFT_SRC)


class TestTheAskBoxOffersItAndRunsNothing(ControlCase):
    def setUp(self):
        super().setUp()
        write(self.root / "System" / "garrick-flags.json", json.dumps({"ask": True}))
        patcher = mock.patch.object(ask, "agent_on", lambda ws: False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.session = FakeSession()                     # an answer the box would ask for is a failure: none is given
        self.asker = ask.Asker(self.root, self.session)

    def assert_nothing_ran(self, before, count):
        self.assertEqual([], self.session.seen)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(count, self.commits())
        self.assertTrue(self.clean())

    def test_a_split_request_offers_the_dialog(self):
        before, count = self.snapshot(), self.commits()
        out = self.asker.ask("split Acme into separate jobs")
        self.assertEqual([{"label": "Review the change", "layout": {"zone": "Work", "project": "Acme", "heading": True}}], out["choices"])
        self.assertEqual([], out["acted"])
        self.assertEqual([], out["launch"])
        self.assertIn("Nothing moves until you say so", out["say"])
        self.assert_nothing_ran(before, count)

    def test_a_join_request_offers_the_dialog_only_where_it_applies(self):
        before, count = self.snapshot(), self.commits()
        out = self.asker.ask("join Acme into one job")
        self.assertEqual([], out["choices"])                       # one job already, and no thread keeps papers of its own
        self.assertIn("one job already", out["say"])
        self.make("project", "--zone", "Work", "--name", "Cedar", "--separate", "--thread", "Harbour")
        self.commit("Cedar")
        out = self.asker.ask("join Cedar into one job")
        self.assertEqual([{"label": "Review the change", "layout": {"zone": "Work", "project": "Cedar", "join": True}}], out["choices"])
        self.assert_nothing_ran(self.snapshot(), self.commits())

    def test_a_request_about_one_threads_papers_offers_nothing_and_is_not_read_as_a_layout(self):
        self.session.answers.append(json.dumps({"say": "Nothing like that here.", "do": []}))
        out = self.asker.ask("give Pricing its own papers")
        self.assertEqual([], [c for c in out.get("choices", []) if "layout" in c])
        self.assertNotIn("Review the change", json.dumps(out))

    def test_the_box_cannot_run_the_verb(self):
        out, _, _ = pa.perform(self.root, self.request(), pa.ops_lib(self.root), via="ask")
        self.assertFalse(out["ok"])
        self.assertTrue(self.clean())
        out, _, _ = pa.perform(self.root, self.request(check=True, plan=True), pa.ops_lib(self.root), via="session")
        self.assertFalse(out["ok"])

    def test_separate_jobs_are_not_split_again(self):
        self.make("project", "--zone", "Work", "--name", "Cedar", "--separate", "--thread", "Harbour")
        self.commit("Cedar")
        out = self.asker.ask("split Cedar into separate jobs")
        self.assertEqual([], out["choices"])
        self.assertIn("separate jobs already", out["say"])

    def personal_project(self):
        self.make("project", "--zone", "Personal", "--name", "Maple")
        self.make("project", "--zone", "Personal", "--name", "Linden", "--separate", "--thread", "Harbour")

    def test_a_project_of_another_zone_is_neither_named_nor_offered_in_this_zones_window(self):
        self.personal_project()
        for request in ("split Maple into separate jobs", "join Linden into one job", "split Harbour into separate jobs"):
            self.session.answers.append(json.dumps({"say": "Nothing like that here.", "do": []}))
            out = self.asker.ask(request, zone="Work")
            self.assertEqual([], [c for c in out.get("choices", []) if "layout" in c], request)
            for word in ("Maple", "Linden", "Harbour", "separate jobs already", "one job already", "Review the change"):
                self.assertNotIn(word, json.dumps(out), request)

    def test_the_same_request_in_its_own_zones_window_offers_it(self):
        self.personal_project()
        out = self.asker.ask("split Maple into separate jobs", zone="Personal")
        self.assertEqual([{"label": "Review the change", "layout": {"zone": "Personal", "project": "Maple", "heading": True}}],
                         out["choices"])
        out = self.asker.ask("split Linden into separate jobs", zone="Personal")
        self.assertIn("separate jobs already", out["say"])

    def test_with_no_window_a_name_held_by_two_zones_offers_nothing(self):
        self.make("project", "--zone", "Personal", "--name", "Acme")
        self.session.answers.append(json.dumps({"say": "Which one?", "do": []}))
        out = self.asker.ask("split Acme into separate jobs")
        self.assertEqual([], [c for c in out.get("choices", []) if "layout" in c])


if __name__ == "__main__":
    unittest.main()
