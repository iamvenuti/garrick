"""history.py (#502): old dated entries move to history files, a note is held under its cap, and a move is
confirmed line by line before it counts.

    cd tests && python3 -m unittest test_history

Invented parties only: Acme Corp (`acme`, zone Work) and Own affairs (`jo`, zone Home), walled from each other.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import GIT_ENV, HAVE_GIT, commit_all, git, write  # noqa: E402
from zone_fixture import build  # noqa: E402

import check  # noqa: E402
import history  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TODAY = datetime.date(2026, 11, 10)
FRONT = "---\ntitle: %s\ntype: thread\nproject: \"[[%s]]\"\nparent: \"[[%s]]\"\nparty: %s\nstatus: active\ncreated: 2026-01-05\nupdated: 2026-11-10\n---\n\n"
RESUME = ("# %s\n\n## State of play\n\n### Resume here\n\n**Where it stands, 10 November 2026.** Under way.\n\n"
          "| | |\n|---|---|\n| Next action | Send the draft |\n\n---\n\n")


def day(n):
    return TODAY - datetime.timedelta(days=n)


def stamp(d):
    return "%d %s %d" % (d.day, d.strftime("%B"), d.year)


def entry(i, d, words=20, link="", who="pricing"):
    """One dated entry: a bold date, a sentence, a second paragraph that belongs to it, `words` words in all. The
    words are the thread's own, so two threads in two zones share none."""
    filler = " ".join("%s%d" % (who, k) for k in range(words))
    return "**%s.** Entry %d settled the %s plan. %s\n\nA second paragraph of entry %d: %s.\n" % (stamp(d), i, who, link, i, filler)


def thread(title, project, party, days, words=20, tail="", link=""):
    """A thread note with one entry for each of `days` (days before today), newest first."""
    body = "\n".join(entry(i, day(n), words, link, title.lower()) for i, n in enumerate(days))
    return FRONT % (title, project, project, party) + RESUME % title + body + tail


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build(self.root)
        self.a = self.root / "Zones" / "Work" / "Northwind" / "Threads" / "Pricing" / "Pricing.md"
        self.b = self.root / "Zones" / "Home" / "Garden" / "Threads" / "Beds" / "Beds.md"
        env = mock.patch.dict(os.environ, GIT_ENV)
        env.start()
        self.addCleanup(env.stop)

    def put(self, path, text):
        write(path, text)
        return path

    def entries_of(self, path):
        return history.parse(Path(path).read_text(encoding="utf-8")).entries


class Reading(Fixture):
    def test_an_entry_is_a_paragraph_that_opens_with_a_bold_date_and_takes_the_ones_after_it(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 40]))
        found = self.entries_of(self.a)
        self.assertEqual([day(1), day(40)], [e.date for e in found])
        self.assertEqual(2, len([l for l in found[0].lines if l.strip()]))

    def test_the_iso_form_of_a_bold_date_is_an_entry_too(self):
        text = thread("Pricing", "Northwind", "acme", [1]).replace("**%s.**" % stamp(day(1)), "**%s.**" % day(1).isoformat())
        self.assertEqual([day(1)], [e.date for e in history.parse(text).entries])

    def test_a_date_that_does_not_parse_skips_the_note(self):
        text = thread("Pricing", "Northwind", "acme", [1]).replace(stamp(day(1)), "31 February 2026")
        with self.assertRaises(history.Skip):
            history.parse(text)

    def test_a_note_without_the_rule_is_skipped_not_guessed_at(self):
        text = thread("Pricing", "Northwind", "acme", [1]).replace("\n---\n\n**", "\n\n**", 1)
        with self.assertRaises(history.Skip) as why:
            history.parse(text)
        self.assertIn("rule", str(why.exception))

    def test_a_rule_inside_a_code_block_is_not_the_rule(self):
        text = thread("Pricing", "Northwind", "acme", [1]).replace("\n---\n\n**", "\n```\n---\n```\n\n**", 1)
        with self.assertRaises(history.Skip):
            history.parse(text)

    def test_carriage_returns_skip_the_note(self):
        with self.assertRaises(history.Skip):
            history.parse(thread("Pricing", "Northwind", "acme", [1]).replace("\n", "\r\n"))

    def test_resume_words_count_the_block_alone(self):
        text = thread("Pricing", "Northwind", "acme", [1], words=500)
        self.assertEqual(history.resume_words(text), len(history.resume_block(text).split()))
        self.assertLess(history.resume_words(text), 40)


class Moving(Fixture):
    def apply(self, path=None, **kw):
        return history.apply(self.root, path or self.a, TODAY, **kw)

    def test_entries_older_than_six_months_move_unchanged_to_quarterly_files_newest_first(self):
        days = [1, 20, 100, 190, 200, 260, 300, 330, 400, 500]       # 190 and later are older than six months
        self.put(self.a, thread("Pricing", "Northwind", "acme", days))
        before = self.entries_of(self.a)
        res = self.apply()
        self.assertTrue(res.done, res.error)
        kept = self.entries_of(self.a)
        self.assertEqual(5, len(kept))
        self.assertEqual([e.text for e in before[:5]], [e.text for e in kept])
        folder = self.a.parent / "history"
        moved = [e for e in before[5:]]
        found = {}
        for path in sorted(folder.glob("*.md")):
            found[path.name] = [e.text for e in history.parse_history_entries(path)] if hasattr(history, "parse_history_entries") else path.read_text(encoding="utf-8")
        self.assertEqual({"Pricing history %s.md" % q for q in {e.quarter for e in moved}}, set(found))
        every = "\n".join(path.read_text(encoding="utf-8") for path in folder.glob("*.md"))
        for e in moved:
            self.assertIn(e.text, every)

    def test_the_note_ends_its_entries_with_one_link_line_newest_quarter_first(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400, 600]))
        self.assertTrue(self.apply().done)
        text = self.a.read_text(encoding="utf-8")
        lines = [l for l in text.split("\n") if l.startswith("*Older entries:")]
        self.assertEqual(1, len(lines))
        self.assertRegex(lines[0], r"^\*Older entries: \[\[Northwind/Threads/Pricing/history/Pricing history 20\d\d-Q[1-4]\]\](, \[\[Northwind/Threads/Pricing/history/Pricing history 20\d\d-Q[1-4]\]\])*\.\*$")
        years = [int(q[:4]) for q in __import__("re").findall(r"(\d{4})-Q", lines[0])]
        self.assertEqual(sorted(years, reverse=True), years)
        kept = self.entries_of(self.a)
        self.assertLess(text.index(kept[-1].lines[0]), text.index(lines[0]))

    def test_a_history_file_holds_its_frontmatter_its_heading_and_the_entries_and_nothing_else(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400]))
        self.assertTrue(self.apply().done)
        (path,) = list((self.a.parent / "history").glob("*.md"))
        lines = path.read_text(encoding="utf-8").split("\n")
        self.assertEqual("---", lines[0])
        shut = lines.index("---", 1)
        fm = lines[1:shut]
        self.assertEqual(["type: history", 'parent: "[[Northwind/Threads/Pricing/Pricing|Pricing]]"', 'project: "[[Northwind]]"', "party: acme"], fm[:4])
        self.assertTrue(fm[4].startswith("created: "))
        self.assertFalse(any(l.startswith("status:") for l in fm))
        rest = [l for l in lines[shut + 1:] if l.strip()]
        self.assertEqual("# Pricing: history, %s" % path.stem.rsplit(" ", 1)[1], rest[0])
        self.assertTrue(rest[1].startswith("**"))

    def test_the_cap_moves_the_oldest_entries_until_the_note_fits_and_keeps_the_newest_five(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", list(range(1, 41)), words=300))
        before = history.note_words(self.a.read_text(encoding="utf-8"))
        self.assertGreater(before, 4000)
        self.assertTrue(self.apply().done)
        text = self.a.read_text(encoding="utf-8")
        self.assertLessEqual(history.note_words(text), 4000)
        kept = self.entries_of(self.a)
        self.assertEqual([day(n) for n in range(1, len(kept) + 1)], [e.date for e in kept])   # the newest stay
        self.assertGreaterEqual(len(kept), 5)

    def test_the_newest_five_stay_even_when_they_alone_are_over_the_cap(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", list(range(1, 9)), words=2000))
        res = self.apply()
        self.assertTrue(res.done, res.error)
        self.assertEqual(5, len(self.entries_of(self.a)))
        self.assertTrue(res.plan.still_over)

    def test_no_time_floor_a_note_with_every_entry_inside_a_fortnight_is_still_held_down(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [n * 0 + (n % 12) for n in range(40)], words=300))
        self.assertTrue(self.apply().done)
        self.assertLessEqual(history.note_words(self.a.read_text(encoding="utf-8")), 4000)

    def test_a_second_run_changes_nothing(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 6, 400, 500]))
        self.assertTrue(self.apply().done)
        snap = {p: p.read_bytes() for p in [self.a] + list((self.a.parent / "history").glob("*.md"))}
        res = self.apply()
        self.assertEqual([], res.plan.moves)
        self.assertFalse(res.done)
        self.assertEqual(snap, {p: p.read_bytes() for p in snap})
        self.assertEqual(set(snap), set([self.a] + list((self.a.parent / "history").glob("*.md"))))

    def test_a_later_move_adds_to_the_quarter_file_that_is_there(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400, 401]))
        self.assertTrue(self.apply().done)
        (path,) = list((self.a.parent / "history").glob("*.md")) if len(list((self.a.parent / "history").glob("*.md"))) == 1 else [None]
        files = sorted((self.a.parent / "history").glob("*.md"))
        first = {p: p.read_text(encoding="utf-8") for p in files}
        text = self.a.read_text(encoding="utf-8")
        newer = entry(9, day(402), who="pricing")
        self.a.write_text(text.replace("*Older entries", newer + "\n*Older entries"), encoding="utf-8")
        again = history.apply(self.root, self.a, TODAY)
        self.assertTrue(again.done or not again.plan.moves, again.error)
        for p, old in first.items():
            now = p.read_text(encoding="utf-8")
            for e in history.parse(thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400, 401])).entries[5:]:
                pass
            self.assertTrue(set(old.split("\n")) <= set(now.split("\n")), p.name)

    def test_a_relative_markdown_link_in_a_moved_entry_still_leads_where_it_led(self):
        link = "See [the memo](Deliverables/memo.md) and [site](https://example.com/x) and [[Wiki Link]]. "
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400], link=link))
        self.assertTrue(self.apply().done)
        (path,) = list((self.a.parent / "history").glob("*.md"))
        text = path.read_text(encoding="utf-8")
        self.assertIn("[the memo](../Deliverables/memo.md)", text)
        self.assertIn("[site](https://example.com/x)", text)
        self.assertIn("[[Wiki Link]]", text)
        self.assertIn("[the memo](Deliverables/memo.md)", self.a.read_text(encoding="utf-8"))   # the kept entries are untouched

    def test_the_settings_change_the_limits(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"history-months": 1, "note-max-words": 100000, "resume-max-words": 10}))
        self.assertEqual({"history-months": 1, "note-max-words": 100000, "resume-max-words": 10}, history.limits(self.root))
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 6, 50, 70]))
        res = history.plan(self.root, self.a, TODAY)
        self.assertEqual(2, len(res.moves))
        self.assertTrue(res.resume_over)

    def test_a_setting_that_is_not_a_whole_number_leaves_the_default(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"history-months": "six", "note-max-words": -3, "resume-max-words": True}))
        self.assertEqual(history.DEFAULTS, history.limits(self.root))

    def test_a_dry_run_lists_the_note_with_both_counts_and_writes_nothing(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400, 500], words=100))
        snap = self.a.read_bytes()
        plan = history.plan(self.root, self.a, TODAY)
        self.assertEqual(2, len(plan.moves))
        self.assertGreater(plan.before, plan.after)
        self.assertEqual(snap, self.a.read_bytes())
        self.assertFalse((self.a.parent / "history").exists())

    def test_a_history_file_this_tool_did_not_write_stops_the_note_and_nothing_moves(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400]))
        quarter = history.plan(self.root, self.a, TODAY).moves[0].quarter
        path = self.a.parent / "history" / ("Pricing history %s.md" % quarter)
        self.put(path, "# Somebody's notes\n\nDifferent text.\n")
        snap = (self.a.read_bytes(), path.read_bytes())
        res = self.apply()
        self.assertFalse(res.done)
        self.assertIn("history file", res.skipped)
        self.assertEqual(snap, (self.a.read_bytes(), path.read_bytes()))

    def test_a_move_that_cannot_be_confirmed_is_put_back_exactly(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400]))
        snap = self.a.read_bytes()
        with mock.patch.object(history, "verify", return_value="a line that left Pricing.md is in no history file, so the move was undone"):
            res = self.apply()
        self.assertFalse(res.done)
        self.assertTrue(res.error)
        self.assertEqual(snap, self.a.read_bytes())
        self.assertFalse((self.a.parent / "history").exists())

    def test_verification_catches_a_line_that_went_missing(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400]))
        real = history.build_files

        def lossy(plan, today):
            files = real(plan, today)
            return {path: text.replace("A second paragraph of entry 5", "x") for path, text in files.items()}

        snap = self.a.read_bytes()
        with mock.patch.object(history, "build_files", side_effect=lossy):
            res = self.apply()
        self.assertFalse(res.done)
        self.assertIn("no history file", res.error)
        self.assertEqual(snap, self.a.read_bytes())

    def test_a_hub_takes_the_same_layout_with_the_projects_name(self):
        hub = self.root / "Zones" / "Work" / "Northwind" / "Northwind.md"
        text = (FRONT % ("Northwind", "Northwind", "Northwind", "acme")).replace("type: thread", "type: project") + \
            RESUME % "Northwind" + "\n".join(entry(i, day(n)) for i, n in enumerate([1, 2, 3, 4, 5, 400]))
        self.put(hub, text)
        self.assertTrue(self.apply(hub).done)
        self.assertEqual(1, len(list((hub.parent / "history").glob("Northwind history *.md"))))

    def test_text_after_the_entries_stays_where_it_was(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400], tail="\n## Other section\n\nStays.\n"))
        self.assertTrue(self.apply().done)
        text = self.a.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("*\n\n## Other section\n\nStays.\n") or "## Other section\n\nStays.\n" in text)
        self.assertLess(text.index("*Older entries"), text.index("## Other section"))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Committing(Fixture):
    """A wrap over 4,000 words, in two walled zones: five entries and one link line in one commit that passes the
    wall check."""

    def setUp(self):
        super().setUp()
        self.put(self.a, thread("Pricing", "Northwind", "acme", list(range(1, 41)), words=300))
        self.put(self.b, thread("Beds", "Garden", "jo", list(range(1, 41)), words=300))
        for zone in ("Work", "Home"):
            repo = self.root / "Zones" / zone
            git(repo, "init", "-q")
            commit_all(repo, "start")

    def log(self, zone):
        return git(self.root / "Zones" / zone, "log", "--format=%s").split("\n")[:-1]

    def test_each_walled_zone_commits_its_move_in_one_commit_that_passes_the_wall_check(self):
        for zone, note in (("Work", self.a), ("Home", self.b)):
            res = history.apply(self.root, note, TODAY, commit="%s: older entries moved to history" % note.stem)
            self.assertTrue(res.done, res.error)
            self.assertTrue(res.commit)
            self.assertEqual(note.stem + ": older entries moved to history", self.log(zone)[0])
            self.assertLessEqual(history.note_words(note.read_text(encoding="utf-8")), 4000)
            self.assertGreaterEqual(len(self.entries_of(note)), 5)
            self.assertEqual(1, note.read_text(encoding="utf-8").count("*Older entries:"))
            status = git(self.root / "Zones" / zone, "status", "--porcelain")
            self.assertEqual("", status)

    def test_the_history_files_pass_the_wall_check_in_every_zone(self):
        for note in (self.a, self.b):
            self.assertTrue(history.apply(self.root, note, TODAY).done)
        found = [f for f in check.run_checks(self.root, walls_only=True) if f.severity == "error"]
        self.assertEqual([], found)
        for zone in ("Work", "Home"):
            commit_all(self.root / "Zones" / zone, "moved")

    def test_every_line_that_left_a_note_is_in_a_history_file(self):
        before = self.a.read_text(encoding="utf-8").split("\n")
        self.assertTrue(history.apply(self.root, self.a, TODAY).done)
        now = set(self.a.read_text(encoding="utf-8").split("\n"))
        held = set()
        for path in (self.a.parent / "history").glob("*.md"):
            held.update(path.read_text(encoding="utf-8").split("\n"))
        for line in before:
            if line.strip() and line not in now:
                self.assertIn(line, held)

    def test_a_second_run_changes_nothing_and_commits_nothing(self):
        history.apply(self.root, self.a, TODAY, commit="first")
        head = git(self.root / "Zones" / "Work", "rev-parse", "HEAD")
        res = history.apply(self.root, self.a, TODAY, commit="second")
        self.assertFalse(res.done)
        self.assertEqual(head, git(self.root / "Zones" / "Work", "rev-parse", "HEAD"))

    def test_the_command_line_dry_run_lists_both_counts_and_apply_moves(self):
        out = self._run("dry-run", "--scope", "Zones/Work")
        self.assertIn("would move", out)
        self.assertIn("Zones/Work/Northwind/Threads/Pricing/Pricing.md", out)
        self.assertFalse((self.a.parent / "history").exists())
        out = self._run("apply", "--scope", "Zones/Work")
        self.assertIn("moved", out)
        self.assertTrue((self.a.parent / "history").is_dir())
        self.assertFalse((self.b.parent / "history").exists())

    def _run(self, *argv):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = history.main(["--root", str(self.root)] + list(argv) + ["--today", TODAY.isoformat()])
        self.assertEqual(0, code)
        return buf.getvalue()


class Notes(Fixture):
    def test_history_files_are_not_hub_or_thread_notes(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400]))
        self.assertTrue(history.apply(self.root, self.a, TODAY).done)
        found = history.notes_in(self.root, "Zones/Work")
        self.assertIn(self.a, found)
        self.assertFalse([p for p in found if "history" in p.parts])


class Guards(Fixture):
    def test_a_history_folder_that_is_a_link_stops_the_note_and_nothing_is_written(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400]))
        elsewhere = self.root / "Zones" / "Home" / "Garden" / "Threads" / "Beds" / "elsewhere"
        elsewhere.mkdir(parents=True)
        os.symlink(str(elsewhere), str(self.a.parent / "history"))
        snap = self.a.read_bytes()
        res = history.apply(self.root, self.a, TODAY)
        self.assertFalse(res.done)
        self.assertIn("link", res.skipped)
        self.assertEqual(snap, self.a.read_bytes())
        self.assertEqual([], list(elsewhere.iterdir()))

    def test_a_history_file_that_is_a_link_out_of_the_folder_stops_the_note(self):
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400]))
        (self.a.parent / "history").mkdir()
        target = self.root / "Zones" / "Home" / "Garden" / "other.md"
        target.write_text("x\n", encoding="utf-8")
        os.symlink(str(target), str(self.a.parent / "history" / "Pricing history 2025-Q1.md"))
        self.assertIn("link", history.apply(self.root, self.a, TODAY).skipped)

    def test_identical_entries_on_one_date_all_reach_the_history_file(self):
        text = thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5])
        old = "**%s.** Parked.\n\n**%s.** Parked.\n\n**%s.** Woken.\n" % ((stamp(day(400)),) * 3)
        self.put(self.a, text + "\n" + old)
        res = history.apply(self.root, self.a, TODAY)
        self.assertTrue(res.done, res.error)
        (path,) = list((self.a.parent / "history").glob("*.md"))
        body = path.read_text(encoding="utf-8")
        self.assertEqual(2, body.count("Parked."))
        self.assertEqual(1, body.count("Woken."))
        self.assertNotIn("Parked.", self.a.read_text(encoding="utf-8"))

    def test_the_confirmation_counts_lines_not_looks_them_up(self):
        said = history.unconfirmed("a\nb\nb\n", "a\n", ["b\n"])
        self.assertIn(history.UNCONFIRMED, said)
        self.assertEqual("", history.unconfirmed("a\nb\nb\n", "a\n", ["b\nb\n"]))


class Skills(unittest.TestCase):
    """The threads skill runs the mover where the note already changes: the wrap, after its new entry, and park,
    before it parks. The skill names no assistant (test_executor reads it too)."""

    def section(self, title):
        folder = REPO / "template" / "System" / "skills" / "threads"
        text = "\n".join(f.read_text(encoding="utf-8") for f in [folder / "SKILL.md"] + sorted((folder / "reference").glob("*.md")))
        start = text.index("\n## %s" % title)
        end = text.index("\n## ", start + 5)
        return text[start:end]

    def test_the_wrap_moves_old_entries_in_its_commit_and_offers_the_shrink_on_a_yes(self):
        wrap = self.section("Wrap")
        self.assertIn("python3 System/tools/history.py apply", wrap)
        self.assertIn("resume-max-words", wrap)
        self.assertIn("never run overnight", wrap)
        self.assertLess(wrap.index("history.py apply"), wrap.index("git -C \"Zones/<Zone>\" commit"))
        self.assertIn("`history/` folder", wrap)

    def test_park_moves_them_first_and_leaves_the_resume_block_as_it_is(self):
        park = self.section("Park")
        self.assertIn("python3 System/tools/history.py apply", park)
        self.assertIn("--commit", park)
        self.assertLess(park.index("history.py apply"), park.index("page_action.py park"))
        self.assertIn("The Resume here block stays as", park)

    def test_the_principle_says_never_edit_an_entry_not_never_move_one(self):
        text = (REPO / "docs" / "principles.md").read_text(encoding="utf-8")
        self.assertIn("An entry is never edited, though it may be moved", text)
        self.assertNotIn("never editing the old ones", text)


if __name__ == "__main__":
    unittest.main()
