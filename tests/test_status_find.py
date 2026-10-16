"""The Threads card's search box (#140): one box that finds a project or a
thread by name in every zone, live, parked and finished, and the line in the
New project and New thread dialogs that names what is already there. The
page's script runs in Node against the page status.py writes.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import html as htmllib
import json
import re
import shutil
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True

from fixtures import project_hub, thread_note, write  # noqa: E402
from test_status import REPO, StatusCase, cards, status  # noqa: E402
from test_status_more import DOM, panel  # noqa: E402

sys.path.insert(0, str(REPO / "template" / "System" / "tools"))
import garrick_lib  # noqa: E402


def find_data(html):
    return json.loads(re.search(r'id="find-data">(.*?)</script>', html, re.S).group(1))


# The page as status.py wrote it, FIND_JS run over it with MANAGE_JS before it
# (whose dialogs ask GarrickFind), and a list of steps: type into the box, press
# a key in it or on the page, reload with the window's sessionStorage kept, say
# a request was done, or open a dialog and type a name into it. After each
# step, what the card shows.
HARNESS = r"""
const vm = require("vm");
const [html, js, steps] = JSON.parse(process.argv[1]);
""" + DOM + r"""
El.prototype.addEventListener = function (t, f) { (this._l = this._l || {})[t] = (this._l[t] || []).concat([f]); };
El.prototype.fire = function (t, e) { (this._l && this._l[t] || []).forEach((f) => f(e)); };
El.prototype.focus = function () { active = this; };
El.prototype.blur = function () { if (active === this) active = null; };
El.prototype.select = function () {};
Object.defineProperty(El.prototype, "style", { get() { return this._s || (this._s = {}); } });
Object.defineProperty(El.prototype, "value", {
  get() { if (this._v !== undefined) return this._v;
          if (this.localName === "select") { const o = this.querySelectorAll("option").find((x) => x.hasAttribute("selected")) || this.querySelector("option");
                                             return o ? o.getAttribute("value") : ""; }
          return this.getAttribute("value") || ""; },
  set(v) { this._v = v; } });
El.prototype.showModal = function () { this.attrs.open = ""; };
El.prototype.close = function () { delete this.attrs.open; this.fire("close", {}); };
let active = null, doc, ctx, box, docl, bound, closed;
const session = {};
function key(k, target) {
  let stopped = false, prevented = false;
  const e = { key: k, target, preventDefault() { prevented = true; }, stopPropagation() { stopped = true; }, get defaultPrevented() { return prevented; } };
  for (let el = target; el && el.nodeType === 1 && !stopped; el = el.parentNode) el.fire("keydown", e);
  if (!stopped) (docl.keydown || []).forEach((f) => f(e));
  return prevented;
}
function load() {
  doc = new El("#document");
  parse(html, doc);
  docl = {};
  bound = 0;
  closed = 0;
  active = null;
  const body = doc.querySelector("body");
  ctx = { JSON, String, Array, Object, Math, RegExp, Date,
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    sessionStorage: { getItem: (k) => (k in session ? session[k] : null), setItem: (k, v) => { session[k] = String(v); },
                      removeItem: (k) => { delete session[k]; } },
    setTimeout: () => 0, clearTimeout: () => {}, navigator: {},
    document: { querySelectorAll: (s) => doc.querySelectorAll(s), querySelector: (s) => doc.querySelector(s), body,
                createElement: (t) => new El(t), getElementById: (id) => doc.querySelectorAll("#" + id)[0] || null,
                addEventListener: (t, f) => { (docl[t] = docl[t] || []).push(f); }, readyState: "complete" } };
  ctx.window = ctx;
  ctx.ThreadRows = { bind: () => { bound++; }, close: () => { closed++; } };
  ctx.StatusTab = (n) => { doc.querySelectorAll("main>section.tab").forEach((s) => { s.hidden = s.id !== "tab-" + n; }); body.dataset.tab = n; };
  ctx.GarrickActed = () => {};
  vm.createContext(ctx);
  vm.runInContext(js, ctx);
  box = doc.querySelectorAll("#tfind")[0];
}
function seen() {
  const v = doc.querySelector(".tview"), wrap = doc.querySelectorAll("#tfound")[0];
  const res = doc.querySelectorAll("#tfound-list .sres").map((r) => {
    const chip = r.querySelector(".chip");
    return { n: r.querySelector(".t>a").textContent, under: r.querySelector("small").textContent, s: r.getAttribute("data-s"),
             chip: chip ? chip.textContent : "", card: JSON.parse(r.getAttribute("data-card")), href: r.querySelector(".t>a").getAttribute("href") };
  });
  const dup = doc.querySelectorAll("#mg-dup")[0];
  return { finding: v.classList.contains("finding"), hidden: wrap.hidden, said: doc.querySelectorAll("#tfound-n")[0].textContent,
           zones: doc.querySelector(".tview .zones").outerHTML, res, value: box.value, bound, closed,
           focus: active ? (active.id || active.localName + (active.textContent ? ":" + active.textContent : "")) : null,
           tab: ctx.document.body.dataset.tab || "", session: Object.assign({}, session),
           dup: dup ? { hidden: dup.hidden, text: dup.textContent, links: dup.querySelectorAll("a").map((a) => a.getAttribute("href")) } : null };
}
load();
const out = [seen()];
for (const [what, a, b] of steps) {
  let r = null;
  if (what === "type") { box.value = a; box.fire("input", { target: box }); }
  if (what === "key") r = key(a, b === "body" ? doc.querySelector("body") : b === "result" ? doc.querySelector("#tfound-list .sres .t>a") : box);
  if (what === "reload") load();
  if (what === "tab") ctx.StatusTab(a);
  if (what === "acted") { const row = doc.querySelectorAll(".tview .zones .thread[data-card]").find((x) => JSON.parse(x.getAttribute("data-card")).n === a);
                          const c = JSON.parse(row.getAttribute("data-card")); Object.assign(c, b); row.setAttribute("data-card", JSON.stringify(c));
                          ctx.GarrickActed({ verb: "wake" }, { ok: true }); }
  if (what === "dialog") { const btn = doc.querySelector('button[data-manage="' + a + '"]');
                           (docl.click || []).forEach((f) => f({ target: btn, preventDefault() {}, stopPropagation() {} })); }
  if (what === "name") { const i = doc.querySelectorAll("#mg-name")[0]; i.value = a; i.fire("input", { target: i }); }
  if (what === "go") { const d = doc.querySelectorAll("#gmanage")[0]; d.querySelector("[data-go]").onclick();
                       r = { open: d.hasAttribute("open"), toast: doc.querySelectorAll("#toast")[0].textContent }; }
  if (what === "alike") r = ctx.GarrickFind.alike(a);
  if (what === "sounds") r = a.map(([x, y]) => ctx.GarrickFind.soundsAlike(x, y));
  out.push(Object.assign(seen(), { r }));
}
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestFind(StatusCase):
    """Two zones, each with live, parked and finished threads, three of them
    called Freight Terms or near it, one only said through its spoken form, one
    with an accent."""

    def setUp(self):
        super().setUp()
        work, home = self.root / "Zones" / "Work", self.root / "Zones" / "Personal"
        acme = work / "Acme Review" / "Threads"
        write(acme / "Freight Terms" / "Freight Terms.md", thread_note("Acme Review", "Freight Terms", status="parked"))
        write(acme / "Old Deal" / "Old Deal.md", thread_note("Acme Review", "Old Deal", status="done"))
        write(work / "Birch Entry" / "Threads" / "Freight terms" / "Freight terms.md",
              thread_note("Birch Entry", "Freight terms", "birch"))
        write(home / "House" / "House.md", project_hub("Personal", "House", "", ["Q4 Planning", "Café Lease", "Freight Terms"]))
        q4 = thread_note("House", "Q4 Planning", "").replace("status: active", "status: active\nspoken: fourth quarter planning")
        write(home / "House" / "Threads" / "Q4 Planning" / "Q4 Planning.md", q4)
        write(home / "House" / "Threads" / "Café Lease" / "Café Lease.md", thread_note("House", "Café Lease", ""))
        write(home / "House" / "Threads" / "Freight Terms" / "Freight Terms.md",
              thread_note("House", "Freight Terms", "", body="The carrier's rate is secret.", status="done"))
        write(home / "Garden" / "Garden.md", project_hub("Personal", "Garden", "").replace("status: active", "status: done"))
        write(home / "Garden" / "Threads" / "Beds" / "Beds.md", thread_note("Garden", "Beds", "", status="done"))

    def run_js(self, *steps, html=None):
        html = html or self.page(show_graph=False)
        done = subprocess.run(["node", "-e", HARNESS, json.dumps([html, status.MANAGE_JS + status.FIND_JS, [list(s) for s in steps]])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_the_page_carries_names_only_finished_ones_included(self):
        html = self.page(show_graph=False)
        items = {(i["z"], i["p"] if i["k"] == "t" else "", i["n"]): i for i in find_data(html)["items"]}
        self.assertEqual("done", items[("Personal", "House", "Freight Terms")]["s"])
        self.assertEqual("parked", items[("Work", "Acme Review", "Freight Terms")]["s"])
        self.assertEqual("live", items[("Work", "Birch Entry", "Freight terms")]["s"])
        self.assertEqual("fourth quarter planning", items[("Personal", "House", "Q4 Planning")]["sp"])
        self.assertEqual(("p", "done"), (items[("Personal", "", "Garden")]["k"], items[("Personal", "", "Garden")]["s"]))
        self.assertEqual("done", items[("Personal", "Garden", "Beds")]["s"])
        old = items[("Work", "Acme Review", "Old Deal")]["c"]          # a finished one carries the card it has no row for
        self.assertEqual((1, "thread", "Work"), (old["fin"], old["kl"], old["z"]))
        self.assertNotIn("pa", old)                                    # nothing that changes it
        self.assertNotIn("c", items[("Work", "Acme Review", "Freight Terms")])     # a parked one's card is its row's
        self.assertNotIn("carrier", html)                              # a note's body never reaches the page
        self.assertNotIn(("Acme Review", "Old Deal"), cards(html))     # and the card's columns stay as they were
        self.assertIn('<input type="search" id="tfind" placeholder="Find a project or thread"', html)
        bar = html[html.index('<div class="mg-new">'):]
        self.assertLess(bar.index('id="tfind"'), bar.index('data-manage="new-project"'))

    def test_two_letters_find_every_zone_and_status_live_first(self):
        start, found = self.run_js(("type", "fr"))
        self.assertFalse(start["finding"])
        self.assertTrue(start["hidden"])
        self.assertTrue(found["finding"])
        self.assertFalse(found["hidden"])
        self.assertEqual([("Freight terms", "Birch Entry · Work", ""), ("Freight Terms", "Acme Review · Work", "parked"),
                          ("Freight Terms", "House · Personal", "done")],
                         [(r["n"], r["under"], r["chip"]) for r in found["res"]])
        self.assertEqual("3 matches in every zone, 1 live", found["said"])
        self.assertEqual(3, found["bound"])                            # each with the row's hover card
        parked = found["res"][1]["card"]
        self.assertEqual(cards(self.page(show_graph=False))[("Acme Review", "Freight Terms")], parked)    # the row's own, Wake and all
        self.assertEqual(start["zones"], found["zones"])              # the columns are hidden, never touched

    def test_spoken_forms_accents_zones_and_word_by_word(self):
        _, q4, said, cafe, upper, acme, zone, none = self.run_js(
            ("type", "q4"), ("type", "fourth quarter"), ("type", "cafe"), ("type", "CAFÉ"), ("type", "acme fr"),
            ("type", "personal"), ("type", "zz top"))
        self.assertEqual(["Q4 Planning"], [r["n"] for r in q4["res"]])
        self.assertEqual(["Q4 Planning"], [r["n"] for r in said["res"]])
        self.assertEqual(["Café Lease"], [r["n"] for r in cafe["res"]])
        self.assertEqual(["Café Lease"], [r["n"] for r in upper["res"]])
        self.assertEqual([("Freight Terms", "parked")], [(r["n"], r["s"]) for r in acme["res"]])
        names = [(r["n"], r["s"]) for r in zone["res"]]                # a zone's name finds what is in it
        self.assertEqual([("Café Lease", "live"), ("House", "live"), ("Q4 Planning", "live"), ("Beds", "done"),
                          ("Freight Terms", "done"), ("Garden", "done")], names)
        self.assertEqual("Project · Personal", zone["res"][1]["under"])
        self.assertEqual([], none["res"])
        self.assertTrue(none["finding"])
        self.assertEqual("Nothing by that name in any zone, live, parked or finished.", none["said"])

    def test_clearing_or_esc_puts_the_card_back_exactly(self):
        start, found, cleared, again, esc, esc2 = self.run_js(
            ("type", "fr"), ("type", ""), ("type", "fr"), ("key", "Escape"), ("key", "Escape"))
        for after in (cleared, esc):
            self.assertFalse(after["finding"])
            self.assertTrue(after["hidden"])
            self.assertEqual([], after["res"])
            self.assertEqual(start["zones"], after["zones"])
        self.assertEqual("", esc["value"])
        self.assertEqual({}, esc["session"])
        self.assertIsNone(esc2["focus"])                               # a second Esc, on an empty box, leaves it

    def test_the_query_outlives_a_rebuild_in_the_same_window(self):
        _, found, rebuilt = self.run_js(("type", "freight"), ("reload",))
        self.assertEqual("freight", found["session"]["garrick-find"])
        self.assertEqual("freight", rebuilt["value"])
        self.assertEqual([r["n"] for r in found["res"]], [r["n"] for r in rebuilt["res"]])

    def test_a_match_says_what_it_is_once_a_row_has_moved(self):
        _, found, woken = self.run_js(("type", "acme fr"), ("acted", "Freight Terms", {"s": 0}))
        self.assertEqual("parked", found["res"][0]["chip"])
        self.assertEqual(("live", ""), (woken["res"][0]["s"], woken["res"][0]["chip"]))

    def test_the_keyboard(self):
        _, found, down, enter_slash, slash = self.run_js(("type", "fr"), ("key", "ArrowDown"), ("key", "ArrowUp", "result"),
                                                          ("key", "/", "body"))
        self.assertEqual("a:Freight terms", down["focus"])
        self.assertEqual("tfind", enter_slash["focus"])               # up from the first match is the box again
        self.assertEqual("tfind", slash["focus"])

    def test_slash_reaches_the_box_from_another_tab_but_not_from_the_guide(self):
        _, guide, ignored, moved, slash = self.run_js(("tab", "guide"), ("key", "/", "body"), ("tab", "status"), ("key", "/", "body"))
        self.assertEqual(("guide", None), (ignored["tab"], ignored["focus"]))      # the Guide keeps its own
        self.assertEqual(("overview", "tfind"), (slash["tab"], slash["focus"]))   # the tab the card is on, then the box

    def test_the_dialogs_name_what_is_already_there(self):
        steps = [("dialog", "new-thread"), ("name", "Freight Terms"), ("name", "Fraight terms"), ("name", "Logistics"),
                 ("dialog", "new-project"), ("name", "Gardens"), ("dialog", "new-thread"), ("name", "Freight Terms"), ("go",)]
        _, opened, three, alike, none, project, garden, _, warned, made = self.run_js(*steps)
        self.assertTrue(opened["dup"]["hidden"])
        self.assertEqual("Already there: Freight terms (Birch Entry, Work); Freight Terms (Acme Review, Work, parked); "
                         "Freight Terms (House, Personal, done).", three["dup"]["text"])
        self.assertEqual(3, len(three["dup"]["links"]))
        self.assertEqual(three["dup"]["text"], alike["dup"]["text"])   # heard as the same, by scaffold.py's own test
        self.assertTrue(none["dup"]["hidden"])
        self.assertEqual("Already there: Garden (a project, Personal, done). Open it", garden["dup"]["text"])
        self.assertFalse(warned["dup"]["hidden"])
        self.assertFalse(made["r"]["open"])                            # a warning, not a refusal: it still goes ahead
        self.assertIn("new thread Freight Terms in House", made["r"]["toast"])

    def test_alike_is_scaffolds_own_test(self):
        pairs = [("Freight Terms", "Freight terms"), ("Freight Terms", "Fraight Terms"), ("Pricing", "Prising"),
                 ("Q4 Planning", "Q four planning"), ("Knight Shift", "Night Shift"), ("Phone Plan", "Fone Plan"),
                 ("Bloc", "Block"), ("Café Lease", "Cafe Lease"), ("Birch & Co", "Birch and Co"), ("Acme", "Acne"),
                 ("Pricing", "Renewal"), ("Supplier Audit", "Supply Audit"), ("Tax", "Taxi"), ("Wharf", "Warf"),
                 ("Schedule", "Skedule"), ("Xenon", "Zenon"), ("Thatch", "Tach"), ("Ünder", "Under"), ("Psalm", "Salm"),
                 ("Market Sizing", "Market-Sizing"), ("Year 2027", "Year 2028"), ("Ice", "Ise"), ("Dodge", "Doj"), ("Mac", "Mak")]
        out = self.run_js(("sounds", pairs))[-1]["r"]
        self.assertEqual([garrick_lib.sounds_alike(a, b) for a, b in pairs], out)
        self.assertIn(True, out)
        self.assertIn(False, out)

    def test_a_finished_ones_card_opens_it_and_changes_nothing(self):
        old = {i["n"]: i for i in find_data(self.page(show_graph=False))["items"]}["Old Deal"]["c"]
        head, acts = panel(True, ("head", old, 1), ("acts", old))
        self.assertIn("Finished, updated", head)
        self.assertNotIn("Park", head)
        self.assertNotIn("Wake", head)
        self.assertIn('title="Open the note"', acts)

    def test_the_page_says_the_box_is_there_in_both_themes_and_at_any_width(self):
        css = status.FIND_CSS
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,6}\b")              # every colour from the page's own tokens
        self.assertIn(".tfind{position:relative;flex:1 1 200px;min-width:0", css)    # shrinks, and wraps above the buttons
        self.assertIn(".mg-new{flex-wrap:wrap", css)
        self.assertIn("@media (hover:none){.tfind kbd{display:none}}", css)


if __name__ == "__main__":
    unittest.main()
