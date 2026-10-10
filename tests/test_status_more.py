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
vm.runInContext(js + ";this.out=" + JSON.stringify(calls) + ".map(function(c){return Panel[c[0]](c[1])})", ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""


def panel(hosted, *calls):
    """Panel.head or Panel.acts, run in Node as the app (hosted) or a browser would."""
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
    def test_a_threads_card_opens_its_projects_note_by_name(self):
        card = cards(self.page())[("Acme Review", "Pricing")]
        acts = panel(True, ("acts", card))[0]
        self.assertNotIn("Open project", acts)
        self.assertRegex(acts, r'<a class="act pnote" href="file://[^"]*/Acme%20Review/Acme%20Review.md" '
                               r'title="Open the project\'s note" aria-label="Open the note of the project Acme Review">'
                               r'<svg[^>]*>.*</svg><span>Acme Review</span></a>')

    def test_the_panels_dot_follows_the_name(self):
        swift = (Path(status.__file__).parent / "app" / "Garrick.swift").read_text(encoding="utf-8")
        line = swift[swift.index("struct PanelLine: View {"):swift.index("struct PanelView: View {")]
        self.assertLess(line.index("Text(row.name)"), line.index("if let live = row.live {"))
        self.assertLess(line.index("if let live = row.live {"), line.index("Spacer(minLength: 8)"))
        menu = swift[swift.index("final class RowView: NSView {"):swift.index("final class MenuField")]
        self.assertIn("draw(at: NSPoint(x: 21 + indent", menu)               # the menu's names start at 21, dot or not


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
