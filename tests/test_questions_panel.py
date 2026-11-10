"""The Questions panel's data and page (#224, point 9). Walls first: the panel
never lists a question or a finding from a zone other than the one shown, never
counts one and never offers a page from there; a wall finding never shows; a
page whose zone cannot be read is placed nowhere.

    cd tests && python3 -m unittest test_questions_panel
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from panel_case import PanelCase, commit_all  # noqa: E402
from test_page_action import pa  # noqa: E402

HERE = Path(__file__).resolve().parent.parent / "extras" / "status"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


status = _load("garrick_status_questions_test", HERE / "status.py")
qp = status.questions_mod()

TODAY = dt.date(2026, 11, 5)
ACME = "Acme: which volume floor holds?"
BIRCH = "Birch: which launch date holds?"
ELSEWHERE = "Elsewhere: another zone?"
OTHER = "Personal"                         # the fixture's second zone


def question(title, zone="Work", parties="[acme]", pages="", status="open", extra=""):
    fields = ("zone: %s\n" % zone if zone else "") + ("parties: %s\n" % parties if parties else "")
    return ("---\ntype: question\nasked: 2026-10-01\nstatus: %s\n%s%s%s---\n\n**%s**\n\nThe call and the mail differ.\n"
            % (status, fields, extra, ('pages: ["%s"]\n' % pages) if pages else "", title))


class Panel(PanelCase):
    def setUp(self):
        super().setUp()
        q = self.meetings / "questions"
        write(q / "261001 - acme.md", question(ACME, pages="[[wiki/sources/260310-acme-kickoff]]"))
        write(q / "261001 - birch.md", question(BIRCH, parties="[birch]", pages="[[wiki/sources/260312-birch-kickoff]]"))
        write(q / "261001 - nozone.md", question("Nozone: where?", zone=""))
        write(q / "261001 - elsewhere.md", question(ELSEWHERE, zone="Personal"))
        write(q / "261001 - unknownzone.md", question("Unknownzone: where?", zone="Nowhere"))
        write(q / "261001 - unreadable.md", question("Unreadable: form?").replace("parties: [acme]", "parties: [acme]\nparties: [birch]"))
        write(q / "261001 - answered.md", question("Answered: done?", status="answered"))
        write(self.knowledge_q, "---\ntype: question\nasked: 2026-09-01\nstatus: open\n---\n\n**Knowledge: which year?**\n\nThe report differs.\n")
        commit_all(self.meetings, "questions")

    @property
    def knowledge_q(self):
        return self.root / "Wikis" / "Knowledge" / "questions" / "260901 - year.md"

    def data(self, C=None):
        link = status.Links(self.root)
        nurture = status.nurture_lib(self.root)
        # a check this build ran (no `at`): as new as the build. C=False is no result at all.
        return qp.build(self.root, {"findings": []} if C is None else (C or None), nurture, TODAY, link)

    def check(self):
        return status.check(self.root)

    def titles(self, bucket):
        return sorted(q["title"] for q in bucket["questions"])


class TestOrigin(Panel):
    def origin_of(self, name, origin):
        write(self.meetings / "questions" / name, question("Origin: which?", extra='origin: "%s"\n' % origin))
        commit_all(self.meetings, name)
        for q in self.data()["buckets"]["Work"]["questions"]:
            if q["title"] == "Origin: which?":
                return q["origin"]

    def test_a_wiki_page_origin_shows_a_came_from_link_in_the_questions_own_zone(self):
        got = self.origin_of("261001 - wikiorigin.md", "[[wiki/sources/260310-acme-kickoff]]")
        self.assertEqual("wiki/sources/260310-acme-kickoff.md", got["name"])
        self.assertTrue(got["href"])

    def test_a_raw_origin_still_shows(self):
        self.assertEqual("260310-acme-kickoff.txt", self.origin_of("261001 - raworigin.md", "[[raw/260310-acme-kickoff]]")["name"])

    def test_a_wiki_page_origin_in_another_zone_shows_nothing(self):
        write(self.meetings / "wiki" / "sources" / "260315-home-call.md", "---\ntitle: Home\ntype: meeting\ndate: 2026-03-15\nzone: Personal\n---\n\n# Home\n")
        commit_all(self.meetings, "home")
        self.assertIsNone(self.origin_of("261001 - farorigin.md", "[[wiki/sources/260315-home-call]]"))


class TestWaitingForTheNextCheck(Panel):
    def test_a_question_edited_after_the_kept_check_is_not_shown_but_counted(self):
        old = {"findings": [], "at": 1.0, "kept": True}                     # a kept result from long ago
        d = self.data(old)
        self.assertEqual([], d["buckets"]["Work"]["questions"])
        self.assertEqual(3, d["buckets"]["Work"]["waiting"])                  # per zone, never added across zones
        self.assertEqual(1, d["buckets"]["Personal"]["waiting"])
        self.assertEqual([], d["knowledge"])
        self.assertEqual(1, d["knowledge_waiting"])
        blob = json.dumps(d["buckets"])
        for text in (ACME, BIRCH, "volume floor"):
            self.assertNotIn(text, blob)

    def test_no_kept_result_leaves_every_question_waiting(self):
        d = self.data(False)
        self.assertEqual([], d["buckets"]["Work"]["questions"])
        self.assertEqual(3, d["buckets"]["Work"]["waiting"])

    def test_a_result_newer_than_the_files_shows_them(self):
        import time
        d = self.data({"findings": [], "at": time.time() + 60, "kept": True})
        self.assertEqual([ACME, BIRCH], self.titles(d["buckets"]["Work"]))
        self.assertEqual(0, d["buckets"]["Work"]["waiting"])

    def test_a_question_edited_after_the_result_waits_while_the_others_show(self):
        import os
        import time
        at = time.time() + 60
        os.utime(self.meetings / "questions" / "261001 - birch.md", (at + 30, at + 30))
        d = self.data({"findings": [], "at": at, "kept": True})
        self.assertEqual([ACME], self.titles(d["buckets"]["Work"]))
        self.assertEqual(1, d["buckets"]["Work"]["waiting"])


class TestWhatIsListed(Panel):
    def test_each_zone_has_a_bucket_of_its_own(self):
        d = self.data()
        self.assertEqual(["Personal", "Work"], [z["zone"] for z in d["zones"]])
        self.assertEqual([ACME, BIRCH], self.titles(d["buckets"]["Work"]))
        self.assertEqual([ELSEWHERE], self.titles(d["buckets"]["Personal"]))

    def test_parties_are_an_index_and_never_split_a_zone(self):
        # two parties of one zone share its bucket: the zone is the wall, not the party
        got = self.titles(self.data()["buckets"]["Work"])
        self.assertIn(ACME, got)
        self.assertIn(BIRCH, got)

    def test_nothing_unreadable_or_in_another_zone_is_in_the_work_bucket(self):
        work = json.dumps(self.data()["buckets"]["Work"])
        for hidden in ("Nozone:", ELSEWHERE, "Unknownzone:", "Unreadable:", "Answered: done"):
            self.assertNotIn(hidden, work, hidden)
        page = qp.body(self.data())
        for nowhere in ("Nozone:", "Unknownzone:", "Unreadable:"):
            self.assertNotIn(nowhere, page, nowhere)

    def test_a_pages_list_never_names_a_page_of_another_zone(self):
        write(self.meetings / "wiki" / "sources" / "260315-home-call.md", "---\ntitle: Home\ntype: meeting\ndate: 2026-03-15\nzone: Personal\n---\n\n# Home\n")
        write(self.meetings / "questions" / "261001 - acme.md", question(
            ACME, pages="[[wiki/sources/260310-acme-kickoff]]\", \"[[wiki/sources/260315-home-call]]"))
        commit_all(self.meetings, "pages")
        q = next(x for x in self.data()["buckets"]["Work"]["questions"] if x["title"] == ACME)
        self.assertEqual(["wiki/sources/260310-acme-kickoff.md"], [p["name"] for p in q["pages"]])

    def test_the_counts_are_per_zone_and_never_add_two(self):
        d = self.data()
        self.assertEqual({"Personal": 1, "Work": 2}, d["menu"])
        self.assertEqual(1, d["menu_knowledge"])                   # a Knowledge question has no zone: counted once, apart
        self.assertEqual({"z": {"Personal": 1, "Work": 2}, "g": {"Personal": [{"h": "Personal", "n": 1}], "Work": [{"h": "Work", "n": 2}]}, "k": 1},
                         qp.counts_of(d))
        self.assertEqual(1, d["buckets"]["Work"]["answered"])
        self.assertEqual(0, d["buckets"]["Personal"]["answered"])
        self.assertFalse(d["select"]["*"]["sum"])
        self.assertTrue(d["select"]["Work"]["sum"])

    def test_knowledge_questions_are_listed_apart_for_every_zone(self):
        d = self.data()
        self.assertEqual(["Knowledge: which year?"], [q["title"] for q in d["knowledge"]])

    def test_a_question_whose_file_carries_a_wall_finding_is_not_listed(self):
        # it links a file of another walled zone, which is a finding on the question's own file
        write(self.meetings / "questions" / "261001 - acme.md", question(ACME).replace("The call and the mail differ.", "See [[Zones/Personal/Todo]]."))
        commit_all(self.meetings, "wall question")
        C = {"findings": [{"check": "walls", "path": "Wikis/Meetings/questions/261001 - acme.md", "line": 5, "severity": "error",
                           "message": "links a file of zone Personal"}]}
        self.assertEqual([BIRCH], self.titles(self.data(C)["buckets"]["Work"]))

    def test_later_is_hidden_until_its_day(self):
        write(self.meetings / "questions" / "261001 - acme.md",
              question(ACME, status="later", extra="later: 2026-11-20\n", pages="[[wiki/sources/260310-acme-kickoff]]"))
        self.assertEqual([BIRCH], self.titles(self.data()["buckets"]["Work"]))
        write(self.meetings / "questions" / "261001 - acme.md",
              question(ACME, status="later", extra="later: 2026-11-05\n", pages="[[wiki/sources/260310-acme-kickoff]]"))
        got = [q for q in self.data()["buckets"]["Work"]["questions"] if q["title"] == ACME]
        self.assertEqual([(ACME, True)], [(q["title"], q["due"]) for q in got])

    def test_the_line_naming_the_files_a_save_writes(self):
        q = next(x for x in self.data()["buckets"]["Work"]["questions"] if x["title"] == ACME)
        self.assertEqual(["Wikis/Meetings/raw/answers/261105 - acme.md", "Wikis/Meetings/questions/261001 - acme.md"],
                         q["writes"]["answer"])
        self.assertEqual(["Wikis/Meetings/questions/261001 - acme.md"], q["writes"]["later"])

    def test_a_proposed_verdict_is_read_from_the_question(self):
        write(self.meetings / "questions" / "261001 - acme.md",
              question(ACME, extra="verdict: stale\nverdict_reason: the call moved on\n", pages="[[wiki/sources/260310-acme-kickoff]]"))
        q = next(x for x in self.data()["buckets"]["Work"]["questions"] if x["title"] == ACME)
        self.assertEqual(("stale", "the call moved on"), (q["verdict"], q["reason"]))

    def test_text_is_data_never_markup(self):
        evil = "<script>alert(1)</script> & </script><img src=x onerror=1>"
        write(self.meetings / "questions" / "261001 - acme.md", question(evil, pages="[[wiki/sources/260310-acme-kickoff]]"))
        html = qp.body(self.data())
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<img", html)
        self.assertEqual(1, len(re.findall(r'<script type="application/json" id="qp-data">', html)))
        blob = re.search(r'id="qp-data">(.*?)</script>', html, re.S).group(1)
        self.assertIn(evil.replace("  ", " "), [x["title"] for x in json.loads(blob)["buckets"]["Work"]["questions"]])
        js = qp.JS
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(bad, js)


def person_page(name):
    return "---\ntitle: %s\ntype: person\nzone: Work\ncreated: 2026-03-10\nupdated: 2026-03-10\n---\n\n# %s\n\nSomeone.\n" % (name, name)


class TestNurtureFindings(Panel):
    def finding(self, rel, check="people", message="links a page that is not there"):
        return {"check": check, "path": rel, "line": 6, "severity": "warning", "message": message}

    def test_a_finding_sits_in_the_bucket_of_its_own_zone_and_carries_its_check_and_line_only(self):
        write(self.meetings / "wiki" / "people" / "dangling.md", person_page("Dangling") + "\nSee [[wiki/people/not-there]].\n")
        write(self.root / "Zones" / OTHER / "Home" / "Home.md", "---\ntype: project\nstatus: active\n---\n\n# Home\n")
        commit_all(self.meetings, "dangling")
        C = {"findings": [self.finding("Wikis/Meetings/wiki/people/dangling.md", "meetings", "links a page that is not there"),
                          self.finding("Zones/%s/Home/Home.md" % OTHER, "notes", "no `parent:`")]}
        d = self.data(C)["buckets"]
        for r in d["Work"]["review"]["read"]:
            self.assertEqual({"key", "path", "check", "line", "href"}, set(r))     # the line is the check's own words (#433)
        self.assertEqual(["Wikis/Meetings/wiki/people/dangling.md"], [r["path"] for r in d["Work"]["review"]["read"]])
        self.assertEqual(["Zones/%s/Home/Home.md" % OTHER], [r["path"] for r in d[OTHER]["review"]["read"]])

    def test_a_wall_finding_is_never_in_any_bucket(self):
        write(self.meetings / "wiki" / "people" / "wall-page.md", person_page("Wall Page") + "\nSee [[Zones/Personal/Todo]].\n")
        commit_all(self.meetings, "wall")
        C = {"findings": [self.finding("Wikis/Meetings/wiki/people/wall-page.md", "walls", "links a file of zone Personal")]}
        blob = json.dumps(self.data(C))
        self.assertNotIn("wall-page", blob)

    def test_a_page_with_no_zone_the_workspace_knows_is_placed_nowhere(self):
        write(self.meetings / "wiki" / "people" / "odd.md", person_page("Odd Person").replace("zone: Work", "zone: Nowhere"))
        commit_all(self.meetings, "odd")
        C = {"findings": [self.finding("Wikis/Meetings/wiki/people/odd.md", "meetings", "no `organisation:`")]}
        self.assertNotIn("odd.md", json.dumps(self.data(C)))


class TestTheViewAndTheZoneRule(Panel):
    def view(self, zone):
        lib = pa.prefs().lib(self.root)
        return pa.View(self.root, lib, zone)

    def test_a_view_is_one_zone_and_ok_takes_a_zone(self):
        v = self.view("Work")
        self.assertTrue(v.ok("Work"))
        for other in ("Personal", "", None, "work ", ["Work"]):
            self.assertFalse(v.ok(other), other)

    def test_an_unknown_zone_is_refused_with_the_rules_sentence(self):
        for bad in ("Nowhere", None, ""):
            with self.assertRaises(pa.Refused):
                self.view(bad)

    def test_a_pages_zone_is_its_path_or_its_meetings_zone(self):
        lib = pa.prefs().lib(self.root)
        self.assertEqual("Work", pa.page_zone(lib, self.root, self.root / "Zones" / "Work" / "Todo.md"))
        self.assertEqual("Work", pa.page_zone(lib, self.root, self.meetings / "wiki" / "sources" / "260310-acme-kickoff.md"))
        self.assertIsNone(pa.page_zone(lib, self.root, self.root / "Wikis" / "Knowledge" / "wiki" / "index.md"))


ZONES = [{"zone": "Personal"}, {"zone": "Work"}]


def keys(views):
    return [v["key"] for v in views]


class TestGroupModel(unittest.TestCase):
    """group_views (#384): a Zone choice, All included, as the list of views."""

    def test_one_zone_is_one_group(self):
        self.assertEqual(["Work"], keys(qp.group_views(ZONES, "Work")))

    def test_all_lists_every_zones_group_in_order(self):
        got = qp.group_views(ZONES)
        self.assertEqual(["Personal", "Work"], keys(got))
        self.assertEqual(["Personal", "Work"], [v["heading"] for v in got])

    def test_an_unknown_zone_is_nothing(self):
        self.assertEqual([], qp.group_views(ZONES, "Nowhere"))

    def test_two_groups_are_never_summed(self):
        self.assertFalse(qp.can_sum(qp.group_views(ZONES)))
        self.assertTrue(qp.can_sum(qp.group_views(ZONES, "Work")))

    def test_every_choice_the_menu_offers_is_precomputed(self):
        sel = qp.selections(ZONES)
        self.assertEqual({"*", "Work", "Personal"}, set(sel))
        self.assertEqual(["Personal", "Work"], keys(sel["*"]["views"]))
        self.assertFalse(sel["*"]["sum"])
        self.assertTrue(sel["Work"]["sum"])


class TestThePage(Panel):
    def test_a_judgment_row_hands_its_finding_to_a_session(self):
        self.assertIn("function handOver(r)", qp.JS)
        self.assertIn("'Open in Claude'", qp.JS)
        self.assertIn("'Open in Codex'", qp.JS)
        self.assertIn("setAttribute('data-launch',o[0])", qp.JS)         # the page's own launcher click, in the app
        self.assertIn("setAttribute('data-request',say_)", qp.JS)        # in a browser the request is copied
        self.assertIn("p.appendChild(handOver(r))", qp.JS)

    def test_there_is_no_party_picker_and_no_attribution_form(self):
        for gone in ("qp-party", "nurture-save", "nurture-organisation", "nurture-answer", "unattributed", "Whose is it"):
            self.assertNotIn(gone, qp.JS + qp.body({"zones": []}))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_scripts_are_valid(self):
        for name, code in (("panel", qp.JS), ("context", qp.CX_JS)):
            with tempfile.TemporaryDirectory() as t:
                f = Path(t) / (name + ".js")
                f.write_text(code, encoding="utf-8")
                r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
            self.assertEqual(0, r.returncode, r.stderr)

    def test_the_tab_the_panel_and_its_script_are_in_the_page(self):
        with mock.patch.object(status, "launch_agents", lambda: self.root / "LaunchAgents"):
            html = status.build(self.root, now=dt.datetime(2026, 11, 5, 9, 0), folder=self.jobs)
        self.assertIn('data-tab="questions">Context<', html)           # one word, like Overview and Guide (#433)
        self.assertIn("<h2 class=\"qp-title\">Context Nurture</h2>", html)
        self.assertIn('id="tab-questions"', html)
        self.assertIn("window.GarrickQuestions", html)
        self.assertIn('"z": {"Personal": 1, "Work": 2}', html.replace('"z":{"Personal":1,"Work":2}', '"z": {"Personal": 1, "Work": 2}'))

    def test_no_panel_where_the_walls_cannot_be_read(self):
        with mock.patch.object(qp, "build", side_effect=RuntimeError("x")):
            self.assertIsNone(status.questions_data(self.root, None, TODAY, status.Links(self.root)))


class TestTheMenu(unittest.TestCase):
    """The Questions row (decision 8): under Ask Garrick in File, in the menu bar's menu and in the edge panel."""

    def setUp(self):
        self.swift = (HERE / "app" / "Garrick.swift").read_text(encoding="utf-8")

    def test_file_menu_has_it_under_ask_garrick(self):
        self.assertRegex(self.swift, r'\n\s*ask,\n\s*item\("Context", #selector\(openQuestions\(_:\)\), ""\)')
        self.assertNotIn("Catch Up", self.swift)                      # the prompt is the only way in (#441)

    def test_the_menu_and_the_panel_have_a_row_with_the_count_of_the_zones_they_show(self):
        self.assertIn("if text.isEmpty, let questions = questionsItem()", self.swift)
        self.assertIn("m.questions = questionsTitle()", self.swift)
        self.assertIn('["questions"] as? [String: Any]', self.swift)
        self.assertIn('q["g"] as? [String: Any]', self.swift)
        self.assertIn("for z in shownZones()", self.swift)             # only the zones the menu shows
        self.assertNotIn("reduce(0)", self.swift[self.swift.index("func questionGroups"):self.swift.index("@objc func openQuestions")])    # no group is added to another

    def test_it_brings_the_window_forward_on_the_panel_the_page_defines(self):
        self.assertIn("window.GarrickQuestions && window.GarrickQuestions.open()", self.swift)
        self.assertIn("window.GarrickQuestions={open:", qp.JS)

    def test_the_page_sends_the_count_per_zone_in_the_menu_data(self):
        self.assertIn('md["questions"] = questions_mod().counts_of(qdata)', (HERE / "status.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
