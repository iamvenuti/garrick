"""People and Aliases in System/names.md, and the held step that moves them there (#653).

    cd tests && python3 -m unittest test_names

Every workspace is a real install in a temporary folder, as in test_update. A workspace from before the split is
made by putting the two tables back into context.md and taking names.md away.
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from test_update import Case, REPO  # noqa: E402

sys.path.insert(0, str(REPO / "template" / "System" / "tools"))
import check  # noqa: E402
import garrick_lib as lib  # noqa: E402
import names_move  # noqa: E402
import update  # noqa: E402

CONTEXT = "System/context.md"
NAMES = "System/names.md"
POINTER_HEADING = "## People and Aliases"


def section(text, heading):
    m = re.search(r"(?ms)^## %s\n.*?(?=^## |\Z)" % re.escape(heading), text)
    return m.group(0) if m else ""


class Legacy(Case):
    """A workspace as 0.76 left it: People and Aliases in context.md, no names.md."""

    def go_back(self):
        names = (self.root / NAMES).read_text()
        context = (self.root / CONTEXT).read_text()
        old = section(context, "People and Aliases")
        self.assertTrue(old, "the template's context.md has the pointer section")
        tables = "\n".join(names.split("\n## ", 1)[1:]).strip("\n")
        (self.root / CONTEXT).write_text(context.replace(old, "## " + tables + "\n\n"))
        (self.root / NAMES).unlink()
        self.commit(self.root, "as 0.76 left it")

    def run_update(self, *args):
        return subprocess.run([sys.executable, str(REPO / "install.py"), "--update", str(self.root), *args],
                              capture_output=True, text=True, env=self.env)


class TheReader(Case):
    def test_a_new_workspace_keeps_its_people_and_aliases_in_names_md(self):
        context = (self.root / CONTEXT).read_text()
        names = (self.root / NAMES).read_text()
        self.assertNotIn("## People\n", context)
        self.assertNotIn("## Aliases", context)
        self.assertIn("System/names.md", context)
        self.assertIn("| Dana Whitlock | `acme` |", names)
        self.assertIn("| dana whitlaw | Dana Whitlock |", names)
        ctx = lib.load_context(self.root)
        self.assertEqual(["Dana Whitlock", "Theo Marsh"], [p["name"] for p in ctx["people"]])
        self.assertEqual("Dana Whitlock", ctx["aliases"]["dana whitlaw"])
        self.assertTrue(ctx["names_file"])
        self.assertEqual({"people": 2, "aliases": 2}, {t: ctx["tables"][t]["rows"] for t in ("people", "aliases")})

    def test_rows_in_both_files_are_all_read_names_first_and_none_is_dropped(self):
        path = self.root / CONTEXT
        path.write_text(path.read_text() + "\n## People\n\n| Name | Party | Role |\n|---|---|---|\n"
                        "| Alex Birch | `birch` | Buyer |\n| Dana Whitlock | `acme` | Repeated |\n\n"
                        "## Aliases\n\n| Heard | Means |\n|---|---|\n| alex birchen | Alex Birch |\n")
        ctx = lib.load_context(self.root)
        self.assertEqual(["Dana Whitlock", "Theo Marsh", "Alex Birch", "Dana Whitlock"], [p["name"] for p in ctx["people"]])
        self.assertEqual({"dana whitlaw", "birch and co", "birchen co", "alex birchen"}, set(ctx["aliases"]))
        self.assertEqual(4, ctx["tables"]["people"]["rows"])

    def test_with_no_names_md_the_tables_are_read_from_context_md_as_before(self):
        (self.root / NAMES).rename(self.root / "elsewhere.md")
        text = (self.root / CONTEXT).read_text()
        (self.root / CONTEXT).write_text(text + "\n## People\n\n| Name | Party | Role |\n|---|---|---|\n| Alex Birch | `birch` | Buyer |\n")
        ctx = lib.load_context(self.root)
        self.assertEqual(["Alex Birch"], [p["name"] for p in ctx["people"]])
        self.assertFalse(ctx["names_file"])

    def test_every_table_says_which_file_it_is_in(self):
        self.assertEqual({"people": "names.md", "aliases": "names.md"}, lib.TABLE_FILE)
        self.assertEqual(["System/names.md", "System/context.md"],
                         [p.relative_to(self.root).as_posix() for p in lib.table_files(self.root, "people")])
        self.assertEqual(["System/context.md"],
                         [p.relative_to(self.root).as_posix() for p in lib.table_files(self.root, "parties")])

    def test_names_md_is_the_users_and_an_update_never_lists_or_replaces_it(self):
        self.assertIn(NAMES, lib.UNLISTED)
        self.assertNotIn(NAMES, self.stamp()["files"])
        self.assertNotIn(NAMES, update.shipped(update.zones_of(self.root, self.stamp())))
        (self.root / NAMES).write_text((self.root / NAMES).read_text() + "| Jo Maple | | Buyer |\n")
        self.commit(self.root, "my row")
        p = self.plan()
        self.assertEqual({k: [] for k in update.KINDS}, p["actions"])
        self.assertEqual("none", p["names"]["state"])

    def test_the_shared_files_list_has_names_md_as_it_has_context_md(self):
        self.assertIn(NAMES, check.SHARED_FILES)
        self.assertIn(CONTEXT, check.SHARED_FILES)


class TheBudget(Case):
    def test_context_md_is_under_its_budget_in_the_example_workspace(self):
        self.assertLess(len((self.root / CONTEXT).read_text()), check.CONTEXT_CHAR_BUDGET)
        self.assertEqual(8000, check.CONTEXT_CHAR_BUDGET)

    def grow(self, people=90, parties=12):
        """A workspace used for some months, with invented parties and people."""
        context = (self.root / CONTEXT).read_text()
        rows = "".join("| Cedar Works %d | Client. Supply review, round %d | Work | `cw%d` | cedar%d.example |\n" % (i, i, i, i)
                       for i in range(parties))
        context = context.replace("| Birch & Co |", rows + "| Birch & Co |", 1)
        (self.root / CONTEXT).write_text(context)
        names = (self.root / NAMES).read_text()
        rows = "".join("| Person Maple%d | `cw%d` | Head of area %d; owns the review of lane %d |\n" % (i, i % parties, i, i)
                       for i in range(people))
        (self.root / NAMES).write_text(names.replace("| Theo Marsh |", rows + "| Theo Marsh |", 1))

    def test_context_md_is_under_its_budget_with_about_ninety_people(self):
        self.grow()
        self.assertGreater(len((self.root / NAMES).read_text()), 4000)
        self.assertLess(len((self.root / CONTEXT).read_text()), check.CONTEXT_CHAR_BUDGET)
        self.assertEqual(92, len(lib.load_context(self.root)["people"]))
        self.assertEqual([], self.budget_findings())

    def budget_findings(self):
        return [f for f in check.run_checks(self.root, quick=True) if "above the" in f.message and "context" in f.path]

    def test_check_warns_above_the_budget_and_names_the_section_that_grew(self):
        context = (self.root / CONTEXT).read_text()
        rows = "".join("| Cedar Works %d | %s | Work | `cw%d` | cedar%d.example |\n" % (i, "A client of long standing. " * 6, i, i)
                       for i in range(30))
        (self.root / CONTEXT).write_text(context.replace("| Birch & Co |", rows + "| Birch & Co |", 1))
        found = self.budget_findings()
        self.assertEqual(1, len(found), found)
        self.assertEqual("warning", found[0].severity)
        self.assertIn("section that grew most is Parties", found[0].message)
        self.assertIn("8000", found[0].message)

    def test_a_context_md_that_still_holds_people_is_told_where_they_go(self):
        context = (self.root / CONTEXT).read_text()
        rows = "".join("| Person Maple%d | `acme` | %s |\n" % (i, "Head of area, owner of the lane review. " * 3) for i in range(90))
        (self.root / NAMES).unlink()
        (self.root / CONTEXT).write_text(context + "\n## People\n\n| Name | Party | Role |\n|---|---|---|\n" + rows
                                         + "\n## Aliases\n\n| Heard | Means |\n|---|---|\n| dana whitlaw | Dana Whitlock |\n")
        found = self.budget_findings()
        self.assertEqual(1, len(found), found)
        self.assertIn("section that grew most is People", found[0].message)
        self.assertIn("moves People and Aliases to System/names.md on your yes", found[0].message)


class TheAlwaysLoadedFiles(unittest.TestCase):
    """A session given a mangled spoken name reads names.md and finds the row, in either assistant: offline, the
    nearest test is that what both load names the file, and the skills that resolve a name read it."""

    def read(self, rel):
        return (REPO / "template" / rel).read_text(encoding="utf-8")

    def test_rules_and_context_name_names_md(self):
        self.assertIn("`System/names.md`", self.read("System/rules.md"))
        context = self.read("System/context.md")
        self.assertIn("System/names.md", context)
        self.assertIn("Read it before acting on a name you cannot place", context)
        self.assertLess(len(self.read("System/rules.md")), 8000)

    def test_the_skills_that_resolve_a_name_read_names_md(self):
        for skill in ("threads", "intake", "meetings", "nurture", "interview"):
            text = self.read("System/skills/%s/SKILL.md" % skill)
            self.assertRegex(text, r"People, Aliases\s*\| `System/names.md`|People and Aliases\)? in `System/names.md`|`System/names.md`", skill)
        self.assertIn("Look it up in Aliases** (`System/names.md`)", self.read("System/skills/threads/SKILL.md"))
        self.assertIn("People and Aliases of `System/names.md`", self.read("System/skills/intake/SKILL.md"))

    def test_no_skill_still_sends_a_person_or_an_alias_to_context_md(self):
        for path in sorted((REPO / "template" / "System" / "skills").rglob("*.md")):
            text = " ".join(path.read_text(encoding="utf-8").split())
            for bad in ("Aliases (`System/context.md`)", "People, Aliases | `System/context.md`",
                        "the Aliases table, in context.md"):
                self.assertNotIn(bad, text, path.name)

    def test_the_template_has_the_file_the_installer_fills(self):
        names = self.read("System/names.md")
        self.assertIn("## People", names)
        self.assertIn("## Aliases", names)
        self.assertIn("| Heard | Means |", names)
        self.assertIn("| Name | Party | Role |", names)


class TheWriters(Case):
    def scaffold(self, *args):
        return subprocess.run([sys.executable, str(self.root / "System" / "tools" / "scaffold.py"), *args],
                              capture_output=True, text=True, env=self.env, cwd=str(self.root))

    def test_a_rename_writes_the_heard_name_to_names_md(self):
        for args in (("project", "--zone", "Work", "--name", "Acme", "--party", "acme", "--thread", "Pricing"),):
            r = self.scaffold(*args)
            self.assertEqual(0, r.returncode, r.stderr)
        zone = self.root / "Zones" / "Work"
        self.git(zone, "add", "-A")
        self.git(zone, "commit", "-q", "-m", "Acme set up")
        before = (self.root / CONTEXT).read_bytes()
        r = self.scaffold("--today", "2027-01-01", "rename", "--zone", "Work", "--project", "Acme", "--thread", "Pricing",
                          "--to", "Renewal")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("in System/names.md", r.stdout)
        self.assertIn("| pricing | Renewal | 2027-01-01, user |", (self.root / NAMES).read_text())
        self.assertEqual(before, (self.root / CONTEXT).read_bytes())

    def test_a_correction_finds_and_fixes_a_name_in_names_md(self):
        import correct
        hits = correct.find_hits(self.root, "Theo Marsh", "Theo Marshall")
        self.assertIn(NAMES, {h.path.relative_to(self.root).as_posix() for h in hits})

    def test_the_example_leaves_and_comes_back_with_its_people_in_names_md(self):
        import example
        names = (self.root / NAMES).read_text()
        context = (self.root / CONTEXT).read_text()
        (self.root / "System" / "names.md").write_text(names.replace("| Theo Marsh |", "| Jo Maple | `acme` | Buyer |\n| Theo Marsh |", 1))
        taken, rows = example.take_rows({"context.md": context, "names.md": (self.root / NAMES).read_text()}, "Work")
        files = {r["file"] for r in rows}
        self.assertEqual({"context.md", "names.md"}, files)
        self.assertNotIn("Dana Whitlock", taken["names.md"])
        self.assertIn("`acme`", "".join(r["line"] for r in rows))
        back = example.put_rows(taken, rows)
        self.assertEqual(context, back["context.md"])
        self.assertEqual((self.root / NAMES).read_text(), back["names.md"])

    def test_an_archive_made_before_the_move_comes_back_into_names_md(self):
        import example
        rows = [{"section": "People", "line": "| Jo Maple | `acme` | Buyer |", "after": "|---|---|---|"}]
        texts = {"context.md": (self.root / CONTEXT).read_text(), "names.md": (self.root / NAMES).read_text()}
        back = example.put_rows(texts, rows)
        self.assertIn("| Jo Maple |", back["names.md"])
        self.assertNotIn("Jo Maple", back["context.md"])


class TheMove(Legacy):
    def setUp(self):
        super().setUp()
        self.go_back()
        self.before = (self.root / CONTEXT).read_text()
        self.rows = [l for l in self.before.split("\n")
                     if l.startswith("|") and ("Dana" in l or "Theo" in l or "birch and co" in l or "dana whitlaw" in l)]
        self.assertEqual(4, len(self.rows))

    def test_the_report_says_the_move_is_waiting_and_nothing_is_written(self):
        p = self.plan()
        self.assertEqual("waiting", p["names"]["state"])
        self.assertIn("still in System/context.md", update.report(p))
        self.assertIn("--names", update.report(p))
        head = self.head(self.root)
        r = self.run_update()
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("With your yes the update moves them to System/names.md", r.stdout)
        self.assertEqual(head, self.head(self.root))
        self.assertEqual(self.before, (self.root / CONTEXT).read_text())

    def test_an_update_with_apply_never_moves_them(self):
        r = self.run_update("--apply", "--yes")
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)
        self.assertFalse((self.root / NAMES).exists())
        self.assertEqual(self.before, (self.root / CONTEXT).read_text())

    def test_names_without_apply_says_what_would_move_and_changes_nothing(self):
        head = self.head(self.root)
        r = self.run_update("--names")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("People (2 rows) and Aliases (2 rows)", r.stdout)
        self.assertIn("--apply", r.stdout)
        self.assertEqual(head, self.head(self.root))
        self.assertFalse((self.root / NAMES).exists())

    def test_names_apply_moves_every_row_once_and_leaves_a_pointer(self):
        r = self.run_update("--names", "--apply")
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)
        context = (self.root / CONTEXT).read_text()
        names = (self.root / NAMES).read_text()
        for row in self.rows:
            self.assertEqual(1, names.split("\n").count(row), row)
            self.assertNotIn(row, context.split("\n"))
        self.assertNotRegex(context, r"(?m)^## (People|Aliases)\s*$")
        self.assertIn(POINTER_HEADING, context)
        self.assertIn("`System/names.md`", context)
        self.assertEqual("", self.git(self.root, "status", "--porcelain"))
        self.assertIn("People and Aliases move to System/names.md", self.git(self.root, "log", "-1", "--format=%s"))
        ctx = lib.load_context(self.root)
        self.assertEqual(["Dana Whitlock", "Theo Marsh"], [p["name"] for p in ctx["people"]])
        self.assertEqual(2 + 1, len(ctx["aliases"]))

    def test_everything_else_in_context_md_stays_as_it_was(self):
        self.run_update("--names", "--apply")
        context = (self.root / CONTEXT).read_text()
        for heading in ("Me", "Zones", "Parties"):
            self.assertEqual(section(self.before, heading), section(context, heading), heading)

    def test_a_second_run_changes_nothing(self):
        self.run_update("--names", "--apply")
        head, context, names = self.head(self.root), (self.root / CONTEXT).read_bytes(), (self.root / NAMES).read_bytes()
        r = self.run_update("--names", "--apply")
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)
        self.assertEqual(head, self.head(self.root))
        self.assertEqual((context, names), ((self.root / CONTEXT).read_bytes(), (self.root / NAMES).read_bytes()))

    def test_a_table_it_cannot_read_stays_and_so_does_the_other(self):
        text = (self.root / CONTEXT).read_text()
        bad = text.replace("| dana whitlaw | Dana Whitlock |", "| dana whitlaw | Dana | Whitlock | extra |")
        (self.root / CONTEXT).write_text(bad)
        self.commit(self.root, "a row with a cell too many")
        self.assertEqual("unreadable", self.plan()["names"]["state"])
        r = self.run_update("--names", "--apply")
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)
        self.assertIn("could not be read as one whole table", r.stdout)
        self.assertEqual(bad, (self.root / CONTEXT).read_text())
        self.assertFalse((self.root / NAMES).exists())

    def test_a_section_with_two_tables_or_prose_instead_of_a_table_stays(self):
        text = (self.root / CONTEXT).read_text()
        for bad in (text.replace("## Aliases\n", "## Aliases\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nand then\n", 1),
                    re.sub(r"(?ms)^## Aliases\n.*?(?=^## |\Z)", "## Aliases\n\nNone yet.\n\n", text)):
            (self.root / CONTEXT).write_text(bad)
            self.assertEqual("unreadable", names_move.study(self.root)["state"])
            self.assertIsNone(names_move.moved_text(bad))
            self.assertEqual(bad, (self.root / CONTEXT).read_text())

    def test_a_row_it_did_not_parse_is_never_lost(self):
        """The check before the write: a move that would drop or repeat a row is refused whole."""
        original = names_move.moved_text
        names_move.moved_text = lambda text: (lambda c, n: (c, n.replace("| Theo Marsh | `birch` | Managing partner |\n", "")))(*original(text))
        try:
            said, ok = names_move.apply_move(self.root)
        finally:
            names_move.moved_text = original
        self.assertFalse(ok)
        self.assertIn("nothing was moved", said)
        self.assertEqual(self.before, (self.root / CONTEXT).read_text())
        self.assertFalse((self.root / NAMES).exists())

    def test_names_md_that_already_holds_a_table_is_left_alone_and_both_are_read(self):
        (self.root / NAMES).write_text("# Names\n\n## People\n\n| Name | Party | Role |\n|---|---|---|\n| Alex Birch | | Buyer |\n")
        self.commit(self.root, "my own names.md")
        self.assertEqual("both", self.plan()["names"]["state"])
        r = self.run_update("--names", "--apply")
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)
        self.assertEqual(self.before, (self.root / CONTEXT).read_text())
        names = [p["name"] for p in lib.load_context(self.root)["people"]]
        self.assertEqual({"Alex Birch", "Dana Whitlock", "Theo Marsh"}, set(names))

    def test_the_move_waits_while_the_workspaces_own_tools_cannot_read_names_md(self):
        """W1: with 0.76's garrick_lib the move would leave every reader of People seeing nobody."""
        lib_path = "System/tools/garrick_lib.py"
        (self.root / lib_path).write_text("# the tools of 0.76, which read no names.md\n")
        self.commit(self.root, "old tools, not in the stamp as Garrick wrote them")
        state = names_move.study(self.root)
        self.assertEqual("tools", state["state"])
        self.assertIn("Update the tools first", state["said"])
        r = self.run_update("--names", "--apply")
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)
        self.assertFalse((self.root / NAMES).exists())
        self.assertEqual(self.before, (self.root / CONTEXT).read_text())
        self.assertIn("Update the tools first", update.report(self.plan()))
        self.assertNotIn("say yes", update.report(self.plan()))

    def test_the_report_offers_the_move_after_the_update_when_the_update_writes_the_tools(self):
        lib_path = "System/tools/garrick_lib.py"
        self.as_if_older(lib_path, "# older tools\n")
        p = self.plan()
        self.assertIn(lib_path, p["actions"]["replace"])
        self.assertEqual("waiting", p["names"]["state"])
        self.assertTrue(p["names"]["after_update"])
        self.assertIn("apply this update, say yes", update.report(p))

    def test_a_names_md_of_the_users_own_is_never_written_over(self):
        """S2: any file with text in it is left as it is, whatever it holds."""
        (self.root / NAMES).write_text("# my own notes\nimportant\n")
        self.commit(self.root, "my names.md")
        self.assertEqual("both", names_move.study(self.root)["state"])
        r = self.run_update("--names", "--apply")
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)
        self.assertEqual("# my own notes\nimportant\n", (self.root / NAMES).read_text())
        self.assertEqual(self.before, (self.root / CONTEXT).read_text())

    def test_it_refuses_a_file_with_changes_not_committed(self):
        (self.root / CONTEXT).write_text(self.before + "\nA note of mine.\n")
        r = self.run_update("--names", "--apply")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("not committed", r.stdout)
        self.assertFalse((self.root / NAMES).exists())

    def test_the_lines_of_a_file_with_windows_line_endings_are_carried_as_they_were(self):
        text = self.before.replace("\n", "\r\n")
        (self.root / CONTEXT).write_bytes(text.encode("utf-8"))
        self.commit(self.root, "crlf")
        r = self.run_update("--names", "--apply")
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)
        names = (self.root / NAMES).read_bytes().decode()
        for row in self.rows:
            self.assertIn(row + "\r", names.split("\n"))

    def test_a_grown_workspace_is_under_its_budget_after_the_move(self):
        people = "".join("| Person Maple%d | `acme` | Head of area %d; owns the review of lane %d |\n" % (i, i, i) for i in range(90))
        text = self.before.replace("| Theo Marsh |", people + "| Theo Marsh |", 1)
        (self.root / CONTEXT).write_text(text)
        self.commit(self.root, "ninety people")
        self.assertGreater(len(text), 6500)
        self.run_update("--names", "--apply")
        self.assertLess(len((self.root / CONTEXT).read_text()), check.CONTEXT_CHAR_BUDGET)
        self.assertEqual(92, len(lib.load_context(self.root)["people"]))
        for i in range(90):
            self.assertIn("| Person Maple%d |" % i, (self.root / NAMES).read_text())


class TheWalls(Case):
    def test_a_row_naming_a_walled_partys_person_commits_in_the_workspace_repository(self):
        """names.md is in System/, outside every zone, as context.md is: the commit hook treats it the same way."""
        path = self.root / NAMES
        path.write_text(path.read_text().replace("| Theo Marsh |", "| Jo Maple | `birch` | Buyer at Birch & Co |\n| Theo Marsh |", 1))
        self.git(self.root, "add", NAMES)
        r = subprocess.run(["git", "-C", str(self.root), "commit", "-q", "-m", "a person of a walled party"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(0, r.returncode, r.stderr + r.stdout)

    def test_the_wall_check_reads_a_person_in_names_md_as_it_read_one_in_context_md(self):
        before = [f for f in check.run_checks(self.root, walls_only=True)]
        text = (self.root / NAMES).read_text()
        (self.root / CONTEXT).write_text((self.root / CONTEXT).read_text() + "\n" + text.split("\n## ", 1)[1].join(["## ", ""]))
        (self.root / NAMES).unlink()
        legacy = [f for f in check.run_checks(self.root, walls_only=True)]
        self.assertEqual([(f.path, f.message) for f in before], [(f.path, f.message) for f in legacy])


if __name__ == "__main__":
    unittest.main()
