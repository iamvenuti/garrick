"""Tests for install.py and System/tools/scaffold.py.

    python3 -m unittest discover -s tests

Standard library only. Every install goes into a temporary folder, with HOME
and git's global config pointed at temporary files, so nothing on the machine
running the tests is read or written.
"""

import importlib.util
import json
import os
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
        self.assertIn("open a terminal in", self.result.stdout)

    def test_structure(self):
        r = self.root
        for path in ["AGENTS.md", "System/rules.md", "System/context.md", "System/tools/scaffold.py",
                     "System/tools/garrick_lib.py", f"System/templates/project/{OPEN}PROJECT}}}}.md",
                     f"System/templates/thread/{OPEN}THREAD}}}}.md", "System/templates/project/Sources",
                     "System/templates/project/Deliverables", "Wikis/Meetings/AGENTS.md",
                     "Wikis/Knowledge/AGENTS.md", "Zones/Work/AGENTS.md", "Zones/Work/Todo.md",
                     "Zones/Personal/Todo.md", "Zones/Work/Inbox/.gitkeep", "Zones/Personal/Inbox/.gitkeep",
                     "System/skills/intake/SKILL.md", "System/skills/intake/intake.py",
                     "System/skills/meetings/ingest.py"]:
            self.assertTrue((r / path).exists(), path)
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


if __name__ == "__main__":
    unittest.main()
