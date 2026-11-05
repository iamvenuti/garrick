"""Ways past the walls the review of the Questions panel found (#224): a count
paid for by a fix elsewhere, wording the quick check does not read, a row
refused but still written, edits that reach beyond the view, a commit that is
partly made, a stored Later that hides another finding.

    cd tests && python3 -m unittest test_panel_hardening
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import git, write  # noqa: E402
from test_nurture_panel_actions import PanelCase, SENTENCE, SaveThroughAll, commit_all, snap  # noqa: E402
from test_page_action import TODAY, pa  # noqa: E402
from test_questions_panel import entity_page, person_page  # noqa: E402

BIRCH_SENTENCE = "Birch will enter the Nordic market in March under the codename Lantern with a budget of four million"


class Hardening(PanelCase):
    def diff(self, before):
        now = snap(self.root)
        return sorted(k for k in set(now) | set(before) if now.get(k) != before.get(k))


class TestCountsAreIdentities(Hardening):
    def test_one_finding_fixed_does_not_pay_for_a_new_one(self):
        # Acme's entity page now cites a Birch meeting: a new wall finding. The row also fixes a warning (the
        # organisation link), so the totals could be equal. The identities are not.
        before = snap(self.root)
        with self.assertRaises(pa.Refused) as ctx:
            out = self.save([self.org("mira-holt", edit={"old": "An organisation", "new": "See [[wiki/sources/260312-birch-kickoff]]"})])
            if not out["rows"][0]["ok"]:
                raise pa.Refused(out["rows"][0]["say"])
        self.assertEqual([], self.diff(before))
        self.assertEqual(2 - 1, len(self.head()))
        self.assertTrue(str(ctx.exception))

    def test_a_new_finding_is_worse_even_when_the_totals_match(self):
        self.assertTrue(pa.worse_counts({"check:warning": {("a", "p", "m1")}}, {"check:warning": {("a", "p", "m2")}}))
        self.assertFalse(pa.worse_counts({"check:warning": {("a", "p", "m1")}}, {"check:warning": set()}))

    def test_the_refusal_says_a_change_elsewhere_can_cause_it(self):
        self.ask_q = None
        with mock.patch.object(pa, "check_counts", side_effect=[{"check:warning": set()}, {"check:warning": {("x", "p", "m")}}, {"check:warning": {("x", "p", "m")}}]):
            with self.assertRaisesRegex(pa.Refused, "something else changed|changed meanwhile"):
                self.save([self.org("mira-holt")])


class TestWordingIsReadInFull(Hardening):
    def test_a_sentence_copied_from_the_far_side_is_not_committed(self):
        birch = self.meetings / "wiki" / "sources" / "260312-birch-kickoff.md"
        birch.write_text(birch.read_text() + "\n" + BIRCH_SENTENCE + ".\n")
        commit_all(self.meetings, "secret")
        before = snap(self.root)
        log = self.head()
        try:
            out = self.save([self.org("mira-holt", choice="no", edit={"old": "Someone at a party", "new": BIRCH_SENTENCE})])
            ok = out["rows"][0]["ok"]
        except pa.Refused:
            ok = False
        self.assertFalse(ok)
        self.assertEqual([], self.diff(before))
        self.assertEqual(log, self.head())


class TestARefusedRowLeavesNothing(Hardening):
    def edit(self, name, old, new, key):
        return dict(do="correct", key=key * 12, path="Wikis/Meetings/wiki/people/%s.md" % name, edit={"old": old, "new": new})

    def test_two_edit_rows_do_not_collide_on_the_index_and_a_refused_one_is_all_back(self):
        real = pa.walls_on_staged

        def fake(ws, repo, rels):
            return "the walls check refused it (walls: x)" if any("dana-whitlock" in r for r in rels) else real(ws, repo, rels)
        before = snap(self.root)
        with mock.patch.object(pa, "walls_on_staged", fake):
            out = self.save([self.edit("mira-holt", "Mira Holt", "Mira Holte", "a"),
                             self.edit("dana-whitlock", "Head of procurement", "Head of buying", "b")])
        by = {r["key"]: r for r in out["rows"]}
        self.assertTrue(by["a" * 12]["ok"], out)
        self.assertEqual(SENTENCE, by["b" * 12]["say"])
        self.assertIn("Mira Holte", (self.people / "mira-holt.md").read_text())
        self.assertIn("Head of procurement", (self.people / "dana-whitlock.md").read_text())
        self.assertEqual("", git(self.meetings, "status", "--porcelain").strip())
        self.assertEqual(2, len(self.head()))
        index = (self.meetings / "wiki" / "index.md").read_text()
        self.assertNotIn("Head of buying", index)

    def test_a_row_reported_as_not_written_is_not_committed_when_it_shares_a_file(self):
        real = pa.walls_on_staged

        def fake(ws, repo, rels):
            return "the walls check refused it (walls: x)" if any("jo-lee" in r for r in rels) else real(ws, repo, rels)
        write(self.people / "jo-lee.md", person_page("Jo Lee", "acme"))
        commit_all(self.meetings, "jo")
        before = (self.people / "jo-lee.md").read_bytes()
        with mock.patch.object(pa, "walls_on_staged", fake):
            out = self.save([self.org("jo-lee"), self.org("mira-holt")])
        by = {r["index"]: r for r in out["rows"]}
        self.assertFalse(by[0]["ok"])
        self.assertEqual(before, (self.people / "jo-lee.md").read_bytes())
        self.assertEqual("", git(self.meetings, "status", "--porcelain").strip())


class TestEditsStayInTheView(Hardening):
    def setUp(self):
        super().setUp()
        shutil_rm = __import__("shutil").rmtree
        self.personal = self.root / "Zones" / "Personal"
        shutil_rm(self.personal / ".git", ignore_errors=True)
        git(self.personal, "init", "-q")
        git(self.personal, "config", "user.name", "T")
        git(self.personal, "config", "user.email", "t@example.com")
        git(self.personal, "config", "gc.auto", "0")
        write(self.personal / "Diary" / "Diary.md", "---\ntype: project\nparty: acme\nstatus: active\n---\n# Diary\n\nMira Holt phoned.\n")
        commit_all(self.personal, "d")
        write(self.meetings / "wiki" / "sources" / "noparty.md", "---\ntitle: No party\ntype: meeting\n---\n# C\n\nMira Holt said hi.\n")
        write(self.meetings / "wiki" / "sources" / "birch-note.md",
              "---\ntitle: Birch note\ntype: meeting\nzone: Work\nparties: [birch]\n---\n# B\n\nMira Holt said hi.\n")
        commit_all(self.meetings, "more")

    def test_only_near_side_wiki_pages_change_and_no_hint_is_given(self):
        before = snap(self.root)
        out = self.save([dict(do="correct", path="Wikis/Meetings/wiki/people/mira-holt.md", edit={"old": "Mira Holt", "new": "Mira Holte"})])
        self.assertTrue(out["rows"][0]["ok"], out)
        changed = self.diff(before)
        self.assertEqual(["Wikis/Meetings/wiki/people/mira-holt.md"], [c for c in changed if "generated" not in c and "index.md" not in c])
        self.assertNotIn("wall", out["rows"][0]["say"].lower())
        self.assertNotRegex(out["rows"][0]["say"], r"\d+ (live )?cop")
        self.assertEqual(1, len(git(self.personal, "log", "--oneline").splitlines()))

    def test_old_needs_three_characters(self):
        for old in ("a", "  b ", "ab", "   "):
            with self.assertRaises(pa.Refused):
                self.save([dict(do="correct", path="Wikis/Meetings/wiki/people/mira-holt.md", edit={"old": old, "new": "x"})])

    def test_the_ui_does_not_default_old_to_the_row_title(self):
        from test_questions_panel import qp
        self.assertNotIn("mk('input','text','',r.title,false)", qp.JS)


class TestPartialCommitsAreTold(Hardening):
    def test_a_path_in_the_wrong_case_is_refused(self):
        before = snap(self.root)
        out = self.save([self.org("MIRA-HOLT")])
        self.assertFalse(out["rows"][0]["ok"])
        self.assertEqual([], self.diff(before))

    def test_a_correction_is_never_told_with_the_wall_sentence_when_it_worked(self):
        write(self.meetings / "wiki" / "sources" / "birch-note.md",
              "---\ntitle: Birch note\ntype: meeting\nzone: Work\nparties: [birch]\n---\n# B\n\nMira Holt said hi.\n")
        commit_all(self.meetings, "b")
        out = self.save([dict(do="correct", path="Wikis/Meetings/wiki/people/mira-holt.md", edit={"old": "Mira Holt", "new": "Mira Holte"})])
        self.assertTrue(out["rows"][0]["ok"])
        self.assertNotIn("Nothing was written", out["rows"][0]["say"])

    def test_a_repository_that_cannot_commit_refuses_the_lot_before_any_commit(self):
        before = snap(self.root)
        log = self.head()
        with mock.patch.object(pa, "commit_refusal", return_value="Meetings would not run the wall check"):
            w = pa.Writes()
            w.write(self.people / "mira-holt.md", (self.people / "mira-holt.md").read_text() + "\nx\n")
            work_file = self.work / "Acme Review" / "Acme Review.md"
            w.write(work_file, work_file.read_text() + "\nx\n")
            with self.assertRaisesRegex(pa.Refused, "nothing was committed"):
                pa.commit_groups(self.root, w, lambda label, rels: "m", wall=None)
        self.assertEqual(log, self.head())
        self.assertEqual(1, len(self.head(self.work)))
        w.restore()
        self.assertEqual(before, snap(self.root))

    def test_the_check_timeouts_fit_inside_the_pages_lost_timeout(self):
        from test_questions_panel import status
        self.assertLessEqual(2 * pa.CHECK_TIMEOUT + pa.COMMIT_TIMEOUT + 60, status.ACTION_LOST)


class TestLaterAndNo(Hardening):
    def test_a_later_is_bound_to_its_path(self):
        out = self.save([self.org("mira-holt", choice="later", until="2026-11-20", key="a" * 12)])
        self.assertTrue(out["rows"][0]["ok"], out)
        later = pa.read_later(self.root)
        self.assertEqual({"a" * 12: {"until": "2026-11-20", "path": "Wikis/Meetings/wiki/people/mira-holt.md"}}, later)

    def test_a_forged_later_for_a_far_side_page_is_refused(self):
        out = self.save([self.org("theo-marsh", choice="later", until="2026-11-20", key="b" * 12)])
        self.assertEqual(SENTENCE, out["rows"][0]["say"])
        self.assertEqual({}, pa.read_later(self.root))

    def test_no_is_recorded_in_the_days_report_and_writes_no_page(self):
        before = snap(self.root)
        out = self.save([self.org("mira-holt", choice="no", key="c" * 12)])
        self.assertTrue(out["rows"][0]["ok"])
        rec = json.loads(self.report().read_text())
        self.assertEqual("no", rec["answered"][-1]["answer"])
        self.assertEqual([k for k in self.diff(before) if "generated" not in k], [])

    def test_js_sends_no(self):
        from test_questions_panel import qp
        self.assertIn("if(c==='no')return'no'", qp.JS)


class TestDuplicateKeys(Hardening):
    def test_a_case_variant_party_key_places_the_page_nowhere(self):
        write(self.people / "odd.md", person_page("Odd", "acme").replace("party: acme", "party: acme\nPARTY: birch"))
        commit_all(self.meetings, "odd")
        lib = pa.prefs().lib(self.root)
        self.assertIsNone(pa.page_party_tags(lib, self.root, self.people / "odd.md"))
        out = self.save([self.org("odd")])
        self.assertFalse(out["rows"][0]["ok"])


SECOND = "Birch has chosen the Rotterdam depot as its first site and will announce the lease before the autumn board"


class TestOpenWallFindings(Hardening):
    def seed_open_wording(self):
        birch = self.meetings / "wiki" / "sources" / "260312-birch-kickoff.md"
        birch.write_text(birch.read_text() + "\n%s.\n\n%s.\n" % (BIRCH_SENTENCE, SECOND))
        page = self.people / "mira-holt.md"
        page.write_text(page.read_text() + "\n%s.\n" % BIRCH_SENTENCE)
        commit_all(self.meetings, "open wording")
        counts = pa.check_counts(self.root)
        walls = [f for found in counts.values() if isinstance(found, set) for f in found if pa.wallish(f[0], f[2])]
        self.assertTrue(any(f[1].endswith("mira-holt.md") for f in walls), "the fixture must carry the open finding: %r" % (walls,))

    def test_a_page_with_an_open_wall_finding_is_read_only(self):
        self.seed_open_wording()
        before, log = snap(self.root), self.head()
        out = self.save([dict(do="correct", path="Wikis/Meetings/wiki/people/mira-holt.md", edit={"old": "Someone at a party", "new": SECOND})])
        self.assertEqual(SENTENCE, out["rows"][0]["say"])
        out = self.save([self.org("mira-holt")])
        self.assertEqual(SENTENCE, out["rows"][0]["say"])
        self.assertEqual([], self.diff(before))
        self.assertEqual(log, self.head())

    def test_a_wall_finding_on_a_file_a_correction_reached_refuses_the_row(self):
        page = self.people / "dana-whitlock.md"
        page.write_text(page.read_text() + "\nWorked with Mira Holt.\n\n%s.\n" % BIRCH_SENTENCE)
        birch = self.meetings / "wiki" / "sources" / "260312-birch-kickoff.md"
        birch.write_text(birch.read_text() + "\n%s.\n" % BIRCH_SENTENCE)
        commit_all(self.meetings, "dana")
        before = snap(self.root)
        out = self.save([dict(do="correct", path="Wikis/Meetings/wiki/people/mira-holt.md", edit={"old": "Mira Holt", "new": "Mira Holte"})])
        self.assertEqual(SENTENCE, out["rows"][0]["say"])
        self.assertEqual([k for k in self.diff(before) if "generated" not in k], [])


class TestPerRowAttribution(Hardening):
    def test_a_party_flip_is_that_rows_wall_reply_not_a_refusal_of_the_save(self):
        mira = self.people / "mira-holt.md"
        mira.write_text(mira.read_text().replace("party: acme\n", 'party: acme\norganisation: "[[wiki/entities/acme-corp]]"\n'))
        commit_all(self.meetings, "mira")
        before, log = snap(self.root), self.head()
        out = self.save([dict(do="correct", key="a" * 12, path="Wikis/Meetings/wiki/people/mira-holt.md",
                              edit={"old": "party: acme", "new": "party: birch"})])
        self.assertEqual(SENTENCE, out["rows"][0]["say"], out)
        self.assertEqual([k for k in self.diff(before) if "generated" not in k], [])
        self.assertEqual(log, self.head())

    def test_a_new_ordinary_finding_puts_back_only_the_row_that_made_it(self):
        write(self.people / "jo-lee.md", person_page("Jo Lee", "acme"))
        commit_all(self.meetings, "jo")
        real, calls = pa.check_counts, [0]

        def fake(ws):
            r = real(ws)
            calls[0] += 1
            if calls[0] == 2:           # the reading after the write: a new finding on the page the first row wrote
                r["check:warning"] = set(r.get("check:warning", set())) | {("x", "Wikis/Meetings/wiki/people/mira-holt.md", "something new")}
            return r
        with mock.patch.object(pa, "check_counts", fake):
            out = self.save([dict(do="correct", key="c" * 12, path="Wikis/Meetings/wiki/people/mira-holt.md",
                                  edit={"old": "Mira Holt", "new": "Mira Holte"}),
                             self.org("jo-lee", key="b" * 12)])
        by = {r["key"]: r for r in out["rows"]}
        self.assertFalse(by["c" * 12]["ok"], out)
        self.assertIn("found something new", by["c" * 12]["say"])
        self.assertNotIn("something else changed", by["c" * 12]["say"])
        self.assertTrue(by["b" * 12]["ok"], out)
        self.assertIn("Mira Holt", (self.people / "mira-holt.md").read_text())
        self.assertNotIn("Mira Holte", (self.people / "mira-holt.md").read_text())

    def test_a_finding_on_a_file_no_row_wrote_refuses_the_lot_with_the_hint(self):
        before = snap(self.root)
        new = {("x", "Zones/Work/Todo.md", "something new")}
        with mock.patch.object(pa, "check_counts", side_effect=[{"check:warning": set()}, {"check:warning": new}, {"check:warning": new}]):
            with self.assertRaisesRegex(pa.Refused, "something else changed"):
                self.save([self.org("mira-holt")])
        self.assertEqual([], self.diff(before))


class TestFailClosed(Hardening):
    def test_any_exception_in_the_commit_puts_every_file_back(self):
        before = snap(self.root)
        with mock.patch.object(pa, "commit_groups", side_effect=OSError("git went away")):
            with self.assertRaisesRegex(pa.Refused, "every file is back"):
                self.save([self.org("mira-holt")])
        self.assertEqual([], self.diff(before))

    def test_a_slow_index_rebuild_is_a_sentence_and_nothing_is_written(self):
        import subprocess
        real = subprocess.run

        def slow(cmd, *a, **kw):
            if cmd and cmd[-1] == "index":
                raise subprocess.TimeoutExpired(cmd, 1)
            return real(cmd, *a, **kw)
        before = snap(self.root)
        with mock.patch.object(pa.subprocess, "run", slow):
            with self.assertRaisesRegex(pa.Refused, "took too long"):
                self.save([dict(do="correct", path="Wikis/Meetings/wiki/people/mira-holt.md", edit={"old": "Mira Holt", "new": "Mira Holte"})])
        self.assertEqual([], self.diff(before))

    def test_a_missing_ingest_refuses_rather_than_skips_the_index(self):
        (self.root / "System" / "skills" / "meetings" / "ingest.py").unlink()
        before = snap(self.root)
        with self.assertRaisesRegex(pa.Refused, "ingest.py is missing"):
            self.save([dict(do="correct", path="Wikis/Meetings/wiki/people/mira-holt.md", edit={"old": "Mira Holt", "new": "Mira Holte"})])
        self.assertEqual([], self.diff(before))

    def test_no_with_an_edit_reads_as_one_outcome(self):
        out = self.save([self.org("mira-holt", choice="no", edit={"old": "Mira Holt", "new": "Mira Holte"})])
        self.assertEqual("Corrected Mira Holt to Mira Holte", out["rows"][0]["say"])


# Every wall test of the panel's save, once more with the save sent from the All view (#384).
for _name, _cls in list(globals().items()):
    if isinstance(_cls, type) and issubclass(_cls, Hardening) and _cls is not Hardening and not _name.endswith("FromAll"):
        globals()[_name + "FromAll"] = type(_name + "FromAll", (SaveThroughAll, _cls), {})
del _name, _cls


if __name__ == "__main__":
    unittest.main()
