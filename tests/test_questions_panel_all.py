"""The Questions panel with All for Zone and Party (#384): the page's groups, counts per group, the
two-way Show switch, and a save that goes out as one request per group. Walls first: no number
adds two groups, and a save from All never mixes two.

    cd tests && python3 -m unittest test_questions_panel_all
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from test_questions_panel import ACME, BIRCH, Panel, qp  # noqa: E402
from test_status_more import DOM  # noqa: E402

HARNESS = r"""
const vm = require("vm");
const [html, js, steps, hosted] = JSON.parse(process.argv[1]);
""" + DOM + r"""
const doc = new El("#document");
parse(html, doc);
const sess = {}, posted = [];
El.prototype.addEventListener = function (t, f) { (this._l = this._l || {})[t] = (this._l[t] || []).concat([f]); };
Object.defineProperty(El.prototype, "value", { get() { return this._v === undefined ? "" : this._v; }, set(v) { this._v = v; } });
const qs = El.prototype.querySelector;
El.prototype.querySelector = function (s) {
  if (s === "input[type=radio]:checked") return this.querySelectorAll("input").find((i) => i.type === "radio" && i.checked) || null;
  return qs.call(this, s);
};
const ctx = { JSON, String, Array, Object, Date, Math,
  sessionStorage: { getItem: (k) => (k in sess ? sess[k] : null), setItem: (k, v) => { sess[k] = String(v); }, removeItem: (k) => { delete sess[k]; } },
  document: { querySelectorAll: (s) => doc.querySelectorAll(s), querySelector: (s) => doc.querySelector(s), createElement: (t) => new El(t),
              createTextNode: (t) => new Text(String(t)), getElementById: (id) => doc.querySelectorAll("#" + id)[0] || null, addEventListener: () => {} } };
ctx.window = ctx;
if (hosted) ctx.webkit = { messageHandlers: { garrick: { postMessage: (m) => posted.push(m.act) } } };
ctx.GarrickSay = () => {};
vm.createContext(ctx);
vm.runInContext(js, ctx);
const $ = (id) => doc.querySelectorAll("#" + id)[0];
function seen() {
  const tab = $("qp-tab-n");
  return {
    counts: $("qp-counts").children.map((c) => c.textContent),
    tab: tab ? tab.textContent : null,
    list: $("qp-list").children.map((li) => [li.className, li.childNodes[0].textContent]),
    heads: $("qp-list").children.filter((li) => li.className === "qp-gh").map((li) => li.children.map((c) => c.className + ":" + c.textContent)
      .concat([li.childNodes.filter((n) => !n.children).map((n) => n.textContent).join("")])),
    switch: $("qp-source").children.map((b) => b.textContent + "|" + b.getAttribute("aria-pressed")),
    party: { hidden: $("qp-party-l").hidden, options: $("qp-party").children.map((o) => o.value + ":" + o.textContent) },
    zones: $("qp-zone").children.map((o) => o.value),
    nurture: $("qp-nurture").hidden ? [] : $("qp-nurture").querySelectorAll("h3,button,summary").map((e) => e.localName + ":" + e.textContent),
    work: $("qp-work").textContent,
    posted: posted.slice(),
  };
}
const out = [seen()];
for (const [what, a] of steps) {
  const z = $("qp-zone"), p = $("qp-party");
  if (what === "zone") { z.value = a; z.onchange.call(z); }
  if (what === "party") { p.value = a; p.onchange.call(p); }
  if (what === "show") $("qp-source").children.find((b) => b.getAttribute("data-source") === a).onclick();
  if (what === "saveAll") $("qp-nurture").querySelectorAll("button").filter((b) => b.textContent === a)[0].onclick();
  if (what === "pickAnother") { /* every row answered "another page", which is a save */
    $("qp-nurture").querySelectorAll("input").filter((i) => i.type === "radio" && i.value === "another").forEach((i) => { i.checked = true; });
    $("qp-nurture").querySelectorAll(".qp-choice").forEach((c) => ((c._l || {}).change || []).forEach((f) => f())); }
  out.push(seen());
}
process.stdout.write(JSON.stringify(out));
"""


def q(title, n, **kw):
    return dict({"wiki": "Meetings", "file": "261001 - %s.md" % n, "title": title, "why": "", "asked": "2026-10-01", "status": "open",
                 "due": False, "verdict": "", "reason": "", "origin": None, "pages": [], "writes": {"answer": [], "later": [], "close": []},
                 "shown": True}, **kw)


def row(key, title, rel):
    return {"key": key, "title": title, "path": "Wikis/Meetings/wiki/people/%s.md" % rel, "href": "#", "proposal": None}


def bucket(questions=(), people=(), entities=(), answered=0):
    return {"questions": list(questions), "answered": answered, "review": {"entities": list(entities), "people": list(people), "read": []},
            "picks": {"entities": [], "parties": []}}


def data():
    zones = [{"zone": "Personal", "scopes": [], "default": "", "unattributed": True},
             {"zone": "Work", "scopes": [{"tag": "acme", "name": "Acme Corp"}, {"tag": "birch", "name": "Birch & Co"}],
              "default": "acme", "unattributed": True}]
    return {"today": "2026-11-05", "root": "/x", "zones": zones, "select": qp.selections(zones),
            "knowledge": [q("Knowledge: which year?", "k", wiki="Knowledge")], "knowledge_answered": 0,
            "buckets": {"Personal|": bucket([q("Home: which plan?", "h")], [row("p1", "Pat Home", "pat-home")]),
                        "unattributed|Personal": bucket(),
                        "Work|acme": bucket([q(ACME, "a1"), q("Acme: second?", "a2")], [row("a1", "Mira Holt", "mira-holt")], answered=1),
                        "Work|birch": bucket([q(BIRCH, "b1")], [row("b1", "Theo Marsh", "theo-marsh"), row("b2", "Una Birch", "una-birch")], answered=2),
                        "unattributed|Work": bucket(entities=[row("e1", "Harbour Ltd", "harbour-ltd")])},
            "menu": {}}


def run(steps, hosted=True, d=None):
    html = '<span id="qp-tab-n"></span>' + qp.body(d or data())
    done = subprocess.run(["node", "-e", HARNESS, json.dumps([html, qp.JS, steps, hosted])], capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestZoneColourOnHeadings(unittest.TestCase):
    def heads(self, zcls):
        d = data()
        d["zcls"] = zcls
        return run([["zone", "Work"], ["party", "*"]], d=d)[-1]["heads"]

    def test_a_zone_with_a_colour_has_it_on_the_zone_part_only(self):
        heads = self.heads({"Work": " zc zc-red"})
        self.assertEqual([["zc zc-red:Work", " \u00b7 Acme Corp (2)"], ["zc zc-red:Work", " \u00b7 Birch & Co (1)"]], heads[:2])

    def test_knowledge_has_none_even_when_every_zone_has_one(self):
        heads = self.heads({"Work": " zc zc-red", "Personal": " zc zc-blue"})
        self.assertEqual([["Knowledge (1)"]], heads[2:])

    def test_a_zone_without_a_colour_looks_as_it_did(self):
        heads = self.heads({"Personal": " zc zc-blue"})
        self.assertEqual([["Work \u00b7 Acme Corp (2)"], ["Work \u00b7 Birch & Co (1)"], ["Knowledge (1)"]], heads)
        self.assertEqual([["Work \u00b7 Acme Corp (2)"], ["Work \u00b7 Birch & Co (1)"], ["Knowledge (1)"]], self.heads({}))

    def test_the_counts_row_carries_the_colour_too(self):
        d = data()
        d["zcls"] = {"Work": " zc zc-red"}
        got = run([["zone", "Work"], ["party", "*"]], d=d)[-1]["counts"]
        self.assertTrue(got[0].startswith("Work \u00b7 Acme Corp"))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestAllInThePage(unittest.TestCase):
    def test_both_menus_offer_all(self):
        got = run([])[0]
        self.assertEqual(["*", "Personal", "Work"], got["zones"])
        got = run([["zone", "Work"]])[-1]
        self.assertEqual(["*:All", "acme:Acme Corp", "birch:Birch & Co"], got["party"]["options"])

    def test_a_zone_shown_alone_is_as_before_one_party_and_no_headings(self):
        got = run([["zone", "Work"]])[-1]
        titles = [t for c, t in got["list"] if c != "qp-gh"]
        self.assertTrue(any(c == "qp-gh" for c, t in got["list"]))              # Knowledge is a group of its own, so headings show
        self.assertEqual([ACME, "Acme: second?", "Knowledge: which year?"], sorted(titles, key=lambda t: t != ACME and t != "Acme: second?"))

    def test_all_parties_of_a_zone_sit_under_one_heading_each_with_its_own_count(self):
        got = run([["zone", "Work"], ["party", "*"]])[-1]
        heads = [t for c, t in got["list"] if c == "qp-gh"]
        self.assertEqual(["Work · Acme Corp (2)", "Work · Birch & Co (1)", "Knowledge (1)"], heads)
        # the Birch question sits under Birch's heading and never under Acme's
        flat = [t for c, t in got["list"]]
        self.assertLess(flat.index("Work · Acme Corp (2)"), flat.index(ACME))
        self.assertLess(flat.index(ACME), flat.index("Work · Birch & Co (1)"))
        self.assertLess(flat.index("Work · Birch & Co (1)"), flat.index(BIRCH))

    def test_no_number_adds_two_groups_across_a_wall(self):
        got = run([["zone", "Work"], ["party", "*"]])[-1]
        self.assertEqual("", got["tab"])                                          # the tab carries no number
        self.assertEqual(["Wiki questions|true", "Nurture findings|false"], got["switch"])      # and the switch no counts
        joined = " ".join(got["counts"])
        for summed in ("3 open", "4 open", "5 open", "6 open"):
            self.assertNotIn(summed, joined)
        self.assertEqual(3, len(got["counts"]))                                    # a row of counts for each group
        self.assertIn("Work · Acme Corp", got["counts"][0])
        self.assertIn("Work · Birch & Co", got["counts"][1])
        self.assertEqual("Work · Acme Corp 1; Work · Birch & Co 2; Knowledge 0 answered, waiting to be worked in.".replace("; Knowledge 0", ""),
                         got["work"].split("Work them in")[-1])

    def test_all_zones_and_all_parties_lists_every_group_and_still_adds_none(self):
        got = run([["zone", "*"]])[-1]
        heads = [t for c, t in got["list"] if c == "qp-gh"]
        self.assertEqual(["Personal (1)", "Work · Acme Corp (2)", "Work · Birch & Co (1)", "Knowledge (1)"], heads)
        self.assertEqual("", got["tab"])
        self.assertEqual(["*:All", "acme:Acme Corp", "birch:Birch & Co"], got["party"]["options"])

    def test_one_party_group_shows_the_two_way_switch_with_both_counts(self):
        got = run([["zone", "Work"], ["party", "birch"]])[-1]
        # Birch's one question and Knowledge's, which carries no party; two people and Work's one unattributed entity page
        self.assertEqual(["Wiki questions 2|true", "Nurture findings 3|false"], got["switch"])
        self.assertEqual("2", got["tab"])
        got = run([["zone", "Work"], ["party", "birch"], ["show", "nurture"]])[-1]
        self.assertEqual(["Wiki questions 2|false", "Nurture findings 3|true"], got["switch"])

    def test_the_switch_is_one_or_the_other_never_all(self):
        got = run([["show", "nurture"], ["show", "wiki"], ["show", "nurture"]])
        for g in got:
            self.assertEqual(1, sum(1 for s in g["switch"] if s.endswith("|true")))

    def test_findings_of_several_groups_have_a_save_each_and_one_without_a_number(self):
        got = run([["zone", "Work"], ["party", "*"], ["show", "nurture"]])[-1]
        saves = [e for e in got["nurture"] if e.startswith("button:Save")]
        self.assertIn("button:Save all answers", saves)
        self.assertEqual(3, sum(1 for e in saves if e == "button:Save 0 answers"))      # one per group, none summing two
        heads = [e for e in got["nurture"] if e.startswith("h3:")]
        self.assertEqual(["h3:Work · Unattributed: whose entity pages are, 1", "h3:Work · Acme Corp: where people work, 1",
                          "h3:Work · Birch & Co: where people work, 2"], heads)

    def test_a_save_from_all_goes_out_as_one_group_for_each_view_its_rows_were_shown_in(self):
        got = run([["zone", "Work"], ["party", "*"], ["show", "nurture"], ["pickAnother", None], ["saveAll", "Save all answers"]])[-1]
        self.assertEqual(1, len(got["posted"]))
        req = got["posted"][0]
        self.assertEqual("nurture-save-all", req["verb"])
        shape = [(g["zone"], g.get("scope"), sorted(r["key"] for r in g["rows"])) for g in req["groups"]]
        self.assertEqual([("unattributed", "Work", ["e1"]), ("Work", "acme", ["a1"]), ("Work", "birch", ["b1", "b2"])], shape)

    def test_a_single_group_save_is_still_the_plain_nurture_save(self):
        got = run([["zone", "Work"], ["party", "acme"], ["show", "nurture"], ["pickAnother", None]])[-1]
        saves = [e for e in got["nurture"] if e.startswith("button:Save")]
        self.assertEqual(["button:Save 2 answers"], saves)

    def test_in_a_browser_nothing_is_posted(self):
        got = run([["zone", "*"], ["show", "nurture"], ["pickAnother", None]], hosted=False)[-1]
        self.assertEqual([], got["posted"])


class TestAllOnTheRealFixture(Panel):
    def test_the_precomputed_groups_name_buckets_that_are_in_the_page(self):
        d = self.data()
        for sel in d["select"].values():
            for v in sel["views"]:
                self.assertIn(v["key"], d["buckets"])
        self.assertFalse(d["select"]["*|*"]["sum"])

    def test_the_far_side_of_a_wall_is_in_no_other_groups_bucket_in_the_all_view(self):
        d = self.data()
        by = {v["key"]: json.dumps(d["buckets"][v["key"]]) for v in d["select"]["Work|*"]["views"]}
        self.assertNotIn("Birch", by["Work|acme"])
        self.assertNotIn("Acme:", by["Work|birch"])


class TestTwoPartyKeys(Panel):
    """A question with `parties: [acme]` and a `party:` key of another case or name reads two ways: it is
    listed in no group and every save of it is refused (#384)."""

    def setUp(self):
        super().setUp()
        self.f = self.meetings / "questions" / "261001 - acme.md"
        self.text = self.f.read_text()

    def spoil(self, line):
        self.f.write_text(self.text.replace("parties: [acme]\n", "parties: [acme]\n" + line + "\n"))

    def test_listed_in_no_group_under_any_selection(self):
        for line in ("party: birch", "party: acme", "PARTY: birch", "Parties: [birch]"):
            self.spoil(line)
            d = self.data()
            self.assertNotIn(ACME, json.dumps(d), line)
            for sel in d["select"].values():
                for v in sel["views"]:
                    self.assertEqual([], [x for x in d["buckets"][v["key"]]["questions"] if "acme.md" in x["file"]], line)

    def test_every_save_of_it_is_refused(self):
        self.spoil("party: birch")
        before = self.f.read_text()
        for req in (dict(verb="question-answer", words="Yes"), dict(verb="question-later", until="2026-12-01"), dict(verb="question-close")):
            with self.assertRaisesRegex(qp.page_action().Refused, "cannot be read plainly"):
                qp.page_action().act(self.root, dict(req, wiki="Meetings", file="questions/261001 - acme.md"), today=__import__("datetime").date(2026, 11, 5))
        self.assertEqual(before, self.f.read_text())


if __name__ == "__main__":
    unittest.main()
