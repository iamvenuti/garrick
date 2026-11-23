"""extras/hooks/parked_hint.py: the UserPromptSubmit hook that says a request may belong to a parked thread (#664).

    cd tests && python3 -m unittest test_parked_hint

The workspace is a small invented one in a temporary folder, with three zones (Work and Personal walled, Studio open)
and the workspace's own System/tools linked in. Nothing reads this Mac.
"""
import itertools
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "extras" / "hooks" / "parked_hint.py"
TOOLS = REPO / "template" / "System" / "tools"

CONTEXT = """# Context

## Me

Jo Example. Works on supply chains.

## Zones

| Zone | Holds | Walled |
|---|---|---|
| Work | Client work | yes |
| Personal | Everything else | yes |
| Studio | Open projects | no |

## Parties

| Party | What it is | Zone | Tag | Domains |
|---|---|---|---|---|
| Acme Corp | Client | Work | `acme` | acme.example |
| Cedar Works | Partner | Work | `cedar` | cedar.example |
| Maple Home | Own affairs | Personal | `maple` | |
| Harbour Art | Open | Studio | `harbour` | |
"""
NAMES = """# Names

## People

| Name | Party | Role |
|---|---|---|
| Alex Birch | `cedar` | Buyer |
| Dana Whitlock | `acme` | Sponsor |

## Aliases

| Heard | Means |
|---|---|
| none | none |
"""


def note(status, party=None, spoken=None):
    fm = ["---", "type: thread", "status: " + status]
    if party:
        fm.append("party: %s" % party)
    if spoken:
        fm.append("spoken: %s" % spoken)
    return "\n".join(fm + ["---", "", "# Note", "", "Body text that the hook never reads.", ""])


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.root = self.base / "ws"
        (self.root / "System").mkdir(parents=True)
        (self.root / "System" / "rules.md").write_text("# Rules\n")
        (self.root / "System" / "context.md").write_text(CONTEXT)
        (self.root / "System" / "names.md").write_text(NAMES)
        os.symlink(str(TOOLS), str(self.root / "System" / "tools"))
        (self.root / "System" / "garrick-checks.json").write_text(json.dumps({"memory": str(self.base / "memory")}))
        (self.base / "memory").mkdir()
        self.thread("Work", "Cedar OEM", "Liveness Pricing", "parked", party="cedar")
        self.thread("Work", "Acme", "Freight", "active", party="acme")
        self.project("Work", "Acme Archive", "parked", party="acme")
        self.thread("Personal", "Home", "Roof repair", "parked", party="maple")
        self.thread("Studio", "Art", "Mural wall", "parked", party="harbour")
        self.thread("Studio", "Art", "Sketches", "active", party="harbour")

    def tearDown(self):
        self.tmp.cleanup()

    def project(self, zone, project, status, party=None):
        d = self.root / "Zones" / zone / project
        d.mkdir(parents=True, exist_ok=True)
        (d / (project + ".md")).write_text(note(status, party))
        return d

    def thread(self, zone, project, name, status, party=None, spoken=None):
        d = self.root / "Zones" / zone / project
        if not (d / (project + ".md")).exists():
            self.project(zone, project, "active", party)
        t = d / "Threads" / name
        t.mkdir(parents=True, exist_ok=True)
        (t / (name + ".md")).write_text(note(status, party, spoken))
        return t / (name + ".md")

    def fire(self, prompt, cwd=None, **event):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR",)}
        env["HOME"] = str(self.home)
        done = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(dict(
            {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "cwd": str(cwd or self.root)}, **event)),
            capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual("", done.stderr)
        return done.stdout

    def said(self, prompt, cwd=None):
        out = self.fire(prompt, cwd)
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    def where(self, *parts):
        return self.root.joinpath(*parts)


class TheHint(Workspace):
    def test_a_session_in_the_zone_is_told_of_its_parked_thread(self):
        line = self.said("draft the liveness rate note", self.where("Zones", "Work"))
        self.assertEqual("This may belong to *Cedar OEM, Liveness Pricing*, which is parked: say 'wake Cedar OEM, "
                         "Liveness Pricing' to pick it up.", line)

    def test_the_reply_is_one_claude_code_context_object(self):
        out = json.loads(self.fire("liveness pricing", self.where("Zones", "Work", "Cedar OEM")))
        self.assertEqual({"hookSpecificOutput"}, set(out))
        self.assertEqual("UserPromptSubmit", out["hookSpecificOutput"]["hookEventName"])

    def test_the_same_prompt_in_another_walled_zone_adds_nothing(self):
        self.assertEqual("", self.fire("draft the liveness rate note", self.where("Zones", "Personal")))

    def test_a_prompt_that_matches_no_parked_thread_adds_nothing(self):
        self.assertEqual("", self.fire("what is the weather", self.where("Zones", "Work")))
        self.assertEqual("", self.fire("send the freight update", self.where("Zones", "Work")))     # Freight is active

    def test_one_significant_word_of_the_name_is_a_match_in_any_case(self):
        self.assertNotEqual("", self.fire("draft the LIVENESS rate note", self.where("Zones", "Work")))
        self.assertNotEqual("", self.fire("what about pricing?", self.where("Zones", "Work")))
        self.assertEqual("", self.fire("draft the live rate note", self.where("Zones", "Work")))      # not a whole word

    def test_the_spoken_form_the_party_tag_and_the_partys_people_match_too(self):
        self.thread("Work", "Cedar OEM", "Q4 Planning", "parked", party="cedar", spoken="fourth quarter planning")
        work = self.where("Zones", "Work")
        self.assertIn("Q4 Planning", self.said("open fourth quarter planning", work))
        self.assertIn("Liveness Pricing", self.said("what did cedar say", work))
        self.assertIn("Liveness Pricing", self.said("mail from Alex Birch", work))
        self.assertEqual("", self.said("mail from Alex", work))           # a first name alone is not a person's name

    def test_a_one_letter_or_common_word_never_matches_alone(self):
        self.thread("Work", "Cedar OEM", "A", "parked", party="cedar")
        self.thread("Work", "Cedar OEM", "Plan", "parked", party="cedar")
        self.assertEqual("", self.fire("a plan for the new thread", self.where("Zones", "Work", "Acme")))
        self.thread("Work", "Cedar OEM", "Big Plan", "parked", party="cedar")       # "plan" is on the list, "big" is short
        self.thread("Work", "Cedar OEM", "Q4 Note", "parked", party="cedar")
        self.assertEqual("", self.fire("the big plan note for q4", self.where("Zones", "Work", "Acme")))

    def test_at_most_the_two_best_are_named_most_matched_words_first(self):
        self.thread("Work", "Cedar OEM", "Harbour Freight Rates", "parked", party="cedar")
        self.thread("Work", "Cedar OEM", "Freight Audit", "parked", party="cedar")
        self.thread("Work", "Cedar OEM", "Rates Review", "parked", party="cedar")
        line = self.said("harbour freight rates please", self.where("Zones", "Work"))
        self.assertEqual(2, line.count("*") // 2)
        self.assertTrue(line.startswith("This may belong to *Cedar OEM, Harbour Freight Rates* or *"), line)

    def test_a_parked_project_is_one_entry_and_a_done_thread_none(self):
        self.assertIn("*Acme Archive*", self.said("open acme archive", self.where("Zones", "Work")))
        self.thread("Work", "Acme", "Wrapped Up", "done", party="acme")
        self.assertEqual("", self.fire("open wrapped up", self.where("Zones", "Work")))

    def test_the_root_and_system_are_told_of_every_zone_and_a_wiki_of_open_zones_only(self):
        (self.root / "Wikis" / "Meetings").mkdir(parents=True)
        for cwd, roof in ((self.root, True), (self.where("System"), True), (self.where("Wikis", "Meetings"), False)):
            self.assertEqual(roof, "Roof repair" in self.said("fix the roof repair", cwd), cwd)
        self.assertIn("Mural wall", self.said("the mural wall", self.where("Wikis", "Meetings")))

    def test_an_open_zones_thread_is_named_in_a_walled_session(self):
        self.assertIn("Mural wall", self.said("paint the mural wall", self.where("Zones", "Personal")))

    def test_a_zone_the_table_does_not_list_counts_as_walled(self):
        self.thread("Ghost", "Spook", "Haunting", "parked")
        self.assertEqual("", self.fire("haunting", self.where("Zones", "Personal")))
        self.assertIn("Haunting", self.said("haunting", self.where("Zones", "Ghost")))      # its own zone

    def test_no_session_names_a_thread_of_another_walled_zone_for_any_pair(self):
        names = {"Work": "Liveness Pricing", "Personal": "Roof repair"}
        every = " and ".join(names.values())
        for here, there in itertools.permutations(names, 2):
            line = self.fire(every + " cedar maple", self.where("Zones", here))
            self.assertNotIn(names[there], line, (here, there))
            self.assertNotIn(there, line, (here, there))
            self.assertIn(names[here], line, (here, there))

    def test_no_message_says_that_a_hidden_thread_exists(self):
        line = self.fire("roof repair", self.where("Zones", "Work"))
        self.assertEqual("", line)


class TheLimits(Workspace):
    def test_with_no_memory_setting_it_adds_nothing(self):
        (self.root / "System" / "garrick-checks.json").write_text("{}")
        self.assertEqual("", self.fire("liveness pricing", self.where("Zones", "Work")))

    def test_it_adds_nothing_and_exits_0_on_any_error(self):
        env = dict(os.environ, HOME=str(self.home))
        for given in ("", "not json", "[1, 2]", json.dumps({"prompt": 5, "cwd": str(self.root)})):
            done = subprocess.run([sys.executable, str(HOOK)], input=given, capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual((0, "", ""), (done.returncode, done.stdout, done.stderr), given)
        (self.root / "System" / "context.md").write_bytes(b"\xff\xfe broken")
        os.unlink(self.root / "System" / "tools")
        done = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"prompt": "liveness pricing", "cwd": str(self.root)}),
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual((0, "", ""), (done.returncode, done.stdout, done.stderr))

    def test_outside_a_workspace_and_on_another_event_it_adds_nothing(self):
        self.assertEqual("", self.fire("liveness pricing", cwd=self.base))
        self.assertEqual("", self.fire("liveness pricing", self.where("Zones", "Work"), hook_event_name="PreToolUse"))

    def test_it_writes_nothing_of_the_prompt_anywhere(self):
        marker = "zxqvmarkerword"
        for prompt in ("%s no match" % marker, "liveness pricing %s" % marker, "%s roof repair" % marker):
            out = self.fire(prompt, self.where("Zones", "Work"))
            self.assertNotIn(marker, out)
        self.assertTrue((self.root / "System" / "generated" / "parked-hints.json").is_file())
        for folder in (self.root, self.home, self.base / "memory"):
            for path in folder.rglob("*"):
                if path.is_file() and not path.is_symlink() and "tools" not in path.relative_to(folder).parts[:2]:
                    self.assertNotIn(marker.encode(), path.read_bytes(), path)

    def test_the_cache_holds_names_zones_and_statuses_and_not_note_bodies(self):
        self.fire("anything", self.where("Zones", "Work"))
        text = (self.root / "System" / "generated" / "parked-hints.json").read_text()
        self.assertIn("Liveness Pricing", text)
        self.assertNotIn("Body text", text)

    def test_the_cache_is_rebuilt_when_a_note_changes(self):
        work = self.where("Zones", "Work")
        self.assertNotEqual("", self.fire("liveness pricing", work))
        path = self.where("Zones", "Work", "Cedar OEM", "Threads", "Liveness Pricing", "Liveness Pricing.md")
        path.write_text(note("active", "cedar"))
        later = time.time() + 30
        os.utime(path, (later, later))
        self.assertEqual("", self.fire("liveness pricing", work))
        path.write_text(note("parked", "cedar"))
        os.utime(path, (later + 30, later + 30))
        self.assertNotEqual("", self.fire("liveness pricing", work))

    def test_a_workspace_of_200_threads_ends_well_inside_its_timeout(self):
        for i in range(200):
            self.thread("Work", "Bulk %d" % (i % 20), "Item %d" % i, "parked" if i % 2 else "active", party="acme")
        self.fire("warm the cache", self.where("Zones", "Work"))
        start = time.time()
        self.assertIn("This may belong to", self.said("open item 101", self.where("Zones", "Work")))
        self.assertLess(time.time() - start, 4.0)
        start = time.time()
        self.fire("no such thing anywhere", self.where("Zones", "Work"))
        self.assertLess(time.time() - start, 4.0)

    def test_the_hook_is_registered_in_the_readme_beside_the_waiting_hook(self):
        text = (REPO / "extras" / "hooks" / "README.md").read_text()
        self.assertIn("parked_hint.py", text)
        self.assertIn('"UserPromptSubmit"', text.split("parked_hint.py", 1)[1])


if __name__ == "__main__":
    unittest.main()
