"""Tests for the demo workspace, examples/demo/build.py.

    python3 -m unittest discover -s tests

Builds Sam Rivera's workspace into a temporary folder and checks what the
3-minute demo depends on: a clean check, one transcript waiting in the inbox,
four mails waiting in the Work zone's Inbox (one to read, one conversation,
one with a file for Acme Review, one that sits on both sides of the wall), and
the wall between the Acme and Birch zones holding around the two Cobalt Freight calls.
Also that the month around them keeps the workspace's own rules: person pages
say who someone is and nothing more, and every to-do line names its thread;
and that the month is moved to end on the day it is built, by whole weeks.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "examples" / "demo" / "build.py"
TOOLS = REPO / "template" / "System" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from garrick_lib import load_context, parse_frontmatter  # noqa: E402

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
REPOS = (".", "Wikis", "Zones/Work", "Zones/Birch", "Zones/Personal")


def builder():
    spec = importlib.util.spec_from_file_location("garrick_demo_build_test", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = builder()
# A Wednesday five weeks and two days after the month as written ends: every
# date moves 35 days, so nothing of the story is left in September.
TODAY = datetime.date(2026, 11, 4)
DAYS = 7 * B.weeks_for(TODAY)


def moved(text):
    """`text` as the build writes it for TODAY."""
    return B.shift_text(text, DAYS)


ACME_SIDE = moved("260915-cobalt-renewal-for-acme")
BIRCH_SIDE = moved("260922-cobalt-northern-lane-for-birch")
# What a date of the story left unmoved looks like in the demo's own record.
SEPTEMBER = re.compile(r"September|\bSept?\b|2026-09|\b2609[0-3]\d\b|\b202609[0-3]\d")


def run(args, cwd=None, env=None):
    return subprocess.run([str(a) for a in args], cwd=cwd, env=env or ENV, capture_output=True, text=True)


def build(target, today=TODAY, env=None):
    return run([sys.executable, BUILD, "--target", target, "--today", today.isoformat()], env=env)


# A scheduled job of the machine the demo is built on, failing: its heartbeat sits in the
# jobs folder the build's own environment names. A finished demo must not show it.
HOST_JOB = "zz-host-nightly"
HOST_BEAT = {"agent": False, "exit": 1, "failing_since": "2026-11-01 03:00:00", "finished": "2026-11-10 03:00:00",
             "finished_ts": 1794276000.0, "idle": False, "idle_days": 0, "items": 0, "job": HOST_JOB, "no_call": False,
             "ok": False, "quiet": False, "reason": "host job failed", "seconds": 5, "started": "2026-11-10 02:59:55"}


def check(root, *flags):
    return run([sys.executable, Path(root) / "System" / "tools" / "check.py", "--root", root, *flags])


def git(root, repo, *args):
    return run(["git", "-C", Path(root) / repo, *args]).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class DemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name).resolve()
        cls.root = cls.base / "demo"
        cls.host = cls.base / "host-jobs"
        cls.host.mkdir()
        (cls.host / (HOST_JOB + ".heartbeat.json")).write_text(json.dumps(HOST_BEAT), encoding="utf-8")
        cls.result = build(cls.root, env=dict(ENV, GARRICK_JOBS_DIR=str(cls.host), GARRICK_HOME=str(cls.base)))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_check_is_clean(self):
        res = check(self.root, "--json")
        self.assertEqual(res.returncode, 0, res.stdout)
        report = json.loads(res.stdout)
        self.assertEqual((report["errors"], report["warnings"]), (0, 0), res.stdout)
        self.assertEqual(check(self.root, "--ear").stdout.strip(), "All clear.")

    def test_page_shows_the_finished_demo(self):
        """The page a build leaves is built after the replay (#209): the demo's live threads and
        its actions are on it, with no manual rebuild."""
        page = (self.root / "System" / "generated" / "status.html").read_text(encoding="utf-8")
        for name in ("Supplier Map", "Freight Terms", "Carrier Choice", "Launch Plan", "Kitchen", "Roof Repair"):
            self.assertIn(name, page, name)
        todo = (self.root / "Zones" / "Work" / "Todo.md").read_text(encoding="utf-8")
        line = next(l for l in todo.splitlines() if l.startswith("- [ ]"))
        text = re.sub(r"^- \[ \]\s*", "", line)
        self.assertTrue(any(word in page for word in re.findall(r"[A-Za-z]{6,}", text)), line)

    def test_page_shows_no_job_of_the_machine_that_built_it(self):
        page = (self.root / "System" / "generated" / "status.html").read_text(encoding="utf-8")
        self.assertNotIn(HOST_JOB, page)
        # The same page, built with that machine's jobs folder, does show the job: the test could fail.
        out = self.base / "diagnostic.html"
        res = run([sys.executable, self.root / "System" / "status" / "status.py", "--workspace", self.root, "--out", out],
                  env=dict(ENV, GARRICK_JOBS_DIR=str(self.host), GARRICK_HOME=str(self.base)))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(HOST_JOB, out.read_text(encoding="utf-8"))

    def test_readme_names_the_page(self):
        readme = (REPO / "examples" / "demo" / "README.md").read_text(encoding="utf-8")
        self.assertIn("System/generated/status.html", readme)

    def test_inbox_holds_one_transcript(self):
        inbox = self.root / "Wikis" / "Meetings" / "raw" / "inbox"
        waiting = [p.name for p in inbox.iterdir() if not p.name.startswith(".")]
        self.assertEqual(len(waiting), 1, waiting)
        self.assertIn(Path(waiting[0]).suffix, {".txt", ".md", ".vtt"})
        # Dropped by a recorder, not yet committed: the only loose file in any repository.
        self.assertEqual(git(self.root, "Wikis", "status", "--porcelain").count("\n"), 0)
        for repo in ("Zones/Work", "Zones/Birch", "Zones/Personal", "."):
            self.assertEqual(git(self.root, repo, "status", "--porcelain"), "", repo)

    def intake(self, root, *args):
        return run([sys.executable, Path(root) / "System" / "skills" / "intake" / "intake.py", *args], cwd=root)

    def test_work_inbox_holds_four_mails(self):
        """A newsletter; Dana's forecast, placed by its domain; Owen's quote, with a file for Acme
        Review; Cobalt's notice, which copies two walled zones, so it asks."""
        res = self.intake(self.root, "list")
        self.assertEqual(res.returncode, 0, res.stderr)
        waiting = [l.split("\t") for l in res.stdout.splitlines()]
        self.assertEqual([w[0] for w in waiting], ["transcript", "mail", "mail", "mail", "mail"])
        infos = {}
        for w in waiting[1:]:
            self.assertEqual(w[1], "Work")
            res = self.intake(self.root, "parse", "--file", w[2])
            self.assertEqual(res.returncode, 0, res.stderr)
            info = json.loads(res.stdout)
            infos[info["subject"]] = info
        self.assertEqual(list(infos), ["Freight Ledger Weekly: winter surcharges arrive early", "Pallet forecast by quarter",
                                       "Second seal-kit quote", "Northern lane: winter booking window"])
        weekly = infos["Freight Ledger Weekly: winter surcharges arrive early"]
        self.assertTrue(weekly["mailing_list"])
        self.assertEqual(weekly["suggested"]["parties"], [])  # no party's domain: nothing to flag
        forecast = infos["Pallet forecast by quarter"]["suggested"]
        self.assertEqual((forecast["parties"], forecast["ask"]), (["acme"], []))
        quote = infos["Second seal-kit quote"]
        self.assertEqual((quote["suggested"]["parties"], quote["suggested"]["ask"]), (["acme"], []))
        self.assertEqual([a["name"] for a in quote["attachments"]], ["Seal kit quotes.csv"])
        notice = infos["Northern lane: winter booking window"]["suggested"]
        self.assertEqual(notice["parties"], ["acme", "birch", "cobalt"])
        self.assertEqual(len(notice["ask"]), 2)        # two walled zones, and the Birch party in the Work inbox
        self.assertIn("walled zones", notice["ask"][0])
        self.assertEqual(git(self.root, "Zones/Work", "status", "--porcelain", "--untracked-files=all"), "")

    def test_processing_the_mails_keeps_the_check_clean(self):
        """The inbox beat, as the intake skill runs it, on a copy: each item where it belongs."""
        copy = self.base / "intake"
        shutil.copytree(self.root, copy, symlinks=True)
        inbox = "Zones/Work/Inbox/"
        steps = [
            ("file-reading", "--file", inbox + "Freight Ledger Weekly.eml"),
            ("file-conversation", "--file", inbox + "Pallet forecast by quarter.eml", "--parties", "acme"),
            ("file-conversation", "--file", inbox + "Second seal-kit quote.eml", "--parties", "acme"),
            ("extract-attachment", "--mail", moved("260928-second-seal-kit-quote"), "--project", "Zones/Work/Acme Review",
             "--name", "Seal kit quotes.csv"),
            ("file-conversation", "--file", inbox + "Northern lane winter booking window.eml",
             "--parties", "acme,cobalt", "--confirmed"),            # copies two walled zones: Sam says Work, and it is split
        ]
        for step in steps:
            res = self.intake(copy, *step)
            self.assertEqual(res.returncode, 0, (step, res.stderr))
        left = self.intake(copy, "list").stdout.splitlines()
        self.assertEqual([l.split("\t")[0] for l in left], ["transcript"])  # only Theo's call is still waiting
        page = copy / "Wikis" / "Knowledge" / "wiki" / "sources" / "freight-ledger-weekly-winter-surcharges-arrive-early.md"
        self.assertNotIn("parties", parse_frontmatter(page))
        self.assertTrue((copy / "Zones/Work/Acme Review/Sources/Seal kit quotes.csv").is_file())
        # The quote is Acme's: the Birch zone is walled from it, and the notice sits in both zones.
        for mail in (moved("260928-second-seal-kit-quote"), moved("260928-northern-lane-winter-booking-window")):
            refused = self.intake(copy, "extract-attachment", "--mail", mail, "--project", "Zones/Birch/Birch Entry",
                                  "--index", "1")
            self.assertEqual(refused.returncode, 1, refused.stdout)
            self.assertIn("Zones never mix", refused.stderr)
        # The draft pages still hold what the assistant fills in; the walls and the sources are clean.
        report = json.loads(check(copy, "--json").stdout)
        self.assertEqual([], [f for f in report["findings"] if f["check"] in ("walls", "sources", "inbox", "knowledge")])
        # And the attachment commits through the zone's own wall check.
        work = copy / "Zones" / "Work"
        run(["git", "-C", work, "add", "--", "Acme Review/Sources/Seal kit quotes.csv"])
        done = run(["git", "-C", work, "commit", "-q", "-m", "Acme Review: seal-kit quotes received from Owen"])
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_history_is_the_month_before_the_build_day(self):
        start = datetime.date(2026, 9, 1) + DAYS * B.DAY
        for repo in REPOS:
            dates = [datetime.date.fromisoformat(d) for d in
                     git(self.root, repo, "log", "--format=%ad", "--date=short").splitlines()]
            self.assertTrue(all(start <= d <= TODAY for d in dates), (repo, dates))
        for repo in ("Wikis", "Zones/Work", "Zones/Birch", "Zones/Personal"):
            self.assertGreaterEqual(len(git(self.root, repo, "log", "--format=%h").splitlines()), 5, repo)

    def test_dates_move_by_whole_weeks(self):
        """Every commit lands on the weekday it was written for, the last day of the
        month is the build day or one of the six before it, and nothing of the
        story is left in September 2026."""
        self.assertEqual(DAYS % 7, 0)
        written = [when for when, _, _, _ in B.PLAN]
        got = []
        for repo in ("Wikis", "Zones/Work", "Zones/Birch", "Zones/Personal", "."):
            got += git(self.root, repo, "log", "--reverse", "--format=%ad", "--date=format:%Y-%m-%d %H:%M").splitlines()[1:]
        self.assertEqual(sorted(moved(w) for w in written), sorted(got))
        for w in written:
            then = datetime.date.fromisoformat(w.split(" ")[0])
            now = datetime.date.fromisoformat(moved(w).split(" ")[0])
            self.assertEqual((then.weekday(), (now - then).days), (now.weekday(), DAYS), w)
        inbox = self.root / "Wikis" / "Meetings" / "raw" / "inbox"
        (waiting,) = [p.name for p in inbox.iterdir() if not p.name.startswith(".")]
        last = datetime.date.fromisoformat(re.search(r"\d{4}-\d{2}-\d{2}", waiting).group(0))
        self.assertTrue(TODAY - 7 * B.DAY < last <= TODAY, last)
        self.assertEqual("Monday", B.WEEKDAYS[last.weekday()])
        stray = []
        record = [self.root / "System" / "context.md", self.root / "System" / "garrick-version.json"]
        record += [p for top in ("Zones", "Wikis") for p in (self.root / top).rglob("*")
                   if p.is_file() and ".git" not in p.parts]
        for path in record:
            rel = path.relative_to(self.root).as_posix()
            for n, line in enumerate([rel] + path.read_text(encoding="utf-8", errors="replace").splitlines()):
                if SEPTEMBER.search(line):
                    stray.append("%s:%d: %s" % (rel, n, line[:120]))
        for repo in REPOS:
            stray += [m for m in git(self.root, repo, "log", "--format=%s").splitlines() if SEPTEMBER.search(m)]
        self.assertEqual([], stray)
        # A date written in words moves with the rest, and a weekday keeps its day.
        kitchen = (self.root / "Zones/Personal/House/Threads/Kitchen/Kitchen.md").read_text(encoding="utf-8")
        self.assertIn("Monday 9 November", kitchen)          # 5 October
        self.assertIn("by the fifth of November", kitchen)   # by the first of October
        call = (inbox / waiting).read_text(encoding="utf-8")
        self.assertIn("by Friday the thirteenth", call)      # Friday the ninth
        self.assertIn("The thirteenth is fine", call)
        # Background stays put: last year's stoppages, and the months of next year's forecast.
        stoppages = (self.root / "Zones/Work/Acme Review/Sources/Pump line stoppages.csv").read_text(encoding="utf-8")
        self.assertIn("2025-03-10", stoppages)
        forecast = (self.root / "Zones/Birch/Birch Entry/Threads/Carrier Choice/Volume forecast.md").read_text(
            encoding="utf-8")
        self.assertIn("| August |", forecast)


    def test_no_birch_file_uses_the_acme_call(self):
        birch = self.root / "Zones" / "Birch" / "Birch Entry"
        users = [p for p in birch.rglob("*") if p.is_file() and ACME_SIDE in p.read_text(encoding="utf-8", errors="replace")]
        self.assertEqual(users, [])
        acme_note = self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Freight Terms" / "Freight Terms.md"
        self.assertIn(ACME_SIDE, acme_note.read_text(encoding="utf-8"))

    def test_todo_lines_name_their_thread(self):
        """Wraps and finishes find a thread's actions by the `[[Thread]]: ` that opens
        the line, so every line opens with a thread or single-thread project that
        exists, or else a party or person in the context file; and its dates are
        Obsidian Tasks fields at the end, where Tasks reads them."""
        ctx = load_context(self.root)
        names = {entry["party"] for entry in ctx["parties"].values()} | {person["name"] for person in ctx["people"]}
        for zone in ("Work", "Birch", "Personal"):
            zdir = self.root / "Zones" / zone
            notes = {p.stem for p in zdir.rglob("*.md")}
            lines = [l for l in (zdir / "Todo.md").read_text(encoding="utf-8").splitlines() if l.startswith("- [")]
            self.assertTrue(lines, zone)
            for line in lines:
                body = line[6:]
                label = re.match(r"^\[\[([^\]|]+)(?:\|[^\]]*)?\]\]: ", body)
                if label:
                    self.assertIn(label.group(1).rsplit("/", 1)[-1], notes, line)
                else:
                    self.assertIn(body.split(": ", 1)[0], names, line)
                self.assertRegex(line, r"(?:(?: (?:📅|🛫|⏳|✅) \d{4}-\d{2}-\d{2})+|[^\d])$", line)
                self.assertNotRegex(line, r"(?:📅|🛫|⏳|✅) \d{4}-\d{2}-\d{2}.*[^\d\s]+.*$", line)

    def test_person_pages_say_who_and_nothing_more(self):
        """A person page is read on both sides of every wall, so it holds who someone is
        and which party, and nothing learned in a meeting. Every meeting links its people."""
        ctx = load_context(self.root)
        wiki = self.root / "Wikis" / "Meetings" / "wiki"
        people = {p.stem: p for p in (wiki / "people").glob("*.md")}
        for page in (wiki / "sources").glob("*.md"):
            links = parse_frontmatter(page).get("people") or []
            self.assertTrue(links, page.name)
            for link in links:
                self.assertIn(link.strip("[]").split("/")[-1], people, page.name)
        self.assertEqual({p["name"] for p in ctx["people"]}, {parse_frontmatter(p)["title"] for p in people.values()})
        for slug, path in people.items():
            fm = parse_frontmatter(path)
            self.assertIn(fm.get("party"), ctx["parties"], slug)
            body = [l for l in path.read_text(encoding="utf-8").split("---", 2)[2].splitlines() if l.strip()]
            self.assertEqual(["# " + fm["title"]], body[:1], slug)
            self.assertEqual(2, len(body), slug)  # the heading, then one paragraph

    def test_check_catches_a_breach(self):
        copy = self.base / "breach"
        shutil.copytree(self.root, copy, symlinks=True)
        note = copy / "Zones" / "Birch" / "Birch Entry" / "Threads" / "Launch Plan" / "Launch Plan.md"
        with note.open("a", encoding="utf-8") as fh:
            fh.write("\nSee [[Meetings/wiki/sources/%s|the renewal call]].\n" % ACME_SIDE)
        res = check(copy, "--json")
        self.assertEqual(res.returncode, 1, res.stdout)
        walls = [f for f in json.loads(res.stdout)["findings"] if f["check"] == "walls"]
        self.assertEqual(len(walls), 1, res.stdout)
        self.assertIn(ACME_SIDE, walls[0]["message"])

        # The zone's pre-commit hook refuses the same breach before it reaches history,
        # and lets it through only when overridden on purpose.
        work = copy / "Zones" / "Birch"
        run(["git", "-C", work, "add", "-A"])
        refused = run(["git", "-C", work, "commit", "-q", "-m", "Launch plan: renewal call"])
        self.assertNotEqual(refused.returncode, 0, refused.stdout + refused.stderr)
        lines = [l for l in refused.stderr.splitlines() if l.startswith("Commit refused")]
        self.assertEqual(len(lines), 1, refused.stderr)
        self.assertIn("check.py allow", refused.stderr)             # and the command that lets it through once
        self.assertIn("Commit refused: Zones/Birch/Birch Entry/Threads/Launch Plan/Launch Plan.md", lines[0])
        self.assertNotIn("--no-verify", refused.stderr)            # no terminal: the check names the allow command instead
        self.assertEqual(git(copy, "Zones/Birch", "rev-parse", "HEAD"), git(self.root, "Zones/Birch", "rev-parse", "HEAD"))
        forced = run(["git", "-C", work, "commit", "-q", "--no-verify", "-m", "Launch plan: renewal call"])
        self.assertEqual(forced.returncode, 0, forced.stderr)

    def test_relative_target_is_relative_to_where_you_are(self):
        """And without --today, the month ends on the day it is built or in the six days before."""
        with tempfile.TemporaryDirectory() as here:
            r = run([sys.executable, BUILD, "--target", "demo-here"], cwd=here)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(here) / "demo-here" / "AGENTS.md").is_file())
            self.assertFalse((REPO / "demo-here").exists())
            inbox = Path(here) / "demo-here" / "Wikis" / "Meetings" / "raw" / "inbox"
            (waiting,) = [p.name for p in inbox.iterdir() if not p.name.startswith(".")]
            last = datetime.date.fromisoformat(re.search(r"\d{4}-\d{2}-\d{2}", waiting).group(0))
            self.assertLessEqual(0, (datetime.date.today() - last).days)
            self.assertLessEqual((datetime.date.today() - last).days, 7)

    def test_deterministic_and_refuses_a_full_folder(self):
        """Built again for the same day, minutes later, from a copy of this
        repository that has a commit of its own and an edit not committed to a
        file the install never reads: the same hashes. The installer records the source's commit and
        its edits, so a commit or an edit made while a long run went on gave the
        root a different first commit (#209)."""
        source = self.base / "source"
        shutil.copytree(REPO, source, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        who = ("-c", "user.name=Sam Rivera", "-c", "user.email=garrick@localhost", "-c", "commit.gpgsign=false")
        for args in (("init", "-q"), ("add", "-A"), who + ("commit", "-q", "-m", "A copy of Garrick")):
            done = run(["git", "-C", source, *args])
            self.assertEqual(done.returncode, 0, done.stderr)
        with (source / "AGENTS.md").open("a", encoding="utf-8") as f:
            f.write("\nAn edit not committed.\n")
        again = self.base / "again"
        res = run([sys.executable, source / "examples" / "demo" / "build.py", "--target", again,
                   "--today", TODAY.isoformat()])
        self.assertEqual(res.returncode, 0, res.stderr)
        for repo in REPOS:
            self.assertEqual(git(self.root, repo, "rev-parse", "HEAD"), git(again, repo, "rev-parse", "HEAD"), repo)
        stamp = json.loads((again / "System" / "garrick-version.json").read_text(encoding="utf-8"))
        self.assertEqual({"commit": "demo", "date": moved("2026-09-01")}, {k: stamp.get(k) for k in ("commit", "date")})
        self.assertNotIn("modified", stamp)
        res = build(again)
        self.assertEqual(res.returncode, 1)
        self.assertIn("not empty", res.stderr)


class ShiftTest(unittest.TestCase):
    """The date arithmetic alone, without a build."""

    def test_weeks_end_on_or_before_the_build_day(self):
        last = B.LAST_DAY
        for k in range(-10, 60):
            today = last + k * B.DAY
            end = last + 7 * B.weeks_for(today) * B.DAY
            self.assertTrue(today - 7 * B.DAY < end <= today, today)
            self.assertEqual(end.weekday(), last.weekday())

    def test_every_form_moves_and_keeps_its_form(self):
        days = 15 * 7   # into the next year
        cases = {
            "2026-09-28": "2027-01-11", "260915-cobalt": "261229-cobalt", "Theo Marsh call 2026-09-28.vtt":
            "Theo Marsh call 2027-01-11.vtt", "28 September 2026": "11 January 2027", "2 October": "15 January",
            "Mon, 28 Sep 2026 07:00": "Mon, 11 Jan 2027 07:00", "<20260928070000.118@x>": "<20270111070000.118@x>",
            "the fifth of October": "the eighteenth of January", "First of October": "Fourteenth of January",
            "mid-September": "mid-December", "follow in November": "follow in February",
            # Background and seasons stay as written.
            "2025-03-10": "2025-03-10", "Published June 2026": "Published June 2026", "launch in March":
            "launch in March", "Autumn 2026": "Autumn 2026", "before the first frosts": "before the first frosts",
            "The second thing": "The second thing", "in the fourth quarter": "in the fourth quarter",
        }
        for written, want in cases.items():
            self.assertEqual(want, B.shift_text(written, days), written)
        self.assertEqual("x 2026-09-28", B.shift_text("x 2026-09-28", 0))

    def test_a_day_alone_is_read_against_the_dated_line_before_it(self):
        text = ("**24 September 2026.** The map went to Dana on the 11th; samples by the ninth of October.\n"
                "Wednesday 2 September 2026. Owen: Friday. The fourth. Dana: by the eighteenth. Iris: The thirtieth, yes.\n")
        want = ("**22 October 2026.** The map went to Dana on the 9th; samples by the sixth of November.\n"
                "Wednesday 30 September 2026. Owen: Friday. The second. Dana: by the sixteenth. Iris: The twenty-eighth, yes.\n")
        self.assertEqual(want, B.shift_text(text, 28))


if __name__ == "__main__":
    unittest.main()
