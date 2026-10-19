"""Making, renaming, parking and deleting projects and threads: scaffold.py's
`--check`, `park`, `wake`, `rename` and `delete`, in a workspace the installer
made, each of them also run the way the status page runs it.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True

from test_setup import Installed  # noqa: E402

import importlib.util  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("garrick_page_action_manage", str(REPO / "extras" / "status" / "page_action.py"))
pa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pa)


class ManageCase(Installed):
    def setUp(self):
        super().setUp()
        self.work = self.root / "Zones" / "Work"
        r = self.run_tool("scaffold.py", "project", "--zone", "Work", "--name", "Acme", "--party", "acme",
                          "--thread", "Pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        r = self.run_tool("scaffold.py", "thread", "--zone", "Work", "--project", "Acme", "--name", "Freight")
        self.assertEqual(0, r.returncode, r.stderr)
        self.freight = self.work / "Acme" / "Threads" / "Freight" / "Freight.md"
        self.freight.write_text(self.freight.read_text() + "\nSee [[Pricing]] and [[Acme/Threads/Pricing/Pricing|Pricing]].\n")
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text().replace("## Inbox\n", "## Inbox\n\n- [ ] [[Pricing]]: call Dana 📅 2026-10-20\n"
                                                 "- [ ] [[Freight]]: send the lanes\n- [x] [[Freight]]: old one ✅ 2026-10-01\n", 1))
        self.commit("Acme set up")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=str(self.work), capture_output=True, text=True, env=self.env)

    def commit(self, message):
        self.git("add", "-A")
        r = self.git("commit", "-q", "-m", message)
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)

    def scaffold(self, *args):
        return self.run_tool("scaffold.py", *args)


class TestParty(ManageCase):
    """`party`: the one step of setting work up that reaches outside the zone,
    and the one the user is asked about. It offers the tag, so nobody has to
    invent one; it runs again without writing a second row; and where two
    parties share a name it refuses in a question."""

    def root_git(self, *args):
        return subprocess.run(["git", *args], cwd=str(self.root), capture_output=True, text=True, env=self.env)

    def context(self):
        return (self.root / "System" / "context.md").read_text(encoding="utf-8")

    def test_check_on_a_new_party_offers_the_tag_and_writes_nothing(self):
        before = self.context()
        r = self.scaffold("party", "--name", "Cobalt Freight", "--zone", "Work", "--check")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Cobalt Freight is not a party yet, and the tag would be `cobalt`, in Work.", r.stdout)
        self.assertEqual(before, self.context())
        self.assertEqual("", self.root_git("status", "--porcelain").stdout)

    def test_check_on_a_known_party_names_its_tag_its_zone_and_its_project(self):
        """The listing is the code's, not the skill's prose: a project is found by
        its hub's `party:`, whatever the folder is called."""
        r = self.scaffold("party", "--name", "Acme Corp", "--check")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Acme Corp is already a party, `acme`, in Work, with the project Acme.", r.stdout)
        r = self.scaffold("party", "--name", "Birch & Co", "--check")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Birch & Co is already a party, `birch`, in Work, with no project yet.", r.stdout)

    def test_a_new_party_is_added_and_the_commit_left_to_the_caller(self):
        r = self.scaffold("party", "--name", "Cobalt Freight", "--zone", "Work", "--what", "Supplier")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Added Cobalt Freight to the Parties table in System/context.md, with the tag `cobalt`, "
                      "in Work.", r.stdout)
        self.assertIn("| Cobalt Freight | Supplier | Work | `cobalt` |  | %s, user |" % datetime.date.today().isoformat(),
                      self.context())
        # The rows typed by hand are left exactly as they were; only the header gains the column.
        self.assertIn("| Domains | Learned |", self.context())
        self.assertNotIn("|  |  |\n", self.context())
        # Left for the caller to commit, in the workspace's own repository.
        self.assertIn("System/context.md", self.root_git("status", "--porcelain").stdout)
        self.assertIn("Commit System/context.md on its own", r.stdout)
        self.assertIn("refused while the row is not there", r.stdout)

    def test_running_it_again_writes_no_second_row(self):
        """An onboarding picked up again: what it already did is found by re-reading,
        not by a state file of its own."""
        self.assertEqual(0, self.scaffold("party", "--name", "Cobalt Freight", "--zone", "Work",
                                          "--what", "Supplier").returncode)
        after = self.context()
        r = self.scaffold("party", "--name", "cobalt  freight", "--zone", "Work", "--what", "Supplier")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Cobalt Freight is already a party, `cobalt`, in Work", r.stdout)
        self.assertEqual(after, self.context())
        self.assertEqual(1, self.context().count("| Cobalt Freight |"))

    def test_the_project_is_refused_until_the_party_row_is_there(self):
        """The ordering the two repositories force: the row first, on its own."""
        r = self.scaffold("project", "--zone", "Work", "--name", "Cobalt Review", "--party", "cobalt",
                          "--thread", "Next Call")
        self.assertEqual(1, r.returncode)
        self.assertIn("not a party tag in System/context.md", r.stderr)
        self.assertFalse((self.work / "Cobalt Review").exists())
        self.assertEqual(0, self.scaffold("party", "--name", "Cobalt Freight", "--zone", "Work",
                                          "--what", "Supplier").returncode)
        r = self.scaffold("project", "--zone", "Work", "--name", "Cobalt Review", "--party", "cobalt",
                          "--thread", "Next Call")
        self.assertEqual(0, r.returncode, r.stderr)
        r = self.scaffold("party", "--name", "Cobalt Freight", "--check")
        self.assertIn("with the project Cobalt Review.", r.stdout)

    def test_a_second_capacity_gets_the_wider_tag_and_the_wall(self):
        self.assertEqual(0, self.scaffold("party", "--name", "Cobalt Freight", "--zone", "Work",
                                          "--what", "Supplier").returncode)
        r = self.scaffold("party", "--name", "Cobalt Freight", "--zone", "Personal", "--what", "Advisory client",
                          "--also", "--walled-from", "cobalt", "--why", "Two capacities, two confidences")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("with the tag `cobalt-freight`, in Personal", r.stdout)
        self.assertIn("Added a wall between `cobalt-freight` and `cobalt`", r.stdout)
        self.assertIn("| `cobalt-freight` | `cobalt` | Two capacities, two confidences |", self.context())
        # The check that would otherwise warn about the two: one name, two tags, a wall.
        found = json.loads(self.run_tool("check.py", "--json").stdout)
        self.assertEqual([], [f for f in found["findings"] if "no wall between them" in f.get("message", "")],
                         found)

    def test_a_second_capacity_with_no_wall_says_what_the_check_will_warn(self):
        self.assertEqual(0, self.scaffold("party", "--name", "Cobalt Freight", "--zone", "Work",
                                          "--what", "Supplier").returncode)
        r = self.scaffold("party", "--name", "Cobalt Freight", "--zone", "Personal", "--what", "Advisory client",
                          "--also")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("with no wall between them, which the workspace check warns about until one is added",
                      r.stdout)

    def test_two_parties_of_one_name_are_a_question_and_nothing_is_written(self):
        """Never resolved silently: which capacity a request means is the user's."""
        for args in (("--name", "Cobalt Freight", "--zone", "Work", "--what", "Supplier"),
                     ("--name", "Cobalt Freight", "--zone", "Personal", "--what", "Client", "--also")):
            self.assertEqual(0, self.scaffold("party", *args).returncode)
        after = self.context()
        for extra in (["--check"], ["--zone", "Work", "--what", "Supplier"], ["--also", "--zone", "Work"]):
            r = self.scaffold("party", "--name", "Cobalt Freight", *extra)
            self.assertEqual(1, r.returncode, extra)
            self.assertEqual(1, len(r.stderr.strip().splitlines()), r.stderr)
            self.assertEqual("Two of your parties are called Cobalt Freight: `cobalt` in Work, and "
                             "`cobalt-freight` in Personal. Which one is this?", r.stderr.strip())
            self.assertEqual(after, self.context())

    def test_what_it_refuses(self):
        for extra, said in (
            (["--name", "Cobalt Freight", "--what", "Supplier"],
             "Which zone is Cobalt Freight in? The zones are Personal, Work."),
            (["--name", "Cobalt Freight", "--zone", "Garden", "--what", "Supplier"],
             "There is no zone called Garden."),
            (["--name", "4Birch", "--zone", "Work", "--check"], 'No tag can be made from "4Birch"'),
            (["--name", "Cobalt Freight", "--zone", "Work", "--also"],
             "is not a party yet, so there is no first capacity for --also to stand beside"),
            (["--name", "Cobalt Freight", "--zone", "Work", "--walled-from", "dune"],
             "`dune` is not a party tag in System/context.md"),
        ):
            before = self.context()
            r = self.scaffold("party", *extra)
            self.assertEqual(1, r.returncode, extra)
            self.assertIn(said, r.stderr)
            self.assertEqual(before, self.context())
        self.assertEqual("", self.root_git("status", "--porcelain").stdout)


class TestCheck(ManageCase):
    def test_check_says_whether_a_name_would_do_and_makes_nothing(self):
        r = self.scaffold("thread", "--zone", "Work", "--project", "Acme", "--name", "Renewal", "--check")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("will do", r.stdout)
        self.assertFalse((self.work / "Acme" / "Threads" / "Renewal").exists())
        r = self.scaffold("thread", "--zone", "Work", "--project", "Acme", "--name", "Prising", "--check")
        self.assertEqual(1, r.returncode)
        self.assertIn("sounds too much like Pricing", r.stderr)
        r = self.scaffold("project", "--zone", "Work", "--name", "Birch", "--party", "birch", "--thread", "Q3_plan",
                          "--check")
        self.assertEqual(1, r.returncode)
        self.assertIn("will not work", r.stderr)
        self.assertFalse((self.work / "Birch").exists())
        self.assertEqual("", self.git("status", "--porcelain").stdout)


class TestNaming(ManageCase):
    """The three naming questions through the script: an ordinary business name
    is made, a name that does not say how it is said is asked about, and a
    sibling collision is a question the user answers."""

    def test_a_business_name_is_made_and_its_spoken_form_asked_for(self):
        r = self.scaffold("thread", "--zone", "Work", "--project", "Acme", "--name", "Q4 Planning")
        self.assertEqual(0, r.returncode, r.stderr)
        note = self.work / "Acme" / "Threads" / "Q4 Planning" / "Q4 Planning.md"
        self.assertTrue(note.is_file())
        self.assertNotIn("spoken:", note.read_text())
        self.assertIn("does not say how it is said", r.stdout)
        self.assertIn("What should be heard for it", r.stdout)

    def test_a_spoken_form_goes_into_the_note_under_the_title(self):
        r = self.scaffold("thread", "--zone", "Work", "--project", "Acme", "--name", "ISO 27001",
                          "--spoken", "I S O twenty seven thousand one")
        self.assertEqual(0, r.returncode, r.stderr)
        note = (self.work / "Acme" / "Threads" / "ISO 27001" / "ISO 27001.md").read_text()
        self.assertIn("title: ISO 27001\nspoken: I S O twenty seven thousand one\ntype: thread", note)
        self.assertNotIn("does not say how it is said", r.stdout)
        r = self.scaffold("project", "--zone", "Work", "--name", "Q4 Planning", "--party", "birch",
                          "--thread", "Audit", "--spoken", "fourth quarter planning")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("spoken: fourth quarter planning",
                      (self.work / "Q4 Planning" / "Q4 Planning.md").read_text())

    def test_a_spoken_form_has_to_say_how_it_is_said_itself(self):
        r = self.scaffold("thread", "--zone", "Work", "--project", "Acme", "--name", "Q4 Planning",
                          "--spoken", "Q4 planning")
        self.assertEqual(1, r.returncode)
        self.assertIn("will not work as the spoken form", r.stderr)

    def test_a_sibling_collision_is_put_as_a_question(self):
        for extra, said in ((["--name", "Pricing"], "already has a thread called Pricing. Open it, or pick"),
                            (["--name", "pricing"], 'stored as "Pricing", and "pricing" would be the same folder'),
                            (["--name", "Prizing"], "Open Pricing, or pick a name that is easy to tell apart?")):
            r = self.scaffold("thread", "--zone", "Work", "--project", "Acme", *extra)
            self.assertEqual(1, r.returncode, extra)
            self.assertEqual(1, len(r.stderr.strip().splitlines()), r.stderr)
            self.assertIn(said, r.stderr)

    def test_two_spoken_forms_that_sound_alike_are_a_question_too(self):
        r = self.scaffold("thread", "--zone", "Work", "--project", "Acme", "--name", "Q4 Planning",
                          "--spoken", "freight")
        self.assertEqual(1, r.returncode)
        self.assertIn('("freight" and "Freight")', r.stderr)
        self.assertIn("Open Freight, or pick", r.stderr)

    def test_renaming_to_a_business_name_and_giving_it_a_form(self):
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing",
                          "--to", "Q4 Pricing", "--spoken", "fourth quarter pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        note = (self.work / "Acme" / "Threads" / "Q4 Pricing" / "Q4 Pricing.md").read_text()
        self.assertIn("title: Q4 Pricing\nspoken: fourth quarter pricing\n", note)
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Q4 Pricing",
                          "--to", "Renewal")
        self.assertEqual(0, r.returncode, r.stderr)
        note = (self.work / "Acme" / "Threads" / "Renewal" / "Renewal.md").read_text()
        self.assertNotIn("spoken:", note)


class TestRename(ManageCase):
    def test_a_thread_and_every_link_to_it(self):
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(0, r.returncode, r.stderr)
        note = self.work / "Acme" / "Threads" / "Renewal" / "Renewal.md"
        self.assertTrue(note.is_file())
        self.assertFalse((self.work / "Acme" / "Threads" / "Pricing").exists())
        text = note.read_text()
        self.assertIn("title: Renewal", text)
        self.assertIn("\n# Renewal\n", text)
        self.assertIn("Renamed from Pricing.", text)
        self.assertIn("[[Acme/Threads/Renewal/Renewal|Renewal]]", (self.work / "Acme" / "Acme.md").read_text())
        self.assertIn("- [ ] [[Renewal]]: call Dana", (self.work / "Todo.md").read_text())
        self.assertIn("See [[Renewal]] and [[Acme/Threads/Renewal/Renewal|Renewal]].", self.freight.read_text())
        self.assertEqual("", self.git("status", "--porcelain").stdout)                   # one commit, all of it
        self.assertIn("Acme, Pricing: renamed Renewal", self.git("log", "-1", "--format=%s").stdout)
        self.assertIn("Renamed from Pricing.", self.git("log", "-1", "--follow", "-p", "--format=", "--",
                                                        "Acme/Threads/Renewal/Renewal.md").stdout)
        context = (self.root / "System" / "context.md").read_text()
        # The alias a rename leaves is a learned row, and says it came from the user.
        self.assertIn("| pricing | Renewal | %s, user |" % datetime.date.today().isoformat(), context)
        self.assertIn("| Heard | Means | Learned |", context)
        found = json.loads(self.run_tool("check.py", "--json").stdout)["findings"]
        self.assertEqual([], [f for f in found if f["severity"] == "error" and "Work" in f["path"]])

    def test_a_thread_and_the_files_in_its_folder(self):
        """#178: links to a file inside a renamed thread's folder follow it,
        from its own note and from anywhere else in the zone."""
        old = self.work / "Acme" / "Threads" / "Pricing"
        (old / "Deliverables").mkdir()
        (old / "Deliverables" / "260914 - Brief.md").write_text("# Brief\n")
        (old / "Sources").mkdir()
        (old / "Sources" / "rates.csv").write_text("lane,rate\n")
        note, hub = old / "Pricing.md", self.work / "Acme" / "Acme.md"
        text = note.read_text()
        self.assertIn("| Live artifact | <path, and what it is> |", text)
        note.write_text(text.replace("| Live artifact | <path, and what it is> |",
                                     "| Live artifact | [[Acme/Threads/Pricing/Deliverables/260914 - Brief|Deliverables/260914 - Brief]] |")
                        + "\nRates: [[Acme/Threads/Pricing/Sources/rates.csv]].\n")
        hub.write_text(hub.read_text() + "\nThe rates: [[Work/Acme/Threads/Pricing/Sources/rates.csv|rates]].\n")
        self.commit("Pricing's files")
        before = self.git("ls-files", "-s").stdout
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(0, r.returncode, r.stderr)
        text = (self.work / "Acme" / "Threads" / "Renewal" / "Renewal.md").read_text()
        self.assertIn("[[Acme/Threads/Renewal/Deliverables/260914 - Brief|Deliverables/260914 - Brief]]", text)
        self.assertIn("[[Acme/Threads/Renewal/Sources/rates.csv]]", text)
        self.assertIn("[[Work/Acme/Threads/Renewal/Sources/rates.csv|rates]]", hub.read_text())
        found = json.loads(self.run_tool("check.py", "--json").stdout)["findings"]
        self.assertEqual([], [f for f in found if "leads nowhere" in f["message"]])    # the Live artifact row too
        commit = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        r = self.scaffold("undo", "--zone", "Work", "--commit", commit)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(before, self.git("ls-files", "-s").stdout)
        self.assertIn("[[Acme/Threads/Pricing/Sources/rates.csv]]", note.read_text())
        self.assertIn("[[Work/Acme/Threads/Pricing/Sources/rates.csv|rates]]", hub.read_text())

    def test_a_project_and_its_threads(self):
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--to", "Apex")
        self.assertEqual(0, r.returncode, r.stderr)
        hub = self.work / "Apex" / "Apex.md"
        self.assertTrue(hub.is_file())
        self.assertIn("[[Apex/Threads/Pricing/Pricing|Pricing]]", hub.read_text())
        self.assertIn('project: "[[Apex]]"', self.freight.parent.parent.parent.parent.joinpath(
            "Apex", "Threads", "Freight", "Freight.md").read_text())
        self.assertIn("[[Apex/Threads/Pricing/Pricing|Pricing]]",
                      (self.work / "Apex" / "Threads" / "Freight" / "Freight.md").read_text())
        self.assertEqual("", self.git("status", "--porcelain").stdout)

    def test_refusals_change_nothing(self):
        cases = [
            (["--thread", "Pricing", "--to", "Freight"], "already has a thread called Freight"),
            (["--thread", "Pricing", "--to", "Pricing_v2"], "will not work"),
            (["--thread", "Pricing", "--to", "Fraight"], "sounds too much like Freight"),
        ]
        for extra, said in cases:
            r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", *extra)
            self.assertEqual(1, r.returncode, extra)
            self.assertIn(said, r.stderr)
        self.freight.write_text(self.freight.read_text() + "An edit not committed.\n")
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(1, r.returncode)
        self.assertIn("not committed", r.stderr)
        self.assertTrue((self.work / "Acme" / "Threads" / "Pricing" / "Pricing.md").is_file())

    def test_a_refused_commit_puts_everything_back(self):
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho refused >&2\nexit 1\n")
        hook.chmod(0o755)
        before = self.git("ls-files", "-s").stdout
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(1, r.returncode)
        self.assertIn("nothing changed", r.stderr)
        self.assertEqual(before, self.git("ls-files", "-s").stdout)
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertFalse((self.work / "Acme" / "Threads" / "Renewal").exists())


class TestDelete(ManageCase):
    def test_without_confirm_it_only_says_what_would_go(self):
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--thread", "Freight")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("its line in the hub", r.stdout)
        self.assertIn("1 open line in Todo.md", r.stdout)
        self.assertIn("[[Freight]]: send the lanes", r.stdout)
        self.assertIn('--confirm "Freight"', r.stdout)
        self.assertTrue(self.freight.is_file())
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--confirm", "freight")
        self.assertEqual(1, r.returncode)
        self.assertTrue(self.freight.is_file())

    def test_confirmed_it_goes_in_one_commit_and_a_revert_brings_it_back(self):
        before = self.git("ls-files", "-s").stdout
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--confirm", "Freight")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertFalse(self.freight.parent.exists())
        self.assertNotIn("Threads/Freight/", (self.work / "Acme" / "Acme.md").read_text())
        todo = (self.work / "Todo.md").read_text()
        self.assertNotIn("send the lanes", todo)
        self.assertIn("[x] [[Freight]]: old one", todo)                  # a done line is the record: it stays
        self.assertIn("removed: - [ ] [[Freight]]: send the lanes", r.stdout)
        self.assertIn("- [ ] [[Freight]]: send the lanes", self.git("log", "-1", "--format=%b").stdout)
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        commit = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        self.assertIn("scaffold.py undo --zone Work --commit " + commit, r.stdout)
        r = self.scaffold("undo", "--zone", "Work", "--commit", commit)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(before, self.git("ls-files", "-s").stdout)
        r = self.scaffold("undo", "--zone", "Work", "--commit", commit)             # no longer the last commit
        self.assertEqual(1, r.returncode)
        self.assertIn("no longer the last commit", r.stderr)

    def test_a_whole_project(self):
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme")
        self.assertIn("with its threads", r.stdout)
        self.assertIn("2 open lines in Todo.md", r.stdout)
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--confirm", "Acme")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertFalse((self.work / "Acme").exists())
        self.assertNotIn("- [ ] [[Pricing]]", (self.work / "Todo.md").read_text())


class TestWhatCannotBeBroughtBack(ManageCase):
    """A rename or deletion refuses whatever a revert could not restore."""

    def test_ignored_files_and_a_nested_repository_are_refused_and_kept(self):
        acme = self.work / "Acme"
        (self.work / ".gitignore").write_text((self.work / ".gitignore").read_text() + "Acme/build/\n")
        self.commit("ignore build")
        (acme / "build").mkdir()
        (acme / "build" / "out.bin").write_bytes(b"x")
        for args in (["delete", "--zone", "Work", "--project", "Acme", "--confirm", "Acme"],
                     ["rename", "--zone", "Work", "--project", "Acme", "--to", "Apex"]):
            r = self.scaffold(*args)
            self.assertEqual(1, r.returncode, args)
            self.assertIn("not in the zone's history", r.stderr)
        self.assertTrue((acme / "build" / "out.bin").exists())
        (acme / "build" / "out.bin").unlink()
        (acme / "build").rmdir()
        repo = acme / "Site"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(repo), env=self.env, check=True)
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--confirm", "Acme")
        self.assertEqual(1, r.returncode)
        self.assertIn("repository of its own", r.stderr)
        self.assertTrue((repo / ".git").is_dir())

    def machine_made(self, folder):
        """What Finder, Python and Obsidian leave in a folder they have opened (#177)."""
        (folder / ".DS_Store").write_bytes(b"\0\0\0\1Bud1")
        (folder / "__pycache__").mkdir()
        (folder / "__pycache__" / "x.cpython-39.pyc").write_bytes(b"\0")
        (folder / ".obsidian").mkdir()
        (folder / ".obsidian" / "workspace.json").write_text("{}")

    def test_what_a_machine_makes_is_cleared_and_never_refuses_a_rename(self):
        old = self.work / "Acme" / "Threads" / "Pricing"
        self.machine_made(old)
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(0, r.returncode, r.stderr)
        new = self.work / "Acme" / "Threads" / "Renewal"
        self.assertTrue((new / "Renewal.md").is_file())
        self.assertFalse(old.exists())                                        # nothing left behind
        self.assertEqual(["Renewal.md"], sorted(os.listdir(new)))            # and nothing carried over
        self.assertEqual("", self.git("status", "--porcelain", "--ignored").stdout)

    def test_a_file_anybody_wrote_still_refuses_a_rename_beside_them(self):
        old = self.work / "Acme" / "Threads" / "Pricing"
        self.machine_made(old)
        (old / "notes.txt").write_text("not committed")
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(1, r.returncode)
        self.assertIn("Acme/Threads/Pricing/notes.txt is in Pricing but not in the zone's history", r.stderr)
        self.assertNotIn(".DS_Store", r.stderr)
        self.assertTrue((old / ".DS_Store").exists())                         # a refusal clears nothing
        self.assertTrue((old / "notes.txt").exists())

    def test_what_a_machine_makes_is_cleared_and_never_refuses_a_deletion(self):
        self.machine_made(self.freight.parent)
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--confirm", "Freight")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertFalse(self.freight.parent.exists())
        self.assertEqual("", self.git("status", "--porcelain", "--ignored").stdout)
        self.machine_made(self.work / "Acme")
        (self.work / "Acme" / "notes.txt").write_text("not committed")
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--confirm", "Acme")
        self.assertEqual(1, r.returncode)
        self.assertIn("Acme/notes.txt is in Acme but not in the zone's history", r.stderr)
        self.assertTrue((self.work / "Acme" / "Acme.md").is_file())

    def test_something_staged_elsewhere_is_never_swept_in(self):
        (self.work / "Birch Sources").mkdir()
        (self.work / "Birch Sources" / "contract.pdf").write_bytes(b"%PDF staged by hand")
        self.git("add", "Birch Sources/contract.pdf")
        r = self.scaffold("rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--to", "Renewal")
        self.assertEqual(1, r.returncode)
        self.assertIn("staged", r.stderr)

    def test_a_thread_of_the_same_name_in_another_project_is_left_alone(self):
        r = self.scaffold("project", "--zone", "Work", "--name", "Birch", "--party", "birch", "--thread", "Pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text().replace("## Inbox\n", "## Inbox\n\n- [ ] [[Birch/Threads/Pricing/Pricing|Pricing]]: Birch's\n", 1))
        self.commit("Birch")
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--thread", "Pricing", "--confirm", "Pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Birch's", todo.read_text())                              # another thread's line stays
        self.assertIn("[[Pricing]]: call Dana", todo.read_text())               # ambiguous now: left, not guessed

    def test_renaming_a_project_leaves_a_thread_that_shares_its_name(self):
        for project in ("Pallets", "Ledger"):
            r = self.scaffold("project", "--zone", "Work", "--name", project, "--party", "acme", "--thread", "Pallets")
            self.assertEqual(0, r.returncode, r.stderr)
        self.commit("two projects with a Pallets thread")
        r = self.scaffold("rename", "--zone", "Work", "--project", "Pallets", "--to", "Crates")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("[[Ledger/Threads/Pallets/Pallets|Pallets]]", (self.work / "Ledger" / "Ledger.md").read_text())
        self.assertIn("[[Crates/Threads/Pallets/Pallets|Pallets]]", (self.work / "Crates" / "Crates.md").read_text())


class TestFromThePage(ManageCase):
    """The page's buttons run scaffold.py and nothing else."""

    def setUp(self):
        super().setUp()
        os.environ["GARRICK_JOBS_DIR"] = str(self.base / "jobs")

    def act(self, **req):
        return pa.act(self.root, req)

    def test_new_project_and_thread_match_the_script_and_are_committed(self):
        said = self.act(verb="check-name", kind="thread", zone="Work", project="Acme", name="Renewal")
        self.assertIn("will do", said)
        with self.assertRaisesRegex(pa.Refused, "sounds too much like Pricing"):
            self.act(verb="check-name", kind="thread", zone="Work", project="Acme", name="Prising")
        self.assertIn("Created thread Renewal", self.act(verb="new-thread", zone="Work", project="Acme", name="Renewal"))
        self.assertIn("Created project Birch", self.act(verb="new-project", zone="Work", name="Birch", party="birch",
                                                         thread="Launch Plan"))
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertIn("New project Birch (birch), first thread Launch Plan", self.git("log", "-1", "--format=%s").stdout)
        self.assertTrue((self.work / "Birch" / "Threads" / "Launch Plan" / "Launch Plan.md").is_file())
        found = json.loads(self.run_tool("check.py", "--json").stdout)["findings"]
        self.assertEqual([], [f for f in found if f["severity"] == "error" and "Work" in f["path"]])

    def slow_hook(self, seconds):
        """The zone's own wall check, after `seconds` of sleep: a workspace whose check takes that long."""
        hook = Path(self.git("rev-parse", "--git-path", "hooks/pre-commit").stdout.strip())
        hook = hook if hook.is_absolute() else self.work / hook
        shipped = hook.read_text()
        hook.write_text(shipped.replace("\n", "\nsleep %s\n" % seconds, 1))
        return hook, shipped

    def test_a_wall_check_slower_than_a_git_command_still_commits(self):
        self.slow_hook(4)
        real = pa.GIT_TIMEOUT, pa.COMMIT_TIMEOUT
        pa.GIT_TIMEOUT, pa.COMMIT_TIMEOUT = 2, 60
        try:
            self.assertIn("Created project Birch", self.act(verb="new-project", zone="Work", name="Birch", party="birch",
                                                             thread="Launch Plan"))
        finally:
            pa.GIT_TIMEOUT, pa.COMMIT_TIMEOUT = real
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertIn("New project Birch (birch), first thread Launch Plan", self.git("log", "-1", "--format=%s").stdout)

    def test_a_wall_check_stopped_leaves_the_files_for_a_commit_by_hand(self):
        hook, shipped = self.slow_hook(30)
        real, pa.COMMIT_TIMEOUT = pa.COMMIT_TIMEOUT, 2
        try:
            with self.assertRaisesRegex(pa.Refused, "^made, but not committed: the wall check was still running after "
                                        "2 s and was stopped. The files are there, unstaged; commit them by hand: that "
                                        "commit waits for the check and goes through$"):
                self.act(verb="new-project", zone="Work", name="Birch", party="birch", thread="Launch Plan")
        finally:
            pa.COMMIT_TIMEOUT = real
        self.assertTrue((self.work / "Birch" / "Threads" / "Launch Plan" / "Launch Plan.md").is_file())
        self.assertEqual("?? Birch/\n", self.git("status", "--porcelain").stdout)
        self.assertFalse((self.work / ".git" / "index.lock").exists())
        hook.write_text(shipped.replace("\n", "\nsleep 3\n", 1))     # by hand, git waits as long as the check takes
        self.commit("New project Birch")
        self.assertEqual("", self.git("status", "--porcelain").stdout)

    def test_rename_delete_and_undo(self):
        self.assertIn("Renamed the thread Pricing to Renewal",
                      self.act(verb="rename", zone="Work", project="Acme", thread="Pricing", to="Renewal"))
        listed = self.act(verb="delete", zone="Work", project="Acme", thread="Freight")
        self.assertIn("Nothing was deleted", listed)
        said = self.act(verb="delete", zone="Work", project="Acme", thread="Freight", confirm="Freight")
        commit = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        self.assertIn(commit, said)
        self.assertIn("Undone", self.act(verb="undo", zone="Work", commit=commit))
        self.assertTrue(self.freight.is_file())
        for bad in ({"verb": "undo", "zone": "Work", "commit": "HEAD~1"},
                    {"verb": "rename", "zone": "Work", "project": "Acme", "to": "--root=/"},
                    {"verb": "new-thread", "zone": "../Personal", "project": "Acme", "name": "X"}):
            with self.assertRaises(pa.Refused):
                pa.act(self.root, bad)

    def wall(self):
        ops = pa.ops_lib(self.root)
        self.assertIsNotNone(ops)
        return ops.WALL_REFUSAL

    def test_a_manage_verb_the_real_wall_check_refuses_says_the_rules_sentence_alone(self):
        """#172: the zone's own wall check, as installed, refuses each manage
        verb, since what it would commit names Birch & Co in a project for Acme.
        The page says #116's sentence and nothing else, where the script, run in
        a terminal, still prints the check's line for whoever has to take the
        material out."""
        wall = self.wall()
        head = self.git("rev-parse", "HEAD").stdout

        def refused(**req):
            with self.assertRaises(pa.Refused, msg=req) as said:
                self.act(**req)
            self.assertEqual(wall, str(said.exception), req)
            for leak in ("Birch", "birch", "acme", "Commit refused", "not committed"):
                self.assertNotIn(leak, str(said.exception), req)
            self.assertEqual(head, self.git("rev-parse", "HEAD").stdout, req)

        refused(verb="rename", zone="Work", project="Acme", thread="Freight", to="Birch Lanes")
        self.assertEqual("", self.git("status", "--porcelain").stdout)              # the rename put back
        self.assertTrue(self.freight.is_file())
        refused(verb="new-thread", zone="Work", project="Acme", name="Birch Pitch")
        self.assertEqual("", self.git("status", "--porcelain").stdout)              # the new thread taken away
        refused(verb="new-project", zone="Work", name="Cobalt", party="acme", thread="Birch Pitch")
        self.assertEqual("", self.git("status", "--porcelain").stdout)              # and the new project
        hub = self.work / "Acme" / "Acme.md"                       # written before the wall stood, say
        hub.write_text(hub.read_text() + "\nBirch & Co asked about the same lanes.\n")
        self.git("commit", "-q", "--no-verify", "-am", "a line from before the wall")
        head = self.git("rev-parse", "HEAD").stdout
        refused(verb="delete", zone="Work", project="Acme", thread="Freight", confirm="Freight")
        self.assertEqual("", self.git("status", "--porcelain").stdout)              # the deletion put back
        self.assertTrue(self.freight.is_file())
        r = self.scaffold("delete", "--zone", "Work", "--project", "Acme", "--thread", "Freight", "--confirm", "Freight")
        self.assertEqual(1, r.returncode)
        self.assertIn("Commit refused: ", r.stderr)                                 # the terminal keeps the check's line

    def test_a_new_thread_the_wall_check_refuses_leaves_nothing_behind(self):
        """#172: "Nothing was written" holds. The thread's folder goes, and the
        hub gets back the bytes it held before the request, an edit another
        session had not committed yet included; the index is as it was."""
        hub = self.work / "Acme" / "Acme.md"
        hub.write_text(hub.read_text() + "\nA line typed in Obsidian, not committed yet.\n")
        before = hub.read_bytes()
        with self.assertRaises(pa.Refused) as said:
            self.act(verb="new-thread", zone="Work", project="Acme", name="Birch Pitch")
        self.assertEqual(self.wall(), str(said.exception))
        self.assertFalse((self.work / "Acme" / "Threads" / "Birch Pitch").exists())
        self.assertEqual(before, hub.read_bytes())
        self.assertEqual(" M Acme/Acme.md\n", self.git("status", "--porcelain").stdout)
        self.assertEqual("", self.git("diff", "--cached", "--name-only").stdout)

    def test_a_new_project_the_wall_check_refuses_leaves_nothing_behind(self):
        """Its folder goes, a Threads folder and a first thread with it, and
        nothing that was there before the request is touched."""
        todo = self.work / "Todo.md"
        todo.write_text(todo.read_text() + "- [ ] [[Freight]]: an edit of its own\n")
        before = {p: p.read_bytes() for p in self.work.rglob("*") if p.is_file() and ".git" not in p.parts}
        with self.assertRaises(pa.Refused) as said:
            self.act(verb="new-project", zone="Work", name="Cobalt", party="acme", thread="Birch Pitch")
        self.assertEqual(self.wall(), str(said.exception))
        self.assertFalse((self.work / "Cobalt").exists())
        self.assertEqual(before, {p: p.read_bytes() for p in self.work.rglob("*") if p.is_file() and ".git" not in p.parts})
        self.assertEqual("", self.git("diff", "--cached", "--name-only").stdout)

    def test_a_manage_verb_refused_for_any_other_reason_still_says_why(self):
        hook = Path(self.git("rev-parse", "--git-path", "hooks/pre-commit").stdout.strip())
        hook = hook if hook.is_absolute() else self.work / hook
        hook.write_text("#!/bin/sh\necho 'fatal: the disk is full' >&2\nexit 1\n")
        for req in ({"verb": "rename", "zone": "Work", "project": "Acme", "thread": "Freight", "to": "Lanes"},
                    {"verb": "delete", "zone": "Work", "project": "Acme", "thread": "Freight", "confirm": "Freight"},
                    {"verb": "new-thread", "zone": "Work", "project": "Acme", "name": "Renewal"}):
            with self.assertRaises(pa.Refused, msg=req) as said:
                self.act(**req)
            self.assertIn("the disk is full", str(said.exception), req)
            self.assertNotIn(self.wall(), str(said.exception), req)
        self.assertTrue((self.work / "Acme" / "Threads" / "Renewal" / "Renewal.md").is_file())    # made, left for the user

    def test_the_interruption_stack_follows_a_rename_and_a_delete(self):
        """Interrupted (#32) on the template's own thread note: the rows filled,
        the rest left as scaffolded; a rename moves the entry, a deletion
        drops it, and the stack file is never committed anywhere."""
        for thread in ("Pricing", "Freight"):
            self.act(verb="interrupt", zone="Work", project="Acme", thread=thread, where="Mid-sheet",
                     next="Fill in row 14", keep="The rate is a guess")
        note = self.work / "Acme" / "Threads" / "Pricing" / "Pricing.md"
        text = note.read_text()
        self.assertRegex(text, r"### Resume here\n\n\*\*Interrupted \d\d:\d\d, \d{1,2} [A-Z][a-z]+ \d{4}\.\*\* Mid-sheet\n\n\| \| \|\n")
        self.assertIn("| Next action | Fill in row 14 |\n| Keep in mind | The rate is a guess |\n| Waiting on | <who, or nobody> |", text)
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.act(verb="rename", zone="Work", project="Acme", thread="Pricing", to="Renewal")
        stack = lambda: [(e["project"], e["thread"], e["file"]) for e in self.act(verb="stack")["stack"]]
        self.assertEqual([("Acme", "Freight", "Acme/Threads/Freight/Freight.md"),
                          ("Acme", "Renewal", "Acme/Threads/Renewal/Renewal.md")], stack())
        self.act(verb="rename", zone="Work", project="Acme", to="Apex")
        self.assertEqual([("Apex", "Freight", "Apex/Threads/Freight/Freight.md"),
                          ("Apex", "Renewal", "Apex/Threads/Renewal/Renewal.md")], stack())
        self.act(verb="delete", zone="Work", project="Apex", thread="Freight")         # a dry run drops nothing
        self.assertEqual(2, len(stack()))
        self.act(verb="delete", zone="Work", project="Apex", thread="Freight", confirm="Freight")
        self.assertEqual("Back to Apex, Renewal.", self.act(verb="back")["say"].split(" Interrupted")[0])
        self.assertTrue((self.root / "System" / "generated" / "interrupted.json").is_file())
        root = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=str(self.root),
                              capture_output=True, text=True, env=self.env).stdout
        self.assertNotIn("interrupted.json", root)


class TestParkBothWays(ManageCase):
    """One request run both ways. The page and the command line must make the
    same change and give the same refusal, word for word, which is what the
    ticket asks of every operation the two share."""

    def setUp(self):
        super().setUp()
        os.environ["GARRICK_JOBS_DIR"] = str(self.base / "jobs")
        self.note = self.work / "Acme" / "Threads" / "Pricing" / "Pricing.md"
        self.today = datetime.date.today().isoformat()

    def cli(self, verb, *args):
        """scaffold.py, as the threads skill runs it."""
        return self.scaffold("--today", self.today, verb, "--zone", "Work", "--project", "Acme", *args)

    def page(self, **req):
        """page_action.py, as the status page's host runs it: one JSON request
        on stdin, one JSON reply, the whole way through main()."""
        done = subprocess.run([sys.executable, str(REPO / "extras" / "status" / "page_action.py"),
                               "--workspace", str(self.root)], input=json.dumps(req), capture_output=True,
                              text=True, env=dict(self.env, GARRICK_JOBS_DIR=str(self.base / "jobs")))
        self.assertTrue(done.stdout, done.stderr)
        return json.loads(done.stdout)

    def restore(self):
        self.git("checkout", "--", "Acme")
        self.assertEqual("", self.git("status", "--porcelain").stdout)

    def test_a_park_both_ways_makes_the_same_change(self):
        r = self.cli("park", "--thread", "Pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("Acme, Pricing is parked", r.stdout.strip())
        by_cli = self.note.read_text()
        self.assertIn("\nstatus: parked\n", by_cli)
        self.assertIn("**%d " % datetime.date.today().day, by_cli)
        self.assertEqual(["Acme/Threads/Pricing/Pricing.md"],                  # left for the caller to commit
                         [l[3:] for l in self.git("status", "--porcelain").stdout.splitlines()])
        self.restore()
        reply = self.page(verb="park", zone="Work", project="Acme", thread="Pricing")
        self.assertEqual({"ok": True, "say": "Acme, Pricing is parked"}, {k: reply[k] for k in ("ok", "say")})
        self.assertEqual(by_cli, self.note.read_text())                        # the same note, to the byte
        self.assertEqual("Acme, Pricing: parked", self.git("log", "-1", "--format=%s").stdout.strip())
        self.assertEqual("", self.git("status", "--porcelain").stdout)         # and committed, which the page does

    def test_a_wake_both_ways_makes_the_same_change(self):
        self.cli("park", "--thread", "Pricing")
        self.commit("Pricing parked")
        r = self.cli("wake", "--thread", "Pricing")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("Acme, Pricing is awake again", r.stdout.strip())
        by_cli = self.note.read_text()
        self.restore()
        reply = self.page(verb="wake", zone="Work", project="Acme", thread="Pricing")
        self.assertEqual("Acme, Pricing is awake again", reply["say"])
        self.assertEqual(by_cli, self.note.read_text())

    def test_a_second_park_is_refused_in_the_same_words_both_ways(self):
        self.cli("park", "--thread", "Pricing")
        self.commit("Pricing parked")
        again = self.cli("park", "--thread", "Pricing")
        self.assertEqual(1, again.returncode, again.stdout)
        self.assertEqual("Not done. Pricing was set aside already, so nothing was changed.", again.stderr.strip())
        self.assertEqual("", self.git("status", "--porcelain").stdout)          # the refusal changed nothing
        reply = self.page(verb="park", zone="Work", project="Acme", thread="Pricing")
        self.assertEqual(False, reply["ok"])
        self.assertEqual(again.stderr.strip(), reply["say"])                    # the same sentence, to the byte
        self.assertEqual(("failed", "refused"), (reply["state"], reply["outcome"]))
        self.assertEqual("", self.git("status", "--porcelain").stdout)
        self.assertEqual(1, self.note.read_text().count("Parked."))             # and no second dated entry

    def test_a_project_and_a_thread_of_it_are_told_apart_both_ways(self):
        r = self.cli("park")                                                    # the project, by name alone
        self.assertEqual("Acme is parked", r.stdout.strip())
        self.assertIn("\nstatus: parked\n", (self.work / "Acme" / "Acme.md").read_text())
        self.assertNotIn("\nstatus: parked\n", self.note.read_text())          # its threads keep their own
        by_cli = (self.work / "Acme" / "Acme.md").read_text()
        self.restore()
        self.assertEqual("Acme is parked", self.page(verb="park", zone="Work", project="Acme")["say"])
        self.assertEqual(by_cli, (self.work / "Acme" / "Acme.md").read_text())

    def test_what_neither_way_will_do(self):
        r = self.cli("park", "--thread", "Nope")
        self.assertEqual(1, r.returncode, r.stdout)
        self.assertIn("There is no thread called Nope", r.stderr)
        r = self.scaffold("park", "--zone", "Work", "--project", "Nothing")
        self.assertEqual(1, r.returncode, r.stdout)
        self.assertIn("There is no project called Nothing", r.stderr)
        for req in ({"verb": "park", "zone": "Work", "project": "Acme", "thread": "Nope"},
                    {"verb": "park", "zone": "Work", "project": "Nothing"}):
            with self.assertRaises(pa.Refused, msg=req):
                pa.act(self.root, req)
        # a field the table does not declare, the one refusal the two make
        # differently: argparse names the flag, operations.py names the field
        # (undo's `commit`: `confirm` is park's own since #137, naming an earlier park it was asked about)
        bad = self.cli("park", "--thread", "Pricing", "--commit", "abc1234")
        self.assertEqual(2, bad.returncode)
        self.assertIn("--commit", bad.stderr)
        reply = self.page(verb="park", zone="Work", project="Acme", thread="Pricing", commit="abc1234")
        self.assertEqual("Not done. Park takes no commit field.", reply["say"])

    def test_the_two_dated_entry_copies_agree_where_a_note_has_an_anchor(self):
        """scaffold.py's dated_entry writes rename's entry and now park's;
        page_action.py keeps its own for `interrupt`. The two already read a
        note with no anchor differently, so park asks for the page's reading
        of that one, and the other difference is pinned here rather than
        left to be found by a note."""
        scaffold = self.tool("scaffold.py")
        today, iso = datetime.date(2026, 10, 5), "2026-10-05"
        for body in ("### Resume here\n\n| Next action | x |\n\n---\n\n<Dated entries, newest first.>\n\n**1 March 2026.** Started.\n",
                     "## State of play\n\n**1 March 2026.** Started.\n",
                     "### Resume here\n\n---\n**1 March 2026.** Started.\n"):
            for said in ("Parked.", "Woken."):
                self.assertEqual(scaffold.dated_entry(body, said, iso, append=False),
                                 pa.dated_entry(body, today, said), body)
        bare = "Nothing to add to.\n"                      # no block of either kind
        self.assertEqual(bare, pa.dated_entry(bare, today, "Parked."))
        self.assertEqual(bare, scaffold.dated_entry(bare, "Parked.", iso, append=False))
        self.assertIn("**5 October 2026.** Renamed.", scaffold.dated_entry(bare, "Renamed.", iso))
        odd = "### Resume here\n\nWhere it stands.\n\n## State of play\n\n**1 March 2026.** Started.\n"
        self.assertEqual(odd, pa.dated_entry(odd, today, "Parked."))          # a block with no rule under it
        self.assertIn("## State of play\n\n**5 October 2026.** Parked.",
                      scaffold.dated_entry(odd, "Parked.", iso, append=False))

    def tool(self, name):
        spec = importlib.util.spec_from_file_location("garrick_" + name[:-3], str(self.root / "System" / "tools" / name))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


if __name__ == "__main__":
    unittest.main()
