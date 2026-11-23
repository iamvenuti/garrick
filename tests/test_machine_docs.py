"""The docs and skills for machines (#612) say what the code does.

    python3 -m unittest test_machine_docs
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "template" / "System" / "skills"


def text(path):
    return (REPO / path).read_text(encoding="utf-8")


class MachineDocs(unittest.TestCase):
    def test_the_page_names_the_roles_the_file_and_the_sync_rules(self):
        page = text("docs/machines.md")
        for word in ("`solo`", "`server`", "`roaming`", "~/.config/garrick/machine.json", "Send Only", "Receive Only", "iCloud Drive",
                     "Dropbox", "in both directions", "same absolute path", ".outbox", "Drop it", "Show me the line",
                     "sync-conflict", "conflicted copy", "not reachable here"):
            self.assertIn(word, page, word)

    def test_the_page_says_the_guard_refuses_the_role_file_and_is_not_a_lock(self):
        page = text("docs/machines.md")
        self.assertIn("The zone guard refuses a file-editing tool's write to that one file", page)
        self.assertIn("a shell command can still change the role file", page)
        self.assertIn("It is not a lock.", page)
        self.assertIn("python3 System/tools/machine.py set --role", page)

    def test_one_link_from_each_page_that_should_have_one(self):
        self.assertIn("(machines.md)", text("docs/harnesses.md"))
        self.assertIn("(../machines.md)", text("docs/extras/scheduled-jobs.md"))
        self.assertIn("System/garrick-docs/machines.md", text("template/System/skills/setup/SKILL.md"))

    def test_the_setup_skill_asks_only_when_told_and_never_writes_the_file(self):
        skill = text("template/System/skills/setup/SKILL.md")
        self.assertIn("Only when the user says it", skill)
        self.assertIn("Never write `~/.config/garrick/machine.json` with an edit tool", skill)
        self.assertIn("python3 System/tools/machine.py set --role", skill)

    def test_the_wrap_records_the_copy_step_when_the_server_cannot_reach_the_share(self):
        wrap = text("template/System/skills/threads/reference/wrap.md")
        self.assertIn("When this machine cannot reach the share", wrap)
        self.assertRegex(wrap, r"(?s)machine\.py.{0,400}`server`.{0,900}`Todo\.md`")
        self.assertIn("A copy to a share is a send", wrap)

    def test_no_skill_or_doc_page_for_this_names_an_assistant(self):
        for path in ("docs/machines.md", "template/System/skills/threads/reference/wrap.md"):
            body = text(path)
            if path.endswith("machines.md"):
                self.assertIsNone(re.search(r"Claude|Codex", body), path)


HEADINGS_MACHINES = ["Do you need this?", "The three roles", "Two computers and one workspace", "A tick on the laptop", "Set it up",
                     "What you cannot do on the laptop", "When something goes wrong"]
HEADINGS_READ_GUARD = ["What it is", "One read", "A mail search", "The first week", "What it does not cover"]
DIAGRAMS = {"docs/machines.md": ("two-computers-one-workspace", "a-tick-on-the-laptop"),
            "docs/read-guard.md": ("one-read", "a-mail-search")}


def headings(path):
    return re.findall(r"^## (.+)$", text(path), re.M)


class SettingsRouteDocs(unittest.TestCase):
    """#621: both pages are written for the user, in the issue's order, and lead with Settings."""

    def test_the_machines_page_has_the_issues_seven_parts_in_order(self):
        found = headings("docs/machines.md")
        self.assertEqual(HEADINGS_MACHINES, [h for h in found if h in HEADINGS_MACHINES])
        self.assertEqual(HEADINGS_MACHINES, found[:len(HEADINGS_MACHINES)])

    def test_the_read_guard_page_has_the_issues_five_parts_in_order(self):
        self.assertEqual(HEADINGS_READ_GUARD, headings("docs/read-guard.md")[:5])

    def test_the_machines_page_leads_with_settings_and_keeps_the_command_at_the_end_of_set_it_up(self):
        page = text("docs/machines.md")
        setup = page[page.index("## Set it up"):page.index("## What you cannot do on the laptop")]
        self.assertLess(setup.index("Settings"), setup.index("python3 System/tools/machine.py set"))
        self.assertLess(setup.index("*Change…*"), setup.index("If you cannot use the app"))
        self.assertIn("In a browser, *This machine* shows the role and says it is changed in Garrick.app", page)

    def test_each_role_has_its_bracket_name_once_and_its_plain_name_used_after(self):
        page = text("docs/machines.md")
        roles = page[page.index("## The three roles"):page.index("## Two computers")]
        for name in ("`solo`", "`server`", "`roaming`"):
            self.assertEqual(1, roles.count(name), name)
        for plain in ("One computer", "Home server", "Laptop copy"):
            self.assertIn("**%s**" % plain, roles)

    def test_the_roles_texts_are_the_settings_texts_word_for_word(self):
        sys.path.insert(0, str(REPO / "extras" / "status"))
        import settings_guard as sg
        roles = text("docs/machines.md")
        roles = roles[roles.index("## The three roles"):roles.index("## Two computers")]
        for key in ("solo", "server", "roaming"):
            self.assertIn(sg.ROLE_TEXT[key], roles, key)

    def test_the_read_guard_page_uses_the_settings_names(self):
        page = text("docs/read-guard.md")
        for word in ("**Off**", "**Watch**", "**On**", "**Refuse**", "**Ask me**", "Settings, then Walls, then *Read guard*",
                     "In the last 7 days it would have stopped 3 files across 2 sessions in Work", "*Show*", "*Across a wall*", "*Mail and calendar tools*",
                     "*Tools with nothing to check*"):
            self.assertIn(word, page, word)
        for old in (r"\benforce\b", r"warn-only", r"\bEnforce\b"):
            self.assertIsNone(re.search(old, page), old)

    def test_each_diagram_has_its_html_svg_and_png_and_alt_text_that_tells_the_flow(self):
        for page, names in DIAGRAMS.items():
            body = text(page)
            for name in names:
                for ext in ("html", "svg", "png"):
                    path = REPO / "docs" / "assets" / ("%s.%s" % (name, ext))
                    self.assertTrue(path.is_file(), path)
                    self.assertLess(path.stat().st_size, 1_000_000, path)
                alt = re.search(r"!\[([^\]]+)\]\(assets/%s\.png\)" % re.escape(name), body)
                self.assertIsNotNone(alt, name)
                self.assertGreater(len(alt.group(1).split()), 45, name)           # the whole flow in words, not a caption
                self.assertTrue(alt.group(1).endswith("."), name)
        for name in ("two-computers-one-workspace", "a-tick-on-the-laptop", "one-read", "a-mail-search"):
            svg = text("docs/assets/%s.svg" % name)
            self.assertEqual(1, svg.count("<svg"), name)
            self.assertIn("viewBox", svg)
            html = text("docs/assets/%s.html" % name)
            self.assertEqual(1, html.count('<svg viewBox'), name)

    def test_the_diagrams_use_only_the_plain_names_and_no_one_in_particular(self):
        for name in ("two-computers-one-workspace", "a-tick-on-the-laptop", "one-read", "a-mail-search"):
            svg = text("docs/assets/%s.svg" % name)
            labels = " ".join(re.findall(r"<text[^>]*>([^<]*)</text>", svg))
            for bad in ("solo", "roaming", "Roaming", "Enforce", "warn", "Mar" + "co", "Tha" + "les"):
                self.assertNotIn(bad, labels, (name, bad))

    def test_the_guide_lists_both_pages_under_understand(self):
        guide = text("extras/status/guide.py")
        self.assertIn('"enforced", "read-guard", "machines", "harnesses"', guide)

    def test_the_setup_skill_leads_with_settings_and_says_the_plain_names(self):
        skill = text("template/System/skills/setup/SKILL.md")
        section = skill[skill.index('## "The workspace is on more than one machine"'):skill.index("## Never")]
        self.assertLess(section.index("Settings, *This machine*, *Change"), section.index("python3 System/tools/machine.py set"))
        for word in ("One computer", "Home server", "Laptop copy", "System/garrick-docs/machines.md"):
            self.assertIn(word, section)

    def test_the_hooks_readme_leads_with_the_settings_route_and_enforced_links_the_page(self):
        readme = text("extras/hooks/README.md")
        part = readme[readme.index("## The read guard"):]
        self.assertLess(part.index("Turn it on in Garrick.app"), part.index('"hooks": {'))
        self.assertIn("(../../docs/read-guard.md)", part)
        self.assertIn("(read-guard.md)", text("docs/enforced.md"))


if __name__ == "__main__":
    unittest.main()
