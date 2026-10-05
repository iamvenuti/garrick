"""Tests for the demo workspace, examples/demo/build.py.

    python3 -m unittest discover -s tests

Builds Sam Rivera's workspace into a temporary folder and checks what the
3-minute demo depends on: a clean check, one transcript waiting in the inbox,
four mails waiting in the Work zone's Inbox (one to read, one conversation,
one with a file for Acme Review, one that sits on both sides of the wall), and
the wall between Acme and Birch holding around the two Cobalt Freight calls.
Also that the month around them keeps the workspace's own rules: person pages
say who someone is and nothing more, and every to-do line names its thread.
"""

from __future__ import annotations

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

from garrick_lib import load_context, parse_frontmatter, walled  # noqa: E402

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
ACME_SIDE = "260915-cobalt-renewal-for-acme"
BIRCH_SIDE = "260922-cobalt-northern-lane-for-birch"
REPOS = (".", "Wikis", "Zones/Work", "Zones/Personal")


def run(args, cwd=None):
    return subprocess.run([str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True)


def build(target):
    return run([sys.executable, BUILD, "--target", target])


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
        cls.result = build(cls.root)

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

    def test_inbox_holds_one_transcript(self):
        inbox = self.root / "Wikis" / "Meetings" / "raw" / "inbox"
        waiting = [p.name for p in inbox.iterdir() if not p.name.startswith(".")]
        self.assertEqual(len(waiting), 1, waiting)
        self.assertIn(Path(waiting[0]).suffix, {".txt", ".md", ".vtt"})
        # Dropped by a recorder, not yet committed: the only loose file in any repository.
        self.assertEqual(git(self.root, "Wikis", "status", "--porcelain").count("\n"), 0)
        for repo in ("Zones/Work", "Zones/Personal", "."):
            self.assertEqual(git(self.root, repo, "status", "--porcelain"), "", repo)

    def intake(self, root, *args):
        return run([sys.executable, Path(root) / "System" / "skills" / "intake" / "intake.py", *args], cwd=root)

    def test_work_inbox_holds_four_mails(self):
        """A newsletter; Dana's forecast, placed by its domain; Owen's quote, with a file for Acme
        Review; Cobalt's notice, which copies both sides of the wall, so it asks."""
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
        self.assertEqual(len(notice["ask"]), 1)
        self.assertIn("wall", notice["ask"][0])
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
            ("extract-attachment", "--mail", "260928-second-seal-kit-quote", "--project", "Zones/Work/Acme Review",
             "--name", "Seal kit quotes.csv"),
            ("file-conversation", "--file", inbox + "Northern lane winter booking window.eml",
             "--parties", "acme,birch,cobalt"),
        ]
        for step in steps:
            res = self.intake(copy, *step)
            self.assertEqual(res.returncode, 0, (step, res.stderr))
        left = self.intake(copy, "list").stdout.splitlines()
        self.assertEqual([l.split("\t")[0] for l in left], ["transcript"])  # only Theo's call is still waiting
        page = copy / "Wikis" / "Knowledge" / "wiki" / "sources" / "freight-ledger-weekly-winter-surcharges-arrive-early.md"
        self.assertNotIn("parties", parse_frontmatter(page))
        self.assertTrue((copy / "Zones/Work/Acme Review/Sources/Seal kit quotes.csv").is_file())
        # The quote is Acme's: Birch Entry is walled from it, and the notice sits on both sides.
        for mail in ("260928-second-seal-kit-quote", "260928-northern-lane-winter-booking-window"):
            refused = self.intake(copy, "extract-attachment", "--mail", mail, "--project", "Zones/Work/Birch Entry",
                                  "--index", "1")
            self.assertEqual(refused.returncode, 1, refused.stdout)
            self.assertIn("wall", refused.stderr)
        # The draft pages still hold what the assistant fills in; the walls and the sources are clean.
        report = json.loads(check(copy, "--json").stdout)
        self.assertEqual([], [f for f in report["findings"] if f["check"] in ("walls", "sources", "inbox", "knowledge")])
        # And the attachment commits through the zone's own wall check.
        work = copy / "Zones" / "Work"
        run(["git", "-C", work, "add", "--", "Acme Review/Sources/Seal kit quotes.csv"])
        done = run(["git", "-C", work, "commit", "-q", "-m", "Acme Review: seal-kit quotes received from Owen"])
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_history_is_september(self):
        for repo in REPOS:
            dates = git(self.root, repo, "log", "--format=%ad", "--date=short").splitlines()
            self.assertTrue(all(d.startswith("2026-09-") for d in dates), (repo, dates))
        for repo in ("Wikis", "Zones/Work", "Zones/Personal"):
            self.assertGreaterEqual(len(git(self.root, repo, "log", "--format=%h").splitlines()), 5, repo)

    def test_prep_for_cobalt_holds_back_the_acme_call(self):
        """Prep for Cobalt, on Birch's behalf: the Birch-side call passes, the Acme-side one is held back."""
        ctx = load_context(self.root)
        sources = self.root / "Wikis" / "Meetings" / "wiki" / "sources"
        cobalt = {p.stem: parse_frontmatter(p) for p in sources.glob("*.md")
                  if "cobalt" in parse_frontmatter(p).get("parties", [])}
        self.assertEqual(set(cobalt), {ACME_SIDE, BIRCH_SIDE})
        passed = {slug for slug, fm in cobalt.items()
                  if fm.get("zone") == "Work" and not any(walled(ctx, "birch", t) for t in fm["parties"])}
        self.assertEqual(passed, {BIRCH_SIDE})

    def test_no_birch_file_uses_the_acme_call(self):
        birch = self.root / "Zones" / "Work" / "Birch Entry"
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
        for zone in ("Work", "Personal"):
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
        note = copy / "Zones" / "Work" / "Birch Entry" / "Threads" / "Launch Plan" / "Launch Plan.md"
        with note.open("a", encoding="utf-8") as fh:
            fh.write("\nSee [[Meetings/wiki/sources/%s|the renewal call]].\n" % ACME_SIDE)
        res = check(copy, "--json")
        self.assertEqual(res.returncode, 1, res.stdout)
        walls = [f for f in json.loads(res.stdout)["findings"] if f["check"] == "walls"]
        self.assertEqual(len(walls), 1, res.stdout)
        self.assertIn(ACME_SIDE, walls[0]["message"])

        # The zone's pre-commit hook refuses the same breach before it reaches history,
        # and lets it through only when overridden on purpose.
        work = copy / "Zones" / "Work"
        run(["git", "-C", work, "add", "-A"])
        refused = run(["git", "-C", work, "commit", "-q", "-m", "Launch plan: renewal call"])
        self.assertNotEqual(refused.returncode, 0, refused.stdout + refused.stderr)
        lines = [l for l in refused.stderr.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, refused.stderr)
        self.assertIn("Commit refused: Zones/Work/Birch Entry/Threads/Launch Plan/Launch Plan.md", lines[0])
        self.assertIn("--no-verify", lines[0])
        self.assertEqual(git(copy, "Zones/Work", "rev-parse", "HEAD"), git(self.root, "Zones/Work", "rev-parse", "HEAD"))
        forced = run(["git", "-C", work, "commit", "-q", "--no-verify", "-m", "Launch plan: renewal call"])
        self.assertEqual(forced.returncode, 0, forced.stderr)

    def test_relative_target_is_relative_to_where_you_are(self):
        with tempfile.TemporaryDirectory() as here:
            r = run([sys.executable, BUILD, "--target", "demo-here"], cwd=here)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(here) / "demo-here" / "AGENTS.md").is_file())
            self.assertFalse((REPO / "demo-here").exists())

    def test_deterministic_and_refuses_a_full_folder(self):
        again = self.base / "again"
        res = build(again)
        self.assertEqual(res.returncode, 0, res.stderr)
        for repo in REPOS:
            self.assertEqual(git(self.root, repo, "rev-parse", "HEAD"), git(again, repo, "rev-parse", "HEAD"), repo)
        res = build(again)
        self.assertEqual(res.returncode, 1)
        self.assertIn("not empty", res.stderr)


if __name__ == "__main__":
    unittest.main()
