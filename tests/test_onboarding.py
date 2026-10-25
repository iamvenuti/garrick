"""The four journeys from an ordinary request to a saved brief (#99).

    python3 -m unittest discover -s tests
    python3 tests/test_onboarding.py --journeys    # the list, to walk by hand

Built like `test_autonomy.py`, and as mechanical: it reads the shipped text, so
it cannot watch an assistant work and does not pretend to. Each journey below
names what the user says, what the route must ask, what it must never ask, and
the sentence in the shipped text that answers it. A question here is a sentence
of the route that ends in a question mark, counted step by step, so a journey
that must ask nothing is a journey whose steps hold no question.

The list doubles as the script for a walk on a clean account: install a fresh
workspace, say each journey's line, and count the questions.
"""

from __future__ import annotations

import re
import sys
import unittest
from collections import namedtuple
from pathlib import Path

from test_skills import flat, section

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "template" / "System" / "skills"
MEETINGS = SKILLS / "meetings" / "SKILL.md"
ROUTE = "## Nothing there yet: from an ordinary request to a saved brief"
PREP = '## Prep: "prep me for X", "brief me for X", "prepare a brief for X"'
SCAFFOLD = REPO / "template" / "System" / "tools" / "scaffold.py"

# A journey: what is said, the state of the workspace, the steps of the route it
# walks, what it must ask, what it must not, and the wording that answers it.
Journey = namedtuple("Journey", "name said workspace steps asks never_asks says not_says")


def journey(name, said, workspace, steps, asks, never_asks, says, not_says=()):
    return Journey(name, said, workspace, steps, asks, never_asks, says, not_says)


ADD = "Shall I add it as a party"
AMBIGUOUS = ("Two of your parties are called Acme Corp: the supplier in Work, and the research client "
             "in Consulting. Which one is this call with?")
BOTH_SIDES = ("These notes mention both, and a wall stands between them. Which one is this brief for? "
              "What belongs to the other stays out.")
SECOND_HAT = ("Is this the same Acme Corp in another capacity? Shall I keep the two apart in writing, "
              "so neither ever informs the other?")

JOURNEYS = [
    journey(
        "a new party",
        "Help me prepare my next supplier call.",
        "Acme Corp is in neither Parties nor any project's hub note.",
        [1, 3, 6, 7, 8, 9],
        [ADD],
        ["a tag", "a thread name", "a mail domain", "a wall", "a person's row"],
        ["Nobody is asked for a tag, a thread name, a mail domain, a person's row, a second wall or an "
         "integration.",
         "One yes covers the Parties row, the tag, the project and the first thread.",
         "The project and the thread are named from the user's own words"],
        # Asking twice is what 0.25.0 removed: the yes is the whole permission.
        ["There is a second confirmation", "confirm again", "ask once more"],
    ),
    journey(
        "a known party",
        "Help me prepare my next call with Acme Corp.",
        "Acme Corp is a party, with the project Acme Review.",
        [1, 2],
        [],
        ["anything at all"],
        ["**Already a party: ask nothing.** Its project is reused",
         "python3 System/tools/scaffold.py party --check --name",
         "that it is already a party, with its tag, its zone and every project whose hub note names that tag"],
    ),
    journey(
        "an ambiguous party, or one organisation in two capacities",
        "Help me prepare my next Acme Corp call.",
        "Two parties are called Acme Corp, in two zones, and a wall stands between them.",
        [1, 4, 5],
        [AMBIGUOUS, BOTH_SIDES, SECOND_HAT],
        ["which one it is, of its own accord"],
        ["**Two parties of one name: ask, and never pick one.**",
         "Saying the name says nothing about which capacity is meant, so this is the user's to answer, "
         "every time, however plain the rest of the request is.",
         "It lists; it never picks.",
         "Never guess a wall, either way."],
        # Nothing may resolve the pair for the user, however it is dressed up.
        ["pick the one in", "choose the one", "default to the", "whichever is more", "assume the supplier",
         "the more recent of the two", "take the first"],
    ),
    journey(
        "an onboarding interrupted and resumed",
        "Back to that supplier call.",
        "The Parties row was written and committed yesterday; the project was not made.",
        [1, 2],
        [],
        ["anything already answered"],
        ["This step is also how the route picks itself up after an interruption.",
         "It keeps nothing of its own",
         "Nothing already answered is asked again, the party script writes no second row for a party "
         "already there, and the project script refuses a name that exists."],
        # No state of its own: re-reading plus --check, the shape park's precheck has.
        ["state file", "progress file", "journal", "onboarding.json"],
    ),
]


def route() -> str:
    """The route's section, with the blockquote markers taken off, so a question
    that wraps over two lines reads as the one sentence the user hears."""
    return re.sub(r"(?m)^[ \t]*>[ \t]?", "", section(MEETINGS.read_text(encoding="utf-8"), ROUTE))


def preamble() -> str:
    """The route's own promise, before its first numbered step."""
    return flat(re.split(r"(?m)^1\. ", route(), maxsplit=1)[0])


def steps() -> dict:
    """{number: the step's text, flattened}."""
    parts = re.split(r"(?m)^(\d+)\. ", route())
    return {int(n): flat(body) for n, body in zip(parts[1::2], parts[2::2])}


def questions(text: str) -> list:
    """Every sentence of `text` that ends in a question mark: what the route asks.
    A colon ends a sentence here too, since that is how the text introduces a
    question it then quotes."""
    return [q.strip() for q in re.findall(r"[^.?!:]*\?", text) if q.strip()]


class JourneysTest(unittest.TestCase):
    def test_four_journeys_each_named_once(self):
        self.assertEqual(4, len(JOURNEYS))
        names = [j.name for j in JOURNEYS]
        self.assertEqual(sorted(set(names)), sorted(names))

    def test_every_journey_walks_steps_the_route_has(self):
        have = steps()
        self.assertEqual(list(range(1, 11)), sorted(have), "the route's steps are not 1 to 10")
        for item in JOURNEYS:
            self.assertTrue(item.steps, item.name)
            for n in item.steps:
                self.assertIn(n, have, "%s: step %d" % (item.name, n))

    def test_the_shipped_text_answers_each_journey(self):
        whole = flat(route())
        for item in JOURNEYS:
            for needle in item.says:
                self.assertIn(flat(needle), whole, "%s: %s" % (item.name, needle))
            for gone in item.not_says:
                self.assertNotIn(flat(gone).lower(), whole.lower(), "%s: %s" % (item.name, gone))

    def test_each_journey_asks_what_it_must_and_nothing_else(self):
        """The count, step by step: every question on a journey's path is one the
        journey names, and a journey that asks nothing walks steps with none."""
        have = steps()
        for item in JOURNEYS:
            walked = " ".join(have[n] for n in item.steps)
            asked = [q for n in item.steps for q in questions(have[n])]
            if not item.asks:
                self.assertEqual([], asked, "%s asks: %s" % (item.name, asked))
                continue
            for wanted in item.asks:
                self.assertIn(flat(wanted), walked, "%s does not ask: %s" % (item.name, wanted))
            for q in asked:
                self.assertTrue([w for w in item.asks if q in flat(w) or flat(w) in q],
                                "%s asks something it should not: %s" % (item.name, q))

    def test_the_new_party_journey_asks_for_no_tag_and_no_thread_name(self):
        """The one question covers everything. Nothing on its path asks for the
        vocabulary a new user would have to learn first."""
        have = steps()
        path = [1, 3, 6, 7, 8, 9]
        asked = " ".join(q.lower() for n in path for q in questions(have[n]))
        for word in ("tag", "domain", "wall", "called", "zone is"):
            self.assertNotIn(word, asked, word)
        self.assertEqual(2, len([q for n in path for q in questions(have[n])]),
                         "the one question, in its two forms: with and without the other zone named")
        self.assertIn("isn't in your workspace yet", have[3])
        self.assertIn("which means its confidences are yours to keep", have[3])
        self.assertIn("start a Supplier call thread for it", have[3])

    def test_the_ambiguous_questions_are_shipped_word_for_word(self):
        """The wording is the deliverable: these two sentences are what the user
        hears, and nothing else may stand in for them."""
        whole = flat(route())
        for wanted in (AMBIGUOUS, BOTH_SIDES):
            self.assertIn(flat(wanted), whole, wanted)
        self.assertIn(flat(BOTH_SIDES), flat(steps()[4]))

    def test_the_route_writes_and_says_so_without_loosening_prep(self):
        """Two promises, kept apart: *Prep* reads until it is asked, this route
        writes. Neither sentence is in the other's section."""
        text = MEETINGS.read_text(encoding="utf-8")
        prep, mine = flat(section(text, PREP)), preamble()
        self.assertIn("Read-only by default", prep)
        self.assertIn("It writes a file only when the user asks to save the brief (step 7).", prep)
        self.assertIn("*Prep* promises to read and not write until it is asked, and that promise stands.", mine)
        self.assertIn("This section is not *Prep*, and makes its own", mine)
        self.assertNotIn("Read-only", mine)
        # The rule about writing outside a project is written once, in the rules.
        self.assertNotIn("outside the project the session was opened in", flat(text))

    def test_the_one_question_is_the_one_write_outside_the_project(self):
        """The Parties row is the only thing here that is not carried by the
        request, and the question in step 3 is the ask for it. No new rule."""
        mine = preamble()
        self.assertIn("bar the Parties row, which is the workspace's own file rather than the project's, "
                      "and that row is what the one question covers", mine)
        self.assertIn("There is no second confirmation afterwards.", mine)
        rules = (REPO / "template" / "System" / "rules.md").read_text(encoding="utf-8")
        autonomy = flat(section(rules, "## Autonomy"))
        self.assertIn("**A request carries its scope through the workflow it names.**", autonomy)
        self.assertIn("Writing outside the project the session was opened in", autonomy)
        for invented in ("short route", "onboarding", "just enough"):
            self.assertNotIn(invented, flat(rules).lower(), "the rules gained an exception for %s" % invented)


class RoutesTest(unittest.TestCase):
    """The route is reached from the three places that dead-ended, and nowhere
    does it become a skill of its own: a trigger phrase claimed twice is what
    `test_skills.py` refuses, and an ordinary request has no phrase to own."""

    def test_prep_sends_the_dead_end_here(self):
        prep = flat(section(MEETINGS.read_text(encoding="utf-8"), PREP))
        self.assertIn("Nothing found at all, and the request names work to prepare for: *Nothing there yet*, "
                      "below, which sets up just enough to answer it and comes back here.", prep)
        self.assertIn("Two parties of the same name: *Nothing there yet*, step 4, which is the same question.",
                      prep)

    def test_the_threads_skill_offers_it_where_a_party_is_created(self):
        new = flat(section((SKILLS / "threads" / "SKILL.md").read_text(encoding="utf-8"),
                           '## New: "new project X for P in Z", "new thread X in P"'))
        self.assertIn("the short route sets up the party, the project and the thread on one question instead: "
                      "the `meetings` skill's *Nothing there yet*", new)
        self.assertIn('scaffold.py party --name "<Party>" --zone <Zone> --what "<what it is>"', new)

    def test_setup_offers_it_instead_of_requiring_the_interview(self):
        text = (SKILLS / "setup" / "SKILL.md").read_text(encoding="utf-8")
        hand_over = flat(text).split("**Hand over.**", 1)[1].split("## ", 1)[0]
        self.assertIn("Tell me one thing you need to prepare, and I'll set up just enough to do it.", hand_over)
        self.assertIn("Or say 'interview me'", hand_over)
        self.assertIn("the `meetings` skill's *Nothing there yet*", hand_over)
        self.assertIn("the `interview` skill is the twenty minutes that sets up the whole workspace first, "
                      "and is unchanged", hand_over)

    def test_the_interview_is_untouched_and_still_has_its_own_phrases(self):
        from test_skills import triggers
        self.assertEqual({"interview me", "get to know me", "ask me about my work",
                          "help me set up my workspace", "where do i start"},
                         triggers(SKILLS / "interview"))

    def test_no_new_skill_was_added_for_this(self):
        self.assertEqual(["intake", "interview", "knowledge", "meetings", "nurture", "setup", "threads", "todo", "update"],
                         sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md")))
        # The route is reached from a procedure, so it claims no phrase of its own.
        description = MEETINGS.read_text(encoding="utf-8").split("---", 2)[1]
        for phrase in ("help me prepare", "set up just enough", "nothing there yet"):
            self.assertNotIn(phrase, description.lower(), phrase)


class CommandsTest(unittest.TestCase):
    """Every command the route gives is one the shipped script has."""

    def test_the_scaffold_verbs_the_route_names_exist(self):
        verbs = set(re.findall(r'sub\.add_parser\("(\w+)"', SCAFFOLD.read_text(encoding="utf-8")))
        self.assertIn("party", verbs)
        named = set(re.findall(r"scaffold\.py (\w+)", route()))
        self.assertTrue(named)
        for verb in named:
            self.assertIn(verb, verbs, "the route runs scaffold.py %s, which the script has no parser for" % verb)

    def test_the_party_command_takes_the_options_the_route_passes(self):
        source = SCAFFOLD.read_text(encoding="utf-8")
        for option in ('"--name"', '"--zone"', '"--what"', '"--also"', '"--walled-from"'):
            self.assertIn(option, source, option)
        self.assertIn("for each in (y, p, t, r):", source)        # party takes --check too

    def test_the_order_of_the_two_commits_is_in_the_code_as_well(self):
        """The row first, on its own: `project` is refused without it, and the two
        live in different repositories. The script says so where it reports."""
        source = SCAFFOLD.read_text(encoding="utf-8")
        self.assertIn("Commit System/context.md on its own, in the workspace's own repository at its top "
                      "folder", source)
        self.assertIn("which is refused while the row is not there", source)
        self.assertIn("is not a party tag in System/context.md", source)
        self.assertIn("git add -- System/context.md", flat(route()))


class FirstSessionTest(unittest.TestCase):
    """The page a beginner reads no longer teaches Garrick's vocabulary first."""

    def setUp(self):
        self.text = (REPO / "docs" / "first-session.md").read_text(encoding="utf-8")

    def test_the_old_request_is_gone(self):
        for gone in ("Create a project called Supplier Review in Work, for the party acme",
                     "for the party acme", "File these as notes of a conversation in Work for acme"):
            self.assertNotIn(gone, self.text, gone)

    def test_the_first_request_is_an_ordinary_one(self):
        first = self.text.split("## 1. ", 1)[1].split("\n## ", 1)[0]
        self.assertIn("> Help me prepare my next supplier call.", first)
        self.assertIn("Acme Corp isn't in your workspace yet.", first)
        self.assertIn("You are never asked to invent a tag or a thread name", first)
        self.assertIn("Which one is this call with?", first)

    def test_the_interview_is_offered_and_not_required(self):
        """It keeps its place on the page, under the short way rather than above it."""
        self.assertLess(self.text.index("## 1. Say what you need to prepare"),
                        self.text.index("Interview me."))
        self.assertIn("### Or let it interview you first", self.text)
        self.assertIn("Allow twenty minutes.", self.text)

    def test_the_brief_lands_where_the_next_session_looks(self):
        third = self.text.split("## 3. ", 1)[1].split("\n## ", 1)[0]
        self.assertIn("The brief goes into the thread note", third)
        self.assertIn("`Todo.md`", third)
        self.assertIn("offered rather than written", third)


def print_journeys() -> None:
    for number, item in enumerate(JOURNEYS, 1):
        print("%d. %s\n   Said: %s\n   Workspace: %s\n   Steps: %s\n   Asks: %s\n   Never asks: %s"
              % (number, item.name, item.said, item.workspace,
                 ", ".join(str(n) for n in item.steps),
                 "; ".join(item.asks) or "nothing", "; ".join(item.never_asks)))


if __name__ == "__main__":
    if "--journeys" in sys.argv:
        print_journeys()
    else:
        unittest.main()
