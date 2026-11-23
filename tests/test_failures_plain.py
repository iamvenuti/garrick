"""#511: every failure the app can show, listed once, with its sentence, its one next step and the test that holds it.

The list below is the failure list the issue asks for. It starts from the executor's outcomes, the hand-off to Claude,
Ask's session start, the page build and Recall's index age, and adds every row of page_action.py's FAILURES. A row of
FAILURES that is not in the list fails here, and so does a listed failure that no code produces.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import test_page_action as tpa  # noqa: E402

pa = tpa.pa
REPO = tpa.REPO
STATUS = REPO / "extras" / "status"
SWIFT = (STATUS / "app" / "Garrick.swift").read_text(encoding="utf-8")
_spec = importlib.util.spec_from_file_location("garrick_operations_fp", str(REPO / "template" / "System" / "tools" / "operations.py"))
ops = importlib.util.module_from_spec(_spec)
sys.modules["garrick_operations_fp"] = ops
_spec.loader.exec_module(ops)
_ask_spec = importlib.util.spec_from_file_location("garrick_ask_fp", str(STATUS / "ask.py"))
ask = importlib.util.module_from_spec(_ask_spec)
sys.modules["garrick_ask_fp"] = ask
_ask_spec.loader.exec_module(ask)

SUCCESS = re.compile(r"(?i)\b(saved|done|committed|parked|woke|ticked|reopened|made)\b")
RAW = re.compile(r"(?i)(/\w|\.py\b|\bgit\b|traceback|\bexit \d|--\w)")

# code: (where it comes from, the test that holds it). Every row of FAILURES is here.
LIST = {
    "wall": ("the record's `refused` outcome, when the zone's wall check refused it: operations.py say()", "TestTheOutcomes"),
    "refused": ("the record's `refused` outcome: page_action.py perform(), operations.py finish()", "TestTheOutcomes"),
    "crashed": ("the record's `crashed` outcome: page_action.py perform()", "TestTheOutcomes"),
    "unknown": ("the record's `unknown` outcome: operations.py, a worker that died", "TestTheOutcomes"),
    "lost": ("the record's `lost` outcome: status.py's page script, no reply in time", "TestTheOutcomes"),
    "unrecorded": ("a reply that says it worked with no outcome: page_action.py with_plain()", "TestTheOutcomes"),
    "noreply": ("a failed reply with no outcome: status.py's page script", "TestTheOutcomes"),
    "handoff": ("Continue could not open Claude: page_action.py continue_work(), ask_desktop(), start's first look", "TestTheHandOff"),
    "handoff-late": ("the desktop app took too long and may have opened: handoff.py TimedOut", "TestTheHandOff"),
    "handoff-off": ("this Mac does not allow a local desktop session: handoff.py LocalOff, a managed setting", "TestTheHandOff"),
    "handoff-cli": ("the command-line tool is not installed: handoff.py NO_CLI", "TestTheHandOff"),
    "handoff-look": ("a first look that did not come back: page_action.py first_look()", "TestTheHandOff"),
    "ask-start": ("the ask server did not start, or Garrick could not run it: ask.py call(), Garrick.swift askStream()", "TestAsk"),
    "ask-silent": ("the ask server did not answer in time: ask.py call(), Garrick.swift askStream()", "TestAsk"),
    "ask-stopped": ("the ask server ended before it answered: ask.py call(), Garrick.swift askStream()", "TestAsk"),
    "ask-failed": ("Ask stopped on an error: ask.py serve() and main()", "TestAsk"),
    "role-server": ("Settings, This machine: page_action.py set_machine_role()", "TestSettingsRows"),
    "role-name": ("Settings, This machine: page_action.py set_machine_role()", "TestSettingsRows"),
    "role-tool": ("Settings, This machine: page_action.py set_machine_role()", "TestSettingsRows"),
    "role-write": ("Settings, This machine: page_action.py set_machine_role()", "TestSettingsRows"),
    "guard-value": ("Settings, read guard: page_action.py set_read_guard()", "TestSettingsRows"),
    "guard-assistant": ("Settings, read guard: settings_guard.py", "TestSettingsRows"),
    "guard-file": ("Settings, read guard: page_action.py set_read_guard()", "TestSettingsRows"),
    "guard-version": ("Settings, read guard: page_action.py set_read_guard()", "TestSettingsRows"),
    "guard-read": ("Settings, read guard: settings_guard.py", "TestSettingsRows"),
    "guard-write": ("Settings, read guard: settings_guard.py", "TestSettingsRows"),
    "guard-check": ("Settings, read guard: page_action.py set_read_guard()", "TestSettingsRows"),
    "guard-save": ("Settings, read guard: page_action.py set_read_guard()", "TestSettingsRows"),
    "release-check": ("Settings, Check for updates: status.py RELEASE_JS, page_action.py release-check", "TestThePanels"),
    "release-update": ("Settings, the update Check for updates starts: status.py RELEASE_JS, page_action.py release-update",
                       "TestThePanels"),
    "count": ("Settings, Memory: what the changes would do, status.py MEMORY_JS, page_action.py memory-preview", "TestThePanels"),
    "note-read": ("Explore's Preview could not read the note: status.py NOTE_JS, page_action.py note-read", "TestThePanels"),
    "note-open": ("Open in default app did not open the note: status.py NOTE_JS, page_action.py note-open", "TestThePanels"),
    "other": ("a failed reply the table has no row for", "TestTheOutcomes"),
}

# The rows the panels draw with GarrickFail (#511's rest), each with the block of status.py that draws it.
PANELS = ("release-check", "release-update", "count", "note-read", "note-open")

# Failures drawn outside the table: where the sentence and the next step are written, and the test that holds them.
OUTSIDE = {
    "page-old": (STATUS / "status.py", "This page is ", "Refresh", "TestThePage"),
    "page-rebuild": (STATUS / "app" / "Garrick.swift", "This page did not rebuild, so it may be old.", "Refresh", "TestThePage"),
}

# A failure on the issue's list that no code produces, and why.
NOT_PRODUCED = {
    "recall-index-old": "Recall's search brings its index up to date before it reads (recall.py open_scope: Refresher(idx).run()), "
                        "and nothing in the app reads the index's age, so no answer says it used old records and no button writes to the index.",
}


def count_in_sources(code: str) -> int:
    n = 0
    for path in list(STATUS.glob("*.py")) + [STATUS / "app" / "Garrick.swift"]:
        text = path.read_text(encoding="utf-8")
        n += text.count('"%s"' % code) + text.count("'%s'" % code)
    return n


class TestTheList(unittest.TestCase):
    def test_every_row_of_the_table_is_in_the_list_and_every_listed_failure_is_in_the_table(self):
        self.assertEqual(set(pa.FAILURE_CODES), set(LIST))

    def test_every_listed_failure_is_produced_by_some_code(self):
        for code in LIST:
            if code == "other":
                continue
            # one use is the row in FAILURES itself; a producer is another
            self.assertGreaterEqual(count_in_sources(code), 2, "%s: no code produces it" % code)

    def test_every_listed_failure_names_its_test(self):
        here = sys.modules[__name__]
        for code, (_where, test) in LIST.items():
            self.assertTrue(hasattr(here, test), "%s: %s" % (code, test))
        for code, (_f, _needle, _act, test) in OUTSIDE.items():
            self.assertTrue(hasattr(here, test), "%s: %s" % (code, test))

    def test_a_failure_nothing_produces_is_not_in_the_table(self):
        for code, why in NOT_PRODUCED.items():
            self.assertNotIn(code, pa.FAILURE_CODES)
            self.assertTrue(why)
        recall = (REPO / "template" / "System" / "tools" / "recall.py").read_text(encoding="utf-8")
        self.assertIn("Refresher(idx).run()", recall)         # a search brings the index up to date before it reads
        for path in STATUS.glob("*.py"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"(?i)indexed (yesterday|\d+ days)", path.name)

    def test_each_row_has_a_sentence_one_action_and_no_raw_text(self):
        for code, say, button, act, hint in pa.FAILURES:
            if code == "wall":
                continue
            self.assertTrue(say.endswith("."), code)
            self.assertIn(act, ("why", "retry", "refresh"), code)
            self.assertTrue(button, code)
            self.assertNotRegex(say + " " + hint, RAW, code)

    def test_a_request_that_may_have_been_acted_on_is_never_sent_again_by_a_button(self):
        for code in ("handoff-late", "ask-silent", "ask-stopped", "unknown", "lost", "unrecorded"):
            self.assertNotEqual("retry", next(r for r in pa.FAILURES if r[0] == code)[3], code)


class TestTheOutcomes(unittest.TestCase):
    def test_saved_is_the_records_word_for_each_outcome_it_has(self):
        for outcome in ops.OUTCOMES:
            reply = {"ok": outcome == "saved", "say": "tool words in /Users/x/Zones", "op": "a19f3c80",
                     "state": ops.state_for(outcome), "outcome": outcome}
            out = pa.with_plain(dict(reply), {"verb": "park"}, ops)
            if outcome == "saved":
                self.assertNotIn("plain", out)
                continue
            self.assertFalse(out["ok"], outcome)
            band = out["plain"]["band"]
            self.assertEqual(outcome, out["plain"]["code"])
            self.assertNotRegex(band, RAW)
            for m in SUCCESS.finditer(band):
                self.assertRegex(band[:m.start()], r"(?i)\b(not|no)\s+$", "%s: %s" % (outcome, band))

    def test_a_reply_that_says_it_worked_without_the_record_is_never_saved(self):
        out = pa.with_plain({"ok": True, "say": "Parked Birch Entry"}, {"verb": "park"}, ops)
        self.assertEqual("unrecorded", out["plain"]["code"])
        self.assertNotRegex(out["plain"]["band"], r"(?i)\bsaved\b")

    def test_every_failing_outcome_has_a_row_and_the_page_script_names_its_table(self):
        for outcome in ops.OUTCOMES:
            if outcome != "saved":
                self.assertIn(outcome, pa.FAILURE_CODES)
        page = (STATUS / "status.py").read_text(encoding="utf-8")
        self.assertIn("function fw(c)", page)
        self.assertIn("<details class=\"wdet\"", page)             # the tool's text sits under Details
        self.assertIn("<summary>Details</summary>", page)

    def test_the_details_disclosure_is_closed_unless_the_reader_opened_it(self):
        page = (STATUS / "status.py").read_text(encoding="utf-8")
        self.assertIn("(e.open?' open':'')", page)


class TestTheHandOff(unittest.TestCase):
    def setUp(self):
        self.H = pa.handoff()

    def test_each_hand_off_failure_names_its_row_and_keeps_the_tools_words(self):
        for exc, code in ((self.H.TimedOut("late /Users/x"), "handoff-late"), (self.H.LocalOff("off /Users/x"), "handoff-off"),
                          (self.H.HandOffError("no /Users/x"), "handoff")):
            e = pa.hand_off_failure(exc)
            self.assertEqual(code, e.reply["failure"])
            self.assertEqual(str(exc), str(e))
            out = pa.with_plain({"ok": False, "say": str(e), "failure": e.reply["failure"]}, {"verb": "continue"}, ops)
            self.assertEqual(code, out["plain"]["code"])
            self.assertNotRegex(out["plain"]["band"], RAW)

    def test_a_first_look_that_cannot_open_is_its_own_row(self):
        e = pa.hand_off_failure(self.H.HandOffError("x"), "handoff-look")
        self.assertEqual("handoff-look", e.reply["failure"])

    def test_every_hand_off_site_names_a_row(self):
        text = (STATUS / "page_action.py").read_text(encoding="utf-8")
        self.assertNotIn("raise Refused(H.NO_CLI)", text)
        self.assertNotRegex(text, r"except H\.HandOffError as e:\n(\s+\w.*\n)?\s+raise Refused\(")

    def test_a_timed_out_hand_off_offers_refresh_and_never_a_second_window(self):
        row = pa.plain_failure("handoff-late")
        self.assertEqual("Refresh", row["next"])


class TestAsk(unittest.TestCase):
    def test_each_failed_reply_carries_the_row_and_keeps_the_tools_words(self):
        for code in ("ask-start", "ask-silent", "ask-stopped", "ask-failed"):
            out = ask.failing({"say": "Something went wrong: KeyError: /Users/x/y.", "ok": False}, code)
            self.assertEqual(code, out["plain"]["code"])
            self.assertIn("KeyError", out["say"])                      # nothing dropped: it is the Details
            self.assertNotRegex(out["plain"]["say"], RAW)
            self.assertNotIn("KeyError", out["plain"]["band"])

    def test_each_site_in_ask_names_a_row(self):
        text = (STATUS / "ask.py").read_text(encoding="utf-8")
        for code in ("ask-start", "ask-silent", "ask-stopped", "ask-failed"):
            self.assertIn('"%s")' % code, text)

    def test_an_unexpected_error_offers_no_resend_but_a_bad_request_does(self):
        text = (STATUS / "ask.py").read_text(encoding="utf-8")
        branch = text.split("except Exception as e:  # a bug must still say so")[1].split("if out.get(")[0]
        self.assertIn('"ask-stopped")', branch)
        self.assertNotIn("ask-failed", branch)
        bad = text.split("except Capped as e:")[1].split("except Exception as e:")[0]
        self.assertIn('"ask-failed")', bad)
        self.assertNotEqual("retry", pa.FAILURES[[r[0] for r in pa.FAILURES].index("ask-stopped")][3])

    def test_the_apps_own_rows_are_the_tables(self):
        for name, code in (("askNoStart", "ask-start"), ("askNoAnswer", "ask-stopped"), ("askNoReply", "ask-silent")):
            m = re.search(r'let %s: \[String: Any\] = \["code": "([^"]+)", "say": "([^"]+)", "next": "([^"]+)"\]' % name, SWIFT)
            self.assertIsNotNone(m, name)
            row = pa.plain_failure(code)
            self.assertEqual((code, row["say"], row["next"]), m.groups())

    def test_the_ask_window_shows_the_sentence_with_details_closed(self):
        self.assertIn('turn.detail = turn.reply == line ? "" : turn.reply', SWIFT)
        self.assertIn('turn.detailOpen ? "Hide details" : "Details"', SWIFT)
        self.assertIn("if turn.detailOpen { out.append", SWIFT)
        self.assertIn("var detailOpen = false", SWIFT)

    def test_try_again_sends_the_same_request_once_and_only_from_the_last_turn(self):
        self.assertIn("askSend(askTurns[n].request)", SWIFT)
        self.assertIn("n == askTurns.count - 1, askRunning == nil", SWIFT)


class TestThePage(unittest.TestCase):
    def test_a_failure_outside_the_table_has_its_sentence_and_its_action(self):
        for code, (path, sentence, action, _test) in OUTSIDE.items():
            text = path.read_text(encoding="utf-8")
            self.assertIn(sentence, text, code)
            if code == "page-old":
                self.assertIn("textContent='" + action + "'", text)
                self.assertIn("textContent='Details'", text)
                self.assertIn("Built '+document.body.dataset.built", text)

    def test_the_rebuild_failure_shows_no_path(self):
        body = SWIFT.split("func rebuild(")[1].split("\n\t// ")[0]
        self.assertNotIn("Cannot run", body)


PAGE = (STATUS / "status.py").read_text(encoding="utf-8")


def block(name, text=PAGE):
    """The text of a JS block of status.py, `NAME = r\"\"\" ... \"\"\"`."""
    return text.split("\n%s = r\"\"\"" % name, 1)[1].split('\n"""', 1)[0]


class TestThePanels(unittest.TestCase):
    """#511's rest: a panel that printed a failed reply's own text draws its row of FAILURES with GarrickFail instead: the
    sentence, one next step that does what it says, and the reply's text under Details, closed."""

    def test_the_drawing_function_puts_the_sentence_first_and_the_tools_text_under_details_closed(self):
        work = block("WORK_JS")
        fn = work.split("window.GarrickFail=function(el,code,raw,again)", 1)[1].split("})();", 1)[0]
        self.assertIn("s.textContent=r[1]", fn)                   # the sentence, as text
        self.assertIn("m.textContent='Details'", fn)
        self.assertIn("p.textContent=raw", fn)                      # the tool's words only under Details
        self.assertNotIn(".open=true;var", fn)
        self.assertNotIn("innerHTML", fn)
        self.assertLess(fn.index("d=document.createElement('details')"), fn.index("d.open=true"))  # opened only by Show why
        self.assertIn("r[3]==='retry'&&typeof again==='function'", fn)   # Try again shows only where the panel can try again
        self.assertIn("r[3]==='why'&&d", fn)                               # Show why only where there is something to show
        self.assertIn('setAttribute(\'data-failure\',r[0])', fn)
        # defined before the host check, so a browser has it too
        self.assertLess(work.index("window.GarrickFail="), work.index("if(!host)return"))

    def test_the_release_check_and_the_update_draw_their_rows(self):
        js = block("RELEASE_JS")
        self.assertIn("failed('release-check',out&&out.say,function(){btn.click()}", js)
        self.assertIn("failed('release-update',out.say,null", js)
        self.assertNotIn("put((out&&out.say)", js)                # the reply's text is never the line
        self.assertIn("GarrickFail(box,code,raw,again)", js)
        self.assertIn("GarrickFailClear(box)", js)

    def test_the_memory_count_draws_its_row_and_tries_again_by_counting_again(self):
        js = block("MEMORY_JS")
        self.assertIn("GarrickFail(said,'count',out&&out.say,ask)", js)
        self.assertIn("GarrickFailClear(said)", js)
        self.assertIn("else if(window.GarrickFail)GarrickFail(said,'count'", js)       # the reply's text only without the helper
        self.assertIn("verb:'memory-preview'", js.split("function ask()", 1)[1].split("\n", 2)[0] + js.split("function ask()", 1)[1].split("\n", 3)[1])   # Try again only counts

    def test_the_note_preview_draws_its_rows_and_a_missing_note_offers_no_second_try(self):
        js = block("NOTE_JS")
        self.assertIn("failed('note-open',out,'That did not open.',function(){openIn(cur&&cur.path)})", js)
        self.assertIn("failed('note-read',out,'That note could not be read.',function(){read(cur.path,t,b)})", js)
        self.assertIn("GarrickFail(p,code,out&&out.say,out&&out.missing?null:again)", js)
        self.assertIn("GarrickFailClear(p)", js)
        self.assertNotIn("said((out&&out.say)||'That did not open.',true);return}", js)

    def test_the_wall_sentence_is_shown_as_it_stands(self):
        fn = block("WORK_JS").split("window.GarrickFail=function", 1)[1]
        self.assertIn("if(/^A wall holds /.test(raw)){el.textContent=raw;el.setAttribute('data-failure','wall');return el}", fn)

    def test_a_row_that_writes_never_offers_a_second_try(self):
        for code in ("release-update",):
            self.assertNotEqual("retry", next(r for r in pa.FAILURES if r[0] == code)[3], code)


# A small DOM, enough for GarrickFail: elements with children, text, attributes, click listeners and `open`.
DOM = r"""
function E(tag){this.tagName=tag.toUpperCase();this.children=[];this.attrs={};this.ls={};this.hidden=true;this.open=false;this.className='';this._t=''}
Object.defineProperty(E.prototype,'textContent',{get:function(){return this._t+this.children.map(function(c){return c.textContent}).join('')},
set:function(v){this._t=String(v);this.children=[]}});
E.prototype.appendChild=function(c){this.children.push(c);return c};
E.prototype.setAttribute=function(k,v){this.attrs[k]=String(v)};E.prototype.removeAttribute=function(k){delete this.attrs[k]};
E.prototype.getAttribute=function(k){return k in this.attrs?this.attrs[k]:null};
E.prototype.addEventListener=function(k,f){this.ls[k]=f};E.prototype.focus=function(){};
E.prototype.click=function(){if(this.ls.click)this.ls.click({preventDefault:function(){},stopPropagation:function(){}})};
E.prototype.querySelector=function(sel){var t=sel.toUpperCase();for(var i=0;i<this.children.length;i++){var c=this.children[i];
if(c.tagName===t)return c;var d=c.querySelector?c.querySelector(sel):null;if(d)return d}return null};
var window={},document={createElement:function(t){return new E(t)},createTextNode:function(t){var e=new E('#text');e._t=t;return e}};
"""

HARNESS = r"""
const vm=require('vm');const [work,code,raw,withAgain]=JSON.parse(process.argv[1]);
const c={};vm.createContext(c);vm.runInContext(DOM+work,c);
vm.runInContext("var el=new E('p'),tried=0;window.GarrickFail(el,"+JSON.stringify(code)+","+JSON.stringify(raw)+","+(withAgain?"function(){tried++}":"null")+");",c);
const out=vm.runInContext("(function(){var kids=el.children.filter(function(k){return k.tagName!=='#TEXT'});"
+"var d=el.querySelector('details'),b=el.querySelector('button');var r={first:kids.length?kids[0].tagName:null,firstText:kids.length?kids[0].textContent:el.textContent,"
+"failure:el.getAttribute('data-failure'),button:b?b.textContent:null,act:b?b.getAttribute('data-fail-next'):null,"
+"details:d?d.children[1].textContent:null,openBefore:d?d.open:null};"
+"if(b){b.click();r.openAfter=d?d.open:null;r.tried=tried;r.failureAfter=el.getAttribute('data-failure')}return JSON.stringify(r)})()",c);
console.log(out);
""".replace("DOM", json.dumps(DOM))


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestTheDrawingRuns(unittest.TestCase):
    """GarrickFail run in Node against a small DOM: the sentence comes first, the tool's text sits under Details, closed, and
    each button does what it says."""

    def draw(self, code, raw, again):
        from test_status import status       # noqa: E402  (the page, loaded as its tests load it)
        work = status.WORK_JS
        r = subprocess.run(["node", "-e", HARNESS, json.dumps([work, code, raw, again])], capture_output=True, text=True, timeout=60)
        self.assertEqual(0, r.returncode, r.stderr)
        return json.loads(r.stdout)

    def test_each_new_row_draws_its_sentence_first_and_its_text_under_details_closed(self):
        raw = "Traceback (most recent call last): /Users/x/System/tools/release.py exit 1"
        for code in PANELS:
            with self.subTest(code=code):
                row = pa.plain_failure(code)
                got = self.draw(code, raw, True)
                self.assertEqual("SPAN", got["first"])
                self.assertEqual(row["say"], got["firstText"])
                self.assertNotRegex(got["firstText"], RAW)
                self.assertEqual(code, got["failure"])
                self.assertEqual(raw, got["details"])
                self.assertFalse(got["openBefore"])
                self.assertEqual(row["next"], got["button"])

    def test_show_why_opens_details_and_try_again_runs_the_panels_own_request_once(self):
        for code in PANELS:
            with self.subTest(code=code):
                got = self.draw(code, "tool words", True)
                if pa.FAILURES[pa.FAILURE_CODES.index(code)][3] == "why":
                    self.assertTrue(got["openAfter"])
                    self.assertEqual(0, got["tried"])
                else:
                    self.assertEqual(1, got["tried"])
                    self.assertIsNone(got["failureAfter"])

    def test_no_button_where_it_could_not_do_what_it_says(self):
        for code in PANELS:
            with self.subTest(code=code):
                act = pa.FAILURES[pa.FAILURE_CODES.index(code)][3]
                if act == "retry":
                    self.assertIsNone(self.draw(code, "tool words", False)["button"])     # no way to try again: no Try again
                else:
                    self.assertIsNone(self.draw(code, "", True)["button"])                # nothing to show: no Show why


class TestSettingsRows(unittest.TestCase):
    def test_each_settings_row_is_in_the_docs_list(self):
        docs = (REPO / "docs" / "extras" / "status-page.md").read_text(encoding="utf-8")
        for code, say, *_ in pa.FAILURES:
            if code.startswith(("role-", "guard-")):
                self.assertIn(say, docs, code)


class TestTheDocs(unittest.TestCase):
    def test_the_docs_list_every_sentence_and_the_failure_nothing_produces(self):
        docs = (REPO / "docs" / "extras" / "status-page.md").read_text(encoding="utf-8")
        section = docs[docs.index("## When something fails"):docs.index("## What the actions keep")]
        for code, say, *_ in pa.FAILURES:
            if say:
                self.assertIn(say, section, code)
        self.assertIn("Recall's index is old", section)
        self.assertIn(pa.plain_failure("ask-start")["say"], section)


if __name__ == "__main__":
    unittest.main()
