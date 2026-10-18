"""Tests for the worked example, examples/example-work/build.py, and the tool
that puts it away, System/tools/example.py.

    python3 -m unittest discover -s tests

Builds Robin Hale's work at Ashgrove Furniture twice: as a new workspace of its
own, and added by `install.py --example` to a workspace with parties of its
own (Acme Corp and Birch & Co, as in examples/acme.json). Its dates are
relative to the day it is built, so these tests build it on a day they choose
and check structure and wording, never commit hashes. Every name is invented.
"""

from __future__ import annotations

import datetime
import hashlib
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
HERE = REPO / "examples" / "example-work"
BUILD = HERE / "build.py"
INSTALL = REPO / "install.py"
ACME = REPO / "examples" / "acme.json"
TOOLS = REPO / "template" / "System" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from garrick_lib import load_context, parse_frontmatter, work_folder  # noqa: E402

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
ENV.pop("GIT_DIR", None)
TODAY = datetime.date(2026, 10, 20)          # a Tuesday
DRIVE = "Ashgrove Shared"
WORK = {  # project: (thread, folder in the drive)
    "Arc chair launch": ("Launch campaign", "Marketing/Arc chair launch"),
    "Larchmont delivery problem": ("Replacement desks", "Customer service/Larchmont delivery problem"),
    "Westbrook University tender": ("Pitch", "Sales/Westbrook University tender"),
    "Dealer price list 2027": ("New prices", "Finance/Dealer price list"),
    "Spring trade show": ("Stand", "Marketing/Spring trade show"),
}
MOST_RECENT_FIRST = ["Arc chair launch", "Larchmont delivery problem", "Westbrook University tender",
                     "Dealer price list 2027", "Spring trade show"]


def run(args, cwd=None):
    return subprocess.run([str(a) for a in args], cwd=str(cwd) if cwd else None, env=ENV,
                          capture_output=True, text=True)


def check(root):
    res = run([sys.executable, Path(root) / "System" / "tools" / "check.py", "--root", root, "--json"])
    return res, json.loads(res.stdout or "{}")


def example(root, *args):
    return run([sys.executable, Path(root) / "System" / "tools" / "example.py", "--root", root, *args])


def git(root, *args):
    return run(["git", "-C", root, *args]).stdout.strip()


def tree(folder):
    """{path: sha256} of every file under a folder, .git included: what moving
    a folder away and back has to leave exactly as it was."""
    out = {}
    folder = Path(folder)
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            out[path.relative_to(folder).as_posix()] = "link:" + os.readlink(str(path))
        elif path.is_file():
            out[path.relative_to(folder).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def builder():
    spec = importlib.util.spec_from_file_location("garrick_example_build_test", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resume_rows(note):
    """The rows of a thread note's Resume here table: {label: value}."""
    text = Path(note).read_text(encoding="utf-8")
    block = text.split("### Resume here", 1)[1].split("\n---", 1)[0]
    return {m.group(1).strip(): m.group(2).strip() for m in re.finditer(r"^\| ([^|]+) \| (.+) \|$", block, re.M)
            if m.group(1).strip()}


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class StandaloneExampleTest(unittest.TestCase):
    """A new workspace with nothing in it but the example, built on a Tuesday."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name).resolve() / "example"
        cls.result = run([sys.executable, BUILD, "--target", cls.root, "--today", TODAY.isoformat()])
        cls.zone = cls.root / "Zones" / "Example"
        cls.d = builder().dates(TODAY)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr + self.result.stdout)

    def thread_note(self, project):
        thread = WORK[project][0]
        return self.zone / project / "Threads" / thread / (thread + ".md")

    def test_check_is_clean(self):
        res, report = check(self.root)
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual((report["errors"], report["warnings"]), (0, 0), res.stdout)

    def test_five_pieces_of_work_each_a_project_with_one_thread(self):
        projects = sorted(p.name for p in self.zone.iterdir() if p.is_dir() and not p.name.startswith((".", "Inbox")))
        self.assertEqual(sorted(WORK), projects)
        for project, (thread, folder) in WORK.items():
            hub = parse_frontmatter(self.zone / project / (project + ".md"))
            self.assertEqual(("project", "Example", "ashgrove", "active"),
                             (hub["type"], hub["zone"], hub["party"], hub["status"]), project)
            threads = [t.name for t in (self.zone / project / "Threads").iterdir() if t.is_dir()]
            self.assertEqual([thread], threads, project)
            self.assertEqual("%s/%s" % (DRIVE, folder), hub["folder"], project)
            self.assertTrue(work_folder(self.root, hub["folder"]).is_dir(), project)

    def test_most_recent_first_arc_chair_on_top_and_the_trade_show_quiet(self):
        updated = {p: parse_frontmatter(self.thread_note(p))["updated"] for p in WORK}
        order = sorted(WORK, key=lambda p: updated[p], reverse=True)
        self.assertEqual(MOST_RECENT_FIRST, order)
        self.assertEqual(self.d["last"].isoformat(), updated["Arc chair launch"])
        quiet = TODAY - datetime.date.fromisoformat(updated["Spring trade show"])
        self.assertGreaterEqual(quiet.days, 21)
        for p in WORK:
            self.assertEqual(updated[p], parse_frontmatter(self.zone / p / (p + ".md"))["updated"], p)

    def test_resume_points(self):
        rows = {p: resume_rows(self.thread_note(p)) for p in WORK}
        for p, r in rows.items():
            for label in ("Live artifact", "Next action", "Waiting on", "Deadline"):
                self.assertIn(label, r, p)
        waiting = {p for p, r in rows.items() if r["Waiting on"].lower() != "nobody"}
        self.assertEqual({"Dealer price list 2027"}, waiting)
        self.assertIn("Nadia", rows["Dealer price list 2027"]["Waiting on"])
        arc = rows["Arc chair launch"]
        self.assertIn("launch email", arc["Next action"].lower())
        self.assertIn("pricing", arc["Next action"].lower())
        self.assertIn("Launch email draft.txt", arc["Live artifact"])

    def test_the_launch_email_stops_before_pricing(self):
        email = (self.root / DRIVE / "Marketing" / "Arc chair launch" / "Launch email draft.txt").read_text()
        before, after = email.split("PRICING", 1)
        self.assertIn("THE CHAIR", before)
        self.assertIn("[to write", after)
        self.assertNotIn("[to write", before)

    def test_one_question_in_needs_you(self):
        found = sorted(self.zone.rglob("Needs you/*.md"))
        self.assertEqual(1, len(found), found)
        q = found[0]
        self.assertEqual(self.zone / "Larchmont delivery problem" / "Threads" / "Replacement desks" / "Needs you",
                         q.parent)
        self.assertRegex(q.name, r"^\d{6} - [a-z0-9-]+\.md$")
        self.assertEqual(self.d["call"].strftime("%y%m%d"), q.name[:6])
        fm = parse_frontmatter(q)
        self.assertEqual(("question", "open", self.d["call"].isoformat()), (fm["type"], fm["status"], fm["asked"]))
        text = q.read_text(encoding="utf-8")
        self.assertIn("**Which date did you promise Carla for the replacement desks?**", text)
        options = re.findall(r"^- \[([^\]]+)\] (.+)$", text, re.M)
        self.assertEqual(2, len(options), text)
        labels = [label for label, _ in options]
        self.assertTrue(labels[0].startswith("The ") and labels[1].startswith("End of"), labels)
        # Answering sets the Next action to the option's words, so each one changes it.
        current = resume_rows(self.thread_note("Larchmont delivery problem"))["Next action"]
        for _, action in options:
            self.assertTrue(action.startswith("Send Carla the schedule for "), action)
            self.assertNotEqual(current, action)
        # Both dates were said in the call, which is in the drive.
        transcript = self.root / DRIVE / WORK["Larchmont delivery problem"][1] / (
            "Call with Carla Mendes %s.txt" % self.d["call"].isoformat())
        said = transcript.read_text(encoding="utf-8")
        tom = re.search(r"Send Carla the schedule for (.+)$", options[0][1]).group(1)
        self.assertIn("by %s" % tom, said)
        self.assertIn("at the latest", said)

    def test_what_is_owed_this_week(self):
        lines = (self.zone / "Todo.md").read_text(encoding="utf-8").split("## Done")[0].splitlines()
        owed = [l for l in lines if l.startswith("- [ ] ")]
        for line in owed:
            self.assertRegex(line, r"^- \[ \] \[\[[^\]]+\]\]: ")
        by_thread = {}
        for line in owed:
            by_thread.setdefault(re.match(r"- \[ \] \[\[([^\]]+)\]\]", line).group(1), []).append(line)
        self.assertEqual({"Launch campaign": 1, "Replacement desks": 2, "Pitch": 1},
                         {k: len(v) for k, v in by_thread.items()})
        week = []
        for line in owed:
            due = re.search(r"📅 (\d{4}-\d{2}-\d{2})$", line)
            if due is None or 0 <= (datetime.date.fromisoformat(due.group(1)) - TODAY).days < 7:
                week.append(line)
        said = " ".join(week)
        for who in ("Leo and Ines", "Carla", "Tom"):
            self.assertIn(who, said)
        email = by_thread["Launch campaign"][0]
        self.assertTrue(email.endswith("📅 " + self.d["email_due"].isoformat()), email)
        self.assertEqual(4, self.d["email_due"].weekday())          # a Friday
        self.assertEqual(3, self.d["schedule_due"].weekday())       # a Thursday

    def test_history_leads_up_to_the_previous_working_day(self):
        days = git(self.zone, "log", "--format=%ad", "--date=short").splitlines()
        self.assertEqual(self.d["last"].isoformat(), days[0])
        self.assertTrue(all(d < TODAY.isoformat() for d in days), days)
        self.assertGreaterEqual((TODAY - datetime.date.fromisoformat(days[-1])).days, 30)
        for repo in (self.root, self.zone, self.root / "Wikis"):
            self.assertEqual("", git(repo, "status", "--porcelain", "--untracked-files=all"), repo)

    def test_the_drive_is_messy_and_never_committed(self):
        drive = self.root / DRIVE
        files = [p for p in drive.rglob("*") if p.is_file()]
        self.assertTrue(18 <= len(files) <= 26, len(files))
        for folder in ("Misc", "Old - do not use", "Marketing/Brand assets"):
            self.assertTrue((drive / folder).is_dir(), folder)
        one = drive / "Marketing" / "Arc chair launch" / "Dealer one-pager Final_v3.docx"
        two = one.with_name("Dealer one-pager Final_v3 (1).docx")
        self.assertEqual(one.read_bytes(), two.read_bytes())
        self.assertTrue(one.read_bytes().startswith(b"PK"))
        self.assertTrue((drive / "Marketing" / "Spring trade show" / "Booking confirmation.pdf").read_bytes()
                        .startswith(b"%PDF-"))
        self.assertTrue(next(drive.rglob("*.png")).read_bytes().startswith(b"\x89PNG"))
        transcripts = [p.name for p in files if p.suffix == ".txt" and ("Call with" in p.name or "prep" in p.name)]
        self.assertEqual(["Call with Carla Mendes %s.txt" % self.d["call"].isoformat(),
                          "Westbrook pitch prep %s.txt" % self.d["prep"].isoformat()], sorted(transcripts))
        self.assertEqual(0, run(["git", "-C", self.root, "check-ignore", "-q", DRIVE + "/"]).returncode)
        # Nothing in the wikis: the transcripts stay in the drive, as a download leaves them.
        self.assertEqual([], [p for p in (self.root / "Wikis" / "Meetings" / "wiki").rglob("*.md")
                              if p.name not in ("index.md", "log.md")])
        # Every file's date is the day it was last saved, never the day of the build.
        stamps = {datetime.date.fromtimestamp(p.stat().st_mtime) for p in files}
        self.assertLess(max(stamps), TODAY)

    def test_the_context_rows_are_marked_for_the_example_zone(self):
        ctx = load_context(self.root)
        self.assertIn("Example", ctx["zones"])
        self.assertEqual("Example", ctx["parties"]["ashgrove"]["zone"])
        people = (self.root / "System" / "context.md").read_text(encoding="utf-8").split("## People", 1)[1]
        for name in ("Robin Hale", "Ines Calder", "Leo Brandt", "Nadia Fenn", "Tom Ashby", "Carla Mendes"):
            self.assertIn("| %s | `ashgrove` |" % name, people)

    def test_a_folder_that_is_not_there_is_warned_about(self):
        hub = self.zone / "Spring trade show" / "Spring trade show.md"
        text = hub.read_text(encoding="utf-8")
        self.addCleanup(hub.write_text, text, encoding="utf-8")
        for value, warned in (("Ashgrove Shared/Marketing/Gone", True), (str(self.root / DRIVE), False),
                              ("Ashgrove Shared/Misc/notes.txt", True), ("", True)):
            hub.write_text(re.sub(r"(?m)^folder: .*$", "folder: " + value, text), encoding="utf-8")
            _, report = check(self.root)
            hits = [f for f in report["findings"] if f["check"] == "projects" and "`folder`" in f["message"]]
            self.assertEqual(warned, bool(hits), (value, report["findings"]))

    def test_refuses_a_second_example_and_a_full_folder(self):
        again = run([sys.executable, BUILD, "--add", self.root])
        self.assertNotEqual(0, again.returncode)
        self.assertIn("already has a zone called Example", again.stderr)
        full = run([sys.executable, BUILD, "--target", self.root])
        self.assertNotEqual(0, full.returncode)
        self.assertIn("not empty", full.stderr)


class RelativeDatesTest(unittest.TestCase):
    """The story's dates, on every day of a year: "yesterday" is a working day,
    the pieces of work keep their order, what is owed this week is due this week."""

    def test_every_day_of_a_year(self):
        b = builder()
        day = datetime.date(2026, 1, 1)
        while day.year == 2026:
            d = b.dates(day)
            v = b.fields(d)
            where = day.isoformat()
            self.assertLess(d["last"].weekday(), 5, where)
            self.assertLessEqual((day - d["last"]).days, 3, where)
            self.assertEqual(d["last"], b.working_days_before(day), where)
            self.assertEqual(7, (d["last"] - d["prep"]).days, where)
            self.assertLess(d["call"].weekday(), 5, where)
            self.assertEqual(d["call"], b.working_days_before(d["last"], 2), where)
            self.assertTrue(d["last"] > d["call"] > d["prep"] > d["dealer"] > d["spring"] > d["zone_start"], where)
            self.assertGreaterEqual((day - d["spring"]).days, 21, where)
            for key in ("spring_start", "arc_start", "dealer_start", "west_start", "larch_start"):
                self.assertGreater(d[key], d["zone_start"], (where, key))
            for key, own in (("spring_start", "spring"), ("arc_start", "last"), ("dealer_start", "dealer"),
                             ("west_start", "prep"), ("larch_start", "call"), ("photos", "last"), ("onepager", "last")):
                self.assertLess(d[key], d[own], (where, key))
            for key in ("email_due", "schedule_due"):
                self.assertTrue(0 <= (d[key] - day).days < 7, (where, key))
            self.assertGreater(d["nadia_by"], day, where)
            self.assertTrue(d["call"] < d["tom"] < d["conference"] < d["robin"], where)
            self.assertEqual(d["robin"], b.month_end(d["robin"]), where)
            month = "the end of the month" if (d["robin"].month == d["call"].month) else "the end of next month"
            self.assertEqual(month, v["robin_phrase"], where)
            self.assertGreater(d["close"], d["deck_due"], where)
            self.assertGreater(d["deck_due"], day, where)
            self.assertGreaterEqual((d["show"] - day).days, 90, where)
            self.assertEqual(str(day.year + 1), v["next_year"], where)
            day += datetime.timedelta(days=1)

    def test_a_monday_build_looks_back_to_friday(self):
        d = builder().dates(datetime.date(2026, 10, 19))
        self.assertEqual(datetime.date(2026, 10, 16), d["last"])
        self.assertEqual(datetime.date(2026, 10, 14), d["call"])
        self.assertEqual(datetime.date(2026, 10, 9), d["prep"])


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class AddedToAWorkspaceTest(unittest.TestCase):
    """`install.py --example` on a workspace with parties of its own, where
    the user then makes work of their own beside the example."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name).resolve() / "garrick"
        cls.result = run([sys.executable, INSTALL, "--config", ACME, "--target", cls.root, "--example"], cwd=REPO)
        if cls.result.returncode != 0:
            return
        # The user's own work, made alongside the example and committed.
        cls.made = run([sys.executable, cls.root / "System" / "tools" / "scaffold.py", "--root", cls.root,
                        "project", "--zone", "Work", "--name", "Acme Review", "--party", "acme",
                        "--thread", "Supplier Map"])
        note = cls.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Supplier Map" / "Supplier Map.md"
        if note.is_file():
            text = re.sub(r"\*\*Where it stands, <[^>]*>\.\*\* <[^>]*>",
                          "**Where it stands, 20 October 2026.** Asked Dana for the supplier list.", note.read_text())
            note.write_text(re.sub(r"(?m)^\| ([A-Z][a-z ]+) \| <[^>]*> \|$", r"| \1 | Not yet |", text))
        git(cls.root / "Zones" / "Work", "add", "-A")
        git(cls.root / "Zones" / "Work", "commit", "-q", "-m", "New project Acme Review")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr + self.result.stdout)
        self.assertEqual(self.made.returncode, 0, self.made.stderr)

    def snapshot(self):
        return {
            "work": tree(self.root / "Zones" / "Work"),
            "wikis": tree(self.root / "Wikis"),
            "example": tree(self.root / "Zones" / "Example"),
            "drive": tree(self.root / DRIVE),
            "context": (self.root / "System" / "context.md").read_bytes(),
            "stamp": (self.root / "System" / "garrick-version.json").read_bytes(),
            "settings": (self.root / ".claude" / "settings.json").read_bytes(),
        }

    def test_check_is_clean_beside_the_users_own_parties(self):
        res, report = check(self.root)
        self.assertEqual((report["errors"], report["warnings"]), (0, 0), res.stdout)
        ctx = load_context(self.root)
        self.assertEqual({"acme", "birch", "ashgrove"}, set(ctx["parties"]))
        self.assertIn('Bash(git -C "Zones/Example" commit:*)',
                      json.loads((self.root / ".claude" / "settings.json").read_text())["permissions"]["allow"])
        self.assertEqual("", git(self.root, "status", "--porcelain"))

    def test_archive_and_restore_leave_everything_else_as_it_was(self):
        before = self.snapshot()
        head = git(self.root / "Zones" / "Example", "rev-parse", "HEAD")
        self.assertIn('"state": "here"', example(self.root, "--json", "status").stdout)

        res = example(self.root, "archive")
        self.assertEqual(0, res.returncode, res.stderr)
        self.addCleanup(lambda: (self.root / ".archive").exists() and example(self.root, "restore"))
        self.assertFalse((self.root / "Zones" / "Example").exists())
        self.assertFalse((self.root / DRIVE).exists())
        context = (self.root / "System" / "context.md").read_text(encoding="utf-8")
        for gone in ("ashgrove", "Ashgrove", "Robin Hale", "Carla Mendes", "| Example |"):
            self.assertNotIn(gone, context)
        stamp = json.loads((self.root / "System" / "garrick-version.json").read_text())
        self.assertEqual([], [k for k in stamp["files"] if k.startswith("Zones/Example/")])
        self.assertEqual(before["work"], tree(self.root / "Zones" / "Work"))
        self.assertEqual(before["wikis"], tree(self.root / "Wikis"))
        self.assertEqual(before["settings"], (self.root / ".claude" / "settings.json").read_bytes())
        self.assertEqual("", git(self.root, "status", "--porcelain"))
        self.assertIn("put away", git(self.root, "log", "-1", "--format=%s"))
        rep_res, report = check(self.root)
        self.assertEqual((report["errors"], report["warnings"]), (0, 0), rep_res.stdout)
        status = json.loads(example(self.root, "--json", "status").stdout)
        self.assertEqual(("archived", ".archive/Example"), (status["state"], status["where"]))
        self.assertNotEqual(0, example(self.root, "archive").returncode)

        res = example(self.root, "restore")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(head, git(self.root / "Zones" / "Example", "rev-parse", "HEAD"))
        self.assertFalse((self.root / ".archive").exists())
        self.assertEqual("", git(self.root, "status", "--porcelain"))
        rep_res, report = check(self.root)
        self.assertEqual((report["errors"], report["warnings"]), (0, 0), rep_res.stdout)
        self.assertNotEqual(0, example(self.root, "restore").returncode)

    def test_uncommitted_changes_of_yours_are_left_uncommitted(self):
        path = self.root / "System" / "context.md"
        mine = path.read_text(encoding="utf-8").rstrip("\n") + "\n| acme corporation | Acme Corp |\n"
        path.write_text(mine, encoding="utf-8")
        self.addCleanup(lambda: git(self.root, "checkout", "--", "System/context.md"))
        head = git(self.root, "rev-parse", "HEAD")
        res = example(self.root, "archive")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertIn("not yet committed", res.stdout)
        self.assertEqual(head, git(self.root, "rev-parse", "HEAD"))   # the stamp waits beside your edit
        self.assertIn("| acme corporation | Acme Corp |", path.read_text(encoding="utf-8"))
        res = example(self.root, "restore")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual(mine, path.read_text(encoding="utf-8"))
        self.assertEqual(head, git(self.root, "rev-parse", "HEAD"))
        git(self.root, "checkout", "--", "System/garrick-version.json")


if __name__ == "__main__":
    unittest.main()
