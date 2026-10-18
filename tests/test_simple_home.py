"""The simple home (#175): Your work, Needs you and Ask something, a piece of
work's page, and Continue, which opens the work in Claude's desktop app.

    python3 -m unittest discover -s tests

The Claude Code CLI is never run here: every hand-off goes to a stand-in
(MOCK_CLAUDE) that writes down how it was called, whether it had a terminal,
and answers as the CLI does. Nothing reads this Mac's managed preferences:
each test names its own.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import importlib.util
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
from fixtures import build_workspace, project_hub, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
HERE = REPO / "extras" / "status"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = _load("garrick_status_simple", HERE / "status.py")
pa = _load("garrick_page_action_simple", HERE / "page_action.py")
handoff = pa.handoff()

TODAY = dt.date.today()


def day(n: int) -> str:
    return (TODAY + dt.timedelta(days=n)).isoformat()


def spoken(n: int) -> str:
    d = TODAY + dt.timedelta(days=n)
    return "%d %s %d" % (d.day, d.strftime("%B"), d.year)


def thread(project, name, party="acme", next_="Send Dana the price sheet", waiting="nobody", updated=0,
           about="What this thread is for.", status="active"):
    return textwrap.dedent("""\
        ---
        title: {name}
        type: thread
        project: "[[{project}]]"
        party: {party}
        status: {status}
        created: 2026-03-01
        updated: {updated}
        ---

        # {name}

        {about}

        ## State of play

        ### Resume here

        **Where it stands, {said}.** In hand.

        | | |
        |---|---|
        | Live artifact | none |
        | Next action | {next_} |
        | Keep in mind | nothing |
        | Waiting on | {waiting} |
        | Deadline | none |

        ---

        **{said}.** Drafted the tier-two rates.
        """).format(project=project, name=name, party=party, status=status, updated=day(updated), about=about,
                    said=spoken(updated), next_=next_, waiting=waiting)


QUESTION = """---
type: question
asked: {asked}
status: {status}
{extra}---

**Acme Review: which volume floor did you agree with Dana?**

In the call Dana said 400 pallets and you said 500. The price sheet waits on this.

- [400 pallets] Send Dana the price sheet at a 400-pallet floor
- [500 pallets] Send Dana the price sheet at a 500-pallet floor
"""


def sid(n: int) -> str:
    """The session id the stand-in CLI gives on its nth call, shaped as the CLI's are."""
    return "%08d-0000-4000-8000-000000000000" % n


def question(status_="open", extra=""):
    return QUESTION.format(asked=day(-2), status=status_, extra=extra)


class HomeCase(unittest.TestCase):
    """A workspace on the simple home: Acme Review is one thread, Birch Entry
    has two, and Personal has a third piece of work."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.root = base / "Workspace"
        self.jobs = base / "jobs"
        self.jobs.mkdir()
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        write(self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md", thread("Acme Review", "Pricing", updated=-1))
        write(self.work / "Birch Entry" / "Birch Entry.md",
              project_hub("Work", "Birch Entry", "birch", ["Market Sizing", "Interviews"]))
        write(self.work / "Birch Entry" / "Threads" / "Market Sizing" / "Market Sizing.md",
              thread("Birch Entry", "Market Sizing", "birch", "Theo to send the volumes", waiting="Theo Marsh", updated=-8))
        write(self.work / "Birch Entry" / "Threads" / "Interviews" / "Interviews.md",
              thread("Birch Entry", "Interviews", "birch", "Write up the interviews", updated=-3))
        self.settings({"home": "simple"})
        agents = mock.patch.object(status, "launch_agents", lambda: base / "LaunchAgents")
        agents.start()
        self.addCleanup(agents.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def settings(self, data):
        (self.root / "System" / "garrick-settings.json").write_text(json.dumps(data), encoding="utf-8")

    def todo(self, *lines):
        write(self.work / "Todo.md", "# Work: open actions\n\n## Inbox\n\n%s\n\n## Done\n" % "\n".join(lines))

    def page(self, **kw):
        return status.build(self.root, folder=self.jobs, **kw)

    def works(self):
        T = status.threads(self.root)
        lists = status.todo_list(self.root, status.Links(self.root), TODAY)
        status.thread_actions(T, lists, None, self.root)
        return {w["name"]: w for w in status.works(self.root, T, TODAY)}


def rows(html):
    """Your work's rows, in order: (name, the next action's text, its side: Continue or Waiting on…)."""
    out = []
    for m in re.finditer(r'<div class="sh-row" data-w="[^"]*">(.*?)</div><div class="sh-next">(.*?)</div>'
                         r'<div class="sh-meta">(.*?)</div>(.*?)</div>', html):
        name = htmllib.unescape(re.sub(r"<[^>]+>", "", re.sub(r'<span class="sh-tag">.*?</span>', "", m.group(1))))
        side = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(4)))
        out.append((name, htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(2))), htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(3))), side))
    return out


class TestWhoSeesIt(HomeCase):
    def test_a_workspace_that_never_chose_keeps_the_full_page(self):
        (self.root / "System" / "garrick-settings.json").unlink()
        html = self.page()
        self.assertNotIn('id="tab-home"', html)
        self.assertNotIn('class="simple"', html)
        self.assertIn('id="tab-overview">', html)                        # shown, as before
        self.assertEqual("full", status.home_layout(self.root))
        self.assertIn('name="garrick-home" value="full" checked', html)  # and Settings can switch it

    def test_full_keeps_the_full_page_too(self):
        self.settings({"home": "full"})
        self.assertNotIn('id="tab-home"', self.page())

    def test_simple_opens_on_the_home_with_everything_else_under_more(self):
        html = self.page()
        self.assertIn('<body class="simple" data-tab="home"', html)
        self.assertIn('<section class="tab" id="tab-home">', html)
        self.assertIn('<section class="tab" id="tab-overview" hidden>', html)
        for tab in ("home", "overview", "status", "guide"):          # graphs, diagnostics, launchers, tuning: all still there
            self.assertIn('data-tab="%s"' % tab, html)
        self.assertIn('data-more="overview"', html)                   # More
        self.assertIn('data-more="status"', html)                     # the status dot by Settings
        self.assertIn('id="gcv"', html)                               # the graph, under More
        self.assertIn('name="garrick-home" value="simple" checked', html)
        for heading in ("Needs you", "Your work"):
            self.assertIn('<h2 class="sh-h">%s' % heading, html)
        self.assertIn('placeholder="Ask something, or start new work"', html)

    def test_the_full_page_says_nothing_of_a_notes_words_still(self):
        self.settings({})
        html = self.page()
        self.assertNotIn("Send Dana the price sheet", html)
        self.assertNotIn("What this thread is for", html)


class TestYourWork(HomeCase):
    def test_most_recent_first_with_the_next_action_and_continue(self):
        got = rows(self.page())
        self.assertEqual(["Acme Review", "Birch Entry, Interviews", "Birch Entry, Market Sizing"], [r[0] for r in got[:3]])
        self.assertEqual("Send Dana the price sheet", got[0][1])
        self.assertTrue(got[0][2].startswith("Yesterday"))
        self.assertEqual("Continue", got[0][3])

    def test_a_next_action_loses_its_whose_it_is_tail(self):
        S = status
        self.assertEqual("Finish the launch email", S.without_owner("Finish the launch email; Robin's"))
        self.assertEqual("Draft it", S.without_owner("Draft it; the assistant's"))
        self.assertEqual("Send it to Dana's team", S.without_owner("Send it to Dana's team"))

    def test_a_waiting_row_says_who_and_has_no_continue(self):
        got = {r[0]: r for r in rows(self.page())}
        self.assertEqual("Waiting on Theo Marsh", got["Birch Entry, Market Sizing"][3])
        self.assertEqual("Continue", got["Birch Entry, Interviews"][3])

    def test_nobody_and_a_placeholder_are_not_waiting(self):
        for said in ("nobody", "Nobody.", "<who, or nobody>", "none", ""):
            self.assertIsNone(status.waiting_on(said), said)
        self.assertEqual("Theo Marsh", status.waiting_on("[[Theo Marsh]]"))

    def test_what_is_owed_counts_the_threads_own_todo_lines(self):
        thursday = next(TODAY + dt.timedelta(days=n) for n in range(2, 7))
        self.todo("- [ ] [[Pricing]]: Send Dana the price sheet 📅 %s" % thursday.isoformat(),
                  "- [ ] [[Pricing]]: Book the review call",
                  "- [ ] [[Pricing]]: Numbers from Dana #waiting ⏳ %s" % day(2),       # owed to you, not by you
                  "- [x] [[Pricing]]: Done already ✅ %s" % day(-1),
                  "- [ ] [[Interviews]]: Send Theo the notes 📅 %s" % day(-1))
        w = self.works()
        self.assertEqual("2 owed, 1 due %s" % thursday.strftime("%A"), status.owed_said(w["Acme Review"]["owed"], TODAY))
        self.assertEqual("1 owed, overdue", status.owed_said(w["Birch Entry, Interviews"]["owed"], TODAY))
        self.assertEqual("", status.owed_said(w["Birch Entry, Market Sizing"]["owed"], TODAY))
        self.assertIn("2 owed, 1 due %s" % thursday.strftime("%A"), rows(self.page())[0][2])

    def test_the_owed_words(self):
        a = lambda d: {"when": d}  # noqa: E731
        self.assertEqual("1 owed", status.owed_said([a(None)], TODAY))
        self.assertEqual("1 owed, due today", status.owed_said([a(TODAY)], TODAY))
        self.assertEqual("1 owed, due tomorrow", status.owed_said([a(TODAY + dt.timedelta(days=1))], TODAY))
        far = TODAY + dt.timedelta(days=30)
        self.assertEqual("3 owed, 2 due %d %s" % (far.day, far.strftime("%B")),
                         status.owed_said([a(far), a(far), a(None)], TODAY))

    def test_when_it_last_moved(self):
        self.assertEqual("Today", status.ago(TODAY, TODAY))
        self.assertEqual("Yesterday", status.ago(TODAY - dt.timedelta(days=1), TODAY))
        self.assertEqual("3 days ago", status.ago(TODAY - dt.timedelta(days=3), TODAY))
        self.assertEqual("Last week", status.ago(TODAY - dt.timedelta(days=9), TODAY))
        self.assertEqual("3 weeks ago", status.ago(TODAY - dt.timedelta(days=21), TODAY))

    def test_five_show_and_the_rest_are_under_more(self):
        for i in range(5):
            write(self.root / "Zones" / "Personal" / ("Errand %d" % i) / ("Errand %d.md" % i),
                  thread("Errand %d" % i, "Errand %d" % i, "personal", updated=-20 - i).replace("type: thread", "type: project"))
        html = self.page()
        listing = html.split('id="sh-list">', 1)[1].split('<details class="sh-more"', 1)[0]
        self.assertEqual(5, listing.count('class="sh-row"'))
        self.assertIn("3 more: Errand 2, Errand 3, Errand 4</summary>", html)
        self.assertEqual(8, len(rows(html)))

    def test_parked_and_finished_work_is_not_listed(self):
        write(self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md", thread("Acme Review", "Pricing", status="parked"))
        self.assertNotIn("Acme Review", [r[0] for r in rows(self.page())])

    def test_the_example_is_marked_and_can_be_put_away(self):
        ex = self.root / "Zones" / "Example"
        (ex / ".git").mkdir(parents=True)
        write(ex / "Spring Catalogue" / "Spring Catalogue.md",
              thread("Spring Catalogue", "Spring Catalogue", updated=1).replace("type: thread", "type: project"))
        html = self.page()
        self.assertIn('Spring Catalogue</button><span class="sh-tag">Example</span>', html)
        self.assertIn("Everything marked Example is made up", html)
        self.assertIn(htmllib.escape(json.dumps({"verb": "example", "do": "archive"})), html)

    def test_an_archived_example_can_be_brought_back(self):
        write(self.root / "System" / "tools" / "example.py",
              "import json, sys\nprint(json.dumps({'state': 'archived'}) if sys.argv[-1] == 'status' else 'done')\n")
        html = self.page()
        self.assertIn("Bring the example back", html)
        self.assertIn(htmllib.escape(json.dumps({"verb": "example", "do": "restore"})), html)
        self.assertNotIn("Remove the example", html)

    def test_no_work_at_all_says_how_to_start(self):
        for zone in ("Work", "Personal"):
            for p in (self.root / "Zones" / zone).iterdir():
                if p.is_dir() and p.name not in ("Inbox", ".git"):
                    shutil.rmtree(p)
        html = self.page()
        self.assertIn("Start with your own work", html)
        self.assertEqual([], rows(html))


class TestNeedsYou(HomeCase):
    def ask(self, text, name="261015 - volume-floor.md"):
        return write(self.work / "Acme Review" / "Threads" / "Pricing" / "Needs you" / name, text)

    def test_nothing_needs_you(self):
        self.assertIn('<div class="sh-empty">Nothing needs you.</div>', self.page())

    def test_an_open_question_with_its_answers_and_not_now(self):
        self.ask(question())
        html = self.page()
        self.assertIn("<b>Acme Review: which volume floor did you agree with Dana?</b>", html)
        self.assertIn("The price sheet waits on this.", html)
        for label in ("400 pallets", "500 pallets"):
            req = {"verb": "answer", "zone": "Work", "file": "Acme Review/Threads/Pricing/Needs you/261015 - volume-floor.md",
                   "label": label}
            self.assertIn(htmllib.escape(json.dumps(req)), html)
        self.assertIn(">Not now</button>", html)
        self.assertIn("1 question</small>", html)
        self.assertIn("waits on your answer above", rows(html)[0][1])

    def test_put_off_hides_it_until_its_day(self):
        self.ask(question("later", "later: %s\n" % day(2)))
        html = self.page()
        self.assertIn("Nothing needs you.", html)
        self.assertIn("1 put off</small>", html)
        self.ask(question("later", "later: %s\n" % day(0)))
        self.assertIn("<b>Acme Review: which volume floor", self.page())

    def test_an_answered_question_is_gone(self):
        self.ask(question("answered", 'answer: "400 pallets"\nanswered: %s\n' % day(0)))
        self.assertIn("Nothing needs you.", self.page())


class TestTheCheck(HomeCase):
    """check.py reads a Needs you question as the home does, and warns where
    the home would leave one out."""

    def findings(self):
        import check  # noqa: E402  (fixtures puts the tools folder on sys.path)
        return [f.message for f in check.run_checks(self.root, quick=True) if f.check == "questions"]

    def test_a_question_as_written_passes(self):
        write(self.work / "Acme Review" / "Threads" / "Pricing" / "Needs you" / "261015 - floor.md", question())
        self.assertEqual([], self.findings())

    def test_one_the_home_cannot_read_is_named(self):
        box = self.work / "Acme Review" / "Threads" / "Pricing" / "Needs you"
        write(box / "a.md", question("pending"))
        write(box / "b.md", question("later"))
        write(box / "c.md", question().replace("**", ""))
        got = self.findings()
        self.assertEqual(3, len(got), got)
        self.assertIn("`status` is 'pending'; the home reads open, answered, later", got)
        self.assertIn("put off with no `later:` date, so it never comes back", got)
        self.assertIn("no bold line to ask, so the home leaves it out", got)


class GitCase(HomeCase):
    """The Work zone a real repository, as the page's actions need."""

    def setUp(self):
        super().setUp()
        self._env = mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": str(self.jobs),
                                                 "GARRICK_MANAGED_PLACES": str(self.root.parent / "no-managed.plist")})
        self._env.start()
        self.addCleanup(self._env.stop)
        shutil.rmtree(self.work / ".git")
        for args in (("init", "-q"), ("config", "user.name", "Sam Rivera"), ("config", "user.email", "sam@example.com"),
                     ("config", "maintenance.auto", "false"), ("config", "gc.auto", "0"), ("add", "-A"),
                     ("commit", "-q", "-m", "start")):
            subprocess.run(["git", "-C", str(self.work)] + list(args), check=True, capture_output=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.work)] + list(args), check=True, capture_output=True, text=True).stdout


class TestAnswering(GitCase):
    FILE = "Acme Review/Threads/Pricing/Needs you/261015 - volume-floor.md"

    def setUp(self):
        super().setUp()
        self.q = write(self.work / self.FILE, question())
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "asked")
        self.note = self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"

    def test_an_answer_sets_the_next_action_adds_an_entry_and_commits_both(self):
        said = pa.act(self.root, {"verb": "answer", "zone": "Work", "file": self.FILE, "label": "500 pallets"}, today=TODAY)
        self.assertEqual("Noted: 500 pallets. Next for Acme Review: Send Dana the price sheet at a 500-pallet floor", said)
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("| Next action | Send Dana the price sheet at a 500-pallet floor |", text)
        self.assertIn("**%s.** Answered: 500 pallets.\n" % spoken(0), text)
        self.assertIn("updated: %s" % TODAY.isoformat(), text)
        fm = status.frontmatter(self.q)
        self.assertEqual(("answered", "500 pallets", TODAY.isoformat()), (fm["status"], fm["answer"], fm["answered"]))
        self.assertEqual("", self.git("status", "--porcelain"))
        changed = self.git("show", "--name-only", "--format=%s", "HEAD").split("\n")
        self.assertEqual("Acme Review: answered 500 pallets", changed[0])
        self.assertEqual({self.FILE, "Acme Review/Threads/Pricing/Pricing.md"}, set(filter(None, changed[1:])))
        self.assertIn("Nothing needs you.", self.page())          # and the home moves on

    def test_a_refused_commit_puts_back_both_files_or_neither(self):
        real = pa.git

        def refused(edit):
            def git(zone, *args, **kw):
                if args[:1] == ("commit",):
                    if edit:
                        self.q.write_text(self.q.read_text() + "\nEdited meanwhile.\n")
                    return 1, "the pre-commit hook said no"
                return real(zone, *args, **kw)
            return git

        before = self.note.read_text(encoding="utf-8"), self.q.read_text(encoding="utf-8")
        req = {"verb": "answer", "zone": "Work", "file": self.FILE, "label": "500 pallets"}
        with mock.patch.object(pa, "git", refused(False)):
            with self.assertRaisesRegex(pa.Refused, "nothing changed: the pre-commit hook said no"):
                pa.act(self.root, req, today=TODAY)
        self.assertEqual(before, (self.note.read_text(encoding="utf-8"), self.q.read_text(encoding="utf-8")))
        with mock.patch.object(pa, "git", refused(True)):
            with self.assertRaisesRegex(pa.Refused, "edited meanwhile"):
                pa.act(self.root, req, today=TODAY)
        self.assertIn("Send Dana the price sheet at a 500-pallet floor", self.note.read_text(encoding="utf-8"))
        self.assertIn("Edited meanwhile.", self.q.read_text(encoding="utf-8"))   # neither put back

    def test_a_second_answer_and_an_unknown_one_are_refused(self):
        with self.assertRaises(pa.Refused):
            pa.act(self.root, {"verb": "answer", "zone": "Work", "file": self.FILE, "label": "450 pallets"}, today=TODAY)
        pa.act(self.root, {"verb": "answer", "zone": "Work", "file": self.FILE, "label": "400 pallets"}, today=TODAY)
        with self.assertRaisesRegex(pa.Refused, "already answered"):
            pa.act(self.root, {"verb": "answer", "zone": "Work", "file": self.FILE, "label": "500 pallets"}, today=TODAY)

    def test_only_a_question_in_a_needs_you_folder(self):
        with self.assertRaisesRegex(pa.Refused, "not a question"):
            pa.act(self.root, {"verb": "answer", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md",
                               "label": "400 pallets"}, today=TODAY)

    def test_not_now_puts_it_off_to_tomorrow_and_it_comes_back(self):
        said = pa.act(self.root, {"verb": "later", "zone": "Work", "file": self.FILE}, today=TODAY)
        self.assertEqual("Put off until tomorrow. It will be back then", said)
        fm = status.frontmatter(self.q)
        self.assertEqual(("later", (TODAY + dt.timedelta(days=1)).isoformat()), (fm["status"], fm["later"]))
        self.assertEqual("", self.git("status", "--porcelain"))
        self.assertIn("Nothing needs you.", self.page())
        # the day comes: it is back, and answering it still works
        later = status.questions_in(self.q.parent.parent, self.work, TODAY + dt.timedelta(days=1))
        self.assertTrue(later[0]["shown"])
        pa.act(self.root, {"verb": "answer", "zone": "Work", "file": self.FILE, "label": "400 pallets"},
               today=TODAY + dt.timedelta(days=1))
        self.assertNotIn("later:", self.q.read_text(encoding="utf-8"))

    def test_not_now_to_a_named_day_and_never_to_today(self):
        pa.act(self.root, {"verb": "later", "zone": "Work", "file": self.FILE, "until": day(5)}, today=TODAY)
        self.assertEqual(day(5), status.frontmatter(self.q)["later"])
        with self.assertRaises(pa.Refused):
            pa.act(self.root, {"verb": "later", "zone": "Work", "file": self.FILE, "until": day(0)}, today=TODAY)

    def test_the_answer_survives_a_restart_because_it_is_files(self):
        """Nothing about a question is kept anywhere but its file: a page
        built afresh, as after a restart, reads it the same way."""
        first = self.page()
        self.assertIn("which volume floor", first)
        self.assertEqual(first.count("which volume floor"), self.page().count("which volume floor"))


MOCK_CLAUDE = r'''#!/usr/bin/env python3
"""A stand-in for the Claude Code CLI: writes down each call, answers as the CLI does."""
import json, os, sys
log = os.environ["MOCK_LOG"]
args = sys.argv[1:]
with open(log, "a") as f:
    f.write(json.dumps({"args": args, "cwd": os.getcwd(), "tty": os.isatty(0) and os.isatty(1)}) + "\n")
if "--desktop" in args:
    if not (os.isatty(0) and os.isatty(1)):
        print("Error: claude --desktop can't run non-interactively"); sys.exit(1)
    if "--settings" in args or "--mcp-config" in args:
        print("Error: --desktop does not take --settings"); sys.exit(1)
    said = os.environ.get("MOCK_DESKTOP_SAY", "Opening in Claude desktop")
    print(said); sys.stdout.flush()
    if os.environ.get("MOCK_DESKTOP_HANG"):
        import time; time.sleep(60)
    sys.exit(int(os.environ.get("MOCK_DESKTOP_EXIT", "0")))
if "-p" in args:
    if os.environ.get("MOCK_PRIME_FAIL"):
        sys.stderr.write("Invalid API key · Please run /login\n"); sys.exit(1)
    prompt = args[args.index("-p") + 1]
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": "%08d-0000-4000-8000-000000000000" % len(open(log).read().splitlines()),
                      "result": "It stands at the draft. Next: " + prompt}))
    sys.exit(0)
sys.exit(2)
'''


class HandOffCase(GitCase):
    def setUp(self):
        super().setUp()
        base = self.root.parent
        self.cli = base / "bin" / "claude"
        write(self.cli, MOCK_CLAUDE)
        self.cli.chmod(0o755)
        self.log = base / "calls.jsonl"
        env = mock.patch.dict(os.environ, {"GARRICK_CLAUDE": str(self.cli), "MOCK_LOG": str(self.log)})
        env.start()
        self.addCleanup(env.stop)

    def calls(self):
        try:
            return [json.loads(l) for l in self.log.read_text().splitlines()]
        except FileNotFoundError:
            return []

    def go(self, file="Acme Review/Threads/Pricing/Pricing.md", now=None):
        return pa.act(self.root, {"verb": "continue", "zone": "Work", "file": file}, now=now)


class TestContinue(HandOffCase):
    def test_it_primes_then_opens_that_session_in_the_desktop_app_under_a_terminal(self):
        said = self.go()
        self.assertEqual("Opened Acme Review in Claude. It already knows where it stands", said)
        prime, desk = self.calls()
        folder = str((self.work / "Acme Review").resolve())          # a project that is one thread opens as the project
        self.assertEqual(["-p", "Where am I on Acme Review?", "--output-format", "json",
                          "--disallowedTools=Bash,Edit,Write,MultiEdit,NotebookEdit"], prime["args"])
        self.assertEqual(folder, str(Path(prime["cwd"]).resolve()))
        self.assertEqual(["--desktop", "--resume", sid(1)], desk["args"])
        self.assertTrue(desk["tty"])                                  # --desktop refuses without one
        self.assertEqual(folder, str(Path(desk["cwd"]).resolve()))
        kept = handoff.session_for(self.root, "Work/Acme Review/Threads/Pricing/Pricing.md")
        self.assertEqual(sid(1), kept["id"])
        self.assertIn("Deliverables/260301 - Pricing memo.md", kept["files"])
        self.assertNotIn("Threads/Pricing/Pricing.md", kept["files"])     # Garrick's own record is not the work's files

    def test_a_thread_of_a_project_with_several_opens_in_the_threads_folder(self):
        self.go("Birch Entry/Threads/Interviews/Interviews.md")
        prime = self.calls()[0]
        self.assertEqual("Where am I on Birch Entry, Interviews?", prime["args"][1])
        self.assertEqual(str((self.work / "Birch Entry" / "Threads" / "Interviews").resolve()), str(Path(prime["cwd"]).resolve()))

    def test_it_commits_the_record_first(self):
        note = self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text() + "\nA line written in a session.\n")
        self.go()
        self.assertEqual("", self.git("status", "--porcelain"))
        self.assertEqual("Acme Review: saved before opening in Claude", self.git("log", "-1", "--format=%s").strip())

    def test_only_garricks_record_is_committed_never_the_users_files(self):
        project = self.work / "Acme Review"
        draft = write(project / "Deliverables" / "private draft.docx", "mine")
        memo = project / "Deliverables" / "260301 - Pricing memo.md"
        memo.write_text(memo.read_text() + "\nAn edit of the user's.\n")
        head = self.git("rev-parse", "HEAD")
        self.go()                                                     # nothing of Garrick's changed: no commit
        self.assertEqual(head, self.git("rev-parse", "HEAD"))
        note = project / "Threads" / "Pricing" / "Pricing.md"
        note.write_text(note.read_text() + "\nA line written in a session.\n")
        asked = write(project / "Threads" / "Pricing" / "Needs you" / "261016 - floor.md", question())
        self.go()
        changed = set(filter(None, self.git("show", "--name-only", "--format=", "HEAD").splitlines()))
        self.assertEqual({"Acme Review/Threads/Pricing/Pricing.md", asked.relative_to(self.work).as_posix()}, changed)
        left = self.git("status", "--porcelain", "--untracked-files=all")
        self.assertIn("?? \"Acme Review/Deliverables/private draft.docx\"", left)
        self.assertIn(" M \"Acme Review/Deliverables/260301 - Pricing memo.md\"", left)
        self.assertTrue(draft.is_file())

    def test_a_recent_session_is_resumed_and_an_old_one_asked_afresh(self):
        now = dt.datetime.now()
        self.go(now=now)
        self.go(now=now + dt.timedelta(hours=1))
        self.assertEqual([["-p"], ["--desktop"], ["--desktop"]], [c["args"][:1] for c in self.calls()])
        self.assertEqual(sid(1), self.calls()[-1]["args"][-1])
        self.go(now=now + dt.timedelta(hours=handoff.FRESH_HOURS + 1))
        self.assertEqual(["-p"], self.calls()[3]["args"][:1])

    def test_a_resumed_session_that_will_not_open_is_asked_afresh_once(self):
        now = dt.datetime.now()
        self.go(now=now)
        with mock.patch.dict(os.environ, {"MOCK_DESKTOP_EXIT": "1"}):
            with self.assertRaisesRegex(pa.Refused, "desktop app did not open"):
                self.go(now=now + dt.timedelta(hours=1))
        self.assertEqual([["-p"], ["--desktop"], ["--desktop"], ["-p"], ["--desktop"]], [c["args"][:1] for c in self.calls()])

    def test_a_resumed_session_that_times_out_is_not_opened_twice(self):
        now = dt.datetime.now()
        self.go(now=now)
        with mock.patch.dict(os.environ, {"MOCK_DESKTOP_HANG": "1"}), mock.patch.object(handoff, "DESKTOP_TIMEOUT", 1):
            with self.assertRaisesRegex(pa.Refused, "did not say it had opened within 1 seconds"):
                self.go(now=now + dt.timedelta(hours=1))
        self.assertEqual([["-p"], ["--desktop"], ["--desktop"]], [c["args"][:1] for c in self.calls()])

    def test_a_kept_id_that_is_not_a_session_id_is_primed_afresh(self):
        now = dt.datetime.now()
        self.go(now=now)
        record = handoff.load(self.root)
        record["sessions"]["Work/Acme Review/Threads/Pricing/Pricing.md"]["id"] = "--dangerously-skip-permissions"
        handoff.save(self.root, record)
        self.go(now=now + dt.timedelta(hours=1))
        self.assertEqual([["-p"], ["--desktop"], ["-p"], ["--desktop"]], [c["args"][:1] for c in self.calls()])
        self.assertEqual(sid(3), self.calls()[-1]["args"][-1])
        with self.assertRaises(handoff.HandOffError):
            handoff.open_desktop(self.cli, self.root, "-x")
        self.assertEqual(4, len(self.calls()))                        # refused before the CLI was run

    def test_the_real_binary_is_found_past_a_wrapper(self):
        bin_ = self.root.parent / "path"
        write(bin_ / "claude", "#!/bin/sh\nexec /somewhere/claude --settings x \"$@\"\n").chmod(0o755)
        real = self.root.parent / "local" / "claude"
        write(real, "#!/usr/bin/env node\n").chmod(0o755)
        with mock.patch.object(handoff, "CLAUDE_PLACES", ()):
            self.assertEqual(real.resolve(), handoff.find_claude({"PATH": "%s:%s" % (bin_, real.parent)}))
            self.assertIsNone(handoff.find_claude({"PATH": str(bin_)}))

    def test_no_cli_says_what_to_do(self):
        with mock.patch.dict(os.environ, {"GARRICK_CLAUDE": str(self.root.parent / "nothing")}):
            with self.assertRaisesRegex(pa.Refused, "command-line tool is not installed"):
                self.go()

    def test_a_prime_that_fails_opens_nothing(self):
        with mock.patch.dict(os.environ, {"MOCK_PRIME_FAIL": "1"}):
            with self.assertRaisesRegex(pa.Refused, "Claude did not answer, so nothing was opened: Invalid API key"):
                self.go()
        self.assertEqual(1, len(self.calls()))


class TestStoppedAtTheTime(unittest.TestCase):
    """A hand-off that runs past its time is stopped, with everything it
    started: a stand-in that never stops writing, and one that leaves a child
    of its own behind."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.left = self.base / "grandchild.pid"

    def script(self, body):
        path = write(self.base / "stand-in", "#!%s\n%s" % (sys.executable, textwrap.dedent(body)))
        path.chmod(0o755)
        return path

    def leaves_a_child(self, then):
        return self.script("""\
            import signal, subprocess, sys, time
            # deaf to the hang-up a closed terminal sends, as a daemon is
            child = subprocess.Popen(["sleep", "60"], preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
            open(%r, "w").write(str(child.pid))
            %s
            """ % (str(self.left), then))

    def assertGone(self, pid):
        for _ in range(60):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        os.kill(pid, 9)
        self.fail("process %d was left running" % pid)

    def test_a_child_that_keeps_writing_is_stopped_at_the_time(self):
        cli = self.script("""\
            import sys, time
            while True:
                sys.stdout.write("|/-\\\\"[int(time.time() * 10) % 4] + "\\r"); sys.stdout.flush(); time.sleep(0.1)
            """)
        started = time.time()
        code, said = handoff.in_terminal([str(cli)], self.base, dict(os.environ), timeout=1)
        self.assertIsNone(code)
        self.assertLess(time.time() - started, 5)
        self.assertTrue(said.strip())                                  # it was heard writing all along

    def test_what_the_terminal_child_started_is_stopped_with_it(self):
        cli = self.leaves_a_child("time.sleep(60)")
        code, _ = handoff.in_terminal([str(cli)], self.base, dict(os.environ), timeout=1)
        self.assertIsNone(code)
        self.assertGone(int(self.left.read_text()))

    def test_a_prime_past_its_time_is_stopped_with_what_it_started(self):
        cli = self.leaves_a_child("time.sleep(60)")
        started = time.time()
        with self.assertRaisesRegex(handoff.HandOffError, "took longer than 1 second to answer"):
            handoff.prime(cli, self.base, "Where am I?", timeout=1)
        self.assertLess(time.time() - started, 10)
        self.assertGone(int(self.left.read_text()))


class TestLocalSessionsOff(HandOffCase):
    def test_the_desktop_apps_refusal_is_said_plainly_and_remembered(self):
        with mock.patch.dict(os.environ, {"MOCK_DESKTOP_SAY": "Local sessions are disabled by your organization's policy.",
                                          "MOCK_DESKTOP_EXIT": "1"}):
            with self.assertRaises(pa.Refused) as caught:
                self.go()
        self.assertEqual("%s %s" % (handoff.LOCAL_OFF_TITLE, handoff.LOCAL_OFF), str(caught.exception))
        self.assertEqual("refused", handoff.local_off(self.root))
        html = self.page()
        self.assertIn('data-local="refused"', html)
        self.assertIn("<b>Claude can&#x27;t open work on this Mac.</b>", html)
        self.assertIn("Your IT team can turn local sessions back on for you.", html)
        self.assertIn("Send Dana the price sheet", html)               # nothing else breaks
        self.go()                                                      # and it clears once the app opens again
        self.assertIsNone(handoff.local_off(self.root))
        self.assertNotIn('id="sh-off"', self.page())

    def test_a_managed_setting_stops_it_before_claude_is_asked(self):
        managed = self.root.parent / "com.anthropic.claudefordesktop.plist"
        managed.write_bytes(plistlib.dumps({"disableDesktopLocalSessions": True}))
        with mock.patch.dict(os.environ, {"GARRICK_MANAGED_PLACES": str(managed)}):
            with self.assertRaisesRegex(pa.Refused, "Claude can't open work on this Mac"):
                self.go()
        self.assertEqual([], self.calls())
        html = self.page(managed=[managed])
        self.assertIn('data-local="managed"', html)
        self.assertIn('id="sh-off"', html)
        self.assertIsNone(handoff.local_off(self.root))               # not kept: once IT turns it back on, it is gone
        self.assertNotIn('id="sh-off"', self.page(managed=[self.root.parent / "none.plist"]))

    def test_managed_off_reads_a_plist_and_claude_codes_managed_settings(self):
        off = self.root.parent / "off.json"
        off.write_text(json.dumps({"disableDesktopLocalSessions": True}))
        on = self.root.parent / "on.plist"
        on.write_bytes(plistlib.dumps({"disableDesktopLocalSessions": False}))
        self.assertTrue(handoff.managed_off([on, off]))
        self.assertFalse(handoff.managed_off([on, self.root.parent / "missing.plist"]))

    def test_the_users_managed_place_is_found_without_user_set(self):
        import pwd
        env = {k: v for k, v in os.environ.items() if k != "USER"}
        with mock.patch.dict(os.environ, env, clear=True):
            places = handoff.managed_places(["/Managed/{user}/x.plist"])
        self.assertEqual([Path("/Managed/%s/x.plist" % pwd.getpwuid(os.getuid()).pw_name)], places)

    def test_ask_something_still_answers_on_the_page(self):
        managed = self.root.parent / "managed.json"
        managed.write_text(json.dumps({"disableDesktopLocalSessions": True}))
        with mock.patch.dict(os.environ, {"GARRICK_MANAGED_PLACES": str(managed)}):
            out = pa.act(self.root, {"verb": "ask-desktop", "prompt": "What do I owe people this week?"})
        self.assertEqual("It stands at the draft. Next: What do I owe people this week?", out["answer"])
        self.assertEqual(["-p"], [c["args"][0] for c in self.calls()])        # asked, and nothing opened
        self.assertIsNone(handoff.local_off(self.root))


class TestAskSomething(HandOffCase):
    def test_it_asks_in_the_workspace_and_opens_that_session(self):
        out = pa.act(self.root, {"verb": "ask-desktop", "prompt": "What do I owe people this week?"})
        self.assertEqual("Opened Claude on your question. Its answer is waiting there", out["say"])
        self.assertNotIn("answer", out)
        prime, desk = self.calls()
        self.assertEqual(["-p", "What do I owe people this week?", "--output-format", "json",
                          "--disallowedTools=Bash,Edit,Write,MultiEdit,NotebookEdit"], prime["args"])
        self.assertEqual(str(self.root.resolve()), str(Path(prime["cwd"]).resolve()))
        self.assertEqual(["--desktop", "--resume", sid(1)], desk["args"])

    def test_a_field_no_verb_declares_is_refused(self):
        out, _, _ = pa.perform(self.root, {"verb": "ask-desktop", "prompt": "x", "folder": "/tmp"})
        self.assertFalse(out["ok"])
        self.assertEqual([], self.calls())


class TestTheExample(GitCase):
    def test_remove_and_bring_back_run_example_py(self):
        log = self.root.parent / "example.log"
        write(self.root / "System" / "tools" / "example.py",
              "import sys\nopen(%r, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
              "print('The example is archived. Nothing of yours was touched.')\n" % str(log))
        self.assertEqual("The example is archived. Nothing of yours was touched",
                         pa.act(self.root, {"verb": "example", "do": "archive"}))
        pa.act(self.root, {"verb": "example", "do": "restore"})
        self.assertEqual(["--root %s archive" % self.root, "--root %s restore" % self.root], log.read_text().splitlines())
        with self.assertRaises(pa.Refused):
            pa.act(self.root, {"verb": "example", "do": "delete"})

    def test_without_the_tool_it_says_so(self):
        with self.assertRaisesRegex(pa.Refused, "example.py is missing"):
            pa.act(self.root, {"verb": "example", "do": "archive"})


class TestTheLayoutSwitch(GitCase):
    def setUp(self):
        super().setUp()
        (self.root / "System" / "tools").mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "template" / "System" / "tools" / "garrick_lib.py", self.root / "System" / "tools" / "garrick_lib.py")

    def test_settings_switches_an_existing_install_and_back(self):
        self.settings({"launchers": {"note": True}})                    # an install from before: no "home"
        self.assertEqual("full", status.home_layout(self.root))
        self.assertEqual("Garrick now opens on the simple home", pa.act(self.root, {"verb": "settings", "home": "simple"}))
        saved = json.loads((self.root / "System" / "garrick-settings.json").read_text())
        self.assertEqual({"launchers": {"note": True}, "home": "simple"}, saved)       # nothing else moved
        self.assertIn('id="tab-home"', self.page())
        pa.act(self.root, {"verb": "settings", "home": "full"})
        self.assertNotIn('id="tab-home"', self.page())
        with self.assertRaises(pa.Refused):
            pa.act(self.root, {"verb": "settings", "home": "fancy"})


class TestAWorksPage(HandOffCase):
    def test_what_it_is_who_what_happened_what_is_open_and_next(self):
        self.todo("- [ ] [[Pricing]]: Book the review call")
        html = self.page()
        w = self.works()["Acme Review"]
        page = html.split('<article class="sh-work" id="%s"' % w["id"], 1)[1].split("</article>", 1)[0]
        for said in ("<dt>What it is</dt><dd>What this thread is for.</dd>",
                     "<dt>Who&#x27;s involved</dt><dd>Acme Corp: Dana Whitlock (Head of procurement)</dd>",
                     "<dt>What happened last</dt><dd>Yesterday: Drafted the tier-two rates.</dd>",
                     "Book the review call", "<dt>Next</dt><dd><b>Send Dana the price sheet</b></dd>",
                     ">Continue in Claude</button>", "Kept with the work in Garrick"):
            self.assertIn(said, page)
        self.assertIn('data-w-open="%s"' % w["id"], html)                # the name on the home opens it

    def test_its_files_say_what_is_new_changed_and_missing_since_continue(self):
        shared = self.root.parent / "Shared" / "Acme"
        write(shared / "Price sheet.xlsx", "v1")
        write(shared / "Old notes.docx", "x")
        hub = self.work / "Acme Review" / "Acme Review.md"
        hub.write_text(hub.read_text().replace("status: active\n", "status: active\nfolder: %s\n" % shared))
        self.go()
        (shared / "Old notes.docx").unlink()
        write(shared / "Photos" / "Pallets.jpg", "new")
        os.utime(shared / "Price sheet.xlsx", (1, 1))
        html = self.page()
        w = self.works()["Acme Review"]
        page = html.split('<article class="sh-work" id="%s"' % w["id"], 1)[1].split("</article>", 1)[0]
        self.assertIn("Folder: %s" % htmllib.escape(str(shared)), page)
        self.assertIn("1 new, 1 changed, 1 missing since you last continued it today", page)
        self.assertIn('<li>Photos/Pallets.jpg <span class="sh-tag">new</span></li>', page)
        self.assertIn('<li>Price sheet.xlsx <span class="sh-tag">changed</span></li>', page)
        self.assertIn('<li class="sh-gone">Old notes.docx <span class="sh-tag">missing</span></li>', page)


class TestTheScript(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_script_parses(self):
        done = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0,'utf8'))"], input=status.SIMPLE_JS,
                              capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)

    def test_the_words_for_local_sessions_off_are_the_sketchs(self):
        self.assertEqual("Claude can't open work on this Mac.", handoff.LOCAL_OFF_TITLE)
        self.assertIn("Your company has turned off Claude's local sessions.", handoff.LOCAL_OFF)

    def test_a_refusal_is_read_from_what_the_cli_says(self):
        for said in ("Local sessions are disabled by your organization", "disableDesktopLocalSessions is set",
                     "Your admin has turned off local sessions"):
            self.assertTrue(handoff.refused_locally(said), said)
        self.assertFalse(handoff.refused_locally("Opening in Claude desktop"))

    def test_the_settings_word_is_one_list(self):
        self.assertEqual(status.HOMES, pa.HOMES)
        lib = _load("garrick_lib_simple", REPO / "template" / "System" / "tools" / "garrick_lib.py")
        self.assertIn("home", lib.PREFERENCES)


if __name__ == "__main__":
    unittest.main()
