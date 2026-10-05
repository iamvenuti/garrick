"""Tests for the meetings skill's helper, System/skills/meetings/ingest.py.

    python3 -m unittest discover -s tests

Standard library only. Each test builds its own small Meetings wiki under a
temporary folder; nothing here touches a real workspace.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "template" / "System" / "skills" / "meetings"
INGEST_PATH = SKILL_DIR / "ingest.py"

sys.path.insert(0, str(REPO / "tests"))
import fixtures  # noqa: E402


def _load_ingest():
    spec = importlib.util.spec_from_file_location("garrick_meetings_ingest", INGEST_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingest = _load_ingest()


def run_cli(root, *args):
    return subprocess.run(
        [sys.executable, str(INGEST_PATH), "--root", str(root), *args],
        capture_output=True, text=True,
    )


class TempWorkspace:
    """A bare Wikis/Meetings tree, enough for ingest.py, nothing more."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        meetings = self.root / "Wikis" / "Meetings"
        fixtures.write(meetings / "raw" / "inbox" / ".gitkeep")
        fixtures.write(meetings / "wiki" / "sources" / ".gitkeep")
        fixtures.write(meetings / "wiki" / "people" / ".gitkeep")
        fixtures.write(meetings / "wiki" / "index.md", "# Index\n\nEvery page, newest first.\n\n"
                                                        "| Page | Type | Updated |\n|---|---|---|\n")
        fixtures.write(meetings / "wiki" / "log.md", "# Log\n\nOne line per ingest, newest first.\n")
        self.meetings = meetings

    def inbox_file(self, name, text="Dana: we start Monday.\n"):
        return fixtures.write(self.meetings / "raw" / "inbox" / name, text)

    def close(self):
        self.tmp.cleanup()


class NamingTest(unittest.TestCase):
    def test_slugify_keeps_letters_digits_hyphens(self):
        self.assertEqual(ingest.slugify("Acme Corp: Kick-off!"), "acme-corp-kick-off")

    def test_slugify_never_empty(self):
        self.assertEqual(ingest.slugify("!!!"), "meeting")

    def test_yymmdd(self):
        self.assertEqual(ingest.yymmdd("2026-03-10"), "260310")

    def test_build_slug_matches_check_pattern(self):
        slug = ingest.build_slug("2026-03-10", "Acme kick-off", taken=set())
        self.assertEqual(slug, "260310-acme-kick-off")
        self.assertRegex(slug, ingest.SLUG_RE)

    def test_build_slug_avoids_collision(self):
        taken = {"260310-acme-kick-off", "260310-acme-kick-off-2"}
        self.assertEqual(ingest.build_slug("2026-03-10", "Acme kick-off", taken), "260310-acme-kick-off-3")


class LandTest(unittest.TestCase):
    def setUp(self):
        self.ws = TempWorkspace()

    def tearDown(self):
        self.ws.close()

    def test_moves_file_and_names_it(self):
        f = self.ws.inbox_file("call.txt")
        slug, dest = ingest.land(self.ws.root, f, "2026-03-10", "Acme kick-off")
        self.assertEqual(slug, "260310-acme-kick-off")
        self.assertFalse(f.exists())
        self.assertTrue(dest.is_file())
        self.assertEqual(dest, self.ws.meetings / "raw" / "260310-acme-kick-off.txt")
        self.assertEqual(dest.read_text(), "Dana: we start Monday.\n")

    def test_never_overwrites_a_same_day_meeting(self):
        f1 = self.ws.inbox_file("one.txt")
        slug1, dest1 = ingest.land(self.ws.root, f1, "2026-03-10", "Acme kick-off")
        f2 = self.ws.inbox_file("two.txt", "A second, different call.\n")
        slug2, dest2 = ingest.land(self.ws.root, f2, "2026-03-10", "Acme kick-off")
        self.assertNotEqual(slug1, slug2)
        self.assertTrue(dest1.is_file())
        self.assertTrue(dest2.is_file())
        self.assertEqual(dest1.read_text(), "Dana: we start Monday.\n")
        self.assertEqual(dest2.read_text(), "A second, different call.\n")

    def test_avoids_a_slug_already_used_by_a_source_page(self):
        fixtures.write(self.ws.meetings / "wiki" / "sources" / "260310-acme-kick-off.md", "already here\n")
        f = self.ws.inbox_file("call.txt")
        slug, dest = ingest.land(self.ws.root, f, "2026-03-10", "Acme kick-off")
        self.assertEqual(slug, "260310-acme-kick-off-2")

    def test_refuses_an_unreadable_extension(self):
        f = self.ws.inbox_file("recording.mp3", "not text")
        with self.assertRaises(ingest.Refusal):
            ingest.land(self.ws.root, f, "2026-03-10", "Acme kick-off")

    def test_refuses_a_missing_file(self):
        with self.assertRaises(ingest.Refusal):
            ingest.land(self.ws.root, self.ws.meetings / "raw" / "inbox" / "missing.txt", "2026-03-10", "X")

    def test_refuses_a_bad_date(self):
        f = self.ws.inbox_file("call.txt")
        with self.assertRaises(ingest.Refusal):
            ingest.land(self.ws.root, f, "10 March 2026", "Acme kick-off")

    def test_refuses_an_empty_title(self):
        f = self.ws.inbox_file("call.txt")
        with self.assertRaises(ingest.Refusal):
            ingest.land(self.ws.root, f, "2026-03-10", "   ")


class LandOnlyFromTheInboxTest(unittest.TestCase):
    """land takes a transcript from raw/inbox/ and nowhere else, never through
    a link, and leaves the file where it was when it refuses."""

    def setUp(self):
        self.ws = TempWorkspace()
        self.note = fixtures.write(self.ws.root / "Zones" / "Work" / "Acme Review" / "Acme Review.md",
                                   "---\ntitle: Acme Review\ntype: project\n---\n")
        self.text = self.note.read_text()

    def tearDown(self):
        self.ws.close()

    def assert_untouched(self):
        self.assertEqual(self.text, self.note.read_text())
        self.assertEqual([], [p.name for p in (self.ws.meetings / "raw").iterdir() if p.name != "inbox"])

    def assert_refused(self, path):
        with self.assertRaises(ingest.Refusal) as caught:
            ingest.land(self.ws.root, path, "2026-03-10", "Acme kick-off")
        self.assertIn("Nothing was moved", str(caught.exception))
        self.assert_untouched()

    def test_refuses_a_file_outside_the_inbox(self):
        self.assert_refused(self.note)
        r = run_cli(self.ws.root, "land", "--inbox", str(self.note), "--date", "2026-03-10", "--title", "X")
        self.assertEqual(1, r.returncode)
        self.assertIn("raw/inbox", r.stderr)
        self.assert_untouched()

    def test_refuses_a_file_in_a_folder_inside_the_inbox(self):
        nested = self.ws.inbox_file("older/call.txt")
        self.assert_refused(nested)
        self.assertTrue(nested.exists())

    def test_refuses_a_link_in_the_inbox(self):
        link = self.ws.meetings / "raw" / "inbox" / "call.md"
        os.symlink(str(self.note), str(link))
        self.assert_refused(link)
        self.assertTrue(link.is_symlink())

    def test_refuses_a_linked_inbox(self):
        inbox = self.ws.meetings / "raw" / "inbox"
        (inbox / ".gitkeep").unlink()
        inbox.rmdir()
        os.symlink(str(self.note.parent), str(inbox))
        self.assert_refused(inbox / self.note.name)

    def test_refuses_a_link_waiting_at_the_destination(self):
        f = self.ws.inbox_file("call.txt")
        waiting = self.ws.meetings / "raw" / "260310-acme-kick-off.txt"
        os.symlink(str(self.note.parent / "Sources" / "call.txt"), str(waiting))
        with self.assertRaises(ingest.Refusal) as caught:
            ingest.land(self.ws.root, f, "2026-03-10", "Acme kick-off")
        self.assertIn("Nothing was moved", str(caught.exception))
        self.assertTrue(f.exists())
        self.assertFalse((self.note.parent / "Sources").exists())

    def test_still_lands_from_the_inbox(self):
        f = self.ws.inbox_file("call.txt")
        slug, dest = ingest.land(self.ws.root, f, "2026-03-10", "Acme kick-off")
        self.assertEqual(self.ws.meetings / "raw" / "260310-acme-kick-off.txt", dest)
        self.assertEqual(self.text, self.note.read_text())

class PastedNotesTest(unittest.TestCase):
    """Notes pasted into the conversation: the skill saves them unedited as
    raw/inbox/<YYMMDD-slug>.txt, the way land names a raw record, and lands
    that file like any dropped one."""

    PASTED = "Marta: nine percent on the renewal.\r\n\r\n  - Dana sends the forecast  \n\tno date set\n".encode("utf-8")

    def setUp(self):
        self.ws = TempWorkspace()
        self.inbox = self.ws.meetings / "raw" / "inbox" / "260915-cobalt-renewal.txt"
        self.inbox.write_bytes(self.PASTED)

    def tearDown(self):
        self.ws.close()

    def test_the_skill_names_the_file_as_land_does(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        pasted = text.split("\n## Notes pasted in\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("`Wikis/Meetings/raw/inbox/<YYMMDD-slug>.txt`", pasted)
        self.assertIn("(`260915-cobalt-renewal.txt`)", pasted)
        self.assertEqual("260915-cobalt-renewal", ingest.build_slug("2026-09-15", "Cobalt renewal", taken=set()))

    def test_lands_under_its_own_name_byte_for_byte(self):
        slug, dest = ingest.land(self.ws.root, self.inbox, "2026-09-15", "Cobalt renewal")
        self.assertEqual("260915-cobalt-renewal", slug)
        self.assertEqual(self.ws.meetings / "raw" / "260915-cobalt-renewal.txt", dest)
        self.assertEqual(self.PASTED, dest.read_bytes())
        self.assertFalse(self.inbox.exists())

    def test_a_date_corrected_on_confirming_names_the_record(self):
        slug, dest = ingest.land(self.ws.root, self.inbox, "2026-09-16", "Cobalt renewal")
        self.assertEqual("260916-cobalt-renewal", slug)
        self.assertEqual(self.PASTED, dest.read_bytes())


class PersonTest(unittest.TestCase):
    def setUp(self):
        self.ws = TempWorkspace()

    def tearDown(self):
        self.ws.close()

    def test_creates_a_stub_once(self):
        path, created = ingest.ensure_person(self.ws.root, "Dana Whitlock", "acme", "2026-03-10")
        self.assertTrue(created)
        self.assertEqual(path, self.ws.meetings / "wiki" / "people" / "dana-whitlock.md")
        text = path.read_text()
        self.assertIn("title: Dana Whitlock", text)
        self.assertIn("type: person", text)
        self.assertIn("party: acme", text)

    def test_never_overwrites_an_existing_page(self):
        path, _ = ingest.ensure_person(self.ws.root, "Dana Whitlock", "acme", "2026-03-10")
        path.write_text("# Dana Whitlock\n\nHand-edited.\n", encoding="utf-8")
        _, created = ingest.ensure_person(self.ws.root, "Dana Whitlock", "acme", "2026-03-11")
        self.assertFalse(created)
        self.assertEqual(path.read_text(), "# Dana Whitlock\n\nHand-edited.\n")


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.ws = TempWorkspace()

    def tearDown(self):
        self.ws.close()

    def test_lists_sources_and_people_newest_first(self):
        fixtures.write(self.ws.meetings / "wiki" / "sources" / "260310-acme-kickoff.md",
                        fixtures.meeting_page("Work", "[acme]", "Acme kick-off"))
        fixtures.write(self.ws.meetings / "wiki" / "sources" / "260312-birch-kickoff.md",
                        fixtures.meeting_page("Work", "[birch]", "Birch kick-off"))
        ingest.ensure_person(self.ws.root, "Dana Whitlock", "acme", "2026-03-05")
        path, n = ingest.rebuild_index(self.ws.root)
        self.assertEqual(n, 3)
        text = path.read_text()
        self.assertIn("| Page | Type | Updated |", text)
        birch_at = text.index("Birch kick-off")
        acme_at = text.index("Acme kick-off")
        dana_at = text.index("Dana Whitlock")
        self.assertLess(birch_at, acme_at)  # 12 March before 10 March
        self.assertLess(acme_at, dana_at)   # 10 March before 5 March
        self.assertIn("[[wiki/sources/260312-birch-kickoff\\|Birch kick-off]]", text)
        self.assertIn("[[wiki/people/dana-whitlock\\|Dana Whitlock]]", text)

    def test_empty_wiki_gives_a_header_only(self):
        path, n = ingest.rebuild_index(self.ws.root)
        self.assertEqual(n, 0)
        self.assertIn("| Page | Type | Updated |", path.read_text())


class LogTest(unittest.TestCase):
    def setUp(self):
        self.ws = TempWorkspace()

    def tearDown(self):
        self.ws.close()

    def test_appends_newest_first(self):
        path = ingest.append_log(self.ws.root, "260310-acme-kick-off", "Acme kick-off", "Work", ["acme"],
                                  today="2026-03-10")
        path = ingest.append_log(self.ws.root, "260312-birch-kick-off", "Birch kick-off", "Work", ["birch"],
                                  today="2026-03-12")
        lines = [l for l in path.read_text().splitlines() if l.startswith("- ")]
        self.assertEqual(len(lines), 2)
        self.assertIn("260312-birch-kick-off", lines[0])
        self.assertIn("260310-acme-kick-off", lines[1])
        self.assertIn("acme", lines[1])

    def test_keeps_the_header(self):
        path = ingest.append_log(self.ws.root, "260310-acme-kick-off", "Acme kick-off", "Work", ["acme"],
                                  today="2026-03-10")
        text = path.read_text()
        self.assertTrue(text.startswith("# Log\n\nOne line per ingest, newest first.\n"))


class CliTest(unittest.TestCase):
    def setUp(self):
        self.ws = TempWorkspace()

    def tearDown(self):
        self.ws.close()

    def test_land_then_index_via_subprocess(self):
        f = self.ws.inbox_file("call.txt")
        r = run_cli(self.ws.root, "land", "--inbox", str(f), "--date", "2026-03-10", "--title", "Acme kick-off")
        self.assertEqual(r.returncode, 0, r.stderr)
        slug = r.stdout.split("\t", 1)[0].strip()
        self.assertEqual(slug, "260310-acme-kick-off")

        r = run_cli(self.ws.root, "index")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_refusal_exits_nonzero_with_a_plain_message(self):
        r = run_cli(self.ws.root, "land", "--inbox", "nowhere.txt", "--date", "2026-03-10", "--title", "X")
        self.assertEqual(r.returncode, 1)
        self.assertIn("is not a file", r.stderr)


if __name__ == "__main__":
    unittest.main()
