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

    def test_a_surname_alone_or_a_cut_short_first_name_meets_a_two_hat_person(self):
        for name in ("Blake", "Ro Blake", "Row Blake", "Blake, Ro", "R. Blake"):
            self.assertEqual({"acme", "birch"}, garrick_lib.people_parties(self.context, (name, name.lower())), name)
        for name in ("Theo Blake", "Ronald Blake", "Rowan Blakely", "Dana Whitlock"):
            self.assertNotEqual({"acme", "birch"}, garrick_lib.people_parties(self.context, (name,)), name)

    def test_no_link_is_proposed_to_such_a_page(self):
        for name in ("Blake", "Ro Blake"):
            self.assertEqual("", garrick_lib.organisation_link(self.root, self.context, name, "acme"), name)
            text = person(name, "acme", "Buyer.")
            self.assertEqual(("", []), garrick_lib.organisation_proposal(self.root, self.context, (name,), "acme", text))
        self.assertEqual("[[wiki/entities/acme-corp]]",
                         garrick_lib.organisation_link(self.root, self.context, "Ronald Blake", "acme"))

    def test_such_a_page_is_asked_about(self):
        write(self.people / "ro-blake.md", person("Ro Blake", "acme", "Buyer."))
        write(self.people / "ronald-blake.md", person("Ronald Blake", "acme", "Buyer."))
        found = {f.path: f for f in check.run_checks(self.root) if f.check == "people" and "blake" in f.path}
        self.assertIn("short form", found["Wikis/Meetings/wiki/people/ro-blake.md"].message)
        self.assertIn("link", found["Wikis/Meetings/wiki/people/ronald-blake.md"].message)
        self.assertNotIn("short form", found["Wikis/Meetings/wiki/people/ronald-blake.md"].message)

    def test_the_hook_refuses_a_link_on_such_a_page(self):
        write(self.people / "blake.md", person("Blake", "none", "Buyer.", "[[wiki/entities/larch-partners]]"))
        write(self.people / "ro-blake.md", person("Ro Blake", "acme", "Buyer.", "[[wiki/entities/acme-corp]]"))
        self.assertEqual(self.refused("blake", "ro-blake"), self.staged())

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

    def test_a_link_to_a_walled_entity_page_in_the_text_is_refused(self):
        for i, link in enumerate(("[[wiki/entities/birch-co]]", "[[wiki/entities/birch-co|Birch]]", "[[birch-co]]",
                                  "[Birch](wiki/entities/birch-co.md)", "[[Birch and Co]]")):
            write(self.people / ("pat-%d.md" % i), person("Pat Newcomer", "acme", "Buyer, met at %s." % link,
                                                          "[[wiki/entities/acme-corp]]"))
        found = self.staged()
        self.assertEqual(self.refused(*("pat-%d" % i for i in range(5))), found)
        self.assertEqual(["Wikis/Meetings/wiki/people/pat-%d.md" % i for i in range(5)],
                         sorted(f.path for f in check.run_checks(self.root) if f.check == "walls"))

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
