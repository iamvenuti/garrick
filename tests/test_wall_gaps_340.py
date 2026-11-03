"""Six gaps the 0.52.0 wall reviews found in older code (#340).

    cd tests && python3 -m unittest test_wall_gaps_340

None let a Garrick tool write across a wall; each needed a hand edit and left
the commit hook saying less than docs/enforced.md suggests. Each is closed by
refusing what cannot be read plainly. Every workspace is built in a temporary
folder.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import fixtures  # noqa: E402  (puts the tools folder on sys.path)
from fixtures import GIT_ENV, HAVE_GIT, checkpoint, git, write  # noqa: E402

import check  # noqa: E402
import garrick_lib  # noqa: E402
import importlib.util  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

from test_person_employer import CONTEXT, Workspace as EmployerWorkspace, entity, person  # noqa: E402

TOOLS = Path(__file__).resolve().parent.parent / "template" / "System" / "tools"

# ---------------------------------------------------------------------------
# 1. A Resume here or checkpoint path into another zone
# ---------------------------------------------------------------------------


class ZonePathTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        fixtures.build_workspace(self.root)
        write(self.root / "Zones" / "Personal" / "Notes" / "home.md", "# Home\n")
        write(self.root / "Zones" / "Work" / "Notes" / "plan.md", "# Plan\n")
        self.note = self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"

    def resume(self, sentence: str) -> Path:
        text = fixtures.thread_note("Acme Review", "Pricing", "acme").replace("Drafting.", sentence)
        write(self.note, text)
        return self.note

    def crossings(self):
        return [f for f in check.run_checks(self.root) if f.check == "links" and f.severity == "error"
                and f.path.endswith("Pricing.md")]

    def test_a_path_into_another_zone_is_an_error_however_it_is_written(self):
        for path in ("../../Personal/Notes/home.md", "../../../Personal/Notes/home.md", "Zones/Personal/Notes/home.md",
                     "Personal/Notes/home.md", "../../Personal/Notes/not-made-yet.md"):
            self.resume("Waiting on `%s`." % path)
            found = self.crossings()
            self.assertEqual(1, len(found), path)
            self.assertIn("a path in another zone", found[0].message)

    def test_a_link_out_of_the_zone_through_a_symbolic_link_is_an_error(self):
        os.symlink(str(self.root / "Zones" / "Personal"), str(self.root / "Zones" / "Work" / "Acme Review" / "away"))
        self.resume("Waiting on `away/Notes/home.md`.")
        self.assertEqual(1, len(self.crossings()))

    def test_a_path_is_read_in_any_case_with_a_suffix_and_with_or_without_backticks(self):
        for path in ("`../../personal/Notes/home.md`", "`../../PERSONAL/Notes/home.md`", "`Zones/personal/Notes/home.md`",
                     "`Zones/Personal/Notes`", "`../../Personal/Notes`", "`Zones/Personal/Notes/home.md:3`",
                     "`Zones/Personal/Notes/home.md#h`", "[h](../../Personal/Notes/home.md)",
                     "[h](<../../Personal/Notes/home.md>)", "[[Personal/Notes/home]]", "<../../Personal/Notes/home.md>",
                     "../../Personal/Notes/home.md", "see Zones/Personal/Notes/home.md in text",
                     "`..\\..\\Personal\\Notes\\home.md`", "[h](%2E%2E/%2E%2E/Personal/Notes/home.md)",
                     "```\n../../Personal/Notes/home.md\n```"):
            self.resume("Waiting on %s." % path)
            self.assertEqual(1, len(self.crossings()), path)

    def test_a_zone_named_with_a_space_or_an_apostrophe_is_found_in_any_spelling(self):
        for zone in ("Side Work", "Jo's Stuff"):
            write(self.root / "Zones" / zone / "Notes" / "home.md", "# Home\n")
            (self.root / "Zones" / zone / ".git").mkdir()
            low = zone.lower()
            for path in ("`../../%s/Notes/home.md`", "`Zones/%s/Notes/home.md`", "Zones/%s/Notes/home.md",
                         "`../../%s`", "[[%s/Notes/home]]", "[h](<../../%s/Notes/home.md>)",
                         "[h](../../%s/Notes/home.md)".replace("%s", zone.replace(" ", "%20").replace("'", "%27") + "%s"[:0]),
                         "`../../%s/Notes/home.md`".replace("%s", "%s"), "`Zones/" + low + "/Notes/home.md`",
                         "`../../" + zone.replace(" ", "  ") + "/Notes/home.md`"):
                text = path % zone if "%s" in path else path
                self.resume("Waiting on %s." % text)
                self.assertEqual(1, len(self.crossings()), text)

    def test_a_folder_of_that_name_in_the_project_is_that_folder(self):
        write(self.root / "Zones" / "Side Work" / "Notes" / "home.md", "# Home\n")
        (self.root / "Zones" / "Side Work" / ".git").mkdir()
        write(self.root / "Zones" / "Work" / "Acme Review" / "Side Work" / "Notes" / "plan.md", "# Plan\n")
        self.resume("See `Side Work/Notes/plan.md` and Side Work/Notes/plan.md.")
        self.assertEqual([], self.crossings())

    def test_a_path_that_is_there_in_the_project_is_that_path(self):
        write(self.root / "Zones" / "Work" / "Acme Review" / "Personal" / "Notes" / "plan.md", "# Plan\n")
        self.resume("See `Personal/Notes/plan.md`, [p](Personal/Notes/plan.md) and Personal/Notes/plan.md.")
        self.assertEqual([], self.crossings())

    def test_a_path_in_the_notes_own_zone_is_not(self):
        self.resume("Waiting on `../../Work/Notes/plan.md` and `Deliverables/260301 - Pricing memo.md`.")
        self.assertEqual([], self.crossings())

    def test_a_checkpoint_path_into_another_zone_is_an_error(self):
        text = fixtures.thread_note("Acme Review", "Pricing", "acme")
        items = fixtures.CHECKPOINT_ITEMS + (("made", "`../../Personal/Notes/home.md`, saved 14:20", "m2"),)
        write(self.note, checkpoint(text, items=items))
        found = self.crossings()
        self.assertEqual(1, len(found))
        self.assertIn("its checkpoint names", found[0].message)


# ---------------------------------------------------------------------------
# 2. Wikis has a pre-commit hook
# ---------------------------------------------------------------------------


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class WikiHookTest(EmployerWorkspace):
    def setUp(self):
        super().setUp()
        self.wikis = self.root / "Wikis"
        shutil.copytree(str(TOOLS), str(self.root / "System" / "tools"), ignore=shutil.ignore_patterns("__pycache__"))
        git(self.wikis, "init", "-q")
        git(self.wikis, "config", "user.email", "test@example.invalid")

    def hooks(self):
        return [f for f in check.run_checks(self.root) if f.check == "zones" and f.path == "Wikis"]

    def test_a_wiki_repository_with_no_wall_check_is_warned(self):
        found = self.hooks()
        self.assertEqual(1, len(found))
        self.assertEqual("warning", found[0].severity)
        self.assertIn("--install-hooks", found[0].message)

    def test_install_hooks_puts_it_in_the_wiki_and_the_warning_goes(self):
        self.assertEqual(0, check.install_hooks(self.root))
        self.assertTrue(garrick_lib.has_wall_hook(self.wikis))
        self.assertEqual([], self.hooks())

    def test_the_hook_refuses_a_commit_that_crosses_a_wall_and_passes_one_that_does_not(self):
        garrick_lib.install_wall_hook(self.wikis, wiki=True)
        env = dict(GIT_ENV)
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/birch-co]]"))
        git(self.wikis, "add", "-A")
        refused = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(self.wikis), env=env,
                                 capture_output=True, text=True)
        self.assertNotEqual(0, refused.returncode)
        self.assertIn("Commit refused", refused.stderr)
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/acme-corp]]"))
        git(self.wikis, "add", "-A")
        passed = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(self.wikis), env=env,
                                capture_output=True, text=True)
        self.assertEqual(0, passed.returncode, passed.stderr)


    def test_a_wiki_reached_through_a_symbolic_link_still_finds_the_workspace(self):
        elsewhere = Path(self._tmp.name).resolve() / "cloud" / "Wikis"
        elsewhere.parent.mkdir()
        shutil.rmtree(str(self.wikis / ".git"))
        shutil.move(str(self.wikis), str(elsewhere))
        os.symlink(str(elsewhere), str(self.wikis))
        git(elsewhere, "init", "-q")
        git(elsewhere, "config", "user.email", "test@example.invalid")
        garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root)
        self.assertIn(shlex_quote(self.root), (elsewhere / ".git" / "hooks" / "pre-commit").read_text())
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/birch-co]]"))
        git(elsewhere, "add", "-A")
        refused = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(elsewhere), env=dict(GIT_ENV),
                                 capture_output=True, text=True)
        self.assertNotEqual(0, refused.returncode)
        self.assertIn("Commit refused: ", refused.stderr)
        self.assertNotIn("no workspace found", refused.stderr)
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/acme-corp]]"))
        git(elsewhere, "add", "-A")
        passed = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(elsewhere), env=dict(GIT_ENV),
                                capture_output=True, text=True)
        self.assertEqual(0, passed.returncode, passed.stderr)

    def commit_in(self, repo):
        return subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(repo), env=dict(GIT_ENV),
                              capture_output=True, text=True)

    def test_a_copied_workspace_is_checked_as_itself(self):
        garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root)
        copy = self.root.parent / "Copy"
        shutil.copytree(str(self.root), str(copy), symlinks=True)
        # The original no longer draws the wall, so a hook that read it would pass.
        context = self.root / "System" / "context.md"
        context.write_text(context.read_text(encoding="utf-8").replace("| `acme` | `birch` |", "| `acme` | `cedar` |"))
        mine = copy / "Wikis" / "Meetings" / "wiki" / "people"
        write(mine / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[wiki/entities/birch-co]].",
                                               "[[wiki/entities/acme-corp]]"))
        git(copy / "Wikis", "add", "-A")
        res = self.commit_in(copy / "Wikis")
        self.assertNotEqual(0, res.returncode, res.stderr)
        self.assertIn("Commit refused", res.stderr)

    def test_a_walled_link_in_the_text_is_refused_in_a_wiki_reached_through_a_link(self):
        elsewhere = Path(self._tmp.name).resolve() / "cloud" / "Wikis"
        elsewhere.parent.mkdir()
        shutil.move(str(self.wikis), str(elsewhere))
        os.symlink(str(elsewhere), str(self.wikis))
        garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root)
        for body in ("Buyer at [[wiki/entities/birch-co]].", "Buyer at [[birch-co]]."):
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", body))
            git(elsewhere, "add", "-A")
            res = self.commit_in(elsewhere)
            self.assertNotEqual(0, res.returncode, body)
            self.assertIn("Wikis/Meetings/wiki/people/pat-newcomer.md", res.stderr)

    def test_a_repository_that_is_not_part_of_the_workspace_is_refused(self):
        outside = Path(self._tmp.name).resolve() / "elsewhere"
        outside.mkdir()
        git(outside, "init", "-q")
        write(outside / "note.md", "x\n")
        git(outside, "add", "-A")
        res = subprocess.run([sys.executable, str(TOOLS / "check.py"), "--root", str(self.root), "--staged",
                              "--walls-only"], cwd=str(outside), env=dict(GIT_ENV), capture_output=True, text=True)
        self.assertEqual(1, res.returncode, res.stdout + res.stderr)
        self.assertIn("not part of the workspace", res.stderr)

    def first_commit(self):
        garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root)
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")

    def bad_page(self, folder):
        write(folder / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[wiki/entities/birch-co]].",
                                                 "[[wiki/entities/acme-corp]]"))

    def test_a_linked_worktree_of_the_wikis_is_refused_wherever_it_stands(self):
        self.first_commit()
        for i, where in enumerate((self.wikis / "wt", self.wikis / "Meetings" / "wt", self.root / "wt")):
            git(self.wikis, "worktree", "add", "-q", "-b", "br%d" % i, str(where))
            self.bad_page(where / "Meetings" / "wiki" / "people")
            git(where, "add", "-A")
            res = self.commit_in(where)
            self.assertNotEqual(0, res.returncode, where)
            self.assertIn("worktree", res.stderr)
            via_check = subprocess.run([sys.executable, str(TOOLS / "check.py"), "--root", str(self.root), "--staged",
                                        "--walls-only"], cwd=str(where), env=dict(GIT_ENV), capture_output=True, text=True)
            self.assertEqual(1, via_check.returncode, where)
            self.assertIn("this repository", via_check.stderr)

    def test_a_work_tree_moved_by_the_environment_or_the_configuration_is_refused(self):
        self.first_commit()
        self.bad_page(self.people)
        git(self.wikis, "add", "-A")
        sub = self.wikis / "Meetings"
        env = dict(GIT_ENV, GIT_DIR=str(self.wikis / ".git"), GIT_WORK_TREE=str(sub))
        res = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(sub), env=env, capture_output=True, text=True)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("work tree", res.stderr)
        git(self.wikis, "config", "core.worktree", str(sub))
        res = self.commit_in(sub)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("work tree", res.stderr)

    def test_a_check_inside_the_repository_is_not_the_one_that_runs(self):
        self.first_commit()
        write(self.wikis / "System" / "tools" / "check.py", "import sys\nsys.exit(0)\n")
        os.symlink(".", str(self.wikis / "Wikis"))
        self.bad_page(self.people)
        git(self.wikis, "add", "-A")
        res = self.commit_in(self.wikis)
        self.assertNotEqual(0, res.returncode, res.stderr)
        self.assertIn("Commit refused", res.stderr)

    def test_a_meetings_wiki_alone_reached_through_a_link_is_checked_and_commits(self):
        cloud = Path(self._tmp.name).resolve() / "cloud"
        cloud.mkdir()
        shutil.rmtree(str(self.wikis / ".git"))
        shutil.move(str(self.wikis / "Meetings"), str(cloud / "Meetings"))
        os.symlink(str(cloud / "Meetings"), str(self.wikis / "Meetings"))
        meetings = self.wikis / "Meetings"
        git(meetings, "init", "-q")
        git(meetings, "config", "user.email", "test@example.invalid")
        garrick_lib.install_wall_hook(meetings, wiki=True, root=self.root)
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/acme-corp]]"))
        git(meetings, "add", "-A")
        self.assertEqual(0, self.commit_in(meetings).returncode)
        self.bad_page(self.people)
        git(meetings, "add", "-A")
        res = self.commit_in(meetings)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("pat-newcomer.md", res.stderr)

    def test_a_hook_that_finds_no_workspace_refuses_the_commit(self):
        hook = garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root / "nowhere")
        shutil.rmtree(str(self.root / "System" / "tools"))
        write(self.wikis / "note.md", "x\n")
        git(self.wikis, "add", "-A")
        res = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(self.wikis), env=dict(GIT_ENV),
                             capture_output=True, text=True)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("no workspace found", res.stderr)
        self.assertTrue(hook.is_file())

    def hooks_path_findings(self):
        return [f for f in check.run_checks(self.root) if f.check == "hooks" and f.path == "Wikis"]

    def test_a_shared_hooks_folder_with_the_zones_hook_is_warned_for_a_wiki_and_with_its_own_is_not(self):
        shared = Path(self._tmp.name).resolve() / "hooks"
        shared.mkdir()
        git(self.wikis, "config", "core.hooksPath", str(shared))
        (shared / "pre-commit").write_text(garrick_lib.WALL_HOOK)
        (shared / "pre-commit").chmod(0o755)
        found = self.hooks_path_findings()
        self.assertEqual(1, len(found))
        self.assertIn("zone's", found[0].message)
        (shared / "pre-commit").write_text(garrick_lib.wiki_hook_text(self.root))
        self.assertEqual([], self.hooks_path_findings())


class InstallerWikiHookTest(unittest.TestCase):
    def test_a_pre_commit_hook_that_is_not_garricks_is_left_and_said_and_the_install_goes_on(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("garrick_install_340", str(Path(__file__).resolve().parent.parent / "install.py"))
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "Wikis" / ".git" / "hooks").mkdir(parents=True)
            hook = root / "Wikis" / ".git" / "hooks" / "pre-commit"
            hook.write_text("#!/bin/sh\necho mine\n")
            said = installer.wiki_hook(root)
            self.assertIn("not Garrick's", said)
            self.assertEqual("#!/bin/sh\necho mine\n", hook.read_text())
            hook.unlink()
            self.assertEqual("", installer.wiki_hook(root))
            self.assertIn("Garrick wall check", hook.read_text())


def shlex_quote(path) -> str:
    import shlex
    return shlex.quote(str(path))


# ---------------------------------------------------------------------------
# 3, 4, 5, 6. The hook's reading of entity pages, tables and person pages
# ---------------------------------------------------------------------------


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class HookTest(EmployerWorkspace):
    def setUp(self):
        super().setUp()
        self.wikis = self.root / "Wikis"
        git(self.wikis, "init", "-q")

    def commit(self):
        git(self.wikis, "add", "-A")
        git(self.wikis, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")

    def staged(self, repo=None, add=True):
        if repo is None:
            repo = self.wikis
            if add:
                git(repo, "add", "-A")
        return sorted((f.severity, f.check, f.path) for f in check.run_checks(self.root, walls_only=True, staged=repo))

    def refused(self, *names):
        return [("error", "walls", "Wikis/Meetings/wiki/people/%s.md" % n) for n in names]

    # 3. The entity index is the staged tree's

    def test_a_staged_delete_of_an_entity_page_leaves_no_link_dangling_unread(self):
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner.", "[[wiki/entities/larch-partners]]"))
        self.commit()
        git(self.wikis, "rm", "-q", str(self.entities / "larch-partners.md"))
        self.assertEqual(self.refused("theo-marsh"), self.staged())

    def test_a_staged_rename_of_an_entity_page_leaves_no_link_dangling_unread(self):
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner.", "[[wiki/entities/larch-partners]]"))
        self.commit()
        git(self.wikis, "mv", str(self.entities / "larch-partners.md"), str(self.entities / "larch-and-sons.md"))
        self.assertEqual(self.refused("theo-marsh"), self.staged())

    def test_moving_the_link_with_the_page_is_fine(self):
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner.", "[[wiki/entities/larch-partners]]"))
        self.commit()
        git(self.wikis, "mv", str(self.entities / "larch-partners.md"), str(self.entities / "larch-and-sons.md"))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner.", "[[wiki/entities/larch-and-sons]]"))
        self.assertEqual([], self.staged())

    def test_an_entity_page_staged_and_then_deleted_from_disk_is_still_read(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer.", "[[wiki/entities/acme-corp]]"))
        self.commit()
        write(self.entities / "acme-ltd.md", entity("Acme Corp", "birch"))      # a namesake of a walled party
        git(self.wikis, "add", "-A")
        (self.entities / "acme-ltd.md").unlink()                                   # staged, not on disk
        self.assertEqual(self.refused("pat-newcomer"), self.staged(add=False))

    # 4. The People and Parties tables

    def table_repo(self):
        git(self.root, "init", "-q")
        git(self.root, "add", "System/context.md", "System/rules.md")
        git(self.root, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "-m", "start")

    def test_a_second_walled_row_for_a_person_with_an_employer_link_is_read_in_the_root_commit(self):
        context = self.root / "System" / "context.md"
        write(context, CONTEXT.replace("| Theo Marsh | `birch` | Managing partner |",
                                       "| Theo Marsh | `birch` | Managing partner |\n| Kit Avery | `birch` | Architect |"))
        write(self.people / "kit-avery.md", person("Kit Avery", "birch", "Architect.", "[[wiki/entities/birch-co]]"))
        self.table_repo()
        write(context, context.read_text(encoding="utf-8").replace("| Kit Avery | `birch` | Architect |",
                                                                    "| Kit Avery | `birch` | Architect |\n"
                                                                    "| Kit Avery | `acme` | Architect |"))
        git(self.root, "add", "System/context.md")
        self.assertEqual(self.refused("kit-avery"), self.staged(self.root))

    def test_a_table_change_that_crosses_nothing_commits(self):
        self.table_repo()
        context = self.root / "System" / "context.md"
        write(context, context.read_text(encoding="utf-8") + "\n")
        git(self.root, "add", "System/context.md")
        self.assertEqual([], self.staged(self.root))

    def test_a_table_staged_differently_from_the_disk_is_refused(self):
        self.table_repo()
        context = self.root / "System" / "context.md"
        write(context, context.read_text(encoding="utf-8") + "\nstaged\n")
        git(self.root, "add", "System/context.md")
        write(context, context.read_text(encoding="utf-8") + "\nnot staged\n")
        self.assertEqual([("error", "walls", "System/context.md")], self.staged(self.root))

    # 5. A short form of a two-hat name

    SHORT = ("Blake", "Ro Blake", "Row Blake", "Blake, Ro", "R. Blake", "Blake Rowan", "Mr Blake", "Dr Blake",
             "Rowan Blake (Birch)", "Rowan Blake / Acme", "Blake (Acme)", "Blake Rowan Jr", "Kjaer Soren", "Kjær S.",
             "BLAKE", "rowan_blake", "Theo Blake", "Ronald Blake", "Rowan Blake-Smith")

    def test_a_page_sharing_a_surname_word_with_a_two_hat_person_meets_them(self):
        for name in self.SHORT:
            self.assertEqual({"acme", "birch"}, garrick_lib.people_parties(self.context, (name, name.lower())), name)
        for name in ("Dana Whitlock", "Dana Smith", "Rowan Blaek", "Blakely"):
            self.assertNotEqual({"acme", "birch"}, garrick_lib.people_parties(self.context, (name,)), name)

    def test_another_row_of_the_table_exactly_is_not_asked_about(self):
        context = dict(self.context)
        context["people"] = self.context["people"] + [{"name": "Theo Blake", "party": "`birch`", "role": "Buyer"}]
        self.assertEqual({"birch"}, garrick_lib.people_parties(context, ("Theo Blake",)))

    def test_no_link_is_proposed_to_such_a_page(self):
        for name in self.SHORT:
            self.assertEqual("", garrick_lib.organisation_link(self.root, self.context, name, "acme"), name)
            text = person(name, "acme", "Buyer.")
            self.assertEqual(("", []), garrick_lib.organisation_proposal(self.root, self.context, (name,), "acme", text))

    def test_such_a_page_is_asked_about(self):
        write(self.people / "ro-blake.md", person("Ro Blake", "acme", "Buyer."))
        write(self.people / "mr-blake.md", person("Mr Blake", "acme", "Buyer."))
        write(self.people / "dana-smith.md", person("Dana Smith", "acme", "Buyer."))
        found = {f.path: f for f in check.run_checks(self.root) if f.check == "people"}
        for slug in ("ro-blake", "mr-blake"):
            self.assertIn("short form", found["Wikis/Meetings/wiki/people/%s.md" % slug].message)
        self.assertNotIn("short form", found["Wikis/Meetings/wiki/people/dana-smith.md"].message)

    def test_the_hook_refuses_a_link_on_such_a_page(self):
        write(self.people / "blake.md", person("Blake", "none", "Buyer.", "[[wiki/entities/larch-partners]]"))
        write(self.people / "ro-blake.md", person("Ro Blake", "acme", "Buyer.", "[[wiki/entities/acme-corp]]"))
        write(self.people / "mr-blake.md", person("Blake Rowan Jr", "acme", "Buyer.", "[[wiki/entities/acme-corp]]"))
        write(self.people / "kjaer.md", person("Kjær S.", "none", "Engineer.", "[[wiki/entities/larch-partners]]"))
        self.assertEqual(self.refused("blake", "kjaer", "mr-blake", "ro-blake"), self.staged())

    # 6. Other keys, and links in the text

    def test_a_key_the_schema_does_not_have_is_refused(self):
        for i, line in enumerate(('company: "[[wiki/entities/birch-co]]"\n', 'employer: [[wiki/entities/birch-co]]\n',
                                  "aliases: [Pat]\n", "employer: Birch\n", "tags: []\n")):
            text = person("Pat Newcomer", "acme", "Buyer.").replace("created:", line + "created:")
            write(self.people / ("pat-%d.md" % i), text)
        self.assertEqual(self.refused(*("pat-%d" % i for i in range(5))), self.staged())

    def test_a_link_in_a_value_other_than_organisation_is_refused(self):
        write(self.people / "pat-newcomer.md",
              person("Pat Newcomer", "acme", "Buyer.").replace("title: Pat Newcomer", 'title: "[[wiki/entities/birch-co]]"'))
        write(self.people / "kit-avery.md", person("Kit Avery", "acme", "Buyer.").replace("type: person", "type: [[x]]"))
        self.assertEqual(self.refused("kit-avery", "pat-newcomer"), self.staged())

    def test_the_schemas_keys_alone_pass(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer.", "[[wiki/entities/acme-corp]]"))
        self.assertEqual([], self.staged())

    IN_THE_TEXT = (
        "[[wiki/entities/birch-co]]", "[[wiki/entities/birch-co|Birch]]", "[[wiki/entities/birch-co#h]]", "[[birch-co]]",
        "[[Birch-Co]]", "[[birch-co|x]]", "[[birch-co#h]]",
    )
    NOT_PLAIN = (
        "[[../entities/birch-co]]", "[[./birch-co]]", "[[entities/birch-co]]", "[[wiki/birch-co]]", "[[birch-co.md]]",
        "[[birch-co.md|x]]", "[B](../entities/birch-co.md)", "[a [b]](wiki/entities/birch-co.md)",
        '[a](wiki/entities/birch-co.md "t (x)")', "[a](wiki/entities/birch-co.md#(x))",
        '[a](<wiki/entities/birch-co.md> "t")', "[B][1]\n\n[1]: wiki/entities/birch-co.md",
        '<a href="wiki/entities/birch-co.md">B</a>', "<wiki/entities/birch-co.md>", "![B](wiki/entities/birch-co.md)",
        "![[wiki/entities/birch-co.md]]", "[[wiki/entities/\nbirch-co]]", "[[a|[[wiki/entities/birch-co]]]]",
        "[a](obsidian://open?vault=Wikis&file=Meetings%2Fwiki%2Fentities%2Fbirch-co)", "[[Birch and Co]]",
        "[[wiki/entities/birch-co]]]]", "[[ wiki/entities/birch-co ]]", "<img src=x>",
    )

    def test_a_link_to_a_walled_entity_page_in_the_text_is_refused(self):
        for i, link in enumerate(self.IN_THE_TEXT):
            write(self.people / ("pat-%d.md" % i), person("Pat Newcomer", "acme", "Buyer, met at %s." % link,
                                                          "[[wiki/entities/acme-corp]]"))
        names = ["pat-%d" % i for i in range(len(self.IN_THE_TEXT))]
        self.assertEqual(self.refused(*sorted(names)), self.staged())
        self.assertEqual(sorted("Wikis/Meetings/wiki/people/%s.md" % n for n in names),
                         sorted(f.path for f in check.run_checks(self.root) if f.check == "walls"))

    def test_a_link_in_any_form_but_the_plain_one_is_refused_in_the_hook_and_the_full_check(self):
        for i, link in enumerate(self.NOT_PLAIN):
            write(self.people / ("pat-%d.md" % i), person("Pat Newcomer", "acme", "Buyer, met at %s." % link,
                                                          "[[wiki/entities/acme-corp]]"))
        names = ["pat-%d" % i for i in range(len(self.NOT_PLAIN))]
        self.assertEqual(self.refused(*sorted(names)), self.staged())
        full = [f for f in check.run_checks(self.root) if f.check == "walls"]
        self.assertEqual(sorted("Wikis/Meetings/wiki/people/%s.md" % n for n in names), sorted(f.path for f in full))
        self.assertIn("[[wiki/<folder>/<name>]]", full[0].message)

    def test_plain_links_to_pages_that_are_there_pass(self):
        write(self.people / "kit-avery.md", person("Kit Avery", "none", "Colleague of [[theo-marsh|Theo]].", ""))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch", "Partner at [[wiki/entities/birch-co#h]]."))
        write(self.people / "pat-newcomer.md",
              person("Pat Newcomer", "acme", "Buyer at [[acme-corp]] and [[wiki/entities/acme-corp|Acme]].",
                     "[[wiki/entities/acme-corp]]"))
        self.assertEqual([], self.staged())

    def test_ordinary_prose_that_looks_like_a_link_is_refused_saying_what_and_how(self):
        for prose in ("[LinkedIn](https://www.example.com/in/pat)", "<pat@acme.example>", "x<y and y>z",
                      "Buyer [EMEA]: Italy", "Buyer <not sure>"):
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", prose, "[[wiki/entities/acme-corp]]"))
            git(self.wikis, "add", "-A")
            found = [f for f in check.run_checks(self.root, walls_only=True, staged=self.wikis)]
            self.assertEqual(1, len(found), prose)
            self.assertIn("holds `", found[0].message)
            start = min(i for i in (prose.find("["), prose.find("<")) if i >= 0)
            self.assertIn(prose[start:start + 5], found[0].message)
            self.assertIn("web address bare", found[0].message)

    def test_an_alias_or_heading_that_could_start_another_link_is_not_plain(self):
        for link in ('[[wiki/entities/acme-corp|<a href="wiki/entities/birch-co.md">x</a>]]',
                     "[[wiki/entities/acme-corp|obsidian://open?file=birch-co]]",
                     "[[wiki/entities/acme-corp|<wiki/entities/birch-co.md>]]",
                     '[[wiki/entities/acme-corp#<a href="x">h</a>]]', "[[wiki/entities/acme-corp|x](wiki/entities/birch-co.md)",
                     "[[wiki/entities/acme-corp|see (this)]]", "[[wiki/entities/acme-corp|https://example.com]]"):
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer, %s." % link))
            self.assertEqual(self.refused("pat-newcomer"), self.staged(), link)

    def test_a_bare_name_is_read_against_every_page_of_that_name_dormant_and_archived_too(self):
        (self.entities / "birch-co.md").unlink()
        write(self.meetings / "wiki" / "topics" / "birch-co.md", "---\ntitle: x\ntype: topic\n---\nhi\n")
        for grade in ("dormant", "archive"):
            page = self.meetings / grade / "wiki" / "entities" / "birch-co.md"
            write(page, entity("Birch & Co", "birch"))
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[birch-co]]."))
            self.assertEqual(self.refused("pat-newcomer"), self.staged(), grade)
            page.unlink()

    def test_what_fade_writes_into_a_person_page_is_plain_and_wall_checked(self):
        fade = _load("garrick_fade_340", TOOLS / "fade.py")
        text = person("Pat Newcomer", "acme", "Buyer at [[acme-corp]] and, once, [[wiki/entities/birch-co]] and "
                      "[[260310-acme-kickoff]].")
        links = fade.Links(self.root)
        for slug in ("acme-corp", "birch-co"):
            old = self.entities / (slug + ".md")
            new = self.meetings / "dormant" / "wiki" / "entities" / (slug + ".md")
            new.parent.mkdir(parents=True, exist_ok=True)
            os.rename(str(old), str(new))
        moved = {"Wikis/Meetings/wiki/entities/%s.md" % s_: "Wikis/Meetings/dormant/wiki/entities/%s.md" % s_
                 for s_ in ("acme-corp", "birch-co")}
        out = fade.relink(text, moved, links, "Wikis/Meetings/wiki/people/pat-newcomer.md")
        self.assertIn("[[dormant/wiki/entities/acme-corp|", out)
        pages, problem = check.text_entity_pages(check.discover(self.root), out)
        self.assertEqual("", problem)
        self.assertEqual(2, len(pages))
        write(self.people / "pat-newcomer.md", out)
        self.assertEqual(self.refused("pat-newcomer"), self.staged())      # the Birch link is across the wall
        clean = fade.relink(text.replace("once, [[wiki/entities/birch-co]] and ", ""), moved, links,
                            "Wikis/Meetings/wiki/people/pat-newcomer.md")
        self.assertNotIn("birch", clean)
        write(self.people / "pat-newcomer.md", clean)
        self.assertEqual([], self.staged())

    def test_a_change_under_a_dormant_or_archived_entity_folder_reads_the_people(self):
        for grade in ("dormant", "archive"):
            page = self.meetings / grade / "wiki" / "entities" / "old-acme.md"
            write(page, entity("Old Acme", "acme"))
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[%s/wiki/entities/old-acme]]." % grade,
                                                          "[[wiki/entities/acme-corp]]"))
            self.commit()
            write(page, entity("Old Acme", "birch"))                       # edited in place, the person page untouched
            self.assertEqual(self.refused("pat-newcomer"), self.staged(), grade)
            git(self.wikis, "reset", "-q", "--hard")
            write(self.meetings / grade / "wiki" / "entities" / "acme-corp.md", entity("Acme Corp", "birch"))
            write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[acme-corp]].",
                                                          "[[wiki/entities/acme-corp]]"))
            self.assertEqual(self.refused("pat-newcomer"), self.staged(), grade + " same name")
            git(self.wikis, "reset", "-q", "--hard")
            git(self.wikis, "clean", "-fdq")

    def test_person_pages_under_dormant_and_archive_are_wall_checked(self):
        for grade in ("dormant", "archive"):
            write(self.meetings / grade / "wiki" / "people" / "pat-two.md",
                  person("Pat Two", "acme", "Buyer at [[wiki/entities/birch-co]].", "[[wiki/entities/acme-corp]]"))
            write(self.meetings / grade / "wiki" / "people" / "pat-three.md",
                  person("Pat Three", "acme", "Buyer.", "[[wiki/entities/birch-co]]"))
        names = sorted("Wikis/Meetings/%s/wiki/people/%s.md" % (g, n) for g in ("dormant", "archive")
                       for n in ("pat-two", "pat-three"))
        self.assertEqual(names, sorted(f.path for f in check.run_checks(self.root) if f.check == "walls"))
        self.assertEqual(names, sorted(x[2] for x in self.staged()))

    def test_fade_never_moves_an_entity_or_person_page(self):
        import datetime
        fade = _load("garrick_fade_340b", TOOLS / "fade.py")
        write(self.entities / "old-acme.md", entity("Old Acme", "acme").replace("---\n\n", "updated: 2019-01-01\n---\n\n", 1))
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer.").replace("2026-03-10", "2019-01-01"))
        plans = fade.plan(self.root, today=datetime.date(2035, 1, 1), wikis=["Meetings"])
        subs = [m.page.sub for m in plans["Meetings"].moves]
        self.assertFalse([x for x in subs if "/entities/" in x or "/people/" in x], subs)
        fixed = {p.sub: p.fixed for p in plans["Meetings"].pages}
        self.assertTrue(fixed.get("wiki/entities/old-acme.md") and fixed.get("wiki/people/pat-newcomer.md"), fixed)

    def test_a_link_in_the_text_to_a_page_that_is_not_there_is_refused(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[wiki/entities/nowhere]]."))
        self.assertEqual(self.refused("pat-newcomer"), self.staged())

    def test_a_link_in_the_text_to_the_persons_own_entity_page_passes(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[wiki/entities/acme-corp]] and [[acme-corp]]."))
        self.assertEqual([], self.staged())

    def test_staging_an_entity_page_reads_the_people_who_link_it_in_their_text(self):
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Buyer at [[acme-corp]]."))
        self.commit()
        write(self.entities / "acme-corp.md", entity("Acme Corp", "birch"))
        self.assertEqual(self.refused("pat-newcomer"), self.staged())


if __name__ == "__main__":
    unittest.main()
