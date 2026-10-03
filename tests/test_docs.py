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


if __name__ == "__main__":
    unittest.main()
