"""The Overview's Waiting on you now card lists a Needs you question (#503), and the simple home is gone.

    cd tests && python3 -m unittest test_needs_you_rows

A question is a file in the `Needs you` folder of the work it blocks. Its row has one button for each answer and Not now,
and names its own zone only. Nothing here reads this Mac: the workspace is built in a temporary folder.
"""
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from html import unescape
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "extras" / "status"))
sys.path.insert(0, str(REPO / "template" / "System" / "tools"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = _load("garrick_status_needs_you", "extras/status/status.py")
NOW = dt.datetime(2026, 11, 10, 10, 0)
TODAY = NOW.date()


def question(ask="Which price list goes to Acme?", status_="open", later=None, own=None, asked="2026-11-07", options=True):
    front = ["---", "type: question", "status: %s" % status_, "asked: %s" % asked]
    if later:
        front.append("later: %s" % later)
    if own:
        front.append("own: %s" % own)
    front.append("---")
    body = ["", "**%s**" % ask, "", "Acme asked on Friday."]
    if options:
        body += ["", "- [List A] Send list A on Monday", "- [List B] Send list B on Monday"]
        if own:
            body.append("- [%s] Say what to do in your own words" % own)
    return "\n".join(front + body) + "\n"


class Rows(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        self.box = self.work / "Acme Review" / "Threads" / "Pricing" / "Needs you"

    def needs(self):
        return status.question_needs(self.root, TODAY)

    def page(self):
        jobs = Path(self._tmp.name) / "jobs"
        jobs.mkdir(exist_ok=True)
        with mock.patch.object(status, "launch_agents", lambda: Path(self._tmp.name) / "LA"), \
                mock.patch.dict(os.environ, {"HOME": str(Path(self._tmp.name) / "home")}):
            return status.build(self.root, now=NOW, folder=jobs)

    def card(self, page):
        return page[page.index('id="waiting-now"'):page.index('id="threads"')]

    def acts(self, html):
        return [json.loads(unescape(m)) for m in re.findall(r'data-act="([^"]*)"', html)]

    def test_an_open_question_is_a_row_with_a_button_for_each_answer_and_not_now(self):
        write(self.box / "261107 - price.md", question())
        (need,) = self.needs()
        self.assertEqual("Work", need["zone"])
        self.assertEqual("Pricing: Which price list goes to Acme?", need["text"])
        card = self.card(self.page())
        self.assertIn("<h2>One thing needs you.</h2>", card)
        self.assertIn("Pricing: Which price list goes to Acme?", card)
        file = "Acme Review/Threads/Pricing/Needs you/261107 - price.md"
        self.assertEqual([{"verb": "answer", "zone": "Work", "file": file, "label": "List A"},
                          {"verb": "answer", "zone": "Work", "file": file, "label": "List B"},
                          {"verb": "later", "zone": "Work", "file": file}], self.acts(card))
        self.assertIn(">Not now<", card)
        self.assertIn("asked Sat 7 Nov", card)

    def test_a_project_of_one_thread_keeps_its_question_in_the_project_folder(self):
        write(self.work / "Acme Review" / "Needs you" / "261107 - price.md", question())
        self.assertEqual(["Work"], [n["zone"] for n in self.needs()])

    def test_answered_closed_and_put_off_questions_are_left_out_until_their_day(self):
        write(self.box / "a.md", question(status_="answered"))
        write(self.box / "b.md", question(status_="later", later="2026-11-11"))
        write(self.box / "c.md", question(ask="Back today?", status_="later", later="2026-11-10"))
        write(self.box / "d.md", question(ask="No bold line").replace("**No bold line**", "plain"))
        write(self.box / "_e.md", question())
        self.assertEqual(["Pricing: Back today?"], [n["text"] for n in self.needs()])

    def test_the_answer_in_the_users_own_words_is_not_a_button(self):
        write(self.box / "a.md", question(own="Change it"))
        labels = [a.get("label") for a in self.acts(self.card(self.page()))]
        self.assertEqual(["List A", "List B", None], labels)

    def test_a_question_with_no_listed_answer_still_offers_not_now_and_the_link(self):
        write(self.box / "a.md", question(options=False))
        card = self.card(self.page())
        self.assertEqual(["later"], [a["verb"] for a in self.acts(card)])
        self.assertIn('href="#threads"', card)

    def test_each_row_names_its_own_zone_and_nothing_adds_two(self):
        personal = self.root / "Zones" / "Personal" / "Garden" / "Threads" / "Beds"
        write(personal.parent.parent / "Garden.md", "---\ntype: project\n---\n# Garden\n")
        write(personal / "Beds.md", "---\ntype: thread\n---\n# Beds\n")
        write(personal / "Needs you" / "a.md", question(ask="Which bed first?"))
        write(self.box / "a.md", question())
        zones = [n["zone"] for n in self.needs()]
        self.assertEqual(["Personal", "Work"], sorted(zones))
        self.assertEqual({"Work": "Acme Review/Threads/Pricing/Needs you/a.md", "Personal": "Garden/Threads/Beds/Needs you/a.md"},
                         {n["zone"]: n["q"] for n in self.needs()})
        self.assertIn("<h2>Two things need you.</h2>", self.card(self.page()))

    def test_a_question_text_cannot_break_the_markup(self):
        write(self.box / "a.md", question(ask='<img src=x onerror="1"> Which?'))
        self.assertNotIn("<img", self.card(self.page()))

    def test_the_row_goes_when_the_answer_is_noted(self):
        js = status.QUESTION_JS
        self.assertIn("'answer'", js)
        self.assertIn("'later'", js)
        self.assertIn("GarrickNeedsLead", js)
        self.assertIn("window.GarrickNeedsLead=", status.WAITING_JS)
        self.assertIn(js.strip(), self.page())

    def test_no_question_no_row(self):
        self.assertEqual([], self.needs())
        self.assertIn("<h2>Nothing needs you right now.</h2>", self.card(self.page()))


class SimpleHomeIsGone(unittest.TestCase):
    """#503: the Garrick App opens on the full page only."""

    def test_the_page_has_no_home_tab_more_button_or_settings_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "Workspace"
            build_workspace(root)
            write(root / "System" / "garrick-settings.json", json.dumps({"home": "simple"}))
            jobs = Path(tmp) / "jobs"
            jobs.mkdir()
            with mock.patch.object(status, "launch_agents", lambda: Path(tmp) / "LA"), \
                    mock.patch.dict(os.environ, {"HOME": str(Path(tmp) / "home")}):
                page = status.build(root, now=NOW, folder=jobs)
        for gone in ('class="simple"', "body.simple", "SIMPLE_CSS", "SIMPLE_JS", "sh-needs", "Ask something", "Add your own work",
                     'data-tab="home"', "choice(\"simple\""):
            self.assertNotIn(gone, page)
        self.assertIn('id="tab-overview"', page)              # the full page, whatever the old setting says

    def test_the_library_has_no_home_setting_to_read(self):
        lib = _load("garrick_lib_for_home", "template/System/tools/garrick_lib.py")
        self.assertFalse(hasattr(lib, "simple_home"))
        self.assertFalse(hasattr(lib, "zone_todo"))

    def test_no_page_action_verb_scans_a_folder_for_the_page(self):
        pa = _load("page_action_for_home", "extras/status/page_action.py")
        self.assertNotIn("discover", pa.VERBS)
        self.assertIn("answer", pa.VERBS)                  # a Needs you question is still answered by this verb
        self.assertIn("later", pa.VERBS)

    def test_no_shipped_file_names_the_simple_home(self):
        ours = ("install.py", "update.py", "split.py")
        hits = []
        for folder in ("template", "extras", "docs"):
            for path in sorted((REPO / folder).rglob("*")):
                if path.is_file() and path.suffix in (".py", ".md", ".swift", ".json", ".html", ".sh", ".txt"):
                    if re.search(r"simple[ -]home|simple_home", path.read_text(encoding="utf-8", errors="replace"), re.I):
                        hits.append(str(path.relative_to(REPO)))
        for name in ours:
            if re.search(r"simple[ -]home|simple_home", (REPO / name).read_text(encoding="utf-8"), re.I):
                hits.append(name)
        self.assertEqual([], hits)


class HomeSettingWarning(unittest.TestCase):
    """A setting that still says `home: simple` opens the full page, and the check warns once (#503)."""

    def findings(self, settings):
        import check
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "Workspace"
            build_workspace(root)
            if settings is not None:
                write(root / "System" / "garrick-settings.json", json.dumps(settings))
            return [f for f in check.run_checks(root, quick=True) if f.check == "home"]

    def test_a_home_key_is_one_warning_with_the_fix(self):
        (found,) = self.findings({"home": "simple", "ask": True})
        self.assertEqual("warning", found.severity)
        self.assertEqual("System/garrick-settings.json", found.path)
        self.assertIn("delete the line, or run the update", found.message)

    def test_any_value_of_the_key_warns_once_and_no_key_warns_not_at_all(self):
        self.assertEqual(1, len(self.findings({"home": "full"})))
        self.assertEqual([], self.findings({"ask": True}))
        self.assertEqual([], self.findings(None))

    def test_the_check_is_the_last_of_the_list_and_has_its_heading(self):
        import check
        self.assertIs(check.check_home_setting, check.ALL_CHECKS[-1])
        self.assertEqual(("home", "Home setting"), check.CHECKS[-1])
        self.assertIn("home", check.EAR_GROUP)


if __name__ == "__main__":
    unittest.main()
