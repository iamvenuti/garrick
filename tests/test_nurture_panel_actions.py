"""The Questions panel's Nurture answers (#224, point 9): page_action.py's
nurture-answer, nurture-organisation, nurture-correct and nurture-save. They
call nurture.py's own code, run in the one transaction, and commit once per
repository after the walls check on what is staged.

    cd tests && python3 -m unittest test_nurture_panel_actions
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import fixtures  # noqa: E402
from fixtures import git, write  # noqa: E402
from test_page_action import ActionCase, TODAY, pa  # noqa: E402
from test_person_organisation import CONTEXT, entity, person  # noqa: E402

SENTENCE = "A wall holds some material back from this project, so I have not used it. Nothing was written."
TOOLS = Path(__file__).resolve().parent.parent / "template" / "System" / "tools"


def commit_all(repo: Path, message: str = "start") -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-qm", message)


def snap(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.parts and "generated" not in p.parts}


class PanelCase(ActionCase):
    """Work holds Acme, Birch and Cedar; the Meetings wiki is its own repository."""

    def setUp(self):
        super().setUp()
        for f in TOOLS.glob("*.py"):
            shutil.copy2(f, self.root / "System" / "tools" / f.name)
        write(self.root / "System" / "context.md", CONTEXT)
        self.meetings = self.root / "Wikis" / "Meetings"
        self.people = self.meetings / "wiki" / "people"
        self.entities = self.meetings / "wiki" / "entities"
        write(self.entities / "acme-corp.md", entity("acme"))
        write(self.entities / "birch-co.md", entity("birch", "Birch & Co"))
        write(self.entities / "harbour-ltd.md", entity("", "Harbour Ltd"))
        write(self.people / "mira-holt.md", person("Mira Holt", "acme"))
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch"))
        shutil.rmtree(self.meetings / ".git", ignore_errors=True)
        git(self.meetings, "init", "-q")
        git(self.meetings, "config", "maintenance.auto", "false")
        git(self.meetings, "config", "gc.auto", "0")
        commit_all(self.meetings)

    def save(self, rows, zone="Work", scope="acme"):
        return pa.act(self.root, dict(verb="nurture-save", zone=zone, scope=scope, rows=rows), today=TODAY)

    def org(self, name, **kw):
        return dict({"do": "organisation", "path": "Wikis/Meetings/wiki/people/%s.md" % name, "choice": "yes"}, **kw)

    def report(self):
        return next(p for p in (self.root / "System" / "generated" / "nurture").glob("*.json") if p.stem[:2] == "20")

    def head(self, repo=None):
        return git(repo or self.meetings, "log", "--format=%s").strip().splitlines()


class TestSingleActions(PanelCase):
    def test_organisation_writes_the_link_and_commits_that_page_alone(self):
        before = snap(self.root)
        say = pa.act(self.root, dict(verb="nurture-organisation", zone="Work", scope="acme",
                                     path="Wikis/Meetings/wiki/people/mira-holt.md"), today=TODAY)
        self.assertEqual("Where they work: written", say)
        self.assertIn('organisation: "[[wiki/entities/acme-corp]]"', (self.people / "mira-holt.md").read_text())
        changed = [k for k in snap(self.root) if snap(self.root)[k] != before.get(k)]
        self.assertEqual(["Wikis/Meetings/wiki/people/mira-holt.md"], changed)
        self.assertEqual(2, len(self.head()))
        self.assertEqual("", git(self.meetings, "status", "--porcelain").strip())

    def test_the_day_report_records_it_as_the_chat_path_does(self):
        pa.act(self.root, dict(verb="nurture-organisation", zone="Work", scope="acme",
                               path="Wikis/Meetings/wiki/people/mira-holt.md"), today=TODAY)
        rec = json.loads(self.report().read_text())
        self.assertEqual([{"path": "Wikis/Meetings/wiki/people/mira-holt.md",
                           "asked": "Does Mira Holt work at Acme Corp? (yes / no / another page)", "answer": "yes"}],
                         rec["answered"])

    def test_answer_gives_an_entity_page_its_party(self):
        say = pa.act(self.root, dict(verb="nurture-answer", zone=pa.UNATTRIBUTED, scope="Work", path="Wikis/Meetings/wiki/entities/harbour-ltd.md",
                                     party="none"), today=TODAY)
        self.assertEqual("Whose it is: none", say)
        self.assertIn("type: entity\nparty: none\n", (self.entities / "harbour-ltd.md").read_text())

    def test_answer_refuses_a_page_that_says_whose_it_is_and_a_party_nobody_knows(self):
        before = snap(self.root)
        for path, party in (("acme-corp", "none"), ("harbour-ltd", "zzz")):
            with self.assertRaises(pa.Refused):
                pa.act(self.root, dict(verb="nurture-answer", zone=pa.UNATTRIBUTED, scope="Work",
                                       path="Wikis/Meetings/wiki/entities/%s.md" % path, party=party), today=TODAY)
        self.assertEqual(before, snap(self.root))

    def test_correct_changes_every_live_copy_in_one_commit_and_records_it(self):
        say = pa.act(self.root, dict(verb="nurture-correct", zone="Work", scope="acme",
                                     path="Wikis/Meetings/wiki/people/mira-holt.md", old="Mira Holt", new="Mira Holte"),
                     today=TODAY)
        self.assertIn("Corrected", say)
        self.assertIn("Mira Holte", (self.people / "mira-holt.md").read_text())
        self.assertEqual("", git(self.meetings, "status", "--porcelain").strip())
        self.assertEqual(2, len(self.head()))
        rec = json.loads(self.report().read_text())
        self.assertTrue(any("Mira Holte" in f["line"] for f in rec["fixed"]))


class TestSave(PanelCase):
    def many(self, n=30):
        names = []
        for i in range(n):
            name = "pat-%02d" % i
            write(self.people / (name + ".md"), person("Pat Number%02d" % i, "acme"))
            names.append(name)
        commit_all(self.meetings, "pages")
        return names

    def test_thirty_findings_save_as_one_commit_per_repository(self):
        names = self.many(30)
        hub = self.work / "Acme Review" / "Acme Review.md"
        hub.write_text(hub.read_text() + "\nMira Holt joined the call.\n")
        commit_all(self.work, "note")
        rows = [self.org(n) for n in names]
        rows[0]["edit"] = {"old": "Mira Holt", "new": "Mira Holte"}
        rows[0]["path"] = "Wikis/Meetings/wiki/people/mira-holt.md"
        rows[0]["do"] = "organisation"
        wiki_before, work_before = len(self.head()), len(self.head(self.work))
        out = self.save(rows)
        self.assertEqual("Saved 30 answers", out["say"])
        self.assertTrue(all(r["ok"] for r in out["rows"]))
        self.assertEqual(wiki_before + 1, len(self.head()))
        self.assertEqual(work_before + 1, len(self.head(self.work)))
        for n in names[1:]:
            self.assertIn('organisation: "[[wiki/entities/acme-corp]]"', (self.people / (n + ".md")).read_text())
        self.assertIn("Mira Holte", hub.read_text())
        self.assertEqual("", git(self.meetings, "status", "--porcelain").strip())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        rec = json.loads(self.report().read_text())
        self.assertGreaterEqual(len(rec["answered"]), 30)

    def test_a_count_made_worse_leaves_every_file_and_commits_nothing(self):
        names = self.many(3)
        before, wiki_log = snap(self.root), self.head()
        with mock.patch.object(pa, "check_counts", side_effect=[{"check:warning": 1}, {"check:warning": 2}]):
            with self.assertRaisesRegex(pa.Refused, "got worse.*back as it was"):
                self.save([self.org(n) for n in names])
        self.assertEqual(before, snap(self.root))
        self.assertEqual(wiki_log, self.head())
        self.assertFalse((self.root / "System" / "generated" / "nurture").exists())

    def test_a_row_across_a_wall_is_refused_with_the_sentence_and_the_rest_go_through(self):
        out = self.save([self.org("mira-holt"), self.org("theo-marsh")])      # Theo is Birch's, the view is Acme's
        by = {r["index"]: r for r in out["rows"]}
        self.assertTrue(by[0]["ok"])
        self.assertEqual({"key": None, "ok": False, "say": SENTENCE, "index": 1}, by[1])
        self.assertIn("organisation:", (self.people / "mira-holt.md").read_text())
        self.assertNotIn("organisation:", (self.people / "theo-marsh.md").read_text())
        self.assertEqual(2, len(self.head()))

    def test_a_pick_on_the_far_side_is_the_same_sentence_as_one_that_is_not_there(self):
        for pick in ("Birch & Co", "birch-co", "No Such Place"):
            out = self.save([self.org("mira-holt", choice="another", pick=pick)])
            self.assertEqual([SENTENCE], [r["say"] for r in out["rows"]])
        self.assertNotIn("organisation:", (self.people / "mira-holt.md").read_text())

    def test_the_walls_check_on_what_is_staged_puts_back_the_row_it_refuses(self):
        write(self.people / "jo-lee.md", person("Jo Lee", "acme"))
        commit_all(self.meetings, "jo")
        real = pa.walls_on_staged

        def refuse_jo(ws, repo, rels):
            return ("the walls check refused it (walls: Wikis/Meetings/wiki/people/jo-lee.md)"
                    if any(r.endswith("jo-lee.md") for r in rels) else real(ws, repo, rels))
        before = (self.people / "jo-lee.md").read_bytes()
        with mock.patch.object(pa, "walls_on_staged", refuse_jo):
            out = self.save([self.org("mira-holt"), self.org("jo-lee")])
        by = {r["index"]: r for r in out["rows"]}
        self.assertTrue(by[0]["ok"], out)
        self.assertEqual(before, (self.people / "jo-lee.md").read_bytes())
        self.assertEqual(SENTENCE, by[1]["say"])
        self.assertIn("organisation:", (self.people / "mira-holt.md").read_text())
        self.assertEqual(3, len(self.head()))

    def test_edit_corrects_a_value_across_scope_but_never_copies_on_the_far_side(self):
        write(self.people / "theo-marsh.md", person("Theo Marsh", "birch").replace("Someone", "Mira Holt, and someone"))
        commit_all(self.meetings, "theo")
        out = self.save([self.org("mira-holt", edit={"old": "Mira Holt", "new": "Mira Holte"})])
        self.assertTrue(out["rows"][0]["ok"], out)
        self.assertIn("Mira Holte", (self.people / "mira-holt.md").read_text())
        self.assertIn("Mira Holt,", (self.people / "theo-marsh.md").read_text())      # the far side is left as it is

    def test_an_entity_page_is_answered_in_the_unattributed_view_only(self):
        row = {"do": "answer", "path": "Wikis/Meetings/wiki/entities/harbour-ltd.md", "choice": "another", "pick": "none"}
        out = self.save([row], zone="Work", scope="acme")
        self.assertEqual(SENTENCE, out["rows"][0]["say"])
        out = self.save([row], zone=pa.UNATTRIBUTED, scope="Work")
        self.assertTrue(out["rows"][0]["ok"], out)

    def test_an_edit_runs_with_a_row_that_is_put_off(self):
        out = self.save([self.org("mira-holt", choice="later", until="2026-11-20", key="aaaaaaaaaaaa",
                                  edit={"old": "Mira Holt", "new": "Mira Holte"})])
        self.assertTrue(out["rows"][0]["ok"], out)
        self.assertIn("Mira Holte", (self.people / "mira-holt.md").read_text())
        self.assertNotIn("organisation:", (self.people / "mira-holt.md").read_text())
        self.assertEqual({"aaaaaaaaaaaa": "2026-11-20"}, pa.read_later(self.root))

    def test_an_entity_page_takes_only_a_party_of_the_zone_chosen(self):
        write(self.root / "System" / "context.md", CONTEXT.replace("| Cedar Ltd | Supplier to Acme | Work |", "| Cedar Ltd | Supplier to Acme | Personal |"))
        row = {"do": "answer", "path": "Wikis/Meetings/wiki/entities/harbour-ltd.md", "choice": "another", "pick": "cedar"}
        out = self.save([row], zone=pa.UNATTRIBUTED, scope="Work")
        self.assertEqual(SENTENCE, out["rows"][0]["say"])
        self.assertNotIn("party:", (self.entities / "harbour-ltd.md").read_text())

    def test_a_view_whose_zone_holds_walled_parties_needs_a_party(self):
        with self.assertRaisesRegex(pa.Refused, "^A wall holds"):
            self.save([self.org("mira-holt")], scope=None)
        with self.assertRaisesRegex(pa.Refused, "^A wall holds"):
            self.save([self.org("mira-holt")], zone="Nowhere")
        with self.assertRaisesRegex(pa.Refused, "^A wall holds"):
            self.save([self.org("mira-holt")], scope="personal")

    def test_a_page_with_changes_not_committed_is_not_swept_into_the_commit(self):
        (self.people / "mira-holt.md").write_text((self.people / "mira-holt.md").read_text() + "\nA note by hand.\n")
        out = self.save([self.org("mira-holt")])
        self.assertFalse(out["rows"][0]["ok"])
        self.assertIn("A note by hand.", (self.people / "mira-holt.md").read_text())
        self.assertEqual(1, len(self.head()))

    def test_an_answers_text_is_data(self):
        # Neither a pick nor an edit is a path to open or a command: odd values are refused or written as plain text.
        for bad in ("../../../etc/passwd", "$(touch /tmp/x); `id`"):
            out = self.save([self.org("mira-holt", choice="another", pick=bad)])
            self.assertEqual([SENTENCE], [r["say"] for r in out["rows"]])
        with self.assertRaises(pa.Refused):
            self.save([self.org("mira-holt", choice="another", pick="x" * 500)])
        for bad in ("a\nparty: birch", "a\x00b", "x" * 300):
            with self.assertRaises(pa.Refused):
                self.save([self.org("mira-holt", edit={"old": "Mira", "new": bad})])
        for extra in ({"x": 1}, {"do": "rm"}, {"choice": "all"}):
            with self.assertRaises(pa.Refused):
                self.save([dict(self.org("mira-holt"), **extra)])
        self.assertNotIn("organisation:", (self.people / "mira-holt.md").read_text())

    def test_later_and_no_write_nothing_to_the_pages(self):
        before = snap(self.root)
        out = self.save([self.org("mira-holt", choice="no", key="aaaaaaaaaaaa"),
                         self.org("mira-holt", choice="later", until="2026-11-20", key="bbbbbbbbbbbb")])
        self.assertTrue(all(r["ok"] for r in out["rows"]))
        self.assertEqual(before, snap(self.root))
        self.assertEqual({"bbbbbbbbbbbb": "2026-11-20"}, pa.read_later(self.root))
        out = self.save([self.org("mira-holt", choice="later", until="2026-01-01", key="cccccccccccc")])
        self.assertFalse(out["rows"][0]["ok"])
        self.assertIn("not a later day", out["rows"][0]["say"])


if __name__ == "__main__":
    unittest.main()
