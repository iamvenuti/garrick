"""The status page's fuller features, against a fictional workspace: the Todo
tab, resume points, jobs that run or idle, the assistant's spend, a vault's
excluded files and the graph's colours, sessions from the cmux extra, shared launcher settings,
--settle and the folders effort.py is told about.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import datetime as dt
import html as htmllib
import io
import inspect
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
from test_status import REPO, StatusCase, cards, graph_data, stamp, status  # noqa: E402


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

    def test_the_toolbar_and_done_today_hold_no_how_to(self):
        _, tab = self.tab()
        bar = tab[tab.index('<div class="tbar">'):tab.index('<div class="tz"')]
        self.assertNotIn('class="hint"', bar)                            # the zones, the filters and the sort only (#235)
        self.assertNotIn("Tick a box again", tab)
        self.assertRegex(tab, r'<span class="tname">Done today</span><span class="n">1</span></summary>')
        self.assertIn('<button class="tick" type="button" title="Reopen" aria-label="Reopen: Sent the brief', tab)
        self.assertIn("b.title=d?'Reopen':'Mark done'", status.WORK_JS)   # and the title follows a tick
        self.assertIn("t.title=d?'Reopen':'Mark done'", status.TODO_JS)
        for said in ("Tick to close", "A preview feature"):               # neither form of the hint, in the app or a browser
            self.assertNotIn(said, inspect.getsource(status.todo_list_card))

    def test_grouped_as_the_todo_file_groups_them(self):
        _, tab = self.tab()
        names = re.findall(r'<span class="tname">([^<]*)</span>', tab)
        self.assertEqual(["Inbox",                                                              # Personal: an empty Inbox is said
                          "Inbox", "This week", "Waiting on", "In thread notes", "Done today"], names)   # Work; Soon is empty
        self.assertIn("Inbox clear.", tab)
        work = tab[tab.index('<div class="tz" data-zone="Work"'):]
        self.assertLess(work.index("Book the room"), work.index("Send the revised terms"))      # A-Z: no thread first
        self.assertIn("<b>5</b> open", work)
        self.assertIn("<b>2</b> late</span>", work)                                     # a chase is late on its day
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
        self.assertIn("verb=d?'todo-done':'todo-undo';", status.TODO_JS)     # a done row's box sends the undo
        self.assertIn("GarrickTick({verb:verb,", status.TODO_JS)

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
        self.assertIn('<button class="tdate late" type="button"', tab)
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
        # #179: on its row it is the check's error, with a `check` chip that says what writes it;
        # the project's row still counts it, and its card still says it.
        self.note().write_text(thread_note("Acme Review", "Pricing").replace("### Resume here", "### Notes"))
        html = self.page()
        self.assertNotIn("no resume block</span>", html)
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
        self.assertIn('<span class="ink2">Per call</span><span class="num">$2 max</span>', self.calls(html))   # a figure, not a sentence (#232)
        self.assertNotIn("Each Claude call stops at", html)
        self.assertIn("$2 max per call", html)
        with self.plists(GARRICK_MAX_CALL_USD="0"):
            html = self.page()
            self.assertIn("no per-call budget", html)
            self.assertIn('<span class="ink2">Per call</span><span class="num">no cap</span>', self.calls(html))

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

    def test_a_vaults_colour_groups_change_nothing(self):
        # #292: the graph does not depend on Obsidian. A workspace whose vaults have colour groups draws the same graph.
        work = self.root / "Zones" / "Work"
        self.obsidian(work)
        self.obsidian(self.root)
        before = graph_data(self.page())
        self.obsidian(work, groups=[("[type:project] OR file:Notes", 0xFF0000), ("path:Birch Entry", 0x00FF00)])
        self.obsidian(self.root, groups=[("[type:meeting]", 0x123456), ("[type:thread]", 0x654321)])
        html = self.page()
        after = graph_data(html)
        self.assertEqual(before, after)
        self.assertFalse(any("g" in n for n in after["nodes"]))
        self.assertNotIn("groups", after)
        self.assertNotIn("other", after)
        self.assertNotIn("Colours from Obsidian", html)
        self.assertNotIn("gkey", html)
        source = (Path(status.__file__)).read_text(encoding="utf-8")
        self.assertNotIn("colorGroups", source)                                 # nothing reads them
        self.assertNotIn('"graph.json"', source)
        for gone in ("obsidian_graph", "group_label", "group_match", "group_word", "PROPERTY_TERM", "OTHER"):
            self.assertFalse(hasattr(status, gone), gone)

    def test_ignore_filters_leave_notes_out(self):
        work = self.root / "Zones" / "Work"
        self.obsidian(work, ignore=["Birch Entry/", "/Sources/"])
        write(work / "Acme Review" / "Sources" / "Brief.md", "# Brief\n")
        names = {n["n"] for n in graph_data(self.page())["nodes"]}
        self.assertNotIn("Market Sizing", names)
        self.assertNotIn("Brief", names)
        self.assertIn("Pricing", names)

    def test_a_root_vaults_filters_hold_in_the_zones(self):
        self.obsidian(self.root, ignore=["Zones/Work/Birch Entry/"])
        names = {n["n"] for n in graph_data(self.page())["nodes"]}
        self.assertNotIn("Market Sizing", names)
        self.assertIn("Pricing", names)
        self.assertEqual([], status.vault_filters(None))

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
        self.assertEqual("entity", kind[by["Stray"]["k"]])                         # a model kind, in any wiki (#250)
        self.assertEqual(0, by["Stray"]["c"])                                     # but the hubs of Meetings are its people
        long = by["A very long report title about pallets, lanes, freight and the winter that came"]
        self.assertEqual("source", kind[long["k"]])
        self.assertTrue(long["n"].endswith("…") and len(long["n"]) <= 41, long["n"])
        self.assertEqual(1, by["lane-capacity"]["c"])
        self.assertEqual(0, long["c"])
        idx = {t: data["nodes"].index(by[t]) for t in ("lane-capacity", "safety-stock", "fictus-cloud")}
        pairs = {(a, b): w for a, b, w in data["ce"]}
        self.assertEqual(1, pairs[tuple(sorted((idx["lane-capacity"], idx["safety-stock"])))])   # one source cites both
        self.assertNotIn("cl", data)                                              # no view button to label (#250)
        self.assertEqual("all", data["modes"]["Knowledge"])
        self.assertIn("var pick=m==='all'?all:m==='core'?hub:((G.modes&&G.modes[z])||G.mode)==='all'?model:hub", status.GRAPH_JS)

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


    def test_a_workspace_deleted_during_the_wait_is_not_made_again(self):
        """A settled build outliving the workspace, as one a test's tool
        started can, writes nothing and makes no folder of it again."""
        gone = lambda marker, seconds: (shutil.rmtree(self.root), True)[1]
        with mock.patch.object(status, "settle", side_effect=gone), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(1, status.main(["--workspace", str(self.root), "--settle", "10", "--same-flags"]))
        self.assertFalse(self.root.exists())
        self.assertIn("no longer a workspace", err.getvalue())


class TestBuildsAtOnce(StatusCase):
    """Builds overlap in ordinary use: the app after a button, a hook, a job,
    a build by hand (#214). Each runs here as its own process, with a home
    folder and a PATH of the test's own, so nothing on this machine is read."""

    def builds(self, n=2):
        home = self.root.parent / "home"
        home.mkdir(exist_ok=True)
        env = dict(os.environ, HOME=str(home), PATH="/usr/bin:/bin", PYTHONDONTWRITEBYTECODE="1")
        env.pop("GARRICK_WORKSPACE", None)
        cmd = [sys.executable, str(REPO / "extras" / "status" / "status.py"), "--workspace", str(self.root),
               "--no-obsidian", "--no-cmux", "--no-graph"]
        procs = [subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(n)]
        return [(p.wait(timeout=120), p.stderr.read()) for p in procs]

    def generated(self):
        return sorted(p.name for p in (self.root / "System" / "generated").iterdir())

    def test_two_builds_at_once_both_succeed_and_leave_a_whole_page(self):
        for _ in range(3):                    # the race shows on the first go; three make sure
            for code, err in self.builds():
                self.assertEqual(0, code, err)
            page = (self.root / "System" / "generated" / "status.html").read_text(encoding="utf-8")
            self.assertTrue(page.startswith("<!doctype html>"))
            self.assertTrue(page.endswith("</body></html>"))
            self.assertEqual(1, page.count("<!doctype html>"))

    def test_no_temporary_file_is_left(self):
        for code, err in self.builds():
            self.assertEqual(0, code, err)
        self.assertEqual(["status.html"], [n for n in self.generated() if n.startswith("status.html")])
        self.assertFalse([n for n in self.generated() if n.endswith(".tmp")])
        out = self.jobs / "page.html"                                       # a write that fails takes its file away
        with mock.patch.object(status.os, "replace", side_effect=OSError("disk full")), \
                mock.patch.object(status, "build", return_value="<html></html>"), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                status.main(["--workspace", str(self.root), "--out", str(out), "--no-obsidian"])
        self.assertEqual([], sorted(p.name for p in self.jobs.iterdir() if p.name.startswith("page.html")))

    def test_the_last_to_finish_wins(self):
        out = self.jobs / "page.html"
        for text in ("<html>first</html>", "<html>second</html>"):
            status.write_page(out, text)
        self.assertEqual("<html>second</html>", out.read_text())
        self.assertEqual(["page.html"], sorted(p.name for p in self.jobs.iterdir()))


class TestReplacedWhileBuilding(StatusCase):
    """An update replaces System/status/status.py while a build is waiting
    out --settle (#213): the page must be the new code's, never the old's."""

    OLD_NAME = 'NAME = "Garrick"     #'
    NEW_NAME = 'NAME = "Garrick Next"     #'

    def test_a_build_whose_code_is_replaced_during_its_settle_wait_draws_with_the_new_code(self):
        copy = self.root / "System" / "status"
        shutil.copytree(REPO / "extras" / "status", copy, ignore=shutil.ignore_patterns("app", "obsidian", "__pycache__"))
        script = copy / "status.py"
        self.assertEqual(1, script.read_text(encoding="utf-8").count(self.OLD_NAME))
        home = self.root.parent / "home"
        home.mkdir()
        env = dict(os.environ, HOME=str(home), PATH="/usr/bin:/bin", PYTHONDONTWRITEBYTECODE="1")
        for k in ("GARRICK_WORKSPACE", status.RERUN):
            env.pop(k, None)
        page = self.root / "System" / "generated" / "status.html"
        proc = subprocess.Popen([sys.executable, str(script), "--workspace", str(self.root), "--settle", "3",
                                 "--no-obsidian", "--no-cmux", "--no-graph"],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        marker = page.with_name("status.html.settle")
        deadline = time.time() + 30
        while not marker.exists() and time.time() < deadline:      # loaded, and waiting
            time.sleep(0.05)
        self.assertTrue(marker.exists())
        newer = script.with_name("status.py.update")
        newer.write_text(script.read_text(encoding="utf-8").replace(self.OLD_NAME, self.NEW_NAME), encoding="utf-8")
        os.replace(newer, script)                                    # as an update writes it
        _, err = proc.communicate(timeout=120)
        self.assertEqual(0, proc.returncode, err)
        html = page.read_text(encoding="utf-8")
        self.assertTrue("<title>Garrick Next</title>" in html, "the page is not the new code's")
        self.assertFalse("<title>Garrick</title>" in html, "the old code drew the page")
        self.assertIn("building it again with the new one", err)
        self.assertEqual(["status.html", "status.html.settle"], sorted(p.name for p in page.parent.iterdir()
                                                                       if p.name.startswith("status.html")))

    def test_started_again_once_without_its_settle(self):
        out = self.jobs / "page.html"
        argv = ["--workspace", str(self.root), "--out", str(out), "--settle", "3", "--no-obsidian", "--no-graph"]
        with mock.patch.object(status, "STARTED", (0, 0, 0)), mock.patch.object(status, "settle", return_value=True), \
                mock.patch.dict(os.environ), mock.patch.object(status.subprocess, "call", return_value=0) as call, \
                mock.patch.object(status, "build", return_value="<html>old</html>"), contextlib.redirect_stderr(io.StringIO()):
            os.environ.pop(status.RERUN, None)
            self.assertEqual(0, status.main(argv))
        cmd = call.call_args.args[0]
        self.assertEqual([sys.executable, str(status.SELF), "--workspace", str(self.root), "--out", str(out),
                          "--no-obsidian", "--no-graph"], cmd)
        self.assertEqual("1", call.call_args.kwargs["env"][status.RERUN])
        self.assertFalse(out.exists())                               # the old code wrote nothing

    def test_a_build_started_again_that_finds_it_changed_again_writes_nothing(self):
        out = self.jobs / "page.html"
        err = io.StringIO()
        with mock.patch.object(status, "STARTED", (0, 0, 0)), mock.patch.dict(os.environ, {status.RERUN: "1"}), \
                mock.patch.object(status.subprocess, "call") as call, mock.patch.object(status.os, "execvpe") as execs, \
                mock.patch.object(status, "build", return_value="<html>old</html>"), contextlib.redirect_stderr(err):
            self.assertEqual(75, status.main(["--workspace", str(self.root), "--out", str(out), "--no-obsidian", "--no-graph"]))
        self.assertFalse(call.called or execs.called)
        self.assertFalse(out.exists())
        self.assertIn("the next build draws it", err.getvalue())

    def test_an_unchanged_file_builds_as_before(self):
        out = self.jobs / "page.html"
        with mock.patch.object(status.subprocess, "call") as call, mock.patch.object(status, "build", return_value="<html>new</html>"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, status.main(["--workspace", str(self.root), "--out", str(out), "--no-obsidian", "--no-graph"]))
        self.assertFalse(call.called)
        self.assertEqual("<html>new</html>", out.read_text(encoding="utf-8"))


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


class TestSameFlags(StatusCase):
    """#246: each build stores the flags that shape the page beside it, and a
    build with --same-flags, as scaffold.py and correct.py ask for, draws with
    them. Obsidian's vaults and the launchers are this test's own."""

    def setUp(self):
        super().setUp()
        self.out = self.jobs / "status.html"
        self.stored = self.jobs / "status.flags.json"
        for name, value in (("obsidian_vaults", []), ("launchers_installed", ())):
            p = mock.patch.object(status, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def main(self, *args, build=None):
        """status.main()'s exit code and the keywords build() was given, or None where it was not called."""
        with mock.patch.object(status, "build", side_effect=build, return_value="<html></html>") as b, \
                mock.patch.object(status, "release_ask"), contextlib.redirect_stdout(io.StringIO()):
            code = status.main(["--workspace", str(self.root), "--out", str(self.out), *args])
        return code, (b.call_args.kwargs if b.called else None)

    def test_a_tool_build_draws_with_the_flags_the_last_build_stored(self):
        real = status.build
        draw = lambda *a, **kw: real(*a, now=self.now, folder=self.jobs, **kw)
        _, first = self.main("--no-obsidian", "--no-graph", "--also", "/old/place", "--moved", "A=B", build=draw)
        self.assertEqual({"args": ["--no-obsidian", "--no-graph", "--also", "/old/place", "--moved", "A=B"]},
                         json.loads(self.stored.read_text(encoding="utf-8")))
        kept = self.stored.read_text(encoding="utf-8")
        code, again = self.main("--same-flags", build=draw)
        self.assertEqual(0, code)
        for k in ("also", "moved", "flags", "show_graph", "vaults"):
            self.assertEqual(first[k], again[k], k)
        self.assertEqual(("/old/place",), again["also"])
        self.assertEqual({"A": "B"}, again["moved"])
        self.assertFalse(again["show_graph"])
        rebuild = htmllib.unescape(re.search(r'id="rebuild"[^>]*data-copy="([^"]*)"', self.out.read_text(encoding="utf-8")).group(1))
        for words in ("--no-obsidian", "--also /old/place", "--moved A=B", "--no-graph"):
            self.assertIn(words, rebuild)                         # the page's own rebuild command names them
        self.assertEqual(kept, self.stored.read_text(encoding="utf-8"))      # used, not stored again

    def test_with_nothing_stored_it_builds_as_the_workspace_alone_does(self):
        _, alone = self.main()
        self.stored.unlink()
        code, same = self.main("--same-flags")
        self.assertEqual(0, code)
        self.assertEqual(alone, same)
        self.assertFalse(self.stored.exists())                    # and stores nothing
        self.stored.write_text("not json", encoding="utf-8")       # a file no build wrote counts as none
        self.assertEqual(alone, self.main("--same-flags")[1])
        self.stored.write_text('{"args": ["--obsidian"]}', encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(alone, self.main("--same-flags")[1])
        self.assertIn("built without them", err.getvalue())

    def test_the_last_build_wins_and_a_build_by_hand_stores_its_own(self):
        self.main("--no-cmux", "--also", "/old")
        self.main("--no-graph")
        self.assertEqual({"args": ["--no-graph"]}, json.loads(self.stored.read_text(encoding="utf-8")))
        self.main()
        self.assertEqual({"args": []}, json.loads(self.stored.read_text(encoding="utf-8")))
        self.assertEqual(True, self.main("--same-flags")[1]["show_graph"])

    def test_it_is_refused_with_the_flags_it_would_replace(self):
        for given in (["--no-graph"], ["--also", "/old"], ["--obsidian", "Vault"], ["--moved", "A=B"]):
            with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as stop:
                self.main("--same-flags", *given)
            self.assertEqual(2, stop.exception.code)
            self.assertIn("--same-flags", err.getvalue())

    def test_with_settle_the_flags_are_read_after_the_wait_and_a_burst_makes_one_page(self):
        self.main("--no-graph")
        app = lambda marker, seconds: (self.stored.write_text('{"args": ["--no-cmux"]}', encoding="utf-8"), True)[1]
        with mock.patch.object(status, "settle", side_effect=app) as s:
            _, kw = self.main("--same-flags", "--settle", "10")
        self.assertEqual(self.out.with_name("status.html.settle"), s.call_args.args[0])
        self.assertTrue(kw["show_graph"])                          # what the app stored during the wait
        self.assertEqual(("--no-cmux",), kw["flags"])
        with mock.patch.object(status, "settle", return_value=False):
            self.assertIsNone(self.main("--same-flags", "--settle", "10")[1])     # a later request builds it


    def test_the_evening_schedule_builds_with_the_stored_flags(self):
        """The 23:30 build is nobody choosing flags: it draws with the stored
        ones and stores none, so it cannot undo the app's (0.46.1)."""
        with open(REPO / "extras" / "status" / "garrick.status.plist", "rb") as f:
            args = plistlib.load(f)["ProgramArguments"]
        build = args[args.index("--") + 1:]
        self.assertTrue(build[1].endswith("/System/status/status.py"), build)
        self.assertEqual(["--workspace", "/Users/<you>/Garrick", "--same-flags"], build[2:])
        self.main("--no-graph", "--also", "/old")
        self.main(*build[4:])                                      # what follows the workspace
        self.assertEqual({"args": ["--no-graph", "--also", "/old"]}, json.loads(self.stored.read_text(encoding="utf-8")))


class TestCheckReuse(StatusCase):
    """#260: every build keeps the check's result beside the page, and a
    build given --reuse-check, as scaffold.py's and correct.py's are, shows
    it while it is younger than that instead of running the check again,
    saying how old it is. A build without the flag always runs it. The check
    here is the test's own: it counts its runs in a file."""

    def setUp(self):
        super().setUp()
        self.runs = self.jobs / "runs"
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        found = {"errors": 0, "warnings": 1, "findings": [{"check": "threads", "severity": "warning", "path": "a.md", "message": "x"}]}
        (tools / "check.py").write_text("import json\nopen(%r, 'a').write('ran\\n')\nprint(json.dumps(%r))\n"
                                        % (str(self.runs), found), encoding="utf-8")
        self.out = self.jobs / "status.html"
        self.kept = self.jobs / "status.check.json"

    def build(self, reuse=None, now=None):
        return status.build(self.root, now=now or self.now, folder=self.jobs, page_at=self.out, reuse_check=reuse)

    def ran(self):
        return len(self.runs.read_text().splitlines()) if self.runs.exists() else 0

    def test_a_young_result_is_shown_and_says_how_old_it_is(self):
        first = self.build()
        self.assertEqual(1, self.ran())
        self.assertNotIn("As the check found it", first)
        self.assertEqual(str(self.root), json.loads(self.kept.read_text(encoding="utf-8"))["workspace"])
        page = self.build(reuse=600, now=self.now + dt.timedelta(minutes=4))
        self.assertEqual(1, self.ran())                                # not run again
        self.assertIn("As the check found it 4 min ago", page)
        self.assertIn(">a.md</a>: x</span>", page)                     # the findings it kept, each path a link

    def test_an_old_or_missing_result_runs_the_check(self):
        self.build()
        self.build(reuse=600, now=self.now + dt.timedelta(minutes=11))
        self.assertEqual(2, self.ran())
        self.kept.unlink()
        page = self.build(reuse=600)
        self.assertEqual(3, self.ran())
        self.assertNotIn("As the check found it", page)
        self.kept.write_text("not json", encoding="utf-8")
        self.build(reuse=600)
        self.assertEqual(4, self.ran())

    def test_a_build_by_hand_or_on_schedule_runs_it_however_young(self):
        self.build()
        self.build(now=self.now + dt.timedelta(minutes=1))
        self.assertEqual(2, self.ran())
        self.assertNotIn("As the check found it", self.build(now=self.now + dt.timedelta(minutes=2)))

    def test_another_workspace_or_a_failed_check_is_never_shown(self):
        self.build()
        kept = json.loads(self.kept.read_text(encoding="utf-8"))
        self.kept.write_text(json.dumps(dict(kept, workspace="/elsewhere")), encoding="utf-8")
        self.build(reuse=600)
        self.assertEqual(2, self.ran())
        self.kept.unlink()
        with mock.patch.object(status.subprocess, "run", side_effect=OSError("no python")):
            self.assertIn("The check did not run", self.build())
        self.assertFalse(self.kept.exists())                           # a failure is not kept

    def test_the_flag_reaches_the_build_and_without_a_page_nothing_is_kept(self):
        with mock.patch.object(status, "build", return_value="<html></html>") as b, \
                mock.patch.object(status, "release_ask"), mock.patch.object(status, "obsidian_vaults", return_value=[]), \
                mock.patch.object(status, "launchers_installed", return_value=()), contextlib.redirect_stdout(io.StringIO()):
            status.main(["--workspace", str(self.root), "--out", str(self.out), "--same-flags", "--reuse-check", "600"])
        self.assertEqual((600, self.out), (b.call_args.kwargs["reuse_check"], b.call_args.kwargs["page_at"]))
        self.page()
        self.assertFalse(self.kept.exists())


class TestSharedLauncherSettings(StatusCase):
    def test_embedded_when_saved(self):
        self.assertNotIn('id="launch-settings"', self.page())
        write(self.root / "System" / "garrick-settings.json",
              json.dumps({"launchers": ["note", "claude", "nonsense"], "default": "claude"}))
        found = re.search(r'id="launch-settings">(.*?)</script>', self.page(), re.S)
        self.assertEqual({"launchers": ["note", "claude"], "default": "claude"}, json.loads(found.group(1)))
        write(self.root / "System" / "garrick-settings.json",
              json.dumps({"launchers": {"note": True, "finder": False, "cmux": False, "codex": False}, "default": "cmux"}))
        found = re.search(r'id="launch-settings">(.*?)</script>', self.page(), re.S)
        self.assertEqual({"launchers": ["note", "preview", "claude"], "default": "cmux"}, json.loads(found.group(1)))   # a name left out is on
        # Explore's Preview (#219): on in a choice saved before it had one, off once switched off, and never the default
        write(self.root / "System" / "garrick-settings.json",
              json.dumps({"launchers": {"note": True, "preview": False}, "default": "preview"}))
        found = re.search(r'id="launch-settings">(.*?)</script>', self.page(), re.S)
        self.assertEqual({"launchers": ["note", "finder", "cmux", "codex", "claude"], "default": "note"}, json.loads(found.group(1)))
        write(self.root / "System" / "garrick-settings.json", json.dumps({"launchers": "all"}))
        self.assertNotIn('id="launch-settings"', self.page())

    def test_the_app_prefers_them_and_saves_through_the_bridge(self):
        self.assertIn("if(host&&el){try{shared=JSON.parse(el.textContent)}", status.PANEL_JS)    # a browser keeps its own
        self.assertIn("return{verb:'settings',launchers:", status.PANEL_JS)
        # A change to the launchers, the zones, the notifications, While you wait, Memory or which assistant a
        # cmux tab starts (#279) makes a request; none makes none. The launchers lead it, the zones and the
        # notifications ride on it, and the desk's choice goes as desk-agent, read from its select.
        self.assertIn("if(!(lpChanged||zChanged||daChanged||n||w||m))return null;\nvar q=lpChanged?GarrickPrefs.request():{verb:'settings'};"
                      "if(zChanged)q.zones=zreq();if(n)q.notifications=N.request();\n"
                      "if(daChanged){q['desk-agent']=document.getElementById('desk-agent').value;daChanged=false}", status.JS)
        self.assertIn("daSel.onchange=function(){daChanged=true;", status.JS)            # set by the select alone


class TestZoneOrder(StatusCase):
    """The Threads card leads with the zone the graph shows (#72)."""

    def test_each_zone_names_itself_and_the_graph_reorders_them(self):
        html = self.page()
        self.assertIn('<details class="zone tsort" id="zone-work" data-zone="Work" open>', html)
        self.assertIn('<details class="zone tsort" id="zone-personal" data-zone="Personal" open>', html)
        self.assertLess(html.index('data-zone="Personal"'), html.index('data-zone="Work"'))    # by name, as built
        self.assertIn("function leadZone(z){", status.GRAPH_JS)
        self.assertIn("leadZone(zsel);", status.GRAPH_JS.split("function leadZone")[1])          # on load
        self.assertIn("st.set('garrick-graph-place',z);leadZone(z);", status.GRAPH_JS)          # on each pick
class TestSettingsRowLines(StatusCase):
    """Settings (#205): a row's own grey line says what the row does, always
    shown, so nobody has to press a "?" to know what a control does."""

    def test_row_lines_always_show(self):
        html = self.page()
        self.assertNotIn(":not(.explained)", html)                                       # nothing hides them
        self.assertNotIn("classList.toggle('explained'", html)
        self.assertNotIn("r.dataset.tip0", html)                                          # nor copies them into a tooltip
        self.assertIn("<small>", html[html.index('id="settings"'):])                     # the lines are all still there


class TestZoneColours(StatusCase):
    """Settings › Zones (#67): a colour and an icon per zone, on every label that names it."""

    def save(self, zones):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"zones": zones}))

    def test_read_with_unknown_names_dropped(self):
        self.assertEqual({}, status.zone_styles(self.root))
        self.save({"Work": {"color": "teal", "icon": "briefcase"}, "Personal": {"color": "Mauve", "icon": "house"},
                   "Other": {"color": "Plum", "icon": "unicorn"}, "Odd": "Teal"})
        self.assertEqual({"Work": {"color": "Teal", "icon": "briefcase"}, "Personal": {"icon": "house"}},
                         status.zone_styles(self.root))
        write(self.root / "System" / "garrick-settings.json", "not json")
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
        self.assertIn('<div class="zt"><b class="zc zc-teal">%sWork</b>' % icon, html)       # Todo
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
const [js, hosted, calls, launchers, cli] = JSON.parse(process.argv[1]);
const dataset = cli ? { launchers, cli: "1" } : { launchers };
const ctx = { JSON, String, Array, localStorage: { getItem: () => null, setItem: () => {} },
              document: { getElementById: () => null, addEventListener: () => {}, body: { dataset } } };
ctx.window = hosted ? { webkit: { messageHandlers: { garrick: { postMessage: () => {} } } } } : {};
vm.createContext(ctx);
vm.runInContext(js + ";this.out=" + JSON.stringify(calls) + ".map(function(c){return Panel[c[0]](c[1],c[2])})", ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""


def panel(hosted, *calls, launchers="", cli=False):
    """Panel.head or Panel.acts, run in Node as the app (hosted) or a browser would.
    A call is (name, card) or, for a row's card, ("head", card, 1). `launchers`
    is what the page's body carries: the ways to open a thread this Mac has;
    `cli`, whether it says the build found Claude Code's command-line tool."""
    import subprocess
    done = subprocess.run(["node", "-e", PANEL_HARNESS,
                           json.dumps([status.PANEL_JS, hosted, [list(c) for c in calls], launchers, cli])],
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


# Just enough of a DOM for a script the page ships, run against the page
# status.py wrote: elements, text, attributes, the selectors it uses, and an
# HTML reader for well-formed markup. PARK_JS's harness, just below, shares it
# with LAYOUT_JS's, further down.
DOM = r"""
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
             remove: (...cs) => { el.className = list().filter((c) => !cs.includes(c)).join(" "); },
             toggle: (c, on) => { if (on === undefined ? !list().includes(c) : on) el.classList.add(c); else el.classList.remove(c); } };
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
"""


# PARK_JS against a page status.py wrote: the requests, each with
# page_action.py's reply, then what the list shows.
DOM_HARNESS = r"""
const vm = require("vm");
const [html, js, steps, redo, expect] = JSON.parse(process.argv[1]);
""" + DOM + r"""
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


# RENAME_JS (#184), with PARK_JS before it and FIND_JS after, as the page
# runs them: the requests with page_action.py's replies, then every row as its
# card and its link say it, the order of each list, and what Find finds.
RENAME_HARNESS = r"""
const vm = require("vm");
const [html, js, steps, redo, expect, find] = JSON.parse(process.argv[1]);
""" + DOM + r"""
const doc = new El("#document");
parse(html, doc);
const store = {};
if (expect) store["garrick-expect"] = JSON.stringify(expect);
const ctx = { JSON, String, Array, Object, RegExp,
  localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
  sessionStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  document: { querySelectorAll: (s) => doc.querySelectorAll(s), querySelector: (s) => doc.querySelector(s), createElement: (t) => new El(t),
              getElementById: (id) => doc.querySelectorAll("#" + id)[0] || null, addEventListener: () => {} } };
ctx.window = ctx;
ctx.ThreadRows = { bind: () => {}, chev: () => {}, close: () => { ctx.closed = (ctx.closed || 0) + 1; } };
ctx.GarrickRedo = redo || undefined;
ctx.GarrickExpect = (x) => { store["garrick-expect"] = JSON.stringify({ x: x, until: 9e15 }); };
vm.createContext(ctx);
vm.runInContext(js, ctx);
steps.forEach(([q, out]) => ctx.window.GarrickActed(q, out));
const rows = doc.querySelectorAll(".tview .thread[data-card]").map((r) => {
  const c = JSON.parse(r.dataset.card), a = r.querySelector(".t>a");
  return { n: c.n, p: c.p, u: c.u, f: c.f, pa: c.pa, oc: c.oc, mg: c.mg, dk: c.dk, w: c.w, text: a && a.textContent, href: a && a.getAttribute("href") };
});
const order = doc.querySelectorAll(".subthreads").map((b) => b.querySelectorAll(":scope>.thread").map((r) => JSON.parse(r.dataset.card).n));
const units = doc.querySelectorAll(".tview details.zone").map((z) => z.children.filter((c) => c.classList.contains("tunit"))
  .map((u) => JSON.parse(u.querySelector(".thread").dataset.card).n));
process.stdout.write(JSON.stringify({ rows, order, units, closed: ctx.closed || 0, find: find ? ctx.GarrickFind.find(find) : null,
                                      expect: store["garrick-expect"] ? JSON.parse(store["garrick-expect"]) : null }));
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestRenameLandsAtOnce(StatusCase):
    """A rename from the page renames the row in place, everything a later
    click reads from it included, and the rebuild confirms it (#184)."""

    def setUp(self):
        super().setUp()
        write(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Renewal" / "Renewal.md",
              thread_note("Acme Review", "Renewal", "acme"))

    def run_js(self, *steps, redo=None, expect=None, find=None):
        import subprocess
        html = self.page(show_graph=False)
        js = status.PARK_JS + status.RENAME_JS + status.FIND_JS
        done = subprocess.run(["node", "-e", RENAME_HARNESS, json.dumps([html, js, [list(s) for s in steps], redo, expect, find])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    OK = {"ok": True, "say": "Renamed"}
    THREAD = {"verb": "rename", "zone": "Work", "project": "Acme Review", "thread": "Pricing", "to": "Zebra Rates"}
    PROJECT = {"verb": "rename", "zone": "Work", "project": "Acme Review", "to": "Zulu Review"}

    def row(self, out, name):
        return [r for r in out["rows"] if r["n"] == name][0]

    def test_a_thread_takes_its_new_name_paths_and_place_at_once(self):
        before = self.row(self.run_js(), "Pricing")
        out = self.run_js((self.THREAD, self.OK), find="zebra")
        r = self.row(out, "Zebra Rates")
        self.assertEqual("Zebra Rates", r["text"])
        self.assertEqual(r["u"], r["href"])
        self.assertEqual(before["u"].replace("Threads/Pricing/Pricing", "Threads/Zebra%20Rates/Zebra%20Rates"), r["u"])
        self.assertEqual(["Work", "Acme Review/Threads/Zebra Rates/Zebra Rates.md"], r["oc"])
        self.assertEqual(["Work", "Acme Review/Threads/Zebra Rates/Zebra Rates.md"], r["pa"])
        self.assertEqual(["Work", "Acme Review", "Zebra Rates"], r["mg"][:3])        # Rename… and Delete… act on the new name
        self.assertEqual(["Renewal", "Zebra Rates"], out["order"][0])                  # its place by name
        self.assertNotIn("Pricing", [x["n"] for x in out["rows"]])
        self.assertEqual(1, out["closed"])
        self.assertEqual(["Zebra Rates"], [h["n"] for h in out["find"]])
        self.assertEqual({"x": "named:Work/Acme Review/Threads/Zebra Rates/Zebra Rates.md", "until": 9e15, "q": self.THREAD},
                         out["expect"])

    def test_a_project_takes_its_threads_with_it(self):
        out = self.run_js((self.PROJECT, self.OK), find="zulu")
        head = self.row(out, "Zulu Review")
        self.assertEqual("Zulu Review", head["text"])
        self.assertEqual(["Work", "Zulu Review"], head["mg"][:2])
        renewal = self.row(out, "Renewal")
        self.assertEqual("Zulu Review", renewal["p"])
        self.assertEqual(["Work", "Zulu Review/Threads/Renewal/Renewal.md"], renewal["oc"])
        self.assertIn("Zulu%20Review/Threads/Renewal/Renewal", renewal["u"])
        self.assertEqual(["Birch Entry", "Zulu Review"], out["units"][1])            # its place by name now
        self.assertTrue(out["find"])

    def test_a_refusal_changes_nothing_and_a_reload_before_the_rebuild_renames_again(self):
        before = self.run_js()
        self.assertEqual(before["rows"], self.run_js((self.THREAD, {"ok": False, "say": "refused"}))["rows"])
        again = self.run_js(redo=self.THREAD, find="zebra")
        self.assertEqual("Zebra Rates", self.row(again, "Zebra Rates")["text"])
        self.assertEqual(["Zebra Rates"], [h["n"] for h in again["find"]])
        self.assertIn("else if(want==='named')now=(S.notes||[]).indexOf(key)>=0?'named':'none';", status.RELOAD_JS)
        state = json.loads(re.search(r'<script type="application/json" id="state-data">(.*?)</script>',
                                     self.page(show_graph=False), re.S).group(1))
        self.assertIn("Work/Acme Review/Threads/Pricing/Pricing.md", state["notes"])


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


class TestKindsFromPages(StatusCase):
    """#250: a type Garrick's model does not know, shared by enough pages of one wiki, is a kind of its own."""

    def meetings(self, domains=("Freight", "Customs", "Ports"), more=()):
        m = self.root / "Wikis" / "Meetings" / "wiki"
        for name in domains:
            write(m / "domains" / (name.lower() + ".md"), "---\ntitle: %s\ntype: domain\n---\n" % name)
        for t, names in more:
            for name in names:
                write(m / "notes" / (name.lower() + ".md"), "---\ntitle: %s\ntype: %s\n---\n" % (name, t))
        write(m / "entities" / "fictus.md", "---\ntitle: Fictus Cloud\ntype: entity\n---\n\nSee [[freight]].\n")
        write(m / "entities" / "brightline.md", "---\ntitle: Brightline\ntype: entity\n---\n")
        write(m / "notes" / "memo-1.md", "---\ntitle: Memo one\ntype: memo\n---\n")
        write(m / "notes" / "memo-2.md", "---\ntitle: Memo two\ntype: memo\n---\n")
        write(m / "notes" / "loose.md", "# Loose\n")
        html = self.page()
        data = graph_data(html)
        return html, data, {n.get("N", n["n"]): n for n in data["nodes"]}

    def test_three_pages_of_a_type_make_a_kind(self):
        html, data, by = self.meetings()
        kind, keys = dict(data["kinds"]), data["keys"]
        self.assertEqual(3, status.KIND_FROM_PAGES)
        self.assertEqual(len(status.KINDS), data["known"])
        domain = by["Freight"]["k"]
        self.assertEqual(("domain", "domain"), (kind[domain], keys[domain]))
        self.assertGreaterEqual(domain, data["known"])                          # after the shipped kinds
        self.assertEqual({domain}, {by[n]["k"] for n in ("Freight", "Customs", "Ports")})
        self.assertIn(data["colors"][domain], status.PAGE_COLOURS)
        self.assertEqual(0, by["Freight"]["c"])                                 # not a hub: it starts hidden
        self.assertEqual("entity", kind[by["Fictus Cloud"]["k"]])               # a model kind is reused, in any wiki
        self.assertEqual(keys.index("entity"), by["Brightline"]["k"])
        for name in ("Memo one", "Memo two", "loose"):
            self.assertEqual("other notes", kind[by[name]["k"]], name)          # too rare, or no type at all
        self.assertNotIn("memo", keys)
        self.assertIn('<button type="button" data-k="%d" aria-pressed="true"><i style="background:%s"></i>Domains</button>'
                      % (domain, data["colors"][domain]), html)
        self.assertIn("></i>Entities</button>", html)

    def test_two_pages_are_not_enough(self):
        _, data, by = self.meetings(domains=("Freight", "Customs"))
        self.assertNotIn("domain", data["keys"])
        self.assertEqual("other notes", dict(data["kinds"])[by["Freight"]["k"]])
        self.assertEqual(len(status.KINDS), len(data["colors"]))

    def test_a_kind_keeps_its_colour(self):
        _, data, by = self.meetings()
        colour = data["colors"][by["Freight"]["k"]]
        self.assertEqual(colour, graph_data(self.page())["colors"][by["Freight"]["k"]])     # from one build to the next
        # Kinds that come later, before it and after it by name, one wanting its colour: it keeps it.
        _, data, by = self.meetings(more=(("area", ("North", "South", "East")), ("theme", ("Cost", "Speed", "Risk"))))
        self.assertEqual(colour, data["colors"][by["Freight"]["k"]])
        found = [data["colors"][by[n]["k"]] for n in ("Freight", "North", "Cost")]
        self.assertEqual(3, len(set(found)))                                     # each its own

    def test_the_palette_stands_apart(self):
        shipped = {c.lower() for _, _, c in status.KINDS}
        rings = set(re.search(r"--warning:(#[0-9a-f]{6});--critical:(#[0-9a-f]{6})", status.CSS).groups())
        self.assertEqual(len(status.PAGE_COLOURS), len(set(status.PAGE_COLOURS)))
        self.assertFalse({c.lower() for c in status.PAGE_COLOURS} & (shipped | rings | {status.BRAND.lower()}))

        def lum(h):
            c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            c = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in c]
            return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
        surfaces = re.findall(r"--surface:(#[0-9a-f]{6})", status.CSS)
        self.assertGreaterEqual(len(set(surfaces)), 2)                           # the light card and the dark one
        for c in status.PAGE_COLOURS:
            for bg in set(surfaces):
                a, b = sorted((lum(c), lum(bg)))
                self.assertGreaterEqual((b + .05) / (a + .05), 2.9, (c, bg))

    def test_the_legend_says_a_kind_as_a_filter_does(self):
        for word, said in (("domain", "Domains"), ("case study", "Case studies"), ("process", "Processes"),
                           ("person", "People"), ("note", "Other notes"), ("mail", "Mail")):
            self.assertEqual(said, status.plural(word))


# GRAPH_JS with its legend's buttons, the find box and the count beside it
# real enough to press: each step clicks a kind, types, presses a key, clicks
# the count or picks a place, and says which notes the graph draws, which
# kinds are pressed, what the count says, the card open and what is stored.
FILTER_HARNESS = r"""
const vm = require("vm");
const [js, data, chips, saved, steps] = JSON.parse(process.argv[1]);
const any = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => 0 : k === "length" ? 0 : any,
                                        apply: () => any, construct: () => any });
const store = Object.assign({}, saved || {});
const attr = function (k, v) { this.attrs[k] = String(v); };
const kinds = chips.map(([k, said]) => ({ dataset: { k: String(k) }, textContent: said, hidden: false, attrs: {}, setAttribute: attr,
                                          classList: { toggle: () => {} }, onclick: null }));
const on = {};
const box = { value: "", addEventListener: (t, fn) => { on[t] = fn; } };
const more = { hidden: true, textContent: "", onclick: null };
const pop = { hidden: true, innerHTML: "", addEventListener: () => {} };
const sel = { value: "", onchange: null, options: [], selectedIndex: 0, className: "",
              parentNode: { querySelectorAll: () => [], classList: { toggle: () => {} } } };
const byId = { "graph-data": { textContent: data }, gfind: box, gfmore: more, gpop: pop };
const ctx = { JSON, String, Array, Object, Math, Date, performance: { now: () => 0 },
              localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
              document: new Proxy({}, { get: (t, k) => k === "getElementById" ? (id) => byId[id] || any
                                                       : k === "querySelectorAll" ? (s) => s === ".glegend [data-k]" ? kinds : []
                                                       : k === "querySelector" ? (s) => s === ".gzsel" ? sel
                                                         : (s.match(/^\.glegend \[data-k="(\d+)"\]$/) || [])[1] ? kinds.filter((c) => s.indexOf('"' + c.dataset.k + '"') > 0)[0] : any
                                                       : any }),
              Panel: { esc: (s) => String(s), head: (o) => "<h4>" + o.n + "</h4>", acts: () => "" },
              requestAnimationFrame: () => 0, setTimeout: () => 0, addEventListener: () => {},
              matchMedia: () => ({ matches: true }), IntersectionObserver: any, ResizeObserver: any, MutationObserver: any,
              getComputedStyle: () => any, location: any, navigator: any, innerWidth: 800, innerHeight: 600, devicePixelRatio: 1 };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(js, ctx);
const G = ctx.window.GarrickGraph, nodes = JSON.parse(data).nodes;
const look = () => {
  const drawn = nodes.filter((n) => G.focus(n.u)).map((n) => n.N || n.n); G.focus(null);
  const h4 = !pop.hidden && (pop.innerHTML.match(/<h4>(.*?)<\/h4>/) || [])[1];
  return { place: G.place(), drawn: drawn.sort(), pressed: kinds.filter((c) => !c.hidden && c.attrs["aria-pressed"] === "true").map((c) => c.textContent),
           offered: kinds.filter((c) => !c.hidden).map((c) => c.textContent), more: more.hidden ? "" : more.textContent, card: h4 || null,
           box: box.value, store: Object.fromEntries(Object.entries(store).filter(([k]) => k.indexOf("garrick-graph-kinds-") === 0)) };
};
const out = [look()];
for (const [op, arg] of steps) {
  if (op === "click") kinds.filter((c) => c.textContent === arg)[0].onclick();
  else if (op === "type") { box.value = arg; on.input(); }
  else if (op === "key") on.keydown({ key: arg, preventDefault: () => {}, stopPropagation: () => {} });
  else if (op === "more") more.onclick();
  else if (op === "pick") { sel.value = arg; sel.onchange(); }
  out.push(look());
}
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestTheLegendFiltersAndTheBoxFinds(StatusCase):
    """#250: each kind in the legend shows or hides it, kept per place; the box finds a note by its name."""

    def setUp(self):
        super().setUp()
        k = self.root / "Wikis" / "Knowledge" / "wiki"
        write(k / "entities" / "fictus-cloud.md", "---\ntitle: Fictus Cloud\ntype: entity\n---\n")
        write(k / "entities" / "orvieto.md", "---\ntitle: Örviéto Labs\ntype: entity\n---\n")
        m = self.root / "Wikis" / "Meetings" / "wiki"
        for name in ("Freight", "Customs", "Ports"):
            write(m / "domains" / (name.lower() + ".md"), "---\ntitle: %s domain\ntype: domain\n---\n" % name)
        write(m / "people" / "jose-perez.md", "---\ntitle: José Pérez\ntype: person\n---\n")

    def run_js(self, *steps, saved=None):
        html = self.page()
        data = re.search(r'<script type="application/json" id="graph-data">(.*?)</script>', html, re.S).group(1)
        legend = html[html.index('class="legend glegend"'):]
        chips = [[int(k), said] for k, said in re.findall(r'data-k="(\d+)" aria-pressed="true"><i[^>]*></i>([^<]+)</button>', legend)]
        done = subprocess.run(["node", "-e", FILTER_HARNESS, json.dumps([status.GRAPH_JS, data, chips, saved or {}, [list(s) for s in steps]])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_a_kind_is_shown_or_hidden_and_kept_for_its_place(self):
        out = self.run_js(("pick", "Knowledge"), ("click", "Concepts"), ("pick", "Work"), ("pick", "Knowledge"),
                          saved={"garrick-graph-kinds-Knowledge": '["concept","entity"]'})
        self.assertEqual(["Concepts", "Entities"], out[1]["pressed"])
        self.assertEqual(["Concepts", "Entities", "Sources"], sorted(out[1]["offered"]))   # every kind the place has
        self.assertEqual(["Fictus Cloud", "resilience", "Örviéto Labs"], out[1]["drawn"])
        self.assertEqual(["Entities"], out[2]["pressed"])                        # entities without concepts
        self.assertEqual(["Fictus Cloud", "Örviéto Labs"], out[2]["drawn"])
        self.assertEqual({"garrick-graph-kinds-Knowledge": '["entity"]'}, out[2]["store"])
        self.assertEqual(["Entities"], out[4]["pressed"])                        # back on the place, as it was left
        out = self.run_js(("pick", "Knowledge"), ("click", "Sources"), saved={"garrick-graph-kinds-Knowledge": '["concept"]'})
        self.assertEqual(["Supply chains", "resilience"], out[2]["drawn"])     # concepts with their sources

    def test_a_place_opens_as_its_old_view_left_it(self):
        core = self.run_js(("pick", "Meetings"), saved={"garrick-graph-mode-Meetings": "core"})[1]
        self.assertEqual(["People"], core["pressed"])                           # its hubs
        self.assertEqual(["Dana Whitlock", "José Pérez"], core["drawn"])
        every = self.run_js(("pick", "Meetings"), saved={"garrick-graph-mode-Meetings": "all"})[1]
        self.assertIn("Domains", every["pressed"])                              # Everything: every kind, those from the pages too
        small = self.run_js(("pick", "Meetings"))[1]
        self.assertEqual(["Meetings", "People"], sorted(small["pressed"]))     # a small place: the model's kinds
        self.assertNotIn("Domains", small["pressed"])                           # a kind from the pages starts hidden
        self.assertIn("Domains", small["offered"])

    def test_the_box_finds_by_name_whatever_the_accents(self):
        out = self.run_js(("pick", "Meetings"), ("type", "j"), ("type", "jose"), ("key", "Enter"), ("type", "ports"),
                          ("more",), ("key", "Escape"), ("pick", "Knowledge"))
        self.assertEqual("", out[2]["more"])                                    # one letter finds nothing
        self.assertEqual("José Pérez", out[4]["card"])                          # Enter opens the first match
        self.assertEqual("1 more in Domains", out[5]["more"])                   # a match in a kind not shown
        self.assertIn("Domains", out[6]["pressed"])                             # and the count shows it
        self.assertIn("Ports domain", out[6]["drawn"])
        self.assertEqual("", out[6]["more"])
        self.assertEqual("", out[7]["box"])                                     # Escape clears
        out = self.run_js(("pick", "Knowledge"), ("type", "orvi"), ("key", "Enter"), ("type", "ORVIETO"), ("pick", "Work"))
        self.assertEqual("Örviéto Labs", out[3]["card"])
        self.assertEqual("", out[5]["box"])                                     # a change of place clears it

    def test_a_linked_note_not_drawn_brings_its_kind(self):
        self.assertIn("if(!ks[m.k]){ks[m.k]=1;keep()}", status.GRAPH_JS)
        self.assertIn("if(m.z!==zsel){if(!cardZone(m.z))held=true;show(m.z)}", status.GRAPH_JS)


# GRAPH_JS drawn on a canvas that records its names: a card of a given size,
# a place and the kinds a window stored. The graph settles and fits as it
# would on screen, and the last frame says each name drawn, where, in which
# font and how wide; and, for each step, what the legend and each node's
# colour look like, and what the window keeps.
CANVAS_HARNESS = r"""
const vm = require("vm");
const [js, data, saved, W, H, legend, steps] = JSON.parse(process.argv[1]);
const any = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => 0 : k === "length" ? 0 : any,
                                        apply: () => any, construct: () => any });
const store = Object.assign({}, saved || {});
let names = [], fills = [];
const g = { font: "", measureText: (t) => ({ width: t.length * (/12px/.test(g.font) ? 7 : 6) }),
            fillText: (t, x, y) => names.push([t, x, y, g.font, g.measureText(t).width]),
            clearRect: () => { names = []; fills = []; }, fill: () => fills.push(g.fillStyle) };
["setTransform", "beginPath", "moveTo", "lineTo", "stroke", "arc", "strokeText"].forEach((k) => { g[k] = () => {}; });
const rect = () => ({ left: 0, top: 0, width: W, height: H });
const wrap = { getBoundingClientRect: rect, querySelector: () => null };
const cv = { getContext: () => g, parentNode: wrap, getBoundingClientRect: rect, addEventListener: () => {}, dataset: {},
             classList: { add: () => {}, remove: () => {}, toggle: () => {} }, setPointerCapture: () => {} };
const sel = { value: "", onchange: null, options: [], selectedIndex: 0, className: "",
              parentNode: { querySelectorAll: () => [], classList: { toggle: () => {} } } };
const chip = (c) => Object.assign(c, { hidden: !!c.hidden, attrs: {}, cls: {}, dataset: c.dataset || {},
  setAttribute(k, v) { this.attrs[k] = String(v); }, classList: { toggle: (k, on) => { c.cls[k] = !!on; } } });
const kinds = (legend.kinds || []).map(([k, said]) => chip({ dataset: { k: String(k) }, textContent: said }));
const byId = { "graph-data": { textContent: data }, gcv: cv, gpop: { hidden: true, innerHTML: "", addEventListener: () => {} } };
let queue = [];
const ctx = { JSON, String, Array, Object, Math, Date, performance: { now: () => 0 },
              localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
                              removeItem: (k) => { delete store[k]; } },
              document: new Proxy({}, { get: (t, k) => k === "getElementById" ? (id) => id in byId ? byId[id] : any
                                                       : k === "querySelectorAll" ? (s) => s === ".glegend [data-k]" ? kinds : []
                                                       : k === "querySelector" ? (s) => s === ".gzsel" ? sel : any : any }),
              Panel: any, requestAnimationFrame: (fn) => queue.push(fn), setTimeout: () => 0, addEventListener: () => {},
              matchMedia: () => ({ matches: true }), ResizeObserver: any, MutationObserver: any,
              IntersectionObserver: function (cb) { this.observe = () => cb([{ isIntersecting: true }]); },
              getComputedStyle: () => ({ getPropertyValue: () => "#000" }), location: any, navigator: any, devicePixelRatio: 1 };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(js, ctx);
let t = 0;
const settle = () => { for (let i = 0; i < 4000 && queue.length; i++) { const q = queue; queue = []; q.forEach((fn) => fn(t += 16)); } };
const nodes = JSON.parse(data).nodes, G = ctx.window.GarrickGraph;
const look = () => { const drawn = nodes.filter((n) => G.focus(n.u)); G.focus(null); settle();
  return { names, fills: drawn.map((n, i) => [n.N || n.n, fills[i]]),
           kinds: kinds.filter((c) => !c.hidden).map((c) => c.textContent), store: Object.assign({}, store) }; };
settle();
const out = [look()];
for (const [op, arg] of steps || []) {
  if (op === "pick") { sel.value = arg; sel.onchange(); }
  out.push(look());
}
process.stdout.write(JSON.stringify(out));
"""


def overlaps(names):
    """The pairs of drawn names whose boxes cover each other, the box as names() measures it."""
    boxes = [(t, x, y, x + w, y + (14 if f.startswith("600") else 13)) for t, x, y, f, w in names]
    return [(a[0], b[0]) for i, a in enumerate(boxes) for b in boxes[i + 1:]
            if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]]


def run_canvas(html, saved=None, size=(900, 520), steps=()):
    data = graph_data_text(html)
    legend = {"kinds": [[int(k), said] for k, said in re.findall(r'data-k="(\d+)" aria-pressed="true"><i[^>]*></i>([^<]+)</button>', html)]}
    done = subprocess.run(["node", "-e", CANVAS_HARNESS, json.dumps([status.GRAPH_JS, data, saved or {}, size[0], size[1], legend,
                                                                    [list(s) for s in steps]])],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def graph_data_text(html):
    return re.search(r'<script type="application/json" id="graph-data">(.*?)</script>', html, re.S).group(1)


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestEveryKindDrawnIsNamed(StatusCase):
    """#252: a kind turned on in the legend is named at any zoom, after projects and hubs, the most linked first."""

    def setUp(self):
        super().setUp()
        m = self.root / "Wikis" / "Meetings" / "wiki"
        self.entities = ["Entity %02d" % i for i in range(40)]
        for i, name in enumerate(self.entities):
            links = " ".join("[[e%02d]]" % j for j in range(i + 1, min(40, i + 1 + (6 if i < 5 else 1))))
            write(m / "entities" / ("e%02d.md" % i), "---\ntitle: %s\ntype: entity\n---\n\n%s\n" % (name, links))
        for i, name in enumerate(("Ada Moss", "Bo Lind", "Cy Hart")):
            write(m / "people" / ("p%d.md" % i), "---\ntitle: %s\ntype: person\n---\n\nKnows [[e%02d]] and [[e%02d]].\n" % (name, i, i + 10))

    def test_a_kind_turned_on_is_named_without_zooming_in(self):
        out = run_canvas(self.page(), {"garrick-graph-place": "Meetings", "garrick-graph-kinds-Meetings": '["entity"]'})[0]
        said = [n[0] for n in out["names"]]
        self.assertGreater(len(set(said) & set(self.entities)), 10, said)     # where there is room, at the scale that fits them all
        self.assertEqual([], overlaps(out["names"]))

    def test_hubs_first_then_the_most_linked(self):
        html = self.page()
        out = run_canvas(html, {"garrick-graph-place": "Meetings", "garrick-graph-kinds-Meetings": '["person","entity"]'},
                         size=(640, 360))[0]
        said = [n[0] for n in reversed(out["names"])]                          # drawn least wanted first
        people = [n for n in said if n not in self.entities]
        self.assertTrue({"Ada Moss", "Bo Lind", "Cy Hart"} <= set(people), said)  # people keep their priority
        self.assertEqual(people, said[:len(people)])
        ents = [n for n in said if n in self.entities]
        self.assertTrue(ents, said)                                              # entities fill the room left
        data = graph_data(html)
        on = {i for i, n in enumerate(data["nodes"]) if n["z"] == "Meetings" and n["n"] in self.entities + people}
        deg = {}
        for a, b in data["edges"]:
            if a in on and b in on:
                for i in (a, b):
                    deg[data["nodes"][i]["n"]] = deg.get(data["nodes"][i]["n"], 0) + 1
        self.assertEqual("Entity 04", max(self.entities, key=lambda n: (deg.get(n, 0), -self.entities.index(n))))
        self.assertEqual(sorted(ents, key=lambda n: (-deg.get(n, 0), self.entities.index(n))), ents)   # the most linked placed first
        self.assertEqual([], overlaps(out["names"]))

    def test_a_note_in_a_project_is_named_and_its_card_keeps_what_it_resumes(self):
        write(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Call notes.md", "# Call notes\n")
        html = self.page(launchers=("finder", "claude"))
        self.assertEqual("Pricing", next(n for n in graph_data(html)["nodes"] if n["n"] == "Call notes")["lw"])
        out = run_canvas(html, {"garrick-graph-place": "Work", "garrick-graph-kinds-Work": '["project","thread","note"]'})[0]
        self.assertIn("Call notes", [n[0] for n in out["names"]])
        self.assertTrue(all(isinstance(n[1], (int, float)) and isinstance(n[4], (int, float)) for n in out["names"]), out["names"])
        self.assertNotIn("n.lw||(n.lw={})", status.GRAPH_JS)                   # a name's widths kept apart from it (tw)
        self.assertIn("lw=n.tw||(n.tw={})", status.GRAPH_JS)

    def test_names_stay_cheap_on_a_crowded_graph(self):
        # Measured in Node on 2,000 notes drawn: 6.6 ms a frame trying every name, 2.3 ms trying BIG of the rest.
        self.assertNotIn("scale>1.4", status.GRAPH_JS)
        self.assertIn("||e[0]===4&&++tried>BIG){n.lp=-1;return}", status.GRAPH_JS)     # a note off the card is not counted


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestExploreNeedsNoObsidian(StatusCase):
    """#292: every place is coloured by its kinds, with or without Obsidian; Settings › Explore has no colour switch."""

    def setUp(self):
        super().setUp()
        TestVaultGraph.obsidian(self, self.root / "Zones" / "Work", groups=[("[type:project]", 0xFF0000), ("path:Birch Entry", 0x00FF00)])
        self.html = self.page()
        self.data = graph_data(self.html)

    def test_a_zone_in_a_vault_takes_its_kinds_colours(self):
        kind = {n["n"]: self.data["colors"][n["k"]] for n in self.data["nodes"] if n["z"] == "Work"}
        for saved in ({}, {"garrick-graph-obsidian": "1"}):                     # what the old switch saved is ignored
            out = run_canvas(self.html, dict(saved, **{"garrick-graph-place": "Work"}))[0]
            self.assertTrue(out["fills"])
            self.assertEqual({n: kind[n] for n, _ in out["fills"]}, dict(out["fills"]))
            self.assertTrue(out["kinds"])
            self.assertNotIn("garrick-graph-obsidian", out["store"])           # and dropped from the window
        legend = self.html[self.html.index('class="legend glegend"'):self.html.index('id="gsum"')]
        self.assertNotIn("data-g", legend)
        first = legend[:legend.index("</div>")]                                # one row: kinds, then the two states
        self.assertLess(first.index("</button>"), first.index("Next action late"))
        self.assertLess(first.index("Next action late"), first.index("Parked"))

    def test_a_wiki_looks_as_it_did(self):
        TestVaultGraph.obsidian(self, self.root, groups=[("[type:meeting]", 0x123456)])
        out = run_canvas(self.page(), {"garrick-graph-place": "Meetings"})[0]
        kind = {n.get("N", n["n"]): self.data["colors"][n["k"]] for n in self.data["nodes"] if n["z"] == "Meetings"}
        self.assertTrue(out["fills"])
        self.assertEqual({n: kind[n] for n, _ in out["fills"]}, dict(out["fills"]))

    def test_settings_explore_has_only_follow(self):
        explore = self.html[self.html.index('id="follow-settings"'):]
        explore = explore[:explore.index("</section>")]
        self.assertIn('<input type="checkbox" id="graph-follow" checked>', explore)
        self.assertEqual(1, explore.count('type="checkbox"'))
        self.assertNotIn("Obsidian", explore)
        self.assertNotIn("graph-obsidian", self.html.replace("localStorage.removeItem('garrick-graph-obsidian')", ""))
        self.assertNotIn("vc&&", status.GRAPH_JS)


# FOLLOW_JS against a page status.py wrote, with the zones' boxes made up
# rather than laid out, a clock that moves only when told, and a graph that
# records what it is asked to follow: the steps scroll, hover, click, wait or
# flip the switch in Settings, and the graph says which zones it followed.
FOLLOW_HARNESS = r"""
const vm = require("vm");
const [html, js, place, boxes, steps, saved] = JSON.parse(process.argv[1]);
""" + DOM + r"""
const doc = new El("#document");
parse(html, doc);
let geo = boxes, y = 0, now = 0, timers = [];
const H = 600, zero = { left: 0, top: 0, bottom: 0, width: 0, height: 0 };
El.prototype.getBoundingClientRect = function () {
  const b = this.localName === "details" && geo[this.getAttribute("data-zone")];
  return b ? { left: b[0], width: 300, top: b[1] - y, bottom: b[2] - y, height: b[2] - b[1] } : zero;
};
const on = {}, listen = (t, fn) => { (on[t] = on[t] || []).push(fn); };
const fire = (t, target) => (on[t] || []).forEach((fn) => fn({ target }));
const store = Object.assign({}, saved || {});
let cur = place;
const followed = [];
const ctx = { JSON, String, Array, Object, Math, innerHeight: H,
  setTimeout: (fn, ms) => { timers.push({ at: now + ms, fn }); return timers.length; },
  clearTimeout: (id) => { if (id && timers[id - 1]) timers[id - 1].fn = null; },
  localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
  document: { querySelectorAll: (s) => doc.querySelectorAll(s), querySelector: (s) => doc.querySelector(s),
              getElementById: (id) => doc.querySelectorAll("#" + id)[0] || null, addEventListener: listen },
  addEventListener: listen };
ctx.window = ctx;
ctx.GarrickGraph = { place: () => cur, follow: (z) => { if (z === cur) return false; cur = z; followed.push(z); return true; } };
vm.createContext(ctx);
vm.runInContext(js, ctx);
const zone = (z) => doc.querySelectorAll(".tview .zones>details.zone").filter((d) => d.getAttribute("data-zone") === z)[0];
const cb = doc.querySelectorAll("#graph-follow")[0];
for (const [op, arg] of steps) {
  if (op === "scroll") { y = arg; fire("scroll", doc); }
  else if (op === "wait") { now += arg; timers.forEach((t) => { if (t.fn && t.at <= now) { const f = t.fn; t.fn = null; f(); } }); }
  else if (op === "hover") fire("mouseover", arg ? zone(arg).querySelector("summary") : doc.querySelector("header") || doc);
  else if (op === "open") fire("click", zone(arg).querySelector(".tunit a"));
  else if (op === "switch") { cb.checked = arg; cb.onchange(); }
}
process.stdout.write(JSON.stringify({ followed, place: cur, checked: cb ? cb.checked : null, store,
  order: doc.querySelectorAll(".tview .zones>details.zone").map((d) => d.getAttribute("data-zone")) }));
"""


# GRAPH_JS with the Threads card's zones and the place drop-down real enough
# to read: each step follows a zone or picks one, and says what the graph
# shows, what the window stored and the order of the card's zones.
PLACE_HARNESS = r"""
const vm = require("vm");
const [js, data, html, saved, steps] = JSON.parse(process.argv[1]);
""" + DOM + r"""
const doc = new El("#document");
parse(html, doc);
const any = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => 0 : k === "length" ? 0 : any,
                                        apply: () => any, construct: () => any });
const sel = { value: "", onchange: null, options: [], selectedIndex: 0, className: "",
              parentNode: { querySelectorAll: () => [], classList: { toggle: () => {} } } };
const card = (s) => s.indexOf(".tview") === 0;
const store = Object.assign({}, saved || {});
const ctx = { JSON, String, Array, Object, Math, Date,
              localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
              document: new Proxy({}, { get: (t, k) => k === "getElementById" ? (id) => id === "graph-data" ? { textContent: data } : any
                                                       : k === "querySelectorAll" ? (s) => card(s) ? doc.querySelectorAll(s) : []
                                                       : k === "querySelector" ? (s) => s === ".gzsel" ? sel : card(s) ? doc.querySelector(s) : any : any }),
              Panel: any, requestAnimationFrame: () => 0, setTimeout: () => 0, addEventListener: () => {},
              matchMedia: () => ({ matches: true }), IntersectionObserver: any, ResizeObserver: any, MutationObserver: any,
              getComputedStyle: () => any, location: any, navigator: any, innerWidth: 800, innerHeight: 600, devicePixelRatio: 1 };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(js, ctx);
const G = ctx.window.GarrickGraph;
const look = (ret) => ({ ret, place: G.place(), shows: sel.value, stored: store["garrick-graph-place"] || null,
  order: doc.querySelectorAll(".tview .zones>details.zone").map((d) => d.getAttribute("data-zone")) });
const out = [look(null)];
for (const [op, z] of steps) {
  if (op === "follow") out.push(look(G.follow(z)));
  else { sel.value = z; sel.onchange(); out.push(look(null)); }
}
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestExploreFollowsTheZoneInView(StatusCase):
    """#142: Explore follows the zone you are reading on the Threads card,
    without storing it or reordering the card."""

    def setUp(self):
        super().setUp()
        zones = self.root / "Zones"
        studio = zones / "Studio"
        (studio / ".git").mkdir(parents=True)
        write(studio / "AGENTS.md", "# Studio zone\n")
        write(studio / "Todo.md", "# Studio: open actions\n\n## Inbox\n\n## Done\n")
        write(studio / "Kiln Build" / "Kiln Build.md", project_hub("Studio", "Kiln Build", "", ["Glazes"]))
        write(studio / "Kiln Build" / "Threads" / "Glazes" / "Glazes.md", thread_note("Kiln Build", "Glazes", ""))
        garden = zones / "Personal" / "Garden Plan"
        write(garden / "Garden Plan.md", project_hub("Personal", "Garden Plan", "", ["Beds"]))
        write(garden / "Threads" / "Beds" / "Beds.md", thread_note("Garden Plan", "Beds", ""))

    # Three zones, one under another, each 700 pixels tall in a window 600 tall.
    STACKED = {"Personal": [0, 0, 700], "Studio": [0, 700, 1400], "Work": [0, 1400, 2100]}
    SIDE = {"Personal": [0, 0, 500], "Studio": [320, 0, 500], "Work": [640, 0, 500]}

    def follow(self, boxes, *steps, place="Personal", saved=None, html=None):
        html = html or self.page()
        done = subprocess.run(["node", "-e", FOLLOW_HARNESS, json.dumps([html, status.FOLLOW_JS, place, boxes,
                                                                          [list(s) for s in steps], saved])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def places(self, *steps, saved=None):
        html = self.page()
        data = re.search(r'<script type="application/json" id="graph-data">(.*?)</script>', html, re.S).group(1)
        done = subprocess.run(["node", "-e", PLACE_HARNESS, json.dumps([status.GRAPH_JS, data, html, saved, [list(s) for s in steps]])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_scrolling_into_the_next_zone_switches_explore_once_it_holds_the_view(self):
        out = self.follow(self.STACKED, ("scroll", 650), ("wait", 299))
        self.assertEqual([], out["followed"])                                   # not yet
        out = self.follow(self.STACKED, ("scroll", 650), ("wait", 300))
        self.assertEqual(["Studio"], out["followed"])                           # within half a second
        self.assertEqual(["Personal", "Studio", "Work"], out["order"])          # and the card's order stands
        self.assertNotIn("garrick-graph-place", out["store"])                   # nor is it stored
        # Reading on down through the zone keeps the wait it started, rather than starting it again.
        out = self.follow(self.STACKED, ("scroll", 650), ("wait", 150), ("scroll", 720), ("wait", 150))
        self.assertEqual(["Studio"], out["followed"])

    def test_a_zone_scrolled_quickly_past_is_not_followed(self):
        out = self.follow(self.STACKED, ("scroll", 650), ("wait", 120), ("scroll", 1350), ("wait", 120), ("wait", 300))
        self.assertEqual(["Work"], out["followed"])                             # Studio went by
        out = self.follow(self.STACKED, ("scroll", 650), ("wait", 120), ("scroll", 0), ("wait", 1000))
        self.assertEqual([], out["followed"])                                   # back where it started: nothing changes
        out = self.follow(self.STACKED, ("wait", 1000), ("scroll", 40), ("wait", 1000), place="Meetings")
        self.assertEqual([], out["followed"])                                   # the zone in view as the page opens is not a change

    def test_side_by_side_a_hover_or_an_open_sets_it(self):
        out = self.follow(self.SIDE, ("scroll", 200), ("wait", 1000))
        self.assertEqual([], out["followed"])                                   # every zone is in view: scrolling changes nothing
        out = self.follow(self.SIDE, ("hover", "Studio"), ("wait", 300))
        self.assertEqual(["Studio"], out["followed"])
        out = self.follow(self.SIDE, ("hover", "Studio"), ("wait", 100), ("hover", None), ("wait", 1000))
        self.assertEqual([], out["followed"])                                   # passing over a column is not resting on it
        out = self.follow(self.SIDE, ("open", "Work"))
        self.assertEqual(["Work"], out["followed"])                             # opening a project or thread: at once
        self.assertEqual(["Personal", "Studio", "Work"], out["order"])

    def test_switched_off_nothing_changes(self):
        off = {"garrick-graph-follow": "0"}
        for boxes, steps in ((self.STACKED, [("scroll", 650), ("wait", 1000)]),
                             (self.SIDE, [("hover", "Studio"), ("wait", 1000), ("open", "Work")])):
            out = self.follow(boxes, *steps, saved=off)
            self.assertEqual([], out["followed"])
            self.assertFalse(out["checked"])                                    # Settings shows it off
        out = self.follow(self.STACKED, ("scroll", 650), ("wait", 100), ("switch", False), ("wait", 1000), ("scroll", 1350), ("wait", 1000))
        self.assertEqual([], out["followed"])                                   # switching it off drops a wait under way
        self.assertEqual("0", out["store"]["garrick-graph-follow"])
        out = self.follow(self.STACKED, ("switch", True), ("scroll", 650), ("wait", 300), saved=off)
        self.assertEqual(["Studio"], out["followed"])

    def test_on_by_default_and_only_with_the_graph(self):
        html = self.page()
        self.assertIn('<section class="setsec" id="follow-settings"><h3>Explore', html)
        self.assertIn('<input type="checkbox" id="graph-follow" checked> <span>Follow the zone in view', html)
        self.assertIn(status.FOLLOW_JS, html)
        bare = self.page(show_graph=False)
        self.assertNotIn("graph-follow", bare)
        self.assertNotIn(status.FOLLOW_JS, bare)

    def test_a_followed_zone_is_shown_not_stored_and_the_pick_still_orders_the_card(self):
        out = self.places(("follow", "Personal"), ("pick", "Studio"), ("follow", "Work"))
        self.assertEqual({"ret": None, "place": "Work", "shows": "Work", "stored": None,
                          "order": ["Work", "Personal", "Studio"]}, out[0])     # as #72 leaves it
        self.assertEqual({"ret": True, "place": "Personal", "shows": "Personal", "stored": None,
                          "order": ["Work", "Personal", "Studio"]}, out[1])     # shown in the drop-down, not stored, card untouched
        self.assertEqual({"ret": None, "place": "Studio", "shows": "Studio", "stored": "Studio",
                          "order": ["Studio", "Personal", "Work"]}, out[2])     # a pick is stored and leads the card
        self.assertEqual({"ret": True, "place": "Work", "shows": "Work", "stored": "Studio",
                          "order": ["Studio", "Personal", "Work"]}, out[3])
        reload = self.places(saved={"garrick-graph-place": "Studio"})[0]
        self.assertEqual(("Studio", ["Studio", "Personal", "Work"]), (reload["place"], reload["order"]))   # the pick, not the zone last followed

    def test_a_wiki_pauses_following_until_the_page_reloads(self):
        out = self.places(("pick", "Meetings"), ("follow", "Studio"), ("pick", "Personal"), ("follow", "Studio"))
        self.assertEqual((False, "Meetings"), (out[2]["ret"], out[2]["place"]))
        self.assertEqual((False, "Personal"), (out[4]["ret"], out[4]["place"]))
        again = self.places(("follow", "Studio"), saved={"garrick-graph-place": "Meetings"})
        self.assertEqual((True, "Studio", "Meetings"), (again[1]["ret"], again[1]["place"], again[1]["stored"]))

    def test_a_stored_all_or_a_place_gone_opens_on_work(self):
        for saved in ("*", "Gone"):                                             # All went in #250
            with self.subTest(saved=saved):
                out = self.places(saved={"garrick-graph-place": saved})[0]
                self.assertEqual(("Work", "Work", saved), (out["place"], out["shows"], out["stored"]))


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


class TestWhereTheChoicesLive(StatusCase):
    """Each zone's colour and icon, and Opening a thread, are committed with
    the workspace in System/garrick-settings.json, and every reader reads them
    through garrick_lib's accessor (#81)."""

    SETTINGS = Path("System") / "garrick-settings.json"

    def build_main(self):
        out = self.jobs / "page.html"
        with contextlib.redirect_stdout(io.StringIO()):
            status.main(["--workspace", str(self.root), "--out", str(out), "--no-obsidian"])
        return out.read_text(encoding="utf-8")

    def test_the_file_the_page_names_is_the_accessors(self):
        prefs = status.prefs()
        self.assertEqual(prefs.lib(self.root).PREFERENCES_FILE, prefs.FILE)
        self.assertEqual("System/garrick-settings.json", prefs.FILE)
        html = self.page()
        self.assertIn("<code>System/garrick-settings.json</code>", html)          # Settings says where they are kept
        self.assertNotIn("status-settings.json", html)

    def test_every_reader_reads_the_same_file(self):
        """The page, the settings request, the Mac app and the cmux desk: the
        generated file is nobody's path any more."""
        pa = REPO / "extras" / "status" / "page_action.py"
        swift = (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")
        self.assertIn('appendingPathComponent("System/garrick-settings.json")', swift)
        for path in (REPO / "extras" / "status" / "status.py", pa, REPO / "extras" / "status" / "ask.py",
                     REPO / "extras" / "cmux" / "desk.py"):
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("status-settings.json", text)
                self.assertNotIn("System/generated/status-settings", text)
        self.assertNotIn("status-settings.json", swift)

    def test_a_rebuild_copies_an_older_garricks_choices_across(self):
        write(self.root / "System" / "generated" / "status-settings.json",
              json.dumps({"zones": {"Work": {"color": "Teal", "icon": "briefcase"}},
                          "launchers": ["note", "claude"], "default": "claude"}))
        self.assertIn('<h3 class="zc zc-teal">', self.build_main())          # the page shows them either way
        kept = json.loads((self.root / self.SETTINGS).read_text(encoding="utf-8"))
        self.assertEqual({"Work": {"color": "Teal", "icon": "briefcase"}}, kept["zones"])
        self.assertEqual(["note", "claude"], kept["launchers"])
        # Deleting the generated folder and rebuilding keeps every choice.
        shutil.rmtree(str(self.root / "System" / "generated"))
        html = self.build_main()
        self.assertIn('<h3 class="zc zc-teal">', html)
        self.assertEqual({"launchers": ["note", "claude"], "default": "claude"},
                         json.loads(re.search(r'id="launch-settings">(.*?)</script>', html, re.S).group(1)))


# LAYOUT_JS against a page status.py wrote, with whatever a window had saved
# under garrick-status-layout: what each slot then holds, in order, and which
# cards are hidden.
LAYOUT_HARNESS = r"""
const vm = require("vm");
const [html, js, saved] = JSON.parse(process.argv[1]);
""" + DOM + r"""
const doc = new El("#document");
parse(html, doc);
const store = {};
if (saved !== null) store["garrick-status-layout"] = JSON.stringify(saved);
const ctx = { JSON, String, Array, Object, setTimeout: () => 0, clearTimeout: () => {},
  localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
                  removeItem: (k) => { delete store[k]; }, get length() { return Object.keys(store).length; },
                  key: (i) => Object.keys(store)[i] },
  document: { querySelectorAll: (s) => doc.querySelectorAll(s), querySelector: (s) => doc.querySelector(s),
              createElement: (t) => new El(t), getElementById: (id) => doc.querySelectorAll("#" + id)[0] || null,
              addEventListener: () => {} } };
ctx.window = {};
vm.createContext(ctx);
vm.runInContext(js, ctx);
const slots = {};
doc.querySelectorAll("[data-slot]").forEach((s) => {
  slots[s.getAttribute("data-slot")] = s.children.filter((c) => c.classList.contains("card")).map((c) => c.id);
});
process.stdout.write(JSON.stringify({ slots, hidden: doc.querySelectorAll("[data-slot]>.card[id]")
  .filter((c) => c.hidden).map((c) => c.id), saved: store["garrick-status-layout"] || null }));
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestASavedLayoutSurvivesANewDefault(StatusCase):
    """#102: the order a build writes is a default. A window that has chosen a
    layout keeps every card where it put it; *Reset view* is what adopts the
    new order."""

    def run_js(self, saved, html=None):
        import subprocess
        html = html if html is not None else self.page()
        done = subprocess.run(["node", "-e", LAYOUT_HARNESS, json.dumps([html, status.LAYOUT_JS, saved])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    # What a window running 0.27.0 could have saved: the old default, with the
    # graph and the threads at the top, and two cards moved by hand.
    OLD = {"v": 2, "c": {"top": ["graph", "threads"], "left": ["todo"], "right": ["inboxes"], "bottom": [],
                         "status-left": ["checks", "repos"], "status-right": ["wikis"], "status-bottom": []}, "h": []}

    # What a window running 0.31.0 saved after its user moved Inboxes to the
    # left and hid Waiting on you: the four cards #143 took away among the rest.
    BEFORE_143 = {"v": 2, "c": {"top": ["recent", "due"], "left": ["thought", "inboxes", "todo"], "right": ["waiting"],
                                "bottom": ["threads", "graph"], "status-left": ["checks", "repos"],
                                "status-right": ["wikis"], "status-bottom": []}, "h": ["waiting"]}

    def test_a_window_with_nothing_saved_takes_the_new_order(self):
        out = self.run_js(None)
        self.assertEqual(["threads"], out["slots"]["top"])          # #143: Threads leads
        self.assertEqual(["todo"], out["slots"]["left"])
        self.assertEqual(["inboxes"], out["slots"]["right"])
        self.assertEqual(["graph"], out["slots"]["bottom"])
        self.assertEqual([], out["hidden"])
        self.assertIsNone(out["saved"])                     # and nothing is written until something is moved

    def test_a_saved_layout_loses_only_the_cards_that_are_gone(self):
        out = self.run_js(self.BEFORE_143)
        self.assertEqual([], out["slots"]["top"])                       # Recent work and Due and overdue go
        self.assertEqual(["inboxes", "todo"], out["slots"]["left"])     # A thought goes; Inboxes stays where it was dragged
        self.assertEqual([], out["slots"]["right"])                     # Waiting on you goes, hidden or not
        self.assertEqual(["threads", "graph"], out["slots"]["bottom"])  # Threads stays where this window put it
        self.assertEqual(["checks", "repos"], out["slots"]["status-left"])
        self.assertEqual(["wikis"], out["slots"]["status-right"])
        self.assertEqual([], out["hidden"])                             # and Settings lists no hidden card
        self.assertEqual(self.BEFORE_143, json.loads(out["saved"]))    # nothing rewritten just for loading

    def test_a_saved_layout_keeps_every_card_where_it_was_put(self):
        moved = json.loads(json.dumps(self.OLD))
        moved["c"]["left"] = ["inboxes", "todo"]            # the user dragged Inboxes over, and hid Wikis
        moved["c"]["right"] = []
        moved["c"]["status-right"] = []
        moved["c"]["status-bottom"] = ["wikis"]
        moved["h"] = ["wikis"]
        out = self.run_js(moved)
        self.assertEqual(["inboxes", "todo"], out["slots"]["left"])    # Inboxes stays where it was dragged
        self.assertEqual([], out["slots"]["right"])
        self.assertEqual(["wikis"], out["slots"]["status-bottom"])
        self.assertEqual(["wikis"], out["hidden"])          # still hidden, and still where it was put
        self.assertEqual(["graph", "threads"], out["slots"]["top"])

    def test_a_card_the_layout_never_named_keeps_the_place_the_build_gave_it(self):
        out = self.run_js({"v": 2, "c": {"top": [], "left": ["inboxes"], "right": [], "bottom": ["threads"]}, "h": []})
        self.assertEqual(["todo", "inboxes"], out["slots"]["left"])     # Todo, unnamed, ahead of what was put back
        self.assertEqual(["graph", "threads"], out["slots"]["bottom"])

    def test_a_layout_naming_a_card_that_is_gone_is_read_without_harm(self):
        out = self.run_js({"v": 2, "c": {"top": ["ghost", "threads"]}, "h": ["ghost"]})
        self.assertEqual(["threads"], out["slots"]["top"])
        self.assertEqual([], out["hidden"])

    def test_an_older_layout_than_the_one_in_use_is_not_replayed(self):
        out = self.run_js({"v": 1, "c": {"top": ["todo"]}, "h": ["threads"]})
        self.assertEqual(["threads"], out["slots"]["top"])     # v1 is ignored, as it always was
        self.assertEqual([], out["hidden"])
        self.assertIn("{v:2,c:c,", status.LAYOUT_JS)                 # and v2 is still what save() writes
        self.assertIn("if(L&&L.v===2)", status.LAYOUT_JS)

    def test_reset_view_is_what_adopts_a_new_order(self):
        self.assertIn("var r=document.getElementById('reset-view');", status.LAYOUT_JS)
        self.assertIn("if(k.indexOf('garrick-')===0&&k!=='garrick-status-theme'&&k!=='garrick-launchers')ks.push(k)",
                      status.LAYOUT_JS)                              # the layout goes with the window's own storage
        self.assertIn("in the order this Garrick builds", self.page())


# A script of the page against a page status.py wrote, with what a window had
# kept under its own keys: then each button's onclick in turn, by id or by
# data-to, and what the page shows afterwards.
PAGE_HARNESS = r"""
const vm = require("vm");
const [html, js, kept, clicks] = JSON.parse(process.argv[1]);
""" + DOM + r"""
const doc = new El("#document");
parse(html, doc);
const store = Object.assign({}, kept), said = [], copied = [];
const ctx = { JSON, String, Array, Object, Promise, setTimeout: () => 0, clearTimeout: () => {},
  localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
                  removeItem: (k) => { delete store[k]; } },
  document: { querySelectorAll: (s) => doc.querySelectorAll(s), querySelector: (s) => doc.querySelector(s),
              createElement: (t) => new El(t), getElementById: (id) => doc.querySelectorAll("#" + id)[0] || null,
              addEventListener: () => {} } };
ctx.window = { GarrickCopy: (t) => { copied.push(t); return Promise.resolve(); }, GarrickSay: (t) => { said.push(t); } };
ctx.GarrickCopy = ctx.window.GarrickCopy;
vm.createContext(ctx);
vm.runInContext(js, ctx);
(async () => {
  for (const c of clicks) {
    const b = c.startsWith("to:") ? doc.querySelector('button[data-to="' + c.slice(3) + '"]') : doc.querySelectorAll("#" + c)[0];
    b.onclick();
    await new Promise((r) => setImmediate(r));
  }
  const names = (sel) => doc.querySelectorAll(sel).map((r) => JSON.parse(r.getAttribute("data-card")).n);
  const box = doc.querySelectorAll("#thought-left")[0];
  const gsum = doc.querySelector(".tview .gsum");
  process.stdout.write(JSON.stringify({ store, said, copied,
    work: names("#zone-work>.tunit>.thread"), acme: names("#sub-work-acme-review>.thread"),
    on: doc.querySelectorAll(".torder button").filter((b) => b.classList.contains("on")).map((b) => b.getAttribute("data-to")),
    gsum: gsum && gsum.textContent,
    left: box ? { hidden: box.hidden, text: doc.querySelectorAll("#thought-text")[0].textContent } : null }));
})();
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestThreadsByNameOrRecent(StatusCase):
    """#143: the Threads card lists each zone's projects and threads by name,
    or most recently touched first, and the window remembers which."""

    def setUp(self):
        super().setUp()
        acme = self.root / "Zones" / "Work" / "Acme Review" / "Threads"
        for name, day in (("Renewal", "2026-03-12"), ("Zebra", "2026-03-05")):
            write(acme / name / (name + ".md"),
                  thread_note("Acme Review", name).replace("updated: 2026-03-01", "updated: " + day))
        sizing = self.root / "Zones" / "Work" / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md"
        sizing.write_text(sizing.read_text(encoding="utf-8").replace("updated: 2026-03-01", "updated: 2026-03-20"),
                          encoding="utf-8")

    def run_js(self, kept=None, clicks=()):
        import subprocess
        html = self.page(show_graph=False)
        done = subprocess.run(["node", "-e", PAGE_HARNESS, json.dumps([html, status.TVIEW_JS, kept or {}, list(clicks)])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_by_name_is_the_default(self):
        out = self.run_js()
        self.assertEqual(["Acme Review", "Birch Entry"], out["work"])
        self.assertEqual(["Pricing", "Renewal", "Zebra"], out["acme"])
        self.assertEqual(["name"], out["on"])
        self.assertIn("· by name ·", out["gsum"])
        self.assertNotIn("garrick-threads-order", out["store"])        # nothing written until a choice is made

    def test_recent_lists_the_most_recently_touched_first_and_is_remembered(self):
        out = self.run_js(clicks=["to:recent"])
        self.assertEqual(["Birch Entry", "Acme Review"], out["work"])   # 20 March, then Acme's newest, 12 March
        self.assertEqual(["Renewal", "Zebra", "Pricing"], out["acme"])
        self.assertEqual(["recent"], out["on"])
        self.assertIn("· most recently touched first ·", out["gsum"])
        self.assertEqual("recent", out["store"]["garrick-threads-order"])
        again = self.run_js(kept=out["store"])                          # the next load keeps it
        self.assertEqual(["Birch Entry", "Acme Review"], again["work"])
        self.assertEqual(["Renewal", "Zebra", "Pricing"], again["acme"])
        self.assertEqual(["recent"], again["on"])
        back = self.run_js(kept=out["store"], clicks=["to:name"])
        self.assertEqual(["Acme Review", "Birch Entry"], back["work"])
        self.assertEqual(["Pricing", "Renewal", "Zebra"], back["acme"])
        self.assertIn("· by name ·", back["gsum"])
        self.assertEqual("name", back["store"]["garrick-threads-order"])

    def test_an_unknown_choice_is_ignored(self):
        out = self.run_js(kept={"garrick-threads-order": "loudest"})
        self.assertEqual(["Acme Review", "Birch Entry"], out["work"])
        self.assertEqual(["name"], out["on"])

    def test_reset_view_forgets_the_choice(self):
        self.assertIn("if(k.indexOf('garrick-')===0&&k!=='garrick-status-theme'&&k!=='garrick-launchers')ks.push(k)",
                      status.LAYOUT_JS)                                 # every garrick- key but those two goes
        self.assertIn("st.set('garrick-threads-order',o)", status.TVIEW_JS)


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestAThoughtLeftBehind(StatusCase):
    """#143 took the A thought card away. A browser that still holds what was
    typed into it shows that text once, offering Copy, so nobody loses it; a
    new browser shows nothing."""

    TEXT = "Ask Birch & Co about the <second> site\nand the dates"

    def run_js(self, kept=None, clicks=()):
        import subprocess
        html = self.page(show_graph=False)
        done = subprocess.run(["node", "-e", PAGE_HARNESS, json.dumps([html, status.HOME_JS, kept or {}, list(clicks)])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout)

    def test_a_new_browser_has_no_card_and_no_message(self):
        html = self.page()
        self.assertNotIn('id="thought"', html)
        self.assertNotIn("<textarea", html)
        out = self.run_js()
        self.assertEqual({"hidden": True, "text": ""}, out["left"])
        self.assertEqual({}, out["store"])

    def test_a_kept_thought_is_shown_with_copy(self):
        out = self.run_js(kept={"garrick-thought": self.TEXT})
        self.assertEqual({"hidden": False, "text": self.TEXT}, out["left"])   # as text, never as markup
        self.assertEqual(self.TEXT, out["store"]["garrick-thought"])          # kept until it is copied or closed
        html = self.page()
        tab = html[html.index('id="tab-overview"'):]
        self.assertLess(tab.index('id="thought-left"'), tab.index('data-slot="top"'))   # above the cards
        self.assertIn('<button class="act" type="button" id="thought-copy">Copy</button>', tab)

    def test_copy_copies_it_and_it_is_gone_from_the_browser(self):
        out = self.run_js(kept={"garrick-thought": self.TEXT}, clicks=["thought-copy"])
        self.assertEqual([self.TEXT], out["copied"])
        self.assertNotIn("garrick-thought", out["store"])
        self.assertEqual(["Copied your thought. It is gone from this browser."], out["said"])
        self.assertFalse(out["left"]["hidden"])                               # still on screen until this page goes
        later = self.run_js(kept=out["store"])
        self.assertTrue(later["left"]["hidden"])                              # once

    def test_close_lets_it_go(self):
        out = self.run_js(kept={"garrick-thought": self.TEXT}, clicks=["thought-close"])
        self.assertTrue(out["left"]["hidden"])
        self.assertNotIn("garrick-thought", out["store"])
        self.assertEqual([], out["copied"])

    def test_an_empty_box_says_nothing_and_is_cleared(self):
        out = self.run_js(kept={"garrick-thought": "  \n"})
        self.assertTrue(out["left"]["hidden"])
        self.assertNotIn("garrick-thought", out["store"])


class TestWhatALaunchSays(StatusCase):
    """Every launcher reports what it achieved, and no launcher replaces the
    clipboard without saying so in the same breath. The page says only that it
    is opening; the host, which alone knows how it went, says what opened.
    Issue #104."""

    SWIFT = REPO / "extras" / "status" / "app" / "Garrick.swift"
    PLUGIN = REPO / "extras" / "status" / "obsidian" / "main.js"

    def swift(self):
        return self.SWIFT.read_text(encoding="utf-8")

    def plugin(self):
        return self.PLUGIN.read_text(encoding="utf-8")

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_page_says_it_is_opening_never_that_it_opened(self):
        html = self.page(launchers=("finder", "cmux", "codex", "claude"))
        self.assertIn('data-launchers="finder,cmux,codex,claude"', html)
        # The desk marker is set here on purpose. Whether a real card carries
        # one depends on whether the cmux extra and cmux itself are installed
        # on the machine, and with no desk cmux is a fourth `data-launch`
        # button rather than a desk button: that branch is the `plain` case
        # below. Reading the ambient machine instead would make this pass on
        # one and fail on the other, which is what it did.
        desk_card = dict(cards(html)[("Acme Review", "Pricing")], dk=["Work", "Acme Review", "Pricing"])
        acts = panel(True, ("acts", desk_card), launchers="finder,cmux,codex,claude")[0]
        said = dict(re.findall(r'data-launch="(\w+)"[^>]*?data-say="([^"]*)"', acts))
        self.assertEqual({"finder": "Showing Pricing in Finder…", "codex": "Opening Pricing in Codex…",
                          "claude": "Opening Pricing in Claude…"}, said)
        # cmux here goes through the cmux extra's desk, which has always said this
        self.assertIn('data-k="cmux"', acts)
        self.assertIn('data-say="Opening Pricing in cmux…"', acts)
        for claim in ("Opened Claude in", "Opened Codex in", "Showed Pricing in Finder.", "Paste “open Pricing”"):
            self.assertNotIn(claim, acts, "the page claims an outcome it cannot know")
        # a plain cmux, with no desk, says the same and leaves the outcome to the host
        plain = panel(True, ("acts", dict(cards(html)[("Acme Review", "Pricing")], dk=None)),
                      launchers="finder,cmux,codex,claude")[0]
        self.assertIn('data-launch="cmux"', plain)
        self.assertIn('data-say="Opening Pricing in cmux…"', plain)

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_open_in_claude_on_a_thread_is_continue_where_the_cli_is_here(self):
        """#180: where the build found Claude Code's command-line tool, Open
        in Claude on a thread sends the simple home's Continue request, and
        the working card says it is opening; without the tool it is the deep
        link, as before, and so is a card with no note to continue."""
        self.assertNotIn("data-cli", self.page(launchers=("claude",)))           # unsaid: the deep link
        html = self.page(launchers=("claude",), cli=True)
        self.assertIn('data-cli="1"', html)
        card = cards(html)[("Acme Review", "Pricing")]
        self.assertEqual(["Work", "Acme Review/Threads/Pricing/Pricing.md"], card["oc"])
        acts = panel(True, ("acts", card), launchers="claude", cli=True)[0]
        q = re.search(r'data-k="claude"[^>]*data-act="(\{.*?\})" data-say="([^"]*)"', acts)
        self.assertIsNotNone(q, acts)
        self.assertEqual({"verb": "continue", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md"}, json.loads(q.group(1)))
        self.assertEqual("Opening Pricing in Claude…", q.group(2))
        self.assertNotIn('data-launch="claude"', acts)
        self.assertNotIn("claude://", status.PANEL_JS)                          # the page never builds the link itself
        # no tool here: the deep link, which leaves the phrase for you to send
        plain = panel(True, ("acts", card), launchers="claude")[0]
        self.assertIn('data-launch="claude"', plain)
        self.assertIn('data-phrase="open Pricing"', plain)
        self.assertNotIn('"verb":"continue"', plain)
        # a project of several threads has no one note to continue
        project = panel(True, ("acts", dict(card, oc=None, n="Acme Review")), launchers="claude", cli=True)[0]
        self.assertIn('data-launch="claude"', project)
        # clicking the thread's name, with Claude the default, sends the same request through the working card
        self.assertIn("var q=d==='claude'&&cont(o);if(q){if(window.GarrickHeld&&GarrickHeld(q))return;"
                      "if(!(window.GarrickAct&&GarrickAct(q,going(o))))", status.PANEL_JS)
        self.assertIn("continue", status.ZONE_VERBS)                            # a zone verb: the working card shows it running

    def test_the_apps_menu_and_panel_continue_a_thread_in_claude(self):
        """#180: the app's menu and panel run a row's action through run(),
        which continues a thread in Claude through page_action.py where the
        page's menu says the tool is here, and keeps the deep link otherwise."""
        swift = self.swift()
        acts = swift[swift.index("func acts(_ r: [String: Any])"):swift.index("// The menu: a field")]
        self.assertIn('let cli = (menuState?["data"] as? [String: Any])?["cli"] as? Int == 1', acts)
        self.assertIn('if k == "claude", cli, let oc = r["oc"] as? [String], oc.count == 2 { a["oc"] = oc;', acts)
        run = swift[swift.index("func run(_ a: [String: Any])"):swift.index("// A row's icon, kept visible")]
        self.assertIn('if k == "claude", let oc = a["oc"] as? [String], oc.count == 2 {', run)
        self.assertIn('act(["verb": "continue", "zone": oc[0], "file": oc[1]])', run)
        self.assertLess(run.index('act(["verb": "continue"'), run.index("launch(k, f,"))      # before the deep link

    def test_both_hosts_say_the_same_words(self):
        # One page, two hosts: the sentences are the same in each, so what a
        # launcher tells you does not depend on where the page is being shown.
        swift, plugin = self.swift(), self.plugin()
        for sentence in ('” typed in. Press Enter to send it.',                 # Claude: the phrase is in the session, not sent
                         '. The clipboard now holds “',                          # Codex and cmux: replaced, and said
                         '; paste it to resume.',
                         ' in Finder. Nothing was copied; the phrase that resumes it is “',
                         '. The phrase that resumes it is “',                    # a failure still names the phrase
                         'Starting Claude, then opening ',                       # while a cold Claude loads
                         '. This takes a few seconds.',
                         'Claude did not say its window was ready within forty seconds. Opened ',
                         'if the session came up empty, the phrase that resumes it is “'):
            self.assertIn(sentence, swift, sentence)
            self.assertIn(sentence, plugin, sentence)
        # and the same waits, so one host does not give up where the other goes on
        self.assertIn('let claudeReadyMark = "boot: done"', swift)
        self.assertIn('const CLAUDE_READY = "boot: done"', plugin)
        self.assertIn("let claudeReadyCeiling: TimeInterval = 40", swift)
        self.assertIn("ceiling: 40000", plugin)
        self.assertIn("let claudeReadyFallback: TimeInterval = 15", swift)
        self.assertIn("fallback: 15000", plugin)

    def test_a_cold_claude_is_started_and_waited_for(self):
        swift = self.swift()
        claude = swift[swift.index('case "claude":'):swift.index('case "codex":')]
        self.assertIn("if NSRunningApplication.runningApplications(withBundleIdentifier: claudeBundle).isEmpty {", claude)
        self.assertIn("startClaude(url, name: name, phrase: phrase)", claude)
        self.assertIn("sendToClaude(url, name: name, phrase: phrase, window: nil)", claude)   # running: at once, as before
        self.assertNotIn("return NSWorkspace.shared.open(url)", claude)                       # never the bare link again
        start = swift[swift.index("func startClaude("):swift.index("// Whether the page says the desk")]
        self.assertLess(start.index("let from = claudeLogSize()"), start.index("openApplication(at: app"))
        self.assertIn("toast(startingClaude(name))", start)                                   # said before the wait
        self.assertIn("let window = awaitClaudeWindow(from: from)", start)
        wait = swift[swift.index("func awaitClaudeWindow("):swift.index("// What the app keeps between launches")]
        self.assertIn("sleep(claudeReadyFallback)", wait)                                      # no log: the fixed delay
        self.assertIn("while waited < claudeReadyCeiling {", wait)
        self.assertIn("contains(claudeReadyMark)", wait)
        self.assertIn("return .late", wait)                                                    # and it always ends

    def test_the_clipboard_is_replaced_in_one_place_and_said(self):
        swift = self.swift()
        launch = swift[swift.index("func launch(_ app: String"):swift.index("func sendToClaude(")]
        # Codex copies only once it has opened, and the toast beside it says so.
        codex = launch[launch.index('case "codex":'):launch.index('case "cmux":')]
        self.assertLess(codex.index("try p.run()"), codex.index("copyText(phrase)"))
        self.assertIn('toast(opened("Codex", folder.lastPathComponent, phrase), alsoNotify: false)', codex)
        self.assertEqual(1, launch.count("copyText("))               # cmux copies in openInCmux(), after its open
        cmux = swift[swift.index("func openInCmux("):swift.index("// MARK: the menu bar")]
        self.assertLess(cmux.index("guard error == nil"), cmux.index("self.copyText(phrase)"))
        self.assertIn('self.toast(self.opened("cmux", folder.lastPathComponent, phrase), alsoNotify: false)', cmux)
        # Finder takes neither, so nothing is copied and the phrase is named instead.
        self.assertNotIn("copyText", launch[launch.index('case "finder":'):])
        self.assertIn("Nothing was copied; the phrase that resumes it is", swift)
        # A launch's own phrase is never copied twice: the handler leaves it to the launcher.
        self.assertIn('if let text = body["copy"] as? String, !text.isEmpty, body["launch"] == nil {', swift)
        self.assertIn('typeof body.copy === "string" && body.copy && typeof body.launch !== "string"', self.plugin())

    def test_no_launcher_route_passes_without_saying_what_it_did(self):
        # Every arm of the switch reports, and so does every failure in it.
        swift = self.swift()
        launch = swift[swift.index("func launch(_ app: String"):swift.index("func sendToClaude(")]
        for arm, says in (('case "codex":', ('notOpened("Codex"', 'opened("Codex"')),
                          ('case "cmux":', ("openInCmux(folder.path, phrase: phrase)",)),
                          ('case "finder":', ("showedInFinder(folder.lastPathComponent, phrase)",))):
            body = launch[launch.index(arm):]
            for said in says:
                self.assertIn(said, body[:body.index("\n\t\tcase ") if "\n\t\tcase " in body else len(body)], arm)
        self.assertIn('toast(notOpened("Claude", name, phrase))', swift)
        self.assertIn('toast(window == .late ? claudeWasLate(name, phrase) : opened("Claude", name, phrase)', swift)

    def test_the_docs_hold_a_scenario_for_every_launcher_and_host_state(self):
        # What cannot be driven from this suite is written down instead, one row
        # per launcher and host state, in docs/extras/status-page.md.
        page = (REPO / "docs" / "extras" / "status-page.md").read_text(encoding="utf-8")
        table = page[page.index("#### What each launcher does"):]
        table = table[:table.index("\n\n", table.index("|"))]
        rows = [r.strip("| ").split(" | ") for r in table.splitlines() if r.startswith("| *") or r.startswith("| ")]
        states = {(r[0].strip(), r[1].strip()) for r in rows if len(r) >= 3}
        for launcher in ("*Open in Claude*", "*Open in Codex*", "*Open in cmux*", "*Reveal in Finder*"):
            self.assertTrue([s for s in states if s[0] == launcher], launcher)
        # through Continue's request where the command-line tool is here (#180), the deep link where it is not
        for state in ("The command-line tool is here", "The command-line tool is here, pressed again within twelve hours",
                      "The command-line tool is here, but the call is refused", "No command-line tool, Claude running",
                      "No command-line tool, Claude not running", "Not installed"):
            self.assertIn(("*Open in Claude*", state), states, state)
        self.assertIn(("*Open in Codex*", "Installed without its own launcher"), states)
        self.assertIn("boot: done", page)                      # the mark the wait watches for
        self.assertIn("forty seconds", page)                   # and the ceiling, in words
