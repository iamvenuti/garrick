"""The commands the documentation gives, checked against each other and the installer.

    python3 -m unittest discover -s tests

Someone following the docs runs their commands one after another: clone Garrick,
build the demo, install from a config, install their own. Each has to land in a
folder of its own. A Mac's disk ignores capitals, so ~/garrick and ~/Garrick are
one folder, and folders here are compared without regard to case.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = re.search(r'^DEFAULT_TARGET = "([^"]+)"', (REPO / "install.py").read_text(encoding="utf-8"),
                           re.M).group(1)
CLONE = re.compile(r"git clone (\S+)(?:[ \t]+([^\s`<]+))?")


def installer():
    """install.py as a module: the commands it allows are documented, not guessed."""
    spec = importlib.util.spec_from_file_location("garrick_install", REPO / "install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
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


LATEST = re.compile(r"https://github\.com/iamvenuti/garrick/releases/latest/download/([^\s)`]+)")
DOWNLOAD_FOLDER = re.compile(r"~/Downloads/([A-Za-z0-9._-]+)")
BEGINNER = ("docs/first-steps.md", "docs/commands.md", "docs/try-it-safely.md",
            "docs/first-session.md", "docs/updating.md")


def release_archive():
    """AGENTS.md's `git archive` step: (what it archives, the folder it unpacks into, the asset name)."""
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    line = next((l for l in text.splitlines() if l.startswith("git archive")), "")
    prefix = re.search(r"--prefix=([^\s/]+)/", line)
    asset = re.search(r"-o[ \t]+(\S+)", line)
    return (line.split()[-1] if line else None,
            prefix.group(1) if prefix else None,
            asset.group(1).rsplit("/", 1)[-1] if asset else None)


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

    def test_the_table_names_every_tool_the_installer_allows(self):
        text = (REPO / "docs" / "first-steps.md").read_text(encoding="utf-8")
        table = text.split("### The commands it asks to approve", 1)[1].split("\n## ", 1)[0]
        named = re.findall(r"`python3 (System/\S+\.py)`", table)
        for tool in installer().ALLOWED_TOOLS:
            self.assertIn(tool, named, "the installer allows %s, which first-steps.md does not name" % tool)

    def test_the_account_says_what_it_refused_to_allow(self):
        text = (REPO / "docs" / "first-steps.md").read_text(encoding="utf-8")
        section = text.split("### The commands it asks to approve", 1)[1].split("\n## ", 1)[0]
        account = section.split("The installer's last question", 1)[1]
        for word in installer().REFUSED_GIT:
            self.assertIn("`%s`" % word, account, word)
        for needle in ("git -C Zones/Work", "take it back", "release.py"):
            self.assertIn(needle, account, needle)

    def test_the_git_commands_to_approve_are_named_by_what_they_do(self):
        # A folder after `git -C` says where a command works, not what it does:
        # the table names the subcommands, and every one the skills run is among them.
        text = (REPO / "docs" / "first-steps.md").read_text(encoding="utf-8")
        table = text.split("### The commands it asks to approve", 1)[1].split("\n## ", 1)[0]
        row = next(line for line in table.splitlines() if line.startswith("| `git -C"))
        named = set(re.findall(r"`(\w+)`", row.split("|")[1]))
        self.assertEqual({"status", "diff", "log", "add", "commit"}, named)
        for word in ("push", "--force"):
            self.assertIn("`%s`" % word, table)
        skills = REPO / "template" / "System" / "skills"
        for path in skills.rglob("SKILL.md"):
            for sub in re.findall(r"git -C (?:\"[^\"]+\"|\S+) (\w+)", path.read_text(encoding="utf-8")):
                self.assertIn(sub, named, f"{path.relative_to(REPO)} runs git {sub}, which first-steps.md does not name")



class LatestReleaseTest(unittest.TestCase):
    """A beginner downloads the newest release, never the default branch. One link and one
    folder serve every release, so the asset the docs name has to be the one the release
    procedure builds, under the name it builds it under."""

    def test_the_procedure_builds_a_fixed_name_archive_from_the_tag(self):
        tree, prefix, asset = release_archive()
        self.assertIsNotNone(asset, "AGENTS.md has no `git archive` step that writes a file")
        self.assertTrue(asset.endswith(".zip"), asset)
        self.assertIsNotNone(prefix, "the archive needs --prefix, or it unpacks into the folder you ran it in")
        self.assertNotIn(tree, ("HEAD", "main"), "the archive comes from the tag, so VERSION names the release")
        # The stamp a workspace carries is git's substitution, which only a tag's archive makes.
        self.assertRegex((REPO / ".gitattributes").read_text(encoding="utf-8"),
                         r"(?m)^VERSION\b.*\bexport-subst\b")
        self.assertIn("$Format:%h$", (REPO / "VERSION").read_text(encoding="utf-8"))

    def test_the_docs_download_the_asset_the_release_carries(self):
        asset = release_archive()[2]
        named = {name for _, text in documents() for name in LATEST.findall(text)}
        self.assertEqual({asset}, named, "a page downloads an asset the release procedure does not build")
        self.assertRegex((REPO / "docs" / "first-steps.md").read_text(encoding="utf-8"), LATEST,
                         "first-steps.md does not send a beginner to the latest release")

    def test_no_page_names_a_version_in_a_download(self):
        for page, text in documents():
            self.assertFalse("/releases/download/" in text,
                             f"{page}: a download link that names one release goes stale at the next")

    def test_no_beginner_page_sends_anyone_to_the_default_branch(self):
        for page in BEGINNER:
            text = (REPO / page).read_text(encoding="utf-8")
            for needle in ("garrick-main", "Download ZIP", "archive/refs/heads/", "/archive/main"):
                self.assertFalse(needle in text, f"{page}: {needle} is the default branch, not a release")

    def test_every_download_folder_is_the_one_the_archive_unpacks_into(self):
        prefix = release_archive()[1]
        found = [(page, folder) for page, text in documents() for folder in DOWNLOAD_FOLDER.findall(text)]
        self.assertTrue(found, "no page says where the download lands")
        for page, folder in found:
            self.assertEqual(prefix, folder, f"{page}: the archive unpacks into {prefix}, not {folder}")
        # ~/garrick and ~/Garrick are one folder on a Mac, so the download stays out of Downloads only.
        self.assertNotEqual(("~/Downloads/" + prefix).lower(), DEFAULT_TARGET.lower(),
                            "the download would land on the workspace")


DISCUSSIONS = "https://github.com/iamvenuti/garrick/discussions"
FORMS = REPO / ".github" / "ISSUE_TEMPLATE"
WORDS = {n: w for n, w in enumerate(
    "no one two three four five six seven eight nine ten eleven twelve".split())}


class HarnessTableTest(unittest.TestCase):
    """What has been tested in each assistant is a record of runs made on a version,
    so it goes stale on its own. The one number on the page that is not a record is
    how many skills ship: it is read off the folder here, so the page cannot keep
    claiming an older count."""

    def setUp(self):
        self.text = (REPO / "docs" / "harnesses.md").read_text(encoding="utf-8")
        self.skills = sorted(p.name for p in (REPO / "template" / "System" / "skills").iterdir()
                             if p.is_dir() and not p.name.startswith("."))

    def test_the_page_says_how_many_skills_ship_now(self):
        self.assertTrue(self.skills)
        word = WORDS[len(self.skills)]
        self.assertIn("%s skills ship now" % word.capitalize(), self.text,
                      "%d skills ship; the page claims another count" % len(self.skills))
        row = [l for l in self.text.splitlines() if l.startswith("| Finds the skills |")]
        self.assertEqual(1, len(row), row)
        self.assertEqual(2, row[0].count("%s ship now" % word), row[0])

    def test_no_row_claims_a_count_that_has_moved_on(self):
        """A row that named the count it had not been rechecked with was the way this
        went stale: the count belongs to the sentence that reads it off the folder."""
        for stale in ("rechecked with five", "rechecked with four", "all four skills", "all five skills"):
            self.assertNotIn(stale, self.text, stale)


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
