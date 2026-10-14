"""A commit made with a pathspec (`git commit -m … -- Todo.md`), which git runs
with GIT_INDEX_FILE pointing at a temporary index inside the committing
repository.

The hook has to read that index: it is what the commit will hold. No other
repository may see it, or each compares its own HEAD against it, reports its
whole tree as changed, and the hook reads every file of it back out of git.

Invented parties only: Acme Corp (`acme`) and Birch & Co (`birch`), walled
from each other, as in fixtures.py. The fixtures here are built by hand and
read nothing of the machine they run on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import fixtures
from fixtures import GIT_ENV, HAVE_GIT, TOOLS, build_workspace, commit_all, git, meeting_page, write

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)
from garrick_lib import LOCAL_ENV_VARS, foreign_git_env, git_local_env_vars, install_wall_hook  # noqa: E402

ENV = dict(GIT_ENV, PYTHONDONTWRITEBYTECODE="1")

# Wording only the Birch side ever heard. Never allowed to appear in a finding.
SECRET = "The board wants the Oslo depot signed before the tenth of November at any price"
SECRET_WORDS = ("oslo", "depot", "november")

FILLER = 60  # files in the other repository: enough that reading it is unmissable


class TestForeignEnv(unittest.TestCase):
    """The helper itself, on an environment handed to it."""

    def test_the_names_come_from_git_not_from_a_list_here(self):
        self.assertIn("GIT_INDEX_FILE", git_local_env_vars())
        self.assertIn("GIT_INDEX_FILE", LOCAL_ENV_VARS)       # the fallback, for a git too old to be asked

    def test_every_local_variable_goes_and_nothing_else_does(self):
        env = {n: "value" for n in git_local_env_vars()}
        env.update(PATH="/usr/bin", GIT_AUTHOR_NAME="Jo Example", HOME="/home/jo")
        clean = foreign_git_env(env)
        self.assertEqual({"PATH": "/usr/bin", "GIT_AUTHOR_NAME": "Jo Example", "HOME": "/home/jo"}, clean)

    def test_nothing_to_strip_leaves_the_child_to_inherit(self):
        self.assertIsNone(foreign_git_env({"PATH": "/usr/bin", "GIT_AUTHOR_NAME": "Jo Example"}))


def _copy_tools(root: Path) -> None:
    tools = root / "System" / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    for name in ("check.py", "garrick_lib.py"):
        shutil.copy2(TOOLS / name, tools / name)


def _run(args, cwd, env=None):
    return subprocess.run([str(a) for a in args], cwd=str(cwd), env=env or ENV, capture_output=True, text=True)


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class PathspecCase(unittest.TestCase):
    """A workspace of two real repositories: the Work zone, with the hook, and
    the Wikis, which holds the meetings and `FILLER` other files."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        _copy_tools(self.root)
        self.acme = self.root / "Zones" / "Work" / "Acme Review"
        self.birch = self.root / "Zones" / "Work" / "Birch Entry"
        self.meetings = self.root / "Wikis" / "Meetings"
        self.zone = self.root / "Zones" / "Work"
        self.wikis = self.root / "Wikis"
        for i in range(FILLER):
            write(self.wikis / "filler" / ("note-%02d.md" % i), "Nordic demand, three scenarios, one chart.\n")
        git(self.wikis, "init", "-q")
        commit_all(self.wikis, "Wikis")
        shutil.rmtree(self.zone / ".git")
        git(self.zone, "init", "-q")
        install_wall_hook(self.zone)
        commit_all(self.zone, "start")

    def tearDown(self):
        check._committing(None)
        self._tmp.cleanup()

    def commit(self, *pathspec, env=None):
        """A commit of `pathspec` alone, as the status page makes it, through
        the hook. The temporary index git builds for it holds the working
        tree's version of those files and the index's of everything else."""
        args = ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "A line"]
        return _run(args + ["--", *pathspec], self.zone, env=env)

    def real_root(self) -> None:
        """The root as its own repository, holding the zones and the wikis as
        repositories of their own and leaving them out of its history, as the
        installer makes it.

        Garrick installs no wall hook at the root (`check.py --install-hooks`
        writes one into each zone and each repository inside a project, and the
        installer the same), so the one put here stands for whatever runs the
        check for a commit at the root: the check run by hand, or a hook added
        later. `scaffold.py party` leaves a `System/context.md` row to commit,
        which is how such a commit comes about."""
        write(self.root / ".gitignore", "Zones/\nWikis/\nSystem/generated/\n")
        for i in range(FILLER):
            write(self.root / "System" / "filler" / ("note-%02d.md" % i), "Nordic demand, three scenarios.\n")
        git(self.root, "init", "-q")
        install_wall_hook(self.root, nested=True)
        commit_all(self.root, "Workspace")

    def foreign_index(self, repo: Path) -> Path:
        """A copy of `repo`'s index where git puts the temporary one for a
        commit of named files, named as git names it."""
        temp = repo / ".git" / "next-index-0.lock"
        shutil.copy2(repo / ".git" / "index", temp)
        return temp

    def view(self, committing: Path, foreign: bool):
        """`git_view` for a commit in `committing`, with and without that
        repository's temporary index in the environment, as git sets it for a
        commit of named files."""
        before = os.environ.get("GIT_INDEX_FILE")
        if foreign:
            os.environ["GIT_INDEX_FILE"] = str(self.foreign_index(committing))
        else:
            os.environ.pop("GIT_INDEX_FILE", None)
        try:
            check._committing(committing)
            ws = check.discover(self.root)
            seen = check.git_view(ws, committing.resolve())
            return {p.relative_to(self.root).as_posix(): t for p, t in seen.items()}
        finally:
            check._committing(None)
            if before is None:
                os.environ.pop("GIT_INDEX_FILE", None)
            else:
                os.environ["GIT_INDEX_FILE"] = before

    def counted(self, repo: Path, name: str):
        """How many git processes a commit of `name` in `repo` starts, each kind:
        {"plain": n, "pathspec": n}, counted from git's own trace."""
        counts = {}
        for kind in ("plain", "pathspec"):
            path = repo / name
            path.write_text(path.read_text(encoding="utf-8") + "\n<!-- A line, %s -->\n" % kind, encoding="utf-8")
            trace = Path(self._tmp.name) / ("trace-%s-%s.txt" % (repo.name, kind))
            args = ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "A line"]
            if kind == "plain":
                git(repo, "add", "--", name)
            else:
                args += ["--", name]
            res = _run(args, repo, env=dict(ENV, GIT_TRACE=str(trace)))
            self.assertEqual(0, res.returncode, res.stdout + res.stderr)
            lines = trace.read_text(errors="replace").splitlines() if trace.exists() else []
            counts[kind] = sum(1 for line in lines if "built-in: git" in line)
        if not counts["plain"]:
            self.skipTest("this git does not write GIT_TRACE")
        return counts

    def head(self):
        return git(self.zone, "rev-parse", "HEAD")

    def birch_call(self):
        """A Birch meeting holding SECRET, committed in the Wikis repository and
        then taken off disk: only git's version of that repository still holds
        the words, so a refusal can come from nowhere else."""
        page = self.meetings / "wiki" / "sources" / "260314-birch-call.md"
        write(page, meeting_page("Work", "[birch]", "Birch call").replace("Decisions.", SECRET + "."))
        commit_all(self.wikis, "Birch call")
        write(page, meeting_page("Work", "[birch]", "Birch call"))
        return page


class TestTheOtherRepository(PathspecCase):
    """What the hook reads from a repository it is not committing must not depend
    on how the commit was made."""

    def test_it_is_read_the_same_either_way(self):
        page = self.meetings / "wiki" / "sources" / "260312-birch-kickoff.md"
        write(page, meeting_page("Work", "[birch]", "Birch kick-off").replace("Decisions.", "Rewritten on disk.\n"))
        plain = self.view(self.zone, foreign=False)
        self.assertEqual(["Wikis/Meetings/wiki/sources/260312-birch-kickoff.md"], sorted(plain))
        self.assertIn("Decisions.", plain["Wikis/Meetings/wiki/sources/260312-birch-kickoff.md"])
        self.assertEqual(plain, self.view(self.zone, foreign=True))       # and not the whole Wikis repository

    def test_a_pathspec_commit_starts_no_more_git_processes_than_a_plain_one(self):
        """The fault was 2,019 git processes for one line. The hook's work must
        not depend on which kind of commit it is."""
        counts = self.counted(self.zone, "Todo.md")
        self.assertLessEqual(counts["pathspec"], counts["plain"] + 8,
                             "%d git processes for a pathspec commit in the zone against %d for a plain one; the "
                             "temporary index is reaching the other repositories again"
                             % (counts["pathspec"], counts["plain"]))


class TestTheRootRepository(PathspecCase):
    """The root repository holds every zone and both wikis, each its own
    repository. Containment is therefore no answer to which repository a folder
    belongs to, and a commit at the root must leave the others alone."""

    def setUp(self):
        super().setUp()
        self.real_root()

    def test_the_zones_and_the_wikis_are_read_the_same_either_way(self):
        page = self.meetings / "wiki" / "sources" / "260312-birch-kickoff.md"
        write(page, meeting_page("Work", "[birch]", "Birch kick-off").replace("Decisions.", "Rewritten on disk.\n"))
        note = self.birch / "Threads" / "Market Sizing" / "Notes.md"
        write(note, "Three scenarios.\n")
        git(self.zone, "add", "--", str(note.relative_to(self.zone)))
        commit_all(self.zone, "Market sizing notes")
        write(note, "Rewritten on disk.\n")
        plain = self.view(self.root, foreign=False)
        self.assertEqual(["Wikis/Meetings/wiki/sources/260312-birch-kickoff.md",
                          "Zones/Work/Birch Entry/Threads/Market Sizing/Notes.md"], sorted(plain))
        self.assertEqual(plain, self.view(self.root, foreign=True))   # and not both repositories whole

    def test_a_pathspec_commit_at_the_root_starts_no_more_git_processes_than_a_plain_one(self):
        counts = self.counted(self.root, "System/context.md")
        self.assertLessEqual(counts["pathspec"], counts["plain"] + 8,
                             "%d git processes for a pathspec commit at the root against %d for a plain one; the "
                             "zones and the wikis are inheriting the root's temporary index"
                             % (counts["pathspec"], counts["plain"]))


class TestWhichRepositoryAFolderBelongsTo(PathspecCase):
    """`_git_env` keeps git's repository-local variables for the repository
    being committed, which is decided by the repository a folder belongs to and
    never by what contains it."""

    def setUp(self):
        super().setUp()
        os.environ["GIT_INDEX_FILE"] = str(self.foreign_index(self.zone))
        self.addCleanup(os.environ.pop, "GIT_INDEX_FILE", None)

    def assertKeeps(self, folder: Path):
        self.assertIsNone(check._git_env(folder), "%s should keep git's own environment" % folder)

    def assertStrips(self, folder: Path):
        env = check._git_env(folder)
        self.assertIsInstance(env, dict, "%s should not keep git's own environment" % folder)
        self.assertNotIn("GIT_INDEX_FILE", env)

    def test_a_project_or_a_thread_inside_the_committing_zone_keeps_them(self):
        check._committing(self.zone)
        self.assertKeeps(self.zone)
        self.assertKeeps(self.acme)                                   # a project folder, not the top
        self.assertKeeps(self.acme / "Threads" / "Pricing")           # nor is a thread folder
        self.assertKeeps(self.acme / "Sources")
        self.assertStrips(self.wikis)
        self.assertStrips(self.meetings)

    def test_a_zone_inside_the_committing_root_does_not(self):
        self.real_root()
        check._committing(self.root)
        self.assertKeeps(self.root)
        self.assertKeeps(self.root / "System" / "tools")              # the root's own folders
        self.assertStrips(self.zone)                                  # its own repository, though below the root
        self.assertStrips(self.acme)
        self.assertStrips(self.wikis)
        self.assertStrips(self.meetings)

    def test_a_repository_inside_a_project_does_not(self):
        site = self.acme / "Site"
        site.mkdir(parents=True)
        git(site, "init", "-q")
        check._committing(self.zone)
        self.assertStrips(site)
        self.assertStrips(site / "src")
        self.assertKeeps(self.acme)


class TestTheWallStillHolds(PathspecCase):
    """Nothing about the environment may let a pathspec commit through a wall."""

    def test_a_name_across_the_wall_is_refused(self):
        note = self.birch / "Threads" / "Market Sizing" / "Notes.md"
        write(note, "Dana Whitlock called.\n")
        git(self.zone, "add", "--", str(note.relative_to(self.zone)))   # git names only what it knows
        head = self.head()
        res = self.commit(str(note.relative_to(self.zone)))
        self.assertEqual(1, res.returncode, res.stdout + res.stderr)
        self.assertIn("Commit refused", res.stderr)
        self.assertIn("names Acme Corp", res.stderr)
        self.assertNotIn("Dana", res.stderr)
        self.assertEqual(head, self.head())

    def test_wording_from_a_meeting_in_the_other_repository_is_refused(self):
        """The quote comparison reads the Wikis repository through the git calls
        this fix changed: the meeting is gone from disk, so git's version of
        that repository is the only place the wording still is."""
        self.birch_call()
        brief = self.acme / "Deliverables" / "260302 - Board note.md"
        write(brief, SECRET + "\n")
        git(self.zone, "add", "--", str(brief.relative_to(self.zone)))
        head = self.head()
        res = self.commit(str(brief.relative_to(self.zone)))
        self.assertEqual(1, res.returncode, res.stdout + res.stderr)
        self.assertIn("Commit refused", res.stderr)
        self.assertIn("260314-birch-call", res.stderr)
        for word in SECRET_WORDS:
            self.assertNotIn(word, res.stderr.lower())
        self.assertEqual(head, self.head())

    def test_the_hook_reads_the_temporary_index_not_the_file_on_disk(self):
        """A pathspec commit holds the working tree's version of what it names,
        and the temporary index is where the hook finds it. Strip the
        environment from the committing repository too and this commit goes
        through: the index on disk still holds the clean version."""
        note = self.birch / "Threads" / "Market Sizing" / "Notes.md"
        write(note, "Three scenarios.\n")
        git(self.zone, "add", "--", str(note.relative_to(self.zone)))
        commit_all(self.zone, "Market sizing notes")
        write(note, "Dana Whitlock called.\n")          # in the working tree alone, never staged
        self.assertEqual("", git(self.zone, "diff", "--cached", "--name-only"))
        head = self.head()
        res = self.commit(str(note.relative_to(self.zone)))
        self.assertEqual(1, res.returncode, res.stdout + res.stderr)
        self.assertIn("names Acme Corp", res.stderr)
        self.assertEqual(head, self.head())

    def test_what_the_commit_leaves_behind_does_not_refuse_it(self):
        """The other side of the same point: a breach staged but taken out of
        the working tree is not what a pathspec commit of that file holds, so
        it passes, and the commit holds the clean version."""
        note = self.birch / "Threads" / "Market Sizing" / "Notes.md"
        write(note, "Dana Whitlock called.\n")
        git(self.zone, "add", "--", str(note.relative_to(self.zone)))
        write(note, "Three scenarios.\n")
        res = self.commit(str(note.relative_to(self.zone)))
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertEqual("Three scenarios.\n",
                         git(self.zone, "show", "HEAD:%s" % note.relative_to(self.zone).as_posix()))


if __name__ == "__main__":
    unittest.main()
