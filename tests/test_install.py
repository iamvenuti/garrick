"""Tests for install.py and System/tools/scaffold.py.

    python3 -m unittest discover -s tests

Standard library only. Every install goes into a temporary folder, with HOME
and git's global config pointed at temporary files, so nothing on the machine
running the tests is read or written.
"""

import contextlib
import importlib.util
import hashlib
import io
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



def recorded_settings(target):
    """System/garrick-settings.json of an installed workspace, {} without one."""
    try:
        return json.loads((Path(target) / "System" / "garrick-settings.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}

class Sandbox:
    """A temporary HOME and git identity for one test class."""

    def __init__(self, page=False):
        """`page`: build the status page at install, as a user's install does.
        Off by default, since a build takes seconds and few tests read the page."""
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.home = base / "home"
        self.home.mkdir()
        self.work = base / "work"
        self.work.mkdir()
        gitconfig = base / "gitconfig"
        # Newer git runs its housekeeping after a commit in a process of its own,
        # which can still be writing in .git when the folder is cleaned up.
        gitconfig.write_text("[user]\n\tname = Test Runner\n\temail = test@example.invalid\n"
                             "[commit]\n\tgpgsign = false\n[maintenance]\n\tautoDetach = false\n")
        # The first build of the status page looks for Claude Code's command-line
        # tool; GARRICK_CLAUDE names one that is not there, so it looks nowhere else.
        # GARRICK_CALLER_BUILDS_PAGE: scaffold.py starts no build of it in the background (#243).
        self.env = dict(os.environ, HOME=str(self.home), GIT_CONFIG_GLOBAL=str(gitconfig),
                        GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1",
                        GARRICK_CLAUDE=str(base / "no-claude"), GARRICK_CALLER_BUILDS_PAGE="1")
        if not page:
            self.env["GARRICK_INSTALL_NO_PAGE"] = "1"
        else:
            self.env.pop("GARRICK_INSTALL_NO_PAGE", None)

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
                         f"Next: open {self.root} in your Claude or ChatGPT app, or start claude or codex there, "
                         f"and say \"set up Garrick\".")
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

    def test_the_workspace_says_which_garrick_it_came_from(self):
        stamp = json.loads((self.root / "System" / "garrick-version.json").read_text())
        self.assertIn(stamp["from"], ("clone", "download"))  # the suite runs in a clone, or in a download's copy
        self.assertRegex(stamp["date"], r"^\d{4}-\d{2}-\d{2}$")
        if stamp["from"] == "clone":
            self.assertEqual(git(REPO, "log", "-1", "--format=%h"), stamp["commit"])
            self.assertIn("modified", stamp)
        self.assertIn("System/garrick-version.json", git(self.root, "ls-files").splitlines())
        res = run([self.root / "System" / "tools" / "check.py", "--version"], self.box.env)
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertTrue(res.stdout.startswith("Garrick %s of " % stamp["commit"]), res.stdout)
        self.assertEqual(1, len(res.stdout.strip().splitlines()))                 # still one line for a bug report
        self.assertIn("All %d files Garrick wrote are as it wrote them." % len(stamp["files"]), res.stdout)

    def test_the_stamp_fingerprints_every_file_garrick_wrote(self):
        files = json.loads((self.root / "System" / "garrick-version.json").read_text())["files"]
        on_disk = set()
        for folder, dirs, names in os.walk(self.root):
            dirs[:] = [d for d in dirs if d != ".git"]
            for n in names:
                p = Path(folder) / n
                if not p.is_symlink():
                    on_disk.add(p.relative_to(self.root).as_posix())
        # Everything the installer wrote, less what is the user's from the start (their
        # answers, their rules, the workspace's settings and the assistant's), the stamp
        # itself and System/generated/, where other tests here build pages.
        on_disk = {p for p in on_disk if not p.startswith("System/generated/")}
        yours = {"System/context.md", "System/garrick-version.json", "System/rules.local.md",
                 "System/garrick-settings.json", ".claude/settings.json"}
        self.assertEqual(on_disk - yours, set(files))
        self.assertTrue(yours <= on_disk)
        for rel, digest in files.items():
            self.assertEqual(hashlib.sha256((self.root / rel).read_bytes()).hexdigest(), digest, rel)
        self.assertIn("Zones/Work/AGENTS.md", files)
        self.assertIn("System/rules.md", files)

    def test_the_commands_garrick_asks_to_have_allowed(self):
        installer = load_installer()
        allow = json.loads((self.root / ".claude" / "settings.json").read_text())["permissions"]["allow"]
        self.assertEqual(installer.claude_allow_rules(["Work", "Personal"]), allow)
        for tool in installer.ALLOWED_TOOLS:            # one rule each, and every one is shipped
            self.assertTrue((self.root / tool).is_file(), tool)
            self.assertIn("Bash(python3 %s:*)" % tool, allow)
        # Each repository the installer makes, in the spelling the skills write and the plain one.
        for repo in (".", "Wikis", '"Zones/Work"', "Zones/Work", '"Zones/Personal"', "Zones/Personal"):
            for word in ("status", "diff", "log", "add", "commit"):
                self.assertIn("Bash(git -C %s %s:*)" % (repo, word), allow)
        # Recorded, so an update can replace Garrick's own entries and leave the user's.
        recorded = json.loads((self.root / "System" / "garrick-settings.json").read_text())
        self.assertEqual(allow, recorded["allowed-commands"])
        tracked = git(self.root, "ls-files").splitlines()
        for rel in (".claude/settings.json", "System/garrick-settings.json"):
            self.assertIn(rel, tracked)                 # saved with the workspace, so it can be read

    def test_the_allowlist_refuses_the_rest(self):
        installer = load_installer()
        allow = json.loads((self.root / ".claude" / "settings.json").read_text())["permissions"]["allow"]
        words = ("push", "pull", "fetch", "clone", "remote",
                 "reset", "checkout", "restore", "clean", "rm", "--force")
        self.assertEqual(sorted(words), sorted(installer.REFUSED_GIT))
        for word in words:
            found = [r for r in allow if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(word), r)]
            self.assertEqual([], found, word)
        # Never a rule that stops at a folder: every git rule says what it may do there.
        for rule in [r for r in allow if r.startswith("Bash(git")]:
            self.assertRegex(rule, r'^Bash\(git -C (?:"[^"]+"|\S+) (?:status|diff|log|add|commit):\*\)$')
        # Nothing outside the workspace, and not the one tool that reaches the network.
        self.assertEqual([], [r for r in allow if "release.py" in r or ".." in r or "~" in r or "/Users/" in r])
        self.assertEqual(len(set(allow)), len(allow))
        # Each is the shape the repository already knows for a shell command: the start
        # of the command, as extras/jobs/headless-settings.json writes its own.
        profile = json.loads((REPO / "extras" / "jobs" / "headless-settings.json").read_text())
        self.assertIn("Bash(git push:*)", profile["permissions"]["deny"])
        for rule in allow:
            self.assertRegex(rule, r"^Bash\([^()]+:\*\)$")

    def test_the_installer_and_the_library_name_the_same_two_settings_files(self):
        sys.path.insert(0, str(self.root / "System" / "tools"))
        import garrick_lib
        self.assertEqual("/".join(garrick_lib.CLAUDE_SETTINGS), load_installer().CLAUDE_SETTINGS)
        # Each holds the user's entries beside Garrick's, so neither is ever replaced whole.
        self.assertIn("/".join(garrick_lib.CLAUDE_SETTINGS), garrick_lib.UNLISTED)
        self.assertIn("/".join(garrick_lib.SETTINGS), garrick_lib.UNLISTED)

    def test_your_rules_start_beside_garricks_and_are_never_listed(self):
        local = self.root / "System" / "rules.local.md"
        self.assertTrue(local.read_text().startswith("# Your rules\n"))
        self.assertNotIn("System/rules.local.md", json.loads((self.root / "System/garrick-version.json").read_text())["files"])
        self.assertIn("System/rules.local.md", git(self.root, "ls-files"))
        self.assertIn("`System/rules.local.md`", (self.root / "System/rules.md").read_text())
        self.assertIn("`AGENTS.local.md`", (self.root / "AGENTS.md").read_text())
        for path in ("Zones/Work/AGENTS.md", "Wikis/AGENTS.md", "Wikis/Meetings/AGENTS.md", "Wikis/Knowledge/AGENTS.md"):
            self.assertIn("AGENTS.local.md", (self.root / path).read_text(), path)

    def test_the_release_notes_come_with_it(self):
        # The status page shows them from here, so it never fetches anything.
        self.assertEqual((REPO / "CHANGELOG.md").read_bytes(), (self.root / "System" / "garrick-changelog.md").read_bytes())

    def test_the_docs_come_with_it(self):
        # #133: the assistant answers from them, and the Garrick App's Guide tab shows them.
        docs = REPO / "docs"
        shipped = load_installer().docs_files()
        copy = self.root / "System" / "garrick-docs"
        self.assertEqual(shipped, sorted(p.relative_to(copy).as_posix() for p in copy.rglob("*") if p.is_file()))
        for rel in shipped:
            self.assertEqual((docs / rel).read_bytes(), (copy / rel).read_bytes(), rel)
        files = json.loads((self.root / "System" / "garrick-version.json").read_text())["files"]
        self.assertIn("System/garrick-docs/concepts.md", files)               # Garrick's, so an update replaces them
        self.assertIn("System/garrick-docs/concepts.md", git(self.root, "ls-files"))
        # The pages and the images they show; a file a page only links to stays on GitHub.
        self.assertIn("extras/status-page.md", shipped)
        self.assertIn("assets/status-graph.png", shipped)                     # extras/status-page.md shows it
        for left in ("architecture/overview.html", "architecture/overview.png", "assets/social-preview.png",
                     "assets/brand.md", "assets/garrick-lockup.svg"):
            self.assertNotIn(left, shipped)
            self.assertFalse((copy / left).exists(), left)

    def test_only_an_image_a_page_shows_is_shipped(self):
        texts = {"a.md": "# A\n\n![shown](assets/shown.png) and [linked](assets/linked.png)\n\n"
                         "`![in code](assets/code.png)`\n\n```\n![fenced](assets/fenced.png)\n```\n",
                 "extras/b.md": "![up](../assets/up.svg) ![web](https://example.com/x.png) ![gone](../assets/none.png)\n",
                 "assets/note.md": "![from the assets](own.png)\n"}
        names = list(texts) + ["assets/" + n for n in ("shown.png", "linked.png", "code.png", "fenced.png", "up.svg",
                                                         "unused.png", "own.png")]
        self.assertEqual(["a.md", "assets/shown.png", "assets/up.svg", "extras/b.md"],
                         load_installer().shipped_docs(names, texts.__getitem__))

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
        (self.root / "System" / "generated").mkdir(exist_ok=True)         # the install built the page there
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
        stamp = self.root / "System" / "garrick-version.json"   # lists the templates' files by name
        for path in self.root.rglob("*"):
            if ".git" in path.parts or templates in path.parents or path.is_symlink() or path == stamp:
                continue
            self.assertNotIn(OPEN, path.name, path)
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue                        # an image the docs carry: its bytes are not text
                self.assertNotIn(OPEN, text, path)

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
        self.assertIn(f"\n{command}\n", (REPO / "docs" / "commands.md").read_text())
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


class SourceVersionTest(unittest.TestCase):
    """Which Garrick an installer is: a download carries its commit in VERSION,
    a clone asks git, and a copy of either with neither says it does not know."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.installer = load_installer()

    def tearDown(self):
        self.tmp.cleanup()

    def point_at(self, folder, version):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "VERSION").write_text(version)
        self.installer.REPO = folder
        self.installer.VERSION_FILE = folder / "VERSION"

    def test_a_download_reads_its_version_file(self):
        self.point_at(self.base / "garrick", "# Which Garrick\ncommit: 3f9c2ab\ndate: 2026-10-04\n")
        self.assertEqual({"commit": "3f9c2ab", "date": "2026-10-04", "from": "download"},
                         self.installer.source_version())

    def test_a_copy_with_neither_does_not_know(self):
        unfilled = (REPO / "VERSION").read_text()
        self.assertIn("$Format:%h$", unfilled)              # the source keeps it for git to fill in
        self.point_at(self.base / "copy", unfilled)
        self.assertEqual("unknown", self.installer.source_version()["commit"])
        # Inside someone else's repository, that repository's commit is not Garrick's.
        outer = self.base / "outer"
        outer.mkdir()
        subprocess.run(["git", "init", "-q", str(outer)], check=True)
        self.point_at(outer / "garrick", unfilled)
        self.assertEqual("unknown", self.installer.source_version()["commit"])

    @unittest.skipUnless((REPO / ".git").exists(), "not a clone")
    def test_git_fills_in_a_download(self):
        self.assertEqual("VERSION: export-subst: set", git(REPO, "check-attr", "export-subst", "VERSION"))


class TagRuleTest(unittest.TestCase):
    """The installer keeps no tag algorithm of its own. One rule and one guess
    live in `garrick_lib`, which the installer loads and a workspace's own
    `scaffold.py party` loads too; the answers are tested in `test_lib.py`."""

    def test_the_installer_asks_the_library(self):
        installer = load_installer()
        for name in ("TAG_RE", "TAG_RULE", "tag_guess", "tag_for"):
            self.assertFalse(hasattr(installer, name), "install.py still carries %s of its own" % name)
        source = INSTALL.read_text(encoding="utf-8")
        for use in ("pl.TAG_RE.match", "pl.TAG_RULE", "pl.tag_for("):
            self.assertIn(use, source, use)
        self.assertEqual("acme", installer.lib().tag_for("Acme Corp"))


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
                   "Sam Rivera", "Independent advisor", "", "", "", "", "", "y"]
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


def parse_context(root):
    """System/context.md as the workspace's own tools read it."""
    sys.path.insert(0, str(REPO / "template" / "System" / "tools"))
    from garrick_lib import load_context
    return load_context(root)


def asked(stdout):
    """The questions an interactive install put, in order: each is the line before a "> " prompt."""
    lines = stdout.splitlines()
    return [lines[i - 1] for i in range(1, len(lines)) if lines[i].startswith(">")]


class InteractiveTest(unittest.TestCase):
    def test_questions_in_order(self):
        # #118: the folder, the name, the line, the zones and what each holds, one
        # parties round, the commands and the go-ahead. No domain, wall, person or alias.
        box = Sandbox()
        try:
            target = box.work / "asked"
            answers = [
                str(target),                      # where
                "Sam Rivera",                     # name
                "Independent advisor",            # one line
                "",                               # zones: Work, Personal
                "Clients", "",                    # what goes in each
                "Acme Corp, Birch & Co",          # the parties, in one line
                "",                               # Acme Corp: the first zone
                "personal",                       # Birch & Co: another, in any case
                "",                               # the commands allowed: the default, yes
                "y",
            ]
            r = run([INSTALL], box.env, stdin="\n".join(answers) + "\n")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual([
                "Where should the workspace go? [~/Garrick]",
                "What is your name?",
                "In one line: what do you do, and for whom?",
                "Zones are the separate sides of your life, each kept apart. Type their names separated by commas. "
                "[Work, Personal]",
                "What goes in Work, in a few words? (Enter to skip)",
                "What goes in Personal, in a few words? (Enter to skip)",
                "Who do you work for or with? Names, separated by commas. Enter to skip.",
                "Which zone is Acme Corp in? (Work, Personal) [Work]",
                "Which zone is Birch & Co in? (Work, Personal) [Work]",
                "May your assistant run Garrick's own tools, and git's status, diff, log, add and commit inside the "
                "workspace, without asking each time? None of them sends anything off your Mac. (y/n) [y]",
                "Go ahead? (y/n) [y]",
            ], asked(r.stdout))
            self.assertIn(f"Ready to install in {target}: 2 zones, 2 parties.", r.stdout)
            ctx = parse_context(target)
            self.assertEqual({t: (p["party"], p["zone"], p["domains"]) for t, p in ctx["parties"].items()},
                             {"acme": ("Acme Corp", "Work", []), "birch": ("Birch & Co", "Personal", [])})
            self.assertEqual((ctx["walls"], ctx["people"], ctx["aliases"]), (set(), [], {}))
            text = (target / "System" / "context.md").read_text()
            # What each party is stays for the user, or their assistant, to fill in.
            self.assertIn("| Acme Corp | <What it is> | Work | `acme` |  |", text)
            self.assertIn("| Personal | <What Personal holds> |", text)
        finally:
            box.close()

    def test_the_parties_round_takes_tags_from_the_names(self):
        box = Sandbox()
        try:
            target = box.work / "plain"
            answers = [
                str(target), "Sam Rivera", "Independent advisor",
                "Work", "",                              # one zone, so no party is asked its zone
                "4Birch, Fernway Logistics, Fernway Freight, fernway logistics",
                "",                                      # 4Birch gives no tag, so one is asked; Enter is refused
                "4birch",                                # refused: a tag starts with a letter
                "fourbirch",                             # accepted
                "", "y",
            ]
            r = run([INSTALL], box.env, stdin="\n".join(answers) + "\n")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            questions = asked(r.stdout)
            self.assertNotIn("Which zone", r.stdout)
            # Only a name that yields no tag has one asked, and the prompt gives the real rule.
            self.assertEqual(3, questions.count(
                "A short tag for 4Birch, used in notes: one lowercase word that starts with a letter."), questions)
            self.assertNotIn("A short tag for Fernway", r.stdout)
            self.assertIn("A tag is one lowercase word that starts with a letter", r.stdout)
            ctx = parse_context(target)
            # A name said twice is one party; a second Fernway gets a wider tag.
            self.assertEqual({t: p["party"] for t, p in ctx["parties"].items()},
                             {"fourbirch": "4Birch", "fernway": "Fernway Logistics",
                              "fernway-freight": "Fernway Freight"})
            self.assertIn(f"Ready to install in {target}: 1 zone, 3 parties.", r.stdout)
        finally:
            box.close()

    # Every answer after the folder: a name, a line, the default zones, and nothing else.
    SHORT = ["Sam Rivera", "Independent advisor", "", "", "", "", "", "y"]

    def test_the_last_question_offers_the_commands_and_takes_a_no(self):
        box = Sandbox()
        try:
            answers = ["ws-asked"] + self.SHORT[:-2] + ["n", "y"]
            r = run([INSTALL], box.env, cwd=box.work, stdin="\n".join(answers) + "\n")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            asked = [line for line in r.stdout.splitlines() if line.startswith("May your assistant run")]
            self.assertEqual(1, len(asked), r.stdout)
            self.assertEqual("May your assistant run Garrick's own tools, and git's status, diff, log, add and "
                             "commit inside the workspace, without asking each time? None of them sends anything "
                             "off your Mac. (y/n) [y]", asked[0])
            # It is the last question before Go ahead, and a no writes nothing about permissions.
            self.assertLess(r.stdout.index(asked[0]), r.stdout.index("Go ahead?"))
            target = box.home / "ws-asked"
            self.assertFalse((target / ".claude" / "settings.json").exists())
            self.assertNotIn("allowed-commands", recorded_settings(target))     # only which page opens (#175)
            self.assertIn("No command is allowed in advance", r.stdout)
        finally:
            box.close()

    def test_a_typed_folder_goes_in_the_home_folder(self):
        box = Sandbox()
        try:
            r = run([INSTALL], box.env, cwd=box.work, stdin="\n".join(["ws-here"] + self.SHORT) + "\n")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            target = box.home / "ws-here"
            self.assertTrue((target / "AGENTS.md").is_file())
            self.assertFalse((box.work / "ws-here").exists())
            # The confirmation shows where it will go, not the words typed.
            self.assertIn(f"Ready to install in {target}: 2 zones, 0 parties.", r.stdout)
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


class AllowlistTest(unittest.TestCase):
    """The commands the assistant may run: declined, and written into a workspace
    already installed, where it may find a settings file of the user's own."""

    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.close)
        self.declined = self.box.config("declined", **{"allow-commands": False})

    def test_a_new_workspace_opens_on_the_simple_home(self):
        """#175: the status page opens a workspace made now on the simple
        home, and the choice is committed with the rest of System/. Saying
        no to the commands changes nothing about it."""
        for name, config in (("allowed", None), ("declined", self.declined)):
            target, r = self.box.install(name, **({"config": config} if config else {}))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual("simple", recorded_settings(target).get("home"), name)
            self.assertEqual("", git(target, "status", "--porcelain"), name)

    def test_a_config_that_declines_writes_nothing_about_permissions(self):
        target, r = self.box.install("declined", config=self.declined)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((target / ".claude" / "settings.json").exists())
        self.assertNotIn("allowed-commands", recorded_settings(target))     # only which page opens (#175)
        self.assertIn("No command is allowed in advance", r.stdout)
        self.assertEqual("", git(target, "status", "--porcelain"))

    def test_a_settings_file_of_your_own_keeps_everything_in_it(self):
        target, r = self.box.install("mine", config=self.declined)
        self.assertEqual(r.returncode, 0, r.stderr)
        settings = target / ".claude" / "settings.json"
        mine = ["Bash(ls:*)", "Bash(python3 System/tools/check.py:*)"]
        settings.write_text(json.dumps({"model": "opus", "permissions": {"allow": list(mine),
                                                                         "deny": ["WebFetch"]}}, indent=2))
        r = run([INSTALL, "--allowlist", target], self.box.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        after = json.loads(settings.read_text())
        self.assertEqual("opus", after["model"])                        # nothing else is touched
        self.assertEqual(["WebFetch"], after["permissions"]["deny"])
        allow = after["permissions"]["allow"]
        self.assertEqual(mine, allow[:2])                               # kept, in their own order
        self.assertEqual(1, allow.count(mine[1]))                       # and not added a second time
        rules = load_installer().claude_allow_rules(["Personal", "Work"])
        self.assertEqual(mine[:1] + rules, allow)
        recorded = json.loads((target / "System" / "garrick-settings.json").read_text())
        self.assertEqual(rules, recorded["allowed-commands"])
        self.assertIn("%d of %d rules added" % (len(rules) - 1, len(rules)), r.stdout)

    def test_a_settings_file_that_does_not_read_is_left_as_it_is(self):
        target, r = self.box.install("broken", config=self.declined)
        settings = target / ".claude" / "settings.json"
        settings.write_text("{ not json")
        r = run([INSTALL, "--allowlist", target], self.box.env)
        self.assertEqual(1, r.returncode)
        self.assertIn("not JSON Garrick can add to", r.stderr)
        self.assertEqual("{ not json", settings.read_text())
        self.assertNotIn("allowed-commands", recorded_settings(target))     # only which page opens (#175)

    def test_it_refuses_a_folder_that_is_not_a_workspace(self):
        r = run([INSTALL, "--allowlist", self.box.work], self.box.env)
        self.assertEqual(1, r.returncode)
        self.assertIn("does not look like a Garrick workspace", r.stderr)


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
        self.assertIn("underscore", self.refuse("project", "--zone", "Work", "--name", "Q3_Review",
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
        self.assertIn("full stop", self.refuse("thread", "--zone", "Work", "--project", "Acme", "--name", "Phase.2"))
        self.assertIn("no project called Cedar",
                      self.refuse("thread", "--zone", "Work", "--project", "Cedar", "--name", "Entry"))
        self.assertFalse((self.root / "Zones/Work/Birch").exists())
        self.assertFalse((self.root / "Zones/Work/Akme").exists())

    def test_a_business_name_will_do_and_is_asked_about(self):
        r = self.scaffold("thread", "--zone", "Work", "--project", "Acme", "--name", "Phase 2", "--check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Phase 2 will do as a thread in Acme.", r.stdout)
        self.assertIn("does not say how it is said", r.stdout)
        self.assertFalse((self.root / "Zones/Work/Acme/Threads/Phase 2").exists())

    def test_checker_passes(self):
        check = self.root / "System" / "tools" / "check.py"
        if not check.exists():
            self.skipTest("check.py is not in the template yet")
        r = run([check, "--root", self.root], self.box.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


# The command docs/commands.md gives for a zone added after install. The tests run
# it as written, with this interpreter, so the page and the script cannot drift apart.
ZONE_COMMAND = re.search(r'^python3 (System/tools/scaffold\.py zone "([^"]+)" --holds "[^"]+")$',
                         (REPO / "docs" / "commands.md").read_text(encoding="utf-8"), re.M)


def first_commit(repo):
    return git(repo, "rev-list", "--max-parents=0", "HEAD")


class ZoneTest(unittest.TestCase):
    """A zone added after install is made the way the installer makes one."""

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        cls.root, r = cls.box.install("ws")
        assert r.returncode == 0, r.stderr
        assert ZONE_COMMAND, "docs/commands.md gives no scaffold.py zone command"
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
        self.assertEqual(sorted(line.strip() for line in git(self.root, "status", "--porcelain").splitlines()),
                         ["M System/context.md", "M System/garrick-version.json"])

    def test_its_files_join_the_stamps_list(self):
        files = json.loads((self.root / "System" / "garrick-version.json").read_text())["files"]
        mine = {p for p in files if p.startswith("Zones/%s/" % self.name)}
        self.assertEqual({"Zones/%s/%s" % (self.name, f) for f in (".gitignore", "AGENTS.md", "Todo.md", "Inbox/.gitkeep")}, mine)
        for p in mine:
            self.assertEqual(hashlib.sha256((self.root / p).read_bytes()).hexdigest(), files[p])
        said = self.made.stdout
        self.assertIn("Listed its files in System/garrick-version.json", said)
        self.assertIn("Commit System/context.md and System/garrick-version.json in the workspace's own repository", said)

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
        for name, why in (("Work", "already has a zone called Work. Open it, or pick another name?"),
                          ("work", 'stored as "Work", and "work" would be the same folder'),
                          ("Werk", "sounds too much like Work"),
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


class ZoneTodoTest(unittest.TestCase):
    """A zone's list starts with the zone template's example line, there to show
    the shape, on the full home only. On the simple home nobody reads the list
    as a file, and an assistant asked what is owed would report the sample."""

    EXAMPLE = "- [ ] [[<Thread>]]: <action>"
    NOTE = "The line below is an example"

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox()
        cls.root, r = cls.box.install("ws")
        assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls):
        cls.box.close()

    def zone(self, name, home):
        settings = self.root / "System" / "garrick-settings.json"
        kept = settings.read_text()
        data = json.loads(kept)
        data.pop("home", None)
        data.update({"home": home} if home else {})
        settings.write_text(json.dumps(data, indent=2) + "\n")
        try:
            r = run([self.root / "System" / "tools" / "scaffold.py", "zone", name, "--holds", "Anything"],
                    self.box.env, cwd=self.root)
        finally:
            settings.write_text(kept)
        self.assertEqual(r.returncode, 0, r.stderr)
        return (self.root / "Zones" / name / "Todo.md").read_text()

    def test_an_install_on_the_simple_home_starts_each_list_without_it(self):
        self.assertEqual("simple", recorded_settings(self.root)["home"])
        for zone in ("Work", "Personal"):
            text = (self.root / "Zones" / zone / "Todo.md").read_text()
            self.assertNotIn(self.EXAMPLE, text, zone)
            self.assertNotIn(self.NOTE, text, zone)
            self.assertNotIn("<", text, zone)
            self.assertIn("One line per action, Obsidian Tasks style.", text)
            self.assertIn("\n\n## Inbox\n\n## Done\n", text)
            self.assertNotIn("\n\n\n", text)
        # The template keeps it, for a zone added to a workspace on the full home.
        template = (self.root / "System" / "templates" / "zone" / "Todo.md").read_text()
        self.assertIn(self.EXAMPLE, template)
        self.assertIn(self.NOTE, template)

    def test_a_zone_added_later_follows_the_home(self):
        self.assertNotIn(self.EXAMPLE, self.zone("Garden", "simple"))
        for name, home in (("Studio", "full"), ("Travel", None)):    # no "home": a workspace from before #175
            text = self.zone(name, home)
            self.assertIn(self.EXAMPLE, text, name)
            self.assertIn(self.NOTE, text, name)
            template = (self.root / "System" / "templates" / "zone" / "Todo.md").read_text()
            self.assertEqual(template.replace("{{ZONE}}", name), text)


class HomePageTest(unittest.TestCase):
    """#208: a workspace that opens on the simple home gets the page itself, the
    status extra in System/status, committed with the rest, and the page built
    once. One installed without the simple home gets neither, as before."""

    PAGE = Path("System") / "generated" / "status.html"

    @classmethod
    def setUpClass(cls):
        cls.box = Sandbox(page=True)
        cls.root, cls.result = cls.box.install("ws")

    @classmethod
    def tearDownClass(cls):
        cls.box.close()

    def in_process(self, name, home, env=None, **patches):
        """An install from this module, with NEW_HOME set to `home`, in the
        sandbox's environment and `env`: (root, what it said)."""
        installer = load_installer()
        installer.NEW_HOME = home
        for key, value in patches.items():
            setattr(installer, key, value)
        out = io.StringIO()
        with mock.patch.dict(os.environ, dict(self.box.env, **(env or {})), clear=True), \
                contextlib.redirect_stdout(out):
            root = installer.install(json.loads(EXAMPLE.read_text()), self.box.work / name)
        return root, out.getvalue()

    def test_a_simple_home_install_has_the_status_page_and_a_built_page(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)
        self.assertEqual("simple", recorded_settings(self.root)["home"])
        sys.path.insert(0, str(REPO))
        try:
            import update
        finally:
            sys.path.remove(str(REPO))
        extra = update.extras_shipped(["status"])
        self.assertIn("System/status/status.py", extra)
        self.assertIn("System/status/app/make-app.sh", extra)
        for rel, (data, mode) in extra.items():                     # as copying the extra by hand would leave it
            self.assertEqual(data, (self.root / rel).read_bytes(), rel)
            self.assertEqual(mode, (self.root / rel).stat().st_mode & 0o777, rel)
        self.assertEqual(sorted(extra), sorted(p.relative_to(self.root).as_posix()
                                               for p in (self.root / "System" / "status").rglob("*") if p.is_file()))
        tracked = git(self.root, "ls-files", "System/status").splitlines()
        self.assertEqual(sorted(extra), sorted(tracked))            # committed with the rest
        stamp = json.loads((self.root / "System" / "garrick-version.json").read_text())["files"]
        self.assertTrue(set(extra) <= set(stamp))                   # fingerprinted, so an update can tell it as written
        # Built once, on the simple home, where git leaves it out.
        page = (self.root / self.PAGE).read_text(encoding="utf-8")
        self.assertIn('<body class="simple" data-tab="home"', page)
        self.assertEqual("", git(self.root, "status", "--porcelain", "--untracked-files=all"))
        self.assertIn("Your home page is built, in System/generated/status.html", self.result.stdout)
        self.assertIn('"Set up Garrick" offers to make it a Mac app.', self.result.stdout)
        self.assertFalse(list(self.box.home.iterdir()))             # nothing built or written outside it, no app
        # An update finds the extra installed, with nothing to do.
        p = update.plan(self.root)
        self.assertEqual(["status"], p["extras"])
        self.assertEqual({k: [] for k in update.KINDS}, p["actions"])

    def test_a_classic_install_has_neither(self):
        root, said = self.in_process("classic", "full")
        self.assertEqual("full", recorded_settings(root)["home"])
        self.assertFalse((root / "System" / "status").exists())
        self.assertFalse((root / self.PAGE).exists())
        self.assertFalse((root / "System" / "generated").exists())
        self.assertNotIn("home page", said)
        stamp = json.loads((root / "System" / "garrick-version.json").read_text())["files"]
        self.assertFalse([rel for rel in stamp if rel.startswith("System/status/")])

    def test_a_page_that_does_not_build_leaves_the_install_and_says_how(self):
        asked = []
        root, said = self.in_process("unbuilt", "simple",
                                     build_page=lambda r: asked.append(r) or "status.py stopped: no luck")
        self.assertEqual([root], asked)
        self.assertTrue((root / "System" / "status" / "status.py").is_file())
        self.assertFalse((root / self.PAGE).exists())
        self.assertIn("Your home page, in System/status, was not built: status.py stopped: no luck", said)
        self.assertIn("To build it: python3 System/status/status.py --workspace %s" % shlex.quote(str(root)), said)
        self.assertEqual("", git(root, "status", "--porcelain"))
        self.assertTrue(said.strip().splitlines()[-1].startswith("Next: open "))

    def test_the_suites_switch_puts_the_page_in_place_unbuilt(self):
        asked = []
        root, said = self.in_process("switched", "simple", env={"GARRICK_INSTALL_NO_PAGE": "1"},
                                     build_page=lambda r: asked.append(r) or "")
        self.assertEqual([], asked)
        self.assertTrue((root / "System" / "status" / "status.py").is_file())
        self.assertFalse((root / self.PAGE).exists())
        self.assertIn("To build it: python3 System/status/status.py --workspace", said)


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
