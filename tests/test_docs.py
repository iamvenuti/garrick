"""The commands the documentation gives, checked against each other and the installer.

    python3 -m unittest discover -s tests

Someone following the docs runs their commands one after another: clone Garrick,
build the demo, install from a config, install their own. Each has to land in a
folder of its own. A Mac's disk ignores capitals, so ~/garrick and ~/Garrick are
one folder, and folders here are compared without regard to case.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = re.search(r'^DEFAULT_TARGET = "([^"]+)"', (REPO / "install.py").read_text(encoding="utf-8"),
                           re.M).group(1)
CLONE = re.compile(r"git clone (\S+)(?:[ \t]+([^\s`<]+))?")
TARGET = re.compile(r"--target[ \t]+([^\s`<)]+)")
CONFIG = re.compile(r"--config[ \t]+([^\s`<)]+)")


def documents():
    """Every page a reader might copy a command from. The changelog is history, not instructions."""
    for path in sorted(REPO.rglob("*")):
        rel = path.relative_to(REPO)
        if (path.suffix in (".md", ".yml", ".html") and ".git" not in rel.parts and rel.name != "CHANGELOG.md"
                and path.is_file()):
            yield rel.as_posix(), path.read_text(encoding="utf-8")


def clones():
    """(page, folder, the next `cd` after it) for every `git clone` in the docs."""
    for page, text in documents():
        for m in CLONE.finditer(text):
            cd = re.search(r"^\s*cd[ \t]+(\S+)", text[m.end():], re.M)
            yield page, m.group(2), cd.group(1) if cd else None


def example_targets():
    """(page, command, folder) for every documented build or install into a folder under ~/."""
    for page, text in documents():
        for line in text.splitlines():
            for m in TARGET.finditer(line):
                before = line[:m.start()]
                script = "build.py" if "build.py" in before else "install.py" if "install.py" in before else None
                if script is None or not m.group(1).startswith("~/"):
                    continue
                config = CONFIG.search(before)
                yield page, script + (" --config " + config.group(1) if config else ""), m.group(1).rstrip(".,;:")


class DocCommandsTest(unittest.TestCase):
    def test_the_docs_give_commands(self):
        self.assertTrue(list(clones()))
        self.assertTrue(list(example_targets()))

    def test_a_clone_names_its_own_folder_and_goes_into_it(self):
        workspaces = {DEFAULT_TARGET.lower()} | {t.lower() for _, _, t in example_targets()}
        for page, folder, cd in clones():
            # Without a folder, git names the clone garrick: on a Mac, the installer's default ~/Garrick.
            self.assertIsNotNone(folder, f"{page}: git clone without a folder")
            self.assertNotIn(folder.lower(), workspaces, f"{page}: the clone goes where a workspace goes")
            self.assertEqual(cd, folder, f"{page}: the commands after the clone do not run inside it")

    def test_each_example_folder_belongs_to_one_command(self):
        used = {}
        for page, command, folder in example_targets():
            self.assertNotEqual(folder.lower(), DEFAULT_TARGET.lower(),
                                f"{page}: {command} installs an example over your own workspace")
            used.setdefault(folder.lower(), set()).add(command)
        shared = {folder: sorted(commands) for folder, commands in used.items() if len(commands) > 1}
        self.assertEqual(shared, {}, "one folder, two different commands: the second stops with 'not empty'")


class FirstStepsTest(unittest.TestCase):
    """What a newcomer reads in docs/ stays true of the product it describes."""

    def test_one_name_for_claudes_code_tab(self):
        for page, text in documents():
            if page.startswith("docs/"):
                self.assertNotRegex(text, r"\bCode (mode|view|icon)\b", f"{page}: call it the Code tab")

    def test_the_commands_to_approve_are_garricks_own(self):
        text = (REPO / "docs" / "first-steps.md").read_text(encoding="utf-8")
        table = text.split("### The commands it asks to approve", 1)[1].split("\n## ", 1)[0]
        scripts = re.findall(r"`python3 (System/\S+\.py)`", table)
        self.assertGreaterEqual(len(scripts), 4)
        for script in scripts:
            self.assertTrue((REPO / "template" / script).is_file(), f"first-steps.md names {script}, which is not shipped")


DISCUSSIONS = "https://github.com/iamvenuti/garrick/discussions"
FORMS = REPO / ".github" / "ISSUE_TEMPLATE"


class FeedbackTest(unittest.TestCase):
    """Someone invited to try Garrick has a place to ask and to say how it went, and
    every way in points there. Bug reports work for desktop app users too."""

    def test_the_issue_chooser_offers_discussions_first(self):
        urls = re.findall(r"^\s*url:\s*(\S+)", (FORMS / "config.yml").read_text(encoding="utf-8"), re.M)
        self.assertEqual(urls[0], DISCUSSIONS)

    def test_ideas_have_a_way_in(self):
        """Blank issues are off and no form fits a proposed change, so the chooser
        and CONTRIBUTING.md both send ideas to the Ideas category."""
        ideas = f"{DISCUSSIONS}/categories/ideas"
        urls = re.findall(r"^\s*url:\s*(\S+)", (FORMS / "config.yml").read_text(encoding="utf-8"), re.M)
        self.assertIn(ideas, urls)
        self.assertIn(f"]({ideas})", (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8"))

    def test_readme_and_contributing_point_there(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"]({DISCUSSIONS})", readme.split("\n## Contributing\n", 1)[1].split("\n## ", 1)[0])
        contributing = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn(f"]({DISCUSSIONS})", contributing.split("\n## ", 1)[0])  # in its opening

    def test_the_bug_form_takes_a_desktop_app_version(self):
        versions = (FORMS / "bug.yml").read_text(encoding="utf-8").split("id: versions", 1)[1]
        self.assertIn("About window", versions)
        self.assertIn("required: true", versions)


if __name__ == "__main__":
    unittest.main()
