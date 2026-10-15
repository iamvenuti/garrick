"""Autonomy: the cases the shipped text has to answer one way only.

    python3 -m unittest discover -s tests
    python3 tests/test_autonomy.py --cases    # the list, to run by hand

This suite is mechanical: it reads files, it cannot watch an assistant work, so
it does not pretend to. Each case below names a moment in ordinary use and says
which answer the text has to give, and the test asserts the sentence that gives
it. `GOES_AHEAD` is a moment where no question of Garrick's own may be raised;
`STILL_STOPS` is a moment where one must be.

The list doubles as the script for a measurement on a clean account: install a
fresh workspace, walk the cases in order, and count the questions, a host's own
permission prompts counted apart from Garrick's.

Nothing here touches sends. Anything that leaves the machine stops every time,
and the last cases hold the text to that.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from collections import namedtuple
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import fixtures
from test_skills import flat, section

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "template" / "System" / "skills"
TOOLS = REPO / "template" / "System" / "tools"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scaffold = _load(TOOLS / "scaffold.py", "garrick_scaffold_autonomy")
lib = _load(TOOLS / "garrick_lib.py", "garrick_lib_autonomy")

# Where a case's evidence may live. The key is what a case names; the value is
# the file, and the section of it the sentence has to be in, or None for all.
SOURCES = {
    "autonomy": (REPO / "template" / "System" / "rules.md", "## Autonomy"),
    "walls": (REPO / "template" / "System" / "rules.md", "## Zones and walls"),
    "ways in": (REPO / "template" / "System" / "rules.md", "## Ways in"),
    "voice": (REPO / "template" / "System" / "rules.md", "## Voice"),
    "threads skill": (SKILLS / "threads" / "SKILL.md", None),
    "rename": (SKILLS / "threads" / "SKILL.md", '## Rename: "rename X to Y"'),
    "new zone": (SKILLS / "threads" / "SKILL.md", '## New zone: "add a zone called X", "new zone X"'),
    "delete": (SKILLS / "threads" / "SKILL.md", '## Delete: "delete X"'),
    "intake skill": (SKILLS / "intake" / "SKILL.md", None),
    "meetings skill": (SKILLS / "meetings" / "SKILL.md", None),
    "short route": (SKILLS / "meetings" / "SKILL.md",
                    "## Nothing there yet: from an ordinary request to a saved brief"),
}

# A case: its name, what happens, and the wording that has to answer it.
# `says` is what must be there, `not_says` what must not.
Case = namedtuple("Case", "name happens where says not_says")


def case(name, happens, where, says, not_says=()):
    return Case(name, happens, where, says, not_says)


GOES_AHEAD = [
    case(
        "revise a note somebody else wrote",
        "The thread note in the project this session was opened in was last written by another "
        "session. Asked to tighten its Resume here block.",
        "autonomy",
        ["A note a zone's git history holds can be recovered, so revising one goes ahead, whoever wrote it."],
        ["overwriting a file you did not create"],
    ),
    case(
        "record what the session just did",
        "A price sheet was saved for the thread and the user said to go with the tier-two rate. "
        "The assistant writes a checkpoint into the thread note, under Resume here, without asking.",
        "threads skill",
        ["**What the user sees**: typed, one closing line, \"Checkpoint: Acme pricing, 14:32.\" "
         "Spoken, nothing at all"],
        ["ask the user whether to record"],
    ),
    case(
        "file a conversation for a project you can name",
        "A transcript of a call with Acme Corp waits in the Meetings inbox. Acme Corp is in "
        "Parties, Acme Review is its project, and the filing writes a page in a wiki, which is "
        "not the project the session was opened in.",
        "autonomy",
        ["**A request carries its scope through the workflow it names.**",
         "Filing a conversation for a project you can name authorises the writes that filing needs",
         "the wiki page, that project's notes, the zone's `Todo.md`"],
    ),
    case(
        "write the actions that filing owes to the zone's list",
        "The same filing, second step: the actions the user owes from the call go to the zone's "
        "`Todo.md`, which sits outside the project too.",
        "meetings skill",
        ["**Actions the user owes go to that zone's `Todo.md`**"],
        # The asking rule is written once, in the rules. A skill that restated it
        # here would make the question come back however the rules are worded.
        ["outside the project the session was opened in"],
    ),
    case(
        "write the brief the filing led to",
        "Asked for a brief on Acme Review from what was just filed, saved in the project.",
        "meetings skill",
        ["**Save it only when asked**", "`Zones/<Zone>/<Project>/Deliverables/YYMMDD - <name>.md`"],
        ["outside the project the session was opened in"],
    ),
    case(
        "wrap the thread the filing belonged to",
        "\"Wrap it\" at the end: the thread note is rewritten and its one Next action goes to the "
        "zone's `Todo.md`.",
        "autonomy",
        ["the zone's `Todo.md`"],
    ),
    case(
        "rename with one match",
        "\"Rename Pricing to Renewal\", and Pricing is one thread of one project.",
        "rename",
        ["**One match goes ahead**", "the instruction named it, so do not ask it back"],
        ["**Confirm in one line** before acting"],
    ),
    case(
        "prepare for a party the workspace already has",
        "\"Help me prepare my next Acme Corp call.\" Acme Corp is in Parties and Acme Review is its "
        "project, so nothing about the workspace has to change.",
        "short route",
        ["**Already a party: ask nothing.** Its project is reused",
         "It lists; it never picks."],
    ),
    case(
        "set the work up on the one yes that was already given",
        "The user said yes to adding Acme Corp as a party. The Parties row, the project, its first "
        "thread, the brief in that note and the zone's `Todo.md` line all follow from it.",
        "short route",
        ["One yes covers the Parties row, the tag, the project and the first thread.",
         "There is no second confirmation afterwards.",
         "That action is a line in the zone's `Todo.md` as well"],
        ["There is a second confirmation"],
    ),
    case(
        "add a zone with a name and a purpose",
        "\"Add a zone called Health, for appointments and records.\"",
        "new zone",
        ["**A name and what it holds is enough to go ahead**",
         "the instruction said both, so do not ask them back"],
        ["wait for the yes"],
    ),
]

STILL_STOPS = [
    case(
        "the party is not resolved",
        "A mail from personal webmail, or one carrying parties from two zones.",
        "ways in",
        ["When the addresses do not settle it, or put both sides of a wall on one mail, ask."],
    ),
    case(
        "the party is not resolved, in the skill that files it",
        "The same mail, in the procedure.",
        "intake skill",
        ["**It never guesses the kind, the zone, a party or a project.**"],
    ),
    case(
        "two projects could take it",
        "The material's party has two projects in the zone.",
        "intake skill",
        ["Several, or none: ask."],
    ),
    case(
        "a wall stands between the conversation and the project",
        "The conversation's parties are walled from the project's party.",
        "autonomy",
        ["a wall between the conversation and the project"],
    ),
    case(
        "a wall stands between them, in the rule that holds the material out",
        "The same pair, before anything is written.",
        "walls",
        ["If a wall stands between them, the material stays out"],
    ),
    case(
        "a refusal that would answer the question it refuses",
        "Asked, from inside the near-side project, whether there is anything from the other side "
        "worth knowing. The refusal holds the answer back as well as the write: the rule gives the "
        "words, so there is nothing left to paraphrase.",
        "walls",
        ['Say that a wall held something back, in these words: "A wall holds some material back from '
         'this project, so I have not used it. Nothing was written."',
         "No party, no person, no subject, no tag, and nothing that says material exists, however "
         "the question was put."],
        ["Do not say what."],
    ),
    case(
        "the name matches more than one thing",
        "\"Open pricing\", and two projects have a Pricing thread.",
        "voice",
        ["**When a name matches more than one thing**, ask in one line, naming the candidates. Never guess."],
    ),
    case(
        "the name matches more than one thread, in the procedure",
        "The same request, in the skill.",
        "threads skill",
        ["**More than one: ask in one line, naming the candidates.**"],
    ),
    case(
        "a heard name is close to one that already exists",
        "\"Rename Pricing to Renewals\" where Renewal exists; \"add a zone called Helth\" where "
        "Health exists.",
        "rename",
        ["A name close to one that already exists may mean that one: ask, naming it."],
    ),
    case(
        "a heard zone name is close to a zone that exists",
        "The same, for a zone.",
        "new zone",
        ["A heard name close to a zone that exists may mean that one: ask, naming it."],
    ),
    case(
        "the new name sounds like a sibling",
        "The rename would leave two siblings that sound alike.",
        "rename",
        ["It refuses a name that will not work, that sounds like a sibling or is taken"],
    ),
    case(
        "deleting, even when asked plainly",
        "\"Delete the test thread.\"",
        "delete",
        ['Act on deletion only on "yes, delete <X>", with the name said again; a plain "yes" is not enough.'],
    ),
    case(
        "overwriting a working copy in a shared folder",
        "The file to be written is a colleague's copy in a synced folder, with no history behind it.",
        "autonomy",
        ["overwriting a file whose content cannot be recovered",
         "a copy in a shared folder that is somebody's working file"],
    ),
    case(
        "sending the brief",
        "\"Send that to Acme.\"",
        "autonomy",
        ["Anything that leaves the machine: sending, posting, sharing, publishing. "
         "Confirm what and where, every time."],
    ),
    case(
        "sending again, to a different recipient",
        "A yes to one send is not a yes to the next.",
        "autonomy",
        ["Yes once is not yes next time."],
    ),
    case(
        "the work widens past what was asked",
        "The filing is done and another project's notes would have to change too.",
        "autonomy",
        ["Writing outside the project the session was opened in"],
    ),
    case(
        "the work widens into another zone",
        "The answer would need a second zone's material.",
        "walls",
        ["**Cross-zone work happens only when asked**"],
    ),
    case(
        "a checkpoint that disagrees with the confirmed next action",
        "The wrap finds a checkpoint written against an older resume point, and its next action is "
        "not the one the Resume here block now names.",
        "threads skill",
        ["a Next action that differs from the confirmed one is asked about"],
    ),
    case(
        "a thread nobody named",
        "A wrap that would touch a thread the request did not name.",
        "threads skill",
        ["**It never touches a thread it was not asked about.**"],
    ),
]

CASES = GOES_AHEAD + STILL_STOPS

# Words a policy engine would need and this workspace does not have. The rules
# say what to do in plain language; they keep no store of what was allowed.
NEW_VOCABULARY = ("approval matrix", "standing permission", "standing approval", "permission store",
                  "pre-approved", "pre-authorised", "pre-authorized", "scope token", "blanket consent")


def wording(where: str) -> str:
    path, heading = SOURCES[where]
    text = path.read_text(encoding="utf-8")
    return flat(text if heading is None else section(text, heading))


class CasesTest(unittest.TestCase):
    def test_every_case_names_a_source_that_exists(self):
        self.assertTrue(CASES)
        for item in CASES:
            self.assertIn(item.where, SOURCES, item.name)
            path, _ = SOURCES[item.where]
            self.assertTrue(path.exists(), item.name)

    def test_no_case_is_named_twice(self):
        names = [item.name for item in CASES]
        self.assertEqual(sorted(set(names)), sorted(names))

    def test_the_text_lets_each_of_these_go_ahead(self):
        for item in GOES_AHEAD:
            text = wording(item.where)
            for needle in item.says:
                self.assertIn(flat(needle), text, "%s: %s" % (item.name, needle))
            for gone in item.not_says:
                self.assertNotIn(flat(gone), text, "%s: %s" % (item.name, gone))

    def test_the_text_still_stops_at_each_of_these(self):
        for item in STILL_STOPS:
            text = wording(item.where)
            for needle in item.says:
                self.assertIn(flat(needle), text, "%s: %s" % (item.name, needle))
            for gone in item.not_says:
                self.assertNotIn(flat(gone), text, "%s: %s" % (item.name, gone))


class CheckpointDialogueTest(unittest.TestCase):
    """Three dialogues an assistant meets while the work is happening. Each
    runs the shipped tool over the turns and then holds the shipped text to
    what the tool leaves: the part no code can settle is the wrap, and the wrap
    is wording.

    The time is given to the tool, never taken from the clock, and the
    workspace is the fictional one in fixtures.py.
    """

    NOW = "2026-03-14T14:32:10+01:00"
    LATER = "2026-03-14T16:05:00+01:00"
    PROJECT = "Acme Review"
    THREAD = "Pricing"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = fixtures.build_workspace(Path(self._tmp.name).resolve() / "ws")
        (self.root / "System" / "templates").mkdir(parents=True, exist_ok=True)
        self.note = (self.root / "Zones" / "Work" / self.PROJECT / "Threads" / self.THREAD
                     / (self.THREAD + ".md"))
        self.todo = self.root / "Zones" / "Work" / "Todo.md"
        self.before = self.todo.read_bytes()

    # -- the tool, as the command line runs it -----------------------------

    def send(self, now=None, **fields):
        req = {"verb": "checkpoint", "zone": "Work", "project": self.PROJECT, "thread": self.THREAD}
        req.update(fields)
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(req))), redirect_stdout(out):
            code = scaffold.main(["--root", str(self.root), "checkpoint", "--now", now or self.NOW])
        return code, json.loads(out.getvalue())

    def state(self):
        _, reply = self.send(read=True)
        return reply["base"], reply["key"]

    def write(self, items, now=None, drop=None):
        base, prev = self.state()
        req = {"base": base, "items": items}
        if prev:
            req["prev"] = prev
        if drop:
            req["drop"] = drop
        code, reply = self.send(now=now, **req)
        self.assertEqual(0, code, reply)
        return reply

    def items(self, kind=None):
        block = lib.read_checkpoint(self.note.read_text(encoding="utf-8"))
        self.assertTrue(block["valid"], block["why"])
        return [i for i in block["items"] if kind is None or i["kind"] == kind]

    def wrap_wording(self):
        return flat(section((SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8"),
                            '## Wrap: "close X", "wrap X"'))

    # -- the dialogues -----------------------------------------------------

    def test_a_maybe_is_still_a_maybe_after_three_checkpoints_and_a_wrap(self):
        """User: "maybe we drop tier three." Then the sheet is saved, then
        "let's see how the volumes land". Three checkpoints later nothing has
        decided anything."""
        self.write([{"kind": "considering", "text": "dropping tier three",
                     "said": "maybe we drop tier three"}])
        self.write([{"kind": "made", "path": "Deliverables/260301 - Pricing memo.md", "at": "14:40"}],
                   now="2026-03-14T14:40:00+01:00")
        self.write([{"kind": "considering", "id": "c1", "text": "dropping tier three",
                     "said": "let's see how the volumes land"}], now=self.LATER)
        self.assertEqual([], self.items("decided"))
        line = self.items("considering")[0]["line"]
        self.assertIn("not decided", line)
        self.assertEqual(1, len(self.items("considering")))
        # Sending that item as a decision is refused by name: a decision
        # carries its own words, and nothing promotes a maybe.
        base, prev = self.state()
        code, reply = self.send(base=base, prev=prev, items=[
            {"kind": "decided", "id": "c1", "said": "maybe we drop tier three", "by": "user"}])
        self.assertEqual(1, code)
        self.assertEqual("considering", reply["refused"])
        self.assertIn("nothing promotes one", reply["say"])
        self.assertEqual(1, len(self.items("considering")))
        # And the wrap, which is wording, puts it where a maybe belongs.
        said = self.wrap_wording()
        self.assertIn('**Considering** items go to Keep in mind, as "leaning towards …, not decided"', said)
        self.assertIn("Nothing promotes one: a decision carries its own words", said)

    def test_send_it_friday_with_no_date_leaves_no_date(self):
        """User: "send it Friday" — a day of the week, not a date anybody can
        file. The line says so, and nothing invents one."""
        self.write([{"kind": "action", "text": "send Dana the price sheet",
                     "said": "send it Friday"}])
        line = self.items("action")[0]["line"]
        self.assertIn("no date given", line)
        self.assertNotIn("📅", line)
        self.assertNotIn("Friday,", line.split("send Dana")[0])
        base, prev = self.state()
        code, reply = self.send(base=base, prev=prev, items=[
            {"kind": "action", "id": "a1", "text": "send Dana the price sheet",
             "said": "send it Friday", "date": "Friday"}])
        self.assertEqual((1, "date"), (code, reply["refused"]))
        self.assertIn("ISO date", reply["say"])
        self.assertEqual(self.before, self.todo.read_bytes())            # and never the list itself
        # The two places the wording has to agree: the row that is not a
        # deadline, and the line that reaches the list.
        rules = flat(section((REPO / "template" / "System" / "rules.md").read_text(encoding="utf-8"), "## Threads"))
        self.assertIn('The Deadline row reads "not given" where nobody has dated the work, and "none" only '
                      "where somebody said there is none.", rules)
        self.assertIn("| Deadline | <date, and what breaks if it slips; none; or not given> |", self.wrap_wording())
        self.assertIn("one nobody dated goes on the list with no 📅", self.wrap_wording())

    def test_a_wrap_after_two_checkpoints_files_each_action_once(self):
        """The same action is recorded twice, once reworded, and a second
        action arrives with it. The block holds one item per action, so the
        wrap has one line each to file."""
        self.write([{"kind": "action", "text": "send Dana the price sheet",
                     "said": "I'll send Dana the sheet"}])
        self.write([{"kind": "action", "text": "send Dana the price sheet",
                     "said": "I'll send Dana the sheet"},
                    {"kind": "action", "text": "book the review with Owen",
                     "said": "and book the review with Owen"}], now=self.LATER)
        self.assertEqual(["a1", "a2"], [i["id"] for i in self.items("action")])
        self.write([{"kind": "action", "id": "a1", "text": "send Dana the price sheet and the cover note",
                     "said": "send the cover note with it"}], now=self.LATER)
        self.assertEqual(["a1", "a2"], [i["id"] for i in self.items("action")])   # reworded, not doubled
        self.assertEqual(self.before, self.todo.read_bytes())            # the tool never writes the list
        said = self.wrap_wording()
        self.assertIn("in the same commit as the `Todo.md` lines it files", said)
        self.assertIn("**To file** items are the actions for step 8, word for word, each compared with the "
                      "list as that step compares any line", said)
        todo_skill = (SKILLS / "todo" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Never the `### Checkpoint` block beside it", flat(todo_skill))


class AutonomyTest(unittest.TestCase):
    def setUp(self):
        self.rules = (REPO / "template" / "System" / "rules.md").read_text(encoding="utf-8")
        self.autonomy = section(self.rules, "## Autonomy")

    def test_the_section_keeps_its_four_stopping_conditions_in_order(self):
        """The scope sentence is an addition, not a swap: each bullet is still there,
        still in its order, so nothing was traded away for it."""
        openings = [line.split(":", 1)[0] for line in self.autonomy.splitlines() if line.startswith("- ")]
        self.assertEqual(["- Anything you cannot undo",
                          "- Anything that leaves the machine",
                          "- Which zone applies, when the task does not make it obvious.",
                          "- Writing outside the project the session was opened in"], openings)

    def test_the_undo_bullet_says_what_cannot_be_recovered(self):
        """Deleting and rewriting history stay as they were; overwriting now names the
        file it means, and the one it does not."""
        bullet = flat([line for line in self.autonomy.splitlines()
                       if line.startswith("- Anything you cannot undo")][0])
        self.assertIn("deleting, rewriting git history", bullet)
        self.assertIn("overwriting a file whose content cannot be recovered", bullet)
        self.assertIn("meaning one outside the workspace's history", bullet)
        self.assertIn("a copy in a shared folder that is somebody's working file", bullet)
        self.assertIn("revising one goes ahead, whoever wrote it", bullet)

    def test_the_scope_sentence_sits_with_what_still_stops(self):
        """One paragraph carries both halves, so neither is read without the other."""
        paragraph = flat([p for p in self.autonomy.split("\n\n")
                          if p.startswith("**A request carries its scope")][0])
        self.assertIn("the wiki page, that project's notes, the zone's `Todo.md`", paragraph)
        self.assertIn("Stop and ask as before for an unresolved party, a destination nobody has named, "
                      "or a wall between the conversation and the project.", paragraph)

    def test_the_sends_are_untouched(self):
        """Nothing here loosens what leaves the machine, and no fetch is excused from it."""
        bullet = flat([line for line in self.autonomy.splitlines()
                       if line.startswith("- Anything that leaves the machine")][0])
        self.assertEqual("- Anything that leaves the machine: sending, posting, sharing, publishing. Confirm "
                         "what and where, every time. Yes once is not yes next time.", bullet)
        for word in ("fetch", "download", "outbound"):
            self.assertNotIn(word, flat(self.autonomy).lower(), word)

    def test_no_policy_vocabulary_was_invented(self):
        """A rule in plain words, not a mechanism. Nothing keeps a record of an answer."""
        texts = {"rules": flat(self.rules).lower(),
                 "threads skill": flat((SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8")).lower()}
        for name, text in texts.items():
            for word in NEW_VOCABULARY:
                self.assertNotIn(word, text, "%s: %s" % (name, word))

    def test_the_asking_rule_is_written_in_one_place(self):
        """The skills that file a conversation carry out the writes the scope sentence
        covers; none of them restates the rule, which would bring the question back."""
        for name in ("intake", "meetings", "threads", "todo", "knowledge"):
            text = flat((SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))
            self.assertNotIn("outside the project the session was opened in", text, name)
            self.assertNotIn("Writing outside the project", text, name)

    def test_the_spoken_form_survives(self):
        """Every sentence this change added has to work read aloud: no path, no code
        span longer than a file name, no sentence over forty words."""
        added = [flat(line) for line in self.autonomy.splitlines()
                 if line.startswith("- Anything you cannot undo") or line.startswith("**A request carries")]
        self.assertEqual(2, len(added))
        for line in added:
            for sentence in re.split(r"(?<=[.:]) ", line):
                self.assertLessEqual(len(sentence.split()), 40, sentence)


class WallRefusalTest(unittest.TestCase):
    """The words a refusal uses, not only that it refuses. The rule holds one
    sentence, every route that can hit a wall quotes it, and the sentence itself
    names nothing from the far side: no party tag, no person, no subject. The demo
    workspace supplies the far side, its Acme/Birch wall standing around the two
    Cobalt Freight calls."""

    SENTENCE = ("A wall holds some material back from this project, so I have not used it. "
                "Nothing was written.")
    FIRST = "A wall holds some material back from this project, so I have not used it."
    # Every route that can meet a wall. The rule gives the words; the four that
    # refuse in their own voice quote them, and so does the demo the user watches.
    ROUTES = (REPO / "template" / "System" / "rules.md",
              SKILLS / "meetings" / "SKILL.md",
              SKILLS / "intake" / "SKILL.md",
              SKILLS / "intake" / "intake.py",
              SKILLS / "threads" / "SKILL.md",
              REPO / "examples" / "demo" / "video-script.md")
    # A sentence of the refusal's shape: it opens "A wall" and goes on to hold
    # material or something back or out. Enough to catch a wording written in the
    # obvious way, which is how all of them so far were written.
    REFUSAL_SHAPE = re.compile(r"A wall\b[^.\"]*\b(?:material|something)\b[^.\"]*\b(?:back|out)\b[^.\"]*\.")
    DEMO = REPO / "examples" / "demo"
    FAR_SIDE = (DEMO / "content" / "Wikis" / "Meetings" / "wiki" / "sources"
                / "260915-cobalt-renewal-for-acme.md")
    # What the walled conversation is about. A refusal that borrowed any of these
    # would be saying what it held back.
    SUBJECTS = ("northern lane", "fuel index", "pallet", "renewal", "freight", "percent")

    def setUp(self):
        self.walls = flat(section((REPO / "template" / "System" / "rules.md")
                                  .read_text(encoding="utf-8"), "## Zones and walls"))

    def refusal(self) -> str:
        """The sentence, read out of the rule that gives it."""
        found = re.search(r'Say that a wall held something back, in these words: "([^"]+)"', self.walls)
        self.assertIsNotNone(found, self.walls)
        return found.group(1)

    def wall_refusal_constant(self) -> str:
        """`WALL_REFUSAL` in `intake.py`, read without importing the script."""
        tree = ast.parse((SKILLS / "intake" / "intake.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "WALL_REFUSAL":
                return ast.literal_eval(node.value)
        self.fail("intake.py has no WALL_REFUSAL")

    def said_in(self, path: Path) -> str:
        """What a route says, flattened. A skill or a page as it is written; a tool as
        the strings it holds, since a literal may be wrapped mid-sentence in source."""
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            return flat(" ".join(node.value for node in ast.walk(ast.parse(text))
                                 if isinstance(node, ast.Constant) and isinstance(node.value, str)))
        return flat(text)

    def shipped_files(self):
        """Everything the user ends up with or watches: the workspace, the demo, the
        docs, the deck, the installer. Not `tests/`, which quotes the wording to hold
        routes to it, and not `CHANGELOG.md`, which quotes every wording there ever
        was."""
        for root in ("template", "examples", "docs", "presentation"):
            yield from sorted(path for path in (REPO / root).rglob("*")
                              if path.is_file() and path.suffix in (".md", ".py", ".html"))
        yield from sorted(REPO.glob("*.py"))

    def far_side_names(self) -> set:
        """Every party tag, party name and person's name the demo workspace holds."""
        config = json.loads((self.DEMO / "config.json").read_text(encoding="utf-8"))
        self.assertTrue(config["walls"])
        names = {side for wall in config["walls"] for side in (wall["between"], wall["and"])}
        for party in config["parties"]:
            names.add(party["tag"])
            names.update(word for word in re.findall(r"[A-Za-z]+", party["name"]) if len(word) > 2)
        for person in config["people"]:
            names.update(word for word in re.findall(r"[A-Za-z]+", person["name"]) if len(word) > 2)
        return names

    def test_the_rule_gives_the_words_rather_than_leaving_them_to_be_paraphrased(self):
        self.assertEqual(self.SENTENCE, self.refusal())
        self.assertTrue(self.SENTENCE.startswith(self.FIRST), self.SENTENCE)
        self.assertIn("No party, no person, no subject, no tag", self.walls)

    def test_every_route_that_can_hit_a_wall_says_the_same_sentence(self):
        """One sentence, wherever the wall is met: the rule, the brief, the filing, the
        wrap, and the demo that shows a wall holding."""
        for path in self.ROUTES:
            self.assertIn(self.SENTENCE, self.said_in(path), str(path.relative_to(REPO)))
        self.assertIn(self.SENTENCE, self.wall_refusal_constant())

    def test_a_route_cannot_arrive_with_a_wording_of_its_own(self):
        """The routes above are not a list a later change may quietly forget. Every
        shipped file is swept for a sentence of the refusal's shape, and each one found
        has to be the rule's, whole, in a file the list knows: a route added with a
        wording of its own fails here, and so does one added with the right wording and
        no entry beside the others. The sweep reads the obvious shape and no more, which
        is why the words live in the rule and not in this test."""
        strays, unlisted = [], []
        for path in self.shipped_files():
            said = self.said_in(path)
            found = self.REFUSAL_SHAPE.findall(said)
            if not found:
                continue
            where = str(path.relative_to(REPO))
            for sentence in found:
                if sentence != self.FIRST:
                    strays.append("%s says %r" % (where, sentence))
            if said.count(self.FIRST) != said.count(self.SENTENCE):
                strays.append("%s drops \"Nothing was written.\"" % where)
            if path not in self.ROUTES:
                unlisted.append(where)
        self.assertEqual([], strays)
        self.assertEqual([], unlisted)

    def test_the_sentence_names_no_far_side_party_or_person(self):
        said = self.refusal().lower()
        for name in sorted(self.far_side_names()):
            self.assertNotRegex(said, r"\b%s\b" % re.escape(name.lower()), name)
        self.assertNotIn(self.SENTENCE, self.far_side_names())

    def test_the_sentence_borrows_no_subject_from_the_walled_conversation(self):
        page = self.FAR_SIDE.read_text(encoding="utf-8").lower()
        said = self.refusal().lower()
        for subject in self.SUBJECTS:
            self.assertIn(subject, page, subject)      # still what that conversation is about
            self.assertNotIn(subject, said, subject)

    def test_the_sentence_survives_being_read_aloud_and_carries_no_tag(self):
        """Short, and nothing in it that only a rules file would print: no tag in
        backticks, no pair of tags, no link."""
        said = self.refusal()
        self.assertLessEqual(len(said.split()), 25, said)
        for mark in ("`", "[[", "/"):
            self.assertNotIn(mark, said, mark)


class ThreadsSkillTest(unittest.TestCase):
    def setUp(self):
        self.text = (SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8")

    def test_rename_keeps_its_steps_and_their_numbers(self):
        """Step 2 changed its answer, not its place: resolving first, the script third."""
        rename = section(self.text, '## Rename: "rename X to Y"')
        numbers = [line.split(".", 1)[0] for line in rename.splitlines() if re.match(r"^\d+\. ", line)]
        self.assertEqual(["1", "2", "3", "4", "5"], numbers)
        self.assertIn("1. **Resolve X.** If it could be the project or one of its threads, ask which.",
                      flat(rename))
        self.assertIn("3. **Run the script.**", flat(rename))

    def test_new_zone_keeps_its_steps_and_their_numbers(self):
        new_zone = section(self.text, '## New zone: "add a zone called X", "new zone X"')
        numbers = [line.split(".", 1)[0] for line in new_zone.splitlines() if re.match(r"^\d+\. ", line)]
        self.assertEqual(["1", "2", "3", "4"], numbers)
        flattened = flat(new_zone)
        self.assertIn("2. **Run the script.**", flattened)
        self.assertIn("If the user did not say what it holds, ask.", flattened)

    def test_delete_still_wants_the_name_said_again(self):
        """Deleting is the one of the three that cannot be undone, so it keeps its question."""
        delete = flat(section(self.text, '## Delete: "delete X"'))
        self.assertIn('ask: "Finish it, park it, or delete it?"', delete)
        self.assertIn('Act on deletion only on "yes, delete <X>", with the name said again', delete)


def print_cases() -> None:
    for title, items in (("Goes ahead", GOES_AHEAD), ("Still stops", STILL_STOPS)):
        print("\n%s\n" % title)
        for number, item in enumerate(items, 1):
            print("%2d. %s\n    %s" % (number, item.name, item.happens))


if __name__ == "__main__":
    if "--cases" in sys.argv:
        print_cases()
    else:
        unittest.main()
