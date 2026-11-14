"""The Context tab's one card (#542): a line for each zone or wiki that holds something, one queue for every kind, and no
count that adds two zones.

    cd tests && python3 -m unittest test_context_card

Invented names only: the zones are Work and Personal, the projects Acme and Birch.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
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
from panel_case import commit_all  # noqa: E402
from test_decisions import RECORD, answer_record, decision  # noqa: E402
from test_questions_panel import ACME, BIRCH, ELSEWHERE, TODAY, Panel, fq, question, status  # noqa: E402

NOW = dt.datetime(2026, 11, 5, 9, 0)
RESUME = ("Zones/Work/Acme/Threads/Pricing/Pricing.md: its Resume here block has 520 words, over the 400 of `resume-max-words`; "
          "the next wrap or Nurture proposes a shorter one, and nothing changes without a yes")
THREAD = "Zones/Work/Acme/Threads/Pricing/Pricing.md"
KNOWLEDGE = "Knowledge: which year?"


class CardCase(Panel):
    def page(self, now=NOW):
        with mock.patch.object(status, "launch_agents", lambda: self.root / "LaunchAgents"):
            return status.build(self.root, now=now, folder=self.jobs)

    def card(self, html):
        start = html.index('<details class="card" id="checks"')
        ends = [i for i in (html.find('<details class="card" id="', start + 1), html.find("</section>", start)) if i > 0]
        return html[start:min(ends)]

    def queue(self, html):
        start = html.index('<dialog id="queue"')
        return html[start:html.index("</dialog>", start)]

    def scope(self, html, scope):
        q = self.queue(html)
        at = q.index('data-scope="%s"' % scope)
        return q[at:q.index("</section>", at)]

    def lines(self, card):
        return dict(re.findall(r'<span class="nsay"><b>([^<]*)</b>: ([^<]*)</span>', card))

    def record(self, standing=(), back=0):
        """A Nurture record, and a quick check that lists what it holds, so the queue keeps it."""
        day = NOW.date() - dt.timedelta(days=back)
        N = status.nurture_lib(self.root)[0]
        scopes = {}
        for f in standing:
            sc = N.debt_scope(f["path"])
            scopes.setdefault(sc, {})
            scopes[sc][f["kind"]] = scopes[sc].get(f["kind"], 0) + 1
        write(self.root / "System" / "generated" / "nurture" / ("%s.json" % day.isoformat()), json.dumps({
            "date": day.isoformat(), "standing": list(standing), "debt": {"total": len(standing), "kinds": {}, "scopes": scopes, "whole": True, "threshold": 40}}))
        listed = [{"check": f.get("check", ""), "severity": "warning", "path": f["path"], "message": f["line"].split(": ", 1)[-1]}
                  for f in standing if f["kind"] != "wall"]
        write(self.root / "System" / "tools" / "check.py", "import json\nprint(json.dumps(%r))\n" % {
            "errors": 0, "warnings": len(listed), "findings": listed})
        status._NURTURE.clear()
        self.addCleanup(status._NURTURE.clear)


class TestOneLineForEachPlace(CardCase):
    def test_a_line_names_a_places_questions_and_answers_and_a_place_with_nothing_has_none(self):
        self.record()
        card = self.card(self.page())
        self.assertEqual({"Work": "2 questions · about 5 minutes",
                          "Personal": "1 question · about 5 minutes",
                          "The Knowledge wiki": "1 question · about 5 minutes"}, self.lines(card))
        for q in (self.meetings / "questions" / "261001 - elsewhere.md", ):
            q.unlink()
        card = self.card(self.page())
        self.assertNotIn("Personal", self.lines(card))                              # a zone with nothing has no line
        self.assertEqual(["Work", "The Knowledge wiki"], list(self.lines(card)))     # zones first, then the wikis

    def test_a_failing_findings_read_still_shows_the_wikis_questions(self):
        self.record()
        with mock.patch.object(status, "finding_queues", return_value=None):
            html = self.page()
        card = self.card(html)
        self.assertIn("question", self.lines(card).get("Work", ""))                # the zone's wiki question line is still there
        self.assertIn('data-qopen="Zones/Work"', card)
        self.assertIn('data-scope="Zones/Work"', self.queue(html))

    def test_a_failing_findings_read_with_no_wiki_question_never_says_nothing_needs_you(self):
        for f in list((self.meetings / "questions").glob("*.md")) + [self.knowledge_q]:
            f.unlink()
        self.record([{"kind": "judgment", "check": "resume", "path": THREAD, "line": RESUME}])
        with mock.patch.object(status, "finding_queues", return_value=None):
            card = self.card(self.page())
        self.assertNotIn("Nothing needs you.", card)                                  # a failed read is not a clean workspace
        self.assertIn(">Nurture<", card)                                              # Nurture's line stands for the findings

    def test_a_failing_findings_read_beside_a_wiki_question_keeps_nurtures_lines(self):
        self.record([{"kind": "judgment", "check": "resume", "path": THREAD, "line": RESUME}])
        with mock.patch.object(status, "finding_queues", return_value=None):
            card = self.card(self.page())
        self.assertNotIn("Nothing needs you.", card)
        self.assertIn('data-qopen="Zones/Work"', card)                                 # the wiki's question line
        self.assertIn(">Nurture<", card)                                              # and Nurture's line for the findings

    def test_the_zone_menu_has_its_script_whenever_the_card_has_the_menu(self):
        for f in list((self.meetings / "questions").glob("*.md")) + [self.knowledge_q]:
            f.unlink()
        personal = THREAD.replace("Zones/Work/Acme", "Zones/Personal/Birch")
        self.record([{"kind": "judgment", "check": "resume", "path": THREAD, "line": RESUME},
                     {"kind": "judgment", "check": "resume", "path": personal, "line": RESUME.replace(THREAD, personal)}])
        with mock.patch.object(status, "questions_data", return_value=None):       # the wikis cannot be placed: no Questions data
            html = self.page()
        card = self.card(html)
        self.assertIn('id="nzone"', card)                                           # two places hold findings, and no wiki question
        self.assertIn("window.GarrickQuestions={open:", html)                       # so the menu's script is on the page
        self.assertIn("sel.onchange=function()", html)

    def test_nothing_anywhere_says_so_once_a_record_exists(self):
        for f in list((self.meetings / "questions").glob("*.md")) + [self.knowledge_q]:
            f.unlink()
        self.record()
        card = self.card(self.page())
        self.assertIn("Nothing needs you.", card)
        self.assertEqual({}, self.lines(card))
        self.assertNotIn("data-qopen", card)

    def test_without_a_record_the_card_does_not_claim_nothing_needs_you(self):
        for f in list((self.meetings / "questions").glob("*.md")) + [self.knowledge_q]:
            f.unlink()
        card = self.card(self.page())
        self.assertNotIn("Nothing needs you.", card)

    def test_a_work_line_counts_works_questions_verdicts_decisions_and_findings_together_and_nothing_else(self):
        write(self.meetings / "questions" / "261001 - birch.md", question(BIRCH, parties="[birch]", extra="verdict: done\nverdict_reason: the call settled it\n"))
        write(self.meetings / RECORD, answer_record())
        write(self.meetings / "wiki" / "decisions" / "261005 - acme.md", decision(extra='revisit: "A later meeting named another vendor."\n'))
        commit_all(self.meetings, "kinds")
        self.record([{"kind": "judgment", "check": "resume", "path": THREAD, "line": RESUME}])
        html = self.page()
        card = self.card(html)
        lines = self.lines(card)
        self.assertEqual("4 questions · about 5 minutes", lines["Work"])   # one question, one verdict, one decision, one finding
        self.assertEqual("1 question · about 5 minutes", lines["Personal"])
        self.assertIn("3 places need you.", card)                                    # places, and never a figure that adds two zones
        for added in ("5 questions", "6 questions", "in all", "7 questions"):
            self.assertNotIn(added, card)
        work = self.scope(html, "Zones/Work")
        self.assertEqual(4, work.count("data-q "))
        self.assertEqual(1, self.scope(html, "Zones/Personal").count("data-q "))
        for other in (ELSEWHERE, KNOWLEDGE):
            self.assertNotIn(other, work)                                            # an item is in the queue of its own zone only
        self.assertNotIn(ACME, self.scope(html, "Zones/Personal"))

    def test_no_element_adds_two_zones(self):
        self.record()
        html = self.page()
        card = self.card(html)
        counts = [int(n) for n in re.findall(r'data-n="(\d+)"', card)]
        self.assertEqual([1, 2, 1], counts)                                          # one place's own number on each line
        self.assertEqual(["*", "Zones/Personal", "Zones/Work", "Wikis/Knowledge"],
                         re.findall(r'<option value="([^"]+)">', card))              # the Zone menu: All, then each place
        self.assertNotIn("4 questions", card)                                        # 2 + 1 + 1: never shown
        self.assertEqual(["", ], re.findall(r'id="qp-tab-n">([^<]*)<', html))        # the tab's number is set for one place only, by the script


QUEUE_HARNESS = r"""
const fs=require('fs');
const js=fs.readFileSync(process.argv[2],'utf8');
function el(extra){const base={dataset:{},hidden:false,textContent:'',style:{},classList:{toggle(){},add(){},remove(){},contains(){return false}},
 getClientRects(){return[1]},querySelectorAll(){return[]},querySelector(){return el()},closest(){return null},focus(){},setAttribute(k,v){this[k]=v},getAttribute(){return ''},appendChild(){},remove(){},click(){}};
 return Object.assign(base,extra||{})}
const clicked=[],handlers={},store={};
const q1=el({dataset:{gk:'k1',wiki:'Meetings',file:'questions/a.md',kind:'wiki-question',path:'Wikis/Meetings/questions/a.md'}});
const q2=el({dataset:{gk:'k2',wiki:'Meetings',file:'questions/b.md',kind:'wiki-question',path:'Wikis/Meetings/questions/b.md'}});
const work=el({dataset:{scope:'Zones/Work',name:'Work',work:'work in the answers in Work'}});
const other=el({dataset:{scope:'Zones/Personal',name:'Personal',work:'work in the answers in Personal'}});
work.querySelectorAll=(s)=>s==='[data-q]'?[q1,q2]:[];other.querySelectorAll=(s)=>s==='[data-q]'?[]:[];
const posted=[];let scopes=[work,other];
const dlg=el({dataset:{folder:'/w',today:'2026-11-13'},open:false,
 querySelectorAll:(s)=>s==='.qscope'?scopes:[],querySelector:()=>el(),
 addEventListener:(t,f)=>{(handlers[t]=handlers[t]||[]).push(f)},showModal(){this.open=true},close(){this.open=false;(handlers.close||[]).forEach(f=>f())},
 appendChild(b){this.last=b}});
global.window={webkit:{messageHandlers:{garrick:{postMessage:(m)=>posted.push(m)}}}};
global.sessionStorage={getItem:(k)=>store[k]||null,setItem:(k,v)=>{store[k]=v},removeItem:(k)=>{delete store[k]}};
global.document={getElementById:(id)=>id==='queue'?dlg:null,addEventListener:(t,f)=>{(handlers['doc'+t]=handlers['doc'+t]||[]).push(f)},
 createElement:()=>{const b=el();b.click=function(){clicked.push(this['data-request'])};return b}};
global.Object=Object;
new Function(js)();
function open(scope){const t=el({dataset:{qopen:scope}});t.closest=(s)=>s==='[data-qopen]'?t:null;(handlers.docclick||[]).forEach(f=>f({target:t,preventDefault(){}}))}
function acted(verb,wiki,file,ok){window.GarrickActed({verb,wiki,file,answer:undefined},{ok})}
const steps=process.argv[3];
open('Zones/Work');
if(steps==='none'){dlg.close()}
if(steps==='one'){acted('question-answer','Meetings','questions/a.md',true);dlg.close();dlg.open=true;dlg.close()}
if(steps==='reload'||steps==='reload-twice'){acted('question-answer','Meetings','questions/a.md',true);
 scopes=[other];handlers.close=[];handlers.docclick=[];dlg.open=false;new Function(js)();      // the page reloads: Work has no section any more
 dlg.open=true;dlg.close();if(steps==='reload-twice'){dlg.open=true;dlg.close()}}
if(steps==='failed'){acted('question-answer','Meetings','questions/a.md',false);dlg.close()}
// a reload that leaves no section for the place (or, for load-open, leaves it), with the dialog never reopened by hand
let atLoad=null;
if(steps.startsWith('load-')){acted('question-answer','Meetings','questions/a.md',true);
 if(steps==='load-stale'){const k=JSON.parse(store['garrick-queue']);k.t=Date.now()-16*60*1000;store['garrick-queue']=JSON.stringify(k)}
 scopes=steps==='load-open'?[work,other]:[other];handlers.close=[];handlers.docclick=[];dlg.open=false;new Function(js)();
 if(steps==='load-twice'){handlers.close=[];handlers.docclick=[];dlg.open=false;new Function(js)()}
 atLoad=clicked.length}
if(steps==='later'){acted('question-later','Meetings','questions/a.md',true);dlg.close()}
setTimeout(()=>{const loaded=clicked.slice();if(dlg.open)dlg.close();
 console.log(JSON.stringify(atLoad===null?clicked:{atLoad,loaded,final:clicked.slice()}))},20);
"""


class TestAnswersAreWorkedInWithoutAButton(CardCase):
    """#550: no Work them in and no count of answers on the card; closing the queue sends the request, once, for its own place."""

    def test_the_card_has_no_button_and_no_count_for_answers(self):
        self.record()
        html = self.page()
        card = self.card(html)
        for gone in ("Work them in", "to work in", "answer to work", "data-request=\"work in the answers"):
            self.assertNotIn(gone, card)
        self.assertEqual(["Work", "Personal", "The Knowledge wiki"], sorted(self.lines(card), key=["Work", "Personal", "The Knowledge wiki"].index))

    def test_each_place_carries_the_request_for_its_own_place_only(self):
        self.record()
        queue = self.queue(self.page())
        got = dict(re.findall(r'data-scope="([^"]+)" data-name="[^"]*" data-work="([^"]+)"', queue))
        self.assertEqual({"Zones/Work": "work in the answers in Work", "Zones/Personal": "work in the answers in Personal",
                          "Wikis/Knowledge": "work in the answers in the Knowledge wiki"}, got)
        self.assertEqual(3, queue.count("data-work="))

    def test_closing_a_queue_that_took_an_answer_sends_one_request_and_a_second_close_none(self):
        js = fq.QUEUE_JS
        # a successful answer counts for its own place, a failed one and a close or a later do not
        self.assertIn("if(q.verb==='question-answer'||q.verb==='question-decide')(taken[cur.dataset.scope]=taken[cur.dataset.scope]||{n:0,work:cur.dataset.work||''}).n++", js)
        self.assertIn("dlg.addEventListener('close',function(){workIn(false)});", js)      # a close sends the request, through the one function
        close = js[js.index("function workIn(later){"):]
        close = close[:close.index("\ndlg.addEventListener")]
        self.assertIn("handoff(t.work)", close)                                # the request that was the button's, kept with the count
        self.assertIn("taken={}", close)                                       # cleared as it goes: a second close has nothing to send
        self.assertIn("if(!t||!t.n||!t.work)return", close)                            # a place that took none sends none
        self.assertIn("taken:taken", js)                                        # a reload while the queue is open keeps the count

    def test_answers_the_night_could_not_work_in_are_a_question_of_their_own_place_only(self):
        self.record()
        write(self.root / "System" / "generated" / "status-answers.json",
              json.dumps({"held": {"Zones/Work": {"why": "cap", "day": "2026-11-13"}, "Zones/Personal": {"why": "held", "day": "2026-11-13"}}}))
        html = self.page()
        work = self.scope(html, "Zones/Work")
        self.assertEqual(1, work.count('data-kind="answers-held"'))
        self.assertIn("Your answers in Work could not be worked in.", work)
        self.assertIn("Work them in with my assistant", work)
        self.assertNotIn('data-kind="answers-held"', self.scope(html, "Zones/Personal"))       # Personal holds no answer: a stale entry shows nothing
        self.assertEqual("3 questions · about 5 minutes", self.lines(self.card(html))["Work"])

    def test_the_queue_script_sends_the_request_as_the_card_once_did(self):
        """Run on stand-in elements: one answer taken, then the dialog closed twice, sends one request naming its own place;
        a failed answer, a Later and a close with nothing taken send none."""
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        with tempfile.TemporaryDirectory() as tmp:
            script, queue = Path(tmp) / "h.js", Path(tmp) / "q.js"
            script.write_text(QUEUE_HARNESS, encoding="utf-8")
            queue.write_text(fq.QUEUE_JS, encoding="utf-8")
            sent = {}
            for steps in ("none", "one", "failed", "later", "reload", "reload-twice"):
                out = subprocess.run([node, str(script), str(queue), steps], capture_output=True, text=True, timeout=60)
                self.assertEqual(0, out.returncode, out.stderr)
                sent[steps] = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual({"none": [], "one": ["work in the answers in Work"], "failed": [], "later": [],
                          "reload": ["work in the answers in Work"], "reload-twice": ["work in the answers in Work"]}, sent)   # a reload that removes the section loses nothing, and sends once

    def test_a_reload_that_removes_the_section_sends_the_kept_request_at_once_and_only_once(self):
        """D: the kept "work in the answers" request goes when the page loads with it and no open queue, not at the next close of one;
        it is marked sent as a close marks it; a section that is still there keeps it for its close; after 15 minutes it is dropped."""
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        with tempfile.TemporaryDirectory() as tmp:
            script, queue = Path(tmp) / "h.js", Path(tmp) / "q.js"
            script.write_text(QUEUE_HARNESS, encoding="utf-8")
            queue.write_text(fq.QUEUE_JS, encoding="utf-8")
            got = {}
            for steps in ("load-gone", "load-twice", "load-open", "load-stale"):
                out = subprocess.run([node, str(script), str(queue), steps], capture_output=True, text=True, timeout=60)
                self.assertEqual(0, out.returncode, out.stderr)
                got[steps] = json.loads(out.stdout.strip().splitlines()[-1])
        sent = ["work in the answers in Work"]
        self.assertEqual({"atLoad": 0, "loaded": sent, "final": sent}, got["load-gone"])        # sent after the load, before any close, once
        self.assertEqual({"atLoad": 0, "loaded": sent, "final": sent}, got["load-twice"])  # a second load finds nothing kept
        self.assertEqual({"atLoad": 0, "loaded": [], "final": sent}, got["load-open"])          # the queue is open again: its close sends
        self.assertEqual({"atLoad": 0, "loaded": [], "final": []}, got["load-stale"])           # dropped after 15 minutes


class TestLater(CardCase):
    def test_a_later_with_a_day_after_today_hides_the_question_until_that_day_and_no_due_count_exists(self):
        write(self.meetings / "questions" / "261001 - acme.md", question(ACME, status="later", extra="later: 2026-11-10\n"))
        commit_all(self.meetings, "later")
        self.record()
        before = self.page()
        self.assertNotIn(ACME, before)
        self.assertEqual("1 question · about 5 minutes", self.lines(self.card(before))["Work"])
        on_the_day = self.page(now=dt.datetime(2026, 11, 10, 9, 0))
        self.assertIn(ACME, self.scope(on_the_day, "Zones/Work"))                    # the day has come: a question again
        self.assertEqual("2 questions · about 5 minutes", self.lines(self.card(on_the_day))["Work"])
        for page in (before, on_the_day):
            self.assertNotIn("due today", page)


class TestTheQueueAsksEveryKind(CardCase):
    def setUp(self):
        super().setUp()
        write(self.meetings / "questions" / "261001 - birch.md", question(BIRCH, parties="[birch]", extra="verdict: done\nverdict_reason: the call settled it\n"))
        write(self.meetings / RECORD, answer_record())
        write(self.meetings / "wiki" / "decisions" / "261005 - acme.md", decision(extra='revisit: "A later meeting named another vendor."\n'))
        commit_all(self.meetings, "kinds")
        self.record([{"kind": "judgment", "check": "resume", "path": THREAD, "line": RESUME}])

    def test_a_wiki_question_a_verdict_and_a_decision_each_with_its_answers_and_the_kinds_label(self):
        work = self.scope(self.page(), "Zones/Work")
        for tag in ("Meetings question", "Proposed verdict", "Decision to review", "Tidy up"):
            self.assertIn('<span class="tag">%s</span>' % tag, work)
        self.assertIn('placeholder="Type the answer"', work)                         # the field of a wiki question
        self.assertIn("Record as a decision", work)
        self.assertIn(">Accept<", work)                                              # a verdict
        self.assertIn("Open the decision", work)
        self.assertNotIn("It still holds", work)                                     # left out: only the user changes a decision
        verbs = set(re.findall(r'&quot;verb&quot;: &quot;([a-z-]+)&quot;', work))
        self.assertEqual({"question-answer", "question-decide", "question-later", "question-close", "note-open", "finding"}, verbs)

    def test_the_order_is_walls_first_then_oldest_first(self):
        work = self.scope(self.page(), "Zones/Work")
        tags = re.findall(r'<span class="tag[^"]*">([^<]+)</span>', work)
        self.assertEqual(["Meetings question", "Proposed verdict", "Decision to review", "Tidy up"], tags)   # asked 1 Oct, 1 Oct, decided 5 Oct, no day

    def test_a_not_now_hides_a_verdict_from_the_next_build(self):
        key = fq.later_key("verdict", "Wikis/Meetings/questions/261001 - birch.md")
        write(self.root / "System" / "generated" / "status-later.json", json.dumps({"version": 1, "later": {key: "2026-11-12"}}))
        work = self.scope(self.page(), "Zones/Work")
        self.assertNotIn("Proposed verdict", work)
        self.assertEqual("3 questions · about 5 minutes", self.lines(self.card(self.page()))["Work"])


class TestTheLineBelow(CardCase):
    def test_the_debt_and_the_last_nurture_are_one_line_and_there_is_one_card(self):
        self.record()
        html = self.page()
        card = self.card(html)
        self.assertIn('<p class="hint ndebt"><span>Context debt 0, under 40</span> · Last nurture Thu 05 Nov</p>', card)
        self.assertEqual(1, html.count('<details class="card" id="checks"'))
        self.assertEqual(1, html.count("Context debt"))


if __name__ == "__main__":
    unittest.main()
