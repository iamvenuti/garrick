"""The skills folder as a whole: every skill is where the installer links it,
and no spoken trigger belongs to two skills.

    python3 -m unittest discover -s tests

Two skills answering to the same phrase would leave the assistant to pick one,
which is exactly the guess the rules forbid. "Process the inbox" belongs to
intake alone; meetings and knowledge are the procedures it calls.
"""

from __future__ import annotations

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
SKILLS = REPO / "template" / "System" / "skills"
# zsh is the macOS default and the shell an assistant's tools run there; bash the other common one.
SHELLS = ("/bin/zsh", "/bin/bash")


def description(skill: Path) -> str:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---", 2)[1]
    return head.split("description:", 1)[1]


def triggers(skill: Path) -> set:
    """The phrases in quotes in a skill's description, lower-cased, with any
    trailing punctuation dropped."""
    found = re.findall(r'"([^"]+)"', " ".join(description(skill).split()))
    return {re.sub(r"[.,;:!?]+$", "", f.strip().lower()) for f in found}


def section(text: str, heading: str) -> str:
    """A skill's section, from its heading to the next heading of the same level."""
    level = heading.split(" ", 1)[0]
    body = text.split("\n" + heading + "\n", 1)[1]
    return re.split(r"\n%s " % re.escape(level), body, maxsplit=1)[0]


def flat(text: str) -> str:
    """Text with every run of white space as one space, so wrapping never matters."""
    return " ".join(text.split())


def listing_snippet() -> str:
    """The shell lines the threads skill gives for listing every thread."""
    text = (SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8")
    after = text.split("To list every thread with its status and last update:", 1)[1]
    return re.search(r"```sh\n(.*?)```", after, re.S).group(1)


def first_value(path: Path, key: str) -> str:
    """What `grep -m1 '^key:' | cut -d' ' -f2` gives for a file."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(key + ":"):
            fields = line.split(" ")
            return fields[1] if len(fields) > 1 else ""
    return ""


class SkillsTest(unittest.TestCase):
    def skills(self):
        return sorted(p.parent for p in SKILLS.glob("*/SKILL.md"))

    def test_the_skills(self):
        self.assertEqual(["intake", "interview", "knowledge", "meetings", "threads"],
                         [p.name for p in self.skills()])

    def test_every_skill_names_itself(self):
        for skill in self.skills():
            head = (skill / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
            self.assertIn("name: %s\n" % skill.name, head, skill)

    def test_no_trigger_is_claimed_twice(self):
        owners = {}
        for skill in self.skills():
            phrases = triggers(skill)
            self.assertTrue(phrases, skill)
            for phrase in phrases:
                owners.setdefault(phrase, []).append(skill.name)
        shared = {p: o for p, o in owners.items() if len(o) > 1}
        self.assertEqual({}, shared)

    def test_intake_owns_the_inbox(self):
        for phrase in ("process the inbox", "check the inbox", "file my mail", "file this mail"):
            self.assertIn(phrase, triggers(SKILLS / "intake"), phrase)
        self.assertIn("file this transcript", triggers(SKILLS / "meetings"))
        self.assertIn("read this", triggers(SKILLS / "knowledge"))

    def test_intake_procedure_points_at_the_rules_and_the_two_memories(self):
        text = (SKILLS / "intake" / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("*Ways in*", "`meetings`", "`knowledge`", "file-reading", "file-to-project",
                       "extract-attachment", "A wall held something back.", "## What this skill does not do"):
            self.assertIn(needle, text, needle)
        rules = (REPO / "template" / "System" / "rules.md").read_text(encoding="utf-8")
        self.assertIn("## Ways in", rules)

    def test_interview_asks_first_and_builds_on_a_yes(self):
        text = (SKILLS / "interview" / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("one question at a time", "Whose confidences you hold", "System/interviews/",
                       "## Proposal", "What I still don't know", "## On a yes", "Never push",
                       "never guesses a wall", "who and what kind"):
            self.assertIn(needle.lower(), text.lower(), needle)
        self.assertEqual({"interview me", "get to know me", "ask me about my work",
                          "help me set up my workspace", "where do i start"}, triggers(SKILLS / "interview"))

    def test_meetings_files_pasted_notes(self):
        """The first session pastes notes of a call; the skill saves them as a transcript and files them."""
        for phrase in ("file these notes", "file these as notes of a conversation", "file this transcript"):
            self.assertIn(phrase, triggers(SKILLS / "meetings"), phrase)
        text = (SKILLS / "meetings" / "SKILL.md").read_text(encoding="utf-8")
        pasted = flat(section(text, "## Notes pasted in"))
        for needle in ("**Save what was pasted, unedited**", "`Wikis/Meetings/raw/inbox/<YYMMDD-slug>.txt`",
                       "not the request around them", "**Confirm date, zone and parties**",
                       "exactly as a dropped one**: *Ingest a transcript*, from step 4 on"):
            self.assertIn(needle, pasted, needle)
        missing = flat(text.split("**No transcript yet, but the user names a meeting**", 1)[1].split("\n\n", 1)[0])
        for needle in ("offer both routes", "drop the transcript in `Wikis/Meetings/raw/inbox/`",
                       "paste the notes or the transcript into the conversation (*Notes pasted in*)"):
            self.assertIn(needle, missing, needle)
        self.assertNotIn("drop the transcript in the inbox first", flat(text))

    def test_prep_is_read_only_until_asked_to_save(self):
        """The first session asks for the brief to be saved: prep writes it to Deliverables, dated, and commits it."""
        self.assertIn("prepare a brief for x", triggers(SKILLS / "meetings"))
        text = (SKILLS / "meetings" / "SKILL.md").read_text(encoding="utf-8")
        prep = flat(section(text, '## Prep: "prep me for X", "brief me for X", "prepare a brief for X"'))
        for needle in ("Read-only by default", "**Save it only when asked**",
                       "`Zones/<Zone>/<Project>/Deliverables/YYMMDD - <name>.md`", "*Files* in `System/rules.md`",
                       "Write the brief that passed step 4", "`[[Meetings/wiki/sources/<slug>|<title>]]`",
                       'git -C "Zones/<Zone>" commit', "the pre-commit hook runs the wall check on it",
                       "Saving is not sending"):
            self.assertIn(needle, prep, needle)
        for gone in ("It never writes anything", "never committed, so this check is the only one",
                     "`prep` never writes anything"):
            self.assertNotIn(gone, flat(text), gone)
        rules = section((REPO / "template" / "System" / "rules.md").read_text(encoding="utf-8"), "## Files")
        self.assertIn("`YYMMDD - <name>.<ext>`", rules)

    def test_thread_commands_survive_being_heard(self):
        """The docs tell the user to say "wrap it". Waking is "wake X" or "unpark X":
        "pick X up again" sounds like "pick up X", which opens a thread."""
        phrases = triggers(SKILLS / "threads")
        for phrase in ("wrap it", "wrap this", "wrap up", "pick up x", "wake x", "unpark x"):
            self.assertIn(phrase, phrases, phrase)
        text = flat((SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn('**No name given** ("wrap it", "wrap this", "wrap up")', text)
        self.assertIn('## Park: "park X", "put X aside"; wake: "wake X", "unpark X"',
                      (SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertNotIn("up again", text)
        rules = flat(section((REPO / "template" / "System" / "rules.md").read_text(encoding="utf-8"), "## Voice"))
        for needle in ('**"wrap it"** for the thread in hand', '**"Wake X"** or **"unpark X"**'):
            self.assertIn(needle, rules, needle)

    def test_a_new_zone_goes_through_the_scaffold(self):
        """A zone is made as the installer makes one, by the scaffold script, after
        the name and what it holds are confirmed; the interview hands over to it."""
        for phrase in ("add a zone called x", "new zone x"):
            self.assertIn(phrase, triggers(SKILLS / "threads"), phrase)
        text = (SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8")
        new_zone = flat(section(text, '## New zone: "add a zone called X", "new zone X"'))
        for needle in ('python3 System/tools/scaffold.py zone "<Zone>" --holds "<what it holds>"',
                       "**Confirm the name and what it holds**", "wait for the yes", "never `git add -A`",
                       "python3 System/tools/check.py"):
            self.assertIn(needle, new_zone, needle)
        self.assertIn("offer to add it (*New zone*, below)", flat(text))
        interview = flat((SKILLS / "interview" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("through the `threads` skill's *New zone* procedure", interview)
        for path in (SKILLS / "threads" / "SKILL.md", SKILLS / "interview" / "SKILL.md"):
            body = flat(path.read_text(encoding="utf-8"))
            self.assertNotIn("not this skill's job", body, path)
            self.assertNotIn("does not create zones", body, path)

    def test_threads_names_no_template_folders(self):
        """`_zone`, `_project` and `_thread` live only in this repository, never in a workspace."""
        text = (SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8")
        for name in ("`_zone`", "`_project`", "`_thread`"):
            self.assertNotIn(name, text, name)
        self.assertIn("A folder whose name starts with `_` is not part of the work", flat(text))

    def test_parked_threads_are_not_live(self):
        text = flat((SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8"))
        for needle in ("A thread is **live** unless its frontmatter says `status: done` (finished) or "
                       "`status: parked`", "Parked threads are not live", "Skip threads marked done or parked"):
            self.assertIn(needle, text, needle)
        self.assertNotIn("Skip threads marked done.", text)

    def test_one_todo_line_format(self):
        """Wrap and finish find a thread's open actions by the thread the line names,
        so the zone's list and every skill that writes to it use the same line."""
        writers = [REPO / "template" / "Zones" / "_zone" / "Todo.md"] + [
            SKILLS / name / "SKILL.md" for name in ("threads", "meetings", "interview")]
        for path in writers:
            lines = re.findall(r"- \[ \] <action> · .*? · <date>", flat(path.read_text(encoding="utf-8")))
            self.assertTrue(lines, path)
            self.assertEqual({"- [ ] <action> · <project>, <thread> · <date>"}, set(lines), path)
        threads = flat((SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8"))
        for needle in ("that is how a later wrap or finish finds its lines", "Touch no line that names another thread",
                       "unticked lines that name this thread"):
            self.assertIn(needle, threads, needle)

    def test_what_is_owed_comes_from_the_todo_list(self):
        """Nothing updates a meeting page's actions table once an action is done:
        what is still open is the zone's Todo.md, for a question and for a brief."""
        agents = (REPO / "template" / "AGENTS.md").read_text(encoding="utf-8")
        route = [line for line in agents.splitlines() if "what do i owe them" in line.lower()]
        self.assertEqual(1, len(route), route)
        self.assertIn("`Todo.md`", route[0])
        self.assertNotIn("Wikis/Meetings", route[0])
        self.assertIn("what was agreed at the time, not what is still open", route[0])
        text = (SKILLS / "meetings" / "SKILL.md").read_text(encoding="utf-8")
        prep = flat(section(text, '## Prep: "prep me for X", "brief me for X", "prepare a brief for X"'))
        for needle in ("from the `Todo.md` of the project's zone", "A `Todo.md` line that names a walled party",
                       "what is still open (the `Todo.md` lines)"):
            self.assertIn(needle, prep, needle)
        self.assertNotIn("from each page's actions table", prep)

    def test_no_dashes_in_the_new_prose(self):
        for path in (SKILLS / "intake" / "SKILL.md", SKILLS / "interview" / "SKILL.md",
                     SKILLS / "meetings" / "SKILL.md", SKILLS / "threads" / "SKILL.md",
                     REPO / "template" / "System" / "rules.md"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("—", text, path)
            self.assertNotIn("–", text, path)


class ThreadListingTest(unittest.TestCase):
    """The listing behind "what's open", run exactly as the threads skill gives it,
    in each shell, on a fresh install, on the demo workspace and on a few odd folders."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name).resolve()
        (base / "home").mkdir()
        env = dict(os.environ, HOME=str(base / "home"), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                   PYTHONDONTWRITEBYTECODE="1")
        cls.fresh, cls.demo, cls.odd = base / "fresh", base / "demo", base / "odd"
        cls.have_git = shutil.which("git") is not None
        if cls.have_git:
            cls.installed = subprocess.run([sys.executable, str(REPO / "install.py"), "--config",
                                            str(REPO / "examples" / "acme.json"), "--target", str(cls.fresh)],
                                           env=env, capture_output=True, text=True)
            cls.built = subprocess.run([sys.executable, str(REPO / "examples" / "demo" / "build.py"),
                                        "--target", str(cls.demo)], env=env, capture_output=True, text=True)
        cls.snippet = listing_snippet()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def listings(self, root):
        """(shell, result) for each shell this machine has: on macOS, both."""
        shells = [s for s in SHELLS if os.access(s, os.X_OK)]
        if sys.platform == "darwin":
            self.assertEqual(list(SHELLS), shells)
        if not shells:
            self.skipTest("neither zsh nor bash is installed")
        return [(s, subprocess.run([s, "-c", self.snippet], cwd=str(root), capture_output=True, text=True))
                for s in shells]

    def test_a_fresh_install_lists_nothing(self):
        if not self.have_git:
            self.skipTest("git is not installed")
        self.assertEqual(0, self.installed.returncode, self.installed.stderr)
        self.assertTrue((self.fresh / "Zones" / "Work").is_dir())
        for shell, res in self.listings(self.fresh):
            self.assertEqual((0, "", ""), (res.returncode, res.stdout, res.stderr), shell)

    def test_the_demo_lists_its_threads(self):
        if not self.have_git:
            self.skipTest("git is not installed")
        self.assertEqual(0, self.built.returncode, self.built.stderr)
        expected = []
        for note in (self.demo / "Zones").glob("*/*/Threads/*/*.md"):
            if note.stem == note.parent.name:
                rel = note.relative_to(self.demo).as_posix()
                expected.append("%s\t%s\t%s" % (first_value(note, "updated"), first_value(note, "status"), rel))
        self.assertEqual(7, len(expected), expected)
        self.assertIn("2026-09-23\tactive\tZones/Work/Birch Entry/Threads/Carrier Choice/Carrier Choice.md", expected)
        self.assertIn("2026-09-17\tdone\tZones/Work/Birch Entry/Threads/Market Sizing/Market Sizing.md", expected)
        for shell, res in self.listings(self.demo):
            lines = res.stdout.splitlines()
            self.assertEqual((0, ""), (res.returncode, res.stderr), shell)
            self.assertEqual(sorted(expected), sorted(lines), shell)
            dates = [line.split("\t", 1)[0] for line in lines]
            self.assertEqual(sorted(dates, reverse=True), dates, shell)  # newest first

    def test_underscore_folders_and_working_notes_are_left_out(self):
        """An installed workspace has no template folders under Zones/; a folder whose
        name starts with `_` is passed over, as the scripts pass over it."""
        notes = {
            "Zones/Work/Acme Review/Threads/Pricing/Pricing.md": "updated: 2026-03-02\nstatus: active\n",
            "Zones/Work/Acme Review/Threads/Pricing/Call notes.md": "updated: 2026-03-03\n",
            "Zones/Work/_project/Threads/_thread/_thread.md": "updated: 2026-03-04\n",
            "Zones/Work/_project/Threads/Kick Off/Kick Off.md": "updated: 2026-03-04\n",
            "Zones/Personal/House/Threads/Roof Repair/Roof Repair.md": "updated: 2026-03-01\nstatus: parked\n",
            "Zones/Personal/House/House.md": "updated: 2026-03-05\n",
        }
        for rel, body in notes.items():
            path = self.odd / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("---\n" + body + "---\n", encoding="utf-8")
        for shell, res in self.listings(self.odd):
            self.assertEqual((0, ""), (res.returncode, res.stderr), shell)
            self.assertEqual(["2026-03-02\tactive\tZones/Work/Acme Review/Threads/Pricing/Pricing.md",
                              "2026-03-01\tparked\tZones/Personal/House/Threads/Roof Repair/Roof Repair.md"],
                             res.stdout.splitlines(), shell)


if __name__ == "__main__":
    unittest.main()
