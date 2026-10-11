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

    def tab(self, **on):
        flags(self.root, **dict({"todo-list": True}, **on))
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

    def test_done_today_can_be_reopened_in_the_app(self):
        _, tab = self.tab()
        done = tab[tab.index("Done today"):]
        self.assertIn("Sent the brief", done)
        self.assertNotIn("An old one", tab)
        self.assertNotIn('class="tick"', tab)                     # read-only without page-actions
        _, tab = self.tab(**{"page-actions": True})
        done = tab[tab.index("Done today"):]
        self.assertRegex(done, r'<div class="trow done[ "]')
        self.assertIn('aria-label="Reopen: Sent the brief"', done)
        self.assertIn("send(d?'todo-done':'todo-undo',r)", status.TODO_JS)

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
        self.assertIn("send('todo-date',r,{date:v})", status.TODO_JS)           # an ISO date, worked out at the click
        self.assertIn("r.classList.add('pending')", status.TODO_JS)             # its key changes: no second click before the rebuild
        self.assertIn("window.TodoPending=function(z,target,date,text)", status.TODO_JS)
        self.assertIn("if(window.TodoPending)TodoPending(z,target,date,text)", status.JS)
        _, tab = self.tab(**{"page-actions": True})
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

    def test_ignore_filters_leave_notes_out(self):
        work = self.root / "Zones" / "Work"
        self.obsidian(work, ignore=["Birch Entry/", "/Sources/"])
        write(work / "Acme Review" / "Sources" / "Brief.md", "# Brief\n")
        names = {n["n"] for n in graph_data(self.page())["nodes"]}
        self.assertNotIn("Market Sizing", names)
        self.assertNotIn("Brief", names)
        self.assertIn("Pricing", names)

    def test_a_root_vault_counts_for_every_place(self):
        self.obsidian(self.root, groups=[("[type:meeting]", 0x123456)])
        data = graph_data(self.page())
        kickoff = next(n for n in data["nodes"] if n["n"] == "Acme kick-off")
        self.assertEqual("#123456", data["groups"][kickoff["g"]][0])

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
        flags(self.root, **{"menu-bar": True, "page-actions": True})
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
        swift = (Path(status.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")
        self.assertIn('live: r["s"] as? String', swift)                                   # the app draws the dot
        self.assertIn('["verb": "open", "zone": dk[0], "project": dk[1]]', swift)          # and opens through the desk
        state = json.loads(re.search(r'id="state-data">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(3, len(state["live"]))          # Pricing's folder, and the two projects' folders above a session
        flags(self.root, **{"menu-bar": True})
        with self.lib():
            html = self.page()
        self.assertEqual("working", cards(html)[("Acme Review", "Pricing")]["live"])   # the dots need no actions
        self.assertNotIn("dk", cards(html)[("Acme Review", "Pricing")])                 # but the desk's buttons do
        self.assertNotIn('class="desk-acts', html)

    def test_the_desks_buttons(self):
        flags(self.root, **{"page-actions": True})
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
        flags(self.root, **{"page-actions": True})
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
        self.assertIn("if(lpChanged){lpChanged=false;host.postMessage({act:GarrickPrefs.request()})}", status.JS)


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
        flags(self.root, **{"page-actions": True, "menu-bar": True})
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

    def test_without_actions_nothing_to_send(self):
        html = self.page()
        self.assertNotIn("pp", project_cards(html)["Acme Review"])
        self.assertEqual(1, project_cards(html)["Acme Review"]["hp"])

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_cards_buttons(self):
        flags(self.root, **{"page-actions": True})
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
        flags(self.root, **{"page-actions": True})
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
        act = swift[swift.index("	func act(_ request: [String: Any]) {"):swift.index("	// Only a folder inside this workspace")]
        self.assertIn("JSONSerialization.data(withJSONObject: [request, said])", act)
        self.assertIn("window.GarrickActed&&window.GarrickActed(a[0],a[1])", act)
        self.assertLess(act.index("GarrickActed"), act.index("self.freshen(force: true)"))   # at once, then the rebuild
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
  el(id).fire(type, ev);
}
process.stdout.write(JSON.stringify({ posted, notes: { hotkey: el("menu-hotkey-note").textContent, askhotkey: el("menu-askkey-note").textContent },
                                     askRow: el("menu-askkey-row").style.display, ask: el("menu-askkey").value }));
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
