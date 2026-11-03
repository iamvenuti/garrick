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
        self.assertNotIn("the wall check is missing", refused.stderr)
        write(self.people / "pat-newcomer.md", person("Pat Newcomer", "acme", "Consultant.", "[[wiki/entities/acme-corp]]"))
        git(elsewhere, "add", "-A")
        passed = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(elsewhere), env=dict(GIT_ENV),
                                capture_output=True, text=True)
        self.assertEqual(0, passed.returncode, passed.stderr)

    def test_a_hook_that_finds_no_workspace_refuses_the_commit(self):
        hook = garrick_lib.install_wall_hook(self.wikis, wiki=True, root=self.root / "nowhere")
        shutil.rmtree(str(self.root / "System" / "tools"))
        write(self.wikis / "note.md", "x\n")
        git(self.wikis, "add", "-A")
        res = subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=str(self.wikis), env=dict(GIT_ENV),
                             capture_output=True, text=True)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("the wall check is missing", res.stderr)
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
