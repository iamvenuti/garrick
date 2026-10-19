"""Your own work (#182): a folder the user already keeps, read and never written.

    python3 -m unittest discover -s tests -p test_your_work.py

Add your own work looks through a folder (discover.py), a yes makes Garrick's
record of a piece of work, Start with this one writes a first look from its
files, Continue asks the suggested request, and Stop using this puts the
record away. Every action is followed by a comparison of the folder with what
it was before: each file's checksum, size and modification time, and every
folder. The Claude Code CLI is never run: a stand-in writes down how it was
called and answers as the CLI does.
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import os
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

from fixtures import CONTEXT, build_workspace, write  # noqa: E402
from test_extract import docx, manifest, pptx, xlsx  # noqa: E402
from test_simple_home import _load  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
HERE = REPO / "extras" / "status"
status = _load("garrick_status_your_work", HERE / "status.py")
pa = _load("garrick_page_action_your_work", HERE / "page_action.py")
Y = pa.your_work()
H = pa.handoff()
TODAY = dt.date.today()

LOOK = {"what": "The 2027 product catalogue, printed and online, 64 pages.",
        "who": "Hana Royle (layout), Owen Tarrant (prices)",
        "last": "Yesterday the page plan went to 64 pages, after the proof review call on 14 October.",
        "open": "The printer needs the page count by Friday. The price pages wait on Owen.",
        "next": "Confirm 64 pages to the printer by Friday",
        "source": "the proof review call on 14 October",
        "waiting": "nobody", "deadline": "Friday, to hold the press date",
        "request": "Draft an email to the printer confirming 64 pages for the 2027 catalogue."}

MOCK_CLAUDE = r'''#!/usr/bin/env python3
"""A stand-in for the Claude Code CLI: writes down each call, answers as the CLI does."""
import json, os, sys
log = os.environ["MOCK_LOG"]
args = sys.argv[1:]
with open(log, "a") as f:
    f.write(json.dumps({"args": args, "cwd": os.getcwd(), "tty": os.isatty(0) and os.isatty(1)}) + "\n")
n = len(open(log).read().splitlines())
if "--desktop" in args:
    if not (os.isatty(0) and os.isatty(1)):
        print("Error: claude --desktop can't run non-interactively"); sys.exit(1)
    print("Opening in Claude desktop"); sys.exit(0)
if "-p" in args:
    brief = args[args.index("--append-system-prompt") + 1] if "--append-system-prompt" in args else ""
    if brief.startswith("You are making Garrick's first record"):
        result = os.environ.get("MOCK_LOOK_SAYS") or "Here it is:\n```json\n" + os.environ["MOCK_LOOK"] + "\n```"
    else:
        result = "It stands at the draft."
    print(json.dumps({"type": "result", "is_error": False, "session_id": "%08d-0000-4000-8000-000000000000" % n,
                      "result": result}))
    sys.exit(0)
sys.exit(2)
'''

ONE_PARTY = CONTEXT.replace("| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` | "
                            "birchco.example, mail.birchco.example |\n", "")


def old(path: Path, days: float) -> None:
    t = time.time() - days * 86400
    os.utime(str(path), (t, t))


def drive(base: Path) -> Path:
    """A folder the user keeps their work in, outside the workspace: three pieces of work and some odds and ends."""
    root = base / "Shared Drive"
    files = {
        "Marketing/Catalogue 2027/Catalogue 2027 page plan.xlsx": (xlsx(), 1),
        "Marketing/Catalogue 2027/Cover options.pptx": (pptx(), 3),
        "Marketing/Catalogue 2027/Proof review call notes.docx": (docx("Cut eight pages"), 4),
        "Marketing/Catalogue 2027/Printer quote.pdf": (b"%PDF-1.4 a quote\n", 9),
        "Marketing/Catalogue 2027/Proofs/Proof 1.pdf": (b"%PDF-1.4 proof\n", 5),
        "Marketing/Website refresh/Site map.docx": (docx("Home, chairs, desks"), 6),
        "Marketing/Website refresh/Page copy home.docx": (docx("Welcome"), 7),
        "Marketing/Website refresh/Search terms.xlsx": (xlsx(), 8),
        "Launches/Lounge seating launch/Launch plan.xlsx": (xlsx(), 2),
        "Launches/Lounge seating launch/Press release.docx": (docx("Lounge"), 5),
        "Archive/Old catalogue/Catalogue 2025.pdf": (b"%PDF-1.4 old\n", 300),
        "Holiday rota.xlsx": (xlsx(), 10),
    }
    for rel, (data, days) in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        old(p, days)
    return root


class Case(unittest.TestCase):
    """A workspace with one place for work (Work, for Acme Corp), its tools
    as Garrick ships them, a real repository in the Work zone and in the
    workspace's own folder, and a drive of the user's beside it."""

    context = ONE_PARTY

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.base = base
        self.root = base / "Workspace"
        self.jobs = base / "jobs"
        self.jobs.mkdir()
        build_workspace(self.root)
        (self.root / "System" / "context.md").write_text(self.context, encoding="utf-8")
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        for f in (REPO / "template" / "System" / "tools").glob("*.py"):
            shutil.copy2(f, tools / f.name)
        shutil.copytree(REPO / "template" / "System" / "templates", self.root / "System" / "templates")
        self.work = self.root / "Zones" / "Work"
        for repo in (self.work, self.root):
            shutil.rmtree(repo / ".git", ignore_errors=True)
            for args in (("init", "-q"), ("config", "user.name", "Sam Rivera"), ("config", "user.email", "sam@example.com"),
                         ("config", "commit.gpgsign", "false"), ("config", "core.hooksPath", os.devnull),
                         ("config", "maintenance.auto", "false"), ("config", "gc.auto", "0")):
                subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True)
        write(self.root / ".gitignore", "Zones/\nWikis/\nSystem/generated/\n")
        (self.root / "System" / "garrick-settings.json").write_text(json.dumps({"home": "simple"}), encoding="utf-8")
        for repo in (self.work, self.root):
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "start"], check=True, capture_output=True)
        self.drive = drive(base)
        self.before = manifest(self.drive)
        self.cli = base / "bin" / "claude"
        write(self.cli, MOCK_CLAUDE)
        self.cli.chmod(0o755)
        self.log = base / "calls.jsonl"
        env = mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": str(self.jobs), "GARRICK_CLAUDE": str(self.cli),
                                           "MOCK_LOG": str(self.log), "MOCK_LOOK": json.dumps(LOOK),
                                           "GARRICK_MANAGED_PLACES": str(base / "no-managed.plist")})
        env.start()
        self.addCleanup(env.stop)
        agents = mock.patch.object(status, "launch_agents", lambda: base / "LaunchAgents")
        agents.start()
        self.addCleanup(agents.stop)

    def tearDown(self):
        self.assertEqual(self.before, manifest(self.drive), "the user's folder changed")
        self._tmp.cleanup()

    def act(self, **req):
        return pa.act(self.root, req)

    def git(self, *args, repo=None):
        return subprocess.run(["git", "-C", str(repo or self.work)] + list(args), check=True, capture_output=True,
                              text=True).stdout

    def calls(self):
        try:
            return [json.loads(l) for l in self.log.read_text().splitlines()]
        except FileNotFoundError:
            return []

    def scan(self):
        out = self.act(verb="discover", folder=str(self.drive))
        entry = Y.discovery(self.root)["folders"][os.path.realpath(str(self.drive))]
        return out, {p["name"]: p for p in entry["top"] + entry["more"]}

    def add(self, name="Catalogue 2027", **more):
        _, props = self.scan()
        return self.act(verb="suggestion", id=props[name]["id"], answer="yes", **more)

    def note(self, name="Catalogue 2027"):
        return self.work / name / "Threads" / name / (name + ".md")

    def page(self):
        return status.build(self.root, folder=self.jobs)


class TestAddYourOwnWork(Case):
    def test_a_folder_is_looked_through_and_its_work_proposed(self):
        out, props = self.scan()
        self.assertEqual(Y.view_id(os.path.realpath(str(self.drive))), out["view"])
        self.assertIn("Nothing in it was changed", out["say"])
        self.assertEqual({"Catalogue 2027", "Lounge seating launch", "Website refresh"}, set(props))
        self.assertTrue((self.root / "System" / "generated" / "discovery.json").is_file())

    def test_the_whole_mac_and_the_home_folder_are_refused(self):
        home = self.base / "home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            with self.assertRaisesRegex(pa.Refused, "Pick the folder your work is in"):
                self.act(verb="discover", folder=str(home))
        for folder in ("/",):
            with self.assertRaisesRegex(pa.Refused, "Pick the folder your work is in"):
                self.act(verb="discover", folder=folder)
        with self.assertRaisesRegex(pa.Refused, "not a folder Garrick can read"):
            self.act(verb="discover", folder="relative/path")

    def test_a_yes_makes_a_project_with_one_thread_committed_by_name(self):
        draft = self.work / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        draft.write_text(draft.read_text() + "\nAn edit another session has not committed.\n")
        said = self.add()
        self.assertEqual("Garrick will keep track of Catalogue 2027. Shared Drive is as it was", said)
        hub = self.work / "Catalogue 2027" / "Catalogue 2027.md"
        self.assertTrue(self.note().is_file())
        fm = hub.read_text().split("---")[1]
        self.assertIn("party: acme", fm)
        real = os.path.realpath(str(self.drive / "Marketing" / "Catalogue 2027"))
        self.assertIn("folder: %s" % json.dumps(Y.folder_value(real)), fm)
        self.assertRegex(fm, r"discovered: [0-9a-f]{8}")
        changed = set(filter(None, self.git("show", "--name-only", "--format=", "HEAD").splitlines()))
        self.assertTrue(changed and all(p.startswith("Catalogue 2027/") for p in changed), changed)
        self.assertEqual(" M \"Acme Review/Threads/Pricing/Pricing.md\"\n", self.git("status", "--porcelain"))
        _, props = self.scan()
        self.assertNotIn("Catalogue 2027", props)                          # answered: not proposed again

    def test_rename_counts_as_a_yes_under_the_new_name(self):
        _, props = self.scan()
        self.act(verb="suggestion", id=props["Website refresh"]["id"], answer="rename", name="New website")
        self.assertTrue((self.work / "New website" / "New website.md").is_file())

    def test_not_a_piece_of_work_is_kept_and_makes_nothing(self):
        _, props = self.scan()
        head = self.git("rev-parse", "HEAD")
        said = self.act(verb="suggestion", id=props["Website refresh"]["id"], answer="not")
        self.assertIn("won't be suggested again", said)
        self.assertEqual(head, self.git("rev-parse", "HEAD"))
        _, again = self.scan()                                             # a restart: a new scan, a new process
        self.assertNotIn("Website refresh", again)
        self.assertIn("Lounge seating launch", again)                      # unanswered: still there for next time

    def test_a_suggestion_answered_already_is_refused(self):
        _, props = self.scan()
        self.act(verb="suggestion", id=props["Website refresh"]["id"], answer="not")
        with self.assertRaisesRegex(pa.Refused, "not waiting any more"):
            self.act(verb="suggestion", id=props["Website refresh"]["id"], answer="yes")


class TestSeveralPlaces(Case):
    context = CONTEXT                                       # Work holds Acme Corp and Birch & Co

    def test_a_yes_asks_which_in_one_line_then_goes_there(self):
        _, props = self.scan()
        pid = props["Catalogue 2027"]["id"]
        with self.assertRaises(pa.Refused) as said:
            self.act(verb="suggestion", id=pid, answer="yes")
        self.assertEqual("Which part of your workspace is this work for: Work (Acme Corp) or Work (Birch & Co)?",
                         str(said.exception))
        self.assertFalse((self.work / "Catalogue 2027").exists())
        self.act(verb="suggestion", id=pid, answer="yes", zone="Work", party="birch")
        self.assertIn("party: birch", (self.work / "Catalogue 2027" / "Catalogue 2027.md").read_text())


class TestStartWithThisOne(Case):
    def start(self):
        self.add()
        return self.act(verb="start", zone="Work", file="Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md")

    def test_the_first_look_is_written_from_the_files_and_committed_by_name(self):
        out = self.start()
        self.assertIn("Garrick has a first look at Catalogue 2027", out["say"])
        note = self.note().read_text()
        self.assertIn("first-look: %s" % TODAY.isoformat(), note)
        self.assertIn("| Next action | Confirm 64 pages to the printer by Friday |", note)
        self.assertIn("First look, made by Garrick from the files in Catalogue 2027; check it before you rely on it.", note)
        self.assertIn("Involved: Hana Royle (layout), Owen Tarrant (prices).", note)
        self.assertNotIn("<", note.split("## State of play")[1])            # no template placeholder left
        hub = (self.work / "Catalogue 2027" / "Catalogue 2027.md").read_text()
        self.assertIn("\nThe 2027 product catalogue, printed and online, 64 pages.\n", hub)
        q = next((self.note().parent / "Needs you").glob("*.md"))
        text = q.read_text()
        self.assertIn("**Catalogue 2027: is this your next step?**", text)
        self.assertIn("- [That's right] Confirm 64 pages to the printer by Friday", text)
        self.assertIn('own: "Change it"', text)
        self.assertIn("From the proof review call on 14 October.", text)
        changed = set(filter(None, self.git("show", "--name-only", "--format=", "HEAD").splitlines()))
        self.assertEqual({"Catalogue 2027/Catalogue 2027.md", "Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md",
                          q.relative_to(self.work).as_posix()}, changed)
        self.assertEqual("", self.git("status", "--porcelain"))

    def test_the_call_reads_the_folder_and_the_extracts_and_writes_nothing(self):
        self.start()
        (call,) = self.calls()
        args = call["args"]
        real = os.path.realpath(str(self.drive / "Marketing" / "Catalogue 2027"))
        dirs = [args[i + 1] for i, a in enumerate(args) if a == "--add-dir"]
        self.assertEqual(real, dirs[0])
        self.assertTrue(dirs[1].startswith(str(self.root / "System" / "generated" / "extracts")))
        self.assertTrue(any(p.name.endswith(".xlsx.txt") for p in Path(dirs[1]).rglob("*")))
        self.assertIn("--disallowedTools=Bash,Edit,Write,MultiEdit,NotebookEdit", args)
        self.assertEqual(Y.FIRST_LOOK_BRIEF, args[args.index("--append-system-prompt") + 1])
        self.assertIn(real, args[args.index("-p") + 1])

    def test_edit_is_denied_in_the_settings_of_the_folder_the_session_starts_in(self):
        """Claude Code reads a project's settings only from the session's own
        folder, so the rule sits there, in the project, committed with it;
        Edit alone, since Claude Code matches no Write rule; and the same rule
        goes with --settings on the call. The workspace's own settings are
        left alone."""
        self.add()
        project = self.work / "Catalogue 2027"
        settings = project / ".claude" / "settings.json"
        real = os.path.realpath(str(self.drive / "Marketing" / "Catalogue 2027"))
        rule = "Edit(/%s/**)" % real
        self.assertEqual({"permissions": {"deny": [rule]}}, json.loads(settings.read_text()))   # from the yes on
        self.assertIn("Catalogue 2027/.claude/settings.json",
                      self.git("show", "--name-only", "--format=", "HEAD").splitlines())
        self.act(verb="start", zone="Work", file="Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md")
        (call,) = self.calls()
        self.assertEqual(str(project.resolve()), str(Path(call["cwd"]).resolve()))       # where the session starts
        self.assertEqual({"permissions": {"deny": [rule]}}, json.loads(call["args"][call["args"].index("--settings") + 1]))
        self.assertFalse(any(r.startswith("Write(") for r in json.loads(settings.read_text())["permissions"]["deny"]))
        self.assertFalse((self.root / ".claude" / "settings.json").exists())
        self.assertEqual("", self.git("status", "--porcelain"))
        pa.act(self.root, {"verb": "continue", "zone": "Work",
                           "file": "Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md"})
        prime = [c for c in self.calls() if "-p" in c["args"]][-1]
        self.assertEqual(str(project.resolve()), str(Path(prime["cwd"]).resolve()))
        self.assertIn("--settings", prime["args"])

    def test_a_rule_taken_out_is_put_back_and_committed_before_claude_opens(self):
        self.add()
        settings = self.work / "Catalogue 2027" / ".claude" / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": ["Read"]}}))
        self.git("commit", "-q", "-am", "a rule taken out by hand")
        pa.act(self.root, {"verb": "continue", "zone": "Work",
                           "file": "Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md"})
        kept = json.loads(settings.read_text())["permissions"]
        self.assertEqual(["Read"], kept["allow"])                                       # what was there stays
        self.assertEqual(1, len(kept["deny"]))
        self.assertEqual("", self.git("status", "--porcelain"))

    def test_an_answer_that_is_not_a_first_look_writes_nothing(self):
        self.add()
        head = self.git("rev-parse", "HEAD")
        with mock.patch.dict(os.environ, {"MOCK_LOOK_SAYS": "I could not read the files."}):
            with self.assertRaisesRegex(pa.Refused, "did not come back in a shape Garrick can use, so nothing was written"):
                self.act(verb="start", zone="Work", file="Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md")
        self.assertEqual(head, self.git("rev-parse", "HEAD"))
        self.assertEqual("", self.git("status", "--porcelain"))

    def test_a_first_look_the_wall_check_refuses_leaves_nothing_behind(self):
        import check
        self.add()
        head = self.git("rev-parse", "HEAD")
        hook = self.base / "hooks" / "pre-commit"
        line = check.report_staged([check.Finding(check.ERROR, "walls", "Catalogue 2027/Catalogue 2027.md",
                                                  "names Birch & Co (`birch`); a wall stands between acme and birch")])
        write(hook, "#!/bin/sh\ncat >&2 <<'EOF'\n%s\nEOF\nexit 1\n" % line).chmod(0o755)
        self.git("config", "core.hooksPath", str(hook.parent))
        with self.assertRaises(pa.Refused) as said:
            self.act(verb="start", zone="Work", file="Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md")
        self.assertEqual(pa.wall_refusal(self.root), str(said.exception))
        self.assertEqual(head, self.git("rev-parse", "HEAD"))
        self.assertEqual("", self.git("status", "--porcelain"))
        self.assertFalse((self.note().parent / "Needs you").exists())

    def test_the_check_finds_nothing_wrong_with_what_was_written(self):
        self.start()
        r = subprocess.run([sys.executable, str(self.root / "System" / "tools" / "check.py"), "--root", str(self.root),
                            "--json"], capture_output=True, text=True)
        found = [f for f in json.loads(r.stdout)["findings"] if "Catalogue 2027" in f["path"]]
        self.assertEqual([], found)

    def test_a_second_start_is_refused(self):
        self.start()
        with self.assertRaisesRegex(pa.Refused, "already has its first look"):
            self.act(verb="start", zone="Work", file="Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md")


class TestTheNextStep(Case):
    def setUp(self):
        super().setUp()
        self.add()
        self.act(verb="start", zone="Work", file="Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md")
        self.q = next((self.note().parent / "Needs you").glob("*.md")).relative_to(self.work).as_posix()
        self.key = "Work/Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md"

    def suggested(self):
        return pa.act(self.root, {"verb": "continue", "zone": "Work", "suggested": True,
                                  "file": "Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md"})

    def test_thats_right_keeps_the_next_step_and_continue_asks_the_request(self):
        said = self.act(verb="answer", zone="Work", file=self.q, label="That's right")
        self.assertIn("Continue in Claude starts on it", said)
        self.assertIn("| Next action | Confirm 64 pages to the printer by Friday |", self.note().read_text())
        self.assertEqual("Opened Catalogue 2027 in Claude, with your request already asked", self.suggested())
        prime = [c for c in self.calls() if "-p" in c["args"]][-1]["args"]
        self.assertEqual(LOOK["request"], prime[prime.index("-p") + 1])
        self.assertEqual(H.REQUEST_BRIEF, prime[prime.index("--append-system-prompt") + 1])
        real = os.path.realpath(str(self.drive / "Marketing" / "Catalogue 2027"))
        self.assertEqual(real, prime[prime.index("--add-dir") + 1])
        self.assertIn("--disallowedTools=Bash,Edit,Write,MultiEdit,NotebookEdit", prime)
        self.assertTrue(Y.first_looks(self.root)[self.key]["used"])
        with self.assertRaisesRegex(pa.Refused, "no suggested request waiting"):
            self.suggested()

    def test_change_it_puts_the_users_words_in_and_the_request_follows(self):
        with self.assertRaisesRegex(pa.Refused, "say what the next step is"):
            self.act(verb="answer", zone="Work", file=self.q, label="Change it")
        self.act(verb="answer", zone="Work", file=self.q, label="Change it", text="Ask Owen for the 2027 prices")
        self.assertIn("| Next action | Ask Owen for the 2027 prices |", self.note().read_text())
        self.assertEqual("Help me with the next step on Catalogue 2027: Ask Owen for the 2027 prices",
                         Y.first_looks(self.root)[self.key]["request"])

    def test_words_are_refused_on_an_answer_that_takes_none(self):
        with self.assertRaisesRegex(pa.Refused, "only Change it takes words"):
            self.act(verb="answer", zone="Work", file=self.q, label="That's right", text="something else")

    def test_a_plain_continue_reads_the_folder_too(self):
        pa.act(self.root, {"verb": "continue", "zone": "Work",
                           "file": "Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md"})
        prime = [c for c in self.calls() if "-p" in c["args"]][-1]["args"]
        self.assertEqual("Where am I on Catalogue 2027?", prime[prime.index("-p") + 1])
        self.assertIn("--add-dir", prime)


class TestStopUsingThis(Case):
    def test_the_record_is_put_away_and_brought_back(self):
        self.add()
        hub_before = (self.work / "Catalogue 2027" / "Catalogue 2027.md").read_text()
        said = self.act(verb="stop-using", zone="Work", file="Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md")
        self.assertEqual("Catalogue 2027 is put away. Its folder is as it was", said)
        self.assertFalse((self.work / "Catalogue 2027").exists())
        away = self.work / "archive" / "Catalogue 2027" / "Catalogue 2027.md"
        self.assertIn("put-away: %s" % TODAY.isoformat(), away.read_text())
        self.assertEqual("", self.git("status", "--porcelain"))
        self.assertEqual([{"zone": "Work", "project": "Catalogue 2027", "since": TODAY.isoformat()}], Y.put_away(self.root))
        html = self.page()
        self.assertIn("Catalogue 2027 is put away.", html)
        self.assertIn(htmllib.escape(json.dumps({"verb": "bring-back", "zone": "Work", "project": "Catalogue 2027"})), html)
        self.assertEqual("Catalogue 2027 is back, where it stood", self.act(verb="bring-back", zone="Work",
                                                                             project="Catalogue 2027"))
        self.assertEqual(hub_before, (self.work / "Catalogue 2027" / "Catalogue 2027.md").read_text())
        self.assertEqual("", self.git("status", "--porcelain"))
        self.assertEqual([], Y.put_away(self.root))

    def test_work_with_changes_not_saved_is_refused(self):
        self.add()
        self.note().write_text(self.note().read_text() + "\nA line not committed.\n")
        with self.assertRaisesRegex(pa.Refused, "has changes not saved yet"):
            self.act(verb="stop-using", zone="Work", file="Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md")
        self.assertTrue(self.note().is_file())


class TestThePage(Case):
    def test_home_offers_add_your_own_work_and_shows_the_suggestions(self):
        html = self.page()
        self.assertIn('data-pick="folder"', html)
        self.assertIn("Add your own work", html)
        out, props = self.scan()
        html = self.page()
        self.assertIn('id="%s"' % out["view"], html)
        self.assertIn("Your work in Shared Drive", html)
        for name in props:
            self.assertIn(htmllib.escape(name), html)
        self.assertIn("Not a piece of work", html)
        self.assertIn("Garrick read only names and dates", html)

    def test_a_yes_waits_under_start_with_one_until_started(self):
        self.add()
        html = self.page()
        self.assertIn("Start with one", html)
        self.assertIn(htmllib.escape(json.dumps({"verb": "start", "zone": "Work",
                                                 "file": "Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md"})), html)
        self.act(verb="start", zone="Work", file="Catalogue 2027/Threads/Catalogue 2027/Catalogue 2027.md")
        html = self.page()
        self.assertIn("Catalogue 2027: is this your next step?", html)
        self.assertIn("First look, made", html)
        self.assertIn('data-own="Change it"', html)


if __name__ == "__main__":
    unittest.main()
