"""Where every rule of the old `System/rules.md` lives now (#366).

    python3 -m unittest discover -s tests

`rules.md` is loaded into every session, so what only one kind of request
needs moved into the skill that runs it. This file holds the map as data: each
rule, a sentence of it, and the file that must carry it, word for word or
tighter. A rule moved without landing in its new home fails here. A rule that
two skills need stays in `rules.md`. The update test at the end shows an older
workspace ends with every moved rule in its skills.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import update  # noqa: E402

RULES = REPO / "template" / "System" / "rules.md"
HOMES = {
    "rules": RULES,
    "threads": REPO / "template" / "System" / "skills" / "threads" / "SKILL.md",
    "intake": REPO / "template" / "System" / "skills" / "intake" / "SKILL.md",
    "nurture": REPO / "template" / "System" / "skills" / "nurture" / "SKILL.md",
    "desk": REPO / "extras" / "cmux" / "desk" / "SKILL.md",
}
# Skills the update installs in the same step as the rules (update.RULE_SKILLS).
SKILL_HOMES = ("threads", "intake", "nurture", "desk")


def flat(text: str) -> str:
    return " ".join(text.split())


# (the rule, a sentence of it exactly as written, where it lives now)
MAP = [
    # Autonomy: stays
    ("autonomy: go ahead", "**Go ahead without asking:** reading, searching, creating and editing files in the zone or wiki the task is about", "rules"),
    ("autonomy: cannot undo", "Anything you cannot undo: deleting, rewriting git history", "rules"),
    ("autonomy: leaves the machine", "Anything that leaves the machine: sending, posting, sharing, publishing. Confirm what and where, every time. Yes once is not yes next time.", "rules"),
    ("autonomy: which zone", "Which zone applies, when the task does not make it obvious.", "rules"),
    ("autonomy: outside the project", "Writing outside the project the session was opened in", "rules"),
    ("autonomy: request carries its scope", "**A request carries its scope through the workflow it names.**", "rules"),
    ("autonomy: memory follows consequence", "**What you may remember follows what acting on it would do.**", "rules"),
    ("autonomy: memory origin", "`source:` and `created:`", "rules"),
    ("autonomy: memory never inbound", "anything whose only source is inbound. Propose it and ask.", "rules"),
    ("autonomy: several good ways", "name two or three, recommend one, and go ahead.", "rules"),
    # Zones and walls: stays
    ("walls: one memory", "**One memory, walled use.**", "rules"),
    ("walls: zones never mix", "**Zones never mix in storage.**", "rules"),
    ("walls: meetings wiki", "**The Meetings wiki spans every zone.**", "rules"),
    ("walls: check before use", "**Check the wall before you use a conversation.**", "rules"),
    ("walls: the refusal sentence", "A wall holds some material back from this project, so I have not used it. Nothing was written.", "rules"),
    ("walls: cross-zone", "**Cross-zone work happens only when asked**", "rules"),
    ("walls: knowledge", "**The Knowledge wiki crosses every wall.**", "rules"),
    ("walls: cannot tell", "If unsure whether a wall applies, ask.", "rules"),
    ("walls: before every commit", "**The walls are checked again before every commit.**", "rules"),
    ("walls: no-verify", "Never use `git commit --no-verify` unless the user explicitly asks.", "rules"),
    ("walls: core.hooksPath", "Git skips the hook when its `core.hooksPath` setting sends commits past it", "threads"),
    # Ways in: two stay, the procedure moves to intake
    ("ways in: inbox first", "**Everything lands in an inbox first.**", "rules"),
    ("ways in: inbox first, in full", "**Everything lands in an inbox first.** A recording as its transcript in `Wikis/Meetings/raw/inbox/`; mail and any other file in the `Inbox/` of the zone it belongs to, or in the workspace's own `Inbox/` when one address serves every zone: there its zone is settled before anything else, from its parties, confirmed. An inbox is never a project, and nothing in one is committed.", "intake"),
    ("ways in: intro", "Getting them here is fetching, done by hand, by a script or by your assistant's own connector, and it decides nothing.", "intake"),
    ("ways in: recording", "**A recording is always a conversation**, filed in Meetings.", "intake"),
    ("ways in: mail and files", "**Mail and files go where they belong:**", "intake"),
    ("ways in: a conversation", "a conversation (a mail exchange with people, notes of a call) is filed in Meetings, with its zone and parties;", "intake"),
    ("ways in: something to read", "something to read (a newsletter, an article, a report) is filed in Knowledge, with no parties. If it comes from a party's domain, ask before treating it as published;", "intake"),
    ("ways in: material for a project", "A mail the Meetings wiki keeps out goes whole into a project's `Sources/` only when the user says it is material, not a conversation.", "intake"),
    ("ways in: parties from addresses", "**Parties come from the addresses, confirmed.** A domain in the Domains column of Parties names its party, and a plus tag (`you+acme@`) is a strong hint.", "intake"),
    ("ways in: own addresses", "the people inside the forward are the ones who count. When the addresses do not settle it, or put both sides of a wall on one mail, ask.", "intake"),
    ("ways in: wall before a project", "**Check the wall before anything goes into a project.**", "rules"),
    ("ways in: wall before a project, in full", "**Check the wall before anything goes into a project.** The project's party must not be walled from the material's parties. If it is, stop, and say only the sentence under *Zones and walls*", "rules"),
    ("ways in: unsure, ask", "**Unsure of the kind, the zone, a party or the project: ask**, in one short line. Never guess across a wall.", "intake"),
    ("ways in: code never chooses", "**Code moves, parses and lists; it never chooses where a thing goes.**", "intake"),
    # Threads
    ("threads: one resume point", "**Every thread has one resume point**: the `## State of play` section of its thread note, opening with a **Resume here** block.", "rules"),
    ("threads: resume point, in full", "It says what is done, the live artifact, the next action, who it waits on and the deadline.", "threads"),
    ("threads: hub is the index", "**The hub is the project's index.** It links every thread: under `## Threads`, or under `## Finished` once it is done.", "threads"),
    ("threads: rewrite Resume here", "**Rewrite the Resume here block at the end of any session that produced a decision or a deliverable**, so that it describes now. Add a dated entry below it; keep the old entries.", "threads"),
    ("threads: finished", "**A finished thread** gets `status: done`, and its Resume here block becomes `### Outcome`: what was delivered or decided. The project hub lists it under `## Finished`.", "threads"),
    ("threads: parked", "**A parked thread** gets `status: parked`: set aside, not finished. It keeps its folder, its Resume here block and its links, and drops out of \"what's open\" until it is woken.", "threads"),
    ("threads: parked project", "**A parked project** has `status: parked` on its hub, and every thread in it is parked with it, whatever its own note says.", "threads"),
    ("threads: open actions", "**Open actions live in the zone's `Todo.md`**", "rules"),
    ("threads: open actions, in full", "An action that opens with its thread's link keeps pointing at a live thread: when a thread is renamed, its lines follow. Dates go last on the line, where Obsidian Tasks reads them.", "threads"),
    ("threads: checkpoint", "**A checkpoint is the one exception.** As the work happens, a `### Checkpoint` block under Resume here records what this session made, decided and left half done, unconfirmed and never touching the block above it; its To file lines are held there, unfiled, until the next wrap files them and removes the block. Only a wrap, a finish or an interrupt confirms anything.", "threads"),
    ("threads: deadline", "**A deadline nobody gave says so.** The Deadline row reads \"not given\" where nobody has dated the work, and \"none\" only where somebody said there is none.", "threads"),
    ("threads: memory pointer", "**If your assistant has a memory of its own**, keep one entry per live or parked thread that says where its resume point is, and nothing else, with its `source:` and `created:`. No status: the note has it. Delete the entry when the thread is finished.", "threads"),
    # Voice
    ("voice: names", "**Names are the names the work already has.** Zones, projects and threads take letters and digits, spaces, hyphens, apostrophes, `&`, and a full stop inside an acronym", "threads"),
    ("voice: spoken form", "**A name that does not say how it is said carries a spoken form.** `spoken:` in the note's frontmatter is what is heard for it", "threads"),
    ("voice: zone has no note", "A zone has no note, so a zone name has to say how it is said.", "threads"),
    ("voice: shortest name", "**Say the shortest unique name.** A thread name alone, if only one thread has it; otherwise project and thread (\"Acme, pricing\"). The zone only if two projects share a name.", "rules"),
    ("voice: more than one match", "**When a name matches more than one thing**, or a heard name is close to two entries", "rules"),
    ("voice: never guess", "ask in one line, naming the candidates. Never guess.", "rules"),
    ("voice: open X", "**\"Open X\"**: read that thread's Resume here block and answer in two sentences: where it stands, and the next action.", "threads"),
    ("voice: close or wrap", "**\"Close X\" or \"wrap X\"**, or **\"wrap it\"** for the thread in hand: rewrite its Resume here block and add the dated entry. **\"Close for the day\"**: do that for every thread worked on today.", "threads"),
    ("voice: interrupted", "**\"I'm being interrupted\"**, **\"hold this\"** or **\"hold X\"**: ask where the user is, the very next step, and anything only in their head, one at a time, the last skippable", "threads"),
    ("voice: back", "**\"Back\"** or **\"where was I\"** opens the thread on top of the stack and reads the three back; **\"back to X\"** takes X from anywhere in it. Nothing held: say so, and offer the most recent thread.", "threads"),
    ("voice: the stack", "Wrapping, parking or finishing a thread takes it off; closing the day leaves the stack as it is and names what is on it.", "threads"),
    ("voice: desk", "Where the desk skill is installed (the cmux extra), each thread has a tab of its own and the session in it holds the thread's conversation.", "desk"),
    ("voice: desk close", "\"Close X\" has that session wrap X, then closes the tab; \"close the X tab\" closes it without a wrap.", "desk"),
    ("voice: desk day", "\"Close for the day\" wraps each tab used today in its own session, then quits cmux. \"Shut everything down\" quits without wrapping. \"Start the day\" or \"restore my tabs\" brings them back, and \"what tabs are open\" lists them.", "desk"),
    ("voice: finish", "**\"Finish X\" or \"X is done\"**: close the thread for good (see Threads).", "threads"),
    ("voice: park and wake", "**\"Park X\"**: set the thread aside without finishing it. **\"Wake X\"** or **\"unpark X\"**: bring it back; so does \"open X\" on a parked thread. **\"What's parked\"**: name the parked threads.", "threads"),
    ("voice: rename and delete", "**\"Rename X to Y\"** moves the note and every link to it; **\"delete X\"**, for what should never have existed, lists what would go and acts only on the name said again.", "threads"),
    ("voice: where am I", "**\"Where am I\" or \"what's open\"**: name the live threads, most recent first; at most five when the user is listening.", "threads"),
    ("voice: fade", "**\"Fade the meetings\"**, **\"fade the library\"** or **\"what would fade\"**: write the list of wiki pages that would leave working memory, go to the archive or come back, and why, and move nothing. The first fade on a wiki stops there; after it, one yes applies exactly that list. **\"Keep X\"** keeps a wiki page in working memory for good, and proposes bringing it back if it has faded.", "nurture"),
    ("voice: mangled", "**Names arrive mangled.** Match every proper noun against Parties, People and Aliases in `System/context.md` before acting.", "rules"),
    ("voice: mangled, ask", "If a heard name is close to two entries, ask.", "rules"),  # tighter: folded into the ambiguity bullet, see below
    ("voice: aliases", "**Learn the aliases.** When you had to ask what a name meant, add the heard form to the Aliases table, with its Learned cell.", "rules"),
    ("voice: that's wrong", "**\"That's wrong, it's Y\"** stops the old value everywhere, not only where it was heard. `System/tools/correct.py` lists every live copy and on one yes fixes them all", "rules"),
    ("voice: that's wrong, raw", "A raw record is never edited; the page resting on it says it was superseded.", "rules"),
    ("voice: the ear", "**Answer for the ear when the user is listening**: when they say so, or the request came in by voice. The answer comes first, in three sentences at most. No tables, code, file paths or links read out; round the numbers. Offer the detail instead of giving it, and put anything long in a file and say where.", "rules"),
    # Files
    ("files: git holds history", "**Git holds the history.** Edit notes in place", "rules"),
    ("files: never commit across zones", "Never commit across zones", "rules"),
    ("files: deliverables dated", "**Deliverables carry their first-made date**: `YYMMDD - <name>.<ext>`.", "rules"),
    ("files: deliverables, in full", "The date never moves, so a folder sorts by when the work started. Build intermediates (`build/`, `render/`, `specs/`), scripts and a folder's `README.md` are not deliverables and keep their names.", "threads"),
    ("files: hub options", "**A hub can change two things about its project.** `layout: thread-first` keeps everything inside the threads", "threads"),
    ("files: hub options, anonymous", "`anonymous: true` makes a project whose deliverables name no other party of its zone, nor any of their people; it can be a list of further names to keep out instead.", "threads"),
    ("files: cloud folders", "**Reach a cloud-synced folder through a link in the workspace**, never its full path (`~/Library/CloudStorage/...`)", "rules"),
    ("files: re-read", "**Another session may be working here too.** Re-read a shared file (`Todo.md`, wiki index, hub note) before you add to it", "rules"),
    ("files: instruction files point", "**Instruction files point, they do not restate.** An `AGENTS.md` routes to the file that owns a fact; it never copies it.", "rules"),
    ("files: Garrick's files as shipped", "**Garrick's instruction files stay as shipped.** This file and every `AGENTS.md` are Garrick's; a rule or route of your own goes in `System/rules.local.md` or an `AGENTS.local.md`. `check.py` warns when one differs from the shipped file.", "rules"),
    ("autonomy: check warns on origin", "`check.py` warns about an entry with no origin, or only an inbound source.", "rules"),
    ("files: run the check", "**Run the check.** `python3 System/tools/check.py` tests the workspace against these rules and exits non-zero on a problem. Add `--ear` for a three-sentence answer to read aloud.", "threads"),
    ("files: raw is never edited", "**Raw is never edited.** Anything in a wiki's `raw/` is the record. Summaries go in `wiki/`.", "rules"),
    ("files: raw travels with its page", "A page that fades takes its raw record with it, into the wiki's `dormant/raw/` or `archive/raw/`, renamed and never changed.", "nurture"),
    ("files: generated", "**`System/generated/` belongs to the tools**: pages a tool rebuilds.", "rules"),
    # Secrets, Talking to me: stay
    ("secrets: by where stored", "Name a secret by where it is stored, never by value. Open a credential file only if that is the task.", "rules"),
    ("secrets: never print", "Never print, write or commit a secret.", "rules"),
    ("talking: heading", "## Talking to me", "rules"),
    ("talking: no summary", "- No summary at the end of what is already on screen. Do report what the user could not see: files changed, commands run, what failed.", "rules"),
    ("talking: look it up", "- When the answer is one lookup away, look it up instead of hedging.", "rules"),
    ("talking: estimates", "- Estimates in real units: \"twenty minutes\", \"two sessions\".", "rules"),
]

# Rules the tightening folded into a neighbour in rules.md. They have no sentence
# of their own any more, so the test names the neighbour that carries them.
FOLDED = {"voice: mangled, ask": "**When a name matches more than one thing**, or a heard name is close to two entries, ask in one line"}


class TestRulesAreKeptAndMapped(unittest.TestCase):
    def test_rules_stays_under_its_budget(self):
        text = RULES.read_text(encoding="utf-8")
        self.assertLess(len(text), 8000, "rules.md is %d characters" % len(text))

    def test_every_rule_is_where_the_map_says(self):
        texts = {name: flat(path.read_text(encoding="utf-8")) for name, path in HOMES.items()}
        for rule, snippet, home in MAP:
            wanted = FOLDED.get(rule, snippet)
            self.assertIn(flat(wanted), texts[home], "%s is not in %s" % (rule, home))

    def test_a_rule_that_moved_is_not_also_left_behind(self):
        """Moved means moved: the long form of a moved rule is not in rules.md."""
        rules = flat(RULES.read_text(encoding="utf-8"))
        for rule, snippet, home in MAP:
            if home != "rules" and len(snippet) > 120:
                self.assertNotIn(flat(snippet), rules, rule)

    def test_the_headings_the_hooks_read_are_still_there(self):
        rules = RULES.read_text(encoding="utf-8")
        for heading in ("## Autonomy", "## Zones and walls", "## Ways in", "## Threads", "## Voice", "## Files",
                        "## Secrets", "## Talking to me"):
            self.assertIn("\n" + heading + "\n", rules, heading)
        talking = rules.split("## Talking to me\n", 1)[1]
        self.assertEqual(3, len([line for line in talking.splitlines() if line.startswith("- ")]))

    def test_each_moved_block_leaves_a_pointer(self):
        rules = flat(RULES.read_text(encoding="utf-8"))
        for needle in ("`intake` skill", "`threads` skill", "`threads`, `desk` and `nurture` skills"):
            self.assertIn(needle, rules, needle)

    def test_the_skills_that_carry_rules_are_the_ones_the_update_installs_with_them(self):
        self.assertEqual({"System/skills/%s/SKILL.md" % name for name in SKILL_HOMES}, set(update.RULE_SKILLS))


class TestUpdateKeepsEveryRule(unittest.TestCase):
    """An update that replaces rules.md must not leave a rule in neither place:
    the skills that carry what it moved arrive in the same step, or the rules
    wait."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        (base / "home").mkdir()
        gitconfig = base / "gitconfig"
        gitconfig.write_text("[user]\n\tname = Test Runner\n\temail = test@example.invalid\n[commit]\n\tgpgsign = false\n")
        self.env = dict(os.environ, HOME=str(base / "home"), GIT_CONFIG_GLOBAL=str(gitconfig),
                        GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1", GARRICK_INSTALL_NO_PAGE="1",
                        GARRICK_CALLER_BUILDS_PAGE="1")
        self.patch = mock.patch.dict(os.environ, self.env)
        self.patch.start()
        self.root = base / "ws"
        run = subprocess.run([sys.executable, str(REPO / "install.py"), "--config", str(REPO / "examples" / "acme.json"),
                              "--target", str(self.root)], capture_output=True, text=True, env=self.env)
        self.assertEqual(0, run.returncode, run.stderr)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True).stdout.strip()

    def older(self, path, old_text, user_text=None):
        """`path` as an older Garrick wrote it, and then, when given, as the user changed it."""
        stamp = json.loads((self.root / "System/garrick-version.json").read_text())
        stamp["commit"] = "0000000"
        stamp["files"][path] = hashlib.sha256(old_text.encode()).hexdigest()
        (self.root / path).write_text(user_text if user_text is not None else old_text)
        self.git("add", "-A")
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "--no-verify", "-m", "older " + path],
                       capture_output=True)
        (self.root / "System/garrick-version.json").write_text(json.dumps(stamp, indent=2) + "\n")
        self.git("add", "-A")
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "--no-verify", "-m", "stamp"], capture_output=True)

    def moved_rules_in_the_workspace(self):
        """Every rule the map says moved to a skill, found in the workspace's own skills."""
        installed = {name: flat((self.root / "System" / "skills" / name / "SKILL.md").read_text(encoding="utf-8"))
                     for name in ("threads", "intake", "nurture")}
        return [rule for rule, snippet, home in MAP if home in installed and flat(snippet) not in installed[home]]

    def test_an_older_workspace_ends_with_every_moved_rule_in_its_skills(self):
        old_rules = "# Rules\n\nThe old rules, with the procedures in them.\n"
        self.older("System/rules.md", old_rules)
        for name in ("threads", "intake", "nurture"):
            self.older("System/skills/%s/SKILL.md" % name, "---\nname: %s\n---\n\nOlder %s.\n" % (name, name))
        self.assertEqual(sorted(r for r, _, h in MAP if h in ("threads", "intake", "nurture")),
                         sorted(r for r in self.moved_rules_in_the_workspace()))      # none of them there yet
        # Naming only the rules is enough: the skills arrive with it.
        result = update.apply(self.root, update.plan(self.root), only=["System/rules.md"])
        self.assertIn("System/rules.md", result["done"]["replace"])
        for name in ("threads", "intake", "nurture"):
            self.assertIn("System/skills/%s/SKILL.md" % name, result["done"]["replace"])
        self.assertEqual([], self.moved_rules_in_the_workspace())
        self.assertEqual(RULES.read_bytes(), (self.root / "System/rules.md").read_bytes())
        self.assertEqual(1, len(self.git("log", "--format=%h", "-1", "--", "System/rules.md").split()))
        self.assertEqual(self.git("log", "--format=%h", "-1", "--", "System/rules.md"),
                         self.git("log", "--format=%h", "-1", "--", "System/skills/threads/SKILL.md"))  # one commit

    def test_a_skill_you_changed_holds_the_rules_back_until_it_is_merged(self):
        self.older("System/rules.md", "# Rules, older\n")
        self.older("System/skills/threads/SKILL.md", "---\nname: threads\n---\n\nOlder.\n",
                   "---\nname: threads\n---\n\nOlder, and mine.\n")
        for name in ("intake", "nurture"):
            self.older("System/skills/%s/SKILL.md" % name, "---\nname: %s\n---\n\nOlder.\n" % name)
        before = (self.root / "System/rules.md").read_text()
        result = update.apply(self.root, update.plan(self.root))
        self.assertEqual(before, (self.root / "System/rules.md").read_text())         # not replaced
        self.assertTrue(any(path == "System/rules.md" and "merge or commit them" in why
                            for path, why in result["skipped"]), result["skipped"])
        self.assertTrue((self.root / "System/skills/threads/SKILL.md.new").is_file())  # Garrick's skill, beside yours
        self.assertIn("The rules behind the commands", (self.root / "System/skills/threads/SKILL.md.new").read_text())
        # Merged (taken as Garrick's), the next run writes the rules.
        (self.root / "System/skills/threads/SKILL.md").write_bytes(HOMES["threads"].read_bytes())
        (self.root / "System/skills/threads/SKILL.md.new").unlink()
        self.git("add", "-A")
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "--no-verify", "-m", "merged"], capture_output=True)
        update.apply(self.root, update.plan(self.root))
        self.assertEqual(RULES.read_bytes(), (self.root / "System/rules.md").read_bytes())
        self.assertEqual([], self.moved_rules_in_the_workspace())


if __name__ == "__main__":
    unittest.main()
