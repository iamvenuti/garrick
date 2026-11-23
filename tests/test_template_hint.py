"""Wall findings that look like an old note template (#662).

    cd tests && python3 -m unittest test_template_hint

A note that repeats wording from four or more projects of one other walled zone, when every shared run is also held by four or more
files of its own zone, is one wall finding with a hint, from counts alone. The wall check itself does not change.

Invented names only: Work and Home are walled zones; Cedar is a project of Work, Maple0 to Maple9 are projects of Home.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, project_hub, write  # noqa: E402
from zone_fixture import HOME_SAYS, build  # noqa: E402
from test_nurture import TOOLS, nurture  # noqa: E402

sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "status"))
import check  # noqa: E402
import finding_queue as fq  # noqa: E402

TEMPLATE = """Welcome to this project note. Everything about the engagement lives in this folder, and the table below says where.

## Contents

| Folder | What it holds |
|---|---|
| Sources/ | Material received from the other side |
| Notes/ | Working notes written here |
| Deliverables/ | What is made for the project |

Content lives in the folder named in the table; this page only points to it.
"""
WORDS = ("Everything about the engagement lives", "Material received from the other side", "this page only points to it")
TODAY = datetime.date(2026, 10, 17)
NOTES = ["Zones/Work/Cedar/Notes/N%d.md" % i for i in range(10)]


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build(self.root)
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        write(self.root / "Zones" / "Work" / "Cedar" / "Cedar.md", project_hub("Work", "Cedar", "acme", ["Notes"]))
        for i in range(10):
            name = "Maple%d" % i
            write(self.root / "Zones" / "Home" / name / (name + ".md"), project_hub("Home", name, "jo", ["Notes"]).rstrip("\n") + "\n\n" + TEMPLATE)
        for path in NOTES:
            write(self.root / path, "# Note\n\n" + TEMPLATE)

    def items(self):
        ctx = nurture.Ctx(self.root, today=TODAY)
        return nurture.gather(ctx, ["Zones/Work/Cedar/Notes"])

    def walls(self, items=None):
        return [i for i in (items if items is not None else self.items()) if i.kind == "wall"]


class TestTheHint(Case):
    def test_the_wall_check_reads_each_note_against_ten_projects(self):
        found = [f for f in check.run_checks(self.root, walls_only=True) if "repeats wording" in f.message and f.path == NOTES[0]]
        self.assertEqual(10, len(found))

    def test_ten_notes_from_one_template_are_one_grouped_wall_finding_each_with_the_hint_and_no_words(self):
        walls = self.walls()
        self.assertEqual(sorted(NOTES), sorted(i.path for i in walls))
        for i in walls:
            self.assertEqual({"zone": "Home", "projects": 10, "notes": 10}, i.hint)
            line = i.line()
            self.assertIn("repeats wording from 10 projects of the Home zone", line)
            self.assertIn("The same wording is in 10 notes of this zone, so it may be text from an old note template.", line)
            self.assertIn("System/templates.local/", line)
            for w in WORDS:
                self.assertNotIn(w, line)
            self.assertNotIn("Maple", line)
            self.assertEqual("", i.message)
            self.assertNotIn("Maple", json.dumps(nurture.item_json(i)))
            for w in WORDS:
                self.assertNotIn(w, json.dumps(nurture.item_json(i)))

    def test_putting_the_template_in_templates_local_clears_the_findings(self):
        write(self.root / "System" / "templates.local" / "Old note.md", TEMPLATE)
        self.assertEqual([], self.walls())
        self.assertEqual([], [f for f in check.run_checks(self.root, walls_only=True) if "repeats wording" in f.message])

    def test_one_sentence_copied_from_one_hub_of_another_zone_gets_no_hint(self):
        for path in NOTES:
            (self.root / path).unlink()
        write(self.root / "Zones" / "Home" / "Maple0" / "Maple0.md",
              (self.root / "Zones" / "Home" / "Maple0" / "Maple0.md").read_text(encoding="utf-8") + "\n" + HOME_SAYS + "\n")
        write(self.root / "Zones" / "Work" / "Cedar" / "Notes" / "Lifted.md", "# Lifted\n\n%s\n" % HOME_SAYS)
        got = [i for i in nurture.gather(nurture.Ctx(self.root, today=TODAY), ["Zones/Work/Cedar/Notes"]) if i.kind == "wall"]
        self.assertEqual(["Zones/Work/Cedar/Notes/Lifted.md"], [i.path for i in got])
        self.assertIsNone(got[0].hint)
        self.assertNotIn("old note template", got[0].line())

    def test_a_wording_finding_never_offers_to_take_the_link_out(self):
        for i in self.walls():
            self.assertNotIn("take the link out", i.line())
        lone = nurture.Item("check", "walls", "Zones/Work/Cedar/Notes/Lone.md",
                            "repeats wording from Zones/Home/Maple0/Maple0.md, in project Maple0 of the Home zone; that zone is walled and this file is in the Work zone")
        nurture.claim_wall(nurture.Ctx(self.root, today=TODAY), lone)
        self.assertEqual("take the repeated wording out, or move this file into that zone", lone.proposal)
        self.assertEqual("wording", nurture.reference_kind("repeats wording from a meeting X, a meeting of Home"))
        self.assertEqual("link", nurture.reference_kind("links [[Garden Notes]], a note of the Personal zone"))
        self.assertEqual("embed", nurture.reference_kind("embeds ![[x]]"))

    def test_the_wall_check_is_not_changed_by_the_hint(self):
        before = sorted((f.path, f.message) for f in check.run_checks(self.root, walls_only=True))
        self.items()
        self.assertEqual(before, sorted((f.path, f.message) for f in check.run_checks(self.root, walls_only=True)))
        self.assertEqual(100, len([1 for p, m in before if "repeats wording" in m]))


class TestTheCounts(Case):
    def hints(self, path=NOTES[0]):
        return check.template_hints(self.root, [path]).get(path)

    def test_the_counts_name_a_zone_and_two_numbers(self):
        self.assertEqual([{"zone": "Home", "projects": 10, "notes": 10}], self.hints())

    def test_fewer_than_four_projects_give_no_hint(self):
        import shutil
        for i in range(3, 10):
            shutil.rmtree(self.root / "Zones" / "Home" / ("Maple%d" % i))
        self.assertIsNone(self.hints())

    def test_fewer_than_four_files_of_the_own_zone_give_no_hint(self):
        for path in NOTES[3:]:
            (self.root / path).unlink()
        self.assertIsNone(self.hints(NOTES[0]))

    def test_a_note_that_is_not_there_has_no_entry(self):
        self.assertEqual({}, check.template_hints(self.root, ["Zones/Work/Cedar/Notes/Missing.md", "Zones/Work/Todo.md"]))


class TestTheQuestion(Case):
    def records(self):
        ctx = nurture.Ctx(self.root, today=TODAY)
        items = nurture.gather(ctx, ["Zones/Work/Cedar/Notes"])
        nurture.record_run(ctx, ["Zones/Work/Cedar/Notes"], items)
        rec = json.loads((self.root / "System" / "generated" / "nurture" / "2026-10-17.json").read_text(encoding="utf-8"))
        return [dict(f, scope=nurture.debt_scope(f["path"]), listed=True,
                     message="%s: repeats wording from Zones/Home/Maple3/Maple3.md, in project Maple3 of the Home zone; that zone is walled and this file is in the Work zone" % f["path"])
                for f in rec["standing"] if f["kind"] == "wall"]

    def test_the_checks_card_asks_one_grouped_question_a_note_with_two_answers_and_no_words(self):
        got = fq.forecast_questions(self.records(), set(), ws=self.root)
        qs = [q for v in got.values() for q in v]
        self.assertEqual(10, len(qs))
        for q in qs:
            self.assertEqual("wall-template", q["id"])
            self.assertIn("repeats wording from 10 projects of Home", q["sentence"])
            self.assertIn("The same wording is in 10 notes of this zone, so it may be text from an old note template.", q["why"])
            self.assertEqual(["template", "one-by-one"], [a["id"] for a in q["answers"]])
            self.assertEqual(["It is an old template", "Show me the findings one by one"], [a["label"] for a in q["answers"]])
            self.assertEqual("", q["recommended"])
            self.assertNotIn("later", [a["action"] for a in q["answers"]])
            for a in q["answers"]:
                self.assertEqual("handoff", a["action"])          # nothing here changes a file
                self.assertNotIn("req", a)
            markup = fq.question_html(q)
            for w in WORDS + ("Maple",):
                self.assertNotIn(w, markup)
                self.assertNotIn(w, json.dumps(q))
            self.assertNotIn("take-out", markup)
            self.assertNotIn("take the link out", markup)

    def test_the_answers_name_what_to_do_and_hold_no_words(self):
        q = fq.forecast_questions(self.records(), set(), ws=self.root)["Zones/Work"][0]
        first, second = q["answers"]
        self.assertIn("templates folder", first["does"])
        self.assertIn("System/templates.local/", first["phrase"])
        self.assertIn("take the template text out of the notes", first["phrase"])
        self.assertIn("one by one", second["phrase"])
        for text in (first["phrase"], second["phrase"], q["free"]):
            self.assertNotIn("Maple", text)
            for w in WORDS:
                self.assertNotIn(w, text)

    def test_a_lone_wall_finding_is_still_a_wall_question(self):
        rec = dict(kind="wall", path="Zones/Work/Cedar/Notes/Lone.md", scope="Zones/Work", listed=True,
                   line="Zones/Work/Cedar/Notes/Lone.md: A note in the Work zone quotes a file of the Home zone Fix: take the repeated wording out, or move this file into that zone.",
                   message="Zones/Work/Cedar/Notes/Lone.md: repeats wording from Zones/Home/Maple0/Maple0.md, in project Maple0 of the Home zone; that zone is walled and this file is in the Work zone")
        self.assertEqual("wall", fq.plain_kind(rec))
        (q,) = fq.forecast_questions([rec], set(), ws=self.root)["Zones/Work"]
        self.assertEqual("wall", q["id"])
        self.assertEqual(["show-both", "take-out", "keep"], [a["id"] for a in q["answers"]])


if __name__ == "__main__":
    unittest.main()
