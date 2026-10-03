"""Tests for install.py and System/tools/scaffold.py.

    python3 -m unittest discover -s tests

Standard library only. Every install goes into a temporary folder, with HOME
and git's global config pointed at temporary files, so nothing on the machine
running the tests is read or written.
"""

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # importing install.py leaves no __pycache__ behind

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "install.py"
EXAMPLE = REPO / "examples" / "acme.json"
OPEN = "{" * 2


def run(args, env, cwd=None, stdin=None, timeout=300):
    # The timeout turns a question asked forever into a failure instead of a hung suite.
    return subprocess.run([sys.executable] + [str(a) for a in args], cwd=cwd, env=env,
                          input=stdin, capture_output=True, text=True, timeout=timeout)


def load_installer():
    """install.py as a module, so a test can point its REPO somewhere else."""
    spec = importlib.util.spec_from_file_location("garrick_install", INSTALL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ignores_capitals(folder):
    """True when the disk holding `folder` treats Name and NAME as one, as a Mac's usually does."""
    probe = Path(folder) / "CapitalsProbe"
    probe.mkdir()
    try:
        return (Path(folder) / "capitalsprobe").exists()
    finally:
        probe.rmdir()


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True).stdout.strip()


class Sandbox:
    """A temporary HOME and git identity for one test class."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.home = base / "home"
        self.home.mkdir()
        self.work = base / "work"
        self.work.mkdir()
        gitconfig = base / "gitconfig"
        gitconfig.write_text("[user]\n\tname = Test Runner\n\temail = test@example.invalid\n"
                             "[commit]\n\tgpgsign = false\n")
        self.env = dict(os.environ, HOME=str(self.home), GIT_CONFIG_GLOBAL=str(gitconfig),
                        GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")

    def install(self, name, config=EXAMPLE, extra=()):
        target = self.work / name
        return target, run([INSTALL, "--config", config, "--target", target, *extra], self.env)

    def config(self, name, **changes):
        cfg = json.loads(EXAMPLE.read_text())
        cfg.update(changes)
        path = self.work / f"{name}.json"
        path.write_text(json.dumps(cfg))
        return path

    def close(self):
        self.tmp.cleanup()


def repos(root):
    return [root, root / "Wikis", root / "Zones" / "Work", root / "Zones" / "Personal"]


class InstallTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        cls.root, cls.result = cls.box.install("ws")

    @classmethod
    def tearDownClass(cls):
        cls.box.close()

    def test_succeeds_and_names_next_step(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)
        # One closing line for either route, app or terminal, with the full path.
        self.assertEqual(self.result.stdout.strip().splitlines()[-1],
                         f"Next: open {self.root} in your Claude or ChatGPT app, or start claude or codex there.")
        self.assertNotIn("garrick@localhost", self.result.stdout)  # git had an identity: no hint

    def test_structure(self):
        r = self.root
        for path in ["AGENTS.md", "System/rules.md", "System/context.md", "System/tools/scaffold.py",
                     "System/tools/garrick_lib.py", f"System/templates/project/{OPEN}PROJECT}}}}.md",
                     f"System/templates/thread/{OPEN}THREAD}}}}.md", "System/templates/project/Sources",
                     "System/templates/project/Deliverables", "Wikis/Meetings/AGENTS.md",
                     "Wikis/Knowledge/AGENTS.md", "Zones/Work/AGENTS.md", "Zones/Work/Todo.md",
                     "Zones/Personal/Todo.md", "Zones/Work/Inbox/.gitkeep", "Zones/Personal/Inbox/.gitkeep",
                     "System/skills/intake/SKILL.md", "System/skills/intake/intake.py",
                     "System/skills/meetings/ingest.py", "System/templates/zone/AGENTS.md",
                     "System/templates/zone/Todo.md", "System/templates/zone/Inbox/.gitkeep"]:
            self.assertTrue((r / path).exists(), path)
        # A zone added later starts from the same template, with the same ignore file as every zone.
        self.assertEqual((r / "System/templates/zone/.gitignore").read_text(), (r / "Zones/Work/.gitignore").read_text())
        self.assertIn("System/templates/zone/Inbox/.gitkeep", git(r, "ls-files").splitlines())
        self.assertFalse((r / "Zones" / "_zone").exists())
        self.assertFalse((r / "Zones" / "Work" / "_project").exists())
        self.assertFalse((r / "System" / "templates" / "project" / "Threads").exists())
        self.assertEqual(sorted(p.name for p in (r / "Zones").iterdir()), ["Personal", "Work"])
        self.assertIn("# Work zone", (r / "Zones/Work/AGENTS.md").read_text())
        self.assertFalse(list(r.rglob("CLAUDE.md")))
        self.assertFalse(list(r.rglob("imap_fetch.py")))  # the fetcher is an extra, never installed

    def test_git_repositories(self):
        for repo in repos(self.root):
            self.assertTrue((repo / ".git").is_dir(), repo)
            self.assertEqual(git(repo, "rev-parse", "--abbrev-ref", "HEAD"), "main", repo)
            self.assertEqual(git(repo, "rev-list", "--count", "HEAD"), "1", repo)
            self.assertEqual(git(repo, "status", "--porcelain"), "", repo)
        tracked = git(self.root, "ls-files").splitlines()
        self.assertFalse([t for t in tracked if t.startswith(("Zones/", "Wikis/"))])
        ignore = (self.root / ".gitignore").read_text()
        for line in ("Zones/", "Wikis/", "System/generated/", ".DS_Store"):
            self.assertIn(line, ignore)
        # A page a tool rebuilds, such as the status page, never enters the root history.
        (self.root / "System" / "generated").mkdir()
        (self.root / "System" / "generated" / "status.html").write_text("<p>every zone</p>\n")
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        # Opening a zone as an Obsidian vault: the state it rewrites constantly stays out, its settings do not.
        vault = self.root / "Zones" / "Work" / ".obsidian"
        vault.mkdir()
        for name in ("workspace.json", "workspace-mobile.json", "graph.json", "app.json"):
            (vault / name).write_text("{}\n")
        try:
            self.assertEqual(git(self.root / "Zones" / "Work", "status", "--porcelain", "--untracked-files=all"),
                             "?? .obsidian/app.json")
        finally:
            shutil.rmtree(vault)
        # A zone's Inbox is tracked only for its .gitkeep: nothing dropped there enters the zone's history.
        work = self.root / "Zones" / "Work"
        self.assertIn("Inbox/.gitkeep", git(work, "ls-files").splitlines())
        dropped = [work / "Inbox" / "forecast.eml", work / "Inbox" / "Contract.pdf"]
        dropped[0].write_text("From: dana.whitlock@acmecorp.example\n\nx\n")
        dropped[1].write_bytes(b"%PDF-1.4")
        try:
            self.assertEqual(git(work, "status", "--porcelain", "--untracked-files=all"), "")
        finally:
            for path in dropped:
                path.unlink()

    def test_no_placeholders_outside_templates(self):
        templates = self.root / "System" / "templates"
        for path in self.root.rglob("*"):
            if ".git" in path.parts or templates in path.parents or path.is_symlink():
                continue
            self.assertNotIn(OPEN, path.name, path)
            if path.is_file():
                self.assertNotIn(OPEN, path.read_text(errors="replace"), path)

    def test_context_filled(self):
        sys.path.insert(0, str(self.root / "System" / "tools"))
        from garrick_lib import load_context
        ctx = load_context(self.root)
        self.assertEqual(set(ctx["parties"]), {"acme", "birch"})
        self.assertEqual(ctx["parties"]["birch"]["party"], "Birch & Co")
        self.assertIn(frozenset({"acme", "birch"}), ctx["walls"])
        self.assertEqual(sorted(p["name"] for p in ctx["people"]), ["Dana Whitlock", "Theo Marsh"])
        self.assertEqual(ctx["aliases"]["birchen co"], "Birch & Co")
        self.assertEqual(ctx["parties"]["acme"]["domains"], ["acmecorp.example"])
        self.assertEqual(ctx["parties"]["birch"]["domains"], ["birchco.example"])
        text = (self.root / "System" / "context.md").read_text()
        self.assertIn("Sam Rivera. Independent advisor", text)
        self.assertNotIn("<Your name>", text)
        self.assertNotIn("The rows below are examples", text)

    def test_skill_links_resolve(self):
        skills = (self.root / "System" / "skills").resolve()
        for repo in repos(self.root):
            for harness in (".claude", ".agents"):
                link = repo / harness / "skills"
                self.assertTrue(link.is_symlink(), link)
                self.assertFalse(os.path.isabs(os.readlink(link)), link)
                self.assertEqual(link.resolve(), skills, link)
                # Every skill, intake included, is found through the link.
                for name in ("intake", "meetings", "knowledge", "threads"):
                    self.assertTrue((link / name / "SKILL.md").is_file(), (link, name))

    def test_home_untouched(self):
        self.assertEqual(list(self.box.home.iterdir()), [])

    def test_root_instructions_say_to_search_zones_and_wikis_by_path(self):
        # The root .gitignore leaves Zones/ and Wikis/ out, and search tools honour it, so a
        # search from the root alone finds nothing filed. The root AGENTS.md says so.
        text = (self.root / "AGENTS.md").read_text()
        self.assertIn("`Zones/` and `Wikis/` are separate repositories that the root's `.gitignore` leaves out, "
                      "so search tools started at the root skip them.", text)
        self.assertIn("Never search from the root alone.", text)
        self.assertIn("| `System/interviews/` |", text)
        # And the check finds no drift in it: no budget passed, nothing copied from another file.
        r = run([self.root / "System" / "tools" / "check.py", "--root", self.root, "--json"], self.box.env)
        found = [f for f in json.loads(r.stdout)["findings"] if f["check"] == "instructions"]
        self.assertEqual(found, [])


class RefusalTest(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()

    def tearDown(self):
        self.box.close()

    def test_non_empty_folder(self):
        target = self.box.work / "busy"
        target.mkdir()
        (target / "notes.txt").write_text("mine")
        _, r = self.box.install("busy")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not empty", r.stderr)
        self.assertEqual(sorted(p.name for p in target.iterdir()), ["notes.txt"])

    def test_force_keeps_own_files_out_of_git(self):
        target = self.box.work / "busy"
        target.mkdir()
        (target / "notes.txt").write_text("mine")
        _, r = self.box.install("busy", extra=["--force"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((target / "notes.txt").read_text(), "mine")
        self.assertNotIn("notes.txt", git(target, "ls-files").splitlines())

    def test_force_never_overwrites(self):
        target = self.box.work / "busy"
        target.mkdir()
        (target / "AGENTS.md").write_text("mine")
        _, r = self.box.install("busy", extra=["--force"])
        self.assertEqual(r.returncode, 1)
        self.assertEqual((target / "AGENTS.md").read_text(), "mine")

    def test_protected_folders(self):
        for name in ("Documents", "Desktop", "Downloads"):
            (self.box.home / name).mkdir()
            target = self.box.home / name / "Garrick"
            r = run([INSTALL, "--config", EXAMPLE, "--target", target], self.box.env)
            self.assertEqual(r.returncode, 1, name)
            self.assertIn("privacy", r.stderr)
            self.assertFalse(target.exists(), name)

    def test_home_itself(self):
        r = run([INSTALL, "--config", EXAMPLE, "--target", self.box.home, "--force"], self.box.env)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(list(self.box.home.iterdir()), [])

    def test_without_git_identity(self):
        empty = self.box.work / "empty-gitconfig"
        empty.write_text("")
        env = dict(self.box.env, GIT_CONFIG_GLOBAL=str(empty))
        target = self.box.work / "anon"
        r = run([INSTALL, "--config", EXAMPLE, "--target", target], env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(git(target / "Zones" / "Work", "config", "user.name"), "Sam Rivera")
        self.assertEqual(empty.read_text(), "")
        # Nothing is required. The one way to use your own address is the one documented, and it works.
        self.assertIn("garrick@localhost. Nothing needs changing.", r.stdout)
        command = r.stdout.split(f"run this in {target}:\n", 1)[1].splitlines()[0].strip()
        self.assertIn(f"\n{command}\n", (REPO / "docs" / "getting-started.md").read_text())
        subprocess.run(["/bin/sh", "-c", command], cwd=target, env=env, check=True)
        for repo in repos(target):
            self.assertEqual(git(repo, "config", "user.email"), "you@example.com", repo)
            self.assertEqual(git(repo, "config", "user.name"), "Sam Rivera", repo)
        self.assertEqual(empty.read_text(), "")

    def test_bad_configs(self):
        cases = {
            "digit": dict(zones=["Work", "Personal", "Clients 2"]),
            "alike": dict(zones=["Work", "Werk"]),
            "wall": dict(walls=[{"between": "acme", "and": "cedar"}]),
            "zone": dict(parties=[{"name": "Acme Corp", "what": "Client", "zone": "Office", "tag": "acme"}]),
            "webmail": dict(parties=[{"name": "Acme Corp", "what": "Client", "zone": "Work", "tag": "acme",
                                      "domains": "acmecorp.example, gmail.com"}]),
            "domain": dict(parties=[{"name": "Acme Corp", "what": "Client", "zone": "Work", "tag": "acme",
                                     "domains": ["not a domain"]}]),
            "shared": dict(parties=[{"name": "Acme Corp", "what": "Client", "zone": "Work", "tag": "acme",
                                     "domains": ["shared.example"]},
                                    {"name": "Birch & Co", "what": "Client", "zone": "Work", "tag": "birch",
                                     "domains": ["shared.example"]}], walls=[]),
        }
        for label, change in cases.items():
            target, r = self.box.install(label, config=self.box.config(label, **change))
            self.assertEqual(r.returncode, 1, label)
            self.assertFalse(target.exists(), label)


class TagGuessTest(unittest.TestCase):
    """The tag the questions offer is always one they would accept."""

    def test_guesses(self):
        installer = load_installer()
        guess = installer.tag_guess
        self.assertEqual(guess("Acme Corp"), "acme")
        self.assertEqual(guess("Birch & Co"), "birch")
        self.assertEqual(guess("Acme Corp", {"acme": "Acme Ltd"}), "acme-corp")
        self.assertEqual(guess("Café Birch"), "cafe")
        for name in ("4Birch", "4Birch Holdings", "12 Cobalt Lanes", "!!!", ""):
            self.assertEqual(guess(name), "", name)
        for name in ("Acme Corp", "Birch & Co", "O'Lark Partners", "Dune-Cedar Group", "Zoë & Ünal"):
            self.assertRegex(guess(name), installer.TAG_RE, name)


class TargetIdentityTest(unittest.TestCase):
    """The target is compared with the home folder, the protected folders and Garrick's
    own folder by identity, not by spelling: a symlink, or a name that differs only in
    capitals on a Mac's disk, is still the same folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        (self.home / "Documents").mkdir(parents=True)
        self.code = self.base / "code"
        self.source = self.code / "garrick-source"
        (self.source / "template").mkdir(parents=True)
        self.installer = load_installer()
        self.installer.REPO = self.source
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def refused(self, target, force=False):
        with self.assertRaises(self.installer.InstallError) as caught:
            self.installer.check_target(Path(target), force=force)
        return str(caught.exception)

    def test_the_source_folder_itself(self):
        self.assertEqual(self.refused(self.source),
                         f"{self.source} is the Garrick folder this installer runs from. "
                         "Pick a new folder outside it, such as ~/Garrick.")

    def test_inside_the_source_folder(self):
        for target in (self.source / "template", self.source / "ws", self.source / "new" / "deeper"):
            self.assertIn(f"{target} is inside {self.source}, the Garrick folder", self.refused(target, force=True))

    def test_holding_the_source_folder(self):
        self.assertEqual(self.refused(self.code, force=True),
                         f"{self.code} holds {self.source}, the Garrick folder this installer runs from. "
                         "Pick a new folder of its own, such as ~/Garrick.")

    def test_through_a_symlink(self):
        link = self.base / "link"
        link.symlink_to(self.source)
        self.assertIn(f"{link} is the same folder as {self.source}", self.refused(link))
        self.assertIn(f"{link / 'ws'} is inside", self.refused(link / "ws"))
        up = self.base / "code-link"
        up.symlink_to(self.code)
        self.assertIn(f"{up} holds", self.refused(up, force=True))
        # And the other way round: the source folder reached through a link, the target spelt out.
        self.installer.REPO = link
        self.assertIn(f"{self.source} is the same folder as {link}", self.refused(self.source))

    def test_a_name_differing_only_in_capitals(self):
        if not ignores_capitals(self.base):
            self.skipTest("this disk tells capitals apart, so there is no second spelling to try")
        self.assertIn(f"is the same folder as {self.source}", self.refused(self.code / "GARRICK-SOURCE"))
        self.assertIn("is inside", self.refused(self.code / "Garrick-Source" / "ws"))
        self.assertIn("holds", self.refused(self.base / "CODE", force=True))
        self.assertIn("home folder or above it", self.refused(self.base / "HOME", force=True))
        self.assertIn("privacy", self.refused(self.home / "documents" / "Garrick"))
        # The reported case: a clone at ~/garrick is the installer's default, ~/Garrick.
        clone = self.home / "garrick"
        clone.mkdir()
        self.installer.REPO = clone
        self.assertEqual(self.refused(self.home / "Garrick"),
                         f"{self.home / 'Garrick'} is the same folder as {clone}, the Garrick folder this "
                         "installer runs from. Pick a new folder outside it, such as ~/Garrick-workspace.")

    def test_neighbours_are_allowed(self):
        for target in (self.code / "garrick-source-ws", self.code / "garrick-sourced", self.code / "Garrick",
                       self.home / "Garrick", self.base / "elsewhere" / "ws"):
            self.assertEqual(self.installer.check_target(target), target)

    def test_suggestion_avoids_the_source_folder(self):
        self.assertEqual(self.installer.suggestion(), "~/Garrick")
        (self.home / "Garrick").mkdir()
        self.installer.REPO = self.home / "Garrick"
        self.assertEqual(self.installer.suggestion(), "~/Garrick-workspace")
        self.assertIn("such as ~/Garrick-workspace.", self.refused(self.home / "Documents" / "ws"))


class SourceFolderInstallTest(unittest.TestCase):
    """The reported case end to end: Garrick cloned into ~/garrick, which on a Mac is
    also ~/Garrick, the installer's default, and the installer run from inside it."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.close)
        name = "garrick" if ignores_capitals(self.box.home) else "Garrick"
        self.source = self.box.home / name
        self.source.mkdir()
        shutil.copy2(INSTALL, self.source / "install.py")
        (self.source / "template").symlink_to(REPO / "template")
        self.installer = self.source / "install.py"

    def untouched(self):
        self.assertEqual(sorted(p.name for p in self.source.iterdir()), ["install.py", "template"])

    def test_questions_offer_another_folder(self):
        answers = ["~/Garrick",                       # typed: refused, and asked again
                   "",                                # the default offered instead
                   "Sam Rivera", "Independent advisor", "", "", "", "", "", "", "y"]
        r = run([self.installer], self.box.env, cwd=self.source, stdin="\n".join(answers) + "\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Where should the workspace go? [~/Garrick-workspace]", r.stdout)
        self.assertIn("the Garrick folder this installer runs from. Pick a new folder outside it", r.stdout)
        self.assertTrue((self.box.home / "Garrick-workspace" / "AGENTS.md").is_file())
        self.untouched()

    def test_config_route_refuses_it(self):
        for target, extra in (("~/Garrick", []), ("~/Garrick", ["--force"]), ("inside", [])):
            r = run([self.installer, "--config", EXAMPLE, "--target", target, *extra], self.box.env, cwd=self.source)
            self.assertEqual(r.returncode, 1, (target, extra, r.stdout))
            self.assertIn("the Garrick folder this installer runs from", r.stderr)
            self.assertIn("such as ~/Garrick-workspace.", r.stderr)
            self.untouched()


class InteractiveTest(unittest.TestCase):
    def test_questions_in_order(self):
        box = Sandbox()
        try:
            target = box.work / "asked"
            answers = [
                str(target),                      # where
                "Sam Rivera",                     # name
                "Independent advisor",            # one line
                "",                               # zones: Work, Personal
                "Clients", "",                    # what goes in each
                "Acme Corp", "Client", "", "",    # party: name, what, zone, tag
                "gmail.com",                      # webmail is refused, and asked again
                "acmecorp.example",               # its mail domain
                "Birch & Co", "Client", "", "",
                "",                               # no domain for Birch
                "",                               # no more parties
                "acme birch", "Competitors", "",  # one wall, then done
                "Dana Whitlock", "acme", "Procurement", "",  # one person, then done
                "dana whitlaw", "Dana Whitlock", "",         # one alias, then done
                "y",
            ]
            r = run([INSTALL], box.env, stdin="\n".join(answers) + "\n")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            text = (target / "System" / "context.md").read_text()
            self.assertIn("| Acme Corp | Client | Work | `acme` | acmecorp.example |", text)
            self.assertIn("| Birch & Co | Client | Work | `birch` |  |", text)
            self.assertIn("personal webmail", r.stdout)
            self.assertIn("| `acme` | `birch` | Competitors |", text)
            self.assertIn("| Dana Whitlock | `acme` | Procurement |", text)
            self.assertIn("| Personal | <What Personal holds> |", text)
            # The walls question shows an example, never the user's own two tags as if suggesting a wall.
            self.assertIn('two clients tagged cedar and dune would be "cedar dune"', r.stdout)
            self.assertNotIn('"acme birch"', r.stdout)
        finally:
            box.close()

    def test_tags_walls_and_aliases_ask_plainly(self):
        box = Sandbox()
        try:
            target = box.work / "plain"
            answers = [
                str(target), "Sam Rivera", "Independent advisor", "", "", "",
                "4Birch", "Client", "",                  # a party whose name starts with a digit
                "",                                      # no tag is offered, so Enter is refused
                "4birch",                                # refused: a tag starts with a letter
                "fourbirch", "",                         # accepted; no domain
                "Fernway Logistics", "Carrier", "", "", "",
                "Cobalt Freight", "Carrier", "", "", "",
                "",                                      # no more parties
                "fernway cobalt", "", "",                # one wall, then done
                "",                                      # no people
                "dana whitlaw", "",                      # an alias with no meaning: skipped, and said so
                "", "y",
            ]
            r = run([INSTALL], box.env, stdin="\n".join(answers) + "\n")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            text = (target / "System" / "context.md").read_text()
            # Only a default the question accepts is offered, and the prompt gives the real rule.
            self.assertIn("A short tag for 4Birch, used in notes: one lowercase word that starts with a letter.\n>",
                          r.stdout)
            self.assertIn("A tag is one lowercase word that starts with a letter", r.stdout)
            self.assertIn("| 4Birch | Client | Work | `fourbirch` |  |", text)
            self.assertIn("A short tag for Fernway Logistics, used in notes: one lowercase word that starts "
                          "with a letter. [fernway]", r.stdout)
            # The wall example is plainly an example: other tags than the user's own.
            self.assertIn('two clients tagged acme and birch would be "acme birch"', r.stdout)
            self.assertNotIn('"fernway cobalt"', r.stdout)
            self.assertIn("| `fernway` | `cobalt` |", text)
            # Aliases can wait: the question says so, and where they go later.
            self.assertIn("Most people skip this now", r.stdout)
            self.assertIn("Aliases table in System/context.md", r.stdout)
            self.assertIn('Skipped "dana whitlaw": an alias needs what it means.', r.stdout)
            self.assertNotIn("dana whitlaw", text)
        finally:
            box.close()

    # Every answer after the folder: a name, a line, the default zones, and nothing else.
    SHORT = ["Sam Rivera", "Independent advisor", "", "", "", "", "", "", "y"]

    def test_a_typed_folder_goes_in_the_home_folder(self):
        box = Sandbox()
        try:
            r = run([INSTALL], box.env, cwd=box.work, stdin="\n".join(["ws-here"] + self.SHORT) + "\n")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            target = box.home / "ws-here"
            self.assertTrue((target / "AGENTS.md").is_file())
            self.assertFalse((box.work / "ws-here").exists())
            # The confirmation shows where it will go, not the words typed.
            self.assertIn(f"Ready to install in {target}: 2 zones, 0 parties, 0 walls.", r.stdout)
        finally:
            box.close()

    def test_the_target_option_stays_relative_to_the_current_folder(self):
        box = Sandbox()
        try:
            r = run([INSTALL, "--target", "ws-there"], box.env, cwd=box.work, stdin="\n".join(self.SHORT) + "\n")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            target = box.work / "ws-there"
            self.assertTrue((target / "AGENTS.md").is_file())
            self.assertFalse((box.home / "ws-there").exists())
            self.assertIn(f"Ready to install in {target}: 2 zones", r.stdout)
        finally:
            box.close()

    def test_end_of_input_stops_without_writing(self):
        box = Sandbox()
        try:
            cases = {
                "no answers at all": "",
                "a folder, then nothing": "ws-eof\n",  # "What is your name?" was asked forever
                "all but Go ahead": "\n".join(["ws-eof"] + self.SHORT[:-1]) + "\n",  # "y" was assumed
            }
            for label, stdin in cases.items():
                r = run([INSTALL], box.env, cwd=box.work, stdin=stdin, timeout=20)
                self.assertEqual(r.returncode, 1, label)
                self.assertEqual(r.stderr.strip(), "The input ended before the last question, so nothing was written.",
                                 label)
                self.assertEqual(list(box.home.iterdir()), [], label)
        finally:
            box.close()

    def test_git_is_checked_before_the_first_question(self):
        box = Sandbox()
        try:
            no_git = box.work / "bin"
            no_git.mkdir()
            env = dict(box.env, PATH=str(no_git))
            r = run([INSTALL], env, cwd=box.work, stdin="\n".join(["ws-git"] + self.SHORT) + "\n", timeout=20)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("git is not installed", r.stderr)
            self.assertNotIn("Where should the workspace go?", r.stdout)
            self.assertEqual(list(box.home.iterdir()), [])
        finally:
            box.close()


class ScaffoldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        cls.root, r = cls.box.install("ws")
        assert r.returncode == 0, r.stderr
        cls.first = cls.scaffold("project", "--zone", "Work", "--name", "Acme", "--party", "acme",
                                 "--thread", "Pricing")
        cls.second = cls.scaffold("thread", "--zone", "work", "--project", "acme", "--name", "Supplier Audit")

    @classmethod
    def tearDownClass(cls):
        cls.box.close()

    @classmethod
    def scaffold(cls, *args):
        return run([cls.root / "System" / "tools" / "scaffold.py", *args], cls.box.env, cwd=cls.root)

    def refuse(self, *args):
        r = self.scaffold(*args)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        return r.stderr

    def test_project_created(self):
        self.assertEqual(self.first.returncode, 0, self.first.stderr)
        self.assertEqual(self.first.stdout.strip(), "Created project Acme in Work, with its first thread, Pricing.")
        p = self.root / "Zones" / "Work" / "Acme"
        for path in ["Acme.md", "Sources", "Deliverables", "Threads/Pricing/Pricing.md"]:
            self.assertTrue((p / path).exists(), path)
        hub = (p / "Acme.md").read_text()
        self.assertIn("party: acme", hub)
        self.assertIn("zone: Work", hub)
        for text in [hub, (p / "Threads/Pricing/Pricing.md").read_text()]:
            self.assertNotIn(OPEN, text)

    def test_thread_created_and_listed(self):
        self.assertEqual(self.second.returncode, 0, self.second.stderr)
        self.assertEqual(self.second.stdout.strip(), "Created thread Supplier Audit in Acme.")
        note = (self.root / "Zones/Work/Acme/Threads/Supplier Audit/Supplier Audit.md").read_text()
        self.assertIn("party: acme", note)
        self.assertIn('project: "[[Acme]]"', note)
        self.assertNotIn(OPEN, note)
        hub = (self.root / "Zones/Work/Acme/Acme.md").read_text()
        threads = hub.split("## Threads")[1].split("##")[0]
        self.assertEqual([l for l in threads.splitlines() if l.startswith("- ")],
                         ["- [[Acme/Threads/Pricing/Pricing|Pricing]]: <what it produces>",
                          "- [[Acme/Threads/Supplier Audit/Supplier Audit|Supplier Audit]]: <what it produces>"])

    def test_refusals(self):
        self.assertIn("files wait", self.refuse("project", "--zone", "Work", "--name", "inbox", "--party", "birch",
                                                "--thread", "Entry"))
        self.assertIn("digit", self.refuse("project", "--zone", "Work", "--name", "Q Three 2026",
                                           "--party", "birch", "--thread", "Entry"))
        self.assertIn("sounds too much like Acme",
                      self.refuse("project", "--zone", "Work", "--name", "Akme", "--party", "birch", "--thread", "Entry"))
        self.assertIn("no zone called Office",
                      self.refuse("project", "--zone", "Office", "--name", "Birch", "--party", "birch", "--thread", "Entry"))
        self.assertIn("not a party tag",
                      self.refuse("project", "--zone", "Work", "--name", "Birch", "--party", "cedar", "--thread", "Entry"))
        self.assertIn("already has a project called Acme",
                      self.refuse("project", "--zone", "Work", "--name", "Acme", "--party", "acme", "--thread", "Entry"))
        self.assertIn("already has a thread called Pricing",
                      self.refuse("thread", "--zone", "Work", "--project", "Acme", "--name", "Pricing"))
        self.assertIn("sounds too much like Pricing",
                      self.refuse("thread", "--zone", "Work", "--project", "Acme", "--name", "Prising"))
        self.assertIn("digit", self.refuse("thread", "--zone", "Work", "--project", "Acme", "--name", "Phase 2"))
        self.assertIn("no project called Cedar",
                      self.refuse("thread", "--zone", "Work", "--project", "Cedar", "--name", "Entry"))
        self.assertFalse((self.root / "Zones/Work/Birch").exists())
        self.assertFalse((self.root / "Zones/Work/Akme").exists())

    def test_checker_passes(self):
        check = self.root / "System" / "tools" / "check.py"
        if not check.exists():
            self.skipTest("check.py is not in the template yet")
        r = run([check, "--root", self.root], self.box.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


# The command docs/getting-started.md gives for a zone added after install. The tests run
# it as written, with this interpreter, so the page and the script cannot drift apart.
ZONE_COMMAND = re.search(r'^python3 (System/tools/scaffold\.py zone "([^"]+)" --holds "[^"]+")$',
                         (REPO / "docs" / "getting-started.md").read_text(encoding="utf-8"), re.M)


def first_commit(repo):
    return git(repo, "rev-list", "--max-parents=0", "HEAD")


class ZoneTest(unittest.TestCase):
    """A zone added after install is made the way the installer makes one."""

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        cls.root, r = cls.box.install("ws")
        assert r.returncode == 0, r.stderr
        assert ZONE_COMMAND, "docs/getting-started.md gives no scaffold.py zone command"
        cls.name = ZONE_COMMAND.group(2)
        cls.zone = cls.root / "Zones" / cls.name
        cls.made = run(shlex.split(ZONE_COMMAND.group(1)), cls.box.env, cwd=cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.box.close()

    def scaffold(self, *args):
        return run([self.root / "System" / "tools" / "scaffold.py", *args], self.box.env, cwd=self.root)

    def test_says_what_it_made_and_what_to_say_next(self):
        self.assertEqual(self.made.returncode, 0, self.made.stderr)
        said = self.made.stdout.strip().splitlines()
        self.assertEqual(said[0], f"Created the {self.name} zone: its own folder and git history, an inbox, "
                                  "and the wall check before every commit.")
        self.assertIn(f"Added {self.name} to the Zones table in System/context.md.", said[1])
        self.assertTrue(said[-1].startswith(f'Next, say "new project <name> for <party> in {self.name}'), said[-1])

    def test_made_as_the_installer_makes_a_zone(self):
        personal = self.root / "Zones" / "Personal"

        def first(zone):
            """Each file and link in the zone's first commit, with the zone's name taken out."""
            out = {}
            for name in git(zone, "ls-tree", "-r", "--name-only", first_commit(zone)).splitlines():
                path = zone / name
                out[name] = os.readlink(path) if path.is_symlink() else path.read_text().replace(zone.name, "<zone>")
            return out

        self.assertEqual(first(self.zone), first(personal))
        self.assertEqual(git(self.zone, "log", "--format=%s", first_commit(self.zone)), f"Garrick: {self.name} created")
        self.assertEqual(git(self.zone, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        for repo in (self.zone, personal):  # git had an identity, so neither sets its own
            self.assertEqual(git(repo, "config", "--local", "--get-regexp", r"^user\."), "", repo)
        hook = self.zone / ".git" / "hooks" / "pre-commit"
        self.assertEqual(hook.read_text(), (personal / ".git" / "hooks" / "pre-commit").read_text())
        self.assertTrue(os.access(hook, os.X_OK))
        for harness in (".claude", ".agents"):
            self.assertEqual((self.zone / harness / "skills").resolve(), (self.root / "System" / "skills").resolve())
        # Its inbox stays out of its history, as every zone's does.
        dropped = self.zone / "Inbox" / "Quote.eml"
        dropped.write_text("From: dana.whitlock@acmecorp.example\n\nx\n")
        try:
            self.assertEqual(git(self.zone, "status", "--porcelain", "--untracked-files=all"), "")
        finally:
            dropped.unlink()

    def test_listed_in_context_and_left_to_commit(self):
        text = (self.root / "System" / "context.md").read_text()
        zones = text.split("## Zones", 1)[1].split("\n## ", 1)[0]
        rows = [line for line in zones.splitlines() if line.startswith("| ") and "---" not in line]
        self.assertEqual([r.split("|")[1].strip() for r in rows], ["Zone", "Work", "Personal", self.name])
        self.assertEqual(git(self.root, "status", "--porcelain"), "M System/context.md")

    def test_check_stays_clean_and_the_hook_works_in_it(self):
        check = run([self.root / "System" / "tools" / "check.py", "--root", self.root], self.box.env)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn("No problems found.", check.stdout)
        made = self.scaffold("project", "--zone", self.name, "--name", "Shed", "--party", "acme", "--thread", "Roof")
        self.assertEqual(made.returncode, 0, made.stderr)
        note = self.zone / "Shed" / "Threads" / "Roof" / "Notes.md"
        note.write_text("Theo Marsh says the roof will hold.\n")  # Birch's partner, behind the wall from acme
        try:
            git(self.zone, "add", "-A")
            r = subprocess.run(["git", "-C", str(self.zone), "commit", "-q", "-m", "Shed"],
                               env=self.box.env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("Commit refused: Zones/%s/Shed/Threads/Roof/Notes.md" % self.name, r.stderr)
        finally:
            git(self.zone, "reset", "-q")
            shutil.rmtree(self.zone / "Shed")
        self.assertEqual(git(self.zone, "rev-list", "--count", "HEAD"), "1")

    def test_refusals(self):
        context = (self.root / "System" / "context.md").read_text()
        for name, why in (("work", "already has a zone called Work"), ("Werk", "sounds too much like Work"),
                          ("Clients 2", "contains a digit"), ("_Garden", "starts with an underscore")):
            r = self.scaffold("zone", name, "--holds", "Anything")
            self.assertEqual(r.returncode, 1, (name, r.stdout))
            self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
            self.assertIn(why, r.stderr)
        ignore = self.root / "System" / "templates" / "zone" / ".gitignore"
        kept = ignore.read_text()
        ignore.unlink()
        try:
            r = self.scaffold("zone", "Studio", "--holds", "Paintings")
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("The zone template, System/templates/zone, is missing or has no .gitignore.", r.stderr)
        finally:
            ignore.write_text(kept)
        self.assertEqual(sorted(p.name for p in (self.root / "Zones").iterdir()), sorted(["Personal", "Work", self.name]))
        self.assertEqual((self.root / "System" / "context.md").read_text(), context)


class ZoneIdentityTest(unittest.TestCase):
    def test_a_new_zone_commits_as_the_workspace_does(self):
        box = Sandbox()
        self.addCleanup(box.close)
        empty = box.work / "empty-gitconfig"
        empty.write_text("")
        # No identity anywhere but what the workspace sets itself, not even in the environment.
        env = {k: v for k, v in box.env.items() if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
        env["GIT_CONFIG_GLOBAL"] = str(empty)
        target = box.work / "anon"
        self.assertEqual(run([INSTALL, "--config", EXAMPLE, "--target", target], env).returncode, 0)
        subprocess.run(["/bin/sh", "-c", load_installer().OWN_ADDRESS], cwd=target, env=env, check=True)
        scaffold = target / "System" / "tools" / "scaffold.py"
        r = run([scaffold, "zone", "Garage", "--holds", ""], env, cwd=target)
        self.assertEqual(r.returncode, 0, r.stderr)
        garage = target / "Zones" / "Garage"
        self.assertEqual(git(garage, "config", "user.name"), "Sam Rivera")
        self.assertEqual(git(garage, "config", "user.email"), "you@example.com")
        self.assertEqual(git(garage, "log", "-1", "--format=%an <%ae>"), "Sam Rivera <you@example.com>")
        # Nothing said about what it holds: the row waits for it, as the installer's does.
        self.assertIn("| Garage | <What Garage holds> |", (target / "System" / "context.md").read_text())
        self.assertEqual(empty.read_text(), "")


if __name__ == "__main__":
    unittest.main()
