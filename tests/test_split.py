"""Tests for split.py, `install.py --update --split`: moving a workspace's own
text out of Garrick's instruction files into the local file beside each.

    python3 -m unittest discover -s tests

The workspaces are real installs, as in test_update. An older Garrick is
simulated by committing an older rules.md as Garrick's own write, with its
fingerprint in the stamp; the user's changes are committed on top.
"""

import json
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True

from test_update import INSTALL, OLDER, Case, sha  # noqa: E402

import split  # noqa: E402  (test_update puts the repository on sys.path)
import update  # noqa: E402

RULES = "System/rules.md"
LOCAL = "System/rules.local.md"

# What Garrick wrote since the older release, in lines of this Garrick's rules.md.
SUMMARY = ("- No summary at the end of what is already on screen. Do report what the user could not see: "
           "files changed, commands run, what failed.")
OLD_SUMMARY = "- No summary at the end of what is on screen. Report what the user could not see."
DROPPED = "- Keep the fax number of every party in the hub note, beside its pager."
SECRET = "- Never print, write or commit a secret."
ESTIMATES = '- Estimates in real units: "twenty minutes", "two sessions".'
ZONE_LINE = "- Which zone applies, when the task does not make it obvious."

# What the user did to the older release's rules.
BILLING = "- Which client account to bill, every time."
TRAVEL = ["## Travel", "", "- Book trains, never flights, under six hundred kilometres.", "", "```sh",
          "python3 trains.py --cheapest", "```"]
MY_SECRET = "- Never print, write, paste or commit a secret, not even in a scratch file."


class SplitCase(Case):
    def shipped(self, path=RULES):
        return update.plan(self.root)["files"][path][0].decode("utf-8")

    def older(self):
        """Garrick's rules as the older release wrote them: one line worded
        differently, one line Garrick has since dropped."""
        text = self.shipped()
        self.assertIn(SUMMARY, text)
        self.assertIn(SECRET, text)
        return text.replace(SUMMARY, OLD_SUMMARY).replace(SECRET, SECRET + "\n" + DROPPED)

    def take_older(self, text):
        """Commit `text` as Garrick's own write of the rules, and record it in the stamp."""
        (self.root / RULES).write_text(text)
        self.git(self.root, "add", "--", RULES)
        self.git(self.root, "commit", "-q", "--no-verify", "-m", "Garrick: update to %s, 1 file" % OLDER)
        stamp = self.stamp()
        stamp["commit"] = OLDER
        stamp["files"][RULES] = sha(text)
        self.set_stamp(stamp)

    def diverge(self, user=None):
        """The workspace this suite is about: rules taken from an older
        Garrick, then given a line of the user's own in a section, a section of
        the user's own, a Garrick sentence changed and one deleted."""
        older = self.older()
        self.take_older(older)
        if user is None:
            user = older.replace(ZONE_LINE, ZONE_LINE + "\n" + BILLING).replace(SECRET, MY_SECRET)
            user = user.replace(ESTIMATES + "\n", "")
            user = user.rstrip("\n") + "\n\n" + "\n".join(TRAVEL) + "\n"
        (self.root / RULES).write_text(user)
        self.commit(self.root, "My rules")
        return older, user

    def split_plan(self, only=None):
        return split.plan(self.root, update.plan(self.root), only)

    def check(self, *args):
        r = subprocess.run([sys.executable, str(self.root / "System/tools/check.py"), "--root", str(self.root),
                            "--json", *args], capture_output=True, text=True, env=self.env)
        return [f for f in json.loads(r.stdout)["findings"] if f["check"] == "instructions"]


class TestThePlan(SplitCase):
    def test_the_update_lists_it_and_the_split_sorts_each_change(self):
        older, user = self.diverge()
        self.assertEqual([RULES], update.plan(self.root)["actions"]["split"])
        [item] = self.split_plan()
        self.assertEqual(LOCAL, item["local"])
        base = self.git(self.root, "log", "-1", "--format=%h", "--grep=^Garrick: update to " + OLDER)
        self.assertEqual(base, item["base"])
        self.assertEqual([("## Autonomy", [BILLING]), ("## Travel", TRAVEL[2:])], item["additions"])
        kinds = [(d["kind"], d["section"]) for d in item["decisions"]]
        self.assertEqual([("changed", "## Secrets"), ("removed", "## Talking to me")], kinds)
        changed, removed = item["decisions"]
        self.assertEqual([SECRET], changed["garrick"])
        self.assertEqual([MY_SECRET], changed["yours"])
        self.assertEqual([ESTIMATES], removed["garrick"])
        self.assertEqual([], item["unplaced"])
        # Garrick's own change since the base, to a line left alone, is taken; the line it dropped stays dropped.
        self.assertNotIn(OLD_SUMMARY, item["text"])
        self.assertNotIn(DROPPED, item["text"])

    def test_the_report_names_the_base_the_moves_and_each_passage_to_settle(self):
        self.diverge()
        r = subprocess.run([sys.executable, str(INSTALL), "--update", str(self.root), "--split"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Nothing has been changed", r.stdout)
        self.assertIn("System/rules.md: Garrick's as shipped, yours to System/rules.local.md.", r.stdout)
        self.assertIn("Base: Garrick's version from commit", r.stdout)
        self.assertIn("Moves what you added: Autonomy (1 line), Travel (", r.stdout)
        self.assertIn("1. Changed, under Secrets.", r.stdout)
        self.assertIn("Garrick's: " + SECRET, r.stdout)
        self.assertIn("Yours: " + MY_SECRET, r.stdout)
        self.assertIn("2. Removed, under Talking to me.", r.stdout)
        self.assertEqual("", self.git(self.root, "status", "--porcelain"))      # a report writes nothing
        r = subprocess.run([sys.executable, str(INSTALL), "--update", str(self.root), "--split", "--json"],
                           capture_output=True, text=True, env=self.env)
        data = json.loads(r.stdout)
        self.assertEqual([RULES], [x["path"] for x in data])
        self.assertEqual(["changed", "removed"], [d["kind"] for d in data[0]["decisions"]])

    def test_a_line_both_sides_changed_is_settled_with_garricks_newer_wording(self):
        older = self.older()
        self.diverge(older.replace(OLD_SUMMARY, "- No summary at the end. Report what the user could not see, briefly."))
        [item] = self.split_plan()
        [d] = item["decisions"]
        self.assertEqual("both", d["kind"])
        self.assertEqual([OLD_SUMMARY], d["garrick"])
        self.assertEqual([SUMMARY], d["newer"])
        self.assertIn("Changed on both sides, under Talking to me", item["text"])
        self.assertIn("Garrick has since changed it too", item["text"])

    def test_a_line_you_moved_is_not_taken_for_yours(self):
        older = self.older()
        moved = older.replace(ESTIMATES + "\n", "").replace(ZONE_LINE, ZONE_LINE + "\n" + ESTIMATES)
        self.diverge(moved)
        [item] = self.split_plan()
        self.assertEqual([], item["additions"])
        self.assertEqual([], item["decisions"])

    def test_without_a_base_all_that_differs_counts_as_yours(self):
        self.diverge()
        with mock.patch.object(split, "garrick_versions", return_value=[]):
            [item] = self.split_plan()
        self.assertIsNone(item["base"])
        text = split.report(self.root, [item])
        self.assertIn("no Garrick version in its history", text)
        # What differs from this Garrick's is never lost: the line Garrick has since reworded is the user's now.
        self.assertIn(OLD_SUMMARY, item["text"])
        self.assertIn(BILLING, item["text"])

    def test_only_names_files_the_split_has(self):
        self.diverge()
        with self.assertRaises(update.UpdateError):
            self.split_plan(only=["System/tools/check.py"])
        self.assertEqual([RULES], [x["path"] for x in self.split_plan(only=[RULES])])

    def test_nothing_to_split_on_a_fresh_install(self):
        self.assertEqual([], self.split_plan())
        self.assertIn("Nothing to split", split.report(self.root, []))


class TestNothingIsLost(SplitCase):
    def assertKeeps(self, user, base, shipped, text):
        """Every line of `user` is in Garrick's file or the local file, or is
        Garrick's own wording that Garrick has since dropped."""
        self.assertEqual([], split.unplaced(user, base, shipped, text))

    def test_every_line_of_yours_ends_up_somewhere(self):
        older, user = self.diverge()
        [item] = self.split_plan()
        self.assertKeeps(user, older, self.shipped(), item["text"])

    def test_a_rewritten_file_keeps_every_line(self):
        older = self.older()
        user = "# My rules\n\nI wrote these myself, long before Garrick.\n\n## Autonomy\n\n- Ask before anything.\n" \
               "- Never ask about reading.\n\n## Odd\n\n| a | b |\n|---|---|\n| one | two |\n"
        self.diverge(user)
        [item] = self.split_plan()
        self.assertKeeps(user, older, self.shipped(), item["text"])
        for line in user.splitlines():
            if line.strip() and line not in self.shipped():
                self.assertIn(line, item["text"])

    def test_a_line_that_finds_no_place_goes_under_the_review_heading(self):
        self.diverge()
        with mock.patch.object(split, "split_text", return_value=([], [])):
            [item] = self.split_plan()
        self.assertIn(BILLING, item["unplaced"])
        review = item["text"].split("## From your earlier rules.md, to review", 1)[1]
        self.assertIn("Not placed", review)
        self.assertIn(BILLING, review)

    def test_split_text_on_its_own(self):
        base = "# Rules\n\n## A\n\n- Garrick one, about the first thing.\n- Garrick two, about the second thing.\n"
        shipped = base
        user = ("# Rules\n\n## A\n\n- Garrick one, about the first thing, reworded by me.\n- Mine alone, a new rule.\n"
                "\n## B\n\n```\ncode\n```\n")
        additions, decisions = split.split_text(user, base, shipped)
        self.assertEqual("changed", decisions[0]["kind"])
        self.assertEqual(["- Garrick one, about the first thing, reworded by me.", "- Mine alone, a new rule."],
                         decisions[0]["yours"])
        self.assertEqual(["- Garrick one, about the first thing.", "- Garrick two, about the second thing."],
                         decisions[0]["garrick"])                        # one passage, settled as one
        self.assertEqual(1, len(decisions))
        self.assertEqual([("## B", ["```", "code", "```"])], additions)     # the fences move with their block


class TestApply(SplitCase):
    def test_garricks_file_as_shipped_and_yours_beside_it_in_one_commit(self):
        older, user = self.diverge()
        shipped = self.shipped()
        items = self.split_plan()
        result = split.apply(self.root, items)
        self.assertEqual([RULES], result["done"])
        self.assertEqual(shipped, (self.root / RULES).read_text())
        local = (self.root / LOCAL).read_text()
        self.assertTrue(local.startswith("# Your rules\n"))           # the installer's start, kept
        autonomy = local.split("## Autonomy", 1)[1].split("\n## ", 1)[0]
        self.assertIn(BILLING, autonomy)
        self.assertIn("## Travel\n\n" + "\n".join(TRAVEL[2:]), local)
        review = local.split("## From your earlier rules.md, to review", 1)[1]
        self.assertIn("### 1. Changed, under Secrets", review)
        self.assertIn(MY_SECRET, review)
        self.assertIn('Garrick\'s line beginning "Never print, write or commit a secret"', review)
        self.assertIn("### 2. Removed, under Talking to me", review)
        self.assertNotIn(SECRET, review)                              # Garrick's is named, not copied
        self.assertEqual("", self.git(self.root, "status", "--porcelain"))
        subjects = self.git(self.root, "log", "-2", "--format=%s").splitlines()
        self.assertEqual("Garrick: version stamp after the split", subjects[0])
        self.assertEqual("Garrick: System/rules.md as shipped, your text in System/rules.local.md", subjects[1])
        self.assertEqual(sha(shipped), self.stamp()["files"][RULES])
        self.assertEqual([], update.plan(self.root)["actions"]["split"])
        self.assertEqual([], self.split_plan())                       # twice changes nothing

    def test_the_check_warns_before_the_split_and_until_the_passages_are_settled(self):
        self.diverge()
        before = self.check()
        self.assertEqual([RULES], [f["path"] for f in before])
        self.assertIn("differs from what Garrick shipped", before[0]["message"])
        self.assertIn(LOCAL, before[0]["message"])
        split.apply(self.root, self.split_plan())
        after = self.check()
        self.assertEqual([LOCAL], [f["path"] for f in after])
        self.assertIn("still holds 2 passages from the split to settle", after[0]["message"])
        local = self.root / LOCAL
        local.write_text(local.read_text().split("## From your earlier", 1)[0])
        self.assertEqual([], self.check())

    def test_a_local_file_already_there_is_added_to(self):
        (self.root / LOCAL).write_text("# Your rules\n\n## Autonomy\n\n- Mine from before.\n\n"
                                       "## From your earlier rules.md, to review\n\nIntro.\n\n### 1. Changed, at the top\n\n"
                                       "Earlier.\n")
        self.commit(self.root, "local rules")
        self.diverge()
        split.apply(self.root, self.split_plan())
        local = (self.root / LOCAL).read_text()
        self.assertIn("- Mine from before.\n\n" + BILLING, local)
        self.assertEqual(1, local.count("## Autonomy"))
        self.assertEqual(1, local.count("## From your earlier rules.md, to review"))
        self.assertIn("### 2. Changed, under Secrets", local)
        self.assertIn("### 3. Removed, under Talking to me", local)

    def test_a_new_an_earlier_update_left_goes_in_the_same_commit(self):
        older, user = self.diverge()
        new = self.root / (RULES + ".new")
        new.write_text(self.shipped())
        self.git(self.root, "add", "--", RULES + ".new")
        self.git(self.root, "commit", "-q", "--no-verify", "-m", "Garrick: update to 1111111, 1 file")
        [item] = self.split_plan()
        self.assertEqual(RULES + ".new", item["new"])
        self.assertIn(RULES + ".new", split.report(self.root, [item]))
        split.apply(self.root, [item])
        self.assertFalse(new.exists())
        self.assertIn(RULES + ".new", self.git(self.root, "show", "--format=", "--name-only", "HEAD~1"))
        self.assertEqual("", self.git(self.root, "status", "--porcelain"))

    def test_a_zone_file_splits_in_its_own_repository(self):
        path = "Zones/Work/AGENTS.md"
        work = self.root / "Zones" / "Work"
        text = (self.root / path).read_text()
        (self.root / path).write_text(text.replace("## Parties\n", "## Parties\n\nAcme Corp's work goes to Acme Review.\n"))
        self.commit(work, "My route")
        [item] = self.split_plan()
        self.assertEqual("Zones/Work/AGENTS.local.md", item["local"])
        self.assertEqual([("## Parties", ["Acme Corp's work goes to Acme Review."])], item["additions"])
        split.apply(self.root, [item])
        self.assertEqual(text, (self.root / path).read_text())
        local = (work / "AGENTS.local.md").read_text()
        self.assertTrue(local.startswith("# Work zone, this workspace's own\n"))
        self.assertIn("## Parties\n\nAcme Corp's work goes to Acme Review.", local)
        self.assertEqual("", self.git(work, "status", "--porcelain"))
        self.assertEqual([], [f for f in self.check() if f["path"].startswith("Zones/Work")])

    def test_changes_not_committed_are_skipped(self):
        self.diverge()
        (self.root / LOCAL).write_text("# Your rules\n\n- Not committed yet.\n")
        result = split.apply(self.root, self.split_plan())
        self.assertEqual([], result["done"])
        self.assertIn("not committed", result["skipped"][0][1])
        self.assertIn(MY_SECRET, (self.root / RULES).read_text())

    def test_a_refused_commit_puts_everything_back(self):
        older, user = self.diverge()
        local = (self.root / LOCAL).read_text()
        hook = self.root / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        result = split.apply(self.root, self.split_plan())
        self.assertEqual([], result["done"])
        self.assertIn("put back", result["skipped"][0][1])
        self.assertEqual(user, (self.root / RULES).read_text())
        self.assertEqual(local, (self.root / LOCAL).read_text())
        self.assertEqual("", self.git(self.root, "status", "--porcelain"))

    def test_apply_from_the_command_line(self):
        self.diverge()
        r = subprocess.run([sys.executable, str(INSTALL), "--update", str(self.root), "--split", "--apply"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("System/rules.md is Garrick's as shipped; your text is in System/rules.local.md, "
                      "with 2 passages to settle under its review heading.", r.stdout)


if __name__ == "__main__":
    unittest.main()
