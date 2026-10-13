"""The status page's fuller features, against a fictional workspace: the Todo
tab, resume points, jobs that run or idle, the assistant's spend, a vault's
own graph colours, sessions from the cmux extra, shared launcher settings,
--settle and the folders effort.py is told about.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import datetime as dt
import html as htmllib
import io
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import project_hub, thread_note, write  # noqa: E402
from test_status import StatusCase, cards, graph_data, stamp, status  # noqa: E402


def attention(html):
    if 'id="attention"' not in html:
        return ""
    start = html.index('id="attention"')
    return html[start:html.index("</details>", start)]


def flags(root, **on):
    write(root / "System" / "garrick-flags.json", json.dumps(on))


class TestTodoTab(StatusCase):
    def setUp(self):
        super().setUp()
        self.now = dt.datetime(2026, 3, 11, 9, 0)
        write(self.root / "Zones" / "Work" / "Todo.md",
              "# Work: open actions\n\n## Inbox\n\n- [ ] [[Pricing]]: Send the revised terms 📅 2026-03-09\n"
              "- [ ] Book the room\n\n## This week\n\n- [ ] [[Market Sizing]]: Draft the sizing 🔺 📅 2026-03-12\n\n"
              "## Waiting on\n\n- [ ] Numbers from Birch #waiting ⏳ 2026-03-11\n\n## Soon\n\n## Done\n\n"
              "- [x] Sent the brief ✅ 2026-03-11\n- [x] An old one ✅ 2026-03-01\n")
        write(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Notes.md", "- [ ] Check the clause\n")

    def tab(self):
        html = self.page()
        start = html.index('id="todolist"')
        return html, html[start:html.index("</section>", start)]

    def test_grouped_as_the_todo_file_groups_them(self):
        _, tab = self.tab()
        names = re.findall(r'<span class="tname">([^<]*)</span>', tab)
        self.assertEqual(["Inbox",                                                              # Personal: an empty Inbox is said
                          "Inbox", "This week", "Waiting on", "In thread notes", "Done today"], names)   # Work; Soon is empty
        self.assertIn("Inbox clear.", tab)
        work = tab[tab.index('<div class="tz" data-zone="Work"'):]
        self.assertLess(work.index("Book the room"), work.index("Send the revised terms"))      # A-Z: no thread first
        self.assertIn("<b>5</b> open", work)
        self.assertIn("<b>2</b> overdue or due a chase", work)                                 # a chase is late on its day
        self.assertIn("<b>2</b> without a date", work)                            # the room, and the clause in its note
        self.assertIn("highest priority", work)
        self.assertIn("in the thread note", work)
        self.assertIn('<a class="thr" href="', work)                                           # the thread opens its note

    def test_a_system_project_thread_opens_its_note(self):
        setup = self.root / "System" / "Workspace Setup"
        write(setup / "Workspace Setup.md", "---\ntype: project\nstatus: active\n---\n\n# Workspace Setup\n")
        write(setup / "Threads" / "Setup" / "Setup.md", "---\ntype: thread\nstatus: active\n---\n\n# Setup\n")
        todo = self.root / "Zones" / "Work" / "Todo.md"
        todo.write_text(todo.read_text().replace("- [ ] Book the room\n", "- [ ] [[Setup]]: Rotate the backup key\n"))
        _, tab = self.tab()
        m = re.search(r'<a class="thr" href="([^"]*)">Setup</a>', tab)
        self.assertTrue(m, "the System thread's label is not a link")
        self.assertIn("System/Workspace%20Setup/Threads/Setup/Setup", m.group(1))

    def test_done_today_can_be_reopened_in_the_app(self):
        _, tab = self.tab()
        done = tab[tab.index("Done today"):]
        self.assertIn("Sent the brief", done)
        self.assertNotIn("An old one", tab)
        self.assertRegex(done, r'<div class="trow done[ "]')
        self.assertIn('aria-label="Reopen: Sent the brief"', done)
        self.assertIn("send(d?'todo-done':'todo-undo',r,null,", status.TODO_JS)

    def test_filters_sorts_and_zones(self):
        html, tab = self.tab()
        for control in ('data-tf="all"', 'data-tf="late"', 'data-tf="nodate"', 'data-ts="alpha"', 'data-ts="date"',
                        'data-tz="Work"', 'data-tz="Personal"'):
            self.assertIn(control, tab)
        self.assertRegex(tab, r'<div class="trow late" data-z="Work"[^>]*data-d="2026-03-09"')
        self.assertRegex(tab, r'<div class="trow undated" data-z="Work"')
        for rule in ('.todotab[data-tf="late"] .trow:not(.late)', '.todotab[data-tf="nodate"] .trow:not(.undated)'):
            self.assertIn(rule, status.TODO_CSS)
        self.assertIn("if(s==='date')", status.TODO_JS)
        self.assertIn("'garrick-todo-zone'", status.TODO_JS)
        self.assertIn('href="#todolist" data-tz-go="Work"', html)         # the Overview's line opens the tab on its zone

    def test_the_date_menu_and_a_pending_line(self):
        for choice in ("'Today'", "'Tomorrow'", "'Friday'", "'Next Monday'", "'In a week'", "'In two weeks'", "Clear the date"):
            self.assertIn(choice, status.TODO_JS)
        self.assertIn("send('todo-date',r,{date:v},", status.TODO_JS)            # an ISO date, worked out at the click
        self.assertIn("r.classList.add('pending')", status.TODO_JS)             # its key changes: no second click before the rebuild
        self.assertIn("window.TodoPending=function(z,target,date,text)", status.TODO_JS)
        self.assertIn("if(window.TodoPending)TodoPending(z,target,date,text)", status.JS)
        _, tab = self.tab()
        self.assertIn('<button class="tdate overdue" type="button"', tab)
        self.assertIn("＋ date", tab)

    def test_a_browser_shows_no_buttons(self):
        for rule in (".nohost .trow .tick{display:none}", ".nohost button.tdate{pointer-events:none}"):
            self.assertIn(rule, status.TODO_CSS)


class TestResumePoints(StatusCase):
    def note(self):
        return self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"

    def test_the_block_and_its_date(self):
        self.assertEqual((True, dt.date(2026, 3, 1)), status.resume_point(self.note()))
        self.note().write_text(thread_note("Acme Review", "Pricing").replace("1 March 2026", "2026-03-04"))
        self.assertEqual((True, dt.date(2026, 3, 4)), status.resume_point(self.note()))
        self.note().write_text(thread_note("Acme Review", "Pricing").replace("1 March 2026", "<D Month YYYY>"))
        self.assertEqual((True, None), status.resume_point(self.note()))
        self.note().write_text(thread_note("Acme Review", "Pricing").replace("### Resume here", "### Notes"))
        self.assertEqual((False, None), status.resume_point(self.note()))

    def test_a_live_thread_without_one_is_marked(self):
        self.note().write_text(thread_note("Acme Review", "Pricing").replace("### Resume here", "### Notes"))
        html = self.page()
        self.assertIn("no resume block</span>", html)
        self.assertIn("1 thread · 1 without a resume block", html)
        self.assertEqual(0, cards(html)[("Acme Review", "Pricing")]["r"])
        self.assertIn("'No resume block'", status.PANEL_JS)
        self.assertNotIn("Drafting", html)                                   # the block's words stay in the note

    def test_a_parked_thread_is_not_marked(self):
        self.note().write_text(thread_note("Acme Review", "Pricing", status="parked").replace("### Resume here", "### Notes"))
        self.assertNotIn("no resume block</span>", self.page())


class TestJobsMore(StatusCase):
    def beat(self, name="brief", **hb):
        body = {"job": name, "finished": stamp(self.now.timestamp() - 60), "exit": 0, "seconds": 30, "items": 1, "idle_days": 0}
        body.update(hb)
        (self.jobs / ("%s.heartbeat.json" % name)).write_text(json.dumps(body))

    def plists(self, **jobs):
        folder = self.jobs.parent / "LaunchAgents"
        folder.mkdir(exist_ok=True)
        for name, env in jobs.items():
            (folder / (name + ".plist")).write_bytes(plistlib.dumps({
                "Label": "garrick." + name, "ProgramArguments": ["/usr/bin/python3", "/w/System/jobs/job.py", name, "--", "true"],
                "EnvironmentVariables": env, "StartCalendarInterval": {"Hour": 6}}))
        return mock.patch.object(status, "launch_agents", lambda: folder)

    def test_running_now_while_the_lock_is_held(self):
        self.beat()
        lock = self.jobs / "brief.lock"
        lock.mkdir()
        (lock / "until").write_text("%d %d %d\n" % (self.now.timestamp() + 600, os.getpid(), self.now.timestamp()))
        self.assertIn(">running now", self.page())
        (lock / "until").write_text("%d %d\n" % (self.now.timestamp() - 1, os.getpid()))        # gone stale
        self.assertNotIn(">running now", self.page())
        (lock / "until").write_text("%d 999999999\n" % (self.now.timestamp() + 600))           # its process is gone
        self.assertNotIn(">running now", self.page())

    def test_an_idle_job_needs_attention(self):
        self.beat(idle_days=9, idle=True)
        self.assertIn("brief: idle 9 days", attention(self.page()))
        self.beat(idle_days=3)                                                 # an older job.py: under the limit
        self.assertNotIn("idle", attention(self.page()))
        with self.plists(brief={"GARRICK_IDLE_DAYS": "2"}):
            self.assertIn("brief: idle 3 days", attention(self.page()))

    def test_quiet_exits_are_fine(self):
        self.beat(exit=5)
        self.assertIn("brief: exit 5", attention(self.page()))
        for hb in ({"quiet": True}, {"ok": True}):
            self.beat(exit=5, **hb)
            html = self.page()
            self.assertNotIn("brief: exit 5", attention(html))
            self.assertIn("ok, exit 5 is quiet", html)
        self.beat(exit=5)
        with self.plists(brief={"GARRICK_QUIET_EXITS": "2, 5"}):
            self.assertNotIn("brief: exit 5", attention(self.page()))
        self.assertEqual((2, 5), status.quiet_exits({"GARRICK_QUIET_EXITS": "2 5,x"}))

    def test_a_run_that_called_no_assistant_is_said_not_raised(self):
        self.beat(no_call=True)
        html = self.page()
        self.assertIn("ok, called no assistant", html)
        self.assertNotIn("brief", attention(html))

    def test_a_quiet_line_in_the_log_is_a_good_day(self):
        self.beat()
        t = self.now.timestamp() - 2 * 86400
        (self.jobs / "brief.log").write_text("===== %s  brief  exit 5  (3s)  quiet =====\n\n" % stamp(t))
        runs = status.history(self.jobs, "brief", self.now)
        self.assertEqual([(5, True)], [(r[1], r[2]) for r in runs])
        self.assertEqual("good", status.day_cells(runs, self.now)[-3][0])

    def test_a_failure_says_its_reason(self):
        self.beat(exit=4, reason="could not sign in twice")
        self.assertIn("brief: exit 4: could not sign in twice", attention(self.page()))

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_changes_left_over_a_day_need_attention(self):
        from fixtures import commit_all, git_init
        work = self.root / "Zones" / "Work"
        shutil.rmtree(work / ".git")
        git_init(work)
        commit_all(work)
        draft = write(work / "Acme Review" / "Sources" / "draft.csv", "x\n")
        self.assertNotIn("Work: 1 changed file", attention(self.page()))
        old = self.now.timestamp() - 3 * 86400
        os.utime(draft, (old, old))
        self.assertIn("Work: 1 changed file, the oldest changed 3 days ago", attention(self.page()))


class TestSpend(StatusCase):
    def ledger(self, *entries):
        with (self.jobs / "ledger.jsonl").open("w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(dict({"ts": self.now.timestamp() - 600, "exit": 0}, **e)) + "\n")

    def plists(self, **env):
        folder = self.jobs.parent / "LaunchAgents"
        folder.mkdir(exist_ok=True)
        (folder / "brief.plist").write_bytes(plistlib.dumps({
            "Label": "garrick.brief", "EnvironmentVariables": env, "StartCalendarInterval": {"Hour": 6},
            "ProgramArguments": ["/usr/bin/python3", "/w/System/jobs/job.py", "brief", "--agent", "--", "true"]}))
        return mock.patch.object(status, "launch_agents", lambda: folder)

    def calls(self, html):
        start = html.index('id="calls"')
        return html[start:html.index("</details>", start)]

    def test_cost_per_day_once_three_days_have_calls(self):
        self.ledger({"job": "brief", "cost_usd": 0.5})
        with self.plists():
            self.assertIn("Recording since", self.calls(self.page()))
        day = 86400
        self.ledger({"job": "brief", "cost_usd": 0.5, "ts": self.now.timestamp() - 3 * day},
                    {"job": "brief", "cost_usd": 1.25, "ts": self.now.timestamp() - 2 * day},
                    {"job": "brief", "cost_usd": 0.25})
        with self.plists():
            block = self.calls(self.page())
        self.assertIn('<div class="cols" role="img"', block)
        self.assertEqual(status.DAYS, block.count("<b style=\"height:"))
        self.assertIn("<em>$0.25</em>", block)                                  # the newest day says its figure
        self.assertIn("1 call · $1.25", block)

    def test_turns_and_the_per_call_budget(self):
        self.ledger({"job": "brief", "cost_usd": 0.5, "turns": 4}, {"job": "brief", "cost_usd": 0.5, "turns": 7})
        with self.plists(GARRICK_MAX_CALL_USD="2"):
            html = self.page()
        self.assertIn('<td class="r">5.5</td>', self.calls(html))
        self.assertIn("Each Claude call stops at $2.", html)
        self.assertIn("$2 max per call", html)
        with self.plists(GARRICK_MAX_CALL_USD="0"):
            self.assertIn("no per-call budget", self.page())

    def test_a_call_stopped_at_its_budget_needs_attention(self):
        self.ledger({"job": "brief", "cost_usd": 2.0, "subtype": "error_max_budget_usd", "exit": 1})
        with self.plists():
            self.assertIn("A call by brief stopped at its per-call budget", attention(self.page()))

    def test_refused_tools_against_the_deny_list(self):
        self.ledger({"job": "brief", "cost_usd": 0.1, "denied": ["WebFetch", "Write"]},
                    {"job": "digest", "cost_usd": 0.1, "denied": ["mcp__mail__send"]})
        profile = self.jobs.parent / "headless-settings.json"
        agent = status.load_agent(self.root)
        core = list(getattr(agent, "CORE_DENY", ()))
        profile.write_text(json.dumps({"permissions": {"deny": core + ["WebFetch", "mcp__mail", "Bash(curl:*)"]}}))
        with self.plists(), mock.patch.object(agent, "PROFILE", profile):
            html = self.page()
        block = attention(html)
        self.assertIn("brief tried a tool the deny list forbids: WebFetch<", block)     # Write was only not allowed
        self.assertIn("digest tried a tool the deny list forbids: mcp__mail__send", block)
        self.assertIn('title="Not allowed for this job"', self.calls(html))
        if core:                                     # a profile that lost a core entry is no profile
            profile.write_text(json.dumps({"permissions": {"deny": core[1:] + ["WebFetch"]}}))
            with self.plists(), mock.patch.object(agent, "PROFILE", profile):
                self.assertIn("headless-settings.json, is missing, does not read or has lost a core entry", attention(self.page()))
        profile.unlink()
        with self.plists(), mock.patch.object(agent, "PROFILE", profile):
            self.assertIn("headless-settings.json, is missing, does not read or has lost a core entry", attention(self.page()))


class TestManageFromThePage(StatusCase):
    """New project, New thread, Rename and Delete (#36, #37, #38): the page
    gives each dialog what it needs, and the script stands alone."""

    def setUp(self):
        super().setUp()
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        shutil.copy(Path(status.__file__).resolve().parents[2] / "template" / "System" / "tools" / "garrick_lib.py",
                    tools / "garrick_lib.py")

    def test_the_dialogs_data_and_the_cards(self):
        write(self.root / "Zones" / "Work" / "Todo.md",
              "# Work\n\n## Inbox\n\n- [ ] [[Pricing]]: call Dana\n- [x] [[Pricing]]: done one\n")
        html = self.page()
        data = json.loads(re.search(r'id="manage-data">(.*?)</script>', html, re.S).group(1))
        self.assertIn("Acme Review", data["zones"]["Work"]["projects"])
        self.assertIn("acme", [t for t, _ in data["zones"]["Work"]["parties"]])
        self.assertTrue(data["acting"])
        pricing = cards(html)[("Acme Review", "Pricing")]
        self.assertEqual(["Work", "Acme Review", "Pricing"], pricing["mg"][:3])
        self.assertGreaterEqual(pricing["mg"][3], 1)                       # its note, at least
        self.assertEqual(1, pricing["mg"][4])                                # the open line, not the done one
        self.assertIn('data-manage="new-project"', html)
        self.assertIn('data-manage="new-thread"', html)
        self.assertIn("<script>%s</script>" % status.MANAGE_JS, html)

    def test_the_script_parses_and_draws_a_cards_buttons(self):
        if not shutil.which("node"):
            self.skipTest("Node is not installed")
        js = """const vm=require("vm");const code=process.argv[1];const added=[];
const ctx={JSON,String,Date,Math,setTimeout:()=>0,clearTimeout:()=>0,localStorage:{getItem:()=>null,setItem:()=>0,removeItem:()=>0},
document:{readyState:"complete",getElementById:(id)=>id==="manage-data"?{textContent:'{"zones":{"Work":{"projects":["Acme"],"parties":[["acme","Acme Corp"]]}},"acting":true}'}:null,
addEventListener:(k,f)=>added.push(k),body:{appendChild:()=>0}}};
ctx.window={webkit:{messageHandlers:{garrick:{postMessage:()=>0}}}};vm.createContext(ctx);vm.runInContext(code,ctx);
const t=ctx.window.GarrickManage({mg:["Work","Acme","Pricing",3,1]}),p=ctx.window.GarrickManage({mg:["Work","Acme","",5,2,["Pricing"]]});
process.stdout.write(JSON.stringify([t,p,ctx.window.GarrickManage({mg:["Work","Acme","Pricing",3,1],held:1}),added]));"""
        done = subprocess.run(["node", "-e", js, status.MANAGE_JS], capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)
        thread, project, held, added = json.loads(done.stdout)
        self.assertIn("Rename…", thread)
        self.assertIn("Delete…", thread)
        self.assertNotIn("New thread here", thread)
        self.assertIn("New thread here", project)
        self.assertEqual("", held)                                          # parked with its project: nothing to do here
        self.assertIn("click", added)

    def test_undo_wraps_the_hook_park_sets(self):
        page = self.page()
        self.assertLess(page.index("window.GarrickActed=function(q,out){if(!out"),
                        page.index("var prev=window.GarrickActed;window.GarrickActed="))


class TestVaultGraph(StatusCase):
    def obsidian(self, folder, groups=None, ignore=None):
        conf = folder / ".obsidian"
        conf.mkdir(parents=True, exist_ok=True)
        if groups is not None:
            (conf / "graph.json").write_text(json.dumps({"colorGroups": [
                {"query": q, "color": {"a": 1, "rgb": rgb}} for q, rgb in groups]}))
        if ignore is not None:
            (conf / "app.json").write_text(json.dumps({"userIgnoreFilters": ignore}))

    def test_colours_from_the_vaults_own_groups(self):
        work = self.root / "Zones" / "Work"
        self.obsidian(work, groups=[("[type:project] OR file:Notes", 0xFF0000), ("path:Birch Entry", 0x00FF00)])
        write(work / "Acme Review" / "Notes.md", "# Notes\n")
        data = graph_data(self.page())
        by = {n["n"]: n for n in data["nodes"]}
        self.assertEqual([["#ff0000", "Project, Notes"], ["#00ff00", "Birch Entry"]], data["groups"])
        self.assertEqual(0, by["Acme Review"]["g"])
        self.assertEqual(0, by["Notes"]["g"])
        self.assertEqual(1, by["Market Sizing"]["g"])
        self.assertEqual(-1, by["Pricing"]["g"])                                # no group takes it: grey
        self.assertNotIn("g", by["Acme kick-off"])                             # a wiki with no vault of its own keeps the kinds
        self.assertIn("n.g===-1?G.other", status.GRAPH_JS)

    def test_the_legend_names_each_group_as_a_person_would(self):
        cases = [
            (['path:"Notes/wiki/concepts/"'], "Concepts"),
            (["path:domains/system-integrator"], "System integrator"),
            (["file:Notes/Brief.md"], "Brief"),
            (['["type","customer"]', 'path:"Notes/customers"'], "Customer"),
            (["[type:customer]", "path:Notes/customers"], "Customer"),
            (['["status":"waiting"]'], "Waiting"),
            (["[status]"], "Status"),
            (['"loose words"', "line:(budget)"], "Group 4"),
            (['"loose words"', "tag:#pricing"], "Pricing"),
        ]
        for terms, said in cases:
            self.assertEqual(said, status.group_label(terms, 4), terms)

    def test_a_quoted_property_term_matches_by_property(self):
        for term in ('["type":"customer"]', '["type","customer"]', "[type:customer]", '[type:"customer"]'):
            self.assertTrue(status.group_match(term, {"type": "customer"}, "Zones/Work/x"), term)
        self.assertFalse(status.group_match('["type","customer"]', {"type": "supplier"}, "Zones/Work/x"))

    def test_an_unreadable_group_is_numbered_in_the_vaults_order(self):
        work = self.root / "Zones" / "Work"
        self.obsidian(work, groups=[("path:Birch Entry", 0x00FF00), ('"loose words"', 0xFF0000)])
        self.assertEqual([["#00ff00", "Birch Entry"], ["#ff0000", "Group 2"]], graph_data(self.page())["groups"])

    def test_ignore_filters_leave_notes_out(self):
        work = self.root / "Zones" / "Work"
        self.obsidian(work, ignore=["Birch Entry/", "/Sources/"])
        write(work / "Acme Review" / "Sources" / "Brief.md", "# Brief\n")
        names = {n["n"] for n in graph_data(self.page())["nodes"]}
        self.assertNotIn("Market Sizing", names)
        self.assertNotIn("Brief", names)
        self.assertIn("Pricing", names)

    def test_a_root_vault_colours_the_zones_and_never_a_wiki(self):
        self.obsidian(self.root, groups=[("[type:meeting]", 0x123456), ("[type:thread]", 0x654321)])
        data = graph_data(self.page())
        kickoff = next(n for n in data["nodes"] if n["n"] == "Acme kick-off")
        self.assertNotIn("g", kickoff)                                      # a wiki is drawn by its own kinds
        self.assertEqual("meeting", dict(data["kinds"])[kickoff["k"]])
        pricing = next(n for n in data["nodes"] if n["n"] == "Pricing")
        self.assertEqual("#654321", data["groups"][pricing["g"]][0])

    def test_each_wiki_has_its_own_kinds_core_and_label(self):
        k = self.root / "Wikis" / "Knowledge" / "wiki"
        write(k / "concepts" / "lane-capacity.md", "# Lane capacity\n\nFrom [[pallet-report]].\n")
        write(k / "concepts" / "safety-stock.md", "---\ntype: concept\n---\n# Safety stock\n")
        write(k / "entities" / "fictus-cloud.md", "# Fictus Cloud\n")
        write(k / "sources" / "pallet-report.md", "---\ntitle: A very long report title about pallets, lanes, freight and the winter that came\n"
              "type: source\n---\n\nTouches [[lane-capacity]], [[safety-stock]] and [[fictus-cloud]].\n")
        write(k / "sources" / "odd.md", "---\ntype: summary\n---\n# Odd\n")
        m = self.root / "Wikis" / "Meetings" / "wiki"
        write(m / "sources" / "260311-stray.md", "---\ntitle: Stray\ntype: entity\n---\n")
        data = graph_data(self.page())
        kind = dict(data["kinds"])
        by = {n.get("N", n["n"]): n for n in data["nodes"]}
        self.assertEqual("concept", kind[by["lane-capacity"]["k"]])                # by its folder
        self.assertEqual("concept", kind[by["safety-stock"]["k"]])                 # by its type
        self.assertEqual("entity", kind[by["fictus-cloud"]["k"]])
        self.assertEqual("other notes", kind[by["odd"]["k"]])                      # a type the model does not know
        self.assertEqual("other notes", kind[by["Stray"]["k"]])                    # an entity has no place in Meetings
        long = by["A very long report title about pallets, lanes, freight and the winter that came"]
        self.assertEqual("source", kind[long["k"]])
        self.assertTrue(long["n"].endswith("…") and len(long["n"]) <= 41, long["n"])
        self.assertEqual(1, by["lane-capacity"]["c"])
        self.assertEqual(0, long["c"])
        idx = {t: data["nodes"].index(by[t]) for t in ("lane-capacity", "safety-stock", "fictus-cloud")}
        pairs = {(a, b): w for a, b, w in data["ce"]}
        self.assertEqual(1, pairs[tuple(sorted((idx["lane-capacity"], idx["safety-stock"])))])   # one source cites both
        self.assertEqual({"Meetings": "People", "Knowledge": "Concepts and entities"}, data["cl"])
        self.assertEqual("all", data["modes"]["Knowledge"])
        self.assertIn("function modeFor(z){return st.get('garrick-graph-mode-'+z)", status.GRAPH_JS)

    def test_any_note_in_a_project_opens_where_its_card_would(self):
        write(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Call notes.md", "# Call notes\n")
        nodes = {n["n"]: n for n in graph_data(self.page(launchers=("finder", "claude")))["nodes"]}
        notes = nodes["Call notes"]
        self.assertEqual(str(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing"), notes["f"])
        self.assertEqual("Pricing", notes["lw"])                               # what an app resumes there
        self.assertEqual("", notes["w"])                                        # but no Park, and no phrase to copy
        self.assertIn("o.lw?'open '+o.lw", status.PANEL_JS)


FAKE_CMUXLIB = '''
def installed():
    return True


def sessions_by_folder(ws):
    return {str(ws) + "/Zones/Work/Acme Review/Threads/Pricing": "working",
            str(ws) + "/Zones/Work/Birch Entry": "idle"}
'''


class TestSessions(StatusCase):
    def lib(self, text=FAKE_CMUXLIB):
        path = self.jobs.parent / "cmux" / "cmuxlib.py"
        write(path, text)
        return mock.patch.object(status, "CMUXLIB", path)

    def test_absent_draws_nothing(self):
        with mock.patch.object(status, "CMUXLIB", self.jobs.parent / "none" / "cmuxlib.py"):
            html = self.page()
        self.assertNotIn('class="live', html.split("<script>")[0])
        self.assertNotIn('class="desk-acts', html)
        self.assertNotIn('"dk"', htmllib.unescape(html))

    def test_dots_on_rows_cards_and_the_menu(self):
        with self.lib():
            html = self.page()
        self.assertIn('<span class="live working" title="A session is open in it, working">', html)
        self.assertIn('<span class="live working" title="A session is open in the project, working">', html)   # Acme counts its thread's
        pricing = cards(html)[("Acme Review", "Pricing")]
        self.assertEqual(("working", ["Work", "Acme Review", "Pricing"]), (pricing["live"], pricing["dk"]))
        self.assertNotIn("live", cards(html)[("Birch Entry", "Market Sizing")])     # the session is in the project's folder
        menu = json.loads(re.search(r'id="menu-data">(.*?)</script>', html, re.S).group(1))
        work = {p["n"]: p for z in menu["zones"] if z["z"] == "Work" for p in z["p"]}
        self.assertEqual(("working", "working"), (work["Acme Review"]["s"], work["Acme Review"]["t"][0]["s"]))
        self.assertEqual(("idle", None), (work["Birch Entry"]["s"], work["Birch Entry"]["t"][0].get("s")))
        self.assertEqual(["Work", "Acme Review", ""], work["Acme Review"]["dk"])           # what the menu's cmux row asks the desk to open
        self.assertEqual(["Work", "Acme Review", "Pricing"], work["Acme Review"]["t"][0]["dk"])
        self.assertEqual(1, menu["dk"])                                                    # and anything else the app opens in cmux
        swift = (Path(status.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")
        self.assertIn('live: r["s"] as? String', swift)                                   # the app draws the dot
        self.assertIn('launch(k, f, phrase: w.isEmpty ? "" : "open " + w, desk: a["dk"] != nil)', swift)   # and opens through the desk
        state = json.loads(re.search(r'id="state-data">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(3, len(state["live"]))          # Pricing's folder, and the two projects' folders above a session

    def test_every_cmux_open_in_the_app_goes_through_the_desk_when_it_is_ready(self):
        # One rule, in launch(): rows, Process the Inbox, the fields' words and
        # Ask's opens all pass through it, and none reaches cmux another way.
        swift = (Path(status.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")
        launch = swift[swift.index("func launch(_ app: String"):swift.index("func deskReady()")]
        rule = launch.index('if app == "cmux" && (desk || deskReady()) {')
        self.assertLess(rule, launch.index("switch app {"))
        self.assertIn('act(["verb": "open", "folder": folder.path, "prompt": phrase])', launch[rule:])
        self.assertIn('(menuState?["data"] as? [String: Any])?["dk"] as? Int == 1', swift)       # the page's word for it
        self.assertEqual(3, swift.count("openInCmux("))          # itself, launch()'s plain cmux, and a page from before 0.5
        self.assertEqual(1, swift.count("withApplicationAt: cmux"))
        for route in ('launch(k, f, phrase: r["w"] ?? "")',                                   # Process the Inbox, the menu's
                      'self.launch(k, f, phrase: act["w"] ?? "")',                            # and the panel's
                      'launch(app, workspace.path, phrase: text)',                            # the menu's field, ask off
                      'self.launch(app, workspace.path, phrase: text)',                       # the panel's field, ask off
                      'self.launch(app, folder, phrase: item["phrase"] as? String ?? "", desk: item["dk"] != nil)',   # Ask
                      'launch(app, folder, phrase: body["phrase"] as? String ?? "", desk: body["dk"] != nil)'):         # the page
            self.assertIn(route, swift)
        self.assertNotIn('["verb": "open", "zone"', swift)        # rows open by folder too, through the same rule

    def test_the_desks_buttons(self):
        with self.lib():
            html = self.page()
        self.assertIn('data-act="{&quot;verb&quot;: &quot;startup&quot;}"', html)
        self.assertIn('data-act="{&quot;verb&quot;: &quot;shutdown&quot;}" data-expect="none:" data-confirm="Click again to shut down"', html)
        self.assertIn('<span class="desk-acts apponly">', html)                # the app only
        self.assertIn('data-expect="none:" data-confirm', html)                 # the page waits for every session to close
        with self.lib(FAKE_CMUXLIB.replace("return True", "return False")):
            self.assertNotIn('class="desk-acts', self.page())                  # no cmux on this Mac
        for js in ("var q={verb:v,zone:o.dk[0],project:o.dk[1]};if(o.dk[2])q.thread=o.dk[2]",
                   "if(k==='cmux'&&o.dk)", "desk(o,'close')"):
            self.assertIn(js, status.PANEL_JS)
        self.assertIn("if(x.dataset.confirm&&!x.classList.contains('armed'))", status.JS)

    def test_a_library_that_fails_shows_nothing_open(self):
        with self.lib("def sessions_by_folder(ws):\n    raise RuntimeError('no socket')\n"):           # no installed(): taken at its word
            self.assertEqual({}, status.sessions(self.root))
            html = self.page()
        self.assertIn('class="desk-acts', html)
        self.assertNotIn('<span class="live', html.split("<script>")[0])


class TestReloadAndSettle(StatusCase):
    def test_the_page_waits_for_what_a_button_asked(self):
        write(self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread_note("Birch Entry", "Market Sizing", "birch", status="parked"))
        state = json.loads(re.search(r'id="state-data">(.*?)</script>', self.page(), re.S).group(1))
        self.assertEqual(["Work/Birch Entry/Threads/Market Sizing/Market Sizing.md"], state["parked"])
        self.assertIn("host.postMessage({rebuild:true});else location.reload()", status.RELOAD_JS)
        self.assertIn("data-expect=\"'+esc((s?'active:':'parked:')+k)", status.PANEL_JS)
        self.assertIn("GarrickExpect(x.dataset.expect)", status.JS)

    def test_settle_lets_only_the_last_request_build(self):
        marker = self.jobs / "status.html.settle"
        self.assertTrue(status.settle(marker, 5, sleep=lambda s: None))
        self.assertFalse(status.settle(marker, 5, sleep=lambda s: marker.write_text("a later request")))

    def test_main_with_settle(self):
        out = self.jobs / "page.html"
        with mock.patch.object(status, "settle", return_value=False) as s:
            status.main(["--workspace", str(self.root), "--out", str(out), "--settle", "3", "--no-obsidian", "--no-graph"])
        s.assert_called_once()
        self.assertFalse(out.exists())


class TestEffortFolders(StatusCase):
    def test_also_and_moved_reach_effort(self):
        flags(self.root, effort=True)
        ef = status.effort()
        with mock.patch.object(ef, "ledger", return_value={}) as led:
            html = status.build(self.root, now=self.now, folder=self.jobs, also=("~/Old Garrick",),
                                moved={"Zones/Work/Acme Old": "Zones/Work/Acme Review"},
                                flags=("--also", "~/Old Garrick", "--moved", "Zones/Work/Acme Old=Zones/Work/Acme Review"))
        kw = led.call_args.kwargs
        self.assertEqual([Path("~/Old Garrick").expanduser()], kw["also"])
        self.assertEqual({"Zones/Work/Acme Old": "Zones/Work/Acme Review"}, kw["moved"])
        self.assertIn("--moved &#x27;Zones/Work/Acme Old=Zones/Work/Acme Review&#x27;", html)    # the rebuild command keeps them

    def test_main_reads_the_flags(self):
        out = self.jobs / "page.html"
        with mock.patch.object(status, "build", return_value="<html></html>") as b, contextlib.redirect_stdout(io.StringIO()):
            status.main(["--workspace", str(self.root), "--out", str(out), "--no-obsidian", "--also", "/old",
                         "--moved", "A=B", "--moved", "nonsense"])
        kw = b.call_args.kwargs
        self.assertEqual((("/old",), {"A": "B"}), (kw["also"], kw["moved"]))
        self.assertIn("--moved", kw["flags"])


class TestSharedLauncherSettings(StatusCase):
    def test_embedded_when_saved(self):
        self.assertNotIn('id="launch-settings"', self.page())
        write(self.root / "System" / "generated" / "status-settings.json",
              json.dumps({"launchers": ["note", "claude", "nonsense"], "default": "claude"}))
        found = re.search(r'id="launch-settings">(.*?)</script>', self.page(), re.S)
        self.assertEqual({"launchers": ["note", "claude"], "default": "claude"}, json.loads(found.group(1)))
        write(self.root / "System" / "generated" / "status-settings.json",
              json.dumps({"launchers": {"note": True, "finder": False, "cmux": False, "codex": False}, "default": "cmux"}))
        found = re.search(r'id="launch-settings">(.*?)</script>', self.page(), re.S)
        self.assertEqual({"launchers": ["note", "claude"], "default": "cmux"}, json.loads(found.group(1)))   # a name left out is on
        write(self.root / "System" / "generated" / "status-settings.json", json.dumps({"launchers": "all"}))
        self.assertNotIn('id="launch-settings"', self.page())

    def test_the_app_prefers_them_and_saves_through_the_bridge(self):
        self.assertIn("if(host&&el){try{shared=JSON.parse(el.textContent)}", status.PANEL_JS)    # a browser keeps its own
        self.assertIn("return{verb:'settings',launchers:", status.PANEL_JS)
        self.assertIn("if(lpChanged||zChanged){var q=lpChanged?GarrickPrefs.request():{verb:'settings'};"
                      "if(zChanged)q.zones=zreq();", status.JS)


class TestZoneOrder(StatusCase):
    """The Threads card leads with the zone the graph shows (#72)."""

    def test_each_zone_names_itself_and_the_graph_reorders_them(self):
        html = self.page()
        self.assertIn('<details class="zone tsort" id="zone-work" data-zone="Work" open>', html)
        self.assertIn('<details class="zone tsort" id="zone-personal" data-zone="Personal" open>', html)
        self.assertLess(html.index('data-zone="Personal"'), html.index('data-zone="Work"'))    # by name, as built
        self.assertIn("function leadZone(z){", status.GRAPH_JS)
        self.assertIn("leadZone(zsel);", status.GRAPH_JS.split("function leadZone")[1])          # on load
        self.assertIn("st.set('garrick-graph-place',zsel);leadZone(zsel);", status.GRAPH_JS)    # on each change
class TestSettingsRowLines(StatusCase):
    """Settings (#73): a row's own grey line waits behind its section's "?", and is its tooltip meanwhile."""

    def test_row_lines_hidden_until_explained(self):
        html = self.page()
        self.assertIn("#settings .setsec:not(.explained) :is(.launcher-choice,.setlink,.flagrow) small{display:none}", html)
        self.assertIn("sec.classList.toggle('explained',!p.hidden)", html)
        self.assertIn("r.title=m.textContent.trim()+(r.dataset.tip0?' '+r.dataset.tip0:'')", html)
        self.assertIn("<small>", html[html.index('id="settings"'):])                     # the lines are all still there


class TestZoneColours(StatusCase):
    """Settings › Zones (#67): a colour and an icon per zone, on every label that names it."""

    def save(self, zones):
        write(self.root / "System" / "generated" / "status-settings.json", json.dumps({"zones": zones}))

    def test_read_with_unknown_names_dropped(self):
        self.assertEqual({}, status.zone_styles(self.root))
        self.save({"Work": {"color": "teal", "icon": "briefcase"}, "Personal": {"color": "Mauve", "icon": "house"},
                   "Other": {"color": "Plum", "icon": "unicorn"}, "Odd": "Teal"})
        self.assertEqual({"Work": {"color": "Teal", "icon": "briefcase"}, "Personal": {"icon": "house"}},
                         status.zone_styles(self.root))
        write(self.root / "System" / "generated" / "status-settings.json", "not json")
        self.assertEqual({}, status.zone_styles(self.root))

    def test_every_label_that_names_a_zone(self):
        self.save({"Work": {"color": "Teal", "icon": "briefcase"}})
        write(self.root / "Zones" / "Work" / "Todo.md", "# Work\n\n## Inbox\n\n- [ ] Book the room\n")
        html = self.page()
        icon = status.zone_icon("briefcase")
        self.assertIn('<h3 class="zc zc-teal">%sWork</h3>' % icon, html)                   # the Threads card
        self.assertIn('data-tz="Work" class="zc zc-teal">%sWork<span class="n">' % icon, html)   # the Todo tab
        self.assertIn('<option value="Work" class="zc zc-teal">Work</option>', html)       # the graph's place
        self.assertIn('<span class="gzi zc zc-teal" data-z="Work" hidden>%s</span>' % icon, html)
        self.assertIn('<b><a class="zc zc-teal" href=', html)                              # Open actions
        self.assertIn('<div class="name zc zc-teal">%sWork<small>' % icon, html)          # Inboxes
        self.assertIn("<h3>Personal</h3>", html)                                           # a zone with neither, as before

    def test_a_light_and_a_dark_ink_for_every_colour(self):
        css = status.zone_css()
        for name, (light, dark) in status.ZONE_COLOURS.items():
            k = name.lower()
            self.assertIn(":root .zc.zc-%s{color:var(--zc-%s)}" % (k, k), css)
            self.assertEqual(1, css.count("--zc-%s:%s" % (k, light)), name)
            self.assertEqual(2, css.count("--zc-%s:%s" % (k, dark)), name)        # the system's dark, and the page's own
        self.assertIn('@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"]))', css)
        self.assertIn(':root[data-theme="dark"]', css)
        self.assertIn(status.zone_css(), self.page())

    def test_each_ink_reads_against_its_ground(self):
        def lum(h):
            c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
            return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
        def ratio(a, b):
            hi, lo = sorted((lum(a), lum(b)), reverse=True)
            return (hi + .05) / (lo + .05)
        for name, (light, dark) in status.ZONE_COLOURS.items():
            for ground in ("#f4f3f0", "#fcfcfb"):                     # the page and a card, light
                self.assertGreaterEqual(ratio(light, ground), 4.5, name)
            for ground in ("#0d0d0d", "#1a1a19", "#211f1e"):          # the page, a card and a raised row, dark
                self.assertGreaterEqual(ratio(dark, ground), 4.5, name)

    def test_the_icons_are_drawn_in_the_text_colour(self):
        self.assertEqual(12, len(status.ZONE_ICONS))
        for name in status.ZONE_ICONS:
            svg = status.zone_icon(name)
            self.assertTrue(svg.startswith('<svg class="zi" viewBox="0 0 16 16" aria-hidden="true"'), name)
            self.assertIn('stroke="currentColor"', svg)
            self.assertNotRegex(svg, r"#[0-9A-Fa-f]{3,6}")
        self.assertEqual("", status.zone_icon("unicorn"))

    def test_the_settings_section(self):
        self.save({"Work": {"color": "Teal", "icon": "briefcase"}})
        html = self.page()
        start = html.index('id="zone-settings"')
        section = html[start:html.index("</section>", start)]
        self.assertIn('<section class="setsec apponly" id="zone-settings">', html)           # the app saves it; a browser cannot
        self.assertEqual(2, section.count('class="zrow"'))
        self.assertIn('<div class="zrow" data-zone="Work"><span class="zprev zc zc-teal">', section)
        self.assertIn('<option value="Teal" selected>Teal</option>', section)
        self.assertIn('<option value="briefcase" selected>Briefcase</option>', section)
        work = section[section.index('data-zone="Work"'):]
        colours = re.search(r'<select class="zcol"[^>]*>(.*?)</select>', work).group(1)
        self.assertEqual(["No colour"] + list(status.ZONE_COLOURS), re.findall(r">([^<]+)</option>", colours))
        # what the eye picks from: the button shows the choice, the palettes show every colour and icon
        self.assertIn('aria-label="Colour for Work"><i class="zsw" style="background:var(--zc-teal)"></i><span>Teal</span></button>', work)
        palette = re.search(r'<span class="zpop zp-col" hidden[^>]*>(.*?)</span></span>', work).group(1)
        self.assertEqual([""] + list(status.ZONE_COLOURS), re.findall(r'data-v="([^"]*)"', palette))
        self.assertEqual(len(status.ZONE_COLOURS), palette.count('class="zsw" style="background:var(--zc-'))
        icons_pop = re.search(r'<span class="zpop zp-ico" hidden[^>]*>(.*?)</span></span>', work).group(1)
        self.assertEqual([""] + list(status.ZONE_ICONS), re.findall(r'data-v="([^"]*)"', icons_pop))
        self.assertEqual(len(status.ZONE_ICONS), icons_pop.count('<svg class="zi"'))
        icons = json.loads(re.search(r'id="zone-icons">(.*?)</script>', section).group(1))
        self.assertEqual(set(status.ZONE_ICONS), set(icons))
        self.assertIn("function zreq(){", status.JS)


if __name__ == "__main__":
    unittest.main()


def project_cards(html):
    """Every project row's card in the threads list, by project name."""
    return {json.loads(htmllib.unescape(raw))["n"]: json.loads(htmllib.unescape(raw))
            for raw in re.findall(r'class="thread proj"[^>]*data-card="([^"]*)"', html)}


PANEL_HARNESS = r"""
const vm = require("vm");
const [js, hosted, calls] = JSON.parse(process.argv[1]);
const ctx = { JSON, String, Array, localStorage: { getItem: () => null, setItem: () => {} },
              document: { getElementById: () => null, addEventListener: () => {}, body: { dataset: { launchers: "" } } } };
ctx.window = hosted ? { webkit: { messageHandlers: { garrick: { postMessage: () => {} } } } } : {};
vm.createContext(ctx);
vm.runInContext(js + ";this.out=" + JSON.stringify(calls) + ".map(function(c){return Panel[c[0]](c[1],c[2])})", ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""


def panel(hosted, *calls):
    """Panel.head or Panel.acts, run in Node as the app (hosted) or a browser would.
    A call is (name, card) or, for a row's card, ("head", card, 1)."""
    import subprocess
    done = subprocess.run(["node", "-e", PANEL_HARNESS, json.dumps([status.PANEL_JS, hosted, [list(c) for c in calls]])],
                          capture_output=True, text=True, timeout=30)
    if done.returncode:
        raise AssertionError(done.stderr)
    return [htmllib.unescape(out) for out in json.loads(done.stdout)]


class TestParkAProject(StatusCase):
    """A project parked as a whole: its hub says parked, and every thread in it
    is parked with it, on the page, in the graph and out of the menu."""

    def setUp(self):
        super().setUp()
        hub = self.root / "Zones" / "Work" / "Acme Review" / "Acme Review.md"
        hub.write_text(hub.read_text().replace("status: active", "status: parked"))

    def test_its_threads_are_parked_with_it(self):
        html = self.page()
        pricing = cards(html)[("Acme Review", "Pricing")]
        self.assertEqual((1, 1), (pricing["s"], pricing["held"]))
        self.assertNotIn("pa", pricing)                                  # woken with the project, not on its own
        acme = project_cards(html)["Acme Review"]
        self.assertEqual((1, 1, ["Work", "Acme Review"]), (acme["s"], acme["hp"], acme["pp"]))
        birch = project_cards(html)["Birch Entry"]
        self.assertEqual((0, 0, ["Work", "Birch Entry"]), (birch["s"], birch["hp"], birch["pp"]))
        parked = html[html.index('id="parked-work"'):]
        self.assertIn("Acme Review", parked[:parked.index("</details>")])
        state = json.loads(re.search(r'id="state-data">(.*?)</script>', html, re.S).group(1))
        self.assertIn("Work/Acme Review/Acme Review.md", state["parked"])        # what Park waits for
        self.assertIn("Work/Acme Review/Threads/Pricing/Pricing.md", state["parked"])
        menu = json.loads(re.search(r'id="menu-data">(.*?)</script>', html, re.S).group(1))
        self.assertNotIn("Acme Review", [p["n"] for z in menu["zones"] for p in z["p"]])
        nodes = {n["n"]: n for n in graph_data(html)["nodes"]}
        self.assertEqual((1, ["Work", "Acme Review"]), (nodes["Acme Review"]["hp"], nodes["Acme Review"]["pp"]))
        self.assertEqual(1, nodes["Pricing"]["held"])
        self.assertNotIn("pa", nodes["Pricing"])
        self.assertEqual(0, nodes["Birch Entry"]["hp"])

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_cards_buttons(self):
        html = self.page()
        acme, birch = project_cards(html)["Acme Review"], project_cards(html)["Birch Entry"]
        pricing = cards(html)[("Acme Review", "Pricing")]
        wake, park, held = panel(True, ("head", acme), ("head", birch), ("head", pricing))
        self.assertIn('data-act="{"verb":"wake","zone":"Work","project":"Acme Review"}"', wake)
        self.assertIn('data-expect="active:Work/Acme Review/Acme Review.md"', wake)
        self.assertIn('title="Wake the project and every thread in it">Wake</button>', wake)
        self.assertIn('data-act="{"verb":"park","zone":"Work","project":"Birch Entry"}"', park)
        self.assertIn('data-expect="parked:Work/Birch Entry/Birch Entry.md"', park)
        self.assertNotIn("pflip", held)                                    # parked with its project: no button of its own
        self.assertIn("Parked with its project", held)
        browser = panel(False, ("head", dict(birch, pp=None)))[0]
        self.assertIn('data-copy="park Birch Entry"', browser)               # elsewhere it copies the phrase


class TestTheThreadsList(StatusCase):
    def test_a_project_without_a_chevron_keeps_its_room(self):
        # The chevron is 16px; a project row without one, a project that is its own thread, indents by as much.
        self.assertIn(".pchev{box-sizing:border-box;width:16px;", status.CSS)
        self.assertIn(".tunit>.thread:not(.proj)>.t{padding-left:16px}", status.CSS)
        shutil.rmtree(self.root / "Zones" / "Work" / "Birch Entry" / "Threads")
        html = self.page()
        work = html[html.index('id="zone-work"'):]
        self.assertRegex(work, r'<div class="tunit" data-a="\d+"><div class="thread" [^>]*><div class="t"><a [^>]*>Birch Entry</a>')
        self.assertIn('<div class="thread proj"', work)

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_no_card_has_a_button_for_its_projects_note(self):
        # A thread's card opens the thread; the project's note is the project row's.
        html = self.page()
        card = cards(html)[("Acme Review", "Pricing")]
        self.assertNotIn("pu", card)
        acts = panel(True, ("acts", card))[0]
        self.assertNotIn("Acme%20Review/Acme%20Review.md", acts)
        self.assertEqual(1, acts.count('<a class="act"'))                       # Open, and no second link
        old = dict(card, pu=card["u"].rsplit("/Threads/", 1)[0] + "/Acme%20Review.md")
        self.assertNotEqual(old["pu"], card["u"])
        self.assertNotIn("Acme%20Review.md", panel(True, ("acts", old))[0])      # a page built by 0.15.4 still says it
        for js in (status.PANEL_JS, status.GRAPH_JS):
            self.assertNotIn("pnote", js)
            self.assertNotIn("o.pu", js)
        self.assertNotIn("hubOf", status.GRAPH_JS)
        self.assertNotIn("pnote", status.CSS)

    def test_the_panels_dot_follows_the_name(self):
        swift = (Path(status.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")
        line = swift[swift.index("struct PanelLine: View {"):swift.index("struct PanelView: View {")]
        self.assertLess(line.index("Text(row.name)"), line.index("if let live = row.live {"))
        self.assertLess(line.index("if let live = row.live {"), line.index("Spacer(minLength: 8)"))
        menu = swift[swift.index("final class RowView: NSView {"):swift.index("final class MenuField")]
        self.assertIn("draw(at: NSPoint(x: 21 + indent", menu)               # the menu's names start at 21, dot or not


    def test_party_tags_are_the_cards_not_the_rows(self):
        # Under a name a party tag reads as part of it; the card says them.
        shutil.rmtree(self.root / "Zones" / "Work" / "Birch Entry" / "Threads")     # Birch Entry: a project that is its own thread
        html = self.page()
        work = html[html.index('id="zone-work"'):]
        work = work[:work.index("</details>")]
        for party in ("acme", "birch"):
            self.assertNotIn('<span class="chip">%s</span>' % party, work)
        self.assertEqual(["birch"], cards(html)[("Birch Entry", "Birch Entry")]["t"])
        self.assertEqual(["acme"], cards(html)[("Acme Review", "Pricing")]["t"])

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_a_rows_card_names_no_kind_zone_or_project(self):
        card = cards(self.page())[("Acme Review", "Pricing")]
        row, graph = panel(True, ("head", card, 1), ("head", card))
        self.assertNotIn("thread · Work · Acme Review", row)                    # the section says the zone, the row above the project
        self.assertNotIn('<div class="muted">', row)
        self.assertIn('<span class="chip" style="margin:0 4px 0 0">acme</span>', row)
        self.assertIn("thread · Work · Acme Review", graph)                     # the graph's panel floats free of any list
        self.assertIn("tc.innerHTML=Panel.head(o,1)+Panel.acts(o)", status.JS)

    def test_the_live_dot_keeps_its_distance(self):
        self.assertIn(".thread .t a+.live{margin-left:.4em}", status.CSS)
        self.assertNotIn("a+.live{margin-left:0}", status.CSS)
        swift = (Path(status.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")
        line = swift[swift.index("struct PanelLine: View {"):swift.index("struct PanelView: View {")]
        self.assertIn("HStack(spacing: 6) {", line)                              # the panel's dot, six points after the name
        menu = swift[swift.index("final class RowView: NSView {"):swift.index("final class MenuField")]
        self.assertIn("NSRect(x: 10 + indent, y: bounds.midY - 3, width: 6, height: 6)", menu)   # the menu's, before it, the name at 21


# PARK_JS against a page status.py wrote, in a DOM just big enough for it:
# the requests, each with page_action.py's reply, then what the list shows.
DOM_HARNESS = r"""
const vm = require("vm");
const [html, js, steps, redo, expect] = JSON.parse(process.argv[1]);
// Just enough of a DOM for PARK_JS on a page status.py wrote: elements, text,
// attributes, the selectors it uses, and an HTML reader for well-formed markup.
const VOID = new Set(["meta", "link", "input", "br", "img", "hr", "path", "circle", "rect", "line"]);
const RAW = new Set(["script", "style", "title", "textarea"]);
const ENT = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
const unent = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|\w+);/gi, (m, e) => e[0] === "#"
  ? String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)) : (e in ENT ? ENT[e] : m));
const escText = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
class Text {
  constructor(t) { this.nodeType = 3; this.data = t; this.parentNode = null; }
  get textContent() { return this.data; }
  get outerHTML() { return escText(this.data); }
  cloneNode() { return new Text(this.data); }
}
const dashed = (k) => "data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
class El {
  constructor(tag) { this.nodeType = 1; this.localName = tag.toLowerCase(); this.attrs = {}; this.childNodes = []; this.parentNode = null; }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  hasAttribute(k) { return k in this.attrs; }
  get id() { return this.attrs.id || ""; }
  set id(v) { this.attrs.id = v; }
  get className() { return this.attrs["class"] || ""; }
  set className(v) { this.attrs["class"] = v; }
  get classList() {
    const el = this, list = () => el.className.split(/\s+/).filter(Boolean);
    return { contains: (c) => list().includes(c),
             add: (...cs) => { el.className = list().concat(cs.filter((c) => !list().includes(c))).join(" "); },
             remove: (...cs) => { el.className = list().filter((c) => !cs.includes(c)).join(" "); } };
  }
  get dataset() {
    const el = this;
    return new Proxy({}, { get: (t, k) => { const v = el.getAttribute(dashed(k)); return v === null ? undefined : v; },
                           set: (t, k, v) => { el.setAttribute(dashed(k), v); return true; } });
  }
  get hidden() { return this.hasAttribute("hidden"); }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(""); }
  set textContent(v) { this.childNodes.forEach((n) => { n.parentNode = null; }); this.childNodes = []; if (v !== "") this.appendChild(new Text(String(v))); }
  get innerHTML() { return this.childNodes.map((n) => n.outerHTML).join(""); }
  set innerHTML(h) { this.childNodes.forEach((n) => { n.parentNode = null; }); this.childNodes = []; parse(h, this); }
  get outerHTML() {
    const a = Object.entries(this.attrs).map(([k, v]) => " " + k + (v === "" ? "" : '="' + escText(v).replace(/"/g, "&quot;") + '"')).join("");
    return "<" + this.localName + a + ">" + (VOID.has(this.localName) ? "" : this.innerHTML + "</" + this.localName + ">");
  }
  appendChild(n) { return this.insertBefore(n, null); }
  insertBefore(n, ref) {
    if (n.parentNode) n.parentNode.removeChild(n);
    const i = ref ? this.childNodes.indexOf(ref) : -1;
    if (ref && i < 0) throw new Error("insertBefore: not a child");
    if (i < 0) this.childNodes.push(n); else this.childNodes.splice(i, 0, n);
    n.parentNode = this;
    return n;
  }
  removeChild(n) { const i = this.childNodes.indexOf(n); if (i >= 0) this.childNodes.splice(i, 1); n.parentNode = null; return n; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  cloneNode(deep) { const c = new El(this.localName); c.attrs = Object.assign({}, this.attrs); if (deep) this.childNodes.forEach((n) => c.appendChild(n.cloneNode(true))); return c; }
  addEventListener() {}
  matches(sel) { return sel.split(",").some((s) => match(this, parseSel(s.trim()), null)); }
  closest(sel) { for (let e = this; e && e.nodeType === 1; e = e.parentNode) if (e.matches(sel)) return e; return null; }
  querySelectorAll(sel) {
    const parts = sel.split(",").map((s) => parseSel(s.trim())), out = [], root = this;
    (function walk(e) { e.children.forEach((c) => { if (parts.some((p) => match(c, p, root))) out.push(c); walk(c); }); })(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
function parseCompound(t) {
  const c = { tag: null, id: null, cls: [], attrs: [], not: [], scope: false };
  let rest = t, m;
  if ((m = /^[a-z][\w-]*/i.exec(rest))) { c.tag = m[0].toLowerCase(); rest = rest.slice(m[0].length); }
  while (rest) {
    if ((m = /^#([\w-]+)/.exec(rest))) c.id = m[1];
    else if ((m = /^\.([\w-]+)/.exec(rest))) c.cls.push(m[1]);
    else if ((m = /^\[([\w-]+)(?:([$^]?=)"([^"]*)")?\]/.exec(rest))) c.attrs.push([m[1], m[2], m[3]]);
    else if ((m = /^:not\(([^)]*)\)/.exec(rest))) c.not.push(parseCompound(m[1]));
    else if ((m = /^:scope/.exec(rest))) c.scope = true;
    else throw new Error("selector: " + t);
    rest = rest.slice(m[0].length);
  }
  return c;
}
function parseSel(s) {
  const steps = [];
  let i = 0, comb = null;
  while (i < s.length) {
    if (s[i] === " ") { comb = comb || " "; i++; continue; }
    if (s[i] === ">") { comb = ">"; i++; continue; }
    let j = i, depth = 0;
    while (j < s.length && (depth || (s[j] !== " " && s[j] !== ">"))) { if ("([".includes(s[j])) depth++; if (")]".includes(s[j])) depth--; j++; }
    steps.push({ comb: steps.length ? comb || " " : null, c: parseCompound(s.slice(i, j)) });
    comb = null;
    i = j;
  }
  return steps;
}
function one(e, c, root) {
  if (c.scope && e !== root) return false;
  if (c.tag && e.localName !== c.tag) return false;
  if (c.id && e.id !== c.id) return false;
  if (!c.cls.every((x) => e.classList.contains(x))) return false;
  for (const [k, op, v] of c.attrs) {
    const a = e.getAttribute(k);
    if (a === null || (op === "=" && a !== v) || (op === "$=" && !a.endsWith(v)) || (op === "^=" && !a.startsWith(v))) return false;
  }
  return !c.not.some((n) => one(e, n, root));
}
function match(e, steps, root) {
  function at(el, i) {
    if (!one(el, steps[i].c, root)) return false;
    if (i === 0) return true;
    if (steps[i].comb === ">") return !!el.parentNode && el.parentNode.nodeType === 1 && at(el.parentNode, i - 1);
    for (let p = el.parentNode; p && p.nodeType === 1; p = p.parentNode) if (at(p, i - 1)) return true;
    return false;
  }
  return at(e, steps.length - 1);
}
function parse(h, parent) {
  const stack = [parent], TAG = /<([a-zA-Z][\w-]*)((?:\s+[^\s=>\/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?)>/y;
  let i = 0;
  while (i < h.length) {
    const cur = stack[stack.length - 1];
    if (h.startsWith("<!--", i)) { const j = h.indexOf("-->", i); i = j < 0 ? h.length : j + 3; continue; }
    if (h.startsWith("<!", i)) { i = h.indexOf(">", i) + 1; continue; }
    if (h.startsWith("</", i)) {
      const j = h.indexOf(">", i), tag = h.slice(i + 2, j).trim().toLowerCase();
      for (let k = stack.length - 1; k > 0; k--) if (stack[k].localName === tag) { stack.length = k; break; }
      i = j + 1;
      continue;
    }
    TAG.lastIndex = i;
    const m = h[i] === "<" ? TAG.exec(h) : null;
    if (m) {
      const el = new El(m[1]), ar = /([^\s=>\/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
      let a;
      while ((a = ar.exec(m[2]))) el.attrs[a[1].toLowerCase()] = unent(a[2] ?? a[3] ?? a[4] ?? "");
      cur.appendChild(el);
      i = TAG.lastIndex;
      if (RAW.has(el.localName)) {
        const end = h.toLowerCase().indexOf("</" + el.localName, i), j = end < 0 ? h.length : end;
        if (j > i) el.appendChild(new Text(h.slice(i, j)));
        i = end < 0 ? h.length : h.indexOf(">", j) + 1;
      } else if (!m[3] && !VOID.has(el.localName)) stack.push(el);
      continue;
    }
    const j = h.indexOf("<", i + 1), end = j < 0 ? h.length : j;
    cur.appendChild(new Text(unent(h.slice(i, end))));
    i = end;
  }
}
const doc = new El("#document");
parse(html, doc);
const store = {};
if (expect) store["garrick-expect"] = JSON.stringify(expect);
const calls = { bind: 0, chev: 0, close: 0 };
const ctx = { JSON, String, Array, Object,
  localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
  document: { querySelectorAll: (s) => doc.querySelectorAll(s), querySelector: (s) => doc.querySelector(s), createElement: (t) => new El(t),
              getElementById: (id) => doc.querySelectorAll("#" + id)[0] || null, addEventListener: () => {} } };
ctx.window = { ThreadRows: { bind: () => { calls.bind++; }, chev: () => { calls.chev++; }, close: () => { calls.close++; } }, GarrickRedo: redo || undefined };
vm.createContext(ctx);
vm.runInContext(js, ctx);
const done = steps.map(([q, out]) => { ctx.window.GarrickActed(q, out); return null; });
function row(r) {
  const c = JSON.parse(r.dataset.card);
  const o = { n: c.n, s: c.s };
  ["held", "pend", "hp"].forEach((k) => { if (c[k] != null) o[k] = c[k]; });
  if (r.classList.contains("pending")) o.pending = 1;
  return o;
}
function unit(u) {
  const h = u.querySelector(":scope>.thread.proj");
  if (!h) return row(u.querySelector(":scope>.thread"));
  return Object.assign(row(h), { subn: h.querySelector(".subn").textContent, sub: u.querySelector(":scope>.subthreads").id,
                                 chev: h.querySelector(".pchev").getAttribute("data-sub"), threads: u.querySelectorAll(":scope>.subthreads>.thread").map(row) });
}
const zones = {};
doc.querySelectorAll(".tview details.zone").forEach((z) => {
  const f = z.children.filter((c) => c.matches("details.parked"))[0];
  zones[z.id] = { meta: z.querySelector(":scope>summary .meta").textContent, none: !!z.querySelector(":scope>p.muted"),
                  live: z.children.filter((c) => c.classList.contains("tunit")).map(unit),
                  parked: f ? { id: f.id, n: f.querySelector(":scope>summary .n").textContent, units: f.children.filter((c) => c.classList.contains("tunit")).map(unit) } : null };
});
const tile = doc.querySelector('a.tile[href="#threads"] .val');
process.stdout.write(JSON.stringify({ zones, gsum: doc.querySelector(".tview .gsum").textContent, tile: tile && tile.textContent, calls,
                                      expect: store["garrick-expect"] ? JSON.parse(store["garrick-expect"]) : null }));
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestParkLandsAtOnce(StatusCase):
    """Park and Wake move the row as soon as the host says the request was
    done, and the rebuild confirms it."""

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.root / "Zones" / "Work" / "Birch Entry" / "Threads")    # its own thread
        write(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Renewal" / "Renewal.md",
              thread_note("Acme Review", "Renewal", "acme"))

    def run_js(self, *steps, redo=None, expect=None, html=None):
        import subprocess
        html = html or self.page(show_graph=False)
        done = subprocess.run(["node", "-e", DOM_HARNESS, json.dumps([html, status.PARK_JS, [list(s) for s in steps], redo, expect])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    BIRCH = {"verb": "park", "zone": "Work", "file": "Birch Entry/Birch Entry.md"}
    PRICING = {"verb": "park", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md"}
    ACME = {"verb": "park", "zone": "Work", "project": "Acme Review"}
    OK = {"ok": True, "say": "done"}

    def test_a_project_that_is_its_own_thread(self):
        out = self.run_js((self.BIRCH, self.OK))
        work = out["zones"]["zone-work"]
        self.assertEqual(["Acme Review"], [u["n"] for u in work["live"]])
        self.assertEqual(("parked-work", "1"), (work["parked"]["id"], work["parked"]["n"]))
        self.assertEqual({"n": "Birch Entry", "s": 1, "pending": 1}, work["parked"]["units"][0])   # greyed until the rebuild
        self.assertTrue(work["meta"].startswith("2 live"))
        self.assertTrue(out["gsum"].startswith("2 live · 1 parked"))
        self.assertEqual("2", out["tile"])
        back = self.run_js((self.BIRCH, self.OK), (dict(self.BIRCH, verb="wake"), self.OK))["zones"]["zone-work"]
        self.assertEqual(["Acme Review", "Birch Entry"], [u["n"] for u in back["live"]])        # by name, as the build lists them
        self.assertIsNone(back["parked"])                                                     # an empty fold goes
        self.assertTrue(back["meta"].startswith("3 live"))

    def test_a_thread_in_a_project_of_several(self):
        out = self.run_js((self.PRICING, self.OK))
        work = out["zones"]["zone-work"]
        acme = work["live"][0]
        self.assertEqual(("1 thread", ["Renewal"]), (acme["subn"], [t["n"] for t in acme["threads"]]))
        held = work["parked"]["units"][0]
        self.assertEqual(("Acme Review", 0, "1 thread"), (held["n"], held["hp"], held["subn"]))   # the project itself stays awake
        self.assertEqual(("sub-work-acme-review-parked", "sub-work-acme-review-parked"), (held["sub"], held["chev"]))
        self.assertEqual([{"n": "Pricing", "s": 1, "pending": 1}], held["threads"])
        self.assertEqual({"bind": 1, "chev": 1, "close": 1}, out["calls"])                 # the project's copied row answers as the others

    def test_a_whole_project_and_back(self):
        out = self.run_js((self.PRICING, self.OK), (self.ACME, self.OK))
        work = out["zones"]["zone-work"]
        self.assertEqual(["Birch Entry"], [u["n"] for u in work["live"]])
        acme = work["parked"]["units"][0]
        self.assertEqual((1, 1, "2 threads"), (acme["hp"], acme["s"], acme["subn"]))
        self.assertEqual([{"n": "Pricing", "s": 1, "pending": 1}, {"n": "Renewal", "s": 1, "held": 1, "pending": 1}], acme["threads"])
        self.assertTrue(out["gsum"].startswith("1 live · 2 parked"))
        woken = self.run_js((self.PRICING, self.OK), (self.ACME, self.OK), (dict(self.ACME, verb="wake"), self.OK))["zones"]["zone-work"]
        self.assertEqual(["Acme Review", "Birch Entry"], [u["n"] for u in woken["live"]])
        self.assertEqual([{"n": "Renewal", "s": 0, "pending": 1}], woken["live"][0]["threads"])
        self.assertEqual(0, woken["live"][0]["hp"])
        self.assertEqual(["Pricing"], [t["n"] for t in woken["parked"]["units"][0]["threads"]])  # parked on its own, it stays

    def test_waking_a_project_parked_in_the_note(self):
        hub = self.root / "Zones" / "Work" / "Acme Review" / "Acme Review.md"
        hub.write_text(hub.read_text().replace("status: active", "status: parked"))
        out = self.run_js((dict(self.ACME, verb="wake"), self.OK))
        acme = out["zones"]["zone-work"]["live"][0]
        self.assertEqual(("Acme Review", 0), (acme["n"], acme["hp"]))
        # Its threads had no Park of their own while held: none until the rebuild gives them one.
        self.assertEqual([{"n": "Pricing", "s": 0, "pend": 1, "pending": 1}, {"n": "Renewal", "s": 0, "pend": 1, "pending": 1}],
                         acme["threads"])
        self.assertIsNone(out["zones"]["zone-work"]["parked"])

    def test_nothing_moves_on_a_refusal_or_a_second_reply(self):
        before = self.run_js()
        self.assertEqual(before["zones"], self.run_js((self.BIRCH, {"ok": False, "say": "refused"}))["zones"])
        once = self.run_js((self.BIRCH, self.OK))
        self.assertEqual(once["zones"], self.run_js((self.BIRCH, self.OK), (self.BIRCH, self.OK))["zones"])
        self.assertEqual(before["zones"], self.run_js(({"verb": "todo-done", "zone": "Work"}, self.OK))["zones"])

    def test_a_reload_before_the_rebuild_moves_it_again(self):
        wait = {"x": "parked:Work/Birch Entry/Birch Entry.md", "until": 9e15}
        out = self.run_js((self.BIRCH, self.OK), expect=wait)
        self.assertEqual(dict(wait, q=self.BIRCH), out["expect"])                    # kept beside what the page waits for
        other = {"x": "parked:Work/Acme Review/Acme Review.md", "until": 9e15}
        self.assertEqual(other, self.run_js((self.BIRCH, self.OK), expect=other)["expect"])    # another click's, left alone
        again = self.run_js(redo=self.BIRCH)["zones"]["zone-work"]
        self.assertEqual("Birch Entry", again["parked"]["units"][0]["n"])
        self.assertIn("if(w.q)window.GarrickRedo=w.q;", status.RELOAD_JS)
        self.assertIn("if(window.GarrickRedo)moved(window.GarrickRedo);", status.PARK_JS)

    def test_the_hosts_hand_over_the_reply(self):
        swift = (Path(status.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")
        act = swift[swift.index("	func act(_ request: [String: Any]) {"):swift.index("	func acted(")]
        acted = swift[swift.index("	func acted("):swift.index("	// Only a folder inside this workspace")]
        self.assertIn("JSONSerialization.data(withJSONObject: [request, said])", acted)
        self.assertIn("window.GarrickActed&&window.GarrickActed(a[0],a[1])", acted)
        self.assertLess(act.index("self.acted(request, said ?? "), act.index("self.freshen(force: true)"))   # at once, then the rebuild
        plugin = (Path(status.__file__).parent / "obsidian" / "main.js").read_text(encoding="utf-8")
        self.assertIn("window.GarrickActed&&window.GarrickActed(a[0],a[1])", plugin)
        self.assertIn("this.rebuild(true);", plugin)
        page = self.page()
        self.assertLess(page.index("window.ThreadRows="), page.index("window.GarrickActed="))   # PARK_JS after the rows it moves

    def test_a_rebuild_asked_for_during_one_follows_it(self):
        swift = (Path(status.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")
        self.assertIn("if force || age >= maxAge { rebuild(queue: force) }", swift)
        self.assertIn("guard !rebuilding else { again = again || queue; return }", swift)
        self.assertIn("if self.again { self.again = false; self.rebuild() }", swift)
        plugin = (Path(status.__file__).parent / "obsidian" / "main.js").read_text(encoding="utf-8")
        self.assertIn("if (queue) this.again = true;", plugin)


SETTINGS_HARNESS = r"""
const vm = require("vm");
const [js, app, steps] = JSON.parse(process.argv[1]);
const els = {}, posted = [];
function el(id) {
  if (!els[id]) els[id] = { id, value: "", textContent: "", hidden: true, checked: false, disabled: false, style: {}, handlers: {},
    addEventListener(t, f) { (this.handlers[t] = this.handlers[t] || []).push(f); },
    closest() { return el(id + "-row"); }, blur() { this.fire("blur", {}); },
    fire(t, e) { (this.handlers[t] || []).forEach((f) => f(e)); } };
  return els[id];
}
const ctx = { JSON, String, Array, setTimeout: () => 0, clearTimeout: () => {},
              document: { getElementById: (id) => (id === "menu-style" ? null : el(id)) } };
ctx.window = { GarrickApp: app, webkit: { messageHandlers: { garrick: { postMessage: (m) => posted.push(m) } } } };
vm.createContext(ctx);
vm.runInContext(js, ctx);
for (const [id, type, e] of steps) {
  const ev = Object.assign({ key: "", code: "", metaKey: false, ctrlKey: false, altKey: false, shiftKey: false,
                             preventDefault() {}, stopPropagation() {} }, e || {});
  if (e && "value" in e) el(id).value = e.value;
  el(id).fire(type, ev);
}
process.stdout.write(JSON.stringify({ posted, notes: { hotkey: el("menu-hotkey-note").textContent, askhotkey: el("menu-askkey-note").textContent,
                                                       dictation: el("menu-dictation-note").textContent, dictationkey: el("menu-dictkey-note").textContent },
                                     askRow: el("menu-askkey-row").style.display, ask: el("menu-askkey").value,
                                     dictRow: el("menu-dictation-row").style.display, dictKeyRow: el("menu-dictkey-row").style.display,
                                     dictation: el("menu-dictation").value, dictkey: el("menu-dictkey").value }));
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestHotkeyFields(unittest.TestCase):
    """Settings › Menu bar's two key fields, run in Node against a stand-in DOM."""

    def run_js(self, app, *steps):
        import subprocess
        done = subprocess.run(["node", "-e", SETTINGS_HARNESS, json.dumps([status.MENU_SETTINGS_JS, app, [list(s) for s in steps]])],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_a_field_lets_the_apps_keys_go_while_it_records(self):
        out = self.run_js({"hotkey": "", "askhotkey": "⌘G", "askdefault": True},
                          ("menu-askkey", "focus"), ("menu-askkey", "keydown", {"key": "g", "code": "KeyG", "metaKey": True}),
                          ("menu-askkey", "blur"))
        self.assertEqual([{"app": {"recording": True}},
                          {"app": {"askhotkey": {"code": "KeyG", "mods": ["cmd"], "label": "⌘G"}}},
                          {"app": {"recording": False}}], out["posted"])
        self.assertEqual(("", "⌘G"), (out["askRow"], out["ask"]))
        self.assertIn("⌘G until you set another", out["notes"]["askhotkey"])

    def test_the_menu_may_take_cmd_g_from_the_default(self):
        out = self.run_js({"hotkey": "", "askhotkey": "⌘G", "askdefault": True},
                          ("menu-hotkey", "keydown", {"key": "g", "code": "KeyG", "metaKey": True}))
        self.assertEqual([{"app": {"hotkey": {"code": "KeyG", "mods": ["cmd"], "label": "⌘G"}}}], out["posted"])

    def test_one_key_never_serves_both(self):
        out = self.run_js({"hotkey": "⌘G", "askhotkey": "⌃⌥A", "askdefault": False},
                          ("menu-askkey", "keydown", {"key": "g", "code": "KeyG", "metaKey": True}),
                          ("menu-hotkey", "keydown", {"key": "a", "code": "KeyA", "ctrlKey": True, "altKey": True}))
        self.assertEqual([], out["posted"])
        self.assertEqual("⌘G is already the menu's hotkey. Clear it there, or pick another.", out["notes"]["askhotkey"])
        self.assertEqual("⌃⌥A is already the Ask hotkey. Clear it there, or pick another.", out["notes"]["hotkey"])

    def test_what_macos_refuses_is_said_before_asking(self):
        out = self.run_js({"hotkey": "", "askhotkey": ""},
                          ("menu-hotkey", "keydown", {"key": " ", "code": "Space", "altKey": True}),
                          ("menu-hotkey", "keydown", {"key": "k", "code": "KeyK"}),
                          ("menu-askkey", "keydown", {"key": "Backspace", "code": "Backspace"}))
        self.assertEqual([{"app": {"askhotkey": None}}], out["posted"])             # Delete clears; the others are refused
        self.assertEqual("Use ⌘, ⌃ or ⌥ with the key.", out["notes"]["hotkey"])
        out = self.run_js({"hotkey": "", "askhotkey": ""}, ("menu-hotkey", "keydown", {"key": " ", "code": "Space", "altKey": True, "shiftKey": True}))
        self.assertEqual([], out["posted"])
        self.assertEqual("Since macOS 15, a shortcut with only ⌥ or ⌥⇧ never reaches an app: add ⌘ or ⌃.", out["notes"]["hotkey"])

    def test_an_app_without_the_setting_hides_its_row(self):
        out = self.run_js({"hotkey": "⌥Space"})
        self.assertEqual("none", out["askRow"])
        self.assertEqual("Opens the menu or the panel from any app", out["notes"]["hotkey"])
        self.assertEqual(("none", "none"), (out["dictRow"], out["dictKeyRow"]))   # nor the dictation rows, from an app before #35

    def test_the_ask_box_starts_dictation_as_chosen(self):
        out = self.run_js({"hotkey": "", "askhotkey": "⌘G", "dictation": "off", "dictationkey": ""},
                          ("menu-dictation", "change", {"value": "fn"}))
        self.assertEqual([{"app": {"dictation": "fn"}}], out["posted"])
        self.assertEqual(("", "none"), (out["dictRow"], out["dictKeyRow"]))   # the shortcut field only for a shortcut
        self.assertEqual("Once the Ask box opens, start dictation in it too", out["notes"]["dictation"])
        out = self.run_js({"hotkey": "", "askhotkey": "⌘G", "dictation": "fn2", "dictationkey": ""})
        self.assertIn("Needs the Accessibility permission", out["notes"]["dictation"])
        out = self.run_js({"hotkey": "", "askhotkey": "⌘G", "dictation": "macos", "dictationkey": "",
                           "said": {"dictation": "Allow Garrick in System Settings"}})
        self.assertEqual(("macos", "Allow Garrick in System Settings"), (out["dictation"], out["notes"]["dictation"]))   # the app's word wins

    def test_the_dictation_shortcut_is_pressed_not_held(self):
        app = {"hotkey": "⌃Space", "askhotkey": "⌘G", "dictation": "key", "dictationkey": ""}
        out = self.run_js(app, ("menu-dictkey", "keydown", {"key": " ", "code": "Space", "altKey": True}))
        self.assertEqual("", out["dictKeyRow"])
        self.assertEqual([{"app": {"dictationkey": {"code": "Space", "mods": ["alt"], "label": "⌥Space"}}}], out["posted"])   # ⌥ alone is fine to press
        out = self.run_js(app, ("menu-dictkey", "keydown", {"key": "g", "code": "KeyG", "metaKey": True}),
                          ("menu-dictkey", "keydown", {"key": " ", "code": "Space", "ctrlKey": True}),
                          ("menu-dictkey", "keydown", {"key": "d", "code": "KeyD"}))
        self.assertEqual([], out["posted"])                                       # neither hotkey, and not a bare letter
        self.assertEqual("Use ⌘, ⌃ or ⌥ with the key.", out["notes"]["dictationkey"])
        out = self.run_js(app, ("menu-dictkey", "keydown", {"key": "g", "code": "KeyG", "metaKey": True}))
        self.assertEqual("⌘G is already a hotkey of Garrick's. Pick your dictation tool's key.", out["notes"]["dictationkey"])


class TestAppNotifies(unittest.TestCase):
    def test_an_answer_with_the_window_out_of_sight_comes_as_a_notification(self):
        swift = (Path(status.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")
        toast = swift[swift.index("func toast("):swift.index("func notify(")]
        self.assertIn("!window.isVisible || !NSApp.isActive { notify(text) }", toast)
        self.assertIn("UNUserNotificationCenter.current()", swift[swift.index("func notify("):])



GRAPH_HARNESS = r"""
const vm = require("vm");
const [js, data, asks] = JSON.parse(process.argv[1]);
// Everything the graph reaches for on a canvas, a window or a page answers with this, and nothing happens.
const any = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => 0 : k === "length" ? 0 : any,
                                        apply: () => any, construct: () => any });
const ctx = { JSON, String, Array, Object, Math, Date, localStorage: { getItem: () => null, setItem: () => {} },
              document: new Proxy({}, { get: (t, k) => k === "getElementById" ? (id) => id === "graph-data" ? { textContent: data } : any
                                                       : k === "querySelectorAll" ? () => [] : any }),
              Panel: any, requestAnimationFrame: () => 0, setTimeout: () => 0, addEventListener: () => {},
              matchMedia: () => ({ matches: true }), IntersectionObserver: any, ResizeObserver: any, MutationObserver: any,
              getComputedStyle: () => any, location: any, navigator: any, innerWidth: 800, innerHeight: 600, devicePixelRatio: 1 };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(js, ctx);
process.stdout.write(JSON.stringify(asks.map((u) => ctx.window.GarrickGraph.focus(u))));
"""


class TestRowsLightTheGraph(StatusCase):
    """#62: hovering a project or thread row lights its node in the graph, as hovering the node does."""

    def test_a_row_and_its_node_share_the_link(self):
        html = self.page()
        nodes = {n["u"]: n for n in graph_data(html)["nodes"]}
        for (project, thread), card in cards(html).items():
            self.assertEqual(thread, nodes[card["u"]]["n"])                               # a thread row: its note
        for project, card in project_cards(html).items():
            self.assertTrue(nodes[card["u"]]["h"], project)                              # a project row: its hub

    def test_rows_reach_the_graph_only_through_its_one_way_in(self):
        self.assertIn("row.addEventListener('mouseenter',function(){light(row);", status.JS)
        self.assertIn("row.addEventListener('mouseleave',function(){dark();tLater()});", status.JS)
        self.assertIn("row.addEventListener('focusin',function(){light(row);", status.JS)
        self.assertIn("tc.hidden=true;dark()}", status.JS)                               # the card closing puts it back
        self.assertIn("var g=window.GarrickGraph,o;if(!g)return;", status.JS)            # no graph, nothing to light
        self.assertNotIn("window.GarrickGraph={", self.page(show_graph=False))         # with --no-graph, no way in

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_only_a_node_the_graph_shows_is_lit(self):
        work = self.root / "Zones" / "Work"
        write(work / "Acme Review" / "Threads" / "Renewal" / "Renewal.md", thread_note("Acme Review", "Renewal", "acme", status="parked"))
        html = self.page()
        data = re.search(r'<script type="application/json" id="graph-data">(.*?)</script>', html, re.S).group(1)
        nodes = {n["n"]: n["u"] for n in graph_data(html)["nodes"]}
        asks = [nodes["Pricing"], nodes["Renewal"], "file:///nowhere.md", None]
        done = subprocess.run(["node", "-e", GRAPH_HARNESS, json.dumps([status.GRAPH_JS, data, asks])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual([True, False, False, False], json.loads(done.stdout))            # a parked thread stays off the graph


class TestSettingsFromTheMenu(unittest.TestCase):
    """#34: Settings… in the menu bar menu and a cog in the panel's footer, between Open Garrick and Quit."""

    swift = (Path(status.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")

    def test_the_menu_and_the_panel_match(self):
        s = self.swift
        menu = s[s.index('let open = NSMenuItem(title: "Open Garrick"'):s.index('menu.addItem(quit)')]
        self.assertLess(menu.index('"Open Garrick"'), menu.index('"Settings…", action: #selector(showSettings(_:))'))
        self.assertLess(menu.index('"Settings…"'), menu.index('"Quit Garrick"'))
        self.assertIn('show(settings, symbol("gearshape"))', menu)
        foot = s[s.index('.help("Open Garrick")'):s.index('.help("Quit Garrick")')]
        self.assertIn('Button { model.perform(model.openSettings) } label: { Image(systemName: "gearshape") }', foot)
        self.assertIn('.help("Settings")', foot)
        self.assertIn("m.openSettings = { [weak self] in self?.showSettings() }", s)

    def test_the_click_is_never_lost(self):
        s = self.swift
        show = s[s.index("@objc func showSettings("):s.index("// Left in the Dock for days")]
        self.assertLess(show.index("showWindow()"), show.index("openSettings(nil)"))           # the window first, as Open Garrick
        self.assertIn("if pageLoaded != nil && !web.isLoading { openSettings(nil) }", show)
        loaded = s[s.index("func webView(_ webView: WKWebView, didFinish"):]
        self.assertIn("if -asked.timeIntervalSinceNow < 60 { openSettings(nil) }", loaded[:600])   # a page loading opens it when it has
        self.assertIn("window.StatusSettings && window.StatusSettings.open()", s)              # the same as ⌘,
