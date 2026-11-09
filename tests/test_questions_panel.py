"""The Questions panel's data and page (#224, point 9). Walls first: the panel
never lists a question or a finding from the far side of a wall from the zone
and party shown, never counts one and never offers a page from there; a wall
finding never shows; a page whose parties cannot be read is placed nowhere.

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
from test_nurture_panel_actions import PanelCase, commit_all  # noqa: E402
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
MIXED = "Mixed: whose figure is it?"


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
        write(q / "261001 - mixed.md", question(MIXED, parties="[acme, birch]"))
        write(q / "261001 - across.md", question("Across: both sides?", pages="[[wiki/sources/260310-acme-kickoff]]\", \"[[wiki/sources/260312-birch-kickoff]]"))
        write(q / "261001 - nozone.md", question("Nozone: where?", zone=""))
        write(q / "261001 - elsewhere.md", question("Elsewhere: another zone?", zone="Personal"))
        write(q / "261001 - unknown.md", question("Unknown: who?", parties="[zzz]"))
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
        for q in self.data()["buckets"]["Work|acme"]["questions"]:
            if q["title"] == "Origin: which?":
                return q["origin"]

    def test_a_wiki_page_origin_shows_a_came_from_link_on_the_questions_own_side(self):
        got = self.origin_of("261001 - wikiorigin.md", "[[wiki/sources/260310-acme-kickoff]]")
        self.assertEqual("wiki/sources/260310-acme-kickoff.md", got["name"])
        self.assertTrue(got["href"])

    def test_a_raw_origin_still_shows(self):
        self.assertEqual("260310-acme-kickoff.txt", self.origin_of("261001 - raworigin.md", "[[raw/260310-acme-kickoff]]")["name"])

    def test_a_wiki_page_origin_across_the_wall_shows_nothing(self):
        self.assertIsNone(self.origin_of("261001 - farorigin.md", "[[wiki/sources/260312-birch-kickoff]]"))


class TestWaitingForTheNextCheck(Panel):
    def test_a_question_edited_after_the_kept_check_is_not_shown_but_counted(self):
        old = {"findings": [], "at": 1.0, "kept": True}                     # a kept result from long ago
        d = self.data(old)
        self.assertEqual([], d["buckets"]["Work|acme"]["questions"])
        self.assertEqual(2, d["buckets"]["Work|acme"]["waiting"])             # (an open and an answered one) per group, never added across the wall
        self.assertEqual(1, d["buckets"]["Work|birch"]["waiting"])
        self.assertEqual([], d["knowledge"])
        self.assertEqual(1, d["knowledge_waiting"])
        blob = json.dumps(d["buckets"])
        for text in (ACME, BIRCH, "volume floor"):
            self.assertNotIn(text, blob)

    def test_no_kept_result_leaves_every_question_waiting(self):
        d = self.data(False)
        self.assertEqual([], d["buckets"]["Work|acme"]["questions"])
        self.assertEqual(2, d["buckets"]["Work|acme"]["waiting"])

    def test_a_result_newer_than_the_files_shows_them(self):
        import time
        d = self.data({"findings": [], "at": time.time() + 60, "kept": True})
        self.assertEqual([ACME], self.titles(d["buckets"]["Work|acme"]))
        self.assertEqual(0, d["buckets"]["Work|acme"]["waiting"])

    def test_a_question_edited_after_the_result_waits_while_the_others_show(self):
        import os
        import time
        at = time.time() + 60
        os.utime(self.meetings / "questions" / "261001 - birch.md", (at + 30, at + 30))
        d = self.data({"findings": [], "at": at, "kept": True})
        self.assertEqual([ACME], self.titles(d["buckets"]["Work|acme"]))
        self.assertEqual([], self.titles(d["buckets"]["Work|birch"]))
        self.assertEqual(1, d["buckets"]["Work|birch"]["waiting"])


class TestWhatIsListed(Panel):
    def test_each_party_of_a_zone_walled_inside_it_has_a_bucket_of_its_own(self):
        d = self.data()
        self.assertEqual(["Work"], [z["zone"] for z in d["zones"]])
        self.assertEqual(["acme", "birch", "cedar"], [s["tag"] for s in d["zones"][0]["scopes"]])
        self.assertEqual([ACME], self.titles(d["buckets"]["Work|acme"]))
        self.assertEqual([BIRCH], self.titles(d["buckets"]["Work|birch"]))
        self.assertEqual([], self.titles(d["buckets"]["Work|cedar"]))

    def test_nothing_unreadable_or_across_a_wall_is_in_the_page_at_all(self):
        html = qp.body(self.data())
        for hidden in (MIXED, "Across:", "Nozone:", "Elsewhere:", "Unknown:", "Unreadable:", "Answered: done"):
            self.assertNotIn(hidden, html, hidden)
        self.assertIn(ACME, html)

    def test_a_far_side_bucket_holds_no_near_side_title_and_the_reverse(self):
        d = self.data()
        self.assertNotIn(BIRCH, json.dumps(d["buckets"]["Work|acme"]))
        self.assertNotIn(ACME, json.dumps(d["buckets"]["Work|birch"]))
        self.assertNotIn("birch", json.dumps(d["buckets"]["Work|acme"]["questions"]))

    def test_a_pages_list_never_names_a_page_from_the_far_side(self):
        d = self.data()
        pages = [p["name"] for q in d["buckets"]["Work|acme"]["questions"] for p in q["pages"]]
        self.assertEqual(["wiki/sources/260310-acme-kickoff.md"], pages)

    def test_the_counts_are_the_default_buckets_and_never_add_the_far_side(self):
        d = self.data()
        self.assertEqual({"Work": 1}, d["menu"])                   # Acme's question; Knowledge's has no zone and is counted once, apart
        self.assertEqual(1, d["menu_knowledge"])
        self.assertEqual({"z": {"Work": 1}, "g": {"Work": [{"h": "Work \u00b7 Acme Corp", "n": 1}, {"h": "Work \u00b7 Birch & Co", "n": 1},
                                                            {"h": "Work \u00b7 Cedar Ltd", "n": 0}]}, "k": 1}, qp.counts_of(d))
        self.assertEqual(1, d["buckets"]["Work|acme"]["answered"])
        self.assertEqual(0, d["buckets"]["Work|birch"]["answered"])

    def test_knowledge_questions_are_listed_apart_for_every_zone(self):
        d = self.data()
        self.assertEqual(["Knowledge: which year?"], [q["title"] for q in d["knowledge"]])

    def test_a_question_whose_file_carries_a_wall_finding_is_not_listed(self):
        # it names a page on the other side of the wall, which is a finding on the question's own file
        write(self.meetings / "questions" / "261001 - acme.md", question(ACME, pages="[[wiki/sources/260312-birch-kickoff]]"))
        commit_all(self.meetings, "wall question")
        C = self.check()
        self.assertTrue(any("261001 - acme" in f["path"] and qp.page_action().wallish(f["check"], f["message"]) for f in C["findings"]),
                        "the fixture must carry the finding")
        self.assertEqual([], self.titles(self.data(C)["buckets"]["Work|acme"]))

    def test_later_is_hidden_until_its_day(self):
        write(self.meetings / "questions" / "261001 - acme.md",
              question(ACME, status="later", extra="later: 2026-11-20\n", pages="[[wiki/sources/260310-acme-kickoff]]"))
        self.assertEqual([], self.titles(self.data()["buckets"]["Work|acme"]))
        write(self.meetings / "questions" / "261001 - acme.md",
              question(ACME, status="later", extra="later: 2026-11-05\n", pages="[[wiki/sources/260310-acme-kickoff]]"))
        got = self.data()["buckets"]["Work|acme"]["questions"]
        self.assertEqual([(ACME, True)], [(q["title"], q["due"]) for q in got])

    def test_the_line_naming_the_files_a_save_writes(self):
        q = self.data()["buckets"]["Work|acme"]["questions"][0]
        self.assertEqual(["Wikis/Meetings/raw/answers/261105 - acme.md", "Wikis/Meetings/questions/261001 - acme.md"],
                         q["writes"]["answer"])
        self.assertEqual(["Wikis/Meetings/questions/261001 - acme.md"], q["writes"]["later"])

    def test_a_proposed_verdict_is_read_from_the_question(self):
        write(self.meetings / "questions" / "261001 - acme.md",
              question(ACME, extra="verdict: stale\nverdict_reason: the call moved on\n", pages="[[wiki/sources/260310-acme-kickoff]]"))
        q = self.data()["buckets"]["Work|acme"]["questions"][0]
        self.assertEqual(("stale", "the call moved on"), (q["verdict"], q["reason"]))

    def test_text_is_data_never_markup(self):
        evil = "<script>alert(1)</script> & </script><img src=x onerror=1>"
        write(self.meetings / "questions" / "261001 - acme.md", question(evil, pages="[[wiki/sources/260310-acme-kickoff]]"))
        html = qp.body(self.data())
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<img", html)
        self.assertEqual(1, len(re.findall(r'<script type="application/json" id="qp-data">', html)))
        blob = re.search(r'id="qp-data">(.*?)</script>', html, re.S).group(1)
        self.assertEqual(evil.replace("  ", " "), json.loads(blob)["buckets"]["Work|acme"]["questions"][0]["title"])
        js = qp.JS
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(bad, js)


class TestNurtureFindings(Panel):
    def setUp(self):
        super().setUp()
        write(self.people / "jo-lee.md", person_page("Jo Lee", "acme"))
        write(self.entities / "harbour-ltd.md", entity_page("Harbour Ltd", ""))
        write(self.people / "ines-quill.md", person_page("Ines Quill", "acme").replace("Someone at a party.", "Works at Harbour Ltd."))
        commit_all(self.meetings, "more")
        self.C = self.check()

    def rows(self, key, kind):
        return sorted(r["title"] for r in self.data(self.C)["buckets"][key]["review"][kind])

    def test_people_rows_sit_in_the_bucket_of_their_own_party(self):
        self.assertEqual(["Dana Whitlock", "Jo Lee", "Mira Holt"], [t for t in self.rows("Work|acme", "people") if t != "Ines Quill"])
        self.assertEqual(["Theo Marsh"], self.rows("Work|birch", "people"))
        self.assertEqual([], self.rows("Work|cedar", "people"))

    def test_a_row_proposes_the_entity_page_with_its_title_and_first_line(self):
        row = next(r for r in self.data(self.C)["buckets"]["Work|acme"]["review"]["people"] if r["title"] == "Mira Holt")
        self.assertEqual({"rel": "acme-corp", "title": "Acme Corp", "line": "An organisation."}, row["proposal"])

    def test_entity_pages_with_no_party_are_offered_only_in_the_unattributed_view(self):
        self.assertEqual(["Harbour Ltd"], self.rows("unattributed|Work", "entities"))
        for k in ("Work|acme", "Work|birch", "Work|cedar"):
            self.assertEqual([], self.rows(k, "entities"))

    def test_the_pickers_offer_near_side_pages_and_the_zones_parties(self):
        d = self.data(self.C)["buckets"]
        self.assertEqual(["acme-corp"], [e["rel"] for e in d["Work|acme"]["picks"]["entities"]])
        self.assertEqual(["birch-co"], [e["rel"] for e in d["Work|birch"]["picks"]["entities"]])
        self.assertNotIn("birch", json.dumps(d["Work|acme"]["picks"]))
        self.assertEqual(["acme", "birch", "cedar", "none"], [p["tag"] for p in d["unattributed|Work"]["picks"]["parties"]])

    def test_a_wall_finding_is_never_in_any_bucket(self):
        # An Acme person page that links Birch's meeting is a wall finding: the Checks card says it, the panel does not.
        # It has no other finding, and a page with a wall on it has no row for any other.
        page = person_page("Wall Page", "acme").replace("party: acme\n", 'party: acme\norganisation: "[[wiki/entities/acme-corp]]"\n')
        write(self.people / "wall-page.md", page.replace("Someone at a party.", "See [[wiki/sources/260312-birch-kickoff]]."))
        commit_all(self.meetings, "wall")
        C = self.check()
        self.assertTrue(any("wall-page" in f["path"] for f in C["findings"]), "the fixture must raise a wall finding")
        N, nctx = status.nurture_lib(self.root)
        kinds = [N.sort_item(nctx, i).kind for f in C["findings"] if "wall-page" in f["path"] for i in N.check_items(f)]
        self.assertIn("wall", kinds)
        blob = json.dumps(self.data(C))
        self.assertNotIn("wall-page", blob)
        self.assertNotIn("Wall Page", blob)

    def test_a_page_with_a_wall_finding_has_no_row_for_another_finding(self):
        write(self.people / "wall-page.md", person_page("Wall Page", "acme").replace("Someone at a party.",
              "See [[wiki/sources/260312-birch-kickoff]]."))
        commit_all(self.meetings, "wall")
        self.assertNotIn("Wall Page", json.dumps(self.data(self.check())))

    def test_a_page_whose_form_cannot_be_read_is_placed_nowhere(self):
        write(self.people / "odd.md", person_page("Odd Person", "acme").replace("party: acme", "party: acme\nparty: birch"))
        commit_all(self.meetings, "odd")
        blob = json.dumps(self.data(self.check()))
        self.assertNotIn("Odd Person", blob)

    def test_judgment_rows_carry_a_path_the_check_and_its_line_only(self):
        write(self.people / "dangling.md", person_page("Dangling", "acme") + "\nSee [[wiki/people/not-there]].\n")
        commit_all(self.meetings, "dangling")
        read = self.data(self.check())["buckets"]["Work|acme"]["review"]["read"]
        for r in read:
            self.assertEqual({"key", "path", "check", "line", "href"}, set(r))     # the line is the check's own words (#433)

    def test_a_row_put_off_stays_hidden_until_its_day(self):
        key = next(r["key"] for r in self.data(self.C)["buckets"]["Work|acme"]["review"]["people"] if r["title"] == "Jo Lee")
        pa.save_later(self.root, {key: {"until": "2026-11-20", "path": "Wikis/Meetings/wiki/people/jo-lee.md"}}, set())
        self.assertNotIn("Jo Lee", self.rows("Work|acme", "people"))
        pa.save_later(self.root, {key: {"until": "2026-11-05", "path": "Wikis/Meetings/wiki/people/jo-lee.md"}}, set())
        self.assertIn("Jo Lee", self.rows("Work|acme", "people"))


def person_page(name, party):
    return ("---\ntitle: %s\ntype: person\nparty: %s\ncreated: 2026-03-10\nupdated: 2026-03-10\n---\n\n# %s\n\nSomeone at a party.\n"
            % (name, party, name))


def entity_page(title, party):
    return ("---\ntitle: %s\ntype: entity\n%screated: 2026-03-10\nupdated: 2026-03-10\n---\n\n# %s\n\nAn organisation.\n"
            % (title, "party: %s\n" % party if party else "", title))


ZONES = [
    {"zone": "Personal", "scopes": [], "default": "", "unattributed": True},
    {"zone": "Work", "scopes": [{"tag": "acme", "name": "Acme Corp"}, {"tag": "birch", "name": "Birch & Co"}],
     "default": "acme", "unattributed": True},
]


def keys(views):
    return [v["key"] for v in views]


class TestGroupModel(unittest.TestCase):
    """group_views (#384): a Zone and Party choice, All included, as the list of views, each what 0.56.0 shows."""

    def test_one_zone_and_a_party_is_that_view_and_the_zones_unattributed_pages(self):
        self.assertEqual(["Work|birch", "unattributed|Work"], keys(qp.group_views(ZONES, "Work", "birch")))

    def test_a_zone_a_wall_divides_is_one_group_per_party_under_all(self):
        got = qp.group_views(ZONES, "Work", qp.ALL)
        self.assertEqual(["Work|acme", "Work|birch", "unattributed|Work"], keys(got))
        self.assertEqual(["Work \u00b7 Acme Corp", "Work \u00b7 Birch & Co", "Work \u00b7 Unattributed"], [v["heading"] for v in got])

    def test_a_zone_no_wall_divides_is_one_group(self):
        self.assertEqual(["Personal|", "unattributed|Personal"], keys(qp.group_views(ZONES, "Personal", qp.ALL)))
        self.assertEqual(["Personal|", "unattributed|Personal"], keys(qp.group_views(ZONES, "Personal", "acme")))

    def test_all_and_all_lists_every_zones_groups_in_order(self):
        self.assertEqual(["Personal|", "unattributed|Personal", "Work|acme", "Work|birch", "unattributed|Work"],
                         keys(qp.group_views(ZONES)))

    def test_a_party_with_all_zones_is_only_the_zone_that_owns_it(self):
        self.assertEqual(["Work|birch", "unattributed|Work"], keys(qp.group_views(ZONES, qp.ALL, "birch")))

    def test_a_party_that_is_not_the_zones_is_read_as_its_default_as_before(self):
        self.assertEqual(["Work|acme", "unattributed|Work"], keys(qp.group_views(ZONES, "Work", "zzz")))
        self.assertEqual(["Work|acme", "unattributed|Work"], keys(qp.group_views(ZONES, "Work", "")))

    def test_an_unknown_zone_is_nothing(self):
        self.assertEqual([], qp.group_views(ZONES, "Nowhere", qp.ALL))

    def test_two_groups_that_hold_parties_are_never_summed(self):
        self.assertFalse(qp.can_sum(qp.group_views(ZONES, "Work", qp.ALL)))
        self.assertFalse(qp.can_sum(qp.group_views(ZONES)))
        self.assertTrue(qp.can_sum(qp.group_views(ZONES, "Work", "acme")))      # one party group, and pages naming no party
        self.assertTrue(qp.can_sum(qp.group_views(ZONES, "Personal", qp.ALL)))

    def test_every_choice_the_menus_offer_is_precomputed(self):
        sel = qp.selections(ZONES)
        for zc in ("*", "Work", "Personal"):
            self.assertIn("%s|*" % zc, sel)
        self.assertEqual(keys(qp.group_views(ZONES, "Work", "birch")), keys(sel["Work|birch"]["views"]))
        self.assertEqual(keys(qp.group_views(ZONES, "*", "acme")), keys(sel["*|acme"]["views"]))
        self.assertFalse(sel["Work|*"]["sum"])
        self.assertTrue(sel["Work|acme"]["sum"])


class TestGroupModelOnTheFixture(Panel):
    def test_the_page_carries_a_group_list_for_all_made_from_the_buckets_that_exist(self):
        d = self.data()
        got = keys(d["select"]["Work|*"]["views"])
        self.assertEqual(["Work|acme", "Work|birch", "Work|cedar", "unattributed|Work"], got)
        for k in got:
            self.assertIn(k, d["buckets"])
        self.assertEqual(sorted(d["buckets"]), sorted(keys(qp.group_views(d["zones"]))))

    def test_all_adds_nothing_to_a_group_a_group_holds_what_the_old_view_holds(self):
        d = self.data()
        self.assertEqual([ACME], self.titles(d["buckets"]["Work|acme"]))
        self.assertNotIn(BIRCH, json.dumps(d["buckets"]["Work|acme"]))
        self.assertNotIn(ACME, json.dumps(d["buckets"]["Work|birch"]))
        self.assertFalse(d["select"]["Work|*"]["sum"])


class TestThePage(Panel):
    def test_a_judgment_row_hands_its_finding_to_a_session(self):
        self.assertIn("function handOver(r)", qp.JS)
        self.assertIn("'Open in Claude'", qp.JS)
        self.assertIn("'Open in Codex'", qp.JS)
        self.assertIn("setAttribute('data-launch',o[0])", qp.JS)         # the page's own launcher click, in the app
        self.assertIn("setAttribute('data-request',say_)", qp.JS)        # in a browser the request is copied
        self.assertIn("p.appendChild(handOver(r))", qp.JS)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_script_is_valid(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "panel.js"
            f.write_text(qp.JS, encoding="utf-8")
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)

    def test_the_tab_the_panel_and_its_script_are_in_the_page(self):
        with mock.patch.object(status, "launch_agents", lambda: self.root / "LaunchAgents"):
            html = status.build(self.root, now=dt.datetime(2026, 11, 5, 9, 0), folder=self.jobs)
        self.assertIn('data-tab="questions">Context<', html)           # one word, like Overview and Guide (#433)
        self.assertIn("<h2 class=\"qp-title\">Context Nurture</h2>", html)
        self.assertIn('id="tab-questions"', html)
        self.assertIn("window.GarrickQuestions", html)
        self.assertIn('"z": {"Work": 1}', html.replace('"z":{"Work":1}', '"z": {"Work": 1}'))

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
